package com.football.app.data.bridge

import com.chaquo.python.Python
import com.football.app.coverage.ExcludedFromCoverage

/**
 * Wraps the Chaquopy call into football.android_report.run_report() (see
 * backend/football/android_report.py). Chaquopy makes a Kotlin
 * `fun interface` (a JVM single-abstract-method type) directly callable
 * from Python as `on_progress(message)`/`on_source_progress(json)` --
 * confirmed against Chaquopy's own docs (chaquo.com/chaquopy/doc/current/
 * python.html: "If a Java object implements a functional interface, then
 * it can be called like a function using () syntax... any interface with
 * a single abstract method"), not assumed.
 *
 * Blocking -- must be called from a background thread (e.g.
 * Dispatchers.IO), same as android_report.run_report()'s own contract:
 * it wraps asyncio.run() internally and has no concept of suspending.
 * Both callbacks below then also fire on that same calling thread, not
 * the main thread -- ReportRepository is responsible for getting back
 * onto the caller's dispatcher before touching UI state.
 */
object PythonBridge {
    fun interface ProgressListener {
        fun onMessage(message: String)
    }

    fun interface SourceProgressListener {
        fun onSourceStatus(statusJson: String)
    }

    fun interface FailureListener {
        fun onFailure(failureJson: String)
    }

    @ExcludedFromCoverage
    fun runReport(
        teamName: String,
        onProgress: ProgressListener,
        onSourceProgress: SourceProgressListener,
        onFailure: FailureListener,
    ): String {
        val module = Python.getInstance().getModule("football.android_report")
        val pyResult = module.callAttr("run_report", teamName, onProgress, onSourceProgress, onFailure)
        return pyResult.toString()
    }
}
