from dataclasses import dataclass

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
