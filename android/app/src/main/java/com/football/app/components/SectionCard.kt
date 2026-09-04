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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * The app's one shared "card surface" treatment -- a subtle dark-green
 * gradient fill (surface fading to surfaceVariant), not a flat surface
 * color -- deliberately quiet compared to PredictionHero's own bold
 * gradient (see that file's doc comment for why the hero stays visually
 * distinct as each screen's one headline element, not one card among
 * many with an identical treatment). Exposed as a plain (non-composable)
 * Modifier extension -- not just baked into SectionCard below -- so any
 * other card-shaped container in the app -- e.g. HistoryScreen's
 * HistoryRow -- can match this same visual language without being
 * forced into SectionCard's title-plus-content shape, which doesn't fit
 * every layout (a list row has no separate "title" slot).
 *
 * Deliberately NOT `@Composable fun Modifier.cardSurface()`: a composable
 * modifier factory makes the whole modifier chain it's spliced into
 * non-skippable on recomposition (a real, documented Compose performance
 * smell, not just a style preference). Callers resolve
 * MaterialTheme.colorScheme themselves (already free -- they're
 * composables) and pass the two colors in, keeping this a plain,
 * skippable Modifier function.
 */
fun Modifier.cardSurface(
    topColor: Color,
    bottomColor: Color,
    cornerRadius: Dp = 18.dp,
): Modifier =
    this
        .clip(RoundedCornerShape(cornerRadius))
        .background(Brush.verticalGradient(listOf(topColor, bottomColor)))

/**
 * Every tab's card, one shared implementation instead of 9 identical
 * private copies (ContextTab, DisciplineTab, FormTab, LineupsTab,
 * OverviewTab, PerformanceTab, ProfileTab, SquadTab, StandingsTab all
 * had the exact same private fun before this).
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
                .cardSurface(MaterialTheme.colorScheme.surface, MaterialTheme.colorScheme.surfaceVariant)
                .padding(16.dp),
    ) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(4.dp))
        content()
    }
}
