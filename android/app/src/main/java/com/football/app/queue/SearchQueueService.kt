package com.football.app.queue

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.football.app.MainActivity
import com.football.app.R
import com.football.app.coverage.ExcludedFromCoverage
import com.football.app.data.ReportRepository
import com.football.app.data.history.HistoryRepository
import com.football.app.report.SearchState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File

/**
 * Runs a queue of team-name searches sequentially -- one at a time, same
 * as run_search() already scrapes its own 5 sources sequentially rather
 * than in parallel (Sofascore is rate-sensitive/Cloudflare-protected;
 * running multiple teams' searches concurrently would compound exactly
 * the risk that per-search sequencing already exists to avoid). A
 * foreground service (not a background one) because Android kills plain
 * background services once the app leaves the foreground -- this is
 * explicitly meant to keep running with the app backgrounded, signaled
 * to the user via the required ongoing notification.
 *
 * Each completed team is saved to HistoryRepository exactly like a
 * single interactive search already is (ReportViewModel.search) --
 * there's no separate "queue results" UI; finished searches just show
 * up in History.
 */
class SearchQueueService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var runJob: Job? = null
    // internal, not private -- same reason as notificationManager below:
    // SearchQueueServiceTest injects a fake ReportRepository (ReportRepository's
    // own injectable `runReport` seam, already used by ReportRepositoryTest)
    // to exercise runQueue()/runOne()/onStartCommand() for real without
    // Chaquopy, bypassing onCreate() entirely.
    internal lateinit var repository: ReportRepository
    internal lateinit var historyRepository: HistoryRepository
    // internal, not private -- SearchQueueServiceTest constructs the
    // service without going through onCreate() (which starts the
    // Chaquopy/Python bridge, unavailable in a plain JVM test) and needs
    // to inject this directly to exercise createNotificationChannel() in
    // isolation.
    internal lateinit var notificationManager: NotificationManager

    @ExcludedFromCoverage
    override fun onCreate() {
        super.onCreate()
        // Guards against a cold-process restart of just this service
        // (e.g. after the whole app process was killed while the
        // notification was still showing) where MainActivity's own
        // Python.start() never ran in THIS process instance -- mirrors
        // MainActivity.onCreate()'s identical guard exactly.
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        Python.getInstance().getModule("football.android_bridge").callAttr("set_application_context", applicationContext)

        repository = ReportRepository()
        historyRepository = HistoryRepository(File(filesDir, "history"))
        notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        createNotificationChannel()
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int,
    ): Int {
        val teamNames = intent?.getStringArrayListExtra(EXTRA_TEAM_NAMES)
        if (!teamNames.isNullOrEmpty() && runJob?.isActive != true) {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                buildNotification("Search queue", "Starting …", ongoing = true),
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
            runJob = serviceScope.launch { runQueue(teamNames) }
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        runJob?.cancel()
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun runQueue(teamNames: List<String>) {
        var succeeded = 0
        var failed = 0
        var lastError: String? = null
        for ((index, teamName) in teamNames.withIndex()) {
            when (val result = runOne(teamName, index, teamNames.size)) {
                is SearchState.Success -> {
                    succeeded++
                    historyRepository.save(result.report, result.rawJson)
                    notify(buildNotification(teamName, "Done ✓", ongoing = true))
                }

                is SearchState.Error -> {
                    failed++
                    lastError = result.message
                    notify(buildNotification(teamName, "Failed: ${result.message}", ongoing = true))
                }

                else -> {
                    // Loading/Idle: only Success/Error end a single team's
                    // search (runOne() only ever returns one of those two),
                    // so this branch is unreachable but required for
                    // exhaustiveness over the sealed SearchState.
                }
            }
        }
        _queueState.value = QueueState.Finished(succeeded, failed, lastError)
        // Explicitly detach + remove the ongoing foreground notification
        // rather than relying on stopSelf() to implicitly clear it --
        // that implicit cleanup isn't reliable across OEM skins (the same
        // class of issue as the battery-optimization kill above), and
        // posting the completion message under a SEPARATE id avoids any
        // ambiguity about whether it's still "the" foreground
        // notification. Confirmed live: the old code left the last
        // ongoing "team (i/total)" notification visibly stuck in the
        // shade after the queue finished.
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        notify(
            buildNotification("Queue complete", "$succeeded succeeded, $failed failed", ongoing = false),
            id = COMPLETE_NOTIFICATION_ID,
        )
        stopSelf()
    }

    /** Blocking, same contract as ReportRepository.search() itself (see
     * PythonBridge's docstring) -- runs on this service's own
     * Dispatchers.IO coroutine, so blocking here is the correct/expected
     * pattern, not a bug. */
    private fun runOne(
        teamName: String,
        index: Int,
        total: Int,
    ): SearchState {
        var finalState: SearchState = SearchState.Error("No result")
        repository.search(teamName) { state ->
            when (state) {
                is SearchState.Loading -> {
                    _queueState.value = QueueState.Running(teamName, index, total, state.message, state.failures)
                    notify(buildNotification("$teamName (${index + 1}/$total)", state.message.ifBlank { "Working …" }, ongoing = true))
                }

                is SearchState.Success, is SearchState.Error -> {
                    finalState = state
                }

                SearchState.Idle -> {
                    // ReportRepository.search() never actually calls back
                    // with Idle (it fires Loading immediately) -- kept only
                    // for exhaustiveness over the sealed SearchState.
                }
            }
        }
        return finalState
    }

    // internal, not private -- same reason as notificationManager/
    // createNotificationChannel above: SearchQueueServiceTest builds and
    // inspects notifications directly without going through onCreate().
    internal fun buildNotification(
        title: String,
        text: String,
        ongoing: Boolean,
    ): android.app.Notification {
        val openAppIntent =
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE,
            )
        return NotificationCompat
            .Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setOngoing(ongoing)
            .setOnlyAlertOnce(true)
            .setAutoCancel(!ongoing)
            .setContentIntent(openAppIntent)
            .build()
    }

    /** Posting can throw SecurityException if the user denied
     * POST_NOTIFICATIONS (API 33+) -- the queue still runs and still
     * saves to History either way, so a missing notification is a
     * degraded-but-safe outcome, not a crash. */
    // internal, not private -- same reason as buildNotification above.
    internal fun notify(
        notification: android.app.Notification,
        id: Int = NOTIFICATION_ID,
    ) {
        try {
            notificationManager.notify(id, notification)
        } catch (_: SecurityException) {
            // Permission denied -- queue keeps running silently.
        }
    }

    // internal, not private -- see notificationManager's comment above;
    // SearchQueueServiceTest calls this directly to regression-test the
    // API-26 guard below without going through onCreate().
    internal fun createNotificationChannel() {
        // NotificationChannel doesn't exist below API 26 -- minSdk here is
        // 24, so this was an unconditional crash on Android 7.0/7.1 (caught
        // by Android Lint's NewApi check, not previously guarded).
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(CHANNEL_ID, "Search queue", NotificationManager.IMPORTANCE_LOW)
        channel.description = "Progress for team searches running in the background"
        notificationManager.createNotificationChannel(channel)
    }

    companion object {
        const val EXTRA_TEAM_NAMES = "team_names"
        internal const val CHANNEL_ID = "search_queue"
        // internal, not private -- SearchQueueServiceTest asserts against
        // the real id rather than duplicating the literal.
        internal const val NOTIFICATION_ID = 1001
        private const val COMPLETE_NOTIFICATION_ID = 1002

        private val _queueState = MutableStateFlow<QueueState>(QueueState.Idle)
        val queueState = _queueState.asStateFlow()

        // Test-only: queueState is companion-scoped (one process-wide
        // value, by design -- see clearStaleNotificationIfIdle's own
        // comment), which means a test that actually runs a queue to
        // completion permanently leaves it Finished for every later test
        // in the same JVM, including ones (like
        // clearStaleNotificationIfIdle's own) that need a genuinely Idle
        // starting state regardless of test execution order.
        internal fun resetQueueStateForTest() {
            _queueState.value = QueueState.Idle
        }

        // Test-only: lets a test simulate a queue run completing (e.g.
        // SearchScreenTest driving its own isSingleSearchRun-gated
        // LaunchedEffect) without needing the real, Chaquopy-bound
        // runQueue() to actually execute.
        internal fun setQueueStateForTest(state: QueueState) {
            _queueState.value = state
        }

        fun start(
            context: Context,
            teamNames: List<String>,
        ) {
            val intent =
                Intent(context, SearchQueueService::class.java)
                    .putStringArrayListExtra(EXTRA_TEAM_NAMES, ArrayList(teamNames))
            ContextCompat.startForegroundService(context, intent)
        }

        /** Cancels a leftover "queue running" notification from a process
         * that died (OOM-killed, force-stopped) before it reached its own
         * completion/cleanup code -- that class of kill was already known
         * to happen on some OEM skins even with the battery-optimization
         * exemption in place. `queueState` is a companion (process-wide)
         * field reset to Idle on every fresh process, so Idle here
         * reliably means no queue is actually running in this process --
         * any notification still posted under NOTIFICATION_ID must be
         * orphaned from a previous one. Call from MainActivity.onCreate()
         * so it's checked every time the app is (re)opened. */
        fun clearStaleNotificationIfIdle(context: Context) {
            if (_queueState.value == QueueState.Idle) {
                (context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                    .cancel(NOTIFICATION_ID)
            }
        }
    }
}
