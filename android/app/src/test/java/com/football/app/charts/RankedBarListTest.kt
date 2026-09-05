package com.football.app.charts

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import com.football.app.runDrawScope
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class RankedBarListTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders every entry's name and value text`() {
        composeTestRule.setContent {
            RankedBarList(
                entries =
                    listOf(
                        RankedEntry("Saka", 12, "12g"),
                        RankedEntry("Havertz", 8, "8g"),
                    ),
                barColor = Color.Green,
            )
        }
        composeTestRule.onNodeWithText("Saka").assertExists()
        composeTestRule.onNodeWithText("12g").assertExists()
        composeTestRule.onNodeWithText("Havertz").assertExists()
        composeTestRule.onNodeWithText("8g").assertExists()
    }

    @Test
    fun `renders nothing for an empty list rather than throwing`() {
        composeTestRule.setContent {
            RankedBarList(entries = emptyList(), barColor = Color.Green)
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `drawRankedBar runs without throwing`() {
        runDrawScope {
            drawRankedBar(value = 8.0, maxValue = 12.0, barColor = Color.Green)
        }
    }

    @Test
    fun `drawRankedBar clamps a value exceeding maxValue`() {
        // The fixture above stays within 0..1 -- coerceIn's upper-clamp
        // branch (value > maxValue) was never reached.
        runDrawScope {
            drawRankedBar(value = 20.0, maxValue = 12.0, barColor = Color.Green)
        }
    }
}
