package com.football.app.charts

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class SegmentedBarTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `SegmentedBar composes without throwing`() {
        // Pure Canvas draw, no semantic text -- a smoke test is all
        // there is to assert against directly.
        composeTestRule.setContent {
            SegmentedBar(segments = listOf(Segment(0.45f, Color.Blue), Segment(0.25f, Color.Gray), Segment(0.3f, Color.Red)))
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `SegmentedBar with a zero total composes without throwing`() {
        // total.coerceAtLeast(0.0001f) guard -- confirms an all-zero
        // segment list doesn't divide by zero and crash.
        composeTestRule.setContent {
            SegmentedBar(segments = listOf(Segment(0f, Color.Blue), Segment(0f, Color.Red)))
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `ThreeWaySegmentedBar renders all three label texts`() {
        composeTestRule.setContent {
            ThreeWaySegmentedBar(
                homeFraction = 45f,
                drawFraction = 25f,
                awayFraction = 30f,
                homeColor = Color.Blue,
                drawColor = Color.Gray,
                awayColor = Color.Red,
                homeText = "Arsenal 45.0%",
                drawText = "Draw 25.0%",
                awayText = "Chelsea 30.0%",
            )
        }
        composeTestRule.onNodeWithText("Arsenal 45.0%").assertExists()
        composeTestRule.onNodeWithText("Draw 25.0%").assertExists()
        composeTestRule.onNodeWithText("Chelsea 30.0%").assertExists()
    }
}
