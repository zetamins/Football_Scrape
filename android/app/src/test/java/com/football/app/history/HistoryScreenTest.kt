package com.football.app.history

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.football.app.data.AppJsonTopLevel
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
import com.football.app.report.HistoryViewModel
import com.football.app.report.ReportViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

/** Dispatchers.Unconfined (not a StandardTestDispatcher needing manual
 * advancement) as HistoryViewModel's ioDispatcher -- its refresh() body
 * has no internal suspension point, so this runs it to completion
 * synchronously within viewModelScope.launch, avoiding any explicit
 * idling/advancement machinery. Still needs Dispatchers.setMain() first,
 * same as HistoryViewModelTest, since viewModelScope itself requires
 * Dispatchers.Main to be registered before it's ever launched on. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
class HistoryScreenTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun loadSampleReportJson(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    private fun newHistoryViewModel(seeded: Boolean = false): HistoryViewModel {
        val dir = File.createTempFile("history", "").apply { delete(); mkdirs() }
        val repository = HistoryRepository(dir)
        if (seeded) {
            val rawJson = loadSampleReportJson()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            repository.save(report, rawJson)
        }
        return HistoryViewModel(repository, ioDispatcher = Dispatchers.Unconfined)
    }

    /** Seeds a history entry with no match section, so
     * HistoryRepository.opponentOf() returns null -- every other test in
     * this suite uses sample_full_report.json, which always has a real
     * opponent, so HistoryRow's `entry.opponent != null` false branch
     * (single-team title, no "vs" badge) was never reached before. */
    private fun newHistoryViewModelWithOpponentlessEntry(): HistoryViewModel {
        val dir = File.createTempFile("history", "").apply { delete(); mkdirs() }
        val repository = HistoryRepository(dir)
        val rawJson = """{"team": "Brentford", "generatedAt": "2026-08-31T02:21:23.778Z"}"""
        val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
        repository.save(report, rawJson)
        return HistoryViewModel(repository, ioDispatcher = Dispatchers.Unconfined)
    }

    @Test
    fun `shows an empty-state message when there are no saved searches`() {
        composeTestRule.setContent {
            HistoryScreen(historyViewModel = newHistoryViewModel(), reportViewModel = ReportViewModel(), onBack = {}, onReportReady = {})
        }
        composeTestRule.onNodeWithText("No searches yet.").assertExists()
    }

    @Test
    fun `renders a row for a saved search`() {
        composeTestRule.setContent {
            HistoryScreen(historyViewModel = newHistoryViewModel(seeded = true), reportViewModel = ReportViewModel(), onBack = {}, onReportReady = {})
        }
        composeTestRule.onNodeWithText("Brentford vs Sunderland").assertExists()
    }

    @Test
    fun `back icon invokes the onBack callback`() {
        var backClicked = false
        composeTestRule.setContent {
            HistoryScreen(historyViewModel = newHistoryViewModel(), reportViewModel = ReportViewModel(), onBack = { backClicked = true }, onReportReady = {})
        }
        composeTestRule.onNodeWithContentDescription("Back").performClick()
        assert(backClicked)
    }

    @Test
    fun `tapping delete opens a confirmation dialog, cancel dismisses it`() {
        composeTestRule.setContent {
            HistoryScreen(historyViewModel = newHistoryViewModel(seeded = true), reportViewModel = ReportViewModel(), onBack = {}, onReportReady = {})
        }
        composeTestRule.onNodeWithContentDescription("Delete").performClick()
        composeTestRule.onNodeWithText("Delete this search?").assertExists()

        composeTestRule.onNodeWithText("Cancel").performClick()
        composeTestRule.onNodeWithText("Delete this search?").assertDoesNotExist()
        // The entry itself is still there -- cancel didn't delete it.
        composeTestRule.onNodeWithText("Brentford vs Sunderland").assertExists()
    }

    @Test
    fun `confirming delete removes the entry and falls back to the empty state`() {
        composeTestRule.setContent {
            HistoryScreen(historyViewModel = newHistoryViewModel(seeded = true), reportViewModel = ReportViewModel(), onBack = {}, onReportReady = {})
        }
        composeTestRule.onNodeWithContentDescription("Delete").performClick()
        composeTestRule.onNodeWithText("Delete").performClick()
        composeTestRule.onNodeWithText("No searches yet.").assertExists()
    }

    @Test
    fun `renders a single-team row with no opponent badge when the entry has no opponent`() {
        composeTestRule.setContent {
            HistoryScreen(historyViewModel = newHistoryViewModelWithOpponentlessEntry(), reportViewModel = ReportViewModel(), onBack = {}, onReportReady = {})
        }
        composeTestRule.onNodeWithText("Brentford").assertExists()
        composeTestRule.onNodeWithText("vs", substring = false).assertDoesNotExist()
    }

    @Test
    fun `an already-successful report state on entry does not trigger onReportReady`() {
        // The doc comment's own scenario: reportViewModel can already be
        // Success when this screen opens (user came from a live report
        // and tapped History) -- isOpening is false in that case, unlike
        // the click-driven case below, so onReportReady must NOT fire.
        val reportViewModel = ReportViewModel()
        reportViewModel.loadFromHistory(loadSampleReportJson())
        var reportReadyCalls = 0
        composeTestRule.setContent {
            HistoryScreen(
                historyViewModel = newHistoryViewModel(),
                reportViewModel = reportViewModel,
                onBack = {},
                onReportReady = { reportReadyCalls++ },
            )
        }
        composeTestRule.waitForIdle()
        assert(reportReadyCalls == 0)
    }

    @Test
    fun `tapping a row opens it via the history view model`() {
        val historyViewModel = newHistoryViewModel(seeded = true)
        val reportViewModel = ReportViewModel()
        composeTestRule.setContent {
            HistoryScreen(historyViewModel = historyViewModel, reportViewModel = reportViewModel, onBack = {}, onReportReady = {})
        }
        composeTestRule.onNodeWithText("Brentford vs Sunderland").performClick()
        val state = reportViewModel.state.value
        assert(state is com.football.app.report.SearchState.Success)
    }
}
