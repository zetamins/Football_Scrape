package com.football.app.report

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.football.app.data.history.HistoryEntry
import com.football.app.data.history.HistoryRepository
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
 */
class HistoryViewModel(
    private val repository: HistoryRepository,
) : ViewModel() {
    private val _entries = MutableStateFlow<List<HistoryEntry>>(emptyList())
    val entries: StateFlow<List<HistoryEntry>> = _entries.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch(Dispatchers.IO) {
            _entries.value = repository.list()
        }
    }

    fun delete(id: String) {
        viewModelScope.launch(Dispatchers.IO) {
            repository.delete(id)
            _entries.value = repository.list()
        }
    }

    /** Loads the saved raw JSON for [id] into [reportViewModel]; runs off the main thread. */
    fun open(
        id: String,
        reportViewModel: ReportViewModel,
    ) {
        viewModelScope.launch(Dispatchers.IO) {
            val rawJson = repository.load(id) ?: return@launch
            reportViewModel.loadFromHistory(rawJson)
        }
    }
}
