package com.football.app.data

import com.chaquo.python.PyException
import com.football.app.data.bridge.PythonBridge
import com.football.app.data.model.ReportJson
import com.football.app.data.model.SourceStatus
import com.football.app.report.SearchState
import kotlinx.serialization.SerializationException

/**
 * Owns the one Chaquopy call the app makes to fetch a report. Runs on
 * the caller's dispatcher -- this class doesn't dispatch itself, so it
 * stays easy to unit test without coroutine-dispatcher mocking
 * (ReportViewModel is responsible for Dispatchers.IO).
 */
class ReportRepository {
    /**
     * Synchronous/blocking (see PythonBridge's own docstring for why).
     * onState fires multiple times during the call -- a Loading update
     * per free-text message and per completed source -- before exactly
     * one final Success or Error.
     */
    fun search(teamName: String, onState: (SearchState) -> Unit) {
        val sourcesSeen = mutableListOf<SourceStatus>()
        onState(SearchState.Loading(message = "Searching for \"$teamName\"..."))

        try {
            val json = PythonBridge.runReport(
                teamName = teamName,
                onProgress = PythonBridge.ProgressListener { message ->
                    onState(SearchState.Loading(sources = sourcesSeen.toList(), message = message))
                },
                onSourceProgress = PythonBridge.SourceProgressListener { statusJson ->
                    sourcesSeen.add(AppJson.decodeFromString(SourceStatus.serializer(), statusJson))
                    onState(SearchState.Loading(sources = sourcesSeen.toList(), message = ""))
                },
            )
            onState(SearchState.Success(AppJsonTopLevel.decodeFromString(ReportJson.serializer(), json), json))
        } catch (e: PyException) {
            onState(SearchState.Error(e.message ?: "Search failed"))
        } catch (e: SerializationException) {
            onState(SearchState.Error("Could not read the report: ${e.message}"))
        }
    }
}
