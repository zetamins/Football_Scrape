from dataclasses import fields as _dc_fields

from football.format_markdown import (
    _lineup_label,
    form_summary_markdown,
    insights_markdown,
    losing_streak_context_str,
    merged_match_markdown,
    merged_profile_markdown,
    prediction_str,
    rest_label,
    slugify,
    standings_impact_str,
    streak_stability_str,
    zone_str,
)
from football.types import MatchPrediction, OutcomeProbabilities


def _all_none(cls, **overrides):
    base = {f.name: None for f in _dc_fields(cls)}
    base.update(overrides)
    return cls(**base)


def _probs(home, draw, away):
    return OutcomeProbabilities(home_win_pct=home, draw_pct=draw, away_win_pct=away)


def _manager(**overrides):
    from football.types import ManagerInfo

    base = {"name": "Some Manager", "country": None, "appointed_date": None, "recent_appointment": None, "previous_manager": None, "record_at_club": None, "age": None}
    base.update(overrides)
    return ManagerInfo(**base)


def _meeting(**overrides):
    from football.types import HeadToHeadMeeting

    base = {
        "date": "2026-01-01T00:00:00.000Z", "competition": "Premier League", "scoreline": "1-0", "venue": "home",
        "home_formation": None, "away_formation": None, "home_xg": None, "away_xg": None, "home_lineup": None, "away_lineup": None,
    }
    base.update(overrides)
    return HeadToHeadMeeting(**base)


def _form_result(**overrides):
    from football.types import FormResult

    base = {
        "opponent": "Rival FC", "competition": "Premier League", "date": "2026-01-01T00:00:00.000Z", "result": "W",
        "scoreline": "2-1", "venue": "home", "margin": 1, "neutral_venue": None, "ht_scoreline": None, "xg_for": None, "xg_against": None,
    }
    base.update(overrides)
    return FormResult(**base)


def _form_summary_full(**overrides):
    from football.types import FormSummary

    base = {
        "last5_overall": [], "last10_overall": [], "last20_overall": [], "last5_home": [], "last5_away": [],
        "next5_with_gaps": [], "gaps_between_last_three": [], "half_split": None, "recent_competitions": [],
        "current_streak": None, "home_win_rate_pct": None, "away_win_rate_pct": None, "momentum": None,
        "narrow_win_share_pct": None, "scoring_draw_share_pct": None, "btts_share_pct": None,
        "clean_sheet_streak": None, "scoreless_streak": None, "over15_share_pct": None, "over25_share_pct": None,
        "over35_share_pct": None, "clean_sheet_share_pct": None, "failed_to_score_share_pct": None,
        "form_by_competition": [], "matches_last7_days": 0, "matches_last14_days": 0, "venue_split_form": None,
        "detailed_venue_split": None, "win_rate_pct": None, "draw_rate_pct": None, "loss_rate_pct": None,
        "points_per_game": None, "goals_for_per_game": None, "goals_against_per_game": None,
    }
    base.update(overrides)
    return FormSummary(**base)


def test_market_implied_labeled_as_primary_when_both_available():
    p = MatchPrediction(market_implied=_probs(60, 25, 15), heuristic_blend=_probs(55, 25, 20))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert "primary" in lines[0]
    assert "not a trained model" in lines[1]
    assert "no market odds" not in lines[1]


def test_heuristic_notes_it_is_the_only_estimate_when_no_market_odds():
    p = MatchPrediction(market_implied=None, heuristic_blend=_probs(55, 25, 20))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 1
    assert "no market odds available" in lines[0]


def test_single_method_prediction_shows_explicit_confidence_na():
    # _blend_predictions returns (None, None) under two methods -- without
    # this branch readers couldn't tell "confident" from "only one estimate".
    p = MatchPrediction(market_implied=_probs(60, 25, 15), heuristic_blend=None, model="market")
    lines = prediction_str(p, "Home FC", "Away FC")
    assert any("Confidence: n/a" in line for line in lines)
    assert any("single method" in line for line in lines)


def test_flags_disagreement_when_methods_favor_different_sides():
    # Market favors home, heuristic favors away.
    p = MatchPrediction(market_implied=_probs(50, 20, 30), heuristic_blend=_probs(35, 25, 40))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 3
    assert "disagree" in lines[2]


def test_flags_disagreement_when_same_side_favored_but_gap_exceeds_15_points():
    p = MatchPrediction(market_implied=_probs(71.7, 17.4, 10.9), heuristic_blend=_probs(49.2, 24.1, 26.6))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 3
    assert "disagree" in lines[2]


def test_no_disagreement_note_when_methods_roughly_agree():
    p = MatchPrediction(market_implied=_probs(52, 26, 22), heuristic_blend=_probs(48, 27, 25))
    lines = prediction_str(p, "Home FC", "Away FC")
    assert len(lines) == 2


# --- slugify / _lineup_label / rest_label ----------------------------------------


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Real Madrid CF") == "real-madrid-cf"


def test_slugify_strips_leading_and_trailing_hyphens():
    assert slugify("!Arsenal!") == "arsenal"


def test_lineup_label_confirmed_vs_predicted_vs_unknown():
    assert _lineup_label(True) == "lineup (confirmed)"
    assert _lineup_label(False) == "expected lineup (predicted, not confirmed)"
    assert _lineup_label(None) == "lineup"


def test_lineup_label_derived_side_says_projected_not_published():
    sources = {"home_lineup": "derived", "away_lineup": "sofascore"}
    assert _lineup_label(None, sources, "home_lineup") == "projected lineup (derived, not published)"
    assert _lineup_label(None, sources, "away_lineup") == "lineup"
    assert _lineup_label(True, sources, "home_lineup") == "projected lineup (derived, not published)"


def test_rest_label_short_rest_threshold():
    assert rest_label(3) == " (short rest)"
    assert rest_label(4) == ""
    assert rest_label(None) == ""


# --- zone_str ----------------------------------------------------------------------


def test_zone_str_includes_in_the_mix_note():
    from football.types import StandingsZoneInfo

    z = StandingsZoneInfo(position=10, total_teams=20, zone="midtable", points_from_boundary=4, in_the_mix=True)
    result = zone_str(z, "Home")
    assert "in the mix" in result
    assert "#10/20" in result


def test_zone_str_omits_stakes_without_boundary_data():
    from football.types import StandingsZoneInfo

    z = StandingsZoneInfo(position=1, total_teams=20, zone="top-of-table", points_from_boundary=None, in_the_mix=None)
    result = zone_str(z, "Home")
    assert "pts from" not in result


# --- streak_stability_str -----------------------------------------------------------


def test_streak_stability_str_short_streak_ignores_stability_fields():
    from football.types import StreakStabilityInfo

    s = StreakStabilityInfo(streak_result="L", streak_count=3, changed_players=None, stable=None)
    result = streak_stability_str(s, "Home")
    assert "losing run" in result


def test_streak_stability_str_stable_win_streak():
    from football.types import StreakStabilityInfo

    s = StreakStabilityInfo(streak_result="W", streak_count=3, changed_players=1, stable=True)
    result = streak_stability_str(s, "Home")
    assert "stable XI" in result
    assert "1 changes" in result


def test_streak_stability_str_rotated_win_streak():
    from football.types import StreakStabilityInfo

    s = StreakStabilityInfo(streak_result="W", streak_count=4, changed_players=5, stable=False)
    result = streak_stability_str(s, "Home")
    assert "rotated XI" in result


def test_streak_stability_str_drawing_run():
    from football.types import StreakStabilityInfo

    s = StreakStabilityInfo(streak_result="D", streak_count=2, changed_players=None, stable=None)
    assert "drawing run" in streak_stability_str(s, "Home")


# --- losing_streak_context_str -------------------------------------------------------


def test_losing_streak_context_str_potential_turnaround():
    from football.types import LosingStreakContextInfo

    losing = LosingStreakContextInfo(streak_count=3, xg_delta=-1.5, potential_turnaround=True)
    result = losing_streak_context_str(losing, "Home FC")
    assert "-1.5 actual-vs-xG" in result
    assert "potential turnaround" in result


def test_losing_streak_context_str_positive_delta_gets_plus_sign():
    from football.types import LosingStreakContextInfo

    losing = LosingStreakContextInfo(streak_count=2, xg_delta=0.5, potential_turnaround=False)
    result = losing_streak_context_str(losing, "Home FC")
    assert "+0.5" in result
    assert "potential turnaround" not in result


def test_losing_streak_context_str_unavailable_xg():
    from football.types import LosingStreakContextInfo

    losing = LosingStreakContextInfo(streak_count=2, xg_delta=None, potential_turnaround=None)
    assert "xG data unavailable" in losing_streak_context_str(losing, "Home FC")


def test_insights_markdown_skips_losing_streak_sentinel_with_zero_count():
    from football.types import LosingStreakContextInfo

    sentinel = LosingStreakContextInfo(streak_count=0, xg_delta=None, potential_turnaround=None)
    insights = _insights_full(home_losing_streak_context=sentinel, away_losing_streak_context=sentinel)
    lines: list[str] = []
    insights_markdown(insights, "Home FC", "Away FC", lines)
    text = "\n".join(lines)
    assert "losing streak context" not in text


def test_insights_markdown_renders_losing_streak_when_count_positive():
    insights = _insights_full()
    lines: list[str] = []
    insights_markdown(insights, "Home FC", "Away FC", lines)
    text = "\n".join(lines)
    assert "Home FC losing streak context" in text


# --- standings_impact_str ------------------------------------------------------------


def test_standings_impact_str_shows_up_down_and_no_change_arrows():
    from football.types import StandingsImpactInfo, StandingsScenario

    s = StandingsImpactInfo(
        current_position=5, current_points=20,
        scenarios=[
            StandingsScenario(outcome="win", new_points=23, new_position=3),
            StandingsScenario(outcome="draw", new_points=21, new_position=5),
            StandingsScenario(outcome="loss", new_points=20, new_position=7),
        ],
    )
    result = standings_impact_str(s, "Home")
    assert "win: #3 (up 2)" in result
    assert "draw: #5 (no change)" in result
    assert "loss: #7 (down 2)" in result


