package com.football.app.components

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class InfoRowTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders both label and value`() {
        composeTestRule.setContent {
            InfoRow(label = "Kickoff", value = "2026-09-05 15:00 UTC")
        }
        composeTestRule.onNodeWithText("Kickoff").assertExists()
        composeTestRule.onNodeWithText("2026-09-05 15:00 UTC").assertExists()
    }

    @Test
    fun `renders with a custom value color`() {
        composeTestRule.setContent {
            InfoRow(label = "Elevated card risk", value = "Arsenal, Chelsea", valueColor = Color.Red)
        }
        composeTestRule.onNodeWithText("Arsenal, Chelsea").assertExists()
    }
}
