package com.football.app.report

import com.football.app.data.model.ReportJson
import com.football.app.data.model.SourceStatus

/**
 * Shared UI state for both Search and Report screens -- ReportViewModel
 * (nav-graph-scoped, see frontend/DESIGN.md's Screen/nav section)
 * exposes exactly one StateFlow<SearchState>; both screens observe the
 * same instance rather than each screen owning separate state.
 */
sealed interface SearchState {
    data object Idle : SearchState
    data class Loading(val sources: List<SourceStatus> = emptyList(), val message: String = "") : SearchState
    data class Success(val report: ReportJson) : SearchState
    data class Error(val message: String) : SearchState
}
