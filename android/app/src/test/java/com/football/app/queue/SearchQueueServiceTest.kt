package com.football.app.queue

import android.app.NotificationManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Regression test for the crash fixed this session: NotificationChannel
 * requires API 26, but minSdk is 24, and createNotificationChannel() was
 * called unconditionally from onCreate() -- a real crash on Android
 * 7.0/7.1, caught by Android Lint's NewApi check, not previously guarded.
 *
 * Doesn't exercise onCreate() itself (starts the Chaquopy/Python bridge,
 * unavailable in a plain JVM test) -- isolates just the guarded method,
 * which is what actually needs the regression coverage.
 */
@RunWith(RobolectricTestRunner::class)
class SearchQueueServiceTest {
    private fun newService(): SearchQueueService {
        val service = Robolectric.buildService(SearchQueueService::class.java).get()
        service.notificationManager =
            ApplicationProvider.getApplicationContext<Context>()
                .getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        return service
    }

    @Config(sdk = [24])
    @Test
    fun `createNotificationChannel does not throw on API 24, below NotificationChannel's API 26 requirement`() {
        val service = newService()
        service.createNotificationChannel()
    }

    @Config(sdk = [26])
    @Test
    fun `createNotificationChannel registers a real channel on API 26 and above`() {
        val service = newService()
        service.createNotificationChannel()

        val channel = service.notificationManager.getNotificationChannel(SearchQueueService.CHANNEL_ID)
        assertNotNull(channel)
    }
}
