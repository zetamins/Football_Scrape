from football.report import _prune_unplayed_match_fields


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
