import asyncio

from football.merge import (
    _fix_defender_count,
    _fix_missing_or_duplicate_gk,
    _validate_lineup_positions,
    apply_deep_recent_meetings,
    annotate_stat_window_notes,
    compute_bench_regulars,
    compute_missing_by_role,
    compute_non_injury_absences,
    compute_recent_form_leaders,
    compute_role_form_breakdown,
    compute_top_defenders,
    compute_top_performers,
    enrich_squad_with_defensive_stats,
    enrich_squad_with_season_stats,
    is_attacker_role,
    is_defender_role,
    is_goalkeeper_role,
    is_midfield_role,
    merge_match_details,
    merge_team_profile,
    reconcile_missing_by_role,
    reconcile_missing_players,
    absent_name_set,
    filter_absent_players,
)
from football.types import (
    DefensiveStats,
    HeadToHeadMeeting,
    LineupPlayer,
    MatchDetails,
    MissingPlayer,
    PlayerUsagePattern,
    SeasonPlayerStats,
    SquadMember,
    TeamProfile,
)


def _lineup_player(name, position):
    return LineupPlayer(
        name=name, position=position, substitute=False, minutes_played=90, goals=0, assists=0,
        xg=None, xa=None, shots=None, shots_on_target=None, tackles=None, interceptions=None,
        fouls=None, rating=None, key_passes=None, shirt_number=None, age=None,
    )


def _match_details(source, **overrides) -> MatchDetails:
    base = {
        "source": source,
        "source_url": f"https://example.com/{source}",
        "competition": "Premier League",
        "home_team": "Liverpool",
        "away_team": "Arsenal",
        "kickoff_utc": "2026-09-01T15:00:00.000Z",
        "venue": None,
        "venue_lat": None,
        "venue_lon": None,
        "status": "scheduled",
        "home_score": None,
        "away_score": None,
        "home_score_ht": None,
        "away_score_ht": None,
        "season": None,
        "round": None,
        "match_id": "1",
        "venue_name": None,
        "venue_city": None,
        "venue_country": None,
        "referee": None,
        "referee_stats": None,
        "attendance": None,
        "weather": None,
        "weather_detail": None,
        "head_to_head_summary": None,
        "head_to_head_streaks": None,
        "recent_meetings": None,
        "home_lineup": None,
        "away_lineup": None,
        "home_bench": None,
        "away_bench": None,
        "home_team_standing": None,
        "away_team_standing": None,
        "home_team_season_stats": None,
        "away_team_season_stats": None,
        "match_stats": None,
        "event_timeline": None,
        "set_piece_goals": None,
        "shotmap_stats": None,
        "player_of_the_match": None,
        "home_formation": None,
        "away_formation": None,
        "lineup_confirmed": None,
        "home_team_country": None,
        "away_team_country": None,
        "home_manager": None,
        "away_manager": None,
        "home_manager_vs_away_club": None,
        "away_manager_vs_home_club": None,
        "standings_table": None,
        "home_suspended_players": None,
        "away_suspended_players": None,
        "note": None,
    }
    base.update(overrides)
    return MatchDetails(**base)


def _team_profile(source, **overrides) -> TeamProfile:
    base = {
        "source": source,
        "team_name": "Liverpool",
        "squad": None,
        "average_age": None,
        "injuries": None,
        "key_injuries": None,
        "recent_transfers": None,
        "missing_midfielders": None,
        "missing_attackers": None,
        "missing_defenders": None,
        "missing_goalkeepers": None,
    }
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


def test_enrich_squad_with_season_stats_unchanged_when_no_source_has_stats():
    member = SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)
    by_source = {"sofascore": _team_profile("sofascore", squad=[member])}
    result = enrich_squad_with_season_stats([member], by_source)
    assert result == [member]


def test_enrich_squad_with_season_stats_leaves_existing_stats_untouched():
    existing_stats = SeasonPlayerStats(appearances=20, goals=10, assists=2, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    other_stats = SeasonPlayerStats(appearances=1, goals=99, assists=99, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    member_with_stats = SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=existing_stats, season_stats_source="sofascore", defensive_stats=None, recent_usage=None)
    member_from_other_source = SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=other_stats, season_stats_source="fotmob", defensive_stats=None, recent_usage=None)
    by_source = {"fotmob": _team_profile("fotmob", squad=[member_from_other_source])}
    result = enrich_squad_with_season_stats([member_with_stats], by_source)
    assert result[0].season_stats is existing_stats


def test_role_matchers_handle_format_variations():
    assert is_midfield_role("M")
    assert is_midfield_role("Midfielder")
    assert is_midfield_role("MIDFIELDER")
    assert not is_midfield_role(None)
    assert not is_midfield_role("Defender")
    assert is_defender_role("D")
    assert is_defender_role("Right-back")
    assert is_defender_role("DEFENDER")
    assert not is_defender_role(None)
    assert is_attacker_role("F")
    assert is_attacker_role("A")
    assert is_attacker_role("Striker")
    assert is_attacker_role("Forward")
    assert not is_attacker_role(None)
    assert is_goalkeeper_role("G")
    assert is_goalkeeper_role("GK")
    assert is_goalkeeper_role("Goalkeeper")
    assert not is_goalkeeper_role(None)


def test_compute_missing_by_role_none_injuries_is_none_not_empty():
    # None (no injury data at all) must stay distinguishable from an empty
    # list (injury data present, nobody hurt).
    assert compute_missing_by_role(None, is_midfield_role) is None
    assert compute_missing_by_role([], is_midfield_role) == []


