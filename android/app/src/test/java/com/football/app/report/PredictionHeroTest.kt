package com.football.app.report

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.football.app.data.AppJson
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class PredictionHeroTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun `renders one probability row per non-null model`() {
        val insightsJson =
            AppJson.parseToJsonElement(
                """
                {"prediction": {
                    "market_implied": {"home_win_pct": 45.0, "draw_pct": 27.0, "away_win_pct": 28.0},
                    "heuristic_blend": {"home_win_pct": 50.0, "draw_pct": 25.0, "away_win_pct": 25.0}
                }}
                """.trimIndent(),
            )
        composeTestRule.setContent {
            PredictionHero(insightsJson = insightsJson, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Prediction").assertExists()
        composeTestRule.onNodeWithText("Market").assertExists()
        composeTestRule.onNodeWithText("Elo model").assertExists()
        composeTestRule.onNodeWithText("xG model").assertDoesNotExist()
        composeTestRule.onNodeWithText("Arsenal 45.0%").assertExists()
    }

    @Test
    fun `renders nothing when insightsJson is null`() {
        composeTestRule.setContent {
            PredictionHero(insightsJson = null, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Prediction").assertDoesNotExist()
    }

    @Test
    fun `renders nothing when prediction is entirely absent`() {
        val insightsJson = AppJson.parseToJsonElement("""{"other_field": 1}""")
        composeTestRule.setContent {
            PredictionHero(insightsJson = insightsJson, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Prediction").assertDoesNotExist()
    }

    @Test
    fun `renders nothing when every prediction model is null`() {
        val insightsJson = AppJson.parseToJsonElement("""{"prediction": {}}""")
        composeTestRule.setContent {
            PredictionHero(insightsJson = insightsJson, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Prediction").assertDoesNotExist()
    }

    @Test
    fun `renders nothing when the prediction shape is malformed rather than crashing`() {
        val insightsJson = AppJson.parseToJsonElement("""{"prediction": "not an object"}""")
        composeTestRule.setContent {
            PredictionHero(insightsJson = insightsJson, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Prediction").assertDoesNotExist()
    }

    @Test
    fun `all three models render together`() {
        val insightsJson =
            AppJson.parseToJsonElement(
                """
                {"prediction": {
                    "market_implied": {"home_win_pct": 45.0, "draw_pct": 27.0, "away_win_pct": 28.0},
                    "heuristic_blend": {"home_win_pct": 50.0, "draw_pct": 25.0, "away_win_pct": 25.0},
                    "xg_model": {"home_win_pct": 48.0, "draw_pct": 24.0, "away_win_pct": 28.0}
                }}
                """.trimIndent(),
            )
        composeTestRule.setContent {
            PredictionHero(insightsJson = insightsJson, homeTeam = "Arsenal", awayTeam = "Chelsea")
        }
        composeTestRule.onNodeWithText("Market").assertExists()
        composeTestRule.onNodeWithText("Elo model").assertExists()
        composeTestRule.onNodeWithText("xG model").assertExists()
    }
}
