from football.merge import (
    apply_deep_recent_meetings,
    compute_bench_regulars,
    compute_missing_by_role,
    compute_role_form_breakdown,
    compute_top_defenders,
    compute_top_performers,
    enrich_squad_with_season_stats,
    is_attacker_role,
    is_defender_role,
    is_goalkeeper_role,
    is_midfield_role,
    merge_match_details,
    merge_team_profile,
)
from football.types import (
    DefensiveStats,
    HeadToHeadMeeting,
    MatchDetails,
    PlayerUsagePattern,
    SeasonPlayerStats,
    SquadMember,
    TeamProfile,
)


def _match_details(source, **overrides) -> MatchDetails:
    base = dict(
        source=source,
        source_url=f"https://example.com/{source}",
        competition="Premier League",
        home_team="Liverpool",
        away_team="Arsenal",
        kickoff_utc="2026-09-01T15:00:00.000Z",
        venue=None,
        venue_lat=None,
        venue_lon=None,
        status="scheduled",
        home_score=None,
        away_score=None,
        home_score_ht=None,
        away_score_ht=None,
        season=None,
        round=None,
        match_id="1",
        venue_name=None,
        venue_city=None,
        venue_country=None,
        referee=None,
        referee_stats=None,
        attendance=None,
        weather=None,
        weather_detail=None,
        head_to_head_summary=None,
        head_to_head_streaks=None,
        recent_meetings=None,
        home_lineup=None,
        away_lineup=None,
        home_bench=None,
        away_bench=None,
        home_team_standing=None,
        away_team_standing=None,
        home_team_season_stats=None,
        away_team_season_stats=None,
        match_stats=None,
        event_timeline=None,
        set_piece_goals=None,
        shotmap_stats=None,
        player_of_the_match=None,
        home_formation=None,
        away_formation=None,
        lineup_confirmed=None,
        home_team_country=None,
        away_team_country=None,
        home_manager=None,
        away_manager=None,
        home_manager_vs_away_club=None,
        away_manager_vs_home_club=None,
        standings_table=None,
        home_suspended_players=None,
        away_suspended_players=None,
        note=None,
    )
    base.update(overrides)
    return MatchDetails(**base)


def _team_profile(source, **overrides) -> TeamProfile:
    base = dict(
        source=source,
        team_name="Liverpool",
        squad=None,
        average_age=None,
        injuries=None,
        key_injuries=None,
        recent_transfers=None,
        missing_midfielders=None,
        missing_attackers=None,
        missing_defenders=None,
        missing_goalkeepers=None,
    )
    base.update(overrides)
    return TeamProfile(**base)


def test_merge_match_details_prefers_sofascore_as_base():
    by_source = {
        "fotmob": _match_details("fotmob", venue_name="Emirates"),
        "sofascore": _match_details("sofascore", referee="Michael Oliver"),
    }
    merged = merge_match_details(by_source)
    assert merged.base_source == "sofascore"
    assert merged.referee == "Michael Oliver"


def test_merge_match_details_fills_gaps_in_source_order():
    by_source = {
        "sofascore": _match_details("sofascore"),  # no venue_name
        "fotmob": _match_details("fotmob", venue_name="Anfield"),
    }
    merged = merge_match_details(by_source)
    assert merged.venue_name == "Anfield"
    assert merged.field_sources["venue_name"] == "fotmob"


def test_merge_match_details_collects_notes_from_non_base_sources():
    by_source = {
        "sofascore": _match_details("sofascore"),
        "goal": _match_details("goal", note="referee not populated by Goal.com"),
    }
    merged = merge_match_details(by_source)
    assert len(merged.additional_notes) == 1
    assert merged.additional_notes[0].source == "goal"


