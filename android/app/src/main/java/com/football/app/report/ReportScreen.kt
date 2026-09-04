package com.football.app.report

import android.content.Intent
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import com.football.app.components.Pill
import com.football.app.components.TeamBadge
import com.football.app.data.AppJson
import com.football.app.data.model.FormSummary
import com.football.app.data.model.InsightsContext
import com.football.app.data.model.InsightsDiscipline
import com.football.app.data.model.InsightsPerformance
import com.football.app.data.model.InsightsProfile
import com.football.app.data.model.InsightsSquadStrength
import com.football.app.data.model.InsightsStandings
import com.football.app.data.model.MatchLineups
import com.football.app.data.model.MatchOverview
import com.football.app.data.model.MatchStandingsTable
import com.football.app.data.model.MatchSummary
import com.football.app.data.model.ReportJson
import com.football.app.data.model.StandingsTableRow
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
import com.football.app.ui.theme.AppTheme
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonElement
import java.io.File

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
fun ReportScreen(
    viewModel: ReportViewModel,
    onBack: () -> Unit,
    onHistoryClick: () -> Unit,
) {
    val state by viewModel.state.collectAsState()
    val success = state as? SearchState.Success

    val context = LocalContext.current
    val saveJsonLauncher =
        rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
            saveReportToUri(context, uri, success?.rawJson)
        }

    Column(modifier = Modifier.fillMaxSize()) {
        // Checking `success` itself (not `report`) lets Kotlin smart-cast
        // it to non-null for the rest of this block -- report.team is
        // used below, but so is success.rawJson (Share button), and a
        // `report == null` guard wouldn't prove `success` is non-null to
        // the compiler even though the two are equivalent here (kotlin:S6619
        // flagged the resulting `success?.` as a redundant safe-call).
        if (success == null) {
            Text("No report loaded.", modifier = Modifier.padding(24.dp))
            return@Column
        }
        val report = success.report

        val match = remember(report.match) { decodeOrNull(report.match, MatchSummary.serializer()) }
        val data = rememberReportTabData(report)

        ReportHeaderRow(
            team = report.team,
            generatedAt = report.generatedAt,
            onBack = onBack,
            onHistoryClick = onHistoryClick,
            onDownloadClick = {
                val safeTeam = report.team.replace(Regex("[^A-Za-z0-9]+"), "_")
                saveJsonLauncher.launch("${safeTeam}_report.json")
            },
            onShareClick = { shareReportJson(context, report.team, success.rawJson) },
        )

        // Shared with ReportTabPager below -- the collapse fraction is
        // derived directly from this same ScrollState's offset, so the
        // header shrinks in lockstep with the tab content actually
        // scrolling (not a separate nested-scroll drag simulation).
        val tabScrollState = rememberScrollState()
        val collapseFraction by remember {
            derivedStateOf { (tabScrollState.value / HEADER_COLLAPSE_RANGE_PX).coerceIn(0f, 1f) }
        }

        if (match != null) {
            CollapsingMatchHeader(
                homeTeam = match.homeTeam,
                awayTeam = match.awayTeam,
                insightsJson = report.insights,
                collapseFraction = collapseFraction,
            )
        }

        var selectedTab by remember { mutableStateOf(ReportTab.OVERVIEW) }
        ReportTabBar(selectedTab = selectedTab, onTabSelected = { selectedTab = it })
        ReportTabPager(selectedTab = selectedTab, teamName = report.team, match = match, data = data, scrollState = tabScrollState)
    }
}

/** How much scroll (in px) it takes to fully collapse the header --
 * tuned by feel, not derived from the header's own measured height, so
 * it stays a constant regardless of how much content the prediction
 * hero happens to render for a given match. */
private const val HEADER_COLLAPSE_RANGE_PX = 600f

/**
 * Wraps MatchupHeader + PredictionHero so they shrink (and fade) toward
 * the top as collapseFraction goes 0 -> 1, freeing vertical space for
 * the actual tab content below as the user scrolls it. Measures its own
 * natural (fully-expanded) height once via onSizeChanged -- the inner
 * Column always measures itself unconstrained (wrapContentHeight(
 * unbounded = true)), so its real content never gets squished; only the
 * outer Box's reported height shrinks, with clipToBounds() cropping the
 * now-taller-than-its-box content rather than letting it bleed into the
 * tab bar below.
 */
