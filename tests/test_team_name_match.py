from football.team_name_match import (
    name_query_variants,
    normalize_for_match,
    slugify_for_match,
    strip_diacritics,
    strip_generic_club_tokens,
)


def test_strip_diacritics():
    assert strip_diacritics("Almería") == "Almeria"
    assert strip_diacritics("Köln") == "Koln"
    assert strip_diacritics("Liverpool") == "Liverpool"


def test_strip_generic_club_tokens():
    assert strip_generic_club_tokens("Girona FC") == "Girona"
    assert strip_generic_club_tokens("Real Madrid CF") == "Real Madrid"
    # Not a generic token -- must not be stripped.
    assert strip_generic_club_tokens("AFC Bournemouth") == "Bournemouth"
    assert strip_generic_club_tokens("Liverpool") == "Liverpool"


def test_name_query_variants_no_change_needed():
    assert name_query_variants("Liverpool") == ["Liverpool"]


def test_name_query_variants_diacritics_only():
    assert name_query_variants("Almería") == ["Almería", "Almeria"]


def test_name_query_variants_suffix_only():
    assert name_query_variants("Girona FC") == ["Girona FC", "Girona"]


def test_name_query_variants_both():
    # A hypothetical name combining both mismatch shapes.
    assert name_query_variants("Málaga CF") == ["Málaga CF", "Malaga CF", "Malaga"]


def test_normalize_for_match():
    # Consolidated from 9 site modules that previously copy-pasted this
    # verbatim -- see team_name_match.py's own docstring on the function.
    assert normalize_for_match("Almería") == "almeria"
    assert normalize_for_match("Girona FC") == "girona fc"
    assert normalize_for_match("St. Pauli") == "st pauli"
    assert normalize_for_match("  Liverpool  ") == "liverpool"


def test_slugify_for_match():
    # Consolidated from 2 site modules that previously copy-pasted this
    # verbatim -- see team_name_match.py's own docstring on the function.
    assert slugify_for_match("Real Madrid") == "real-madrid"
    assert slugify_for_match("St. Pauli") == "st-pauli"
    assert slugify_for_match("-Leading and trailing-") == "leading-and-trailing"
