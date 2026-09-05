package com.football.app

import android.os.Looper
import android.webkit.WebView
import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors

/**
 * WebViewRenderer's own methods block the CALLING thread waiting for
 * work posted to the main Looper (see its own class doc comment) --
 * previously assumed entirely untestable in a plain JVM test for that
 * reason, alongside PythonBridge/Chaquopy-bound code. Two separate
 * findings this session corrected that, in stages:
 *
 * 1. open()/close() don't need real WebView JavaScript at all --
 *    running the blocking call on a background thread while this test
 *    thread drains the (Robolectric-paused) main Looper via
 *    shadowOf(Looper.getMainLooper()).idle() lets the posted work
 *    actually execute, same pattern as SearchQueueServiceTest's own
 *    async-Dispatchers.IO polling.
 * 2. goto()/evaluate()/isContentReady()/evalOnMainThread() -- initially
 *    assumed stuck forever, since evaluateJavascript()'s callback never
 *    fires on its own under Robolectric's WebView shadow. It turns out
 *    Robolectric's ShadowWebView still RECORDS every evaluateJavascript()
 *    call (getLastEvaluatedJavascript()/getLastEvaluatedJavascriptCallback()),
 *    even though nothing runs it -- so a test can intercept each call as
 *    it happens and answer it directly, simulating exactly what a real
 *    page's JS engine would eventually have returned. The same technique
 *    answers onPageStarted() (WebViewRenderer's own navigation-start
 *    gate) by calling `webView.webViewClient.onPageStarted(...)` directly.
 *
 * driveAndAnswer() below is the shared harness for #2: it runs [block]
 * on a background thread, and on each drained Looper iteration checks
 * for a new (not-yet-answered) evaluateJavascript() call, resolving it
 * via [answer]. [firePageStartedAfterIterations], when set, calls the
 * real WebViewClient's onPageStarted() once that many iterations have
 * passed -- NOT immediately (confirmed live this races goto()'s own
 * `navigationStarted = false` init and gets silently clobbered if fired
 * too early; a few drained iterations reliably lets goto() run that
 * line first).
 */
@RunWith(RobolectricTestRunner::class)
class WebViewRendererTest {
    private fun <T> runOnBackgroundAndDrain(
        timeoutMs: Long = 5_000,
        block: () -> T,
    ): T = driveAndAnswer(timeoutMs = timeoutMs, answer = { "null" }, block = block)

    private fun <T> driveAndAnswer(
        timeoutMs: Long = 5_000,
        firePageStartedAfterIterations: Int? = null,
        answer: (script: String) -> String,
        block: () -> T,
    ): T {
        val executor = Executors.newSingleThreadExecutor()
        val latch = CountDownLatch(1)
        var result: T? = null
        var error: Throwable? = null
        executor.execute {
            try {
                result = block()
            } catch (t: Throwable) {
                error = t
            } finally {
                latch.countDown()
            }
        }
        val deadline = System.currentTimeMillis() + timeoutMs
        var lastAnsweredScript: String? = null
        var pageStartedFired = false
        var iterations = 0
        while (latch.count > 0 && System.currentTimeMillis() < deadline) {
            shadowOf(Looper.getMainLooper()).idle()
            iterations++
            val wv: WebView? = currentRenderer?.webView
            if (wv != null) {
                if (firePageStartedAfterIterations != null && !pageStartedFired && iterations > firePageStartedAfterIterations) {
                    pageStartedFired = true
                    wv.webViewClient?.onPageStarted(wv, "https://example.com", null)
                }
                val shadowWv = shadowOf(wv)
                val script = shadowWv.lastEvaluatedJavascript
                val callback = shadowWv.lastEvaluatedJavascriptCallback
                if (script != null && callback != null && script != lastAnsweredScript) {
                    lastAnsweredScript = script
                    callback.onReceiveValue(answer(script))
                }
            }
            Thread.sleep(10)
        }
        executor.shutdown()
        check(latch.count == 0L) { "block() did not complete within ${timeoutMs}ms" }
        error?.let { throw it }
        @Suppress("UNCHECKED_CAST")
        return result as T
    }

