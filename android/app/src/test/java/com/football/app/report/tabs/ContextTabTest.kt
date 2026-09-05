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
                        awayRestPerformance = RestPerformanceInfo(shortRestPpg = 0.9, shortRestSampleSize = 4, longRestPpg = 1.8, longRestSampleSize = 7),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Rest").assertExists()
        composeTestRule.onNodeWithText("Days since last match").assertExists()
        composeTestRule.onNodeWithText("Arsenal performance by rest").assertExists()
        composeTestRule.onNodeWithText("Chelsea performance by rest").assertExists()
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
    fun `rotation row spells out a loss or draw preceding result too`() {
        // "W" is covered above; resultWord()'s "L"/"D" branches were
        // never reached by any fixture.
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        homeRotation = RotationInfo(changedPlayers = 2, startingXiSize = 11, precedingResult = "L"),
                        awayRotation = RotationInfo(changedPlayers = 3, startingXiSize = 11, precedingResult = "D"),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("2 changed (after a loss)", substring = true).assertExists()
        composeTestRule.onNodeWithText("3 changed (after a draw)", substring = true).assertExists()
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
    fun `experience section falls back to plain text when only one side's age is known`() {
        // NumericComparisonRow (shared with RestSection above, already
        // covered there for the both-known case) falls back to a plain
        // InfoRow when either value is null -- never exercised before.
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(experienceComparison = ExperienceComparison(ownAverageAge = 25.4)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Average age").assertExists()
        composeTestRule.onNodeWithText("Arsenal 25.4 vs Chelsea n/a").assertExists()
    }

    @Test
    fun `experience section renders 'not aligned' when the h2h edge doesn't match`() {
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(experienceH2h = ExperienceH2HNote(aligned = false)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Experience").assertExists()
        composeTestRule.onNodeWithText("not aligned").assertExists()
    }

    @Test
    fun `travel section renders when the away team is traveling`() {
        composeTestRule.setContent {
            ContextTab(
                insights =
                    InsightsContext(
                        travelInfo =
                            TravelInfo(
                                awayTraveling = true,
                                awayTravelDistanceKm = 450.0,
                                awayTravelTimeHours = 5.5,
                                awayTimezoneDiffHours = 2.0,
                            ),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        // "Travel" alone would match both the SectionCard title and the
        // InfoRow's own label -- asserting on the constructed value text
        // instead confirms the actual traveling-team branch rendered.
        // awayTravelTimeHours is set (unlike the "both at home" and
        // home-traveling tests below) to also exercise the
        // awayTravelTimeHours?.let{} sub-branch, previously untested.
        composeTestRule.onNodeWithText("Chelsea traveling (~450.0km, ~5.5h travel, 2.0h tz diff)").assertExists()
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
    fun `bench row falls back to plain text when a value is missing`() {
        // BenchRow's bar-comparison branch needs both values known and
        // positive -- never exercised the plain-text fallback before.
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(homeBenchInfo = BenchInfo(benchSize = 9, benchTotalMarketValue = null, startingTotalMarketValue = null)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal bench").assertExists()
        composeTestRule.onNodeWithText("9 named, n/a combined value vs starting XI's n/a", substring = true).assertExists()
    }

    @Test
    fun `rest section renders when only rest-performance is known and restComparison is null`() {
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(homeRestPerformance = RestPerformanceInfo(shortRestPpg = 1.0, shortRestSampleSize = 3, longRestPpg = 2.0, longRestSampleSize = 3)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Rest").assertExists()
        composeTestRule.onNodeWithText("Days since last match").assertDoesNotExist()
        composeTestRule.onNodeWithText("Arsenal performance by rest").assertExists()
    }

    @Test
    fun `fatigue pill row is skipped when only rotation is known`() {
        // The inner fatigue-flag if() is a distinct branch from the
        // section-level hasFatigue||hasRotation early return -- never
        // exercised false while the section itself still renders.
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(homeRotation = RotationInfo(changedPlayers = 2, startingXiSize = 11, formationChanged = false)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Fatigue & rotation").assertExists()
        composeTestRule.onNodeWithText("Arsenal: elevated").assertDoesNotExist()
        composeTestRule.onNodeWithText("Arsenal: normal").assertDoesNotExist()
        composeTestRule.onNodeWithText("2 changed, shape unchanged", substring = true).assertExists()
    }

    @Test
    fun `experience h2h alignment renders n-slash-a when aligned is null`() {
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(experienceH2h = ExperienceH2HNote(aligned = null)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Experience/H2H alignment").assertExists()
        composeTestRule.onNodeWithText("n/a").assertExists()
    }

    @Test
    fun `travel section renders when the home team is traveling with unknown distance and no tz diff`() {
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(travelInfo = TravelInfo(homeTraveling = true)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal traveling (~?km)").assertExists()
    }

    @Test
    fun `bench row falls back to plain text when both values are known but zero`() {
        // Distinct from the null-values fallback case above -- both
        // values are non-null here, so only the (benchValue > 0 ||
        // startingValue > 0) half of the guard is false.
        composeTestRule.setContent {
            ContextTab(
                insights = InsightsContext(homeBenchInfo = BenchInfo(benchSize = 0, benchTotalMarketValue = 0.0, startingTotalMarketValue = 0.0)),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Arsenal bench").assertExists()
        composeTestRule.onNodeWithText("0 named, €0m combined value vs starting XI's €0m", substring = true).assertExists()
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
                        travelInfo = TravelInfo(homeTraveling = true, homeTravelDistanceKm = 300.0, homeTravelTimeHours = 3.5),
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
