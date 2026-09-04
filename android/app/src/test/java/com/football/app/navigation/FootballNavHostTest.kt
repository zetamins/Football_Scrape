package com.football.app.navigation

import android.content.Context
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import com.football.app.onboarding.OnboardingPrefs
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** Never navigates into a state that would click Search/Run queue --
 * same reasoning as SearchScreenTest (that path starts a real
 * foreground service requiring Chaquopy's native Python runtime,
 * unavailable in a plain JVM test). Onboarding <-> Search <-> History
 * navigation itself doesn't touch that and is covered here. */
@RunWith(RobolectricTestRunner::class)
class FootballNavHostTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `starts on Onboarding for a first launch`() {
        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Get started").assertExists()
    }

    @Test
    fun `starts on Search once onboarding has already been seen`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("DeepXI").assertExists()
    }

    @Test
    fun `get started navigates from Onboarding to Search and marks onboarding as seen`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Get started").performClick()
        composeTestRule.onNodeWithText("DeepXI").assertExists()
        assert(OnboardingPrefs(context).hasSeenOnboarding)
    }

    @Test
    fun `history icon on Search navigates to History`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        OnboardingPrefs(context).hasSeenOnboarding = true

        composeTestRule.setContent {
            FootballNavHost()
        }
        composeTestRule.onNodeWithText("Team name").assertExists()

        composeTestRule.onNodeWithContentDescription("History").performClick()
        composeTestRule.onNodeWithText("No searches yet.").assertExists()
    }
}
