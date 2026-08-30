from football.sites.fotmob import _find_best_team_match, _TeamIndexEntry


def _entry(id_, slug):
    return _TeamIndexEntry(id=id_, slug=slug, url=f"https://www.fotmob.com/teams/{id_}/overview/{slug}")


def test_liverpool_resolves_to_the_english_club_not_the_uruguayan_one():
    # Confirmed live, directly (fetching each team's own Fotmob page and
    # reading details.country, not guessed from slug/title -- both are
    # misleading here): a real Uruguayan club is ALSO officially named
    # "Liverpool FC" and holds the Fotmob slug "liverpool-fc" (id 2219,
    # country="URU"). team_aliases.py's canonical alias for this
    # project's "Liverpool" is "Liverpool FC", which normalizes to
    # exactly that slug -- the alias loop's exact-match branch hit the
    # Uruguayan club first and returned before ever trying the plain
    # "liverpool" alias, which is the real English club (id 8650,
    # confirmed country="ENG"). This silently corrupted every
    # Fotmob-derived insight (season xG/shots/aerial/passing/fouls/
    # goalkeeping/possession/corners estimates) for "Liverpool" searches.
    entries = [
        _entry(8650, "liverpool"),  # the real English Premier League club
        _entry(2219, "liverpool-fc"),  # a same-named Uruguayan club (Montevideo)
        _entry(1070259, "liverpool-u21"),
        _entry(258665, "liverpool"),  # Liverpool's own women's team, same bare slug
        _entry(1113546, "liverpool-u18"),
    ]
    match = _find_best_team_match(entries, "Liverpool")
    assert match is not None
    assert match.id == 8650
    assert match.slug == "liverpool"


def test_general_algorithm_prefers_a_later_aliass_exact_match_over_an_earlier_aliass_substring():
    # Same structural fix as goal.py's equivalent test, using
    # team_aliases.py's "leicester city" -> "leicester" pair: the
    # canonical alias ("leicester-city", tried first) would
    # substring-match a longer, wrong entity if checked in isolation, but
    # the exact-match pass now runs across every alias before any
    # substring fallback runs for any of them.
    entries = [
        _entry("real", "leicester"),
        _entry("wrong", "leicester-city-academy"),
    ]
    match = _find_best_team_match(entries, "Leicester City")
    assert match is not None
    assert match.id == "real"


def test_override_is_still_required_for_liverpool_unlike_goal_dot_com():
    # Confirmed live by temporarily clearing _FOTMOB_SLUG_OVERRIDE and
    # re-running the Liverpool case above: unlike goal.py (where the
    # equivalent override turned out to be fully redundant with the
    # general fix and was removed), Fotmob's Uruguayan club holds a
    # GENUINE exact slug "liverpool-fc" -- not a substring false-positive
    # -- so even a full exact-match-across-every-alias pass hits that
    # real, exact, wrong match on the canonical alias before the shorter
    # "liverpool" alias (tried second) is ever reached. This test proves
    # the override is load-bearing, not belt-and-braces -- if it were
    # ever removed under the assumption the general fix alone covers it,
    # this would catch the regression.
    from football.sites.fotmob import _FOTMOB_SLUG_OVERRIDE

    entries = [
        _entry(8650, "liverpool"),
        _entry(2219, "liverpool-fc"),
    ]
    saved = dict(_FOTMOB_SLUG_OVERRIDE)
    _FOTMOB_SLUG_OVERRIDE.clear()
    try:
        match = _find_best_team_match(entries, "Liverpool")
        assert match is not None
        assert match.id == 2219  # the WRONG club -- proves the override is necessary
    finally:
        _FOTMOB_SLUG_OVERRIDE.update(saved)


def test_other_teams_still_resolve_via_the_normal_alias_exact_match():
    # The override table is scoped to specific known collisions -- this
    # confirms it doesn't interfere with the general case.
    entries = [
        _entry(1, "arsenal"),
        _entry(2, "arsenal-women"),
    ]
    match = _find_best_team_match(entries, "Arsenal")
    assert match is not None
    assert match.id == 1
