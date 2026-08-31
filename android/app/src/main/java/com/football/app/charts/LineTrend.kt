package com.football.app.charts

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModelProducer
import com.patrykandpatrick.vico.core.cartesian.data.lineSeries

/**
 * xG-per-match trend (Form tab, frontend/DESIGN.md) -- the one genuine
 * line-chart need in the report, using Vico (verified against Vico's
 * own docs before writing this, not guessed -- see charts/BarComparison.kt's
 * comment for why every other chart in the app is hand-rolled instead).
 * Two series (for/against), most recent match last.
 */
@Composable
fun LineTrend(forValues: List<Float>, againstValues: List<Float>, modifier: Modifier = Modifier) {
    if (forValues.isEmpty() || forValues.size != againstValues.size) return
    val modelProducer = remember { CartesianChartModelProducer() }

    LaunchedEffect(forValues, againstValues) {
        modelProducer.runTransaction {
            lineSeries {
                series(forValues)
                series(againstValues)
            }
        }
    }

    val chart = rememberCartesianChart(
        rememberLineCartesianLayer(),
        startAxis = VerticalAxis.rememberStart(),
        bottomAxis = HorizontalAxis.rememberBottom(),
    )

    CartesianChartHost(
        chart = chart,
        modelProducer = modelProducer,
        modifier = modifier.fillMaxWidth().height(160.dp),
    )
}
