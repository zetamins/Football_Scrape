"""Consolidated team-name alias table, shared across every site scraper.

Each site's own normalize+substring matching logic (team_name_match.py,
form.py's normalize_team_name/is_team_home, and each site file's own
_normalize_*/_names_match helpers) remains the PRIMARY matching mechanism.
This table only supplements it for the specific cases where substring
matching alone genuinely fails -- e.g. Fotmob's literal stored name for
Nottingham Forest is "Nottm Forest" (no apostrophe, no space before
"Forest"), which is not a substring of "Nottingham Forest" in either
direction.

Kept intentionally small and scoped to the 10 leagues currently in scope
(EPL, Championship, Ligue 1, LaLiga, Bundesliga, Serie A, Belgian Pro
League, Eredivisie, Liga Portugal, Super Lig) -- only confirmed mismatches,
verified either against football-data.co.uk's live fixtures.csv short
names or, for entries marked "confirmed live", against a real Fotmob
search. Not an exhaustive database, and entries that couldn't be verified
(e.g. Royale Union Saint-Gilloise and Sint-Truiden on Fotmob -- direct
lookups failed outright, and a fuzzy-search attempt risked matching an
unrelated Argentine club also named "Unión") were deliberately left out
rather than guessed.

Each entry maps a canonical (well-known, full) team name to a list of
alternate spellings/short forms actually observed across this project's
sources. Both the canonical key and every alias are stored pre-normalized
(see `normalize()`) so lookups are a plain dict hit.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from .team_name_match import normalize_for_match as normalize

# canonical (normalized) -> [aliases (each already normalized)]
_RAW_ALIASES: dict[str, list[str]] = {
    # ---- EPL ----
    "manchester city": ["man city"],
    # Squawka (exact-match only) lists the club as "Tottenham Hotspur";
    # searching the bare "Tottenham" previously expanded to no alias at
    # all, so every Tottenham squad member silently got zero Squawka
    # defensive stats (confirmed: 0 of the squad vs 22 for Man Utd).
    "tottenham hotspur": ["tottenham", "spurs"],
    # "manchester utd" confirmed live via StatsUltra ("Manchester Utd" --
    # keeps "Manchester" in full, unlike "Man Utd" -- doesn't substring-
    # match either "manchester united" or the "man utd" alias).
    "manchester united": ["man united", "man utd", "manchester utd"],
    # Fotmob's own literal stored name is "Nottm Forest"; StatsUltra's is
    # "Nott'ham Forest" -- both confirmed live, each a distinct spelling.
    "nottingham forest": ["nott m forest", "nottm forest", "nott ham forest"],
    "newcastle united": ["newcastle"],
    "west ham united": ["west ham"],
    # "wolverhampton" confirmed live via Sofascore's own literal name
    # (drops "Wanderers" entirely, unlike the "wolves" nickname alias).
    "wolverhampton wanderers": ["wolves", "wolverhampton"],
    "brighton and hove albion": ["brighton hove albion", "brighton"],
    "leicester city": ["leicester"],
    # All four confirmed live via 365Scores: the bare short name exact- or
    # substring-matches an unrelated same-name entity from a different
    # sport/age-group/reserve squad (Hull FC is rugby league; "Leeds",
    # "Blackburn" alone pick reserve/wrong-sport entries) rather than the
    # real senior football club, which only turns up under its fuller name.
    "hull city": ["hull"],
    # Both confirmed live via Squawka (exact-match only, no substring
    # fallback -- the strictest of any site in this project).
    "afc bournemouth": ["bournemouth"],
    "liverpool fc": ["liverpool"],
    "leeds united": ["leeds"],
    "blackburn rovers": ["blackburn"],

    # ---- Championship ----
    "queens park rangers": ["qpr"],
    # Both confirmed live via 365Scores.
    "bolton wanderers": ["bolton"],
    "lincoln city": ["lincoln"],
    "west bromwich albion": ["west brom", "wba"],
    # "preston" confirmed live via SoccerDesk: searching "Preston" (the
    # football-data.co.uk short name) returns both "Preston North End"
    # (the real club) and an unrelated, unaffiliated club literally named
    # just "Preston" (no country attached) -- without this alias, the
    # bare exact match won over the real club's forward-substring match.
    "preston north end": ["preston"],
    # Sofascore ranks "Aston Villa" (a different Birmingham-based club)
    # above the real "Birmingham City" for the bare query "Birmingham" --
    # confirmed live. The fuller name correctly ranks the real club first.
    "birmingham city": ["birmingham"],

    # ---- Ligue 1 ----
    # "paris s g" confirmed live via StatsUltra ("Paris S-G" -- the hyphen
    # normalizes to a space between S and G, so it doesn't substring-match
    # the "paris sg" alias, which has no space).
    "paris saint germain": ["paris sg", "psg", "paris s g"],
    # "rennes" (football-data.co.uk short name) confirmed live against
    # Sofascore's own literal "Stade Rennais" -- "rennais" (adjective
    # form) shares no substring with "rennes" (city name) in either
    # direction.
    "stade rennais": ["rennes"],
    # All three confirmed live via Squawka.
    "angers sco": ["angers"],
    "rc lens": ["lens"],
    "rc strasbourg": ["strasbourg"],
    # "marseille" confirmed live via SoccerDesk -- Sofascore's own literal
    # "Olympique de Marseille" doesn't reach it (SoccerDesk's search is
    # strict-prefix, "olympique de marseille" != "marseille").
    # "olympique marseille" (Squawka's own literal, missing "de")
    # confirmed live.
    "olympique de marseille": ["marseille", "olympique marseille"],
    # "brest" confirmed live via SoccerDesk.
    # "stade brestois 29" is Sofascore-style (with the club number).
    "stade brestois": ["brest", "stade brestois 29"],
    # Squawka lists it as plain "Lille"; "LOSC Lille" is the official name.
    "lille": ["losc lille"],
    # "lyon" (football-data.co.uk's short name) confirmed live against
    # Squawka's own embedded team name "Olympique Lyonnais" -- Squawka's
    # matching is exact-equality only (no substring fallback, the
    # strictest of any site in this project), so this alias is the only
    # way "Lyon" ever resolves there.
    "olympique lyonnais": ["lyon"],
    # Sofascore's own search ranks "FC Bayern München" above the real "AS
    # Monaco" for the bare query "Monaco" -- confirmed live, consistently
    # reproducible. The fuller name correctly ranks AS Monaco first.
    "as monaco": ["monaco"],

    # ---- LaLiga ----
    "athletic bilbao": ["ath bilbao", "athletic club"],
    "atletico madrid": ["ath madrid", "atletico de madrid"],
    "espanyol": ["espanol", "rcd espanyol"],
    # All three confirmed live via Squawka.
    "fc barcelona": ["barcelona"],
    "levante ud": ["levante"],
    "malaga cf": ["malaga"],
    # Sofascore ranks "Real Betis" (Sevilla's local rival) above the real
    # "Sevilla"/"Sevilla FC" for the bare query "Sevilla" -- confirmed
    # live. Querying "Sevilla FC" correctly ranks the real club first.
    "sevilla fc": ["sevilla"],
    # "real racing club" (Sofascore's own literal name) and "racing
    # santander" (StatsUltra's) both confirmed live -- neither is the
    # bare, collision-risky "racing" (see the earlier StadiumDB finding
    # for why that alone was deliberately left out).
    # "racing de santander" (Squawka's own literal) confirmed live.
    "racing santander": ["real racing club", "racing de santander", "real racing club de santander"],
    # "celta de vigo" (StadiumDB's own name, "de" in the middle) vs
    # Sofascore's "Celta Vigo" -- confirmed live, breaks the substring
    # match either direction.
    "celta de vigo": ["celta vigo", "celta"],

    # ---- Bundesliga ----
    # "eint frankfurt" confirmed live via StatsUltra ("Eint Frankfurt" --
    # a different abbreviation than football-data.co.uk's "Ein Frankfurt").
    "eintracht frankfurt": ["ein frankfurt", "eint frankfurt"],
    # Both confirmed live via Squawka.
    "vfb stuttgart": ["stuttgart"],
    "sc paderborn 07": ["paderborn"],
    # "sv 07 elversberg" (Sofascore) vs StadiumDB's "SV Elversberg" -- the
    # "07" breaks the substring match. Confirmed live.
    "sv elversberg": ["sv 07 elversberg", "elversberg"],
    # "borussia moenchengladbach" ("oe" digraph) confirmed live via
    # SoccerDesk -- also matters as a safety fix: the bare "gladbach"
    # alias below wrongly matches an unrelated club, "Bergisch Gladbach",
    # on SoccerDesk (confirmed live), but this exact, fuller alias
    # produces a genuine exact match first, which the exact-match-before-
    # fuzzy-fallback ordering in soccerdesk.py's own resolver already
    # guarantees takes priority.
    "borussia monchengladbach": ["m gladbach", "gladbach", "borussia moenchengladbach", "borussia m gladbach"],
    # "hsv" confirmed live via StadiumDB (literal club listing is just
    # "HSV", no "hamburg" text at all).
    "hamburger sv": ["hamburg", "hsv"],
    # "bayer" confirmed live via StadiumDB (literal club listing is just
    # "Bayer", dropping "Leverkusen" entirely).
    # "bayer 04 leverkusen" confirmed live via Sofascore's own literal
    # name -- the "04" breaks the substring match against the plain
    # "bayer leverkusen" alias.
    "bayer leverkusen": ["leverkusen", "bayer", "bayer 04 leverkusen"],
    "borussia dortmund": ["dortmund"],
    # "koeln" confirmed live via SoccerDesk -- spells it with an "oe"
    # digraph instead of "o" or "ö", a genuinely different normalized
    # string than football-data.co.uk's "Koln". "fc koln" is also listed
    # explicitly (not left to generic-"FC"-stripping alone) since the
    # alias lookup runs on the raw searched name, before that stripping
    # happens, and needs its own exact key to reach "koeln" at all.
    # "1 fc koln" confirmed live via Sofascore's own literal name -- not
    # previously registered, so this alias didn't get a chance to reach
    # the existing "koeln" alias via known_aliases_for's full list.
    "koln": ["koeln", "fc koln", "1 fc koln"],
    # "hoffenheim" confirmed live via 365Scores -- the bare word correctly
    # ranks the senior club first, while the full "TSG Hoffenheim" (no
    # alias registered before this) resolved to an U20 women's team via
    # the reverse-candidate fallback matching only the original query.
    "tsg hoffenheim": ["hoffenheim"],
    # All three confirmed live via SoccerDesk.
    "mainz 05": ["mainz", "1 fsv mainz 05"],
    "union berlin": ["1 fc union berlin"],
    "werder bremen": ["sv werder bremen"],
    "willem ii": ["willem ii tilburg"],
    # "bayern munchen" confirmed live via Fotmob -- the German spelling
    # ("München"), not the English "Munich" this canonical name uses, so
    # diacritics-stripping alone doesn't bridge it (different word, not
    # just an accent).
    # "fc bayern munchen" confirmed live via Sofascore's own literal name
    # -- the "fc" prefix, absent from the existing "bayern munchen" alias.
    "bayern munich": ["bayern munchen", "fc bayern munchen"],

    # ---- Serie A ----
    "internazionale": ["inter", "inter milan"],
    "ac milan": ["milan"],
    # "roma" confirmed live via SoccerDesk -- Sofascore's own literal
    # name "AS Roma" doesn't reach it via generic-suffix-stripping ("AS"
    # isn't in the small stripped-token set).
    "as roma": ["roma"],
    # "napoli" confirmed live via Squawka.
    "ssc napoli": ["napoli"],

    # ---- Eredivisie ----
    "fortuna sittard": ["for sittard"],
    # All six confirmed live via Squawka.
    "afc ajax": ["ajax"],
    "sc cambuur": ["sc cambuur leeuwarden"],
    "fc groningen": ["groningen"],
    "sc telstar": ["telstar"],
    "fc twente": ["twente"],
    "fc utrecht": ["utrecht"],
    # "sparta r dam" confirmed live via StatsUltra ("Sparta R'dam").
    "sparta rotterdam": ["sparta r dam"],
    # "psv" confirmed live via StadiumDB and Fotmob's own literal name.
    "psv eindhoven": ["psv"],
    # "az" confirmed live via StadiumDB's own literal club listing.
    "az alkmaar": ["az"],
    # "nec" confirmed live via StadiumDB (the club's own initials --
    # football-data.co.uk's short name "Nijmegen" shares no substring).
    # "nec nijmegen" confirmed live via Sofascore's own literal name --
    # registering it lets the bare "nec" alias below also get tried
    # against it via known_aliases_for's full list.
    "nijmegen": ["nec", "nec nijmegen"],
    # "heerenven" confirmed live via StadiumDB -- a typo on the site's own
    # page (missing the second "e" in "Heerenveen").
    # "sc heerenveen" confirmed live via Sofascore's own literal name --
    # doesn't reach the "heerenven" typo alias directly (correct spelling,
    # different prefix), but registering it lets that alias also get
    # tried via known_aliases_for's full list.
    "heerenveen": ["heerenven", "sc heerenveen"],
    # "exelsior" confirmed live via StadiumDB -- a typo on the site's own
    # page (missing the second "s" in "Excelsior").
    "excelsior": ["exelsior"],

    # "estrela" (football-data.co.uk's short name) forward-substring-
    # matches BOTH the real club and an unrelated, shorter-named "Estrela
    # Calheta" on SoccerDesk -- the existing shortest-name tiebreak (meant
    # to prefer a senior club over youth variants) picked the wrong,
    # shorter one. Confirmed live.
    # "cf estrela amadora" confirmed live via Sofascore's own literal
    # name (after the Sofascore-search fix above) -- "cf" prefix and
    # missing "da" both break the substring match against this canonical.
    "estrela da amadora": ["estrela", "cf estrela amadora"],
    # ---- Liga Portugal ----
    # Fotmob: searching "Sporting Lisbon" finds nothing, "Sporting CP"
    # succeeds -- confirmed live. Note "Sp Braga" needs NO alias here --
    # Fotmob's real literal name is just "Braga", which already
    # substring-matches "Sp Braga" fine (verified live, deliberately not
    # added as an entry).
    "sporting cp": ["sp lisbon", "sporting lisbon", "sporting clube de portugal"],
    # "braga" confirmed live via SoccerDesk -- its strict search returns
    # nothing for the literal 2-word phrase "Sp Braga" (football-data.co.uk's
    # short form), only for the bare club name.
    # "sporting braga" (Sofascore's own literal name) confirmed live --
    # neither the canonical "braga" nor the existing "sp braga" alias.
    "braga": ["sp braga", "sporting braga"],
    # Sofascore ranks the Colombian "Atlético Nacional" above the real
    # Portuguese "CD Nacional" for the bare query "Nacional" -- confirmed
    # live. The fuller name correctly ranks the Portuguese club first.
    "cd nacional": ["nacional"],
    # FC Porto: Sofascore ranks the "Portugal" national team above the
    # real club for the bare query "Porto" -- confirmed live.
    "fc porto": ["porto"],
    # Both confirmed live via SoccerDesk.
    "estoril praia": ["estoril"],
    "cs maritimo": ["maritimo"],

    # ---- Super Lig ----
    # Fotmob: confirmed live.
    # "basaksehir fk" confirmed live via Sofascore's own literal name --
    # a different combination (no "Istanbul" prefix, but with "FK") than
    # either existing alias.
    "istanbul basaksehir": ["buyuksehyr", "basaksehir", "istanbul basaksehir fk", "basaksehir fk"],
    # "gaziantep fk" (Sofascore's own literal name) and "gazisehir
    # gaziantep" (StatsUltra's) both confirmed live -- distinct spellings
    # sharing no substring.
    "gaziantep fk": ["gaziantep", "gazisehir gaziantep"],
    # Both confirmed live via SoccerDesk.
    "besiktas jk": ["besiktas"],
    "caykur rizespor": ["rizespor"],
    # "kasmpasa" confirmed live via Fotmob -- their own slug drops the
    # "i" in "Kasımpaşa" entirely rather than mapping the Turkish dotless
    # ı to "i" the way this project's own diacritics-stripping does, so
    # it's a site-specific spelling quirk, not fixable by better
    # normalization on this project's side.
    "kasimpasa": ["kasmpasa"],
    # "amed sportif" confirmed live via Fotmob -- football-data.co.uk's
    # own short name "Amedspor" doesn't substring-match it either way.
    # "amed sportif faaliyetler" confirmed live via Sofascore's own
    # literal name -- the full club name, not the shorter "amed sportif"
    # already registered.
    "amedspor": ["amed sportif", "amed sportif faaliyetler"],
    # "deportivo la coruna" confirmed live via Fotmob, which lists it as
    # "Deportivo (de) Coruña", not "La Coruña" -- football-data.co.uk's
    # own short name "La Coruna" shares no substring with either Fotmob
    # slug at all.
    # "deportivo de a coruna" confirmed live via Sofascore's own literal
    # name -- the extra "a" (Galician "A Coruña") breaks the substring
    # match against the existing "deportivo de coruna" alias.
    # "deportivo de la coruna" (Squawka's own literal, "la" not "a")
    # confirmed live -- a third distinct spelling.
    "deportivo la coruna": ["la coruna", "deportivo coruna", "deportivo de coruna", "deportivo de a coruna", "deportivo de la coruna"],

    # ---- Belgian Pro League ----
    # All five confirmed live via SoccerDesk -- its strict search wants
    # the bare club-identifying word, not Sofascore's fuller literal name
    # (the "RSC"/"KRC"/"KAA"/"KV" prefixes aren't in the generic-token
    # stripping set).
    "rsc anderlecht": ["anderlecht"],
    "club brugge kv": ["club brugge"],
    "krc genk": ["genk"],
    "kaa gent": ["gent"],
    "kv kortrijk": ["kortrijk"],
    # Both confirmed live via SoccerDesk -- same strict-bare-word pattern.
    "sv zulte waregem": ["zulte waregem"],
    "kvc westerlo": ["westerlo"],
    # "st truiden" confirmed directly against football-data.co.uk's own
    # live fixtures.csv. "sttruiden" (no space) confirmed live via
    # Fotmob's own slug. Union Saint-Gilloise's Fotmob lookups still
    # failed outright / risked a false match to an unrelated Argentine
    # club also named "Unión", so no Fotmob-specific alias is added there.
    # "stvv" confirmed live via 365Scores (Sint-Truidense Voetbalvereniging's
    # own abbreviation) -- its strict search also rejects "sint truiden"
    # (the normalized/space form) outright, only accepting the literal
    # hyphenated "Sint-Truiden", which this table's normalization can't
    # represent distinctly from the space form anyway.
    # Confirmed live via 365Scores: "Antwerp"/"Standard" alone pick a
    # wrong/reserve entity, the real senior clubs only turn up under their
    # fuller names.
    "royal antwerp fc": ["antwerp", "royal antwerp"],
    "standard de liege": ["standard", "standard liege"],
    # "sint truidense vv" confirmed live via Sofascore's own literal name
    # (the club's full formal name, Sint-Truidense Voetbalvereniging) --
    # shares no substring with the existing aliases.
    "sint truiden": ["st truiden", "sttruiden", "stvv", "sint truidense vv"],
    # "oh leuven" confirmed live via Fotmob -- abbreviates to the club's
    # initials, sharing no substring with the full name at all.
    "oud heverlee leuven": ["oh leuven"],
    # The club rebuilt/renamed from "Lommel SK" to "Lommel United" --
    # confirmed live via 365Scores, whose search returns "Lommel United"
    # for "Lommel" but only the U21 reserve team for "Lommel SK" itself
    # (its old name still forward-substring-matches the reserve entry's
    # longer name). football-data.co.uk still uses the old short name.
    "lommel united": ["lommel sk", "lommel"],
    # "union sg" confirmed live against StadiumDB's own club listing
    # ("Royale Union SG") -- doesn't substring-match "st gilloise" at all,
    # a distinct abbreviation for the same club. "gilloise" confirmed live
    # as a 365scores/SoccerDesk-style strict single-token search query
    # (multi-word queries like "st gilloise" return zero results on both,
    # but the single distinctive word does) -- safe as a bare-word alias
    # since no other club plausibly contains it.
    "royale union saint gilloise": ["st gilloise", "union sg", "gilloise"],
}

TEAM_ALIASES: dict[str, list[str]] = {normalize(k): [normalize(a) for a in v] for k, v in _RAW_ALIASES.items()}

_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical for canonical, aliases in TEAM_ALIASES.items() for alias in aliases
}


def canonical_for(name: str) -> str:
    """Normalize `name` and, if it's a known alias of some canonical team
    in the table, return that canonical (normalized) name -- otherwise
    return the normalized input unchanged. Safe to call on any name,
    known or not; callers combine this with their own existing
    normalize+substring fallback rather than relying on it alone."""
    normalized = normalize(name)
    return _ALIAS_TO_CANONICAL.get(normalized, normalized)


def known_aliases_for(name: str) -> list[str]:
    """All known spellings (canonical + every alias) for the team `name`
    belongs to, or just [normalize(name)] if it isn't in the table."""
    canonical = canonical_for(name)
    return [canonical, *TEAM_ALIASES.get(canonical, [])]


