package com.football.app.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Every Pill/OutlinedPill/DotPill call site's shared font size -- a
 * deliberate custom in-between size (M3's own labelMedium/labelLarge are
 * 12sp/14sp), pulled into one named value instead of the literal `13.sp`
 * being repeated at each of their 3 definitions. */
private val PillFontSize = 13.sp
private val PillContentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)

/**
 * Small rounded chip -- odds values, source/availability status, and the
 * report tab bar all use this instead of plain text, matching the
 * reference's pill-heavy visual language (every discrete value sits in
 * its own rounded container, not just inline text).
 *
 * [fontSize]/[contentPadding] default to every other Pill call site's
 * sizing, overridable for a caller with different sizing needs (e.g.
 * ReportScreen's tab bar, which needs the tab-bar's own ambient font
 * size and roomier padding) -- lets that caller reuse this shape/
 * background/clip logic instead of a hand-rolled duplicate, without
 * changing its own already-tuned visual output.
 */
@Composable
fun Pill(
    text: String,
    containerColor: Color,
    contentColor: Color,
    modifier: Modifier = Modifier,
    fontWeight: FontWeight = FontWeight.SemiBold,
    fontSize: TextUnit = PillFontSize,
    contentPadding: PaddingValues = PillContentPadding,
) {
    Text(
        text = text,
        color = contentColor,
        fontWeight = fontWeight,
        fontSize = fontSize,
        modifier =
            modifier
                .background(containerColor, RoundedCornerShape(50))
                .padding(contentPadding),
    )
}

/** Same shape as Pill, but a bordered/tinted-surface fill rather than a solid color -- for values that don't carry their own semantic color (plain odds numbers, neutral tags). */
@Composable
fun OutlinedPill(
    text: String,
    borderColor: Color,
    contentColor: Color,
    modifier: Modifier = Modifier,
) {
    Text(
        text = text,
        color = contentColor,
        fontWeight = FontWeight.Medium,
        fontSize = PillFontSize,
        modifier =
            modifier
                .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(50))
                .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(50))
                .padding(PillContentPadding),
    )
}

/**
 * OutlinedPill with a small leading color dot -- the reference's
 * dot-prefixed odds chips. `dotColor` ties back to the same home/draw/
 * away colors the segmented bars and pitch diagram already use, so a
 * Home-odds pill and the Home slice of a prediction bar read as the
 * same "home" identity.
 */
@Composable
fun DotPill(
    text: String,
    dotColor: Color,
    borderColor: Color,
    contentColor: Color,
    modifier: Modifier = Modifier,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier =
            modifier
                .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(50))
                .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(50))
                .padding(PillContentPadding),
    ) {
        Box(modifier = Modifier.size(8.dp).background(dotColor, CircleShape))
        Text(
            text = text,
            color = contentColor,
            fontWeight = FontWeight.Medium,
            fontSize = PillFontSize,
            modifier = Modifier.padding(start = 6.dp),
        )
    }
}