def test_standings_impact_str_handles_unknown_new_position():
    from football.types import StandingsImpactInfo, StandingsScenario

    s = StandingsImpactInfo(current_position=5, current_points=20, scenarios=[StandingsScenario(outcome="win", new_points=23, new_position=None)])
    result = standings_impact_str(s, "Home")
    assert "win: #?" in result


# --- broad integration: exercises many small formatters through real code paths ----


def test_merged_match_markdown_renders_a_populated_match_without_error():
    from football.merge import MergedMatch

    d = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished", kickoff_utc="2026-01-01T15:00:00.000Z",
        competition="Premier League", venue_name="Home Stadium", referee="Some Ref", additional_notes=[], field_sources={},
        home_score=2, away_score=1, note="A note",
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "Home FC vs Away FC" in text
    assert "Premier League" in text
    assert "Some Ref" in text


def test_merged_profile_markdown_renders_a_populated_profile_without_error():
    from football.merge import MergedProfile

    p = _all_none(MergedProfile, source="sofascore", team_name="Home FC", squad=None, field_sources={})
    lines: list[str] = []
    merged_profile_markdown(p, lines)
    # squad=None -- should render without raising even with nothing to show.


def test_insights_markdown_renders_a_populated_insights_object_without_error():
    from football.types import MatchInsights

    insights = _all_none(MatchInsights, match_type="competitive")
    lines: list[str] = []
    insights_markdown(insights, "Home FC", "Away FC", lines)
    assert any("competitive" in line for line in lines)


# --- direct unit tests for every remaining *_str formatter -------------------------------


def test_transfer_str_includes_clubs_and_date():
    from football.format_markdown import transfer_str
    from football.types import TransferRecord

    t = TransferRecord(player_name="Some Player", direction="in", from_club="Club A", to_club="Club B", date="2026-01-15T00:00:00.000Z")
    result = transfer_str(t)
    assert "Some Player" in result
    assert "Club A -> Club B" in result
    assert "2026-01-15" in result


def test_transfer_str_omits_clubs_and_date_when_missing():
    from football.format_markdown import transfer_str
    from football.types import TransferRecord

    t = TransferRecord(player_name="Some Player", direction="out", from_club=None, to_club=None, date=None)
    result = transfer_str(t)
    assert result == "Some Player (out)"


def test_form_result_str_includes_ht_xg_and_narrow_flag():
    from football.format_markdown import form_result_str
    from football.types import FormResult

    r = FormResult(opponent="Rival", competition="Premier League", date="2026-01-01T00:00:00.000Z", result="W", scoreline="2-1", venue="home", margin=1, neutral_venue=None, ht_scoreline="1-0", xg_for=1.8, xg_against=0.9)
    result = form_result_str(r)
    assert "HT 1-0" in result
    assert "xG 1.8-0.9" in result
    assert "(narrow)" in result


def test_meeting_str_includes_xg_and_formations():
    from football.format_markdown import meeting_str
    from football.types import HeadToHeadMeeting

    m = HeadToHeadMeeting(date="2026-01-01T00:00:00.000Z", competition="Premier League", scoreline="2-1", venue="home", home_formation="4-3-3", away_formation="4-4-2", home_xg=1.5, away_xg=0.8, home_lineup=None, away_lineup=None)
    result = meeting_str(m)
    assert "4-3-3 v 4-4-2" in result
    assert "xG 1.5-0.8" in result


def test_meeting_str_handles_missing_date():
    from football.format_markdown import meeting_str
    from football.types import HeadToHeadMeeting

    m = _all_none(HeadToHeadMeeting, date=None, competition="Premier League", scoreline="1-0", venue="home")
    assert meeting_str(m).startswith("? ")


def test_half_split_str_formats_both_halves():
    from football.format_markdown import half_split_str
    from football.types import HalfSplitStats

    h = HalfSplitStats(sample_size=5, first_half_goals_for=3, first_half_goals_against=1, second_half_goals_for=4, second_half_goals_against=2)
    assert half_split_str(h) == "1H 3-1, 2H 4-2 (n=5)"


def test_competition_form_str_formats_record():
    from football.format_markdown import competition_form_str
    from football.types import CompetitionFormRecord

    c = CompetitionFormRecord(competition="FA Cup", played=5, wins=3, draws=1, losses=1, goals_for=8, goals_against=4)
    assert competition_form_str(c) == "FA Cup 3W-1D-1L, 8-4 goals"


def test_venue_split_form_str_includes_all_three_buckets():
    from football.format_markdown import venue_split_form_str
    from football.types import VenueSplitForm

    v = VenueSplitForm(
        home_sample_size=5, home_wins=3, home_draws=1, home_losses=1, home_goals_for=8, home_goals_against=4,
        away_sample_size=5, away_wins=2, away_draws=1, away_losses=2, away_goals_for=6, away_goals_against=7,
        neutral_sample_size=1, neutral_wins=1, neutral_draws=0, neutral_losses=0, neutral_goals_for=2, neutral_goals_against=0,
    )
    result = venue_split_form_str(v)
    assert "home 3W-1D-1L" in result
    assert "away 2W-1D-2L" in result
    assert "neutral 1W-0D-0L" in result


def _venue_bucket(**overrides):
    from football.types import VenueSplitStats

    base = {
        "sample_size": 5, "xg_for": 7.5, "xg_against": 5.0, "shots_for": 50, "shots_against": 40,
        "shots_on_target_for": 20, "shots_on_target_against": 15, "possession_pct_avg": 55.0,
        "corners_for": 25, "corners_against": 20, "fouls_for": 40, "fouls_against": 35,
        "yellow_cards_for": 10, "yellow_cards_against": 8, "red_cards_for": 1, "red_cards_against": 0,
        "big_chances_created_for": 15, "big_chances_created_against": 10,
    }
    base.update(overrides)
    return VenueSplitStats(**base)


def test_venue_bucket_str_computes_per_game_rates():
    from football.format_markdown import venue_bucket_str

    result = venue_bucket_str(_venue_bucket())
    assert "n=5" in result
    assert "55.0%" in result


def test_venue_bucket_str_zero_sample_size():
    from football.format_markdown import venue_bucket_str

    assert venue_bucket_str(_venue_bucket(sample_size=0)) == "n=0"


def test_detailed_venue_split_str_includes_all_three_buckets():
    from football.format_markdown import detailed_venue_split_str
    from football.types import DetailedVenueSplitForm

    d = DetailedVenueSplitForm(home=_venue_bucket(), away=_venue_bucket(), neutral=_venue_bucket(sample_size=0))
    result = detailed_venue_split_str(d)
    assert "home:" in result
    assert "away:" in result
    assert "neutral: n=0" in result


def test_referee_stats_str_includes_all_optional_parts():
    from football.format_markdown import referee_stats_str
    from football.types import RefereeHomeAwayBias, RefereeStats

    rs = RefereeStats(
        games=20, yellow_cards=60, red_cards=3, yellow_cards_per_game=3.0,
        penalties_awarded=5, home_away_bias=RefereeHomeAwayBias(sample_size=20, home_cards_per_game=2.5, away_cards_per_game=3.5),
        fouls_per_game=22.0, red_cards_per_game=0.15, referee_matches=20, penalties_per_game=0.25,
        cards_per_foul=0.14, avg_total_cards=4.5, second_yellow_cards=2,
    )
    result = referee_stats_str(rs)
    assert "5 penalties this season" in result
    assert "2 second-yellow dismissals" in result
    assert "home 2.5 vs away 3.5 cards/game" in result
    assert "22.0 fouls/game" in result


def test_referee_stats_str_minimal_fields_only():
    from football.format_markdown import referee_stats_str
    from football.types import RefereeStats

    rs = RefereeStats(games=10, yellow_cards=20, red_cards=1, yellow_cards_per_game=2.0, penalties_awarded=None, home_away_bias=None, fouls_per_game=None)
    result = referee_stats_str(rs)
    assert result == "10 games, 20 yellow / 1 red, 2.0 yellow/game"


def test_manager_str_unknown_without_manager():
    from football.format_markdown import manager_str

    assert manager_str(None) == "unknown"


def test_manager_str_includes_all_parts():
    from football.format_markdown import manager_str

    m = _manager(name="Some Boss", country="England", appointed_date="2020-01-01T00:00:00.000Z", recent_appointment=True, previous_manager="Old Boss")
    result = manager_str(m)
    assert "Some Boss (England)" in result
    assert "appointed 2020-01-01" in result
    assert "recent managerial change" in result
    assert "previously Old Boss" in result


def test_performer_str_goals_and_assists():
    from football.format_markdown import performer_str
    from football.merge import TopPerformer

    t = TopPerformer(name="Star Player", goals=10, assists=5, appearances=20, rating=7.35, source="sofascore")
    result = performer_str(t)
    assert "10g/5a" in result
    assert "in 20 apps" in result
    assert "7.35 avg rating" in result


def test_performer_str_goals_only_omits_apps():
    from football.format_markdown import performer_str
    from football.merge import TopPerformer

    t = TopPerformer(name="Striker", goals=8, assists=0, appearances=None, rating=None, source="sofascore")
    result = performer_str(t)
    assert result == "Striker (8g)"


def test_performer_str_assists_only():
    from football.format_markdown import performer_str
    from football.merge import TopPerformer

    t = TopPerformer(name="Playmaker", goals=0, assists=3, appearances=None, rating=None, source="sofascore")
    assert performer_str(t) == "Playmaker (3a)"


def test_defender_str_formats_tackles_and_interceptions():
    from football.format_markdown import defender_str
    from football.merge import TopDefender

    d = TopDefender(name="Some CB", tackles_made=5, interceptions=3)
    assert defender_str(d) == "Some CB (5 tackles, 3 interceptions)"