@Composable
private fun CollapsingMatchHeader(
    homeTeam: String,
    awayTeam: String,
    insightsJson: JsonElement?,
    collapseFraction: Float,
) {
    val density = LocalDensity.current
    var naturalHeightPx by remember { mutableIntStateOf(0) }
    Box(
        modifier =
            Modifier
                .fillMaxWidth()
                .then(
                    if (naturalHeightPx > 0) {
                        val collapsedPx = (naturalHeightPx * (1f - collapseFraction)).toInt().coerceAtLeast(0)
                        Modifier.height(with(density) { collapsedPx.toDp() })
                    } else {
                        Modifier
                    },
                ).clipToBounds(),
    ) {
        Column(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .wrapContentHeight(unbounded = true)
                    .onSizeChanged { size -> if (naturalHeightPx == 0) naturalHeightPx = size.height }
                    .graphicsLayer { alpha = (1f - collapseFraction).coerceIn(0.25f, 1f) },
        ) {
            MatchupHeader(homeTeam = homeTeam, awayTeam = awayTeam)
            PredictionHero(insightsJson = insightsJson, homeTeam = homeTeam, awayTeam = awayTeam)
        }
    }
}

private fun saveReportToUri(
    context: android.content.Context,
    uri: android.net.Uri?,
    rawJson: String?,
) {
    if (uri != null && rawJson != null) {
        context.contentResolver.openOutputStream(uri)?.use { it.write(rawJson.toByteArray()) }
        Toast.makeText(context, "Saved.", Toast.LENGTH_SHORT).show()
    }
}

/**
 * Opens the system share sheet with the report's raw JSON as a file --
 * ChatGPT, Gemini, or any other installed app that accepts a shared
 * file/text shows up there if the user has it installed. There's no
 * public API on either app to jump straight into "paste this into a new
 * chat" -- the share sheet, where the user picks the target themselves,
 * is the standard (and only reliable, Play-Store-compliant) mechanism
 * for handing content to a third-party app on Android.
 *
 * Shared as a FILE (via FileProvider), not as plain EXTRA_TEXT -- this
 * app's reports are large (9 tabs' worth of nested JSON), and
 * ACTION_SEND's EXTRA_TEXT has no guaranteed size ceiling but is known
 * to silently truncate or fail in some receiving apps well under 1MB;
 * a file attachment doesn't have that problem and both ChatGPT and
 * Gemini's Android apps accept file attachments for analysis.
 */
private fun shareReportJson(
    context: android.content.Context,
    team: String,
    rawJson: String,
) {
    val safeTeam = team.replace(Regex("[^A-Za-z0-9]+"), "_")
    val sharedDir = File(context.cacheDir, "shared").apply { mkdirs() }
    // Cheap unbounded-growth guard, not a security fix (each file's
    // actual readability is already gated per-grant by FileProvider/
    // FLAG_GRANT_READ_URI_PERMISSION regardless of how many pile up) --
    // clears prior shares before writing this one, so repeated use of
    // this button doesn't slowly accumulate files in the app's cache.
    sharedDir.listFiles()?.forEach { it.delete() }
    val file = File(sharedDir, "${safeTeam}_report.json")
    file.writeText(rawJson)

    val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    val sendIntent =
        Intent(Intent.ACTION_SEND).apply {
            type = "application/json"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, "$team football report")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    context.startActivity(Intent.createChooser(sendIntent, "Share report"))
}

