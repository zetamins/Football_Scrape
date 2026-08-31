"""Data shapes shared across the scraping/merging/insights pipeline.

Ported 1:1 from src/types.ts. Field names are snake_case (idiomatic Python)
rather than the TS camelCase -- the camelCase mapping needed for JSON
compatibility with the existing web dashboard is handled at the
serialization boundary (report.py), not here.

Every dataclass field is required (no defaults) except genuinely optional
keys (TS's `field?: T`, as opposed to `field: T | null`) -- this mirrors how
every function in the original always constructs full literals, even for
null fields, rather than omitting keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Source = Literal["sofascore", "fotmob", "soccerdesk", "goal", "365scores"]
FieldSource = Literal["sofascore", "fotmob", "soccerdesk", "goal", "365scores", "wttr.in"]


@dataclass
class MatchInfo:
    source: Source
    source_url: str
    competition: Optional[str]
    home_team: str
    away_team: str
    kickoff_utc: Optional[str]
    venue: Optional[str]
    status: Optional[str]
    home_score: Optional[int]
    away_score: Optional[int]
    # Half-time score, when the source provides it (Sofascore only) -- null
    # for Fotmob and for not-yet-played/in-progress matches.
    home_score_ht: Optional[int]
    away_score_ht: Optional[int]
    # Season label (e.g. "Premier League 25/26") -- Sofascore only.
    season: Optional[str]
    # Matchday/round number within the competition -- Sofascore only, and
    # only for competitions that actually have rounds (league play).
    round: Optional[int]
    # The source's own internal match/event id.
    match_id: str


@dataclass
class TeamSearchResult:
    team: str
    source: Source
    matches: list[MatchInfo]
    error: Optional[str] = None


@dataclass
class LineupPlayer:
    name: str
    position: Optional[str]
    # Sofascore only -- null from every other source.
    substitute: Optional[bool]
    # Minutes actually played -- null (not 0) for an unused substitute, since
    # 0 would wrongly imply "played and recorded 0 minutes" rather than
    # "never came on".
    minutes_played: Optional[int]
    goals: Optional[int]
    assists: Optional[int]
    xg: Optional[float]
    xa: Optional[float]
    shots: Optional[int]
    shots_on_target: Optional[int]
    tackles: Optional[int]
    interceptions: Optional[int]
    fouls: Optional[int]
    rating: Optional[float]
    key_passes: Optional[int]
    # Sofascore and Goal.com only -- confirmed live: no "captain" marker
    # exists anywhere in either source's lineup payload (checked directly,
    # not assumed), so no is_captain field was added here.
    shirt_number: Optional[int] = None
    # Sofascore only, derived from dateOfBirthTimestamp at extraction time
    # (age as of the match, not stored as a birth date).
    age: Optional[int] = None


@dataclass
class TeamStanding:
    position: int
    played: int
    wins: int
    draws: int
    losses: int
    points: int
    goal_diff: str
    # Size of the full standings table this position came from -- lets us
    # classify "top of table"/"relegation zone" without guessing a fixed
    # league size.
    total_teams: Optional[int]


@dataclass
class SetPieceGoalCounts:
    corner: int
    penalty: int
    free_kick: int


@dataclass
class SetPieceGoals:
    home: SetPieceGoalCounts
    away: SetPieceGoalCounts


@dataclass
class ShotmapSideStats:
    non_penalty_xg: float
    set_piece_xg: float
    penalties_awarded: int


@dataclass
class ShotmapStats:
    home: ShotmapSideStats
    away: ShotmapSideStats


@dataclass
class TimelineEvent:
    minute: int
    type: str
    detail: Optional[str]
    player: Optional[str]
    team: Optional[Literal["home", "away"]]


@dataclass
class ManagerTenureRecord:
    """Overall P/W/D/L at the manager's CURRENT club, from the same
    Wikipedia "Managerial record" table row already fetched for
    appointed_date -- distinct from ManagerClubRecord, which is the
    manager's record against one specific OPPONENT club."""

    played: int
    wins: int
    draws: int
    losses: int
    win_pct: Optional[float]


@dataclass
class ManagerInfo:
    name: str
    country: Optional[str]
    # From the manager's own Wikipedia page's "Managerial record" table (the
    # row whose "To" column reads "Present"). Null if no such page/row.
    appointed_date: Optional[str]
    # From the CLUB's "List of {Club} managers" Wikipedia page -- the
    # manager immediately before the current one in that table.
    previous_manager: Optional[str]
    # <=90 days old at search time counts as "recent" -- deliberately round,
    # not competition-tuned. Null (not false) whenever appointed_date is
    # null, so "recent" vs "unknown" stay distinguishable.
    recent_appointment: Optional[bool]
    # Same Wikipedia row as appointed_date -- the Played/Won/Drawn/Lost
    # columns already sitting on that row, previously discarded.
    record_at_club: Optional[ManagerTenureRecord] = None
    # Same Wikipedia article page as appointed_date/record_at_club -- the
    # infobox's own "Date of birth", previously unused.
    age: Optional[int] = None


@dataclass
class RefereeHomeAwayBias:
    sample_size: int
    home_cards_per_game: float
    away_cards_per_game: float


