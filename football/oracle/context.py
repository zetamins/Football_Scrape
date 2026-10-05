"""LLM context panel. The quantitative engine already prices form, xG, odds, ratings, squad value and the market value of
absent players. The panel's job is what numbers miss: motivation and stakes, rotation and fatigue, tactical / manager /
matchup context, weather, referee, travel, surprising lineup news. Each model returns BOUNDED adjustments and must cite the
evidence tag of the brief line it relies on; code then validates every claim:

  * numbers are clamped (rates +-12%, draw +-3 points);
  * an adjustment is scaled by the fraction of its factors whose evidence tag really exists in the brief, and is zero if none do;
  * the panel is aggregated by median (3+ models), mean x0.75 (2), or the single opinion x0.5 -- fewer voices, less trust.

Nothing a model says can change a probability directly: it only nudges the expected goals that the exact score distribution then uses.
"""

from __future__ import annotations

import json
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import llm
from .debate import MAX_ABSENTEES
from .lineup import lineup_picture

MAX_RATE_PCT = 12.0
MAX_DRAW_PCT = 3.0
MIN_CONFIDENCE = 0.2
EFFECTS = ("home_rate_pct", "away_rate_pct", "draw_bias_pct")
# Tags that describe what the engine already priced (numbers from the baseline, who has the home edge). Advocates may cite them to explain the odds; an ADJUSTMENT may not rely on them
# (it would count the same evidence twice), so a factor whose evidence is one of these is rejected.
PRICED_TAGS = frozenset({"[BASELINE]", "[FIXTURE]"})

EXAMPLE_OPINION = {
    "home_rate_pct": 0, "away_rate_pct": -3, "draw_bias_pct": 0, "confidence": 0.5,
    "factors": [{"effect": "away_rate_pct", "evidence": "[A.rotation]", "note": "changed 6 of 11 starters in the previous match, a pattern that should carry over"}],
    "data_gaps": ["confirmed lineups"],
}

_PRICED = {
    "independent": (
        "our own trained national-team goals model (opponent-adjusted, fitted on ~17,500 international results), recent xG and results, ratings and squad value, "
        "and who has the home edge (from the venue). Bookmaker odds are NOT an input (they are only a benchmark). Players missing through injury or suspension "
        "are NOT applied by the engine."),
    "market-informed": (
        "bookmaker odds (de-vigged, the largest share), a small share of our trained model, xG, recent results, ratings and squad value, and who has the home edge. "
        "The odds already price injuries and suspensions, so do NOT adjust for absentees."),
}
_ABSENCE_CLAUSE = {
    "independent": (" Key absentees are yours to judge: a starter or key player listed as missing may justify at most +-3 and must cite its [X.absent.<name>] tag. "
                    "The [X.availability] line classifies each absentee from recent minutes; a fringe player or one marked unknown (not in the squad list) is worth 0 and a factor citing them is rejected. "
                    "A missing attacker lowers that side's rate; a missing defender or keeper raises the OPPONENT's rate."),
    "market-informed": "",
}


