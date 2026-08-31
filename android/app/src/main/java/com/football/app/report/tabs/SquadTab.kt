package com.football.app.report.tabs

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.football.app.charts.RankedBarList
import com.football.app.charts.RankedEntry
import com.football.app.charts.Segment
import com.football.app.charts.SegmentedBar
import com.football.app.components.OutlinedPill
import com.football.app.components.PillFlow
import com.football.app.components.SectionCard
import com.football.app.components.InfoRow
import com.football.app.data.model.SquadStrengthInfo
import com.football.app.data.model.TeamProfileData
import com.football.app.ui.theme.AppTheme

/**
 * frontend/DESIGN.md's Squad tab, rendered once per team (called twice
 * -- team + opponent, same shape either way).
 */
@Composable
fun SquadTab(profile: TeamProfileData, squadStrength: SquadStrengthInfo?, label: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        Text(label, style = MaterialTheme.typography.titleMedium)
        TopPerformersSection(profile)
        AvailabilitySection(profile)
        FormSection(profile)
        RoleFormSection(profile)
        SquadValueSection(squadStrength)
        TransfersSection(profile)
    }
}


@Composable
private fun TopPerformersSection(profile: TeamProfileData) {
    val hasAny = !profile.topScorers.isNullOrEmpty() || !profile.topAssists.isNullOrEmpty() || !profile.topDefenders.isNullOrEmpty()
    if (!hasAny) return
    SectionCard("Top performers") {
        profile.topScorers?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Top scorers", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(4.dp))
            RankedBarList(list.map { RankedEntry(it.name, it.goals, "${it.goals}g") }, AppTheme.colors.statusGood)
            Spacer(Modifier.height(10.dp))
        }
        profile.topAssists?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Top assists", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(4.dp))
            RankedBarList(list.map { RankedEntry(it.name, it.assists, "${it.assists}a") }, AppTheme.colors.brandBright)
            Spacer(Modifier.height(10.dp))
        }
        profile.topDefenders?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Top defenders", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(4.dp))
            RankedBarList(list.map { RankedEntry(it.name, it.tacklesMade, "${it.tacklesMade}T/${it.interceptions}I") }, AppTheme.colors.statusWarning)
            Spacer(Modifier.height(6.dp))
        }
        profile.averageAge?.let { InfoRow("Average age", "$it") }
    }
}

@Composable
private fun AvailabilitySection(profile: TeamProfileData) {
    val keyInjuries = profile.keyInjuries?.takeIf { it.isNotEmpty() }
    val injuries = profile.injuries?.takeIf { it.isNotEmpty() }
    val missing = listOfNotNull(
        profile.missingGoalkeepers?.takeIf { it.isNotEmpty() },
        profile.missingDefenders?.takeIf { it.isNotEmpty() },
        profile.missingMidfielders?.takeIf { it.isNotEmpty() },
        profile.missingAttackers?.takeIf { it.isNotEmpty() },
    ).flatten()
    if (keyInjuries == null && injuries == null && missing.isEmpty()) return
    SectionCard("Availability") {
        (keyInjuries ?: injuries)?.let { list ->
            Text(if (keyInjuries != null) "Key injuries" else "Injuries", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(6.dp))
            PlayerPillRow(list.map { it.name })
            Spacer(Modifier.height(8.dp))
        }
        if (missing.isNotEmpty()) {
            Text("Missing", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(6.dp))
            PlayerPillRow(missing)
        }
    }
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun PlayerPillRow(names: List<String>) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        names.forEach { name ->
            OutlinedPill(text = name, borderColor = AppTheme.colors.statusCritical, contentColor = AppTheme.colors.statusCritical)
        }
    }
}

