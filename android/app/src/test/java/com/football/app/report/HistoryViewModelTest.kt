package com.football.app.report

import com.football.app.data.AppJsonTopLevel
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
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
 * HistoryViewModel's refresh()/delete()/open() each launch a real
 * viewModelScope.launch(Dispatchers.IO) coroutine, so viewModelScope needs
 * Dispatchers.Main.immediate available -- setMain(StandardTestDispatcher())
 * supplies that on a plain JVM, and runTest's scheduler is what actually
 * advances the launched coroutine to completion deterministically.
 */
class HistoryViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    private fun newHistoryRepository(): HistoryRepository = HistoryRepository(File.createTempFile("history", "").apply { delete(); mkdirs() })

    @Test
    fun `constructing the view model refreshes entries from the repository`() =
        runTest {
            val repository = newHistoryRepository()
            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            repository.save(report, rawJson)

            val viewModel = HistoryViewModel(repository, dispatcher)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(1, viewModel.entries.value.size)
            assertEquals("Brentford", viewModel.entries.value.first().team)
        }

    @Test
    fun `refresh reloads entries added after construction`() =
        runTest {
            val repository = newHistoryRepository()
            val viewModel = HistoryViewModel(repository, dispatcher)
            dispatcher.scheduler.advanceUntilIdle()
            assertTrue(viewModel.entries.value.isEmpty())

            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            repository.save(report, rawJson)

            viewModel.refresh()
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(1, viewModel.entries.value.size)
        }

    @Test
    fun `delete removes the entry from the repository and refreshes entries`() =
        runTest {
            val repository = newHistoryRepository()
            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            val entry = repository.save(report, rawJson)
            val viewModel = HistoryViewModel(repository, dispatcher)
            dispatcher.scheduler.advanceUntilIdle()
            assertEquals(1, viewModel.entries.value.size)

            viewModel.delete(entry.id)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(viewModel.entries.value.isEmpty())
            assertNull(repository.load(entry.id))
        }

    @Test
    fun `open loads the saved raw json into the given report view model`() =
        runTest {
            val repository = newHistoryRepository()
            val rawJson = loadSample()
            val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
            val entry = repository.save(report, rawJson)
            val viewModel = HistoryViewModel(repository, dispatcher)
            dispatcher.scheduler.advanceUntilIdle()
            val reportViewModel = ReportViewModel()

            viewModel.open(entry.id, reportViewModel)
            dispatcher.scheduler.advanceUntilIdle()

            val state = reportViewModel.state.value
            assertTrue(state is SearchState.Success)
            assertEquals(rawJson, (state as SearchState.Success).rawJson)
        }

    @Test
    fun `open with an id that has no saved file leaves the report view model idle`() =
        runTest {
            val repository = newHistoryRepository()
            val viewModel = HistoryViewModel(repository, dispatcher)
            dispatcher.scheduler.advanceUntilIdle()
            val reportViewModel = ReportViewModel()

            viewModel.open("does-not-exist", reportViewModel)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(reportViewModel.state.value is SearchState.Idle)
        }
}
