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
from typing import Literal

Source = Literal["sofascore", "fotmob", "soccerdesk", "goal", "365scores"]
FieldSource = Literal[
    "sofascore", "fotmob", "soccerdesk", "goal", "365scores", "wttr.in",
    "derived", "mixed", "football-data",
]


@dataclass
class MatchInfo:
    source: Source
    source_url: str
    competition: str | None
    home_team: str
    away_team: str
    kickoff_utc: str | None
    venue: str | None
    status: str | None
    home_score: int | None
    away_score: int | None
    # Half-time score, when the source provides it (Sofascore only) -- null
    # for Fotmob and for not-yet-played/in-progress matches.
    home_score_ht: int | None
    away_score_ht: int | None
    # Season label (e.g. "Premier League 25/26") -- Sofascore only.
    season: str | None
    # Matchday/round number within the competition -- Sofascore only, and
    # only for competitions that actually have rounds (league play).
    round: int | None
    # The source's own internal match/event id.
    match_id: str


@dataclass
class TeamSearchResult:
    team: str
    source: Source
    matches: list[MatchInfo]
    error: str | None = None


@dataclass
class LineupPlayer:
    name: str
    position: str | None
    # Sofascore only -- null from every other source.
    substitute: bool | None
    # Minutes actually played -- null (not 0) for an unused substitute, since
    # 0 would wrongly imply "played and recorded 0 minutes" rather than
    # "never came on".
    minutes_played: int | None
    goals: int | None
    assists: int | None
    xg: float | None
    xa: float | None
    shots: int | None
    shots_on_target: int | None
    tackles: int | None
    interceptions: int | None
    fouls: int | None
    rating: float | None
    key_passes: int | None
    # Sofascore and Goal.com only -- confirmed live: no "captain" marker
    # exists anywhere in either source's lineup payload (checked directly,
    # not assumed), so no is_captain field was added here.
    shirt_number: int | None = None
    # Sofascore only, derived from dateOfBirthTimestamp at extraction time
    # (age as of the match, not stored as a birth date).
    age: int | None = None


@dataclass
class TeamStanding:
    position: int
    played: int
    wins: int
    draws: int
    losses: int
    points: int
    # Deliberately str, not int: Sofascore's own scoreDiffFormatted is
    # already a signed string ("+8"/"-9"), and the Android app's
    # TeamStanding.goalDiff (OverviewModels.kt) is declared String
    # specifically to match this field exactly -- changing this to int
    # would be a breaking cross-repo JSON contract change, not a pure
    # Python-side fix. StandingsTableRow.goal_difference (the full-table
    # equivalent, below) is parsed to int instead since it's a newer
    # field with no existing consumer depending on a specific type; the
    # two fields legitimately differ on purpose, not by oversight.
    goal_diff: str
    # Size of the full standings table this position came from -- lets us
    # classify "top of table"/"relegation zone" without guessing a fixed
    # league size.
    total_teams: int | None
    # Numeric twin of goal_diff (same type as StandingsTableRow.
    # goal_difference), derived from it -- so a consumer can compare the
    # two standings shapes without parsing the string; goal_diff itself
    # stays a string for the Android contract above.
    goal_difference: int | None = None

    def __post_init__(self) -> None:
        if self.goal_difference is None:
            try:
                self.goal_difference = int(self.goal_diff)
            except (TypeError, ValueError):
                self.goal_difference = None


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
    detail: str | None
    player: str | None
    team: Literal["home", "away"] | None


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
    win_pct: float | None


