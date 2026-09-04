package com.football.app.report.tabs

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.football.app.charts.BarComparison
import com.football.app.charts.RadarAxis
import com.football.app.charts.RadarChart
import com.football.app.components.InfoRow
import com.football.app.components.SectionCard
import com.football.app.data.model.AdvancedStats
import com.football.app.data.model.InsightsPerformance
import com.football.app.ui.theme.AppTheme

/** frontend/DESIGN.md's Performance tab. */
@Composable
fun PerformanceTab(
    insights: InsightsPerformance,
    homeTeam: String,
    awayTeam: String,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        AttackProfileRadar(insights)
        CoreStatsSection(insights, homeTeam, awayTeam)
        AdvancedStatsSection(insights, homeTeam, awayTeam)
        PossessionMatchupSection(insights, homeTeam, awayTeam)
    }
}

@Composable
private fun AttackProfileRadar(insights: InsightsPerformance) {
    val home = insights.homeAdvancedStats
    val away = insights.awayAdvancedStats
    if (home == null || away == null) return
    SectionCard("Attack profile") {
        val axes =
            listOf(
                RadarAxis(
                    "xG",
                    (insights.homeXgEstimate?.xgFor ?: 0.0).toFloat(),
                    (insights.awayXgEstimate?.xgFor ?: 0.0).toFloat(),
                    maxValue = 3f,
                ),
                RadarAxis("Shots", home.totalShotsFor.toFloat(), away.totalShotsFor.toFloat(), maxValue = 20f),
                RadarAxis("Big chances", home.bigChancesCreatedFor.toFloat(), away.bigChancesCreatedFor.toFloat(), maxValue = 8f),
                RadarAxis("Touches in box", home.touchesInBoxFor.toFloat(), away.touchesInBoxFor.toFloat(), maxValue = 40f),
                RadarAxis("Dribbles", home.dribblesFor.toFloat(), away.dribblesFor.toFloat(), maxValue = 15f),
            )
        RadarChart(axes = axes, homeColor = AppTheme.colors.homeSeries, awayColor = AppTheme.colors.awaySeries)
    }
}

