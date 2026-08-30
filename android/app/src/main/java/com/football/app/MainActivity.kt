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
 * Stage 1 proof-of-concept: confirms Chaquopy can actually embed and run
 * this project's real football/ package (via the app/src/main/python/
 * football symlink to ../../../football, one source of truth -- not a
 * copy) on a real device/emulator, before any WebView-bridge work is
 * built on top. Calls one pure, network-free function (geo.py's
 * country_distance_km, already unit-tested on the desktop side in
 * tests/test_geo.py) so this checks the embedding itself, not network
 * access or the browser-dependent sources.
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

        try {
            val geo = Python.getInstance().getModule("football.geo")
            val km = geo.callAttr("country_distance_km", "England", "France").toDouble()
            val message = "Chaquopy OK -- football.geo.country_distance_km(England, France) = %.1f km".format(km)
            Log.i("FootballApp", message)
            statusView.text = message
        } catch (e: PyException) {
            val message = "Python call failed: ${e.message}"
            Log.e("FootballApp", message, e)
            statusView.text = message
            statusView.setTextColor(Color.RED)
        }
    }
}