@dataclass
class ManagerInfo:
    name: str
    country: str | None
    # From the manager's own Wikipedia page's "Managerial record" table (the
    # row whose "To" column reads "Present"). Null if no such page/row.
    appointed_date: str | None
    # From the CLUB's "List of {Club} managers" Wikipedia page -- the
    # manager immediately before the current one in that table.
    previous_manager: str | None
    # <=90 days old at search time counts as "recent" -- deliberately round,
    # not competition-tuned. Null (not false) whenever appointed_date is
    # null, so "recent" vs "unknown" stay distinguishable.
    recent_appointment: bool | None
    # Same Wikipedia row as appointed_date -- the Played/Won/Drawn/Lost
    # columns already sitting on that row, previously discarded.
    record_at_club: ManagerTenureRecord | None = None
    # Same Wikipedia article page as appointed_date/record_at_club -- the
    # infobox's own "Date of birth", previously unused.
    age: int | None = None


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
    Implied_pct fields are the raw implied probability per outcome
    (100/odds) -- these three do NOT sum to 100%, they sum to the
    overround (see overround_pct below). Fair_pct fields are the
    de-vigged version (each 1/odds share renormalized so the three
    outcomes sum to exactly 100%) -- use those, not implied_pct, for
    anything that needs a real probability distribution."""

    home_win_odds: float | None
    draw_odds: float | None
    away_win_odds: float | None
    home_win_implied_pct: float | None
    draw_implied_pct: float | None
    away_win_implied_pct: float | None
    over_2_5_odds: float | None
    under_2_5_odds: float | None
    # Overround: the bookmaker's margin. Sum of raw implied probabilities
    # (1/odds) before de-vig normalization. >100% means the bookmaker
    # has embedded a margin. 100% = no margin (fair odds).
    overround_pct: float | None = None
    # De-vigged (fair) implied probabilities that sum to exactly 100%
    # after removing the overround. These are the "true" probabilities
    # the market is estimating, before bookmaker margin.
    home_win_fair_pct: float | None = None
    draw_fair_pct: float | None = None
    away_win_fair_pct: float | None = None
    # Same raw-implied/overround/fair treatment as the 1X2 market above,
    # applied to the Over/Under 2.5 goals market -- over_2_5_implied_pct
    # and under_2_5_implied_pct do NOT sum to 100% (they sum to
    # over_under_2_5_overround_pct); use the _fair_pct pair for a real
    # probability distribution.
    over_2_5_implied_pct: float | None = None
    under_2_5_implied_pct: float | None = None
    over_under_2_5_overround_pct: float | None = None
    over_2_5_fair_pct: float | None = None
    under_2_5_fair_pct: float | None = None


@dataclass
class RefereeStats:
    games: int
    yellow_cards: int
    red_cards: int
    # float, not str -- previously js_to_fixed returned a string ("2.5")
    # while every other rate in the report was a float, an asymmetry the
    # Android model mirrored as String. Changed to float for consistency
    # with red_cards_per_game / fouls_per_game / RefereeCardRiskNote's
    # own yellow_cards_per_game (all float).
    yellow_cards_per_game: float
    # From worldfootball.net's competition referee-stats page. Null if the
    # competition isn't in our small tracked mapping, or the name doesn't match.
    penalties_awarded: int | None
    # From football-data.co.uk's per-season CSV, matched by referee surname.
    # Uses last season's file if the current one isn't published yet.
    home_away_bias: RefereeHomeAwayBias | None
    # From refsradar.com's referee profile page ("Fouls/g").
    fouls_per_game: float | None
    # Same refsradar.com profile page, "RED/g" -- a rate, distinct from the
    # raw red_cards count above (which is Sofascore's season total, not a
    # per-game figure). Null under the same conditions as fouls_per_game.
    red_cards_per_game: float | None = None
    # All four from the same refsradar.com fetch as fouls_per_game/
    # red_cards_per_game above -- zero extra requests. Not duplicating
    # refsradar's own "YEL/g" here since yellow_cards_per_game above
    # already covers that concept (Sofascore-sourced instead).
    referee_matches: int | None = None
    penalties_per_game: float | None = None
    cards_per_foul: float | None = None
    avg_total_cards: float | None = None
    # From the same worldfootball.net fetch as penalties_awarded --
    # second-yellow-then-red dismissals specifically, distinct from the
    # straight-red red_cards count above (that column exists on the same
    # table but isn't used here, since Sofascore's season total already
    # covers reds generally).
    second_yellow_cards: int | None = None
    # Source labels: which source provided each non-base field, so a
    # consumer knows where each number came from and can reconcile
    # conflicts (e.g. games from sofascore vs referee_matches from
    # refsradar).
    penalties_source: str | None = None
    home_away_bias_source: str | None = None
    fouls_per_game_source: str | None = None
    red_cards_per_game_source: str | None = None
    referee_matches_source: str | None = None
    penalties_per_game_source: str | None = None
    cards_per_foul_source: str | None = None
    avg_total_cards_source: str | None = None


@dataclass
class WeatherDetail:
    temp_c: float | None
    humidity_pct: float | None
    wind_speed_kmph: float | None
    precip_mm: float | None
    # All wttr.in-only, from the same j1 hourly payload as the four fields
    # above -- zero extra requests. Genuinely relevant to a football match
    # preview (rain risk, gusty conditions affecting aerial play/set
    # pieces), unlike some of the payload's other fields (pressure, UV
    # index) that were left out as not meaningfully match-relevant.
    chance_of_rain_pct: float | None = None
    wind_gust_kmph: float | None = None
    cloud_cover_pct: float | None = None
    feels_like_c: float | None = None
    # True when the venue's country resolved to a real UTC offset and this
    # reading is the wttr.in hourly slot actually closest to true local
    # kickoff time. False means the offset was unknown and this is the
    # older "local midday" same-day approximation instead.
    kickoff_hour_matched: bool = False


@dataclass
class TeamSeasonStats:
    goals_scored: int
    goals_conceded: int
    # Season aggregate as published by the source. Never mutated by form-
    # window reconciliation -- last20 can span the previous season, so a
    # raise from that window can produce impossible stats (e.g. 5 clean
    # sheets beside 8 goals conceded). clean_sheets_recent_check below
    # records the form-window count for comparison only.
    clean_sheets: int
    yellow_cards: int
    red_cards: int
    # Season-to-date average possession as published by the source, until
    # add_possession_venue_split_check reconciles it. When the form-window
    # venue-split average diverges by >5pp, this is replaced with that
    # more recent, match-relevant figure and the original is preserved in
    # average_ball_possession_source_season -- one displayed number, not
    # two that look like a contradiction.
    average_ball_possession: float | None
    # Clean sheets among the competitive matches in form.last20_overall
    # (real results this run actually fetched) -- a DIFFERENT window from
    # season_stats.clean_sheets, kept for comparison only (never used to
    # overwrite the season figure). None when there's no recent form.
    clean_sheets_recent_check: int | None = None
    # How many competitive (non-friendly) results in that same last-20
    # window fed clean_sheets_recent_check -- without this the count alone
    # can look impossible beside a short season sample (e.g. check=5 beside
    # 5 league games / 8 conceded: the form window may be almost all
    # previous-season fixtures). None when there's no recent form.
    clean_sheets_recent_check_sample_size: int | None = None
    # Which source's recent match results fed clean_sheets_recent_check --
    # that count can legitimately swing between two runs of the same team
    # (e.g. Sofascore blocked one run, Fotmob used as a fallback the next,
    # each with its own recent-match sample), same reasoning as EloRating.
    # sample_source; this says why, instead of leaving a swing unexplained.
    clean_sheets_recent_check_source: str | None = None
    # Deprecated / unused: clean_sheets is no longer raised from the form
    # window, so this stays None. Kept for JSON schema stability.
    clean_sheets_source_aggregate: int | None = None
    # Weighted average of detailed_venue_split.possession_pct_avg over the
    # same team's form window (home/away/neutral buckets, n-weighted) --
    # computed for every run with venue-split possession, and used to
    # reconcile average_ball_possession when the gap exceeds 5pp.
    # None when there's no venue-split possession to check against.
    possession_venue_split_check: float | None = None
    possession_venue_split_check_source: str | None = None
    # Pre-reconcile average_ball_possession as the source originally
    # reported it, only set when possession was replaced with the
    # form-window figure. None when no reconciliation happened.
    average_ball_possession_source_season: float | None = None
    # Human-readable note on which window average_ball_possession
    # currently represents and why (set by add_possession_venue_split_check).
    # Field-level companion to dataWindows so a JSON consumer doesn't have
    # to infer the swap rule from presence/absence of source_season alone.
    possession_window_note: str | None = None


@dataclass
class HeadToHeadSummary:
    home_wins: int
    away_wins: int
    draws: int
    # Total matches this summary is based on -- lets consumers know
    # whether this is 3 meetings or 30. Null when the source doesn't
    # publish a total count alongside the W/D/L breakdown.
    sample_size: int | None = None


@dataclass
class MatchStatItem:
    name: str
    home: str
    away: str


@dataclass
class PlayerOfTheMatch:
    name: str
    rating: str | None


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
    date: str | None
    competition: str | None
    scoreline: str
    # "neutral" set only by the deep (Sofascore-based) recent-meetings
    # path in insights.py, when both teams' own countries differ from
    # the match venue's -- confirmed live: a cup final was previously
    # forced into "home"/"away" with no way to represent the truth.
    # Fallback sources (Fotmob/SoccerDesk) can't detect this and still
    # only ever produce "home"/"away".
    #
    # Frame, for every source (final consumer frame after orchestrate's
    # _meetings_in_report_team_frame): "home" means the REPORT/SEARCHED
    # team hosted that past meeting, "away" means the opponent did.
    # Intermediate pipeline stages may briefly use the upcoming fixture's
    # home-team frame; they are normalized before the report is built.
    # home_team/away_team below name who actually hosted.
    venue: Literal["home", "away", "neutral"]
    home_formation: str | None
    away_formation: str | None
    home_xg: float | None
    away_xg: float | None
    home_lineup: list[LineupPlayer] | None
    away_lineup: list[LineupPlayer] | None
    # Who actually played at home/away in THAT meeting (scoreline, xG and
    # formations above are in this same home-first order).
    home_team: str | None = None
    away_team: str | None = None


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
    description: str | None
    expected_return: str | None
    # "injury" / "suspension" / "coach_decision" / "other" (None when there
    # is no description to classify) -- derived from `description`, so a
    # consumer needn't parse the mixed slug/free-text itself, and a
    # non-injury absence (e.g. Richarlison, "coach_decision") isn't read as
    # an injury just because it sits in the missing list. expected_return is
    # left exactly as the source published it for injury/suspension; for
    # coach_decision it is forced to None (a fixed far-future date is not a
    # medical return and reads as a data error).
    absence_type: str | None = None

    def __post_init__(self) -> None:
        if self.absence_type is None:
            self.absence_type = classify_absence(self.description)
        if self.absence_type == "coach_decision":
            self.expected_return = None


_INJURY_WORDS = (
    "injur", "ligament", "fractur", "strain", "sprain", "knee", "ankle", "hamstring", "muscle", "surgery", "illness",
    "concussion", "discomfort", "groin", "calf", "thigh", "foot", "shoulder", "back problem", "virus", "physical",
)


def classify_absence(description: str | None) -> str | None:
    if not description or not description.strip():
        return None
    text = description.lower().replace("_", " ")
    if "suspen" in text or " ban" in f" {text}" or "red card" in text:
        return "suspension"
    if "coach" in text or "not in squad" in text or "tactical" in text:
        return "coach_decision"
    if any(word in text for word in _INJURY_WORDS):
        return "injury"
    return "other"


@dataclass
class MatchDetails(MatchInfo):
    venue_name: str | None
    venue_city: str | None
    venue_country: str | None
    # Sofascore only, from the same event fetch as everything else --
    # lets TravelInfo compute exact venue-to-venue distance instead of the
    # country-capital approximation geo.py otherwise falls back to.
    venue_lat: float | None
    venue_lon: float | None
    referee: str | None
    referee_stats: RefereeStats | None
    attendance: int | None
    weather: str | None
    weather_detail: WeatherDetail | None
    head_to_head_summary: HeadToHeadSummary | None
    head_to_head_streaks: list[str] | None
    # Individual past meetings found within the already-fetched recent-form
    # window (last20Overall) -- NOT an exhaustive career head-to-head.
    # Capped at 3 most recent.
    recent_meetings: list[HeadToHeadMeeting] | None
    home_lineup: list[LineupPlayer] | None
    away_lineup: list[LineupPlayer] | None
    # Named substitutes (used or unused) -- Sofascore only.
    home_bench: list[LineupPlayer] | None
    away_bench: list[LineupPlayer] | None
    home_team_standing: TeamStanding | None
    away_team_standing: TeamStanding | None
    home_team_season_stats: TeamSeasonStats | None
    away_team_season_stats: TeamSeasonStats | None
    match_stats: list[MatchStatItem] | None
    event_timeline: list[TimelineEvent] | None
    # Sofascore only, from its shotmap endpoint. Zeroed (not null) for a
    # not-yet-played match.
    set_piece_goals: SetPieceGoals | None
    shotmap_stats: ShotmapStats | None
    player_of_the_match: PlayerOfTheMatch | None
    home_formation: str | None
    away_formation: str | None
    # null (nothing published) -> false (predicted) -> true (confirmed).
    lineup_confirmed: bool | None
    # Each team's own registered country (not the venue's country) --
    # Sofascore only.
    home_team_country: str | None
    away_team_country: str | None
    home_manager: ManagerInfo | None
    away_manager: ManagerInfo | None
    home_manager_vs_away_club: ManagerClubRecord | None
    away_manager_vs_home_club: ManagerClubRecord | None
    # Full league table for this competition, not just the two teams playing.
    standings_table: list[StandingsTableRow] | None
    # SoccerDesk only.
    home_suspended_players: list[str] | None
    away_suspended_players: list[str] | None
    # Sofascore only, from the same lineups fetch as home_lineup/home_bench
    # -- richer than home_suspended_players/the team profile's injuries
    # list: match-specific, with a reason category and (where published) an
    # expected return date.
    home_missing_players: list[MissingPlayer] | None = None
    away_missing_players: list[MissingPlayer] | None = None
    # Sofascore only, from the same h2h fetch as head_to_head_summary --
    # the actual two-manager head-to-head (both currently in charge of
    # their respective clubs), distinct from ManagerClubRecord (one
    # manager's record against an opponent CLUB across his whole career).
    manager_duel: HeadToHeadSummary | None = None
    # football-data.co.uk only, populated centrally in orchestrate.py
    # (not per-site like the fields above) since it's matched by team
    # name/date against a single shared all-leagues fixtures file, not
    # tied to any one scraper's own match object. This is a cross-
    # bookmaker AVERAGE (football-data.co.uk's own "Avg" columns).
    betting_odds: BettingOdds | None = None
    # Sofascore only, from the same event fetch as everything else above
    # (one extra request, to its /odds/1/all endpoint) -- reuses the same
    # BettingOdds shape as betting_odds above, but this is a SINGLE
    # bookmaker's own price (Sofascore's odds provider "1"), not a
    # cross-bookmaker average, so the two can legitimately disagree.
    # Deliberately kept as a separate field rather than merged/blended
    # into betting_odds: collapsing a single-book price and a market
    # average into one number would hide which kind of price a consumer
    # is looking at.
    sofascore_betting_odds: BettingOdds | None = None
    note: str | None = None
    # Sofascore only, from the same event fetch as venue_name/venue_lat/
    # venue_lon above -- zero extra requests. A separate field from
    # VenueDetails.capacity (StadiumDB) rather than folding into it: this
    # is available whenever Sofascore succeeds even if StadiumDB has no
    # page for the venue at all (confirmed live: several smaller grounds
    # this project has hit aren't in StadiumDB's country listings).
    venue_capacity: int | None = None
    # Each team's OWN home venue coordinates -- distinct from venue_lat/
    # venue_lon above (the CURRENT match's venue, normally the home
    # team's own ground already). Needed to compute the away team's real
    # travel distance instead of the country-level approximation
    # compute_travel_info previously fell back to unconditionally --
    # confirmed live that comparison alone reports 0km for every same-
    # country match regardless of actual distance (Newcastle away at
    # Coventry, ~250km, showed 0). One extra Sofascore fetch per team;
    # None from every other source.
    home_team_venue_lat: float | None = None
    home_team_venue_lon: float | None = None
    away_team_venue_lat: float | None = None
    away_team_venue_lon: float | None = None


@dataclass
class StandingsTableRow:
    team_name: str
    position: int
    points: int
    # Extended standings fields -- not every source provides all of these.
    # Null when the source doesn't publish that column.
    played: int | None = None
    wins: int | None = None
    draws: int | None = None
    losses: int | None = None
    goals_for: int | None = None
    goals_against: int | None = None
    # int here, unlike TeamStanding.goal_diff's str -- see that field's
    # own comment for why the two intentionally differ.
    goal_difference: int | None = None
    form: str | None = None


@dataclass
class SeasonPlayerStats:
    # Optional (not every source has this) -- confirmed live: Fotmob's
    # squad page has real per-player rating/goals/assists/cards for the
    # whole squad, but no appearances count anywhere on that page. Left
    # None rather than guessing, same convention as rating/expected_goals
    # below being Sofascore-only extras.
    appearances: int | None
    goals: int
    assists: int
    yellow_cards: int
    red_cards: int
    # Sofascore-only extras -- null from every other source.
    rating: float | None
    expected_goals: float | None


@dataclass
class DefensiveStats:
    """Squawka only. See squawka.py module doc for which named stats are
    genuinely populated vs. an empty-option trap on that site -- despite
    the name (kept for continuity with chances_created, already a
    non-defensive stat living here), this is really "Squawka's own
    per-player season stats", not strictly defensive ones."""

    tackles_made: int | None
    interceptions: int | None
    ball_recoveries: int | None
    clearances: int | None
    ground_duel_success_pct: float | None
    chances_created: int | None
    # Genuinely new per-player numbers no other source in this project
    # provides (Sofascore/Fotmob's per-player stats don't include shots or
    # pass volume; aerial duels only exists as a team-level estimate
    # elsewhere, not per-player).
    shots: int | None = None
    shots_on_target: int | None = None
    passes_completed: int | None = None
    fouls_won: int | None = None
    aerial_duels_won: int | None = None
    # A second pass over Squawka's own stat-filter labels (confirmed live
    # against the site's own rendered column headers this time, not
    # guessed) found 9 more real, non-empty per-player stats.
    goals_from_inside_box: int | None = None
    goals_from_outside_box: int | None = None
    conversion_rate_pct: float | None = None
    shots_off_target: int | None = None
    passes_attempted: int | None = None
    passing_accuracy_pct: float | None = None
    blocked_shots: int | None = None
    take_ons_completed: int | None = None
    ground_duels_won: int | None = None


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
    avg_rating: float | None
    goals_per_90: float | None
    assists_per_90: float | None
    xg_per_90: float | None
    xa_per_90: float | None
    key_passes_per_90: float | None
    # Starts in the wide slots (right/left of a 4- or 5-man back line) vs
    # the central slots, read from each match's lineup order and formation
    # (Sofascore lists GK, then the back line right-to-left) -- the only
    # fullback-vs-centre-back signal any source gives us, since squad
    # positions are just G/D/M/F. A midfielder-listed player deployed as a
    # full-back (e.g. Archie Gray) counts as a wide back start.
    wide_back_starts: int = 0
    central_back_starts: int = 0


