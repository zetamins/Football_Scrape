package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class SeasonPlayerStats(
    val appearances: Int? = null,
    val goals: Int,
    val assists: Int,
    val yellowCards: Int,
    val redCards: Int,
    val rating: Double? = null,
    val expectedGoals: Double? = null,
)

@Serializable
data class DefensiveStats(
    val tacklesMade: Int? = null,
    val interceptions: Int? = null,
    val ballRecoveries: Int? = null,
    val clearances: Int? = null,
    val groundDuelSuccessPct: Double? = null,
    val chancesCreated: Int? = null,
    val shots: Int? = null,
    val shotsOnTarget: Int? = null,
    val passesCompleted: Int? = null,
    val foulsWon: Int? = null,
    val aerialDuelsWon: Int? = null,
    val goalsFromInsideBox: Int? = null,
    val goalsFromOutsideBox: Int? = null,
    val conversionRatePct: Double? = null,
    val shotsOffTarget: Int? = null,
    val passesAttempted: Int? = null,
    val passingAccuracyPct: Double? = null,
    val blockedShots: Int? = null,
    val takeOnsCompleted: Int? = null,
    val groundDuelsWon: Int? = null,
)

@Serializable
data class PlayerUsagePattern(
    val matchesInSquad: Int,
    val starts: Int,
    val subAppearances: Int,
    val unusedBench: Int,
    val totalMinutes: Int,
    val totalGoals: Int,
    val totalAssists: Int,
    val totalXg: Double,
    val totalXa: Double,
    val totalShots: Int,
    val totalShotsOnTarget: Int,
    val totalTackles: Int,
    val totalInterceptions: Int,
    val totalFouls: Int,
    val totalKeyPasses: Int,
    val appearancesWithStats: Int,
    val avgRating: Double? = null,
    val goalsPer90: Double? = null,
    val assistsPer90: Double? = null,
    val xgPer90: Double? = null,
    val xaPer90: Double? = null,
    val keyPassesPer90: Double? = null,
)

// season_stats_source is always stripped from JSON (in
// report.py's _SOURCE_LABEL_KEYS, same as every other *_source field
// across this app's models).
@Serializable
data class SquadMember(
    val name: String,
    val role: String? = null,
    val injury: String? = null,
    val age: Int? = null,
    val marketValue: Double? = null,
    val seasonStats: SeasonPlayerStats? = null,
    val defensiveStats: DefensiveStats? = null,
    val recentUsage: PlayerUsagePattern? = null,
)

@Serializable
data class TransferRecord(
    val playerName: String,
    val direction: String,
    val fromClub: String? = null,
    val toClub: String? = null,
    val date: String? = null,
)

@Serializable
data class TopPerformer(
    val name: String,
    val goals: Int,
    val assists: Int,
    val appearances: Int? = null,
    val rating: Double? = null,
)

@Serializable
data class TopDefender(val name: String, val tacklesMade: Int, val interceptions: Int)

@Serializable
data class BenchRegular(
    val name: String,
    val matchesInSquad: Int,
    val starts: Int,
    val subAppearances: Int,
    val unusedBench: Int,
)

@Serializable
data class RecentFormLeader(
    val name: String,
    val goals: Int,
    val assists: Int,
    val xg: Double,
    val xa: Double,
    val avgRating: Double? = null,
    val goalsPer90: Double? = null,
    val assistsPer90: Double? = null,
    val keyPasses: Int,
    val sampleSize: Int,
)

@Serializable
data class RoleFormEntry(
    val name: String,
    val matchesInSquad: Int,
    val starts: Int,
    val totalMinutes: Int,
    val goals: Int,
    val assists: Int,
    val xg: Double,
    val xa: Double,
    val keyPasses: Int,
    val avgRating: Double? = null,
)

/**
 * Everything Squad needs from `teamProfile`/`opponentProfile`
 * (frontend/DESIGN.md, every field). `source` (on the Python
 * TeamProfile dataclass) is always stripped from JSON, same as every
 * other *_source field this app models -- not included here.
 */
@Serializable
data class TeamProfileData(
    val teamName: String,
    val squad: List<SquadMember>? = null,
    val averageAge: Double? = null,
    val injuries: List<SquadMember>? = null,
    val keyInjuries: List<SquadMember>? = null,
    val recentTransfers: List<TransferRecord>? = null,
    val missingMidfielders: List<String>? = null,
    val missingAttackers: List<String>? = null,
    val missingDefenders: List<String>? = null,
    val missingGoalkeepers: List<String>? = null,
    val topScorers: List<TopPerformer>? = null,
    val topAssists: List<TopPerformer>? = null,
    val topDefenders: List<TopDefender>? = null,
    val benchRegulars: List<BenchRegular>? = null,
    val midfieldersForm: List<RoleFormEntry>? = null,
    val defendersForm: List<RoleFormEntry>? = null,
    val recentFormLeaders: List<RecentFormLeader>? = null,
)

@Serializable
data class SquadStrengthInfo(
    val totalValue: Double? = null,
    val attackValue: Double? = null,
    val midfieldValue: Double? = null,
    val defenseValue: Double? = null,
    val goalkeeperValue: Double? = null,
    val availableValue: Double? = null,
)

/** Just the squad-value fields Squad needs from `insights` (separate
 * from TeamProfileData since it lives in a different top-level JSON
 * section -- same pattern as MatchStandingsTable). */
@Serializable
data class InsightsSquadStrength(
    val homeSquadStrength: SquadStrengthInfo? = null,
    val awaySquadStrength: SquadStrengthInfo? = null,
)
