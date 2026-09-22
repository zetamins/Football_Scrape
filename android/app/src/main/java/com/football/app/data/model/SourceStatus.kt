package com.football.app.data.model

import kotlinx.serialization.Serializable

/**
 * Mirrors orchestrate.SourceStatus exactly (source, fixtures_scraped,
 * matches_error, details_error, profile_error, skipped) -- one JSON
 * object per on_source_progress call from android_report.run_report().
 * Backs the per-source loading checklist (frontend/DESIGN.md's Premium
 * direction section) -- decoded fresh per callback via AppJson, not
 * accumulated field-by-field, since each call already carries one
 * source's complete status.
 */
@Serializable
data class SourceStatus(
    val source: String,
    val fixturesScraped: Int = 0,
    val matchesError: String? = null,
    val detailsError: String? = null,
    val profileError: String? = null,
    // True when this source was never queried because Sofascore (the
    // base source) already had everything a fallback source could have
    // contributed -- not a failure, so it does not affect `succeeded`.
    val skipped: Boolean = false,
) {
    val succeeded: Boolean
        get() = matchesError == null && detailsError == null && profileError == null
}