def system_prompt(mode: str = "independent") -> str:
    """The system prompt for the cloud LLM panel. Mode-aware so that it never claims the engine prices something it does not (it is built from the same bounds
    the validator enforces; tests/test_prompts.py checks they stay in sync)."""
    mode = mode if mode in _PRICED else "independent"
    example = json.dumps(EXAMPLE_OPINION, indent=1)
    return (
        "You review the CONTEXT of one football match for a statistical prediction engine and propose small, evidence-cited adjustments. "
        "Reply with ONE JSON object and nothing else.\n\n"
        f"WHAT THE ENGINE ALREADY DOES (do not re-count it): {_PRICED[mode]}\n"
        "WHAT IT CANNOT SEE (your job): motivation and stakes (table scenarios, qualification, dead rubbers), unusual rotation or fatigue, manager and tactical "
        f"matchup, weather, referee, travel, surprising lineup news.{_ABSENCE_CLAUSE[mode]}\n\n"
        "RULES\n"
        "1. Use ONLY facts in the brief. Never invent players, injuries, results or numbers.\n"
        "2. Every factor cites exactly ONE evidence tag, written exactly as printed in the brief, for example [H.stakes]. A claim without a real tag is discarded.\n"
        f"3. Be conservative. The expected answer is 0 for most matches; a single weak factor stays 0; typical size is 1-3. Hard bounds: home_rate_pct and "
        f"away_rate_pct within +-{MAX_RATE_PCT:g}, draw_bias_pct within +-{MAX_DRAW_PCT:g}.\n"
        "4. Rotation tags describe the PREVIOUS match: use one only if the pattern clearly carries over. [BASELINE] and [FIXTURE] describe what the engine already priced: a factor citing them is rejected.\n"
        "5. draw_bias_pct only for draw-specific context you can cite (a table scenario where a draw suits both sides, a dead rubber, a clearly defensive matchup), "
        "never because a team 'draws a lot'.\n"
        f"6. confidence is 0 to 1; below {MIN_CONFIDENCE:g} every adjustment is ignored.\n"
        "7. A number only counts if a factor with the SAME effect cites a real tag: a value in away_rate_pct needs an away_rate_pct factor.\n"
        "8. If the brief says lineups are not confirmed, the XIs are guesses: do not reason from names in them.\n\n"
        "MEANING: home_rate_pct changes the home side's expected goals (+ = scores more), away_rate_pct the away side's, draw_bias_pct moves probability toward (+) "
        "or away from (-) a draw. Use 0 when the evidence does not justify a change; an empty factors list is a valid answer.\n\n"
        f"FORMAT (example; the tags are illustrative, use the tags of YOUR brief):\n{example}"
    )


SYSTEM = system_prompt("independent")


