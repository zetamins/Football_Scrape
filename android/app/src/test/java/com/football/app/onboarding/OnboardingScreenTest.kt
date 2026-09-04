package com.football.app.onboarding

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class OnboardingScreenTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders the headline, subtext, and get-started button`() {
        composeTestRule.setContent {
            OnboardingScreen(onGetStarted = {})
        }
        composeTestRule.onNodeWithText("Every match,\nfully broken down.").assertExists()
        composeTestRule.onNodeWithText("Get started").assertExists()
    }

    @Test
    fun `get-started button invokes the callback`() {
        var clicked = false
        composeTestRule.setContent {
            OnboardingScreen(onGetStarted = { clicked = true })
        }
        composeTestRule.onNodeWithText("Get started").performClick()
        assert(clicked)
    }
}
