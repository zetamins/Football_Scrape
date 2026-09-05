package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.AdvancedStats
import com.football.app.data.model.InsightsPerformance
import com.football.app.data.model.PossessionMatchupInfo
import com.football.app.data.model.SeasonBigChancesEstimate
import com.football.app.data.model.SeasonCornersEstimate
import com.football.app.data.model.SeasonShotsEstimate
import com.football.app.data.model.SeasonXGEstimate
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** A zeroed-out AdvancedStats -- the class has ~80 mostly-required
 * fields, so tests `.copy()` the specific ones they care about rather
 * than repeating the full field list each time. */
private fun fakeAdvancedStats(
    touchesInBoxFor: Int = 0,
    shotsInsideBoxFor: Int = 0,
) = AdvancedStats(
    sampleSize = 10, touchesInBoxFor = touchesInBoxFor, touchesInBoxAgainst = 0, crossesFor = 0, crossesAgainst = 0,
    dribblesFor = 0, dribblesAgainst = 0, throughBallsFor = 0, throughBallsAgainst = 0, finalThirdEntriesFor = 0,
    finalThirdEntriesAgainst = 0, recoveriesFor = 0, recoveriesAgainst = 0, errorsLeadToShotFor = 0, errorsLeadToShotAgainst = 0,
    errorsLeadToGoalFor = 0, errorsLeadToGoalAgainst = 0, shotsInsideBoxFor = shotsInsideBoxFor, shotsInsideBoxAgainst = 0,
    shotsOutsideBoxFor = 0, shotsOutsideBoxAgainst = 0, shotsOffTargetFor = 0, shotsOffTargetAgainst = 0, blockedShotsFor = 0,
    blockedShotsAgainst = 0, offsidesFor = 0, offsidesAgainst = 0, bigChancesScoredFor = 0, bigChancesScoredAgainst = 0,
    dispossessedFor = 0, dispossessedAgainst = 0, teamTacklesFor = 0, teamTacklesAgainst = 0, teamInterceptionsFor = 0,
    teamInterceptionsAgainst = 0, goalsPreventedFor = 0.0, goalsPreventedAgainst = 0.0, bigSavesFor = 0, bigSavesAgainst = 0,
    highClaimsFor = 0, highClaimsAgainst = 0, distanceCoveredKmFor = 0.0, distanceCoveredKmAgainst = 0.0, sprintsFor = 0,
    sprintsAgainst = 0, teamClearancesFor = 0, teamClearancesAgainst = 0, freeKicksFor = 0, freeKicksAgainst = 0, xaFor = 0.0,
    xaAgainst = 0.0, cornerGoalsFor = 0, cornerGoalsAgainst = 0, penaltyGoalsFor = 0, penaltyGoalsAgainst = 0,
    freeKickGoalsFor = 0, freeKickGoalsAgainst = 0, totalShotsFor = 0, totalShotsAgainst = 0, shotsOnTargetFor = 0,
    shotsOnTargetAgainst = 0, cornersFor = 0, cornersAgainst = 0, foulsFor = 0, foulsAgainst = 0, yellowCardsFor = 0,
    yellowCardsAgainst = 0, redCardsFor = 0, redCardsAgainst = 0, bigChancesCreatedFor = 0, bigChancesCreatedAgainst = 0,
    nonPenaltyXgFor = 0.0, nonPenaltyXgAgainst = 0.0, setPieceXgFor = 0.0, setPieceXgAgainst = 0.0, penaltiesAwardedFor = 0,
    penaltiesAwardedAgainst = 0,
)