    // driveAndAnswer() needs the renderer's own WebView instance to
    // inspect/answer -- set as a side effect of newRenderer() so every
    // test can share one driving implementation regardless of which
    // renderer instance it's currently driving.
    private var currentRenderer: WebViewRenderer? = null

    private fun newRenderer(): WebViewRenderer {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        return WebViewRenderer(context).also { currentRenderer = it }
    }

    @Test
    fun `open creates a WebView on the main thread without throwing`() {
        runOnBackgroundAndDrain { newRenderer().open("") }
    }

    @Test
    fun `open with a real user agent string sets it without throwing`() {
        val renderer = newRenderer()
        runOnBackgroundAndDrain {
            renderer.open("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        }
    }

    @Test
    fun `close after open destroys the WebView without throwing`() {
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }
        runOnBackgroundAndDrain { renderer.close() }
    }

    @Test
    fun `close before open does not throw -- webView is null`() {
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.close() }
    }

    @Test
    fun `evalOnMainThread returns null immediately when webView is null`() {
        // No open() call -- webView is null the whole time. Reached via
        // evaluate(), the only public method that calls it before a page
        // is loaded (goto() would too, but only after its own
        // navigationStarted gate, which this doesn't need to exercise).
        val renderer = newRenderer()
        val result = runOnBackgroundAndDrain(timeoutMs = 2_000) { renderer.evaluate("() => 1", null, 500) }
        val parsed = JSONObject(result)
        assertFalse(parsed.getBoolean("ok"))
    }