def build_brief(facts: dict, baseline: dict, mode: str = "independent") -> tuple[str, set[str]]:
    """(brief text, set of evidence tags that appear in it). Every line starts with its [TAG]."""
    lines: list[tuple[str, str]] = []

    def add(tag: str, text: str):
        lines.append((tag, text))

    edge = {1: "home side", -1: "AWAY side", 0: "nobody (neutral)"}[facts["edge"]]
    add("FIXTURE", f"{facts['home']} (home label) vs {facts['away']} (away label), {facts['competition']}, kickoff {facts['kickoff']}; home edge goes to: {edge} ({facts['edge_reason']})")
    if facts["venue"] or facts["weather"]:
        add("VENUE", f"venue {facts['venue']} ({facts['venue_country']}); weather {facts['weather']}")
    rs = facts.get("referee_stats") or {}
    if facts["referee"]:
        add("REFEREE", f"{facts['referee']}: {rs.get('yellow_cards_per_game')} yellows/game, {rs.get('red_cards_per_game')} reds/game over {rs.get('referee_matches')} recent matches")
    tr = facts.get("travel") or {}
    if tr.get("away_traveling") or tr.get("home_traveling"):
        add("TRAVEL", f"home travels {tr.get('home_travel_distance_km')} km; away travels {tr.get('away_travel_distance_km')} km")
    if facts["h2h"]:
        h = facts["h2h"]
        add("H2H", f"head to head: home {h['home_wins']} wins, {h['draws']} draws, away {h['away_wins']} wins (n={h['n']})")
    add("LINEUPS", f"lineups confirmed: {facts['lineup_confirmed']}" + ("" if facts["lineup_confirmed"] else " (the XIs below are guesses: do not reason from names)"))
    pic = lineup_picture(facts)
    for side, tag in (("home", "H"), ("away", "A")):
        s = facts["sides"][side]
        letters = "".join(r["result"] or "?" for r in s["form"][:6]) or "n/a"
        add(f"{tag}.form", f"{s['name']} last results (newest first) {letters}; goals {[(r['gf'], r['ga']) for r in s['form'][:6]]}")
        st = s["standing"] or {}
        if st:
            add(f"{tag}.table", f"{s['name']} position {st.get('position')}/{st.get('total_teams')}, {st.get('points')} pts from {st.get('played')} played, GD {st.get('goal_diff')}")
        if s["stakes"]:
            sc = "; ".join(f"{x['outcome']} -> {x['new_points']} pts, position {x['new_position']}" for x in s["stakes"].get("scenarios", []))
            add(f"{tag}.stakes", f"{s['name']} table scenarios: {sc}; zone {(s['zone'] or {}).get('zone')}")
        if s["rotation"]:
            r = s["rotation"]
            add(f"{tag}.rotation", f"{s['name']} changed {r.get('changed_players')} of {r.get('starting_xi_size')} starters last match; formation changed: {r.get('formation_changed')}")
        if s["fatigue"]:
            add(f"{tag}.fatigue", f"{s['name']} multi-competition: {s['fatigue'].get('multi_competition')}, average gap {s['fatigue'].get('avg_gap_days')} days; rest before this match: {s['rest_days']} days")
        if s["manager"]:
            add(f"{tag}.manager", f"{s['name']} manager {s['manager']}, formation {s['formation']}")
        for a in s["absentees"][:MAX_ABSENTEES]:
            priced = f"value {a['value'] / 1e6:.0f}M, modelled impact {a['impact']:.3f}" if a["in_squad_list"] else ("NOT in the squad list: impact unknown and unmodelled" + (f"; injury list: market value {a['value'] / 1e6:.1f}M" if a.get("from_injury_list") and a["value"] else ""))
            add(f"{tag}.absent.{a['name']}", f"{s['name']} missing {a['name']} ({(a['role'] or 'role unknown') + (' (outside reference)' if a.get('role_reference') else '')}, {priced}): {a['reason']}, back {a['return']}")
        if s["lineup"]:
            add(f"{tag}.lineup", f"{s['name']} {'confirmed' if facts['lineup_confirmed'] else 'predicted'} XI: {', '.join(s['lineup'])}")
        if s["absentees"]:
            kinds = ", ".join(f"{a['name']} = {a['status']}" for a in pic[side]["absentees"][:MAX_ABSENTEES])
            add(f"{tag}.availability", f"{s['name']} missing players by recent playing time (starter >=60% of minutes; unknown = not in squad list, NOT zero impact): {kinds}")
    odds_role = "bookmaker odds (benchmark only, NOT an input to the engine)" if mode == "independent" else "bookmaker odds (an input to the engine)"
    add("BASELINE", f"engine baseline ({'our own model' if mode == 'independent' else 'odds-informed'}): expected goals {baseline['lam_home']:.2f}-{baseline['lam_away']:.2f}; win/draw/loss "
                    f"{baseline['home']:.0%}/{baseline['draw']:.0%}/{baseline['away']:.0%}; {odds_role}: {_odds_text(facts)}")
    text = "\n".join(f"[{tag}] {t}" for tag, t in lines)
    return text, {f"[{tag}]" for tag, _ in lines}


def _odds_text(facts: dict) -> str:
    o = facts["odds"]
    return f"{o['home']:.0%}/{o['draw']:.0%}/{o['away']:.0%}" if o else "none"


def weak_absence_tags(facts: dict) -> set[str]:
    """Absence tags a factor may not cite: players who are fringe or not in the squad list (impact unknown). The skill says they are worth 0."""
    pic = lineup_picture(facts)
    return {f"[{tag}.absent.{a['name']}]" for side, tag in (("home", "H"), ("away", "A")) for a in pic[side]["absentees"] if a["status"] in ("unknown", "fringe")}