def test_bench_regular_str_formats_all_counts():
    from football.format_markdown import bench_regular_str
    from football.merge import BenchRegular

    b = BenchRegular(name="Sub Player", matches_in_squad=10, starts=2, sub_appearances=5, unused_bench=3)
    assert bench_regular_str(b) == "Sub Player (2 starts, 5 sub apps, 3 unused, of 10)"


def test_recent_form_leader_str_includes_per90_and_key_passes():
    from football.format_markdown import recent_form_leader_str
    from football.merge import RecentFormLeader

    r = RecentFormLeader(name="Winger", goals=4, assists=3, xg=3.5, xa=2.1, avg_rating=7.6, goals_per90=0.5, assists_per90=0.3, key_passes=12, sample_size=10)
    result = recent_form_leader_str(r)
    assert "0.5g/0.3a per 90" in result
    assert "12 key passes" in result
    assert "n=10" in result


def test_role_form_entry_str_formats_minutes_and_stats():
    from football.format_markdown import role_form_entry_str
    from football.merge import RoleFormEntry

    r = RoleFormEntry(name="Midfielder", matches_in_squad=10, starts=8, total_minutes=720, goals=2, assists=4, xg=1.5, xa=3.2, key_passes=20, avg_rating=7.1)
    result = role_form_entry_str(r)
    assert "720min in 10 (8 starts)" in result
    assert "20 key passes" in result


def test_venue_details_markdown_includes_optional_fields():
    from football.format_markdown import venue_details_markdown
    from football.types import VenueDetails

    v = VenueDetails(
        stadium_name="Some Arena", capacity=60000, opened=1990, renovated="2010", clubs=["Some FC"],
        source_url="https://x", city="Somewhere", address="123 Main St", architect="Some Architect",
        record_attendance="70,000 (1995)",
    )
    lines: list[str] = []
    venue_details_markdown(v, lines)
    text = "\n".join(lines)
    assert "Some Arena" in text
    assert "capacity 60,000" in text
    assert "Address: 123 Main St" in text
    assert "Design: Some Architect" in text
    assert "Record attendance: 70,000 (1995)" in text


def test_venue_details_markdown_names_the_capacity_source_when_sources_conflicted():
    from football.format_markdown import venue_details_markdown
    from football.merge import SourceConflict, SourceValue
    from football.types import VenueDetails

    v = VenueDetails(
        stadium_name="Old Trafford", capacity=74244, opened=1910, renovated=None, clubs=["Manchester United"],
        source_url="https://x", city="Manchester", address=None, architect=None, record_attendance=None,
    )
    conflicts = [SourceConflict("venue_capacity", 74244, "stadiumdb", [SourceValue("sofascore", 74879)], "StadiumDB preferred")]
    lines: list[str] = []
    venue_details_markdown(v, lines, conflicts)
    text = "\n".join(lines)
    assert "capacity 74,244 (stadiumdb preferred over sofascore 74,879)" in text


def test_elo_str_never_mentions_a_world_rank():
    """EloRating has no rank field -- this project's own Elo computation
    has no cross-team network to rank against (see elo.py), unlike
    ClubStrengthRating's separate, genuinely-populated StatsUltra rank."""
    from football.format_markdown import elo_str
    from football.types import EloRating

    e = EloRating(elo=1650.5, as_of="2026-01-01")
    result = elo_str(e, "Home")
    assert "world rank" not in result
    assert "1650.5" in result


def test_club_strength_str_includes_positive_change():
    from football.format_markdown import club_strength_str
    from football.types import ClubStrengthRating

    s = ClubStrengthRating(overall=85.2, attack=80.0, defense=75.0, rank=3, strength_change=1.2)
    result = club_strength_str(s, "Home")
    assert "StatsUltra global rank #3 of ~480 clubs" in result
    assert "+1.2 vs last check" in result


def test_club_strength_str_negative_change_no_plus_sign():
    from football.format_markdown import club_strength_str
    from football.types import ClubStrengthRating

    s = ClubStrengthRating(overall=70.0, attack=65.0, defense=60.0, rank=None, strength_change=-0.6)
    result = club_strength_str(s, "Home")
    assert ", -0.6 vs last check" in result
    assert "global rank" not in result
    assert "StatsUltra global rank" not in result


def test_card_str_flags_elevated_risk():
    from football.format_markdown import card_str
    from football.types import CardDisciplineInfo

    c = CardDisciplineInfo(yellow_per_game=3.0, red_per_game=0.3, elevated_risk=True)
    assert "(elevated risk)" in card_str(c, "Home")


def test_card_str_no_flag_when_not_elevated():
    from football.format_markdown import card_str
    from football.types import CardDisciplineInfo

    c = CardDisciplineInfo(yellow_per_game=1.5, red_per_game=0.05, elevated_risk=False)
    assert "(elevated risk)" not in card_str(c, "Home")


def test_card_discipline_venue_split_str_both_sides_populated():
    from football.format_markdown import card_discipline_venue_split_str
    from football.types import CardDisciplineVenueSplit

    s = CardDisciplineVenueSplit(at_home_sample_size=5, at_home_yellow_per_game=2.0, at_home_red_per_game=0.1, away_sample_size=5, away_yellow_per_game=2.5, away_red_per_game=0.2, source="football-data")
    result = card_discipline_venue_split_str(s, "Home")
    assert "at home 2Y/0.1R (n=5)" in result
    assert "away 2.5Y/0.2R (n=5)" in result


def test_card_discipline_venue_split_str_na_without_sample():
    from football.format_markdown import card_discipline_venue_split_str
    from football.types import CardDisciplineVenueSplit

    s = CardDisciplineVenueSplit(at_home_sample_size=0, at_home_yellow_per_game=None, at_home_red_per_game=None, away_sample_size=0, away_yellow_per_game=None, away_red_per_game=None, source="football-data")
    result = card_discipline_venue_split_str(s, "Home")
    assert "at home n/a" in result
    assert "away n/a" in result


def test_travel_str_home_at_home_turf():
    from football.format_markdown import travel_str
    from football.types import TravelInfo

    t = TravelInfo(
        venue_country="England", home_team_country="England", away_team_country="Spain",
        home_traveling=False, away_traveling=True,
        home_travel_distance_km=None, away_travel_distance_km=1200.0,
        home_timezone_diff_hours=None, away_timezone_diff_hours=1.0,
        home_travel_time_hours=None, away_travel_time_hours=2.5,
    )
    result = travel_str(t, "Home FC", "Away FC")
    assert "Home FC at home turf (England)" in result
    assert "Away FC traveling (Spain -> England, ~1,200km, ~2.5h travel, 1h tz diff)" in result


def test_travel_str_unknown_side():
    from football.format_markdown import travel_str
    from football.types import TravelInfo

    t = _all_none(TravelInfo, venue_country="England")
    result = travel_str(t, "Home FC", "Away FC")
    assert "Home FC: unknown" in result
    assert "Away FC: unknown" in result


def test_rank_record_str_formats_record():
    from football.format_markdown import rank_record_str
    from football.types import OpponentRankRecord

    r = OpponentRankRecord(sample_size=8, wins=2, draws=1, losses=5)
    assert rank_record_str(r, "Home") == "Home vs currently-higher-ranked opponents (same competition): 2W-1D-5L (n=8)"


def test_presence_str_counts_present_and_absent():
    from football.format_markdown import presence_str
    from football.types import PresenceEntry

    entries = [
        PresenceEntry(name="A", status="P", starting=True, on_bench=False, reason=None),
        PresenceEntry(name="B", status="P", starting=False, on_bench=True, reason=None),
        PresenceEntry(name="C", status="A", starting=False, on_bench=False, reason="injury"),
    ]
    result = presence_str(entries, "Home")
    assert "2 present (1 starting, 1 on bench)" in result
    assert "1 absent: C (injury)" in result


def test_presence_str_no_absent_list_when_none_absent():
    from football.format_markdown import presence_str
    from football.types import PresenceEntry

    entries = [PresenceEntry(name="A", status="P", starting=True, on_bench=None, reason=None)]
    result = presence_str(entries, "Home")
    assert result.endswith("0 absent")


def test_bench_info_str_formats_market_values():
    from football.format_markdown import bench_info_str
    from football.types import BenchInfo

    b = BenchInfo(bench_size=7, bench_total_market_value=25_000_000.0, starting_total_market_value=450_000_000.0)
    result = bench_info_str(b, "Home")
    assert "7 named" in result
    assert "€25m" in result
    assert "€450m" in result


def test_bench_info_str_na_without_market_values():
    from football.format_markdown import bench_info_str
    from football.types import BenchInfo

    b = BenchInfo(bench_size=5, bench_total_market_value=None, starting_total_market_value=None)
    assert "n/a" in bench_info_str(b, "Home")


def test_squad_strength_str_formats_all_position_groups():
    from football.format_markdown import squad_strength_str
    from football.types import SquadStrengthInfo

    s = SquadStrengthInfo(total_value=500_000_000.0, attack_value=200_000_000.0, midfield_value=150_000_000.0, defense_value=100_000_000.0, goalkeeper_value=50_000_000.0, available_value=480_000_000.0)
    result = squad_strength_str(s, "Home")
    assert "€500m total" in result
    assert "€480m available" in result
    assert "attack €200m" in result


def test_rotation_str_no_shape_note_without_formation_data():
    from football.format_markdown import rotation_str
    from football.types import RotationInfo

    r = RotationInfo(changed_players=3, starting_xi_size=11, last_match_date="2026-01-08T00:00:00.000Z", previous_match_date="2026-01-01T00:00:00.000Z", last_formation=None, previous_formation=None, formation_changed=None, last_defender_count=None, previous_defender_count=None, preceding_result="W")
    result = rotation_str(r, "Home")
    assert "after a win" in result
    assert "3/11 starting XI changed" in result
    assert "shape" not in result


