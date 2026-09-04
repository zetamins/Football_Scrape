package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.AdvancedStats
import com.football.app.data.model.CardDisciplineInfo
import com.football.app.data.model.CardDisciplineVenueSplit
import com.football.app.data.model.FlaggedPlayer
import com.football.app.data.model.InsightsDiscipline
import com.football.app.data.model.PlayerCardRisk
import com.football.app.data.model.RefereeCardRiskNote
import com.football.app.data.model.SeasonCornersEstimate
import com.football.app.data.model.SeasonFoulsEstimate
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

private fun fakeAdvancedStats(yellowCardsFor: Int = 0) = AdvancedStats(
    sampleSize = 10, touchesInBoxFor = 0, touchesInBoxAgainst = 0, crossesFor = 0, crossesAgainst = 0,
    dribblesFor = 0, dribblesAgainst = 0, throughBallsFor = 0, throughBallsAgainst = 0, finalThirdEntriesFor = 0,
    finalThirdEntriesAgainst = 0, recoveriesFor = 0, recoveriesAgainst = 0, errorsLeadToShotFor = 0, errorsLeadToShotAgainst = 0,
    errorsLeadToGoalFor = 0, errorsLeadToGoalAgainst = 0, shotsInsideBoxFor = 0, shotsInsideBoxAgainst = 0,
    shotsOutsideBoxFor = 0, shotsOutsideBoxAgainst = 0, shotsOffTargetFor = 0, shotsOffTargetAgainst = 0, blockedShotsFor = 0,
    blockedShotsAgainst = 0, offsidesFor = 0, offsidesAgainst = 0, bigChancesScoredFor = 0, bigChancesScoredAgainst = 0,
    dispossessedFor = 0, dispossessedAgainst = 0, teamTacklesFor = 0, teamTacklesAgainst = 0, teamInterceptionsFor = 0,
    teamInterceptionsAgainst = 0, goalsPreventedFor = 0.0, goalsPreventedAgainst = 0.0, bigSavesFor = 0, bigSavesAgainst = 0,
    highClaimsFor = 0, highClaimsAgainst = 0, distanceCoveredKmFor = 0.0, distanceCoveredKmAgainst = 0.0, sprintsFor = 0,
    sprintsAgainst = 0, teamClearancesFor = 0, teamClearancesAgainst = 0, freeKicksFor = 0, freeKicksAgainst = 0, xaFor = 0.0,
    xaAgainst = 0.0, cornerGoalsFor = 0, cornerGoalsAgainst = 0, penaltyGoalsFor = 0, penaltyGoalsAgainst = 0,
    freeKickGoalsFor = 0, freeKickGoalsAgainst = 0, totalShotsFor = 0, totalShotsAgainst = 0, shotsOnTargetFor = 0,
    shotsOnTargetAgainst = 0, cornersFor = 0, cornersAgainst = 0, foulsFor = 0, foulsAgainst = 0, yellowCardsFor = yellowCardsFor,
    yellowCardsAgainst = 0, redCardsFor = 0, redCardsAgainst = 0, bigChancesCreatedFor = 0, bigChancesCreatedAgainst = 0,
    nonPenaltyXgFor = 0.0, nonPenaltyXgAgainst = 0.0, setPieceXgFor = 0.0, setPieceXgAgainst = 0.0, penaltiesAwardedFor = 0,
    penaltiesAwardedAgainst = 0,
)

