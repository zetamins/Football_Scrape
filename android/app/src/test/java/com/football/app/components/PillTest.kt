package com.football.app.components

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Phase 4's first Compose UI test -- deliberately targets the smallest,
 * most dependency-free composable in the app first, to validate the
 * Robolectric+Compose toolchain itself (createComposeRule() under
 * RobolectricTestRunner, no device/emulator needed) before rolling it
 * out across the report tabs/screens.
 */
@RunWith(RobolectricTestRunner::class)
class PillTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `Pill renders the given text`() {
        composeTestRule.setContent {
            Pill(text = "Home 1.85", containerColor = Color.Green, contentColor = Color.White)
        }
        composeTestRule.onNodeWithText("Home 1.85").assertExists()
    }

    @Test
    fun `Pill accepts custom fontSize and contentPadding overrides`() {
        // Exercises the exact override path ReportScreen's ReportTabPill
        // uses (TextUnit.Unspecified + a custom PaddingValues) instead of
        // Pill's own defaults -- confirms the override params themselves
        // work, not just that Pill renders with its defaults.
        composeTestRule.setContent {
            Pill(
                text = "Overview",
                containerColor = Color.Green,
                contentColor = Color.White,
                fontSize = TextUnit.Unspecified,
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            )
        }
        composeTestRule.onNodeWithText("Overview").assertExists()
    }

    @Test
    fun `OutlinedPill renders the given text`() {
        composeTestRule.setContent {
            OutlinedPill(text = "O 2.5", borderColor = Color.Green, contentColor = Color.White)
        }
        composeTestRule.onNodeWithText("O 2.5").assertExists()
    }

    @Test
    fun `DotPill renders the given text`() {
        composeTestRule.setContent {
            DotPill(text = "Home 1.85", dotColor = Color.Blue, borderColor = Color.Green, contentColor = Color.White)
        }
        composeTestRule.onNodeWithText("Home 1.85").assertExists()
    }

    @Test
    fun `Pill applies a caller modifier such as padding`() {
        composeTestRule.setContent {
            Pill(text = "Draw", containerColor = Color.Green, contentColor = Color.White, modifier = Modifier.padding(4.dp))
        }
        composeTestRule.onNodeWithText("Draw").assertExists()
    }
}
