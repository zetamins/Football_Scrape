package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Decodes InsightsPerformance against real backend JSON (a trimmed copy
 * of backend/output/sunderland-2026-08-29T22-51-11-993Z.json's
 * `insights` object -- see resources/sample_insights_performance.json).
 * Specifically verifies `source` (present in the Python dataclasses, per
 * types.py) is correctly modeled as ABSENT here -- report.py's
 * _strip_source_labels always removes it from JSON, confirmed against
 * this real sample before writing the models, not assumed.
 */
class PerformanceModelsTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_insights_performance.json")) {
            "sample_insights_performance.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes xg and shots estimates`() {
        val perf = AppJson.decodeFromString(InsightsPerformance.serializer(), loadSample())

        val xg = assertNotNullAndReturn(perf.homeXgEstimate)
        assertEquals(0.66, xg.xgFor, 0.0)
        assertEquals(1.8, xg.xgAgainst, 0.0)
        assertEquals(1, xg.actualGoalsFor)

        val shots = assertNotNullAndReturn(perf.homeShotsEstimate)
        assertEquals(22, shots.shotsFor)
        assertEquals(9, shots.shotsOnTargetFor)
    }

    @Test
    fun `decodes the full AdvancedStats object, including a negative Double field`() {
        val perf = AppJson.decodeFromString(InsightsPerformance.serializer(), loadSample())
        val stats = assertNotNullAndReturn(perf.homeAdvancedStats)

        assertEquals(364, stats.touchesInBoxFor)
        assertEquals(48.9, stats.possessionPctAvg!!, 0.0)
        assertEquals(52.7, stats.fieldTiltPct!!, 0.0)
        // A whole-number JSON literal (-2, no decimal point) still
        // decodes correctly into a Kotlin Double field.
        assertEquals(-2.0, stats.goalsPreventedFor!!, 0.0)
    }

    @Test
    fun `decodes null advanced-stat fields as null (source never reported them), not a crash`() {
        // Real backend shape after the null-not-structural-0 change:
        // unavailable_stats names the keys; their *_for/_against pairs
        // are JSON null. AppJson's SnakeCase naming strategy means keys
        // match Python asdict (snake_case). Must not throw on Int?.
        val json =
            """
            {
              "sample_size": 5,
              "red_cards_for": null,
              "red_cards_against": null,
              "through_balls_for": null,
              "through_balls_against": null,
              "yellow_cards_for": 8,
              "yellow_cards_against": 6,
              "fouls_for": 50,
              "fouls_against": 55,
              "xa_for": 0.4,
              "xa_against": 0.2,
              "corner_goals_for": 1,
              "corner_goals_against": 0,
              "penalty_goals_for": 0,
              "penalty_goals_against": 1,
              "free_kick_goals_for": 0,
              "free_kick_goals_against": 0,
              "non_penalty_xg_for": 1.1,
              "non_penalty_xg_against": 0.9,
              "set_piece_xg_for": 0.3,
              "set_piece_xg_against": 0.1,
              "penalties_awarded_for": 2,
              "penalties_awarded_against": 3,
              "unavailable_stats": ["red_cards", "through_balls"]
            }
            """.trimIndent()
        val stats = AppJson.decodeFromString(AdvancedStats.serializer(), json)

        assertNull(stats.redCardsFor)
        assertNull(stats.redCardsAgainst)
        assertNull(stats.throughBallsFor)
        assertEquals(8, stats.yellowCardsFor)
        assertEquals(listOf("red_cards", "through_balls"), stats.unavailableStats)
    }

    @Test
    fun `away_advanced_stats is null in this real sample and decodes as null, not a crash`() {
        val perf = AppJson.decodeFromString(InsightsPerformance.serializer(), loadSample())
        assertNull(perf.awayAdvancedStats)
    }

    @Test
    fun `decodes big chances, corners, and possession matchup`() {
        val perf = AppJson.decodeFromString(InsightsPerformance.serializer(), loadSample())

        val bigChances = assertNotNullAndReturn(perf.homeBigChancesEstimate)
        assertEquals(3, bigChances.bigChancesCreatedFor)

        val corners = assertNotNullAndReturn(perf.homeCornersEstimate)
        assertEquals(19, corners.cornersFor)

        val matchup = assertNotNullAndReturn(perf.homePossessionMatchup)
        assertNull(matchup.highOpponentPossessionPpg)
        assertEquals(0, matchup.highOpponentPossessionSampleSize)
        assertEquals(1.0, matchup.otherPpg!!, 0.0)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
