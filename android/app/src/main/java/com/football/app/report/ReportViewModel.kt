package com.football.app.report

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.football.app.data.ReportRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Nav-graph-scoped (both SearchScreen and ReportScreen observe the same
 * instance -- see frontend/DESIGN.md's Screen/nav section) rather than
 * per-screen, since Search has no state of its own beyond this shared
 * one. Manual DI: constructed with a default ReportRepository() rather
 * than through Hilt/Koin (see DESIGN.md's DI decision).
 */
class ReportViewModel(private val repository: ReportRepository = ReportRepository()) : ViewModel() {
    private val _state = MutableStateFlow<SearchState>(SearchState.Idle)
    val state: StateFlow<SearchState> = _state.asStateFlow()

    fun search(teamName: String) {
        viewModelScope.launch(Dispatchers.IO) {
            repository.search(teamName) { newState -> _state.value = newState }
        }
    }
}
