package com.football.app.report

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ReportScreenTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    private fun loadSampleReportJson(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    @Test
    fun `shows a fallback message when no report is loaded`() {
        val viewModel = ReportViewModel()
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("No report loaded.").assertExists()
    }

    @Test
    fun `renders the team header, matchup, and default overview tab for a loaded report`() {
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSampleReportJson())
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = {})
        }
        // "Brentford"/"Sunderland" legitimately appear more than once
        // (header, matchup, plus various Overview sections referencing
        // the team by name), so this checks presence, not uniqueness.
        composeTestRule.onAllNodesWithText("Brentford").onFirst().assertExists()
        composeTestRule.onAllNodesWithText("Sunderland").onFirst().assertExists()
        // The tab bar's own default-selected tab
        composeTestRule.onNodeWithText("Overview").assertExists()
    }

    @Test
    fun `back button invokes the onBack callback`() {
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSampleReportJson())
        var backClicked = false
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = { backClicked = true }, onHistoryClick = {})
        }
        composeTestRule.onNodeWithContentDescription("Back").performClick()
        assert(backClicked)
    }

    @Test
    fun `history button invokes the onHistoryClick callback`() {
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSampleReportJson())
        var historyClicked = false
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = { historyClicked = true })
        }
        composeTestRule.onNodeWithContentDescription("History").performClick()
        assert(historyClicked)
    }

    /** Just needs to not crash -- rememberLauncherForActivityResult's own
     * CreateDocument launch() is a real Android SAF picker intent, not
     * something this JVM test can complete (no shadow wired for it), but
     * onDownloadClick's own body (building the sanitized filename and
     * calling launch()) is plain Kotlin, previously fully uncovered. */
    @Test
    fun `download button builds a sanitized filename and launches without crashing`() {
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSampleReportJson())
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithContentDescription("Download JSON").performClick()
    }

    @Test
    fun `share button writes the raw json to cache and opens a real share sheet`() {
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSampleReportJson())
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithContentDescription("Share report (e.g. to ChatGPT or Gemini)").performClick()

        // shareReportJson() doesn't need any Activity-Result shadow like
        // the Download button does -- it's a plain startActivity() call,
        // which Robolectric records rather than actually launching a
        // chooser. Confirms the intent was actually built and sent, not
        // just that the click didn't crash.
        val app = androidx.test.core.app.ApplicationProvider.getApplicationContext<android.app.Application>()
        val nextActivity = org.robolectric.Shadows.shadowOf(app).nextStartedActivity
        assertNotNull(nextActivity)
    }

    @Test
    fun `tapping a different tab switches the rendered content`() {
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSampleReportJson())
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = {})
        }
        // Overview (the default tab) renders a "Match" section card --
        // confirms the starting state before switching.
        composeTestRule.onNodeWithText("Match").assertExists()

        // performScrollTo() is required here: the tab bar is a
        // horizontally-scrollable Row and, under Robolectric's narrow
        // default test viewport (320px), "Squad" (the last tab) lays out
        // beyond the visible/clipped bounds. Without scrolling it into
        // view first, performClick() synthesizes a touch at the node's
        // true (off-screen) root-coordinate center, which silently lands
        // outside the compose root and never reaches the click handler --
        // confirmed live via a full semantics-tree dump showing the tab
        // content never changed despite the click "succeeding" with no
        // exception. That false failure was initially mistaken for a
        // possible real tab-switching bug; it was not one -- with
        // performScrollTo() added, the switch works correctly.
        composeTestRule.onNodeWithText("Squad").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        // "Top scorers" is Squad-tab-exclusive (unlike "Brentford", which
        // also appears in the always-visible header/matchup and so
        // wouldn't actually prove the tab switched). Overview's own
        // "Match" section disappearing confirms the switch actually
        // replaced the content rather than just adding to it.
        composeTestRule.onAllNodesWithText("Top scorers").onFirst().assertExists()
        composeTestRule.onNodeWithText("Match").assertDoesNotExist()
    }

    @Test
    fun `tapping every tab in the bar renders its own real content`() {
        // ReportTabContent's when(tab) dispatch, and each of its 6
        // one-line DecodedTab{...} lambdas (LINEUPS/PERFORMANCE/
        // DISCIPLINE/PROFILE/STANDINGS/CONTEXT), were previously only
        // ever exercised for the default OVERVIEW tab plus SQUAD (the
        // tab-switching test above) -- every other tab was never
        // actually switched to by any test.
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSampleReportJson())
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = {})
        }

        composeTestRule.onNodeWithText("Lineups").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Formations").assertExists()

        composeTestRule.onNodeWithText("Performance").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Attack profile").assertExists()

        composeTestRule.onNodeWithText("Discipline").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Cards per game").assertExists()

        composeTestRule.onNodeWithText("Profile").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Style profile").assertExists()

        composeTestRule.onNodeWithText("Standings").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Table position").assertExists()

        composeTestRule.onNodeWithText("Context").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Rest").assertExists()

        composeTestRule.onNodeWithText("Form").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        // Rendered once per team (own + opponent form), unlike every
        // other tab's marker above.
        composeTestRule.onAllNodesWithText("Streak & momentum").onFirst().assertExists()

        // Ends on a BACKWARD transition (Form, ordinal 7 -> Overview,
        // ordinal 0) -- every switch above was forward-only, and
        // AnimatedContent's transitionSpec branches on direction.
        composeTestRule.onNodeWithText("Overview").performScrollTo().performClick()
        // Advances past the slide animation's own duration -- the pixel-
        // offset lambda passed to slideInHorizontally/slideOutHorizontally
        // for the backward-transition branch only actually runs once the
        // animation progresses through real frames, not just on the
        // initial recomposition triggered by waitForIdle() alone.
        composeTestRule.mainClock.advanceTimeBy(2000L)
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Match").assertExists()
    }

    @Test
    fun `a tab whose own section decodes to null falls back to its placeholder`() {
        // PlaceholderTab was never rendered by any test -- every fixture
        // used elsewhere in this suite has real data for every tab.
        // Omitting "insights" entirely (leaving `match` and `team`/
        // `generatedAt` so the rest of the screen still renders) makes
        // every insights-derived tab (Performance among them) null.
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(
            """{"team": "Brentford", "generatedAt": "2026-08-31T02:21:23.778Z", "match": {"home_team": "Brentford", "away_team": "Sunderland"}}""",
        )
        composeTestRule.setContent {
            ReportScreen(viewModel = viewModel, onBack = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Performance").performScrollTo().performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Performance not yet implemented.").assertExists()
    }
}
