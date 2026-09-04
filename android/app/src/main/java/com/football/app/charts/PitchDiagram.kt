package com.football.app.charts

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.football.app.data.model.LineupPlayer
import com.football.app.ui.theme.StatNumberStyle

/**
 * Starting XI laid out on a pitch by formation, not a flat name list --
 * frontend/DESIGN.md's own Lineups tab comment scoped this out earlier
 * ("a real pitch layout... is a scoped-out visual upgrade, not a missing
 * requirement"); now built.
 *
 * Row assignment: LineupPlayer.position is only ever G/D/M/F (coarse --
 * confirmed against real backend JSON, not finer-grained like "CDM"),
 * but the formation string (e.g. "4-2-3-1") tells us how many midfield
 * *rows* there are and how many players in each. So: bucket players by
 * G/D/M/F first (their list order within a bucket is already the
 * backend's own order), then split the M bucket into consecutive chunks
 * sized by the formation's middle numbers. This reconstructs a
 * "4-2-3-1"-style double-pivot-plus-front-three shape correctly even
 * though no single field states it directly. Formations with only one
 * midfield number (e.g. "4-4-2") just get one row. Falls back to plain
 * G/D/M/F buckets (no sub-split) if the formation string is missing or
 * malformed.
 */
@Composable
fun PitchDiagram(
    formation: String?,
    players: List<LineupPlayer>,
    teamColor: Color,
) {
    val rows = remember(formation, players) { buildRows(formation, players) }
    if (rows.isEmpty()) return

    val textMeasurer = rememberTextMeasurer()
    val pitchGreenDark = Color(0xFF1E5E2E)
    val pitchGreenLight = Color(0xFF247A3A)
    val lineColor = Color.White.copy(alpha = 0.55f)

    // Built from MaterialTheme.typography here, in the @Composable
    // function body -- not inside the Canvas draw lambda below, which
    // isn't itself a @Composable context (same reason RadarChart.kt
    // reads its own labelStyle outside its Canvas block). Previously a
    // bare TextStyle(fontSize = ...) with no fontFamily at all, which
    // silently rendered in the system default font instead of the app's
    // Barlow -- the only text in the app that did. The shirt number
    // specifically also gets StatNumberStyle (tabular figures), being a
    // genuine stat-tile number per that style's own stated purpose.
    val shirtNumberStyle = StatNumberStyle.copy(color = Color.White, fontSize = 12.sp, textAlign = TextAlign.Center)
    val playerNameStyle = MaterialTheme.typography.bodySmall.copy(color = Color.White, fontSize = 9.sp, textAlign = TextAlign.Center)

    Canvas(modifier = Modifier.fillMaxWidth().aspectRatio(0.72f)) {
        drawPitchDiagram(rows, teamColor, textMeasurer, shirtNumberStyle, playerNameStyle, pitchGreenDark, pitchGreenLight, lineColor)
    }
}

/**
 * The actual pitch-drawing logic, extracted from PitchDiagram's
 * Canvas{} block as a plain (non-@Composable) DrawScope extension --
 * Kover doesn't credit statements inside an inline Canvas{} draw lambda
 * as executed under Robolectric, but a plain function invoked directly
 * via CanvasDrawScope().draw(...) measures correctly. See
 * PitchDiagramTest.kt.
 */
