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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.football.app.components.InfoRow
import com.football.app.data.model.InsightsContext
import com.football.app.data.model.PresenceEntry
import com.football.app.ui.theme.AppTheme

/** frontend/DESIGN.md's Context tab. */
@Composable
fun ContextTab(insights: InsightsContext, homeTeam: String, awayTeam: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        RestSection(insights, homeTeam, awayTeam)
        FatigueRotationSection(insights, homeTeam, awayTeam)
        StreakSection(insights, homeTeam, awayTeam)
        ExperienceSection(insights, homeTeam, awayTeam)
        TravelSection(insights, homeTeam, awayTeam)
        AvailabilitySection(insights, homeTeam, awayTeam)
    }
}

@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(4.dp))
            content()
        }
    }
}

@Composable
private fun RestSection(insights: InsightsContext, homeTeam: String, awayTeam: String) {
    val rest = insights.restComparison
    val hasPerf = insights.homeRestPerformance != null || insights.awayRestPerformance != null
    if (rest == null && !hasPerf) return
    SectionCard("Rest") {
        rest?.let { InfoRow("Days since last match", "$homeTeam ${it.ownRestDays ?: "n/a"}d vs $awayTeam ${it.opponentRestDays ?: "n/a"}d") }
        insights.homeRestPerformance?.let { p ->
            InfoRow(
                "$homeTeam performance by rest",
                "short ${p.shortRestPpg ?: "n/a"} ppg (n=${p.shortRestSampleSize}) vs long ${p.longRestPpg ?: "n/a"} ppg (n=${p.longRestSampleSize})",
            )
        }
        insights.awayRestPerformance?.let { p ->
            InfoRow(
                "$awayTeam performance by rest",
                "short ${p.shortRestPpg ?: "n/a"} ppg (n=${p.shortRestSampleSize}) vs long ${p.longRestPpg ?: "n/a"} ppg (n=${p.longRestSampleSize})",
            )
        }
    }
}

@Composable
private fun FatigueRotationSection(insights: InsightsContext, homeTeam: String, awayTeam: String) {
    val hasFatigue = insights.homeFatigueFlag != null || insights.awayFatigueFlag != null
    val hasRotation = insights.homeRotation != null || insights.awayRotation != null
    if (!hasFatigue && !hasRotation) return
    SectionCard("Fatigue & rotation") {
        insights.homeFatigueFlag?.let { f ->
            InfoRow(homeTeam, if (f.flagged) "elevated" else "normal", valueColor = if (f.flagged) AppTheme.colors.statusWarning else AppTheme.colors.statusGood)
        }
        insights.awayFatigueFlag?.let { f ->
            InfoRow(awayTeam, if (f.flagged) "elevated" else "normal", valueColor = if (f.flagged) AppTheme.colors.statusWarning else AppTheme.colors.statusGood)
        }
        insights.homeRotation?.let { r ->
            val resultText = resultWord(r.precedingResult)
            InfoRow(
                "$homeTeam rotation",
                "${r.changedPlayers}/${r.startingXiSize} changed${r.formationChanged?.let { ", shape ${if (it) "changed" else "unchanged"}" } ?: ""}${resultText?.let { " (after a $it)" } ?: ""}",
            )
        }
        insights.awayRotation?.let { r ->
            val resultText = resultWord(r.precedingResult)
            InfoRow(
                "$awayTeam rotation",
                "${r.changedPlayers}/${r.startingXiSize} changed${r.formationChanged?.let { ", shape ${if (it) "changed" else "unchanged"}" } ?: ""}${resultText?.let { " (after a $it)" } ?: ""}",
            )
        }
    }
}

private fun resultWord(result: String?): String? = when (result) {
    "W" -> "win"
    "L" -> "loss"
    "D" -> "draw"
    else -> null
}

