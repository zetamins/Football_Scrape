package com.football.app.report.tabs

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.football.app.charts.BarComparison
import com.football.app.components.InfoRow
import com.football.app.components.OutlinedPill
import com.football.app.components.PillFlow
import com.football.app.components.SectionCard
import com.football.app.data.model.CardDisciplineInfo
import com.football.app.data.model.InsightsDiscipline
import com.football.app.ui.theme.AppTheme

/** frontend/DESIGN.md's Discipline tab. */
@Composable
fun DisciplineTab(
    insights: InsightsDiscipline,
    homeTeam: String,
    awayTeam: String,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        CardsSection(insights, homeTeam, awayTeam)
        FoulsAndCornersSection(insights, homeTeam, awayTeam)
        MatchedSampleSection(insights, homeTeam, awayTeam)
        CardRisksSection(insights, homeTeam, awayTeam)
        RefereeNoteSection(insights)
    }
}

@Composable
private fun CardsSection(
    insights: InsightsDiscipline,
    homeTeam: String,
    awayTeam: String,
) {
    val home = insights.homeCardDiscipline
    val away = insights.awayCardDiscipline
    if (home == null && away == null) return
    SectionCard("Cards per game") {
        if (home != null && away != null) {
            BothTeamsCardRows(homeTeam, awayTeam, home, away)
        } else {
            home?.let { SingleTeamCardRow(homeTeam, it) }
            away?.let { SingleTeamCardRow(awayTeam, it) }
        }
        insights.homeCardDisciplineVenueSplit?.let { s ->
            Spacer(Modifier.height(8.dp))
            InfoRow(
                "$homeTeam by venue",
                "at home ${s.atHomeYellowPerGame ?: "n/a"}Y (n=${s.atHomeSampleSize}) / away ${s.awayYellowPerGame ?: "n/a"}Y (n=${s.awaySampleSize})",
            )
        }
        insights.awayCardDisciplineVenueSplit?.let { s ->
            InfoRow(
                "$awayTeam by venue",
                "at home ${s.atHomeYellowPerGame ?: "n/a"}Y (n=${s.atHomeSampleSize}) / away ${s.awayYellowPerGame ?: "n/a"}Y (n=${s.awaySampleSize})",
            )
        }
    }
}

/** Both teams' card rows, shown when both sides have card-discipline data. */
@Composable
private fun BothTeamsCardRows(
    homeTeam: String,
    awayTeam: String,
    home: CardDisciplineInfo,
    away: CardDisciplineInfo,
) {
    BarComparison(
        "Yellow cards per game",
        home.yellowPerGame.toFloat(),
        away.yellowPerGame.toFloat(),
        AppTheme.colors.homeSeries,
        AppTheme.colors.awaySeries,
        "$homeTeam ${home.yellowPerGame}",
        "$awayTeam ${away.yellowPerGame}",
    )
    if (home.elevatedRisk || away.elevatedRisk) {
        Spacer(Modifier.height(6.dp))
        val flagged = listOfNotNull(homeTeam.takeIf { home.elevatedRisk }, awayTeam.takeIf { away.elevatedRisk })
        InfoRow("Elevated card risk", flagged.joinToString(", "), valueColor = AppTheme.colors.statusWarning)
    }
    Spacer(Modifier.height(8.dp))
    BarComparison(
        "Red cards per game",
        home.redPerGame.toFloat(),
        away.redPerGame.toFloat(),
        AppTheme.colors.homeSeries,
        AppTheme.colors.awaySeries,
        "$homeTeam ${home.redPerGame}",
        "$awayTeam ${away.redPerGame}",
    )
}

/** Fallback when only one side has card-discipline data. */
@Composable
private fun SingleTeamCardRow(
    team: String,
    discipline: CardDisciplineInfo,
) {
    InfoRow(
        team,
        "${discipline.yellowPerGame}Y / ${discipline.redPerGame}R per game",
        valueColor = if (discipline.elevatedRisk) AppTheme.colors.statusWarning else Color.Unspecified,
    )
}

@Composable
private fun FoulsAndCornersSection(
    insights: InsightsDiscipline,
    homeTeam: String,
    awayTeam: String,
) {
    val h = insights.homeFoulsEstimate
    val a = insights.awayFoulsEstimate
    if (h == null || a == null) return
    SectionCard("Fouls (last 10)") {
        BarComparison(
            "Fouls committed",
            h.foulsCommittedFor.toFloat(),
            a.foulsCommittedFor.toFloat(),
            AppTheme.colors.homeSeries,
            AppTheme.colors.awaySeries,
            "$homeTeam ${h.foulsCommittedFor}",
            "$awayTeam ${a.foulsCommittedFor}",
        )
        insights.homeCornersEstimate?.let { hc ->
            Spacer(Modifier.height(8.dp))
            InfoRow("$homeTeam corners for/against", "${hc.cornersFor} / ${hc.cornersAgainst}")
        }
        insights.awayCornersEstimate?.let { ac ->
            InfoRow("$awayTeam corners for/against", "${ac.cornersFor} / ${ac.cornersAgainst}")
        }
    }
}

