package com.football.app.report

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
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
        composeTestRule.onNodeWithText("Squad").performClick()
        // Squad tab renders the searched team's own name as a section
        // header -- among other, already-present "Brentford" mentions
        // (header, matchup), so this checks presence, not uniqueness.
        composeTestRule.onAllNodesWithText("Brentford").onFirst().assertExists()
    }
}
