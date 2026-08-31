package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

/**
 * Decodes TeamProfileData and InsightsSquadStrength against real backend
 * JSON (borussia-dortmund-2026-08-29T16-06-26-830Z.json). Specifically
 * verifies `goalsPer90`/`assistsPer90` (digit-adjacent camelCase, same
 * risk class as over_2_5_odds) round-trip correctly against the real
 * `goals_per90`/`assists_per90` JSON keys via the SnakeCase strategy.
 */
class SquadModelsTest {
    private fun loadProfileSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_team_profile.json")) {
            "sample_team_profile.json not found on the test classpath"
        }.bufferedReader().readText()

    private fun loadStrengthSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_insights_squad_strength.json")) {
            "sample_insights_squad_strength.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes squad members with nested season and defensive stats`() {
        val profile = AppJson.decodeFromString(TeamProfileData.serializer(), loadProfileSample())

        assertEquals("Borussia Dortmund", profile.teamName)
        val squad = assertNotNullAndReturn(profile.squad)
        assertEquals(2, squad.size)
        assertEquals("Serhou Guirassy", squad[0].name)
        assertEquals("F", squad[0].role)
        assertEquals(34000000.0, squad[0].marketValue!!, 0.0)

        val seasonStats = assertNotNullAndReturn(squad[0].seasonStats)
        assertEquals(6.3, seasonStats.rating!!, 0.0)
    }

    @Test
    fun `decodes injuries as SquadMember lists, and missing-by-position string lists`() {
        val profile = AppJson.decodeFromString(TeamProfileData.serializer(), loadProfileSample())

        val injuries = assertNotNullAndReturn(profile.injuries)
        assertEquals("Carney Chukwuemeka", injuries[0].name)
        assertEquals("Muscle Injury (dayToDay)", injuries[0].injury)

        assertEquals(listOf("Carney Chukwuemeka"), profile.missingMidfielders)
        assertEquals(listOf<String>(), profile.missingAttackers)
    }

    @Test
    fun `decodes top scorers, bench regulars, and recent transfers`() {
        val profile = AppJson.decodeFromString(TeamProfileData.serializer(), loadProfileSample())

        val topScorers = assertNotNullAndReturn(profile.topScorers)
        assertEquals("Fábio Silva", topScorers[0].name)
        assertEquals(1, topScorers[0].goals)

        val bench = assertNotNullAndReturn(profile.benchRegulars)
        assertEquals(20, bench[0].matchesInSquad)

        val transfers = assertNotNullAndReturn(profile.recentTransfers)
        assertEquals("in", transfers[0].direction)
    }

    @Test
    fun `goalsPer90 and assistsPer90 map correctly to real digit-adjacent JSON keys`() {
        val profile = AppJson.decodeFromString(TeamProfileData.serializer(), loadProfileSample())
        val leaders = assertNotNullAndReturn(profile.recentFormLeaders)

        assertEquals("Serhou Guirassy", leaders[0].name)
        assertEquals(0.64, leaders[0].goalsPer90!!, 0.0)
        assertEquals(0.0, leaders[0].assistsPer90!!, 0.0)
    }

    @Test
    fun `decodes squad strength value breakdown`() {
        val strength = AppJson.decodeFromString(InsightsSquadStrength.serializer(), loadStrengthSample())
        val home = assertNotNullAndReturn(strength.homeSquadStrength)

        assertEquals(527260000.0, home.totalValue!!, 0.0)
        assertEquals(98310000.0, home.attackValue!!, 0.0)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
