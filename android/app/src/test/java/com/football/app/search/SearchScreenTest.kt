package com.football.app.search

import android.app.Activity
import android.app.Application
import android.content.Context
import android.os.PowerManager
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasProgressBarRangeInfo
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import com.football.app.data.model.FetchFailure
import com.football.app.queue.QueueState
import com.football.app.queue.SearchQueueService
import com.football.app.report.ReportViewModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf

/**
 * "Search"/"Run queue" ARE clicked below, and -- unlike an earlier pass
 * over this file assumed -- the full battery-optimization ->
 * notification-permission launcher chain CAN be driven to completion:
 * AndroidX's Activity Result API bridges through the classic
 * startActivityForResult/onActivityResult mechanism under the hood
 * (confirmed directly, not assumed, via a throwaway diagnostic test),
 * which Robolectric's ShadowActivity.receiveResult() supports. Delivering
 * a result to each chained launcher in turn (see
 * driveLauncherChainToServiceStart() below) genuinely reaches
 * SearchQueueService.start() -- confirmed via
 * shadowOf(application).nextStartedService actually showing the real
 * service Intent with the typed team name(s) in its extras. What stays
 * an accepted gap beyond that point is SearchQueueService.onCreate()
 * itself (Python.start()) -- Robolectric records the startService()
 * call rather than invoking onCreate() for it, the same
 * already-established finding from SearchQueueServiceTest's own
 * `start()` test.
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

    // Some tests below set queueState directly (via setQueueStateForTest)
    // to simulate a queue run completing -- same companion-StateFlow
    // leak-across-test-methods concern as SearchQueueServiceTest's own
    // @Before reset.
    @org.junit.Before
    fun resetQueueState() {
        SearchQueueService.resetQueueStateForTest()
    }

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
    fun `clicking Search, not yet battery-exempted, drives the full chain to a real service start`() {
        var registryOwner: ActivityResultRegistryOwner? = null
        composeTestRule.setContent {
            registryOwner = LocalContext.current as? ActivityResultRegistryOwner
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Arsenal")
        composeTestRule.onNodeWithText("Search").performClick()
        composeTestRule.waitForIdle()

        val serviceIntent = driveLauncherChainToServiceStart(registryOwner!!)
        assertEquals(listOf("Arsenal"), serviceIntent.getStringArrayListExtra(SearchQueueService.EXTRA_TEAM_NAMES))
    }

    @Test
    fun `clicking Search, already battery-exempted, skips straight to the notification-permission step`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        shadowOf(powerManager).setIgnoringBatteryOptimizations(context.packageName, true)

        var registryOwner: ActivityResultRegistryOwner? = null
        composeTestRule.setContent {
            registryOwner = LocalContext.current as? ActivityResultRegistryOwner
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Chelsea")
        composeTestRule.onNodeWithText("Search").performClick()
        composeTestRule.waitForIdle()

        // Only ONE launcher fires here (the battery-optimization branch
        // is skipped entirely, not just auto-resolved) -- deliver just
        // the permission-request result directly.
        val shadowActivity = shadowOf(registryOwner as ComponentActivity)
        val pending = shadowActivity.peekNextStartedActivityForResult()
        assertEquals("android.content.pm.action.REQUEST_PERMISSIONS", pending!!.intent.action)
        shadowActivity.receiveResult(pending.intent, Activity.RESULT_OK, null)
        composeTestRule.waitForIdle()

        val serviceIntent = shadowOf(ApplicationProvider.getApplicationContext<Application>()).nextStartedService
        assertEquals(listOf("Chelsea"), serviceIntent!!.getStringArrayListExtra(SearchQueueService.EXTRA_TEAM_NAMES))
    }

    @Test
    fun `clicking Run queue drives the same launcher chain for a batch queue`() {
        var registryOwner: ActivityResultRegistryOwner? = null
        composeTestRule.setContent {
            registryOwner = LocalContext.current as? ActivityResultRegistryOwner
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Arsenal")
        composeTestRule.onNodeWithText("Add \"Arsenal\" to queue").performClick()
        // performScrollTo() is required here: SearchScreen's own Column
        // is vertically scrollable under Robolectric's narrow default
        // test viewport (320x470px), and "Run queue (1)" lays out below
        // the visible 470px height once the queued-team row is showing.
        // Without it, performClick() synthesizes a touch at the node's
        // true (off-screen) coordinates, which silently misses --
        // confirmed live via a full semantics-tree dump showing the node
        // positioned at t=521..b=573 against a 470px-tall viewport. Same
        // root cause as ReportScreenTest's earlier tab-bar finding, just
        // vertical scroll instead of horizontal.
        composeTestRule.onNodeWithText("Run queue (1)").performScrollTo().performClick()
        composeTestRule.waitForIdle()

        val serviceIntent = driveLauncherChainToServiceStart(registryOwner!!)
        assertEquals(listOf("Arsenal"), serviceIntent.getStringArrayListExtra(SearchQueueService.EXTRA_TEAM_NAMES))
    }

    /** Delivers RESULT_OK to the battery-optimization launcher, then to
     * the notification-permission launcher it chains to, and returns the
     * resulting SearchQueueService start Intent. */
    private fun driveLauncherChainToServiceStart(registryOwner: ActivityResultRegistryOwner): android.content.Intent {
        val shadowActivity = shadowOf(registryOwner as ComponentActivity)
        val batteryOptPending = shadowActivity.peekNextStartedActivityForResult()
        assertEquals("android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS", batteryOptPending!!.intent.action)
        shadowActivity.receiveResult(batteryOptPending.intent, Activity.RESULT_OK, null)
        composeTestRule.waitForIdle()

        val permissionPending = shadowActivity.peekNextStartedActivityForResult()
        assertEquals("android.content.pm.action.REQUEST_PERMISSIONS", permissionPending!!.intent.action)
        shadowActivity.receiveResult(permissionPending.intent, Activity.RESULT_OK, null)
        composeTestRule.waitForIdle()

        val app = ApplicationProvider.getApplicationContext<Application>()
        return checkNotNull(shadowOf(app).nextStartedService) { "SearchQueueService was never started" }
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
    fun `single search progress lists each failed link with its source, reason, and url`() {
        val failures =
            listOf(
                FetchFailure("fotmob", "https://api.fotmob.com/matches", "HTTP 403"),
                FetchFailure("sofascore", "https://www.sofascore.com/api/v1/team/1", "timed out"),
            )
        composeTestRule.setContent {
            SingleSearchProgress(QueueState.Running(currentTeam = "Arsenal", index = 0, total = 1, message = "Working", failures = failures))
        }
        composeTestRule.onNodeWithText("2 links failed").assertExists()
        composeTestRule.onNodeWithText("fotmob — HTTP 403").assertExists()
        composeTestRule.onNodeWithText("https://api.fotmob.com/matches").assertExists()
        composeTestRule.onNodeWithText("sofascore — timed out").assertExists()
    }

    @Test
    fun `failed links header is singular for one failure`() {
        composeTestRule.setContent {
            FailedLinksList(listOf(FetchFailure("goal", "https://api.goal.com/x", "HTTP 500")))
        }
        composeTestRule.onNodeWithText("1 link failed").assertExists()
    }

    @Test
    fun `failed links list renders nothing when there are no failures`() {
        composeTestRule.setContent {
            SingleSearchProgress(QueueState.Running(currentTeam = "Arsenal", index = 0, total = 1, message = "Working"))
        }
        composeTestRule.onNodeWithText("Arsenal", substring = true).assertExists()
        composeTestRule.onNodeWithText("failed", substring = true).assertDoesNotExist()
    }

    @Test
    fun `queue status card also lists failed links for a running batch`() {
        val failures = listOf(FetchFailure("goal", "https://api.goal.com/x", "HTTP 500"))
        composeTestRule.setContent {
            QueueStatusCard(QueueState.Running(currentTeam = "Chelsea", index = 0, total = 2, message = "Working", failures = failures))
        }
        composeTestRule.onNodeWithText("goal — HTTP 500").assertExists()
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
        // The "step parses, total doesn't" direction of the same
        // toIntOrNull() pair -- distinct from "(x/5)" above, which fails
        // on the step half instead.
        assertNull(parseStepProgress("(2/x) Not a number"))
    }

    @Test
    fun `a single search completing successfully loads the report and signals ready`() {
        // isSingleSearchRun is set synchronously by the Search button's
        // own onClick, before startQueue() -- true regardless of whether
        // the battery/notification launcher chain ever completes, so
        // this doesn't need driveLauncherChainToServiceStart() at all.
        val context = ApplicationProvider.getApplicationContext<Context>()
        val historyRepository =
            com.football.app.data.history.HistoryRepository(java.io.File(context.filesDir, "history-${System.nanoTime()}"))
        val rawJson =
            checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
                "sample_full_report.json missing from test resources"
            }.bufferedReader().readText()
        val report =
            kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
                .decodeFromString(com.football.app.data.model.ReportJson.serializer(), rawJson)
        historyRepository.save(report, rawJson)

        val viewModel = ReportViewModel(historyRepository = historyRepository)
        var readySignaled = false
        composeTestRule.setContent {
            SearchScreen(viewModel = viewModel, onReportReady = { readySignaled = true }, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Brentford")
        composeTestRule.onNodeWithText("Search").performClick()
        composeTestRule.waitForIdle()

        SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 1, failed = 0, lastError = null))
        composeTestRule.waitForIdle()

        assert(readySignaled) { "onReportReady was never called" }
    }

    @Test
    fun `a single search completing with a failure shows the error message`() {
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Xyz")
        composeTestRule.onNodeWithText("Search").performClick()
        composeTestRule.waitForIdle()

        SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 0, failed = 1, lastError = "Could not find a team matching \"Xyz\""))
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Could not find a team matching \"Xyz\"").assertExists()
    }

    @Test
    fun `a single search failure with no lastError falls back to a generic message`() {
        // Every other failure test above supplies a real lastError --
        // the `finished.lastError ?: "Search failed."` null branch was
        // never taken.
        composeTestRule.setContent {
            SearchScreen(viewModel = ReportViewModel(), onReportReady = {}, onHistoryClick = {})
        }
        composeTestRule.onNodeWithText("Team name").performTextInput("Xyz")
        composeTestRule.onNodeWithText("Search").performClick()
        composeTestRule.waitForIdle()

        SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 0, failed = 1, lastError = null))
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Search failed.").assertExists()
    }
}
