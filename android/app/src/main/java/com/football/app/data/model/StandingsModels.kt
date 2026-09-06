package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class EloRating(
    val elo: Double,
    val asOf: String,
)

@Serializable
data class ClubStrengthRating(
    val overall: Double,
    val attack: Double,
    val defense: Double,
    val rank: Int? = null,
    val strengthChange: Double? = null,
)

@Serializable
data class StandingsZoneInfo(
    val position: Int,
    val totalTeams: Int,
    val zone: String,
    val pointsFromBoundary: Int? = null,
    val inTheMix: Boolean? = null,
)

@Serializable
data class StandingsScenario(
    val outcome: String,
    val newPoints: Int,
    val newPosition: Int? = null,
)

@Serializable
data class StandingsImpactInfo(
    val currentPosition: Int,
    val currentPoints: Int,
    val scenarios: List<StandingsScenario> = emptyList(),
)

@Serializable
data class HomeAdvantageInfo(
    val homeWinRatePct: Double? = null,
    val awayWinRatePct: Double? = null,
    val gapPct: Double? = null,
    val strength: String? = null,
)

@Serializable
data class OpponentRankRecord(
    val sampleSize: Int,
    val wins: Int,
    val draws: Int,
    val losses: Int,
)

/** Everything Standings needs from `insights` (frontend/DESIGN.md). */
@Serializable
data class InsightsStandings(
    val homeEloRating: EloRating? = null,
    val awayEloRating: EloRating? = null,
    val homeClubStrength: ClubStrengthRating? = null,
    val awayClubStrength: ClubStrengthRating? = null,
    val homeStandingsZone: StandingsZoneInfo? = null,
    val awayStandingsZone: StandingsZoneInfo? = null,
    val homeStandingsImpact: StandingsImpactInfo? = null,
    val awayStandingsImpact: StandingsImpactInfo? = null,
    val homeAdvantage: HomeAdvantageInfo? = null,
    val awayAdvantage: HomeAdvantageInfo? = null,
    val homeOpponentRankRecord: OpponentRankRecord? = null,
    val awayOpponentRankRecord: OpponentRankRecord? = null,
)

/** team_name/position/points only -- confirmed against
 * StandingsTableRow in types.py, which genuinely has no played/W-D-L/GD
 * fields (this project's own DESIGN.md draft assumed a richer row before
 * checking the real dataclass -- corrected here). */
@Serializable
data class StandingsTableRow(
    val teamName: String,
    val position: Int,
    val points: Int,
)

/** Just standings_table from `match` -- a separate wrapper (same pattern
 * as MatchOverview/MatchLineups) since this one field belongs to `match`
 * while the rest of Standings' data lives in `insights`. */
@Serializable
data class MatchStandingsTable(
    val standingsTable: List<StandingsTableRow>? = null,
)
