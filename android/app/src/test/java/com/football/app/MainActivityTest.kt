package com.football.app

import android.view.WindowManager
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Only exercises setKeepVisibleDuringSearch, a self-contained method
 * touching only Build.VERSION.SDK_INT/window flags -- never calls
 * .create() (MainActivity.onCreate() starts Chaquopy's Python runtime
 * and calls setContent{}, neither available/meaningful in a plain JVM
 * test), same pattern SearchQueueServiceTest already uses to isolate
 * createNotificationChannel() from that service's own onCreate().
 * Robolectric.buildActivity(...).get() constructs and attaches the
 * Activity (a real Window exists) without invoking the app's onCreate()
 * override.
 */
@Suppress("DEPRECATION") // testing the legacy (pre-API-27) fallback necessarily references these
@RunWith(RobolectricTestRunner::class)
class MainActivityTest {
    private fun newActivity(): MainActivity = Robolectric.buildActivity(MainActivity::class.java).get()

    @Config(sdk = [28])
    @Test
    fun `activating on API 28+ sets showWhenLocked, turnScreenOn, and keep-screen-on`() {
        val activity = newActivity()
        activity.setKeepVisibleDuringSearch(true)
        assertEquals(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
        )
    }

    @Config(sdk = [28])
    @Test
    fun `deactivating on API 28+ clears keep-screen-on`() {
        val activity = newActivity()
        activity.setKeepVisibleDuringSearch(true)
        activity.setKeepVisibleDuringSearch(false)
        assertEquals(0, activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    @Config(sdk = [24])
    @Test
    fun `activating below API 27 (O_MR1) falls back to the legacy window flags`() {
        val activity = newActivity()
        activity.setKeepVisibleDuringSearch(true)
        val flags = activity.window.attributes.flags
        assertEquals(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED, flags and WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED)
        assertEquals(WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON, flags and WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        assertEquals(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON, flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    @Config(sdk = [24])
    @Test
    fun `deactivating below API 27 clears the legacy window flags`() {
        val activity = newActivity()
        activity.setKeepVisibleDuringSearch(true)
        activity.setKeepVisibleDuringSearch(false)
        val flags = activity.window.attributes.flags
        assertEquals(0, flags and WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED)
        assertEquals(0, flags and WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        assertEquals(0, flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
}
