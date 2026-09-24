package com.football.app.data.model

import kotlinx.serialization.Serializable

/**
 * Pre-kickoff, only name/position/substitute/shirtNumber/age are ever
 * present -- report.py's _prune_unplayed_match_fields strips every
 * outcome stat (minutesPlayed, goals, xg, rating, ...) from each entry
 * while match.status is "notstarted"/"scheduled" (confirmed against
 * report.py's source, not a stale sample -- see LineupsTab's own
 * comment for why a stale local sample once suggested otherwise).
 */
@Serializable
data class LineupPlayer(
    val name: String,
    val position: String? = null,
    val substitute: Boolean? = null,
    val shirtNumber: Int? = null,
    val age: Int? = null,
    val minutesPlayed: Int? = null,
    val goals: Int? = null,
    val assists: Int? = null,
    val xg: Double? = null,
    val xa: Double? = null,
    val shots: Int? = null,
    val shotsOnTarget: Int? = null,
    val tackles: Int? = null,
    val interceptions: Int? = null,
    val fouls: Int? = null,
    // Sofascore's own rating, published as a string ("7.4").
    val rating: String? = null,
    val keyPasses: Int? = null,
)

@Serializable
data class MissingPlayer(
    val name: String,
    val description: String? = null,
    val expectedReturn: String? = null,
)

@Serializable
data class SetPieceGoalCounts(
    val corner: Int,
    val penalty: Int,
    val freeKick: Int,
)

@Serializable
data class SetPieceGoals(
    val home: SetPieceGoalCounts,
    val away: SetPieceGoalCounts,
)

@Serializable
data class ShotmapSideStats(
    val nonPenaltyXg: Double,
    val setPieceXg: Double,
    val penaltiesAwarded: Int,
)

@Serializable
data class ShotmapStats(
    val home: ShotmapSideStats,
    val away: ShotmapSideStats,
)

/** rating is a String ("8.7"), not a number -- matches
 * PlayerOfTheMatch.rating: Optional[str] in types.py exactly. */
@Serializable
data class PlayerOfTheMatch(
    val name: String,
    val rating: String? = null,
)

@Serializable
data class TeamSeasonStats(
    val goalsScored: Int,
    val goalsConceded: Int,
    val cleanSheets: Int,
    val yellowCards: Int,
    val redCards: Int,
    val averageBallPossession: Double? = null,
    val possessionWindowNote: String? = null,
)

/**
 * Everything Lineups & match detail needs from `match`
 * (frontend/DESIGN.md). A growing subset, same pattern as MatchOverview.
 */
@Serializable
data class MatchLineups(
    val homeFormation: String? = null,
    val awayFormation: String? = null,
    val lineupConfirmed: Boolean? = null,
    val homeLineup: List<LineupPlayer>? = null,
    val awayLineup: List<LineupPlayer>? = null,
    val homeBench: List<LineupPlayer>? = null,
    val awayBench: List<LineupPlayer>? = null,
    val homeSuspendedPlayers: List<String>? = null,
    val awaySuspendedPlayers: List<String>? = null,
    val homeMissingPlayers: List<MissingPlayer>? = null,
    val awayMissingPlayers: List<MissingPlayer>? = null,
    val playerOfTheMatch: PlayerOfTheMatch? = null,
    val setPieceGoals: SetPieceGoals? = null,
    val shotmapStats: ShotmapStats? = null,
    val homeTeamSeasonStats: TeamSeasonStats? = null,
    val awayTeamSeasonStats: TeamSeasonStats? = null,
)
