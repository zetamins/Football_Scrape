package com.football.app.components

import org.junit.Assert.assertEquals
import org.junit.Test

class TeamBadgeTest {
    @Test
    fun `two-word team name uses first letter of each word`() {
        assertEquals("MU", initialsFor("Manchester United"))
        assertEquals("BS", initialsFor("Borussia Sud"))
    }

    @Test
    fun `single-word team name uses its first two letters`() {
        assertEquals("BR", initialsFor("Brentford"))
    }

    @Test
    fun `three-plus-word name still only uses the first two words`() {
        assertEquals("BM", initialsFor("Bayern Munich FC"))
    }

    @Test
    fun `extra whitespace is ignored`() {
        assertEquals("MU", initialsFor("  Manchester   United  "))
    }

    @Test
    fun `blank name falls back to a placeholder rather than crashing`() {
        assertEquals("?", initialsFor(""))
        assertEquals("?", initialsFor("   "))
    }
}
