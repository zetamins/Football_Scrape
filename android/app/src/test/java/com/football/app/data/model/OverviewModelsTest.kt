package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Decodes MatchOverview against real backend JSON (a trimmed copy of
 * backend/output/borussia-dortmund-2026-08-29T16-06-26-830Z.json's
 * `match` object, restricted to Overview-relevant keys -- see
 * resources/sample_match_overview.json), not synthetic/hand-written
 * data. Exists specifically to verify field-name mappings this session
 * was genuinely uncertain about (does JsonNamingStrategy.SnakeCase
 * reconstruct `temp_c`/`over_2_5_odds`/`home_xg` correctly from a
 * camelCase Kotlin property, or does it need an explicit @SerialName?)
 * empirically rather than by assumption.
 */
class OverviewModelsTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_match_overview.json")) {
            "sample_match_overview.json not found on the test classpath"
        }.bufferedReader().readText()

    @Test
    fun `decodes real match JSON into MatchOverview without error`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())

        assertEquals("Signal Iduna Park", overview.venueName)
        assertEquals("Dortmund", overview.venueCity)
        assertEquals(81365, overview.venueCapacity)
        assertEquals("Felix Zwayer", overview.referee)
    }

    @Test
    fun `weather_detail single-letter-suffix fields decode correctly (temp_c, precip_mm, feels_like_c)`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())
        val weather = assertNotNullAndReturn(overview.weatherDetail)

        assertEquals(21.0, weather.tempC)
        assertEquals(0.0, weather.precipMm)
        assertEquals(21.0, weather.feelsLikeC)
        assertEquals(55.0, weather.humidityPct)
    }

    @Test
    fun `referee_stats yellow_cards_per_game decodes as String, not a number`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())
        val stats = assertNotNullAndReturn(overview.refereeStats)

        assertEquals("4.6", stats.yellowCardsPerGame)
        assertEquals(527, stats.games)
        assertEquals(20.75, stats.foulsPerGame)
        // penalties_awarded and home_away_bias are null in this real sample
        assertNull(stats.penaltiesAwarded)
        assertNull(stats.homeAwayBias)
    }

    @Test
    fun `betting_odds over_2_5 and under_2_5 decode via explicit SerialName`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())
        val odds = assertNotNullAndReturn(overview.bettingOdds)

        assertEquals(1.47, odds.over25Odds)
        assertEquals(2.6, odds.under25Odds)
        assertEquals(1.31, odds.homeWinOdds)
    }

    @Test
    fun `team_standing goal_diff decodes as String`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())
        val standing = assertNotNullAndReturn(overview.homeTeamStanding)

        assertEquals("0", standing.goalDiff)
        assertEquals(9, standing.position)
        assertEquals(18, standing.totalTeams)
    }

    @Test
    fun `manager info, including nested recordAtClub, decodes correctly`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())
        val homeManager = assertNotNullAndReturn(overview.homeManager)
        val awayManager = assertNotNullAndReturn(overview.awayManager)

        assertEquals("Niko Kovač", homeManager.name)
        assertEquals("Croatia", homeManager.country)
        assertNull(homeManager.appointedDate)
        val homeRecord = assertNotNullAndReturn(homeManager.recordAtClub)
        assertEquals(43, homeRecord.played)

        assertEquals("Merlin Polzin", awayManager.name)
        assertEquals(false, awayManager.recentAppointment)
        val awayRecord = assertNotNullAndReturn(awayManager.recordAtClub)
        assertEquals(38.98, awayRecord.winPct)
    }

    @Test
    fun `head-to-head summary, streaks, and trimmed recent meetings decode correctly`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())
        val h2h = assertNotNullAndReturn(overview.headToHeadSummary)

        assertEquals(6, h2h.homeWins)
        assertEquals(2, h2h.awayWins)
        assertEquals(2, h2h.draws)
        assertEquals(6, overview.headToHeadStreaks?.size)

        val duel = assertNotNullAndReturn(overview.managerDuel)
        assertEquals(1, duel.homeWins)
        assertEquals(0, duel.awayWins)
        assertEquals(1, duel.draws)

        val meetings = assertNotNullAndReturn(overview.recentMeetings)
        assertEquals(1, meetings.size)
        assertEquals("3-2", meetings[0].scoreline)
        assertEquals("3-5-2", meetings[0].homeFormation)
        // home_xg decodes correctly with no @SerialName needed --
        // "home_xg" -> Kotlin "homeXg" round-trips through the naming
        // strategy without a digit/case-boundary ambiguity (unlike
        // over_2_5_odds above, which does need one).
        assertEquals(6.0, meetings[0].homeXg)
    }

    @Test
    fun `additional_notes list-of-objects decodes correctly`() {
        val overview = AppJson.decodeFromString(MatchOverview.serializer(), loadSample())
        val notes = assertNotNullAndReturn(overview.additionalNotes)

        assertEquals(3, notes.size)
        assert(notes[0].note.contains("SoccerDesk"))
    }

    private fun <T> assertNotNullAndReturn(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
