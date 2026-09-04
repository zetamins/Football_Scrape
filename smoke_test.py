"""Manual smoke test for Phase 3 -- not part of the pytest suite (hits the
live Sofascore site, slow and non-deterministic). Run directly:
    uv run python smoke_test.py "Liverpool"
"""

import asyncio
import sys
from dataclasses import asdict

from football.sites.sofascore import (
    get_sofascore_match_details,
    get_sofascore_matches,
    get_sofascore_team_profile,
)


def _default(o):
    return str(o)


async def main() -> None:
    team_name = " ".join(sys.argv[1:]) or "Liverpool"

    print(f"--- get_sofascore_matches({team_name!r}) ---")
    matches = await get_sofascore_matches(team_name)
    print(f"{len(matches)} matches found")
    for m in matches[:3]:
        print(f"  {m.home_team} vs {m.away_team} -- {m.kickoff_utc} -- {m.status} -- {m.competition}")

    upcoming = next((m for m in matches if m.status == "notstarted"), matches[0] if matches else None)
    if upcoming is None:
        print("No match to fetch details for -- stopping.")
        return

    print(f"\n--- get_sofascore_match_details() for {upcoming.home_team} vs {upcoming.away_team} ---")
    details = await get_sofascore_match_details(upcoming)
    d = asdict(details)
    populated = sum(1 for v in d.values() if v not in (None, [], {}, ""))
    print(f"{populated}/{len(d)} top-level fields populated")
    print(f"  venue: {details.venue_name}, {details.venue_city}, {details.venue_country}")
    print(f"  referee: {details.referee}  stats: {details.referee_stats}")
    print(f"  home manager: {details.home_manager}")
    print(f"  standings table entries: {len(details.standings_table) if details.standings_table else 0}")
    print(f"  note: {details.note}")

    print(f"\n--- get_sofascore_team_profile({team_name!r}) ---")
    profile = await get_sofascore_team_profile(team_name)
    print(f"  squad size: {len(profile.squad) if profile.squad else 0}")
    print(f"  average age: {profile.average_age}")
    print(f"  injuries: {len(profile.injuries) if profile.injuries else 0}")
    print(f"  recent transfers: {len(profile.recent_transfers) if profile.recent_transfers else 0}")
    if profile.squad:
        sample = profile.squad[0]
        print(f"  sample player: {sample.name} ({sample.role}), age {sample.age}, stats: {sample.season_stats}")

    print("\nOK -- no exceptions, structurally sane output.")


if __name__ == "__main__":
    asyncio.run(main())
