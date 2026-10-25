"""Optional advisory audit by a LOCAL LLM (Ollama, default qwen3:1.7b -- ~1.4 GB, fits a 7.5 GB CPU-only laptop).

The numbers always come from analyze.py. A model this small is not trusted to do arithmetic or to move
probabilities; it reads a condensed brief (audit findings, method table, prediction, plus the human-readable facts
the numbers cannot capture: recent form, absentees, table, H2H, venue) and returns a constrained JSON opinion:
is the prediction consistent with the evidence, what should a human double-check, which context is missing.
Everything it says is labelled advisory and never changes a probability.

Needs a running Ollama (http://127.0.0.1:11434, override with OLLAMA_HOST) with the model pulled.
(Cloud providers live in football/oracle/llm.py.)
Memory-friendly: keep_alive is short so the model unloads soon after the run.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_MODEL = os.environ.get("FOOTBALL_LLM_MODEL", "qwen3:1.7b")
KEEP_ALIVE = "30s"
NUM_CTX = 4096
NUM_PREDICT = 700
# Thinking mode is the default: on the same brief qwen3:1.7b without it invented a concern ("exact venue not specified"
# although the venue was in the brief); with it every concern cited a real item (H2H, absentees, market gap).
# Cost: ~85 s instead of ~28 s on an i7-1255U CPU.
RETRIES = 4            # Ollama can restart or drop the model under memory pressure on a small machine
RETRY_WAIT_S = 15.0
TIMEOUT_S = 900   # time is not a constraint: a CPU run of a 1.7B model takes tens of seconds to minutes

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["consistent", "questionable", "insufficient_data"]},
        "summary": {"type": "string"},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "missing_context": {"type": "array", "items": {"type": "string"}},
        "lean_if_any": {"type": "string", "enum": ["none", "home", "draw", "away"]},
    },
    "required": ["verdict", "summary", "concerns", "missing_context", "lean_if_any"],
}

SYSTEM = (
    "You audit a football match prediction produced by a statistics program. You are given a brief. "
    "Use ONLY facts in the brief; never invent players, injuries, results or numbers. Do not recalculate "
    "probabilities. Decide whether the prediction is consistent with the evidence, list concrete concerns a human "
    "should double-check (cite the specific item from the brief), and list important context that is missing. "
    "lean_if_any is the side the evidence in the brief points to beyond the numbers, or 'none'. "
    "Keep summary under 60 words. Reply with JSON only."
)


def _get(d: Any, *path: str, default=None):
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
    return default if d is None else d


def _form_letters(form: dict | None, n: int = 5) -> str:
    rows = (_get(form, "last5_overall") or _get(form, "last10_overall") or [])[:n]
    return "".join(r.get("result", "?") for r in rows) or "n/a"


def _absentees(match: dict, side: str, limit: int = 6) -> str:
    people = (match.get(f"{side}_missing_players") or [])[:limit]
    if not people:
        return "none reported"
    return "; ".join(f"{p.get('name')} ({p.get('description') or p.get('absence_type') or 'out'})" for p in people)


def build_brief(report: dict, analysis: dict) -> str:
    m = report.get("match") or {}
    pred = analysis.get("prediction") or {}
    aud = analysis.get("audit") or {}
    own_home = analysis.get("own_is_home", True)
    home_form, away_form = (_form_letters(report.get("form")), _form_letters(report.get("opponentForm")))
    if not own_home:
        home_form, away_form = away_form, home_form
    h2h = m.get("head_to_head_summary") or {}
    lines = [
        f"FIXTURE: {analysis.get('home')} (home) vs {analysis.get('away')} (away); {analysis.get('competition') or m.get('competition')}; kickoff {analysis.get('kickoff_utc')}",
        f"VENUE: {m.get('venue_name') or 'n/a'}, {m.get('venue_country') or 'n/a'}; neutral={m.get('neutral')}; weather: {m.get('weather') or 'n/a'}; referee: {m.get('referee') or 'n/a'}",
        f"LINEUPS CONFIRMED: {bool(m.get('lineup_confirmed'))}",
        f"RECENT FORM (newest first): home {home_form}; away {away_form}",
        f"TABLE: home {_get(m, 'home_team_standing', 'position')}/{_get(m, 'home_team_standing', 'total_teams')} ({_get(m, 'home_team_standing', 'points')} pts, {_get(m, 'home_team_standing', 'played')} played); "
        f"away {_get(m, 'away_team_standing', 'position')}/{_get(m, 'away_team_standing', 'total_teams')} ({_get(m, 'away_team_standing', 'points')} pts, {_get(m, 'away_team_standing', 'played')} played)",
        f"HEAD-TO-HEAD: home wins {h2h.get('home_wins')}, draws {h2h.get('draws')}, away wins {h2h.get('away_wins')} (n={h2h.get('sample_size')})",
        f"HOME ABSENT: {_absentees(m, 'home')}",
        f"AWAY ABSENT: {_absentees(m, 'away')}",
        "",
        f"DATA QUALITY: {aud.get('quality')}",
    ]
    lines += [f"- [{f['severity']}] {f['message']}" for f in (aud.get("findings") or [])[:10]]
    lines += ["", "CALCULATIONS (home/draw/away):"]
    for x in analysis.get("methods") or []:
        p = x["probs"]
        lines.append(f"- {x['name']}: {p[0]:.0%}/{p[1]:.0%}/{p[2]:.0%} (weight {x['weight']}) -- {x['why']}")
    if pred:
        lines += [
            "", f"PREDICTION: home {pred['home_win_pct']}% / draw {pred['draw_pct']}% / away {pred['away_win_pct']}%; pick {pred['pick']} "
            f"with calibrated chance {pred['confidence_pct']}%",
            f"RANGE (10-90%): " + ", ".join(f"{k} {lo}-{hi}%" for k, (lo, hi) in pred["uncertainty"]["ranges_pct"].items()),
        ]
        g = pred.get("goals")
        if g:
            lines.append(f"EXPECTED GOALS: {g['expected_goals'][0]}-{g['expected_goals'][1]}; over 2.5 {g['over_2_5_pct']}%")
    return "\n".join(lines)


def _post(path: str, payload: dict) -> dict:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if not host.startswith("http"):
        host = "http://" + host
    req = urllib.request.Request(f"{host}{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 -- local Ollama endpoint
        return json.loads(resp.read().decode())


def audit_with_llm(brief: str, model: str | None = None, think: bool = True) -> dict:
    """{'ok': True, 'model', 'opinion': {...}} or {'ok': False, 'error': ...}. Never raises."""
    model = model or DEFAULT_MODEL
    payload = {
        "model": model, "stream": False, "format": SCHEMA, "think": think, "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT + (2000 if think else 0), "seed": 7},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": brief}],
    }
    data = None
    error = ""
    for attempt in range(RETRIES):
        try:
            data = _post("/api/chat", payload)
            opinion = json.loads(_get(data, "message", "content", default="{}"))
            break
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as e:   # server down / restarting: wait, retry
            error = f"{type(e).__name__}: {e}"
            if attempt < RETRIES - 1:
                time.sleep(RETRY_WAIT_S * (attempt + 1))
        except ValueError as e:                                                                    # model produced invalid JSON: retrying won't fix it
            return {"ok": False, "model": model, "error": f"{type(e).__name__}: {e}"}
    else:
        return {"ok": False, "model": model, "error": f"{error} (after {RETRIES} attempts)"}
    missing = [k for k in SCHEMA["required"] if k not in opinion]
    if missing:
        return {"ok": False, "model": model, "error": f"model reply lacked {missing}", "raw": opinion}
    seconds = (data.get("total_duration") or 0) / 1e9
    return {"ok": True, "model": model, "opinion": opinion, "seconds": round(seconds, 1)}


def format_llm_section(result: dict) -> str:
    if not result.get("ok"):
        return f"## LLM audit (local, advisory)\n- unavailable: {result.get('error')}"
    o = result["opinion"]
    lines = [f"## LLM audit (local {result['model']}, advisory -- never changes the numbers; {result.get('seconds', '?')}s)",
             f"- Verdict: **{o['verdict']}**; leans: {o['lean_if_any']}", f"- {o['summary']}"]
    lines += [f"- Concern: {c}" for c in o["concerns"]]
    lines += [f"- Missing context: {c}" for c in o["missing_context"]]
    return "\n".join(lines)