@Composable
private fun CoreStatsSection(
    insights: InsightsPerformance,
    homeTeam: String,
    awayTeam: String,
) {
    val hasCore =
        insights.homeXgEstimate != null || insights.homeShotsEstimate != null ||
            insights.homeBigChancesEstimate != null || insights.homeCornersEstimate != null
    if (!hasCore) return
    SectionCard("Season estimates") {
        insights.homeXgEstimate?.let { h ->
            insights.awayXgEstimate?.let { a ->
                BarComparison(
                    "xG for",
                    h.xgFor.toFloat(),
                    a.xgFor.toFloat(),
                    AppTheme.colors.homeSeries,
                    AppTheme.colors.awaySeries,
                    "$homeTeam ${h.xgFor}",
                    "$awayTeam ${a.xgFor}",
                )
                Spacer(Modifier.height(8.dp))
                BarComparison(
                    "xG against",
                    h.xgAgainst.toFloat(),
                    a.xgAgainst.toFloat(),
                    AppTheme.colors.homeSeries,
                    AppTheme.colors.awaySeries,
                    "$homeTeam ${h.xgAgainst}",
                    "$awayTeam ${a.xgAgainst}",
                )
                Spacer(Modifier.height(8.dp))
            }
        }
        insights.homeShotsEstimate?.let { h ->
            insights.awayShotsEstimate?.let { a ->
                BarComparison(
                    "Shots (last 10)",
                    h.shotsFor.toFloat(),
                    a.shotsFor.toFloat(),
                    AppTheme.colors.homeSeries,
                    AppTheme.colors.awaySeries,
                    "$homeTeam ${h.shotsFor}",
                    "$awayTeam ${a.shotsFor}",
                )
                Spacer(Modifier.height(8.dp))
                BarComparison(
                    "Shots on target (last 10)",
                    h.shotsOnTargetFor.toFloat(),
                    a.shotsOnTargetFor.toFloat(),
                    AppTheme.colors.homeSeries,
                    AppTheme.colors.awaySeries,
                    "$homeTeam ${h.shotsOnTargetFor}",
                    "$awayTeam ${a.shotsOnTargetFor}",
                )
                Spacer(Modifier.height(8.dp))
            }
        }
        insights.homeBigChancesEstimate?.let { h ->
            insights.awayBigChancesEstimate?.let { a ->
                BarComparison(
                    "Big chances created",
                    h.bigChancesCreatedFor.toFloat(),
                    a.bigChancesCreatedFor.toFloat(),
                    AppTheme.colors.homeSeries,
                    AppTheme.colors.awaySeries,
                    "$homeTeam ${h.bigChancesCreatedFor}",
                    "$awayTeam ${a.bigChancesCreatedFor}",
                )
                Spacer(Modifier.height(8.dp))
                BarComparison(
                    "Big chances missed",
                    h.bigChancesMissedFor.toFloat(),
                    a.bigChancesMissedFor.toFloat(),
                    AppTheme.colors.homeSeries,
                    AppTheme.colors.awaySeries,
                    "$homeTeam ${h.bigChancesMissedFor}",
                    "$awayTeam ${a.bigChancesMissedFor}",
                )
                Spacer(Modifier.height(8.dp))
            }
        }
        insights.homeCornersEstimate?.let { h ->
            insights.awayCornersEstimate?.let { a ->
                BarComparison(
                    "Corners (last 10)",
                    h.cornersFor.toFloat(),
                    a.cornersFor.toFloat(),
                    AppTheme.colors.homeSeries,
                    AppTheme.colors.awaySeries,
                    "$homeTeam ${h.cornersFor}",
                    "$awayTeam ${a.cornersFor}",
                )
            }
        }
    }
}

