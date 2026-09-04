package com.football.app.report

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class MatchupHeaderTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders both team names and the vs separator`() {
        composeTestRule.setContent {
            MatchupHeader(homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Arsenal").assertExists()
        composeTestRule.onNodeWithText("Chelsea").assertExists()
        composeTestRule.onNodeWithText("vs").assertExists()
    }
}
