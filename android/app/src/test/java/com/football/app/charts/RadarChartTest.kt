package com.football.app.charts

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.createFontFamilyResolver
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.sp
import androidx.test.core.app.ApplicationProvider
import com.football.app.runDrawScope
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Axis labels are drawn directly via Canvas's drawText, not a Text()
 * composable -- they don't appear in the semantics tree, so the
 * composition tests below are smoke tests (composes without throwing)
 * rather than content assertions.
 *
 * The Canvas draw lambda's own internal statements were previously
 * assumed a genuine, permanent Kover/Robolectric tooling gap (neither
 * `@GraphicsMode(GraphicsMode.Mode.NATIVE)` nor `onRoot().captureToImage()`
 * closes it -- both confirmed dead ends, still true). That conclusion
 * was too broad: `drawRadarChart runs without throwing` below exercises
 * the extracted draw logic directly via `runDrawScope()`
 * (`CanvasDrawScope().draw(...)`, bypassing Compose's own rendering
 * pipeline -- which Robolectric can't run -- entirely), and Kover DOES
 * credit statements reached that way.
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

    @Test
    fun `drawRadarChart runs without throwing`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val textMeasurer = TextMeasurer(createFontFamilyResolver(context), Density(1f), LayoutDirection.Ltr)
        runDrawScope {
            drawRadarChart(
                axes =
                    listOf(
                        RadarAxis("xG", 1.8f, 1.2f, maxValue = 3f),
                        RadarAxis("Shots", 14f, 10f, maxValue = 20f),
                        RadarAxis("Big chances", 3f, 2f, maxValue = 8f),
                    ),
                homeColor = Color.Blue,
                awayColor = Color.Red,
                textMeasurer = textMeasurer,
                labelStyle = TextStyle(fontSize = 11.sp),
                gridColor = Color.Gray.copy(alpha = 0.3f),
            )
        }
    }
}
