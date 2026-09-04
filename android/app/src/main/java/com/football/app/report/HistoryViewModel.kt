package com.football.app.report

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.football.app.data.history.HistoryEntry
import com.football.app.data.history.HistoryRepository
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Backs HistoryScreen: the list of past searches, plus delete. Reopening
 * a saved entry goes through ReportViewModel.loadFromHistory (this class
 * only owns the list, not the currently-displayed report) -- HistoryScreen
 * calls both, the same "state change drives navigation" pattern
 * SearchScreen already uses for its own Success transition.
 *
 * [ioDispatcher] defaults to the real Dispatchers.IO -- overridable only
 * so a unit test can substitute kotlinx-coroutines-test's test dispatcher.
 * Without this seam, viewModelScope.launch(Dispatchers.IO) dispatches onto
 * the real IO thread pool, which a TestScope's virtual-time scheduler
 * can't see or await (confirmed live: advanceUntilIdle() returned before
 * the launched coroutine had run, since it wasn't scheduled on the test
 * dispatcher at all). Every real caller uses the default.
 */
class HistoryViewModel(
    private val repository: HistoryRepository,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    private val _entries = MutableStateFlow<List<HistoryEntry>>(emptyList())
    val entries: StateFlow<List<HistoryEntry>> = _entries.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch(ioDispatcher) {
            _entries.value = repository.list()
        }
    }

    fun delete(id: String) {
        viewModelScope.launch(ioDispatcher) {
            repository.delete(id)
            _entries.value = repository.list()
        }
    }

    /** Loads the saved raw JSON for [id] into [reportViewModel]; runs off the main thread. */
    fun open(
        id: String,
        reportViewModel: ReportViewModel,
    ) {
        viewModelScope.launch(ioDispatcher) {
            val rawJson = repository.load(id) ?: return@launch
            reportViewModel.loadFromHistory(rawJson)
        }
    }
}
