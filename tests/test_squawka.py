from football.sites.squawka import _resolve_competition_id


def _competitions():
    return [
        # Not-yet-started next season -- must be filtered out even though
        # it's a duplicate-name entry that could otherwise "win" by being
        # picked as latest.
        {"competition": "Premier League", "start_date": "2099-08-01 00:00:00", "_id": "future"},
        {"competition": "Premier League", "start_date": "2025-08-15 00:00:00", "_id": "current"},
        {"competition": "Premier League", "start_date": "2024-08-16 00:00:00", "_id": "older"},
    ]


def test_resolves_most_recent_started_season():
    # Regression test: Squawka's start_date has no timezone marker at all
    # ("YYYY-MM-DD HH:MM:SS", space-separated) -- naive datetime parsing
    # and comparison must not raise, and must correctly exclude a
    # not-yet-started season even when it's the "latest" by date.
    assert _resolve_competition_id(_competitions(), "Premier League") == "current"


def test_applies_competition_alias():
    competitions = [{"competition": "Primera Division", "start_date": "2024-08-16 00:00:00", "_id": "laliga"}]
    assert _resolve_competition_id(competitions, "LaLiga") == "laliga"
    assert _resolve_competition_id(competitions, "La Liga") == "laliga"


def test_no_match_returns_none():
    assert _resolve_competition_id(_competitions(), "Ligue 1") is None