def test_merge_team_profile_derives_missing_by_role():
    injuries = [
        SquadMember(name="A", role="Midfielder", injury="hamstring", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
        SquadMember(name="B", role="D", injury="knee", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
    ]
    by_source = {"sofascore": _team_profile("sofascore", injuries=injuries)}
    merged = merge_team_profile(by_source)
    assert merged.missing_midfielders == ["A"]
    assert merged.missing_defenders == ["B"]
    assert merged.missing_attackers == []
    assert merged.missing_goalkeepers == []


def test_enrich_squad_with_season_stats_prefers_higher_priority_source():
    # Regression test: a prior implementation iterated SOURCE_ORDER but
    # unconditionally overwrote each surname's entry on every match, so
    # the LAST source in SOURCE_ORDER with data silently won instead of
    # the first/highest-priority one -- confirmed to also exist in the
    # original TS (Map.set() has the same unconditional-overwrite
    # behavior there). SOURCE_ORDER = (sofascore, fotmob, soccerdesk,
    # goal, 365scores), so fotmob must win over 365scores here.
    stats_fotmob = SeasonPlayerStats(appearances=10, goals=5, assists=1, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    stats_365 = SeasonPlayerStats(appearances=10, goals=99, assists=99, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    member_no_stats = SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)
    member_fotmob = SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=stats_fotmob, season_stats_source="fotmob", defensive_stats=None, recent_usage=None)
    member_365 = SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=stats_365, season_stats_source="365scores", defensive_stats=None, recent_usage=None)

    by_source = {
        "fotmob": _team_profile("fotmob", squad=[member_fotmob]),
        "365scores": _team_profile("365scores", squad=[member_365]),
    }
    result = enrich_squad_with_season_stats([member_no_stats], by_source)
    assert result[0].season_stats.goals == 5
    assert result[0].season_stats_source == "fotmob"


def test_role_matchers_handle_format_variations():
    assert is_midfield_role("M")
    assert is_midfield_role("Midfielder")
    assert is_midfield_role("MIDFIELDER")
    assert not is_midfield_role(None)
    assert not is_midfield_role("Defender")
    assert is_defender_role("D")
    assert is_defender_role("Right-back")
    assert is_defender_role("DEFENDER")
    assert is_attacker_role("F")
    assert is_attacker_role("A")
    assert is_attacker_role("Striker")
    assert is_attacker_role("Forward")
    assert is_goalkeeper_role("G")
    assert is_goalkeeper_role("GK")
    assert is_goalkeeper_role("Goalkeeper")


def test_compute_missing_by_role_none_injuries_is_none_not_empty():
    # None (no injury data at all) must stay distinguishable from an empty
    # list (injury data present, nobody hurt).
    assert compute_missing_by_role(None, is_midfield_role) is None
    assert compute_missing_by_role([], is_midfield_role) == []


def _squad_member(name, goals=0, assists=0, tackles=None, interceptions=None):
    stats = SeasonPlayerStats(appearances=10, goals=goals, assists=assists, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    defensive = DefensiveStats(tackles_made=tackles, interceptions=interceptions, ball_recoveries=None, clearances=None, ground_duel_success_pct=None, chances_created=None) if tackles is not None else None
    return SquadMember(name=name, role=None, injury=None, age=None, market_value=None, season_stats=stats, season_stats_source="sofascore", defensive_stats=defensive, recent_usage=None)


def test_compute_top_performers_sorts_and_excludes_zero():
    squad = [_squad_member("Salah", goals=20), _squad_member("Nunez", goals=5), _squad_member("Alisson", goals=0)]
    top = compute_top_performers(squad, "goals", count=2)
    assert [p.name for p in top] == ["Salah", "Nunez"]


def test_compute_top_defenders_sorts_by_combined_score():
    squad = [_squad_member("VVD", tackles=3, interceptions=1), _squad_member("Konate", tackles=1, interceptions=1)]
    top = compute_top_defenders(squad)
    assert [d.name for d in top] == ["VVD", "Konate"]


def test_compute_bench_regulars_requires_non_start_majority():
    frequent_bench = SquadMember(
        name="Bench Regular", role=None, injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None,
        recent_usage=PlayerUsagePattern(matches_in_squad=5, starts=1, sub_appearances=2, unused_bench=2, total_minutes=90, total_goals=0, total_assists=0, total_xg=0, total_xa=0, total_shots=0, total_shots_on_target=0, total_tackles=0, total_interceptions=0, total_fouls=0, total_key_passes=0, appearances_with_stats=0, avg_rating=None, goals_per_90=None, assists_per_90=None, xg_per_90=None, xa_per_90=None, key_passes_per_90=None),
    )
    mostly_starter = SquadMember(
        name="Starter", role=None, injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None,
        recent_usage=PlayerUsagePattern(matches_in_squad=5, starts=4, sub_appearances=1, unused_bench=0, total_minutes=360, total_goals=0, total_assists=0, total_xg=0, total_xa=0, total_shots=0, total_shots_on_target=0, total_tackles=0, total_interceptions=0, total_fouls=0, total_key_passes=0, appearances_with_stats=0, avg_rating=None, goals_per_90=None, assists_per_90=None, xg_per_90=None, xa_per_90=None, key_passes_per_90=None),
    )
    result = compute_bench_regulars([frequent_bench, mostly_starter])
    assert [b.name for b in result] == ["Bench Regular"]


def _meeting(**overrides) -> HeadToHeadMeeting:
    base = dict(
        date="2026-01-01T00:00:00.000Z", competition="Premier League", scoreline="1-0", venue="home",
        home_formation=None, away_formation=None, home_xg=None, away_xg=None, home_lineup=None, away_lineup=None,
    )
    base.update(overrides)
    return HeadToHeadMeeting(**base)


def test_apply_deep_recent_meetings_clears_fallback_label_when_base_source_wins():
    # Regression test: caught live when the deep Sofascore computation
    # overwrote a SoccerDesk-sourced fallback but field_sources kept
    # claiming "soccerdesk" -- a stale provenance label pointing at data
    # (formations/xG/lineups) that source never actually provided.
    merged = merge_match_details({"sofascore": _match_details("sofascore"), "soccerdesk": _match_details("soccerdesk", recent_meetings=[_meeting()])})
    assert merged.field_sources.get("recent_meetings") == "soccerdesk"

    deep = [_meeting(home_formation="4-3-3", home_xg=1.2)]
    apply_deep_recent_meetings(merged, deep, "sofascore")

    assert merged.recent_meetings == deep
    assert "recent_meetings" not in merged.field_sources  # absence = base source, per convention


def test_apply_deep_recent_meetings_labels_non_base_source():
    merged = merge_match_details({"sofascore": _match_details("sofascore"), "soccerdesk": _match_details("soccerdesk", recent_meetings=[_meeting()])})
    deep = [_meeting(home_formation="4-3-3")]
    # form_source can differ from base_source in edge cases (e.g. sofascore
    # had fixtures but its own details() fetch failed) -- the label must
    # follow whichever source actually produced the deep computation.
    apply_deep_recent_meetings(merged, deep, "goal")
    assert merged.field_sources.get("recent_meetings") == "goal"


def test_apply_deep_recent_meetings_leaves_fallback_when_deep_computation_empty():
    merged = merge_match_details({"sofascore": _match_details("sofascore"), "soccerdesk": _match_details("soccerdesk", recent_meetings=[_meeting()])})
    original = merged.recent_meetings
    apply_deep_recent_meetings(merged, [], "sofascore")
    assert merged.recent_meetings == original
    assert merged.field_sources.get("recent_meetings") == "soccerdesk"