@dataclass
class SquadMember:
    name: str
    role: str | None
    injury: str | None
    age: int | None
    market_value: float | None
    season_stats: SeasonPlayerStats | None
    season_stats_source: Source | None
    defensive_stats: DefensiveStats | None
    recent_usage: PlayerUsagePattern | None
    # Shirt number when the squad source publishes one (Sofascore's
    # /team/{id}/players player.shirtNumber). Null when the source has
    # no shirt field -- never guessed from match lineups alone, since a
    # transfer between seasons would leave a stale number.
    shirt_number: int | None = None
    # Set when season_stats.goals and recent_usage.total_goals disagree
    # for this player (different windows -- season vs last-20). Explains
    # the Gallagher-style 1g vs 2g discrepancy directly on the row instead
    # of leaving the consumer to notice it from two separate leaderboards.
    # None when the numbers match or one side is missing.
    stat_window_note: str | None = None


@dataclass
class TransferRecord:
    player_name: str
    direction: Literal["in", "out"]
    from_club: str | None
    to_club: str | None
    date: str | None


@dataclass
class TeamProfile:
    source: Source
    team_name: str
    squad: list[SquadMember] | None
    average_age: float | None
    injuries: list[SquadMember] | None
    # Ranked by squad market value -- an objective proxy for "key player".
    key_injuries: list[SquadMember] | None
    recent_transfers: list[TransferRecord] | None
    missing_midfielders: list[str] | None
    missing_attackers: list[str] | None
    missing_defenders: list[str] | None
    missing_goalkeepers: list[str] | None
    # Names on missing_*_role that are NOT in injuries (coach_decision /
    # not-in-squad). Explicit field so JSON consumers needn't re-derive
    # the set difference; None when there are none (or no role lists).
    # Populated by orchestrate after reconcile_missing_by_role.
    non_injury_absences: list[str] | None = None


