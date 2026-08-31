package com.football.app.report

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.football.app.charts.Segment
import com.football.app.charts.SegmentedBar
import com.football.app.data.AppJson
import com.football.app.data.model.Prediction
import com.football.app.data.model.WinProbabilities
import com.football.app.ui.theme.AppTheme
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/**
 * The number most users open the app to see -- rendered above the tab
 * row, not one tap deep inside a tab (frontend/DESIGN.md's Overview
 * section: "Prediction hero (not a tab)"). Renders nothing if
 * insights/insights.prediction is null or both its own fields are null
 * (a pre-kickoff-but-no-odds-found match, or no upcoming match at all)
 * -- matches the doc's resolved null-handling convention: a block with
 * no backing data emits nothing, not a placeholder.
 */
@Composable
fun PredictionHero(insightsJson: JsonElement?, homeTeam: String, awayTeam: String) {
    val prediction = remember(insightsJson) { decodePrediction(insightsJson) } ?: return
    if (prediction.marketImplied == null && prediction.heuristicBlend == null) return

    Card(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Prediction", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(12.dp))
            prediction.marketImplied?.let {
                ProbabilityRow(label = "Market", probs = it, homeTeam = homeTeam, awayTeam = awayTeam)
                Spacer(Modifier.height(8.dp))
            }
            prediction.heuristicBlend?.let {
                ProbabilityRow(label = "Model", probs = it, homeTeam = homeTeam, awayTeam = awayTeam)
            }
        }
    }
}

@Composable
private fun ProbabilityRow(label: String, probs: WinProbabilities, homeTeam: String, awayTeam: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(4.dp))
        SegmentedBar(
            segments = listOf(
                Segment(probs.homeWinPct.toFloat(), AppTheme.colors.homeSeries),
                Segment(probs.drawPct.toFloat(), AppTheme.colors.neutral),
                Segment(probs.awayWinPct.toFloat(), AppTheme.colors.awaySeries),
            ),
        )
        Spacer(Modifier.height(4.dp))
        Row(modifier = Modifier.fillMaxWidth()) {
            Text(
                "$homeTeam ${probs.homeWinPct.format1()}%",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
            )
            Text(
                "Draw ${probs.drawPct.format1()}%",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
            )
            Text(
                "$awayTeam ${probs.awayWinPct.format1()}%",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.End,
            )
        }
    }
}

private fun Double.format1(): String = "%.1f".format(this)

private fun decodePrediction(insightsJson: JsonElement?): Prediction? {
    if (insightsJson == null) return null
    val obj = insightsJson as? JsonObject ?: return null
    val predictionElement = obj["prediction"] ?: return null
    return try {
        AppJson.decodeFromJsonElement(Prediction.serializer(), predictionElement)
    } catch (e: SerializationException) {
        null
    }
}
