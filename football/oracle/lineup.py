"""Lineup picture: who is expected to play and who is missing, from the facts only (no numbers are invented).

Each missing player is classified from the squad list by recent playing time, not reputation: starter (>=60% of available
minutes), rotation (>=25%), fringe, or unknown when the name is not in the squad list. Nothing here moves a probability;
the engine's absence scale stays 0.0 until it passes the gate in research/LINEUP_NEWS_PLAN.md.
"""

from __future__ import annotations

from .facts import norm

STARTER_SHARE = 0.6
ROTATION_SHARE = 0.25
ROTATION_HEAVY = 8


def _status(player: dict | None) -> str:
    if player is None:
        return "unknown"
    share = player["minutes_share"]
    return "starter" if share >= STARTER_SHARE else "rotation" if share >= ROTATION_SHARE else "fringe"


def _side(side: dict, confirmed: bool) -> dict:
    squad = {norm(p["name"]): p for p in side["squad"]}
    absentees = []
    for a in side["absentees"]:
        p = squad.get(norm(a["name"]))
        absentees.append({"name": a["name"], "role": a["role"], "status": _status(p), "impact": a["impact"], "reason": a["reason"]})
    xi = [n for n in side["lineup"] if n]
    names = {norm(n) for n in xi}
    out_names = {norm(a["name"]) for a in side["absentees"]}
    unknown_in_xi = [n for n in xi if squad and norm(n) not in squad]
    rot = side["rotation"] or {}
    return {
        "confirmed_xi": bool(xi) and confirmed, "xi_size": len(xi), "absentees": absentees,
        "starters_out": [a["name"] for a in absentees if a["status"] == "starter"],
        "missing_in_xi": sorted(n for n in xi if norm(n) in out_names),
        "xi_not_in_squad": unknown_in_xi,
        "injured_in_xi": [p["name"] for p in side["squad"] if p["injury"] and norm(p["name"]) in names],
        "empty_absentee_list": not side["absentees"] and any(p["injury"] for p in side["squad"]),
        "heavy_rotation": (rot.get("changed_players") or 0) >= ROTATION_HEAVY and (rot.get("changed_players") or 0) < (rot.get("starting_xi_size") or 99),
    }


def lineup_picture(facts: dict) -> dict:
    """{'home': {...}, 'away': {...}, 'overlap': [names in both XIs], 'confirmed': bool}"""
    confirmed = bool(facts["lineup_confirmed"])
    picture = {side: _side(facts["sides"][side], confirmed) for side in ("home", "away")}
    both = {norm(n) for n in facts["sides"]["home"]["lineup"] if n} & {norm(n) for n in facts["sides"]["away"]["lineup"] if n}
    picture["overlap"] = sorted(both)
    picture["confirmed"] = confirmed
    return picture
