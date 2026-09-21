package com.football.app.data.model

import kotlinx.serialization.Serializable

/**
 * One link/API request that failed for good during a search (retries
 * exhausted, or a 403/429 block) -- mirrors football/fetch_log.py's
 * FetchFailure, one JSON object per PythonBridge.FailureListener call.
 * Backs the live "failed links" list on the loading screen.
 */
@Serializable
data class FetchFailure(
    val source: String,
    val url: String,
    val reason: String,
)