def _squad_member(name, goals=0, assists=0, tackles=None, interceptions=None, role=None):
    stats = SeasonPlayerStats(appearances=10, goals=goals, assists=assists, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    defensive = DefensiveStats(tackles_made=tackles, interceptions=interceptions, ball_recoveries=None, clearances=None, ground_duel_success_pct=None, chances_created=None) if tackles is not None else None
    return SquadMember(name=name, role=role, injury=None, age=None, market_value=None, season_stats=stats, season_stats_source="sofascore", defensive_stats=defensive, recent_usage=None)


def test_compute_top_performers_sorts_and_excludes_zero():
    squad = [_squad_member("Salah", goals=20), _squad_member("Nunez", goals=5), _squad_member("Alisson", goals=0)]
    top = compute_top_performers(squad, "goals", count=2)
    assert [p.name for p in top] == ["Salah", "Nunez"]
    # Row-level window: season_stats is season-to-date, never last-20.
    assert all(p.window == "season_to_date" for p in top)


def test_compute_top_defenders_sorts_by_combined_score():
    squad = [
        _squad_member("VVD", tackles=3, interceptions=1, role="D"),
        _squad_member("Konate", tackles=1, interceptions=1, role="D"),
    ]
    top = compute_top_defenders(squad)
    assert [d.name for d in top] == ["VVD", "Konate"]


def test_compute_top_defenders_excludes_midfielders():
    """Regression: a high-tackle midfielder (e.g. Kobbie Mainoo, Youri
    Tielemans) previously outranked real defenders since there was no
    role filter at all -- confirmed live across multiple reports."""
    squad = [
        _squad_member("Midfielder With Tackles", tackles=10, interceptions=5, role="M"),
        _squad_member("Real Defender", tackles=2, interceptions=1, role="D"),
    ]
    top = compute_top_defenders(squad)
    assert [d.name for d in top] == ["Real Defender"]


def test_compute_top_defenders_empty_when_no_real_defender_qualifies():
    squad = [_squad_member("Midfielder Only", tackles=10, interceptions=5, role="M")]
    assert compute_top_defenders(squad) == []


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


def test_compute_bench_regulars_excludes_injured_players():
    usage = PlayerUsagePattern(
        matches_in_squad=5, starts=1, sub_appearances=2, unused_bench=2, total_minutes=90, total_goals=0, total_assists=0,
        total_xg=0, total_xa=0, total_shots=0, total_shots_on_target=0, total_tackles=0, total_interceptions=0, total_fouls=0,
        total_key_passes=0, appearances_with_stats=0, avg_rating=None, goals_per_90=None, assists_per_90=None, xg_per_90=None,
        xa_per_90=None, key_passes_per_90=None,
    )
    injured_bench_regular = SquadMember(
        name="Injured Player", role=None, injury="Cruciate Ligament Injury (out)", age=None, market_value=None,
        season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=usage,
    )
    result = compute_bench_regulars([injured_bench_regular])
    assert result == []


def _meeting(**overrides) -> HeadToHeadMeeting:
    base = {
        "date": "2026-01-01T00:00:00.000Z", "competition": "Premier League", "scoreline": "1-0", "venue": "home",
        "home_formation": None, "away_formation": None, "home_xg": None, "away_xg": None, "home_lineup": None, "away_lineup": None,
    }
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


def test_apply_deep_recent_meetings_keeps_older_fallback_meetings_it_could_not_detail():
    # Regression (confirmed live): the deep computation only detailed the
    # newest meeting, and replacing the list dropped the two older ones the
    # fallback source still had.
    old_a = _meeting(date="2025-11-08T12:30:00.000Z")
    old_b = _meeting(date="2025-05-21T19:00:00.000Z")
    newest_shallow = _meeting(date="2026-02-07T12:30:00.000Z")
    merged = merge_match_details({"sofascore": _match_details("sofascore"), "soccerdesk": _match_details("soccerdesk", recent_meetings=[newest_shallow, old_a, old_b])})

    deep = [_meeting(date="2026-02-07T12:30:00.000Z", home_formation="4-2-3-1")]
    apply_deep_recent_meetings(merged, deep, "sofascore")

    assert [m.date[:10] for m in merged.recent_meetings] == ["2026-02-07", "2025-11-08", "2025-05-21"]
    assert merged.recent_meetings[0].home_formation == "4-2-3-1"  # the detailed copy wins the same-date tie
    assert merged.recent_meetings[1].home_formation is None
    # Deep rows (Sofascore) + leftover fallback rows coexist -- neither
    # single source produced the whole list, so provenance is "mixed".
    assert merged.field_sources.get("recent_meetings") == "mixed"


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


def test_apply_deep_recent_meetings_tolerates_none_dates():
    # HeadToHeadMeeting.date is str | None; None used to TypeError on
    # m.date[:10] and kill the entire team run mid-merge.
    merged = merge_match_details({"sofascore": _match_details("sofascore")})
    merged.recent_meetings = [_meeting(date=None)]
    deep = [
        _meeting(date="2026-03-01T12:00:00.000Z", home_formation="4-3-3"),
        _meeting(date=None, home_formation="3-5-2"),
    ]
    apply_deep_recent_meetings(merged, deep, "sofascore")
    assert merged.recent_meetings
    # dated row sorts first; undated rows never crash the merge
    assert merged.recent_meetings[0].date == "2026-03-01T12:00:00.000Z"


def test_apply_deep_recent_meetings_filters_non_h2h_leftovers_and_caps_at_three():
    # Confirmed live (Germany): recent_meetings contained Germany vs
    # Australia rows that were never against the Netherlands, and
    # deep_meetings + leftovers could grow past the documented cap of 3.
    non_h2h = _meeting(date="2025-06-01T00:00:00.000Z", home_team="Germany", away_team="Australia")
    true_h2h = _meeting(date="2025-03-01T00:00:00.000Z", home_team="Germany", away_team="Netherlands")
    # Neither home_team nor away_team populated (pre-frame-fix form-only
    # fallback) -- can't be judged either way, so it must be kept.
    frameless = _meeting(date="2025-01-15T00:00:00.000Z")
    merged = merge_match_details({
        "sofascore": _match_details("sofascore"),
        "soccerdesk": _match_details("soccerdesk", recent_meetings=[non_h2h, true_h2h, frameless]),
    })
    deep = [
        _meeting(date="2026-02-07T12:30:00.000Z", home_formation="4-3-3", home_team="Netherlands", away_team="Germany"),
        _meeting(date="2025-11-08T12:30:00.000Z", home_team="Germany", away_team="Netherlands"),
        _meeting(date="2025-09-01T12:30:00.000Z", home_team="Netherlands", away_team="Germany"),
        _meeting(date="2025-08-01T12:30:00.000Z", home_team="Germany", away_team="Netherlands"),
    ]
    apply_deep_recent_meetings(merged, deep, "sofascore", opponent_name="Netherlands")

    dates = [m.date[:10] for m in merged.recent_meetings]
    # non-H2H leftover (Germany vs Australia) dropped by the opponent filter
    assert "2025-06-01" not in dates
    # 4 deep rows alone already fill the window -- leftover H2H rows that
    # would exceed the cap of 3 are not appended (cap is newest-first).
    assert len(merged.recent_meetings) == 3
    assert dates == ["2026-02-07", "2025-11-08", "2025-09-01"]
    assert dates == sorted(dates, reverse=True)
    assert merged.field_sources.get("recent_meetings") == "mixed"


def test_apply_deep_recent_meetings_keeps_h2h_and_frameless_leftovers_when_under_cap():
    non_h2h = _meeting(date="2025-06-01T00:00:00.000Z", home_team="Germany", away_team="Australia")
    true_h2h = _meeting(date="2025-03-01T00:00:00.000Z", home_team="Germany", away_team="Netherlands")
    frameless = _meeting(date="2025-01-15T00:00:00.000Z")
    merged = merge_match_details({
        "sofascore": _match_details("sofascore"),
        "soccerdesk": _match_details("soccerdesk", recent_meetings=[non_h2h, true_h2h, frameless]),
    })
    deep = [_meeting(date="2026-02-07T12:30:00.000Z", home_formation="4-3-3", home_team="Netherlands", away_team="Germany")]
    apply_deep_recent_meetings(merged, deep, "sofascore", opponent_name="Netherlands")

    dates = [m.date[:10] for m in merged.recent_meetings]
    assert "2025-06-01" not in dates  # non-H2H dropped
    assert "2025-03-01" in dates  # true H2H kept
    assert "2025-01-15" in dates  # frameless kept (teams unknown)
    assert len(merged.recent_meetings) == 3
    assert merged.field_sources.get("recent_meetings") == "mixed"


def test_apply_deep_recent_meetings_leaves_empty_deep_fallback_untouched_even_with_opponent():
    # Deep computation failure must not clobber the earlier fallback --
    # filtering runs only when deep_meetings is non-empty.
    non_h2h = _meeting(date="2025-06-01T00:00:00.000Z", home_team="Germany", away_team="Australia")
    merged = merge_match_details({
        "sofascore": _match_details("sofascore"),
        "soccerdesk": _match_details("soccerdesk", recent_meetings=[non_h2h]),
    })
    original = merged.recent_meetings
    apply_deep_recent_meetings(merged, [], "sofascore", opponent_name="Netherlands")
    assert merged.recent_meetings == original


def test_text_conflict_resolution_flags_completely_different_places_as_wrong_fixture():
    # Confirmed live: Sofascore said venue_city=Amsterdam while Fotmob's
    # venueDetails said Karlsruhe -- zero shared tokens means one source
    # matched the wrong fixture entirely, not a spelling variant.
    from football.merge import _text_conflict_resolution

    resolution = _text_conflict_resolution(
        "venue_city", "sofascore", {"sofascore": "Amsterdam", "fotmob": "Karlsruhe"}, "Amsterdam",
    )
    assert "different fixture" in resolution
    assert "reported, not overridden" in resolution


def test_text_conflict_resolution_keeps_plain_note_for_spelling_variants():
    from football.merge import _text_conflict_resolution

    resolution = _text_conflict_resolution(
        "venue_name", "sofascore", {"sofascore": "Old Trafford", "fotmob": "Old Trafford Stadium"}, "Old Trafford",
    )
    assert "different fixture" not in resolution
    assert "text disagreements are reported, not overridden" in resolution


def test_merge_match_details_wrong_fixture_city_conflict_resolution():
    # End-to-end: base kept, conflict reported, resolution upgraded to
    # wrong-fixture (not the generic "text disagreements" note).
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", venue_city="Amsterdam"),
        "fotmob": _match_details("fotmob", venue_city="Karlsruhe"),
    })
    assert merged.venue_city == "Amsterdam"
    (conflict,) = merged.source_conflicts
    assert conflict.field == "venue_city"
    assert "different fixture" in conflict.resolution


