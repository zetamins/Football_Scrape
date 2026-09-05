package com.football.app.navigation

import android.content.Context
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
import com.football.app.onboarding.OnboardingPrefs
import com.football.app.queue.QueueState
import com.football.app.queue.SearchQueueService
import kotlinx.serialization.json.Json
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

/** Never navigates into a state that would click Search/Run queue --
 * same reasoning as SearchScreenTest (that path starts a real
 * foreground service requiring Chaquopy's native Python runtime,
 * unavailable in a plain JVM test). Onboarding <-> Search <-> History
 * navigation itself doesn't touch that and is covered here. */
@RunWith(RobolectricTestRunner::class)
class FootballNavHostTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    // A test below drives SearchQueueService.queueState directly to
    // simulate a search running/finishing -- same companion-StateFlow
    // leak-across-test-methods concern as SearchScreenTest's own reset.
    @Before
    fun resetQueueState() {
        SearchQueueService.resetQueueStateForTest()
    }

    @After
    fun tearDownQueueState() {
        SearchQueueService.resetQueueStateForTest()
    }

    @Test
    fun `starts on Onboarding for a first launch`() {
        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Get started").assertExists()
    }

    @Test
    fun `starts on Search once onboarding has already been seen`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("DeepXI").assertExists()
    }

    @Test
    fun `get started navigates from Onboarding to Search and marks onboarding as seen`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Get started").performClick()
        composeTestRule.onNodeWithText("DeepXI").assertExists()
        assert(OnboardingPrefs(context).hasSeenOnboarding)
    }

    @Test
    fun `history icon on Search navigates to History`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Team name").assertExists()

        composeTestRule.onNodeWithContentDescription("History").performClick()
        composeTestRule.onNodeWithText("No searches yet.").assertExists()
    }

    /**
     * Reaches the REPORT destination via History -> tap a saved entry,
     * not via a live search -- the only path to REPORT that doesn't
     * require Chaquopy's native Python runtime (SearchScreen's own
     * Search/Run-queue buttons start a real foreground service that
     * needs it, an accepted, documented gap elsewhere in this suite).
     * HistoryViewModel.open()/ReportViewModel.loadFromHistory() are pure
     * I/O + JSON decode, so this exercises FootballNavHost's REPORT
     * composable() lambda (previously fully uncovered) for real.
     */
    @Test
    fun `tapping a saved entry in History navigates to Report`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        // Same historyDir FootballNavHost itself constructs
        // (Context.filesDir/history) -- seeding through it here matches
        // exactly what a real saved search would have written.
        val rawJson =
            checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
                "sample_full_report.json missing from test resources"
            }.bufferedReader().readText()
        val report = Json { ignoreUnknownKeys = true }.decodeFromString(ReportJson.serializer(), rawJson)
        val historyRepository = HistoryRepository(File(context.filesDir, "history"))
        historyRepository.save(report, rawJson)

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithContentDescription("History").performClick()
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Brentford vs Sunderland").performClick()
        // HistoryViewModel.open() dispatches onto the real
        // Dispatchers.IO (FootballNavHost doesn't expose a test seam to
        // swap it, unlike HistoryViewModelTest's own ioDispatcher param)
        // -- waitForIdle() alone doesn't wait for that background-thread
        // hop, so a plain assertExists() right after the click flaked
        // (confirmed live: failed with "could not find any node...
        // Overview" even though the entry click itself registered fine).
        // waitUntil polls (with waitForIdle between attempts) until the
        // async loadFromHistory()-driven recomposition lands.
        composeTestRule.waitUntil(timeoutMillis = 5_000) {
            composeTestRule.onAllNodesWithText("Overview").fetchSemanticsNodes().isNotEmpty()
        }

        // "Overview" is the default-selected report tab pill -- unlike
        // "Generated <date>" or the team-vs-team title (both of which
        // HistoryRow itself also renders, so asserting on them here
        // would pass even if the click never actually navigated away
        // from History; confirmed live this exact mistake initially
        // produced a false-positive-passing test with Kover still
        // showing FootballNavHost's REPORT composable() lambda fully
        // uncovered). "Overview" only exists on Report's own tab bar.
        composeTestRule.onNodeWithText("Overview").assertExists()

        // Report's own onBack (resetToIdle() + popBackStack()) --
        // previously unexercised, since no test reached Report from
        // History before this one. Returning to History (not Search)
        // confirms popBackStack() actually walked back one entry, not
        // to the graph's start destination.
        composeTestRule.onNodeWithContentDescription("Back").performClick()
        composeTestRule.onNodeWithText("Brentford vs Sunderland").assertExists()
    }

    /**
     * Reproduces the reported bug directly through the app's real wiring
     * (the single ReportViewModel instance FootballNavHost threads
     * through Search/Report/History, not a standalone ReportViewModel()
     * like ReportViewModelTest uses): start a single search, then -- while
     * SearchQueueService.queueState is still Running -- navigate away to
     * History and open a completely unrelated saved report. Confirmed
     * live this used to permanently lose the running search's eventual
     * result: SearchScreen's own LaunchedEffect(queueState) (the only
     * code that used to promote a Finished queue-of-one into view) was
     * torn down the moment SearchScreen left composition, along with
     * isSingleSearchRun's value. The fix moved that watcher onto
     * ReportViewModel itself (see its own doc comment) -- this test
     * proves it now survives exactly this navigation sequence, ending
     * with the newly-finished search's report replacing whatever History
     * report happened to be showing, with no re-navigation back to
     * Search required.
     */
    @Test
    fun `a single search still running when the user opens an unrelated History report is not lost -- its result still surfaces once finished`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        val rawJson =
            checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
                "sample_full_report.json missing from test resources"
            }.bufferedReader().readText()
        val json = Json { ignoreUnknownKeys = true }
        val historyRepository = HistoryRepository(File(context.filesDir, "history"))
        // The unrelated, previously-saved report the user is about to
        // open from History mid-search.
        historyRepository.save(json.decodeFromString(ReportJson.serializer(), rawJson), rawJson)

        composeTestRule.setContent {
            FootballNavHost()
        }

        // Start a single search for a different team -- isSingleSearchRun
        // is armed synchronously by the Search button's own onClick,
        // before startQueue() (same precedent as SearchScreenTest), so
        // this doesn't need the battery/notification launcher chain
        // driven to completion.
        composeTestRule.onNodeWithText("Team name").performTextInput("Chelsea")
        composeTestRule.onNodeWithText("Search").performClick()
        composeTestRule.waitForIdle()
        SearchQueueService.setQueueStateForTest(
            QueueState.Running(currentTeam = "Chelsea", index = 0, total = 1, message = "Scraping..."),
        )
        composeTestRule.waitForIdle()

        // Navigate away from SearchScreen entirely while the search is
        // still Running -- the exact step that used to lose it.
        composeTestRule.onNodeWithContentDescription("History").performClick()
        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Brentford vs Sunderland").performClick()
        composeTestRule.waitUntil(timeoutMillis = 5_000) {
            composeTestRule.onAllNodesWithText("Brentford").fetchSemanticsNodes().isNotEmpty()
        }

        // The Chelsea search finishes now, while History's Brentford
        // report is what's on screen -- SearchQueueService.runQueue()
        // saves to history before flipping to Finished, replicated here
        // since this test drives queueState directly. A plain text
        // substitution on the raw JSON (rather than decoding, copying
        // just the top-level `team` field, and re-encoding) is
        // deliberate: MatchupHeader's home/away team text actually comes
        // from a separately-decoded nested `match` object, not the
        // top-level `team` field, so copy(team = "Chelsea") alone left
        // "Brentford" still rendered and didn't prove anything.
        val chelseaRawJson = rawJson.replace("Brentford", "Chelsea")
        val chelseaReport = json.decodeFromString(ReportJson.serializer(), chelseaRawJson)
        historyRepository.save(chelseaReport, chelseaRawJson)
        SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 1, failed = 0))

        // No further navigation happens (SearchScreen -- the only screen
        // that used to react to Success -- isn't even composed right
        // now); the already-visible Report screen just picks up the new
        // Success value reactively.
        composeTestRule.waitUntil(timeoutMillis = 5_000) {
            composeTestRule.onAllNodesWithText("Chelsea").fetchSemanticsNodes().isNotEmpty()
        }
        // Brentford (the report the user was looking at from History)
        // must be gone entirely -- otherwise this could pass merely
        // because "Chelsea" happens to appear somewhere without the
        // screen having actually switched reports.
        composeTestRule.onAllNodesWithText("Brentford").assertCountEquals(0)
    }
}