def same_team(name_a: str, name_b: str) -> bool:
    """Do two spellings refer to the same club? True when they share any
    known alias (so "Man Utd" and "Manchester United" match even though
    neither contains the other), or when one normalized name contains the
    other -- the substring rule the callers used on its own before, kept
    as the fallback for names the alias table doesn't cover."""
    if set(known_aliases_for(name_a)) & set(known_aliases_for(name_b)):
        return True
    normalized_a, normalized_b = normalize(name_a), normalize(name_b)
    return bool(normalized_a and normalized_b and (normalized_a in normalized_b or normalized_b in normalized_a))


class SlugIndexed(Protocol):
    slug: str


_E = TypeVar("_E", bound=SlugIndexed)


def find_best_slug_match(entries: list[_E], team_name: str) -> _E | None:
    """Match `team_name` against a slug-indexed team list (a sitemap/search
    index entry from any site with a `.slug` field), via 3 passes:

    1. Exact-match across EVERY known alias (see known_aliases_for above)
       before ANY substring fallback for ANY alias. Trying each alias
       sequentially (exact-match THEN substring-fallback, returning on
       the first alias with any hit) is unsafe: the canonical alias is
       usually tried first, and if ITS substring fallback happens to
       match a longer, wrong same-club-family entity (a women's/reserve/
       youth side), that wrong match returns before a later, more
       specific alias ever gets a chance at its own exact match --
       confirmed live as exactly the mechanism behind a real
       Liverpool/Liverpool-Women collision on goal.com.
    2. No exact match for any alias -- pool substring candidates across
       EVERY alias (not just the first one that had any hits), then
       prefer the shortest slug (the main senior club page over a
       "-u21"/"-women" variant), same principle as pass 1.
    3. Reverse direction: a source's official name is sometimes longer
       than another source's short slug ("Girona FC" vs slug "girona")
       -- a 4-char floor keeps a generic short slug from false-matching
       an unrelated longer query.

    Was duplicated verbatim (~20 lines) between goal.py and fotmob.py
    before being consolidated here; each site still layers its own extra
    pre-check on top where its own source has a collision this general
    algorithm alone doesn't resolve (e.g. fotmob.py's per-slug override
    for a case where the wrong team's exact slug is reached before the
    right one, a different failure mode than the substring collision
    this function's own pass 1 already handles)."""
    known = known_aliases_for(team_name)
    for target in known:
        target_slug = target.replace(" ", "-")
        exact = next((e for e in entries if e.slug == target_slug), None)
        if exact:
            return exact

    candidates: list[_E] = []
    for target in known:
        candidates.extend(e for e in entries if target in normalize(e.slug))
    if candidates:
        candidates.sort(key=lambda e: len(e.slug))
        return candidates[0]

    target = normalize(team_name)
    reverse_candidates = [e for e in entries if len(normalize(e.slug)) >= 4 and normalize(e.slug) in target]
    if not reverse_candidates:
        return None
    reverse_candidates.sort(key=lambda e: len(e.slug), reverse=True)
    return reverse_candidates[0]