internal fun DrawScope.drawPitchDiagram(
    rows: List<List<LineupPlayer>>,
    teamColor: Color,
    textMeasurer: TextMeasurer,
    shirtNumberStyle: TextStyle,
    playerNameStyle: TextStyle,
    pitchGreenDark: Color,
    pitchGreenLight: Color,
    lineColor: Color,
) {
    val w = size.width
    val h = size.height

    // Alternating mown-stripe bands, subtle -- purely decorative,
    // matches the reference's textured-pitch look without a real
    // image asset.
    val stripeCount = 8
    for (i in 0 until stripeCount) {
        drawRect(
            color = if (i % 2 == 0) pitchGreenDark else pitchGreenLight,
            topLeft = Offset(0f, h * i / stripeCount),
            size = Size(w, h / stripeCount),
        )
    }

    val stroke = Stroke(width = 2.dp.toPx())
    drawRect(color = lineColor, topLeft = Offset.Zero, size = Size(w, h), style = stroke)
    drawLine(lineColor, Offset(0f, h / 2), Offset(w, h / 2), strokeWidth = stroke.width)
    drawCircle(lineColor, radius = w * 0.16f, center = Offset(w / 2, h / 2), style = stroke)

    // Penalty boxes, top (opponent end) and bottom (own end, GK's row).
    val boxW = w * 0.6f
    val boxH = h * 0.14f
    drawRect(lineColor, topLeft = Offset((w - boxW) / 2, 0f), size = Size(boxW, boxH), style = stroke)
    drawRect(lineColor, topLeft = Offset((w - boxW) / 2, h - boxH), size = Size(boxW, boxH), style = stroke)

    // Rows bottom (GK, own goal) to top (forwards, opponent goal) --
    // matches the reference's vertical pitch orientation.
    val rowCount = rows.size
    rows.forEachIndexed { rowIndex, rowPlayers ->
        val rowFromBottom = rowCount - 1 - rowIndex
        val yFraction = 0.10f + (rowFromBottom.toFloat() / (rowCount - 1).coerceAtLeast(1)) * 0.80f
        val y = h * yFraction
        val n = rowPlayers.size
        rowPlayers.forEachIndexed { i, player ->
            val xFraction = (i + 1f) / (n + 1f)
            val x = w * xFraction

            drawCircle(color = Color.Black.copy(alpha = 0.25f), radius = 16.dp.toPx(), center = Offset(x, y + 2.dp.toPx()))
            drawCircle(color = teamColor, radius = 16.dp.toPx(), center = Offset(x, y))
            drawCircle(color = Color.White, radius = 16.dp.toPx(), center = Offset(x, y), style = Stroke(width = 1.5.dp.toPx()))

            val shirt = player.shirtNumber?.toString() ?: "-"
            val numberLayout = textMeasurer.measure(shirt, style = shirtNumberStyle)
            drawText(numberLayout, topLeft = Offset(x - numberLayout.size.width / 2f, y - numberLayout.size.height / 2f))

            val shortName = player.name.substringAfterLast(' ').take(10)
            val nameLayout = textMeasurer.measure(shortName, style = playerNameStyle)
            drawText(nameLayout, topLeft = Offset(x - nameLayout.size.width / 2f, y + 18.dp.toPx()))
        }
    }
}

internal fun buildRows(
    formation: String?,
    players: List<LineupPlayer>,
): List<List<LineupPlayer>> {
    if (players.isEmpty()) return emptyList()
    val gk = players.filter { it.position == "G" }
    val defenders = players.filter { it.position == "D" }
    val midfielders = players.filter { it.position == "M" }
    val forwards = players.filter { it.position == "F" }
    if (defenders.isEmpty() && midfielders.isEmpty() && forwards.isEmpty()) return emptyList()

    val formationParts = formation?.split("-")?.mapNotNull { it.toIntOrNull() }?.takeIf { it.size >= 2 }

    val midfieldRows: List<List<LineupPlayer>> =
        if (formationParts != null && formationParts.size > 2) {
            val midCounts = formationParts.subList(1, formationParts.size - 1)
            var idx = 0
            midCounts
                .map { count ->
                    val chunk = midfielders.subList(idx.coerceAtMost(midfielders.size), (idx + count).coerceAtMost(midfielders.size))
                    idx += count
                    chunk
                }.filter { it.isNotEmpty() }
        } else {
            listOf(midfielders).filter { it.isNotEmpty() }
        }

    return buildList {
        if (gk.isNotEmpty()) add(gk)
        if (defenders.isNotEmpty()) add(defenders)
        addAll(midfieldRows)
        if (forwards.isNotEmpty()) add(forwards)
    }
}