@dataclass
class BettingOdds:
    """From football-data.co.uk's own live upcoming-fixtures file (a
    different file from the per-season results CSV RefereeHomeAwayBias
    uses) -- real decimal odds for THIS specific upcoming match, not a
    historical/derived estimate. Uses each market's "Avg" column (the
    average across every bookmaker football-data.co.uk tracks for that
    match) rather than a single bookmaker, since the market average is a
    more representative consensus than any one bookmaker's line.
    Implied_pct fields are the standard de-vig calculation (each
    1/odds share renormalized so the three outcomes sum to 100%) --
    a real, well-established calculation, not a guess."""

    home_win_odds: Optional[float]
    draw_odds: Optional[float]
    away_win_odds: Optional[float]
    home_win_implied_pct: Optional[float]
    draw_implied_pct: Optional[float]
    away_win_implied_pct: Optional[float]
    over_2_5_odds: Optional[float]
    under_2_5_odds: Optional[float]


@dataclass
class RefereeStats:
    games: int
    yellow_cards: int
    red_cards: int
    yellow_cards_per_game: str
    # From worldfootball.net's competition referee-stats page. Null if the
    # competition isn't in our small tracked mapping, or the name doesn't match.
    penalties_awarded: Optional[int]
    # From football-data.co.uk's per-season CSV, matched by referee surname.
    # Uses last season's file if the current one isn't published yet.
    home_away_bias: Optional[RefereeHomeAwayBias]
    # From refsradar.com's referee profile page ("Fouls/g").
    fouls_per_game: Optional[float]
    # Same refsradar.com profile page, "RED/g" -- a rate, distinct from the
    # raw red_cards count above (which is Sofascore's season total, not a
    # per-game figure). Null under the same conditions as fouls_per_game.
    red_cards_per_game: Optional[float] = None
    # All four from the same refsradar.com fetch as fouls_per_game/
    # red_cards_per_game above -- zero extra requests. Not duplicating
    # refsradar's own "YEL/g" here since yellow_cards_per_game above
    # already covers that concept (Sofascore-sourced instead).
    referee_matches: Optional[int] = None
    penalties_per_game: Optional[float] = None
    cards_per_foul: Optional[float] = None
    avg_total_cards: Optional[float] = None
    # From the same worldfootball.net fetch as penalties_awarded --
    # second-yellow-then-red dismissals specifically, distinct from the
    # straight-red red_cards count above (that column exists on the same
    # table but isn't used here, since Sofascore's season total already
    # covers reds generally).
    second_yellow_cards: Optional[int] = None


@dataclass
class WeatherDetail:
    temp_c: Optional[float]
    humidity_pct: Optional[float]
    wind_speed_kmph: Optional[float]
    precip_mm: Optional[float]
    # All wttr.in-only, from the same j1 hourly payload as the four fields
    # above -- zero extra requests. Genuinely relevant to a football match
    # preview (rain risk, gusty conditions affecting aerial play/set
    # pieces), unlike some of the payload's other fields (pressure, UV
    # index) that were left out as not meaningfully match-relevant.
    chance_of_rain_pct: Optional[float] = None
    wind_gust_kmph: Optional[float] = None
    cloud_cover_pct: Optional[float] = None
    feels_like_c: Optional[float] = None
    # True when the venue's country resolved to a real UTC offset and this
    # reading is the wttr.in hourly slot actually closest to true local
    # kickoff time. False means the offset was unknown and this is the
    # older "local midday" same-day approximation instead.
    kickoff_hour_matched: bool = False


@dataclass
class TeamSeasonStats:
    goals_scored: int
    goals_conceded: int
    clean_sheets: int
    yellow_cards: int
    red_cards: int
    average_ball_possession: Optional[float]


@dataclass
class HeadToHeadSummary:
    home_wins: int
    away_wins: int
    draws: int


@dataclass
class MatchStatItem:
    name: str
    home: str
    away: str


@dataclass
class PlayerOfTheMatch:
    name: str
    rating: Optional[str]


@dataclass
class ManagerClubRecord:
    manager_name: str
    opponent_club: str
    sample_size: int
    wins: int
    draws: int
    losses: int


@dataclass
class HeadToHeadMeeting:
    date: Optional[str]
    competition: Optional[str]
    scoreline: str
    venue: Literal["home", "away"]
    home_formation: Optional[str]
    away_formation: Optional[str]
    home_xg: Optional[float]
    away_xg: Optional[float]
    home_lineup: Optional[list[LineupPlayer]]
    away_lineup: Optional[list[LineupPlayer]]


@dataclass
class MissingPlayer:
    """Match-specific, reasoned unavailability -- Sofascore's own
    lineups.missingPlayers, distinct from a team profile's general
    (not-match-specific) injuries list. `description` is whatever text
    Sofascore published -- sometimes a category slug ("coach_decision"),
    sometimes a real description ("Knee Injury") -- confirmed live to be
    inconsistent in shape; Sofascore's own numeric `reason` code has no
    published lookup table, so it's dropped rather than exposed unexplained."""

    name: str
    description: Optional[str]
    expected_return: Optional[str]


