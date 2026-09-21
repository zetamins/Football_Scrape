package com.football.app.search

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.football.app.components.Logo
import com.football.app.data.model.FetchFailure
import com.football.app.queue.QueueState
import com.football.app.queue.SearchQueueService
import com.football.app.report.ReportViewModel
import com.football.app.report.SearchState
import com.football.app.ui.theme.AppTheme

@Composable
fun SearchScreen(
    viewModel: ReportViewModel,
    onReportReady: () -> Unit,
    onHistoryClick: () -> Unit,
) {
    val state by viewModel.state.collectAsState()
    var teamName by remember { mutableStateOf("") }
    val context = LocalContext.current
    val queueState by SearchQueueService.queueState.collectAsState()

    // Navigates as a side effect of state, not as part of a click handler
    // -- Success can be reached either via loadMostRecentFromHistory()
    // below (a single search completing through the queue) or
    // loadFromHistory() (opening a saved report from History).
    LaunchedEffect(state) {
        if (state is SearchState.Success) onReportReady()
    }

    // Every search -- single or batch -- now runs through
    // SearchQueueService (a "queue of one" for a single team) rather
    // than ReportViewModel talking to ReportRepository directly. Confirmed
    // live this matters, not just architectural tidiness: a single search
    // tied to the Activity's own coroutine had no foreground-service or
    // battery-optimization protection, and stalled once the app lost
    // visibility (switching to a different app -- a real backgrounding,
    // distinct from the lock-screen case setKeepVisibleDuringSearch in
    // FootballNavHost handles). Routing through the same service the
    // batch queue already used gives single search the identical
    // protection, for free, rather than duplicating it.
    //
    // isSingleSearchRun/singleSearchError and the watcher that promotes a
    // finished queue-of-one into a visible report now live on
    // viewModel (see ReportViewModel's own doc comment) rather than as
    // remember{} state here -- confirmed live that this screen-local
    // version silently broke whenever the user navigated away from
    // SearchScreen (e.g. to History) while a search was still Running.
    val isSingleSearchRun by viewModel.isSingleSearchRun.collectAsState()
    val singleSearchError by viewModel.singleSearchError.collectAsState()

    val startQueue = rememberStartQueue(context)
    val isSearchRunning = queueState is QueueState.Running

    Column(
        // Scrollable -- without this, a queue of more than a few teams
        // (Batch search section) pushes the "Run queue" button below
        // the visible screen with no way to reach it. Confirmed live:
        // 5 queued teams left "Run queue" completely inaccessible.
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(48.dp))
        Box(modifier = Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.align(Alignment.Center)) {
                Logo(size = 34.dp)
                Spacer(Modifier.width(10.dp))
                Text(
                    "DeepXI",
                    style =
                        MaterialTheme.typography.headlineMedium.copy(
                            fontSize = 26.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = (-0.01).em,
                        ),
                )
            }
            IconButton(onClick = onHistoryClick, modifier = Modifier.align(Alignment.CenterEnd)) {
                Icon(Icons.Default.History, contentDescription = "History")
            }
        }
        Spacer(Modifier.height(32.dp))

        OutlinedTextField(
            value = teamName,
            onValueChange = { teamName = it },
            label = { Text("Team name") },
            singleLine = true,
            enabled = !isSearchRunning,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = {
                viewModel.markSingleSearchStarted()
                startQueue(listOf(teamName))
            },
            enabled = teamName.isNotBlank() && !isSearchRunning,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Search")
        }

        Spacer(Modifier.height(32.dp))

        if (isSingleSearchRun && queueState is QueueState.Running) {
            SingleSearchProgress(queueState as QueueState.Running)
        }
        singleSearchError?.let {
            Text(it, color = AppTheme.colors.statusCritical, modifier = Modifier.padding(top = 8.dp))
        }

        Spacer(Modifier.height(32.dp))
        BatchQueueSection(
            teamName = teamName,
            onTeamNameConsumed = { teamName = "" },
            startQueue = startQueue,
            showStatusCard = !isSingleSearchRun,
            isSearchRunning = isSearchRunning,
        )
    }
}

/** Shared "ask for battery-optimization exemption, then notification
 * permission, then start the service" flow -- used by both the main
 * Search button (a queue of one) and the batch queue's Run queue button.
 * Proceeds regardless of what the user picks at each step (best-effort,
 * same policy SearchQueueService.notify()'s SecurityException handling
 * already has): a denied permission just means the notification/OEM
 * backgrounding protection is degraded, not that the search can't run. */
@Composable
private fun rememberStartQueue(context: Context): (List<String>) -> Unit {
    var pendingTeams by remember { mutableStateOf<List<String>>(emptyList()) }
    val notificationPermissionLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
            SearchQueueService.start(context, pendingTeams)
        }
    // Confirmed live: a correctly-declared foreground service alone isn't
    // enough to survive backgrounding on many OEM Android skins (Samsung,
    // MIUI, EMUI, ColorOS, vivo/iQOO, etc.) -- SearchQueueService was
    // getting OOM-killed mid-run because the app never asked to be
    // exempted from Doze/App Standby battery restrictions. This is the
    // one system dialog Android lets an app trigger directly for that (no
    // manual Settings navigation needed).
    val batteryOptimizationLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    return { teams ->
        pendingTeams = teams
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!powerManager.isIgnoringBatteryOptimizations(context.packageName)) {
            batteryOptimizationLauncher.launch(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}")),
            )
        } else {
            // Already exempted -- skip straight to the notification-
            // permission step rather than showing a system dialog for
            // something already granted.
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}

