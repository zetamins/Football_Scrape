package com.football.app.data.model

import kotlinx.serialization.Serializable

@Serializable
data class WinProbabilities(
    val homeWinPct: Double,
    val drawPct: Double,
    val awayWinPct: Double,
)

/**
 * Mirrors insights.prediction exactly -- confirmed shape from real
 * sample data (backend/output/brentford-2026-08-29T23-38-47-868Z.json):
 * marketImplied (from betting odds, when available) and heuristicBlend
 * (the backend's own Elo-based estimate). Both nullable independently --
 * either can be absent on its own (e.g. no odds found for this match).
 */
@Serializable
data class Prediction(
    val marketImplied: WinProbabilities? = null,
    val heuristicBlend: WinProbabilities? = null,
)
