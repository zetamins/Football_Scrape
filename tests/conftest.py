import asyncio

import httpx
import pytest


@pytest.fixture(autouse=True)
def _block_real_footballdata_network(monkeypatch):
    """football-data.co.uk has no circuit breaker like Sofascore's -- it's
    plain HTTP with an open robots.txt, so nothing stops a real request by
    itself. compute_recent_meetings' historical-odds path (insights.py)
    reaches this module via a chain most H2H tests don't know about and
    so never thought to mock, which otherwise fires a real network call on
    every one of those tests. Default every test to a client that raises
    immediately (no network, no hang) -- tests in test_footballdata.py
    that want real CSV content already monkeypatch footballdata.new_client
    themselves; that per-test patch, applied after this fixture runs,
    simply overrides this default."""
    from football.sites import footballdata

    class _NoNetworkClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("network disabled in tests (see conftest._block_real_footballdata_network)")

    monkeypatch.setattr(footballdata, "new_client", lambda: _NoNetworkClient())


@pytest.fixture(autouse=True)
def _block_real_browser_network(monkeypatch):
    """sofascore.py/squawka.py/worldfootball.py each do `from ..browser
    import launch_browser`, binding their OWN module-level name -- patched
    per-module here rather than football.browser.launch_browser itself, so
    test_browser.py's own real end-to-end launch (against about:blank, not
    a real site) is untouched.

    Confirmed live via `ps aux` mid-test: test_orchestrate.py's
    _apply_own_recent_meetings_and_form tests mock compute_recent_meetings
    and enrich_form_with_venue_classification, but NOT the separate
    _refine_undetailed_meetings call later in the same function, which
    reaches sofascore_site.get_sofascore_older_meeting_info whenever
    form_source=="sofascore" and a meeting lacks a lineup/formation (true
    of the plain _meeting() test helper's defaults) -- a REAL headless
    Chromium process was launching and hitting Sofascore on every run of
    those two tests, for who knows how long before this was noticed.

    Raising inside __aenter__ (not when launch_browser() is merely called)
    mirrors _block_real_footballdata_network's shape; every caller of
    these three modules' launch_browser already wraps it in try/except
    (best-effort per match/stat), so this fails the specific real-site
    attempt quietly instead of silently making it -- tests needing a
    specific response monkeypatch launch_browser (or a narrower seam like
    _fetch_json) themselves, which overrides this default same as the
    footballdata fixture above."""
    from contextlib import asynccontextmanager

    from football.sites import sofascore as sofascore_module
    from football.sites import squawka, worldfootball

    @asynccontextmanager
    async def _no_network_browser():
        raise RuntimeError(
            "real browser launch attempted during tests -- see conftest._block_real_browser_network; "
            "mock launch_browser (or a narrower seam) in this test"
        )
        yield  # pragma: no cover - unreachable, keeps this a valid async generator

    for module in (sofascore_module, squawka, worldfootball):
        monkeypatch.setattr(module, "launch_browser", _no_network_browser)


@pytest.fixture(autouse=True)
def _reset_sofascore_block_state():
    """The Sofascore circuit breaker is module-level state; a test that
    trips it must not leave later tests short-circuited. Also zero the
    inter-request floor for the suite so multi-fetch tests stay fast
    (production keeps 0.8s via _MIN_INTERVAL_S)."""
    from football.sites import sofascore

    original_interval = sofascore._MIN_INTERVAL_S
    sofascore.reset_block_state()
    asyncio.run(sofascore.close_run_session())  # leak insurance: a test that armed a session must not leave it open
    sofascore._MIN_INTERVAL_S = 0
    yield
    sofascore.reset_block_state()
    asyncio.run(sofascore.close_run_session())
    sofascore._MIN_INTERVAL_S = original_interval
