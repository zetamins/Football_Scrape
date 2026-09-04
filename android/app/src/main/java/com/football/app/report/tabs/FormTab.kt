package com.football.app.report.tabs

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import com.football.app.charts.FormGuideStrip
import com.football.app.charts.LineTrend
import com.football.app.charts.Segment
import com.football.app.charts.SegmentedBar
import com.football.app.components.InfoRow
import com.football.app.components.OutlinedPill
import com.football.app.components.PillFlow
import com.football.app.components.SectionCard
import com.football.app.data.model.FormSummary
import com.football.app.ui.theme.AppTheme

/**
 * frontend/DESIGN.md's Form tab, rendered once per team (called twice --
 * for the searched team and its opponent, same shape either way).
 */
@Composable
fun FormTab(
    form: FormSummary,
    opponentForm: FormSummary,
    teamLabel: String,
    opponentLabel: String,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        Text(teamLabel, style = MaterialTheme.typography.titleMedium)
        OneTeamForm(form)
        Spacer(Modifier.height(16.dp))
        Text(opponentLabel, style = MaterialTheme.typography.titleMedium)
        OneTeamForm(opponentForm)
    }
}

@Composable
private fun OneTeamForm(form: FormSummary) {
    StreakSection(form)
    RatesSection(form)
    OverUnderSection(form)
    XgTrendSection(form)
    VenueSplitSection(form)
    CongestionSection(form)
    NextFixturesSection(form)
}

@Composable
private fun StreakSection(form: FormSummary) {
    if (form.currentStreak == null && form.last10Overall.isEmpty()) return
    SectionCard("Streak & momentum") {
        if (form.last10Overall.isNotEmpty()) {
            FormGuideStrip(form.last10Overall.map { it.result })
            Spacer(Modifier.height(8.dp))
        }
        form.currentStreak?.let { s -> InfoRow("Streak", "${s.count}-game ${streakWord(s.result)}") }
        form.momentum?.let { m ->
            InfoRow(
                "Momentum",
                "${m.recentPpg} ppg (last 3) vs ${m.priorPpg} ppg (prior 3) -- ${m.trend}",
                valueColor = momentumColor(m.trend),
            )
        }
        if (form.cleanSheetStreak != null && form.cleanSheetStreak >= 2) {
            InfoRow("Clean sheets", "${form.cleanSheetStreak}-game streak", valueColor = AppTheme.colors.statusGood)
        }
        if (form.scorelessStreak != null && form.scorelessStreak >= 2) {
            InfoRow("Scoreless", "${form.scorelessStreak}-game streak", valueColor = AppTheme.colors.statusCritical)
        }
    }
}

private fun streakWord(result: String): String =
    when (result) {
        "W" -> "winning"
        "L" -> "losing"
        else -> "drawing"
    }

@Composable
private fun momentumColor(trend: String): Color =
    when (trend) {
        "improving" -> AppTheme.colors.statusGood
        "declining" -> AppTheme.colors.statusCritical
        else -> Color.Unspecified
    }

@Composable
private fun RatesSection(form: FormSummary) {
    val hasRates = form.winRatePct != null || form.pointsPerGame != null
    if (!hasRates) return
    SectionCard("Rates (last 10)") {
        if (form.winRatePct != null && form.drawRatePct != null && form.lossRatePct != null) {
            SegmentedBar(
                segments =
                    listOf(
                        Segment(form.winRatePct.toFloat(), AppTheme.colors.statusGood),
                        Segment(form.drawRatePct.toFloat(), AppTheme.colors.neutral),
                        Segment(form.lossRatePct.toFloat(), AppTheme.colors.statusCritical),
                    ),
            )
            Spacer(Modifier.height(4.dp))
        }
        InfoRow(
            "W/D/L",
            "W${form.winRatePct ?: "n/a"}%/D${form.drawRatePct ?: "n/a"}%/L${form.lossRatePct ?: "n/a"}%, " +
                "${form.pointsPerGame ?: "n/a"} ppg, ${form.goalsForPerGame ?: "n/a"}-${form.goalsAgainstPerGame ?: "n/a"} goals/game",
        )
        form.homeWinRatePct?.let { h -> InfoRow("Win rate", "home $h% / away ${form.awayWinRatePct ?: "n/a"}%") }
        form.narrowWinSharePct?.let { InfoRow("Narrow wins", "$it% of last 10 wins") }
        form.scoringDrawSharePct?.let { InfoRow("Scoring draws", "$it% of last 10 draws") }
        form.bttsSharePct?.let { InfoRow("BTTS rate", "$it%") }
        form.halfSplit?.let { h ->
            InfoRow(
                "Half split",
                "1H ${h.firstHalfGoalsFor}-${h.firstHalfGoalsAgainst}, 2H ${h.secondHalfGoalsFor}-${h.secondHalfGoalsAgainst}",
            )
        }
    }
}

