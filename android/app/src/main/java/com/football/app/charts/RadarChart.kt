package com.football.app.charts

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.cos
import kotlin.math.sin

/** One axis of a RadarChart -- a metric compared between two series
 * (home/away), each on its own 0..maxValue scale (metrics with very
 * different natural ranges, e.g. xG vs. touches in box, still overlay
 * legibly since each axis normalizes independently, not against a
 * shared scale). */
data class RadarAxis(
    val label: String,
    val homeValue: Float,
    val awayValue: Float,
    val maxValue: Float,
)

/**
 * Overlaid two-series radar/pizza chart -- Performance and Profile tabs'
 * "attack profile" comparisons (frontend/DESIGN.md). Hand-rolled Canvas,
 * not Vico (it doesn't cover this chart form).
 */
@Composable
fun RadarChart(
    axes: List<RadarAxis>,
    homeColor: Color,
    awayColor: Color,
    modifier: Modifier = Modifier,
    diameter: Dp = 240.dp,
) {
    if (axes.size < 3) return // a radar shape needs at least a triangle
    val textMeasurer = rememberTextMeasurer()
    val labelStyle = MaterialTheme.typography.labelSmall
    val gridColor = Color.Gray.copy(alpha = 0.3f)

    Canvas(modifier = modifier.size(diameter)) {
        drawRadarChart(axes, homeColor, awayColor, textMeasurer, labelStyle, gridColor)
    }
}

/**
 * The actual radar-drawing logic, extracted from RadarChart's Canvas{}
 * block as a plain (non-@Composable) DrawScope extension -- Kover
 * doesn't credit statements inside an inline Canvas{} draw lambda as
 * executed under Robolectric, but a plain function invoked directly
 * via CanvasDrawScope().draw(...) measures correctly. See
 * RadarChartTest.kt.
 */
internal fun DrawScope.drawRadarChart(
    axes: List<RadarAxis>,
    homeColor: Color,
    awayColor: Color,
    textMeasurer: TextMeasurer,
    labelStyle: TextStyle,
    gridColor: Color,
) {
    val center = Offset(size.width / 2, size.height / 2)
    val radius = (minOf(size.width, size.height) / 2) * 0.72f
    val angleStep = (2 * Math.PI / axes.size).toFloat()

    fun angleFor(index: Int) = -(Math.PI / 2).toFloat() + index * angleStep

    // Grid rings (4 concentric polygons)
    for (ring in 1..4) {
        val ringRadius = radius * (ring / 4f)
        val path = Path()
        axes.indices.forEach { i ->
            val angle = angleFor(i)
            val point = Offset(center.x + ringRadius * cos(angle), center.y + ringRadius * sin(angle))
            if (i == 0) path.moveTo(point.x, point.y) else path.lineTo(point.x, point.y)
        }
        path.close()
        drawPath(path, color = gridColor, style = Stroke(1.dp.toPx()))
    }

    // Axis spokes + labels
    axes.forEachIndexed { i, axis ->
        val angle = angleFor(i)
        val spokeEnd = Offset(center.x + radius * cos(angle), center.y + radius * sin(angle))
        drawLine(gridColor, center, spokeEnd, strokeWidth = 1.dp.toPx())

        val labelRadius = radius + 24.dp.toPx()
        val labelPoint = Offset(center.x + labelRadius * cos(angle), center.y + labelRadius * sin(angle))
        val layout = textMeasurer.measure(axis.label, labelStyle)
        drawText(
            layout,
            topLeft = Offset(labelPoint.x - layout.size.width / 2, labelPoint.y - layout.size.height / 2),
        )
    }

    fun drawSeries(
        valueSelector: (RadarAxis) -> Float,
        color: Color,
    ) {
        val path = Path()
        axes.forEachIndexed { i, axis ->
            val angle = angleFor(i)
            val fraction = (valueSelector(axis) / axis.maxValue).coerceIn(0f, 1f)
            val point = Offset(center.x + radius * fraction * cos(angle), center.y + radius * fraction * sin(angle))
            if (i == 0) path.moveTo(point.x, point.y) else path.lineTo(point.x, point.y)
        }
        path.close()
        drawPath(path, color = color.copy(alpha = 0.2f))
        drawPath(path, color = color, style = Stroke(2.dp.toPx()))
    }
    drawSeries({ it.homeValue }, homeColor)
    drawSeries({ it.awayValue }, awayColor)
}
