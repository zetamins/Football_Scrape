package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * xgModel is the newest field on Prediction (the backend's third,
 * independent Poisson-goal-model prediction method, added alongside
 * marketImplied/heuristicBlend). Prediction's properties carry no
 * explicit @SerialName, so AppJson's SnakeCase naming strategy is what
 * maps them to the real backend keys -- report.py's MatchPrediction
 * dataclass fields are market_implied/heuristic_blend/xg_model
 * (snake_case; only ReportJson's own 10 top-level keys are hand-
 * camelCased, confirmed earlier this session), so this test's JSON uses
 * snake_case top-level keys deliberately, not the Kotlin property names
 * -- using camelCase here would silently test the wrong shape.
 */
class PredictionTest {
    @Test
    fun `decodes all three methods when present`() {
        val json = """
            {
              "market_implied": {"home_win_pct": 50.4, "draw_pct": 24.0, "away_win_pct": 25.6},
              "heuristic_blend": {"home_win_pct": 47.2, "draw_pct": 26.1, "away_win_pct": 26.7},
              "xg_model": {"home_win_pct": 44.8, "draw_pct": 23.5, "away_win_pct": 31.7}
            }
        """.trimIndent()
        val prediction = AppJson.decodeFromString(Prediction.serializer(), json)

        assertEquals(50.4, prediction.marketImplied!!.homeWinPct, 0.0)
        assertEquals(47.2, prediction.heuristicBlend!!.homeWinPct, 0.0)
        assertEquals(44.8, prediction.xgModel!!.homeWinPct, 0.0)
        assertEquals(31.7, prediction.xgModel!!.awayWinPct, 0.0)
    }

    @Test
    fun `xgModel absent (no xG data for one team) decodes as null, not a decode failure`() {
        val json = """{"heuristic_blend": {"home_win_pct": 50.0, "draw_pct": 25.0, "away_win_pct": 25.0}}"""
        val prediction = AppJson.decodeFromString(Prediction.serializer(), json)

        assertNull(prediction.marketImplied)
        assertNull(prediction.xgModel)
        assertEquals(50.0, prediction.heuristicBlend!!.homeWinPct, 0.0)
    }

    @Test
    fun `a report captured before xgModel existed still decodes (ignoreUnknownKeys both ways)`() {
        // The exact shape real reports had before this session added
        // xg_model on the backend -- must keep decoding an OLD-shaped
        // payload without a decode error, or reopening a History entry
        // saved before this feature would break.
        val json = """{"market_implied": {"home_win_pct": 50.4, "draw_pct": 24.0, "away_win_pct": 25.6}}"""
        val prediction = AppJson.decodeFromString(Prediction.serializer(), json)

        assertEquals(50.4, prediction.marketImplied!!.homeWinPct, 0.0)
        assertNull(prediction.xgModel)
    }
}
