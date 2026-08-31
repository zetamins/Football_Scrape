package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

/**
 * Decodes FormSummary against real backend JSON
 * (borussia-dortmund-2026-08-29T16-06-26-830Z.json's `form` object,
 * trimmed to 2 entries per match-result list -- see
 * resources/sample_form.json). This is the largest single object
 * decoded in the app (34 top-level fields); this test spot-checks
 * across the whole shape rather than exhaustively, since every field
 * name/type risk class (nested lists, nested objects, digit-adjacent
 * names) is already covered by the other *ModelsTest files.
 */
class FormModelsTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_form.json")) {
            "sample_form.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes last-N match result lists`() {
        val form = AppJson.decodeFromString(FormSummary.serializer(), loadSample())

        assertEquals(2, form.last5Overall.size)
        val first = form.last5Overall[0]
        assertEquals("FC Bayern München", first.opponent)
        assertEquals("L", first.result)
        assertEquals("1-2", first.scoreline)
        assertEquals(1, first.margin)
    }

    @Test
    fun `decodes streak, momentum, and rate fields`() {
        val form = AppJson.decodeFromString(FormSummary.serializer(), loadSample())

        val streak = assertNotNullAndReturn(form.currentStreak)
        assertEquals("L", streak.result)
        assertEquals(1, streak.count)

        val momentum = assertNotNullAndReturn(form.momentum)
        assertEquals(0.67, momentum.recentPpg, 0.0)
        assertEquals("stable", momentum.trend)

        assertEquals(1.4, form.pointsPerGame!!, 0.0)
    }

    @Test
    fun `decodes next5_with_gaps, form_by_competition, and both venue split shapes`() {
        val form = AppJson.decodeFromString(FormSummary.serializer(), loadSample())

        assertEquals("Hamburger SV", form.next5WithGaps[0].opponent)
        assertEquals(7, form.next5WithGaps[0].daysSincePrevious)

        assertEquals("Supercup", form.formByCompetition[0].competition)

        val venueSplit = assertNotNullAndReturn(form.venueSplitForm)
        assertEquals(4, venueSplit.homeWins)

        val detailed = assertNotNullAndReturn(form.detailedVenueSplit)
        assertEquals(17.72, detailed.home.xgFor, 0.0)
        assertEquals(52.1, detailed.home.possessionPctAvg!!, 0.0)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
