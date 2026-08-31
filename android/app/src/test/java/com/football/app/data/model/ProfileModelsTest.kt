package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Decodes InsightsProfile against real backend JSON, merged from two
 * real reports (passing/aerial/goalkeeping/defensive-errors/set-piece
 * threat/direct-play from borussia-dortmund-...json; duel_vulnerabilities/
 * fullback_exposure -- both empty there -- from brentford-2026-08-28
 * T19-52-01-656Z.json, which has real populated values). See
 * resources/sample_insights_profile.json.
 */
class ProfileModelsTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_insights_profile.json")) {
            "sample_insights_profile.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes passing style and aerial estimates`() {
        val p = AppJson.decodeFromString(InsightsProfile.serializer(), loadSample())

        val passing = assertNotNullAndReturn(p.homePassingStyle)
        assertEquals(86.3, passing.passAccuracyPct!!, 0.0)
        assertEquals(4.2, passing.longBallSharePct!!, 0.0)

        val aerial = assertNotNullAndReturn(p.homeAerialEstimate)
        assertEquals(40, aerial.aerialDuelsWonFor)
    }

    @Test
    fun `decodes goalkeeping and defensive errors, with away_defensive_errors_estimate null`() {
        val p = AppJson.decodeFromString(InsightsProfile.serializer(), loadSample())

        val gk = assertNotNullAndReturn(p.homeGoalkeepingEstimate)
        assertEquals(73.5, gk.savePct!!, 0.0)
        assertEquals(15, gk.goalsConceded)

        assertNotNullAndReturn(p.homeDefensiveErrorsEstimate)
        assertNull(p.awayDefensiveErrorsEstimate)
    }

    @Test
    fun `decodes real populated duel vulnerabilities and fullback exposure lists`() {
        val p = AppJson.decodeFromString(InsightsProfile.serializer(), loadSample())

        val duels = assertNotNullAndReturn(p.homeDuelVulnerabilities)
        assertEquals(2, duels.size)
        assertEquals("Tarik Muharemović", duels[0].name)
        assertEquals(0.0, duels[0].groundDuelSuccessPct, 0.0)

        val fullbacks = assertNotNullAndReturn(p.homeFullbackExposure)
        assertEquals(1, fullbacks.size)
        assertEquals("Joe Rodon", fullbacks[0].name)
        assertEquals(1, fullbacks[0].chancesCreated)
    }

    @Test
    fun `decodes set-piece threat and direct-play exposure flags`() {
        val p = AppJson.decodeFromString(InsightsProfile.serializer(), loadSample())

        val setPiece = assertNotNullAndReturn(p.homeSetPieceThreat)
        assertEquals(4.75, setPiece.cornersPerGame!!, 0.0)
        assertEquals(false, setPiece.elevated)
        assertNull(p.awaySetPieceThreat)

        val directPlay = assertNotNullAndReturn(p.awayDirectPlayExposure)
        assertEquals(7.0, directPlay.longBallSharePct!!, 0.0)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
