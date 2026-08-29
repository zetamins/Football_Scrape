"""Wikipedia scraper. Ported from src/sites/wikipedia.ts.

Wikipedia's robots.txt disallows /w/ (the MediaWiki action API used for
search/query) and /api/ for generic user-agents -- only a few narrow paths
are explicitly allowed there. Plain article pages under /wiki/ are NOT
disallowed (only /wiki/Special:... and other meta/admin namespaces are),
so this fetches the rendered article page directly by constructing the URL
from the manager's name, rather than using the search API to resolve it
first. A manager whose Wikipedia title doesn't exactly match the name
string we have (rare disambiguation cases) just resolves to None rather
than guessing further.
"""

from __future__ import annotations

import re
from typing import Optional
from datetime import datetime, timezone
from urllib.parse import quote

from ..http import USER_AGENT, new_client


async def _fetch_article_html(title: str) -> str | None:
    url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
    async with new_client() as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return None
        return resp.text


_SUP_SPLIT_RE = re.compile(r"<sup\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")


def _strip_tags(html: str) -> str:
    """Footnote reference markers (<sup class="reference">...</sup>) carry
    a data-mw JSON attribute with the citation's raw wikitext inside it,
    including literal unescaped ">" characters -- a naive tag strip
    terminates early on those and leaks citation text into the cell.
    Truncating at the first <sup before stripping avoids that entirely:
    the actual cell content (a date, or "Present") always comes before any
    footnote marker in these tables."""
    before_sup = _SUP_SPLIT_RE.split(html, maxsplit=1)[0]
    return _BRACKET_RE.sub("", _TAG_RE.sub("", before_sup)).strip()


_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

_WIKI_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")


