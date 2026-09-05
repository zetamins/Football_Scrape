package com.football.app.data.history

import com.football.app.data.AppJsonTopLevel
import com.football.app.data.model.ReportJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

/** Robolectric, not a plain JVM test -- delete()'s failure-to-delete
 * branch logs via android.util.Log, which throws "not mocked" outside
 * an Android test environment. */
@RunWith(RobolectricTestRunner::class)
class HistoryRepositoryTest {
    private fun loadSample(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    private fun newRepo(): HistoryRepository = HistoryRepository(File.createTempFile("history", "").apply { delete(); mkdirs() })

    @Test
    fun `save then list round-trips team, opponent, and generatedAt`() {
        val rawJson = loadSample()
        val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
        val repo = newRepo()

        val entry = repo.save(report, rawJson)

        assertEquals("Brentford", entry.team)
        assertEquals("Sunderland", entry.opponent)
        assertEquals("2026-08-31T02:21:23.778Z", entry.generatedAt)

        val listed = repo.list()
        assertEquals(1, listed.size)
        assertEquals(entry, listed.first())
    }

    @Test
    fun `save then load returns the exact original bytes`() {
        val rawJson = loadSample()
        val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
        val repo = newRepo()

        val entry = repo.save(report, rawJson)

        assertEquals(rawJson, repo.load(entry.id))
    }

    @Test
    fun `delete removes both the entry and its file`() {
        val rawJson = loadSample()
        val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
        val repo = newRepo()
        val entry = repo.save(report, rawJson)

        repo.delete(entry.id)

        assertTrue(repo.list().isEmpty())
        assertNull(repo.load(entry.id))
    }

    @Test
    fun `list on a fresh directory is empty, not an error`() {
        assertTrue(newRepo().list().isEmpty())
    }

    @Test
    fun `a corrupt index file is treated as empty rather than crashing`() {
        val dir = File.createTempFile("history", "").apply { delete(); mkdirs() }
        File(dir, "index.json").writeText("{not valid json[")
        val repo = HistoryRepository(dir)

        assertTrue(repo.list().isEmpty())
    }

    @Test
    fun `opponentOf resolves the away team when the searched team is the home side`() {
        // Every other test above uses the sample report, where the
        // searched team ("Brentford") is the home side -- the
        // `if (home == report.team) away else home` false branch (the
        // searched team being the AWAY side) was never taken.
        val rawJson = """{"team": "Sunderland", "generatedAt": "2026-08-31T02:21:23.778Z", "match": {"home_team": "Brentford", "away_team": "Sunderland"}}"""
        val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
        val repo = newRepo()

        val entry = repo.save(report, rawJson)

        assertEquals("Brentford", entry.opponent)
    }

    @Test
    fun `opponentOf returns null when the match object is missing home or away team`() {
        val rawJson = """{"team": "Brentford", "generatedAt": "2026-08-31T02:21:23.778Z", "match": {"home_team": "Brentford"}}"""
        val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
        val repo = newRepo()

        val entry = repo.save(report, rawJson)

        assertNull(entry.opponent)
    }

    @Test
    fun `load returns null for an id that was never saved`() {
        assertNull(newRepo().load("nonexistent-id"))
    }

    @Test
    fun `deleting an id with no backing file is a no-op, not a crash`() {
        newRepo().delete("nonexistent-id")
    }

    @Test
    fun `multiple saves are all listed, newest first`() {
        val rawJson = loadSample()
        val report = AppJsonTopLevel.decodeFromString(ReportJson.serializer(), rawJson)
        val repo = newRepo()

        val first = repo.save(report, rawJson)
        Thread.sleep(2)
        val second = repo.save(report, rawJson)

        val listed = repo.list()
        assertEquals(2, listed.size)
        assertEquals(second.id, listed.first().id)
        assertEquals(first.id, listed.last().id)
    }
}
