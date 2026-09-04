package com.football.app.charts

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class FormGuideStripTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders one pill per result`() {
        composeTestRule.setContent {
            FormGuideStrip(results = listOf("W", "W", "D", "L", "W"))
        }
        composeTestRule.onAllNodesWithText("W").assertCountEquals(3)
        composeTestRule.onNodeWithText("D").assertExists()
        composeTestRule.onNodeWithText("L").assertExists()
    }

    @Test
    fun `renders an unrecognized result string using the neutral color without crashing`() {
        composeTestRule.setContent {
            FormGuideStrip(results = listOf("?"))
        }
        composeTestRule.onNodeWithText("?").assertExists()
    }
}
