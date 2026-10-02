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
