package com.football.app.charts

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.football.app.ui.theme.AppTheme

/**
 * A row of W/D/L pills -- the standard "form guide" pattern (Form tab,
 * frontend/DESIGN.md). Most recent result first.
 */
@Composable
fun FormGuideStrip(results: List<String>, modifier: Modifier = Modifier) {
    Row(modifier = modifier) {
        results.forEach { result ->
            val color = when (result) {
                "W" -> AppTheme.colors.statusGood
                "L" -> AppTheme.colors.statusCritical
                else -> AppTheme.colors.neutral
            }
            Box(
                modifier = Modifier
                    .size(24.dp)
                    .clip(CircleShape)
                    .background(color),
                contentAlignment = Alignment.Center,
            ) {
                Text(result, color = Color.White, fontSize = 11.sp, textAlign = TextAlign.Center)
            }
            androidx.compose.foundation.layout.Spacer(Modifier.size(4.dp))
        }
    }
}
