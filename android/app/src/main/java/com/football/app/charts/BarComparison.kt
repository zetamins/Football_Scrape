package com.football.app.charts

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Paired home/away horizontal bar comparison -- the most common chart
 * shape in the whole report (xG, shots, touches in box, cards, ... —
 * frontend/DESIGN.md). Hand-rolled Canvas rather than Vico: this mark
 * type (two independent proportional bars, not a shared-axis chart) is
 * simple enough to implement directly with full control, and it's used
 * at high volume across Performance/Discipline/Standings/Form/Squad --
 * getting one small, fully-understood primitive right once matters more
 * here than pulling in a charting library's exact API surface for it.
 * Vico is reserved for the one genuine line-chart need (Form tab's
 * xG-per-match trend).
 */
@Composable
fun BarComparison(
    label: String,
    homeValue: Float,
    awayValue: Float,
    homeColor: Color,
    awayColor: Color,
    homeText: String,
    awayText: String,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(4.dp))
        val maxValue = maxOf(homeValue, awayValue, 0.0001f)
        SingleBar(fraction = homeValue / maxValue, color = homeColor, valueText = homeText)
        Spacer(Modifier.height(2.dp))
        SingleBar(fraction = awayValue / maxValue, color = awayColor, valueText = awayText)
    }
}

@Composable
private fun SingleBar(fraction: Float, color: Color, valueText: String) {
    Column {
        androidx.compose.foundation.layout.Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(14.dp)
                .clip(RoundedCornerShape(4.dp)),
        ) {
            Canvas(modifier = Modifier.fillMaxWidth().height(14.dp)) {
                drawRect(
                    color = color.copy(alpha = 0.15f),
                    topLeft = Offset.Zero,
                    size = Size(size.width, size.height),
                )
                drawRect(
                    color = color,
                    topLeft = Offset.Zero,
                    size = Size(size.width * fraction.coerceIn(0f, 1f), size.height),
                )
            }
        }
        Text(valueText, style = MaterialTheme.typography.bodySmall)
    }
}
