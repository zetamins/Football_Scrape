package com.football.app.report.tabs

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.AdditionalNote
import com.football.app.data.model.BettingOdds
import com.football.app.data.model.HeadToHeadMeeting
import com.football.app.data.model.HeadToHeadSummary
import com.football.app.data.model.ManagerClubRecord
import com.football.app.data.model.ManagerInfo
import com.football.app.data.model.ManagerTenureRecord
import com.football.app.data.model.MatchOverview
import com.football.app.data.model.RefereeHomeAwayBias
import com.football.app.data.model.RefereeStats
import com.football.app.data.model.TeamStanding
import com.football.app.data.model.VenueDetails
import com.football.app.data.model.WeatherDetail
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class OverviewTabTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `an entirely empty overview renders no sections`() {
        composeTestRule.setContent {
            OverviewTab(overview = MatchOverview(), venueDetails = null, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Match").assertDoesNotExist()
        composeTestRule.onNodeWithText("Venue").assertDoesNotExist()
    }

    @Test
    fun `match section renders kickoff and competition`() {
        composeTestRule.setContent {
            OverviewTab(
                overview = MatchOverview(kickoffUtc = "2026-09-05T15:00:00Z", round = 3, season = "2026/27"),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Match").assertExists()
        composeTestRule.onNodeWithText("Round 3 -- 2026/27").assertExists()
    }

    @Test
    fun `venue section merges match-level and venueDetails fields`() {
        composeTestRule.setContent {
            OverviewTab(
                overview = MatchOverview(venueName = "Emirates Stadium", venueCity = "London", venueCapacity = 60704),
                venueDetails =
                    VenueDetails(
                        address = "Holloway, N5 1BU",
                        opened = 2006,
                        architect = "Populous",
                        recordAttendance = "60,161",
                        clubs = listOf("Arsenal", "Arsenal Women"),
                    ),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Venue").assertExists()
        composeTestRule.onNodeWithText("Holloway, N5 1BU").assertExists()
        composeTestRule.onNodeWithText("Populous").assertExists()
    }

    @Test
    fun `venue section renders match-level fields only when venueDetails is null`() {
        composeTestRule.setContent {
            OverviewTab(
                overview = MatchOverview(venueName = "Emirates Stadium", venueCity = "London"),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Venue").assertExists()
        composeTestRule.onNodeWithText("Emirates Stadium, London").assertExists()
        composeTestRule.onNodeWithText("Capacity").assertDoesNotExist()
    }

    @Test
    fun `venue section omits every optional venueDetails line when all are null`() {
        composeTestRule.setContent {
            OverviewTab(
                overview = MatchOverview(venueCapacity = 60704),
                venueDetails = VenueDetails(),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Venue").assertExists()
        composeTestRule.onNodeWithText("60,704").assertExists()
        composeTestRule.onNodeWithText("Location").assertDoesNotExist()
        composeTestRule.onNodeWithText("Address").assertDoesNotExist()
        composeTestRule.onNodeWithText("Built").assertDoesNotExist()
        composeTestRule.onNodeWithText("Architect").assertDoesNotExist()
        composeTestRule.onNodeWithText("Record attendance").assertDoesNotExist()
        composeTestRule.onNodeWithText("Shared by").assertDoesNotExist()
    }

    @Test
    fun `venue section shows built when only renovated is known and skips clubs when only one club`() {
        composeTestRule.setContent {
            OverviewTab(
                overview = MatchOverview(),
                venueDetails = VenueDetails(renovated = "2010", clubs = listOf("Arsenal")),
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Venue").assertExists()
        composeTestRule.onNodeWithText("renovated 2010").assertExists()
        composeTestRule.onNodeWithText("Shared by").assertDoesNotExist()
    }

    @Test
    fun `weather section renders conditions and detail`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        weather = "Overcast, 14C",
                        weatherDetail = WeatherDetail(humidityPct = 73.0, windSpeedKmph = 13.0),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Weather").assertExists()
        composeTestRule.onNodeWithText("Overcast, 14C").assertExists()
    }

    @Test
    fun `referee section renders discipline and elevated home-away bias`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        referee = "Michael Oliver",
                        refereeStats =
                            RefereeStats(
                                games = 200,
                                yellowCardsPerGame = "3.6",
                                foulsPerGame = 21.5,
                                penaltiesAwarded = 8,
                                homeAwayBias = RefereeHomeAwayBias(sampleSize = 50, homeCardsPerGame = 2.1, awayCardsPerGame = 3.4),
                            ),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Referee").assertExists()
        composeTestRule.onNodeWithText("Michael Oliver").assertExists()
    }

    @Test
    fun `managers section renders both managers, tenure, and a real head-to-head duel`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        homeManager =
                            ManagerInfo(
                                name = "Mikel Arteta",
                                country = "Spain",
                                recentAppointment = false,
                                recordAtClub = ManagerTenureRecord(played = 300, wins = 180, draws = 60, losses = 60),
                            ),
                        awayManager = ManagerInfo(name = "Enzo Maresca", country = "Italy", recentAppointment = true),
                        managerDuel = HeadToHeadSummary(homeWins = 2, awayWins = 1, draws = 0),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Managers").assertExists()
        composeTestRule.onNodeWithText("Head-to-head as managers").assertExists()
    }

    // A manager's personal record against the opposing club (across any
    // club he's managed, not tied to managerDuel or recordAtClub above)
    // -- was decoded but never rendered anywhere before this test.
    @Test
    fun `managers section renders each manager's personal record against the opposing club`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        homeManager = ManagerInfo(name = "Mikel Arteta"),
                        awayManager = ManagerInfo(name = "Enzo Maresca"),
                        homeManagerVsAwayClub =
                            ManagerClubRecord(
                                managerName = "Mikel Arteta",
                                opponentClub = "Chelsea",
                                sampleSize = 6,
                                wins = 3,
                                draws = 2,
                                losses = 1,
                            ),
                        awayManagerVsHomeClub =
                            ManagerClubRecord(
                                managerName = "Enzo Maresca",
                                opponentClub = "Arsenal",
                                sampleSize = 0,
                                wins = 0,
                                draws = 0,
                                losses = 0,
                            ),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Mikel Arteta vs Chelsea").assertExists()
        composeTestRule.onNodeWithText("3W-2D-1L (last 6)").assertExists()
        // awayManagerVsHomeClub has sampleSize=0 -- gated out, matching
        // format_markdown.py's own `if ... .sample_size` check.
        composeTestRule.onNodeWithText("Enzo Maresca vs Arsenal").assertDoesNotExist()
    }

    @Test
    fun `standings section renders a bar comparison when both sides are known`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        homeTeamStanding = TeamStanding(position = 1, played = 5, wins = 4, draws = 1, losses = 0, points = 13, goalDiff = "+8", totalTeams = 20),
                        awayTeamStanding = TeamStanding(position = 5, played = 5, wins = 3, draws = 0, losses = 2, points = 9, goalDiff = "+2", totalTeams = 20),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Standings").assertExists()
        composeTestRule.onNodeWithText("Points").assertExists()
    }

    @Test
    fun `standings section falls back to a home-only row when only home is known`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        homeTeamStanding =
                            TeamStanding(position = 1, played = 5, wins = 4, draws = 1, losses = 0, points = 13, goalDiff = "+8", totalTeams = 20),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Standings").assertExists()
        composeTestRule.onNodeWithText("#1/20 (13pts, 4W-1D-0L, GD +8)").assertExists()
    }

    @Test
    fun `standings section falls back to an away-only row when only away is known`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        awayTeamStanding =
                            TeamStanding(position = 5, played = 5, wins = 3, draws = 0, losses = 2, points = 9, goalDiff = "+2", totalTeams = 20),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Standings").assertExists()
        composeTestRule.onNodeWithText("#5/20 (9pts, 3W-0D-2L, GD +2)").assertExists()
    }

    @Test
    fun `head-to-head section renders the bar, streaks, and recent meetings`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        headToHeadSummary = HeadToHeadSummary(homeWins = 7, awayWins = 2, draws = 1),
                        headToHeadStreaks = listOf("Wins (home): 3"),
                        recentMeetings =
                            listOf(
                                HeadToHeadMeeting(
                                    date = "2026-08-31",
                                    scoreline = "0-1",
                                    venue = "home",
                                    homeFormation = "4-3-3",
                                    awayFormation = "4-2-3-1",
                                    homeXg = 1.4,
                                    awayXg = 1.1,
                                ),
                            ),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Head-to-head").assertExists()
        composeTestRule.onNodeWithText("Recent meetings").assertExists()
    }

    @Test
    fun `odds section renders moneyline and over-under pills`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        bettingOdds =
                            BettingOdds(homeWinOdds = 1.85, drawOdds = 3.6, awayWinOdds = 4.2, over25Odds = 1.9, under25Odds = 1.95),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Moneyline").assertExists()
        composeTestRule.onNodeWithText("Over/under").assertExists()
    }

    @Test
    fun `notes section renders the primary note and additional notes with dividers`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        note = "Lineup predicted, not confirmed",
                        additionalNotes = listOf(AdditionalNote("Kickoff moved for TV"), AdditionalNote("Behind closed doors")),
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onNodeWithText("Notes").assertExists()
        composeTestRule.onNodeWithText("Kickoff moved for TV").assertExists()
        composeTestRule.onNodeWithText("Behind closed doors").assertExists()
    }

    @Test
    fun `a fully populated overview composes without throwing`() {
        composeTestRule.setContent {
            OverviewTab(
                overview =
                    MatchOverview(
                        kickoffUtc = "2026-09-05T15:00:00Z",
                        round = 3,
                        season = "2026/27",
                        venueName = "Emirates Stadium",
                        venueCity = "London",
                        venueCountry = "England",
                        venueCapacity = 60704,
                        weather = "Clear, 18C",
                        referee = "Michael Oliver",
                        homeManager = ManagerInfo(name = "Mikel Arteta"),
                        awayManager = ManagerInfo(name = "Enzo Maresca"),
                        homeTeamStanding = TeamStanding(position = 1, played = 5, wins = 4, draws = 1, losses = 0, points = 13, goalDiff = "+8"),
                        awayTeamStanding = TeamStanding(position = 5, played = 5, wins = 3, draws = 0, losses = 2, points = 9, goalDiff = "+2"),
                        headToHeadSummary = HeadToHeadSummary(homeWins = 7, awayWins = 2, draws = 1),
                        bettingOdds = BettingOdds(homeWinOdds = 1.85),
                        note = "All clear",
                    ),
                venueDetails = null,
                homeTeam = "Arsenal",
                awayTeam = "Chelsea",
            )
        }
        composeTestRule.onRoot().assertExists()
    }
}
