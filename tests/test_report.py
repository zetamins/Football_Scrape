from dataclasses import fields as _dc_fields

from football.report import (
    _prune_unplayed_match_fields,
    _strip_source_labels,
    build_report_json,
    build_report_markdown,
)


def _base_match(status: str) -> dict:
    return {
        "status": status,
        "home_score": None,
        "away_score": None,
        "home_score_ht": None,
        "away_score_ht": None,
        "attendance": None,
        "match_stats": [],
        "event_timeline": [],
        "player_of_the_match": None,
        "home_bench": [],
        "away_bench": [],
        "home_formation": "",
        "away_formation": "",
        "home_lineup": [
            {
                "name": "Player A",
                "position": "D",
                "substitute": False,
                "minutes_played": None,
                "goals": None,
                "assists": None,
                "xg": None,
                "xa": None,
                "shots": None,
                "shots_on_target": None,
                "tackles": None,
                "interceptions": None,
                "fouls": None,
                "rating": None,
                "key_passes": None,
            }
        ],
        "away_lineup": [],
        "referee": "Some Ref",
        "venue_name": "Some Stadium",
        # Confirmed live: sofascore.py's extraction functions return a
        # zero-filled shell for these two, never None, for an unplayed
        # match -- this is exactly why they were missing from the
        # original fixture and the bug went unnoticed until a live
        # report was inspected directly.
        "set_piece_goals": {"home": {"corner": 0, "penalty": 0, "free_kick": 0}, "away": {"corner": 0, "penalty": 0, "free_kick": 0}},
        "shotmap_stats": {"home": {"non_penalty_xg": 0.0, "set_piece_xg": 0.0, "penalties_awarded": 0}, "away": {"non_penalty_xg": 0.0, "set_piece_xg": 0.0, "penalties_awarded": 0}},
    }


def test_prunes_outcome_only_fields_for_not_started_match():
    match = _base_match("notstarted")
    result = _prune_unplayed_match_fields(match)

    for field in (
        "home_score", "away_score", "home_score_ht", "away_score_ht",
        "attendance", "match_stats", "event_timeline", "player_of_the_match",
        "home_bench", "away_bench", "home_formation", "away_formation",
        "set_piece_goals", "shotmap_stats",
    ):
        assert field not in result

    assert result["home_lineup"] == [{"name": "Player A", "position": "D", "substitute": False}]
    assert result["referee"] == "Some Ref"
    assert result["venue_name"] == "Some Stadium"


def test_prunes_set_piece_goals_and_shotmap_stats_even_though_never_empty():
    # These two are NOT None/[]/"" -- sofascore.py always returns a
    # zero-filled shell for an unplayed match (confirmed live), so the
    # generic is_empty_value-gated pruning loop can never catch them on
    # its own. This is what _ALWAYS_PRUNE_WHEN_UNPLAYED exists for.
    match = _base_match("notstarted")
    assert match["set_piece_goals"]["home"] == {"corner": 0, "penalty": 0, "free_kick": 0}  # sanity: genuinely non-empty
    result = _prune_unplayed_match_fields(match)
    assert "set_piece_goals" not in result
    assert "shotmap_stats" not in result


def test_leaves_a_real_finished_match_set_piece_goals_untouched():
    match = _base_match("finished")
    match["set_piece_goals"] = {"home": {"corner": 2, "penalty": 1, "free_kick": 0}, "away": {"corner": 0, "penalty": 0, "free_kick": 0}}
    result = _prune_unplayed_match_fields(dict(match))
    assert result["set_piece_goals"]["home"]["corner"] == 2


def test_prunes_outcome_only_fields_for_scheduled_match():
    match = _base_match("scheduled")
    result = _prune_unplayed_match_fields(match)
    assert "home_score" not in result


def test_leaves_finished_match_untouched():
    match = _base_match("finished")
    result = _prune_unplayed_match_fields(dict(match))
    assert result == match


def test_leaves_live_match_untouched():
    match = _base_match("inprogress")
    result = _prune_unplayed_match_fields(dict(match))
    assert result == match


def test_never_deletes_populated_score_even_if_status_not_started():
    match = _base_match("notstarted")
    match["home_score"] = 1
    match["away_score"] = 0
    result = _prune_unplayed_match_fields(match)
    assert result["home_score"] == 1
    assert result["away_score"] == 0


def test_never_deletes_a_real_early_confirmed_formation():
    # Regression coverage: home_formation/away_formation are
    # Optional[str], so an unplayed match's genuinely-empty value is ""
    # not None -- the pruning check previously only recognized None/[]
    # as "empty", so these two fields silently survived pruning as
    # pointless empty strings (confirmed live). Also confirms a REAL
    # early-announced formation is never discarded just because the
    # match hasn't kicked off yet.
    match = _base_match("notstarted")
    match["home_formation"] = "4-3-3"
    result = _prune_unplayed_match_fields(match)
    assert result["home_formation"] == "4-3-3"
    assert "away_formation" not in result


# --- _strip_source_labels -------------------------------------------------------


def test_strip_source_labels_removes_per_item_source_keys_at_any_depth():
    # base_source/field_sources are deliberately NOT stripped -- they're
    # the per-field provenance a consumer actually asked for (which
    # source supplied each field of the match/profile merge). Only the
    # finer-grained, per-item source/season_stats_source labels are.
    obj = {
        "source": "sofascore",
        "team": "Arsenal",
        "nested": {"season_stats_source": "fotmob", "value": 1},
        "list": [{"field_sources": {"x": "goal"}, "keep": "yes"}],
    }
    result = _strip_source_labels(obj)
    assert "source" not in result
    assert result["team"] == "Arsenal"
    assert "season_stats_source" not in result["nested"]
    assert result["nested"]["value"] == 1
    assert "field_sources" in result["list"][0]
    assert result["list"][0]["keep"] == "yes"


