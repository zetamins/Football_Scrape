package com.football.app.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * The top-level shape of report.build_report_json()'s output (confirmed
 * directly against report.py's source, not assumed). Every field here is
 * @SerialName-annotated explicitly rather than relying on
 * JsonConfig.kt's SnakeCase strategy -- this is the one place in the
 * whole model tree where the strategy's default conversion would be
 * WRONG (report.py hand-picks these 10 keys as camelCase; everything
 * nested inside them reverts to snake_case, which the strategy handles
 * correctly on its own -- see JsonConfig.kt).
 *
 * match/venueDetails/form/opponentForm/teamProfile/opponentProfile/
 * insights stay as raw JsonElement for now, not fully-typed data classes
 * -- each is a substantial nested shape (insights alone has 74 top-level
 * fields, mapped tab-by-tab in frontend/DESIGN.md) best typed
 * incrementally as each report tab actually gets built and verified
 * against real sample JSON, not translated blind in one pass. A tab's
 * own code decodes just the piece it needs via
 * AppJson.decodeFromJsonElement<SomeType>(report.insights!!).
 */
@Serializable
data class ReportJson(
    @SerialName("team") val team: String,
    @SerialName("generatedAt") val generatedAt: String,
    @SerialName("sources") val sources: List<SourceStatus> = emptyList(),
    @SerialName("match") val match: JsonElement? = null,
    @SerialName("venueDetails") val venueDetails: JsonElement? = null,
    @SerialName("form") val form: JsonElement? = null,
    @SerialName("opponentForm") val opponentForm: JsonElement? = null,
    @SerialName("teamProfile") val teamProfile: JsonElement? = null,
    @SerialName("opponentProfile") val opponentProfile: JsonElement? = null,
    @SerialName("insights") val insights: JsonElement? = null,
)
