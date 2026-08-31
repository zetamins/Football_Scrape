package com.football.app

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.football.app.navigation.FootballNavHost
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
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        Python.getInstance().getModule("football.android_bridge")
            .callAttr("set_application_context", applicationContext)

        setContent {
            FootballTheme {
                FootballNavHost()
            }
        }
    }
}