def test_rotation_str_formation_changed_with_defender_count():
    from football.format_markdown import rotation_str
    from football.types import RotationInfo

    r = RotationInfo(changed_players=4, starting_xi_size=11, last_match_date="2026-01-08T00:00:00.000Z", previous_match_date="2026-01-01T00:00:00.000Z", last_formation="3-5-2", previous_formation="4-4-2", formation_changed=True, last_defender_count=3, previous_defender_count=4, preceding_result=None)
    result = rotation_str(r, "Home")
    assert "shape changed 4-4-2 -> 3-5-2 (4 -> 3 defenders)" in result


def test_rotation_str_formation_unchanged():
    from football.format_markdown import rotation_str
    from football.types import RotationInfo

    r = RotationInfo(changed_players=2, starting_xi_size=11, last_match_date="2026-01-08T00:00:00.000Z", previous_match_date="2026-01-01T00:00:00.000Z", last_formation="4-3-3", previous_formation="4-3-3", formation_changed=False, last_defender_count=4, previous_defender_count=4, preceding_result="D")
    result = rotation_str(r, "Home")
    assert "shape unchanged (4-3-3)" in result


def test_resilience_str_formats_draw_share():
    from football.format_markdown import resilience_str
    from football.types import ResilienceInfo

    r = ResilienceInfo(non_win_sample_size=8, draw_share_pct=37.5)
    assert resilience_str(r, "Home") == "Home resilience: 37.5% of non-win results (n=8) were draws rather than losses"


def test_rest_performance_str_both_buckets_populated():
    from football.format_markdown import rest_performance_str
    from football.types import RestPerformanceInfo

    r = RestPerformanceInfo(short_rest_ppg=1.2, short_rest_sample_size=4, long_rest_ppg=2.1, long_rest_sample_size=6)
    result = rest_performance_str(r, "Home")
    assert "1.2 ppg (n=4)" in result
    assert "2.1 ppg (n=6)" in result


def test_rest_performance_str_na_without_short_rest_data():
    from football.format_markdown import rest_performance_str
    from football.types import RestPerformanceInfo

    r = RestPerformanceInfo(short_rest_ppg=None, short_rest_sample_size=0, long_rest_ppg=2.0, long_rest_sample_size=10)
    assert "<=3 days rest n/a" in rest_performance_str(r, "Home")


def test_experience_h2h_str_not_directly_comparable_when_even():
    from football.format_markdown import experience_h2h_str
    from football.types import ExperienceH2HNote

    e = ExperienceH2HNote(more_experienced="own", h2h_leader="opponent", aligned=None)
    result = experience_h2h_str(e)
    assert "not directly comparable" in result


def test_experience_h2h_str_aligned_true():
    from football.format_markdown import experience_h2h_str
    from football.types import ExperienceH2HNote

    e = ExperienceH2HNote(more_experienced="own", h2h_leader="own", aligned=True)
    assert "also holds" in experience_h2h_str(e)


def test_experience_h2h_str_aligned_false():
    from football.format_markdown import experience_h2h_str
    from football.types import ExperienceH2HNote

    e = ExperienceH2HNote(more_experienced="own", h2h_leader="opponent", aligned=False)
    assert "does not hold" in experience_h2h_str(e)


def test_fatigue_flag_str_elevated_with_avg_gap():
    from football.format_markdown import fatigue_flag_str
    from football.types import FatigueFlag

    f = FatigueFlag(multi_competition=True, competitions=["Premier League", "FA Cup"], avg_gap_days=3.5, flagged=True)
    result = fatigue_flag_str(f, "Home")
    assert "elevated" in result
    assert "2 competitions" in result
    assert "3.5d avg gap" in result


def test_fatigue_flag_str_normal_without_avg_gap():
    from football.format_markdown import fatigue_flag_str
    from football.types import FatigueFlag

    f = FatigueFlag(multi_competition=False, competitions=["Premier League"], avg_gap_days=None, flagged=False)
    result = fatigue_flag_str(f, "Home")
    assert "normal" in result
    assert "n/a" in result


def test_home_advantage_str_positive_gap():
    from football.format_markdown import home_advantage_str
    from football.types import HomeAdvantageInfo

    h = HomeAdvantageInfo(home_win_rate_pct=60.0, away_win_rate_pct=40.0, gap_pct=20.0, strength="strong")
    result = home_advantage_str(h, "Home")
    assert "+20.0pp" in result
    assert "strong" in result


def test_home_advantage_str_negative_gap_no_plus_sign():
    from football.format_markdown import home_advantage_str
    from football.types import HomeAdvantageInfo

    h = HomeAdvantageInfo(home_win_rate_pct=30.0, away_win_rate_pct=50.0, gap_pct=-20.0, strength="reverse")
    result = home_advantage_str(h, "Home")
    assert ", -20.0pp" in result


def test_xg_estimate_str_formats_estimate():
    from football.format_markdown import xg_estimate_str
    from football.types import SeasonXGEstimate

    x = SeasonXGEstimate(sample_size=10, xg_for=15.5, xg_against=8.2, actual_goals_for=16, actual_goals_against=7, source="fotmob")
    result = xg_estimate_str(x, "Home")
    assert "last 10 finished" in result
    assert "15.5 xGF" in result
    assert "16-7" in result


def test_shots_estimate_str_formats_estimate():
    from football.format_markdown import shots_estimate_str
    from football.types import SeasonShotsEstimate

    x = SeasonShotsEstimate(sample_size=10, shots_for=150, shots_against=100, shots_on_target_for=60, shots_on_target_against=40, source="fotmob")
    result = shots_estimate_str(x, "Home")
    assert "150 shots for (60 on target)" in result


def test_aerial_estimate_str_formats_estimate():
    from football.format_markdown import aerial_estimate_str
    from football.types import SeasonAerialEstimate

    x = SeasonAerialEstimate(sample_size=10, aerial_duels_won_for=45, aerial_duels_won_against=55, source="fotmob")
    assert aerial_estimate_str(x, "Home") == "Home aerial duels (last 10 finished): 45 won / 55 lost"


def test_big_chances_estimate_str_formats_estimate():
    from football.format_markdown import big_chances_estimate_str
    from football.types import SeasonBigChancesEstimate

    x = SeasonBigChancesEstimate(sample_size=10, big_chances_created_for=20, big_chances_created_against=12, big_chances_missed_for=8, big_chances_missed_against=5, source="fotmob")
    result = big_chances_estimate_str(x, "Home")
    assert "20 created (8 missed)" in result
    assert "12 conceded (5 missed by opponent)" in result


def _advanced_stats(**overrides):
    from football.types import SeasonAdvancedStatsEstimate

    fields = {f.name: 1 for f in _dc_fields(SeasonAdvancedStatsEstimate)}
    fields["sample_size"] = 10
    fields["source"] = "sofascore"
    fields["unavailable_stats"] = None
    fields["possession_pct_avg"] = 55.0
    fields["field_tilt_pct"] = 52.0
    fields.update(overrides)
    return SeasonAdvancedStatsEstimate(**fields)


def test_advanced_stats_str_renders_every_part_without_error():
    from football.format_markdown import advanced_stats_str

    result = advanced_stats_str(_advanced_stats(), "Home")
    assert result.startswith("Home advanced stats (last 10 matched):")
    assert "possession 55%" in result
    assert "field tilt 52%" in result


def test_advanced_stats_str_na_without_possession_or_tilt():
    from football.format_markdown import advanced_stats_str

    result = advanced_stats_str(_advanced_stats(possession_pct_avg=None, field_tilt_pct=None), "Home")
    assert "possession n/a%" in result
    assert "field tilt n/a%" in result


def test_advanced_stats_str_null_unavailable_pair_renders_na_not_zero():
    """JSON null (source never reported the stat) must not print as 0-0."""
    from football.format_markdown import advanced_stats_str

    result = advanced_stats_str(
        _advanced_stats(
            unavailable_stats=["red_cards", "through_balls"],
            red_cards_for=None,
            red_cards_against=None,
            through_balls_for=None,
            through_balls_against=None,
        ),
        "Home",
    )
    assert "cards 1Y/n/a-1Y/n/a" in result
    assert "through balls n/a" in result
    assert "unavailable from source: red_cards, through_balls" in result
    # yellow stayed available (helper default = 1)
    assert "0R" not in result


def test_advanced_stats_str_null_pair_even_without_unavailable_stats_name():
    """Null field alone is enough for n/a -- unavailable_stats is belt-and-braces."""
    from football.format_markdown import advanced_stats_str

    result = advanced_stats_str(_advanced_stats(red_cards_for=None, red_cards_against=None), "Home")
    assert "cards 1Y/n/a-1Y/n/a" in result


def test_advanced_stats_str_null_goals_prevented_and_distance_render_na():
    """goals_prevented / distance_covered_km can now be null when the source
    never reported them -- must not crash js_number_to_string(None)."""
    from football.format_markdown import advanced_stats_str

    result = advanced_stats_str(
        _advanced_stats(
            unavailable_stats=["goals_prevented", "distance_covered_km"],
            goals_prevented_for=None,
            goals_prevented_against=None,
            distance_covered_km_for=None,
            distance_covered_km_against=None,
        ),
        "Home",
    )
    assert "goals prevented n/a" in result
    assert "distance n/akm" in result


def test_passing_style_str_formats_pass_accuracy():
    from football.format_markdown import passing_style_str
    from football.types import SeasonPassingStyleEstimate

    x = SeasonPassingStyleEstimate(sample_size=10, total_passes_for=5000, accurate_passes_for=4200, pass_accuracy_pct=84.0, accurate_long_balls_for=300, long_ball_share_pct=7.1, source="fotmob")
    result = passing_style_str(x, "Home")
    assert "84% pass accuracy" in result
    assert "7.1% of accurate passes" in result


