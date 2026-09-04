package com.football.app.components

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** Logo is pure Canvas drawing with no semantic text/content -- these are
 * smoke tests confirming it composes (and draws) without throwing at a
 * couple of real call-site sizes, not content assertions (there's no
 * text/semantics for a Canvas draw to assert against). */
@RunWith(RobolectricTestRunner::class)
class LogoTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `composes at the default size without throwing`() {
        composeTestRule.setContent {
            Logo()
        }
        composeTestRule.onRoot().assertExists()
    }

    @Test
    fun `composes at a custom size without throwing`() {
        composeTestRule.setContent {
            Logo(size = 96.dp)
        }
        composeTestRule.onRoot().assertExists()
    }
}
