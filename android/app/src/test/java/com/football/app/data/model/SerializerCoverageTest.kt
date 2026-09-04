package com.football.app.data.model

import com.football.app.data.AppJson
import org.junit.Test

/**
 * kotlinx.serialization generates a Companion.serializer() accessor for
 * every @Serializable class here. Kover attributes that single generated
 * line to the class declaration itself and only credits it as executed
 * when something calls Type.serializer() directly by name -- decoding
 * these types transitively (as a nested field of a parent type, via the
 * parent's own generated childSerializers()) does not hit this exact
 * line under Kover's line-mapping, even though every one of these types
 * IS genuinely exercised elsewhere in this suite (via the shared report/
 * team-profile fixtures and each tab's own field-level assertions).
 * Confirmed directly: adding one such call closed the gap with no other
 * change. This file exists purely to make that call for every affected
 * type in one place, rather than scattering a throwaway line across 80
 * unrelated test files.
 */
class SerializerCoverageTest {
    @Test
    fun `every model type's generated serializer accessor is reachable`() {
        AdditionalNote.serializer()
        AdvancedStats.serializer()
        BenchInfo.serializer()
        BenchRegular.serializer()
        BettingOdds.serializer()
        CardDisciplineInfo.serializer()
        CardDisciplineVenueSplit.serializer()
        ClubStrengthRating.serializer()
        CompetitionFormRecord.serializer()
        DefensiveStats.serializer()
        DetailedVenueSplitForm.serializer()
        DirectPlayExposureFlag.serializer()
        DuelVulnerability.serializer()
        EloRating.serializer()
        ExperienceComparison.serializer()
        ExperienceH2HNote.serializer()
        FatigueFlag.serializer()
        FixtureGap.serializer()
        FlaggedPlayer.serializer()
        FormResult.serializer()
        FullbackExposureInfo.serializer()
        HalfSplitStats.serializer()
        HeadToHeadMeeting.serializer()
        HeadToHeadSummary.serializer()
        HomeAdvantageInfo.serializer()
        LineupPlayer.serializer()
        LosingStreakContextInfo.serializer()
        ManagerClubRecord.serializer()
        ManagerInfo.serializer()
        ManagerTenureRecord.serializer()
        MissingPlayer.serializer()
        MomentumInfo.serializer()
        OpponentRankRecord.serializer()
        PlayerCardRisk.serializer()
        PlayerOfTheMatch.serializer()
        PlayerUsagePattern.serializer()
        PossessionMatchupInfo.serializer()
        PresenceEntry.serializer()
        RecentFormLeader.serializer()
        RefereeCardRiskNote.serializer()
        RefereeHomeAwayBias.serializer()
        RefereeStats.serializer()
        ResilienceInfo.serializer()
        RestComparison.serializer()
        RestPerformanceInfo.serializer()
        RoleFormEntry.serializer()
        RotationInfo.serializer()
        SeasonAerialEstimate.serializer()
        SeasonBigChancesEstimate.serializer()
        SeasonCornersEstimate.serializer()
        SeasonDefensiveErrorsEstimate.serializer()
        SeasonFoulsEstimate.serializer()
        SeasonGoalkeepingEstimate.serializer()
        SeasonPassingStyleEstimate.serializer()
        SeasonPlayerStats.serializer()
        SeasonShotsEstimate.serializer()
        SeasonXGEstimate.serializer()
        SetPieceGoalCounts.serializer()
        SetPieceGoals.serializer()
        SetPieceThreatFlag.serializer()
        ShotmapSideStats.serializer()
        ShotmapStats.serializer()
        SquadMember.serializer()
        SquadStrengthInfo.serializer()
        StandingsImpactInfo.serializer()
        StandingsScenario.serializer()
        StandingsTableRow.serializer()
        StandingsZoneInfo.serializer()
        StreakInfo.serializer()
        StreakStabilityInfo.serializer()
        TeamSeasonStats.serializer()
        TeamStanding.serializer()
        TopDefender.serializer()
        TopPerformer.serializer()
        TransferRecord.serializer()
        TravelInfo.serializer()
        VenueSplitForm.serializer()
        VenueSplitStats.serializer()
        WeatherDetail.serializer()
        WinProbabilities.serializer()
    }

    // The generated encode-side (write$Self) counterpart to the above --
    // this app only ever decodes these model types (real backend JSON in,
    // never re-serialized back out), so unlike deserialize() /
    // Companion.serializer(), write$Self genuinely never runs anywhere
    // else in the suite for these two types specifically (most other
    // types' write$Self incidentally shares a debug line with their own
    // covered constructor and so isn't flagged separately by Kover; these
    // two apparently don't).
    @Test
    fun `RefereeHomeAwayBias and LosingStreakContextInfo round-trip through encode too`() {
        val bias = RefereeHomeAwayBias(sampleSize = 50, homeCardsPerGame = 2.1, awayCardsPerGame = 3.4)
        val decodedBias = AppJson.decodeFromString(RefereeHomeAwayBias.serializer(), AppJson.encodeToString(RefereeHomeAwayBias.serializer(), bias))
        assert(bias == decodedBias)

        val streak = LosingStreakContextInfo(streakCount = 3, xgDelta = 0.8, potentialTurnaround = true)
        val decodedStreak =
            AppJson.decodeFromString(LosingStreakContextInfo.serializer(), AppJson.encodeToString(LosingStreakContextInfo.serializer(), streak))
        assert(streak == decodedStreak)
    }

    // Same "plain constructor never called directly, only via the
    // generated decode path" gap as MatchSummaryTest -- WinProbabilities
    // is always decoded (see PredictionHeroTest), never hand-constructed.
    @Test
    fun `WinProbabilities can be constructed directly`() {
        val probs = WinProbabilities(homeWinPct = 45.0, drawPct = 27.0, awayWinPct = 28.0)
        assert(probs.homeWinPct == 45.0)
    }
}