    @Test
    fun `the WebViewClient's other diagnostic callbacks run without throwing`() {
        // onPageStarted is exercised via the goto()/challenge tests above
        // (it's WebViewRenderer's own navigation-start signal); the other
        // 3 are purely diagnostic logging with no effect on control flow,
        // so calling them directly is enough to exercise their bodies.
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }
        val wv = checkNotNull(renderer.webView)
        val client = checkNotNull(wv.webViewClient)
        client.onPageFinished(wv, "https://example.com")
        client.onReceivedError(wv, null, null)
        client.onReceivedHttpError(wv, null, null)
    }

    /** The standard "page is ready" answer for isContentReady()'s two
     * probes -- readyState complete, a real (non-challenge) title. */
    private fun readyAnswer(script: String): String =
        when (script) {
            "document.readyState" -> "\"complete\""
            "document.title" -> "\"Real Page\""
            else -> "null"
        }

    @Test
    fun `goto returns true once the simulated page reports ready`() {
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }

        val result =
            driveAndAnswer(timeoutMs = 5_000, firePageStartedAfterIterations = 3, answer = ::readyAnswer) {
                renderer.goto("https://example.com", 3_000)
            }
        assertTrue(result)
    }

    @Test
    fun `goto stays false while the page is stuck on Cloudflare's challenge title`() {
        // isContentReady()'s own pastChallenge check -- domReady is true
        // (readyState complete) but the title never changes, unlike the
        // "ready" case above.
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }

        val result =
            driveAndAnswer(
                timeoutMs = 3_000,
                firePageStartedAfterIterations = 3,
                answer = { script ->
                    when (script) {
                        "document.readyState" -> "\"complete\""
                        "document.title" -> "\"Just a moment...\""
                        else -> "null"
                    }
                },
            ) { renderer.goto("https://example.com", 500) }
        assertFalse(result)
    }

    @Test
    fun `goto gives up and returns false once its own short deadline passes with no onPageStarted at all`() {
        // No firePageStartedAfterIterations -- reproduces the original
        // finding this test class started from: without a simulated
        // navigation start, goto() can't get past its own
        // navigationStarted gate.
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }
        val result = runOnBackgroundAndDrain(timeoutMs = 3_000) { renderer.goto("https://example.com", timeoutMs = 300) }
        assertFalse(result)
    }

    @Test
    fun `evaluate returns a synchronous script's value once the page is ready`() {
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }

        val result =
            driveAndAnswer(
                timeoutMs = 5_000,
                answer = { script ->
                    when {
                        script == "document.readyState" -> "\"complete\""
                        script == "document.title" -> "\"Real Page\""
                        script.contains("window['") -> """{"ok":true,"value":4}"""
                        else -> "null"
                    }
                },
            ) { renderer.evaluate("() => 2 + 2", null, 3_000) }

        val parsed = JSONObject(result)
        assertTrue(parsed.getBoolean("ok"))
        assertEquals(4, parsed.getInt("value"))
    }

    @Test
    fun `evaluate reports a thrown script error instead of hanging or crashing`() {
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }

        val result =
            driveAndAnswer(
                timeoutMs = 5_000,
                answer = { script ->
                    when {
                        script == "document.readyState" -> "\"complete\""
                        script == "document.title" -> "\"Real Page\""
                        script.contains("window['") -> """{"ok":false,"error":"boom"}"""
                        else -> "null"
                    }
                },
            ) { renderer.evaluate("() => { throw new Error('boom'); }", null, 3_000) }

        val parsed = JSONObject(result)
        assertFalse(parsed.getBoolean("ok"))
        assertEquals("boom", parsed.getString("error"))
    }

    @Test
    fun `evaluate succeeds when passed a non-null argJson`() {
        // Every other evaluate() test above passes argJson = null --
        // the `if (argJson != null) "($functionScript)($argJson)" else
        // "($functionScript)()"` branch that actually appends the arg
        // was never taken. (The inject call itself uses a null callback,
        // so its exact text isn't observable through driveAndAnswer's
        // poll-answering mechanism -- this only proves the non-null
        // branch runs the pipeline through to a correct result.)
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }

        val result =
            driveAndAnswer(
                timeoutMs = 5_000,
                answer = { script ->
                    when {
                        script == "document.readyState" -> "\"complete\""
                        script == "document.title" -> "\"Real Page\""
                        script.contains("window['") -> """{"ok":true,"value":42}"""
                        else -> "null"
                    }
                },
            ) { renderer.evaluate("(x) => x + 1", """{"x":41}""", 3_000) }

        val parsed = JSONObject(result)
        assertTrue(parsed.getBoolean("ok"))
        assertEquals(42, parsed.getInt("value"))
    }

    @Test
    fun `evaluate retries and eventually times out when the result never appears`() {
        // Distinct from the "page never becomes ready" case below --
        // here isContentReady() succeeds immediately, but the injected
        // script's result (the window[...] poll) never resolves,
        // exercising evaluate()'s own result-polling retry loop and its
        // separate timeout message. Each poll only gets answered once
        // (driveAndAnswer never re-answers identical script text), so
        // the underlying evalOnMainThread() genuinely blocks out its own
        // real 5s internal timeout on the second+ poll attempt -- this
        // test takes several real seconds to run, unlike the others.
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }

        val result =
            driveAndAnswer(
                timeoutMs = 15_000,
                answer = { script ->
                    when {
                        script == "document.readyState" -> "\"complete\""
                        script == "document.title" -> "\"Real Page\""
                        else -> "null"
                    }
                },
            ) { renderer.evaluate("() => 1", null, 6_000) }

        val parsed = JSONObject(result)
        assertFalse(parsed.getBoolean("ok"))
        assertTrue(parsed.getString("error").contains("timed out"))
    }

    @Test
    fun `evaluate times out with an explanatory message when the page never becomes ready`() {
        val renderer = newRenderer()
        runOnBackgroundAndDrain { renderer.open("") }

        // Never answers "ready" -- readyState/title stay unanswered
        // (default "null"), so waitUntilReady() exhausts its own
        // deadline before evaluate() ever injects its real script.
        val result = driveAndAnswer(timeoutMs = 3_000, answer = { "null" }) { renderer.evaluate("() => 1", null, 500) }

        val parsed = JSONObject(result)
        assertFalse(parsed.getBoolean("ok"))
        assertTrue(parsed.getString("error").contains("not ready"))
    }
}
