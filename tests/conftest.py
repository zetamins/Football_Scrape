import pytest


@pytest.fixture(autouse=True)
def _reset_sofascore_block_state():
    """The Sofascore circuit breaker is module-level state; a test that
    trips it must not leave later tests short-circuited."""
    from football.sites import sofascore

    sofascore.reset_block_state()
    yield
    sofascore.reset_block_state()
