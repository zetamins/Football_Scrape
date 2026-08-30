from football.sites.goal import _find_best_team_match, _TeamIndexEntry


def _entry(id_, slug):
    return _TeamIndexEntry(id=id_, slug=slug, url=f"https://www.goal.com/en/team/{slug}/{id_}")


def test_liverpool_resolves_to_the_mens_team_not_the_womens():
    # Confirmed live: get_goal_matches("Liverpool") returned 36 fixtures,
    # ALL of them Liverpool FC Women's WSL/FA Cup matches -- none the
    # men's Premier League team. team_aliases.py's canonical alias for
    # "Liverpool" is "Liverpool FC", normalizing to "liverpool fc".
    # Goal.com has no "liverpool-fc" slug, so the exact-match branch
    # misses, but the SUBSTRING branch right after doesn't: "liverpool
    # fc" is contained in the normalized form of "liverpool-fc-women"
    # ("liverpool fc women"), so that becomes the first candidate tried
    # -- the men's team's own bare "liverpool" slug, a separate and more
    # precise entry, is never reached (the alias loop returns on the
    # first alias that yields any candidate).
    entries = [
        _entry("men123", "liverpool"),  # the real men's Premier League club
        _entry("women456", "liverpool-fc-women"),
    ]
    match = _find_best_team_match(entries, "Liverpool")
    assert match is not None
    assert match.id == "men123"
    assert match.slug == "liverpool"


def test_other_teams_still_resolve_via_the_normal_alias_match():
    entries = [
        _entry("1", "arsenal"),
        _entry("2", "arsenal-women"),
    ]
    match = _find_best_team_match(entries, "Arsenal")
    assert match is not None
    assert match.id == "1"
