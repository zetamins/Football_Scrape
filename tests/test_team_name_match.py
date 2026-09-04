from football.team_name_match import (
    name_query_variants,
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
