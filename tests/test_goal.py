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


def test_general_algorithm_prefers_a_later_aliass_exact_match_over_an_earlier_aliass_substring():
    # This is the structural fix itself, using a DIFFERENT known
    # collision shape than the Liverpool test above (team_aliases.py:
    # "leicester city" -> alias "leicester"): the canonical alias
    # ("leicester city", tried first via known_aliases_for's
    # canonical-first ordering) would substring-match a longer, wrong
    # entity ("leicester-city-academy") if checked in isolation, but the
    # exact-match pass now runs across EVERY alias before any substring
    # fallback runs for ANY of them, so the later, shorter alias's exact
    # match ("leicester" -> the real club's actual slug) wins regardless
    # of alias order.
    entries = [
        _entry("real", "leicester"),
        _entry("wrong", "leicester-city-academy"),
    ]
    match = _find_best_team_match(entries, "Leicester City")
    assert match is not None
    assert match.id == "real"


def test_other_teams_still_resolve_via_the_normal_alias_match():
    entries = [
        _entry("1", "arsenal"),
        _entry("2", "arsenal-women"),
    ]
    match = _find_best_team_match(entries, "Arsenal")
    assert match is not None
    assert match.id == "1"