def test_merge_absences_into_profile_injuries_adds_injury_absences_and_skips_non_injury():
    # Confirmed live (Germany): match.missing_players had five entries
    # while profile.injuries only listed two -- the two lists are
    # independently sourced.
    from football.merge import merge_absences_into_profile_injuries

    malen = SquadMember(
        name="Malen", role="F", injury="Unknown", age=None, market_value=40_000_000.0,
        season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None,
    )
    profile = _team_profile("sofascore", injuries=[malen], key_injuries=[malen])
    missing = [
        MissingPlayer(name="De Jong", description="Knee Injury", expected_return="3 months"),
        MissingPlayer(name="Malen", description="Unknown", expected_return=None),  # already known
        MissingPlayer(name="Richarlison", description="coach_decision", expected_return=None),  # non-injury
    ]
    merge_absences_into_profile_injuries(profile, missing)

    names = [m.name for m in profile.injuries or []]
    assert "De Jong" in names  # injury absence folded in
    assert names.count("Malen") == 1  # no duplicate
    assert "Richarlison" not in names  # coach_decision stays off injuries
    # key_injuries re-ranked over the expanded list; non-squad addition
    # has no market value so it sorts off the key list (we know less).
    assert [m.name for m in profile.key_injuries or []] == ["Malen"]


def test_merge_absences_into_profile_injuries_noop_when_either_side_empty():
    from football.merge import merge_absences_into_profile_injuries

    # missing_players empty -> no change (even if injuries was None)
    profile = _team_profile("sofascore", injuries=None)
    merge_absences_into_profile_injuries(profile, None)
    merge_absences_into_profile_injuries(profile, [])
    assert profile.injuries is None
    # profile itself None -> no crash
    merge_absences_into_profile_injuries(None, [MissingPlayer(name="X", description="Knee", expected_return=None)])  # type: ignore[arg-type]
    # injuries None but missing has an injury -> populates from None
    profile2 = _team_profile("sofascore", injuries=None)
    merge_absences_into_profile_injuries(profile2, [MissingPlayer(name="X", description="Knee", expected_return=None)])
    assert [m.name for m in profile2.injuries or []] == ["X"]


# --- empty/None-squad guards across the compute_* leaderboard functions --------------------


def test_compute_top_performers_empty_without_squad():
    assert compute_top_performers(None, "goals") == []
    assert compute_top_performers([], "goals") == []