@dataclass
class FormResult:
    opponent: str
    competition: str | None
    date: str | None
    result: Literal["W", "D", "L"]
    scoreline: str
    venue: Literal["home", "away"]
    margin: int
    # Whether this match was played somewhere other than the team's own
    # country despite the fixture data's home/away label. Null until enriched.
    neutral_venue: bool | None
    ht_scoreline: str | None
    xg_for: float | None
    xg_against: float | None


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
    # Every stat field is None when sample_size=0 (no matches in that
    # venue bucket) -- confirmed live: xg/shots/etc previously rendered
    # as literal zeros next to possession_pct_avg=None, a mix of "we
    # checked and it was 0" and "we have no data" in the same row.
    # A zero requires at least one observed match; n=0 is honest nulls
    # across the board. possession_pct_avg was already optional.
    xg_for: float | None
    xg_against: float | None
    shots_for: int | None
    shots_against: int | None
    shots_on_target_for: int | None
    shots_on_target_against: int | None
    possession_pct_avg: float | None
    corners_for: int | None
    corners_against: int | None
    fouls_for: int | None
    fouls_against: int | None
    yellow_cards_for: int | None
    yellow_cards_against: int | None
    red_cards_for: int | None
    red_cards_against: int | None
    big_chances_created_for: int | None
    big_chances_created_against: int | None


