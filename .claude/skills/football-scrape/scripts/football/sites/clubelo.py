"""ClubElo scraper (clubelo.com).

api.clubelo.com is unreachable from here (connection timeout, confirmed live),
but the main site's per-club HTML page is not: https://clubelo.com/<Club>
carries the current Elo and Golo in its header line and the club's whole
dated rating history in an embedded chart payload, so one page per club gives
a long-run rating that is directly comparable between any two clubs. This is
the missing piece elo.py's own docstring describes (its rating only knows a
side's own recent results).

The site's robots.txt answers with a redirect (no rules published); one page
per club, two per match, plus the front page once (it lists every rated club
with its country, which rates the opponents in both form tables), no crawling."""

from __future__ import annotations

import re
from datetime import date, timedelta

from ..http import fetch_text
from ..team_aliases import known_aliases_for
from ..types import ClubEloRating

_BASE = "https://clubelo.com/"
_MAX_ATTEMPTS = 8

_HEADER = re.compile(r"Elo:\s*<b>([\d.]+)</b>(?:\s*\(Best:\s*([\d.]+),\s*reached on\s*(\d{4}-\d{2}-\d{2})\))?")
_GOLO = re.compile(r"Golo:\s*([\d.]+)")
_AS_OF = re.compile(r'<h1><a href="/(\d{4}-\d{2}-\d{2})/')
_H1_NAME = re.compile(r'<h1><a href="/\d{4}-\d{2}-\d{2}/[^"]*">([^<]+)</a>')
_POINT = re.compile(r'"Date":\s*"(\d{4}-\d{2}-\d{2})T[^"]*",\s*"Elo":\s*([\d.]+)')


def parse_club_page(html: str) -> ClubEloRating | None:
    """None when the page has no rating line (unknown club / layout change)."""
    head = _HEADER.search(html)
    if head is None:
        return None
    elo = float(head.group(1))
    golo = _GOLO.search(html)
    as_of = _AS_OF.search(html)
    history = [(d, float(v)) for d, v in _POINT.findall(html)]
    change = None
    if as_of and history:
        cutoff = (date.fromisoformat(as_of.group(1)) - timedelta(days=90)).isoformat()
        older = [v for d, v in history if d <= cutoff]
        if older:
            change = round(elo - older[-1], 1)
    return ClubEloRating(
        elo=elo,
        as_of=as_of.group(1) if as_of else None,
        golo=float(golo.group(1)) if golo else None,
        best=float(head.group(2)) if head.group(2) else None,
        best_date=head.group(3),
        change_90d=change,
    )


def _fold(text: str, german: bool = False) -> str:
    """Accents folded to plain letters ("Atlético" -> "Atletico"); with german=True the umlauts become digraphs ("Köln" -> "Koeln")."""
    import unicodedata
    if german:
        text = text.replace("ö", "oe").replace("ü", "ue").replace("ä", "ae").replace("Ö", "Oe").replace("Ü", "Ue").replace("Ä", "Ae")
    text = text.replace("ß", "ss").replace("ø", "o").replace("Ø", "O").replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def slug_candidates(team_name: str) -> list[str]:
    """ClubElo page names are the club name with spaces dropped ("ManCity",
    "RealMadrid"); the site is case-sensitive and a few clubs live under an
    all-lowercase name ("atalanta", "realmadrid", "atletico"), and a miss is a
    200 with an empty page, so each spelling is tried as capitalised then
    lowercase. Order: searched name, aliases, then the first word alone for
    ClubElo's short names ("Hajduk", "Bayern"). At most _MAX_ATTEMPTS pages."""
    words_of = lambda n: re.sub(r"[^A-Za-z0-9 ]", "", _fold(n)).split()   # noqa: E731
    out: list[str] = []

    def add(slug: str) -> None:
        if slug and slug not in out:
            out.append(slug)

    full = "".join(w[:1].upper() + w[1:] for w in words_of(team_name))
    add(full)
    add(full.lower())
    words = words_of(team_name)
    for w in (words[:1] + words[-1:]):                  # ClubElo's short names are either end of the name: "Hajduk", "Bayern", "Forest", "Frankfurt", "Sociedad"
        if len(w) >= 5:
            add(w[:1].upper() + w[1:])
    de = [w for w in re.sub(r"[^A-Za-z0-9 ]", "", _fold(team_name, german=True)).split() if len(w) >= 4]
    for w in de[-1:] + de[:1]:                          # Köln is "Koeln" on ClubElo
        if w.lower() in ("koeln", "muenchen", "nuernberg", "duesseldorf"):
            add(w[:1].upper() + w[1:].lower())
    for name in known_aliases_for(team_name):
        slug = "".join(w[:1].upper() + w[1:] for w in words_of(name))
        add(slug)
        add(slug.lower())
    for w in (words[:1] + words[-1:]):
        if len(w) >= 5:
            add(w.lower())
    return out[:_MAX_ATTEMPTS]