def test_compute_top_defenders_empty_without_squad():
    assert compute_top_defenders(None) == []
    assert compute_top_defenders([]) == []


def test_compute_bench_regulars_empty_without_squad():
    assert compute_bench_regulars(None) == []
    assert compute_bench_regulars([]) == []


def test_compute_role_form_breakdown_empty_without_squad():
    assert compute_role_form_breakdown(None, is_midfield_role) == []
    assert compute_role_form_breakdown([], is_midfield_role) == []


def _usage(**overrides) -> PlayerUsagePattern:
    base = {
        "matches_in_squad": 5, "starts": 4, "sub_appearances": 1, "unused_bench": 0, "total_minutes": 360,
        "total_goals": 2, "total_assists": 1, "total_xg": 1.5, "total_xa": 0.8, "total_shots": 10,
        "total_shots_on_target": 5, "total_tackles": 3, "total_interceptions": 2, "total_fouls": 1,
        "total_key_passes": 4, "appearances_with_stats": 5, "avg_rating": 7.1, "goals_per_90": 0.5,
        "assists_per_90": 0.25, "xg_per_90": 0.4, "xa_per_90": 0.2, "key_passes_per_90": 1.0,
    }
    base.update(overrides)
    return PlayerUsagePattern(**base)


def _squad_member_with_usage(name, role, **usage_overrides) -> SquadMember:
    return SquadMember(
        name=name, role=role, injury=None, age=None, market_value=None, season_stats=None,
        season_stats_source=None, defensive_stats=None, recent_usage=_usage(**usage_overrides),
    )


def test_compute_role_form_breakdown_filters_by_role_and_ranks_by_minutes():
    midfielder = _squad_member_with_usage("Rodri", "M", total_minutes=500)
    other_midfielder = _squad_member_with_usage("Bellingham", "Midfielder", total_minutes=300)
    defender = _squad_member_with_usage("VVD", "D", total_minutes=900)
    result = compute_role_form_breakdown([midfielder, other_midfielder, defender], is_midfield_role)
    assert [r.name for r in result] == ["Rodri", "Bellingham"]


def test_compute_role_form_breakdown_excludes_unused_players():
    unused = _squad_member_with_usage("Benched", "M", matches_in_squad=0)
    result = compute_role_form_breakdown([unused], is_midfield_role)
    assert result == []


def test_compute_recent_form_leaders_empty_without_squad():
    assert compute_recent_form_leaders(None) == []
    assert compute_recent_form_leaders([]) == []


def test_compute_recent_form_leaders_ranks_by_goals_plus_assists():
    top = _squad_member_with_usage("Salah", "F", total_goals=5, total_assists=3)
    quiet = _squad_member_with_usage("Backup", "F", total_goals=0, total_assists=0)
    result = compute_recent_form_leaders([top, quiet])
    assert [r.name for r in result] == ["Salah"]
    assert all(r.window == "last_20" for r in result)


def test_compute_recent_form_leaders_excludes_a_currently_injured_player():
    # Confirmed live: a player out for months on a cruciate ligament
    # injury still topped this list on the strength of matches played
    # before getting hurt.
    injured_top = SquadMember(
        name="Xavi Simons", role="M", injury="Cruciate Ligament Injury", age=None, market_value=None,
        season_stats=None, season_stats_source=None, defensive_stats=None,
        recent_usage=_usage(total_goals=3, total_assists=1),
    )
    fit = _squad_member_with_usage("Richarlison", "F", total_goals=4, total_assists=0)
    result = compute_recent_form_leaders([injured_top, fit])
    assert [r.name for r in result] == ["Richarlison"]


# --- merge_team_profile squad enrichment branch ---------------------------------------------


def test_merge_team_profile_enriches_squad_with_season_stats_when_present():
    stats = SeasonPlayerStats(appearances=10, goals=5, assists=1, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    member_with_stats = SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=stats, season_stats_source="fotmob", defensive_stats=None, recent_usage=None)
    member_without_stats = SquadMember(name="Some Other Player", role="M", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)

    by_source = {
        "sofascore": _team_profile("sofascore", squad=[member_without_stats]),
        "fotmob": _team_profile("fotmob", squad=[member_with_stats]),
    }
    merged = merge_team_profile(by_source)
    assert merged.squad is not None
    names = {m.name: m for m in merged.squad}
    assert "Some Other Player" in names


# --- enrich_squad_with_defensive_stats (async) -----------------------------------------------


def test_enrich_squad_with_defensive_stats_attaches_matching_stats(monkeypatch):
    stats = DefensiveStats(tackles_made=3, interceptions=1, ball_recoveries=None, clearances=None, ground_duel_success_pct=None, chances_created=None)

    async def fake_get_stats(_team_name, _competition_candidates):
        return {"mohamed salah": stats}

    monkeypatch.setattr("football.sites.squawka.get_squawka_defensive_stats", fake_get_stats)
    squad = [SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)]
    result = asyncio.run(enrich_squad_with_defensive_stats(squad, "Liverpool", ["Premier League"]))
    assert result[0].defensive_stats == stats


def test_enrich_squad_with_defensive_stats_unchanged_without_a_match(monkeypatch):
    async def fake_get_stats(_team_name, _competition_candidates):
        return {"someone else": DefensiveStats(tackles_made=1, interceptions=0, ball_recoveries=None, clearances=None, ground_duel_success_pct=None, chances_created=None)}

    monkeypatch.setattr("football.sites.squawka.get_squawka_defensive_stats", fake_get_stats)
    squad = [SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)]
    result = asyncio.run(enrich_squad_with_defensive_stats(squad, "Liverpool", ["Premier League"]))
    assert result[0].defensive_stats is None


def test_enrich_squad_with_defensive_stats_returns_squad_unchanged_when_fetch_raises(monkeypatch):
    async def failing_get_stats(_team_name, _competition_candidates):
        raise RuntimeError("boom")

    monkeypatch.setattr("football.sites.squawka.get_squawka_defensive_stats", failing_get_stats)
    squad = [SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)]
    result = asyncio.run(enrich_squad_with_defensive_stats(squad, "Liverpool", ["Premier League"]))
    assert result[0].defensive_stats is None


