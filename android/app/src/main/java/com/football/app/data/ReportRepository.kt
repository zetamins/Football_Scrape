package com.football.app.data

import com.chaquo.python.PyException
import com.football.app.data.bridge.PythonBridge
import com.football.app.data.model.FetchFailure
import com.football.app.data.model.ReportJson
import com.football.app.data.model.SourceStatus
import com.football.app.report.SearchState
import kotlinx.serialization.SerializationException

/**
 * Owns the one Chaquopy call the app makes to fetch a report. Runs on
 * the caller's dispatcher -- this class doesn't dispatch itself, so it
 * stays easy to unit test without coroutine-dispatcher mocking
 * (ReportViewModel is responsible for Dispatchers.IO).
 *
 * [runReport] defaults to the real [PythonBridge.runReport] call --
 * overridable only so a unit test can substitute a fake without needing
 * Chaquopy's native Python runtime (which [PythonBridge] itself has no
 * seam to fake around, since it calls the static `Python.getInstance()`
 * singleton directly). Every real caller uses the default; this is the
 * one point in the class this repository's own docstring already claims
 * ("stays easy to unit test") actually needed a seam to be true.
 */
class ReportRepository(
    private val runReport: (
        String,
        PythonBridge.ProgressListener,
        PythonBridge.SourceProgressListener,
        PythonBridge.FailureListener,
    ) -> String = PythonBridge::runReport,
) {
    /**
     * Synchronous/blocking (see PythonBridge's own docstring for why).
     * onState fires multiple times during the call -- a Loading update
     * per free-text message and per completed source -- before exactly
     * one final Success or Error.
     */
    fun search(
        teamName: String,
        onState: (SearchState) -> Unit,
    ) {
        val sourcesSeen = mutableListOf<SourceStatus>()
        val failuresSeen = mutableListOf<FetchFailure>()
        onState(SearchState.Loading(message = "Searching for \"$teamName\"..."))

        try {
            // Explicit `object : Interface { override fun ... }` here,
            // NOT SAM-constructor lambda syntax (`ProgressListener {
            // ... }`) -- confirmed live that the lambda form still
            // crashed release builds ("TypeError: b implements multiple
            // functional interfaces") even with every relevant proguard
            // -keep rule in place. Root cause: ProgressListener.onMessage
            // and SourceProgressListener.onSourceStatus share an
            // identical erased signature (String) -> Unit, and Kotlin
            // 2.0's default indy-based SAM conversion doesn't necessarily
            // emit a distinct static class per lambda for R8 to protect
            // in the first place -- there was nothing for `-keep class *
            // implements ...` to match against. `object :` syntax always
            // compiles to a real, separately-named class in the dex
            // regardless of indy settings, which is what actually fixed
            // it (verified live). SonarQube's kotlin:S6516 flags this as
            // "replace with lambda expression" -- suppressed deliberately:
            // that suggestion is exactly the change that caused the crash
            // in the first place, since a SAM-constructor lambda is what
            // collapsed under R8. Do not "fix" this finding.
            @Suppress("kotlin:S6516")
            val progressListener =
                object : PythonBridge.ProgressListener {
                    override fun onMessage(message: String) {
                        onState(SearchState.Loading(sources = sourcesSeen.toList(), message = message, failures = failuresSeen.toList()))
                    }
                }

            @Suppress("kotlin:S6516")
            val sourceProgressListener =
                object : PythonBridge.SourceProgressListener {
                    override fun onSourceStatus(statusJson: String) {
                        sourcesSeen.add(AppJson.decodeFromString(SourceStatus.serializer(), statusJson))
                        onState(SearchState.Loading(sources = sourcesSeen.toList(), message = "", failures = failuresSeen.toList()))
                    }
                }

            @Suppress("kotlin:S6516")
            val failureListener =
                object : PythonBridge.FailureListener {
                    override fun onFailure(failureJson: String) {
                        failuresSeen.add(AppJson.decodeFromString(FetchFailure.serializer(), failureJson))
                        onState(SearchState.Loading(sources = sourcesSeen.toList(), message = "", failures = failuresSeen.toList()))
                    }
                }
            val json = runReport(teamName, progressListener, sourceProgressListener, failureListener)
            onState(SearchState.Success(AppJsonTopLevel.decodeFromString(ReportJson.serializer(), json), json))
        } catch (e: PyException) {
            onState(SearchState.Error(e.message ?: "Search failed"))
        } catch (e: SerializationException) {
            onState(SearchState.Error("Could not read the report: ${e.message}"))
        }
    }
}
