"""Report JSON -> Facts: everything the Oracle uses, extracted deterministically and normalised to the HOME/AWAY frame.

Player-level absence impact: each absentee is matched to the squad list by name; its weight is its share of total squad
market value, scaled by how much it has actually played recently (0.5 + 0.5 * minutes share of the last games). Shares are
summed per role group (attack = F + half of M, defence = D + G + half of M).
"""

from __future__ import annotations

import unicodedata
from typing import Any

from ..analyze import _parse_score  # validated form-row orientation logic (tests/test_analyze.py)
from ..national_elo import canonical_name

GOAL_CAP = 6
ATTACK_ROLES = {"F": 1.0, "M": 0.5}
DEFENCE_ROLES = {"D": 1.0, "G": 1.0, "M": 0.5}


def _get(d: Any, *path: str, default=None):
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
    return default if d is None else d


_FOLD = str.maketrans({"ı": "i", "İ": "i", "ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "đ": "d", "Đ": "d", "ß": "ss", "æ": "ae", "œ": "oe"})  # letters NFKD does not decompose


def norm(s: str | None) -> str:
    s = s if isinstance(s, str) else ("" if s is None or isinstance(s, (dict, list)) else str(s))      # a scraped name can be a number or an object: never crash on it
    s = "".join(c for c in unicodedata.normalize("NFKD", (s or "").translate(_FOLD)) if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def own_is_home(report: dict) -> bool:
    team, home, away = norm(report.get("team")), norm(_get(report, "match", "home_team")), norm(_get(report, "match", "away_team"))
    if team and team == home:
        return True
    if team and team == away:
        return False
    return bool(team and home and (team in home or home in team))


def _shootout_like(gf: int, ga: int, competition: str | None) -> bool:
    """The scraper adds penalty-shootout goals to the scoreline of a match decided on penalties (England v France showed 6-4 with equal xG; Azerbaijan v Sierra Leone 10-9).
    Both sides on 4+, a margin of at most 2 and 9+ goals in a cup, playoff or series match is read as a drawn match plus a shootout; qualifying-league matches are real scores (Italy 5-4 Israel)."""
    comp = (competition or "").lower()
    league_qual = "qual" in comp and "playoff" not in comp and "play-off" not in comp
    return gf >= 4 and ga >= 4 and gf + ga >= 9 and abs(gf - ga) <= 2 and not league_qual


def _form_rows(form: dict | None) -> list[dict]:
    rows_raw = next((r for r in (_get(form, k) for k in ("last10_overall", "last5_overall", "last20_overall")) if r), [])[:10]
    rows = []
    for r in rows_raw:
        parsed = _parse_score(r)
        if parsed is None:
            continue
        shootout = _shootout_like(parsed[0], parsed[1], r.get("competition"))
        rows.append({"gf": parsed[0], "ga": parsed[1], "xg_for": r.get("xg_for"), "xg_against": r.get("xg_against"),
                     "result": "D" if shootout else (r.get("result") if r.get("result") in ("W", "D", "L") else None), "competition": r.get("competition"), "venue": r.get("venue"),
                     "date": (r.get("date") if isinstance(r.get("date"), str) else "")[:10], "opponent": r.get("opponent") if isinstance(r.get("opponent"), str) else None, "shootout": shootout})
    return rows


def _squad(profile: dict | None) -> list[dict]:
    out = []
    for p in _get(profile, "squad", default=[]) or []:
        if not isinstance(p, dict):
            continue
        use = _dict(p.get("recent_usage")) or {}
        matches = as_number(use.get("matches_in_squad")) or 0
        minutes = as_number(use.get("total_minutes")) or 0
        out.append({
            "name": p.get("name"), "role": p.get("role"), "value": p.get("market_value") or 0, "age": p.get("age"),
            "minutes_share": min(1.0, minutes / (90.0 * matches)) if matches else 0.0,
            "starts": use.get("starts"), "matches": matches,
            "xg90": use.get("xg_per_90"), "goals90": use.get("goals_per_90"), "assists90": use.get("assists_per_90"),
            "rating": use.get("avg_rating"), "injury": p.get("injury"),
        })
    return out


def _dict(x):
    """A scraped section that must be an object; anything else (a number, text, a list) counts as missing."""
    return x if isinstance(x, dict) else None


def as_number(x):
    """A number from a scraped field, or None: text such as '' or 'n/a', booleans and non-finite values are not numbers."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return x if x == x and abs(x) != float("inf") else None
    if isinstance(x, str):
        try:
            v = float(x.strip())
        except ValueError:
            return None
        return v if v == v and abs(v) != float("inf") else None
    return None


def _role_reference() -> dict[str, str]:
    import json
    from pathlib import Path
    try:
        data = json.loads((Path(__file__).parent / "player_roles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {norm(k): v for k, v in (data.get("players") or {}).items() if isinstance(v, str)}


ROLE_REFERENCE = _role_reference()


def _absentees(missing: list[dict], squad: list[dict], injuries: list[dict] | None = None) -> tuple[list[dict], dict[str, float]]:
    total_value = sum(p["value"] for p in squad) or 0.0
    by_name = {norm(p["name"]): p for p in squad}
    inj = {norm(x.get("name")): x for x in (injuries or []) if isinstance(x, dict) and x.get("name")}     # the profile's injury list knows role, age and market value of players the squad list lacks
    items, attack_loss, defence_loss = [], 0.0, 0.0
    for m in missing or []:
        if not isinstance(m, dict) or not isinstance(m.get("name"), str) or not m["name"].strip():
            continue                                        # a missing-player entry without a usable name cannot be described
        p = by_name.get(norm(m.get("name")))
        known = inj.get(norm(m.get("name"))) if p is None else None
        value = p["value"] if p else (known.get("market_value") or 0 if known else 0)
        role = p["role"] if p else (known.get("role") if known else None)
        ref_role = None
        if p is None and not role:
            ref_role = ROLE_REFERENCE.get(norm(m.get("name")))
            role = ref_role
        weight = (value / total_value) * (0.5 + 0.5 * p["minutes_share"]) if (p and total_value) else 0.0
        attack_loss += weight * ATTACK_ROLES.get(role, 0.0)
        defence_loss += weight * DEFENCE_ROLES.get(role, 0.0)
        items.append({"name": m.get("name"), "reason": m.get("description") or m.get("absence_type"), "return": (m.get("expected_return") or "")[:10] or None,
                      "role": role, "value": value, "impact": round(weight, 4), "in_squad_list": p is not None, "from_injury_list": bool(known and (known.get("role") or known.get("market_value"))), "role_reference": bool(ref_role)})
    return items, {"attack_loss": round(attack_loss, 4), "defence_loss": round(defence_loss, 4)}


def home_edge(m: dict) -> tuple[int, str]:
    """(+1 home side has the home edge, -1 the AWAY side has it, 0 nobody) and a short reason. The scraped `neutral` flag is
    usually empty, so the venue's country decides: the home label is trusted only when the venue is in that team's country.
    A match labelled 'home' but played in the away team's country gives the away team the edge; a third country is neutral."""
    if m.get("neutral"):
        return 0, "neutral venue flag set"
    venue, home, away = m.get("venue_country"), m.get("home_team_country"), m.get("away_team_country")
    if not (venue and home and away):
        return 1, "no venue country: home label trusted"
    v, h, a = canonical_name(venue), canonical_name(home), canonical_name(away)
    if v == h:
        return 1, f"venue in {venue} (home side's country)"
    if v == a:
        return -1, f"venue in {venue}, the AWAY side's country: the 'home' label contradicts the venue, so the away side gets the edge"
    return 0, f"venue in {venue}, neither team's country: neutral"


def _xg(est: dict | None) -> dict | None:
    est = _dict(est)
    n, xf, xa = (as_number(est.get(k)) for k in ("sample_size", "xg_for", "xg_against")) if est else (None, None, None)
    if n and xf is not None and xa is not None:
        return {"for_pg": xf / n, "against_pg": xa / n, "n": n}
    return None


def _odds(report: dict) -> dict | None:
    o = _get(report, "match", "betting_odds") or _get(report, "match", "sofascore_betting_odds")
    if not o:
        return None
    fair = [o.get(k) for k in ("home_win_fair_pct", "draw_fair_pct", "away_win_fair_pct")]
    if not all(isinstance(v, (int, float)) for v in fair):
        raw = [o.get(k) for k in ("home_win_odds", "draw_odds", "away_win_odds")]
        if not all(isinstance(v, (int, float)) and v > 1 for v in raw):
            return None
        fair = [100 / v for v in raw]
    t = sum(fair)
    out = {"home": fair[0] / t, "draw": fair[1] / t, "away": fair[2] / t, "over_2_5": None, "overround_pct": o.get("overround_pct")}
    ov, un = o.get("over_2_5_fair_pct"), o.get("under_2_5_fair_pct")
    if isinstance(ov, (int, float)) and isinstance(un, (int, float)) and ov + un > 0:
        out["over_2_5"] = ov / (ov + un)
    return out


def _meetings_seen(m: dict) -> dict | None:
    """Wins by the fixture's home team / draws / wins by the away team among the listed recent meetings (a subset of the summary), or None when none can be read."""
    home, away = norm(m.get("home_team")), norm(m.get("away_team"))
    out = {"home": 0, "draws": 0, "away": 0, "n": 0}
    for r in m.get("recent_meetings") or []:
        if not isinstance(r, dict):
            continue
        try:
            gh, ga = [int(x) for x in str(r.get("scoreline")).split("-")]
        except (TypeError, ValueError):
            continue
        th, ta = norm(r.get("home_team")), norm(r.get("away_team"))
        if {th, ta} != {home, away} or th == ta:
            continue
        out["n"] += 1
        if gh == ga:
            out["draws"] += 1
        else:
            out["home" if (th if gh > ga else ta) == home else "away"] += 1
    return out if out["n"] else None


SECTIONS = ("match", "form", "opponentForm", "teamProfile", "opponentProfile", "insights", "dataCompleteness")
MATCH_SECTIONS = ("betting_odds", "head_to_head_summary", "home_team_standing", "away_team_standing", "home_manager", "away_manager")


def _sanitize(report: dict) -> dict:
    """Sections that must be objects but arrive as text, numbers or lists count as missing, so one bad field cannot crash the analysis."""
    clean = {k: v for k, v in report.items()}
    for k in SECTIONS:
        if k in clean and not isinstance(clean[k], dict):
            clean[k] = {}
    m = dict(clean.get("match") or {})
    for k in MATCH_SECTIONS:
        if k in m and not isinstance(m[k], dict):
            m[k] = {}
    clean["match"] = m
    return clean


def extract_facts(report: dict) -> dict:
    report = _sanitize(report if isinstance(report, dict) else {})
    m = report.get("match") or {}
    ins = report.get("insights") or {}
    own_home = own_is_home(report)
    profiles = {"home": report.get("teamProfile") if own_home else report.get("opponentProfile"),
                "away": report.get("opponentProfile") if own_home else report.get("teamProfile")}
    forms = {"home": report.get("form") if own_home else report.get("opponentForm"),
             "away": report.get("opponentForm") if own_home else report.get("form")}
    sides: dict[str, dict] = {}
    for side in ("home", "away"):
        squad = _squad(profiles[side])
        absent, loss = _absentees(m.get(f"{side}_missing_players") or [], squad, (profiles[side] or {}).get("injuries"))
        elo = ins.get(f"{side}_elo_rating") or {}
        rest = ins.get("rest_comparison") or {}
        own_rest = as_number(rest.get("own_rest_days") if (side == "home") == own_home else rest.get("opponent_rest_days"))
        sides[side] = {
            "name": m.get(f"{side}_team"),
            "form": _form_rows(forms[side]),
            "xg": _xg(ins.get(f"{side}_xg_estimate")),
            "elo": ({"rating": elo["elo"], "national": elo.get("sample_source") == "eloratings.net"} if elo.get("elo") else None),
            "squad": squad, "squad_value": sum(p["value"] for p in squad) or None,
            "absentees": absent, "absence_loss": loss,
            "standing": _dict(m.get(f"{side}_team_standing")), "zone": _dict(ins.get(f"{side}_standings_zone")), "stakes": _dict(ins.get(f"{side}_standings_impact")),
            "rest_days": own_rest, "rotation": _dict(ins.get(f"{side}_rotation")), "fatigue": _dict(ins.get(f"{side}_fatigue_flag")),
            "manager": _get(m, f"{side}_manager", "name"), "formation": m.get(f"{side}_formation"),
            "lineup": [p["name"] for p in (m.get(f"{side}_lineup") or []) if isinstance(p, dict) and isinstance(p.get("name"), str) and not p.get("substitute")],
            "discipline": _dict(ins.get(f"{side}_card_discipline")), "set_pieces": _dict(ins.get(f"{side}_set_piece_threat")),
            "home_advantage": ins.get(f"{side}_advantage"),
        }
    h2h = m.get("head_to_head_summary") or {}
    edge, edge_reason = home_edge(m)
    seen = _meetings_seen(m)
    return {
        "home": m.get("home_team"), "away": m.get("away_team"), "competition": m.get("competition"), "kickoff": m.get("kickoff_utc"),
        "status": m.get("status"), "generated_at": report.get("generatedAt"), "neutral_flag_set": bool(m.get("neutral")), "own_is_home": own_home,
        "neutral": edge == 0, "edge": edge, "edge_reason": edge_reason, "venue": m.get("venue_name"), "venue_country": m.get("venue_country"),
        "weather": m.get("weather"), "referee": m.get("referee"), "referee_stats": m.get("referee_stats"),
        "travel": ins.get("travel_info"), "lineup_confirmed": bool(m.get("lineup_confirmed")),
        "h2h": {"home_wins": h2h.get("home_wins"), "draws": h2h.get("draws"), "away_wins": h2h.get("away_wins"), "n": h2h.get("sample_size")} if h2h else None, "h2h_seen": seen,
        "odds": _odds(report), "sides": sides, "completeness": report.get("dataCompleteness"),
        "pipeline_blend": _get(ins, "prediction", "blended"), "source_conflicts": m.get("source_conflicts") or [],
    }


def _lineup_findings(facts: dict, add) -> None:
    from .lineup import lineup_picture  # local import: lineup imports norm from this module
    pic = lineup_picture(facts)
    if pic["overlap"]:
        add("warn", "xi_overlap", f"the same player is in both XIs ({', '.join(pic['overlap'][:3])}): the lineup data is unreliable", 0.05)
    for side in ("home", "away"):
        p = pic[side]
        if p["missing_in_xi"]:
            add("warn", "missing_in_xi", f"{side} XI contains a player listed as missing ({', '.join(p['missing_in_xi'][:3])}): XI or absence list is wrong", 0.04)
        if p["injured_in_xi"]:
            add("warn", "injured_in_xi", f"{side} XI contains a player marked injured in the squad list ({', '.join(p['injured_in_xi'][:3])}): treat the XI as unverified", 0.03)
        if p["xi_not_in_squad"]:
            add("info", "xi_not_in_squad", f"{side} XI names not found in the squad list: {', '.join(p['xi_not_in_squad'][:3])}")
        if p["empty_absentee_list"]:
            add("info", "empty_absentee_list", f"{side} has injured players in the squad list but no listed absentees: absences may be incomplete (unknown, not zero)")
        if p["heavy_rotation"]:
            add("info", "heavy_rotation", f"{side} changed {facts['sides'][side]['rotation']['changed_players']} starters last match: check stakes before assuming a weak XI")


def audit_facts(facts: dict, now_iso: str | None = None, independent: bool = False, has_trained_model: bool = True) -> dict:
    """Findings + a 0-1 data-quality score. Severity: error (prediction may be invalid), warn, info."""
    findings: list[dict] = []
    penalty = 0.0

    def add(sev: str, code: str, msg: str, cost: float = 0.0):
        nonlocal penalty
        findings.append({"severity": sev, "code": code, "message": msg})
        penalty += cost

    if not (facts["home"] and facts["away"]):
        add("error", "no_fixture", "report has no upcoming fixture", 1.0)
    if facts["status"] not in (None, "notstarted"):
        add("error", "not_pre_match", f"match status is '{facts['status']}': the data may contain the result", 0.5)
    if facts["kickoff"] and facts["generated_at"] and facts["generated_at"] >= facts["kickoff"]:
        add("error", "after_kickoff", "report was generated at/after kickoff", 0.5)
    if independent:
        if not facts["odds"]:
            add("info", "no_odds", "no bookmaker odds: not needed (independent mode), but the odds challenge is not possible")
        if not has_trained_model:
            add("warn", "weak_model", "no trained model for these teams (clubs / unknown national sides): the estimate rests on recent results, xG and ratings from the JSON only, "
                "which scored 0.658 Brier on 36 fixtures against 0.667 for guessing; treat it as weak", 0.25)
    elif not facts["odds"]:
        add("warn", "no_odds", "no bookmaker odds (the strongest single signal)", 0.15)
    for side in ("home", "away"):
        s = facts["sides"][side]
        n = len(s["form"])
        if n == 0:
            add("error", "no_form", f"no recent results for {side}", 0.25)
        elif n < 5:
            add("warn", "short_form", f"only {n} recent results for {side}", 0.06)
        if not s["xg"]:
            add("info", "no_xg", f"no xG sample for {side}", 0.02)
        if not s["squad"]:
            add("info", "no_squad", f"no squad list for {side}: absence impact cannot be computed", 0.03)
        unmatched = [a["name"] for a in s["absentees"] if not a["in_squad_list"]]
        if unmatched:
            add("info", "absentee_not_in_squad", f"{side} absentees not found in the squad list (impact unknown): {', '.join(unmatched[:4])}")
    if facts["edge"] != 1 and not facts["neutral_flag_set"]:
        add("warn", "venue_edge", f"home edge handled from the venue, not the label: {facts['edge_reason']}")
    for side in ("home", "away"):
        s = facts["sides"][side]
        shoot = [r for r in s["form"] if r.get("shootout")]
        if shoot:
            add("info", "shootout_score_ignored", f"{side} form: {shoot[0]['gf']}-{shoot[0]['ga']} vs {shoot[0]['opponent']} looks like a draw plus a penalty shootout: counted as a draw, its goals are ignored")
        odd = [r for r in s["form"] if not r.get("shootout") and (r["gf"] + r["ga"] >= 9 or max(r["gf"], r["ga"]) >= 8)]
        if odd:
            add("warn", "implausible_score", f"{side} form has an implausible score ({odd[0]['gf']}-{odd[0]['ga']} vs {odd[0]['opponent']}): possible shootout or data error; goals are capped at {GOAL_CAP} per match in the goal models")
        rot = s["rotation"] or {}
        if rot.get("starting_xi_size") and rot.get("changed_players") is not None and rot["changed_players"] >= rot["starting_xi_size"]:
            add("info", "rotation_artefact", f"{side} 'changed {rot['changed_players']} of {rot['starting_xi_size']} starters' is probably a data artefact (different competition or squad), not real rotation")
        zero = [p["name"] for p in s["squad"] if not p["value"]]
        if len(zero) >= 5:
            add("info", "zero_value_players", f"{side}: {len(zero)} squad players have no market value, so squad value and absence impact are understated")
    tr = facts.get("travel") or {}
    if tr.get("home_traveling") and facts["edge"] == 1:
        add("info", "travel_contradiction", "home side is marked as travelling although the venue is in its own country")
    comp = (facts.get("competition") or "").lower()
    if any(k in comp for k in ("knockout", "final", "semi", "quarter", "round of", "playoff", "play-off")):
        add("info", "knockout_definition", "knockout match: the model was trained on international results as recorded after extra time (penalty shootouts count as draws), "
            "so its draw probability means 'level after 120 minutes' and cannot give a clean 90-minute result")
    h2h, seen = facts.get("h2h"), facts.get("h2h_seen")
    if h2h and seen and h2h.get("n") is not None and (seen["home"] > (h2h["home_wins"] or 0) or seen["away"] > (h2h["away_wins"] or 0) or seen["draws"] > (h2h["draws"] or 0)):
        add("warn", "h2h_conflict", f"the head-to-head summary (home {h2h['home_wins']}, draws {h2h['draws']}, away {h2h['away_wins']}, n={h2h['n']}) is smaller than the meetings listed in the same report "
            f"(home {seen['home']}, draws {seen['draws']}, away {seen['away']}): the source summary undercounts, so treat the H2H record as unverified", 0.03)
    if not facts["lineup_confirmed"]:
        add("info", "lineup_unconfirmed", "lineups are predicted, not confirmed", 0.04)
    _lineup_findings(facts, add)
    if facts["source_conflicts"]:
        add("info", "source_conflicts", f"{len(facts['source_conflicts'])} field(s) differ between sources")
    comp = facts.get("completeness") or {}
    populated, total = as_number(comp.get("populated")), as_number(comp.get("total"))
    if total and populated is not None and populated / total < 0.7:
        add("warn", "low_completeness", f"only {populated / total:.0%} of expected fields populated", 0.1)
    return {"findings": findings, "quality": round(max(0.0, min(1.0, 1.0 - penalty)), 2)}
