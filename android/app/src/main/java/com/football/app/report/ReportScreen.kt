package com.football.app.report

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.football.app.data.AppJson
import com.football.app.data.model.InsightsDiscipline
import com.football.app.data.model.InsightsPerformance
import com.football.app.data.model.FormSummary
import com.football.app.data.model.InsightsContext
import com.football.app.data.model.InsightsProfile
import com.football.app.data.model.InsightsSquadStrength
import com.football.app.data.model.InsightsStandings
import com.football.app.data.model.MatchLineups
import com.football.app.data.model.MatchOverview
import com.football.app.data.model.MatchStandingsTable
import com.football.app.data.model.MatchSummary
import com.football.app.data.model.TeamProfileData
import com.football.app.data.model.VenueDetails
import com.football.app.report.tabs.ContextTab
import com.football.app.report.tabs.DisciplineTab
import com.football.app.report.tabs.FormTab
import com.football.app.report.tabs.LineupsTab
import com.football.app.report.tabs.OverviewTab
import com.football.app.report.tabs.PerformanceTab
import com.football.app.report.tabs.ProfileTab
import com.football.app.report.tabs.SquadTab
import com.football.app.report.tabs.StandingsTab
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonElement

/**
 * Prediction hero + the 9-tab body (frontend/DESIGN.md) -- all 9 tabs
 * have real content. Each tab still falls back to PlaceholderTab if its
 * own decode comes back null (a genuinely absent section for this
 * match, not a bug), which is why every branch below is an if/else, not
 * a bare call. By the time this screen is reached, viewModel.state is
 * guaranteed to be Success (SearchScreen only navigates here on that
 * transition).
 */
