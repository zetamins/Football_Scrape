package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.LineupPlayer
import com.football.app.data.model.MatchLineups
import com.football.app.data.model.MissingPlayer
import com.football.app.data.model.PlayerOfTheMatch
import com.football.app.data.model.SetPieceGoalCounts
import com.football.app.data.model.SetPieceGoals
import com.football.app.data.model.ShotmapSideStats
import com.football.app.data.model.ShotmapStats
import com.football.app.data.model.TeamSeasonStats
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

private fun startingEleven(withStats: Boolean = false): List<LineupPlayer> =
    (1..11).map { n ->
        LineupPlayer(
            name = "Player $n",
            position = if (n == 1) "G" else if (n <= 5) "D" else if (n <= 9) "M" else "F",
            shirtNumber = n,
            minutesPlayed = if (withStats) 90 else null,
            rating = if (withStats) "7.2" else null,
        )
    }

@RunWith(RobolectricTestRunner::class)
class LineupsTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty match lineups renders no sections`() {
        composeTestRule.setContent {
            LineupsTab(lineups = MatchLineups(), homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Season stats").assertDoesNotExist()
        composeTestRule.onNodeWithText("Formations").assertDoesNotExist()
    }

    @Test
    fun `season stats section renders for both teams`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups =
                    MatchLineups(
                        homeTeamSeasonStats = TeamSeasonStats(goalsScored = 20, goalsConceded = 8, cleanSheets = 5, yellowCards = 22, redCards = 1),
                        awayTeamSeasonStats = TeamSeasonStats(goalsScored = 15, goalsConceded = 12, cleanSheets = 3, yellowCards = 30, redCards = 2),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Season stats").assertExists()
    }

    @Test
    fun `formations section renders shape and confirmation`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups = MatchLineups(homeFormation = "4-3-3", awayFormation = "4-2-3-1", lineupConfirmed = true),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Formations").assertExists()
        composeTestRule.onNodeWithText("Shape").assertExists()
    }

    @Test
    fun `pitch section renders the starting XI without a separate stats section pre-kickoff`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups = MatchLineups(homeFormation = "4-3-3", homeLineup = startingEleven(withStats = false)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal starting XI (4-3-3)").assertExists()
        composeTestRule.onNodeWithText("Arsenal starting XI (4-3-3) -- stats").assertDoesNotExist()
    }

    @Test
    fun `pitch section adds a stats section once real per-player stats exist`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups = MatchLineups(homeFormation = "4-3-3", homeLineup = startingEleven(withStats = true)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal starting XI (4-3-3) -- stats").assertExists()
        composeTestRule.onNodeWithText("#1 Player 1 (G)").assertExists()
    }

    @Test
    fun `bench section renders a pill per player`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups = MatchLineups(homeBench = listOf(LineupPlayer(name = "Havertz"), LineupPlayer(name = "Trossard"))),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal bench").assertExists()
        composeTestRule.onNodeWithText("Havertz").assertExists()
    }

    @Test
    fun `unavailable section renders suspended and missing players`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups =
                    MatchLineups(
                        homeSuspendedPlayers = listOf("Partey"),
                        homeMissingPlayers = listOf(MissingPlayer(name = "Saliba", description = "Back injury")),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal availability").assertExists()
        composeTestRule.onNodeWithText("Suspended").assertExists()
        composeTestRule.onNodeWithText("Partey").assertExists()
        composeTestRule.onNodeWithText("Saliba (Back injury)").assertExists()
    }

    @Test
    fun `match detail section renders player of the match set-piece and shotmap stats`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups =
                    MatchLineups(
                        playerOfTheMatch = PlayerOfTheMatch(name = "Saka", rating = "8.6"),
                        setPieceGoals =
                            SetPieceGoals(
                                home = SetPieceGoalCounts(corner = 1, penalty = 0, freeKick = 0),
                                away = SetPieceGoalCounts(corner = 0, penalty = 1, freeKick = 0),
                            ),
                        shotmapStats =
                            ShotmapStats(
                                home = ShotmapSideStats(nonPenaltyXg = 1.4, setPieceXg = 0.3, penaltiesAwarded = 0),
                                away = ShotmapSideStats(nonPenaltyXg = 0.9, setPieceXg = 0.2, penaltiesAwarded = 1),
                            ),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Match detail").assertExists()
        composeTestRule.onNodeWithText("Player of the match").assertExists()
    }

    @Test
    fun `a fully populated lineups tab composes without throwing`() {
        composeTestRule.setContent {
            LineupsTab(
                lineups =
                    MatchLineups(
                        homeFormation = "4-3-3",
                        awayFormation = "4-2-3-1",
                        lineupConfirmed = true,
                        homeLineup = startingEleven(withStats = true),
                        awayLineup = startingEleven(withStats = true),
                        homeBench = listOf(LineupPlayer(name = "Havertz")),
                        homeSuspendedPlayers = listOf("Partey"),
                        homeMissingPlayers = listOf(MissingPlayer(name = "Saliba")),
                        playerOfTheMatch = PlayerOfTheMatch(name = "Saka", rating = "8.6"),
                        homeTeamSeasonStats = TeamSeasonStats(20, 8, 5, 22, 1),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
