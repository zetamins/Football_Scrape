package com.football.app.data.model

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * MatchSummary is otherwise only ever constructed via
 * MatchSummary.serializer() decode (see ReportScreenTest.kt, exercised
 * many times over) -- kotlinx.serialization generates a separate
 * mask-aware constructor for that path, distinct from the plain
 * 2-arg constructor a direct `MatchSummary(a, b)` call uses, which
 * nothing in the app calls directly. This closes that specific gap.
 */
class MatchSummaryTest {
    @Test
    fun `equal instances constructed directly are equal`() {
        val a = MatchSummary(homeTeam = "Arsenal", awayTeam = "Chelsea")
        val b = MatchSummary(homeTeam = "Arsenal", awayTeam = "Chelsea")
        assertEquals(a, b)
        assertEquals(a.hashCode(), b.hashCode())
        assertEquals("Arsenal", a.homeTeam)
        assertEquals("Chelsea", a.awayTeam)
    }
}