@dataclass
class DetailedVenueSplitForm:
    home: VenueSplitStats
    away: VenueSplitStats
    neutral: VenueSplitStats


@dataclass
class FixtureGap:
    opponent: str
    date: str | None
    days_since_previous: int | None


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
    half_split: HalfSplitStats | None
    recent_competitions: list[str]
    current_streak: StreakInfo | None
    home_win_rate_pct: float | None
    away_win_rate_pct: float | None
    momentum: MomentumInfo | None
    # 1-goal margin AND <=3 total goals -- a 1-goal margin alone would also
    # count high-scoring games like 4-3.
    narrow_win_share_pct: float | None
    scoring_draw_share_pct: float | None
    btts_share_pct: float | None
    clean_sheet_streak: int | None
    scoreless_streak: int | None
    over15_share_pct: float | None
    over25_share_pct: float | None
    over35_share_pct: float | None
    clean_sheet_share_pct: float | None
    failed_to_score_share_pct: float | None
    form_by_competition: list[CompetitionFormRecord]
    matches_last7_days: int
    matches_last14_days: int
    venue_split_form: VenueSplitForm | None
    detailed_venue_split: DetailedVenueSplitForm | None
    win_rate_pct: float | None
    draw_rate_pct: float | None
    loss_rate_pct: float | None
    points_per_game: float | None
    goals_for_per_game: float | None
    goals_against_per_game: float | None
    # Sample sizes for computed rate/per-game metrics -- lets consumers
    # know how many matches each percentage/average is derived from.
    home_win_rate_sample_size: int | None = None
    away_win_rate_sample_size: int | None = None
    win_rate_sample_size: int | None = None
    points_per_game_sample_size: int | None = None
    goals_for_per_game_sample_size: int | None = None
    goals_against_per_game_sample_size: int | None = None


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
    points_from_boundary: int | None
    in_the_mix: bool | None


@dataclass
class RestComparison:
    own_rest_days: int | None
    opponent_rest_days: int | None
    more_rested: Literal["own", "opponent", "even"] | None


@dataclass
class ExperienceComparison:
    own_average_age: float | None
    opponent_average_age: float | None
    # >=1.5 year average-age gap required for "more experienced".
    more_experienced: Literal["own", "opponent", "even"] | None


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
    pass_accuracy_pct: float | None
    accurate_long_balls_for: int
    long_ball_share_pct: float | None
    source: str


@dataclass
class SeasonFoulsEstimate:
    sample_size: int
    fouls_committed_for: int
    fouls_committed_against: int
    source: str


@dataclass
class SeasonGoalkeepingEstimate:
    """saves_for comes from the per-match "Keeper saves" stat;
    goals_conceded from the match score; shots_on_target_faced is DERIVED
    at build time as saves_for + goals_conceded (_build_goalkeeping_estimate)
    so the three figures always reconcile arithmetically -- the customer
    reported "25 + 16 = 41 != 40" as a bug even though it was flagged,
    because the flag explained the gap without fixing it. The provider's
    independent "Shots on target" sum can legitimately disagree (own
    goals, provider quirks; confirmed live off by 1 both directions on one
    fixture) and is still used for the shots estimate, but not for this
    dataclass's displayed shots_on_target_faced. save_pct is
    saves_for / shots_on_target_faced with that derived denominator."""

    sample_size: int
    saves_for: int
    shots_on_target_faced: int
    save_pct: float | None
    goals_conceded: int
    source: str
    # shots_on_target_faced - (saves_for + goals_conceded). Stays 0 for
    # normally-built estimates (shots_on_target_faced is derived from the
    # other two, so they reconcile by construction). Still quantifies a
    # gap when a caller constructs this dataclass directly with an
    # independent SOT figure (tests, or a future source that exposes one).
    unreconciled_shots_on_target: int = 0

    def __post_init__(self) -> None:
        self.unreconciled_shots_on_target = self.shots_on_target_faced - (self.saves_for + self.goals_conceded)


@dataclass
class SeasonDefensiveErrorsEstimate:
    sample_size: int
    defensive_errors_for: int
    defensive_errors_against: int
    source: str


