package com.football.app.charts

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.football.app.ui.theme.StatNumberStyle

/** One ranked row: a name, a value to bar-encode, and the text already formatted for display (e.g. "9g", "6a"). */
data class RankedEntry(
    val name: String,
    val value: Number,
    val valueText: String,
)

/**
 * A ranked list where each row's bar length is proportional to its
 * value relative to the top entry -- top scorers/assists/tacklers, not
 * a comma-joined text line. Distinct from BarComparison (which pairs
 * exactly two values, home vs away): this is N rows of one team's own
 * players ranked against each other, so it needs its own layout.
 */
@Composable
fun RankedBarList(
    entries: List<RankedEntry>,
    barColor: Color,
    modifier: Modifier = Modifier,
) {
    if (entries.isEmpty()) return
    val maxValue = entries.maxOf { it.value.toDouble() }.coerceAtLeast(0.0001)
    Column(modifier = modifier.fillMaxWidth()) {
        entries.forEach { entry ->
            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                Text(
                    entry.name,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.width(96.dp),
                )
                Spacer(Modifier.width(8.dp))
                Canvas(
                    modifier =
                        Modifier
                            .weight(1f)
                            .height(12.dp)
                            .clip(RoundedCornerShape(3.dp)),
                ) {
                    drawRankedBar(entry.value.toDouble(), maxValue, barColor)
                }
                Spacer(Modifier.width(8.dp))
                Text(entry.valueText, style = MaterialTheme.typography.bodySmall.merge(StatNumberStyle))
            }
        }
    }
}

/**
 * The actual bar-drawing logic, extracted from RankedBarList's Canvas{}
 * block as a plain (non-@Composable) DrawScope extension -- Kover
 * doesn't credit statements inside an inline Canvas{} draw lambda as
 * executed under Robolectric, but a plain function invoked directly
 * via CanvasDrawScope().draw(...) measures correctly. See
 * RankedBarListTest.kt.
 */
internal fun DrawScope.drawRankedBar(
    value: Double,
    maxValue: Double,
    barColor: Color,
) {
    val fraction = (value / maxValue).toFloat().coerceIn(0f, 1f)
    drawRect(color = barColor.copy(alpha = 0.15f), topLeft = Offset.Zero, size = Size(size.width, size.height))
    drawRect(color = barColor, topLeft = Offset.Zero, size = Size(size.width * fraction, size.height))
}
