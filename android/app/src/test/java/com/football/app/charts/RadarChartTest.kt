package com.football.app.charts

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Axis labels are drawn directly via Canvas's drawText, not a Text()
 * composable -- they don't appear in the semantics tree, so these are
 * smoke tests (composes without throwing) rather than content
 * assertions.
 *
 * The Canvas draw lambda's own internal statements (drawPath/drawLine/
 * drawText calls) stay 0% in Kover even with a passing test here --
 * confirmed live this is a genuine tooling gap, not a missing test:
 * neither `@GraphicsMode(GraphicsMode.Mode.NATIVE)` nor forcing an
 * actual draw pass via `onRoot().captureToImage()` closes it (the
 * latter times out outright under this Robolectric+Compose setup, a
 * real limitation, not just unexplored). Same accepted-gap category as
 * PythonBridge.kt/WebViewRenderer/SearchQueueService's service-lifecycle
 * code -- documented, not silently ignored.
 */
@RunWith(RobolectricTestRunner::class)
class RadarChartTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `composes with 3 or more axes without throwing`() {
        composeTestRule.setContent {
            RadarChart(
                axes =
                    listOf(
                        RadarAxis("xG", 1.8f, 1.2f, maxValue = 3f),
                        RadarAxis("Shots", 14f, 10f, maxValue = 20f),
                        RadarAxis("Big chances", 3f, 2f, maxValue = 8f),
                    ),
                homeColor = Color.Blue,
                awayColor = Color.Red,
            )
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `fewer than 3 axes renders nothing rather than throwing`() {
        // A radar shape needs at least a triangle -- axes.size < 3
        // returns early.
        composeTestRule.setContent {
            RadarChart(axes = listOf(RadarAxis("xG", 1.8f, 1.2f, maxValue = 3f)), homeColor = Color.Blue, awayColor = Color.Red)
        }
        composeTestRule.onRoot().assertExists()
    }
}
