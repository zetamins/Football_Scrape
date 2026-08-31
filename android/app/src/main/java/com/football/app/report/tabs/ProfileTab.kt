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
import com.football.app.data.model.InsightsProfile
import com.football.app.ui.theme.AppTheme

/** frontend/DESIGN.md's Profile tab. */
@Composable
fun ProfileTab(insights: InsightsProfile, homeTeam: String, awayTeam: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        StyleRadar(insights)
        PassingSection(insights, homeTeam, awayTeam)
        AerialAndGoalkeepingSection(insights, homeTeam, awayTeam)
        DefensiveErrorsSection(insights, homeTeam, awayTeam)
        RiskSection(insights, homeTeam, awayTeam)
        ThreatSection(insights, homeTeam, awayTeam)
    }
}

@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(4.dp))
            content()
        }
    }
}

@Composable
private fun StyleRadar(insights: InsightsProfile) {
    val hp = insights.homePassingStyle
    val ap = insights.awayPassingStyle
    val ha = insights.homeAerialEstimate
    val aa = insights.awayAerialEstimate
    val hg = insights.homeGoalkeepingEstimate
    val ag = insights.awayGoalkeepingEstimate
    if (hp == null || ap == null) return
    SectionCard("Style profile") {
        val axes = listOfNotNull(
            RadarAxis("Pass accuracy", (hp.passAccuracyPct ?: 0.0).toFloat(), (ap.passAccuracyPct ?: 0.0).toFloat(), maxValue = 100f),
            RadarAxis("Long-ball share", (hp.longBallSharePct ?: 0.0).toFloat(), (ap.longBallSharePct ?: 0.0).toFloat(), maxValue = 25f),
            if (ha != null && aa != null) RadarAxis("Aerial duels won", ha.aerialDuelsWonFor.toFloat(), aa.aerialDuelsWonFor.toFloat(), maxValue = 60f) else null,
            if (hg != null && ag != null) RadarAxis("Save %", (hg.savePct ?: 0.0).toFloat(), (ag.savePct ?: 0.0).toFloat(), maxValue = 100f) else null,
        )
        if (axes.size >= 3) {
            RadarChart(axes = axes, homeColor = AppTheme.colors.homeSeries, awayColor = AppTheme.colors.awaySeries)
        }
    }
}

@Composable
private fun PassingSection(insights: InsightsProfile, homeTeam: String, awayTeam: String) {
    if (insights.homePassingStyle == null && insights.awayPassingStyle == null) return
    SectionCard("Passing") {
        insights.homePassingStyle?.let { p ->
            InfoRow(homeTeam, "${p.passAccuracyPct ?: "n/a"}% accuracy, ${p.longBallSharePct ?: "n/a"}% long balls")
        }
        insights.awayPassingStyle?.let { p ->
            InfoRow(awayTeam, "${p.passAccuracyPct ?: "n/a"}% accuracy, ${p.longBallSharePct ?: "n/a"}% long balls")
        }
    }
}

@Composable
private fun AerialAndGoalkeepingSection(insights: InsightsProfile, homeTeam: String, awayTeam: String) {
    val ha = insights.homeAerialEstimate
    val aa = insights.awayAerialEstimate
    val hasAerial = ha != null && aa != null
    val hasGk = insights.homeGoalkeepingEstimate != null || insights.awayGoalkeepingEstimate != null
    if (!hasAerial && !hasGk) return
    SectionCard("Aerial & goalkeeping") {
        if (hasAerial) {
            BarComparison(
                "Aerial duels won (last 10)",
                ha!!.aerialDuelsWonFor.toFloat(),
                aa!!.aerialDuelsWonFor.toFloat(),
                AppTheme.colors.homeSeries,
                AppTheme.colors.awaySeries,
                "$homeTeam ${ha.aerialDuelsWonFor}",
                "$awayTeam ${aa.aerialDuelsWonFor}",
            )
            Spacer(Modifier.height(8.dp))
        }
        insights.homeGoalkeepingEstimate?.let { g ->
            InfoRow(homeTeam, "${g.savesFor} saves / ${g.shotsOnTargetFaced} faced (${g.savePct ?: "n/a"}%), ${g.goalsConceded} conceded")
        }
        insights.awayGoalkeepingEstimate?.let { g ->
            InfoRow(awayTeam, "${g.savesFor} saves / ${g.shotsOnTargetFaced} faced (${g.savePct ?: "n/a"}%), ${g.goalsConceded} conceded")
        }
    }
}

