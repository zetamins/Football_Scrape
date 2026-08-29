from football.form import is_team_home
from football.types import MatchInfo


def _match(home_team: str, away_team: str) -> MatchInfo:
    return MatchInfo(
        source=None, source_url=None, competition=None,
        home_team=home_team, away_team=away_team,
        kickoff_utc="2026-01-01T15:00:00Z", venue=None, status=None,
        home_score=1, away_score=1, home_score_ht=None, away_score_ht=None,
        season=None, round=None, match_id=None,
    )


def test_direct_substring_match_still_works():
    m = _match("Arsenal FC", "Chelsea FC")
    assert is_team_home(m, "Arsenal") is True
    assert is_team_home(m, "Chelsea") is False


def test_alias_table_resolves_name_with_no_shared_substring():
    # Fotmob's own literal stored name for Nottingham Forest is "Nottm
    # Forest" -- confirmed live -- which shares no substring with
    # "Nottingham Forest" in either direction, so only the alias-table
    # fallback in is_team_home can resolve this.
    m = _match("Nottm Forest", "Arsenal")
    assert is_team_home(m, "Nottingham Forest") is True
    assert is_team_home(m, "Nott'm Forest") is True


def test_unrelated_team_returns_none():
    m = _match("Nottm Forest", "Arsenal")
    assert is_team_home(m, "Chelsea") is None
