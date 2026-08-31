package com.football.app.data.model

import kotlinx.serialization.Serializable

/**
 * Mirrors orchestrate.SourceStatus exactly (source, fixtures_scraped,
 * matches_error, details_error, profile_error) -- one JSON object per
 * on_source_progress call from android_report.run_report(). Backs the
 * per-source loading checklist (frontend/DESIGN.md's Premium direction
 * section) -- decoded fresh per callback via AppJson, not accumulated
 * field-by-field, since each call already carries one source's complete
 * status.
 */
@Serializable
data class SourceStatus(
    val source: String,
    val fixturesScraped: Int = 0,
    val matchesError: String? = null,
    val detailsError: String? = null,
    val profileError: String? = null,
) {
    val succeeded: Boolean
        get() = matchesError == null && detailsError == null && profileError == null
}
