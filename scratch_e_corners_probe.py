"""Diagnose E: Man Utd vs Tottenham corners_for both 47 over sample 7.

Read-only against goal.com (plain HTTP, sequential, no retries — no-hammer).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from football.form import is_team_home  # noqa: E402
from football.insights import compute_possession_matchup  # noqa: E402
from football.sites import goal  # noqa: E402


async def main() -> None:
    for name in ("Manchester United", "Tottenham Hotspur"):
        index = await goal._load_teams_index()
        team = goal._find_best_team_match(index, name)
        print(f"team {name!r} -> id={getattr(team, 'id', None)} slug={getattr(team, 'slug', None)} url={getattr(team, 'url', None)}")

    man = await goal.get_goal_matches("Manchester United")
    tot = await goal.get_goal_matches("Tottenham Hotspur")
    print(f"man matches={len(man)} tot matches={len(tot)}")
    man_ids = {m.match_id for m in man}
    tot_ids = {m.match_id for m in tot}
    overlap = man_ids & tot_ids
    print(f"overlap match_ids ({len(overlap)}): {sorted(overlap)[:10]}")

    man_fin = sorted((m for m in man if m.status == "finished" and m.kickoff_utc), key=lambda m: m.kickoff_utc, reverse=True)[:10]
    tot_fin = sorted((m for m in tot if m.status == "finished" and m.kickoff_utc), key=lambda m: m.kickoff_utc, reverse=True)[:10]
    print(f"man finished[:10]={len(man_fin)} tot finished[:10]={len(tot_fin)}")
    for label, ms, tname in (("MAN", man_fin, "Manchester United"), ("TOT", tot_fin, "Tottenham Hotspur")):
        print(f"--- {label} ---")
        for m in ms:
            h = is_team_home(m, tname)
            print(f"  {m.kickoff_utc} {m.home_team} {m.home_score}-{m.away_score} {m.away_team} home={h} id={m.match_id}")

    own = await compute_possession_matchup("Manchester United", man)
    opp = await compute_possession_matchup("Tottenham Hotspur", tot)
    print("own corners", own.corners)
    print("opp corners", opp.corners)

    # Also dump raw Corner total from first few detail fetches
    from football.http import new_client
    from football.sites.goal import get_goal_match_details

    async with new_client() as client:
        for label, ms, tname in (("MAN", man_fin, "Manchester United"), ("TOT", tot_fin, "Tottenham Hotspur")):
            print(f"--- {label} per-match Corner total ---")
            for m in ms:
                home = is_team_home(m, tname)
                try:
                    details = await get_goal_match_details(m, client)
                except Exception as err:
                    print(f"  {m.match_id} ERROR {err}")
                    continue
                cs = next((s for s in (details.match_stats or []) if s.name == "Corner total"), None)
                if not cs:
                    print(f"  {m.match_id} no Corner total | {m.home_team} vs {m.away_team}")
                    continue
                print(
                    f"  {m.match_id} home={home} raw={cs.home}/{cs.away} "
                    f"for={cs.home if home else cs.away} against={cs.away if home else cs.home} "
                    f"| {m.home_team} vs {m.away_team}"
                )


if __name__ == "__main__":
    asyncio.run(main())
