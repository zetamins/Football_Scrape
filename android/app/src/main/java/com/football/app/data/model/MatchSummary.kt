package com.football.app.data.model

import kotlinx.serialization.Serializable

/**
 * Minimal, growing subset of `match` -- just the fields needed across
 * multiple screens/tabs before `match` gets a full typed model (the
 * Overview tab's own work, not yet done -- see frontend/DESIGN.md).
 * Every other match field stays reachable via ReportJson.match's raw
 * JsonElement until then.
 */
@Serializable
data class MatchSummary(
    val homeTeam: String,
    val awayTeam: String,
)
