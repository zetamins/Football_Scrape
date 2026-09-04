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
        assertEquals(1, seasonStats.appearances)
        assertEquals(0, seasonStats.goals)
        assertEquals(0, seasonStats.assists)
        assertEquals(0, seasonStats.yellowCards)
        assertEquals(0, seasonStats.redCards)
        assertEquals(null, seasonStats.expectedGoals)
    }

    @Test
    fun `decodes each squad member's own defensive stats and recent-usage pattern`() {
        val profile = AppJson.decodeFromString(TeamProfileData.serializer(), loadProfileSample())
        val squad = assertNotNullAndReturn(profile.squad)

        val defensiveStats = assertNotNullAndReturn(squad[0].defensiveStats)
        assertEquals(0, defensiveStats.tacklesMade)
        assertEquals(0, defensiveStats.interceptions)
        assertEquals(0, defensiveStats.ballRecoveries)
        assertEquals(0, defensiveStats.clearances)
        assertEquals(null, defensiveStats.groundDuelSuccessPct)
        assertEquals(0, defensiveStats.chancesCreated)
        assertEquals(0, defensiveStats.shots)
        assertEquals(0, defensiveStats.shotsOnTarget)
        assertEquals(0, defensiveStats.passesCompleted)
        assertEquals(0, defensiveStats.foulsWon)
        assertEquals(0, defensiveStats.aerialDuelsWon)
        assertEquals(0, defensiveStats.goalsFromInsideBox)
        assertEquals(0, defensiveStats.goalsFromOutsideBox)
        assertEquals(null, defensiveStats.conversionRatePct)
        assertEquals(0, defensiveStats.shotsOffTarget)
        assertEquals(0, defensiveStats.passesAttempted)
        assertEquals(null, defensiveStats.passingAccuracyPct)
        assertEquals(0, defensiveStats.blockedShots)
        assertEquals(0, defensiveStats.takeOnsCompleted)
        assertEquals(0, defensiveStats.groundDuelsWon)

        val recentUsage = assertNotNullAndReturn(squad[0].recentUsage)
        assertEquals(20, recentUsage.matchesInSquad)
        assertEquals(13, recentUsage.starts)
        assertEquals(7, recentUsage.subAppearances)
        assertEquals(0, recentUsage.unusedBench)
        assertEquals(1130, recentUsage.totalMinutes)
        assertEquals(8, recentUsage.totalGoals)
        assertEquals(0, recentUsage.totalAssists)
        assertEquals(7.1522, recentUsage.totalXg, 0.0001)
        assertEquals(0.8743228999999999, recentUsage.totalXa, 0.0000001)
        assertEquals(37, recentUsage.totalShots)
        assertEquals(17, recentUsage.totalShotsOnTarget)
        assertEquals(0, recentUsage.totalTackles)
        assertEquals(0, recentUsage.totalInterceptions)
        assertEquals(9, recentUsage.totalFouls)
        assertEquals(10, recentUsage.totalKeyPasses)
        assertEquals(19, recentUsage.appearancesWithStats)
        assertEquals(6.69, recentUsage.avgRating!!, 0.0)
        // The 5 "per 90" fields all need an explicit @SerialName -- real
        // bug found while writing this test, fixed in SquadModels.kt: the
        // automatic SnakeCase strategy produces "goals_per90" (no
        // underscore before the digit), but this class's own real backend
        // JSON uses "goals_per_90" (WITH an underscore) -- a different
        // convention than RecentFormLeader's own goalsPer90, whose real
        // JSON happens to already match the automatic form. Every one of
        // these 5 fields silently decoded as null before the fix.
        assertEquals(0.64, recentUsage.goalsPer90!!, 0.0)
        assertEquals(0.0, recentUsage.assistsPer90!!, 0.0)
        assertEquals(0.57, recentUsage.xgPer90!!, 0.0)
        assertEquals(0.07, recentUsage.xaPer90!!, 0.0)
        assertEquals(0.8, recentUsage.keyPassesPer90!!, 0.0)
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
