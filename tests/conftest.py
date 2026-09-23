import pytest


@pytest.fixture(autouse=True)
def _reset_sofascore_block_state():
    """The Sofascore circuit breaker is module-level state; a test that
    trips it must not leave later tests short-circuited. Also zero the
    inter-request floor for the suite so multi-fetch tests stay fast
    (production keeps 0.8s via _MIN_INTERVAL_S)."""
    from football.sites import sofascore

    original_interval = sofascore._MIN_INTERVAL_S
    sofascore.reset_block_state()
    sofascore._MIN_INTERVAL_S = 0
    yield
    sofascore.reset_block_state()
    sofascore._MIN_INTERVAL_S = original_interval
