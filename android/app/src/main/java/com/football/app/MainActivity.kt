package com.football.app

import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.football.app.coverage.ExcludedFromCoverage
import com.football.app.navigation.FootballNavHost
import com.football.app.queue.SearchQueueService
import com.football.app.ui.theme.FootballTheme

/**
 * Real app entry point. Chaquopy's Python.start() + handing the
 * application context to football.android_bridge (needed by browser.py's
 * Android/WebView branch, which WebViewRenderer.kt backs) are the only
 * platform-level init this class does -- everything past that is
 * Compose (FootballNavHost -> Search/Report screens -> the
 * football.android_report.run_report() bridge call, see
 * data/bridge/PythonBridge.kt).
 *
 * Previously this class ran staged diagnostic proofs-of-concept (Chaquopy
 * embedding, then each WebView-backed source in isolation, then the full
 * pipeline) directly in onCreate -- those proved the platform layer works
 * and are superseded now that the real app exists on top of it. The
 * underlying diagnostic entry points (football.android_test) are
 * untouched and still callable directly if that layer ever needs
 * re-verifying in isolation from the UI.
 */
class MainActivity : AppCompatActivity() {
    @ExcludedFromCoverage
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        Python
            .getInstance()
            .getModule("football.android_bridge")
            .callAttr("set_application_context", applicationContext)

        // Clears a "search queue running" notification left behind by a
        // process that was killed before it reached its own cleanup code
        // (see SearchQueueService.clearStaleNotificationIfIdle's doc).
        // Now covers single search too -- it routes through this same
        // service (see SearchScreen.kt), so this is the only search
        // notification path in the app.
        SearchQueueService.clearStaleNotificationIfIdle(this)

        setContent {
            FootballTheme {
                FootballNavHost()
            }
        }
    }

    /** Confirmed live: sofascore's scrape (the one source that needs a
     * real WebView to get past Cloudflare -- see WebViewRenderer.kt/
     * browser.py) freezes completely while the device is locked, even
     * with the screen woken but not unlocked -- 0% CPU, no progress, for
     * as long as it stayed locked -- then resumes instantly the moment
     * the keyguard is dismissed. Root cause: Android/Chromium's WebView
     * throttles JS execution for an app with no visible, resumed window,
     * and a locked keyguard makes every window in the app count as not
     * visible, regardless of process priority (this app's process stayed
     * at top-sleeping/oom=0 the whole time it was frozen -- process
     * priority was never the problem).
     *
     * setShowWhenLocked()/setTurnScreenOn() (the same mechanism alarm/
     * camera/call-screen apps use to stay interactive over the lock
     * screen) keeps this Activity's window counted as visible/resumed
     * even while the keyguard is drawn on top of it, which is what
     * un-freezes WebView -- a secure device still requires the user's
     * PIN/biometric to actually touch the content, but rendering and JS
     * execution aren't gated on that the way they're gated on window
     * visibility. Real, visible side effect users should expect: the
     * screen turns back on and shows this app over the lock screen for
     * as long as a search is active, not just silently continuing
     * unseen. Toggled from SearchScreen for exactly the span a search
     * (single or the batch queue) is actually running, not left on
     * permanently. */
    fun setKeepVisibleDuringSearch(active: Boolean) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(active)
            setTurnScreenOn(active)
        } else {
            @Suppress("DEPRECATION")
            val legacyFlags = WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            if (active) window.addFlags(legacyFlags) else window.clearFlags(legacyFlags)
        }
        if (active) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }
}
