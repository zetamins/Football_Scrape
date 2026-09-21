package com.football.app.data

import com.chaquo.python.PyException
import com.football.app.report.SearchState
import kotlinx.serialization.SerializationException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ReportRepositoryTest {
    private fun loadSampleReportJson(): String =
        checkNotNull(javaClass.classLoader?.getResourceAsStream("sample_full_report.json")) {
            "sample_full_report.json missing from test resources"
        }.bufferedReader().readText()

    @Test
    fun `emits an initial Loading state before the blocking call runs`() {
        val states = mutableListOf<SearchState>()
        val repository = ReportRepository(runReport = { _, _, _, _ -> loadSampleReportJson() })

        repository.search("Arsenal") { states.add(it) }

        val first = states.first()
        assertTrue(first is SearchState.Loading)
        assertEquals("Searching for \"Arsenal\"...", (first as SearchState.Loading).message)
    }

    @Test
    fun `emits Success with the decoded report and the exact raw json on completion`() {
        val states = mutableListOf<SearchState>()
        val sample = loadSampleReportJson()
        val repository = ReportRepository(runReport = { _, _, _, _ -> sample })

        repository.search("Brentford") { states.add(it) }

        val last = states.last()
        assertTrue(last is SearchState.Success)
        last as SearchState.Success
        assertEquals("Brentford", last.report.team)
        assertEquals(sample, last.rawJson)
    }

    @Test
    fun `progress listener callback emits a Loading state carrying the message`() {
        val states = mutableListOf<SearchState>()
        val repository =
            ReportRepository(runReport = { _, onProgress, _, _ ->
                onProgress.onMessage("Scraping sofascore...")
                loadSampleReportJson()
            })

        repository.search("Arsenal") { states.add(it) }

        val progressState = states[1]
        assertTrue(progressState is SearchState.Loading)
        assertEquals("Scraping sofascore...", (progressState as SearchState.Loading).message)
    }

    @Test
    fun `source progress listener decodes SourceStatus and accumulates across calls`() {
        val states = mutableListOf<SearchState>()
        val repository =
            ReportRepository(runReport = { _, _, onSourceProgress, _ ->
                onSourceProgress.onSourceStatus("""{"source":"sofascore","fixtures_scraped":5}""")
                onSourceProgress.onSourceStatus("""{"source":"fotmob","matches_error":"blocked"}""")
                loadSampleReportJson()
            })

        repository.search("Arsenal") { states.add(it) }

        val afterSecond = states[2] as SearchState.Loading
        assertEquals(2, afterSecond.sources.size)
        assertEquals("sofascore", afterSecond.sources[0].source)
        assertEquals(5, afterSecond.sources[0].fixturesScraped)
        assertTrue(afterSecond.sources[0].succeeded)
        assertEquals("fotmob", afterSecond.sources[1].source)
        assertEquals("blocked", afterSecond.sources[1].matchesError)
        assertTrue(!afterSecond.sources[1].succeeded)
    }

    @Test
    fun `PyException from the bridge becomes a SearchState Error with its message`() {
        val states = mutableListOf<SearchState>()
        val repository = ReportRepository(runReport = { _, _, _, _ -> throw PyException("Could not find a team matching \"Xyz\"") })

        repository.search("Xyz") { states.add(it) }

        val last = states.last()
        assertTrue(last is SearchState.Error)
        assertEquals("Could not find a team matching \"Xyz\"", (last as SearchState.Error).message)
    }

    @Test
    fun `PyException with no message falls back to a generic Search failed message`() {
        val states = mutableListOf<SearchState>()
        val repository = ReportRepository(runReport = { _, _, _, _ -> throw PyException() })

        repository.search("Xyz") { states.add(it) }

        val last = states.last() as SearchState.Error
        assertEquals("Search failed", last.message)
    }

    @Test
    fun `malformed json becomes a SearchState Error mentioning it could not be read`() {
        val states = mutableListOf<SearchState>()
        val repository = ReportRepository(runReport = { _, _, _, _ -> "not valid json at all" })

        repository.search("Arsenal") { states.add(it) }

        val last = states.last()
        assertTrue(last is SearchState.Error)
        assertTrue((last as SearchState.Error).message.startsWith("Could not read the report:"))
    }

    @Test
    fun `failure listener decodes FetchFailure and accumulates it onto every later Loading state`() {
        val states = mutableListOf<SearchState>()
        val repository =
            ReportRepository(runReport = { _, onProgress, _, onFailure ->
                onFailure.onFailure("""{"source":"fotmob","url":"https://api.fotmob.com/matches","reason":"HTTP 403"}""")
                onFailure.onFailure("""{"source":"sofascore","url":"https://www.sofascore.com/api/v1/team/1","reason":"timed out"}""")
                onProgress.onMessage("Scraping goal...")
                loadSampleReportJson()
            })

        repository.search("Arsenal") { states.add(it) }

        val afterFirst = states[1] as SearchState.Loading
        assertEquals(1, afterFirst.failures.size)
        assertEquals("fotmob", afterFirst.failures[0].source)
        assertEquals("HTTP 403", afterFirst.failures[0].reason)

        val afterMessage = states[3] as SearchState.Loading
        assertEquals("Scraping goal...", afterMessage.message)
        assertEquals(listOf("fotmob", "sofascore"), afterMessage.failures.map { it.source })
    }

    @Test
    fun `Loading has no failures until one is reported`() {
        val states = mutableListOf<SearchState>()
        val repository = ReportRepository(runReport = { _, onProgress, _, _ ->
            onProgress.onMessage("Working")
            loadSampleReportJson()
        })

        repository.search("Arsenal") { states.add(it) }

        assertTrue((states[0] as SearchState.Loading).failures.isEmpty())
        assertTrue((states[1] as SearchState.Loading).failures.isEmpty())
    }

    @Test
    fun `a malformed failure payload surfaces as a search error rather than crashing`() {
        val states = mutableListOf<SearchState>()
        val repository = ReportRepository(runReport = { _, _, _, onFailure ->
            onFailure.onFailure("not json")
            loadSampleReportJson()
        })

        repository.search("Arsenal") { states.add(it) }

        assertTrue(states.last() is SearchState.Error)
    }

    @Test
    fun `default constructor wires the real PythonBridge runReport without throwing at construction time`() {
        // Just confirms the default-argument reference (PythonBridge::runReport)
        // resolves and the class constructs -- actually invoking search()
        // with no fake would require a real Chaquopy Python runtime, out
        // of scope for a plain JVM unit test.
        ReportRepository()
    }
}
