"""Shared plain-HTTP fetch helpers for the 10 non-browser-dependent site
scrapers (everything except sofascore/squawka/worldfootball, which need
real Chromium -- see browser.py). Each original TS file duplicated its own
fetchJson/fetchText with the same User-Agent header and `if (!res.ok) throw`
handling; consolidated here since porting touches every one of these files
anyway. Per-site deviations (retry loops, "return null instead of throw")
stay local to that site's module rather than being forced into one generic
shape here.

`http2=True` is load-bearing, not an optimization: found while porting
wikipedia.py -- en.wikipedia.org's edge returns 403 ("please respect our
robot policy") to a browser-UA request sent over plain HTTP/1.1, but
accepts the identical request over HTTP/2 (confirmed directly: same
headers, only the negotiated protocol differed). httpx defaults to
HTTP/1.1 unless told otherwise; a real browser (and Node's fetch, which
the original TS version used) negotiates HTTP/2 automatically, so an
HTTP/1.1-only client carrying a Chrome User-Agent is itself a bot signal
to a fingerprinting edge. Likely relevant to any of these 10 sites, not
just Wikipedia, so applied here globally rather than per-site.
"""

from __future__ import annotations

from typing import Any

import httpx

from .fetch_log import record_failure

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_TIMEOUT = httpx.Timeout(30.0)


def new_client() -> httpx.AsyncClient:
    """Shared client factory -- use this instead of constructing
    httpx.AsyncClient directly, so the http2=True fix above (and any
    future one like it) applies everywhere, not just here."""
    return httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, http2=True)


async def fetch_text(url: str, client: httpx.AsyncClient | None = None) -> str:
    """`client` is optional -- omit it for a one-off fetch (a fresh
    client is created and closed for you, same as before). Pass a
    client a caller already owns when making several sequential
    requests to the same host in a loop (e.g. insights.py's
    compute_possession_matchup, fetching up to 20 Goal.com match pages
    one at a time) -- confirmed live this matters a lot, not just in
    theory: creating a brand-new client per request means paying a
    fresh DNS lookup + TCP + TLS handshake on EVERY one of those 20
    requests instead of once, which measured ~6 minutes on a real
    Android emulator for the same work that took ~12 seconds on a
    host machine with a warm DNS cache and low round-trip latency --
    httpx's connection-pooling/keep-alive (the whole point of reusing
    one AsyncClient) only helps when a client is actually reused across
    calls to the same host."""
    owns_client = client is None
    active = client or new_client()
    try:
        resp = await active.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.text
    except Exception as err:
        record_failure(url, err)
        raise
    finally:
        if owns_client:
            await active.aclose()


async def fetch_json(url: str, client: httpx.AsyncClient | None = None) -> Any:
    """See fetch_text's docstring for the optional `client` parameter."""
    owns_client = client is None
    active = client or new_client()
    try:
        resp = await active.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.json()
    except Exception as err:
        record_failure(url, err)
        raise
    finally:
        if owns_client:
            await active.aclose()
