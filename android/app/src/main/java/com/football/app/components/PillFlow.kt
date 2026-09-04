package com.football.app.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * A wrapping row of pills -- the shared layout every "list of players/
 * tags" section uses instead of a comma-joined string (Squad's
 * injuries, Context's absent players, Profile's risk lists, Lineups'
 * bench/suspended/missing). One place for the FlowRow + spacing
 * boilerplate instead of re-declaring it per tab file.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PillFlow(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    FlowRow(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
        content = { content() },
    )
}
