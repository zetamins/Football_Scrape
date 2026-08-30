"""Shared retry-with-backoff helper for the 3 browser-dependent scrapers.

Extracted from sofascore.py (where it originated) so worldfootball.py and
squawka.py can use the same resilience sofascore.py already had, rather
than each browser-dependent source having a different failure tolerance
for the same class of problem: a transient goto()/evaluate() failure
(network hiccup, a slow challenge that genuinely times out once, a
momentary site error) that a second attempt often clears.

Deliberately NOT applied universally without judgment -- see
sofascore.py's _find_team docstring for a documented case where retrying
was confirmed live to make things worse (resending requests at an
already-blocked connection rather than clearing anything). Call sites
choose whether and where retrying is safe for their own request shape;
this module only provides the mechanism.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

_T = TypeVar("_T")


async def retry_with_backoff(fn: Callable[[], Awaitable[_T]], attempts: int = 3) -> _T:
    last_err: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except BaseException as err:  # noqa: BLE001 - re-raised below, mirrors TS catch-all
            last_err = err
            if i < attempts - 1:
                delay_s = 3 * 2**i  # 3s, 6s, 12s
                await asyncio.sleep(delay_s)
    assert last_err is not None
    raise last_err