def test_enrich_squad_with_defensive_stats_empty_result_returns_squad_unchanged(monkeypatch):
    async def fake_get_stats(_team_name, _competition_candidates):
        return {}

    monkeypatch.setattr("football.sites.squawka.get_squawka_defensive_stats", fake_get_stats)
    squad = [SquadMember(name="Mohamed Salah", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)]
    result = asyncio.run(enrich_squad_with_defensive_stats(squad, "Liverpool", ["Premier League"]))
    assert result == squad


# --- _validate_lineup_positions / _fix_missing_or_duplicate_gk / _fix_defender_count --------


def test_fix_defender_count_promotes_midfielder_closest_to_goalkeeper():
    """Regression for the Everton vs Man Utd 2026-09-06 report: formation
    4-2-3-1 needs 4 defenders but only 3 are tagged D, with the real
    mistagged fullback (Röhl) sitting right after the GK and three
    genuine attacking midfielders listed after him. The fix must promote
    Röhl (first M in list order), not the last M in the list."""
    lineup = [
        _lineup_player("Pickford", "G"),
        _lineup_player("Röhl", "M"),  # actually a fullback, mistagged
        _lineup_player("Tarkowski", "D"),
        _lineup_player("Branthwaite", "D"),
        _lineup_player("Mykolenko", "D"),
        _lineup_player("Armstrong", "M"),
        _lineup_player("Garner", "M"),
        _lineup_player("Johnson", "F"),
        _lineup_player("Dewsbury-Hall", "M"),
        _lineup_player("George", "F"),
        _lineup_player("Barry", "F"),
    ]
    result = _validate_lineup_positions(lineup, "4-2-3-1")
    by_name = {p.name: p.position for p in result}
    assert by_name["Röhl"] == "D"
    assert by_name["Dewsbury-Hall"] == "M"  # not the one reclassified


def test_fix_defender_count_demotes_trailing_excess_defenders():
    lineup = [
        _lineup_player("GK", "G"),
        _lineup_player("D1", "D"),
        _lineup_player("D2", "D"),
        _lineup_player("D3", "D"),
        _lineup_player("D4", "D"),
        _lineup_player("D5", "D"),  # excess -- should become M
        _lineup_player("M1", "M"),
    ]
    fixed = _fix_defender_count(lineup, expected_def=4)
    assert fixed is None  # mutates in place
    by_name = {p.name: p.position for p in lineup}
    assert by_name["D5"] == "M"
    assert by_name["D4"] == "D"


def test_fix_defender_count_noop_when_count_matches():
    lineup = [_lineup_player("D1", "D"), _lineup_player("M1", "M")]
    original = list(lineup)
    _fix_defender_count(lineup, expected_def=1)
    assert lineup == original


def test_fix_missing_gk_reclassifies_unpositioned_player():
    lineup = [_lineup_player("A", None), _lineup_player("B", "D")]
    _fix_missing_or_duplicate_gk(lineup, formation="4-4-2")
    assert lineup[0].position == "G"


def test_fix_duplicate_gk_keeps_first_reclassifies_rest():
    lineup = [_lineup_player("A", "G"), _lineup_player("B", "G")]
    _fix_missing_or_duplicate_gk(lineup, formation="4-4-2")
    assert lineup[0].position == "G"
    assert lineup[1].position == "M"


def test_validate_lineup_positions_none_lineup_passthrough():
    assert _validate_lineup_positions(None, "4-4-2") is None
    assert _validate_lineup_positions([], "4-4-2") == []


def test_validate_lineup_positions_returns_unchanged_without_formation():
    lineup = [_lineup_player("A", "M")]
    result = _validate_lineup_positions(lineup, None)
    assert result[0].position == "M"


def test_enrich_squad_with_season_stats_avoids_surname_collision():
    """Regression for Everton's Jordan Pickford / George Pickford
    collision: two players in the TARGET squad share a surname, so the
    bare-surname fallback must not fire for either -- only an exact
    full-name match may attach season stats in that case."""
    jordan_stats = SeasonPlayerStats(appearances=2, goals=0, assists=0, yellow_cards=0, red_cards=0, rating=7.75, expected_goals=None)
    jordan_source = SquadMember(name="Jordan Pickford", role="G", injury=None, age=None, market_value=None, season_stats=jordan_stats, season_stats_source="fotmob", defensive_stats=None, recent_usage=None)

    jordan_target = SquadMember(name="Jordan Pickford", role="G", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)
    george_target = SquadMember(name="George Pickford", role="G", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)

    by_source = {"fotmob": _team_profile("fotmob", squad=[jordan_source])}
    result = enrich_squad_with_season_stats([jordan_target, george_target], by_source)
    by_name = {m.name: m for m in result}

    assert by_name["Jordan Pickford"].season_stats == jordan_stats  # exact full-name match
    assert by_name["George Pickford"].season_stats is None  # surname alone must not attach it


