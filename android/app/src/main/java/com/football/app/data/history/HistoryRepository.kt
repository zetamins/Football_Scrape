package com.football.app.data.history

import com.football.app.data.model.ReportJson
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.util.UUID

/**
 * Persists every completed search to app-private storage (historyDir,
 * normally Context.filesDir/history -- no runtime permission needed)
 * as one raw-JSON file per entry (id.json, byte-identical to what the
 * backend actually returned -- same string ReportRepository decoded,
 * not a re-serialization) plus a flat index.json for listing without
 * reading every saved report. Not backed by Room -- the only queries
 * this app needs are "list all, newest first" and "delete by id", which
 * a small JSON list handles without adding a new dependency.
 *
 * Synchronized, not because multiple threads call this concurrently
 * today, but because ReportViewModel and HistoryViewModel each run
 * their own IO-dispatched coroutine and both touch index.json --
 * cheap insurance against a future overlap corrupting the index.
 */
class HistoryRepository(
    private val historyDir: File,
) {
    private val indexFile = File(historyDir, "index.json")
    private val entrySerializer = ListSerializer(HistoryEntry.serializer())
    private val json = Json { ignoreUnknownKeys = true }

    @Synchronized
    @Suppress("SwallowedException", "TooGenericExceptionCaught")
    fun list(): List<HistoryEntry> {
        if (!indexFile.exists()) return emptyList()
        return try {
            json.decodeFromString(entrySerializer, indexFile.readText()).sortedByDescending { it.savedAtEpochMs }
        } catch (e: Exception) {
            // A corrupt index shouldn't take down the history screen --
            // treat it as empty rather than crashing.
            emptyList()
        }
    }

    @Synchronized
    fun save(
        report: ReportJson,
        rawJson: String,
    ): HistoryEntry {
        historyDir.mkdirs()
        val id = UUID.randomUUID().toString()
        val entry =
            HistoryEntry(
                id = id,
                team = report.team,
                opponent = opponentOf(report),
                generatedAt = report.generatedAt,
                savedAtEpochMs = System.currentTimeMillis(),
            )
        File(historyDir, "$id.json").writeText(rawJson)
        writeIndex(list() + entry)
        return entry
    }

    @Synchronized
    fun delete(id: String) {
        // A failed delete (already gone, or a permissions hiccup) isn't
        // fatal -- the index is rewritten regardless, and an orphaned
        // file doesn't break list()/load() since those only ever consult
        // index.json -- but it's still worth a log line rather than
        // silently discarding File.delete()'s result.
        val deleted = File(historyDir, "$id.json").delete()
        if (!deleted) android.util.Log.w("HistoryRepository", "Failed to delete history file for id=$id (may already be gone)")
        writeIndex(list().filterNot { it.id == id })
    }

    @Synchronized
    fun load(id: String): String? {
        val file = File(historyDir, "$id.json")
        return if (file.exists()) file.readText() else null
    }

    private fun writeIndex(entries: List<HistoryEntry>) {
        indexFile.writeText(json.encodeToString(entrySerializer, entries))
    }

    private fun opponentOf(report: ReportJson): String? {
        val match = report.match as? JsonObject ?: return null
        val home = match["home_team"]?.jsonPrimitive?.contentOrNull
        val away = match["away_team"]?.jsonPrimitive?.contentOrNull
        if (home == null || away == null) return null
        return if (home == report.team) away else home
    }
}
