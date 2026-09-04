package com.football.app.charts

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.football.app.data.model.LineupPlayer
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** Separate from PitchDiagramTest.kt (buildRows' own pure-function
 * tests, no Robolectric needed) -- this exercises the actual
 * @Composable Canvas render path, including the shirt-number/player-name
 * text drawn via textMeasurer.measure()+drawText() rather than a Text()
 * composable, so these are smoke tests (composes/draws without
 * throwing), not semantic-tree content assertions. */
@RunWith(RobolectricTestRunner::class)
class PitchDiagramComposeTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    private fun player(
        name: String,
        position: String,
        shirtNumber: Int? = null,
    ) = LineupPlayer(name = name, position = position, shirtNumber = shirtNumber)

    private fun eleven(): List<LineupPlayer> =
        listOf(
            player("Raya", "G", 1),
            player("White", "D", 4), player("Saliba", "D", 2), player("Gabriel", "D", 6), player("Timber", "D", 12),
            player("Rice", "M", 41), player("Odegaard", "M", 8),
            player("Saka", "F", 7), player("Havertz", "F", 29), player("Martinelli", "F", 11),
        )

    @Test
    fun `composes a full XI with a formation without throwing`() {
        composeTestRule.setContent {
            PitchDiagram(formation = "4-4-2", players = eleven(), teamColor = Color.Blue)
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `composes without a formation string (falls back to plain buckets)`() {
        composeTestRule.setContent {
            PitchDiagram(formation = null, players = eleven(), teamColor = Color.Blue)
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `composes with a player missing a shirt number (dash fallback)`() {
        composeTestRule.setContent {
            PitchDiagram(formation = "4-4-2", players = listOf(player("Sub", "M", shirtNumber = null)), teamColor = Color.Blue)
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `renders nothing for an empty player list rather than throwing`() {
        composeTestRule.setContent {
            PitchDiagram(formation = "4-4-2", players = emptyList(), teamColor = Color.Blue)
        }
        composeTestRule.onRoot().assertExists()
    }
}