@dataclass
class MatchDetails(MatchInfo):
    venue_name: Optional[str]
    venue_city: Optional[str]
    venue_country: Optional[str]
    # Sofascore only, from the same event fetch as everything else --
    # lets TravelInfo compute exact venue-to-venue distance instead of the
    # country-capital approximation geo.py otherwise falls back to.
    venue_lat: Optional[float]
    venue_lon: Optional[float]
    referee: Optional[str]
    referee_stats: Optional[RefereeStats]
    attendance: Optional[int]
    weather: Optional[str]
    weather_detail: Optional[WeatherDetail]
    head_to_head_summary: Optional[HeadToHeadSummary]
    head_to_head_streaks: Optional[list[str]]
    # Individual past meetings found within the already-fetched recent-form
    # window (last20Overall) -- NOT an exhaustive career head-to-head.
    # Capped at 3 most recent.
    recent_meetings: Optional[list[HeadToHeadMeeting]]
    home_lineup: Optional[list[LineupPlayer]]
    away_lineup: Optional[list[LineupPlayer]]
    # Named substitutes (used or unused) -- Sofascore only.
    home_bench: Optional[list[LineupPlayer]]
    away_bench: Optional[list[LineupPlayer]]
    home_team_standing: Optional[TeamStanding]
    away_team_standing: Optional[TeamStanding]
    home_team_season_stats: Optional[TeamSeasonStats]
    away_team_season_stats: Optional[TeamSeasonStats]
    match_stats: Optional[list[MatchStatItem]]
    event_timeline: Optional[list[TimelineEvent]]
    # Sofascore only, from its shotmap endpoint. Zeroed (not null) for a
    # not-yet-played match.
    set_piece_goals: Optional[SetPieceGoals]
    shotmap_stats: Optional[ShotmapStats]
    player_of_the_match: Optional[PlayerOfTheMatch]
    home_formation: Optional[str]
    away_formation: Optional[str]
    # null (nothing published) -> false (predicted) -> true (confirmed).
    lineup_confirmed: Optional[bool]
    # Each team's own registered country (not the venue's country) --
    # Sofascore only.
    home_team_country: Optional[str]
    away_team_country: Optional[str]
    home_manager: Optional[ManagerInfo]
    away_manager: Optional[ManagerInfo]
    home_manager_vs_away_club: Optional[ManagerClubRecord]
    away_manager_vs_home_club: Optional[ManagerClubRecord]
    # Full league table for this competition, not just the two teams playing.
    standings_table: Optional[list["StandingsTableRow"]]
    # SoccerDesk only.
    home_suspended_players: Optional[list[str]]
    away_suspended_players: Optional[list[str]]
    # Sofascore only, from the same lineups fetch as home_lineup/home_bench
    # -- richer than home_suspended_players/the team profile's injuries
    # list: match-specific, with a reason category and (where published) an
    # expected return date.
    home_missing_players: Optional[list[MissingPlayer]] = None
    away_missing_players: Optional[list[MissingPlayer]] = None
    # Sofascore only, from the same h2h fetch as head_to_head_summary --
    # the actual two-manager head-to-head (both currently in charge of
    # their respective clubs), distinct from ManagerClubRecord (one
    # manager's record against an opponent CLUB across his whole career).
    manager_duel: Optional[HeadToHeadSummary] = None
    # football-data.co.uk only, populated centrally in orchestrate.py
    # (not per-site like the fields above) since it's matched by team
    # name/date against a single shared all-leagues fixtures file, not
    # tied to any one scraper's own match object.
    betting_odds: Optional[BettingOdds] = None
    note: Optional[str] = None
    # Sofascore only, from the same event fetch as venue_name/venue_lat/
    # venue_lon above -- zero extra requests. A separate field from
    # VenueDetails.capacity (StadiumDB) rather than folding into it: this
    # is available whenever Sofascore succeeds even if StadiumDB has no
    # page for the venue at all (confirmed live: several smaller grounds
    # this project has hit aren't in StadiumDB's country listings).
    venue_capacity: Optional[int] = None


@dataclass
class StandingsTableRow:
    team_name: str
    position: int
    points: int


@dataclass
class SeasonPlayerStats:
    # Optional (not every source has this) -- confirmed live: Fotmob's
    # squad page has real per-player rating/goals/assists/cards for the
    # whole squad, but no appearances count anywhere on that page. Left
    # None rather than guessing, same convention as rating/expected_goals
    # below being Sofascore-only extras.
    appearances: Optional[int]
    goals: int
    assists: int
    yellow_cards: int
    red_cards: int
    # Sofascore-only extras -- null from every other source.
    rating: Optional[float]
    expected_goals: Optional[float]


@dataclass
class DefensiveStats:
    """Squawka only. See squawka.py module doc for which named stats are
    genuinely populated vs. an empty-option trap on that site -- despite
    the name (kept for continuity with chances_created, already a
    non-defensive stat living here), this is really "Squawka's own
    per-player season stats", not strictly defensive ones."""

    tackles_made: Optional[int]
    interceptions: Optional[int]
    ball_recoveries: Optional[int]
    clearances: Optional[int]
    ground_duel_success_pct: Optional[float]
    chances_created: Optional[int]
    # Genuinely new per-player numbers no other source in this project
    # provides (Sofascore/Fotmob's per-player stats don't include shots or
    # pass volume; aerial duels only exists as a team-level estimate
    # elsewhere, not per-player).
    shots: Optional[int] = None
    shots_on_target: Optional[int] = None
    passes_completed: Optional[int] = None
    fouls_won: Optional[int] = None
    aerial_duels_won: Optional[int] = None
    # A second pass over Squawka's own stat-filter labels (confirmed live
    # against the site's own rendered column headers this time, not
    # guessed) found 9 more real, non-empty per-player stats.
    goals_from_inside_box: Optional[int] = None
    goals_from_outside_box: Optional[int] = None
    conversion_rate_pct: Optional[float] = None
    shots_off_target: Optional[int] = None
    passes_attempted: Optional[int] = None
    passing_accuracy_pct: Optional[float] = None
    blocked_shots: Optional[int] = None
    take_ons_completed: Optional[int] = None
    ground_duels_won: Optional[int] = None


