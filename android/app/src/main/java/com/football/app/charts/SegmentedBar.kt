package com.football.app.charts

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * One colored fraction of a SegmentedBar. `fraction` is that segment's
 * share of the total (segments are normalized by their own sum inside
 * SegmentedBar, so callers can pass raw percentages that sum to ~100,
 * not just values that sum to exactly 1f).
 */
data class Segment(val fraction: Float, val color: Color)

/**
 * Proportional segmented bar -- win/draw/away probability, head-to-head
 * record, over/under share, etc. (frontend/DESIGN.md). Rounded as one
 * overall pill shape (via Compose's own clip, not per-segment rounded-
 * rect math) with a small gap between adjacent segments -- matches
 * dataviz's mark spec (rounded data-ends, a surface gap between adjacent
 * fills).
 */
@Composable
fun SegmentedBar(
    segments: List<Segment>,
    modifier: Modifier = Modifier,
    height: Dp = 20.dp,
    gap: Dp = 2.dp,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .clip(RoundedCornerShape(height / 2)),
    ) {
        Canvas(modifier = Modifier.fillMaxWidth().height(height)) {
            val gapPx = gap.toPx()
            val total = segments.sumOf { it.fraction.toDouble() }.toFloat().coerceAtLeast(0.0001f)
            var x = 0f
            segments.forEachIndexed { index, segment ->
                val widthPx = (segment.fraction / total) * size.width
                val drawWidth = if (index == segments.lastIndex) widthPx else (widthPx - gapPx).coerceAtLeast(0f)
                drawRect(
                    color = segment.color,
                    topLeft = Offset(x, 0f),
                    size = Size(drawWidth, size.height),
                )
                x += widthPx
            }
        }
    }
}
