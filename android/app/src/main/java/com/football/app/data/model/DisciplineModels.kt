package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class CardDisciplineInfo(
    val yellowPerGame: Double,
    val redPerGame: Double,
    val elevatedRisk: Boolean,
)

// `source: str` on the Python side, always stripped from JSON -- same
// pattern confirmed for every Season*Estimate class (see
// PerformanceModels.kt's comment).
@Serializable
data class CardDisciplineVenueSplit(
    val atHomeSampleSize: Int,
    val atHomeYellowPerGame: Double? = null,
    val atHomeRedPerGame: Double? = null,
    val awaySampleSize: Int,
    val awayYellowPerGame: Double? = null,
    val awayRedPerGame: Double? = null,
)

@Serializable
data class SeasonFoulsEstimate(
    val sampleSize: Int,
    val foulsCommittedFor: Int,
    val foulsCommittedAgainst: Int,
)

@Serializable
data class PlayerCardRisk(
    val name: String,
    val yellowCards: Int,
    val redCards: Int,
    val appearances: Int? = null,
    val accumulationRisk: Boolean,
    val priorDismissal: Boolean,
)

@Serializable
data class FlaggedPlayer(
    val name: String,
    val side: String,
    val priorDismissal: Boolean,
)

@Serializable
data class RefereeCardRiskNote(
    val refereeName: String,
    val yellowCardsPerGame: Double,
    val elevatedCardReferee: Boolean,
    val flaggedPlayers: List<FlaggedPlayer> = emptyList(),
)

/** Everything Discipline needs from `insights` (frontend/DESIGN.md,
 * using the old web dashboard's fuller field list -- includes
 * home/away_advanced_stats and home/away_corners_estimate too, both
 * already modeled in PerformanceModels.kt and reused here rather than
 * duplicated). */
@Serializable
data class InsightsDiscipline(
    val homeCardDiscipline: CardDisciplineInfo? = null,
    val awayCardDiscipline: CardDisciplineInfo? = null,
    val homeCardDisciplineVenueSplit: CardDisciplineVenueSplit? = null,
    val awayCardDisciplineVenueSplit: CardDisciplineVenueSplit? = null,
    val homeFoulsEstimate: SeasonFoulsEstimate? = null,
    val awayFoulsEstimate: SeasonFoulsEstimate? = null,
    val homeAdvancedStats: AdvancedStats? = null,
    val awayAdvancedStats: AdvancedStats? = null,
    val homeCornersEstimate: SeasonCornersEstimate? = null,
    val awayCornersEstimate: SeasonCornersEstimate? = null,
    val homeCardRisks: List<PlayerCardRisk>? = null,
    val awayCardRisks: List<PlayerCardRisk>? = null,
    val refereeCardRiskNote: RefereeCardRiskNote? = null,
)