def _page_is_this_club(html: str, team_name: str) -> bool:
    """A fallback slug must not land on another club: the page's own heading
    name has to appear among the searched name's words."""
    m = _H1_NAME.search(html)
    if m is None:
        return False
    page = re.sub(r"[^a-z0-9 ]", "", m.group(1).lower()).split()
    searched = re.sub(r"[^a-z0-9 ]", "", team_name.lower()).split()
    if page and searched and len(page[0]) >= 5 and page[0] == searched[0]:      # "Bayern München" v "Bayern Munich"
        return True
    return bool(page) and (all(w in searched for w in page) or any(re.sub(r"[^a-z0-9]", "", m.group(1).lower()) == re.sub(r"[^a-z0-9]", "", a) for a in known_aliases_for(team_name)))


async def get_club_elo(team_name: str) -> ClubEloRating | None:
    """A 404 on one candidate spelling moves to the next; any other failure
    (timeout, block) stops at once -- no retry loop against the site."""
    for slug in slug_candidates(team_name):
        try:
            html = await fetch_text(_BASE + slug)
        except Exception as err:  # noqa: BLE001
            if "404" in str(err):
                continue
            raise
        rating = parse_club_page(html)
        if rating is not None and _page_is_this_club(html, team_name):
            return rating
    return None


async def get_club_elo_ratings(home_team: str, away_team: str) -> dict[str, ClubEloRating | None]:
    return {"home": await get_club_elo(home_team), "away": await get_club_elo(away_team)}


# Front-page rows: a country flag link, then the club (linked or plain) and its rating.
_RANK_ROW = re.compile(
    r'<a href="/([A-Z]{3})"><img[^>]*></a>(?:(?!</tr>).)*?<span class="Ast">([^<]+)</span>(?:</a>)?</td><td class="r">(\d+)</td>',
    re.S,
)
_GENERIC = {"fc", "sc", "cf", "ac", "afc", "nk", "hnk", "gnk", "fk", "sk", "sv", "vfb", "vfl", "bv", "rc", "cd", "ud", "sd", "ca", "club", "de", "the", "1", "if", "bk", "kv", "krc"}


def parse_ranking(html: str) -> list[tuple[str, str, float]]:
    """(country code, ClubElo name, rating) for every club on the front page."""
    return [(c, n.strip(), float(e)) for c, n, e in _RANK_ROW.findall(html)]


def _tokens(name: str, keep_generic: bool = False) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", _fold(name).lower()).split() if keep_generic or w not in _GENERIC]


def match_ranked_club(name: str, ranking: list[tuple[str, str, float]], prefer_country: str | None = None) -> tuple[str, float] | None:
    """The ranking row whose every name word starts a word of `name` ("Lok Zagreb" ~ "NK Lokomotiva Zagreb",
    "Sittard" ~ "Fortuna Sittard"), most words first; a tie is broken by `prefer_country`, then by the first word
    ("PSV" over "Eindhoven" for "PSV Eindhoven"), and is otherwise
    no match, so an ambiguous name ("Barcelona") is left unrated rather than guessed."""
    want, every = _tokens(name), _tokens(name, keep_generic=True)
    if not want:
        return None
    hits = []
    for country, club, elo in ranking:
        words = _tokens(club, keep_generic=True)      # ClubElo keeps "FC" only to tell clubs apart ("Paris FC" is not "Paris Saint-Germain")
        if words and all(any(t == w or (len(w) == 3 and t.startswith(w)) for t in every) for w in words):      # a word, or a 3-letter abbreviation ("Lok"); "Vardar" is not "Vardarac", "Port" is not "Porto"
            hits.append((len(words), country == prefer_country, words[0] in (want[0], every[0]), country, elo))
    if not hits:
        return None
    hits.sort(reverse=True)
    best = hits[0]
    rivals = [h for h in hits[1:] if h[:3] == best[:3]]
    if rivals and any(h[4] != best[4] for h in rivals):
        return None
    return best[3], best[4]


async def get_ranking() -> list[tuple[str, str, float]]:
    """One fetch of the front page; [] when it cannot be read."""
    return parse_ranking(await fetch_text(_BASE))
