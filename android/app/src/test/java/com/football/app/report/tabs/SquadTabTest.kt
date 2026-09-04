package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.BenchRegular
import com.football.app.data.model.RecentFormLeader
import com.football.app.data.model.RoleFormEntry
import com.football.app.data.model.SquadMember
import com.football.app.data.model.SquadStrengthInfo
import com.football.app.data.model.TeamProfileData
import com.football.app.data.model.TopDefender
import com.football.app.data.model.TopPerformer
import com.football.app.data.model.TransferRecord
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class SquadTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty profile still renders the label but no sections`() {
        composeTestRule.setContent {
            SquadTab(profile = TeamProfileData(teamName = "Arsenal"), squadStrength = null, label = "Arsenal")
        }
        composeTestRule.onNodeWithText("Arsenal").assertExists()
        composeTestRule.onNodeWithText("Top performers").assertDoesNotExist()
    }

    @Test
    fun `top performers section renders scorers assists defenders and average age`() {
        composeTestRule.setContent {
            SquadTab(
                profile =
                    TeamProfileData(
                        teamName = "Arsenal",
                        averageAge = 25.8,
                        topScorers = listOf(TopPerformer(name = "Saka", goals = 12, assists = 5)),
                        topAssists = listOf(TopPerformer(name = "Odegaard", goals = 4, assists = 9)),
                        topDefenders = listOf(TopDefender(name = "Rice", tacklesMade = 40, interceptions = 20)),
                    ),
                squadStrength = null,
                label = "Arsenal",
            )
        }
        composeTestRule.onNodeWithText("Top performers").assertExists()
        composeTestRule.onNodeWithText("Top scorers").assertExists()
        composeTestRule.onNodeWithText("Top assists").assertExists()
        composeTestRule.onNodeWithText("Top defenders").assertExists()
        composeTestRule.onNodeWithText("Average age").assertExists()
    }

    @Test
    fun `availability section prefers key injuries over the full injuries list`() {
        composeTestRule.setContent {
            SquadTab(
                profile =
                    TeamProfileData(
                        teamName = "Arsenal",
                        injuries = listOf(SquadMember(name = "Timber")),
                        keyInjuries = listOf(SquadMember(name = "Saliba")),
                        missingMidfielders = listOf("Partey"),
                    ),
                squadStrength = null,
                label = "Arsenal",
            )
        }
        composeTestRule.onNodeWithText("Key injuries").assertExists()
        composeTestRule.onNodeWithText("Saliba").assertExists()
        composeTestRule.onNodeWithText("Missing").assertExists()
        composeTestRule.onNodeWithText("Partey").assertExists()
    }

    @Test
    fun `availability section falls back to the plain injuries list when there are no key injuries`() {
        composeTestRule.setContent {
            SquadTab(
                profile = TeamProfileData(teamName = "Arsenal", injuries = listOf(SquadMember(name = "Timber"))),
                squadStrength = null,
                label = "Arsenal",
            )
        }
        composeTestRule.onNodeWithText("Injuries").assertExists()
        composeTestRule.onNodeWithText("Timber").assertExists()
    }

    @Test
    fun `form section renders bench regulars and form leaders`() {
        composeTestRule.setContent {
            SquadTab(
                profile =
                    TeamProfileData(
                        teamName = "Arsenal",
                        benchRegulars = listOf(BenchRegular(name = "Havertz", matchesInSquad = 10, starts = 3, subAppearances = 6, unusedBench = 1)),
                        recentFormLeaders =
                            listOf(
                                RecentFormLeader(name = "Saka", goals = 5, assists = 2, xg = 3.4, xa = 1.9, keyPasses = 12, sampleSize = 10, avgRating = 7.6, goalsPer90 = 0.5),
                            ),
                    ),
                squadStrength = null,
                label = "Arsenal",
            )
        }
        composeTestRule.onNodeWithText("Recent form (last 20)").assertExists()
        composeTestRule.onNodeWithText("Bench regulars").assertExists()
        composeTestRule.onNodeWithText("Form leaders").assertExists()
    }

    @Test
    fun `form by role section renders midfielders and defenders`() {
        composeTestRule.setContent {
            SquadTab(
                profile =
                    TeamProfileData(
                        teamName = "Arsenal",
                        midfieldersForm = listOf(RoleFormEntry(name = "Rice", matchesInSquad = 10, starts = 10, totalMinutes = 900, goals = 2, assists = 3, xg = 1.5, xa = 2.1, keyPasses = 20)),
                        defendersForm = listOf(RoleFormEntry(name = "Saliba", matchesInSquad = 10, starts = 10, totalMinutes = 900, goals = 1, assists = 0, xg = 0.4, xa = 0.1, keyPasses = 2)),
                    ),
                squadStrength = null,
                label = "Arsenal",
            )
        }
        composeTestRule.onNodeWithText("Form by role (ranked by minutes)").assertExists()
        composeTestRule.onNodeWithText("Midfielders").assertExists()
        composeTestRule.onNodeWithText("Defenders").assertExists()
    }

    @Test
    fun `squad value section renders the total and the segmented breakdown legend`() {
        composeTestRule.setContent {
            SquadTab(
                profile = TeamProfileData(teamName = "Arsenal"),
                squadStrength =
                    SquadStrengthInfo(
                        totalValue = 1_200_000_000.0,
                        attackValue = 400_000_000.0,
                        midfieldValue = 350_000_000.0,
                        defenseValue = 300_000_000.0,
                        goalkeeperValue = 80_000_000.0,
                        availableValue = 1_000_000_000.0,
                    ),
                label = "Arsenal",
            )
        }
        composeTestRule.onNodeWithText("Squad value").assertExists()
        composeTestRule.onNodeWithText("Total (available)").assertExists()
    }

    @Test
    fun `transfers section renders at most the pills for recent transfers`() {
        composeTestRule.setContent {
            SquadTab(
                profile =
                    TeamProfileData(
                        teamName = "Arsenal",
                        recentTransfers =
                            listOf(
                                TransferRecord(playerName = "Martinelli", direction = "out", fromClub = "Arsenal", toClub = "Al-Hilal", date = "2026-09-03"),
                                TransferRecord(playerName = "Nelson", direction = "out", fromClub = "Arsenal", toClub = "Feyenoord"),
                            ),
                    ),
                squadStrength = null,
                label = "Arsenal",
            )
        }
        composeTestRule.onNodeWithText("Recent transfers").assertExists()
    }

    @Test
    fun `a fully populated squad tab composes without throwing`() {
        composeTestRule.setContent {
            SquadTab(
                profile =
                    TeamProfileData(
                        teamName = "Arsenal",
                        averageAge = 25.8,
                        topScorers = listOf(TopPerformer("Saka", 12, 5)),
                        keyInjuries = listOf(SquadMember(name = "Saliba")),
                        benchRegulars = listOf(BenchRegular("Havertz", 10, 3, 6, 1)),
                        midfieldersForm = listOf(RoleFormEntry("Rice", 10, 10, 900, 2, 3, 1.5, 2.1, 20)),
                        recentTransfers = listOf(TransferRecord("Martinelli", "out")),
                    ),
                squadStrength = SquadStrengthInfo(totalValue = 1_200_000_000.0, attackValue = 400_000_000.0),
                label = "Arsenal",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
