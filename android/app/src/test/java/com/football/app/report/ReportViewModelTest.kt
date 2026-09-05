package com.football.app.report

import com.football.app.data.AppJsonTopLevel
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
import com.football.app.queue.QueueState
import com.football.app.queue.SearchQueueService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * ReportViewModel's queue-completion watcher (see its own class doc)
 * launches a real viewModelScope.launch { SearchQueueService.queueState
 * .collect { ... } } coroutine from init{}, so every test here needs
 * Dispatchers.Main available the same way HistoryViewModelTest does --
 * setMain(StandardTestDispatcher()) supplies that on a plain JVM, and
 * dispatcher.scheduler.advanceUntilIdle() is what actually advances the
 * launched coroutine deterministically. SearchQueueService.queueState is
 * a companion-object (process-wide) singleton (see its own doc), so
 * every test also resets it before and after to avoid leaking state
 * to/from other test classes.
 */
class ReportViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        SearchQueueService.resetQueueStateForTest()
    }

    @After
    fun tearDown() {
        SearchQueueService.resetQueueStateForTest()
        Dispatchers.resetMain()
    }

    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    private fun newHistoryRepository(): HistoryRepository = HistoryRepository(File.createTempFile("history", "").apply { delete(); mkdirs() })

    @Test
    fun `starts in Idle state`() =
        runTest {
            val viewModel = ReportViewModel()
            assertTrue(viewModel.state.value is SearchState.Idle)
        }

    @Test
    fun `starts with isSingleSearchRun false and no error`() =
        runTest {
            val viewModel = ReportViewModel()
            assertTrue(!viewModel.isSingleSearchRun.value)
            assertNull(viewModel.singleSearchError.value)
        }

    @Test
    fun `loadFromHistory decodes valid raw json into a Success state carrying the exact bytes`() =
        runTest {
            val viewModel = ReportViewModel()
            val rawJson = loadSample()

            viewModel.loadFromHistory(rawJson)

            val state = viewModel.state.value
            assertTrue(state is SearchState.Success)
            state as SearchState.Success
            assertEquals("Brentford", state.report.team)
            assertEquals(rawJson, state.rawJson)
        }

    @Test
    fun `loadFromHistory with malformed json becomes an Error mentioning the saved report couldn't be read`() =
        runTest {
            val viewModel = ReportViewModel()

            viewModel.loadFromHistory("not valid json at all")

            val state = viewModel.state.value
            assertTrue(state is SearchState.Error)
            assertTrue((state as SearchState.Error).message.startsWith("Could not read saved report:"))
        }

    @Test
    fun `resetToIdle returns to Idle after a Success`() =
        runTest {
            val viewModel = ReportViewModel()
            viewModel.loadFromHistory(loadSample())
            assertTrue(viewModel.state.value is SearchState.Success)

            viewModel.resetToIdle()

            assertTrue(viewModel.state.value is SearchState.Idle)
        }

    @Test
    fun `loadMostRecentFromHistory with no historyRepository leaves state Idle`() =
        runTest {
            val viewModel = ReportViewModel(historyRepository = null)

            viewModel.loadMostRecentFromHistory()

            assertTrue(viewModel.state.value is SearchState.Idle)
        }

    @Test
    fun `loadMostRecentFromHistory with an empty history leaves state Idle`() =
        runTest {
            val viewModel = ReportViewModel(historyRepository = newHistoryRepository())

            viewModel.loadMostRecentFromHistory()

            assertTrue(viewModel.state.value is SearchState.Idle)
        }

    @Test
    fun `loadMostRecentFromHistory with an indexed entry whose file is missing leaves state Idle`() =
        runTest {
            val dir = File.createTempFile("history", "").apply { delete(); mkdirs() }
            val repository = HistoryRepository(dir)
            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            val entry = repository.save(report, rawJson)
            File(dir, "${entry.id}.json").delete()
            val viewModel = ReportViewModel(historyRepository = repository)

            viewModel.loadMostRecentFromHistory()

            assertTrue(viewModel.state.value is SearchState.Idle)
        }

    @Test
    fun `loadMostRecentFromHistory loads the most recently saved entry into a Success state`() =
        runTest {
            val repository = newHistoryRepository()
            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            repository.save(report, rawJson)
            val viewModel = ReportViewModel(historyRepository = repository)

            viewModel.loadMostRecentFromHistory()

            val state = viewModel.state.value
            assertTrue(state is SearchState.Success)
            assertEquals(rawJson, (state as SearchState.Success).rawJson)
        }

    @Test
    fun `markSingleSearchStarted arms isSingleSearchRun and clears any previous error`() =
        runTest {
            val viewModel = ReportViewModel()

            viewModel.markSingleSearchStarted()

            assertTrue(viewModel.isSingleSearchRun.value)
            assertNull(viewModel.singleSearchError.value)
        }

    @Test
    fun `markSingleSearchStarted clears a stale error left over from a previous failed run`() =
        runTest {
            val viewModel = ReportViewModel()
            viewModel.markSingleSearchStarted()
            SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 0, failed = 1, lastError = "boom"))
            dispatcher.scheduler.advanceUntilIdle()
            assertEquals("boom", viewModel.singleSearchError.value)

            viewModel.markSingleSearchStarted()

            assertNull(viewModel.singleSearchError.value)
        }

    // The following tests exercise the actual bug fix: this promotion
    // logic used to live as SearchScreen-local remember{}/LaunchedEffect
    // state, which was torn down the instant the user navigated away from
    // SearchScreen (e.g. to open a saved report from History) while a
    // single search was still Running -- confirmed live, that left a
    // still-running queue's eventual Finished result permanently
    // unobserved. ReportViewModel has no notion of "which screen is
    // showing" at all; it only depends on viewModelScope (cleared solely
    // when the hosting Activity is destroyed) and the process-wide
    // SearchQueueService.queueState, so driving the queue directly here
    // -- with no SearchScreen composed anywhere -- is exactly the
    // regression scenario the fix needs to survive.

    @Test
    fun `a successful queue-of-one finish promotes the saved report to Success with nothing observing SearchScreen`() =
        runTest {
            val repository = newHistoryRepository()
            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            repository.save(report, rawJson)
            val viewModel = ReportViewModel(historyRepository = repository)
            viewModel.markSingleSearchStarted()

            SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 1, failed = 0))
            dispatcher.scheduler.advanceUntilIdle()

            val state = viewModel.state.value
            assertTrue(state is SearchState.Success)
            assertEquals(rawJson, (state as SearchState.Success).rawJson)
            assertTrue(!viewModel.isSingleSearchRun.value)
        }

    @Test
    fun `a failed queue-of-one finish sets singleSearchError instead of touching state`() =
        runTest {
            val viewModel = ReportViewModel()
            viewModel.markSingleSearchStarted()

            SearchQueueService.setQueueStateForTest(
                QueueState.Finished(succeeded = 0, failed = 1, lastError = "No team found matching \"asdf\"."),
            )
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals("No team found matching \"asdf\".", viewModel.singleSearchError.value)
            assertTrue(viewModel.state.value is SearchState.Idle)
            assertTrue(!viewModel.isSingleSearchRun.value)
        }

    @Test
    fun `a failed queue-of-one finish with no lastError falls back to a generic message`() =
        runTest {
            val viewModel = ReportViewModel()
            viewModel.markSingleSearchStarted()

            SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 0, failed = 1, lastError = null))
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals("Search failed.", viewModel.singleSearchError.value)
        }

    @Test
    fun `a queue Finished state is ignored when isSingleSearchRun was never armed -- a batch queue run, for example`() =
        runTest {
            val viewModel = ReportViewModel()
            // markSingleSearchStarted() deliberately not called -- mirrors
            // a batch queue run, which never arms this flag.

            SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 1, failed = 0))
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(viewModel.state.value is SearchState.Idle)
            assertNull(viewModel.singleSearchError.value)
        }

    @Test
    fun `a Running queue state does not disarm isSingleSearchRun`() =
        runTest {
            val viewModel = ReportViewModel()
            viewModel.markSingleSearchStarted()

            SearchQueueService.setQueueStateForTest(
                QueueState.Running(currentTeam = "Arsenal", index = 0, total = 1, message = "Searching..."),
            )
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(viewModel.isSingleSearchRun.value)
        }

    @Test
    fun `the completion watcher fires across a Running-then-Finished transition with no SearchScreen involved at all`() =
        runTest {
            val repository = newHistoryRepository()
            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            val viewModel = ReportViewModel(historyRepository = repository)
            viewModel.markSingleSearchStarted()

            SearchQueueService.setQueueStateForTest(
                QueueState.Running(currentTeam = "Brentford", index = 0, total = 1, message = "Scraping..."),
            )
            dispatcher.scheduler.advanceUntilIdle()
            assertTrue(viewModel.state.value is SearchState.Idle)

            // The queue itself saves to history before flipping to
            // Finished (see SearchQueueService.runQueue) -- replicated
            // here since this test drives queueState directly.
            repository.save(report, rawJson)
            SearchQueueService.setQueueStateForTest(QueueState.Finished(succeeded = 1, failed = 0))
            dispatcher.scheduler.advanceUntilIdle()

            val state = viewModel.state.value
            assertTrue(state is SearchState.Success)
            assertEquals(rawJson, (state as SearchState.Success).rawJson)
        }
}