@dataclass
class PlayerUsagePattern:
    matches_in_squad: int
    starts: int
    sub_appearances: int
    unused_bench: int
    total_minutes: int
    total_goals: int
    total_assists: int
    total_xg: float
    total_xa: float
    total_shots: int
    total_shots_on_target: int
    total_tackles: int
    total_interceptions: int
    total_fouls: int
    total_key_passes: int
    appearances_with_stats: int
    avg_rating: Optional[float]
    goals_per_90: Optional[float]
    assists_per_90: Optional[float]
    xg_per_90: Optional[float]
    xa_per_90: Optional[float]
    key_passes_per_90: Optional[float]


@dataclass
class SquadMember:
    name: str
    role: Optional[str]
    injury: Optional[str]
    age: Optional[int]
    market_value: Optional[float]
    season_stats: Optional[SeasonPlayerStats]
    season_stats_source: Optional[Source]
    defensive_stats: Optional[DefensiveStats]
    recent_usage: Optional[PlayerUsagePattern]


@dataclass
class TransferRecord:
    player_name: str
    direction: Literal["in", "out"]
    from_club: Optional[str]
    to_club: Optional[str]
    date: Optional[str]


@dataclass
class TeamProfile:
    source: Source
    team_name: str
    squad: Optional[list[SquadMember]]
    average_age: Optional[float]
    injuries: Optional[list[SquadMember]]
    # Ranked by squad market value -- an objective proxy for "key player".
    key_injuries: Optional[list[SquadMember]]
    recent_transfers: Optional[list[TransferRecord]]
    missing_midfielders: Optional[list[str]]
    missing_attackers: Optional[list[str]]
    missing_defenders: Optional[list[str]]
    missing_goalkeepers: Optional[list[str]]


@dataclass
class FormResult:
    opponent: str
    competition: Optional[str]
    date: Optional[str]
    result: Literal["W", "D", "L"]
    scoreline: str
    venue: Literal["home", "away"]
    margin: int
    # Whether this match was played somewhere other than the team's own
    # country despite the fixture data's home/away label. Null until enriched.
    neutral_venue: Optional[bool]
    ht_scoreline: Optional[str]
    xg_for: Optional[float]
    xg_against: Optional[float]


@dataclass
class VenueSplitForm:
    home_sample_size: int
    home_wins: int
    home_draws: int
    home_losses: int
    home_goals_for: int
    home_goals_against: int
    away_sample_size: int
    away_wins: int
    away_draws: int
    away_losses: int
    away_goals_for: int
    away_goals_against: int
    neutral_sample_size: int
    neutral_wins: int
    neutral_draws: int
    neutral_losses: int
    neutral_goals_for: int
    neutral_goals_against: int


@dataclass
class VenueSplitStats:
    sample_size: int
    xg_for: float
    xg_against: float
    shots_for: int
    shots_against: int
    shots_on_target_for: int
    shots_on_target_against: int
    possession_pct_avg: Optional[float]
    corners_for: int
    corners_against: int
    fouls_for: int
    fouls_against: int
    yellow_cards_for: int
    yellow_cards_against: int
    red_cards_for: int
    red_cards_against: int
    big_chances_created_for: int
    big_chances_created_against: int


@dataclass
class DetailedVenueSplitForm:
    home: VenueSplitStats
    away: VenueSplitStats
    neutral: VenueSplitStats


@dataclass
class FixtureGap:
    opponent: str
    date: Optional[str]
    days_since_previous: Optional[int]


@dataclass
class HalfSplitStats:
    sample_size: int
    first_half_goals_for: int
    first_half_goals_against: int
    second_half_goals_for: int
    second_half_goals_against: int


@dataclass
class StreakInfo:
    result: Literal["W", "D", "L"]
    count: int


@dataclass
class MomentumInfo:
    # PPG, most-recent-3 vs the 3 games before that. >=0.5 ppg swing for
    # "improving"/"declining"; smaller differences are "stable".
    recent_ppg: float
    prior_ppg: float
    trend: Literal["improving", "declining", "stable"]


@dataclass
class CompetitionFormRecord:
    competition: str
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int