def test_enrich_squad_with_season_stats_surname_fallback_when_unambiguous():
    stats = SeasonPlayerStats(appearances=10, goals=5, assists=1, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    # Goal.com abbreviates first names -- "A. Becker" can only be matched
    # to "Alisson Becker" by surname.
    source_member = SquadMember(name="A. Becker", role="G", injury=None, age=None, market_value=None, season_stats=stats, season_stats_source="goal", defensive_stats=None, recent_usage=None)
    target_member = SquadMember(name="Alisson Becker", role="G", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)

    by_source = {"goal": _team_profile("goal", squad=[source_member])}
    result = enrich_squad_with_season_stats([target_member], by_source)
    assert result[0].season_stats == stats
    assert result[0].season_stats_source == "goal"


# --- reconcile_missing_players -----------------------------------------------------------


def test_reconcile_missing_players_adds_profile_injury_not_in_match_list():
    """Regression: confirmed live (repeatedly) -- Pedro Porro was
    correctly flagged in teamProfile.injuries/missing_defenders but
    silently absent from match.away_missing_players, since the two
    lists were never cross-referenced."""
    existing = [MissingPlayer(name="Manuel Ugarte", description="Cruciate Ligament Injury", expected_return="2027-04-10T00:00:00+00:00")]
    profile_injuries = [
        SquadMember(name="Manuel Ugarte", role="M", injury="Cruciate Ligament Injury", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
        SquadMember(name="Pedro Porro", role="D", injury="Physical Discomfort (out)", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
    ]
    result = reconcile_missing_players(existing, profile_injuries)
    names = [p.name for p in result]
    assert names == ["Manuel Ugarte", "Pedro Porro"]  # existing entries first, unchanged
    porro = next(p for p in result if p.name == "Pedro Porro")
    assert porro.description == "Physical Discomfort (out)"
    assert porro.expected_return is None


def test_reconcile_missing_players_none_when_both_empty():
    assert reconcile_missing_players(None, None) is None
    # Confirmed-empty [] stays [] (checked, none missing) -- not collapsed
    # back to None, which would mean "no source told us".
    assert reconcile_missing_players([], []) == []


def test_reconcile_missing_players_keeps_match_list_when_no_profile_injuries():
    existing = [MissingPlayer(name="Player", description="Knock", expected_return=None)]
    result = reconcile_missing_players(existing, None)
    assert result == existing


# --- absent_name_set / filter_absent_players (N1: bench must not list the missing) ---


def test_absent_name_set_unions_missing_suspended_and_injuries():
    missing = [MissingPlayer(name="Richarlison", description="coach_decision", expected_return=None)]
    injuries = [SquadMember(name="Pedro Porro", role="D", injury="Knock", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)]
    result = absent_name_set(missing, ["Manuel Ugarte"], injuries)
    assert "richarlison" in result
    assert "manuel ugarte" in result
    assert "pedro porro" in result


def test_absent_name_set_empty_when_nothing_ruled_out():
    assert absent_name_set(None, None) == set()
    assert absent_name_set([], []) == set()


def test_filter_absent_players_removes_injured_from_published_bench():
    bench = [
        _lineup_player("Fit Sub", "M"),
        _lineup_player("Richarlison", "F"),
        _lineup_player("Xavi Simons", "M"),
    ]
    absent = {"richarlison", "xavi simons"}
    kept = filter_absent_players(bench, absent)
    assert [p.name for p in kept] == ["Fit Sub"]


def test_filter_absent_players_none_stays_none_and_empty_absent_is_noop():
    assert filter_absent_players(None, {"anyone"}) is None
    players = [_lineup_player("A", "M")]
    assert filter_absent_players(players, set()) is players


def test_filter_absent_players_all_filtered_becomes_empty_not_none():
    # Distinguish "we checked, nobody remains" from "never published".
    bench = [_lineup_player("Richarlison", "F")]
    assert filter_absent_players(bench, {"richarlison"}) == []


def test_filter_absent_players_uses_containment_for_name_spelling_gaps():
    bench = [_lineup_player("Chido Obi-Martin", "F"), _lineup_player("Other", "M")]
    kept = filter_absent_players(bench, {"chido obi"})
    assert [p.name for p in kept] == ["Other"]


# --- reconcile_missing_by_role -----------------------------------------------------------


def test_reconcile_missing_by_role_includes_missing_player_not_in_injuries():
    """Regression: confirmed live -- Richarlison (ruled out for
    "coach_decision", a forward) was absent from missing_attackers
    despite being unavailable, since that field only ever looked at
    `injuries`, never match-level missing_players."""
    from football.merge import is_attacker_role

    squad = [
        SquadMember(name="Richarlison", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
        SquadMember(name="Injured Mid", role="M", injury="Hamstring", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
    ]
    injuries = [squad[1]]  # only the midfielder is in the injuries list
    missing_players = [MissingPlayer(name="Richarlison", description="coach_decision", expected_return=None)]

    attackers = reconcile_missing_by_role(squad, injuries, missing_players, is_attacker_role)
    assert attackers == ["Richarlison"]


def test_reconcile_missing_by_role_none_when_injuries_unavailable():
    from football.merge import is_attacker_role

    assert reconcile_missing_by_role([], None, [MissingPlayer(name="X", description="Y", expected_return=None)], is_attacker_role) is None


def test_reconcile_missing_by_role_skips_missing_player_with_wrong_role():
    from football.merge import is_attacker_role

    squad = [SquadMember(name="A Defender", role="D", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)]
    missing_players = [MissingPlayer(name="A Defender", description="Suspended", expected_return=None)]
    assert reconcile_missing_by_role(squad, [], missing_players, is_attacker_role) == []


def test_confirmed_empty_suspended_list_survives_the_merge_instead_of_staying_none():
    base = _match_details("sofascore")
    other = _match_details("soccerdesk", home_suspended_players=[], away_suspended_players=["Banned Player"])
    merged = merge_match_details({"sofascore": base, "soccerdesk": other})
    assert merged.home_suspended_players == []  # "checked, nobody" is kept
    assert merged.away_suspended_players == ["Banned Player"]
    assert merged.field_sources["home_suspended_players"] == "soccerdesk"


# --- non_injury_absences / stat_window_note ------------------------------------


def test_compute_non_injury_absences_names_missing_player_not_in_injuries():
    """Confirmed live: Richarlison (coach_decision) sits on
    missing_attackers after reconcile but not in injuries."""
    from football.types import TeamProfile

    squad = [
        SquadMember(name="Richarlison", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
        SquadMember(name="Injured Mid", role="M", injury="Hamstring", age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None),
    ]
    profile = TeamProfile(
        source="sofascore", team_name="Spurs", squad=squad, average_age=None,
        injuries=[squad[1]], key_injuries=None, recent_transfers=None,
        missing_midfielders=["Injured Mid"], missing_attackers=["Richarlison"],
        missing_defenders=None, missing_goalkeepers=None,
    )
    assert compute_non_injury_absences(profile) == ["Richarlison"]


def test_compute_non_injury_absences_none_when_everyone_is_an_injury_or_lists_missing():
    from football.types import TeamProfile

    only_injury = TeamProfile(
        source="sofascore", team_name="T", squad=None, average_age=None,
        injuries=None, key_injuries=None, recent_transfers=None,
        missing_midfielders=None, missing_attackers=None,
        missing_defenders=None, missing_goalkeepers=None,
    )
    assert compute_non_injury_absences(only_injury) is None
    assert compute_non_injury_absences(None) is None


def test_annotate_stat_window_notes_flags_season_vs_recent_goal_mismatch():
    """Gallagher-style row: season_stats.goals=1, recent_usage.total_goals=2."""
    season = SeasonPlayerStats(appearances=3, goals=1, assists=0, yellow_cards=0, red_cards=0, rating=7.1, expected_goals=None)
    member = SquadMember(
        name="Conor Gallagher", role="M", injury=None, age=None, market_value=None,
        season_stats=season, season_stats_source="sofascore", defensive_stats=None,
        recent_usage=_usage(total_goals=2),
    )
    annotate_stat_window_notes([member])
    assert member.stat_window_note is not None
    assert "season_stats.goals=1" in member.stat_window_note
    assert "recent_usage.total_goals=2" in member.stat_window_note
    assert "season to date" in member.stat_window_note
    assert "last 20" in member.stat_window_note


def test_annotate_stat_window_notes_none_when_windows_agree_or_one_side_missing():
    season = SeasonPlayerStats(appearances=5, goals=2, assists=1, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    agree = SquadMember(
        name="Agree", role="F", injury=None, age=None, market_value=None,
        season_stats=season, season_stats_source="sofascore", defensive_stats=None,
        recent_usage=_usage(total_goals=2),
    )
    only_season = SquadMember(
        name="Only Season", role="F", injury=None, age=None, market_value=None,
        season_stats=season, season_stats_source="sofascore", defensive_stats=None,
        recent_usage=None,
    )
    # Stale note from a previous run must be cleared when figures agree.
    agree.stat_window_note = "stale"
    annotate_stat_window_notes([agree, only_season])
    assert agree.stat_window_note is None
    assert only_season.stat_window_note is None


def test_unknown_suspended_stays_none_when_no_source_knows():
    merged = merge_match_details({"sofascore": _match_details("sofascore"), "soccerdesk": _match_details("soccerdesk")})
    assert merged.home_suspended_players is None



def test_canonical_role_maps_every_sources_spelling_to_g_d_m_f():
    from football.merge import canonical_role

    for raw, expected in [
        ("G", "G"), ("Keeper", "G"), ("Goalkeeper", "G"), ("GOALKEEPER", "G"),
        ("D", "D"), ("Defender", "D"), ("DEFENDER", "D"), ("Right-back", "D"),
        ("M", "M"), ("Midfielder", "M"), ("MIDFIELDER", "M"),
        ("F", "F"), ("Attacker", "F"), ("Forward", "F"), ("Striker", "F"), ("A", "F"),
    ]:
        assert canonical_role(raw) == expected, raw
    assert canonical_role(None) is None
    assert canonical_role("Coach") == "Coach"  # unrecognized passes through


def test_merge_team_profile_gives_squad_and_injuries_one_role_vocabulary():
    squad = [_squad_member("A", role="Keeper"), _squad_member("B", role="Defender"), _squad_member("C", role="Midfielder"), _squad_member("D", role="Attacker")]
    base = _team_profile("fotmob", squad=squad, injuries=[_squad_member("B", role="Defender")])
    merged = merge_team_profile({"fotmob": base})
    assert [m.role for m in merged.squad] == ["G", "D", "M", "F"]
    assert [m.role for m in merged.injuries] == ["D"]
    assert merged.missing_defenders == ["B"]


# --- source conflicts / reliability weighting ---------------------------------------------------


def test_no_conflict_when_sources_agree_or_one_simply_lacks_the_value():
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", attendance=60000, venue_name="Old Trafford"),
        "fotmob": _match_details("fotmob", attendance=60000, venue_name="Old Trafford"),
        "goal": _match_details("goal", attendance=None, venue_name=None),
    })
    assert merged.source_conflicts == []


def test_one_dissenting_source_does_not_override_the_base_number():
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", attendance=60000),
        "fotmob": _match_details("fotmob", attendance=61234),
    })
    assert merged.attendance == 60000  # sofascore weight 3 beats fotmob 2
    (conflict,) = merged.source_conflicts
    assert (conflict.field, conflict.kept, conflict.kept_source) == ("attendance", 60000, "sofascore")
    assert [(a.from_source, a.value) for a in conflict.alternatives] == [("fotmob", 61234)]
    assert conflict.resolution == "sofascore kept"


def test_two_mid_tier_sources_that_agree_outvote_the_base_on_a_number():
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", venue_capacity=74000),
        "fotmob": _match_details("fotmob", venue_capacity=74310),
        "goal": _match_details("goal", venue_capacity=74310),
    })
    assert merged.venue_capacity == 74310
    assert merged.field_sources["venue_capacity"] == "fotmob"
    (conflict,) = merged.source_conflicts
    assert conflict.kept_source == "fotmob"
    assert conflict.resolution == "weighted vote: 2 sources agree"
    assert [(a.from_source, a.value) for a in conflict.alternatives] == [("sofascore", 74000)]


def test_a_number_won_by_the_base_after_a_fallback_label_clears_the_label():
    # base is sofascore; the vote goes to the base -> no fallback label
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", attendance=50000),
        "fotmob": _match_details("fotmob", attendance=50001),
        "soccerdesk": _match_details("soccerdesk", attendance=50002),
    })
    assert merged.attendance == 50000
    assert "attendance" not in merged.field_sources


