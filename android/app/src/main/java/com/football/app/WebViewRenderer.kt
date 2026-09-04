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
 * Readiness (goto() and evaluate()'s pre-check) is judged by polling
 * document.readyState/title directly via evaluateJavascript, NOT by
 * waiting for onPageFinished. This replaced an earlier onPageFinished-
 * plus-settle-window design after live diagnosis (the
 * onPageStarted/onPageFinished/onReceivedError/onReceivedHttpError
 * logging below, kept permanently, is what did it): worldfootball.net's
 * page loads a long chain of third-party ad/tracking requests (Sparteo,
 * SmileWanted, Missena, LoopMe, SmartAdServer, ...) that frequently
 * 403/429/502 or hang, and onPageFinished's timing tracks THEIR
 * completion, not the real content or even Cloudflare's own challenge
 * (which resolves in a fairly consistent ~2-4s once triggered) -- a page
 * could sit at "still loading" by WebView's own accounting for 90+
 * seconds while the actual content had been sitting in the DOM the
 * whole time. document.readyState reaching "interactive" means the DOM
 * is parsed and synchronous scripts have run -- true regardless of
 * whether async ad/tracker resources are still pending. The
 * document.title check on top of that specifically guards against
 * declaring victory on Cloudflare's OWN challenge page, which is itself
 * a fully-loaded, readyState-"complete" document titled "Just a
 * moment..." -- the title changes the instant Cloudflare's automatic
 * redirect delivers the real page, independent of that page's own
 * background ad requests.
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
 */
class WebViewRenderer(
    private val context: Context,
) {
    // internal, not private -- WebViewRendererTest reaches the real
    // WebView instance via Robolectric's ShadowWebView to answer
    // evaluateJavascript() calls directly (getLastEvaluatedJavascriptCallback()),
    // simulating a real page's JS execution without needing Robolectric's
    // shadow to actually run one.
    internal var webView: WebView? = null
        private set
    private val mainHandler = Handler(Looper.getMainLooper())
    private val resultCounter = AtomicLong(0)

    // Set false right before each loadUrl(), true by onPageStarted for
    // that navigation -- see goto()'s comment for why this matters.
    @Volatile private var navigationStarted = false

    companion object {
        private const val READY_POLL_INTERVAL_MS = 200L
        private const val RESULT_POLL_INTERVAL_MS = 250L
        private const val NAV_START_POLL_INTERVAL_MS = 50L
        private const val NAV_START_MAX_WAIT_MS = 10000L
        private const val CHALLENGE_TITLE = "\"Just a moment...\""

        // Gated behind BuildConfig.DEBUG rather than always logging: this
        // is per-navigation, per-resource diagnostic detail (URLs being
        // scraped, error bodies) that's genuinely useful during
        // development -- it's what diagnosed both real bugs this class's
        // docstring describes -- but has no place running unconditionally
        // in a release build, for both noise and information-exposure
        // reasons. message is a lambda, not a plain String, so building
        // the log text is skipped entirely in release rather than just
        // its output being discarded.
        private fun logd(
            tag: String,
            message: () -> String,
        ) {
            if (BuildConfig.DEBUG) {
                android.util.Log.d(tag, message())
            }
        }
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
            wv.webViewClient =
                object : WebViewClient() {
                    override fun onPageStarted(
                        view: WebView?,
                        url: String?,
                        favicon: Bitmap?,
                    ) {
                        navigationStarted = true
                        logd("WebViewRenderer") { "onPageStarted: $url" }
                    }

                    override fun onPageFinished(
                        view: WebView?,
                        finishedUrl: String?,
                    ) {
                        logd("WebViewRenderer") { "onPageFinished: $finishedUrl" }
                    }

                    override fun onReceivedError(
                        view: WebView?,
                        request: android.webkit.WebResourceRequest?,
                        error: android.webkit.WebResourceError?,
                    ) {
                        logd("WebViewRenderer") {
                            "onReceivedError: url=${request?.url} isForMainFrame=${request?.isForMainFrame} code=${error?.errorCode} desc=${error?.description}"
                        }
                    }

                    override fun onReceivedHttpError(
                        view: WebView?,
                        request: android.webkit.WebResourceRequest?,
                        errorResponse: android.webkit.WebResourceResponse?,
                    ) {
                        logd("WebViewRenderer") {
                            "onReceivedHttpError: url=${request?.url} isForMainFrame=${request?.isForMainFrame} status=${errorResponse?.statusCode}"
                        }
                    }
                }
            webView = wv
            latch.countDown()
        }
        val completed = latch.await(10, TimeUnit.SECONDS)
        if (!completed) logd("WebViewRenderer") { "open() timed out waiting for the WebView to be created on the main thread" }
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
        // A timeout here just leaves result[0] null, which isContentReady()
        // already treats as "not ready yet, try again" (see its own
        // doc comment) -- logged for diagnostics, not acted on further.
        val completed = latch.await(5, TimeUnit.SECONDS)
        if (!completed) logd("WebViewRenderer") { "evalOnMainThread() timed out waiting for evaluateJavascript's callback" }
        return result[0]
    }

    /** True once the DOM is past parsing (readyState interactive/complete)
     * AND we're not still looking at Cloudflare's own challenge page --
     * see class docstring for why both checks are needed. A momentary
     * evaluateJavascript failure (null back, e.g. mid-navigation) reads
     * as "not ready yet" rather than an error -- the caller's poll loop
     * just tries again. */
    private fun isContentReady(): Boolean {
        val state = evalOnMainThread("document.readyState")
        val title = evalOnMainThread("document.title")
        val domReady = state == "\"interactive\"" || state == "\"complete\""
        val pastChallenge = title != CHALLENGE_TITLE
        return domReady && pastChallenge
    }

    /** Blocks the CALLING thread (not the main thread) until
     * isContentReady() or deadlineMs passes. */
    private fun waitUntilReady(deadlineMs: Long): Boolean {
        while (System.currentTimeMillis() < deadlineMs) {
            if (isContentReady()) {
                return true
            }
            Thread.sleep(READY_POLL_INTERVAL_MS)
        }
        return false
    }

    /** Mirrors Playwright's page.goto(url, wait_until=..., timeout=ms).
     * wait_until itself isn't distinguished -- waitUntilReady's
     * content-based approach stands in for all of Playwright's
     * finer-grained load-state options here.
     *
     * Waits for onPageStarted to confirm the new navigation has actually
     * begun before polling content readiness. Confirmed live this
     * matters: mainHandler.post{}'s loadUrl() call and the first
     * isContentReady() check can race, with the poll sometimes winning --
     * document.readyState/title from the PREVIOUS page (already
     * "complete") gets read as if it belonged to the new one, declaring
     * victory on stale content. Produced a fast-but-wrong "0 rows
     * scraped" result once, and a Sofascore fetch returning an old
     * cached response once -- both against a page that hadn't actually
     * started loading yet when checked. Bounded to
     * NAV_START_MAX_WAIT_MS so a genuinely missing onPageStarted (an
     * edge case, not expected for a fresh loadUrl to a different URL)
     * can't hang the whole call. */
    fun goto(
        url: String,
        timeoutMs: Long,
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        navigationStarted = false
        mainHandler.post { webView?.loadUrl(url) }

        val startDeadline = minOf(deadline, System.currentTimeMillis() + NAV_START_MAX_WAIT_MS)
        while (!navigationStarted && System.currentTimeMillis() < startDeadline) {
            Thread.sleep(NAV_START_POLL_INTERVAL_MS)
        }

        return waitUntilReady(deadline)
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
    fun evaluate(
        functionScript: String,
        argJson: String?,
        timeoutMs: Long,
    ): String {
        val deadline = System.currentTimeMillis() + timeoutMs
        // Re-check readiness right before injecting -- closes the
        // (unlikely but possible) race where a fresh navigation starts
        // between goto() returning and evaluate() being called. Uses the
        // same content-based check goto() does, not the old
        // onPageFinished-tracking one -- that would reintroduce the exact
        // slow-ad-tracker dependency this whole design change removed.
        if (!waitUntilReady(deadline)) {
            return """{"ok":false,"error":"page not ready after ${timeoutMs}ms, gave up before evaluate"}"""
        }

        val propName = "__androidResult" + resultCounter.incrementAndGet()
        val callExpr = if (argJson != null) "($functionScript)($argJson)" else "($functionScript)()"
        // Always awaits the call, even when it's not a Promise -- await on
        // a plain value just resolves immediately, so this one wrapper
        // form covers both sync (worldfootball's table scrape, sofascore's
        // innerText read) and async (Squawka's fetch()) scripts without
        // needing to tell them apart.
        val injectScript =
            """
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
        val completed = latch.await(5, TimeUnit.SECONDS)
        if (!completed) logd("WebViewRenderer") { "close() timed out waiting for the WebView to be destroyed on the main thread" }
    }
}
