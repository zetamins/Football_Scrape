package com.football.app.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * DeepXI's mark -- Canvas-drawn, not an image asset, matching how every
 * other visual in this app is built (charts, pitch diagram, onboarding
 * background all draw directly rather than shipping bitmaps). An
 * abstract pitch-corner: a rounded-square badge in the brand gradient,
 * containing a corner-arc (the actual corner-kick quadrant line on a
 * real pitch) plus a goal-frame chevron -- reads as "football pitch",
 * not a generic ball icon, and doubles as an "X" reference to DeepXI's
 * own name where the two strokes cross.
 */
@Composable
fun Logo(size: Dp = 40.dp) {
    Canvas(modifier = Modifier.size(size)) {
        val w = this.size.width
        val h = this.size.height
        val corner = w * 0.28f

        drawRoundRect(
            brush =
                Brush.linearGradient(
                    colors = listOf(Color(0xFF1E8E3E), Color(0xFF8FD13F)),
                    start = Offset(0f, 0f),
                    end = Offset(w, h),
                ),
            cornerRadius =
                androidx.compose.ui.geometry
                    .CornerRadius(corner, corner),
        )

        val stroke = Stroke(width = w * 0.075f, cap = StrokeCap.Round)

        // Corner-arc: the quarter-circle corner-kick marking, anchored bottom-left.
        val arcInset = w * 0.16f
        val arcSize = w * 0.5f
        drawArc(
            color = Color.White,
            startAngle = 270f,
            sweepAngle = 90f,
            useCenter = false,
            topLeft = Offset(arcInset - arcSize, h - arcInset - arcSize),
            size =
                androidx.compose.ui.geometry
                    .Size(arcSize * 2, arcSize * 2),
            style = stroke,
        )

        // Goal-frame chevron: two strokes meeting near the top-right,
        // crossing the corner-arc's sweep -- the "X" read.
        val chevron =
            Path().apply {
                moveTo(w * 0.42f, h * 0.30f)
                lineTo(w * 0.74f, h * 0.30f)
                lineTo(w * 0.74f, h * 0.62f)
            }
        drawPath(chevron, color = Color.White, style = stroke)
    }
}
