package com.football.app.components

import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class PillFlowTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders every child passed to it`() {
        composeTestRule.setContent {
            PillFlow {
                Text("Saliba")
                Text("Timber")
                Text("Rice")
            }
        }
        composeTestRule.onNodeWithText("Saliba").assertExists()
        composeTestRule.onNodeWithText("Timber").assertExists()
        composeTestRule.onNodeWithText("Rice").assertExists()
    }
}
