package com.football.app

import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.PyException
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Two staged proofs-of-concept, run in order:
 *
 * Stage 1: confirms Chaquopy can actually embed and run this project's
 * real football/ package (via the app/src/main/python/football symlink
 * to ../../../football, one source of truth -- not a copy) on a real
 * device/emulator. Calls one pure, network-free function (geo.py's
 * country_distance_km, already unit-tested on the desktop side in
 * tests/test_geo.py) so this checks the embedding itself, not network
 * access or the browser-dependent sources. Verified live on-device
 * already (see the commit that added this file).
 *
 * Stage 2: confirms the WebView-backed browser.py implementation
 * (WebViewRenderer.kt + browser.py's Android branch) works end to end
 * against a REAL site -- worldfootball.py's referee-stats scraper, the
 * simplest of the 3 browser-dependent sources (single page load + one
 * synchronous JS table scrape, no nonce dance, no async fetch()).
 * Deliberately run on a background thread, not directly in onCreate:
 * WebViewRenderer's methods block the calling thread while the actual
 * WebView work happens on the main thread via Handler.post() -- calling
 * them FROM the main thread would deadlock (the main thread would be
 * blocked waiting for Python, while Python's WebView calls sit queued
 * waiting for the main thread's Looper to free up).
 */
class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val statusView = TextView(this).apply {
            textSize = 16f
            setPadding(48, 96, 48, 48)
        }
        setContentView(statusView)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        val py = Python.getInstance()
        py.getModule("football.android_bridge").callAttr("set_application_context", applicationContext)

        try {
            val geo = py.getModule("football.geo")
            val km = geo.callAttr("country_distance_km", "England", "France").toDouble()
            val message = "Stage 1 OK -- football.geo.country_distance_km(England, France) = %.1f km".format(km)
            Log.i("FootballApp", message)
            statusView.text = message
        } catch (e: PyException) {
            val message = "Stage 1 FAILED: ${e.message}"
            Log.e("FootballApp", message, e)
            statusView.text = message
            statusView.setTextColor(Color.RED)
            return
        }

        statusView.append("\n\nStage 2 (WebView -> worldfootball.net) running...")

        Thread {
            try {
                val bridge = py.getModule("football.android_test")
                val summary = bridge.callAttr(
                    "run_worldfootball_referee_stats",
                    "Premier League",
                    "Michael Oliver"
                ).toString()
                val message = "Stage 2 OK -- $summary"
                Log.i("FootballApp", message)
                runOnUiThread {
                    statusView.append("\n$message")
                }
            } catch (e: PyException) {
                val message = "Stage 2 FAILED: ${e.message}"
                Log.e("FootballApp", message, e)
                runOnUiThread {
                    statusView.append("\n$message")
                    statusView.setTextColor(Color.RED)
                }
            }
        }.start()
    }
}