def test_strip_source_labels_leaves_non_dict_non_list_values_alone():
    assert _strip_source_labels("plain string") == "plain string"
    assert _strip_source_labels(42) == 42
    assert _strip_source_labels(None) is None


# --- build_report_json / build_report_markdown (integration) --------------------


def _all_none(cls, **overrides):
    base = {f.name: None for f in _dc_fields(cls)}
    base.update(overrides)
    return cls(**base)


def _run_search_result(**overrides):
    from football.orchestrate import RunSearchResult

    base = {
        "team": "Arsenal", "generated_at": "2026-01-01T00:00:00.000Z", "statuses": [],
        "merged": None, "opponent_name": None, "form": None, "form_source": None,
        "opponent_form": None, "opponent_form_source": None, "merged_profile": None,
        "opponent_profile": None, "insights": None, "venue_details": None,
    }
    base.update(overrides)
    return RunSearchResult(**base)


def test_build_report_json_with_no_match_found():
    result = _run_search_result()
    report = build_report_json(result)
    assert report["team"] == "Arsenal"
    assert report["match"] is None
    assert report["sources"] == []


def test_build_report_json_strips_only_per_item_source_from_match():
    from football.merge import MergedMatch

    merged = _all_none(
        MergedMatch, home_team="Home FC", away_team="Away FC", status="finished",
        source="sofascore", base_source="sofascore", field_sources={"venue_name": "fotmob"}, additional_notes=[],
    )
    result = _run_search_result(merged=merged)
    report = build_report_json(result)
    assert report["match"]["home_team"] == "Home FC"
    assert "source" not in report["match"]
    # base_source/field_sources ARE the per-field provenance that was
    # requested -- exposed now, not stripped.
    assert report["match"]["base_source"] == "sofascore"
    assert report["match"]["field_sources"] == {"venue_name": "fotmob"}


def test_build_report_json_includes_source_statuses():
    from football.orchestrate import SourceStatus

    statuses = [SourceStatus(source="sofascore", fixtures_scraped=5), SourceStatus(source="fotmob", matches_error="blocked")]
    result = _run_search_result(statuses=statuses)
    report = build_report_json(result)
    assert len(report["sources"]) == 2
    assert report["sources"][0]["fixtures_scraped"] == 5
    assert report["sources"][1]["matches_error"] == "blocked"


def test_build_report_json_data_completeness_none_without_match():
    result = _run_search_result()
    report = build_report_json(result)
    assert report["dataCompleteness"] is None


def test_build_report_json_includes_data_completeness_when_match_exists():
    from football.merge import MergedMatch

    merged = _all_none(MergedMatch, home_team="Home FC", away_team="Away FC", status="notstarted", additional_notes=[])
    result = _run_search_result(merged=merged)
    report = build_report_json(result)
    assert report["dataCompleteness"] is not None
    assert "populated" in report["dataCompleteness"]
    assert "total" in report["dataCompleteness"]


def test_build_report_markdown_with_no_match_found():
    result = _run_search_result()
    md = build_report_markdown(result)
    assert "No upcoming match found from any source." in md
    assert "Arsenal" in md


def test_build_report_markdown_lists_source_fetch_status():
    from football.orchestrate import SourceStatus

    statuses = [SourceStatus(source="sofascore", fixtures_scraped=5), SourceStatus(source="fotmob", matches_error="blocked")]
    result = _run_search_result(statuses=statuses)
    md = build_report_markdown(result)
    assert "sofascore: 5 fixtures" in md
    assert "fotmob: 0 fixtures -- blocked" in md


def test_build_report_markdown_includes_data_completeness_line():
    from football.merge import MergedMatch

    merged = _all_none(MergedMatch, home_team="Home FC", away_team="Away FC", status="notstarted", additional_notes=[], field_sources={})
    result = _run_search_result(merged=merged)
    md = build_report_markdown(result)
    assert "Data completeness:" in md
    assert "fields populated this run" in md


def _form_summary(**overrides):
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


def test_build_report_markdown_includes_every_optional_match_section():
    from football.merge import MergedMatch, MergedProfile
    from football.types import MatchInsights, VenueDetails

    merged = _all_none(MergedMatch, home_team="Home FC", away_team="Away FC", status="finished", additional_notes=[], field_sources={})
    venue = _all_none(VenueDetails, stadium_name="Some Stadium", clubs=[], source_url="https://example.com")
    form = _form_summary()
    opponent_form = _form_summary()
    profile = _all_none(MergedProfile, source="sofascore", team_name="Home FC", squad=None, field_sources={})
    opponent_profile = _all_none(MergedProfile, source="sofascore", team_name="Opponent FC", squad=None, field_sources={})
    insights = _all_none(MatchInsights, match_type="competitive")

    result = _run_search_result(
        merged=merged, venue_details=venue, form=form, form_source="sofascore",
        opponent_form=opponent_form, opponent_name="Opponent FC",
        merged_profile=profile, opponent_profile=opponent_profile, insights=insights,
    )
    md = build_report_markdown(result)
    assert "## Next match" in md
    assert "## Form" in md
    assert "## Opponent FC form" in md
    assert "Some Stadium" in md
    assert "Home FC" in md
    assert "Opponent FC" in md
    assert "competitive" in md