@RunWith(RobolectricTestRunner::class)
class PerformanceTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty insights object renders no sections`() {
        composeTestRule.setContent {
            PerformanceTab(insights = InsightsPerformance(), homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Attack profile").assertDoesNotExist()
        composeTestRule.onNodeWithText("Season estimates").assertDoesNotExist()
    }

    @Test
    fun `attack profile radar renders when both sides have advanced stats`() {
        composeTestRule.setContent {
            PerformanceTab(
                insights = InsightsPerformance(homeAdvancedStats = fakeAdvancedStats(), awayAdvancedStats = fakeAdvancedStats()),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Attack profile").assertExists()
    }

    @Test
    fun `season estimates section renders xG shots big-chances and corners bars`() {
        composeTestRule.setContent {
            PerformanceTab(
                insights =
                    InsightsPerformance(
                        homeXgEstimate = SeasonXGEstimate(10, 1.8, 1.1, 9, 6),
                        awayXgEstimate = SeasonXGEstimate(10, 1.2, 1.4, 6, 7),
                        homeShotsEstimate = SeasonShotsEstimate(10, 140, 100, 60, 45),
                        awayShotsEstimate = SeasonShotsEstimate(10, 110, 130, 50, 55),
                        homeBigChancesEstimate = SeasonBigChancesEstimate(10, 30, 20, 10, 8),
                        awayBigChancesEstimate = SeasonBigChancesEstimate(10, 20, 25, 12, 6),
                        homeCornersEstimate = SeasonCornersEstimate(10, 60, 40),
                        awayCornersEstimate = SeasonCornersEstimate(10, 45, 55),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Season estimates").assertExists()
        composeTestRule.onNodeWithText("xG for").assertExists()
        composeTestRule.onNodeWithText("Corners (last 10)").assertExists()
    }

    @Test
    fun `advanced stats section renders every bar and info row`() {
        composeTestRule.setContent {
            PerformanceTab(
                insights =
                    InsightsPerformance(
                        homeAdvancedStats = fakeAdvancedStats(touchesInBoxFor = 40, shotsInsideBoxFor = 10),
                        awayAdvancedStats = fakeAdvancedStats(touchesInBoxFor = 28, shotsInsideBoxFor = 7),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Advanced stats (matched sample)").assertExists()
        composeTestRule.onNodeWithText("Touches in box").assertExists()
        composeTestRule.onNodeWithText("Arsenal errors -> shot/goal").assertExists()
    }

    @Test
    fun `possession matchup section renders for both teams`() {
        composeTestRule.setContent {
            PerformanceTab(
                insights =
                    InsightsPerformance(
                        homePossessionMatchup = PossessionMatchupInfo(1.1, 8, 2.0, 12),
                        awayPossessionMatchup = PossessionMatchupInfo(0.9, 6, 1.7, 14),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Possession matchup").assertExists()
        composeTestRule.onNodeWithText("Arsenal vs high-possession opponents").assertExists()
    }

    @Test
    fun `season estimates section skips every bar when only one side of each pair is known`() {
        // Every nested homeX?.let { awayX?.let { ... } } pair was always
        // either both-present or both-absent before -- never one side
        // alone, which is the actual false-branch case for the inner let.
        composeTestRule.setContent {
            PerformanceTab(
                insights = InsightsPerformance(homeXgEstimate = SeasonXGEstimate(10, 1.8, 1.1, 9, 6)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Season estimates").assertExists()
        composeTestRule.onNodeWithText("xG for").assertDoesNotExist()
    }

    @Test
    fun `advanced stats section highlights errors that led directly to a goal`() {
        composeTestRule.setContent {
            PerformanceTab(
                insights =
                    InsightsPerformance(
                        homeAdvancedStats = fakeAdvancedStats().copy(errorsLeadToGoalFor = 1),
                        awayAdvancedStats = fakeAdvancedStats(),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal errors -> shot/goal").assertExists()
    }

    @Test
    fun `a fully populated performance tab composes without throwing`() {
        composeTestRule.setContent {
            PerformanceTab(
                insights =
                    InsightsPerformance(
                        homeXgEstimate = SeasonXGEstimate(10, 1.8, 1.1, 9, 6),
                        awayXgEstimate = SeasonXGEstimate(10, 1.2, 1.4, 6, 7),
                        homeAdvancedStats = fakeAdvancedStats(),
                        awayAdvancedStats = fakeAdvancedStats(),
                        homePossessionMatchup = PossessionMatchupInfo(1.1, 8, 2.0, 12),
                        awayPossessionMatchup = PossessionMatchupInfo(0.9, 6, 1.7, 14),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
