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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.football.app.charts.BarComparison
import com.football.app.charts.RadarAxis
import com.football.app.charts.RadarChart
import com.football.app.components.InfoRow
import com.football.app.components.OutlinedPill
import com.football.app.components.SectionCard
import com.football.app.data.model.InsightsProfile
import com.football.app.data.model.SeasonAerialEstimate
import com.football.app.data.model.SeasonGoalkeepingEstimate
import com.football.app.ui.theme.AppTheme

/** frontend/DESIGN.md's Profile tab. */
@Composable
fun ProfileTab(
    insights: InsightsProfile,
    homeTeam: String,
    awayTeam: String,
) {
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
private fun StyleRadar(insights: InsightsProfile) {
    val hp = insights.homePassingStyle
    val ap = insights.awayPassingStyle
    val ha = insights.homeAerialEstimate
    val aa = insights.awayAerialEstimate
    val hg = insights.homeGoalkeepingEstimate
    val ag = insights.awayGoalkeepingEstimate
    if (hp == null || ap == null) return
    SectionCard("Style profile") {
        val axes =
            listOfNotNull(
                RadarAxis("Pass accuracy", (hp.passAccuracyPct ?: 0.0).toFloat(), (ap.passAccuracyPct ?: 0.0).toFloat(), maxValue = 100f),
                RadarAxis(
                    "Long-ball share",
                    (hp.longBallSharePct ?: 0.0).toFloat(),
                    (ap.longBallSharePct ?: 0.0).toFloat(),
                    maxValue = 25f,
                ),
                aerialAxis(ha, aa),
                goalkeepingAxis(hg, ag),
            )
        if (axes.size >= 3) {
            RadarChart(axes = axes, homeColor = AppTheme.colors.homeSeries, awayColor = AppTheme.colors.awaySeries)
        }
    }
}

private fun aerialAxis(
    ha: SeasonAerialEstimate?,
    aa: SeasonAerialEstimate?,
): RadarAxis? =
    if (ha != null &&
        aa != null
    ) {
        RadarAxis("Aerial duels won", ha.aerialDuelsWonFor.toFloat(), aa.aerialDuelsWonFor.toFloat(), maxValue = 60f)
    } else {
        null
    }

private fun goalkeepingAxis(
    hg: SeasonGoalkeepingEstimate?,
    ag: SeasonGoalkeepingEstimate?,
): RadarAxis? =
    if (hg != null &&
        ag != null
    ) {
        RadarAxis("Save %", (hg.savePct ?: 0.0).toFloat(), (ag.savePct ?: 0.0).toFloat(), maxValue = 100f)
    } else {
        null
    }

@Composable
private fun PassingSection(
    insights: InsightsProfile,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homePassingStyle == null && insights.awayPassingStyle == null) return
    SectionCard("Passing") {
        val hp = insights.homePassingStyle
        val ap = insights.awayPassingStyle
        if (hp?.passAccuracyPct != null && ap?.passAccuracyPct != null) {
            BarComparison(
                "Pass accuracy",
                hp.passAccuracyPct.toFloat(),
                ap.passAccuracyPct.toFloat(),
                AppTheme.colors.homeSeries,
                AppTheme.colors.awaySeries,
                "$homeTeam ${hp.passAccuracyPct}%",
                "$awayTeam ${ap.passAccuracyPct}%",
            )
            Spacer(Modifier.height(8.dp))
        }
        if (hp?.longBallSharePct != null && ap?.longBallSharePct != null) {
            BarComparison(
                "Long-ball share",
                hp.longBallSharePct.toFloat(),
                ap.longBallSharePct.toFloat(),
                AppTheme.colors.homeSeries,
                AppTheme.colors.awaySeries,
                "$homeTeam ${hp.longBallSharePct}%",
                "$awayTeam ${ap.longBallSharePct}%",
            )
        }
        if (hp?.passAccuracyPct == null || ap?.passAccuracyPct == null) {
            hp?.let { InfoRow(homeTeam, "${it.passAccuracyPct ?: "n/a"}% accuracy, ${it.longBallSharePct ?: "n/a"}% long balls") }
            ap?.let { InfoRow(awayTeam, "${it.passAccuracyPct ?: "n/a"}% accuracy, ${it.longBallSharePct ?: "n/a"}% long balls") }
        }
    }
}