def test_passing_style_str_na_without_pass_accuracy():
    from football.format_markdown import passing_style_str
    from football.types import SeasonPassingStyleEstimate

    x = SeasonPassingStyleEstimate(sample_size=10, total_passes_for=5000, accurate_passes_for=4200, pass_accuracy_pct=None, accurate_long_balls_for=300, long_ball_share_pct=None, source="fotmob")
    result = passing_style_str(x, "Home")
    assert "n/a% pass accuracy" in result


def test_fouls_estimate_str_formats_committed_and_suffered():
    from football.format_markdown import fouls_estimate_str
    from football.types import SeasonFoulsEstimate

    x = SeasonFoulsEstimate(sample_size=10, fouls_committed_for=120, fouls_committed_against=95, source="fotmob")
    assert fouls_estimate_str(x, "Home") == "Home fouls estimate (last 10 finished): 120 committed / 95 suffered"


def test_goalkeeping_estimate_str_formats_save_rate():
    from football.format_markdown import goalkeeping_estimate_str
    from football.types import SeasonGoalkeepingEstimate

    x = SeasonGoalkeepingEstimate(sample_size=10, saves_for=30, shots_on_target_faced=40, save_pct=75.0, goals_conceded=10, source="fotmob")
    result = goalkeeping_estimate_str(x, "Home")
    assert "30 saves on 40 shots faced (75% save rate)" in result


def test_goalkeeping_estimate_str_na_without_save_pct():
    from football.format_markdown import goalkeeping_estimate_str
    from football.types import SeasonGoalkeepingEstimate

    x = SeasonGoalkeepingEstimate(sample_size=10, saves_for=30, shots_on_target_faced=40, save_pct=None, goals_conceded=10, source="fotmob")
    assert "n/a% save rate" in goalkeeping_estimate_str(x, "Home")


def test_set_piece_threat_str_elevated():
    from football.format_markdown import set_piece_threat_str
    from football.types import SetPieceThreatFlag

    f = SetPieceThreatFlag(corners_per_game=6.5, opponent_aerial_win_pct=42.0, elevated=True)
    result = set_piece_threat_str(f, "Home")
    assert "6.5 corners/game" in result
    assert "-- elevated" in result


def test_direct_play_exposure_str_not_elevated():
    from football.format_markdown import direct_play_exposure_str
    from football.types import DirectPlayExposureFlag

    f = DirectPlayExposureFlag(long_ball_share_pct=10.0, opponent_aerial_win_pct=60.0, elevated=False)
    result = direct_play_exposure_str(f, "Home")
    assert "10% long-ball share" in result
    assert "-- elevated" not in result


def test_card_risks_str_formats_multiple_players():
    from football.format_markdown import card_risks_str
    from football.types import PlayerCardRisk

    risks = [
        PlayerCardRisk(name="A", yellow_cards=5, red_cards=0, appearances=10, accumulation_risk=True, prior_dismissal=False),
        PlayerCardRisk(name="B", yellow_cards=4, red_cards=1, appearances=8, accumulation_risk=True, prior_dismissal=True),
    ]
    result = card_risks_str(risks, "Home")
    assert "A (5Y)" in result
    assert "B (4Y/1R, prior dismissal)" in result


def test_referee_card_risk_note_str_formats_flagged_players_by_side():
    from football.format_markdown import referee_card_risk_note_str
    from football.types import FlaggedPlayer, RefereeCardRiskNote

    n = RefereeCardRiskNote(
        referee_name="Some Ref", yellow_cards_per_game=3.2, elevated_card_referee=True,
        flagged_players=[FlaggedPlayer(name="A", side="home", prior_dismissal=False), FlaggedPlayer(name="B", side="away", prior_dismissal=True)],
    )
    result = referee_card_risk_note_str(n, "Home FC", "Away FC")
    assert "Some Ref books 3.2 yellow/game (elevated)" in result
    assert "A (Home FC)" in result
    assert "B (Away FC, prior dismissal)" in result


def test_duel_vulnerabilities_str_formats_players():
    from football.format_markdown import duel_vulnerabilities_str
    from football.types import DuelVulnerability

    vulns = [DuelVulnerability(name="A", ground_duel_success_pct=35.5)]
    assert duel_vulnerabilities_str(vulns, "Home") == "Home defensive duel risk: A (35.5% ground duels won)"


def test_fullback_exposure_str_formats_players():
    from football.format_markdown import fullback_exposure_str
    from football.types import FullbackExposureInfo

    exposure = [FullbackExposureInfo(name="A", chances_created=3, ground_duel_success_pct=48.0)]
    assert fullback_exposure_str(exposure, "Home") == "Home attacking-defender exposure: A (3 chances created, 48.0% ground duels won)"


def test_possession_matchup_str_both_buckets():
    from football.format_markdown import possession_matchup_str
    from football.types import PossessionMatchupInfo

    p = PossessionMatchupInfo(high_opponent_possession_ppg=1.2, high_opponent_possession_sample_size=3, other_ppg=2.0, other_sample_size=7)
    result = possession_matchup_str(p, "Home FC")
    assert "1.2 ppg (n=3)" in result
    assert "2 ppg (n=7)" in result


def test_corners_estimate_str_formats_estimate():
    from football.format_markdown import corners_estimate_str
    from football.types import SeasonCornersEstimate

    x = SeasonCornersEstimate(sample_size=10, corners_for=55, corners_against=40, source="fotmob")
    assert corners_estimate_str(x, "Home") == "Home corners estimate (last 10 finished): 55 for / 40 against"


def test_defensive_errors_estimate_str_formats_estimate():
    from football.format_markdown import defensive_errors_estimate_str
    from football.types import SeasonDefensiveErrorsEstimate

    x = SeasonDefensiveErrorsEstimate(sample_size=10, defensive_errors_for=3, defensive_errors_against=5, source="fotmob")
    assert defensive_errors_estimate_str(x, "Home") == "Home defensive errors (last 10 published): 3 for / 5 against"


# --- broad integration: every optional section of each top-level markdown fn ---------------


def _lineup_player(name, **overrides):
    from football.types import LineupPlayer

    base = {
        "name": name, "position": "M", "substitute": False, "minutes_played": 90, "goals": 0, "assists": 0,
        "xg": None, "xa": None, "shots": None, "shots_on_target": None, "tackles": None, "interceptions": None,
        "fouls": None, "rating": None, "key_passes": None, "shirt_number": None, "age": None,
    }
    base.update(overrides)
    return LineupPlayer(**base)


def test_merged_match_markdown_renders_every_optional_section():
    from football.merge import AdditionalNote, MergedMatch
    from football.types import (
        BettingOdds,
        HeadToHeadSummary,
        ManagerClubRecord,
        MatchStatItem,
        PlayerOfTheMatch,
        TeamSeasonStats,
        TeamStanding,
        TimelineEvent,
        WeatherDetail,
    )

    odds = BettingOdds(home_win_odds=1.8, draw_odds=3.5, away_win_odds=4.2, home_win_implied_pct=50.0, draw_implied_pct=25.0, away_win_implied_pct=25.0, over_2_5_odds=1.9, under_2_5_odds=1.95)
    sofascore_odds = BettingOdds(home_win_odds=1.91, draw_odds=3.6, away_win_odds=3.9, home_win_implied_pct=None, draw_implied_pct=None, away_win_implied_pct=None, over_2_5_odds=1.73, under_2_5_odds=2.1)
    h2h = HeadToHeadSummary(home_wins=3, away_wins=2, draws=1)
    standing = TeamStanding(position=4, played=20, wins=12, draws=4, losses=4, points=40, goal_diff=15, total_teams=20)
    season_stats = TeamSeasonStats(goals_scored=45, goals_conceded=20, clean_sheets=8, yellow_cards=30, red_cards=1, average_ball_possession=55.0)
    manager_record = ManagerClubRecord(manager_name="Some Boss", opponent_club="Away FC", sample_size=5, wins=3, draws=1, losses=1)
    weather_detail = WeatherDetail(temp_c=15.0, humidity_pct=60.0, wind_speed_kmph=10.0, precip_mm=0.0, chance_of_rain_pct=20.0, wind_gust_kmph=18.0, cloud_cover_pct=50.0, feels_like_c=14.0, kickoff_hour_matched=True)

    d = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished", kickoff_utc="2026-01-01T15:00:00.000Z",
        competition="Premier League", season="25/26", round=10, venue_name="Home Stadium", venue_city="Somewhere", venue_country="England",
        referee="Some Ref", referee_stats=None, attendance=45000, weather="Sunny, 15.0°C", weather_detail=weather_detail,
        betting_odds=odds, sofascore_betting_odds=sofascore_odds, head_to_head_summary=h2h, head_to_head_streaks=["Home FC unbeaten in last 5"],
        recent_meetings=[_meeting()], home_team_standing=standing, away_team_standing=standing,
        home_team_season_stats=season_stats, away_team_season_stats=season_stats,
        match_stats=[MatchStatItem(name="Possession", home="55", away="45")],
        event_timeline=[TimelineEvent(minute=23, type="Goal", detail=None, player="Some Player", team="home")],
        player_of_the_match=PlayerOfTheMatch(name="Some Player", rating=8.5),
        home_formation="4-3-3", away_formation="4-4-2",
        home_lineup=[_lineup_player("Home Player")], away_lineup=[_lineup_player("Away Player")],
        lineup_confirmed=True,
        home_manager=_manager(name="Home Boss"), away_manager=_manager(name="Away Boss"),
        home_manager_vs_away_club=manager_record, away_manager_vs_home_club=manager_record,
        note="A general note", additional_notes=[AdditionalNote(source="soccerdesk", note="A sourced note")],
        field_sources={},
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "Odds (football-data.co.uk avg): Home FC 1.8" in text
    assert "Odds (Sofascore, single book): Home FC 1.91" in text
    assert "H2H: Home FC 3W" in text
    assert "H2H streaks: Home FC unbeaten in last 5" in text
    assert "Recent meetings:" in text
    assert "Home FC rank: #4" in text
    assert "Home FC season: 45 scored" in text
    assert "clean-sheet cross-check" not in text  # recent_check is None / not greater than season total
    assert "Match stats: Possession 55-45" in text
    assert "Timeline: 23' Goal (Some Player)" in text
    assert "Player of the match: Some Player (8.5)" in text
    assert "Home FC formation: 4-3-3" in text
    assert "Home FC lineup (confirmed): Home Player" in text
    assert "Managers: Home FC: Home Boss" in text
    assert "Some Boss vs Away FC" in text
    assert "Note: A general note" in text
    assert "Note: A sourced note" in text
    assert "gusts 18" in text
    assert "feels like 14" in text


