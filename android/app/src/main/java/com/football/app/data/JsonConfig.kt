package com.football.app.data

import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNamingStrategy

/**
 * Shared Json instance for every model in data/model/.
 *
 * report.py's build_report_json() only camelCases its 10 top-level keys
 * by hand ("team", "generatedAt", "sources", "match", "venueDetails",
 * "form", "opponentForm", "teamProfile", "opponentProfile", "insights")
 * -- verified directly against report.py's source, not assumed. Every
 * field nested inside those (asdict() on a Python dataclass) stays
 * snake_case, matching the Python attribute name exactly, all the way
 * down. SnakeCase naming strategy handles every nested model
 * automatically; only the top-level ReportJson wrapper needs explicit
 * @SerialName overrides where the real key is camelCase instead (see
 * ReportJson.kt).
 */
@OptIn(ExperimentalSerializationApi::class)
val AppJson =
    Json {
        ignoreUnknownKeys = true // a new backend field shouldn't crash an older app build
        namingStrategy = JsonNamingStrategy.SnakeCase
        explicitNulls = false // the backend omits some optional keys entirely, not just nulls them
        coerceInputValues = true
    }

/**
 * Same config as AppJson, minus namingStrategy. kotlinx.serialization
 * applies namingStrategy's transform even to elements carrying an
 * explicit @SerialName (confirmed via a failing unit test, not assumed
 * from docs -- see ReportJsonTest: a property named "generatedAt" with
 * @SerialName("generatedAt") was still looked up in the JSON as
 * "generated_at" and reported "unknown key" / "missing field"). ReportJson
 * is the one type that fully hand-annotates every field with its real
 * (camelCase) backend key, so it must be decoded without the strategy
 * fighting those annotations. Every other model in data/model/ relies on
 * the strategy's automatic snake_case conversion and must keep using
 * AppJson, not this.
 */
@OptIn(ExperimentalSerializationApi::class)
val AppJsonTopLevel =
    Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }
