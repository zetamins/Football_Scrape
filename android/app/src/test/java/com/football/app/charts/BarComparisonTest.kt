package com.football.app.charts

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class BarComparisonTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders label and both value texts`() {
        composeTestRule.setContent {
            BarComparison(
                label = "xG for",
                homeValue = 1.8f,
                awayValue = 1.2f,
                homeColor = Color.Blue,
                awayColor = Color.Red,
                homeText = "Arsenal 1.8",
                awayText = "Chelsea 1.2",
            )
        }
        composeTestRule.onNodeWithText("xG for").assertExists()
        composeTestRule.onNodeWithText("Arsenal 1.8").assertExists()
        composeTestRule.onNodeWithText("Chelsea 1.2").assertExists()
    }

    @Test
    fun `renders correctly when both values are zero`() {
        // BarComparison guards against a 0/0 division (maxValue coerced
        // to a nonzero floor) -- confirms that doesn't crash the render.
        composeTestRule.setContent {
            BarComparison(
                label = "Penalties",
                homeValue = 0f,
                awayValue = 0f,
                homeColor = Color.Blue,
                awayColor = Color.Red,
                homeText = "Arsenal 0",
                awayText = "Chelsea 0",
            )
        }
        composeTestRule.onNodeWithText("Arsenal 0").assertExists()
        composeTestRule.onNodeWithText("Chelsea 0").assertExists()
    }
}
