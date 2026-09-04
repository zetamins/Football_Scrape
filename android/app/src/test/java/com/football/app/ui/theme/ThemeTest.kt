package com.football.app.ui.theme

import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ThemeTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders content in light mode`() {
        composeTestRule.setContent {
            FootballTheme(darkTheme = false) {
                Text("Hello")
            }
        }
        composeTestRule.onNodeWithText("Hello").assertExists()
    }

    @Test
    fun `renders content in dark mode`() {
        composeTestRule.setContent {
            FootballTheme(darkTheme = true) {
                Text("Hello")
            }
        }
        composeTestRule.onNodeWithText("Hello").assertExists()
    }

    @Test
    fun `AppTheme colors resolves to the light palette under a light theme`() {
        var homeSeries: androidx.compose.ui.graphics.Color? = null
        composeTestRule.setContent {
            FootballTheme(darkTheme = false) {
                homeSeries = AppTheme.colors.homeSeries
            }
        }
        assert(homeSeries == LightAppColors.homeSeries)
    }

    @Test
    fun `AppTheme colors resolves to the dark palette under a dark theme`() {
        var homeSeries: androidx.compose.ui.graphics.Color? = null
        composeTestRule.setContent {
            FootballTheme(darkTheme = true) {
                homeSeries = AppTheme.colors.homeSeries
            }
        }
        assert(homeSeries == DarkAppColors.homeSeries)
    }
}
