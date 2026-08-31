package com.football.app.data.model

import kotlinx.serialization.Serializable

// Every Season*Estimate class below has a `source: str` field in
// types.py that report.py's _strip_source_labels always removes from
// JSON output (confirmed against a real sample -- home_xg_estimate's
// real keys have no "source") -- deliberately not modeled here, it will
// never be present.

@Serializable
data class SeasonXGEstimate(
    val sampleSize: Int,
    val xgFor: Double,
    val xgAgainst: Double,
    val actualGoalsFor: Int,
    val actualGoalsAgainst: Int,
)

@Serializable
data class SeasonShotsEstimate(
    val sampleSize: Int,
    val shotsFor: Int,
    val shotsAgainst: Int,
    val shotsOnTargetFor: Int,
    val shotsOnTargetAgainst: Int,
)

@Serializable
data class SeasonCornersEstimate(
    val sampleSize: Int,
    val cornersFor: Int,
    val cornersAgainst: Int,
)

@Serializable
data class SeasonBigChancesEstimate(
    val sampleSize: Int,
    val bigChancesCreatedFor: Int,
    val bigChancesCreatedAgainst: Int,
    val bigChancesMissedFor: Int,
    val bigChancesMissedAgainst: Int,
)

@Serializable
data class PossessionMatchupInfo(
    val highOpponentPossessionPpg: Double? = null,
    val highOpponentPossessionSampleSize: Int,
    val otherPpg: Double? = null,
    val otherSampleSize: Int,
)

/**
 * The single largest object in the whole report (65 fields on the
 * Python side, matched exactly here) -- shared between Performance and
 * Discipline tabs (frontend/DESIGN.md lists overlapping fields from this
 * same object for both), so it's modeled once here rather than twice.
 * Every field transcribed directly from SeasonAdvancedStatsEstimate in
 * types.py, cross-checked against a real sample's actual key list (not
 * just the dataclass) -- confirms `source` is the only field genuinely
 * absent from JSON.
 */
@Serializable
data class AdvancedStats(
    val sampleSize: Int,
    val touchesInBoxFor: Int,
    val touchesInBoxAgainst: Int,
    val crossesFor: Int,
    val crossesAgainst: Int,
    val dribblesFor: Int,
    val dribblesAgainst: Int,
    val throughBallsFor: Int,
    val throughBallsAgainst: Int,
    val finalThirdEntriesFor: Int,
    val finalThirdEntriesAgainst: Int,
    val recoveriesFor: Int,
    val recoveriesAgainst: Int,
    val errorsLeadToShotFor: Int,
    val errorsLeadToShotAgainst: Int,
    val errorsLeadToGoalFor: Int,
    val errorsLeadToGoalAgainst: Int,
    val shotsInsideBoxFor: Int,
    val shotsInsideBoxAgainst: Int,
    val shotsOutsideBoxFor: Int,
    val shotsOutsideBoxAgainst: Int,
    val shotsOffTargetFor: Int,
    val shotsOffTargetAgainst: Int,
    val blockedShotsFor: Int,
    val blockedShotsAgainst: Int,
    val offsidesFor: Int,
    val offsidesAgainst: Int,
    val bigChancesScoredFor: Int,
    val bigChancesScoredAgainst: Int,
    val dispossessedFor: Int,
    val dispossessedAgainst: Int,
    val teamTacklesFor: Int,
    val teamTacklesAgainst: Int,
    val teamInterceptionsFor: Int,
    val teamInterceptionsAgainst: Int,
    val goalsPreventedFor: Double,
    val goalsPreventedAgainst: Double,
    val bigSavesFor: Int,
    val bigSavesAgainst: Int,
    val highClaimsFor: Int,
    val highClaimsAgainst: Int,
    val distanceCoveredKmFor: Double,
    val distanceCoveredKmAgainst: Double,
    val sprintsFor: Int,
    val sprintsAgainst: Int,
    val teamClearancesFor: Int,
    val teamClearancesAgainst: Int,
    val freeKicksFor: Int,
    val freeKicksAgainst: Int,
    val xaFor: Double,
    val xaAgainst: Double,
    val cornerGoalsFor: Int,
    val cornerGoalsAgainst: Int,
    val penaltyGoalsFor: Int,
    val penaltyGoalsAgainst: Int,
    val freeKickGoalsFor: Int,
    val freeKickGoalsAgainst: Int,
    val totalShotsFor: Int,
    val totalShotsAgainst: Int,
    val shotsOnTargetFor: Int,
    val shotsOnTargetAgainst: Int,
    val cornersFor: Int,
    val cornersAgainst: Int,
    val foulsFor: Int,
    val foulsAgainst: Int,
    val yellowCardsFor: Int,
    val yellowCardsAgainst: Int,
    val redCardsFor: Int,
    val redCardsAgainst: Int,
    val possessionPctAvg: Double? = null,
    val bigChancesCreatedFor: Int,
    val bigChancesCreatedAgainst: Int,
    val nonPenaltyXgFor: Double,
    val nonPenaltyXgAgainst: Double,
    val setPieceXgFor: Double,
    val setPieceXgAgainst: Double,
    val penaltiesAwardedFor: Int,
    val penaltiesAwardedAgainst: Int,
    val fieldTiltPct: Double? = null,
)

/**
 * Everything Performance needs from `insights` (frontend/DESIGN.md).
 * A growing subset -- same pattern as MatchOverview/MatchLineups, this
 * time over `insights` instead of `match`.
 */
@Serializable
data class InsightsPerformance(
    val homeXgEstimate: SeasonXGEstimate? = null,
    val awayXgEstimate: SeasonXGEstimate? = null,
    val homeShotsEstimate: SeasonShotsEstimate? = null,
    val awayShotsEstimate: SeasonShotsEstimate? = null,
    val homeAdvancedStats: AdvancedStats? = null,
    val awayAdvancedStats: AdvancedStats? = null,
    val homeBigChancesEstimate: SeasonBigChancesEstimate? = null,
    val awayBigChancesEstimate: SeasonBigChancesEstimate? = null,
    val homeCornersEstimate: SeasonCornersEstimate? = null,
    val awayCornersEstimate: SeasonCornersEstimate? = null,
    val homePossessionMatchup: PossessionMatchupInfo? = null,
    val awayPossessionMatchup: PossessionMatchupInfo? = null,
)
