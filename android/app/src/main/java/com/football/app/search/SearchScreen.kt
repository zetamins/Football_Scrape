package com.football.app.search

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.unit.dp
import com.football.app.report.ReportViewModel
import com.football.app.report.SearchState
import com.football.app.ui.theme.AppTheme

@Composable
fun SearchScreen(viewModel: ReportViewModel, onReportReady: () -> Unit, onHistoryClick: () -> Unit) {
    val state by viewModel.state.collectAsState()
    var teamName by remember { mutableStateOf("") }

    // Navigates as a side effect of state, not as part of the click
    // handler above -- Success can also be reached by re-observing
    // already-in-flight state (e.g. process restore), not only a fresh
    // search.
    LaunchedEffect(state) {
        if (state is SearchState.Success) onReportReady()
    }

    val isLoading = state is SearchState.Loading

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(48.dp))
        Box(modifier = Modifier.fillMaxWidth()) {
            Text(
                "Football",
                style = MaterialTheme.typography.headlineMedium,
                modifier = Modifier.align(Alignment.Center),
            )
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
            enabled = !isLoading,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = { viewModel.search(teamName) },
            enabled = teamName.isNotBlank() && !isLoading,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Search")
        }

        Spacer(Modifier.height(32.dp))

        when (val s = state) {
            is SearchState.Loading -> LoadingChecklist(s)
            is SearchState.Error -> Text(
                s.message,
                color = AppTheme.colors.statusCritical,
                modifier = Modifier.padding(top = 8.dp),
            )
            else -> {}
        }
    }
}

/**
 * Real per-source progress, not a blank spinner -- backs
 * frontend/DESIGN.md's Premium direction requirement, fed directly by
 * SearchState.Loading.sources (one entry per on_source_progress
 * callback the bridge has actually fired so far).
 */
@Composable
private fun LoadingChecklist(loading: SearchState.Loading) {
    Column(modifier = Modifier.fillMaxWidth()) {
        if (loading.message.isNotBlank()) {
            Text(loading.message, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(12.dp))
        }
        loading.sources.forEach { status ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
            ) {
                if (status.succeeded) {
                    Icon(Icons.Default.Check, contentDescription = null, tint = AppTheme.colors.statusGood)
                    Spacer(Modifier.width(8.dp))
                    Text("${status.source}: ${status.fixturesScraped} fixtures")
                } else {
                    Icon(Icons.Default.Close, contentDescription = null, tint = AppTheme.colors.statusCritical)
                    Spacer(Modifier.width(8.dp))
                    Text("${status.source}: ${status.matchesError ?: status.profileError ?: "failed"}")
                }
            }
        }
        if (loading.sources.isEmpty()) {
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}