def test_merged_match_markdown_surfaces_clean_sheet_discrepancy_when_windows_differ():
    from football.merge import MergedMatch
    from football.types import TeamSeasonStats

    lagging = TeamSeasonStats(
        goals_scored=20, goals_conceded=25, clean_sheets=2, yellow_cards=30, red_cards=2,
        average_ball_possession=None, clean_sheets_recent_check=5, clean_sheets_recent_check_sample_size=17,
        clean_sheets_recent_check_source="sofascore",
    )
    d = _all_none(
        MergedMatch, home_team="Man Utd", away_team="Away FC", status="finished",
        home_team_season_stats=lagging, away_team_season_stats=None,
        field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "Man Utd season: 20 scored, 25 conceded, 2 clean sheets" in text
    assert "Man Utd clean-sheet cross-check: season aggregate 2, last-20 competitive results show 5 of 17 competitive results in the window (sofascore)" in text
    assert "different windows, not reconciled" in text


def test_merged_match_markdown_omits_clean_sheet_cross_check_when_windows_match():
    from football.merge import MergedMatch
    from football.types import TeamSeasonStats

    normal = TeamSeasonStats(
        goals_scored=45, goals_conceded=20, clean_sheets=8, yellow_cards=30, red_cards=1,
        average_ball_possession=None, clean_sheets_recent_check=8, clean_sheets_recent_check_source="fotmob",
    )
    d = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished",
        home_team_season_stats=normal, away_team_season_stats=None,
        field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "clean-sheet cross-check" not in text


def test_merged_match_markdown_notes_h2h_detail_subset_of_sample():
    from football.merge import MergedMatch
    from football.types import HeadToHeadMeeting, HeadToHeadSummary

    h2h = HeadToHeadSummary(home_wins=5, away_wins=5, draws=0, sample_size=10)
    meeting = HeadToHeadMeeting(
        date="2026-03-22T14:15:00.000Z", competition="Premier League", scoreline="0-3",
        venue="home", home_formation=None, away_formation=None, home_xg=None, away_xg=None,
        home_lineup=None, away_lineup=None, home_team="Home FC", away_team="Away FC",
    )
    d = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished",
        head_to_head_summary=h2h, recent_meetings=[meeting],
        field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "detailed list below shows 1 of 10" in text
    assert "2026-03-22 0-3" in text


def test_merged_match_markdown_notes_partial_standings_form():
    from football.merge import MergedMatch
    from football.types import StandingsTableRow

    def _row(position, team_name, form=None):
        return StandingsTableRow(
            team_name=team_name, position=position, points=0, wins=0, draws=0, losses=0,
            goal_difference=0, goals_for=0, goals_against=0, form=form,
        )

    table = [
        _row(1, "Home FC", form="WWDLW"),
        _row(2, "Away FC", form="LDWWD"),
        _row(3, "Other FC"),
    ]
    d = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished",
        standings_table=table, field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "Standings form (partial; remaining rows have no source form column): Home FC WWDLW, Away FC LDWWD" in text


def test_merged_match_markdown_omits_standings_form_note_when_every_row_is_filled_or_none():
    from football.merge import MergedMatch
    from football.types import StandingsTableRow

    def _row(position, team_name, form=None):
        return StandingsTableRow(
            team_name=team_name, position=position, points=0, wins=0, draws=0, losses=0,
            goal_difference=0, goals_for=0, goals_against=0, form=form,
        )

    filled = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished",
        standings_table=[_row(1, "A", form="W"), _row(2, "B", form="L")],
        field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(filled, lines)
    assert "Standings form" not in "\n".join(lines)

    empty = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished",
        standings_table=[_row(1, "A"), _row(2, "B")],
        field_sources={}, additional_notes=[],
    )
    lines = []
    merged_match_markdown(empty, lines)
    assert "Standings form" not in "\n".join(lines)


