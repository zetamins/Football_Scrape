package com.football.app.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.unit.dp

/**
 * Every tab's card, one shared implementation instead of 9 identical
 * private copies (ContextTab, DisciplineTab, FormTab, LineupsTab,
 * OverviewTab, PerformanceTab, ProfileTab, SquadTab, StandingsTab all
 * had the exact same private fun before this). A subtle dark-green
 * gradient fill (surface fading to surfaceVariant), not a flat surface
 * color -- deliberately quiet compared to PredictionHero's own bold
 * gradient (see that file's doc comment for why the hero stays visually
 * distinct as each screen's one headline element, not one card among
 * many with an identical treatment).
 */
@Composable
fun SectionCard(
    title: String,
    content: @Composable () -> Unit,
) {
    Column(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(vertical = 6.dp)
                .clip(RoundedCornerShape(18.dp))
                .background(
                    Brush.verticalGradient(
                        listOf(MaterialTheme.colorScheme.surface, MaterialTheme.colorScheme.surfaceVariant),
                    ),
                ).padding(16.dp),
    ) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(4.dp))
        content()
    }
}