@dataclass
class FormSummary:
    last5_overall: list[FormResult]
    last10_overall: list[FormResult]
    last20_overall: list[FormResult]
    last5_home: list[FormResult]
    last5_away: list[FormResult]
    next5_with_gaps: list[FixtureGap]
    gaps_between_last_three: list[int]
    half_split: Optional[HalfSplitStats]
    recent_competitions: list[str]
    current_streak: Optional[StreakInfo]
    home_win_rate_pct: Optional[float]
    away_win_rate_pct: Optional[float]
    momentum: Optional[MomentumInfo]
    # 1-goal margin AND <=3 total goals -- a 1-goal margin alone would also
    # count high-scoring games like 4-3.
    narrow_win_share_pct: Optional[float]
    scoring_draw_share_pct: Optional[float]
    btts_share_pct: Optional[float]
    clean_sheet_streak: Optional[int]
    scoreless_streak: Optional[int]
    over15_share_pct: Optional[float]
    over25_share_pct: Optional[float]
    over35_share_pct: Optional[float]
    clean_sheet_share_pct: Optional[float]
    failed_to_score_share_pct: Optional[float]
    form_by_competition: list[CompetitionFormRecord]
    matches_last7_days: int
    matches_last14_days: int
    venue_split_form: Optional[VenueSplitForm]
    detailed_venue_split: Optional[DetailedVenueSplitForm]
    win_rate_pct: Optional[float]
    draw_rate_pct: Optional[float]
    loss_rate_pct: Optional[float]
    points_per_game: Optional[float]
    goals_for_per_game: Optional[float]
    goals_against_per_game: Optional[float]


@dataclass
class CardDisciplineInfo:
    yellow_per_game: float
    red_per_game: float
    # >2.5 yellow/game or >0.2 red/game -- deliberately conservative
    # "notably above average" cutoff, not a league-specific benchmark.
    elevated_risk: bool


@dataclass
class StandingsZoneInfo:
    position: int
    total_teams: int
    zone: Literal["top-of-table", "midtable", "relegation-zone"]
    # <=6 points from a boundary = "in the mix". Null if we don't have every
    # team's points (standingsTable is Sofascore-only).
    points_from_boundary: Optional[int]
    in_the_mix: Optional[bool]


@dataclass
class RestComparison:
    own_rest_days: Optional[int]
    opponent_rest_days: Optional[int]
    more_rested: Optional[Literal["own", "opponent", "even"]]


@dataclass
class ExperienceComparison:
    own_average_age: Optional[float]
    opponent_average_age: Optional[float]
    # >=1.5 year average-age gap required for "more experienced".
    more_experienced: Optional[Literal["own", "opponent", "even"]]


@dataclass
class SeasonXGEstimate:
    sample_size: int
    xg_for: float
    xg_against: float
    actual_goals_for: int
    actual_goals_against: int
    source: str


@dataclass
class SeasonShotsEstimate:
    sample_size: int
    shots_for: int
    shots_against: int
    shots_on_target_for: int
    shots_on_target_against: int
    source: str


@dataclass
class SeasonCornersEstimate:
    sample_size: int
    corners_for: int
    corners_against: int
    source: str


@dataclass
class SeasonAerialEstimate:
    sample_size: int
    aerial_duels_won_for: int
    aerial_duels_won_against: int
    source: str


@dataclass
class SeasonBigChancesEstimate:
    sample_size: int
    big_chances_created_for: int
    big_chances_created_against: int
    big_chances_missed_for: int
    big_chances_missed_against: int
    source: str


@dataclass
class SeasonPassingStyleEstimate:
    sample_size: int
    total_passes_for: int
    accurate_passes_for: int
    pass_accuracy_pct: Optional[float]
    accurate_long_balls_for: int
    long_ball_share_pct: Optional[float]
    source: str


@dataclass
class SeasonFoulsEstimate:
    sample_size: int
    fouls_committed_for: int
    fouls_committed_against: int
    source: str


@dataclass
class SeasonGoalkeepingEstimate:
    sample_size: int
    saves_for: int
    shots_on_target_faced: int
    save_pct: Optional[float]
    goals_conceded: int
    source: str


@dataclass
class SeasonDefensiveErrorsEstimate:
    sample_size: int
    defensive_errors_for: int
    defensive_errors_against: int
    source: str


@dataclass
class SeasonAdvancedStatsEstimate:
    sample_size: int
    touches_in_box_for: int
    touches_in_box_against: int
    crosses_for: int
    crosses_against: int
    dribbles_for: int
    dribbles_against: int
    through_balls_for: int
    through_balls_against: int
    final_third_entries_for: int
    final_third_entries_against: int
    recoveries_for: int
    recoveries_against: int
    errors_lead_to_shot_for: int
    errors_lead_to_shot_against: int
    errors_lead_to_goal_for: int
    errors_lead_to_goal_against: int
    shots_inside_box_for: int
    shots_inside_box_against: int
    shots_outside_box_for: int
    shots_outside_box_against: int
    shots_off_target_for: int
    shots_off_target_against: int
    blocked_shots_for: int
    blocked_shots_against: int
    offsides_for: int
    offsides_against: int
    big_chances_scored_for: int
    big_chances_scored_against: int
    dispossessed_for: int
    dispossessed_against: int
    team_tackles_for: int
    team_tackles_against: int
    team_interceptions_for: int
    team_interceptions_against: int
    goals_prevented_for: float
    goals_prevented_against: float
    big_saves_for: int
    big_saves_against: int
    high_claims_for: int
    high_claims_against: int
    distance_covered_km_for: float
    distance_covered_km_against: float
    sprints_for: int
    sprints_against: int
    team_clearances_for: int
    team_clearances_against: int
    free_kicks_for: int
    free_kicks_against: int
    xa_for: float
    xa_against: float
    corner_goals_for: int
    corner_goals_against: int
    penalty_goals_for: int
    penalty_goals_against: int
    free_kick_goals_for: int
    free_kick_goals_against: int
    total_shots_for: int
    total_shots_against: int
    shots_on_target_for: int
    shots_on_target_against: int
    corners_for: int
    corners_against: int
    fouls_for: int
    fouls_against: int
    yellow_cards_for: int
    yellow_cards_against: int
    red_cards_for: int
    red_cards_against: int
    possession_pct_avg: Optional[float]
    big_chances_created_for: int
    big_chances_created_against: int
    non_penalty_xg_for: float
    non_penalty_xg_against: float
    set_piece_xg_for: float
    set_piece_xg_against: float
    penalties_awarded_for: int
    penalties_awarded_against: int
    # Share of combined final-third entries that were this team's own --
    # null until at least one match in the sample has both figures.
    field_tilt_pct: Optional[float]
    source: str


