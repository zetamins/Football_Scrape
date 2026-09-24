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
 * The single largest object in the whole report -- shared between
 * Performance and Discipline tabs (frontend/DESIGN.md lists overlapping
 * fields from this same object for both), so it's modeled once here
 * rather than twice. Every field transcribed from
 * SeasonAdvancedStatsEstimate in types.py, cross-checked against a real
 * sample's actual key list -- confirms `source` is the only field
 * genuinely absent from JSON.
 *
 * Fields Python marks Optional (stat_totals pairs the source never
 * reported this run) are Int?/Double? here: JSON null means "this source
 * never reported that stat", not a zero. Fields derived from the
 * set-piece accumulator (xa, corner/pen/FK goals, non-pen xG, set-piece
 * xG, penalties awarded) stay non-null -- a real 0 when no such events
 * occurred. `source` is stripped from JSON by report.py and never
 * modeled here.
 */
@Serializable
data class AdvancedStats(
    val sampleSize: Int,
    val touchesInBoxFor: Int? = null,
    val touchesInBoxAgainst: Int? = null,
    val crossesFor: Int? = null,
    val crossesAgainst: Int? = null,
    val dribblesFor: Int? = null,
    val dribblesAgainst: Int? = null,
    val throughBallsFor: Int? = null,
    val throughBallsAgainst: Int? = null,
    val finalThirdEntriesFor: Int? = null,
    val finalThirdEntriesAgainst: Int? = null,
    val recoveriesFor: Int? = null,
    val recoveriesAgainst: Int? = null,
    val errorsLeadToShotFor: Int? = null,
    val errorsLeadToShotAgainst: Int? = null,
    val errorsLeadToGoalFor: Int? = null,
    val errorsLeadToGoalAgainst: Int? = null,
    val shotsInsideBoxFor: Int? = null,
    val shotsInsideBoxAgainst: Int? = null,
    val shotsOutsideBoxFor: Int? = null,
    val shotsOutsideBoxAgainst: Int? = null,
    val shotsOffTargetFor: Int? = null,
    val shotsOffTargetAgainst: Int? = null,
    val blockedShotsFor: Int? = null,
    val blockedShotsAgainst: Int? = null,
    val offsidesFor: Int? = null,
    val offsidesAgainst: Int? = null,
    val bigChancesScoredFor: Int? = null,
    val bigChancesScoredAgainst: Int? = null,
    val dispossessedFor: Int? = null,
    val dispossessedAgainst: Int? = null,
    val teamTacklesFor: Int? = null,
    val teamTacklesAgainst: Int? = null,
    val teamInterceptionsFor: Int? = null,
    val teamInterceptionsAgainst: Int? = null,
    val goalsPreventedFor: Double? = null,
    val goalsPreventedAgainst: Double? = null,
    val bigSavesFor: Int? = null,
    val bigSavesAgainst: Int? = null,
    val highClaimsFor: Int? = null,
    val highClaimsAgainst: Int? = null,
    val distanceCoveredKmFor: Double? = null,
    val distanceCoveredKmAgainst: Double? = null,
    val sprintsFor: Int? = null,
    val sprintsAgainst: Int? = null,
    val teamClearancesFor: Int? = null,
    val teamClearancesAgainst: Int? = null,
    val freeKicksFor: Int? = null,
    val freeKicksAgainst: Int? = null,
    val xaFor: Double,
    val xaAgainst: Double,
    val cornerGoalsFor: Int,
    val cornerGoalsAgainst: Int,
    val penaltyGoalsFor: Int,
    val penaltyGoalsAgainst: Int,
    val freeKickGoalsFor: Int,
    val freeKickGoalsAgainst: Int,
    val totalShotsFor: Int? = null,
    val totalShotsAgainst: Int? = null,
    val shotsOnTargetFor: Int? = null,
    val shotsOnTargetAgainst: Int? = null,
    val cornersFor: Int? = null,
    val cornersAgainst: Int? = null,
    val foulsFor: Int? = null,
    val foulsAgainst: Int? = null,
    val yellowCardsFor: Int? = null,
    val yellowCardsAgainst: Int? = null,
    val redCardsFor: Int? = null,
    val redCardsAgainst: Int? = null,
    val possessionPctAvg: Double? = null,
    val bigChancesCreatedFor: Int? = null,
    val bigChancesCreatedAgainst: Int? = null,
    val nonPenaltyXgFor: Double,
    val nonPenaltyXgAgainst: Double,
    val setPieceXgFor: Double,
    val setPieceXgAgainst: Double,
    val penaltiesAwardedFor: Int,
    val penaltiesAwardedAgainst: Int,
    val fieldTiltPct: Double? = null,
    /** Python's `unavailable_stats` -- ADVANCED_STAT_NAMES keys the source
     * never reported this run (their numeric pairs above are null). */
    val unavailableStats: List<String>? = null,
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
