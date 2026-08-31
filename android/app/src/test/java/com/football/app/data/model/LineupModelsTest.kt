package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

/**
 * Decodes MatchLineups against real backend JSON (a trimmed copy of
 * backend/output/sunderland-2026-08-29T22-51-11-993Z.json's `match`
 * object -- see resources/sample_match_lineups.json).
 *
 * Note: this sample's set_piece_goals/shotmap_stats/player_of_the_match
 * are present (zero-filled/populated) even though match.status is
 * "notstarted" -- report.py's current source (_prune_unplayed_match_
 * fields, verified directly) prunes these to absent for an unplayed
 * match, so this local sample predates that fix and isn't representative
 * of what the real app will see pre-kickoff. Still valid for what this
 * test actually checks: that the Kotlin model's SHAPE decodes these
 * nested objects correctly when they ARE present, independent of
 * report.py's separate pruning decision about WHEN they're present.
 */
class LineupModelsTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_match_lineups.json")) {
            "sample_match_lineups.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes formations, confirmation flag, and lineup identity fields`() {
        val lineups = AppJson.decodeFromString(MatchLineups.serializer(), loadSample())

        assertEquals("4-2-3-1", lineups.homeFormation)
        assertEquals("4-2-3-1", lineups.awayFormation)
        assertEquals(false, lineups.lineupConfirmed)

        val homeLineup = assertNotNullAndReturn(lineups.homeLineup)
        assertEquals(3, homeLineup.size)
        assertEquals("Robin Roefs", homeLineup[0].name)
        assertEquals("G", homeLineup[0].position)
        assertEquals(22, homeLineup[0].shirtNumber)
        // Outcome fields absent from a pre-kickoff lineup entry --
        // decodes as null, not a crash.
        assertEquals(null, homeLineup[0].minutesPlayed)
        assertEquals(null, homeLineup[0].rating)
    }

    @Test
    fun `decodes suspended and missing players`() {
        val lineups = AppJson.decodeFromString(MatchLineups.serializer(), loadSample())

        assertEquals(listOf("Dayann Methalie"), lineups.homeSuspendedPlayers)
        assertEquals(null, lineups.awaySuspendedPlayers)

        val missing = assertNotNullAndReturn(lineups.homeMissingPlayers)
        assertEquals(2, missing.size)
        assertEquals("Dayann Methalie", missing[0].name)
        assertEquals("yellow_card_accumulation_suspension", missing[0].description)
    }

    @Test
    fun `decodes team season stats`() {
        val lineups = AppJson.decodeFromString(MatchLineups.serializer(), loadSample())
        val stats = assertNotNullAndReturn(lineups.homeTeamSeasonStats)

        assertEquals(1, stats.goalsScored)
        assertEquals(2, stats.goalsConceded)
        assertEquals(62.0, stats.averageBallPossession)
    }

    @Test
    fun `decodes set_piece_goals, shotmap_stats, and player_of_the_match nested shapes`() {
        val lineups = AppJson.decodeFromString(MatchLineups.serializer(), loadSample())

        val potm = assertNotNullAndReturn(lineups.playerOfTheMatch)
        assertEquals("Josh King", potm.name)
        assertEquals("7.9", potm.rating)

        val setPieces = assertNotNullAndReturn(lineups.setPieceGoals)
        assertEquals(0, setPieces.home.corner)

        val shotmap = assertNotNullAndReturn(lineups.shotmapStats)
        assertEquals(0.0, shotmap.home.nonPenaltyXg, 0.0)
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
