package com.football.app.search

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.football.app.report.ReportViewModel
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Deliberately never clicks "Search" or "Run queue" -- both eventually
 * call SearchQueueService.start(), which starts a real foreground
 * service whose onCreate() constructs a ReportRepository bound to the
 * real PythonBridge::runReport, requiring Chaquopy's native Python
 * runtime (confirmed unavailable in a plain JVM test by
 * SearchQueueServiceTest's own doc comment, which avoids onCreate() for
 * exactly this reason). That whole path -- battery-optimization/
 * notification-permission launchers, the actual queue run, and the
 * progress-bar UI that only renders once SearchQueueService.queueState
 * (a private companion field this test can't set directly) transitions
 * away from Idle -- is an accepted gap, the same category as
 * PythonBridge.kt itself. Everything else (initial render, text input,
 * button enablement, add/remove-from-queue local state, the history
 * button) is real UI/state logic and is covered here.
 */
@RunWith(RobolectricTestRunner::class)
class SearchScreenTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders the wordmark, search field, and disabled search button initially`() {
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("DeepXI").assertExists()
        composeTestRule.onNodeWithText("Team name").assertExists()
        composeTestRule.onNodeWithText("Search").assertIsNotEnabled()
        composeTestRule.onNodeWithText("Batch search").assertExists()
    }

    @Test
    fun `typing a team name enables the search button`() {
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Arsenal")
        composeTestRule.onNodeWithText("Search").assertIsEnabled()
    }

    @Test
    fun `history icon invokes the onHistoryClick callback`() {
        var historyClicked = false
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = { historyClicked = true })
        }
        composeTestRule.onNodeWithContentDescription("History").performClick()
        assert(historyClicked)
    }

    @Test
    fun `add to queue appends the typed team and clears the field`() {
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Arsenal")
        composeTestRule.onNodeWithText("Add \"Arsenal\" to queue").performClick()
        composeTestRule.onNodeWithText("Arsenal").assertExists()
        composeTestRule.onNodeWithText("Add to queue").assertExists()
    }

    @Test
    fun `remove button drops a queued team`() {
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Arsenal")
        composeTestRule.onNodeWithText("Add \"Arsenal\" to queue").performClick()
        composeTestRule.onNodeWithText("Run queue (1)").assertExists()

        composeTestRule.onNodeWithContentDescription("Remove").performClick()
        composeTestRule.onNodeWithText("Run queue (1)").assertDoesNotExist()
        composeTestRule.onNodeWithText("Arsenal").assertDoesNotExist()
    }

    @Test
    fun `adding the same team twice does not duplicate it in the queue`() {
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Arsenal")
        composeTestRule.onNodeWithText("Add \"Arsenal\" to queue").performClick()
        composeTestRule.onNodeWithText("Team name").performTextInput("Arsenal")
        composeTestRule.onNodeWithText("Add \"Arsenal\" to queue").performClick()
        composeTestRule.onNodeWithText("Run queue (1)").assertExists()
    }
}
