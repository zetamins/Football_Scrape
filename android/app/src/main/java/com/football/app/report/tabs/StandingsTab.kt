package com.football.app.report.tabs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.football.app.charts.BarComparison
import com.football.app.components.InfoRow
import com.football.app.components.SectionCard
import com.football.app.data.model.InsightsStandings
import com.football.app.data.model.StandingsTableRow
import com.football.app.ui.theme.AppTheme

/** frontend/DESIGN.md's Standings tab. */
@Composable
fun StandingsTab(
    insights: InsightsStandings,
    standingsTable: List<StandingsTableRow>?,
    homeTeam: String,
    awayTeam: String,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        StrengthSection(insights, homeTeam, awayTeam)
        ZoneSection(insights, homeTeam, awayTeam)
        ImpactSection(insights, homeTeam, awayTeam)
        AdvantageSection(insights, homeTeam, awayTeam)
        OpponentRankSection(insights, homeTeam, awayTeam)
        FullTableSection(standingsTable)
    }
}

@Composable
private fun StrengthSection(
    insights: InsightsStandings,
    homeTeam: String,
    awayTeam: String,
) {
    val he = insights.homeEloRating
    val ae = insights.awayEloRating
    val hc = insights.homeClubStrength
    val ac = insights.awayClubStrength
    if (he == null && hc == null) return
    SectionCard("Strength ratings") {
        if (he != null && ae != null) {
            BarComparison(
                "Elo rating (clubelo.com)",
                he.elo.toFloat(),
                ae.elo.toFloat(),
                AppTheme.colors.homeSeries,
                AppTheme.colors.awaySeries,
                "$homeTeam ${he.elo}${he.rank?.let { " (#$it world)" } ?: ""}",
                "$awayTeam ${ae.elo}${ae.rank?.let { " (#$it world)" } ?: ""}",
            )
            Spacer(Modifier.height(8.dp))
        }
        if (hc != null && ac != null) {
            BarComparison(
                "Overall strength (statsultra.com)",
                hc.overall.toFloat(),
                ac.overall.toFloat(),
                AppTheme.colors.homeSeries,
                AppTheme.colors.awaySeries,
                "$homeTeam ${hc.overall}",
                "$awayTeam ${ac.overall}",
            )
            Spacer(Modifier.height(8.dp))
            BarComparison(
                "Attack rating",
                hc.attack.toFloat(),
                ac.attack.toFloat(),
                AppTheme.colors.homeSeries,
                AppTheme.colors.awaySeries,
                "$homeTeam ${hc.attack}",
                "$awayTeam ${ac.attack}",
            )
            Spacer(Modifier.height(8.dp))
            BarComparison(
                "Defense rating",
                hc.defense.toFloat(),
                ac.defense.toFloat(),
                AppTheme.colors.homeSeries,
                AppTheme.colors.awaySeries,
                "$homeTeam ${hc.defense}",
                "$awayTeam ${ac.defense}",
            )
        }
    }
}

@Composable
private fun ZoneSection(
    insights: InsightsStandings,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homeStandingsZone == null && insights.awayStandingsZone == null) return
    SectionCard("Table position") {
        insights.homeStandingsZone?.let { z ->
            InfoRow(
                homeTeam,
                "#${z.position}/${z.totalTeams} (${z.zone})${z.pointsFromBoundary?.let {
                    ", ${it}pts from boundary"
                } ?: ""}${if (z.inTheMix == true) " -- in the mix" else ""}",
            )
        }
        insights.awayStandingsZone?.let { z ->
            InfoRow(
                awayTeam,
                "#${z.position}/${z.totalTeams} (${z.zone})${z.pointsFromBoundary?.let {
                    ", ${it}pts from boundary"
                } ?: ""}${if (z.inTheMix == true) " -- in the mix" else ""}",
            )
        }
    }
}

@Composable
private fun ImpactSection(
    insights: InsightsStandings,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homeStandingsImpact == null && insights.awayStandingsImpact == null) return
    SectionCard("If this match ends in...") {
        insights.homeStandingsImpact?.let { s ->
            InfoRow(homeTeam, s.scenarios.joinToString(", ") { "${it.outcome}: #${it.newPosition ?: "?"}" })
        }
        insights.awayStandingsImpact?.let { s ->
            InfoRow(awayTeam, s.scenarios.joinToString(", ") { "${it.outcome}: #${it.newPosition ?: "?"}" })
        }
    }
}

@Composable
private fun AdvantageSection(
    insights: InsightsStandings,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homeAdvantage == null && insights.awayAdvantage == null) return
    SectionCard("Home advantage") {
        insights.homeAdvantage?.let { a ->
            InfoRow(homeTeam, "${a.strength ?: "n/a"} (home ${a.homeWinRatePct ?: "n/a"}% / away ${a.awayWinRatePct ?: "n/a"}%)")
        }
        insights.awayAdvantage?.let { a ->
            InfoRow(awayTeam, "${a.strength ?: "n/a"} (home ${a.homeWinRatePct ?: "n/a"}% / away ${a.awayWinRatePct ?: "n/a"}%)")
        }
    }
}

@Composable
private fun OpponentRankSection(
    insights: InsightsStandings,
    homeTeam: String,
    awayTeam: String,
) {
    if (insights.homeOpponentRankRecord == null && insights.awayOpponentRankRecord == null) return
    SectionCard("Record vs higher-ranked opponents") {
        insights.homeOpponentRankRecord?.let { r ->
            InfoRow(homeTeam, "${r.wins}W-${r.draws}D-${r.losses}L")
        }
        insights.awayOpponentRankRecord?.let { r ->
            InfoRow(awayTeam, "${r.wins}W-${r.draws}D-${r.losses}L")
        }
    }
}

@Composable
private fun FullTableSection(rows: List<StandingsTableRow>?) {
    if (rows.isNullOrEmpty()) return
    SectionCard("League table") {
        rows.forEach { row ->
            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("#${row.position} ${row.teamName}", style = MaterialTheme.typography.bodyMedium)
                Text("${row.points} pts", style = MaterialTheme.typography.bodyMedium)
            }
            HorizontalDivider()
        }
    }
}
