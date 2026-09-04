package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.DirectPlayExposureFlag
import com.football.app.data.model.DuelVulnerability
import com.football.app.data.model.FullbackExposureInfo
import com.football.app.data.model.InsightsProfile
import com.football.app.data.model.SeasonAerialEstimate
import com.football.app.data.model.SeasonDefensiveErrorsEstimate
import com.football.app.data.model.SeasonGoalkeepingEstimate
import com.football.app.data.model.SeasonPassingStyleEstimate
import com.football.app.data.model.SetPieceThreatFlag
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ProfileTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty insights object renders no sections`() {
        composeTestRule.setContent {
            ProfileTab(insights = InsightsProfile(), homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Style profile").assertDoesNotExist()
        composeTestRule.onNodeWithText("Passing").assertDoesNotExist()
    }

    @Test
    fun `style radar renders once pass accuracy, aerial, and goalkeeping axes are all present`() {
        composeTestRule.setContent {
            ProfileTab(
                insights =
                    InsightsProfile(
                        homePassingStyle = SeasonPassingStyleEstimate(10, 500, 420, 84.0, 40, 8.0),
                        awayPassingStyle = SeasonPassingStyleEstimate(10, 480, 380, 79.2, 55, 11.5),
                        homeAerialEstimate = SeasonAerialEstimate(10, 45, 30),
                        awayAerialEstimate = SeasonAerialEstimate(10, 38, 42),
                        homeGoalkeepingEstimate = SeasonGoalkeepingEstimate(10, 28, 35, 80.0, 7),
                        awayGoalkeepingEstimate = SeasonGoalkeepingEstimate(10, 22, 30, 73.3, 8),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Style profile").assertExists()
        composeTestRule.onNodeWithText("Passing").assertExists()
        composeTestRule.onNodeWithText("Aerial & goalkeeping").assertExists()
    }

    @Test
    fun `passing section falls back to plain rows when only one side has full accuracy`() {
        composeTestRule.setContent {
            ProfileTab(
                insights = InsightsProfile(homePassingStyle = SeasonPassingStyleEstimate(10, 500, 420, null, 40, 8.0)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Passing").assertExists()
    }

    @Test
    fun `style radar omits the aerial and goalkeeping axes when only one side is known`() {
        // aerialAxis()/goalkeepingAxis() both return null unless BOTH
        // sides are present -- the style radar still renders (via the
        // pass-accuracy axes below), just without those two, but that
        // null-returning branch itself was never reached before.
        composeTestRule.setContent {
            ProfileTab(
                insights =
                    InsightsProfile(
                        homePassingStyle = SeasonPassingStyleEstimate(10, 500, 420, 84.0, 40, 8.0),
                        awayPassingStyle = SeasonPassingStyleEstimate(10, 480, 380, 79.2, 55, 11.5),
                        homeAerialEstimate = SeasonAerialEstimate(10, 45, 30),
                        homeGoalkeepingEstimate = SeasonGoalkeepingEstimate(10, 28, 35, 80.0, 7),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Style profile").assertExists()
    }

    @Test
    fun `defensive errors section renders bar comparison when both sides known`() {
        composeTestRule.setContent {
            ProfileTab(
                insights =
                    InsightsProfile(
                        homeDefensiveErrorsEstimate = SeasonDefensiveErrorsEstimate(10, 4, 6),
                        awayDefensiveErrorsEstimate = SeasonDefensiveErrorsEstimate(10, 6, 5),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Defensive errors").assertExists()
    }

    @Test
    fun `defensive errors section falls back to a home-only row when only home is known`() {
        composeTestRule.setContent {
            ProfileTab(
                insights = InsightsProfile(homeDefensiveErrorsEstimate = SeasonDefensiveErrorsEstimate(10, 4, 6)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Defensive errors").assertExists()
        composeTestRule.onNodeWithText("4 for / 6 against").assertExists()
    }

    @Test
    fun `defensive errors section falls back to an away-only row when only away is known`() {
        composeTestRule.setContent {
            ProfileTab(
                insights = InsightsProfile(awayDefensiveErrorsEstimate = SeasonDefensiveErrorsEstimate(10, 6, 5)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Defensive errors").assertExists()
        composeTestRule.onNodeWithText("6 for / 5 against").assertExists()
    }

    @Test
    fun `risk section renders duel vulnerabilities and exposed fullbacks pills`() {
        composeTestRule.setContent {
            ProfileTab(
                insights =
                    InsightsProfile(
                        homeDuelVulnerabilities = listOf(DuelVulnerability(name = "Timber", groundDuelSuccessPct = 38.0)),
                        awayDuelVulnerabilities = listOf(DuelVulnerability(name = "Colwill", groundDuelSuccessPct = 42.0)),
                        homeFullbackExposure = listOf(FullbackExposureInfo(name = "Zinchenko", chancesCreated = 2, groundDuelSuccessPct = 35.0)),
                        awayFullbackExposure = listOf(FullbackExposureInfo(name = "Chilwell", chancesCreated = 3, groundDuelSuccessPct = 40.0)),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Risk").assertExists()
        composeTestRule.onNodeWithText("Arsenal duel risk").assertExists()
        composeTestRule.onNodeWithText("Chelsea duel risk").assertExists()
        composeTestRule.onNodeWithText("Arsenal exposed fullbacks").assertExists()
        composeTestRule.onNodeWithText("Chelsea exposed fullbacks").assertExists()
    }

    @Test
    fun `threat section renders set-piece and direct-play rows with elevated coloring`() {
        composeTestRule.setContent {
            ProfileTab(
                insights =
                    InsightsProfile(
                        homeSetPieceThreat = SetPieceThreatFlag(cornersPerGame = 6.5, opponentAerialWinPct = 48.0, elevated = true),
                        awaySetPieceThreat = SetPieceThreatFlag(cornersPerGame = 4.2, opponentAerialWinPct = 51.0, elevated = false),
                        awayDirectPlayExposure = DirectPlayExposureFlag(longBallSharePct = 12.0, opponentAerialWinPct = 55.0, elevated = true),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Set-piece & direct-play tendencies").assertExists()
        composeTestRule.onNodeWithText("Arsenal set-piece threat").assertExists()
        composeTestRule.onNodeWithText("Chelsea set-piece threat").assertExists()
        composeTestRule.onNodeWithText("Chelsea direct-play exposure").assertExists()
    }

    @Test
    fun `a fully populated profile tab composes without throwing`() {
        composeTestRule.setContent {
            ProfileTab(
                insights =
                    InsightsProfile(
                        homePassingStyle = SeasonPassingStyleEstimate(10, 500, 420, 84.0, 40, 8.0),
                        awayPassingStyle = SeasonPassingStyleEstimate(10, 480, 380, 79.2, 55, 11.5),
                        homeAerialEstimate = SeasonAerialEstimate(10, 45, 30),
                        awayAerialEstimate = SeasonAerialEstimate(10, 38, 42),
                        homeGoalkeepingEstimate = SeasonGoalkeepingEstimate(10, 28, 35, 80.0, 7),
                        awayGoalkeepingEstimate = SeasonGoalkeepingEstimate(10, 22, 30, 73.3, 8),
                        homeDefensiveErrorsEstimate = SeasonDefensiveErrorsEstimate(10, 4, 6),
                        awayDefensiveErrorsEstimate = SeasonDefensiveErrorsEstimate(10, 6, 5),
                        homeDuelVulnerabilities = listOf(DuelVulnerability("Timber", 38.0)),
                        homeSetPieceThreat = SetPieceThreatFlag(cornersPerGame = 6.5, opponentAerialWinPct = 48.0, elevated = true),
                        homeDirectPlayExposure = DirectPlayExposureFlag(longBallSharePct = 12.0, opponentAerialWinPct = 55.0, elevated = false),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
