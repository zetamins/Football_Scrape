package com.football.app.report

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.football.app.components.TeamBadge
import com.football.app.ui.theme.AppTheme

/**
 * Team-vs-team scoreboard header, above the Prediction hero -- the
 * reference's badge-flanking-a-score layout, adapted to a pre-match
 * report (no live score to show, so the center is "vs" rather than a
 * number pair).
 */
@Composable
fun MatchupHeader(
    homeTeam: String,
    awayTeam: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TeamColumn(homeTeam, AppTheme.colors.homeSeries, Modifier.weight(1f), TextAlign.Start, Alignment.Start)
        Text(
            "vs",
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 8.dp),
        )
        TeamColumn(awayTeam, AppTheme.colors.awaySeries, Modifier.weight(1f), TextAlign.End, Alignment.End)
    }
}

@Composable
private fun TeamColumn(
    team: String,
    color: androidx.compose.ui.graphics.Color,
    modifier: Modifier,
    textAlign: TextAlign,
    horizontalAlignment: Alignment.Horizontal,
) {
    Column(modifier = modifier, horizontalAlignment = horizontalAlignment) {
        TeamBadge(team, color, size = 52.dp)
        Spacer(Modifier.width(4.dp))
        Text(
            team,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            textAlign = textAlign,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}
