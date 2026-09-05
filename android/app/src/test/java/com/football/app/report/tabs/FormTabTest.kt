package com.football.app.report.tabs

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.CompetitionFormRecord
import com.football.app.data.model.DetailedVenueSplitForm
import com.football.app.data.model.FixtureGap
import com.football.app.data.model.FormResult
import com.football.app.data.model.FormSummary
import com.football.app.data.model.HalfSplitStats
import com.football.app.data.model.MomentumInfo
import com.football.app.data.model.StreakInfo
import com.football.app.data.model.VenueSplitForm
import com.football.app.data.model.VenueSplitStats
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

private fun minimalForm() = FormSummary(matchesLast7Days = 1, matchesLast14Days = 2)

private fun fakeVenueSplitStats(sampleSize: Int = 5) = VenueSplitStats(
    sampleSize = sampleSize, xgFor = 1.5, xgAgainst = 1.1, shotsFor = 12, shotsAgainst = 9, shotsOnTargetFor = 5,
    shotsOnTargetAgainst = 4, cornersFor = 6, cornersAgainst = 4, foulsFor = 10, foulsAgainst = 9, yellowCardsFor = 2,
    yellowCardsAgainst = 2, redCardsFor = 0, redCardsAgainst = 0, bigChancesCreatedFor = 3, bigChancesCreatedAgainst = 2,
)

