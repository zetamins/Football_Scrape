package com.football.app.components

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.football.app.runDrawScope
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** Logo is pure Canvas drawing with no semantic text/content -- the
 * composition tests below are smoke tests confirming it composes
 * without throwing at a couple of real call-site sizes. The actual
 * drawing logic (drawLogo(), extracted from Logo's Canvas{} block) is
 * exercised for real by `drawLogo runs without throwing` via
 * runDrawScope() -- see that function's own doc comment for why this
 * is necessary at all (Kover doesn't credit an inline Canvas{} draw
 * lambda's statements under Robolectric, even though the composable
 * itself renders correctly). */
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

    @Test
    fun `drawLogo runs without throwing`() {
        runDrawScope { drawLogo() }
    }
}