def test_merged_match_markdown_labels_season_possession_as_season_to_date():
    from football.merge import MergedMatch
    from football.types import TeamSeasonStats

    stats = TeamSeasonStats(
        goals_scored=45, goals_conceded=20, clean_sheets=8, yellow_cards=30, red_cards=1,
        average_ball_possession=59.0,
    )
    d = _all_none(
        MergedMatch, home_team="Tottenham Hotspur", away_team="Away FC", status="finished",
        home_team_season_stats=stats, away_team_season_stats=None,
        field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "59% avg possession (season to date)" in text


def test_merged_match_markdown_surfaces_possession_cross_check_when_windows_diverge():
    from football.merge import MergedMatch
    from football.types import TeamSeasonStats

    # Reconciliation path: gap >5pp so average_ball_possession was replaced
    # and average_ball_possession_source_season preserves the original.
    stats = TeamSeasonStats(
        goals_scored=45, goals_conceded=20, clean_sheets=8, yellow_cards=30, red_cards=1,
        average_ball_possession=52.5, average_ball_possession_source_season=59.0,
        possession_venue_split_check=52.5,
        possession_venue_split_check_source="sofascore",
    )
    d = _all_none(
        MergedMatch, home_team="Tottenham Hotspur", away_team="Away FC", status="finished",
        home_team_season_stats=stats, away_team_season_stats=None,
        field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "Tottenham Hotspur possession cross-check: using last-20 venue-split 52.5% (sofascore) (season-to-date source figure was 59%" in text
    assert "form window preferred for this fixture" in text


def test_merged_match_markdown_surfaces_possession_cross_check_when_gap_is_small():
    from football.merge import MergedMatch
    from football.types import TeamSeasonStats

    # Gap within 5pp: no reconciliation, but both windows still exist and
    # must both be labelled so neither bare percentage looks like a
    # contradiction (previously this note was silent).
    stats = TeamSeasonStats(
        goals_scored=45, goals_conceded=20, clean_sheets=8, yellow_cards=30, red_cards=1,
        average_ball_possession=56.6, possession_venue_split_check=56.2,
        possession_venue_split_check_source="sofascore",
    )
    d = _all_none(
        MergedMatch, home_team="Tottenham Hotspur", away_team="Away FC", status="finished",
        home_team_season_stats=stats, away_team_season_stats=None,
        field_sources={}, additional_notes=[],
    )
    lines: list[str] = []
    merged_match_markdown(d, lines)
    text = "\n".join(lines)
    assert "possession cross-check: season-to-date 56.6% vs last-20 venue-split 56.2% (sofascore)" in text
    assert "season figure kept" in text


def test_merged_profile_markdown_renders_full_squad_and_leaderboards():
    from football.merge import MergedProfile
    from football.types import DefensiveStats, SeasonPlayerStats, SquadMember

    scorer = SquadMember(
        name="Top Scorer", role="F", injury=None, age=24, market_value=50_000_000.0,
        season_stats=SeasonPlayerStats(appearances=20, goals=15, assists=5, yellow_cards=2, red_cards=0, rating=7.5, expected_goals=12.0),
        season_stats_source="sofascore",
        defensive_stats=None,
        recent_usage=None,
    )
    top_defender = SquadMember(
        name="Top Defender", role="D", injury=None, age=28, market_value=30_000_000.0,
        season_stats=None, season_stats_source=None,
        defensive_stats=DefensiveStats(tackles_made=5, interceptions=3, ball_recoveries=None, clearances=None, ground_duel_success_pct=None, chances_created=None),
        recent_usage=None,
    )
    injured = SquadMember(name="Injured Player", role="D", injury="hamstring", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)

    p = _all_none(
        MergedProfile, source="sofascore", team_name="Home FC", squad=[scorer, top_defender, injured], average_age=26.4,
        injuries=[injured], key_injuries=[injured], missing_midfielders=["Some Mid"], missing_attackers=["Some Att"],
        missing_defenders=["Injured Player"], missing_goalkeepers=["Some GK"],
        recent_transfers=[__import__("football.types", fromlist=["TransferRecord"]).TransferRecord(player_name="New Signing", direction="in", from_club="Old Club", to_club="Home FC", date="2026-01-01T00:00:00.000Z")],
        field_sources={},
    )
    lines: list[str] = []
    merged_profile_markdown(p, lines)
    text = "\n".join(lines)
    assert "Squad (3, avg age 26.4): Top Scorer, Top Defender, Injured Player" in text
    assert "Injuries: Injured Player - hamstring" in text
    assert "Key injuries" in text
    assert "Missing midfielders: Some Mid" in text
    assert "Missing attackers: Some Att" in text
    assert "Missing defenders: Injured Player" in text
    assert "Missing goalkeepers: Some GK" in text
    assert "Recent transfers: New Signing" in text
    assert "Top scorers (season to date): Top Scorer" in text
    assert "Top defenders: Top Defender" in text


def test_form_summary_markdown_renders_every_optional_section():
    from football.types import (
        CompetitionFormRecord,
        DetailedVenueSplitForm,
        FixtureGap,
        HalfSplitStats,
        MomentumInfo,
        StreakInfo,
        VenueSplitForm,
    )

    f = _form_summary_full(
        last5_overall=[_form_result()], last20_overall=[_form_result(ht_scoreline="1-0")], last5_home=[_form_result()], last5_away=[_form_result()],
        next5_with_gaps=[FixtureGap(opponent="Next Opp", date="2026-02-01T00:00:00.000Z", days_since_previous=5)],
        gaps_between_last_three=[7, 4], half_split=HalfSplitStats(sample_size=5, first_half_goals_for=3, first_half_goals_against=1, second_half_goals_for=2, second_half_goals_against=1),
        recent_competitions=["Premier League", "FA Cup"], current_streak=StreakInfo(result="W", count=3),
        home_win_rate_pct=60.0, away_win_rate_pct=40.0, momentum=MomentumInfo(recent_ppg=2.0, prior_ppg=1.0, trend="improving"),
        narrow_win_share_pct=30.0, scoring_draw_share_pct=20.0, btts_share_pct=50.0, clean_sheet_streak=3, scoreless_streak=0,
        over15_share_pct=80.0, over25_share_pct=60.0, over35_share_pct=30.0, clean_sheet_share_pct=40.0, failed_to_score_share_pct=10.0,
        form_by_competition=[CompetitionFormRecord(competition="Premier League", played=10, wins=6, draws=2, losses=2, goals_for=20, goals_against=10), CompetitionFormRecord(competition="FA Cup", played=3, wins=2, draws=0, losses=1, goals_for=5, goals_against=3)],
        matches_last7_days=1, matches_last14_days=2,
        venue_split_form=VenueSplitForm(home_sample_size=5, home_wins=3, home_draws=1, home_losses=1, home_goals_for=8, home_goals_against=4, away_sample_size=5, away_wins=2, away_draws=1, away_losses=2, away_goals_for=6, away_goals_against=7, neutral_sample_size=0, neutral_wins=0, neutral_draws=0, neutral_losses=0, neutral_goals_for=0, neutral_goals_against=0),
        detailed_venue_split=DetailedVenueSplitForm(home=_venue_bucket(), away=_venue_bucket(), neutral=_venue_bucket(sample_size=0)),
        win_rate_pct=55.0, draw_rate_pct=20.0, loss_rate_pct=25.0, points_per_game=1.8, goals_for_per_game=1.5, goals_against_per_game=1.0,
    )
    lines: list[str] = []
    form_summary_markdown(f, lines)
    text = "\n".join(lines)
    assert "Last 5 (all):" in text
    assert "With HT score:" in text
    assert "Last 5 (home):" in text
    assert "Last 5 (away):" in text
    assert "Next 5: " in text
    assert "Gaps between last 3 matches: 7, 4 days" in text
    assert "Half split:" in text
    assert "Competitions played recently: Premier League | FA Cup (2)" in text
    assert "Streak: 3-game winning streak" in text
    assert "Win rate: Home 60.0% / Away 40.0%" in text
    assert "Momentum: 2 ppg (last 3) vs 1 ppg (prior 3) -- improving" in text
    assert "Narrow wins: 30.0%" in text
    assert "Scoring draws: 20.0%" in text
    assert "BTTS: 50.0%" in text
    assert "Clean sheets: 3-game clean sheet streak" in text
    assert "Over/Under (last 10): O1.5 80.0%" in text
    assert "Clean sheet / failed-to-score rate" in text
    assert "Form by competition (last 20):" in text
    assert "Fixture congestion: 1 match in last 7 days, 2 in last 14 days" in text
    assert "Rates (last 10): W55.0%" in text
    assert "Venue split (true venue not fixture label):" in text
    assert "Detailed venue split (last 20 by true venue):" in text


def test_form_summary_markdown_scoreless_streak_line():
    f = _form_summary_full(scoreless_streak=2)
    lines: list[str] = []
    form_summary_markdown(f, lines)
    assert any("Scoreless: 2-game scoreless streak" in line for line in lines)


def _insights_full(**overrides):
    from football.types import (
        BenchInfo,
        CardDisciplineInfo,
        CardDisciplineVenueSplit,
        ClubStrengthRating,
        DirectPlayExposureFlag,
        DuelVulnerability,
        EloRating,
        ExperienceComparison,
        ExperienceH2HNote,
        FatigueFlag,
        FlaggedPlayer,
        FullbackExposureInfo,
        HomeAdvantageInfo,
        MatchInsights,
        MatchPrediction,
        OpponentRankRecord,
        OutcomeProbabilities,
        PlayerCardRisk,
        PossessionMatchupInfo,
        PresenceEntry,
        RefereeCardRiskNote,
        ResilienceInfo,
        RestComparison,
        RestPerformanceInfo,
        RotationInfo,
        SeasonAerialEstimate,
        SeasonBigChancesEstimate,
        SeasonCornersEstimate,
        SeasonDefensiveErrorsEstimate,
        SeasonFoulsEstimate,
        SeasonGoalkeepingEstimate,
        SeasonPassingStyleEstimate,
        SeasonShotsEstimate,
        SeasonXGEstimate,
        SetPieceThreatFlag,
        SquadStrengthInfo,
        StandingsImpactInfo,
        StandingsScenario,
        StandingsZoneInfo,
        StreakStabilityInfo,
        TravelInfo,
    )

    probs = OutcomeProbabilities(home_win_pct=50.0, draw_pct=25.0, away_win_pct=25.0)
    xg = SeasonXGEstimate(sample_size=10, xg_for=15.0, xg_against=8.0, actual_goals_for=16, actual_goals_against=7, source="fotmob")
    shots = SeasonShotsEstimate(sample_size=10, shots_for=150, shots_against=100, shots_on_target_for=60, shots_on_target_against=40, source="fotmob")
    aerial = SeasonAerialEstimate(sample_size=10, aerial_duels_won_for=45, aerial_duels_won_against=55, source="fotmob")
    big_chances = SeasonBigChancesEstimate(sample_size=10, big_chances_created_for=20, big_chances_created_against=12, big_chances_missed_for=8, big_chances_missed_against=5, source="fotmob")
    passing = SeasonPassingStyleEstimate(sample_size=10, total_passes_for=5000, accurate_passes_for=4200, pass_accuracy_pct=84.0, accurate_long_balls_for=300, long_ball_share_pct=7.1, source="fotmob")
    fouls = SeasonFoulsEstimate(sample_size=10, fouls_committed_for=120, fouls_committed_against=95, source="fotmob")
    gk = SeasonGoalkeepingEstimate(sample_size=10, saves_for=30, shots_on_target_faced=40, save_pct=75.0, goals_conceded=10, source="fotmob")
    set_piece = SetPieceThreatFlag(corners_per_game=6.5, opponent_aerial_win_pct=42.0, elevated=True)
    direct_play = DirectPlayExposureFlag(long_ball_share_pct=10.0, opponent_aerial_win_pct=60.0, elevated=False)
    zone = StandingsZoneInfo(position=4, total_teams=20, zone="top-of-table", points_from_boundary=4, in_the_mix=True)
    card = CardDisciplineInfo(yellow_per_game=2.0, red_per_game=0.1, elevated_risk=False)
    card_split = CardDisciplineVenueSplit(at_home_sample_size=5, at_home_yellow_per_game=2.0, at_home_red_per_game=0.1, away_sample_size=5, away_yellow_per_game=2.5, away_red_per_game=0.2, source="football-data")
    rank_record = OpponentRankRecord(sample_size=8, wins=2, draws=1, losses=5)
    presence = [PresenceEntry(name="A", status="P", starting=True, on_bench=False, reason=None)]
    rotation = RotationInfo(changed_players=3, starting_xi_size=11, last_match_date="2026-01-08T00:00:00.000Z", previous_match_date="2026-01-01T00:00:00.000Z", last_formation="4-3-3", previous_formation="4-4-2", formation_changed=True, last_defender_count=4, previous_defender_count=4, preceding_result="W")
    resilience = ResilienceInfo(non_win_sample_size=8, draw_share_pct=37.5)
    rest_perf = RestPerformanceInfo(short_rest_ppg=1.2, short_rest_sample_size=4, long_rest_ppg=2.1, long_rest_sample_size=6)
    fatigue = FatigueFlag(multi_competition=True, competitions=["Premier League", "FA Cup"], avg_gap_days=3.5, flagged=True)
    home_adv = HomeAdvantageInfo(home_win_rate_pct=60.0, away_win_rate_pct=40.0, gap_pct=20.0, strength="strong")
    streak_stab = StreakStabilityInfo(streak_result="W", streak_count=3, changed_players=1, stable=True)
    losing_ctx = __import__("football.types", fromlist=["LosingStreakContextInfo"]).LosingStreakContextInfo(streak_count=3, xg_delta=-1.5, potential_turnaround=True)
    card_risks = [PlayerCardRisk(name="A", yellow_cards=5, red_cards=0, appearances=10, accumulation_risk=True, prior_dismissal=False)]
    referee_note = RefereeCardRiskNote(referee_name="Some Ref", yellow_cards_per_game=3.2, elevated_card_referee=True, flagged_players=[FlaggedPlayer(name="A", side="home", prior_dismissal=False)])
    duel_vulns = [DuelVulnerability(name="A", ground_duel_success_pct=35.5)]
    possession_matchup = PossessionMatchupInfo(high_opponent_possession_ppg=1.2, high_opponent_possession_sample_size=3, other_ppg=2.0, other_sample_size=7)
    corners = SeasonCornersEstimate(sample_size=10, corners_for=55, corners_against=40, source="fotmob")
    def_errors = SeasonDefensiveErrorsEstimate(sample_size=10, defensive_errors_for=3, defensive_errors_against=5, source="fotmob")
    fullback = [FullbackExposureInfo(name="A", chances_created=3, ground_duel_success_pct=48.0)]
    standings_impact = StandingsImpactInfo(current_position=5, current_points=20, scenarios=[StandingsScenario(outcome="win", new_points=23, new_position=3)])
    advanced = _advanced_stats()
    bench_info = BenchInfo(bench_size=7, bench_total_market_value=25_000_000.0, starting_total_market_value=450_000_000.0)
    elo = EloRating(elo=1650.5, as_of="2026-01-01")
    squad_strength = SquadStrengthInfo(total_value=500_000_000.0, attack_value=200_000_000.0, midfield_value=150_000_000.0, defense_value=100_000_000.0, goalkeeper_value=50_000_000.0, available_value=480_000_000.0)
    club_strength = ClubStrengthRating(overall=85.2, attack=80.0, defense=75.0, rank=3, strength_change=1.2)
    travel = TravelInfo(venue_country="England", home_team_country="England", away_team_country="Spain", home_traveling=False, away_traveling=True, home_travel_distance_km=None, away_travel_distance_km=1200.0, home_timezone_diff_hours=None, away_timezone_diff_hours=1.0, home_travel_time_hours=None, away_travel_time_hours=2.5)

    base = {
        "match_type": "competitive",
        "rest_comparison": RestComparison(own_rest_days=5, opponent_rest_days=3, more_rested="own"),
        "experience_comparison": ExperienceComparison(own_average_age=26.0, opponent_average_age=24.0, more_experienced="own"),
        "home_standings_zone": zone, "away_standings_zone": zone,
        "home_card_discipline": card, "away_card_discipline": card,
        "home_card_discipline_venue_split": card_split, "away_card_discipline_venue_split": card_split,
        "home_xg_estimate": xg, "away_xg_estimate": xg,
        "home_shots_estimate": shots, "away_shots_estimate": shots,
        "home_aerial_estimate": aerial, "away_aerial_estimate": aerial,
        "home_big_chances_estimate": big_chances, "away_big_chances_estimate": big_chances,
        "home_passing_style": passing, "away_passing_style": passing,
        "home_fouls_estimate": fouls, "away_fouls_estimate": fouls,
        "home_goalkeeping_estimate": gk, "away_goalkeeping_estimate": gk,
        "home_set_piece_threat": set_piece, "away_set_piece_threat": set_piece,
        "home_direct_play_exposure": direct_play, "away_direct_play_exposure": direct_play,
        "travel_info": travel,
        "home_opponent_rank_record": rank_record, "away_opponent_rank_record": rank_record,
        "home_presence": presence, "away_presence": presence,
        "home_rotation": rotation, "away_rotation": rotation,
        "home_resilience": resilience, "away_resilience": resilience,
        "home_rest_performance": rest_perf, "away_rest_performance": rest_perf,
        "experience_h2h": ExperienceH2HNote(more_experienced="own", h2h_leader="own", aligned=True),
        "home_fatigue_flag": fatigue, "away_fatigue_flag": fatigue,
        "home_advantage": home_adv, "away_advantage": home_adv,
        "home_streak_stability": streak_stab, "away_streak_stability": streak_stab,
        "home_losing_streak_context": losing_ctx, "away_losing_streak_context": losing_ctx,
        "home_card_risks": card_risks, "away_card_risks": card_risks,
        "referee_card_risk_note": referee_note,
        "home_duel_vulnerabilities": duel_vulns, "away_duel_vulnerabilities": duel_vulns,
        "home_possession_matchup": possession_matchup, "away_possession_matchup": possession_matchup,
        "home_corners_estimate": corners, "away_corners_estimate": corners,
        "home_defensive_errors_estimate": def_errors, "away_defensive_errors_estimate": def_errors,
        "home_fullback_exposure": fullback, "away_fullback_exposure": fullback,
        "home_standings_impact": standings_impact, "away_standings_impact": standings_impact,
        "home_advanced_stats": advanced, "away_advanced_stats": advanced,
        "home_bench_info": bench_info, "away_bench_info": bench_info,
        "home_elo_rating": elo, "away_elo_rating": elo,
        "home_squad_strength": squad_strength, "away_squad_strength": squad_strength,
        "home_club_strength": club_strength, "away_club_strength": club_strength,
        "prediction": MatchPrediction(market_implied=probs, heuristic_blend=probs),
        "opponent_context_error": None,
    }
    base.update(overrides)
    return MatchInsights(**base)


def test_insights_markdown_renders_every_field_when_fully_populated():
    insights = _insights_full()
    lines: list[str] = []
    insights_markdown(insights, "Home FC", "Away FC", lines)
    text = "\n".join(lines)
    for expected in [
        "Prediction (market-implied", "Match type: competitive", "Rest: own 5d", "Experience: own avg age 26",
        "Home FC Elo:", "Home FC strength (StatsUltra rating", "Home FC: #4/20", "Home FC: 2 yellow/game", "1650.5",
        "Travel:", "Home FC vs currently-higher-ranked", "Home FC rotation", "Home FC availability",
        "Home FC bench:", "Home FC squad value:", "Home FC resilience:", "Home FC performance by rest",
        "Experience/H2H:", "Home FC fatigue risk", "Home FC home advantage:", "Home FC streak:",
        "Home FC losing streak context", "Home FC card risk:", "Referee Some Ref books", "Home FC defensive duel risk",
        "Home FC vs high-possession", "Home FC corners estimate", "Home FC defensive errors",
        "Home FC attacking-defender exposure", "Home FC new standing if",
    ]:
        assert expected in text, f"missing: {expected!r}"


def test_insights_markdown_opponent_context_error_line():
    insights = _insights_full(opponent_context_error="opponent lookup timed out")
    lines: list[str] = []
    insights_markdown(insights, "Home FC", "Away FC", lines)
    assert any("opponent lookup issue: opponent lookup timed out" in line for line in lines)


def test_insights_markdown_rest_and_experience_even_branches():
    from football.types import ExperienceComparison, RestComparison

    insights = _insights_full(
        rest_comparison=RestComparison(own_rest_days=4, opponent_rest_days=4, more_rested="even"),
        experience_comparison=ExperienceComparison(own_average_age=25.0, opponent_average_age=25.0, more_experienced="even"),
    )
    lines: list[str] = []
    insights_markdown(insights, "Home FC", "Away FC", lines)
    text = "\n".join(lines)
    assert "-- even" in text


def test_insights_markdown_rest_and_experience_without_a_more_rested_side():
    from football.types import ExperienceComparison, RestComparison

    insights = _insights_full(
        rest_comparison=RestComparison(own_rest_days=None, opponent_rest_days=None, more_rested=None),
        experience_comparison=ExperienceComparison(own_average_age=None, opponent_average_age=None, more_experienced=None),
    )
    lines: list[str] = []
    insights_markdown(insights, "Home FC", "Away FC", lines)
    text = "\n".join(lines)
    assert "Rest: own n/a" in text
    assert "Experience: own avg age n/a" in text


# --- remaining small branch gaps ------------------------------------------------------


def test_append_form_recent_results_losing_and_drawing_streak_words():
    from football.types import StreakInfo

    losing = _form_summary_full(current_streak=StreakInfo(result="L", count=2))
    lines: list[str] = []
    form_summary_markdown(losing, lines)
    assert any("2-game losing streak" in line for line in lines)

    drawing = _form_summary_full(current_streak=StreakInfo(result="D", count=2))
    lines2: list[str] = []
    form_summary_markdown(drawing, lines2)
    assert any("2-game drawing streak" in line for line in lines2)


def test_append_profile_performers_renders_bench_and_role_form_sections():
    from football.merge import MergedProfile
    from football.types import PlayerUsagePattern, SquadMember

    frequent_bench = PlayerUsagePattern(matches_in_squad=5, starts=1, sub_appearances=2, unused_bench=2, total_minutes=90, total_goals=1, total_assists=0, total_xg=0.5, total_xa=0.1, total_shots=3, total_shots_on_target=1, total_tackles=0, total_interceptions=0, total_fouls=0, total_key_passes=1, appearances_with_stats=5, avg_rating=6.8, goals_per_90=0.5, assists_per_90=0.0, xg_per_90=0.3, xa_per_90=0.1, key_passes_per_90=0.5)
    starter_usage = PlayerUsagePattern(matches_in_squad=5, starts=5, sub_appearances=0, unused_bench=0, total_minutes=450, total_goals=3, total_assists=2, total_xg=2.5, total_xa=1.5, total_shots=10, total_shots_on_target=5, total_tackles=2, total_interceptions=2, total_fouls=3, total_key_passes=5, appearances_with_stats=5, avg_rating=7.5, goals_per_90=0.6, assists_per_90=0.4, xg_per_90=0.5, xa_per_90=0.3, key_passes_per_90=1.0)

    bench_player = SquadMember(name="Bench Regular", role="M", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=frequent_bench)
    midfielder = SquadMember(name="Starting Mid", role="M", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=starter_usage)
    defender = SquadMember(name="Starting Def", role="D", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=starter_usage)

    p = _all_none(MergedProfile, source="sofascore", team_name="Home FC", squad=[bench_player, midfielder, defender], field_sources={})
    lines: list[str] = []
    merged_profile_markdown(p, lines)
    text = "\n".join(lines)
    assert "Bench regulars (last 20): Bench Regular" in text
    assert "Recent form leaders (last 20):" in text
    assert "Midfielders (last 20, by minutes): Starting Mid" in text
    assert "Defenders (last 20, by minutes): Starting Def" in text


def test_club_strength_str_no_change_note_without_strength_change():
    from football.format_markdown import club_strength_str
    from football.types import ClubStrengthRating

    s = ClubStrengthRating(overall=70.0, attack=65.0, defense=60.0, rank=None, strength_change=None)
    result = club_strength_str(s, "Home")
    assert "vs last check" not in result


def test_streak_stability_str_short_win_streak_uses_winning_word():
    from football.types import StreakStabilityInfo

    s = StreakStabilityInfo(streak_result="W", streak_count=1, changed_players=None, stable=None)
    result = streak_stability_str(s, "Home")
    assert "1-game winning run" in result


def test_streak_stability_str_unknown_without_rotation_data():
    from football.types import StreakStabilityInfo

    s = StreakStabilityInfo(streak_result="W", streak_count=3, changed_players=None, stable=None)
    result = streak_stability_str(s, "Home")
    assert "unknown (no rotation data)" in result
