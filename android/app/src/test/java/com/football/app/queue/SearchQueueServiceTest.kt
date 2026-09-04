package com.football.app.queue

import android.app.Notification
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import com.chaquo.python.PyException
import com.football.app.data.ReportRepository
import com.football.app.data.history.HistoryRepository
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

/**
 * Regression test for the crash fixed this session: NotificationChannel
 * requires API 26, but minSdk is 24, and createNotificationChannel() was
 * called unconditionally from onCreate() -- a real crash on Android
 * 7.0/7.1, caught by Android Lint's NewApi check, not previously guarded.
 *
 * Doesn't exercise onCreate() itself (starts the Chaquopy/Python bridge,
 * unavailable in a plain JVM test) -- isolates just the guarded method,
 * which is what actually needs the regression coverage. runQueue()/
 * runOne(), reached via onStartCommand() below, don't share that
 * limitation once `repository` is injected directly (bypassing
 * onCreate()) with a fake using ReportRepository's own `runReport` seam
 * (see ReportRepositoryTest.kt) -- confirmed live this was previously
 * over-cautious: a real, non-empty team-name Intent doesn't crash even
 * with `repository` left uninitialized (the coroutine just fails async
 * on Dispatchers.IO, invisible to the test thread), and injecting a
 * fake `repository` lets the entire queue-run path execute for real.
 */
@RunWith(RobolectricTestRunner::class)
class SearchQueueServiceTest {
    // Every test starts from a known Idle queueState regardless of what
    // ran before it in the same JVM -- see resetQueueStateForTest()'s
    // own doc comment.
    @Before
    fun resetQueueState() {
        SearchQueueService.resetQueueStateForTest()
    }

    private fun newService(repository: ReportRepository? = null): SearchQueueService {
        val service = Robolectric.buildService(SearchQueueService::class.java).get()
        service.notificationManager =
            ApplicationProvider.getApplicationContext<Context>()
                .getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        service.historyRepository =
            HistoryRepository(File(ApplicationProvider.getApplicationContext<Context>().filesDir, "history-${System.nanoTime()}"))
        if (repository != null) service.repository = repository
        return service
    }

    /**
     * runQueue()/runOne() run on the service's own real Dispatchers.IO
     * scope (not a test dispatcher -- SearchQueueService has no seam for
     * one, unlike HistoryViewModel's ioDispatcher), so a bounded poll is
     * needed rather than a virtual-time advance.
     *
     * queueState is a companion (process-wide) StateFlow shared across
     * every test in this class, so a Finished value already sitting
     * there from an earlier test would make a naive "poll until
     * Finished" immediately (and wrongly) return stale state. [before]
     * must be a snapshot taken right before triggering the run being
     * awaited -- this only returns once the value has both changed AND
     * become Finished, guaranteeing it reflects a transition this call
     * actually caused.
     */
    private fun awaitFinished(
        before: QueueState,
        timeoutMs: Long = 5_000,
    ): QueueState.Finished {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val state = SearchQueueService.queueState.value
            if (state is QueueState.Finished && state != before) return state
            Thread.sleep(20)
        }
        throw AssertionError("queueState never reached a new Finished value within ${timeoutMs}ms (was ${SearchQueueService.queueState.value})")
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

    private fun loadSampleReportJson(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    @Test
    fun `onStartCommand runs a single-team queue to completion, saving history and posting notifications`() {
        val sample = loadSampleReportJson()
        val service = newService(repository = ReportRepository(runReport = { _, _, _ -> sample }))
        val before = SearchQueueService.queueState.value

        val intent = Intent().putStringArrayListExtra(SearchQueueService.EXTRA_TEAM_NAMES, arrayListOf("Brentford"))
        val result = service.onStartCommand(intent, 0, 1)
        assertEquals(Service.START_NOT_STICKY, result)

        val finished = awaitFinished(before)
        assertEquals(1, finished.succeeded)
        assertEquals(0, finished.failed)
        assertNull(finished.lastError)

        // historyRepository.save() actually ran -- confirms runOne()'s
        // Success branch reached it, not just that queueState updated.
        assertEquals(1, service.historyRepository.list().size)
        assertEquals("Brentford", service.historyRepository.list().first().team)

        // "Queue complete" notification posted under COMPLETE_NOTIFICATION_ID
        // (1002) -- the exact id is private, so this checks by content
        // instead, matching how buildNotification's own tests inspect flags.
        val shadow = org.robolectric.Shadows.shadowOf(service.notificationManager)
        assertNotNull(shadow.getNotification(1002))
    }

    @Test
    fun `onStartCommand runs a failing search to completion, recording the error`() {
        val service =
            newService(repository = ReportRepository(runReport = { _, _, _ -> throw PyException("Could not find a team matching \"Xyz\"") }))
        val before = SearchQueueService.queueState.value

        val intent = Intent().putStringArrayListExtra(SearchQueueService.EXTRA_TEAM_NAMES, arrayListOf("Xyz"))
        service.onStartCommand(intent, 0, 1)

        val finished = awaitFinished(before)
        assertEquals(0, finished.succeeded)
        assertEquals(1, finished.failed)
        assertEquals("Could not find a team matching \"Xyz\"", finished.lastError)
        assertEquals(0, service.historyRepository.list().size)
    }

    @Test
    fun `onStartCommand runs a multi-team queue with mixed results sequentially`() {
        var calls = 0
        val sample = loadSampleReportJson()
        val service =
            newService(
                repository =
                    ReportRepository(runReport = { teamName, _, _ ->
                        calls++
                        if (teamName == "Bad") throw PyException("not found") else sample
                    }),
            )
        val before = SearchQueueService.queueState.value

        val intent = Intent().putStringArrayListExtra(SearchQueueService.EXTRA_TEAM_NAMES, arrayListOf("Good1", "Bad", "Good2"))
        service.onStartCommand(intent, 0, 1)

        val finished = awaitFinished(before)
        assertEquals(2, finished.succeeded)
        assertEquals(1, finished.failed)
        assertEquals("not found", finished.lastError)
        assertEquals(3, calls)
        assertEquals(2, service.historyRepository.list().size)
    }

    @Test
    fun `start builds a foreground-service intent carrying the team names`() {
        // Doesn't actually run the service (Robolectric records the
        // startForegroundService() call rather than invoking onCreate()/
        // onStartCommand() for it) -- this is start()'s own body only.
        val context = ApplicationProvider.getApplicationContext<Context>()
        SearchQueueService.start(context, listOf("Arsenal", "Chelsea"))

        val nextIntent = org.robolectric.Shadows.shadowOf(context as android.app.Application).nextStartedService
        assertNotNull(nextIntent)
        assertEquals(listOf("Arsenal", "Chelsea"), nextIntent.getStringArrayListExtra(SearchQueueService.EXTRA_TEAM_NAMES))
    }
}
