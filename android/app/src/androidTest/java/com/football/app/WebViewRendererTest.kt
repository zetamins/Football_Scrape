package com.football.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Instrumented tests for WebViewRenderer.kt -- a real WebView can't run in
 * a plain JVM unit test, so these run on-device (or on the emulator) via
 * `./gradlew connectedAndroidTest`.
 *
 * Deliberately uses a local MockWebServer, not live external sites: the
 * manual runs driven by football/android_test.py (Sofascore/Squawka/
 * worldfootball) are still the only check against the real sites'
 * behavior, but they're slow, network-dependent, and non-deterministic --
 * exactly wrong for regression-testing WebViewRenderer's own logic
 * (readiness detection, the async-eval poll, error propagation). These
 * tests instead serve small, controlled HTML from localhost, so they're
 * fast and repeatable, and specifically exercise the two real bugs this
 * bridge already had fixed live against worldfootball.net: the
 * onPageFinished-tracks-slow-subresources problem (challenge-title
 * detection) and the stale-previous-page race (fresh navigation actually
 * replacing the DOM before content is read).
 */
private const val DOCUMENT_TITLE_SCRIPT = "() => document.title"

@RunWith(AndroidJUnit4::class)
class WebViewRendererTest {
    private lateinit var server: MockWebServer
    private lateinit var renderer: WebViewRenderer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        renderer = WebViewRenderer(context)
        renderer.open("")
    }

    @After
    fun tearDown() {
        renderer.close()
        server.shutdown()
    }

    private fun url(path: String) = server.url(path).toString()

    private fun evaluateOk(script: String, argJson: String? = null): Any {
        val parsed = JSONObject(renderer.evaluate(script, argJson, 5000))
        assertTrue("expected ok:true, got $parsed", parsed.getBoolean("ok"))
        return parsed.get("value")
    }

    @Test
    fun gotoReturnsTrueForANormalPage() {
        server.enqueue(MockResponse().setBody("<html><head><title>Normal Page</title></head><body>hi</body></html>"))
        assertTrue(renderer.goto(url("/normal"), 10000))
    }

    @Test
    fun gotoReturnsFalseRatherThanHangingWhenAChallengePageNeverResolves() {
        server.enqueue(MockResponse().setBody("<html><head><title>Just a moment...</title></head><body>checking</body></html>"))
        val start = System.currentTimeMillis()
        val ok = renderer.goto(url("/stuck"), 2000)
        val elapsed = System.currentTimeMillis() - start
        assertFalse(ok)
        assertTrue("goto() took ${elapsed}ms, well past its 2000ms timeout", elapsed < 5000)
    }

    @Test
    fun gotoWaitsPastACloudflareStyleChallengeTitleUntilTheRealPageLoads() {
        // Reproduces the exact shape that broke the old onPageFinished-
        // based design: a challenge page (readyState "complete" almost
        // immediately, but titled "Just a moment...") that redirects to
        // the real content after a delay via its own JS, not a server
        // response the WebViewClient callbacks would necessarily see as
        // a clean single navigation.
        server.enqueue(
            MockResponse().setBody(
                """<html><head><title>Just a moment...</title></head>
                   <body><script>setTimeout(function(){ window.location.href = "/real-content"; }, 700);</script></body></html>"""
            )
        )
        server.enqueue(MockResponse().setBody("<html><head><title>Real Content</title></head><body>data here</body></html>"))

        assertTrue(renderer.goto(url("/challenge"), 10000))
        assertEquals("Real Content", evaluateOk(DOCUMENT_TITLE_SCRIPT))
    }

    @Test
    fun gotoNavigatingToASecondPageDoesNotReadTheFirstPagesStaleContent() {
        // Regression coverage for the race found live: mainHandler.post{}'s
        // loadUrl() and the first readiness poll could interleave such
        // that document.readyState/title from the PREVIOUS page were read
        // as if they belonged to the new navigation.
        server.enqueue(MockResponse().setBody("<html><head><title>First Page</title></head><body></body></html>"))
        server.enqueue(MockResponse().setBody("<html><head><title>Second Page</title></head><body></body></html>"))

        assertTrue(renderer.goto(url("/first"), 10000))
        assertEquals("First Page", evaluateOk(DOCUMENT_TITLE_SCRIPT))

        assertTrue(renderer.goto(url("/second"), 10000))
        assertEquals("Second Page", evaluateOk(DOCUMENT_TITLE_SCRIPT))
    }

    @Test
    fun evaluateReturnsASynchronousScriptsValue() {
        server.enqueue(MockResponse().setBody("<html><head><title>Sync Test</title></head><body></body></html>"))
        renderer.goto(url("/sync"), 10000)
        assertEquals(4, evaluateOk("() => 2 + 2"))
    }

    @Test
    fun evaluateAwaitsAnAsyncFunctionsResolvedValue() {
        // Mirrors squawka.py's _FETCH_STAT_JS shape: an async arrow
        // function whose eventual result, not its immediate Promise, is
        // what the caller needs.
        server.enqueue(MockResponse().setBody("<html><head><title>Async Test</title></head><body></body></html>"))
        renderer.goto(url("/async"), 10000)
        val script = "async () => { await new Promise(r => setTimeout(r, 300)); return 'done'; }"
        assertEquals("done", evaluateOk(script))
    }

    @Test
    fun evaluatePassesTheJsonEncodedArgThroughToTheScript() {
        // Mirrors squawka.py's page.evaluate(script, {nonce, ...}) call
        // shape.
        server.enqueue(MockResponse().setBody("<html><head><title>Arg Test</title></head><body></body></html>"))
        renderer.goto(url("/arg"), 10000)
        assertEquals(7, evaluateOk("(x) => x.a + x.b", """{"a": 3, "b": 4}"""))
    }

    @Test
    fun evaluateReturnsAnObjectResultDirectlyNotDoubleEncoded() {
        // Mirrors worldfootball.py's _TABLE_JS returning an array of
        // objects, and squawka's parsed fetch() response.
        server.enqueue(MockResponse().setBody("<html><head><title>Object Test</title></head><body></body></html>"))
        renderer.goto(url("/obj"), 10000)
        val value = evaluateOk("() => ({name: 'Test', items: [1,2,3]})") as JSONObject
        assertEquals("Test", value.getString("name"))
        assertEquals(3, value.getJSONArray("items").length())
    }

    @Test
    fun evaluateReportsAThrownErrorInsteadOfHangingOrCrashing() {
        server.enqueue(MockResponse().setBody("<html><head><title>Error Test</title></head><body></body></html>"))
        renderer.goto(url("/err"), 10000)
        val parsed = JSONObject(renderer.evaluate("() => { throw new Error('boom'); }", null, 5000))
        assertFalse(parsed.getBoolean("ok"))
        assertTrue(parsed.getString("error").contains("boom"))
    }
}
