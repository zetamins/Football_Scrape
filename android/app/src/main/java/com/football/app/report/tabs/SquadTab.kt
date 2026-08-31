package com.football.app.report.tabs

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
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
            InfoRow("Top scorers", list.joinToString(", ") { "${it.name} (${it.goals}g)" })
        }
        profile.topAssists?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow("Top assists", list.joinToString(", ") { "${it.name} (${it.assists}a)" })
        }
        profile.topDefenders?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow("Top defenders", list.joinToString(", ") { "${it.name} (${it.tacklesMade}T/${it.interceptions}I)" })
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
            InfoRow(
                if (keyInjuries != null) "Key injuries" else "Injuries",
                list.joinToString(", ") { it.name },
                valueColor = AppTheme.colors.statusCritical,
            )
        }
        profile.missingGoalkeepers?.takeIf { it.isNotEmpty() }?.let { InfoRow("Missing goalkeepers", it.joinToString(", "), valueColor = AppTheme.colors.statusCritical) }
        profile.missingDefenders?.takeIf { it.isNotEmpty() }?.let { InfoRow("Missing defenders", it.joinToString(", "), valueColor = AppTheme.colors.statusCritical) }
        profile.missingMidfielders?.takeIf { it.isNotEmpty() }?.let { InfoRow("Missing midfielders", it.joinToString(", "), valueColor = AppTheme.colors.statusCritical) }
        profile.missingAttackers?.takeIf { it.isNotEmpty() }?.let { InfoRow("Missing attackers", it.joinToString(", "), valueColor = AppTheme.colors.statusCritical) }
    }
}

@Composable
private fun FormSection(profile: TeamProfileData) {
    val hasBench = !profile.benchRegulars.isNullOrEmpty()
    val hasLeaders = !profile.recentFormLeaders.isNullOrEmpty()
    if (!hasBench && !hasLeaders) return
    SectionCard("Recent form (last 20)") {
        profile.benchRegulars?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow(
                "Bench regulars",
                list.joinToString(", ") { "${it.name} (${it.starts} starts, ${it.subAppearances} sub apps, ${it.unusedBench} unused)" },
            )
        }
        profile.recentFormLeaders?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow(
                "Form leaders",
                list.joinToString(", ") { l ->
                    val xgText = "%.2f".format(l.xg)
                    val keyPassesText = if (l.keyPasses > 0) ", ${l.keyPasses} KP" else ""
                    val per90Text = l.goalsPer90?.let { ", $it/90" } ?: ""
                    val ratingText = l.avgRating?.let { ", $it rating" } ?: ""
                    "${l.name} (${l.goals}g/${l.assists}a, ${xgText}xG$keyPassesText$per90Text$ratingText)"
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
            InfoRow(
                "Midfielders",
                list.joinToString(", ") { m -> "${m.name} (${m.totalMinutes}min in ${m.matchesInSquad} (${m.starts} starts), ${m.goals}g/${m.assists}a)" },
            )
        }
        profile.defendersForm?.takeIf { it.isNotEmpty() }?.let { list ->
            InfoRow(
                "Defenders",
                list.joinToString(", ") { m -> "${m.name} (${m.totalMinutes}min in ${m.matchesInSquad} (${m.starts} starts), ${m.goals}g/${m.assists}a)" },
            )
        }
    }
}

@Composable
private fun SquadValueSection(strength: SquadStrengthInfo?) {
    if (strength == null) return
    SectionCard("Squad value") {
        fun fmt(v: Double?) = v?.let { "€${(it / 1_000_000).toInt()}m" } ?: "n/a"
        InfoRow(
            "Total (available)",
            "${fmt(strength.totalValue)} (${fmt(strength.availableValue)} available)",
        )
        InfoRow(
            "Attack / midfield / defense / GK",
            "${fmt(strength.attackValue)} / ${fmt(strength.midfieldValue)} / ${fmt(strength.defenseValue)} / ${fmt(strength.goalkeeperValue)}",
        )
    }
}

@Composable
private fun TransfersSection(profile: TeamProfileData) {
    val transfers = profile.recentTransfers?.takeIf { it.isNotEmpty() } ?: return
    SectionCard("Recent transfers") {
        Text(
            transfers.take(5).joinToString("; ") { "${it.playerName} (${it.direction}${it.date?.let { d -> ", ${d.take(10)}" } ?: ""})" },
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
