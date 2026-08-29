"""football-data.co.uk scraper. Ported from src/sites/footballdata.ts.

football-data.co.uk's robots.txt is fully open ("Disallow:" with nothing
after it, for User-agent: *) -- plain fetch works, no browser needed.
Per-season, per-league CSVs with real per-match data (scores, cards,
referee name, shots, etc). Same "big 5" scope as worldfootball.py's
COMPETITION_PATHS -- deliberately small, hand-maintained mapping to this
site's own two-letter+digit codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .._jsmath import js_number_or, js_round_to
from ..http import USER_AGENT, new_client
from ..team_aliases import canonical_for
from ..types import BettingOdds, RefereeHomeAwayBias

_COMPETITION_CODES: dict[str, str] = {
    "Premier League": "E0",
    "LaLiga": "SP1",
    "La Liga": "SP1",
    "Serie A": "I1",
    "Bundesliga": "D1",
    "Ligue 1": "F1",
}


def _season_code(offset: int) -> str:
    """The football calendar year starts around July/August -- before
    that, "this season" is (lastYear, thisYear); after, it's (thisYear,
    nextYear)."""
    now = datetime.now(tz=timezone.utc)
    start_year = (now.year if now.month >= 7 else now.year - 1) - offset

    def yy(y: int) -> str:
        return f"{y % 100:02d}"

    return f"{yy(start_year)}{yy(start_year + 1)}"


async def _fetch_csv_or_none(url: str) -> str | None:
    async with new_client() as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return None
        return resp.text


@dataclass
class _MatchRow:
    referee: str
    home_yellow: int
    away_yellow: int
    home_red: int
    away_red: int


def _parse_rows(csv: str) -> list[_MatchRow]:
    """Minimal CSV split -- these files have no quoted commas in the
    columns this parser reads (Referee/HY/AY/HR/AR are all plain tokens),
    so a naive split is safe here even though the file has 100+ columns
    overall (odds data this project doesn't touch)."""
    lines = csv.strip().split("\n")
    header = lines[0].split(",")

    def col(name: str) -> int:
        return header.index(name) if name in header else -1

    idx = {"referee": col("Referee"), "hy": col("HY"), "ay": col("AY"), "hr": col("HR"), "ar": col("AR")}
    if any(i == -1 for i in idx.values()):
        return []

    rows: list[_MatchRow] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split(",")
        referee = cells[idx["referee"]].strip() if idx["referee"] < len(cells) else ""
        if not referee:
            continue
        rows.append(
            _MatchRow(
                referee=referee,
                home_yellow=int(js_number_or(cells[idx["hy"]]) if idx["hy"] < len(cells) else 0),
                away_yellow=int(js_number_or(cells[idx["ay"]]) if idx["ay"] < len(cells) else 0),
                home_red=int(js_number_or(cells[idx["hr"]]) if idx["hr"] < len(cells) else 0),
                away_red=int(js_number_or(cells[idx["ar"]]) if idx["ar"] < len(cells) else 0),
            )
        )
    return rows


def _surname(name: str) -> str:
    """football-data.co.uk uses "Initial Surname" ("C Pawson"), unlike
    Sofascore's full first name ("Craig Pawson") -- matching on surname
    alone (last whitespace-separated token) is the reliable common ground."""
    parts = name.strip().lower().split()
    return parts[-1] if parts else ""


async def get_referee_home_away_bias(
    competition: str | None, referee_name: str | None
) -> RefereeHomeAwayBias | None:
    """Tries this season's file first, then last season's -- early in a new
    season (or before it starts) the current file may be empty or not yet
    published (confirmed live: the file 404s outright until the season is
    underway), so falling back to the most recently completed season keeps
    this from going empty for months at a time. Counts yellow+red combined
    as "cards" -- same generic definition as CardDisciplineInfo elsewhere
    in this project."""
    if not competition or not referee_name:
        return None
    code = _COMPETITION_CODES.get(competition)
    if not code:
        return None

    csv: str | None = None
    for offset in (0, 1):
        try:
            csv = await _fetch_csv_or_none(f"https://www.football-data.co.uk/mmz4281/{_season_code(offset)}/{code}.csv")
        except httpx.HTTPError:
            csv = None
        if csv:
            break
    if not csv:
        return None

    rows = _parse_rows(csv)
    target = _surname(referee_name)
    matches = [r for r in rows if _surname(r.referee) == target]
    if not matches:
        return None

    home_cards = sum(r.home_yellow + r.home_red for r in matches)
    away_cards = sum(r.away_yellow + r.away_red for r in matches)
    return RefereeHomeAwayBias(
        sample_size=len(matches),
        home_cards_per_game=js_round_to(home_cards / len(matches), 2),
        away_cards_per_game=js_round_to(away_cards / len(matches), 2),
    )


def _odds_match_name(name: str) -> str:
    return canonical_for(name)


def _names_match(a: str, b: str) -> bool:
    a, b = _odds_match_name(a), _odds_match_name(b)
    return a == b or a in b or b in a


async def get_upcoming_match_odds(home_team: str, away_team: str) -> BettingOdds | None:
    """One shared fetch (a single live all-leagues upcoming-fixtures file,
    distinct from the per-season results CSV get_referee_home_away_bias
    uses) covers every match across every league football-data.co.uk
    tracks -- no competition lookup needed, unlike the referee-bias path
    above. Uses each market's "Avg" column (the average across every
    bookmaker tracked for that match) as the representative odds, and
    derives implied win/draw/loss percentages via the standard de-vig
    calculation (each outcome's 1/odds share renormalized to sum to
    100%). Best-effort: None if the match isn't found (fixture not yet
    published, name-match miss, or the match isn't in a tracked league)."""
    try:
        csv = await _fetch_csv_or_none("https://www.football-data.co.uk/fixtures.csv")
    except httpx.HTTPError:
        csv = None
    if not csv:
        return None

    lines = csv.strip().split("\n")
    header = lines[0].strip().split(",")

    def col(name: str) -> int:
        return header.index(name) if name in header else -1

    idx = {
        "home": col("HomeTeam"), "away": col("AwayTeam"),
        "avg_h": col("AvgH"), "avg_d": col("AvgD"), "avg_a": col("AvgA"),
        "avg_over": col("Avg>2.5"), "avg_under": col("Avg<2.5"),
    }
    if idx["home"] == -1 or idx["away"] == -1:
        return None

    row: list[str] | None = None
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split(",")
        if len(cells) <= max(idx["home"], idx["away"]):
            continue
        if _names_match(cells[idx["home"]], home_team) and _names_match(cells[idx["away"]], away_team):
            row = cells
            break
    if row is None:
        return None

    def cell_float(key: str) -> float | None:
        i = idx[key]
        if i == -1 or i >= len(row):
            return None
        raw = row[i].strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    home_odds = cell_float("avg_h")
    draw_odds = cell_float("avg_d")
    away_odds = cell_float("avg_a")

    home_pct = draw_pct = away_pct = None
    if home_odds and draw_odds and away_odds:
        inv_h, inv_d, inv_a = 1 / home_odds, 1 / draw_odds, 1 / away_odds
        total = inv_h + inv_d + inv_a
        home_pct = js_round_to(100 * inv_h / total, 1)
        draw_pct = js_round_to(100 * inv_d / total, 1)
        away_pct = js_round_to(100 * inv_a / total, 1)

    return BettingOdds(
        home_win_odds=home_odds,
        draw_odds=draw_odds,
        away_win_odds=away_odds,
        home_win_implied_pct=home_pct,
        draw_implied_pct=draw_pct,
        away_win_implied_pct=away_pct,
        over_2_5_odds=cell_float("avg_over"),
        under_2_5_odds=cell_float("avg_under"),
    )
