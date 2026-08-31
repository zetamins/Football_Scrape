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
import androidx.compose.ui.unit.dp
import com.football.app.charts.PitchDiagram
import com.football.app.components.OutlinedPill
import com.football.app.components.PillFlow
import com.football.app.components.SectionCard
import com.football.app.components.InfoRow
import com.football.app.data.model.LineupPlayer
import com.football.app.data.model.MatchLineups
import com.football.app.ui.theme.AppTheme

/**
 * frontend/DESIGN.md's Lineups & match detail tab. Starting XIs render
 * on a pitch diagram (PitchDiagram, positioned by formation string +
 * G/D/M/F position), not a flat name list, plus season stats/bench/
 * availability/match-detail sections below.
 */
@Composable
fun LineupsTab(lineups: MatchLineups, homeTeam: String, awayTeam: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        SeasonStatsSection(lineups, homeTeam, awayTeam)
        FormationsSection(lineups)
        PitchSection("$homeTeam starting XI (${lineups.homeFormation ?: "?"})", lineups.homeLineup, lineups.homeFormation, AppTheme.colors.homeSeries)
        PitchSection("$awayTeam starting XI (${lineups.awayFormation ?: "?"})", lineups.awayLineup, lineups.awayFormation, AppTheme.colors.awaySeries)
        BenchSection("$homeTeam bench", lineups.homeBench)
        BenchSection("$awayTeam bench", lineups.awayBench)
        UnavailableSection(homeTeam, lineups.homeSuspendedPlayers, lineups.homeMissingPlayers)
        UnavailableSection(awayTeam, lineups.awaySuspendedPlayers, lineups.awayMissingPlayers)
        MatchDetailSection(lineups)
    }
}


@Composable
private fun SeasonStatsSection(lineups: MatchLineups, homeTeam: String, awayTeam: String) {
    if (lineups.homeTeamSeasonStats == null && lineups.awayTeamSeasonStats == null) return
    SectionCard("Season stats") {
        lineups.homeTeamSeasonStats?.let { s ->
            InfoRow(homeTeam, "${s.goalsScored} scored, ${s.goalsConceded} conceded, ${s.cleanSheets} clean sheets")
        }
        lineups.awayTeamSeasonStats?.let { s ->
            InfoRow(awayTeam, "${s.goalsScored} scored, ${s.goalsConceded} conceded, ${s.cleanSheets} clean sheets")
        }
    }
}

@Composable
private fun FormationsSection(lineups: MatchLineups) {
    if (lineups.homeFormation == null && lineups.awayFormation == null) return
    SectionCard("Formations") {
        InfoRow("Shape", "${lineups.homeFormation ?: "?"} vs ${lineups.awayFormation ?: "?"}")
        lineups.lineupConfirmed?.let { InfoRow("Confirmed", if (it) "Yes" else "Predicted") }
    }
}

@Composable
private fun PitchSection(title: String, players: List<LineupPlayer>?, formation: String?, teamColor: androidx.compose.ui.graphics.Color) {
    if (players.isNullOrEmpty()) return
    SectionCard(title) {
        PitchDiagram(formation = formation, players = players, teamColor = teamColor)
    }
    // Pre-kickoff (the common case -- see LineupPlayer's own doc comment)
    // every stat below is pruned to null, so this list would just repeat
    // name/position/shirt the pitch diagram above already shows -- only
    // worth its own section once there's real per-player stat data to add.
    if (players.any { it.minutesPlayed != null || it.rating != null }) {
        LineupSection("$title -- stats", players)
    }
}

@Composable
private fun LineupSection(title: String, players: List<LineupPlayer>?) {
    if (players.isNullOrEmpty()) return
    SectionCard(title) {
        players.forEach { p ->
            val statLine = listOfNotNull(
                p.minutesPlayed?.let { "${it}'" },
                p.goals?.takeIf { it > 0 }?.let { "${it}g" },
                p.assists?.takeIf { it > 0 }?.let { "${it}a" },
                p.rating?.let { "$it rating" },
            ).joinToString(", ")
            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                Text(
                    "${p.shirtNumber?.let { "#$it " } ?: ""}${p.name} (${p.position ?: "?"})",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.weight(1f),
                )
                if (statLine.isNotEmpty()) Text(statLine, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun BenchSection(title: String, players: List<LineupPlayer>?) {
    if (players.isNullOrEmpty()) return
    SectionCard(title) {
        PillFlow {
            players.forEach { p -> OutlinedPill(text = p.name, borderColor = MaterialTheme.colorScheme.outline, contentColor = MaterialTheme.colorScheme.onSurface) }
        }
    }
}

@Composable
private fun UnavailableSection(team: String, suspended: List<String>?, missing: List<com.football.app.data.model.MissingPlayer>?) {
    if (suspended.isNullOrEmpty() && missing.isNullOrEmpty()) return
    SectionCard("$team availability") {
        suspended?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Suspended", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(6.dp))
            PillFlow {
                list.forEach { name -> OutlinedPill(text = name, borderColor = AppTheme.colors.statusCritical, contentColor = AppTheme.colors.statusCritical) }
            }
            Spacer(Modifier.height(8.dp))
        }
        missing?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Missing", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(6.dp))
            PillFlow {
                list.forEach { m ->
                    OutlinedPill(
                        text = "${m.name}${m.description?.let { " ($it)" } ?: ""}",
                        borderColor = AppTheme.colors.statusCritical,
                        contentColor = AppTheme.colors.statusCritical,
                    )
                }
            }
        }
    }
}

@Composable
private fun MatchDetailSection(lineups: MatchLineups) {
    if (lineups.playerOfTheMatch == null && lineups.setPieceGoals == null && lineups.shotmapStats == null) return
    SectionCard("Match detail") {
        lineups.playerOfTheMatch?.let { potm ->
            InfoRow("Player of the match", "${potm.name}${potm.rating?.let { " ($it)" } ?: ""}")
        }
        lineups.setPieceGoals?.let { sp ->
            InfoRow(
                "Set-piece goals (corner/pen/FK)",
                "home ${sp.home.corner}/${sp.home.penalty}/${sp.home.freeKick} -- away ${sp.away.corner}/${sp.away.penalty}/${sp.away.freeKick}",
            )
        }
        lineups.shotmapStats?.let { sm ->
            InfoRow(
                "Non-penalty xG / set-piece xG",
                "home ${sm.home.nonPenaltyXg}/${sm.home.setPieceXg} -- away ${sm.away.nonPenaltyXg}/${sm.away.setPieceXg}",
            )
        }
    }
}
