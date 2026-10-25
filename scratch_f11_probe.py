"""F11 research probe: sofascore event 16363879 /h2h + /team-streaks via browser logic only.

Uses football.browser.launch_browser + sofascore._fetch_json (same-origin
in-page fetch after homepage warm-up -- never page.goto to /api/, never
curl/httpx). Human-like jittered pacing. Reports both endpoints even when
the first trips the 403 breaker (SofascoreBlockedError). Stops after a
block rather than hammering.
"""

from __future__ import annotations

import asyncio
import json

from football.sites.sofascore import (
    SofascoreBlockedError,
    _fetch_json,
    _sleep,
    _warm_up,
    is_blocked,
    reset_block_state,
)


EVENT_ID = 16363879


def summarize(label: str, data) -> None:
    print(f"=== {label} ===")
    if data is None:
        print("  None")
        return
    if not isinstance(data, dict):
        print(f"  type={type(data).__name__} value={data!r}")
        return
    if "error" in data:
        print(f"  error payload: {json.dumps(data, ensure_ascii=False)[:400]}")
        return
    print(f"  top-level keys: {sorted(data.keys())}")
    h2h_obj = data.get("h2h") if isinstance(data.get("h2h"), dict) else data
    if isinstance(h2h_obj, dict):
        print(f"  h2h-ish keys: {sorted(h2h_obj.keys())}")
        for k in ("teamDuel", "managerDuel", "teamDuels", "managerDuels"):
            if k in h2h_obj:
                v = h2h_obj[k]
                print(f"  {k}: {type(v).__name__} = {json.dumps(v, ensure_ascii=False)[:600]}")
    for k in ("head2head", "home", "away", "homeTeam", "awayTeam", "streaks"):
        if k in data:
            v = data[k]
            length = len(v) if hasattr(v, "__len__") and not isinstance(v, (int, float, bool)) else "n/a"
            print(f"  {k}: {type(v).__name__} len={length} sample={json.dumps(v, ensure_ascii=False)[:600]}")
    preview = {
        k: (type(v).__name__, (len(v) if hasattr(v, "__len__") and not isinstance(v, (int, float, bool)) else v))
        for k, v in data.items()
    }
    print(f"  preview: {preview}")


async def fetch_one(page, url: str):
    try:
        return await _fetch_json(page, url)
    except SofascoreBlockedError as err:
        print(f"  blocked before request: {err}")
        return None
    except Exception as err:  # noqa: BLE001
        print(f"  fetch failed: {type(err).__name__}: {err}")
        return None


async def main() -> None:
    reset_block_state()
    from football.browser import launch_browser

    async with launch_browser() as browser:
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await _warm_up(page)
        except SofascoreBlockedError as err:
            print(f"warm-up blocked: {err}")
            return
        except Exception as err:  # noqa: BLE001
            print(f"warm-up failed: {type(err).__name__}: {err}")
            # still try the endpoints -- warm-up 403 may be homepage-only

        await _sleep(800)
        h2h = await fetch_one(page, f"https://www.sofascore.com/api/v1/event/{EVENT_ID}/h2h")
        summarize("h2h", h2h)
        if is_blocked():
            print("breaker open after h2h -- not requesting team-streaks (no hammer)")
            return

        await _sleep(800)
        streaks = await fetch_one(page, f"https://www.sofascore.com/api/v1/event/{EVENT_ID}/team-streaks")
        summarize("team-streaks", streaks)
        if is_blocked():
            print("breaker open after team-streaks")


if __name__ == "__main__":
    asyncio.run(main())