@Composable
private fun FormSection(profile: TeamProfileData) {
    val hasBench = !profile.benchRegulars.isNullOrEmpty()
    val hasLeaders = !profile.recentFormLeaders.isNullOrEmpty()
    if (!hasBench && !hasLeaders) return
    SectionCard("Recent form (last 20)") {
        profile.benchRegulars?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Bench regulars", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(4.dp))
            PlayerStatRows(list.map { it.name to "${it.starts} starts, ${it.subAppearances} sub, ${it.unusedBench} unused" })
            Spacer(Modifier.height(8.dp))
        }
        profile.recentFormLeaders?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Form leaders", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(4.dp))
            PlayerStatRows(
                list.map { l ->
                    val xgText = "%.2f".format(l.xg)
                    val keyPassesText = if (l.keyPasses > 0) ", ${l.keyPasses} KP" else ""
                    val per90Text = l.goalsPer90?.let { ", $it/90" } ?: ""
                    val ratingText = l.avgRating?.let { ", $it rating" } ?: ""
                    l.name to "${l.goals}g/${l.assists}a, ${xgText}xG$keyPassesText$per90Text$ratingText"
                },
            )
        }
    }
}

@Composable
private fun RoleFormSection(profile: TeamProfileData) {
    val hasMid = !profile.midfieldersForm.isNullOrEmpty()
    val hasDef = !profile.defendersForm.isNullOrEmpty()
    if (!hasMid && !hasDef) return
    SectionCard("Form by role (ranked by minutes)") {
        profile.midfieldersForm?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Midfielders", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(4.dp))
            PlayerStatRows(list.map { m -> m.name to "${m.totalMinutes}min in ${m.matchesInSquad} (${m.starts} starts), ${m.goals}g/${m.assists}a" })
            Spacer(Modifier.height(8.dp))
        }
        profile.defendersForm?.takeIf { it.isNotEmpty() }?.let { list ->
            Text("Defenders", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(4.dp))
            PlayerStatRows(list.map { m -> m.name to "${m.totalMinutes}min in ${m.matchesInSquad} (${m.starts} starts), ${m.goals}g/${m.assists}a" })
        }
    }
}

/** One row per player: name left, stat text right -- not a comma-joined string. Shared by every dense per-player list in this tab. */
@Composable
private fun PlayerStatRows(rows: List<Pair<String, String>>) {
    rows.forEach { (name, stat) ->
        Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
            Text(name, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f), maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
            Text(stat, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun SquadValueSection(strength: SquadStrengthInfo?) {
    if (strength == null) return
    SectionCard("Squad value") {
        fun fmt(v: Double?) = v?.let { "€${(it / 1_000_000).toInt()}m" } ?: "n/a"
        InfoRow(
            "Total (available)",
            "${fmt(strength.totalValue)} (${fmt(strength.availableValue)} available)",
        )
        val parts = listOfNotNull(
            strength.attackValue?.let { "Attack" to it },
            strength.midfieldValue?.let { "Midfield" to it },
            strength.defenseValue?.let { "Defense" to it },
            strength.goalkeeperValue?.let { "GK" to it },
        )
        if (parts.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            val colors = AppTheme.colors.squadCategorical
            SegmentedBar(segments = parts.mapIndexed { i, (_, v) -> Segment(v.toFloat(), colors[i % colors.size]) })
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                parts.forEachIndexed { i, (label, v) ->
                    LegendChip(label, fmt(v), colors[i % colors.size])
                }
            }
        }
    }
}

@Composable
private fun LegendChip(label: String, value: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(modifier = Modifier.size(8.dp).background(color, CircleShape))
        Text("$label $value", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 4.dp))
    }
}

@Composable
private fun TransfersSection(profile: TeamProfileData) {
    val transfers = profile.recentTransfers?.takeIf { it.isNotEmpty() } ?: return
    SectionCard("Recent transfers") {
        PillFlow {
            transfers.take(5).forEach { t ->
                val color = if (t.direction == "in") AppTheme.colors.statusGood else AppTheme.colors.statusCritical
                OutlinedPill(
                    text = "${if (t.direction == "in") "→" else "←"} ${t.playerName}${t.date?.let { d -> " (${d.take(10)})" } ?: ""}",
                    borderColor = color,
                    contentColor = color,
                )
            }
        }
    }
}