@Composable
private fun AdvancedStatsSection(
    insights: InsightsPerformance,
    homeTeam: String,
    awayTeam: String,
) {
    val h = insights.homeAdvancedStats
    val a = insights.awayAdvancedStats
    if (h == null || a == null) return
    SectionCard("Advanced stats (matched sample)") {
        AdvancedBar("Touches in box", h.touchesInBoxFor, a.touchesInBoxFor, homeTeam, awayTeam)
        AdvancedBar("Shots inside box", h.shotsInsideBoxFor, a.shotsInsideBoxFor, homeTeam, awayTeam)
        AdvancedBar("Blocked shots", h.blockedShotsFor, a.blockedShotsFor, homeTeam, awayTeam)
        AdvancedBar("Crosses", h.crossesFor, a.crossesFor, homeTeam, awayTeam)
        AdvancedBar("Dribbles", h.dribblesFor, a.dribblesFor, homeTeam, awayTeam)
        AdvancedBar("Tackles", h.teamTacklesFor, a.teamTacklesFor, homeTeam, awayTeam)
        AdvancedBar("Interceptions", h.teamInterceptionsFor, a.teamInterceptionsFor, homeTeam, awayTeam)
        AdvancedBar("Clearances", h.teamClearancesFor, a.teamClearancesFor, homeTeam, awayTeam)
        AdvancedBarDouble("xA", h.xaFor, a.xaFor, homeTeam, awayTeam)
        AdvancedBarDouble("Distance covered (km)", h.distanceCoveredKmFor, a.distanceCoveredKmFor, homeTeam, awayTeam)
        AdvancedBar("Total shots (sofascore)", h.totalShotsFor, a.totalShotsFor, homeTeam, awayTeam)
        AdvancedBar("Shots on target (sofascore)", h.shotsOnTargetFor, a.shotsOnTargetFor, homeTeam, awayTeam)
        AdvancedBarDouble("Non-penalty xG", h.nonPenaltyXgFor, a.nonPenaltyXgFor, homeTeam, awayTeam)
        AdvancedBarDouble("Set-piece xG", h.setPieceXgFor, a.setPieceXgFor, homeTeam, awayTeam)
        AdvancedBar("Big chances created (sofascore)", h.bigChancesCreatedFor, a.bigChancesCreatedFor, homeTeam, awayTeam)

        InfoRow("$homeTeam set-piece goals (corner/pen/FK)", "${h.cornerGoalsFor}/${h.penaltyGoalsFor}/${h.freeKickGoalsFor}")
        InfoRow("$awayTeam set-piece goals (corner/pen/FK)", "${a.cornerGoalsFor}/${a.penaltyGoalsFor}/${a.freeKickGoalsFor}")
        InfoRow(
            "$homeTeam errors -> shot/goal",
            "${h.errorsLeadToShotFor} / ${h.errorsLeadToGoalFor}",
            valueColor = if (h.errorsLeadToGoalFor > 0) AppTheme.colors.statusCritical else androidx.compose.ui.graphics.Color.Unspecified,
        )
        InfoRow(
            "$awayTeam errors -> shot/goal",
            "${a.errorsLeadToShotFor} / ${a.errorsLeadToGoalFor}",
            valueColor = if (a.errorsLeadToGoalFor > 0) AppTheme.colors.statusCritical else androidx.compose.ui.graphics.Color.Unspecified,
        )
        InfoRow("$homeTeam offsides / dispossessed", "${h.offsidesFor} / ${h.dispossessedFor}")
        InfoRow("$awayTeam offsides / dispossessed", "${a.offsidesFor} / ${a.dispossessedFor}")
        val possessionLine1 = "${h.possessionPctAvg ?: "n/a"}% poss, ${h.fieldTiltPct ?: "n/a"}% field tilt"
        val possessionLine2 = "${a.possessionPctAvg ?: "n/a"}% poss, ${a.fieldTiltPct ?: "n/a"}% field tilt"
        InfoRow("$homeTeam possession / field tilt", possessionLine1)
        InfoRow("$awayTeam possession / field tilt", possessionLine2)
        InfoRow("$homeTeam penalties awarded", "${h.penaltiesAwardedFor} for / ${h.penaltiesAwardedAgainst} against")
        InfoRow("$awayTeam penalties awarded", "${a.penaltiesAwardedFor} for / ${a.penaltiesAwardedAgainst} against")
    }
}

@Composable
private fun AdvancedBar(
    label: String,
    home: Int,
    away: Int,
    homeTeam: String,
    awayTeam: String,
) {
    BarComparison(
        label,
        home.toFloat(),
        away.toFloat(),
        AppTheme.colors.homeSeries,
        AppTheme.colors.awaySeries,
        "$homeTeam $home",
        "$awayTeam $away",
    )
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun AdvancedBarDouble(
    label: String,
    home: Double,
    away: Double,
    homeTeam: String,
    awayTeam: String,
) {
    BarComparison(
        label,
        home.toFloat(),
        away.toFloat(),
        AppTheme.colors.homeSeries,
        AppTheme.colors.awaySeries,
        "$homeTeam $home",
        "$awayTeam $away",
    )
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun PossessionMatchupSection(
    insights: InsightsPerformance,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homePossessionMatchup == null && insights.awayPossessionMatchup == null) return
    SectionCard("Possession matchup") {
        insights.homePossessionMatchup?.let { p ->
            InfoRow(
                "$homeTeam vs high-possession opponents",
                "${p.highOpponentPossessionPpg ?: "n/a"} ppg (n=${p.highOpponentPossessionSampleSize}) vs ${p.otherPpg ?: "n/a"} ppg otherwise",
            )
        }
        insights.awayPossessionMatchup?.let { p ->
            InfoRow(
                "$awayTeam vs high-possession opponents",
                "${p.highOpponentPossessionPpg ?: "n/a"} ppg (n=${p.highOpponentPossessionSampleSize}) vs ${p.otherPpg ?: "n/a"} ppg otherwise",
            )
        }
    }
}
