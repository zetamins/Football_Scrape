"""Cross-source team-name matching helpers. Ported from src/teamNameMatch.ts.

Two concrete, repeatedly-observed cross-source team-name mismatch shapes
found during testing (e.g. "Girona FC" / "Almeria" as Sofascore names
searched against Fotmob, Goal.com, SoccerDesk):

1. Diacritics: source APIs/indexes are inconsistent about accented
   characters ("Almeria" vs "Almeria" with an accent). A naive normalize()
   that only strips non a-z0-9 characters turns "i" (accented) into a space
   rather than "i" -- silently corrupting the name instead of matching it.
2. Generic club-entity suffixes: Sofascore's official names often carry a
   trailing "FC"/"CF"/etc. that other sources' slugs/search indexes drop
   entirely ("Girona FC" vs slug "girona").

Both are explicit, mechanical, documented transformations -- not guessed
aliases -- so they generalize to any team with the same shape of mismatch.
"""

from __future__ import annotations

import re
import unicodedata

# U+0300-U+036F: combining diacritical marks, same range as TS's
# /[̀-ͯ]/g -- built via chr() to avoid embedding literal
# combining characters in this source file.
_COMBINING_DIACRITICS = re.compile(f"[{chr(0x0300)}-{chr(0x036F)}]")

# Turkish dotless i (U+0131 lowercase, U+0130 uppercase) isn't a base
# letter plus a combining mark -- it's its own codepoint with no NFD
# decomposition -- so the strip below never touches it, confirmed live:
# "Kasımpaşa" (a real Süper Lig club) normalized to "kasımpasa", not
# "kasimpasa", silently failing to match "Kasimpasa" (the ASCII form
# every other source in this project uses). Same general-transformation
# category as the NFD stripping itself, not a one-off alias.
_TURKISH_DOTLESS_I = str.maketrans({"ı": "i", "İ": "I"})


def strip_diacritics(s: str) -> str:
    normalized = unicodedata.normalize("NFD", s.translate(_TURKISH_DOTLESS_I))
    return _COMBINING_DIACRITICS.sub("", normalized)


# Generic entity-type tokens that commonly appear in a club's official name
# but not in the short name other sources index/search by. Deliberately
# conservative -- only tokens seen to be purely decorative across major
# European leagues, never a club's actual identifying word.
_GENERIC_CLUB_TOKENS = {"fc", "cf", "afc", "sc", "ac", "cd", "ud", "sd", "rc", "ec", "ff"}


def strip_generic_club_tokens(s: str) -> str:
    words = [w for w in re.split(r"\s+", s) if w and w.lower() not in _GENERIC_CLUB_TOKENS]
    return " ".join(words).strip()


def name_query_variants(team_name: str) -> list[str]:
    """Ordered, deduped variants worth trying against a live search API (or
    a local index) when the exact team name fails to resolve: original,
    then diacritics stripped, then generic club-suffix stripped from that.
    Each stage only added if it actually differs from what's already queued."""
    variants = [team_name]
    no_diacritics = strip_diacritics(team_name)
    if no_diacritics != team_name:
        variants.append(no_diacritics)
    no_suffix = strip_generic_club_tokens(no_diacritics)
    if no_suffix and no_suffix not in variants:
        variants.append(no_suffix)
    return variants


def normalize_for_match(s: str) -> str:
    """Diacritics-stripped, lowercased, punctuation-collapsed-to-spaces
    form used for loose team/venue/referee-name comparison across sites.
    Was copy-pasted verbatim into 9 site modules (each already importing
    strip_diacritics from here) before being consolidated -- every one of
    those 9 imports it under its original local name via `as _normalize`
    so their many internal call sites needed no changes."""
    return re.sub(r"[^a-z0-9]+", " ", strip_diacritics(s).lower()).strip()


def slugify_for_match(s: str) -> str:
    """Lowercase, hyphen-joined slug used for building/matching site-local
    match/team slugs (e.g. soccerdesk's/three65scores' URL-shaped match
    ids). Was copy-pasted verbatim into 2 site modules before being
    consolidated -- both import it under its original local name via
    `as _slugify`."""
    return re.sub(r"(?:^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))
