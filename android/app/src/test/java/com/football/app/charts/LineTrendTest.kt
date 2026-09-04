package com.football.app.charts

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class LineTrendTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `composes with matching-length series without throwing`() {
        composeTestRule.setContent {
            LineTrend(forValues = listOf(1.2f, 1.8f, 0.9f), againstValues = listOf(0.8f, 1.1f, 1.4f))
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `renders nothing for an empty series rather than throwing`() {
        composeTestRule.setContent {
            LineTrend(forValues = emptyList(), againstValues = emptyList())
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `renders nothing when series lengths mismatch rather than throwing`() {
        composeTestRule.setContent {
            LineTrend(forValues = listOf(1.2f, 1.8f), againstValues = listOf(0.8f))
        }
        composeTestRule.onRoot().assertExists()
    }
}