def test_text_disagreements_are_reported_but_never_override_the_base_spelling():
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", referee="Michael Oliver"),
        "fotmob": _match_details("fotmob", referee="Anthony Taylor"),
        "goal": _match_details("goal", referee="Anthony Taylor"),
    })
    assert merged.referee == "Michael Oliver"
    (conflict,) = merged.source_conflicts
    assert conflict.field == "referee"
    assert "reported, not overridden" in conflict.resolution
    assert {a.value for a in conflict.alternatives} == {"Anthony Taylor"}


def test_different_spellings_of_the_same_name_are_not_a_conflict():
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", venue_name="Old Trafford"),
        "fotmob": _match_details("fotmob", venue_name="Old Trafford Stadium"),
        "goal": _match_details("goal", venue_name="Old Trafford"),
    })
    assert merged.source_conflicts == []


def test_score_disagreement_between_finished_match_sources_is_settled_by_vote():
    merged = merge_match_details({
        "sofascore": _match_details("sofascore", home_score=2, away_score=1),
        "fotmob": _match_details("fotmob", home_score=3, away_score=1),
        "goal": _match_details("goal", home_score=3, away_score=1),
    })
    assert (merged.home_score, merged.away_score) == (3, 1)
    assert [c.field for c in merged.source_conflicts] == ["home_score"]


