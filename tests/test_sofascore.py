import asyncio

import pytest

import football.sites.sofascore as sofascore


class _FakePage:
    pass


def _mock_fetch_json(response: dict, urls_seen: list[str]):
    async def fake(page, url):
        urls_seen.append(url)
        return response

    return fake


def test_alias_translates_to_canonical_query_in_one_request(monkeypatch):
    # "Nott'm Forest" (football-data.co.uk's short form) returns no team
    # result from Sofascore's own search -- confirmed live -- while the
    # canonical "Nottingham Forest" resolves immediately. The alias
    # translation must still cost exactly one search request.
    urls_seen: list[str] = []
    response = {"results": [{"type": "team", "entity": {"id": 14, "name": "Nottingham Forest", "slug": "nottingham-forest"}}]}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    team = asyncio.run(sofascore._find_team(_FakePage(), "Nott'm Forest"))

    assert team is not None
    assert team.name == "Nottingham Forest"
    assert len(urls_seen) == 1
    assert "nottingham" in urls_seen[0].lower()
    assert "forest" in urls_seen[0].lower()


def test_unknown_team_query_is_passed_through_unchanged(monkeypatch):
    urls_seen: list[str] = []
    response = {"results": [{"type": "team", "entity": {"id": 99, "name": "Some Club", "slug": "some-club"}}]}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    asyncio.run(sofascore._find_team(_FakePage(), "Some Club"))

    assert len(urls_seen) == 1
    assert "Some%20Club" in urls_seen[0] or "Some+Club" in urls_seen[0]


def test_block_response_raises_with_exactly_one_request(monkeypatch):
    urls_seen: list[str] = []
    response = {"error": {"code": 403, "reason": "Forbidden"}}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    coro = sofascore._find_team(_FakePage(), "Nott'm Forest")
    with pytest.raises(ValueError, match="blocked"):
        asyncio.run(coro)

    assert len(urls_seen) == 1


def test_no_results_returns_none_with_exactly_one_request(monkeypatch):
    urls_seen: list[str] = []
    response = {"results": []}
    monkeypatch.setattr(sofascore, "_fetch_json", _mock_fetch_json(response, urls_seen))

    team = asyncio.run(sofascore._find_team(_FakePage(), "Nonexistent FC"))

    assert team is None
    assert len(urls_seen) == 1
