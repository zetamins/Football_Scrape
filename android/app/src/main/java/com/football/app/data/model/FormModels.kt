package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class FormResult(
    val opponent: String,
    val competition: String? = null,
    val date: String? = null,
    val result: String,
    val scoreline: String,
    val venue: String,
    val margin: Int,
    val neutralVenue: Boolean? = null,
    val htScoreline: String? = null,
    val xgFor: Double? = null,
    val xgAgainst: Double? = null,
)

@Serializable
data class FixtureGap(
    val opponent: String,
    val date: String? = null,
    val daysSincePrevious: Int? = null,
)

@Serializable
data class HalfSplitStats(
    val sampleSize: Int,
    val firstHalfGoalsFor: Int,
    val firstHalfGoalsAgainst: Int,
    val secondHalfGoalsFor: Int,
    val secondHalfGoalsAgainst: Int,
)

@Serializable
data class StreakInfo(
    val result: String,
    val count: Int,
)

@Serializable
data class MomentumInfo(
    val recentPpg: Double,
    val priorPpg: Double,
    val trend: String,
)

@Serializable
data class CompetitionFormRecord(
    val competition: String,
    val played: Int,
    val wins: Int,
    val draws: Int,
    val losses: Int,
    val goalsFor: Int,
    val goalsAgainst: Int,
)

@Serializable
data class VenueSplitForm(
    val homeSampleSize: Int,
    val homeWins: Int,
    val homeDraws: Int,
    val homeLosses: Int,
    val homeGoalsFor: Int,
    val homeGoalsAgainst: Int,
    val awaySampleSize: Int,
    val awayWins: Int,
    val awayDraws: Int,
    val awayLosses: Int,
    val awayGoalsFor: Int,
    val awayGoalsAgainst: Int,
    // Neutral-venue matches (cup finals, etc.) -- usually all zero, but a
    // real field the backend always sends; was silently dropped before
    // (ignoreUnknownKeys swallowed it) since this class had no matching
    // properties at all.
    val neutralSampleSize: Int = 0,
    val neutralWins: Int = 0,
    val neutralDraws: Int = 0,
    val neutralLosses: Int = 0,
    val neutralGoalsFor: Int = 0,
    val neutralGoalsAgainst: Int = 0,
)

@Serializable
data class VenueSplitStats(
    val sampleSize: Int,
    val xgFor: Double,
    val xgAgainst: Double,
    val shotsFor: Int,
    val shotsAgainst: Int,
    val shotsOnTargetFor: Int,
    val shotsOnTargetAgainst: Int,
    val possessionPctAvg: Double? = null,
    val cornersFor: Int,
    val cornersAgainst: Int,
    val foulsFor: Int,
    val foulsAgainst: Int,
    val yellowCardsFor: Int,
    val yellowCardsAgainst: Int,
    val redCardsFor: Int,
    val redCardsAgainst: Int,
    val bigChancesCreatedFor: Int,
    val bigChancesCreatedAgainst: Int,
)

@Serializable
data class DetailedVenueSplitForm(
    val home: VenueSplitStats,
    val away: VenueSplitStats,
    val neutral: VenueSplitStats,
)

/**
 * The full form/opponentForm shape (frontend/DESIGN.md's Form tab --
 * every field, not a subset, per this session's "cover everything"
 * pass). Transcribed directly from types.py's FormSummary, cross-checked
 * against a real sample (see resources/sample_form.json).
 */
@Serializable
data class FormSummary(
    val last5Overall: List<FormResult> = emptyList(),
    val last10Overall: List<FormResult> = emptyList(),
    val last20Overall: List<FormResult> = emptyList(),
    val last5Home: List<FormResult> = emptyList(),
    val last5Away: List<FormResult> = emptyList(),
    val next5WithGaps: List<FixtureGap> = emptyList(),
    val gapsBetweenLastThree: List<Int> = emptyList(),
    val halfSplit: HalfSplitStats? = null,
    val recentCompetitions: List<String> = emptyList(),
    val currentStreak: StreakInfo? = null,
    val homeWinRatePct: Double? = null,
    val awayWinRatePct: Double? = null,
    val momentum: MomentumInfo? = null,
    val narrowWinSharePct: Double? = null,
    val scoringDrawSharePct: Double? = null,
    val bttsSharePct: Double? = null,
    val cleanSheetStreak: Int? = null,
    val scorelessStreak: Int? = null,
    val over15SharePct: Double? = null,
    val over25SharePct: Double? = null,
    val over35SharePct: Double? = null,
    val cleanSheetSharePct: Double? = null,
    val failedToScoreSharePct: Double? = null,
    val formByCompetition: List<CompetitionFormRecord> = emptyList(),
    val matchesLast7Days: Int,
    val matchesLast14Days: Int,
    val venueSplitForm: VenueSplitForm? = null,
    val detailedVenueSplit: DetailedVenueSplitForm? = null,
    val winRatePct: Double? = null,
    val drawRatePct: Double? = null,
    val lossRatePct: Double? = null,
    val pointsPerGame: Double? = null,
    val goalsForPerGame: Double? = null,
    val goalsAgainstPerGame: Double? = null,
)
