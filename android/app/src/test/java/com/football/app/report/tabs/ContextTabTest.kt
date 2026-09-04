package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.BenchInfo
import com.football.app.data.model.ExperienceComparison
import com.football.app.data.model.ExperienceH2HNote
import com.football.app.data.model.FatigueFlag
import com.football.app.data.model.InsightsContext
import com.football.app.data.model.LosingStreakContextInfo
import com.football.app.data.model.PresenceEntry
import com.football.app.data.model.ResilienceInfo
import com.football.app.data.model.RestComparison
import com.football.app.data.model.RestPerformanceInfo
import com.football.app.data.model.RotationInfo
import com.football.app.data.model.StreakStabilityInfo
import com.football.app.data.model.TravelInfo
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ContextTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty insights object renders no sections`() {
        composeTestRule.setContent {
            ContextTab(insights = InsightsContext(), homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Rest").assertDoesNotExist()
        composeTestRule.onNodeWithText("Travel").assertDoesNotExist()
    }

    @Test
    fun `rest section renders the comparison bar and per-team performance rows`() {
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        restComparison = RestComparison(ownRestDays = 4, opponentRestDays = 6, moreRested = "away"),
                        homeRestPerformance = RestPerformanceInfo(shortRestPpg = 1.2, shortRestSampleSize = 5, longRestPpg = 2.0, longRestSampleSize = 8),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Rest").assertExists()
        composeTestRule.onNodeWithText("Days since last match").assertExists()
        composeTestRule.onNodeWithText("Arsenal performance by rest").assertExists()
    }

    @Test
    fun `fatigue and rotation section renders pills and rotation bars`() {
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        homeFatigueFlag = FatigueFlag(multiCompetition = true, flagged = true),
                        awayFatigueFlag = FatigueFlag(multiCompetition = false, flagged = false),
                        homeRotation = RotationInfo(changedPlayers = 4, startingXiSize = 11, formationChanged = true, precedingResult = "W"),
                        awayRotation = RotationInfo(changedPlayers = 1, startingXiSize = 11),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Fatigue & rotation").assertExists()
        composeTestRule.onNodeWithText("Arsenal: elevated").assertExists()
        composeTestRule.onNodeWithText("Chelsea: normal").assertExists()
    }

    @Test
    fun `streaks section renders stability losing-streak and resilience rows`() {
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        homeStreakStability = StreakStabilityInfo(streakResult = "W", streakCount = 4, stable = true),
                        awayLosingStreakContext = LosingStreakContextInfo(streakCount = 3, xgDelta = 0.8, potentialTurnaround = true),
                        homeResilience = ResilienceInfo(nonWinSampleSize = 6, drawSharePct = 50.0),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Streaks").assertExists()
        composeTestRule.onNodeWithText("Arsenal streak stability").assertExists()
        composeTestRule.onNodeWithText("Chelsea losing-streak xG").assertExists()
        composeTestRule.onNodeWithText("Arsenal resilience").assertExists()
    }

    @Test
    fun `experience section renders age comparison and h2h alignment`() {
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        experienceComparison = ExperienceComparison(ownAverageAge = 25.4, opponentAverageAge = 27.1, moreExperienced = "away"),
                        experienceH2h = ExperienceH2HNote(aligned = true),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Experience").assertExists()
        composeTestRule.onNodeWithText("Average age").assertExists()
    }

    @Test
    fun `travel section renders when the away team is traveling`() {
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(travelInfo = TravelInfo(awayTraveling = true, awayTravelDistanceKm = 450.0, awayTimezoneDiffHours = 2.0)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        // "Travel" alone would match both the SectionCard title and the
        // InfoRow's own label -- asserting on the constructed value text
        // instead confirms the actual traveling-team branch rendered.
        composeTestRule.onNodeWithText("Chelsea traveling", substring = true).assertExists()
    }

    @Test
    fun `travel section renders both-at-home when neither side is traveling`() {
        composeTestRule.setContent {
            ContextTab(insights = InsightsContext(travelInfo = TravelInfo()), homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Both at home turf").assertExists()
    }

    @Test
    fun `availability section renders present-only status and absent player pills`() {
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        homePresence = listOf(PresenceEntry(name = "Saka", status = "P", starting = true)),
                        awayPresence =
                            listOf(
                                PresenceEntry(name = "Enzo", status = "P", starting = true),
                                PresenceEntry(name = "Colwill", status = "A", starting = false, reason = "injury"),
                            ),
                        homeBenchInfo = BenchInfo(benchSize = 9, benchTotalMarketValue = 45_000_000.0, startingTotalMarketValue = 620_000_000.0),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Availability").assertExists()
        composeTestRule.onNodeWithText("Colwill").assertExists()
    }

    @Test
    fun `a fully populated context tab composes without throwing`() {
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        restComparison = RestComparison(4, 6),
                        homeFatigueFlag = FatigueFlag(multiCompetition = true, flagged = true),
                        homeRotation = RotationInfo(changedPlayers = 4, startingXiSize = 11),
                        homeStreakStability = StreakStabilityInfo("W", 4, stable = true),
                        experienceComparison = ExperienceComparison(25.4, 27.1),
                        travelInfo = TravelInfo(homeTraveling = true, homeTravelDistanceKm = 300.0),
                        homePresence = listOf(PresenceEntry("Saka", "A", starting = true)),
                        homeBenchInfo = BenchInfo(9, 45_000_000.0, 620_000_000.0),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
