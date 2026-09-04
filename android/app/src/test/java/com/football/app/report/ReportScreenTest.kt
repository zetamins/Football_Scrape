package com.football.app.report

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
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
}
