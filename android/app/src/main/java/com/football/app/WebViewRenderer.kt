package com.football.app

import android.content.Context
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import android.webkit.WebViewClient
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * The Android-side implementation football/browser.py's WebView backend
 * calls into (via Chaquopy's `java` module) in place of Playwright, which
 * can't run inside an Android app sandbox at all -- see browser.py's
 * module docstring.
 *
 * WebView must be created and driven on the main UI thread; every public
 * method here is called from a Python coroutine running on a background
 * thread (via asyncio.to_thread on the Python side, so the event loop
 * itself isn't blocked). Mutating the WebView itself always happens via
 * mainHandler.post{}; the CALLING thread (not the main thread) does the
 * actual waiting -- via CountDownLatch/poll loops -- since that thread
 * isn't the one driving the Looper and blocking it briefly is exactly
 * the point.
 *
 * evaluate() polls a `window` property rather than using
 * addJavascriptInterface + a Java callback object, despite that being the
 * more commonly-documented pattern. Confirmed live and directly, against
 * a real site (worldfootball.net), that addJavascriptInterface's binding
 * was never actually reachable from injected JS here -- a direct
 * `typeof window['name']` probe immediately after a successful
 * addJavascriptInterface() call returned "undefined", with no navigation
 * in between and the class already made public (the most common cause).
 * Root cause not fully pinned down (a plausible explanation is Chromium
 * WebView's multi-process renderer model not always sharing the binding
 * the way single-process addJavascriptInterface examples assume), but
 * evaluateJavascript's own native callback -- not a Java reflection
 * bridge at all -- doesn't have this failure mode, so it replaces
 * addJavascriptInterface entirely rather than trying to fix the binding
 * timing further.
 *
 * The onPageStarted/onPageFinished/onReceivedError/onReceivedHttpError
 * logging below is kept permanently, not left over from debugging: it's
 * what actually diagnosed why worldfootball.net's navigation time varies
 * so widely (14s in some runs, still not settled at 90s in others) --
 * the page carries a long chain of third-party ad/tracking requests
 * (Sparteo, SmileWanted, Missena, LoopMe, SmartAdServer, ...) that
 * frequently 403/429/502 or hang, and onPageFinished's timing tracks
 * THEIR completion, not Cloudflare's own challenge (which resolves in a
 * fairly consistent ~2-4s once triggered) or anything about the real
 * content (the referee table) being ready. Not something this bridge
 * can fix from here -- browser.py's Android goto()-timeout floor exists
 * because of exactly this, and this logging is what a future fix (e.g.
 * polling for the real content directly instead of trusting
 * onPageFinished) would need to build on.
 */
class WebViewRenderer(private val context: Context) {
    private var webView: WebView? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private val resultCounter = AtomicLong(0)

    @Volatile private var isNavigating = false
    @Volatile private var lastPageFinishedAt = 0L

    companion object {
        // How long the page must go quiet (no onPageStarted) before it's
        // considered settled. Short is fine here precisely because it's
        // re-armed by every navigation, however many hops a Cloudflare-
        // style challenge chain takes -- unlike a single fixed
        // post-onPageFinished delay, this doesn't have to guess the
        // challenge's total duration.
        private const val SETTLE_WINDOW_MS = 800L
        private const val NAV_POLL_INTERVAL_MS = 100L
        private const val RESULT_POLL_INTERVAL_MS = 250L
    }

    fun open(userAgent: String) {
        val latch = CountDownLatch(1)
        mainHandler.post {
            val wv = WebView(context)
            wv.settings.javaScriptEnabled = true
            wv.settings.domStorageEnabled = true
            // A blank userAgent (the Python side now always sends "" --
            // see _WebViewBrowser.new_context()'s comment) leaves
            // WebView's own default UA in place, rather than overriding
            // it with a string built for real desktop Chrome under
            // Playwright.
            if (userAgent.isNotBlank()) {
                wv.settings.userAgentString = userAgent
            }
            wv.webViewClient = object : WebViewClient() {
                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    isNavigating = true
                    android.util.Log.d("WebViewRenderer", "onPageStarted: $url")
                }

                override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                    isNavigating = false
                    lastPageFinishedAt = System.currentTimeMillis()
                    android.util.Log.d("WebViewRenderer", "onPageFinished: $finishedUrl")
                }

                override fun onReceivedError(view: WebView?, request: android.webkit.WebResourceRequest?, error: android.webkit.WebResourceError?) {
                    android.util.Log.d("WebViewRenderer", "onReceivedError: url=${request?.url} isForMainFrame=${request?.isForMainFrame} code=${error?.errorCode} desc=${error?.description}")
                }

                override fun onReceivedHttpError(view: WebView?, request: android.webkit.WebResourceRequest?, errorResponse: android.webkit.WebResourceResponse?) {
                    android.util.Log.d("WebViewRenderer", "onReceivedHttpError: url=${request?.url} isForMainFrame=${request?.isForMainFrame} status=${errorResponse?.statusCode}")
                }
            }
            webView = wv
            latch.countDown()
        }
        latch.await(10, TimeUnit.SECONDS)
    }

    /** Blocks the CALLING thread (not the main thread) until no
     * navigation has been in flight for SETTLE_WINDOW_MS, or deadlineMs
     * passes. Safe to call from a background thread since it only reads
     * @Volatile fields the main thread writes -- no WebView API touched
     * here. */
    private fun waitForSettledPage(deadlineMs: Long): Boolean {
        while (System.currentTimeMillis() < deadlineMs) {
            if (!isNavigating && System.currentTimeMillis() - lastPageFinishedAt >= SETTLE_WINDOW_MS) {
                return true
            }
            Thread.sleep(NAV_POLL_INTERVAL_MS)
        }
        return !isNavigating
    }

    /** Mirrors Playwright's page.goto(url, wait_until=..., timeout=ms).
     * wait_until itself isn't distinguished -- waitForSettledPage's
     * settle-based approach stands in for all of Playwright's
     * finer-grained load-state options here. */
    fun goto(url: String, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        isNavigating = true
        lastPageFinishedAt = 0L
        mainHandler.post { webView?.loadUrl(url) }
        return waitForSettledPage(deadline)
    }

    /** Runs one evaluateJavascript call on the main thread and blocks the
     * calling thread for its (synchronous, native) callback result --
     * this part of evaluateJavascript's contract is reliable; it's only
     * addJavascriptInterface that wasn't (see class docstring). */
    private fun evalOnMainThread(script: String): String? {
        val latch = CountDownLatch(1)
        val result = arrayOfNulls<String>(1)
        mainHandler.post {
            val wv = webView
            if (wv == null) {
                latch.countDown()
                return@post
            }
            wv.evaluateJavascript(script) { value ->
                result[0] = value
                latch.countDown()
            }
        }
        latch.await(5, TimeUnit.SECONDS)
        return result[0]
    }

    /** Mirrors Playwright's page.evaluate(page_function, arg). functionScript
     * is always a JS function string (arrow or regular) -- matches how
     * every call site in sofascore.py/squawka.py/worldfootball.py already
     * uses it. argJson is the JSON-encoded arg, or null for a no-arg call.
     * Returns a JSON string: {"ok":true,"value":...} or
     * {"ok":false,"error":"..."} -- never throws itself, so the Python
     * side gets a clean result either way instead of a bridge-level
     * exception.
     *
     * Implementation: inject a script that stores its outcome as a real
     * JS object (not a JSON string) on a uniquely-named `window`
     * property, fire it and forget, then poll that property via
     * evaluateJavascript until it's set or timeoutMs passes. Storing an
     * object rather than calling JSON.stringify() inside the injected
     * script matters: evaluateJavascript's callback already returns the
     * JSON form of whatever the polled expression evaluates to, so
     * polling a plain object yields exactly {"ok":...,"value":...}
     * directly -- polling a JSON-string value would double-encode it
     * (JSON of a string wraps it in an extra pair of quotes). */
    fun evaluate(functionScript: String, argJson: String?, timeoutMs: Long): String {
        val deadline = System.currentTimeMillis() + timeoutMs
        if (!waitForSettledPage(deadline)) {
            return """{"ok":false,"error":"page still navigating after ${timeoutMs}ms, gave up before evaluate"}"""
        }

        val propName = "__androidResult" + resultCounter.incrementAndGet()
        val callExpr = if (argJson != null) "($functionScript)($argJson)" else "($functionScript)()"
        // Always awaits the call, even when it's not a Promise -- await on
        // a plain value just resolves immediately, so this one wrapper
        // form covers both sync (worldfootball's table scrape, sofascore's
        // innerText read) and async (Squawka's fetch()) scripts without
        // needing to tell them apart.
        val injectScript = """
            (function() {
              window['$propName'] = undefined;
              (async () => {
                try {
                  const __r = await ($callExpr);
                  window['$propName'] = {ok: true, value: (__r === undefined ? null : __r)};
                } catch (e) {
                  window['$propName'] = {ok: false, error: String((e && e.message) || e)};
                }
              })();
            })();
        """.trimIndent()

        mainHandler.post { webView?.evaluateJavascript(injectScript, null) }

        val pollExpr = "window['$propName'] || null"
        while (System.currentTimeMillis() < deadline) {
            val raw = evalOnMainThread(pollExpr)
            if (raw != null && raw != "null") {
                return raw
            }
            Thread.sleep(RESULT_POLL_INTERVAL_MS)
        }
        return """{"ok":false,"error":"evaluate() timed out after ${timeoutMs}ms"}"""
    }

    fun close() {
        val latch = CountDownLatch(1)
        mainHandler.post {
            webView?.destroy()
            webView = null
            latch.countDown()
        }
        latch.await(5, TimeUnit.SECONDS)
    }
}