@Composable
fun ReportScreen(viewModel: ReportViewModel, onHistoryClick: () -> Unit) {
    val state by viewModel.state.collectAsState()
    val success = state as? SearchState.Success
    val report = success?.report

    val context = LocalContext.current
    val saveJsonLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        val rawJson = success?.rawJson
        if (uri != null && rawJson != null) {
            context.contentResolver.openOutputStream(uri)?.use { it.write(rawJson.toByteArray()) }
            Toast.makeText(context, "Saved.", Toast.LENGTH_SHORT).show()
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        if (report == null) {
            Text("No report loaded.", modifier = Modifier.padding(24.dp))
            return@Column
        }

        val match = remember(report.match) { decodeMatchSummary(report.match) }
        val overview = remember(report.match) { decodeMatchOverview(report.match) }
        val venueDetails = remember(report.venueDetails) { decodeVenueDetails(report.venueDetails) }
        val lineups = remember(report.match) { decodeMatchLineups(report.match) }
        val performance = remember(report.insights) { decodeInsightsPerformance(report.insights) }
        val discipline = remember(report.insights) { decodeInsightsDiscipline(report.insights) }
        val profile = remember(report.insights) { decodeInsightsProfile(report.insights) }
        val standings = remember(report.insights) { decodeInsightsStandings(report.insights) }
        val standingsTable = remember(report.match) { decodeMatchStandingsTable(report.match)?.standingsTable }
        val context = remember(report.insights) { decodeInsightsContext(report.insights) }
        val teamForm = remember(report.form) { decodeFormSummary(report.form) }
        val opponentForm = remember(report.opponentForm) { decodeFormSummary(report.opponentForm) }
        val teamProfile = remember(report.teamProfile) { decodeTeamProfile(report.teamProfile) }
        val opponentProfile = remember(report.opponentProfile) { decodeTeamProfile(report.opponentProfile) }
        val squadStrength = remember(report.insights) { decodeInsightsSquadStrength(report.insights) }

        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(report.team, style = MaterialTheme.typography.headlineMedium)
                Text("Generated ${report.generatedAt}", style = MaterialTheme.typography.bodySmall)
            }
            Row {
                IconButton(onClick = onHistoryClick) {
                    Icon(Icons.Default.History, contentDescription = "History")
                }
                IconButton(onClick = {
                    val safeTeam = report.team.replace(Regex("[^A-Za-z0-9]+"), "_")
                    saveJsonLauncher.launch("${safeTeam}_report.json")
                }) {
                    Icon(Icons.Default.Download, contentDescription = "Download JSON")
                }
            }
        }

        if (match != null) {
            PredictionHero(insightsJson = report.insights, homeTeam = match.homeTeam, awayTeam = match.awayTeam)
        }

        var selectedTab by remember { mutableStateOf(ReportTab.OVERVIEW) }

        ScrollableTabRow(selectedTabIndex = selectedTab.ordinal) {
            ReportTab.entries.forEach { tab ->
                Tab(
                    selected = selectedTab == tab,
                    onClick = { selectedTab = tab },
                    text = { Text(tab.title) },
                )
            }
        }

        Column(modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            AnimatedContent(
                targetState = selectedTab,
                transitionSpec = {
                    // Spatial consistency (apple-design skill): moving to
                    // a later tab slides content in from the right and
                    // the old content out to the left, and vice versa --
                    // never a plain crossfade that discards direction.
                    val forward = targetState.ordinal > initialState.ordinal
                    if (forward) {
                        slideInHorizontally(spring(stiffness = Spring.StiffnessMedium)) { it } togetherWith
                            slideOutHorizontally(spring(stiffness = Spring.StiffnessMedium)) { -it }
                    } else {
                        slideInHorizontally(spring(stiffness = Spring.StiffnessMedium)) { -it } togetherWith
                            slideOutHorizontally(spring(stiffness = Spring.StiffnessMedium)) { it }
                    }
                },
                label = "report-tab",
            ) { tab ->
                when (tab) {
                    ReportTab.OVERVIEW -> {
                        if (overview != null) {
                            OverviewTab(overview = overview, venueDetails = venueDetails, homeTeam = match?.homeTeam ?: "Home", awayTeam = match?.awayTeam ?: "Away")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.LINEUPS -> {
                        if (lineups != null) {
                            LineupsTab(lineups = lineups, homeTeam = match?.homeTeam ?: "Home", awayTeam = match?.awayTeam ?: "Away")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.PERFORMANCE -> {
                        if (performance != null) {
                            PerformanceTab(insights = performance, homeTeam = match?.homeTeam ?: "Home", awayTeam = match?.awayTeam ?: "Away")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.DISCIPLINE -> {
                        if (discipline != null) {
                            DisciplineTab(insights = discipline, homeTeam = match?.homeTeam ?: "Home", awayTeam = match?.awayTeam ?: "Away")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.PROFILE -> {
                        if (profile != null) {
                            ProfileTab(insights = profile, homeTeam = match?.homeTeam ?: "Home", awayTeam = match?.awayTeam ?: "Away")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.STANDINGS -> {
                        if (standings != null) {
                            StandingsTab(insights = standings, standingsTable = standingsTable, homeTeam = match?.homeTeam ?: "Home", awayTeam = match?.awayTeam ?: "Away")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.CONTEXT -> {
                        if (context != null) {
                            ContextTab(insights = context, homeTeam = match?.homeTeam ?: "Home", awayTeam = match?.awayTeam ?: "Away")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.FORM -> {
                        if (teamForm != null && opponentForm != null) {
                            FormTab(form = teamForm, opponentForm = opponentForm, teamLabel = report.team, opponentLabel = if (match != null) (if (match.homeTeam == report.team) match.awayTeam else match.homeTeam) else "Opponent")
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                    ReportTab.SQUAD -> {
                        if (teamProfile != null && opponentProfile != null) {
                            // insights.home/awaySquadStrength are keyed by
                            // match side, not by "searched team vs
                            // opponent" -- map correctly rather than
                            // assuming the searched team is always home.
                            val teamIsHome = match?.homeTeam == report.team
                            Column {
                                SquadTab(
                                    profile = teamProfile,
                                    squadStrength = if (teamIsHome) squadStrength?.homeSquadStrength else squadStrength?.awaySquadStrength,
                                    label = report.team,
                                )
                                SquadTab(
                                    profile = opponentProfile,
                                    squadStrength = if (teamIsHome) squadStrength?.awaySquadStrength else squadStrength?.homeSquadStrength,
                                    label = opponentProfile.teamName,
                                )
                            }
                        } else {
                            PlaceholderTab(tab)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PlaceholderTab(tab: ReportTab) {
    Text(
        "${tab.title} not yet implemented.",
        modifier = Modifier.padding(24.dp),
        style = MaterialTheme.typography.bodyMedium,
    )
}

private fun decodeMatchSummary(matchJson: JsonElement?): MatchSummary? {
    if (matchJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(MatchSummary.serializer(), matchJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeMatchOverview(matchJson: JsonElement?): MatchOverview? {
    if (matchJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(MatchOverview.serializer(), matchJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeVenueDetails(venueDetailsJson: JsonElement?): VenueDetails? {
    if (venueDetailsJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(VenueDetails.serializer(), venueDetailsJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeMatchLineups(matchJson: JsonElement?): MatchLineups? {
    if (matchJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(MatchLineups.serializer(), matchJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeInsightsPerformance(insightsJson: JsonElement?): InsightsPerformance? {
    if (insightsJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(InsightsPerformance.serializer(), insightsJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeInsightsDiscipline(insightsJson: JsonElement?): InsightsDiscipline? {
    if (insightsJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(InsightsDiscipline.serializer(), insightsJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeInsightsProfile(insightsJson: JsonElement?): InsightsProfile? {
    if (insightsJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(InsightsProfile.serializer(), insightsJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeInsightsStandings(insightsJson: JsonElement?): InsightsStandings? {
    if (insightsJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(InsightsStandings.serializer(), insightsJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeMatchStandingsTable(matchJson: JsonElement?): MatchStandingsTable? {
    if (matchJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(MatchStandingsTable.serializer(), matchJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeInsightsContext(insightsJson: JsonElement?): InsightsContext? {
    if (insightsJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(InsightsContext.serializer(), insightsJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeFormSummary(formJson: JsonElement?): FormSummary? {
    if (formJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(FormSummary.serializer(), formJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeTeamProfile(profileJson: JsonElement?): TeamProfileData? {
    if (profileJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(TeamProfileData.serializer(), profileJson)
    } catch (e: SerializationException) {
        null
    }
}

private fun decodeInsightsSquadStrength(insightsJson: JsonElement?): InsightsSquadStrength? {
    if (insightsJson == null) return null
    return try {
        AppJson.decodeFromJsonElement(InsightsSquadStrength.serializer(), insightsJson)
    } catch (e: SerializationException) {
        null
    }
}
