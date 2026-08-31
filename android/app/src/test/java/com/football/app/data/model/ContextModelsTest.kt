package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Decodes InsightsContext against real backend JSON
 * (borussia-dortmund-2026-08-29T16-06-26-830Z.json's `insights` subset
 * -- see resources/sample_insights_context.json). Specifically checks
 * `experienceH2h` (a digit-in-camelCase name, the same risk class as
 * over_2_5_odds in OverviewModelsTest) round-trips correctly against
 * the real `experience_h2h` JSON key via the SnakeCase strategy alone.
 */
class ContextModelsTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_insights_context.json")) {
            "sample_insights_context.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes rest comparison and rest performance`() {
        val c = AppJson.decodeFromString(InsightsContext.serializer(), loadSample())

        val rest = assertNotNullAndReturn(c.restComparison)
        assertEquals(7, rest.ownRestDays)
        assertEquals("own", rest.moreRested)

        val perf = assertNotNullAndReturn(c.homeRestPerformance)
        assertEquals(1.85, perf.longRestPpg!!, 0.0)
    }

    @Test
    fun `decodes rotation info with all 10 fields including preceding_result`() {
        val c = AppJson.decodeFromString(InsightsContext.serializer(), loadSample())
        val rotation = assertNotNullAndReturn(c.homeRotation)

        assertEquals(1, rotation.changedPlayers)
        assertEquals(false, rotation.formationChanged)
        assertEquals(3, rotation.lastDefenderCount)
        assertEquals("D", rotation.precedingResult)
    }

    @Test
    fun `experienceH2h maps correctly to the real experience_h2h key`() {
        val c = AppJson.decodeFromString(InsightsContext.serializer(), loadSample())
        val h2h = assertNotNullAndReturn(c.experienceH2h)

        assertEquals("even", h2h.moreExperienced)
        assertEquals("own", h2h.h2hLeader)
        assertNull(h2h.aligned)
    }

    @Test
    fun `decodes travel info and presence entries`() {
        val c = AppJson.decodeFromString(InsightsContext.serializer(), loadSample())

        val travel = assertNotNullAndReturn(c.travelInfo)
        assertEquals(false, travel.homeTraveling)
        assertEquals("Germany", travel.venueCountry)

        val presence = assertNotNullAndReturn(c.homePresence)
        assertEquals(4, presence.size)
        assertEquals("Serhou Guirassy", presence[0].name)
        assertEquals(true, presence[0].starting)
    }

    @Test
    fun `decodes bench info and null losing-streak context`() {
        val c = AppJson.decodeFromString(InsightsContext.serializer(), loadSample())

        val bench = assertNotNullAndReturn(c.homeBenchInfo)
        assertEquals(9, bench.benchSize)
        assertEquals(92285000.0, bench.benchTotalMarketValue!!, 0.0)

        assertNull(c.homeLosingStreakContext)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
