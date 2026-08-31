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
import com.football.app.components.InfoRow
import com.football.app.data.model.InsightsDiscipline
import com.football.app.ui.theme.AppTheme

/** frontend/DESIGN.md's Discipline tab. */
@Composable
fun DisciplineTab(insights: InsightsDiscipline, homeTeam: String, awayTeam: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        CardsSection(insights, homeTeam, awayTeam)
        FoulsAndCornersSection(insights, homeTeam, awayTeam)
        MatchedSampleSection(insights, homeTeam, awayTeam)
        CardRisksSection(insights, homeTeam, awayTeam)
        RefereeNoteSection(insights)
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
private fun CardsSection(insights: InsightsDiscipline, homeTeam: String, awayTeam: String) {
    if (insights.homeCardDiscipline == null && insights.awayCardDiscipline == null) return
    SectionCard("Cards per game") {
        insights.homeCardDiscipline?.let { c ->
            InfoRow(
                homeTeam,
                "${c.yellowPerGame}Y / ${c.redPerGame}R per game",
                valueColor = if (c.elevatedRisk) AppTheme.colors.statusWarning else Color.Unspecified,
            )
        }
        insights.awayCardDiscipline?.let { c ->
            InfoRow(
                awayTeam,
                "${c.yellowPerGame}Y / ${c.redPerGame}R per game",
                valueColor = if (c.elevatedRisk) AppTheme.colors.statusWarning else Color.Unspecified,
            )
        }
        insights.homeCardDisciplineVenueSplit?.let { s ->
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

@Composable
private fun FoulsAndCornersSection(insights: InsightsDiscipline, homeTeam: String, awayTeam: String) {
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
private fun MatchedSampleSection(insights: InsightsDiscipline, homeTeam: String, awayTeam: String) {
    val h = insights.homeAdvancedStats
    val a = insights.awayAdvancedStats
    if (h == null || a == null) return
    SectionCard("Matched sample (sofascore)") {
        BarComparison("Yellow cards", h.yellowCardsFor.toFloat(), a.yellowCardsFor.toFloat(), AppTheme.colors.homeSeries, AppTheme.colors.awaySeries, "$homeTeam ${h.yellowCardsFor}", "$awayTeam ${a.yellowCardsFor}")
        Spacer(Modifier.height(8.dp))
        BarComparison("Red cards", h.redCardsFor.toFloat(), a.redCardsFor.toFloat(), AppTheme.colors.homeSeries, AppTheme.colors.awaySeries, "$homeTeam ${h.redCardsFor}", "$awayTeam ${a.redCardsFor}")
        Spacer(Modifier.height(8.dp))
        BarComparison("Fouls", h.foulsFor.toFloat(), a.foulsFor.toFloat(), AppTheme.colors.homeSeries, AppTheme.colors.awaySeries, "$homeTeam ${h.foulsFor}", "$awayTeam ${a.foulsFor}")
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

@Composable
private fun CardRisksSection(insights: InsightsDiscipline, homeTeam: String, awayTeam: String) {
    if (insights.homeCardRisks.isNullOrEmpty() && insights.awayCardRisks.isNullOrEmpty()) return
    SectionCard("Card risk") {
        insights.homeCardRisks?.takeIf { it.isNotEmpty() }?.let { risks ->
            InfoRow(
                "$homeTeam players",
                risks.joinToString(", ") { "${it.name} (${it.yellowCards}Y${if (it.redCards > 0) "/${it.redCards}R" else ""})" },
                valueColor = AppTheme.colors.statusWarning,
            )
        }
        insights.awayCardRisks?.takeIf { it.isNotEmpty() }?.let { risks ->
            InfoRow(
                "$awayTeam players",
                risks.joinToString(", ") { "${it.name} (${it.yellowCards}Y${if (it.redCards > 0) "/${it.redCards}R" else ""})" },
                valueColor = AppTheme.colors.statusWarning,
            )
        }
    }
}

@Composable
private fun RefereeNoteSection(insights: InsightsDiscipline) {
    val note = insights.refereeCardRiskNote ?: return
    SectionCard("Referee ${note.refereeName}") {
        InfoRow(
            "Yellow cards per game",
            "${note.yellowCardsPerGame}${if (note.flaggedPlayers.isNotEmpty()) " -- flags " + note.flaggedPlayers.joinToString(", ") { it.name } else ""}",
            valueColor = if (note.elevatedCardReferee) AppTheme.colors.statusWarning else Color.Unspecified,
        )
    }
}
