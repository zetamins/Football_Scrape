"""Rounding helpers matching JavaScript's Math.round()/toFixed() semantics.

Python's built-in round() (and the ":.Nf" format spec) use round-half-to-
even ("banker's rounding"); JS's Math.round()/toFixed() round half towards
positive infinity. They disagree on exact .5 midpoints -- e.g.
round(1.25, 1) is 1.2 in Python but (1.25).toFixed(1) is "1.3" in JS.
Caught while porting geo.ts's travel_time_hours (100/80 = 1.25 exactly);
the same mismatch risk exists anywhere else this project divides then
rounds/formats to a fixed number of decimals (per-game rates, xG sums,
average age, ...). Fixed here once rather than left to silently drift
site-by-site.
"""

from __future__ import annotations

import math


def js_round(x: float) -> int:
    """Math.round(): nearest integer, ties towards +Infinity."""
    return math.floor(x + 0.5)


def js_round_to(x: float, digits: int) -> float:
    factor = 10**digits
    return js_round(x * factor) / factor


def js_to_fixed(x: float, digits: int) -> str:
    """Number.prototype.toFixed(digits), as a string -- always shows
    exactly `digits` decimal places, matching TS's .toFixed(n) call sites
    (e.g. RefereeStats.yellow_cards_per_game)."""
    return f"{js_round_to(x, digits):.{digits}f}"


def js_number(s: str | None) -> float:
    """Number(s) semantics: empty string is 0, an unparseable string is
    NaN (not an exception, unlike Python's float()) -- several site
    scrapers parse loosely-structured CSV/HTML cells this way and rely on
    the graceful-NaN-not-a-crash behavior."""
    if s is None:
        return float("nan")
    s = s.strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return float("nan")


def js_number_to_string(n: float) -> str:
    """String(number) semantics: JS has no separate int/float type, so a
    whole-number float prints without a trailing ".0" ("-1", not "-1.0").
    Caught while porting three65scores.py's standings parsing
    (`String(stat("ratio"))` on a whole-number goal difference)."""
    if n == n and n not in (float("inf"), float("-inf")) and n == int(n):  # noqa: PLR0124  # NOSONAR(S1764) -- portable NaN check, not a typo
        return str(int(n))
    return str(n)


def js_number_or(s: str | None, default: float = 0) -> float:
    """`Number(s) || default` -- JS treats NaN/0/"" as falsy, so this
    substitutes `default` for any of those, not just outright parse
    failure (mirrors sites that write `Number(cell) || 0`)."""
    n = js_number(s)
    if n != n or n == 0:  # noqa: PLR0124  # NOSONAR(S1764) -- portable NaN check, not a typo
        return default
    return n