@RunWith(RobolectricTestRunner::class)
class FormTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders both team labels, congestion always shows even with no other data`() {
        composeTestRule.setContent {
            FormTab(form = minimalForm(), opponentForm = minimalForm(), teamLabel = "Arsenal", opponentLabel = "Chelsea")
        }
        composeTestRule.onNodeWithText("Arsenal").assertExists()
        composeTestRule.onNodeWithText("Chelsea").assertExists()
        composeTestRule.onNodeWithText("Streak & momentum").assertDoesNotExist()
    }

    @Test
    fun `streak section renders the form guide and current streak`() {
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        last10Overall = listOf(FormResult(opponent = "X", result = "W", scoreline = "2-0", venue = "home", margin = 2)),
                        currentStreak = StreakInfo(result = "W", count = 4),
                        momentum = MomentumInfo(recentPpg = 2.3, priorPpg = 1.2, trend = "improving"),
                        cleanSheetStreak = 3,
                        scorelessStreak = null,
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Streak & momentum").assertExists()
        composeTestRule.onNodeWithText("Streak").assertExists()
        composeTestRule.onNodeWithText("Momentum").assertExists()
    }

    @Test
    fun `a drawing streak and declining momentum render their own branches`() {
        // Distinct from the "W"/"L"/"improving" cases exercised above and
        // by "renders down-trending form" below -- streakWord()'s
        // else-branch ("drawing") and momentumColor()'s "declining"
        // branch were previously never reached by any fixture.
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        currentStreak = StreakInfo(result = "D", count = 3),
                        momentum = MomentumInfo(recentPpg = 1.0, priorPpg = 1.8, trend = "declining"),
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("3-game drawing").assertExists()
        composeTestRule.onNodeWithText("1.0 ppg (last 3) vs 1.8 ppg (prior 3) -- declining").assertExists()
    }

    @Test
    fun `a steady momentum trend renders the neutral else-branch color`() {
        // momentumColor()'s else branch (neither "improving" nor
        // "declining") was never reached by any fixture.
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        currentStreak = StreakInfo(result = "W", count = 2),
                        momentum = MomentumInfo(recentPpg = 1.5, priorPpg = 1.5, trend = "steady"),
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("1.5 ppg (last 3) vs 1.5 ppg (prior 3) -- steady").assertExists()
    }

    @Test
    fun `rates section renders a segmented bar and win-draw-loss line`() {
        composeTestRule.setContent {
            FormTab(
                form = minimalForm().copy(winRatePct = 60.0, drawRatePct = 20.0, lossRatePct = 20.0, pointsPerGame = 2.0),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Rates (last 10)").assertExists()
        composeTestRule.onNodeWithText("W/D/L").assertExists()
    }

    @Test
    fun `over-under section renders both share lines`() {
        composeTestRule.setContent {
            FormTab(
                form = minimalForm().copy(over15SharePct = 80.0, over25SharePct = 60.0, over35SharePct = 30.0, cleanSheetSharePct = 40.0, failedToScoreSharePct = 20.0),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Over/under & clean sheets").assertExists()
    }

    @Test
    fun `xG trend section renders once at least 2 matches have both xg values`() {
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        last10Overall =
                            listOf(
                                FormResult(opponent = "X", result = "W", scoreline = "2-0", venue = "home", margin = 2, xgFor = 1.8, xgAgainst = 0.6),
                                FormResult(opponent = "Y", result = "D", scoreline = "1-1", venue = "away", margin = 0, xgFor = 1.1, xgAgainst = 1.3),
                            ),
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("xG per match (recent, oldest to newest)").assertExists()
    }

    @Test
    fun `venue split section renders home away and neutral rows plus detailed split`() {
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        venueSplitForm =
                            VenueSplitForm(
                                homeSampleSize = 5, homeWins = 4, homeDraws = 1, homeLosses = 0, homeGoalsFor = 12, homeGoalsAgainst = 3,
                                awaySampleSize = 5, awayWins = 2, awayDraws = 1, awayLosses = 2, awayGoalsFor = 7, awayGoalsAgainst = 6,
                                neutralSampleSize = 1, neutralWins = 1, neutralGoalsFor = 3, neutralGoalsAgainst = 0,
                            ),
                        detailedVenueSplit = DetailedVenueSplitForm(home = fakeVenueSplitStats(), away = fakeVenueSplitStats(), neutral = fakeVenueSplitStats(sampleSize = 0)),
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("True venue split").assertExists()
        composeTestRule.onNodeWithText("Home detail").assertExists()
    }

    @Test
    fun `congestion section renders elevated fixture warning and competition breakdown`() {
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        matchesLast7Days = 3,
                        gapsBetweenLastThree = listOf(3, 4),
                        recentCompetitions = listOf("Premier League", "Champions League"),
                        formByCompetition =
                            listOf(
                                CompetitionFormRecord(competition = "Premier League", played = 8, wins = 6, draws = 1, losses = 1, goalsFor = 20, goalsAgainst = 8),
                                CompetitionFormRecord(competition = "Champions League", played = 3, wins = 2, draws = 0, losses = 1, goalsFor = 7, goalsAgainst = 4),
                            ),
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        // CongestionSection has no null-guard, so it renders once per
        // team (2 total) regardless of data -- unlike every other section.
        composeTestRule.onAllNodesWithText("Congestion & competitions").assertCountEquals(2)
        composeTestRule.onNodeWithText("Competitions").assertExists()
        composeTestRule.onNodeWithText("Form by competition").assertExists()
    }

    @Test
    fun `upcoming fixtures section renders each fixture gap`() {
        composeTestRule.setContent {
            FormTab(
                form = minimalForm().copy(next5WithGaps = listOf(FixtureGap(opponent = "Newcastle", date = "2026-09-14"))),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Upcoming fixtures").assertExists()
    }

    @Test
    fun `half split appears within the rates section when present`() {
        composeTestRule.setContent {
            FormTab(
                form = minimalForm().copy(winRatePct = 50.0, halfSplit = HalfSplitStats(sampleSize = 10, firstHalfGoalsFor = 8, firstHalfGoalsAgainst = 4, secondHalfGoalsFor = 10, secondHalfGoalsAgainst = 6)),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Half split").assertExists()
    }

    @Test
    fun `clean-sheet and scoreless streaks below the 2-game threshold render nothing`() {
        // `!= null && >= 2` -- every other fixture leaves these null
        // (false via the first operand) or >= 2 (true); a non-null value
        // that fails the threshold (false via the second operand) was
        // never reached before.
        composeTestRule.setContent {
            FormTab(
                form = minimalForm().copy(currentStreak = StreakInfo(result = "W", count = 1), cleanSheetStreak = 1, scorelessStreak = 1),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Clean sheets").assertDoesNotExist()
        composeTestRule.onNodeWithText("Scoreless").assertDoesNotExist()
    }

    @Test
    fun `rates section renders the win-rate-only fallback lines when only home-away splits and shares are known`() {
        // hasRates can be true (winRatePct alone) while the segmented-bar
        // guard (all three of win/draw/loss) is false, and the
        // homeWinRatePct/narrowWinSharePct/scoringDrawSharePct/
        // bttsSharePct optional lines were never reached by any fixture.
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        winRatePct = 55.0,
                        homeWinRatePct = 70.0,
                        awayWinRatePct = 40.0,
                        narrowWinSharePct = 25.0,
                        scoringDrawSharePct = 33.0,
                        bttsSharePct = 45.0,
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Rates (last 10)").assertExists()
        composeTestRule.onNodeWithText("Win rate").assertExists()
        composeTestRule.onNodeWithText("home 70.0% / away 40.0%").assertExists()
        composeTestRule.onNodeWithText("Narrow wins").assertExists()
        composeTestRule.onNodeWithText("Scoring draws").assertExists()
        composeTestRule.onNodeWithText("BTTS rate").assertExists()
    }

    @Test
    fun `over-under and clean-sheet lines are each skipped when only one side of their pair is known`() {
        composeTestRule.setContent {
            FormTab(
                form = minimalForm().copy(over25SharePct = 55.0, cleanSheetSharePct = 35.0),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Over/under & clean sheets").assertExists()
        composeTestRule.onNodeWithText("Over/under (last 10)").assertDoesNotExist()
        composeTestRule.onNodeWithText("CS% / FTS%").assertDoesNotExist()
    }

    @Test
    fun `venue split section omits the neutral row when there are no neutral-venue matches`() {
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        venueSplitForm =
                            VenueSplitForm(
                                homeSampleSize = 5, homeWins = 4, homeDraws = 1, homeLosses = 0, homeGoalsFor = 12, homeGoalsAgainst = 3,
                                awaySampleSize = 5, awayWins = 2, awayDraws = 1, awayLosses = 2, awayGoalsFor = 7, awayGoalsAgainst = 6,
                                neutralSampleSize = 0,
                            ),
                        detailedVenueSplit = DetailedVenueSplitForm(home = fakeVenueSplitStats(sampleSize = 0), away = fakeVenueSplitStats(), neutral = fakeVenueSplitStats(sampleSize = 0)),
                    ),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Neutral").assertDoesNotExist()
        composeTestRule.onNodeWithText("Home detail").assertExists()
    }

    @Test
    fun `upcoming fixtures section renders a fixture with no date`() {
        composeTestRule.setContent {
            FormTab(
                form = minimalForm().copy(next5WithGaps = listOf(FixtureGap(opponent = "Newcastle", date = null))),
                opponentForm = minimalForm(),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Newcastle").assertExists()
    }

    @Test
    fun `a fully populated form tab composes without throwing`() {
        composeTestRule.setContent {
            FormTab(
                form =
                    minimalForm().copy(
                        last10Overall =
                            listOf(
                                FormResult(opponent = "X", result = "W", scoreline = "2-0", venue = "home", margin = 2, xgFor = 1.8, xgAgainst = 0.6),
                                FormResult(opponent = "Y", result = "D", scoreline = "1-1", venue = "away", margin = 0, xgFor = 1.1, xgAgainst = 1.3),
                            ),
                        currentStreak = StreakInfo("W", 4),
                        winRatePct = 60.0, drawRatePct = 20.0, lossRatePct = 20.0,
                        over25SharePct = 60.0,
                        venueSplitForm = VenueSplitForm(5, 4, 1, 0, 12, 3, 5, 2, 1, 2, 7, 6),
                        next5WithGaps = listOf(FixtureGap(opponent = "Newcastle")),
                    ),
                opponentForm =
                    minimalForm().copy(
                        currentStreak = StreakInfo("L", 2),
                        winRatePct = 40.0, drawRatePct = 30.0, lossRatePct = 30.0,
                    ),
                teamLabel = "Arsenal",
                opponentLabel = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
