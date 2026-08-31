package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class WinProbabilities(
    val homeWinPct: Double,
    val drawPct: Double,
    val awayWinPct: Double,
)

/**
 * Mirrors insights.prediction exactly -- marketImplied (from betting
 * odds, when available), heuristicBlend (Elo + rest/availability-
 * adjusted, see prediction.py's own module doc for exactly which
 * adjustments and why), and xgModel (an independent Poisson goal model
 * from each team's own rolling xG rates, deliberately free of the
 * rest/availability adjustments so it stays a clean third read). All
 * three nullable independently -- any can be absent on its own (e.g. no
 * odds found, or one team's xG estimate unavailable).
 */
@Serializable
data class Prediction(
    val marketImplied: WinProbabilities? = null,
    val heuristicBlend: WinProbabilities? = null,
    val xgModel: WinProbabilities? = null,
)
