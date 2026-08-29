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
    }


def test_prunes_outcome_only_fields_for_not_started_match():
    match = _base_match("notstarted")
    result = _prune_unplayed_match_fields(match)

    for field in (
        "home_score", "away_score", "home_score_ht", "away_score_ht",
        "attendance", "match_stats", "event_timeline", "player_of_the_match",
        "home_bench", "away_bench",
    ):
        assert field not in result

    assert result["home_lineup"] == [{"name": "Player A", "position": "D", "substitute": False}]
    assert result["referee"] == "Some Ref"
    assert result["venue_name"] == "Some Stadium"


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