def validate_opinion(op: dict, valid_tags: set[str], weak_tags: set[str] | frozenset = frozenset()) -> dict:
    """Clamped adjustments + the factors whose evidence tag really exists. Returns {'adjust', 'factors', 'rejected', 'confidence'}.
    `weak_tags` (see weak_absence_tags) are tags that exist but cannot justify a number."""
    if not isinstance(op, dict):          # a list, string or number in the opinion file is an empty opinion, not a crash
        op = {}
    def num(key: str, bound: float) -> float:
        try:
            return max(-bound, min(bound, float(op.get(key, 0) or 0)))
        except (TypeError, ValueError):
            return 0.0

    adjust = {"home_rate_pct": num("home_rate_pct", MAX_RATE_PCT), "away_rate_pct": num("away_rate_pct", MAX_RATE_PCT), "draw_bias_pct": num("draw_bias_pct", MAX_DRAW_PCT)}
    try:
        confidence = max(0.0, min(1.0, float(op.get("confidence", 0) or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    factors, rejected = [], []
    for f in op.get("factors") or []:
        if not isinstance(f, dict):
            continue
        raw = str(f.get("evidence", "")).strip()
        tags = re.findall(r"\[[^\]]+\]", raw) or [f"[{raw}]"]       # one tag normally; "[A], [B]" is accepted if every tag exists
        ok = all(t in valid_tags and t not in PRICED_TAGS and t not in weak_tags for t in tags) and f.get("effect") in EFFECTS
        (factors if ok else rejected).append({**f, "evidence": ", ".join(tags)})
    for effect in EFFECTS:
        claims = [f for f in factors + rejected if f.get("effect") == effect]
        valid = [f for f in factors if f.get("effect") == effect]
        if adjust[effect] != 0 and (not valid or confidence < MIN_CONFIDENCE):
            adjust[effect] = 0.0                                   # unsupported or low-confidence claim: ignored
        elif claims and adjust[effect] != 0:
            adjust[effect] *= len(valid) / len(claims)            # partly unsupported: scale by the supported share
    return {"adjust": adjust, "factors": factors, "rejected": rejected, "confidence": confidence, "data_gaps": [str(g) for g in (op.get("data_gaps") or [])][:5]}


def aggregate(validated: list[dict], trust_override: float | None = None) -> dict:
    """Panel -> one adjustment. Fewer opinions are trusted less (1 voice x0.5, 2 voices x0.75); trust_override replaces that
    rule, e.g. for a human/agent reviewer who has read the whole report."""
    n = len(validated)
    if n == 0:
        return {"adjust": {e: 0.0 for e in EFFECTS}, "n": 0, "trust": 0.0, "agreement": None}
    trust = trust_override if trust_override is not None else {1: 0.5, 2: 0.75}.get(n, 1.0)
    out = {}
    for e in EFFECTS:
        vals = [v["adjust"][e] for v in validated]
        out[e] = round(trust * (statistics.median(vals) if n >= 3 else statistics.fmean(vals)), 3)
    signs = [1 if v["adjust"]["home_rate_pct"] - v["adjust"]["away_rate_pct"] > 0.5 else (-1 if v["adjust"]["home_rate_pct"] - v["adjust"]["away_rate_pct"] < -0.5 else 0) for v in validated]
    return {"adjust": out, "n": n, "trust": trust, "agreement": round(max(signs.count(1), signs.count(-1), signs.count(0)) / n, 2)}


def run_panel(facts: dict, baseline: dict, panel: list[tuple[str, str]] | None = None, use_cache: bool = True, mode: str = "independent") -> dict:
    """Ask every panel model; returns {'adjust', 'n', 'trust', 'agreement', 'members': [...], 'factors', 'data_gaps', 'brief'}."""
    brief, tags = build_brief(facts, baseline, mode)
    system = system_prompt(mode)
    panel = panel if panel is not None else llm.default_panel()
    members, validated = [], []
    # Panel members are independent: ask them concurrently (latency = the slowest member, not the sum). Per-provider
    # throttling in llm.ask_json keeps each provider under its own rate limit.
    with ThreadPoolExecutor(max_workers=max(1, len(panel))) as pool:
        replies = list(pool.map(lambda pm: llm.ask_json(pm[0], system, brief, model=pm[1], use_cache=use_cache), panel))
    for (provider, model), r in zip(panel, replies):
        if not r["ok"]:
            members.append({"provider": provider, "model": model, "ok": False, "error": r["error"]})
            continue
        v = validate_opinion(r["data"], tags, weak_absence_tags(facts))
        validated.append(v)
        members.append({"provider": provider, "model": r["model"], "ok": True, "cached": r.get("cached", False), **v})
    agg = aggregate(validated)
    seen, factors = set(), []
    for m in members:
        for f in m.get("factors", []):
            key = (f["effect"], f["evidence"])
            if key not in seen:
                seen.add(key)
                factors.append({**f, "by": m["model"]})
    return {**agg, "members": members, "factors": factors, "data_gaps": sorted({g for m in members for g in m.get("data_gaps", [])})[:8], "brief": brief}
