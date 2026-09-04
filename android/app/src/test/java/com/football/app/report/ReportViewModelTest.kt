package com.football.app.report

import com.football.app.data.AppJsonTopLevel
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class ReportViewModelTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    private fun newHistoryRepository(): HistoryRepository = HistoryRepository(File.createTempFile("history", "").apply { delete(); mkdirs() })

    @Test
    fun `starts in Idle state`() {
        val viewModel = ReportViewModel()
        assertTrue(viewModel.state.value is SearchState.Idle)
    }

    @Test
    fun `loadFromHistory decodes valid raw json into a Success state carrying the exact bytes`() {
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
    fun `loadFromHistory with malformed json becomes an Error mentioning the saved report couldn't be read`() {
        val viewModel = ReportViewModel()

        viewModel.loadFromHistory("not valid json at all")

        val state = viewModel.state.value
        assertTrue(state is SearchState.Error)
        assertTrue((state as SearchState.Error).message.startsWith("Could not read saved report:"))
    }

    @Test
    fun `resetToIdle returns to Idle after a Success`() {
        val viewModel = ReportViewModel()
        viewModel.loadFromHistory(loadSample())
        assertTrue(viewModel.state.value is SearchState.Success)

        viewModel.resetToIdle()

        assertTrue(viewModel.state.value is SearchState.Idle)
    }

    @Test
    fun `loadMostRecentFromHistory with no historyRepository leaves state Idle`() {
        val viewModel = ReportViewModel(historyRepository = null)

        viewModel.loadMostRecentFromHistory()

        assertTrue(viewModel.state.value is SearchState.Idle)
    }

    @Test
    fun `loadMostRecentFromHistory with an empty history leaves state Idle`() {
        val viewModel = ReportViewModel(historyRepository = newHistoryRepository())

        viewModel.loadMostRecentFromHistory()

        assertTrue(viewModel.state.value is SearchState.Idle)
    }

    @Test
    fun `loadMostRecentFromHistory with an indexed entry whose file is missing leaves state Idle`() {
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
    fun `loadMostRecentFromHistory loads the most recently saved entry into a Success state`() {
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
}