def test_source_weights_rank_the_base_highest_and_a_single_other_source_below_it():
    from football.merge import SOURCE_ORDER, SOURCE_WEIGHTS

    assert set(SOURCE_WEIGHTS) == set(SOURCE_ORDER)
    assert SOURCE_WEIGHTS[SOURCE_ORDER[0]] == max(SOURCE_WEIGHTS.values())
    assert SOURCE_WEIGHTS[SOURCE_ORDER[0]] < SOURCE_WEIGHTS["fotmob"] + SOURCE_WEIGHTS["goal"]
    assert all(SOURCE_WEIGHTS[SOURCE_ORDER[0]] > w for s, w in SOURCE_WEIGHTS.items() if s != SOURCE_ORDER[0])


# --- find_by_name_containment --------------------------------------------------------------------


def test_find_by_name_containment_matches_a_shortened_hyphenated_surname():
    # Confirmed live: Sofascore's "Chido Obi-Martin" vs Fotmob's "Chido Obi"
    # for the same Man Utd player -- neither exact match nor surname()
    # (comparing "obi-martin" to "obi") catches this.
    from football.merge import find_by_name_containment

    candidates = {"chido obi martin": "real-stats"}
    assert find_by_name_containment("Chido Obi", candidates) == "real-stats"


def test_find_by_name_containment_works_in_either_direction():
    from football.merge import find_by_name_containment

    assert find_by_name_containment("Chido Obi Martin", {"chido obi": "x"}) == "x"


def test_find_by_name_containment_none_when_ambiguous_or_too_short():
    from football.merge import find_by_name_containment

    # "obi" alone would risk matching an unrelated "Obiora" -- two
    # candidates both containing it must not silently pick either.
    assert find_by_name_containment("Obi", {"chido obi martin": "a", "sam obiora": "b"}) is None
    assert find_by_name_containment("Al", {"al smith": "x"}) is None  # below the length floor


def test_enrich_squad_with_season_stats_falls_back_to_containment_after_surname_fails():
    # Confirmed live: Sofascore's own squad has "Chido Obi-Martin" but the
    # own team's squad here (whichever source lacks his stats) has just
    # "Chido Obi" -- surname() alone ("obi martin" vs "obi") still misses it.
    fotmob_named = SquadMember(name="Chido Obi", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)
    full_stats = SeasonPlayerStats(appearances=5, goals=5, assists=1, yellow_cards=0, red_cards=0, rating=None, expected_goals=None)
    sourced = SquadMember(name="Chido Obi-Martin", role="F", injury=None, age=None, market_value=None, season_stats=full_stats, season_stats_source="sofascore", defensive_stats=None, recent_usage=None)
    result = enrich_squad_with_season_stats([fotmob_named], {"sofascore": _team_profile("sofascore", squad=[sourced])})
    assert result[0].season_stats.goals == 5


def test_enrich_squad_with_defensive_stats_falls_back_to_containment(monkeypatch):
    async def fake(_team_name, _competitions):
        return {"chido obi martin": DefensiveStats(tackles_made=3, interceptions=None, ball_recoveries=None, clearances=None, ground_duel_success_pct=None, chances_created=None)}

    monkeypatch.setattr("football.sites.squawka.get_squawka_defensive_stats", fake)
    squad = [SquadMember(name="Chido Obi", role="F", injury=None, age=None, market_value=None, season_stats=None, season_stats_source=None, defensive_stats=None, recent_usage=None)]
    result = asyncio.run(enrich_squad_with_defensive_stats(squad, "Man Utd", ["Premier League"]))
    assert result[0].defensive_stats.tackles_made == 3


# --- is_match_details_complete / is_profile_complete ---------------------------------------------


def test_is_match_details_complete_false_for_a_pre_match_fixture_missing_referee_lineups_etc():
    from football.merge import is_match_details_complete

    details = _match_details("sofascore")  # every merge field left None by the fixture
    assert is_match_details_complete(details) is False


def test_is_match_details_complete_true_once_every_merge_field_is_populated():
    from football.merge import _MATCH_MERGE_FIELDS, is_match_details_complete

    details = _match_details("sofascore", **dict.fromkeys(_MATCH_MERGE_FIELDS, "x"))
    assert is_match_details_complete(details) is True


def test_is_match_details_complete_true_when_confirmed_empty_suspended_lists_count_as_filled():
    from football.merge import _MATCH_MERGE_FIELDS, is_match_details_complete

    overrides = dict.fromkeys(_MATCH_MERGE_FIELDS, "x")
    overrides["home_suspended_players"] = []
    overrides["away_suspended_players"] = []
    assert is_match_details_complete(_match_details("sofascore", **overrides)) is True


def test_is_profile_complete_false_until_every_profile_field_is_populated_then_true():
    from football.merge import _PROFILE_MERGE_FIELDS, is_profile_complete

    empty = _team_profile("sofascore")
    assert is_profile_complete(empty) is False
    full = _team_profile("sofascore", **dict.fromkeys(_PROFILE_MERGE_FIELDS, "x"))
    assert is_profile_complete(full) is True


# --- _base_source_already_complete ----------------------------------------------------------------


def test_base_source_already_complete_requires_matches_details_and_profile_all_populated():
    from football.merge import _MATCH_MERGE_FIELDS, _PROFILE_MERGE_FIELDS
    from football.orchestrate import _base_source_already_complete

    complete_details = _match_details("sofascore", **dict.fromkeys(_MATCH_MERGE_FIELDS, "x"))
    complete_profile = _team_profile("sofascore", **dict.fromkeys(_PROFILE_MERGE_FIELDS, "x"))
    matches = {"sofascore": [object()]}

    assert _base_source_already_complete("sofascore", matches, {"sofascore": complete_details}, {"sofascore": complete_profile}) is True
    assert _base_source_already_complete("sofascore", {}, {"sofascore": complete_details}, {"sofascore": complete_profile}) is False  # no fixtures
    assert _base_source_already_complete("sofascore", matches, {}, {"sofascore": complete_profile}) is False  # no details at all
    assert _base_source_already_complete("sofascore", matches, {"sofascore": _match_details("sofascore")}, {"sofascore": complete_profile}) is False  # details incomplete
    assert _base_source_already_complete("sofascore", matches, {"sofascore": complete_details}, {}) is False  # no profile at all
