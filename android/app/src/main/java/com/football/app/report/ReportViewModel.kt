package com.football.app.report

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.football.app.data.AppJsonTopLevel
import com.football.app.data.ReportRepository
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.SerializationException

/**
 * Nav-graph-scoped (both SearchScreen and ReportScreen observe the same
 * instance -- see frontend/DESIGN.md's Screen/nav section) rather than
 * per-screen, since Search has no state of its own beyond this shared
 * one. Manual DI: constructed with a default ReportRepository() rather
 * than through Hilt/Koin (see DESIGN.md's DI decision). historyRepository
 * is nullable/optional the same way -- production always passes a real
 * one from FootballNavHost (it needs a Context-derived directory), but a
 * plain unit test constructing this ViewModel shouldn't have to fake one
 * just to call search().
 */
class ReportViewModel(
    private val repository: ReportRepository = ReportRepository(),
    private val historyRepository: HistoryRepository? = null,
) : ViewModel() {
    private val _state = MutableStateFlow<SearchState>(SearchState.Idle)
    val state: StateFlow<SearchState> = _state.asStateFlow()

    fun search(teamName: String) {
        viewModelScope.launch(Dispatchers.IO) {
            repository.search(teamName) { newState ->
                _state.value = newState
                if (newState is SearchState.Success) {
                    historyRepository?.save(newState.report, newState.rawJson)
                }
            }
        }
    }

    /** Reopens a report previously saved to history, bypassing the network/Python call entirely. */
    fun loadFromHistory(rawJson: String) {
        _state.value = try {
            SearchState.Success(AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson), rawJson)
        } catch (e: SerializationException) {
            SearchState.Error("Could not read saved report: ${e.message}")
        }
    }
}
