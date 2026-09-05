package com.football.app.charts

import com.football.app.data.model.LineupPlayer
import org.junit.Assert.assertEquals
import org.junit.Test

class PitchDiagramTest {
    private fun player(name: String, position: String) = LineupPlayer(name = name, position = position)

    private fun eleven(): List<LineupPlayer> = listOf(
        player("GK", "G"),
        player("D1", "D"), player("D2", "D"), player("D3", "D"), player("D4", "D"),
        player("M1", "M"), player("M2", "M"), player("M3", "M"), player("M4", "M"), player("M5", "M"),
        player("F1", "F"),
    )

    @Test
    fun `4-2-3-1 splits the 5 midfielders into a 2-row and a 3-row, in list order`() {
        val rows = buildRows("4-2-3-1", eleven())

        assertEquals(listOf(1, 4, 2, 3, 1), rows.map { it.size })
        assertEquals(listOf("M1", "M2"), rows[2].map { it.name })
        assertEquals(listOf("M3", "M4", "M5"), rows[3].map { it.name })
    }

    @Test
    fun `4-4-2 keeps midfield as a single row (only one middle number)`() {
        val players = listOf(
            player("GK", "G"),
            player("D1", "D"), player("D2", "D"), player("D3", "D"), player("D4", "D"),
            player("M1", "M"), player("M2", "M"), player("M3", "M"), player("M4", "M"),
            player("F1", "F"), player("F2", "F"),
        )
        val rows = buildRows("4-4-2", players)

        assertEquals(listOf(1, 4, 4, 2), rows.map { it.size })
    }

    @Test
    fun `3-5-2 handles a back three and a five-man midfield`() {
        val players = listOf(
            player("GK", "G"),
            player("D1", "D"), player("D2", "D"), player("D3", "D"),
            player("M1", "M"), player("M2", "M"), player("M3", "M"), player("M4", "M"), player("M5", "M"),
            player("F1", "F"), player("F2", "F"),
        )
        val rows = buildRows("3-5-2", players)

        assertEquals(listOf(1, 3, 5, 2), rows.map { it.size })
    }

    @Test
    fun `missing or malformed formation string falls back to plain G-D-M-F buckets`() {
        assertEquals(listOf(1, 4, 5, 1), buildRows(null, eleven()).map { it.size })
        assertEquals(listOf(1, 4, 5, 1), buildRows("unknown", eleven()).map { it.size })
        assertEquals(listOf(1, 4, 5, 1), buildRows("4", eleven()).map { it.size })
    }

    @Test
    fun `no goalkeeper in the list omits the GK row entirely rather than an empty row`() {
        val rows = buildRows("4-4-2", eleven().drop(1))
        assertEquals(3, rows.size)
        assertEquals(4, rows[0].size)
    }

    @Test
    fun `empty player list produces no rows`() {
        assertEquals(emptyList<List<LineupPlayer>>(), buildRows("4-4-2", emptyList()))
    }

    @Test
    fun `a goalkeeper-only list produces no rows`() {
        // Distinct from the "empty player list" case above: `players`
        // itself is non-empty here, so `players.isEmpty()` is false --
        // it's the separate `defenders/midfielders/forwards all empty`
        // guard that returns emptyList(), never reached by any other
        // test (every other fixture has at least one outfield player).
        assertEquals(emptyList<List<LineupPlayer>>(), buildRows("4-4-2", listOf(player("GK", "G"))))
    }
}
