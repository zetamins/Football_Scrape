"""One Squawka stat answering with an error payload must be retried and reported, not silently left empty."""
import asyncio

import pytest

from football.sites import squawka


class _Page:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    async def evaluate(self, _js, _arg):
        self.calls += 1
        return self.answers.pop(0)


def test_error_payload_raises_and_real_empty_does_not():
    with pytest.raises(RuntimeError):
        asyncio.run(squawka._fetch_stat_values(_Page([{"code": "rest_cookie_invalid_nonce"}]), "n", "1", "Blocked Shots"))
    with pytest.raises(RuntimeError):
        asyncio.run(squawka._fetch_stat_values(_Page([None]), "n", "1", "Blocked Shots"))
    assert asyncio.run(squawka._fetch_stat_values(_Page([{"items": [], "http_status": 200, "curl_message": ""}]), "n", "1", "Blocked Shots")) == {}
    # an upstream failure inside a well-formed envelope (items empty, status or curl error set) is an error too
    for bad in ({"items": [], "http_status": 502, "curl_message": ""}, {"items": [], "http_status": 200, "curl_message": "Operation timed out"}, {"items": [], "http_status": 0, "curl_message": "x"}):
        with pytest.raises(RuntimeError):
            asyncio.run(squawka._fetch_stat_values(_Page([bad]), "n", "1", "Blocked Shots"))
    # a stat with no data still returns its items with null values: not an error
    nul = {"name": "A B", "participant_name": "Arsenal", "statistic_groups": [{"statistics": [{"value": None}]}]}
    assert asyncio.run(squawka._fetch_stat_values(_Page([{"items": [nul], "http_status": 200, "curl_message": ""}]), "n", "1", "Red Cards")) == {}


def test_stat_is_retried_once_after_an_error_payload(monkeypatch):
    async def no_sleep(_s):
        return None
    monkeypatch.setattr("football.retry.asyncio.sleep", no_sleep)
    item = {"name": "Bukayo Saka", "participant_name": "Arsenal", "statistic_groups": [{"statistics": [{"value": 4}]}]}
    page = _Page([{"message": "slow down"}, {"items": [item]}])
    got = asyncio.run(squawka.retry_with_backoff(lambda: squawka._fetch_stat_values(page, "n", "1", "Blocked Shots"), attempts=2))
    assert page.calls == 2 and list(got.values()) == [4]
