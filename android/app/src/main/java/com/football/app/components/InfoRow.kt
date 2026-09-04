package com.football.app.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * One label/value line -- the plain-text row shape most report fields
 * end up as (frontend/DESIGN.md's per-tab bullet lists are mostly this,
 * with charts reserved for actual numeric comparisons). `valueColor`
 * defaults to the theme's body text color; pass AppTheme.colors.status*
 * for a warn/critical-toned row (e.g. suspended players, elevated risk).
 */
@Composable
fun InfoRow(
    label: String,
    value: String,
    valueColor: Color = Color.Unspecified,
) {
    Column(modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = valueColor)
    }
}
