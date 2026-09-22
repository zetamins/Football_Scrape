from dataclasses import dataclass

import pytest

from football.team_aliases import (
    canonical_for,
    find_best_slug_match,
    known_aliases_for,
    normalize,
)


@dataclass
class _Entry:
    slug: str


def test_normalize():
    assert normalize("Almería") == "almeria"
    assert normalize("Girona FC") == "girona fc"


def test_canonical_for_known_alias():
    assert canonical_for("Man Utd") == canonical_for("Manchester United")


def test_canonical_for_unknown_name_returns_normalized_input():
    assert canonical_for("Some Totally Unrelated Club") == "some totally unrelated club"


def test_known_aliases_for_includes_canonical_and_aliases():
    aliases = known_aliases_for("Man Utd")
    assert "manchester united" in aliases
    assert len(aliases) > 1


def test_known_aliases_for_unknown_name_returns_just_normalized_input():
    assert known_aliases_for("Some Totally Unrelated Club") == ["some totally unrelated club"]


def test_find_best_slug_match_exact():
    entries = [_Entry("liverpool"), _Entry("liverpool-fc-women")]
    match = find_best_slug_match(entries, "Liverpool")
    assert match is not None
    assert match.slug == "liverpool"


def test_find_best_slug_match_substring_fallback():
    entries = [_Entry("some-totally-unrelated-club-reserves")]
    match = find_best_slug_match(entries, "Some Totally Unrelated Club")
    assert match is not None
    assert match.slug == "some-totally-unrelated-club-reserves"


def test_find_best_slug_match_reverse_direction():
    entries = [_Entry("girona")]
    match = find_best_slug_match(entries, "Girona Futbol Club")
    assert match is not None
    assert match.slug == "girona"


def test_find_best_slug_match_no_match_returns_none():
    entries = [_Entry("completely-different")]
    match = find_best_slug_match(entries, "Zzz Nonexistent")
    assert match is None


def test_bare_tottenham_expands_to_the_full_club_name_squawka_uses():
    # Squawka matches team names exactly; "Tottenham" alone used to expand
    # to nothing, so no Tottenham player ever matched.
    assert "tottenham hotspur" in known_aliases_for("Tottenham")
    assert "tottenham" in known_aliases_for("Tottenham Hotspur")


# --- same_team ----------------------------------------------------------------------------------


def test_same_team_matches_through_the_alias_table_when_neither_name_contains_the_other():
    from football.team_aliases import same_team

    assert same_team("Man Utd", "Manchester United")
    assert same_team("Nott'm Forest", "Nottingham Forest")
    assert same_team("Spurs", "Tottenham Hotspur")


def test_same_team_keeps_the_substring_fallback_for_names_the_table_does_not_cover():
    from football.team_aliases import same_team

    assert same_team("Coventry", "Coventry City")
    assert same_team("Coventry City", "Coventry")


def test_same_team_rejects_different_clubs():
    from football.team_aliases import same_team

    assert not same_team("Manchester United", "Manchester City")
    assert not same_team("Arsenal", "Chelsea")
    assert not same_team("", "Arsenal")


def test_alias_table_has_no_name_claimed_by_two_teams_and_no_self_aliases():
    from collections import Counter

    from football.team_aliases import TEAM_ALIASES

    claims = Counter(name for canonical, aliases in TEAM_ALIASES.items() for name in {canonical, *aliases})
    assert [n for n, c in claims.items() if c > 1] == []
    assert [c for c, aliases in TEAM_ALIASES.items() if c in aliases] == []


# --- alias matrix: every alias reaches its own club through the shared matchers --------------


def _alias_pairs():
    from football.team_aliases import TEAM_ALIASES

    return [(canonical, alias) for canonical, aliases in TEAM_ALIASES.items() for alias in aliases]


@pytest.mark.parametrize(("canonical", "alias"), _alias_pairs())
def test_every_alias_resolves_to_its_canonical_slug_even_with_a_longer_decoy_present(canonical, alias):
    # Fotmob and Goal.com both resolve teams through find_best_slug_match
    # over a sitemap; the decoy is the women's/youth sibling page every
    # club has there, which must never win.
    slug = canonical.replace(" ", "-")
    entries = [_Entry(slug=f"{slug}-women"), _Entry(slug=f"{slug}-u21"), _Entry(slug=slug), _Entry(slug="unrelated-club")]
    match = find_best_slug_match(entries, alias)
    assert match is not None
    assert match.slug == slug


@pytest.mark.parametrize(("canonical", "alias"), _alias_pairs())
def test_every_alias_shares_a_known_alias_set_with_its_canonical(canonical, alias):
    # StatsUltra, StadiumDB, SoccerDesk and 365Scores all iterate
    # known_aliases_for(name) -- so an alias and its canonical must expand
    # to the same set, whichever one the user (or a source) typed.
    from football.team_aliases import known_aliases_for

    assert set(known_aliases_for(alias)) == set(known_aliases_for(canonical))
    assert canonical in known_aliases_for(alias)


@pytest.mark.parametrize(("canonical", "alias"), _alias_pairs())
def test_same_team_recognises_every_alias_of_its_canonical(canonical, alias):
    from football.team_aliases import same_team

    assert same_team(alias, canonical)
