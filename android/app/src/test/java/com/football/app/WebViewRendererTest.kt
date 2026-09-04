package com.football.app

import android.os.Looper
import androidx.test.core.app.ApplicationProvider
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
 * reason, alongside PythonBridge/Chaquopy-bound code. Verified directly
 * that assumption was too broad for open()/close() specifically: neither
 * needs real WebView JavaScript execution (unlike goto()/evaluate(),
 * which poll evaluateJavascript() -- Robolectric's WebView shadow
 * doesn't run a real JS engine, confirmed separately, so those stay an
 * accepted gap). Running the call on a background thread while this
 * test thread drains the (Robolectric-paused) main Looper via
 * shadowOf(Looper.getMainLooper()).idle() lets the posted work actually
 * execute and the CountDownLatch resolve, same pattern as
 * SearchQueueServiceTest's own async-Dispatchers.IO polling.
 */
@RunWith(RobolectricTestRunner::class)
class WebViewRendererTest {
    private fun <T> runOnBackgroundAndDrain(
        timeoutMs: Long = 5_000,
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
        while (latch.count > 0 && System.currentTimeMillis() < deadline) {
            shadowOf(Looper.getMainLooper()).idle()
            Thread.sleep(10)
        }
        executor.shutdown()
        check(latch.count == 0L) { "block() did not complete within ${timeoutMs}ms" }
        error?.let { throw it }
        @Suppress("UNCHECKED_CAST")
        return result as T
    }

    @Test
    fun `open creates a WebView on the main thread without throwing`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val renderer = WebViewRenderer(context)
        runOnBackgroundAndDrain { renderer.open("") }
    }

    @Test
    fun `open with a real user agent string sets it without throwing`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val renderer = WebViewRenderer(context)
        runOnBackgroundAndDrain {
            renderer.open("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        }
    }

    @Test
    fun `close after open destroys the WebView without throwing`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val renderer = WebViewRenderer(context)
        runOnBackgroundAndDrain { renderer.open("") }
        runOnBackgroundAndDrain { renderer.close() }
    }

    @Test
    fun `close before open does not throw -- webView is null`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val renderer = WebViewRenderer(context)
        runOnBackgroundAndDrain { renderer.close() }
    }

    /**
     * goto()'s own control flow (polling for onPageStarted, then bailing
     * via waitUntilReady's deadline) is real, testable code -- but only
     * with a SHORT timeoutMs. Verified directly (throwaway probe, not
     * kept) that onPageStarted's callback doesn't fire under Robolectric
     * for a URL that was never actually loaded over the network, so a
     * long timeoutMs here would burn real wall-clock time waiting for a
     * callback that never comes (confirmed a 15s timeoutMs still hadn't
     * returned after 20 real seconds) -- isContentReady()/
     * evalOnMainThread()'s own success path needs evaluateJavascript()'s
     * callback to fire, which never happens either, so those (and
     * evaluate(), which depends on the same callback) stay an accepted
     * gap, same reason as the rest of this class's JS-execution-bound
     * methods.
     */
    @Test
    fun `goto gives up and returns false once its own short deadline passes`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val renderer = WebViewRenderer(context)
        runOnBackgroundAndDrain { renderer.open("") }
        val result = runOnBackgroundAndDrain(timeoutMs = 3_000) { renderer.goto("https://example.com", timeoutMs = 300) }
        assert(!result)
    }
}