/** Determinate-when-possible progress for a single search running through
 * the queue -- same "(step/6)" parsing LoadingChecklist used to do
 * directly off SearchState.Loading, now off QueueState.Running.message
 * instead. Deliberately simpler than the old per-source checklist (no
 * checkmark list): that per-source detail lived in
 * SearchState.Loading.sources, which QueueState.Running doesn't carry --
 * accepted tradeoff for giving single search the queue's foreground-
 * service protection rather than duplicating that protection just to
 * keep the richer view. */
@Composable
internal fun SingleSearchProgress(running: QueueState.Running) {
    Column(modifier = Modifier.fillMaxWidth()) {
        val displayMessage = running.message.ifBlank { "Computing match insights..." }
        StepProgressBar(displayMessage)
        Spacer(Modifier.height(12.dp))
        Text("Searching \"${running.currentTeam}\"...", style = MaterialTheme.typography.bodyMedium)
        Text(displayMessage, style = MaterialTheme.typography.bodySmall)
        FailedLinksList(running.failures)
    }
}

/** Live list of every link/API request that failed so far this search --
 * source + reason on one line, the URL beneath. Shows nothing until the
 * first failure. Height-capped and scrollable so a run where a whole
 * source is down can't push the rest of the screen off-screen. */
@Composable
internal fun FailedLinksList(failures: List<FetchFailure>) {
    if (failures.isEmpty()) return
    Spacer(Modifier.height(16.dp))
    Text(
        "${failures.size} link${if (failures.size == 1) "" else "s"} failed",
        style = MaterialTheme.typography.titleSmall,
        color = AppTheme.colors.statusCritical,
    )
    Column(modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
        failures.forEach { failure ->
            Column(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Text("${failure.source} — ${failure.reason}", style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
                Text(
                    failure.url,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

/** Determinate when `message` carries a "(step/total)" prefix (see
 * parseStepProgress below), indeterminate otherwise -- shared by
 * SingleSearchProgress and QueueStatusCard's own Running state, which
 * previously showed plain text with no progress bar at all despite
 * being driven by the exact same QueueState.Running.message. */
@Composable
internal fun StepProgressBar(message: String) {
    val stepProgress = remember(message) { parseStepProgress(message) }
    if (stepProgress != null) {
        LinearProgressIndicator(progress = { stepProgress }, modifier = Modifier.fillMaxWidth())
    } else {
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
    }
}

/**
 * Add-to-queue + run-queue UI. Deliberately separate from the single
 * "Search" flow above rather than replacing it -- most searches are one
 * team, and the queue (a background service + notification, see
 * SearchQueueService) is specifically for "search several teams, one
 * after another, without babysitting the app." Both now start the exact
 * same service, just with different team-name lists.
 */
@Composable
private fun BatchQueueSection(
    teamName: String,
    onTeamNameConsumed: () -> Unit,
    startQueue: (List<String>) -> Unit,
    showStatusCard: Boolean,
    isSearchRunning: Boolean,
) {
    var queuedTeams by remember { mutableStateOf(listOf<String>()) }
    val queueState by SearchQueueService.queueState.collectAsState()

    Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        Text("Batch search", style = MaterialTheme.typography.titleSmall, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                onClick = {
                    val name = teamName.trim()
                    if (name.isNotEmpty() && name !in queuedTeams) queuedTeams = queuedTeams + name
                    onTeamNameConsumed()
                },
                enabled = teamName.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Default.Add, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text(if (teamName.isNotBlank()) "Add \"$teamName\" to queue" else "Add to queue")
            }
        }

        queuedTeams.forEach { team ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
            ) {
                Text(team, modifier = Modifier.weight(1f))
                IconButton(onClick = { queuedTeams = queuedTeams - team }) {
                    Icon(Icons.Default.Close, contentDescription = "Remove")
                }
            }
        }

        if (queuedTeams.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = {
                    startQueue(queuedTeams)
                    queuedTeams = emptyList()
                },
                enabled = !isSearchRunning,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Run queue (${queuedTeams.size})")
            }
        }

        if (showStatusCard) QueueStatusCard(queueState)
    }
}

@Composable
internal fun QueueStatusCard(queueState: QueueState) {
    when (queueState) {
        is QueueState.Running -> {
            Spacer(Modifier.height(16.dp))
            StepProgressBar(queueState.message)
            Spacer(Modifier.height(8.dp))
            Text(
                "Queue: ${queueState.currentTeam} (${queueState.index + 1}/${queueState.total}) -- ${queueState.message.ifBlank {
                    "working…"
                }}",
                style = MaterialTheme.typography.bodySmall,
            )
            FailedLinksList(queueState.failures)
        }

        is QueueState.Finished -> {
            Spacer(Modifier.height(16.dp))
            Text(
                "Queue finished: ${queueState.succeeded} succeeded, ${queueState.failed} failed",
                style = MaterialTheme.typography.bodySmall,
            )
        }

        QueueState.Idle -> {
            // No queue has run yet this session -- nothing to show.
        }
    }
}

private val STEP_PROGRESS_REGEX = Regex("""^\((\d+)/(\d+)\)""")

/** Parses a leading "(step/total)" prefix (see football/orchestrate.py's
 * _step_message()) into a 0f..1f fraction for a determinate progress
 * bar; null for any message without that prefix (the pre-scrape and
 * per-source messages don't have one, and correctly stay indeterminate). */
internal fun parseStepProgress(message: String): Float? {
    val match = STEP_PROGRESS_REGEX.find(message) ?: return null
    val (stepText, totalText) = match.destructured
    val step = stepText.toIntOrNull() ?: return null
    val total = totalText.toIntOrNull() ?: return null
    if (total <= 0) return null
    return (step.toFloat() / total.toFloat()).coerceIn(0f, 1f)
}
