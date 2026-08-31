package com.football.app.data.history

import kotlinx.serialization.Serializable

/**
 * Lightweight record for one saved search, listed in HistoryScreen.
 * The full report JSON lives in its own file (id.json) -- this is just
 * the index entry, so listing history never requires reading every
 * saved report's full payload.
 */
@Serializable
data class HistoryEntry(
    val id: String,
    val team: String,
    val opponent: String? = null,
    val generatedAt: String,
    val savedAtEpochMs: Long,
)
