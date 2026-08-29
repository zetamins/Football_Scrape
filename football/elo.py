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

from datetime import datetime, timezone
from typing import Optional

from .types import EloRating, FormResult

_BASELINE_RATING = 1500.0
_AVERAGE_OPPONENT_RATING = 1500.0
_K_FACTOR = 32.0


def _is_friendly(competition: Optional[str]) -> bool:
    # "friendly" alone misses the plural -- "friendlies" doesn't contain
    # it as a substring ("...dly" vs "...dlies"), confirmed by testing
    # both real-world label shapes seen live ("Club Friendly Games") and
    # the plural form other sources use ("Club Friendlies").
    if not competition:
        return False
    lowered = competition.lower()
    return "friendly" in lowered or "friendlies" in lowered


def compute_elo_rating(results: list[FormResult]) -> Optional[EloRating]:
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
    competitive = [r for r in results if not _is_friendly(r.competition)]
    if not competitive:
        competitive = results
    if not competitive:
        return None
    rating = _BASELINE_RATING
    for r in reversed(competitive):
        actual = 1.0 if r.result == "W" else 0.5 if r.result == "D" else 0.0
        expected = 1.0 / (1.0 + 10 ** ((_AVERAGE_OPPONENT_RATING - rating) / 400.0))
        # Modest goal-margin scaling (a common practical Elo-for-football
        # variant, e.g. FiveThirtyEight's SPI) -- a 4-0 result moves the
        # rating more than a 1-0 does, capped so one blowout can't swing
        # the rating on its own.
        margin_multiplier = 1.0 + min(r.margin, 4) * 0.1
        rating += _K_FACTOR * margin_multiplier * (actual - expected)
    as_of = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return EloRating(elo=round(rating, 1), rank=None, as_of=as_of)
