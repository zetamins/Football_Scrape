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
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def retry_with_backoff(fn: Callable[[], Awaitable[T]], attempts: int = 3) -> T:  # NOSONAR(S6796) -- PEP 695 generic syntax (def foo[T](...)) needs Python 3.12+, incompatible with this project's declared requires-python = ">=3.11" (this exact PEP 695 swap was already tried and reverted here once, see git history); TypeVar is the correct, intentional form
    # Exception, not BaseException -- catching BaseException would also
    # swallow KeyboardInterrupt/SystemExit/GeneratorExit and retry a
    # deliberate interruption instead of honoring it, which is a real bug,
    # not just an overly-broad catch. Still deliberately generic beyond
    # that: `fn` can be any of this project's own scrape functions, whose
    # failure modes this module has no visibility into by design -- see
    # the module docstring for why retrying broadly (rather than picking
    # specific exception types up front) is the intended behavior here.
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as err:  # noqa: BLE001
            last_err = err
            if i < attempts - 1:
                delay_s = 3 * 2**i  # 3s, 6s, 12s
                await asyncio.sleep(delay_s)
    assert last_err is not None
    raise last_err
