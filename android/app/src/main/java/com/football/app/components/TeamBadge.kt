package com.football.app.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * A colored circle with a team's initials -- stands in for a real crest
 * image (this app has no artwork source/rights to pull real club
 * badges), used wherever a team is named prominently (Report header,
 * History rows). `color` is always AppTheme.colors.homeSeries/awaySeries
 * at call sites, never a per-club color -- team identity in this app is
 * "which side" (home/away), the same categorical meaning the segmented
 * bars and pitch diagram already use, not a literal brand color.
 */
@Composable
fun TeamBadge(teamName: String, color: Color, size: Dp = 32.dp) {
    Box(
        modifier = Modifier
            .size(size)
            .clip(CircleShape)
            .background(color),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = initialsFor(teamName),
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = (size.value * 0.34f).sp,
        )
    }
}

/** Up to 2 letters: first letters of the first two words, or the first 2 letters of a single word. */
internal fun initialsFor(teamName: String): String {
    val words = teamName.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
    return when {
        words.isEmpty() -> "?"
        words.size == 1 -> words[0].take(2).uppercase()
        else -> (words[0].take(1) + words[1].take(1)).uppercase()
    }
}