def parse_wiki_date(s: str) -> str | None:
    """Parses "22 December 2019" as UTC midnight directly, rather than a
    local-timezone parse that would silently shift the date by a day
    depending on the running machine's timezone (confirmed live: this
    project has run in an environment where that shift actually
    happened)."""
    m = _WIKI_DATE_RE.match(s.strip())
    if not m:
        return None
    try:
        month = _MONTHS.index(m.group(2).lower())
    except ValueError:
        return None
    dt = datetime(int(m.group(3)), month + 1, int(m.group(1)), tzinfo=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


_TD_RE = re.compile(r"<td[^>]*>([\s\S]*?)</td>", re.IGNORECASE)
_TR_SPLIT_RE = re.compile(r"<tr[ >]", re.IGNORECASE)
_NUMERIC_ONLY_RE = re.compile(r"^[\d,]+$")


_BDAY_RE = re.compile(r'class="bday">(\d{4}-\d{2}-\d{2})<')


class _ManagerRecordRow:
    def __init__(
        self,
        from_date: str | None,
        played: int | None,
        wins: int | None,
        draws: int | None,
        losses: int | None,
        win_pct: float | None,
        date_of_birth: str | None = None,
    ) -> None:
        self.from_date = from_date
        self.played = played
        self.wins = wins
        self.draws = draws
        self.losses = losses
        self.win_pct = win_pct
        # From the same article page's infobox ("Personal information" ->
        # "Date of birth"), a clean machine-readable ISO date in a
        # `class="bday"` span -- zero extra requests.
        self.date_of_birth = date_of_birth


# Win% cells are zero-padded to exactly 2 decimal digits ("056.94",
# "024.29", "000.00") -- confirmed live across every manager page checked,
# and distinctive enough (unlike a plain integer P/W/D/L/GF/GA/GD cell) to
# locate the Record group by CONTENT instead of position. Necessary
# because position-from-either-end isn't reliable: some pages have an
# extra leading flag/icon cell (Paulo Fonseca's), others an extra trailing
# empty Ref-column cell (Niko Kovač's, whose Wikipedia page's ref markup
# leaves that cell text-empty), and at least one manager (Kovač) has been
# seen with the SECOND pattern, breaking a pure end-anchored count that
# only accounted for the first.
_WIN_PCT_RE = re.compile(r"^\d{1,3}\.\d{2}$")


def _find_win_pct_index(row: list[str]) -> int | None:
    for i in range(len(row) - 1, -1, -1):
        if _WIN_PCT_RE.match(row[i]):
            return i
    return None


def _select_current_row(team_rows: list[list[str]]) -> list[str]:
    def to_cell(cells: list[str]) -> str | None:
        wp = _find_win_pct_index(cells)
        return cells[wp - 8] if wp is not None and wp >= 9 else None

    present_row = next((cells for cells in team_rows if (to_cell(cells) or "").lower().find("present") != -1), None)
    return present_row if present_row else team_rows[-1]


def _parse_tenure_fields(
    row: list[str],
) -> tuple[Optional[str], Optional[int], Optional[int], Optional[int], Optional[int], Optional[float]]:
    def to_int(s: str) -> int | None:
        return int(s) if s.isdigit() else None

    # P/W/D/L/GF/GA/GD/Win% is an 8-column group ending at Win% -- located
    # by content (see _WIN_PCT_RE above), not a fixed offset from either
    # end, since neither end is reliably shaped across every manager page.
    wp = _find_win_pct_index(row)
    if wp is None or wp < 9:
        return None, None, None, None, None, None
    from_date = row[wp - 9]
    played, wins, draws, losses = to_int(row[wp - 7]), to_int(row[wp - 6]), to_int(row[wp - 5]), to_int(row[wp - 4])
    win_pct = float(row[wp])
    return from_date, played, wins, draws, losses, win_pct


async def get_current_tenure_row(manager_name: str) -> _ManagerRecordRow | None:
    """Every notable football manager's Wikipedia page carries a
    standardized "Managerial record by team and tenure" table -- Team,
    [optional flag/icon cell -- present on some pages (e.g. Paulo Fonseca's)
    and absent on others (e.g. Didier Digard's), confirmed live, and NOT
    reliably inferable from row length alone], From, To, then an 8-column
    "Record" group (P/W/D/L/GF/GA/GD/Win%) -- confirmed live this is 8
    columns, not 5; fixed positions counted from the START of the row
    previously assumed only P/W/D/L/Win% (5 columns) sat there, which
    silently read the Goals-For column as Win% for every manager (e.g.
    Didier Digard's real 24.29% read back as 71.0, his actual goals-for
    count) and, combined with the optional icon cell, shifted every field
    by one position for managers whose page includes it (e.g. Paulo
    Fonseca's From/Played/Win% all read from the wrong cell entirely).
    Anchoring from the END of the row instead is robust to both: the
    trailing Win%/GD/GA/GF/L/D/W/P/To/From order is consistent regardless
    of whether the optional leading icon cell exists. The row whose "To"
    cell reads "Present" is their current job -- but not every current
    job is marked "Present": a manager on a fixed-term contract (confirmed
    live: Arne Slot's Liverpool row reads "30 May 2026", not "Present",
    despite being his current job) just gets a specific end date there
    instead. Falling back to the LAST real team
    row in the table (chronological order) when no "Present" row exists
    covers that case."""
    html = await _fetch_article_html(manager_name)
    if not html:
        return None

    # Most pages use a "Managerial statistics" subheading; some (e.g. Pep
    # Guardiola's) put the same table directly under a plain "Managerial"
    # section instead -- confirmed live, both lead straight into the same
    # table shape.
    heading_idx = html.find('id="Managerial_statistics"')
    if heading_idx == -1:
        heading_idx = html.find('id="Managerial"')
    if heading_idx == -1:
        return None
    table_start = html.find("<table", heading_idx)
    table_end = html.find("</table>", table_start)
    if table_start == -1 or table_end == -1:
        return None
    table_html = html[table_start:table_end]

    raw_rows = _TR_SPLIT_RE.split(table_html)[1:]
    team_rows = []
    for row in raw_rows:
        cells = [_strip_tags(m.group(1)) for m in _TD_RE.finditer(row)]
        # The final row is a career-totals summary (no team name, just
        # numbers) -- excluded by requiring a non-numeric first cell.
        if len(cells) >= 3 and cells[0] and not _NUMERIC_ONLY_RE.match(cells[0]):
            team_rows.append(cells)
    if not team_rows:
        return None

    row = _select_current_row(team_rows)

    bday_m = _BDAY_RE.search(html)
    from_date, played, wins, draws, losses, win_pct = _parse_tenure_fields(row)
    return _ManagerRecordRow(
        from_date=from_date, played=played, wins=wins, draws=draws, losses=losses, win_pct=win_pct,
        date_of_birth=(bday_m.group(1) if bday_m else None),
    )


async def get_manager_appointment_date(manager_name: str) -> str | None:
    row = await get_current_tenure_row(manager_name)
    return parse_wiki_date(row.from_date) if row and row.from_date else None


async def get_manager_tenure_record(manager_name: str) -> "ManagerTenureRecord | None":
    """Overall P/W/D/L/Win% at the manager's current club, from the same
    table row already parsed for get_manager_appointment_date. Callers
    wanting both should prefer get_current_tenure_row directly to avoid
    fetching the page twice."""
    from ..types import ManagerTenureRecord

    row = await get_current_tenure_row(manager_name)
    if not row or row.played is None or row.wins is None or row.draws is None or row.losses is None:
        return None
    return ManagerTenureRecord(played=row.played, wins=row.wins, draws=row.draws, losses=row.losses, win_pct=row.win_pct)


_TH_OR_TD_RE = re.compile(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", re.IGNORECASE)
# Non-greedy leading [^>]*? avoids the super-linear backtracking risk of
# two adjacent unbounded [^>]* segments around a literal -- flagged by
# static analysis; behavior confirmed identical on real input (several
# real Wikipedia <a> tag shapes), this only changes how a non-match fails,
# not what a match returns.
_LINK_TITLE_RE = re.compile(r'<a[^>]*?title="([^"]+)"[^>]*>', re.IGNORECASE)


def _row_cells(row_html: str) -> list[str]:
    """Every cell in a row, <th> or <td> alike, in document order --
    clubs' list pages aren't consistent about which one holds the manager
    name (confirmed live: Arsenal's uses <th scope="row"> for it,
    Manchester City's uses a plain first <td>), so cells are read
    generically here and matched against the header row's own column order
    instead of a hardcoded position."""
    cells = []
    for m in _TH_OR_TD_RE.finditer(row_html):
        link_m = _LINK_TITLE_RE.search(m.group(1))
        cells.append(link_m.group(1) if link_m else _strip_tags(m.group(1)))
    return cells


async def get_previous_manager(club_name: str) -> str | None:
    """Clubs' own "List of {Club} managers" Wikipedia pages --
    chronologically ordered, current manager last (confirmed live:
    Arsenal's table ends with Arteta, "To" = Present). Tries the "F.C."
    title variant first (the more common English-club naming), then a
    plain variant. Returns the manager immediately before whichever row is
    current -- best-effort, same "may lag a real-world change until
    Wikipedia updates" caveat as get_manager_appointment_date."""
    candidates = [f"List of {club_name} F.C. managers", f"List of {club_name} managers"]
    html: str | None = None
    for title in candidates:
        html = await _fetch_article_html(title)
        if html:
            break
    if not html:
        return None

    # Not necessarily the first <table> on the page -- some clubs'
    # articles (confirmed live: Liverpool's) have an earlier plain
    # formatting/legend table before the real data table. Scanning every
    # table for one whose own header row actually has "Manager" and "To"
    # columns finds the right one regardless of position.
    name_col = -1
    to_col = -1
    rows: list[list[str]] = []
    search_from = 0
    while True:
        table_start = html.find("<table", search_from)
        if table_start == -1:
            break
        table_end = html.find("</table>", table_start)
        if table_end == -1:
            break
        raw_rows = _TR_SPLIT_RE.split(html[table_start:table_end])[1:]
        search_from = table_end + 8
        if not raw_rows:
            continue

        header_cells = [c.lower() for c in _row_cells(raw_rows[0])]
        try:
            candidate_name = header_cells.index("manager")
        except ValueError:
            candidate_name = -1
        try:
            candidate_to = header_cells.index("to")
        except ValueError:
            candidate_to = -1
        if candidate_name == -1 or candidate_to == -1:
            continue

        name_col = candidate_name
        to_col = candidate_to
        rows = [
            cells
            for row in raw_rows[1:]
            if len(cells := _row_cells(row)) > max(candidate_name, candidate_to) and cells[candidate_name]
        ]
        break
    if name_col == -1 or len(rows) < 2:
        return None

    present_idx = next((i for i, cells in enumerate(rows) if re.search(r"present", cells[to_col], re.IGNORECASE)), -1)
    current_idx = present_idx if present_idx != -1 else len(rows) - 1
    return rows[current_idx - 1][name_col] if current_idx > 0 else None
