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


async def fetch_text(url: str) -> str:
    async with new_client() as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.text


async def fetch_json(url: str) -> Any:
    async with new_client() as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.json()
