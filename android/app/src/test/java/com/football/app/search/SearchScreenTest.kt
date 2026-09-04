package com.football.app.search

import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasProgressBarRangeInfo
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.football.app.queue.QueueState
import com.football.app.report.ReportViewModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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
 * notification-permission launchers and the actual queue run -- is an
 * accepted gap, the same category as PythonBridge.kt itself.
 *
 * The progress-bar UI itself doesn't share that limitation, though:
 * SingleSearchProgress/StepProgressBar/QueueStatusCard/parseStepProgress
 * are plain functions of a QueueState value (widened from private to
 * internal, the same precedent SearchQueueService's own
 * buildNotification/notify already set) -- constructing a QueueState
 * directly and rendering them standalone below doesn't touch
 * SearchQueueService's real (unsettable-from-outside) companion
 * StateFlow at all. Everything else (initial render, text input, button
 * enablement, add/remove-from-queue local state, the history button) is
 * real UI/state logic and is covered here too.
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

    @Test
    fun `single search progress shows the team, message, and a determinate bar for a step-prefixed message`() {
        composeTestRule.setContent {
            SingleSearchProgress(QueueState.Running(currentTeam = "Arsenal", index = 0, total = 1, message = "(2/5) Fetching Sofascore"))
        }
        composeTestRule.onNodeWithText("Searching \"Arsenal\"...").assertExists()
        composeTestRule.onNodeWithText("(2/5) Fetching Sofascore").assertExists()
        composeTestRule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo(0.4f, 0f..1f))).assertExists()
    }

    @Test
    fun `single search progress falls back to a default message and an indeterminate bar when blank`() {
        composeTestRule.setContent {
            SingleSearchProgress(QueueState.Running(currentTeam = "Arsenal", index = 0, total = 1, message = ""))
        }
        composeTestRule.onNodeWithText("Computing match insights...").assertExists()
        composeTestRule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo.Indeterminate)).assertExists()
    }

    @Test
    fun `queue status card renders the running row with a determinate bar`() {
        composeTestRule.setContent {
            QueueStatusCard(QueueState.Running(currentTeam = "Arsenal", index = 1, total = 3, message = "(1/4) Scraping"))
        }
        composeTestRule.onNodeWithText("Queue: Arsenal (2/3) -- (1/4) Scraping").assertExists()
        composeTestRule.onNode(hasProgressBarRangeInfo(ProgressBarRangeInfo(0.25f, 0f..1f))).assertExists()
    }

    @Test
    fun `queue status card falls back to 'working…' for a blank running message`() {
        composeTestRule.setContent {
            QueueStatusCard(QueueState.Running(currentTeam = "Arsenal", index = 0, total = 1, message = ""))
        }
        composeTestRule.onNodeWithText("Queue: Arsenal (1/1) -- working…").assertExists()
    }

    @Test
    fun `queue status card renders the finished summary`() {
        composeTestRule.setContent {
            QueueStatusCard(QueueState.Finished(succeeded = 2, failed = 1, lastError = "timeout"))
        }
        composeTestRule.onNodeWithText("Queue finished: 2 succeeded, 1 failed").assertExists()
    }

    @Test
    fun `queue status card renders nothing for Idle`() {
        composeTestRule.setContent {
            QueueStatusCard(QueueState.Idle)
        }
        composeTestRule.onNodeWithText("Queue finished:", substring = true).assertDoesNotExist()
        composeTestRule.onNodeWithText("Queue:", substring = true).assertDoesNotExist()
    }

    @Test
    fun `parseStepProgress reads a leading step-total prefix as a fraction`() {
        assertEquals(0.4f, parseStepProgress("(2/5) Fetching Sofascore"))
        assertEquals(1f, parseStepProgress("(5/5) Done"))
    }

    @Test
    fun `parseStepProgress returns null for a message without a step prefix`() {
        assertNull(parseStepProgress("Fetching Sofascore"))
        assertNull(parseStepProgress(""))
    }

    @Test
    fun `parseStepProgress returns null for a malformed or zero total prefix`() {
        assertNull(parseStepProgress("(2/0) Bad total"))
        assertNull(parseStepProgress("(x/5) Not a number"))
    }
}
