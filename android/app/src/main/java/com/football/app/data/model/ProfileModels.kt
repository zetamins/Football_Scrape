package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class SeasonPassingStyleEstimate(
    val sampleSize: Int,
    val totalPassesFor: Int,
    val accuratePassesFor: Int,
    val passAccuracyPct: Double? = null,
    val accurateLongBallsFor: Int,
    val longBallSharePct: Double? = null,
)

@Serializable
data class SeasonAerialEstimate(
    val sampleSize: Int,
    val aerialDuelsWonFor: Int,
    val aerialDuelsWonAgainst: Int,
)

@Serializable
data class SeasonGoalkeepingEstimate(
    val sampleSize: Int,
    val savesFor: Int,
    val shotsOnTargetFaced: Int,
    val savePct: Double? = null,
    val goalsConceded: Int,
)

@Serializable
data class SeasonDefensiveErrorsEstimate(
    val sampleSize: Int,
    val defensiveErrorsFor: Int,
    val defensiveErrorsAgainst: Int,
)

@Serializable
data class DuelVulnerability(
    val name: String,
    val groundDuelSuccessPct: Double,
)

@Serializable
data class FullbackExposureInfo(
    val name: String,
    val chancesCreated: Int,
    val groundDuelSuccessPct: Double,
)

@Serializable
data class SetPieceThreatFlag(
    val cornersPerGame: Double? = null,
    val opponentAerialWinPct: Double? = null,
    val elevated: Boolean,
)

@Serializable
data class DirectPlayExposureFlag(
    val longBallSharePct: Double? = null,
    val opponentAerialWinPct: Double? = null,
    val elevated: Boolean,
)

/** Everything Profile needs from `insights` (frontend/DESIGN.md). */
@Serializable
data class InsightsProfile(
    val homePassingStyle: SeasonPassingStyleEstimate? = null,
    val awayPassingStyle: SeasonPassingStyleEstimate? = null,
    val homeAerialEstimate: SeasonAerialEstimate? = null,
    val awayAerialEstimate: SeasonAerialEstimate? = null,
    val homeGoalkeepingEstimate: SeasonGoalkeepingEstimate? = null,
    val awayGoalkeepingEstimate: SeasonGoalkeepingEstimate? = null,
    val homeDefensiveErrorsEstimate: SeasonDefensiveErrorsEstimate? = null,
    val awayDefensiveErrorsEstimate: SeasonDefensiveErrorsEstimate? = null,
    val homeDuelVulnerabilities: List<DuelVulnerability>? = null,
    val awayDuelVulnerabilities: List<DuelVulnerability>? = null,
    val homeFullbackExposure: List<FullbackExposureInfo>? = null,
    val awayFullbackExposure: List<FullbackExposureInfo>? = null,
    val homeSetPieceThreat: SetPieceThreatFlag? = null,
    val awaySetPieceThreat: SetPieceThreatFlag? = null,
    val homeDirectPlayExposure: DirectPlayExposureFlag? = null,
    val awayDirectPlayExposure: DirectPlayExposureFlag? = null,
)