@Composable
private fun OverUnderSection(form: FormSummary) {
    if (form.over25SharePct == null && form.cleanSheetSharePct == null) return
    SectionCard("Over/under & clean sheets") {
        if (form.over15SharePct != null && form.over25SharePct != null && form.over35SharePct != null) {
            InfoRow("Over/under (last 10)", "O1.5 ${form.over15SharePct}% / O2.5 ${form.over25SharePct}% / O3.5 ${form.over35SharePct}%")
        }
        if (form.cleanSheetSharePct != null && form.failedToScoreSharePct != null) {
            InfoRow("CS% / FTS%", "${form.cleanSheetSharePct}% / ${form.failedToScoreSharePct}%")
        }
    }
}

@Composable
private fun XgTrendSection(form: FormSummary) {
    val withXg = form.last10Overall.filter { it.xgFor != null && it.xgAgainst != null }
    if (withXg.size < 2) return
    SectionCard("xG per match (recent, oldest to newest)") {
        val reversed = withXg.reversed() // most-recent-first list -> chronological for the chart
        LineTrend(
            forValues = reversed.map { it.xgFor!!.toFloat() },
            againstValues = reversed.map { it.xgAgainst!!.toFloat() },
        )
    }
}

@Composable
private fun VenueSplitSection(form: FormSummary) {
    val v = form.venueSplitForm ?: return
    SectionCard("True venue split") {
        InfoRow(
            "Home",
            "${v.homeWins}W-${v.homeDraws}D-${v.homeLosses}L, ${v.homeGoalsFor}-${v.homeGoalsAgainst} (n=${v.homeSampleSize})",
        )
        InfoRow(
            "Away",
            "${v.awayWins}W-${v.awayDraws}D-${v.awayLosses}L, ${v.awayGoalsFor}-${v.awayGoalsAgainst} (n=${v.awaySampleSize})",
        )
        if (v.neutralSampleSize > 0) {
            InfoRow(
                "Neutral",
                "${v.neutralWins}W-${v.neutralDraws}D-${v.neutralLosses}L, ${v.neutralGoalsFor}-${v.neutralGoalsAgainst} (n=${v.neutralSampleSize})",
            )
        }
        form.detailedVenueSplit?.let { d ->
            fun bucketStr(b: com.football.app.data.model.VenueSplitStats): String {
                if (b.sampleSize == 0) return "n=0"

                fun per(n: Number) = "%.1f".format(n.toDouble() / b.sampleSize)
                return "xG ${per(
                    b.xgFor,
                )}-${per(b.xgAgainst)}/g, shots ${per(b.shotsFor)}-${per(b.shotsAgainst)}/g, poss ${b.possessionPctAvg ?: "n/a"}%"
            }
            InfoRow("Home detail", bucketStr(d.home))
            InfoRow("Away detail", bucketStr(d.away))
        }
    }
}

@Composable
private fun CongestionSection(form: FormSummary) {
    SectionCard("Congestion & competitions") {
        InfoRow(
            "Fixture congestion",
            "${form.matchesLast7Days} in last 7d, ${form.matchesLast14Days} in last 14d",
            valueColor = if (form.matchesLast7Days >= 3) AppTheme.colors.statusWarning else Color.Unspecified,
        )
        if (form.gapsBetweenLastThree.isNotEmpty()) {
            InfoRow("Fixture gaps", "${form.gapsBetweenLastThree.joinToString(", ")} days")
        }
        if (form.recentCompetitions.size > 1) {
            Text("Competitions", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(6.dp))
            PillFlow {
                form.recentCompetitions.forEach { c ->
                    OutlinedPill(
                        text = c,
                        borderColor = MaterialTheme.colorScheme.outline,
                        contentColor = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        if (form.formByCompetition.size > 1) {
            Text("Form by competition", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(6.dp))
            form.formByCompetition.forEach { c ->
                Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                    Text(c.competition, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    Text("${c.wins}W-${c.draws}D-${c.losses}L, ${c.goalsFor}-${c.goalsAgainst}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
private fun NextFixturesSection(form: FormSummary) {
    if (form.next5WithGaps.isEmpty()) return
    SectionCard("Upcoming fixtures") {
        form.next5WithGaps.forEach { f ->
            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                Text(
                    "${f.opponent}${f.date?.let { " -- ${it.take(10)}" } ?: ""}",
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}