@Composable
private fun StreakSection(insights: InsightsContext, homeTeam: String, awayTeam: String) {
    val hasStability = insights.homeStreakStability != null || insights.awayStreakStability != null
    val hasLosing = insights.homeLosingStreakContext != null || insights.awayLosingStreakContext != null
    val hasResilience = insights.homeResilience != null || insights.awayResilience != null
    if (!hasStability && !hasLosing && !hasResilience) return
    SectionCard("Streaks") {
        insights.homeStreakStability?.let { s ->
            InfoRow("$homeTeam streak stability", "${s.streakCount}-game ${s.streakResult}${s.stable?.let { if (it) " -- stable" else " -- unstable" } ?: ""}")
        }
        insights.awayStreakStability?.let { s ->
            InfoRow("$awayTeam streak stability", "${s.streakCount}-game ${s.streakResult}${s.stable?.let { if (it) " -- stable" else " -- unstable" } ?: ""}")
        }
        insights.homeLosingStreakContext?.let { l ->
            InfoRow(
                "$homeTeam losing-streak xG",
                "${l.streakCount} games, xG delta ${l.xgDelta ?: "n/a"}${if (l.potentialTurnaround == true) " -- potential turnaround" else ""}",
                valueColor = if (l.potentialTurnaround == true) AppTheme.colors.statusGood else Color.Unspecified,
            )
        }
        insights.awayLosingStreakContext?.let { l ->
            InfoRow(
                "$awayTeam losing-streak xG",
                "${l.streakCount} games, xG delta ${l.xgDelta ?: "n/a"}${if (l.potentialTurnaround == true) " -- potential turnaround" else ""}",
                valueColor = if (l.potentialTurnaround == true) AppTheme.colors.statusGood else Color.Unspecified,
            )
        }
        insights.homeResilience?.let { r -> InfoRow("$homeTeam resilience", "${r.drawSharePct}% of non-wins were draws") }
        insights.awayResilience?.let { r -> InfoRow("$awayTeam resilience", "${r.drawSharePct}% of non-wins were draws") }
    }
}

@Composable
private fun ExperienceSection(insights: InsightsContext, homeTeam: String, awayTeam: String) {
    if (insights.experienceComparison == null && insights.experienceH2h == null) return
    SectionCard("Experience") {
        insights.experienceComparison?.let { e ->
            InfoRow("Average age", "$homeTeam ${e.ownAverageAge ?: "n/a"} vs $awayTeam ${e.opponentAverageAge ?: "n/a"}")
        }
        insights.experienceH2h?.let { h ->
            InfoRow(
                "Experience/H2H alignment",
                when (h.aligned) {
                    null -> "n/a"
                    true -> "more experienced squad also holds the H2H edge"
                    false -> "not aligned"
                },
            )
        }
    }
}

@Composable
private fun TravelSection(insights: InsightsContext, homeTeam: String, awayTeam: String) {
    val t = insights.travelInfo ?: return
    SectionCard("Travel") {
        fun tzSuffix(hours: Double?) = if ((hours ?: 0.0) > 0) ", ${hours}h tz diff" else ""
        val text = when {
            t.awayTraveling == true -> "$awayTeam traveling (~${t.awayTravelDistanceKm ?: "?"}km${t.awayTravelTimeHours?.let { ", ~${it}h travel" } ?: ""}${tzSuffix(t.awayTimezoneDiffHours)})"
            t.homeTraveling == true -> "$homeTeam traveling (~${t.homeTravelDistanceKm ?: "?"}km${t.homeTravelTimeHours?.let { ", ~${it}h travel" } ?: ""}${tzSuffix(t.homeTimezoneDiffHours)})"
            else -> "Both at home turf"
        }
        InfoRow("Travel", text)
    }
}

@Composable
private fun AvailabilitySection(insights: InsightsContext, homeTeam: String, awayTeam: String) {
    val hasPresence = !insights.homePresence.isNullOrEmpty() || !insights.awayPresence.isNullOrEmpty()
    val hasBench = insights.homeBenchInfo != null || insights.awayBenchInfo != null
    if (!hasPresence && !hasBench) return
    SectionCard("Availability") {
        insights.homePresence?.let { PresenceRow(homeTeam, it) }
        insights.awayPresence?.let { PresenceRow(awayTeam, it) }
        insights.homeBenchInfo?.let { b -> BenchRow(homeTeam, b.benchSize, b.benchTotalMarketValue, b.startingTotalMarketValue) }
        insights.awayBenchInfo?.let { b -> BenchRow(awayTeam, b.benchSize, b.benchTotalMarketValue, b.startingTotalMarketValue) }
    }
}

@Composable
private fun PresenceRow(team: String, entries: List<PresenceEntry>) {
    val absent = entries.filter { it.status == "A" }
    InfoRow(
        "$team availability",
        if (absent.isNotEmpty()) "${entries.size - absent.size} present, ${absent.size} absent: ${absent.joinToString(", ") { it.name }}" else "${entries.size} present, none absent",
        valueColor = if (absent.isNotEmpty()) AppTheme.colors.statusWarning else AppTheme.colors.statusGood,
    )
}

@Composable
private fun BenchRow(team: String, size: Int, benchValue: Double?, startingValue: Double?) {
    fun fmt(v: Double?) = v?.let { "€${(it / 1_000_000).toInt()}m" } ?: "n/a"
    InfoRow("$team bench", "$size named, ${fmt(benchValue)} combined value vs starting XI's ${fmt(startingValue)}")
}
