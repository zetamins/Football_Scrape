package com.football.app.components

import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class SectionCardTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders the title and its content`() {
        composeTestRule.setContent {
            SectionCard(title = "Match") {
                Text("Kickoff 15:00")
            }
        }
        composeTestRule.onNodeWithText("Match").assertExists()
        composeTestRule.onNodeWithText("Kickoff 15:00").assertExists()
    }
}
