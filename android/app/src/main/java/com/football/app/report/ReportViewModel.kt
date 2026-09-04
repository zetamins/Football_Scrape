package com.football.app.report

import androidx.lifecycle.ViewModel
import com.football.app.data.AppJsonTopLevel
import com.football.app.data.history.HistoryRepository
import com.football.app.data.model.ReportJson
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerializationException

/**
 * Nav-graph-scoped (both SearchScreen and ReportScreen observe the same
 * instance -- see frontend/DESIGN.md's Screen/nav section) rather than
 * per-screen, since Search has no state of its own beyond this shared
 * one. Manual DI: historyRepository is nullable/optional -- production
 * always passes a real one from FootballNavHost (it needs a Context-
 * derived directory), but a plain unit test constructing this ViewModel
 * shouldn't have to fake one just to call loadFromHistory().
 *
 * Previously also ran a search directly (a `search(teamName)` method
 * driving its own viewModelScope coroutine against a ReportRepository).
 * Removed: SearchScreen now routes every search -- single or batch --
 * through SearchQueueService instead (a queue of one for a single team),
 * so it gets the same foreground-service + battery-optimization-
 * exemption protection the batch queue already had. Confirmed live this
 * was a real gap, not a theoretical one: a single search tied to this
 * ViewModel's coroutine had no such protection and could stall
 * indefinitely once the Activity lost visibility. See
 * loadMostRecentFromHistory() below for how Success is reached now.
 */
class ReportViewModel(
    private val historyRepository: HistoryRepository? = null,
) : ViewModel() {
    private val _state = MutableStateFlow<SearchState>(SearchState.Idle)
    val state: StateFlow<SearchState> = _state.asStateFlow()

    /** Called after a single search completes via SearchQueueService
     * (queue-of-one) rather than a direct search() call. The service
     * uses its own ReportRepository instance and already saved the
     * result to History before this fires (SearchQueueService.runQueue()
     * calls historyRepository.save() before updating queueState to
     * Finished), so "most recent history entry" is the report that
     * queue-of-one run just produced -- unambiguous, since queue runs
     * are strictly one-at-a-time (see SearchQueueService's own
     * runJob?.isActive guard). */
    fun loadMostRecentFromHistory() {
        val entry = historyRepository?.list()?.firstOrNull() ?: return
        val rawJson = historyRepository.load(entry.id) ?: return
        loadFromHistory(rawJson)
    }

    /** Called when leaving Report via its back button. Without this, state
     * stays Success after popBackStack() -- SearchScreen's own
     * LaunchedEffect(state) reacts to that same still-Success value and
     * immediately re-navigates forward to Report again (confirmed live:
     * the back button appeared to do nothing at all). */
    fun resetToIdle() {
        _state.value = SearchState.Idle
    }

    /** Reopens a report previously saved to history, bypassing the network/Python call entirely. */
    fun loadFromHistory(rawJson: String) {
        _state.value =
            try {
                SearchState.Success(AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson), rawJson)
            } catch (e: SerializationException) {
                SearchState.Error("Could not read saved report: ${e.message}")
            }
    }
}