@Composable
private fun AerialAndGoalkeepingSection(
    insights: InsightsProfile,
    homeTeam: String,
    awayTeam: String,
) {
    val ha = insights.homeAerialEstimate
    val aa = insights.awayAerialEstimate
    val hasGk = insights.homeGoalkeepingEstimate != null || insights.awayGoalkeepingEstimate != null
    if ((ha == null || aa == null) && !hasGk) return
    SectionCard("Aerial & goalkeeping") {
        // Direct null-check here (not a `hasAerial` boolean) so Kotlin can
        // smart-cast ha/aa to non-null -- previously used `ha!!`/`aa!!`
        // instead, which SonarQube (kotlin:S6619) flags as an avoidable
        // non-null assertion.
        if (ha != null && aa != null) {
            BarComparison(
                "Aerial duels won (last 10)",
                ha.aerialDuelsWonFor.toFloat(),
                aa.aerialDuelsWonFor.toFloat(),
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
private fun DefensiveErrorsSection(
    insights: InsightsProfile,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homeDefensiveErrorsEstimate == null && insights.awayDefensiveErrorsEstimate == null) return
    SectionCard("Defensive errors") {
        val h = insights.homeDefensiveErrorsEstimate
        val a = insights.awayDefensiveErrorsEstimate
        if (h != null && a != null) {
            BarComparison(
                "Defensive errors leading to a chance",
                h.defensiveErrorsFor.toFloat(),
                a.defensiveErrorsFor.toFloat(),
                AppTheme.colors.statusWarning,
                AppTheme.colors.statusWarning,
                "$homeTeam ${h.defensiveErrorsFor} for / ${h.defensiveErrorsAgainst} against",
                "$awayTeam ${a.defensiveErrorsFor} for / ${a.defensiveErrorsAgainst} against",
            )
        } else {
            h?.let {
                InfoRow(
                    homeTeam,
                    "${it.defensiveErrorsFor} for / ${it.defensiveErrorsAgainst} against",
                    valueColor = AppTheme.colors.statusWarning,
                )
            }
            a?.let {
                InfoRow(
                    awayTeam,
                    "${it.defensiveErrorsFor} for / ${it.defensiveErrorsAgainst} against",
                    valueColor = AppTheme.colors.statusWarning,
                )
            }
        }
    }
}

@Composable
private fun RiskSection(
    insights: InsightsProfile,
    homeTeam: String,
    awayTeam: String,
) {
    val hasDuel = !insights.homeDuelVulnerabilities.isNullOrEmpty() || !insights.awayDuelVulnerabilities.isNullOrEmpty()
    val hasFullback = !insights.homeFullbackExposure.isNullOrEmpty() || !insights.awayFullbackExposure.isNullOrEmpty()
    if (!hasDuel && !hasFullback) return
    SectionCard("Risk") {
        insights.homeDuelVulnerabilities?.takeIf { it.isNotEmpty() }?.let { list ->
            RiskPillGroup("$homeTeam duel risk", list.map { "${it.name} ${it.groundDuelSuccessPct}%" })
        }
        insights.awayDuelVulnerabilities?.takeIf { it.isNotEmpty() }?.let { list ->
            RiskPillGroup("$awayTeam duel risk", list.map { "${it.name} ${it.groundDuelSuccessPct}%" })
        }
        insights.homeFullbackExposure?.takeIf { it.isNotEmpty() }?.let { list ->
            RiskPillGroup("$homeTeam exposed fullbacks", list.map { it.name })
        }
        insights.awayFullbackExposure?.takeIf { it.isNotEmpty() }?.let { list ->
            RiskPillGroup("$awayTeam exposed fullbacks", list.map { it.name })
        }
    }
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun RiskPillGroup(
    label: String,
    items: List<String>,
) {
    Text(label, style = MaterialTheme.typography.labelMedium)
    Spacer(Modifier.height(6.dp))
    androidx.compose.foundation.layout.FlowRow(
        horizontalArrangement =
            androidx.compose.foundation.layout.Arrangement
                .spacedBy(6.dp),
        verticalArrangement =
            androidx.compose.foundation.layout.Arrangement
                .spacedBy(6.dp),
    ) {
        items.forEach { item ->
            OutlinedPill(text = item, borderColor = AppTheme.colors.statusWarning, contentColor = AppTheme.colors.statusWarning)
        }
    }
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun ThreatSection(
    insights: InsightsProfile,
    homeTeam: String,
    awayTeam: String,
) {
    val hasSetPiece = insights.homeSetPieceThreat != null || insights.awaySetPieceThreat != null
    val hasDirectPlay = insights.homeDirectPlayExposure != null || insights.awayDirectPlayExposure != null
    if (!hasSetPiece && !hasDirectPlay) return
    SectionCard("Set-piece & direct-play tendencies") {
        insights.homeSetPieceThreat?.let { t ->
            InfoRow(
                "$homeTeam set-piece threat",
                "${t.cornersPerGame ?: "n/a"} corners/game vs opp's ${t.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = elevatedColor(t.elevated, AppTheme.colors.statusGood),
            )
        }
        insights.awaySetPieceThreat?.let { t ->
            InfoRow(
                "$awayTeam set-piece threat",
                "${t.cornersPerGame ?: "n/a"} corners/game vs opp's ${t.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = elevatedColor(t.elevated, AppTheme.colors.statusGood),
            )
        }
        insights.homeDirectPlayExposure?.let { d ->
            InfoRow(
                "$homeTeam direct-play exposure",
                "${d.longBallSharePct ?: "n/a"}% long balls vs opp's ${d.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = elevatedColor(d.elevated, AppTheme.colors.statusWarning),
            )
        }
        insights.awayDirectPlayExposure?.let { d ->
            InfoRow(
                "$awayTeam direct-play exposure",
                "${d.longBallSharePct ?: "n/a"}% long balls vs opp's ${d.opponentAerialWinPct ?: "n/a"}% aerial win",
                valueColor = elevatedColor(d.elevated, AppTheme.colors.statusWarning),
            )
        }
    }
}

private fun elevatedColor(
    elevated: Boolean,
    colorWhenElevated: Color,
): Color = if (elevated) colorWhenElevated else Color.Unspecified