@dataclass
class SetPieceThreatFlag:
    corners_per_game: Optional[float]
    opponent_aerial_win_pct: Optional[float]
    # Requires BOTH >=5 corners/game AND opponent losing more aerial duels
    # than they win.
    elevated: bool


@dataclass
class DirectPlayExposureFlag:
    long_ball_share_pct: Optional[float]
    opponent_aerial_win_pct: Optional[float]
    # Requires BOTH >=15% long-ball share AND opponent aerial win rate <50%.
    elevated: bool


@dataclass
class CardDisciplineVenueSplit:
    at_home_sample_size: int
    at_home_yellow_per_game: Optional[float]
    at_home_red_per_game: Optional[float]
    away_sample_size: int
    away_yellow_per_game: Optional[float]
    away_red_per_game: Optional[float]
    source: str


@dataclass
class VenueDetails:
    stadium_name: str
    capacity: Optional[int]
    opened: Optional[int]
    renovated: Optional[str]
    clubs: list[str]
    source_url: str
    # All StadiumDB-only, from the same stadium-page table fetch as
    # capacity/opened/renovated above -- zero extra requests.
    city: Optional[str] = None
    address: Optional[str] = None
    architect: Optional[str] = None
    # Free-text, not split into a number/date/opponent -- StadiumDB's own
    # format varies too much ("61,905 (Liverpool - Wolves 2-1, 02/02/1952)")
    # to parse reliably without guessing at a schema it doesn't publish.
    record_attendance: Optional[str] = None


@dataclass
class TravelInfo:
    """Sofascore only. Distance is COUNTRY-level (capital-to-capital
    great-circle), not venue-to-venue -- no live geocoding is used (see
    geo.py); treat km as a rough order of magnitude."""

    venue_country: Optional[str]
    home_team_country: Optional[str]
    away_team_country: Optional[str]
    home_traveling: Optional[bool]
    away_traveling: Optional[bool]
    home_travel_distance_km: Optional[float]
    away_travel_distance_km: Optional[float]
    home_timezone_diff_hours: Optional[float]
    away_timezone_diff_hours: Optional[float]
    home_travel_time_hours: Optional[float]
    away_travel_time_hours: Optional[float]


@dataclass
class OpponentRankRecord:
    """Record against opponents CURRENTLY ranked higher in the same
    competition -- "currently" is the real caveat: it's each opponent's
    rank as of today, not on the day that result happened."""

    sample_size: int
    wins: int
    draws: int
    losses: int


@dataclass
class PresenceEntry:
    name: str
    status: Literal["P", "A"]
    starting: bool
    # True when named among substitutes (used or unused) -- Sofascore only.
    on_bench: Optional[bool]
    reason: Optional[str]


@dataclass
class RotationInfo:
    """Rotation between the last two played matches (not vs. the upcoming
    match's lineup, which usually isn't published until close to kickoff)."""

    changed_players: int
    starting_xi_size: int
    last_match_date: Optional[str]
    previous_match_date: Optional[str]
    last_formation: Optional[str]
    previous_formation: Optional[str]
    formation_changed: Optional[bool]
    last_defender_count: Optional[int]
    previous_defender_count: Optional[int]
    preceding_result: Optional[Literal["W", "D", "L"]]


@dataclass
class BenchInfo:
    bench_size: int
    bench_total_market_value: Optional[float]
    starting_total_market_value: Optional[float]


@dataclass
class SquadStrengthInfo:
    total_value: Optional[float]
    attack_value: Optional[float]
    midfield_value: Optional[float]
    defense_value: Optional[float]
    goalkeeper_value: Optional[float]
    # total_value minus anyone currently injured or suspended.
    available_value: Optional[float]


@dataclass
class EloRating:
    elo: float
    # Only ClubElo's global-network calibration could ever produce a real
    # world rank -- this project's own computation (elo.py) has no such
    # network to rank against, so this stays None from that path. Left
    # here (rather than dropped) in case a future source populates it.
    rank: Optional[int]
    as_of: str


@dataclass
class OutcomeProbabilities:
    home_win_pct: float
    draw_pct: float
    away_win_pct: float


