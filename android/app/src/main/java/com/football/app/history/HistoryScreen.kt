package com.football.app.history

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.football.app.components.TeamBadge
import com.football.app.data.history.HistoryEntry
import com.football.app.report.HistoryViewModel
import com.football.app.report.ReportViewModel
import com.football.app.report.SearchState
import com.football.app.ui.theme.AppTheme

/**
 * Lists every completed search (newest first), saved automatically by
 * ReportViewModel.search() on each Success -- see HistoryRepository's
 * own doc comment for the storage shape. Tapping an entry reopens it
 * without a new network/Python call (HistoryViewModel.open ->
 * ReportViewModel.loadFromHistory); the trailing icon deletes it after
 * a confirmation, since delete has no undo.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(
    historyViewModel: HistoryViewModel,
    reportViewModel: ReportViewModel,
    onBack: () -> Unit,
    onReportReady: () -> Unit,
) {
    val entries by historyViewModel.entries.collectAsState()
    val reportState by reportViewModel.state.collectAsState()
    var pendingDeleteId by remember { mutableStateOf<String?>(null) }

    // Unlike SearchScreen (whose only reason to exist is to reach
    // Success), reportViewModel.state can *already* be Success when this
    // screen opens -- the user just came from a live report and tapped
    // the history icon. Reacting to every Success the way SearchScreen
    // does would bounce straight back to Report before the list is even
    // visible. So this only navigates for a Success this screen itself
    // triggered (a tap on a row, via isOpening), not one it merely
    // observes.
    var isOpening by remember { mutableStateOf(false) }

    // historyViewModel is nav-graph-scoped (survives across screens), so
    // its list isn't naturally re-read on every visit -- refresh whenever
    // this screen (re)enters composition to pick up a search saved since
    // the last visit.
    LaunchedEffect(Unit) { historyViewModel.refresh() }

    LaunchedEffect(reportState) {
        if (isOpening && reportState is SearchState.Success) onReportReady()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("History") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        if (entries.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("No searches yet.", style = MaterialTheme.typography.bodyMedium)
            }
            return@Scaffold
        }

        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp, vertical = 8.dp)) {
            items(entries, key = { it.id }) { entry ->
                HistoryRow(
                    entry = entry,
                    onOpen = {
                        isOpening = true
                        historyViewModel.open(entry.id, reportViewModel)
                    },
                    onDeleteRequest = { pendingDeleteId = entry.id },
                )
            }
        }
    }

    val deleteId = pendingDeleteId
    if (deleteId != null) {
        AlertDialog(
            onDismissRequest = { pendingDeleteId = null },
            title = { Text("Delete this search?") },
            text = { Text("This can't be undone.") },
            confirmButton = {
                TextButton(onClick = {
                    historyViewModel.delete(deleteId)
                    pendingDeleteId = null
                }) { Text("Delete") }
            },
            dismissButton = {
                TextButton(onClick = { pendingDeleteId = null }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun HistoryRow(entry: HistoryEntry, onOpen: () -> Unit, onDeleteRequest: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onOpen)
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.weight(1f)) {
                TeamBadge(entry.team, AppTheme.colors.homeSeries, size = 30.dp)
                if (entry.opponent != null) {
                    Spacer(Modifier.width(4.dp))
                    Text("vs", style = MaterialTheme.typography.labelSmall)
                    Spacer(Modifier.width(4.dp))
                    TeamBadge(entry.opponent, AppTheme.colors.awaySeries, size = 30.dp)
                }
                Spacer(Modifier.width(12.dp))
                Column {
                    val title = if (entry.opponent != null) "${entry.team} vs ${entry.opponent}" else entry.team
                    Text(title, style = MaterialTheme.typography.titleMedium)
                    Text("Generated ${entry.generatedAt}", style = MaterialTheme.typography.bodySmall)
                }
            }
            IconButton(onClick = onDeleteRequest) {
                Icon(Icons.Filled.DeleteOutline, contentDescription = "Delete")
            }
        }
    }
}
