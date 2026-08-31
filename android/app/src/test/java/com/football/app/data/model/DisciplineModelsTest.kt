package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Decodes InsightsDiscipline against real backend JSON, merged from two
 * real reports (card discipline/venue-split/fouls from
 * sunderland-2026-08-29T22-51-11-993Z.json; card_risks/referee_card_
 * risk_note -- both empty in the Sunderland sample -- from
 * borussia-dortmund-2026-08-29T16-06-26-830Z.json, which has real
 * populated values for both). See resources/sample_insights_discipline.json.
 */
class DisciplineModelsTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_insights_discipline.json")) {
            "sample_insights_discipline.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes card discipline and venue split, including nulls for an unrepresented venue`() {
        val d = AppJson.decodeFromString(InsightsDiscipline.serializer(), loadSample())

        val home = assertNotNullAndReturn(d.homeCardDiscipline)
        assertEquals(3.0, home.yellowPerGame, 0.0)
        assertTrue(home.elevatedRisk)

        val split = assertNotNullAndReturn(d.homeCardDisciplineVenueSplit)
        assertEquals(0, split.atHomeSampleSize)
        assertNull(split.atHomeYellowPerGame)
        assertEquals(2, split.awaySampleSize)
        assertEquals(2.0, split.awayYellowPerGame!!, 0.0)
    }

    @Test
    fun `decodes fouls estimate`() {
        val d = AppJson.decodeFromString(InsightsDiscipline.serializer(), loadSample())
        val fouls = assertNotNullAndReturn(d.homeFoulsEstimate)
        assertEquals(23, fouls.foulsCommittedFor)
        assertEquals(30, fouls.foulsCommittedAgainst)
    }

    @Test
    fun `decodes populated card_risks and referee_card_risk_note with nested flagged players`() {
        val d = AppJson.decodeFromString(InsightsDiscipline.serializer(), loadSample())

        val risks = assertNotNullAndReturn(d.homeCardRisks)
        assertEquals(1, risks.size)
        assertEquals("Ramy Bensebaini", risks[0].name)
        assertTrue(risks[0].priorDismissal)

        val note = assertNotNullAndReturn(d.refereeCardRiskNote)
        assertEquals("Felix Zwayer", note.refereeName)
        assertTrue(note.elevatedCardReferee)
        assertEquals(1, note.flaggedPlayers.size)
        assertEquals("home", note.flaggedPlayers[0].side)
    }

    @Test
    fun `empty card_risks list decodes as empty, not null`() {
        val d = AppJson.decodeFromString(InsightsDiscipline.serializer(), loadSample())
        assertNotNull(d.awayCardRisks)
        assertEquals(0, d.awayCardRisks!!.size)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
