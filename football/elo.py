"""Computes an Elo-style rating from a team's own recent match results,
replacing the previous clubelo.com API dependency -- removed because
api.clubelo.com was persistently unreachable from this environment (not a
transient blip, confirmed across repeated checks), and because carrying an
external API dependency cuts against this project's goal of eventually
running entirely inside an Android app with no server.

Important limitation, stated plainly: this is NOT the same metric as
ClubElo's own published ratings. ClubElo continuously calibrates every
team's rating against a global network of results across every team going
back decades, so a rating reflects real strength relative to the whole
football world. This project has no persistent storage between runs and
no independent knowledge of any past opponent's actual strength -- each
run only has one team's own last-N results (already fetched for form.py,
zero extra requests). This calculation assumes every past opponent was
exactly average (baseline rating) and applies the standard Elo update
formula sequentially in play order. The output is a genuine, non-
fabricated computation from real match results, but should be read as
"how strongly has this team performed against an average side over its
last N games" -- a recent-form-strength estimate, not a globally
cross-calibrated power rating. Never presented as directly comparable to
the removed external metric.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from .types import EloRating, FormResult, StandingsTableRow

_BASELINE_RATING = 1500.0
_AVERAGE_OPPONENT_RATING = 1500.0
_K_FACTOR = 32.0


def is_friendly_competition(competition: str | None) -> bool:
    """Shared with form.py's friendly/preseason exclusion and
    insights.py's classify_match_type -- kept as one definition so every
    caller agrees on what counts as a friendly."""
    # "friendly" alone misses the plural -- "friendlies" doesn't contain
    # it as a substring ("...dly" vs "...dlies"), confirmed by testing
    # both real-world label shapes seen live ("Club Friendly Games") and
    # the plural form other sources use ("Club Friendlies"). Pre-season
    # tournaments are sometimes labeled that way instead of "friendly"
    # (e.g. "Premier League Summer Series").
    if not competition:
        return False
    lowered = competition.lower()
    return "friendly" in lowered or "friendlies" in lowered or "pre-season" in lowered or "preseason" in lowered


def _standings_score(row: StandingsTableRow) -> float | None:
    """Season score fraction, (W + D/2) / played -- the same "vs an
    average opponent" reading compute_elo_rating uses, applied to a whole
    league-table record. None when the source omitted W/D/L."""
    if not row.played or row.wins is None or row.draws is None or row.losses is None:
        return None
    return (row.wins + 0.5 * row.draws) / row.played


def league_elo_rank(standings_table: list[StandingsTableRow] | None, position: int | None) -> tuple[int, int, int] | None:
    """(rank, teams_ranked, matches_played) for the table row at
    `position`, ordered by season score fraction (goal difference, then
    points, break ties). Every row is scored the same way, so unlike the
    sequential last-20 `elo` this ranking is like-for-like across the
    league. Rows are matched by table POSITION, not team name, so no fuzzy
    name matching is involved. Elo is monotonic in score fraction, so
    ordering by it is the ordering by Elo-scale rating."""
    if not standings_table or position is None:
        return None
    scored = [(r, s) for r in standings_table if (s := _standings_score(r)) is not None]
    own = next(((r, s) for r, s in scored if r.position == position), None)
    if own is None:
        return None
    scored.sort(key=lambda rs: (rs[1], rs[0].goal_difference or 0, rs[0].points), reverse=True)
    rank = next(i for i, (r, _) in enumerate(scored, start=1) if r.position == position)
    return rank, len(scored), own[0].played


def with_league_rank(elo: EloRating | None, standings_table: list[StandingsTableRow] | None, position: int | None) -> EloRating | None:
    if elo is None:
        return None
    ranked = league_elo_rank(standings_table, position)
    if ranked is None:
        return elo
    rank, of, played = ranked
    elo.rank, elo.rank_of = rank, of
    elo.rank_basis = f"rank among {of} league-table teams by season record vs an average opponent ({played} matches played); not a world rank"
    return elo


def compute_elo_rating(results: list[FormResult]) -> EloRating | None:
    """`results` is expected in the same newest-first order FormSummary's
    last20_overall already uses -- reversed here to process oldest-to-
    newest, since Elo updates must be applied in the order matches were
    actually played.

    Friendlies are excluded first -- confirmed live this matters a lot:
    a real team's last20_overall window can be roughly a third preseason
    "Club Friendly Games" entries (weakened lineups, no real stakes,
    results that don't reflect true strength), which was flattening every
    team's rating toward the same ~1500-1515 band regardless of actual
    quality -- three completely different real matchups (a relegation
    six-pointer, a league leader vs. mid-table, a strong club vs. a
    newly-promoted side) all came back within about 10 Elo points of each
    other before this fix. Falls back to the unfiltered list only if
    every single result is a friendly (better than returning nothing)."""
    competitive = [r for r in results if not is_friendly_competition(r.competition)]
    if not competitive:
        competitive = results
    if not competitive:
        return None
    result_points = {"W": 1.0, "D": 0.5}
    rating = _BASELINE_RATING
    for r in reversed(competitive):
        actual = result_points.get(r.result, 0.0)
        expected = 1.0 / (1.0 + 10 ** ((_AVERAGE_OPPONENT_RATING - rating) / 400.0))
        # Modest goal-margin scaling (a common practical Elo-for-football
        # variant, e.g. FiveThirtyEight's SPI) -- a 4-0 result moves the
        # rating more than a 1-0 does, capped so one blowout can't swing
        # the rating on its own.
        margin_multiplier = 1.0 + min(r.margin, 4) * 0.1
        rating += _K_FACTOR * margin_multiplier * (actual - expected)
    as_of = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return EloRating(elo=round(rating, 1), as_of=as_of)
