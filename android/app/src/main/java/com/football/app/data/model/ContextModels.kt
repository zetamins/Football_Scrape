package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class RestComparison(
    val ownRestDays: Int? = null,
    val opponentRestDays: Int? = null,
    val moreRested: String? = null,
)

@Serializable
data class RestPerformanceInfo(
    val shortRestPpg: Double? = null,
    val shortRestSampleSize: Int,
    val longRestPpg: Double? = null,
    val longRestSampleSize: Int,
)

@Serializable
data class FatigueFlag(
    val multiCompetition: Boolean,
    val competitions: List<String> = emptyList(),
    val avgGapDays: Double? = null,
    val flagged: Boolean,
)

@Serializable
data class RotationInfo(
    val changedPlayers: Int,
    val startingXiSize: Int,
    val lastMatchDate: String? = null,
    val previousMatchDate: String? = null,
    val lastFormation: String? = null,
    val previousFormation: String? = null,
    val formationChanged: Boolean? = null,
    val lastDefenderCount: Int? = null,
    val previousDefenderCount: Int? = null,
    val precedingResult: String? = null,
)

@Serializable
data class StreakStabilityInfo(
    val streakResult: String,
    val streakCount: Int,
    val changedPlayers: Int? = null,
    val stable: Boolean? = null,
)

@Serializable
data class LosingStreakContextInfo(
    val streakCount: Int,
    val xgDelta: Double? = null,
    val potentialTurnaround: Boolean? = null,
)

@Serializable
data class ResilienceInfo(
    val nonWinSampleSize: Int,
    val drawSharePct: Double,
)

@Serializable
data class ExperienceComparison(
    val ownAverageAge: Double? = null,
    val opponentAverageAge: Double? = null,
    val moreExperienced: String? = null,
)

@Serializable
data class ExperienceH2HNote(
    val moreExperienced: String? = null,
    val h2hLeader: String? = null,
    val aligned: Boolean? = null,
)

@Serializable
data class TravelInfo(
    val venueCountry: String? = null,
    val homeTeamCountry: String? = null,
    val awayTeamCountry: String? = null,
    val homeTraveling: Boolean? = null,
    val awayTraveling: Boolean? = null,
    val homeTravelDistanceKm: Double? = null,
    val awayTravelDistanceKm: Double? = null,
    val homeTimezoneDiffHours: Double? = null,
    val awayTimezoneDiffHours: Double? = null,
    val homeTravelTimeHours: Double? = null,
    val awayTravelTimeHours: Double? = null,
)

@Serializable
data class PresenceEntry(
    val name: String,
    val status: String,
    val starting: Boolean,
    val onBench: Boolean? = null,
    val reason: String? = null,
)

@Serializable
data class BenchInfo(
    val benchSize: Int,
    val benchTotalMarketValue: Double? = null,
    val startingTotalMarketValue: Double? = null,
)

/** Everything Context needs from `insights` (frontend/DESIGN.md). */
@Serializable
data class InsightsContext(
    val restComparison: RestComparison? = null,
    val homeRestPerformance: RestPerformanceInfo? = null,
    val awayRestPerformance: RestPerformanceInfo? = null,
    val homeFatigueFlag: FatigueFlag? = null,
    val awayFatigueFlag: FatigueFlag? = null,
    val homeRotation: RotationInfo? = null,
    val awayRotation: RotationInfo? = null,
    val homeStreakStability: StreakStabilityInfo? = null,
    val awayStreakStability: StreakStabilityInfo? = null,
    val homeLosingStreakContext: LosingStreakContextInfo? = null,
    val awayLosingStreakContext: LosingStreakContextInfo? = null,
    val homeResilience: ResilienceInfo? = null,
    val awayResilience: ResilienceInfo? = null,
    val experienceComparison: ExperienceComparison? = null,
    val experienceH2h: ExperienceH2HNote? = null,
    val travelInfo: TravelInfo? = null,
    val homePresence: List<PresenceEntry>? = null,
    val awayPresence: List<PresenceEntry>? = null,
    val homeBenchInfo: BenchInfo? = null,
    val awayBenchInfo: BenchInfo? = null,
)