@dataclass
class SeasonAdvancedStatsEstimate:
    sample_size: int
    # Names (ADVANCED_STAT_NAMES keys) whose *_for/*_against below are
    # null -- this run's source never reported that stat at all, not "zero
    # of these events happened". None when every stat had data. The paired
    # numeric fields are null for those keys (not structural 0), so JSON
    # consumers don't read a fabricated 0 as real data.
    unavailable_stats: list[str] | None
    touches_in_box_for: int | None
    touches_in_box_against: int | None
    crosses_for: int | None
    crosses_against: int | None
    dribbles_for: int | None
    dribbles_against: int | None
    through_balls_for: int | None
    through_balls_against: int | None
    final_third_entries_for: int | None
    final_third_entries_against: int | None
    recoveries_for: int | None
    recoveries_against: int | None
    errors_lead_to_shot_for: int | None
    errors_lead_to_shot_against: int | None
    errors_lead_to_goal_for: int | None
    errors_lead_to_goal_against: int | None
    shots_inside_box_for: int | None
    shots_inside_box_against: int | None
    shots_outside_box_for: int | None
    shots_outside_box_against: int | None
    shots_off_target_for: int | None
    shots_off_target_against: int | None
    blocked_shots_for: int | None
    blocked_shots_against: int | None
    offsides_for: int | None
    offsides_against: int | None
    big_chances_scored_for: int | None
    big_chances_scored_against: int | None
    dispossessed_for: int | None
    dispossessed_against: int | None
    team_tackles_for: int | None
    team_tackles_against: int | None
    team_interceptions_for: int | None
    team_interceptions_against: int | None
    goals_prevented_for: float | None
    goals_prevented_against: float | None
    big_saves_for: int | None
    big_saves_against: int | None
    high_claims_for: int | None
    high_claims_against: int | None
    distance_covered_km_for: float | None
    distance_covered_km_against: float | None
    sprints_for: int | None
    sprints_against: int | None
    team_clearances_for: int | None
    team_clearances_against: int | None
    free_kicks_for: int | None
    free_kicks_against: int | None
    # Derived from the set-piece event accumulator, not stat_totals --
    # stays a real 0 when the sample simply had no such events.
    xa_for: float
    xa_against: float
    corner_goals_for: int
    corner_goals_against: int
    penalty_goals_for: int
    penalty_goals_against: int
    free_kick_goals_for: int
    free_kick_goals_against: int
    total_shots_for: int | None
    total_shots_against: int | None
    shots_on_target_for: int | None
    shots_on_target_against: int | None
    corners_for: int | None
    corners_against: int | None
    fouls_for: int | None
    fouls_against: int | None
    yellow_cards_for: int | None
    yellow_cards_against: int | None
    red_cards_for: int | None
    red_cards_against: int | None
    possession_pct_avg: float | None
    big_chances_created_for: int | None
    big_chances_created_against: int | None
    # From the set-piece accumulator, not stat_totals -- real 0 when no
    # such events occurred in the sample.
    non_penalty_xg_for: float
    non_penalty_xg_against: float
    set_piece_xg_for: float
    set_piece_xg_against: float
    penalties_awarded_for: int
    penalties_awarded_against: int
    # Share of combined final-third entries that were this team's own --
    # null until at least one match in the sample has both figures.
    field_tilt_pct: float | None
    source: str


@dataclass
class SetPieceThreatFlag:
    corners_per_game: float | None
    opponent_aerial_win_pct: float | None
    # Requires BOTH >=5 corners/game AND opponent losing more aerial duels
    # than they win.
    elevated: bool


@dataclass
class DirectPlayExposureFlag:
    long_ball_share_pct: float | None
    opponent_aerial_win_pct: float | None
    # Requires BOTH >=15% long-ball share AND opponent aerial win rate <50%.
    elevated: bool


@dataclass
class CardDisciplineVenueSplit:
    at_home_sample_size: int
    at_home_yellow_per_game: float | None
    at_home_red_per_game: float | None
    away_sample_size: int
    away_yellow_per_game: float | None
    away_red_per_game: float | None
    source: str


@dataclass
class VenueDetails:
    stadium_name: str
    capacity: int | None
    opened: int | None
    renovated: str | None
    clubs: list[str]
    source_url: str
    # All StadiumDB-only, from the same stadium-page table fetch as
    # capacity/opened/renovated above -- zero extra requests.
    city: str | None = None
    address: str | None = None
    architect: str | None = None
    # Free-text, not split into a number/date/opponent -- StadiumDB's own
    # format varies too much ("61,905 (Liverpool - Wolves 2-1, 02/02/1952)")
    # to parse reliably without guessing at a schema it doesn't publish.
    record_attendance: str | None = None


@dataclass
class TravelInfo:
    """Sofascore only. Distance is COUNTRY-level (capital-to-capital
    great-circle), not venue-to-venue -- no live geocoding is used (see
    geo.py); treat km as a rough order of magnitude."""

    venue_country: str | None
    home_team_country: str | None
    away_team_country: str | None
    home_traveling: bool | None
    away_traveling: bool | None
    home_travel_distance_km: float | None
    away_travel_distance_km: float | None
    home_timezone_diff_hours: float | None
    away_timezone_diff_hours: float | None
    home_travel_time_hours: float | None
    away_travel_time_hours: float | None


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
    on_bench: bool | None
    reason: str | None
    # True for the 11 available players a projection expects to start
    # (see insights.mark_projected_starters) -- NOT a published lineup;
    # `starting` stays False until a real lineup exists.
    projected_starter: bool = False


@dataclass
class RotationInfo:
    """Rotation between the last two played matches (not vs. the upcoming
    match's lineup, which usually isn't published until close to kickoff)."""

    changed_players: int
    starting_xi_size: int
    last_match_date: str | None
    previous_match_date: str | None
    last_formation: str | None
    previous_formation: str | None
    formation_changed: bool | None
    last_defender_count: int | None
    previous_defender_count: int | None
    # Result of the match BEFORE last (not the most recent match) --
    # renamed from "preceding_result" to avoid ambiguity with "the match
    # that precedes" (which sounds like "the last match").
    result_before_last: Literal["W", "D", "L"] | None = None
    # Kept for backward compatibility with existing consumers.
    preceding_result: Literal["W", "D", "L"] | None = None


@dataclass
class BenchInfo:
    bench_size: int
    bench_total_market_value: float | None
    starting_total_market_value: float | None


@dataclass
class SquadStrengthInfo:
    total_value: float | None
    attack_value: float | None
    midfield_value: float | None
    defense_value: float | None
    goalkeeper_value: float | None
    # total_value minus anyone currently injured or suspended.
    available_value: float | None


@dataclass
class EloRating:
    elo: float
    as_of: str
    # Which source's match results this was computed from -- compute_elo_
    # rating uses whatever source succeeded for this team's own recent
    # form (form_source/opponent_context.matches_source), which can
    # legitimately differ run to run (e.g. Sofascore blocked one run,
    # available the next). A genuine source change is the most common
    # reason `elo` jumps between two runs of the same team -- not a bug,
    # but worth being able to tell apart from one.
    sample_source: str | None = None
    # Rank among the teams in the same league table (1 = strongest), NOT
    # a world rank -- ClubElo's global network is gone (see elo.py). Every
    # team in the table is rated the same way (season W/D/L record vs an
    # average opponent, on the Elo scale), so the ranking is like-for-like;
    # rank_basis says exactly that. None when there's no usable table.
    rank: int | None = None
    rank_of: int | None = None
    rank_basis: str | None = None


