package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Decodes InsightsStandings and MatchStandingsTable against real backend
 * JSON (borussia-dortmund-2026-08-29T16-06-26-830Z.json's `insights`
 * subset and `match.standings_table`). Also verifies a design-doc
 * assumption this session corrected: StandingsTableRow only has
 * team_name/position/points -- no played/W-D-L/GD, confirmed against
 * types.py directly, not the richer shape originally assumed in
 * frontend/DESIGN.md before checking.
 */
class StandingsModelsTest {
    private fun loadInsightsSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_insights_standings.json")) {
            "sample_insights_standings.json not found on the test classpath"
        }.bufferedReader().readText()

    private fun loadTableSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_match_standings_table.json")) {
            "sample_match_standings_table.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes elo rating and club strength, including a null rank`() {
        val s = AppJson.decodeFromString(InsightsStandings.serializer(), loadInsightsSample())

        val elo = assertNotNullAndReturn(s.homeEloRating)
        assertEquals(1510.9, elo.elo, 0.0)
        assertNull(elo.rank)
        assertEquals("2026-08-29", elo.asOf)

        val strength = assertNotNullAndReturn(s.homeClubStrength)
        assertEquals(80.1, strength.overall, 0.0)
        assertEquals(18, strength.rank)
    }

    @Test
    fun `decodes standings zone and impact scenarios`() {
        val s = AppJson.decodeFromString(InsightsStandings.serializer(), loadInsightsSample())

        val zone = assertNotNullAndReturn(s.homeStandingsZone)
        assertEquals("midtable", zone.zone)
        assertEquals(true, zone.inTheMix)

        val impact = assertNotNullAndReturn(s.homeStandingsImpact)
        assertEquals(3, impact.scenarios.size)
        assertEquals("win", impact.scenarios[0].outcome)
        assertEquals(5, impact.scenarios[0].newPosition)
    }

    @Test
    fun `decodes home advantage and opponent rank record`() {
        val s = AppJson.decodeFromString(InsightsStandings.serializer(), loadInsightsSample())

        val advantage = assertNotNullAndReturn(s.homeAdvantage)
        assertEquals("strong", advantage.strength)
        assertEquals(20.0, advantage.gapPct!!, 0.0)

        val rankRecord = assertNotNullAndReturn(s.homeOpponentRankRecord)
        assertEquals(2, rankRecord.wins)
    }

    @Test
    fun `decodes standings_table rows with only team_name, position, points`() {
        val t = AppJson.decodeFromString(MatchStandingsTable.serializer(), loadTableSample())
        val rows = assertNotNullAndReturn(t.standingsTable)

        assertEquals(3, rows.size)
        assertEquals("FC Bayern München", rows[0].teamName)
        assertEquals(1, rows[0].position)
        assertEquals(3, rows[0].points)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
