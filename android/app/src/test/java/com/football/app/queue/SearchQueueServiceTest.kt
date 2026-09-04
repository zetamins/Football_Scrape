package com.football.app.queue

import android.app.Notification
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
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

    @Test
    fun `buildNotification marks an ongoing notification as ongoing and not auto-cancel`() {
        val notification = newService().buildNotification("Arsenal", "Working...", ongoing = true)
        assertTrue(notification.flags and Notification.FLAG_ONGOING_EVENT != 0)
        assertTrue(notification.flags and Notification.FLAG_AUTO_CANCEL == 0)
    }

    @Test
    fun `buildNotification marks a finished notification as auto-cancel and not ongoing`() {
        val notification = newService().buildNotification("Queue complete", "1 succeeded, 0 failed", ongoing = false)
        assertTrue(notification.flags and Notification.FLAG_AUTO_CANCEL != 0)
        assertTrue(notification.flags and Notification.FLAG_ONGOING_EVENT == 0)
    }

    @Test
    fun `notify posts the notification under the given id`() {
        val service = newService()
        val notification = service.buildNotification("Arsenal", "Working...", ongoing = true)
        service.notify(notification, id = 42)
        // Robolectric's shadow NotificationManager tracks posted
        // notifications for inspection -- confirms notify() actually
        // reaches the real NotificationManager, not just that it doesn't
        // throw.
        val shadow = org.robolectric.Shadows.shadowOf(service.notificationManager)
        assertNotNull(shadow.getNotification(42))
    }

    @Test
    fun `onBind returns null -- this service offers no binding interface`() {
        assertNull(newService().onBind(Intent()))
    }

    @Test
    fun `onDestroy does not throw when no job was ever started`() {
        // runJob is null until onStartCommand actually launches one --
        // confirms the null-safe runJob?.cancel() call handles that.
        newService().onDestroy()
    }

    @Test
    fun `onStartCommand with no team names does nothing and returns START_NOT_STICKY`() {
        // Deliberately an empty-extras Intent, not a real team-name list
        // -- a non-empty list would launch runQueue(), which needs
        // `repository` (only set in onCreate(), which starts Chaquopy's
        // Python runtime and can't run in a plain JVM test -- same
        // accepted-gap class as PythonBridge.kt/the rest of this
        // service's Python-calling code).
        val result = newService().onStartCommand(Intent(), 0, 1)
        assertEquals(Service.START_NOT_STICKY, result)
    }

    @Test
    fun `onStartCommand with a null intent does nothing and returns START_NOT_STICKY`() {
        val result = newService().onStartCommand(null, 0, 1)
        assertEquals(Service.START_NOT_STICKY, result)
    }

    @Test
    fun `clearStaleNotificationIfIdle cancels the notification while the queue is idle`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(SearchQueueService.NOTIFICATION_ID, newService().buildNotification("Arsenal", "Working...", ongoing = true))
        assertNotNull(org.robolectric.Shadows.shadowOf(notificationManager).getNotification(SearchQueueService.NOTIFICATION_ID))

        // queueState defaults to (and, since nothing in this test suite
        // ever starts a real queue run, stays) Idle -- confirmed via the
        // public queueState StateFlow rather than assumed.
        assertEquals(QueueState.Idle, SearchQueueService.queueState.value)
        SearchQueueService.clearStaleNotificationIfIdle(context)

        assertNull(org.robolectric.Shadows.shadowOf(notificationManager).getNotification(SearchQueueService.NOTIFICATION_ID))
    }
}