@dataclass
class MatchPrediction:
    """Three independent methods, shown side by side rather than merged
    into one number, so a reader can see where they agree or disagree
    instead of trusting an opaque blend.

    market_implied: the de-vig implied probability from real bookmaker
    odds (football-data.co.uk's betting_odds, already fetched) --
    research on football prediction consistently finds market odds the
    single strongest standalone predictor, often outperforming home-built
    statistical models outright. None whenever betting_odds itself is
    None (fixture not in a tracked league, or not yet published).

    heuristic_blend: NOT a trained/backtested model -- this project has
    no historical result archive to train or validate one against.
    Computed by prediction.py from each team's own already-computed
    Elo rating (elo.py, recent-form-based) plus a +100 Elo-point home-
    advantage adjustment (a widely-cited approximation from the public
    World Football Elo Ratings system -- not tuned to any specific
    league), converted to three outcome probabilities via the Davidson
    (1970) three-outcome extension of the standard Elo win-probability
    formula, with its draw parameter calibrated to football's commonly-
    cited ~25% average draw rate. Read this as "what a simple, documented
    formula built from signals we already compute says" -- a transparent
    heuristic, not a claim of accuracy comparable to market_implied.
    Also folds in two small, capped, directional heuristic adjustments
    (rest-days differential, available-squad-value differential) -- see
    prediction.py's own doc comment for exactly why those two and not
    others (e.g. head-to-head, discipline, weather), and for the
    real research each is grounded in.

    xg_model: a genuine Poisson goal model (Maher 1982 / the standard
    academic approach Dixon & Coles 1997 refined) using each team's own
    already-computed rolling xG-for/xG-against rates (insights.py's
    SeasonXGEstimate, last 10 finished matches) as the expected-goals
    inputs -- not a heuristic like the other two, an actual statistical
    model of the thing being predicted (goals). None whenever either
    team's xG estimate is unavailable. Deliberately kept free of the
    rest/injury adjustments heuristic_blend applies, so this stays a
    clean, independent read to compare against the other two rather than
    a third copy of the same adjustments."""

    market_implied: Optional[OutcomeProbabilities]
    heuristic_blend: Optional[OutcomeProbabilities]
    xg_model: Optional[OutcomeProbabilities] = None


@dataclass
class ClubStrengthRating:
    overall: float
    attack: float
    defense: float
    # Both from the same table row fetch as overall/attack/defense above --
    # zero extra requests. rank is this club's position in StatsUltra's own
    # flat 480-club global table (not a domestic league rank). Sign is
    # preserved in strength_change (e.g. -0.6 means the rating fell).
    rank: Optional[int] = None
    strength_change: Optional[float] = None


@dataclass
class ResilienceInfo:
    non_win_sample_size: int
    draw_share_pct: float


@dataclass
class PlayerCardRisk:
    """>=4 season yellows is a generic early-warning threshold (many leagues
    suspend at 5 -- "one booking away", not competition-specific)."""

    name: str
    yellow_cards: int
    red_cards: int
    appearances: Optional[int]
    accumulation_risk: bool
    prior_dismissal: bool


@dataclass
class FlaggedPlayer:
    name: str
    side: Literal["home", "away"]
    prior_dismissal: bool


@dataclass
class RefereeCardRiskNote:
    referee_name: str
    yellow_cards_per_game: float
    elevated_card_referee: bool
    flagged_players: list[FlaggedPlayer]


@dataclass
class DuelVulnerability:
    """Squawka only -- defenders whose groundDuelSuccessPct is below 50%."""

    name: str
    ground_duel_success_pct: float


@dataclass
class FullbackExposureInfo:
    """Defenders with above-their-own-team-median chances created AND
    below-55% ground duel success -- uses their own squad as baseline
    rather than a fixed league-wide number."""

    name: str
    chances_created: int
    ground_duel_success_pct: float


@dataclass
class StandingsScenario:
    outcome: Literal["win", "draw", "loss"]
    new_points: int
    new_position: Optional[int]


@dataclass
class StandingsImpactInfo:
    current_position: int
    current_points: int
    scenarios: list[StandingsScenario]


@dataclass
class PossessionMatchupInfo:
    """PPG split by whether the OPPONENT had high possession (>=55%) --
    Goal.com only, last 5 matches with a possession stat available."""

    high_opponent_possession_ppg: Optional[float]
    high_opponent_possession_sample_size: int
    other_ppg: Optional[float]
    other_sample_size: int


@dataclass
class StreakStabilityInfo:
    """Flagged "stable" on a winning streak (>=2 games) with <=2 XI changes
    between the last two matches. Correlation only, not causation."""

    streak_result: Literal["W", "D", "L"]
    streak_count: int
    changed_players: Optional[int]
    stable: Optional[bool]


@dataclass
class LosingStreakContextInfo:
    """Losing streak (>=2 games) + actual goals notably below xG
    (xg_delta <= -1) = an objective "underperforming their own chances"
    signal, not a prediction."""

    streak_count: int
    xg_delta: Optional[float]
    potential_turnaround: Optional[bool]


@dataclass
class HomeAdvantageInfo:
    """>=20pp gap = "strong", 5-20pp = "slight", -5..5pp = "negligible",
    <=-5pp = "reverse" (worse at home than away)."""

    home_win_rate_pct: Optional[float]
    away_win_rate_pct: Optional[float]
    gap_pct: Optional[float]
    strength: Optional[Literal["strong", "slight", "negligible", "reverse"]]


@dataclass
class RestPerformanceInfo:
    """"short" rest is <=3 days. Computed across ALL played matches on
    record, not just the recent-form sample."""

    short_rest_ppg: Optional[float]
    short_rest_sample_size: int
    long_rest_ppg: Optional[float]
    long_rest_sample_size: int


