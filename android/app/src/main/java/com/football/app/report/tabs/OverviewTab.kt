package com.football.app.report.tabs

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.football.app.charts.Segment
import com.football.app.charts.SegmentedBar
import com.football.app.components.InfoRow
import com.football.app.data.model.HeadToHeadSummary
import com.football.app.data.model.MatchOverview
import com.football.app.data.model.VenueDetails
import com.football.app.ui.theme.AppTheme

/**
 * frontend/DESIGN.md's Overview tab. Every block below checks its own
 * backing field(s) and emits nothing if absent (the doc's resolved
 * null-handling convention) -- there's no single "is this tab empty"
 * check, the tab is just naturally empty if every block below is.
 *
 * Betting odds' implied win/draw/win percentages are deliberately NOT
 * re-rendered here as a second segmented bar -- insights.prediction's
 * market_implied (already shown in PredictionHero, above every tab) is
 * computed from these same odds, so repeating it here would just be the
 * same three numbers twice. The raw decimal odds themselves (not implied
 * %) are shown instead, since those aren't shown anywhere else.
 */
@Composable
fun OverviewTab(overview: MatchOverview, venueDetails: VenueDetails?, homeTeam: String, awayTeam: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        MatchInfoSection(overview)
        VenueSection(overview, venueDetails)
        WeatherSection(overview)
        RefereeSection(overview)
        ManagersSection(overview, homeTeam, awayTeam)
        StandingsSection(overview, homeTeam, awayTeam)
        HeadToHeadSection(overview, homeTeam, awayTeam)
        OddsSection(overview)
        NotesSection(overview)
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
private fun MatchInfoSection(overview: MatchOverview) {
    if (overview.kickoffUtc == null && overview.round == null && overview.season == null) return
    SectionCard("Match") {
        overview.kickoffUtc?.let { InfoRow("Kickoff", "${it.replace("T", " ").take(16)} UTC") }
        val roundSeason = listOfNotNull(overview.round?.let { "Round $it" }, overview.season).joinToString(" -- ")
        if (roundSeason.isNotEmpty()) InfoRow("Competition", roundSeason)
    }
}

@Composable
private fun VenueSection(overview: MatchOverview, venueDetails: VenueDetails?) {
    if (overview.venueName == null && overview.venueCity == null && venueDetails == null) return
    SectionCard("Venue") {
        val location = listOfNotNull(overview.venueName, overview.venueCity, overview.venueCountry).joinToString(", ")
        if (location.isNotEmpty()) InfoRow("Location", location)
        overview.venueCapacity?.let { InfoRow("Capacity", "%,d".format(it)) }
        venueDetails?.let { v ->
            v.address?.let { InfoRow("Address", it) }
            val built = listOfNotNull(v.opened?.let { "opened $it" }, v.renovated?.let { "renovated $it" })
            if (built.isNotEmpty()) InfoRow("Built", built.joinToString(", "))
            v.architect?.let { InfoRow("Architect", it) }
            v.recordAttendance?.let { InfoRow("Record attendance", it) }
            v.clubs?.takeIf { it.size > 1 }?.let { InfoRow("Shared by", it.joinToString(", ")) }
        }
    }
}

@Composable
private fun WeatherSection(overview: MatchOverview) {
    if (overview.weather == null && overview.weatherDetail == null) return
    SectionCard("Weather") {
        overview.weather?.let { InfoRow("Conditions", it) }
        overview.weatherDetail?.let { w ->
            val parts = listOfNotNull(
                w.humidityPct?.let { "humidity ${it.toInt()}%" },
                w.windSpeedKmph?.let { "wind ${it.toInt()} km/h" },
                w.windGustKmph?.let { "gusts ${it.toInt()} km/h" },
                w.precipMm?.let { "precip ${it} mm" },
                w.chanceOfRainPct?.let { "${it.toInt()}% rain chance" },
            )
            if (parts.isNotEmpty()) InfoRow("Detail", parts.joinToString(", "))
        }
    }
}

@Composable
private fun RefereeSection(overview: MatchOverview) {
    if (overview.referee == null) return
    SectionCard("Referee") {
        InfoRow("Name", overview.referee)
        overview.refereeStats?.let { stats ->
            val parts = mutableListOf("${stats.yellowCardsPerGame} yellow/game", "${stats.games} games")
            stats.foulsPerGame?.let { parts.add("$it fouls/game") }
            stats.penaltiesAwarded?.let { parts.add("$it penalties this season") }
            InfoRow("Discipline", parts.joinToString(", "))
            stats.homeAwayBias?.let { bias ->
                InfoRow(
                    "Home/away card bias",
                    "home ${bias.homeCardsPerGame} vs away ${bias.awayCardsPerGame} cards/game (n=${bias.sampleSize})",
                    valueColor = if (bias.awayCardsPerGame > bias.homeCardsPerGame) AppTheme.colors.statusWarning else Color.Unspecified,
                )
            }
        }
    }
}

@Composable
private fun ManagersSection(overview: MatchOverview, homeTeam: String, awayTeam: String) {
    if (overview.homeManager == null && overview.awayManager == null) return
    SectionCard("Managers") {
        overview.homeManager?.let { m ->
            val tenure = m.recordAtClub?.let { r -> ", ${r.wins}W-${r.draws}D-${r.losses}L at club" } ?: ""
            val recent = if (m.recentAppointment == true) " (recent appointment)" else ""
            InfoRow(homeTeam, "${m.name}${m.country?.let { " ($it)" } ?: ""}$tenure$recent")
        }
        overview.awayManager?.let { m ->
            val tenure = m.recordAtClub?.let { r -> ", ${r.wins}W-${r.draws}D-${r.losses}L at club" } ?: ""
            val recent = if (m.recentAppointment == true) " (recent appointment)" else ""
            InfoRow(awayTeam, "${m.name}${m.country?.let { " ($it)" } ?: ""}$tenure$recent")
        }
        overview.managerDuel?.let { duel ->
            if (duel.homeWins + duel.awayWins + duel.draws > 0) {
                InfoRow("Head-to-head as managers", "${duel.homeWins}W-${duel.draws}D-${duel.awayWins}L")
            }
        }
    }
}

@Composable
private fun StandingsSection(overview: MatchOverview, homeTeam: String, awayTeam: String) {
    if (overview.homeTeamStanding == null && overview.awayTeamStanding == null) return
    SectionCard("Standings") {
        overview.homeTeamStanding?.let { s ->
            InfoRow(homeTeam, "#${s.position}${s.totalTeams?.let { "/$it" } ?: ""} (${s.points}pts, ${s.wins}W-${s.draws}D-${s.losses}L, GD ${s.goalDiff})")
        }
        overview.awayTeamStanding?.let { s ->
            InfoRow(awayTeam, "#${s.position}${s.totalTeams?.let { "/$it" } ?: ""} (${s.points}pts, ${s.wins}W-${s.draws}D-${s.losses}L, GD ${s.goalDiff})")
        }
    }
}

@Composable
private fun HeadToHeadSection(overview: MatchOverview, homeTeam: String, awayTeam: String) {
    val summary = overview.headToHeadSummary ?: return
    SectionCard("Head-to-head") {
        H2HBar(summary, homeTeam, awayTeam)
        overview.headToHeadStreaks?.takeIf { it.isNotEmpty() }?.let {
            Spacer(Modifier.height(8.dp))
            InfoRow("Streaks", it.joinToString("; "))
        }
        overview.recentMeetings?.takeIf { it.isNotEmpty() }?.let { meetings ->
            Spacer(Modifier.height(8.dp))
            Text("Recent meetings", style = MaterialTheme.typography.labelMedium)
            meetings.forEach { m ->
                val formations = if (m.homeFormation != null && m.awayFormation != null) " (${m.homeFormation} v ${m.awayFormation})" else ""
                val xg = if (m.homeXg != null && m.awayXg != null) ", xG ${m.homeXg}-${m.awayXg}" else ""
                Text(
                    "${m.date?.take(10) ?: "?"} ${m.scoreline}$formations$xg",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun H2HBar(summary: HeadToHeadSummary, homeTeam: String, awayTeam: String) {
    SegmentedBar(
        segments = listOf(
            Segment(summary.homeWins.toFloat(), AppTheme.colors.homeSeries),
            Segment(summary.draws.toFloat(), AppTheme.colors.neutral),
            Segment(summary.awayWins.toFloat(), AppTheme.colors.awaySeries),
        ),
    )
    Spacer(Modifier.height(4.dp))
    Row(modifier = Modifier.fillMaxWidth()) {
        Text("$homeTeam ${summary.homeWins}W", modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
        Text("${summary.draws}D", modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
        Text("$awayTeam ${summary.awayWins}W", modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.End)
    }
}

@Composable
private fun OddsSection(overview: MatchOverview) {
    val odds = overview.bettingOdds ?: return
    SectionCard("Betting odds") {
        val moneyline = listOfNotNull(
            odds.homeWinOdds?.let { "home $it" },
            odds.drawOdds?.let { "draw $it" },
            odds.awayWinOdds?.let { "away $it" },
        )
        if (moneyline.isNotEmpty()) InfoRow("Moneyline", moneyline.joinToString(" / "))
        val overUnder = listOfNotNull(
            odds.over25Odds?.let { "over 2.5: $it" },
            odds.under25Odds?.let { "under 2.5: $it" },
        )
        if (overUnder.isNotEmpty()) InfoRow("Over/under", overUnder.joinToString(" / "))
    }
}

@Composable
private fun NotesSection(overview: MatchOverview) {
    if (overview.note == null && overview.additionalNotes.isNullOrEmpty()) return
    SectionCard("Notes") {
        overview.note?.let { InfoRow("Note", it) }
        overview.additionalNotes?.forEachIndexed { index, note ->
            if (index > 0 || overview.note != null) HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
            Text(note.note, style = MaterialTheme.typography.bodySmall)
        }
    }
}
