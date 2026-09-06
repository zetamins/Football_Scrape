package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.ClubStrengthRating
import com.football.app.data.model.EloRating
import com.football.app.data.model.HomeAdvantageInfo
import com.football.app.data.model.InsightsStandings
import com.football.app.data.model.OpponentRankRecord
import com.football.app.data.model.StandingsImpactInfo
import com.football.app.data.model.StandingsScenario
import com.football.app.data.model.StandingsTableRow
import com.football.app.data.model.StandingsZoneInfo
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class StandingsTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty insights object and no table renders no sections`() {
        composeTestRule.setContent {
            StandingsTab(insights = InsightsStandings(), standingsTable = null, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Strength ratings").assertDoesNotExist()
        composeTestRule.onNodeWithText("League table").assertDoesNotExist()
    }

    @Test
    fun `strength section renders elo and club-strength bars when both sides known`() {
        composeTestRule.setContent {
            StandingsTab(
                insights =
                    InsightsStandings(
                        homeEloRating = EloRating(elo = 1920.0, asOf = "2026-09-01"),
                        awayEloRating = EloRating(elo = 1880.0, asOf = "2026-09-01"),
                        homeClubStrength = ClubStrengthRating(overall = 90.3, attack = 85.6, defense = 93.4, rank = 1),
                        awayClubStrength = ClubStrengthRating(overall = 84.5, attack = 86.5, defense = 82.2, rank = 7),
                    ),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Strength ratings").assertExists()
        composeTestRule.onNodeWithText("Elo rating (computed from recent form)").assertExists()
        composeTestRule.onNodeWithText("Attack rating").assertExists()
    }

    @Test
    fun `table position section renders zone info for both teams`() {
        composeTestRule.setContent {
            StandingsTab(
                insights =
                    InsightsStandings(
                        homeStandingsZone = StandingsZoneInfo(position = 1, totalTeams = 20, zone = "Title race", pointsFromBoundary = 3, inTheMix = true),
                        awayStandingsZone = StandingsZoneInfo(position = 6, totalTeams = 20, zone = "Europe", pointsFromBoundary = 5),
                    ),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Table position").assertExists()
    }

    @Test
    fun `match-outcome impact section renders scenarios`() {
        composeTestRule.setContent {
            StandingsTab(
                insights =
                    InsightsStandings(
                        homeStandingsImpact =
                            StandingsImpactInfo(
                                currentPosition = 1,
                                currentPoints = 13,
                                scenarios = listOf(StandingsScenario(outcome = "win", newPoints = 16, newPosition = 1)),
                            ),
                        awayStandingsImpact =
                            StandingsImpactInfo(
                                currentPosition = 5,
                                currentPoints = 9,
                                scenarios = listOf(StandingsScenario(outcome = "loss", newPoints = 9, newPosition = 7)),
                            ),
                    ),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("If this match ends in...").assertExists()
        composeTestRule.onNodeWithText("win: #1").assertExists()
        composeTestRule.onNodeWithText("loss: #7").assertExists()
    }

    @Test
    fun `home advantage section renders for both teams`() {
        composeTestRule.setContent {
            StandingsTab(
                insights =
                    InsightsStandings(
                        homeAdvantage = HomeAdvantageInfo(homeWinRatePct = 65.0, awayWinRatePct = 30.0, strength = "strong"),
                        awayAdvantage = HomeAdvantageInfo(homeWinRatePct = 50.0, awayWinRatePct = 45.0, strength = "mild"),
                    ),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Home advantage").assertExists()
    }

    @Test
    fun `record vs higher-ranked opponents section renders for both teams`() {
        composeTestRule.setContent {
            StandingsTab(
                insights =
                    InsightsStandings(
                        homeOpponentRankRecord = OpponentRankRecord(sampleSize = 10, wins = 3, draws = 4, losses = 3),
                        awayOpponentRankRecord = OpponentRankRecord(sampleSize = 10, wins = 2, draws = 5, losses = 3),
                    ),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Record vs higher-ranked opponents").assertExists()
    }

    @Test
    fun `full league table section renders every row`() {
        composeTestRule.setContent {
            StandingsTab(
                insights = InsightsStandings(),
                standingsTable =
                    listOf(
                        StandingsTableRow(teamName = "Arsenal", position = 1, points = 13),
                        StandingsTableRow(teamName = "Chelsea", position = 5, points = 9),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("League table").assertExists()
        composeTestRule.onNodeWithText("#1 Arsenal").assertExists()
        composeTestRule.onNodeWithText("#5 Chelsea").assertExists()
    }

    @Test
    fun `strength section renders elo alone when club strength is unknown`() {
        composeTestRule.setContent {
            StandingsTab(
                insights = InsightsStandings(homeEloRating = EloRating(elo = 1920.0, asOf = "2026-09-01"), awayEloRating = EloRating(elo = 1880.0, asOf = "2026-09-01")),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Elo rating (computed from recent form)").assertExists()
        composeTestRule.onNodeWithText("Overall strength (statsultra.com)").assertDoesNotExist()
        composeTestRule.onNodeWithText("Arsenal 1920.0").assertExists()
    }

    @Test
    fun `table position section omits points-from-boundary when it is unknown`() {
        composeTestRule.setContent {
            StandingsTab(
                insights = InsightsStandings(homeStandingsZone = StandingsZoneInfo(position = 1, totalTeams = 20, zone = "Title race", pointsFromBoundary = null)),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("#1/20 (Title race)").assertExists()
    }

    @Test
    fun `home advantage section falls back to n-slash-a when strength and rates are unknown`() {
        composeTestRule.setContent {
            StandingsTab(
                insights = InsightsStandings(homeAdvantage = HomeAdvantageInfo(homeWinRatePct = null, awayWinRatePct = null, strength = null)),
                standingsTable = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("n/a (home n/a% / away n/a%)").assertExists()
    }

    @Test
    fun `a fully populated standings tab composes without throwing`() {
        composeTestRule.setContent {
            StandingsTab(
                insights =
                    InsightsStandings(
                        homeEloRating = EloRating(1920.0, "2026-09-01"),
                        awayEloRating = EloRating(1880.0, "2026-09-01"),
                        homeStandingsZone = StandingsZoneInfo(1, 20, "Title race"),
                        homeAdvantage = HomeAdvantageInfo(homeWinRatePct = 65.0),
                        homeOpponentRankRecord = OpponentRankRecord(10, 3, 4, 3),
                    ),
                standingsTable = listOf(StandingsTableRow("Arsenal", 1, 13)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