@dataclass
class OutcomeProbabilities:
    home_win_pct: float
    draw_pct: float
    away_win_pct: float


@dataclass
class ScorelineProbability:
    home_goals: int
    away_goals: int
    probability_pct: float


@dataclass
class GoalMarketProbabilities:
    """Both markets derived from the same independent-Poisson score grid
    xg_model itself uses (see MatchPrediction.xg_model's own doc comment
    for the model's real citation and stated limitations) -- not a
    separate model, just a different summary of the same grid."""

    over_2_5_pct: float
    under_2_5_pct: float
    btts_yes_pct: float
    btts_no_pct: float


@dataclass
class MethodCalibration:
    method: str
    sample_size: int
    brier_score: float
    log_loss: float
    accuracy_pct: float


@dataclass
class CalibrationSummary:
    """How this app's own earlier predictions scored against what actually
    happened -- see calibration.py. Headline numbers are for the blended
    prediction; by_method breaks out each method that had probabilities."""

    evaluated: int
    pending: int
    brier_score: float | None
    brier_skill_vs_uniform_pct: float | None
    log_loss: float | None
    accuracy_pct: float | None
    by_method: list[MethodCalibration]
    note: str


@dataclass
class MatchPrediction:
    """Three independent methods, shown side by side rather than merged
    into one number, so a reader can see where they agree or disagree
    instead of trusting an opaque blend.

    market_implied: the de-vig implied probability from real bookmaker
    odds -- football-data.co.uk's cross-book average when that fixture is
    published, otherwise Sofascore's single-book 1X2 (orchestrate passes
    whichever is available; both share the same fair_pct shape). Research
    on football prediction consistently finds market odds the single
    strongest standalone predictor, often outperforming home-built
    statistical models outright. None only when neither feed has posted
    1X2 for this fixture yet.

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

    market_implied: OutcomeProbabilities | None
    heuristic_blend: OutcomeProbabilities | None
    xg_model: OutcomeProbabilities | None = None
    # Weighted average of all available methods, with confidence based
    # on agreement. Market-implied gets highest weight (research shows
    # it's the strongest standalone predictor), followed by xg_model,
    # then heuristic_blend. confidence is 0-100: agreement across the
    # methods that ran, scaled by how many of the three that is -- two
    # in-house models agreeing closely cannot read as near-certain when
    # the market check never ran.
    blended: OutcomeProbabilities | None = None
    confidence: float | None = None
    # Plain-language basis for `confidence`: it measures only how closely
    # the methods that ran agree with each other (and is scaled by how
    # many ran), NOT real-world accuracy (no outcome archive exists to
    # calibrate against) -- and names any method that could not run,
    # e.g. no market odds this far out.
    confidence_basis: str | None = None
    # "+"-joined names of whichever of market/heuristic/xg contributed
    # (e.g. "heuristic+xg") -- which methods actually ran for THIS match,
    # not a fixed algorithm name (the three methods are three different,
    # independently-documented approaches, not variants of one model).
    model: str | None = None
    # Same xG rates _xg_model_from_estimates already computes internally
    # to run the Poisson model -- exposed directly rather than making a
    # consumer re-derive them from SeasonXGEstimate. None under the same
    # conditions xg_model is None (either team's xG estimate unavailable).
    home_expected_goals: float | None = None
    away_expected_goals: float | None = None
    # Both derived from the same Poisson grid as xg_model -- None under
    # the same conditions xg_model is None. Not part of xg_model itself
    # (that's strictly win/draw/loss) so a consumer that only wants the
    # three headline outcome probabilities isn't forced to also parse
    # these.
    likely_scorelines: list[ScorelineProbability] | None = None
    goal_markets: GoalMarketProbabilities | None = None
    # NOT provided: a calibration/Brier-score/model-accuracy note would
    # require comparing past predictions against actual results, which
    # needs a persistent archive of predictions made and outcomes
    # observed across many prior runs. This project has no such archive
    # by design (see elo.py's own docstring on the identical limitation
    # for its rating) -- every run is stateless. Not a bug to fix; would
    # need new persistent-storage infrastructure, out of scope here.


@dataclass
class ClubStrengthRating:
    overall: float
    attack: float
    defense: float
    # Both from the same table row fetch as overall/attack/defense above --
    # zero extra requests. rank is this club's position in StatsUltra's own
    # flat 480-club global table (not a domestic league rank). Sign is
    # preserved in strength_change (e.g. -0.6 means the rating fell).
    rank: int | None = None
    strength_change: float | None = None


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
    appearances: int | None
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
    new_position: int | None


@dataclass
class StandingsImpactInfo:
    current_position: int
    current_points: int
    scenarios: list[StandingsScenario]


@dataclass
class PossessionMatchupInfo:
    """PPG split by whether the OPPONENT had high possession (>=55%) --
    Goal.com only, last 5 matches with a possession stat available."""

    high_opponent_possession_ppg: float | None
    high_opponent_possession_sample_size: int
    other_ppg: float | None
    other_sample_size: int


@dataclass
class StreakStabilityInfo:
    """Flagged "stable" on a winning streak (>=2 games) with <=2 XI changes
    between the last two matches. Correlation only, not causation."""

    streak_result: Literal["W", "D", "L"]
    streak_count: int
    changed_players: int | None
    stable: bool | None


@dataclass
class LosingStreakContextInfo:
    """Losing streak (>=2 games) + actual goals notably below xG
    (xg_delta <= -1) = an objective "underperforming their own chances"
    signal, not a prediction."""

    streak_count: int
    xg_delta: float | None
    potential_turnaround: bool | None


@dataclass
class HomeAdvantageInfo:
    """>=20pp gap = "strong", 5-20pp = "slight", -5..5pp = "negligible",
    <=-5pp = "reverse" (worse at home than away).

    strength is None when either side's win-rate sample is <3 matches
    (a single home win must not read as "strong" home advantage) --
    confirmed live off a Germany report with home n=1. The rates and gap
    stay populated; the sample sizes are reported alongside so a consumer
    can see exactly why the label was withheld."""

    home_win_rate_pct: float | None
    away_win_rate_pct: float | None
    gap_pct: float | None
    strength: Literal["strong", "slight", "negligible", "reverse"] | None
    home_sample_size: int | None = None
    away_sample_size: int | None = None


@dataclass
class RestPerformanceInfo:
    """"short" rest is <=3 days. Computed across ALL played matches on
    record, not just the recent-form sample."""

    short_rest_ppg: float | None
    short_rest_sample_size: int
    long_rest_ppg: float | None
    long_rest_sample_size: int


@dataclass
class ExperienceH2HNote:
    more_experienced: Literal["own", "opponent", "even"] | None
    h2h_leader: Literal["own", "opponent", "even"] | None
    aligned: bool | None


@dataclass
class FatigueFlag:
    """Flagged only when BOTH >1 distinct competition in the recent-form
    sample AND an average gap <5 days between the last three matches."""

    multi_competition: bool
    competitions: list[str]
    avg_gap_days: float | None
    flagged: bool


MatchType = Literal["friendly", "competitive"]


@dataclass
class MatchInsights:
    match_type: MatchType | None
    rest_comparison: RestComparison | None
    experience_comparison: ExperienceComparison | None
    home_standings_zone: StandingsZoneInfo | None
    away_standings_zone: StandingsZoneInfo | None
    home_card_discipline: CardDisciplineInfo | None
    away_card_discipline: CardDisciplineInfo | None
    home_card_discipline_venue_split: CardDisciplineVenueSplit | None
    away_card_discipline_venue_split: CardDisciplineVenueSplit | None
    home_xg_estimate: SeasonXGEstimate | None
    away_xg_estimate: SeasonXGEstimate | None
    home_shots_estimate: SeasonShotsEstimate | None
    away_shots_estimate: SeasonShotsEstimate | None
    home_aerial_estimate: SeasonAerialEstimate | None
    away_aerial_estimate: SeasonAerialEstimate | None
    home_big_chances_estimate: SeasonBigChancesEstimate | None
    away_big_chances_estimate: SeasonBigChancesEstimate | None
    home_passing_style: SeasonPassingStyleEstimate | None
    away_passing_style: SeasonPassingStyleEstimate | None
    home_fouls_estimate: SeasonFoulsEstimate | None
    away_fouls_estimate: SeasonFoulsEstimate | None
    home_goalkeeping_estimate: SeasonGoalkeepingEstimate | None
    away_goalkeeping_estimate: SeasonGoalkeepingEstimate | None
    home_set_piece_threat: SetPieceThreatFlag | None
    away_set_piece_threat: SetPieceThreatFlag | None
    home_direct_play_exposure: DirectPlayExposureFlag | None
    away_direct_play_exposure: DirectPlayExposureFlag | None
    travel_info: TravelInfo | None
    home_opponent_rank_record: OpponentRankRecord | None
    away_opponent_rank_record: OpponentRankRecord | None
    home_presence: list[PresenceEntry] | None
    away_presence: list[PresenceEntry] | None
    home_rotation: RotationInfo | None
    away_rotation: RotationInfo | None
    home_resilience: ResilienceInfo | None
    away_resilience: ResilienceInfo | None
    home_rest_performance: RestPerformanceInfo | None
    away_rest_performance: RestPerformanceInfo | None
    experience_h2h: ExperienceH2HNote | None
    home_fatigue_flag: FatigueFlag | None
    away_fatigue_flag: FatigueFlag | None
    home_advantage: HomeAdvantageInfo | None
    away_advantage: HomeAdvantageInfo | None
    home_streak_stability: StreakStabilityInfo | None
    away_streak_stability: StreakStabilityInfo | None
    home_losing_streak_context: LosingStreakContextInfo | None
    away_losing_streak_context: LosingStreakContextInfo | None
    home_card_risks: list[PlayerCardRisk] | None
    away_card_risks: list[PlayerCardRisk] | None
    referee_card_risk_note: RefereeCardRiskNote | None
    home_duel_vulnerabilities: list[DuelVulnerability] | None
    away_duel_vulnerabilities: list[DuelVulnerability] | None
    home_possession_matchup: PossessionMatchupInfo | None
    away_possession_matchup: PossessionMatchupInfo | None
    home_corners_estimate: SeasonCornersEstimate | None
    away_corners_estimate: SeasonCornersEstimate | None
    home_defensive_errors_estimate: SeasonDefensiveErrorsEstimate | None
    away_defensive_errors_estimate: SeasonDefensiveErrorsEstimate | None
    home_fullback_exposure: list[FullbackExposureInfo] | None
    away_fullback_exposure: list[FullbackExposureInfo] | None
    home_standings_impact: StandingsImpactInfo | None
    away_standings_impact: StandingsImpactInfo | None
    home_advanced_stats: SeasonAdvancedStatsEstimate | None
    away_advanced_stats: SeasonAdvancedStatsEstimate | None
    home_bench_info: BenchInfo | None
    away_bench_info: BenchInfo | None
    home_elo_rating: EloRating | None
    away_elo_rating: EloRating | None
    home_squad_strength: SquadStrengthInfo | None
    away_squad_strength: SquadStrengthInfo | None
    home_club_strength: ClubStrengthRating | None
    away_club_strength: ClubStrengthRating | None
    prediction: MatchPrediction | None
    opponent_context_error: str | None
    # How PresenceEntry.projected_starter was chosen; None when no
    # projection was made (a real lineup is out, or no usage history).
    projected_xi_basis: str | None = None
    # Set when home_squad_strength/away_squad_strength's market values came
    # from two DIFFERENT sources (e.g. one team's own Sofascore search
    # failed, so its squad fell back to Fotmob) -- each source runs its own
    # valuation model, not just a currency difference, so the two totals
    # are not directly comparable or summable. None when both came from
    # the same source, or when either squad strength is unavailable.
    squad_value_basis_note: str | None = None

    # Set when the same side's corners_for disagrees between
    # home/away_advanced_stats (form-source detail window) and
    # home/away_corners_estimate (Goal.com Corner total) -- different
    # sources and sample windows, both correct for their own window.
    # None when they agree or either figure is unavailable.
    corners_cross_source_note: str | None = None