@Composable
private fun MatchedSampleSection(
    insights: InsightsDiscipline,
    homeTeam: String,
    awayTeam: String,
) {
    val h = insights.homeAdvancedStats
    val a = insights.awayAdvancedStats
    if (h == null || a == null) return
    SectionCard("Matched sample (sofascore)") {
        AdvancedStatBar(
            "Yellow cards",
            h.yellowCardsFor, a.yellowCardsFor,
            homeTeam, awayTeam,
        )
        Spacer(Modifier.height(8.dp))
        AdvancedStatBar(
            "Red cards",
            h.redCardsFor, a.redCardsFor,
            homeTeam, awayTeam,
        )
        Spacer(Modifier.height(8.dp))
        AdvancedStatBar(
            "Fouls",
            h.foulsFor, a.foulsFor,
            homeTeam, awayTeam,
        )
        Spacer(Modifier.height(8.dp))
        InfoRow(
            "$homeTeam penalties conceded",
            "${h.penaltyGoalsAgainst} scored against, ${h.penaltiesAwardedAgainst} awarded to opponent",
            valueColor = if (h.penaltiesAwardedAgainst > 0) AppTheme.colors.statusWarning else Color.Unspecified,
        )
        InfoRow(
            "$awayTeam penalties conceded",
            "${a.penaltyGoalsAgainst} scored against, ${a.penaltiesAwardedAgainst} awarded to opponent",
            valueColor = if (a.penaltiesAwardedAgainst > 0) AppTheme.colors.statusWarning else Color.Unspecified,
        )
    }
}

/** Bar for a nullable advanced-stat pair -- null means this source never
 * reported the stat, so show n/a instead of a fabricated 0 bar. */
@Composable
private fun AdvancedStatBar(
    label: String,
    home: Int?,
    away: Int?,
    homeTeam: String,
    awayTeam: String,
) {
    if (home == null || away == null) {
        InfoRow(label, "n/a (${homeTeam} ${home ?: "n/a"} / ${awayTeam} ${away ?: "n/a"})")
        return
    }
    BarComparison(
        label,
        home.toFloat(),
        away.toFloat(),
        AppTheme.colors.homeSeries,
        AppTheme.colors.awaySeries,
        "$homeTeam $home",
        "$awayTeam $away",
    )
}

@Composable
private fun CardRisksSection(
    insights: InsightsDiscipline,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homeCardRisks.isNullOrEmpty() && insights.awayCardRisks.isNullOrEmpty()) return
    SectionCard("Card risk") {
        insights.homeCardRisks?.takeIf { it.isNotEmpty() }?.let { risks -> CardRiskPills(homeTeam, risks) }
        insights.awayCardRisks?.takeIf { it.isNotEmpty() }?.let { risks -> CardRiskPills(awayTeam, risks) }
    }
}

@Composable
private fun CardRiskPills(
    team: String,
    risks: List<com.football.app.data.model.PlayerCardRisk>,
) {
    Text("$team players", style = MaterialTheme.typography.labelMedium)
    Spacer(Modifier.height(6.dp))
    PillFlow {
        risks.forEach { p ->
            OutlinedPill(
                text = "${p.name} ${p.yellowCards}Y${if (p.redCards > 0) "/${p.redCards}R" else ""}",
                borderColor = AppTheme.colors.statusWarning,
                contentColor = AppTheme.colors.statusWarning,
            )
        }
    }
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun RefereeNoteSection(insights: InsightsDiscipline) {
    val note = insights.refereeCardRiskNote ?: return
    SectionCard("Referee ${note.refereeName}") {
        InfoRow(
            "Yellow cards per game",
            "${note.yellowCardsPerGame}",
            valueColor = if (note.elevatedCardReferee) AppTheme.colors.statusWarning else Color.Unspecified,
        )
        if (note.flaggedPlayers.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text("Flagged players", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(6.dp))
            PillFlow {
                note.flaggedPlayers.forEach { p ->
                    OutlinedPill(text = p.name, borderColor = AppTheme.colors.statusWarning, contentColor = AppTheme.colors.statusWarning)
                }
            }
        }
    }
}