@dataclass
class ExperienceH2HNote:
    more_experienced: Optional[Literal["own", "opponent", "even"]]
    h2h_leader: Optional[Literal["own", "opponent", "even"]]
    aligned: Optional[bool]


@dataclass
class FatigueFlag:
    """Flagged only when BOTH >1 distinct competition in the recent-form
    sample AND an average gap <5 days between the last three matches."""

    multi_competition: bool
    competitions: list[str]
    avg_gap_days: Optional[float]
    flagged: bool


MatchType = Literal["friendly", "competitive"]


@dataclass
class MatchInsights:
    match_type: Optional[MatchType]
    rest_comparison: Optional[RestComparison]
    experience_comparison: Optional[ExperienceComparison]
    home_standings_zone: Optional[StandingsZoneInfo]
    away_standings_zone: Optional[StandingsZoneInfo]
    home_card_discipline: Optional[CardDisciplineInfo]
    away_card_discipline: Optional[CardDisciplineInfo]
    home_card_discipline_venue_split: Optional[CardDisciplineVenueSplit]
    away_card_discipline_venue_split: Optional[CardDisciplineVenueSplit]
    home_xg_estimate: Optional[SeasonXGEstimate]
    away_xg_estimate: Optional[SeasonXGEstimate]
    home_shots_estimate: Optional[SeasonShotsEstimate]
    away_shots_estimate: Optional[SeasonShotsEstimate]
    home_aerial_estimate: Optional[SeasonAerialEstimate]
    away_aerial_estimate: Optional[SeasonAerialEstimate]
    home_big_chances_estimate: Optional[SeasonBigChancesEstimate]
    away_big_chances_estimate: Optional[SeasonBigChancesEstimate]
    home_passing_style: Optional[SeasonPassingStyleEstimate]
    away_passing_style: Optional[SeasonPassingStyleEstimate]
    home_fouls_estimate: Optional[SeasonFoulsEstimate]
    away_fouls_estimate: Optional[SeasonFoulsEstimate]
    home_goalkeeping_estimate: Optional[SeasonGoalkeepingEstimate]
    away_goalkeeping_estimate: Optional[SeasonGoalkeepingEstimate]
    home_set_piece_threat: Optional[SetPieceThreatFlag]
    away_set_piece_threat: Optional[SetPieceThreatFlag]
    home_direct_play_exposure: Optional[DirectPlayExposureFlag]
    away_direct_play_exposure: Optional[DirectPlayExposureFlag]
    travel_info: Optional[TravelInfo]
    home_opponent_rank_record: Optional[OpponentRankRecord]
    away_opponent_rank_record: Optional[OpponentRankRecord]
    home_presence: Optional[list[PresenceEntry]]
    away_presence: Optional[list[PresenceEntry]]
    home_rotation: Optional[RotationInfo]
    away_rotation: Optional[RotationInfo]
    home_resilience: Optional[ResilienceInfo]
    away_resilience: Optional[ResilienceInfo]
    home_rest_performance: Optional[RestPerformanceInfo]
    away_rest_performance: Optional[RestPerformanceInfo]
    experience_h2h: Optional[ExperienceH2HNote]
    home_fatigue_flag: Optional[FatigueFlag]
    away_fatigue_flag: Optional[FatigueFlag]
    home_advantage: Optional[HomeAdvantageInfo]
    away_advantage: Optional[HomeAdvantageInfo]
    home_streak_stability: Optional[StreakStabilityInfo]
    away_streak_stability: Optional[StreakStabilityInfo]
    home_losing_streak_context: Optional[LosingStreakContextInfo]
    away_losing_streak_context: Optional[LosingStreakContextInfo]
    home_card_risks: Optional[list[PlayerCardRisk]]
    away_card_risks: Optional[list[PlayerCardRisk]]
    referee_card_risk_note: Optional[RefereeCardRiskNote]
    home_duel_vulnerabilities: Optional[list[DuelVulnerability]]
    away_duel_vulnerabilities: Optional[list[DuelVulnerability]]
    home_possession_matchup: Optional[PossessionMatchupInfo]
    away_possession_matchup: Optional[PossessionMatchupInfo]
    home_corners_estimate: Optional[SeasonCornersEstimate]
    away_corners_estimate: Optional[SeasonCornersEstimate]
    home_defensive_errors_estimate: Optional[SeasonDefensiveErrorsEstimate]
    away_defensive_errors_estimate: Optional[SeasonDefensiveErrorsEstimate]
    home_fullback_exposure: Optional[list[FullbackExposureInfo]]
    away_fullback_exposure: Optional[list[FullbackExposureInfo]]
    home_standings_impact: Optional[StandingsImpactInfo]
    away_standings_impact: Optional[StandingsImpactInfo]
    home_advanced_stats: Optional[SeasonAdvancedStatsEstimate]
    away_advanced_stats: Optional[SeasonAdvancedStatsEstimate]
    home_bench_info: Optional[BenchInfo]
    away_bench_info: Optional[BenchInfo]
    home_elo_rating: Optional[EloRating]
    away_elo_rating: Optional[EloRating]
    home_squad_strength: Optional[SquadStrengthInfo]
    away_squad_strength: Optional[SquadStrengthInfo]
    home_club_strength: Optional[ClubStrengthRating]
    away_club_strength: Optional[ClubStrengthRating]
    prediction: Optional[MatchPrediction]
    opponent_context_error: Optional[str]
