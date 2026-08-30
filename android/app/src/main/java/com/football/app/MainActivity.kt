package com.football.app

import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.PyException
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Staged proofs-of-concept, run in order:
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
 * Stages 2-4: confirm the WebView-backed browser.py implementation
 * (WebViewRenderer.kt + browser.py's Android branch) works end to end
 * against all 3 real browser-dependent sources, unmodified --
 * worldfootball.py (single page load + one synchronous JS table scrape),
 * sofascore.py (retry-with-backoff-wrapped sequential JSON API calls
 * through the same page), and squawka.py (an async fetch() with a custom
 * header, injected and awaited inside the page's own JS context). Each
 * opens and closes its own WebView/renderer via launch_browser() --
 * deliberately run one after another on the same background thread, not
 * concurrently, given this project's own resource constraints (a full
 * Cloudflare-challenge WebView session per stage).
 *
 * All of stages 2-4 run on a background thread, not directly in
 * onCreate: WebViewRenderer's methods block the calling thread while the
 * actual WebView work happens on the main thread via Handler.post() --
 * calling them FROM the main thread would deadlock (the main thread
 * would be blocked waiting for Python, while Python's WebView calls sit
 * queued waiting for the main thread's Looper to free up).
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

        Thread {
            val bridge = py.getModule("football.android_test")

            runStage(statusView, "Stage 2 (worldfootball.net)") {
                bridge.callAttr("run_worldfootball_referee_stats", "Premier League", "Michael Oliver")
            }
            runStage(statusView, "Stage 3 (sofascore.com)") {
                bridge.callAttr("run_sofascore_matches", "Liverpool")
            }
            runStage(statusView, "Stage 4 (squawka.com)") {
                bridge.callAttr("run_squawka_defensive_stats", "Liverpool", "Premier League")
            }
            // Previously-untested Sofascore call shapes -- Stage 3 only
            // covered get_sofascore_matches (search + fixture list).
            // These hit a different, larger set of same-origin
            // /api/v1/... endpoints through the same WebView bridge.
            runStage(statusView, "Stage 5 (sofascore.com match_details)") {
                bridge.callAttr("run_sofascore_match_details", "Liverpool")
            }
            runStage(statusView, "Stage 6 (sofascore.com team_profile)") {
                bridge.callAttr("run_sofascore_team_profile", "Liverpool")
            }
            // The real end-to-end path: orchestrate.run_search() +
            // report.build_report_json(), the same sequence cli.py's own
            // entry point uses -- exercises all 13 sources (10 plain-HTTP
            // + the 3 WebView ones tested individually above), merge.py,
            // insights.py, elo.py/prediction.py, and JSON serialization
            // together. Every stage above tests one piece in isolation;
            // this is the only one that proves the whole pipeline
            // produces a correct report on Android. Run last -- by far
            // the slowest (touches every source).
            runStage(statusView, "Stage 7 (full report, all 13 sources)") {
                bridge.callAttr("run_full_report", "Liverpool")
            }
        }.start()
    }

    /** Runs one Python call on the calling (background) thread and posts
     * its result/failure to statusView on the main thread. */
    private fun runStage(statusView: TextView, label: String, call: () -> PyObject) {
        runOnUiThread { statusView.append("\n\n$label running...") }
        try {
            val summary = call().toString()
            val message = "$label OK -- $summary"
            Log.i("FootballApp", message)
            runOnUiThread { statusView.append("\n$message") }
        } catch (e: PyException) {
            val message = "$label FAILED: ${e.message}"
            Log.e("FootballApp", message, e)
            runOnUiThread {
                statusView.append("\n$message")
                statusView.setTextColor(Color.RED)
            }
        }
    }
}
