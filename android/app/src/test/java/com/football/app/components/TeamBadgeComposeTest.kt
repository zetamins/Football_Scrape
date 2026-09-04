package com.football.app.components

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** Separate from TeamBadgeTest.kt (initialsFor's own pure-function tests,
 * no Robolectric needed) -- this exercises the actual @Composable render
 * path, which initialsFor's tests alone don't cover. */
@RunWith(RobolectricTestRunner::class)
class TeamBadgeComposeTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders the team's initials`() {
        composeTestRule.setContent {
            TeamBadge(teamName = "Arsenal", color = Color.Red)
        }
        composeTestRule.onNodeWithText("AR").assertExists()
    }

    @Test
    fun `renders at a custom size`() {
        composeTestRule.setContent {
            TeamBadge(teamName = "Chelsea", color = Color.Blue, size = TeamBadge.SizeLarge)
        }
        composeTestRule.onNodeWithText("CH").assertExists()
    }
}