@RunWith(RobolectricTestRunner::class)
class DisciplineTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty insights object renders no sections`() {
        composeTestRule.setContent {
            DisciplineTab(insights = InsightsDiscipline(), homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Cards per game").assertDoesNotExist()
    }

    @Test
    fun `cards section renders both teams, elevated risk, and venue split`() {
        composeTestRule.setContent {
            DisciplineTab(
                insights =
                    InsightsDiscipline(
                        homeCardDiscipline = CardDisciplineInfo(yellowPerGame = 2.1, redPerGame = 0.1, elevatedRisk = true),
                        awayCardDiscipline = CardDisciplineInfo(yellowPerGame = 1.4, redPerGame = 0.0, elevatedRisk = false),
                        homeCardDisciplineVenueSplit = CardDisciplineVenueSplit(atHomeSampleSize = 5, atHomeYellowPerGame = 1.8, awaySampleSize = 5, awayYellowPerGame = 2.4),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Cards per game").assertExists()
        composeTestRule.onNodeWithText("Elevated card risk").assertExists()
        composeTestRule.onNodeWithText("Arsenal by venue").assertExists()
    }

    @Test
    fun `cards section falls back to single-team rows when only one side is known`() {
        composeTestRule.setContent {
            DisciplineTab(
                insights = InsightsDiscipline(homeCardDiscipline = CardDisciplineInfo(2.1, 0.1, elevatedRisk = true)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Cards per game").assertExists()
    }

    @Test
    fun `fouls and corners section renders bars and info rows`() {
        composeTestRule.setContent {
            DisciplineTab(
                insights =
                    InsightsDiscipline(
                        homeFoulsEstimate = SeasonFoulsEstimate(10, 120, 100),
                        awayFoulsEstimate = SeasonFoulsEstimate(10, 100, 130),
                        homeCornersEstimate = SeasonCornersEstimate(10, 60, 40),
                        awayCornersEstimate = SeasonCornersEstimate(10, 45, 55),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Fouls (last 10)").assertExists()
        composeTestRule.onNodeWithText("Arsenal corners for/against").assertExists()
    }

    @Test
    fun `matched sample section renders cards fouls and penalty rows`() {
        composeTestRule.setContent {
            DisciplineTab(
                insights =
                    InsightsDiscipline(
                        homeAdvancedStats = fakeAdvancedStats(yellowCardsFor = 30),
                        awayAdvancedStats = fakeAdvancedStats(yellowCardsFor = 25),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Matched sample (sofascore)").assertExists()
        composeTestRule.onNodeWithText("Arsenal penalties conceded").assertExists()
    }

    @Test
    fun `card risk section renders pills for both teams`() {
        composeTestRule.setContent {
            DisciplineTab(
                insights =
                    InsightsDiscipline(
                        homeCardRisks = listOf(PlayerCardRisk("Rice", yellowCards = 4, redCards = 0, accumulationRisk = true, priorDismissal = false)),
                        awayCardRisks = listOf(PlayerCardRisk("Caicedo", yellowCards = 5, redCards = 1, accumulationRisk = true, priorDismissal = true)),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Card risk").assertExists()
        composeTestRule.onNodeWithText("Arsenal players").assertExists()
    }

    @Test
    fun `referee note section renders yellow rate and flagged players`() {
        composeTestRule.setContent {
            DisciplineTab(
                insights =
                    InsightsDiscipline(
                        refereeCardRiskNote =
                            RefereeCardRiskNote(
                                refereeName = "Michael Oliver",
                                yellowCardsPerGame = 3.9,
                                elevatedCardReferee = true,
                                flaggedPlayers = listOf(FlaggedPlayer(name = "Rice", side = "home", priorDismissal = false)),
                            ),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Referee Michael Oliver").assertExists()
        composeTestRule.onNodeWithText("Flagged players").assertExists()
    }

    @Test
    fun `a fully populated discipline tab composes without throwing`() {
        composeTestRule.setContent {
            DisciplineTab(
                insights =
                    InsightsDiscipline(
                        homeCardDiscipline = CardDisciplineInfo(2.1, 0.1, elevatedRisk = true),
                        awayCardDiscipline = CardDisciplineInfo(1.4, 0.0, elevatedRisk = false),
                        homeFoulsEstimate = SeasonFoulsEstimate(10, 120, 100),
                        awayFoulsEstimate = SeasonFoulsEstimate(10, 100, 130),
                        homeAdvancedStats = fakeAdvancedStats(),
                        awayAdvancedStats = fakeAdvancedStats(),
                        homeCardRisks = listOf(PlayerCardRisk("Rice", 4, 0, accumulationRisk = true, priorDismissal = false)),
                        refereeCardRiskNote = RefereeCardRiskNote("Michael Oliver", 3.9, elevatedCardReferee = true),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