@Composable
private fun DefensiveErrorsSection(insights: InsightsProfile, homeTeam: String, awayTeam: String) {
    if (insights.homeDefensiveErrorsEstimate == null && insights.awayDefensiveErrorsEstimate == null) return
    SectionCard("Defensive errors") {
        insights.homeDefensiveErrorsEstimate?.let { e ->
            InfoRow(homeTeam, "${e.defensiveErrorsFor} for / ${e.defensiveErrorsAgainst} against", valueColor = AppTheme.colors.statusWarning)
        }
        insights.awayDefensiveErrorsEstimate?.let { e ->
            InfoRow(awayTeam, "${e.defensiveErrorsFor} for / ${e.defensiveErrorsAgainst} against", valueColor = AppTheme.colors.statusWarning)
        }
    }
}

@Composable
private fun RiskSection(insights: InsightsProfile, homeTeam: String, awayTeam: String) {
    val hasDuel = !insights.homeDuelVulnerabilities.isNullOrEmpty() || !insights.awayDuelVulnerabilities.isNullOrEmpty()
    val hasFullback = !insights.homeFullbackExposure.isNullOrEmpty() || !insights.awayFullbackExposure.isNullOrEmpty()
    if (!hasDuel && !hasFullback) return
    SectionCard("Risk") {
        insights.homeDuelVulnerabilities?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow("$homeTeam duel risk", list.joinToString(", ") { "${it.name} (${it.groundDuelSuccessPct}%)" }, valueColor = AppTheme.colors.statusWarning)
        }
        insights.awayDuelVulnerabilities?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow("$awayTeam duel risk", list.joinToString(", ") { "${it.name} (${it.groundDuelSuccessPct}%)" }, valueColor = AppTheme.colors.statusWarning)
        }
        insights.homeFullbackExposure?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow("$homeTeam exposed fullbacks", list.joinToString(", ") { it.name }, valueColor = AppTheme.colors.statusWarning)
        }
        insights.awayFullbackExposure?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow("$awayTeam exposed fullbacks", list.joinToString(", ") { it.name }, valueColor = AppTheme.colors.statusWarning)
        }
    }
}

@Composable
private fun ThreatSection(insights: InsightsProfile, homeTeam: String, awayTeam: String) {
    val hasSetPiece = insights.homeSetPieceThreat != null || insights.awaySetPieceThreat != null
    val hasDirectPlay = insights.homeDirectPlayExposure != null || insights.awayDirectPlayExposure != null
    if (!hasSetPiece && !hasDirectPlay) return
    SectionCard("Set-piece & direct-play tendencies") {
        insights.homeSetPieceThreat?.let { t ->
            InfoRow(
                "$homeTeam set-piece threat",
                "${t.cornersPerGame ?: "n/a"} corners/game vs opp's ${t.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = if (t.elevated) AppTheme.colors.statusGood else androidx.compose.ui.graphics.Color.Unspecified,
            )
        }
        insights.awaySetPieceThreat?.let { t ->
            InfoRow(
                "$awayTeam set-piece threat",
                "${t.cornersPerGame ?: "n/a"} corners/game vs opp's ${t.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = if (t.elevated) AppTheme.colors.statusGood else androidx.compose.ui.graphics.Color.Unspecified,
            )
        }
        insights.homeDirectPlayExposure?.let { d ->
            InfoRow(
                "$homeTeam direct-play exposure",
                "${d.longBallSharePct ?: "n/a"}% long balls vs opp's ${d.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = if (d.elevated) AppTheme.colors.statusWarning else androidx.compose.ui.graphics.Color.Unspecified,
            )
        }
        insights.awayDirectPlayExposure?.let { d ->
            InfoRow(
                "$awayTeam direct-play exposure",
                "${d.longBallSharePct ?: "n/a"}% long balls vs opp's ${d.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = if (d.elevated) AppTheme.colors.statusWarning else androidx.compose.ui.graphics.Color.Unspecified,
            )
        }
    }
}
