package com.football.app.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class RefereeHomeAwayBias(
    val sampleSize: Int,
    val homeCardsPerGame: Double,
    val awayCardsPerGame: Double,
)

@Serializable
data class RefereeStats(
    val games: Int,
    val yellowCardsPerGame: Double,
    val penaltiesAwarded: Int? = null,
    val foulsPerGame: Double? = null,
    val redCardsPerGame: Double? = null,
    val homeAwayBias: RefereeHomeAwayBias? = null,
)

@Serializable
data class ManagerTenureRecord(
    val played: Int,
    val wins: Int,
    val draws: Int,
    val losses: Int,
    val winPct: Double? = null,
)

@Serializable
data class ManagerInfo(
    val name: String,
    val country: String? = null,
    val appointedDate: String? = null,
    val previousManager: String? = null,
    val recentAppointment: Boolean? = null,
    val recordAtClub: ManagerTenureRecord? = null,
    val age: Int? = null,
)

@Serializable
data class ManagerClubRecord(
    val managerName: String,
    val opponentClub: String,
    val sampleSize: Int,
    val wins: Int,
    val draws: Int,
    val losses: Int,
)

/** goalDiff is a String ("0", not 0) -- matches TeamStanding.goal_diff:
 * str in types.py exactly. */
@Serializable
data class TeamStanding(
    val position: Int,
    val played: Int,
    val wins: Int,
    val draws: Int,
    val losses: Int,
    val points: Int,
    val goalDiff: String,
    val totalTeams: Int? = null,
)

@Serializable
data class HeadToHeadSummary(
    val homeWins: Int,
    val awayWins: Int,
    val draws: Int,
)

@Serializable
data class HeadToHeadMeeting(
    val date: String? = null,
    val competition: String? = null,
    val scoreline: String,
    val venue: String,
    val homeFormation: String? = null,
    val awayFormation: String? = null,
    val homeXg: Double? = null,
    val awayXg: Double? = null,
    // home_lineup/away_lineup deliberately not modeled here -- Overview
    // only shows the summary line per frontend/DESIGN.md; ignoreUnknownKeys
    // (see JsonConfig.kt) skips them safely rather than requiring this
    // tab to type LineupPlayer just to discard it.
)

/** over_2_5_odds/under_2_5_odds get explicit @SerialName rather than
 * relying on the SnakeCase naming strategy to reconstruct a digit inside
 * a camelCase name correctly -- verified via OverviewModelsTest against
 * real backend JSON, not assumed. */
@Serializable
data class BettingOdds(
    val homeWinOdds: Double? = null,
    val drawOdds: Double? = null,
    val awayWinOdds: Double? = null,
    val homeWinImpliedPct: Double? = null,
    val drawImpliedPct: Double? = null,
    val awayWinImpliedPct: Double? = null,
    @SerialName("over_2_5_odds") val over25Odds: Double? = null,
    @SerialName("under_2_5_odds") val under25Odds: Double? = null,
)

@Serializable
data class WeatherDetail(
    val tempC: Double? = null,
    val humidityPct: Double? = null,
    val windSpeedKmph: Double? = null,
    val precipMm: Double? = null,
    val chanceOfRainPct: Double? = null,
    val windGustKmph: Double? = null,
    val cloudCoverPct: Double? = null,
    val feelsLikeC: Double? = null,
)

@Serializable
data class AdditionalNote(
    val note: String,
)

// report.venueDetails -- a whole top-level section (stadium profile, not
// match-specific) that was decoded into ReportJson but never actually
// read by any tab until now. Distinct from MatchOverview's
// venueName/venueCity/venueCountry/venueCapacity, which come from
// `match` and can legitimately disagree (e.g. a sponsor-renamed stadium)
// -- shown as additional facts in the same Venue card, not a merge/dedupe
// of the two sources.

/**
 * renovated/recordAttendance are String, not Int, despite looking
 * numeric -- renovated can be a range ("2000, 2002", "1998-1999") and
 * recordAttendance is a full free-text description ("48 353 (Sunderland
 * - Liverpool; 13.04.2002)"), confirmed across 4 real backend/output/
 * samples, not assumed from the field name.
 */
@Serializable
data class VenueDetails(
    val stadiumName: String? = null,
    val capacity: Int? = null,
    val opened: Int? = null,
    val renovated: String? = null,
    val clubs: List<String>? = null,
    val city: String? = null,
    val address: String? = null,
    val architect: String? = null,
    val recordAttendance: String? = null,
)

/**
 * Everything Overview needs from `match` (frontend/DESIGN.md's Overview
 * section) -- a growing subset, same pattern as MatchSummary.kt. Field
 * name mappings verified against real backend JSON in
 * OverviewModelsTest, not assumed from the naming strategy alone.
 */
@Serializable
data class MatchOverview(
    val kickoffUtc: String? = null,
    val round: Int? = null,
    val season: String? = null,
    val venueName: String? = null,
    val venueCity: String? = null,
    val venueCountry: String? = null,
    val venueCapacity: Int? = null,
    val weather: String? = null,
    val weatherDetail: WeatherDetail? = null,
    val referee: String? = null,
    val refereeStats: RefereeStats? = null,
    val homeManager: ManagerInfo? = null,
    val awayManager: ManagerInfo? = null,
    val homeManagerVsAwayClub: ManagerClubRecord? = null,
    val awayManagerVsHomeClub: ManagerClubRecord? = null,
    val homeTeamStanding: TeamStanding? = null,
    val awayTeamStanding: TeamStanding? = null,
    val headToHeadSummary: HeadToHeadSummary? = null,
    // Same {home_wins, away_wins, draws} shape as headToHeadSummary
    // (confirmed against real data) -- one manager's record against the
    // other, not the two clubs' H2H record.
    val managerDuel: HeadToHeadSummary? = null,
    val headToHeadStreaks: List<String>? = null,
    val recentMeetings: List<HeadToHeadMeeting>? = null,
    val bettingOdds: BettingOdds? = null,
    val note: String? = null,
    val additionalNotes: List<AdditionalNote>? = null,
)
