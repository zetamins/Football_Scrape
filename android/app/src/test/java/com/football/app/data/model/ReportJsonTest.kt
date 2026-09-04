package com.football.app.data.model

import com.football.app.data.AppJsonTopLevel
import org.junit.Assert.assertEquals
import org.junit.Test

class ReportJsonTest {
    // Regression test for a real on-device bug: kotlinx.serialization's
    // namingStrategy transformed property names even where an explicit
    // @SerialName was present (e.g. "generatedAt" was looked up in the
    // JSON as "generated_at"), so AppJson (which sets namingStrategy)
    // failed to decode ReportJson with "unknown key" / "missing field"
    // even though the real backend JSON had "generatedAt" right there.
    // Fixed by decoding ReportJson with AppJsonTopLevel, which has no
    // namingStrategy -- every ReportJson field is already explicitly
    // @SerialName-annotated with its real backend key, so it doesn't
    // need the strategy's automatic conversion the way nested models do.
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    @Test
    fun `real full report decodes with AppJsonTopLevel`() {
        val decoded = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), loadSample())
        assertEquals("Brentford", decoded.team)
        assertEquals("2026-08-31T02:21:23.778Z", decoded.generatedAt)
    }

    // sources defaults to emptyList() -- every real fixture in this suite
    // includes it, so that default was previously never exercised.
    @Test
    fun `sources defaults to an empty list when the field is absent`() {
        val json = """{"team": "Brentford", "generatedAt": "2026-08-31T02:21:23.778Z"}"""
        val decoded = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), json)
        assertEquals(emptyList<SourceStatus>(), decoded.sources)
    }
}