@Composable
private fun ReportHeaderRow(
    team: String,
    generatedAt: String,
    onBack: () -> Unit,
    onHistoryClick: () -> Unit,
    onDownloadClick: () -> Unit,
    onShareClick: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.weight(1f)) {
            // Previously missing entirely -- there was no way to leave
            // the Report screen except the system back gesture/button,
            // which didn't reliably navigate away either (confirmed live:
            // pressing system back while on this screen stayed put).
            // Every other secondary screen (History) already has this
            // exact pattern -- Report was the one screen missing it.
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            TeamBadge(team, AppTheme.colors.homeSeries, size = TeamBadge.SizeMedium)
            Column(modifier = Modifier.padding(start = 10.dp).weight(1f, fill = false)) {
                Text(team, style = MaterialTheme.typography.headlineMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("Generated $generatedAt", style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        Row {
            IconButton(onClick = onHistoryClick) {
                Icon(Icons.Default.History, contentDescription = "History")
            }
            IconButton(onClick = onShareClick) {
                Icon(Icons.Default.Share, contentDescription = "Share report (e.g. to ChatGPT or Gemini)")
            }
            IconButton(onClick = onDownloadClick) {
                Icon(Icons.Default.Download, contentDescription = "Download JSON")
            }
        }
    }
}

// A scrollable row of pill buttons, not ScrollableTabRow's default
// underline indicator -- matches the reference's segmented-pill tab bar
// (active = solid brand fill, inactive = plain text) used throughout
// this session's reskin.
@Composable
private fun ReportTabBar(
    selectedTab: ReportTab,
    onTabSelected: (ReportTab) -> Unit,
) {
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        ReportTab.entries.forEach { tab ->
            ReportTabPill(tab = tab, selected = selectedTab == tab, onClick = { onTabSelected(tab) })
        }
    }
}

/** Reuses the shared Pill shape/background/clip logic (previously
 * hand-rolled here, duplicating it) -- its own font size/padding stay
 * exactly what they were (ambient tab-bar size, 16/8 padding), since
 * this is a distinct, already-tuned use, not a plain Pill call site. */
@Composable
private fun ReportTabPill(
    tab: ReportTab,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Pill(
        text = tab.title,
        containerColor = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
        contentColor = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        fontSize = TextUnit.Unspecified,
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        modifier = Modifier.clickable(onClick = onClick),
    )
}

@Composable
private fun ReportTabPager(
    selectedTab: ReportTab,
    teamName: String,
    match: MatchSummary?,
    data: ReportTabData,
    scrollState: ScrollState,
) {
    Column(modifier = Modifier.fillMaxSize().verticalScroll(scrollState)) {
        AnimatedContent(
            targetState = selectedTab,
            transitionSpec = {
                // Spatial consistency (apple-design skill): moving to a
                // later tab slides content in from the right and the old
                // content out to the left, and vice versa -- never a
                // plain crossfade that discards direction.
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
            ReportTabContent(tab = tab, teamName = teamName, match = match, data = data)
        }
    }
}

/**
 * One tab's null-check-then-render decision, factored out so the
 * dispatch `when` below stays a flat list of single calls instead of 9
 * repeated if/else blocks -- that repetition was the entire reason
 * ReportScreen's own cognitive complexity previously ran to 111
 * (python:S3776's Kotlin equivalent, kotlin:S3776).
 */
@Composable
private fun <T> DecodedTab(
    tab: ReportTab,
    data: T?,
    content: @Composable (T) -> Unit,
) {
    if (data != null) content(data) else PlaceholderTab(tab)
}

/**
 * Every decoded report section, bundled into one value class purely so
 * ReportTabContent/ReportTabPager don't carry a 14-parameter signature
 * (kotlin:S107) -- each field keeps its own original meaning, this is
 * just a grouping, not a new abstraction over the data itself.
 */
private data class ReportTabData(
    val overview: MatchOverview?,
    val venueDetails: VenueDetails?,
    val lineups: MatchLineups?,
    val performance: InsightsPerformance?,
    val discipline: InsightsDiscipline?,
    val profile: InsightsProfile?,
    val standings: InsightsStandings?,
    val standingsTable: List<StandingsTableRow>?,
    val context: InsightsContext?,
    val teamForm: FormSummary?,
    val opponentForm: FormSummary?,
    val teamProfile: TeamProfileData?,
    val opponentProfile: TeamProfileData?,
    val squadStrength: InsightsSquadStrength?,
)

/** Same `remember(report.X) { decodeOrNull(report.X, ...) }` keys as
 * before this was factored out -- each field only re-decodes when its
 * own specific report sub-field changes, not on every ReportTabData
 * construction. */
@Composable
private fun rememberReportTabData(report: ReportJson): ReportTabData =
    ReportTabData(
        overview = remember(report.match) { decodeOrNull(report.match, MatchOverview.serializer()) },
        venueDetails = remember(report.venueDetails) { decodeOrNull(report.venueDetails, VenueDetails.serializer()) },
        lineups = remember(report.match) { decodeOrNull(report.match, MatchLineups.serializer()) },
        performance = remember(report.insights) { decodeOrNull(report.insights, InsightsPerformance.serializer()) },
        discipline = remember(report.insights) { decodeOrNull(report.insights, InsightsDiscipline.serializer()) },
        profile = remember(report.insights) { decodeOrNull(report.insights, InsightsProfile.serializer()) },
        standings = remember(report.insights) { decodeOrNull(report.insights, InsightsStandings.serializer()) },
        standingsTable =
            remember(report.match) { decodeOrNull(report.match, MatchStandingsTable.serializer())?.standingsTable },
        context = remember(report.insights) { decodeOrNull(report.insights, InsightsContext.serializer()) },
        teamForm = remember(report.form) { decodeOrNull(report.form, FormSummary.serializer()) },
        opponentForm = remember(report.opponentForm) { decodeOrNull(report.opponentForm, FormSummary.serializer()) },
        teamProfile = remember(report.teamProfile) { decodeOrNull(report.teamProfile, TeamProfileData.serializer()) },
        opponentProfile =
            remember(report.opponentProfile) { decodeOrNull(report.opponentProfile, TeamProfileData.serializer()) },
        squadStrength = remember(report.insights) { decodeOrNull(report.insights, InsightsSquadStrength.serializer()) },
    )

/**
 * The 9-tab dispatch, extracted from ReportScreen's AnimatedContent body
 * for the same complexity reason as DecodedTab above -- every branch is
 * now a single call (FORM/SQUAD delegate their own multi-value-null-
 * check logic to their own small composables below), so this function's
 * own complexity is just the `when` itself.
 */
@Composable
private fun ReportTabContent(
    tab: ReportTab,
    teamName: String,
    match: MatchSummary?,
    data: ReportTabData,
) {
    val homeTeam = match?.homeTeam ?: "Home"
    val awayTeam = match?.awayTeam ?: "Away"
    when (tab) {
        ReportTab.OVERVIEW -> {
            DecodedTab(tab, data.overview) {
                OverviewTab(overview = it, venueDetails = data.venueDetails, homeTeam = homeTeam, awayTeam = awayTeam)
            }
        }

        ReportTab.LINEUPS -> {
            DecodedTab(tab, data.lineups) { LineupsTab(lineups = it, homeTeam = homeTeam, awayTeam = awayTeam) }
        }

        ReportTab.PERFORMANCE -> {
            DecodedTab(
                tab,
                data.performance,
            ) { PerformanceTab(insights = it, homeTeam = homeTeam, awayTeam = awayTeam) }
        }

        ReportTab.DISCIPLINE -> {
            DecodedTab(tab, data.discipline) { DisciplineTab(insights = it, homeTeam = homeTeam, awayTeam = awayTeam) }
        }

        ReportTab.PROFILE -> {
            DecodedTab(tab, data.profile) { ProfileTab(insights = it, homeTeam = homeTeam, awayTeam = awayTeam) }
        }

        ReportTab.STANDINGS -> {
            DecodedTab(tab, data.standings) {
                StandingsTab(insights = it, standingsTable = data.standingsTable, homeTeam = homeTeam, awayTeam = awayTeam)
            }
        }

        ReportTab.CONTEXT -> {
            DecodedTab(tab, data.context) { ContextTab(insights = it, homeTeam = homeTeam, awayTeam = awayTeam) }
        }

        ReportTab.FORM -> {
            FormTabContent(tab, teamName, match, data.teamForm, data.opponentForm)
        }

        ReportTab.SQUAD -> {
            SquadTabContent(tab, teamName, match, data.teamProfile, data.opponentProfile, data.squadStrength)
        }
    }
}

@Composable
private fun FormTabContent(
    tab: ReportTab,
    teamName: String,
    match: MatchSummary?,
    teamForm: FormSummary?,
    opponentForm: FormSummary?,
) {
    val bothForms = if (teamForm != null && opponentForm != null) teamForm to opponentForm else null
    DecodedTab(tab, bothForms) { (ownForm, oppForm) ->
        val opponentLabel = if (match != null) (if (match.homeTeam == teamName) match.awayTeam else match.homeTeam) else "Opponent"
        FormTab(form = ownForm, opponentForm = oppForm, teamLabel = teamName, opponentLabel = opponentLabel)
    }
}

@Composable
private fun SquadTabContent(
    tab: ReportTab,
    teamName: String,
    match: MatchSummary?,
    teamProfile: TeamProfileData?,
    opponentProfile: TeamProfileData?,
    squadStrength: InsightsSquadStrength?,
) {
    val bothProfiles = if (teamProfile != null && opponentProfile != null) teamProfile to opponentProfile else null
    DecodedTab(tab, bothProfiles) { (ownProfile, oppProfile) ->
        // insights.home/awaySquadStrength are keyed by match side, not by
        // "searched team vs opponent" -- map correctly rather than
        // assuming the searched team is always home.
        val teamIsHome = match?.homeTeam == teamName
        Column {
            SquadTab(
                profile = ownProfile,
                squadStrength = if (teamIsHome) squadStrength?.homeSquadStrength else squadStrength?.awaySquadStrength,
                label = teamName,
            )
            SquadTab(
                profile = oppProfile,
                squadStrength = if (teamIsHome) squadStrength?.awaySquadStrength else squadStrength?.homeSquadStrength,
                label = oppProfile.teamName,
            )
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

/**
 * Every report sub-field's own decode-with-null-safety, in one place --
 * previously 13 separate functions (decodeMatchSummary, decodeMatchOverview,
 * decodeVenueDetails, ... through decodeInsightsSquadStrength), each the
 * exact same 6-line body differing only by type. `json` is `null` for a
 * genuinely absent report section (matches ReportJson field nullability);
 * decode failure (a malformed/unexpected shape) is treated the same way
 * as absence, not surfaced as an error -- this screen's whole per-tab
 * design already renders "not yet implemented" for a null section (see
 * DecodedTab/PlaceholderTab above), so a bad decode just falls into that
 * same, already-handled path.
 */
private fun <T> decodeOrNull(
    json: JsonElement?,
    serializer: KSerializer<T>,
): T? {
    if (json == null) return null
    return try {
        AppJson.decodeFromJsonElement(serializer, json)
    } catch (e: SerializationException) {
        null
    }
}
