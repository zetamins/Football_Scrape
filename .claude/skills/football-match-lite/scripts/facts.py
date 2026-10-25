#!/usr/bin/env python3
"""Reading aid of the football-match-lite skill (Python standard library only): prints the facts of a scraped match-report JSON as a short sheet.

It only READS and re-prints what the report contains (scores turned round so they read "this team - opponent", xG per game, Elo, squad values,
absentees, lineup status, the bookmaker odds as a benchmark). It forecasts nothing: you do the estimating.

    python3 facts.py report.json
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
import re
import sys
import unicodedata


def norm(s) -> str:
    s = s if isinstance(s, str) else ""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def d(x) -> dict:
    return x if isinstance(x, dict) else {}


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def oriented(row: dict) -> tuple[int, int] | None:
    """The row's scoreline is home-away of THAT match; turn it round to this team's goals first. Neutral or unclear venues use the result letter."""
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(row.get("scoreline") or ""))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    venue, res = row.get("venue"), row.get("result")
    if venue == "home":
        return a, b
    if venue == "away":
        return b, a
    if res == "W":
        return (a, b) if a > b else (b, a)
    if res == "L":
        return (a, b) if a < b else (b, a)
    return a, b


def form_lines(rows) -> list[str]:
    out = []
    for r in (rows if isinstance(rows, list) else [])[:10]:
        r = d(r)
        sc = oriented(r)
        flag = ""
        if sc and sc[0] >= 4 and sc[1] >= 4 and sc[0] + sc[1] >= 9 and "qual" not in str(r.get("competition", "")).lower():
            flag = "  <-- looks like penalty-shootout goals added to the score: ignore its goals, count it as a draw"
        elif sc and (sc[0] + sc[1] >= 9 or max(sc) >= 8):
            flag = "  <-- very high score: cap each side at 6 goals when you average"
        xg = f", xG {r.get('xg_for')}-{r.get('xg_against')}" if r.get("xg_for") is not None else ""
        friendly = "  (friendly: weight x0.7)" if "friendl" in str(r.get("competition") or "").lower() else ""
        out.append(f"  {str(r.get('date') or '')[:10]} {r.get('result') or '?'} {sc[0] if sc else '?'}-{sc[1] if sc else '?'} v {r.get('opponent')} ({r.get('venue')}, {str(r.get('competition') or '')[:30]}{xg}){friendly}{flag}")
    return out or ["  (no results in the report)"]


def xg_line(est) -> str:
    est = d(est)
    n, f, a = num(est.get("sample_size")), num(est.get("xg_for")), num(est.get("xg_against"))
    return f"xG per game: for {f / n:.2f}, against {a / n:.2f} over {n:g} games" if n and f is not None and a is not None else "xG per game: not available"


def compact(v, limit: int = 420) -> str:
    t = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return t if len(t) <= limit else t[:limit] + "..."


SKIP_INSIGHTS = ("presence", "prediction", "corners_cross_source_note")
SHARED_INSIGHTS = ("match_type", "rest_comparison", "experience_comparison", "experience_h2h", "travel_info", "referee_card_risk_note")


def deep_section(r: dict, m: dict, ins: dict, home, away, profiles: dict) -> list[str]:
    """Everything else the report knows, printed raw so you can dig: underlying performance (xG against goals, shots, big chances, save rate), style, set pieces,
    results against strong sides, rest and fatigue, discipline, referee, weather, managers, bench, standings, meetings, key players."""
    out = ["", "# DEEP DATA (look here for what the results hide; numbers are the report's own, sample sizes included)"]
    out.append("shared: " + "; ".join(f"{k}={compact(ins.get(k))}" for k in SHARED_INSIGHTS if ins.get(k) is not None))
    for side, name in (("home", home), ("away", away)):
        out.append(f"\n## {name} ({side}) underlying numbers")
        for k, v in ins.items():
            if k.startswith(f"{side}_") and v not in (None, [], {}) and not any(x in k for x in SKIP_INSIGHTS) and k not in (f"{side}_elo_rating", f"{side}_squad_strength"):
                out.append(f"  {k[len(side) + 1:]}: {compact(v)}")
        prof = profiles[side]
        for key in ("recent_form_leaders", "top_scorers", "top_assists", "top_defenders", "key_injuries", "non_injury_absences", "recent_transfers"):
            v = prof.get(key)
            if v:
                out.append(f"  profile.{key}: {compact(v, 380)}")
        out.append(f"  manager: {compact(m.get(f'{side}_manager'), 200)}; formation {m.get(f'{side}_formation')}; manager record v this club: {compact(m.get(side + '_manager_vs_' + ('away' if side == 'home' else 'home') + '_club'), 200)}")
        out.append(f"  season stats: {compact(m.get(f'{side}_team_season_stats'), 380)}")
        out.append(f"  suspended: {compact(m.get(f'{side}_suspended_players'), 200)}; lineup {'confirmed' if m.get('lineup_confirmed') else 'predicted'}: {compact(m.get(f'{side}_lineup'), 300)}")
    out.append("\n## Match context")
    for k in ("venue_name", "venue_city", "referee", "referee_stats", "weather", "weather_detail", "round", "season", "manager_duel", "head_to_head_streaks", "note", "additional_notes"):
        if m.get(k) not in (None, [], {}, ""):
            out.append(f"  {k}: {compact(m.get(k), 360)}")
    meets = [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict)][:6]
    if meets:
        out.append("  recent meetings: " + "; ".join(f"{str(x.get('date'))[:10]} {x.get('home_team')} {x.get('scoreline')} {x.get('away_team')} ({str(x.get('competition') or '')[:22]})" for x in meets))
    table = m.get("standings_table")
    if table:
        out.append(f"  standings table: {compact(table, 700)}")
    if m.get("source_conflicts"):
        out.append(f"  source conflicts (the scrapers disagree): {compact(m.get('source_conflicts'), 400)}")
    out.append("\nOther sections of the JSON you may open: " + ", ".join(k for k in r if k not in ("match", "form", "opponentForm", "insights", "teamProfile", "opponentProfile")) + "; match.* and teamProfile.* hold more (squad with minutes, bench, transfers).")
    return out


def days_between(a, b) -> int | None:
    import datetime
    try:
        return (datetime.date.fromisoformat(str(a)[:10]) - datetime.date.fromisoformat(str(b)[:10])).days
    except ValueError:
        return None


def physiology_section(r: dict, m: dict, ins: dict, home, away, forms: dict, profiles: dict, own_home: bool = True) -> list[str]:
    """What the data says about bodies and schedules: match density, minutes load of the regular players, age profile, injury returns, travel, weather."""
    out = ["", "# PHYSIOLOGY (players and teams: freshness, load, age, returns, travel, conditions)"]
    kick = str(m.get("kickoff_utc") or "")
    tr = d(ins.get("travel_info"))
    w = d(m.get("weather_detail"))
    lon = num(m.get("venue_lon"))
    local = f"{(int(kick[11:13]) + round(lon / 15)) % 24:02d}:00 local (approximate, from the venue's longitude)" if lon is not None and len(kick) >= 13 else "unknown"
    out.append(f"conditions at kickoff: {m.get('weather') or 'unknown'}; temp {w.get('temp_c')} C (feels like {w.get('feels_like_c')}), humidity {w.get('humidity_pct')}%, wind {w.get('wind_speed_kmph')} km/h, rain chance {w.get('chance_of_rain_pct')}%, precipitation {w.get('precip_mm')} mm; "
               f"weather matched to the kickoff hour: {w.get('kickoff_hour_matched')}; kickoff {local}; stadium capacity {m.get('venue_capacity')}")
    out.append(f"travel: home side {tr.get('home_travel_distance_km')} km / {tr.get('home_travel_time_hours')} h, time-zone shift {tr.get('home_timezone_diff_hours')}; away side {tr.get('away_travel_distance_km')} km / {tr.get('away_travel_time_hours')} h, time-zone shift {tr.get('away_timezone_diff_hours')}")
    for side, name in (("home", home), ("away", away)):
        form = d(forms[side])
        rows = next((form[k] for k in ("last10_overall", "last5_overall", "last20_overall") if form.get(k)), [])
        dates = [str(x.get("date"))[:10] for x in rows if isinstance(x, dict) and x.get("date")]
        gaps = [days_between(kick, dates[0])] if dates else []
        last7 = sum(1 for x in dates if (days_between(kick, x) or 99) <= 7)
        last14 = sum(1 for x in dates if (days_between(kick, x) or 99) <= 14)
        prof = profiles[side]
        out.append(f"\n## {name} ({side})")
        out.append(f"  schedule: {gaps[0] if gaps else '?'} days since the last match; {last7} matches in the last 7 days, {last14} in the last 14; rest before this match {d(ins.get('rest_comparison')).get('own_rest_days' if (side == 'home') == own_home else 'opponent_rest_days')} days; fatigue flag {compact(ins.get(f'{side}_fatigue_flag'), 200)}")
        out.append(f"  rest performance (points per game on short and long rest): {compact(ins.get(f'{side}_rest_performance'), 160)}")
        lineup = [p for p in (m.get(f"{side}_lineup") or []) if isinstance(p, dict) and not p.get("substitute") and num(p.get("age")) is not None]
        if lineup:
            ages = sorted(lineup, key=lambda p: p["age"])
            out.append(f"  {'confirmed' if m.get('lineup_confirmed') else 'predicted'} XI ages: mean {sum(p['age'] for p in lineup) / len(lineup):.1f}; oldest {ages[-1].get('name')} {ages[-1]['age']} ({ages[-1].get('position')}), youngest {ages[0].get('name')} {ages[0]['age']}; goalkeeper age {next((p['age'] for p in lineup if p.get('position') == 'G'), '?')}")
        out.append(f"  squad average age {prof.get('average_age')}; experience comparison {compact(ins.get('experience_comparison'), 160)}")
        load = []
        for p in prof.get("squad") or []:
            if isinstance(p, dict) and isinstance(p.get("recent_usage"), dict) and num(p["recent_usage"].get("total_minutes")):
                u = p["recent_usage"]
                load.append((u["total_minutes"], p.get("name"), p.get("role"), p.get("age"), u.get("matches_in_squad"), u.get("starts")))
        load.sort(reverse=True, key=lambda t: t[0])
        out.append("  minutes load of the busiest players (recent window): " + ("; ".join(f"{n} ({role}, age {age}) {mins:g} min in {ms} matches, {st} starts" for mins, n, role, age, ms, st in load[:7]) or "not in the report"))
        back = []
        for x in [x for x in (m.get(f"{side}_missing_players") or []) if isinstance(x, dict)]:
            dd = days_between(x.get("expected_return"), kick) if x.get("expected_return") else None
            if dd is not None:
                back.append(f"{x.get('name')}: {x.get('description') or x.get('absence_type')}, expected back {str(x.get('expected_return'))[:10]} ({'AFTER this match' if dd > 0 else 'back by match day' if dd >= -1 else f'back {-dd} days before the match: match fitness is a question' if dd >= -10 else 'back well before the match'})")
        out.append("  injury and suspension returns: " + ("; ".join(back) if back else "none dated in the report"))
    out.append("\nHow to read it: matches in 7 days and minutes piled on the same players mean fatigue and rotation; a player back only days before the match is unlikely to play 90 minutes; an old spine tires late and a young one is volatile; heat, humidity and long travel across time zones slow the tempo and favour the side with the deeper bench; wind and rain favour direct play and set pieces.")
    return out


def per(x, n):
    return x / n if num(x) is not None and num(n) else None


def fmt(v, nd: int = 2, unit: str = "") -> str:
    return "n/a" if v is None else (f"{v:.{nd}f}{unit}" if isinstance(v, float) else f"{v}{unit}")


def key_metrics(r: dict, m: dict, ins: dict, side: str, forms: dict, profiles: dict) -> dict[str, str]:
    """Per-game and per-team figures worked out from the report's own totals, with their sample sizes, so you can quote them instead of dividing yourself."""
    out: dict[str, str] = {}
    g = lambda key: d(ins.get(f"{side}_{key}"))
    xg, sh, ae, bc, ps, gk, sp, cn, ad, cd, rp, pm = (g(k) for k in ("xg_estimate", "shots_estimate", "aerial_estimate", "big_chances_estimate", "passing_style", "goalkeeping_estimate", "set_piece_threat",
                                                                  "corners_estimate", "advanced_stats", "card_discipline", "rest_performance", "possession_matchup"))
    n = num(xg.get("sample_size"))
    if n:
        out["xG for per game"] = f"{fmt(per(xg.get('xg_for'), n))} ({n:g} games)"
        out["xG against per game"] = f"{fmt(per(xg.get('xg_against'), n))} ({n:g} games)"
        out["goals scored per game (only the games that carry the xG estimate)"] = fmt(per(xg.get("actual_goals_for"), n))
        out["goals conceded per game (only the games that carry the xG estimate)"] = fmt(per(xg.get("actual_goals_against"), n))
        if num(xg.get("actual_goals_for")) is not None and num(xg.get("xg_for")) is not None:
            out["goals minus xG for, per game (finishing luck)"] = fmt(per(xg["actual_goals_for"] - xg["xg_for"], n), 2)
        if num(xg.get("actual_goals_against")) is not None and num(xg.get("xg_against")) is not None:
            out["goals conceded minus xG against, per game (defensive luck: negative = lucky)"] = fmt(per(xg["actual_goals_against"] - xg["xg_against"], n), 2)
    n = num(sh.get("sample_size"))
    if n:
        out["shots for / against per game"] = f"{fmt(per(sh.get('shots_for'), n), 1)} / {fmt(per(sh.get('shots_against'), n), 1)} ({n:g} games)"
        out["shots on target for / against per game"] = f"{fmt(per(sh.get('shots_on_target_for'), n), 1)} / {fmt(per(sh.get('shots_on_target_against'), n), 1)}"
    n = num(bc.get("sample_size"))
    if n:
        out["big chances created / conceded per game"] = f"{fmt(per(bc.get('big_chances_created_for'), n))} / {fmt(per(bc.get('big_chances_created_against'), n))} ({n:g} games)"
        out["big chances missed (own) / missed by opponents per game"] = f"{fmt(per(bc.get('big_chances_missed_for'), n))} / {fmt(per(bc.get('big_chances_missed_against'), n))}"
    n = num(ad.get("sample_size"))
    if n:
        out["touches in the opposition box for / against per game"] = f"{fmt(per(ad.get('touches_in_box_for'), n), 1)} / {fmt(per(ad.get('touches_in_box_against'), n), 1)} ({n:g} games)"
        out["crosses for / against per game"] = f"{fmt(per(ad.get('crosses_for'), n), 1)} / {fmt(per(ad.get('crosses_against'), n), 1)}"
    won, lost = num(ae.get("aerial_duels_won_for")), num(ae.get("aerial_duels_won_against"))
    if won is not None and lost is not None and won + lost:
        out["aerial duels won %"] = f"{100 * won / (won + lost):.0f}% ({won:g} of {won + lost:g})"
    if num(ps.get("pass_accuracy_pct")) is not None:
        out["pass accuracy % / long-ball share %"] = f"{ps.get('pass_accuracy_pct')}% / {ps.get('long_ball_share_pct')}%"
    if num(gk.get("save_pct")) is not None:
        out["goalkeeper save % (a rate far from about 72% rarely lasts)"] = f"{gk.get('save_pct')}% ({gk.get('saves_for')} saves from {gk.get('shots_on_target_faced')} shots on target)"
    n = num(cn.get("sample_size"))
    if n:
        out["corners for / against per game"] = f"{fmt(per(cn.get('corners_for'), n), 1)} / {fmt(per(cn.get('corners_against'), n), 1)} ({n:g} games)"
    if num(cd.get("yellow_per_game")) is not None:
        out["yellow / red cards per game"] = f"{cd.get('yellow_per_game')} / {cd.get('red_per_game')}"
    if num(rp.get("short_rest_ppg")) is not None:
        out["points per game on short rest / long rest"] = f"{rp.get('short_rest_ppg')} ({rp.get('short_rest_sample_size')} games) / {rp.get('long_rest_ppg')} ({rp.get('long_rest_sample_size')} games)"
    if num(pm.get("high_opponent_possession_ppg")) is not None:
        out["points per game v high-possession opponents / others"] = f"{pm.get('high_opponent_possession_ppg')} ({pm.get('high_opponent_possession_sample_size')} games) / {pm.get('other_ppg')} ({pm.get('other_sample_size')} games)"
    ss = d(m.get(f"{side}_team_season_stats"))
    if num(ss.get("clean_sheets_recent_check")) is not None:
        out["clean sheets in the last N matches"] = f"{ss.get('clean_sheets_recent_check')} of {ss.get('clean_sheets_recent_check_sample_size')}"
    bi = g("bench_info")
    if num(bi.get("starting_total_market_value")) and num(bi.get("bench_total_market_value")) is not None:
        out["bench value / starting XI value"] = f"{bi.get('bench_total_market_value')} / {bi.get('starting_total_market_value')} (bench is {100 * bi['bench_total_market_value'] / bi['starting_total_market_value']:.0f}% of the XI)"
    form = d(forms[side])
    rows = next((form[k] for k in ("last10_overall", "last5_overall", "last20_overall") if form.get(k)), [])
    use = [oriented(x) for x in rows[:6] if isinstance(x, dict) and oriented(x) and not (oriented(x)[0] >= 4 and oriented(x)[1] >= 4 and oriented(x)[0] + oriented(x)[1] >= 9 and "qual" not in str(x.get("competition", "")).lower())]
    res = [x.get("result") for x in rows[:6] if isinstance(x, dict) and x.get("result") in ("W", "D", "L")]
    if use:
        out["last results: goals for / against per game (up to 6, shootout rows skipped)"] = f"{sum(a for a, _ in use) / len(use):.2f} / {sum(b for _, b in use) / len(use):.2f} ({len(use)} games)"
    if res:
        out["last results: points per game (up to 6)"] = f"{sum({'W': 3, 'D': 1, 'L': 0}[x] for x in res) / len(res):.2f} ({len(res)} games; newest first {''.join(res)})"
    return out


UEFA_WORDS = ("uefa", "champions league", "europa", "conference", "cup", "pokal", "copa", "coupe", "coppa", "beker", "friendly", "qualif", "super", "shield", "trophy")


def domestic_league(form) -> str | None:
    """The side's own league: the most common competition in its form rows that is not a European, cup or friendly match."""
    rows = [x for x in (d(form).get("last20_overall") or d(form).get("last10_overall") or []) if isinstance(x, dict)]
    comps = [str(x.get("competition") or "") for x in rows if x.get("competition") and not any(w in str(x.get("competition")).lower() for w in UEFA_WORDS)]
    return max(set(comps), key=comps.count) if comps else None


def unformed_table(ins: dict) -> bool:
    """True when both sides' standings exist and both have 0 points: a table before matchday 1 (or a new phase) ranks nothing."""
    pts = [d(ins.get(f"{s_}_standings_impact")).get("current_points") for s_ in ("home", "away")]
    return all(p is not None and num(p) == 0 for p in pts)


def club_elo_after_kickoff(ins: dict, kickoff) -> str:
    """A ClubElo rating dated after kickoff already counts this match's result (clubelo.com serves today's ratings only): the sheet
    says so, so a past match re-run with fresh ratings is not taken as a clean test. '' when every rating predates kickoff."""
    k = str(kickoff or "")[:10]
    late = [f"{s_} {d(ins.get(f'{s_}_club_elo')).get('as_of')}" for s_ in ("home", "away") if k and str(d(ins.get(f"{s_}_club_elo")).get("as_of") or "")[:10] > k]
    return (f"CLUBELO AFTER KICKOFF: rating dated {', '.join(late)} for a {k} kickoff already includes this result (and the opponents' ratings"
            " in the form rows are as fresh): the rating anchor leaks, so score this run as NOT a clean test.") if late else ""


def prefer_larger_xg_sample(ins: dict, forms: dict, names: dict) -> list[str]:
    """The xG estimate (Fotmob's match stats) and the result rows (Sofascore's match details) cover different games. When the
    last-10 rows carry xG for MORE games than the estimate, the anchors use the rows instead (the larger sample is the less noisy one);
    returns the notes to print."""
    notes = []
    for side in ("home", "away"):
        est = d(ins.get(f"{side}_xg_estimate"))
        rows = [x for x in (d(forms.get(side)).get("last10_overall") or []) if isinstance(x, dict) and num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
        n_est = num(est.get("sample_size")) or 0
        if len(rows) > n_est:
            gf = sum(int(str(x.get("scoreline", "0-0")).split("-")[0 if x.get("venue") != "away" else 1]) for x in rows if re.fullmatch(r"\d+-\d+", str(x.get("scoreline") or "")))
            ga = sum(int(str(x.get("scoreline", "0-0")).split("-")[1 if x.get("venue") != "away" else 0]) for x in rows if re.fullmatch(r"\d+-\d+", str(x.get("scoreline") or "")))
            ins[f"{side}_xg_estimate"] = {"sample_size": len(rows), "xg_for": round(sum(num(x["xg_for"]) for x in rows), 2), "xg_against": round(sum(num(x["xg_against"]) for x in rows), 2),
                                          "actual_goals_for": gf, "actual_goals_against": ga, "source": "result rows"}
            notes.append(f"XG SOURCE: {names[side]}'s anchors use the result rows' xG ({len(rows)} games) instead of the xG estimate ({n_est:g} games): the larger sample; the two sources cover different games.")
    return notes


def drop_unformed_table(ins: dict) -> str:
    """Remove a 0-point table from the insights so no section quotes its positions; returns the note to print (empty when the table is real)."""
    if not unformed_table(ins):
        return ""
    pos = [d(ins.get(f"{s_}_standings_zone")).get("position") for s_ in ("home", "away")]
    for s_ in ("home", "away"):
        for k in ("standings_zone", "standings_impact"):
            ins.pop(f"{s_}_{k}", None)
    return (f"TABLE NOT FORMED: both sides have 0 points in this competition (positions {pos[0]} and {pos[1]} are a listing order, not a ranking), "
            "so the table says nothing about class or motivation; do not cite a position, a 'top of the table' or a 'chase' from it.")


def opposition_summary(form, ins: dict, side: str) -> str:
    """One cell for the key metrics: the average ClubElo of the last 10 opponents against the side's own, and points against stronger sides."""
    rows = [x for x in (d(form).get("last10_overall") or []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L")]
    me = num(d(ins.get(f"{side}_club_elo")).get("elo"))
    rated = [(num(x.get("opponent_club_elo")), x["result"]) for x in rows if num(x.get("opponent_club_elo")) is not None]
    if me is None or not rated:
        return "n/a (opponents not rated)"
    avg = sum(e for e, _ in rated) / len(rated)
    up = [r for e, r in rated if e > me]
    pts = lambda rs: sum({"W": 3, "D": 1, "L": 0}[r] for r in rs) / len(rs)
    return (f"avg ClubElo {avg:.0f} v own {me:.0f} ({len(rated)} of {len(rows)} rated); v stronger sides "
            + (f"{pts(up):.2f} pts a game in {len(up)}" if up else "no games") + ("; form built against WEAKER opposition" if avg < me - 80 else ""))


def cross_league_line(r: dict, m: dict, ins: dict, home, away, forms: dict) -> str:
    """For a tie between clubs from different leagues: ClubElo's own expectancy (results, comparable across leagues) beside the squad-value ratio, and whether the two class measures agree."""
    lh, la = domestic_league(forms.get("home")), domestic_league(forms.get("away"))
    eh, ea = num(d(ins.get("home_club_elo")).get("elo")), num(d(ins.get("away_club_elo")).get("elo"))
    vh, va = num(d(ins.get("home_squad_strength")).get("total_value")), num(d(ins.get("away_squad_strength")).get("total_value"))
    if not (lh and la and lh != la and eh is not None and ea is not None):
        return ""
    edge = 0.0 if _NEUTRAL else 100 * ELO_EDGE / (2 * ELO_SLOPE)      # the rating anchor's own home edge in Elo points (50), so the two lines agree
    we = 1 / (1 + 10 ** (-(eh - ea + edge) / 400))
    text = (f"CROSS-LEAGUE TIE ({lh} v {la}): ClubElo, a results rating built to compare clubs across leagues, gives {home} an expected share of {100 * we:.0f}% "
            f"(Elo {eh:.0f} v {ea:.0f}" + (f", plus the rating anchor's home edge of {edge:.0f} points" if edge else ", neutral ground") + "; 50% is level)")
    if vh and va:
        ratio = max(vh, va) / min(vh, va)
        rich = home if vh > va else away
        elo_fav = home if we > 0.55 else away if we < 0.45 else None
        close = 0.40 <= we <= 0.60                                   # ClubElo calls it a close match
        size = ratio >= 3.0 and close                                # value sees a big gap where ClubElo sees a close one
        direction = ratio >= 2.0 and elo_fav is not None and elo_fav != rich
        agree = not (size or direction)
        seen = "a close match" if close else f"{elo_fav} as clearly the stronger side"
        text += (f"; squad market value {vh / 1e6:.1f}m v {va / 1e6:.1f}m ({ratio:.1f}x for {rich}). "
                 + ("The two class measures AGREE." if agree else
                    f"The two class measures DISAGREE{' on the size of the gap' if size and not direction else ''}: ClubElo sees {seen}, squad value sees {rich} as much the stronger. "
                    "Prices in cross-league ties tend to follow squad value and ClubElo follows results; neither has been tested here on European ties, "
                    "so state both, say which you lean on and why, and do not call the gap settled."))
    return text


def key_metrics_table(r: dict, m: dict, ins: dict, home, away, forms: dict, profiles: dict) -> list[str]:
    a, b = key_metrics(r, m, ins, "home", forms, profiles), key_metrics(r, m, ins, "away", forms, profiles)
    labels = list(dict.fromkeys(list(a) + list(b)))
    out = ["", "# KEY METRICS (quote these: worked out from the report's own totals, with sample sizes; both sides side by side)", f"| metric | {home} (home) | {away} (away) |", "|---|---|---|"]
    out += [f"| {k} | {a.get(k, 'n/a')} | {b.get(k, 'n/a')} |" for k in labels]
    if any(num(x.get("opponent_club_elo")) is not None for f in forms.values() for x in (d(f).get("last10_overall") or []) if isinstance(x, dict)):
        out.append(f"| opposition faced, last 10 | {opposition_summary(forms.get('home'), ins, 'home')} | {opposition_summary(forms.get('away'), ins, 'away')} |")
    out.append("Compare per-game figures, not totals, when the sample sizes differ; keep the two teams' numbers on their own side.")
    return out


def p90(total, minutes):
    return None if num(total) is None or not num(minutes) else 90.0 * total / minutes


def team_identity(r: dict, m: dict, ins: dict, side: str) -> dict:
    """Per-game team indicators for attack, defence, midfield and goalkeeper, plus the plain labels the rules below give them."""
    g = lambda key: d(ins.get(f"{side}_{key}"))
    ad, xg, gk, ps, sh = g("advanced_stats"), g("xg_estimate"), g("goalkeeping_estimate"), g("passing_style"), g("shots_estimate")
    n = num(ad.get("sample_size")) or num(xg.get("sample_size")) or num(sh.get("sample_size"))
    ss = d(m.get(f"{side}_team_season_stats"))
    out: dict = {"n": n}
    xn = num(xg.get("sample_size"))
    out["xg_for"], out["xg_against"] = per(xg.get("xg_for"), xn), per(xg.get("xg_against"), xn)
    out["np_xg_for"], out["np_xg_against"] = per(ad.get("non_penalty_xg_for"), n), per(ad.get("non_penalty_xg_against"), n)
    out["shots_in_box_for"], out["shots_in_box_against"] = per(ad.get("shots_inside_box_for"), n), per(ad.get("shots_inside_box_against"), n)
    out["big_chances_for"] = per(d(ins.get(f"{side}_big_chances_estimate")).get("big_chances_created_for"), num(d(ins.get(f"{side}_big_chances_estimate")).get("sample_size")))
    out["box_touches_for"], out["box_touches_against"] = per(ad.get("touches_in_box_for"), n), per(ad.get("touches_in_box_against"), n)
    out["xa_for"] = per(ad.get("xa_for"), n)
    out["tackles"], out["interceptions"], out["clearances"], out["recoveries"] = (per(ad.get(k), n) for k in ("team_tackles_for", "team_interceptions_for", "team_clearances_for", "recoveries_for"))
    out["blocks"] = per(ad.get("blocked_shots_for"), n)
    out["shots_against"] = per(sh.get("shots_against"), num(sh.get("sample_size")))
    out["shots_for"] = per(sh.get("shots_for"), num(sh.get("sample_size")))
    out["xg_per_shot"] = (out["xg_for"] / out["shots_for"]) if out.get("xg_for") is not None and out.get("shots_for") else None            # shot quality created
    out["xg_per_shot_ag"] = (out["xg_against"] / out["shots_against"]) if out.get("xg_against") is not None and out.get("shots_against") else None   # shot quality conceded
    out["sot_faced"] = per(gk.get("shots_on_target_faced"), num(gk.get("sample_size")))
    out["saves"] = per(gk.get("saves_for"), num(gk.get("sample_size")))
    out["save_pct"] = num(gk.get("save_pct"))
    out["possession"] = num(ad.get("possession_pct_avg")) or num(ss.get("average_ball_possession"))
    out["passes"] = per(ps.get("total_passes_for"), num(ps.get("sample_size")))
    out["pass_acc"], out["long_ball"] = num(ps.get("pass_accuracy_pct")), num(ps.get("long_ball_share_pct"))
    out["f3_for"], out["f3_against"] = per(ad.get("final_third_entries_for"), n), per(ad.get("final_third_entries_against"), n)
    out["tilt"] = num(ad.get("field_tilt_pct"))
    # labels (rules written down so they can be argued with)
    xf, xa = out["xg_for"], out["xg_against"]
    if xf is not None and xa is not None:
        out["attack_label"] = ("attacking (creates 1.4+ xG a game)" if xf >= 1.4 else "low-creating (under 1.1 xG a game)" if xf < 1.1 else "moderate attack")
        out["defence_label"] = ("solid (concedes under 1.2 xG a game)" if xa < 1.2 else "leaky (concedes 1.5+ xG a game)" if xa >= 1.5 else "average defence")
        out["identity"] = ("defence-first" if xf < 1.1 and xa < 1.2 else "attack-led" if xf >= 1.4 and xa < 1.5 else "open and loose" if xf >= 1.3 and xa >= 1.5 else "struggling at both ends" if xf < 1.1 and xa >= 1.5 else "balanced")
    poss, lb = out["possession"], out["long_ball"]
    out["passing_label"] = ("possession-based short passing" if (poss is not None and poss >= 52 and (lb is None or lb <= 9)) else "direct / counter" if ((poss is not None and poss <= 46) or (lb is not None and lb >= 14)) else "balanced passing")
    if out["f3_for"] and out["f3_against"]:
        ratio = out["f3_for"] / out["f3_against"]
        out["midfield_label"] = "dominates the middle (final-third entries x%.2f of the opponents')" % ratio if ratio >= 1.1 and (poss is None or poss >= 48) else "loses the middle (final-third entries x%.2f)" % ratio if ratio <= 0.9 else "contested middle (entries x%.2f)" % ratio
    sf, sot = out["shots_against"], out["sot_faced"]
    if sot is not None or sf is not None:
        out["keeper_label"] = ("goalkeeper busy because the defence leaks: %.1f shots on target faced a game (many saves = a weak defence in front of him, not a great keeper)" % sot if (sot is not None and sot >= 4.5) or (sf is not None and sf >= 14.5)
                               else "quiet goalkeeper: the defence protects him (%.1f shots on target faced a game)" % sot if sot is not None and sot <= 3.0 else "average goalkeeper workload")
    return out


def rate_tag(u: dict) -> str:
    """Average match rating over the recent window, tagged weak (under 6.6) or strong (7.2+) when there are enough minutes."""
    rt = num(u.get("avg_rating"))
    if rt is None:
        return ""
    tag = " WEAK form: likely to underperform" if rt < 6.6 and (num(u.get("total_minutes")) or 0) >= 180 else " strong form" if rt >= 7.2 else ""
    return f", rating {rt:.2f}{tag}"


def player_roles(prof: dict, role: str, minutes_min: float = 90):
    rows = []
    for p in prof.get("squad") or []:
        u = d(p.get("recent_usage")) if isinstance(p, dict) else {}
        mins = num(u.get("total_minutes"))
        if isinstance(p, dict) and p.get("role") == role and mins and mins >= minutes_min:
            rows.append((mins, p, u))
    rows.sort(key=lambda t: -t[0])
    return rows


def role_section(r: dict, m: dict, ins: dict, home, away, profiles: dict) -> list[str]:
    out = ["", "# ROLE-BY-ROLE PROFILE (read each side's identity from its statistics, then player by player)"]
    ids = {s: team_identity(r, m, ins, s) for s in ("home", "away")}
    f = lambda v, nd=2: "n/a" if num(v) is None else f"{num(v):.{nd}f}"
    out += [f"| indicator | {home} (home) | {away} (away) |", "|---|---|---|"]
    rows = (("identity (rule: defence-first / attack-led / open / struggling / balanced)", "identity"), ("attack", "attack_label"), ("defence", "defence_label"), ("passing style", "passing_label"), ("midfield", "midfield_label"), ("goalkeeper", "keeper_label"))
    out += [f"| {lab} | {ids['home'].get(k, 'n/a')} | {ids['away'].get(k, 'n/a')} |" for lab, k in rows]
    nums = (("ATTACK xG for / non-penalty xG / shots in the box / big chances / box touches / xA, per game", ("xg_for", "np_xg_for", "shots_in_box_for", "big_chances_for", "box_touches_for", "xa_for"), 2),
            ("DEFENCE xG against / shots against / tackles / interceptions / clearances / blocks / recoveries, per game", ("xg_against", "shots_against", "tackles", "interceptions", "clearances", "blocks", "recoveries"), 1),
            ("MIDFIELD possession % / passes / pass accuracy % / long-ball % / final-third entries for-against / field tilt %", ("possession", "passes", "pass_acc", "long_ball", "f3_for", "f3_against", "tilt"), 1),
            ("GOALKEEPER saves / shots on target faced per game, save %", ("saves", "sot_faced", "save_pct"), 1))
    for lab, keys, nd in nums:
        out.append(f"{lab}:")
        for side, name in (("home", home), ("away", away)):
            out.append(f"  {name}: " + " / ".join(f(ids[side].get(k), nd) for k in keys))
    for side, name in (("home", home), ("away", away)):
        prof = profiles[side]
        out.append(f"\n## {name}: the players by role (recent window; per 90 minutes; minimum 90 minutes)")
        fw = [f"{p.get('name')} (age {p.get('age')}) {mins:g} min: xG {f(p90(u.get('total_xg'), mins))}/90, goals {u.get('total_goals')} vs xG {f(u.get('total_xg'))}, shots {f(p90(u.get('total_shots'), mins), 1)}/90{rate_tag(u)}" for mins, p, u in player_roles(prof, "F")[:4]]
        mf = [f"{p.get('name')} (age {p.get('age')}) {mins:g} min: key passes {f(p90(u.get('total_key_passes'), mins), 1)}/90, xA {f(p90(u.get('total_xa'), mins))}/90, tackles {f(p90(u.get('total_tackles'), mins), 1)}/90{rate_tag(u)}" for mins, p, u in player_roles(prof, "M")[:5]]
        df = [f"{p.get('name')} (age {p.get('age')}) {mins:g} min: tackles+interceptions {f(p90((num(u.get('total_tackles')) or 0) + (num(u.get('total_interceptions')) or 0), mins), 1)}/90{rate_tag(u)}" for mins, p, u in player_roles(prof, "D")[:5]]
        gks = [f"{p.get('name')} (age {p.get('age')}) {mins:g} min{rate_tag(u)}" for mins, p, u in player_roles(prof, "G", 1)[:1]]
        out += ["  attackers: " + ("; ".join(fw) or "not in the report"), "  midfielders: " + ("; ".join(mf) or "not in the report"), "  defenders: " + ("; ".join(df) or "not in the report"), "  goalkeeper: " + ("; ".join(gks) or "not in the report")]
    out.append("\nHow to read it: attackers are judged on xG per 90 and shots (goals far above xG are finishing luck); defenders on tackles, interceptions, clearances and the shots and xG their team concedes; the midfield must dominate the passing and the final-third entries to control a match; "
               "a player whose recent match ratings are weak (under 6.6 over 180+ minutes) will most likely underperform again, so discount him and the part of the team he carries; strong ratings (7.2+) are a real edge unless the minutes are few; a goalkeeper who faces many shots on target is protecting a weak defence (many saves are a symptom of the defence, not proof of a great keeper); a team that creates easily shows high shots in the box, box touches and big chances.")
    return out


def meeting_possession(x: dict):
    for st in x.get("match_stats") or []:
        if isinstance(st, dict) and str(st.get("name", "")).lower() == "ball possession":
            return st.get("home"), st.get("away")
    return None, None


def parse_shape(f):
    """'4-2-3-1' -> (defenders, midfield players, forwards, line count); None when it is not a formation."""
    try:
        n = [int(x) for x in str(f).strip().split("-")]
    except ValueError:
        return None
    return (n[0], sum(n[1:-1]), n[-1], len(n)) if len(n) >= 3 and sum(n) in (9, 10, 11) and min(n) > 0 else None


def shape_matchup(fh, fa, home, away) -> list[str]:
    """Plain numbers-in-each-zone comparison of the two shapes (analyst judgement starts here; shapes shift in play)."""
    a, b = parse_shape(fh), parse_shape(fa)
    if not (a and b):
        return []
    out = [f"Shape v shape: {home} {fh} against {away} {fa}"]
    mid = a[1] - b[1]
    out.append(f"  Midfield bodies (wide midfielders and wing-backs in the midfield line included; the zones below split them): {a[1]} v {b[1]} -> " + (f"{home} outnumber them by {mid} in the middle" if mid > 0 else f"{away} outnumber them by {-mid} in the middle" if mid < 0 else "level in the middle (the duels decide it)"))
    for x, y, nx, ny, fx, fy in ((a, b, home, away, fh, fa), (b, a, away, home, fa, fh)):
        spare = x[0] - y[2]
        out.append(f"  {nx}'s back line ({x[0]}) v {ny}'s front line ({y[2]}): " + (f"{spare} spare defender(s), the front line has little room to run at" if spare >= 3 else f"{spare} spare defender(s), a comfortable cover" if spare >= 2 else "no spare man: one slip is a clear chance" if spare <= 0 else "one spare man, normal cover"))
    out.append(f"  Back-five or wing-back shape: {home} {'yes' if a[0] >= 5 else 'no'}, {away} {'yes' if b[0] >= 5 else 'no'} (a back five usually gives up the ball, concedes width high up the pitch and counters; a back four with two holders keeps more of the ball)")
    out.append("  Which shape is more dominant: " + (f"{home} (more bodies in midfield and no fewer in attack)" if mid > 0 and a[2] >= b[2] else f"{away} (more bodies in midfield and no fewer in attack)" if mid < 0 and b[2] >= a[2] else "neither on paper: the evidence from past meetings and the personnel decides"))
    za, zb = shape_zones(fh), shape_zones(fa)
    if za and zb:
        for x, y, nx, ny in ((za, zb, home, away), (zb, za, away, home)):
            out.append(f"  {nx} by zone: {x['flank']:g} a flank ({x['flank_how']}), {x['centre']:g} central midfielders"
                       + (f" with {x['pivot']:g} holding" if x["pivot"] else "") + (f", {x['tens']:g} between the lines" if x["tens"] else "") + f", {x['strikers']:g} up front")
        weak = {home: [], away: []}
        for x, y, nx, ny in ((za, zb, home, away), (zb, za, away, home)):
            if y["flank"] > x["flank"]:
                weak[nx].append(f"the flanks: {ny} has {y['flank']:g} a side against its {x['flank']:g}, so {ny} can go 2 v 1 out wide" + (" and get in behind its wing-backs" if x["flank_how"] == "a wing-back" else ""))
            if y["centre"] + y["tens"] > x["centre"] + x["tens"] and y["centre"] + y["tens"] - (x["centre"] + x["tens"]) >= 1:
                weak[nx].append(f"the centre of midfield ({y['centre'] + y['tens']:g} v {x['centre'] + x['tens']:g})")
            if y["tens"] and x["pivot"] <= 1:
                weak[nx].append(f"the space in front of its back line: {ny}'s {y['tens']:g} player(s) between the lines face {'a single holder' if x['pivot'] == 1 else 'no set holder'}")
            if y["strikers"] >= 2 and x["back"] == 4 and x["pivot"] <= 1:
                weak[nx].append(f"its two centre-backs against {ny}'s {y['strikers']:g} strikers with little cover in front")
        for nx in (home, away):
            out.append(f"  Where {nx} is weak on paper: " + ("; ".join(weak[nx]) if weak[nx] else "no zone where it is outnumbered"))
        out.append("  Shapes shift in play (a back five becomes a back three with the ball, a 4-3-3 defends as 4-5-1): treat the zones as the starting map; the tactical note and the evidence decide")
    return out


def shape_zones(f) -> dict | None:
    """Rough zone counts from a formation string: players a flank (full-back or wing-back plus winger or wide midfielder), central midfielders,
    holders, players between the lines and strikers. A paper reading only: '4-3-3' cannot say whether the midfield has one holder or two."""
    try:
        n = [int(x) for x in str(f).strip().split("-")]
    except ValueError:
        return None
    if len(n) < 3 or sum(n) not in (10, 11) or min(n) <= 0:
        return None
    back, mids, strikers = n[0], n[1:-1], n[-1]
    wide_back = 2 if back in (4, 5) else 0                        # full-backs in a back four, wing-backs in a back five
    wingbacks_in_mid = 2 if back == 3 and mids[0] >= 4 else 0      # a back three's wing-backs sit at the ends of the first midfield line
    wingers = 0
    tens = 0
    if len(mids) >= 2:
        last = mids[-1]
        if last == 3:
            wingers, tens = 2, 1                                   # 4-2-3-1: two wide, one No. 10
        elif last in (1, 2):
            tens = last                                            # 4-4-1-1, 3-4-2-1, 4-3-1-2
    if strikers == 3:
        wingers, strikers = wingers + 2, 1                         # 4-3-3, 3-4-3: two wide forwards and a centre-forward
    flat_wide = 2 if back == 4 and not wingers and 4 in mids else 0   # a line of four in midfield (4-4-2, 4-1-4-1, 4-4-1-1) has two wide players
    wide = wide_back + wingbacks_in_mid + wingers + flat_wide
    centre = sum(mids) - wingbacks_in_mid - flat_wide - tens - (2 if len(mids) >= 2 and mids[-1] == 3 else 0)
    first = mids[0] if len(mids) >= 2 else max(centre, 0)          # the deepest midfield line's central players
    pivot = first if first <= 2 else 2 if first == 4 else 1        # a line of three usually has one holder (a 4-3-3's No. 6), a flat four two
    how = "full-back and winger" if wide_back == 2 and (wingers or flat_wide) else "a wing-back" if (back == 5 or wingbacks_in_mid) and not wingers else "wing-back and wide forward" if wingers else "full-back only"
    return {"back": back, "flank": wide / 2, "flank_how": how, "centre": max(centre, 0), "pivot": pivot, "tens": tens, "strikers": strikers}


def h2h_relevance(m: dict, home, away) -> list[str]:
    """Is the head to head still useful? Only if the tactical setup is similar and the squads are comparable: same formations, same manager, most of the same XI."""
    out = []
    ko = parse_day(m.get("kickoff_utc"))
    for x in [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict)][:3]:
        day = parse_day(x.get("date"))
        parts = []
        score = 0
        for side, team in (("home", home), ("away", away)):
            was_home = norm_name(x.get("home_team")) == norm_name(team)
            then_shape = x.get("home_formation" if was_home else "away_formation")
            now_shape = m.get(f"{side}_formation")
            same_shape = bool(then_shape and now_shape and str(then_shape) == str(now_shape))
            then_xi = {norm_name(p.get("name")) for p in (x.get("home_lineup" if was_home else "away_lineup") or []) if isinstance(p, dict) and not p.get("substitute")}
            now_xi = {norm_name(p.get("name")) for p in (m.get(f"{side}_lineup") or []) if isinstance(p, dict) and not p.get("substitute")}
            overlap = len(then_xi & now_xi) if then_xi and now_xi else None
            mg = d(m.get(f"{side}_manager"))
            appointed = parse_day(mg.get("appointed_date"))
            same_mgr = None if appointed is None or day is None else appointed <= day
            ok = same_shape and (overlap is None or overlap >= 6) and same_mgr is not False
            score += int(ok)
            parts.append(f"{team}: shape {then_shape or '?'} then v {now_shape or '?'} now ({'same' if same_shape else 'different'}); {overlap if overlap is not None else '?'} of the same XI; manager {'already in charge' if same_mgr else 'NOT in charge then' if same_mgr is False else 'unknown'}")
        comp_then, comp_now = str(x.get("competition") or ""), str(m.get("competition") or "")
        kind = lambda c: "friendly" if "friendl" in c.lower() else "qualifier" if "qual" in c.lower() else "cup or knockout" if re.search(r"cup|knockout|playoff|final|round of", c, re.I) else "league or group" if c else "unknown"
        parts.append(f"context then {kind(comp_then)} ({comp_then[:28] or 'n/a'}) v now {kind(comp_now)}" + ("" if kind(comp_then) == kind(comp_now) or "unknown" in (kind(comp_then), kind(comp_now)) else " (a different kind of match: counts for less)"))
        if kind(comp_then) == "friendly" and kind(comp_now) != "friendly":
            score = min(score, 1)
        years = round((ko - day).days / 365.25, 1) if ko and day else None
        verdict = "RELEVANT (similar setup and squad)" if score == 2 and (years is None or years <= 3) else "WEAK (setup or squad changed)" if score else "NOT RELEVANT (different setup and squad)"
        out.append(f"  {str(x.get('date'))[:10]} {x.get('home_team')} {x.get('scoreline')} {x.get('away_team')} ({years if years is not None else '?'} years ago): {'; '.join(parts)} -> {verdict}")
    return out or ["  no meeting with details to judge relevance"]


def h2h_section(m: dict, home, away) -> list[str]:
    """Head to head on three levels: the clubs/nations across history, the two managers, and the tactics (formations and how past meetings were played)."""
    out = ["", "# HEAD TO HEAD: HISTORY, MANAGERS, TACTICS (weak evidence alone; use it to explain, not to override, the numbers)"]
    h = d(m.get("head_to_head_summary"))
    out.append(f"History (all meetings the source records): {home} wins {h.get('home_wins', '?')}, draws {h.get('draws', '?')}, {away} wins {h.get('away_wins', '?')} from {h.get('sample_size', '?')} meetings" + (" (very small sample)" if (num(h.get("sample_size")) or 0) < 5 else "") + f"; streaks: {compact(m.get('head_to_head_streaks'), 160) if m.get('head_to_head_streaks') else 'none published'}")
    for side, name, other in (("home", home, away), ("away", away, home)):
        mg = d(m.get(f"{side}_manager"))
        rec = d(mg.get("record_at_club"))
        vs = d(m.get(f"{side}_manager_vs_{'away' if side == 'home' else 'home'}_club"))
        out.append(f"Manager of {name}: {mg.get('name', 'n/a')} ({mg.get('country', '?')}, age {mg.get('age', '?')}), in charge since {str(mg.get('appointed_date') or '?')[:10]}" + (", NEW appointment" if mg.get("recent_appointment") else "")
                   + (f"; record at the club W{rec.get('wins')} D{rec.get('draws')} L{rec.get('losses')} ({rec.get('win_pct')}% wins)" if rec else "") + f"; v {other}: W{vs.get('wins', '?')} D{vs.get('draws', '?')} L{vs.get('losses', '?')} in {vs.get('sample_size', '?')} games"
                   + (" (the source's record only, likely incomplete: use the manager duel below and your own knowledge, labelled)" if (num(vs.get("sample_size")) or 0) < 3 else ""))
    md = d(m.get("manager_duel"))
    out.append("Manager duel (the two managers' sides against each other): " + (f"home manager wins {md.get('home_wins')}, draws {md.get('draws')}, away manager wins {md.get('away_wins')} from {md.get('sample_size')}" if md else "not published"))
    out.append(f"Expected formations: {home} {m.get('home_formation') or 'n/a'}, {away} {m.get('away_formation') or 'n/a'}")
    out += shape_matchup(m.get("home_formation"), m.get("away_formation"), home, away)
    for side, name in (("home", home), ("away", away)):
        rot = d(d(m.get("_insights")).get(f"{side}_rotation"))
        if rot.get("formation_changed"):
            out.append(f"  {name} changed shape from {rot.get('previous_formation')} to {rot.get('last_formation')} last match (new shape: less settled)")
    hist = {}
    for x in [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict)]:
        pair = (x.get("home_formation"), x.get("away_formation"))
        px = meeting_possession(x)
        if all(pair) and px[0]:
            hist.setdefault(pair, []).append(f"{x.get('home_team')} {x.get('scoreline')} {x.get('away_team')}, possession {px[0]}-{px[1]}, xG {x.get('home_xg')}-{x.get('away_xg')}")
    for (p, q), rows in hist.items():
        out.append(f"  Shape pairing {p} (home side) v {q} (away side) in past meetings: " + "; ".join(rows))
    for x in [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict)][:3]:
        ph, pa = meeting_possession(x)
        out.append(f"  {str(x.get('date'))[:10]} {x.get('home_team')} {x.get('scoreline')} {x.get('away_team')} ({str(x.get('competition') or '')[:24]}): formations {x.get('home_formation')} v {x.get('away_formation')}; xG {x.get('home_xg')}-{x.get('away_xg')}; possession {ph}-{pa}; referee {x.get('referee')}")
    out.append("Is the head to head still relevant (same tactical setup, same manager, comparable squads)?")
    out += h2h_relevance(m, home, away)
    out.append("How to read it: did the same formations meet before and who controlled it (possession, xG)? Does a manager have a pattern against this opponent (never lost, never won)? A new manager or a changed formation makes old meetings less relevant; a 2-3 meeting history is a hint, not a trend. Say which side's tactics beat the other's last time and whether anything has changed since.")
    return out


def norm_name(x) -> str:
    return re.sub(r'[^a-z0-9]', '', str(x or '').lower())


def window_line(rows) -> str:
    rows = [d(x) for x in (rows if isinstance(rows, list) else [])]
    rows = [x for x in rows if x.get("result") in ("W", "D", "L")]
    if not rows:
        return "no results"
    pts = sum({"W": 3, "D": 1, "L": 0}[x["result"]] for x in rows)
    gf = ga = k = 0
    for x in rows:
        sc = oriented(x)
        if sc:
            gf, ga, k = gf + min(sc[0], 6), ga + min(sc[1], 6), k + 1
    xs = [(num(x.get("xg_for")), num(x.get("xg_against"))) for x in rows if num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
    xt = f", xG {sum(a for a, _ in xs) / len(xs):.2f}-{sum(b for _, b in xs) / len(xs):.2f} per game ({len(xs)} with xG)" if xs else ""
    return f"{''.join(x['result'] for x in rows)} ({len(rows)} games, {pts / len(rows):.2f} points a game, goals {gf / max(k, 1):.1f}-{ga / max(k, 1):.1f} per game{xt})"


def form_windows_section(m: dict, forms: dict, home, away) -> list[str]:
    out = ["", "# FORM WINDOWS: last 5 against last 10, and form inside the head to head (newest result first)"]
    for side, name in (("home", home), ("away", away)):
        f = d(forms[side])
        l5, l10 = window_line(f.get("last5_overall")), window_line(f.get("last10_overall"))
        r5, r10 = [x for x in (f.get("last5_overall") or []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L")], [x for x in (f.get("last10_overall") or []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L")]
        trend = ""
        if len(r5) >= 5 and len(r10) >= 8:
            p = lambda rs: sum({"W": 3, "D": 1, "L": 0}[x["result"]] for x in rs) / len(rs)
            diff = p(r5) - p(r10[5:])
            trend = f"; last 5 v the 5 before: {diff:+.2f} points a game ({'improving' if diff >= 0.5 else 'declining' if diff <= -0.5 else 'steady'})"
        r3 = [x for x in (f.get("last5_overall") or []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L")][:3]
        l3 = window_line(r3) if r3 else "no results"
        p3 = (sum({"W": 3, "D": 1, "L": 0}[x["result"]] for x in r3) / len(r3)) if r3 else None
        p10 = (sum({"W": 3, "D": 1, "L": 0}[x["result"]] for x in r10) / len(r10)) if r10 else None
        mom = "" if p3 is None or p10 is None else f"; momentum (last 3 v last 10): {p3 - p10:+.2f} points a game ({'hot' if p3 - p10 >= 0.7 else 'cold' if p3 - p10 <= -0.7 else 'in line with the longer run'})"
        out += [f"{name}: last 3 (momentum) {l3}{mom}", f"{name}: last 5 {l5}", f"{name}: last 10 (stability) {l10}{trend}"]
    meets = [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict)]
    for name, is_home_side in ((home, True), (away, False)):
        seq = []
        for x in meets:
            mm = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(x.get("scoreline") or ""))
            if not mm:
                continue
            a, b = int(mm.group(1)), int(mm.group(2))
            mine_home = norm_name(x.get("home_team")) == norm_name(name)
            gf, ga = (a, b) if mine_home else (b, a)
            seq.append(("W" if gf > ga else "D" if gf == ga else "L") + f" {gf}-{ga}")
        out.append(f"{name} in the head to head: " + (", ".join(seq) if seq else "no meetings listed") + (" (a hint only: few games, different squads)" if len(seq) < 5 else ""))
    out.append("How to read it: last 5 against last 10 shows whether form is rising or fading; recent form counts for more than old, but check the quality of the opponents behind each result and whether the head-to-head pattern matches the current form or contradicts it.")
    return out


def ppg(w, dr, lo):
    n = (num(w) or 0) + (num(dr) or 0) + (num(lo) or 0)
    return None if not n else ((3 * (num(w) or 0) + (num(dr) or 0)) / n, int(n))


def ground_section(m: dict, ins: dict, forms: dict, home, away) -> list[str]:
    """How hard the home ground is for the visitors: both sides' venue splits, what away games cost the visitors, the trip, the crowd and past meetings here."""
    out = ["", "# HOME GROUND: HOW HOSTILE IS IT FOR THE VISITORS (descriptive, small samples; judge it, do not add a fixed bonus)"]
    out.append(f"Venue: {m.get('venue_name') or 'n/a'}, {m.get('venue_city') or ''} ({m.get('venue_country') or 'n/a'}); capacity {m.get('venue_capacity') or 'n/a'}; round/type {ins.get('match_type') or 'n/a'}")
    sp = {s: d(d(forms[s]).get("venue_split_form")) for s in ("home", "away")}
    hp = ppg(sp["home"].get("home_wins"), sp["home"].get("home_draws"), sp["home"].get("home_losses"))
    ap_home = ppg(sp["home"].get("away_wins"), sp["home"].get("away_draws"), sp["home"].get("away_losses"))
    ap = ppg(sp["away"].get("away_wins"), sp["away"].get("away_draws"), sp["away"].get("away_losses"))
    ah = ppg(sp["away"].get("home_wins"), sp["away"].get("home_draws"), sp["away"].get("home_losses"))
    t = lambda v: "no games" if v is None else f"{v[0]:.2f} points a game in {v[1]} games"
    out.append("Venue split (only the most recent games whose venue the scraper confirmed, usually 5):")
    out += [f"{home} at home: {t(hp)}; away from home: {t(ap_home)}", f"{away} away from home: {t(ap)}; at home: {t(ah)}"]
    def rows_rec(side, venue):
        rs = [x for x in (d(forms[side]).get("last20_overall") or []) if isinstance(x, dict) and x.get("venue") == venue and x.get("neutral_venue") is not True and x.get("result") in ("W", "D", "L")]
        return ppg(sum(x["result"] == "W" for x in rs), sum(x["result"] == "D" for x in rs), sum(x["result"] == "L" for x in rs)) if rs else None
    rh, ra = rows_rec("home", "home"), rows_rec("away", "away")
    out.append(f"From the result rows (last 20, by the fixture's home/away label, confirmed neutral grounds left out): {home} at home {t(rh)}; {away} away {t(ra)}. Quote this record when it has more games than the venue split; the two differ only in window.")
    if rh and (not hp or rh[1] > hp[1]):
        hp = rh
    if ra and (not ap or ra[1] > ap[1]):
        ap = ra
    if hp and ap:
        out.append(f"Venue swing: the home side's home record against the visitors' away record = {hp[0] - ap[0]:+.2f} points a game" + (" (visitors travel badly)" if ap[0] <= 0.8 and ap[1] >= 3 else " (visitors travel well)" if ap[0] >= 1.6 and ap[1] >= 3 else "") + ("; thin samples" if min(hp[1], ap[1]) < 4 else ""))
    for s, name in (("home", home), ("away", away)):
        f = d(forms[s])
        out.append(f"{name} win rate in the venue split at home {f.get('home_win_rate_pct', 'n/a')}% (sample {f.get('home_win_rate_sample_size', '?')}), away {f.get('away_win_rate_pct', 'n/a')}% (sample {f.get('away_win_rate_sample_size', '?')})")
    for s, name, key in (("home", home, "home"), ("away", away, "away")):
        dv = d(d(d(forms[s]).get("detailed_venue_split")).get(key))
        n = num(dv.get("sample_size"))
        if n:
            g = lambda k: per(dv.get(k), n)
            out.append(f"{name} {key} games ({int(n)}): xG {g('xg_for') and round(g('xg_for'), 2)}-{g('xg_against') and round(g('xg_against'), 2)}, shots {g('shots_for')}-{g('shots_against')}, possession {dv.get('possession_pct_avg')}%, fouls {g('fouls_for')}-{g('fouls_against')}, yellows {g('yellow_cards_for')}-{g('yellow_cards_against')}, reds {dv.get('red_cards_for')}-{dv.get('red_cards_against')} (more fouls and cards for the visitors than against them = the crowd and referee leaning on them)")
    tr = d(ins.get("travel_info"))
    out.append(f"Trip for the visitors: {tr.get('away_travel_distance_km', 'n/a')} km, {tr.get('away_travel_time_hours', 'n/a')} h, time-zone shift {tr.get('away_timezone_diff_hours', 'n/a')} h; the home side travels {tr.get('home_travel_distance_km', 'n/a')} km")
    def at_ground(x):
        if m.get("venue_name") and x.get("venue_name"):
            return norm_name(x.get("venue_name")) == norm_name(m.get("venue_name"))
        return norm_name(x.get("home_team")) == norm_name(home) and x.get("neutral_venue") is not True   # venue not named: today's hosts at home
    here = [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict) and at_ground(x)]
    rec = []
    for x in here:
        mm = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(x.get("scoreline") or ""))
        if mm:
            a, b = int(mm.group(1)), int(mm.group(2))
            rec.append("W" if a > b else "D" if a == b else "L")
    out.append("Past meetings at this ground: " + ("; ".join(f"{str(x.get('date'))[:10]} {x.get('home_team')} {x.get('scoreline')} {x.get('away_team')}" + (f", attendance {x.get('attendance')}" if x.get("attendance") else "") for x in here) if here else "none listed")
               + (f" -> {home} here: {''.join(rec)} ({len(rec)} of the listed meetings; a hint only)" if rec else ""))
    w = d(m.get("weather_detail"))
    wind, gust, rain, mm, temp, hum = (num(w.get(k)) for k in ("wind_speed_kmph", "wind_gust_kmph", "chance_of_rain_pct", "precip_mm", "temp_c", "humidity_pct"))
    fx = []
    if wind is not None and (wind >= 25 or (gust or 0) >= 40):
        fx.append(f"WIND {wind:.0f} km/h (gusts {fmt(gust, 0)}): crossing, long balls, goal kicks and keeper distribution suffer; direct play and set pieces gain, passing-heavy sides lose control")
    if (mm or 0) >= 1 or (rain or 0) >= 60:
        fx.append(f"RAIN ({fmt(rain, 0)}% chance, {fmt(mm, 1)} mm): a slick pitch raises set-piece danger and defensive mistakes, favours shooting from range and quick passing, and can lower the total on a heavy pitch")
    if temp is not None and (temp >= 27 or (temp >= 24 and (hum or 0) >= 70)):
        fx.append(f"HEAT {temp:.0f}C (humidity {fmt(hum, 0)}%): suppresses pressing and the second-half tempo, rewards the deeper bench and the side that presses less")
    if temp is not None and temp <= 3:
        fx.append(f"COLD {temp:.0f}C: a harder, faster pitch and tighter muscles")
    out.append("weather effects: " + ("; ".join(fx) if fx else "no wind, rain or heat flag at kickoff") + ". Pitch type, surface quality and altitude are not in the data: use your own knowledge and label it unverified.")
    out.append("How to read it: a loud ground matters when the home side's home record is clearly better than its away record, the visitors travel badly, the trip is long, the crowd is large or the tie has a derby or title edge; it matters little on a neutral ground or when both sides have thin home/away samples. Say how hostile it is and which player types it hurts (young or inexperienced visitors, a goalkeeper under crosses, referee pressure on tight calls).")
    return out


def rating_lines(prof: dict) -> dict:
    out = {}
    for role in "GDMF":
        rows = [(mins, num(u.get("avg_rating")), p) for mins, p, u in player_roles(prof, role, 90) if num(u.get("avg_rating")) is not None]
        tot = sum(mn for mn, _, _ in rows)
        out[role] = (sum(mn * rt for mn, rt, _ in rows) / tot if tot else None, rows)
    return out


SHRINK_MEAN, SHRINK_K = 1.35, 6.0          # goals per side per game in internationals; the sample is worth K games of "average" before the team's own games count for more


def shrunk(raw, n, k=None):
    """Small-sample shrink toward the league mean: (n x raw + K x mean) / (n + K). 4 games count for 40% of the answer, 12 games for 67%."""
    k = SHRINK_K if k is None else k
    if n is None or n + k <= 0:
        return SHRINK_MEAN
    return (n * raw + k * SHRINK_MEAN) / (n + k)


HOME_EDGE = 0.093          # log-goal shift for the venue: HALF of the fitted home advantage (0.186 in the Poisson model fitted on 17,498 internationals, data/history-model.json). Each side's sample mixes home and away games, so its average sits about midway; this match's venue moves the home side up and the away side down by half the edge each. Applied only when the match is not at a neutral ground.


_NEUTRAL = False           # set per report by set_venue(): True when the "home" side is not playing in its own country


def set_venue(report) -> bool:
    """Reads the report's venue: the home edge is off when the venue's country is not the home team's country (a displaced home game such as Belarus in Hungary, or a tournament ground). Missing data counts as a normal home game."""
    global _NEUTRAL
    m = report.get("match") if isinstance(report, dict) and isinstance(report.get("match"), dict) else report if isinstance(report, dict) else {}
    a, b = (str(m.get(k) or "").strip().lower() for k in ("home_team_country", "venue_country"))
    _NEUTRAL = bool(a and b and a != b)
    return _NEUTRAL


def venue_anchor(home_att, away_def, away_att, home_def, neutral=None):
    """The xG anchor for this match from each side's (shrunk) attack and the other's defence: the plain average, then the venue edge (off at a neutral or displaced ground)."""
    e = 0.0 if (_NEUTRAL if neutral is None else neutral) else HOME_EDGE
    return (home_att + away_def) / 2 * math.exp(e), (away_att + home_def) / 2 * math.exp(-e)

RATING_SLOPE, RATING_EDGE, RATING_MEAN = 0.24, 0.14, 1.54   # fitted on 539 matches of the 2026-27 season in 7 leagues with each club's StatsUltra overall rating AS IT STOOD BEFORE the match (no look-ahead): log goals = log(1.54) +- (0.14 / 2 for the venue) +- 0.24 x (rating gap / 10). Held out (216 matches): Brier 0.580 against the bookmaker's 0.578 and 0.651 with no ratings.


ELO_SLOPE, ELO_EDGE = 0.20, 0.20     # fitted on 229 top-5-league matches of 2026-27 with each club's ClubElo as it stood the day BEFORE the match (no look-ahead): log goals = log(1.54) +- (0.20 / 2 for the venue) +- 0.20 x (Elo gap / 100). Held out (92 matches): Brier 0.528 against the bookmaker's 0.542 and 0.612 with no ratings (too few matches to call it better than the bookmaker; it scored no worse than the StatsUltra rating, 0.549, on the same matches).


LEAGUE_GOALS = (    # (countries, competition pattern, goals a match) from football-data.co.uk results 2019-20 to 2024-25. One goal level for every league (1.54 a side, 3.08 a match) put LaLiga's draw at 24% against 27% real, and missed Alavés 1-1 Málaga (2026-10-23). Held out on 2024-25 (2,916 matches, venue edge only, no ratings): Brier 0.6513 fixed v 0.6508 league-scaled, better in 6 of 8 leagues, most in the low-scoring ones.
    ({"England"}, r"premier league", 2.88), ({"England"}, r"championship", 2.50), ({"England"}, r"league one", 2.62), ({"England"}, r"league two", 2.53), ({"England"}, r"national league", 2.78),
    ({"Scotland"}, r"premiership", 2.66), ({"Scotland"}, r"championship", 2.69),
    ({"Spain"}, r"hypermotion|segunda|laliga ?2|smartbank", 2.21), ({"Spain"}, r"la ?liga|primera", 2.54),
    ({"Germany"}, r"2\.? ?bundesliga", 2.96), ({"Germany"}, r"bundesliga", 3.15),
    ({"Italy"}, r"serie b", 2.45), ({"Italy"}, r"serie a", 2.78),
    ({"France"}, r"ligue 2", 2.36), ({"France"}, r"ligue 1", 2.77),
    ({"Netherlands"}, r"eredivisie", 3.04), ({"Portugal"}, r"primeira|liga portugal", 2.58),
    ({"Belgium"}, r"pro league|first division a", 2.93), ({"Turkey", "Türkiye"}, r"s[uü]per lig", 2.83), ({"Greece"}, r"super league", 2.45),
)


def league_goals(match) -> tuple[float, str] | None:
    """(goals a match, competition) for a domestic league in LEAGUE_GOALS, gated on the home club's country (several countries share names like Premier League); None for cups, European ties and unlisted leagues."""
    if not isinstance(match, dict):
        return None
    comp, country = str(match.get("competition") or ""), match.get("home_team_country") or match.get("venue_country")
    if any(w in comp.lower() for w in ("cup", "copa", "pokal", "coupe", "coppa", "taça", "beker", "play-off", "playoff")):
        return None
    for countries, pat, goals in LEAGUE_GOALS:
        if country in countries and re.search(pat, comp, re.I):
            return goals, comp
    return None


NAT_SLOPE, NAT_EDGE, NAT_MEAN = 0.20, 0.30, 1.36   # national teams. The first fit (8,630 internationals since 2018, Elo computed in date order, held out 1,396: Brier 0.502 against 0.636 with no ratings) gave 0.165 per 100 Elo each side, which divided by 1.2 for eloratings.net's wider scale was 0.14. That flattened the favourites: on the 23 national matches of 1-5 Oct 2026 with Bet365 prices and results, slope 0.14 scored Brier 0.457 against the market's 0.430, while 0.20 scored 0.430 (equal to the market) and slopes up to 0.35 scored better still on results (0.406). 0.20 is the market-matching, conservative choice; home edge 0.30 (0 on neutral ground), 1.36 goals a side. Still a small sample.


NAT_GAP_CAP = 4.0   # national rating gaps are capped at 400 points: Spain (2281) v Czechia (1659) gave 5.48-0.34 (99% for Spain) and Czechia scored in a 3-1; at 400 points the anchor is 3.50-0.53 (about 93%)


def class_elo(ins: dict, side: str) -> float | None:
    """A rating of the side's class: ClubElo for clubs, eloratings.net for national sides; None otherwise (other Elo sources are form-only and say nothing about class)."""
    ce = num(d(ins.get(f"{side}_club_elo")).get("elo"))
    if ce is not None:
        return ce
    er = d(ins.get(f"{side}_elo_rating"))
    return num(er.get("elo")) if er.get("sample_source") == "eloratings.net" else None


def rating_anchor(ins: dict, match: dict | None = None):
    """Expected goals from the two clubs' class (None without both): ClubElo first (long-run, comparable between any two clubs), else StatsUltra overall. Returns (lam_home, lam_away, home_rating, away_rating, source). The data-only anchor that counts class, which the xG anchor lacks. Venue edge off for a displaced ground. The goal level is the league's (league_goals) when the match is a listed domestic league, else RATING_MEAN a side."""
    def pair(key, field):
        vals = []
        for side in ("home", "away"):
            row = ins.get(f"{side}_{key}") if isinstance(ins, dict) else None
            v = row.get(field) if isinstance(row, dict) else None
            if not isinstance(v, (int, float)):
                return None
            vals.append(float(v))
        return vals
    lg = league_goals(match)
    m = math.log(lg[0] / 2 if lg else RATING_MEAN)
    o = pair("club_elo", "elo")
    if o:
        d, e = (o[0] - o[1]) / 100, 0.0 if _NEUTRAL else ELO_EDGE
        return math.exp(m + e / 2 + ELO_SLOPE * d), math.exp(m - e / 2 - ELO_SLOPE * d), o[0], o[1], "ClubElo"
    o = pair("club_strength", "overall")
    if o:
        d, e = (o[0] - o[1]) / 10, 0.0 if _NEUTRAL else RATING_EDGE
        return math.exp(m + e / 2 + RATING_SLOPE * d), math.exp(m - e / 2 - RATING_SLOPE * d), o[0], o[1], "StatsUltra"
    if all(isinstance(ins.get(f"{side}_elo_rating"), dict) and ins[f"{side}_elo_rating"].get("sample_source") == "eloratings.net" for side in ("home", "away")) if isinstance(ins, dict) else False:
        o = pair("elo_rating", "elo")                              # national sides on eloratings.net: a real cross-calibrated rating (form-only Elo from other sources is never used here)
        if o:
            d, e, m_n = max(-NAT_GAP_CAP, min(NAT_GAP_CAP, (o[0] - o[1]) / 100)), 0.0 if _NEUTRAL else NAT_EDGE, math.log(NAT_MEAN)
            return math.exp(m_n + e / 2 + NAT_SLOPE * d), math.exp(m_n - e / 2 - NAT_SLOPE * d), o[0], o[1], "eloratings.net"
    return None



LEVEL_K = 12.0              # a side flagged as stepping up in level or thin on evidence is shrunk twice as hard


def level_flag(side: str, name: str, forms: dict, ins: dict, home, away, n_xg) -> list[str]:
    """Reasons the side's recent numbers may not carry over to this match (promoted or newly arrived at this level, form from weaker opposition, few comparable games). KellyBench: newly promoted sides broke LLM agents that kept using their old numbers."""
    reasons = []
    if n_xg is not None and n_xg < 5:
        reasons.append(f"only {n_xg:g} games with xG")
    elo = load_elo()
    other = "away" if side == "home" else "home"
    opp_elo = class_elo(ins, other) or (elo_of(elo, away if side == "home" else home) if elo else None)
    if elo and opp_elo is not None:
        rows = [x for x in (d(forms.get(side)).get("last10_overall") or []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L")]
        known = [e for e in (elo_of(elo, x.get("opponent")) for x in rows) if e is not None]
        if len(known) >= 3:
            avg = sum(known) / len(known)
            if avg < opp_elo - 120:
                reasons.append(f"its last {len(known)} opponents average Elo {avg:.0f}, {opp_elo - avg:.0f} below this opponent's {opp_elo:.0f} (a step up in level)")
            close = sum(1 for e in known if e >= opp_elo - 100)
            if close < 2:
                reasons.append(f"only {close} of its last {len(known)} games came against a side within 100 Elo of this opponent")
    return reasons


def shrink_section(r: dict, m: dict, ins: dict, home, away, forms: dict | None = None) -> list[str]:
    """xG per game shrunk for small samples, and the xG anchor built from the shrunk numbers (the anchor to use when the report has no odds, and the reference the specialists' xG changes are measured from)."""
    out = ["", f"# SHRUNK xG (small samples are pulled toward {SHRINK_MEAN} goals a side: (n x raw + {SHRINK_K:g} x {SHRINK_MEAN}) / (n + {SHRINK_K:g}); a team with 4 games counts for 40% of its own number)"]
    got: dict = {}
    comp: dict = {}
    for side, name in (("home", home), ("away", away)):
        est = d(ins.get(f"{side}_xg_estimate"))
        n, f, a = num(est.get("sample_size")), num(est.get("xg_for")), num(est.get("xg_against"))
        if not n or f is None or a is None:
            out.append(f"{name}: no xG sample, nothing to shrink")
            continue
        rf, ra = f / n, a / n
        flags_ = level_flag(side, name, forms or {}, ins, home, away, n)
        k = LEVEL_K if flags_ else None
        got[side] = (shrunk(rf, n, k), shrunk(ra, n, k))
        out.append(f"{name}: raw {rf:.2f} for / {ra:.2f} against over {n:g} games -> shrunk {got[side][0]:.2f} for / {got[side][1]:.2f} against" + (f"  <-- LEVEL FLAG (shrunk twice as hard, K={LEVEL_K:g}): {'; '.join(flags_)}. Do not move this side far from the anchor on its recent numbers alone." if flags_ else ""))
        rows = [x for x in (d(d(forms or {}).get(side)).get("last10_overall") or []) if isinstance(x, dict) and num(x.get("xg_for")) is not None and oriented(x)]
        ad = d(ins.get(f"{side}_advanced_stats"))
        an = num(ad.get("sample_size"))
        if len(rows) >= 3:
            gf, ga = (sum(oriented(x)[i] for x in rows) / len(rows) for i in (0, 1))
            npf, npa = (num(ad.get("non_penalty_xg_for")), num(ad.get("non_penalty_xg_against"))) if an else (None, None)
            if npf is None or npa is None or not (0.75 * rf <= npf / an <= 1.02 * rf and 0.75 * ra <= npa / an <= 1.02 * ra):
                npf = npa = None                                    # non-penalty xG cannot exceed total xG or be far below it: a different sample, so leave it out
            parts_f = [gf, rf] + ([npf / an] if npf is not None else [])
            parts_a = [ga, ra] + ([npa / an] if npa is not None else [])
            cf, ca = sum(parts_f) / len(parts_f), sum(parts_a) / len(parts_a)
            comp[side] = (shrunk(cf, len(rows), k), shrunk(ca, len(rows), k))
            out.append(f"  composite (goals {gf:.2f}/{ga:.2f}{', non-penalty xG ' + format(npf / an, '.2f') + '/' + format(npa / an, '.2f') if npf is not None else ''}, xG {rf:.2f}/{ra:.2f} averaged, as the SPI model does, so no single noisy measure leads): {cf:.2f} for / {ca:.2f} against -> shrunk {comp[side][0]:.2f} / {comp[side][1]:.2f} over {len(rows)} games")
    if len(got) == 2:
        ah_, aa_ = venue_anchor(got['home'][0], got['away'][1], got['away'][0], got['home'][1])
        out.append(f"xG anchor from the shrunk numbers: {home} ({got['home'][0]:.2f} + {got['away'][1]:.2f}) / 2 = {(got['home'][0] + got['away'][1]) / 2:.2f}; {away} ({got['away'][0]:.2f} + {got['home'][1]:.2f}) / 2 = {(got['away'][0] + got['home'][1]) / 2:.2f}. With the venue edge (home x{math.exp(0 if _NEUTRAL else HOME_EDGE):.2f}, away x{math.exp(0 if _NEUTRAL else -HOME_EDGE):.2f}, from the fitted home advantage{'; OFF here: the venue is outside the home team country' if _NEUTRAL else '; off when the venue is outside the home team country'}): {home} {ah_:.2f}, {away} {aa_:.2f}")
    ra_ = rating_anchor(ins, m)
    if ra_:
        lg_ = league_goals(m) if ra_[4] != "eloratings.net" else None
        level = (f"goal level {lg_[0]:.2f} a match, the {lg_[1]} average 2019-25" if lg_ else f"goal level {2 * RATING_MEAN:.2f} a match, the default (league not listed)") if ra_[4] != "eloratings.net" else f"goal level {2 * NAT_MEAN:.2f} a match"
        out.append(f"RATING ANCHOR (the class of the two clubs, {ra_[4]} {'overall' if ra_[4] == 'StatsUltra' else 'Elo'} {ra_[2]:.1f} v {ra_[3]:.1f}, gap {ra_[2] - ra_[3]:+.1f}; {level}): {home} {ra_[0]:.2f}, {away} {ra_[1]:.2f}. This one counts class, which the xG anchor above lacks; on held-out 2026-27 matches it scored about the same as the bookmaker. START from it and move it ONLY for team news (a named absence or a confirmed lineup); form, luck, short samples, tactics and the xG anchor (the cross-check) do not move it.")
    cl_ = cross_league_line(r, m, ins, home, away, forms or {})
    if cl_:
        out.append(cl_)
    if len(comp) == 2:
        out.append(f"composite anchor (cross-check): {home} ({comp['home'][0]:.2f} + {comp['away'][1]:.2f}) / 2 = {(comp['home'][0] + comp['away'][1]) / 2:.2f}; {away} ({comp['away'][0]:.2f} + {comp['home'][1]:.2f}) / 2 = {(comp['away'][0] + comp['home'][1]) / 2:.2f}")
    return out


def news_window(r: dict, m: dict) -> tuple[float | None, str]:
    """Hours between the scrape and kickoff, and a plain label: LATE-NEWS WINDOW (unconfirmed lineups within a day of kickoff: late injuries and rotation can still move everything; markets also misprice at that moment) or STALE REPORT (scraped a week or more before kickoff)."""
    import datetime
    def t(x):
        try:
            v = datetime.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except ValueError:
            return None
        return v if v.tzinfo else v.replace(tzinfo=datetime.timezone.utc)          # a time with no zone is UTC, so the two can be subtracted
    ko, gen = t(m.get("kickoff_utc")), t(r.get("generatedAt"))
    if ko is None or gen is None:
        return None, ""
    hours = (ko - gen).total_seconds() / 3600
    if hours >= 7 * 24:
        return hours, f"STALE REPORT: scraped {hours / 24:.0f} days before kickoff; injuries, form and lineups may have changed since, so confidence cannot be high"
    if not m.get("lineup_confirmed") and 0 <= hours <= 24:
        return hours, f"LATE-NEWS WINDOW: kickoff {hours:.0f} h after the scrape with lineups unconfirmed; late news can still change the picture, so confidence cannot be high"
    return hours, ""


def rating_section(home, away, profiles: dict) -> list[str]:
    out = ["", "# PLAYER RATINGS COMPARED (minutes-weighted average match rating over the recent window, regulars with 90+ minutes)"]
    rl = {s: rating_lines(profiles[s]) for s in ("home", "away")}
    names = {"G": "goalkeeper", "D": "defenders", "M": "midfielders", "F": "attackers"}
    out += [f"| line | {home} (home) | {away} (away) | edge |", "|---|---|---|---|"]
    for role in "GDMF":
        a, b = rl["home"][role][0], rl["away"][role][0]
        edge = "n/a" if a is None or b is None else f"{home} +{a - b:.2f}" if a - b >= 0.15 else f"{away} +{b - a:.2f}" if b - a >= 0.15 else "level"
        out.append(f"| {names[role]} | {'n/a' if a is None else f'{a:.2f}'} | {'n/a' if b is None else f'{b:.2f}'} | {edge} |")
    for s, name in (("home", home), ("away", away)):
        allr = sorted(((rt, str(p.get("name")), mins) for role in "GDMF" for mins, rt, p in rl[s][role][1] if mins >= 180), key=lambda t: (t[0], t[1]))
        low = [f"{n} {rt:.2f}" for rt, n, _ in allr[:3] if rt < 6.6]
        top = [f"{n} {rt:.2f}" for rt, n, _ in allr[::-1][:3]]
        out.append(f"{name}: best rated {', '.join(top) or 'n/a'}; weak form (under 6.6, likely to underperform): {', '.join(low) or 'none'}")
    out.append("How to read it: a line rated clearly higher than the opposing line has been playing better against its own opposition (not this opponent: opposition quality differs); a ratings gap on the same line as a stats gap (xG, tackles, passing) is a stronger signal than either alone; ratings can be inflated by a few easy games.")
    return out


def flank_section(m: dict, ins: dict, home, away, profiles: dict) -> list[str]:
    """The report has no left/right data: show the width evidence it does have and the wide players, and leave the flank-by-flank map to the analyst."""
    out = ["", "# FLANKS (the report has NO left / right / centre split: use the width evidence below plus your own football knowledge of the named players, and label the knowledge as unverified)"]
    for side, name, other in (("home", home, away), ("away", away, home)):
        ad = d(ins.get(f"{side}_advanced_stats"))
        n = num(ad.get("sample_size"))
        fx = lambda k, nd=1: "n/a" if per(ad.get(k), n) is None else f"{per(ad.get(k), n):.{nd}f}"
        shape = parse_shape(m.get(f"{side}_formation"))
        wb = " (back five: wing-backs provide the width)" if shape and shape[0] >= 5 else " (back four: full-backs)" if shape and shape[0] == 4 else ""
        out.append(f"{name}: crosses {fx('crosses_for')} for / {fx('crosses_against')} against per game; dribbles {fx('dribbles_for')} / {fx('dribbles_against')}; shots outside the box {fx('shots_outside_box_for')} / {fx('shots_outside_box_against')}; touches in the box {fx('touches_in_box_for')} / {fx('touches_in_box_against')}; formation {m.get(f'{side}_formation') or 'n/a'}{wb}")
        prof = profiles[side]
        wide = []
        for role in "DMF":
            for mins, p, u in player_roles(prof, role, 90)[:4 if role != "F" else 3]:
                wide.append(f"{p.get('name')} ({role}, {mins:g} min, rating {u.get('avg_rating')}, KP {p90(u.get('total_key_passes'), mins) and round(p90(u.get('total_key_passes'), mins), 1)}/90, wide-back starts {u.get('wide_back_starts')}, centre-back starts {u.get('central_back_starts')})")
        out.append(f"  {name} outfield regulars to place on a flank (left back, right back, left or right wing, centre): " + ("; ".join(wide[:9]) or "none with 90+ minutes"))
    goals = []
    for x in [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict)][:3]:
        for e in x.get("event_timeline") or []:
            if isinstance(e, dict) and e.get("type") == "goal":
                goals.append(f"{str(x.get('date'))[:10]} {e.get('minute')}' {e.get('player')} ({x.get('home_team') if e.get('team') == 'home' else x.get('away_team')}, {e.get('detail')})")
    out.append("Goals in the past meetings (who scored, to place the route): " + ("; ".join(goals) if goals else "none listed / goalless"))
    out.append("How to read it: place each side's wide players on left and right from your knowledge, then compare the MIRROR pairs for both sides: side A's right-wing attack meets side B's LEFT-back; side A's left-wing attack meets side B's RIGHT-back; then the centre. A side strong on a flank against an opponent weak on the opposite defensive flank has a route to exploit; do it for both sides with the same depth (symmetry), say what the evidence for each flank is, and mark it unverified where it is only your knowledge.")
    return out


def ht_pair(x: dict):
    """Half-time score from this team's side: (own, other); None when missing."""
    mm = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(x.get("ht_scoreline") or ""))
    if not mm:
        return None
    a, b = int(mm.group(1)), int(mm.group(2))
    return (b, a) if x.get("venue") == "away" else (a, b)


def mind_profile(f: dict) -> dict:
    """What recent results say about how a side reacts to being behind, ahead or beaten."""
    rows = [x for x in (f.get("last20_overall") or f.get("last10_overall") or []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L")]
    out = {"n": len(rows)}
    behind = [x for x in rows if ht_pair(x) and ht_pair(x)[0] < ht_pair(x)[1]]
    ahead = [x for x in rows if ht_pair(x) and ht_pair(x)[0] > ht_pair(x)[1]]
    out["behind"], out["ahead"] = len(behind), len(ahead)
    out["with_ht"] = sum(1 for x in rows if ht_pair(x))
    out["rescued"] = sum(x["result"] in ("W", "D") for x in behind)
    out["won_from_behind"] = sum(x["result"] == "W" for x in behind)
    out["dropped"] = sum(x["result"] in ("D", "L") for x in ahead)
    after = [rows[i - 1] for i in range(1, len(rows)) if rows[i]["result"] == "L"]       # newest first: rows[i-1] is the next match
    out["after_loss"] = "".join(x["result"] for x in after)
    out["after_loss_pts"] = sum({"W": 3, "D": 1, "L": 0}[x["result"]] for x in after)
    return out


def psychology_section(m: dict, ins: dict, forms: dict, home, away) -> list[str]:
    out = ["", "# PSYCHOLOGY: HOW EACH SIDE REACTS WHEN LOSING, LEADING AND AFTER DEFEAT (small samples: a tendency to weigh, not a law)"]
    for side, name in (("home", home), ("away", away)):
        f = d(forms[side])
        mp = mind_profile(f)
        st = d(f.get("current_streak"))
        ls = d(ins.get(f"{side}_losing_streak_context"))
        ss = d(ins.get(f"{side}_streak_stability"))
        hs = d(f.get("half_split"))
        res = d(ins.get(f"{side}_resilience"))
        z = d(ins.get(f"{side}_standings_zone"))
        out.append(f"{name}: current streak {st.get('count', '?')}{st.get('result', '')}; losing-run context {compact(ls, 160)}; streak stability {compact(ss, 160)}")
        out.append(f"  after a defeat (next-match results, newest first): {mp['after_loss'] or 'no defeat in the window'}" + (f" = {mp['after_loss_pts'] / max(len(mp['after_loss']), 1):.2f} points a game (sample {len(mp['after_loss'])})" if mp["after_loss"] else ""))
        out.append(f"  trailing at half time in {mp['behind']} of {mp['with_ht']} games with half-time scores: got something in {mp['rescued']}, won {mp['won_from_behind']}; leading at half time in {mp['ahead']}: dropped points in {mp['dropped']}")
        if hs:
            out.append(f"  half split ({hs.get('sample_size')} games): first half {hs.get('first_half_goals_for')}-{hs.get('first_half_goals_against')}, second half {hs.get('second_half_goals_for')}-{hs.get('second_half_goals_against')} (a slow starter or a side that fades shows here)")
        out.append(f"  resilience: {compact(res, 120)}; errors leading to a goal for/against {d(ins.get(f'{side}_advanced_stats')).get('errors_lead_to_goal_for')}/{d(ins.get(f'{side}_advanced_stats')).get('errors_lead_to_goal_against')}; stakes: {compact(z, 150)}")
    for side, name in (("home", home), ("away", away)):
        fm = d(forms.get(side))
        z = d(ins.get(f"{side}_standings_zone"))
        rot = d(ins.get(f"{side}_rotation"))
        changed = num(rot.get("changed_players")) or 0
        zone = str(z.get("zone") or "")
        nxt = [x for x in (fm.get("next5_with_gaps") or []) if isinstance(x, dict)][1:2]
        short = bool(nxt) and (num(nxt[0].get("days_since_previous")) or 99) <= 4
        quality = ("DESPERATE (fighting relegation: it needs the result)" if z.get("in_the_mix") and zone == "relegation-zone"
                   else "CHASING (a title or promotion race still open: it wants the result)" if z.get("in_the_mix") and zone in ("top-of-table", "title", "promotion")
                   else "ROTATING (a changed XI and a close next match)" if changed >= 4 and short else "SECURE (nothing decided either way: motivation is ordinary)" if z else "unknown (no standings)")
        dv = d(d(fm.get("detailed_venue_split")))
        yel = sum(num(d(dv.get(k)).get("yellow_cards_for")) or 0 for k in ("home", "away", "neutral"))
        red = sum(num(d(dv.get(k)).get("red_cards_for")) or 0 for k in ("home", "away", "neutral"))
        gms = sum(num(d(dv.get(k)).get("sample_size")) or 0 for k in ("home", "away", "neutral"))
        comp = [c for c in (fm.get("form_by_competition") or []) if isinstance(c, dict) and num(c.get("played"))]
        stakes = sorted(comp, key=lambda c: -(num(c.get("played")) or 0))[:3]
        out.append(f"{name} - motivation quality: {quality}; emotional control proxy (discipline): {yel:g} yellows and {red:g} reds in {gms:g} games with venue data; record by competition: " + ("; ".join(f"{c.get('competition')} W{c.get('wins')} D{c.get('draws')} L{c.get('losses')} ({c.get('played')})" for c in stakes) or "n/a"))
    out.append("Not in the data (label your own knowledge, unverified): confidence, anxiety and focus as such, dressing-room cohesion, how the pre-match meeting is timed, crowd-pressure response in derbies and knockout ties, player-specific pressure response, routine disruption and emotional readiness. The proxies above are results after defeat, points rescued and dropped, a new manager, frozen-out players, discipline, a travel and rest load, and the record in similar competitions.")
    out.append("How to read it: a side on a losing run usually tries to bounce back (more intensity, a changed XI), but only if the cause is luck (xG better than results) rather than quality, and it is fragile if a goal conceded early snowballs (trailing at half time and rarely rescued). A side that rescues points from behind and wins after defeats has a resilient mentality; a side that drops points from leading positions fades under pressure. Stakes change it (a side with nothing to play for, one in a relegation fight, one needing a win). Compare both sides the same way and say what it does to the draw and to the underdog's chance.")
    return out


def parse_day(x):
    import datetime
    try:
        return datetime.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def gap_profile(rows, kickoff) -> dict:
    """Days between consecutive matches (newest first), how the side did on short rest, and results against xG."""
    import datetime
    rows = [x for x in (rows if isinstance(rows, list) else []) if isinstance(x, dict) and parse_day(x.get("date"))]
    rows.sort(key=lambda x: parse_day(x.get("date")), reverse=True)
    ko = parse_day(kickoff)
    out = {"gaps": [], "short": [], "long": []}
    if ko and rows:
        out["since_last"] = (ko - parse_day(rows[0]["date"])).days
    for i, x in enumerate(rows[:-1]):
        gap = (parse_day(x["date"]) - parse_day(rows[i + 1]["date"])).days
        out["gaps"].append(gap)
        if x.get("result") in ("W", "D", "L"):
            (out["short"] if gap <= 4 else out["long"]).append(x["result"])
    pts = lambda rs: None if not rs else sum({"W": 3, "D": 1, "L": 0}[r] for r in rs) / len(rs)
    out["short_ppg"], out["long_ppg"] = pts(out["short"]), pts(out["long"])
    gd = []
    for x in rows[:10]:
        sc, a, b = oriented(x), num(x.get("xg_for")), num(x.get("xg_against"))
        if sc and a is not None and b is not None:
            gd.append((sc[0] - a, sc[1] - b))
    out["xg_n"] = len(gd)
    out["gf_vs_xg"] = sum(g for g, _ in gd) / len(gd) if gd else None
    out["ga_vs_xg"] = sum(g for _, g in gd) / len(gd) if gd else None
    return out


def fatigue_section(m: dict, ins: dict, forms: dict, home, away) -> list[str]:
    out = ["", "# GAPS BETWEEN MATCHES, FATIGUE AND UNDERPERFORMING (same reading for both sides)"]
    ko = m.get("kickoff_utc") or m.get("kickoff") or m.get("date")
    for side, name in (("home", home), ("away", away)):
        f = d(forms[side])
        g = gap_profile(f.get("last10_overall"), ko)
        gaps = g["gaps"][:6]
        t = lambda v, n: "no games" if v is None else f"{v:.2f} points a game in {len(n)} games"
        out.append(f"{name}: days between its last matches (newest first) {gaps or 'n/a'}" + (f"; {g['since_last']} days since the last match" if "since_last" in g else "") + f"; matches in the last 7/14 days {f.get('matches_last7_days', '?')}/{f.get('matches_last14_days', '?')}")
        out.append(f"  on short rest (4 days or fewer after the previous match): {t(g['short_ppg'], g['short'])}; on longer rest: {t(g['long_ppg'], g['long'])}" + ("  <-- tires when the schedule is tight" if g["short_ppg"] is not None and g["long_ppg"] is not None and len(g["short"]) >= 3 and g["short_ppg"] <= g["long_ppg"] - 0.7 else ""))
        if g["xg_n"]:
            out.append(f"  results against chances, last {g['xg_n']} games with xG: scored {g['gf_vs_xg']:+.2f} goals a game against its xG, conceded {g['ga_vs_xg']:+.2f} against xG against" + ("  <-- UNDERPERFORMING in attack (finishing below chances: expect a return to the xG level, not above it; only about 10% of a finishing gap carries into the next games and nothing is 'owed')" if g["gf_vs_xg"] <= -0.4 else "  <-- OVERPERFORMING in attack (finishing above chances: expect regression)" if g["gf_vs_xg"] >= 0.4 else "") + ("  <-- conceding MORE than the chances allowed (weak keeper or bad luck)" if g["ga_vs_xg"] >= 0.4 else "  <-- conceding LESS than the chances allowed (keeper hot or lucky)" if g["ga_vs_xg"] <= -0.4 else ""))
        rp = d(ins.get(f"{side}_rest_performance"))
        out.append(f"  report's own short/long rest record: {compact(rp, 200)}")
    for side, name in (("home", home), ("away", away)):
        f = d(forms[side])
        nxt = [x for x in (f.get("next5_with_gaps") or []) if isinstance(x, dict)]
        here = [x for x in nxt if parse_day(x.get("date")) and parse_day(ko) and abs((parse_day(x.get("date")) - parse_day(ko)).days) <= 1]
        after = [x for x in nxt if x not in here][:2]
        rot = d(ins.get(f"{side}_rotation"))
        txt = "; ".join(f"{x.get('opponent')} on {str(x.get('date'))[:10]} ({x.get('days_since_previous')} days after the previous match)" for x in after) or "none listed"
        soon = [x for x in after[:1] if (num(x.get("days_since_previous")) or 99) <= 4]
        out.append(f"{name}: matches after this one (the first listed is the NEXT match): {txt}; changed {rot.get('changed_players', '?')} of {rot.get('starting_xi_size', 11)} starters between its last two matches (not today's XI)" + ("  <-- the next match comes within 4 days: rotation risk if it matters more" if soon else ""))
    out.append("Rotation logic: a manager benches or rests regulars when the NEXT match matters more than this one (a cup tie, a title or relegation decider, a knockout leg, a derby) especially with a short gap and a squad that has played heavy minutes, or when this match has little at stake (qualified, eliminated, a friendly). Judge from the report's stakes, the standings zone and the next fixtures above which match is the priority for EACH side; if you know a next fixture is crucial (labelled unverified), estimate how many starters change and which positions (usually the older, heavily used regulars and the goalkeeper only rarely), then discount that side's strength and say so. Never assume the full XI plays when rotation is plausible.")
    out.append("How to read it: short gaps, three matches in 7 days and the same regulars playing every minute lead to tired legs, rotation and a drop late in matches; a side with a bad short-rest record is exposed; a side underperforming its chances may be due a rebound, but a side underperforming for a reason (poor finishers, an unfit striker) is not. Compare both sides' rest before this match and say who has the fresher legs.")
    return out


def depth_profile(prof: dict) -> dict:
    """Regulars (the 11 with most recent minutes) against the next 7: how much quality is lost if the manager rotates."""
    rows = []
    for p in (prof.get("squad") or []):
        if not isinstance(p, dict) or p.get("role") == "G":
            continue
        u = d(p.get("recent_usage"))
        mins = num(u.get("total_minutes"))
        if mins:
            rows.append((mins, num(p.get("market_value")), num(u.get("avg_rating")), p.get("name")))
    rows.sort(key=lambda t: -t[0])
    reg, res = rows[:10], rows[10:17]
    avg = lambda xs: None if not [x for x in xs if x is not None] else sum(x for x in xs if x is not None) / len([x for x in xs if x is not None])
    return {"n_reg": len(reg), "n_res": len(res), "val_reg": avg([r[1] for r in reg]), "val_res": avg([r[1] for r in res]), "rt_reg": avg([r[2] for r in reg]), "rt_res": avg([r[2] for r in res]), "reserves": [r[3] for r in res]}


def key_players(prof: dict, k: int = 5) -> list[str]:
    """Players a manager rarely rests: the ones who make the difference (high rating, xG+xA per 90, tackles+interceptions for defenders)."""
    rows = []
    out_names = {norm_name(x.get("name")) for x in (prof.get("injuries") or []) if isinstance(x, dict)}
    for p in (prof.get("squad") or []):
        if not isinstance(p, dict) or norm_name(p.get("name")) in out_names:
            continue                                                  # an absent player is not a key player for this match
        u = d(p.get("recent_usage"))
        mins, rt = num(u.get("total_minutes")), num(u.get("avg_rating"))
        if not mins or mins < 180:
            continue
        role = p.get("role")
        if role in ("F", "M"):
            imp = p90((num(u.get("total_xg")) or 0) + (num(u.get("total_xa")) or 0), mins)
            tag = f"xG+xA {imp:.2f}/90"
            val = 4 * (imp or 0)
        elif role == "D":
            imp = p90((num(u.get("total_tackles")) or 0) + (num(u.get("total_interceptions")) or 0), mins)
            tag = f"tackles+interceptions {imp:.1f}/90"
            val = (imp or 0) / 4
        else:
            tag, val = "first-choice goalkeeper", 0.5
        if rt is not None and rt < 6.6:
            continue                      # a player in weak form is not one the manager must keep
        score = (rt or 6.5) - 6.5 + val
        rows.append((score, f"{p.get('name')} ({role}, rating {rt if rt is not None else 'n/a'}, {tag})"))
    rows.sort(key=lambda t: -t[0])
    return [t for _, t in rows[:k]]


def depth_lines(profiles: dict, home, away) -> list[str]:
    out = []
    for side, name in (("home", home), ("away", away)):
        dp = depth_profile(d(profiles.get(side)))
        if not dp["n_res"]:
            out.append(f"{name}: not enough squad data to compare the regulars with the reserves")
            continue
        vr = f", market value per player {dp['val_reg'] / 1e6:.1f}m regulars against {dp['val_res'] / 1e6:.1f}m reserves (reserves are worth {100 * dp['val_res'] / dp['val_reg']:.0f}% of the regulars)" if dp["val_reg"] and dp["val_res"] else ""
        rt = f", rating {dp['rt_reg']:.2f} regulars against {dp['rt_res']:.2f} reserves" if dp["rt_reg"] and dp["rt_res"] else ""
        out.append(f"{name}: players who make the difference and are rarely rested: " + ("; ".join(key_players(d(profiles.get(side)))) or "none identified"))
        out.append(f"{name}: depth if the manager rotates (the 10 outfield regulars against the next {dp['n_res']} by minutes){vr}{rt}")
    return out


def complacency_section(m: dict, ins: dict, forms: dict, home, away, profiles: dict) -> list[str]:
    """Upset risk: the bigger side can underestimate the smaller one. Shows the quality gap and the factors that make a favourite careless."""
    out = ["", "# BIG TEAM v SMALL TEAM: COMPLACENCY AND UPSET RISK (the favourite often plays below its level against a side it expects to beat)"]
    eh, ea = class_elo(ins, "home"), class_elo(ins, "away")      # class: ClubElo or eloratings.net, never a form-only Elo
    if eh is None or ea is None:
        out.append("Elo gap: not available; judge the gap from squad value, ratings and results")
        return out + ["How to read it: see the rule in the skill (complacency lens)."]
    gap = eh - ea
    fav, dog, fside, dside = (home, away, "home", "away") if gap >= 0 else (away, home, "away", "home")
    out.append(f"Elo: {home} {eh:.0f}, {away} {ea:.0f}; gap {abs(gap):.0f} in favour of {fav} ({'big gap: complacency risk' if abs(gap) >= 200 else 'moderate gap' if abs(gap) >= 100 else 'small gap: no favourite effect'})")
    risks = []
    ff, df = d(forms[fside]), d(forms[dside])
    fr = d(ins.get(f"{fside}_rotation"))
    if (num(fr.get("changed_players")) or 0) >= 4:
        risks.append(f"{fav} changed {int(num(fr.get('changed_players')))} starters between its last two matches (not today's XI): it rotates, check today's lineup")
    nxt = [x for x in (ff.get("next5_with_gaps") or []) if isinstance(x, dict)][1:2]
    if nxt and (num(nxt[0].get("days_since_previous")) or 99) <= 4:
        risks.append(f"{fav}'s next match ({nxt[0].get('opponent')}) follows within {nxt[0].get('days_since_previous')} days: eyes on it")
    if (num(ff.get("matches_last7_days")) or 0) >= 2:
        risks.append(f"{fav} played {ff.get('matches_last7_days')} matches in the last 7 days")
    sh = parse_shape(m.get(f"{dside}_formation"))
    if sh and sh[0] >= 5:
        risks.append(f"{dog} lines up with a back five (a low block: harder to break down, dangerous on the counter)")
    xs = gap_profile(ff.get("last10_overall"), m.get("kickoff_utc"))
    if xs["xg_n"] and xs["gf_vs_xg"] is not None and xs["gf_vs_xg"] <= -0.4:
        risks.append(f"{fav} finishes below its chances ({xs['gf_vs_xg']:+.2f} goals a game against xG): chances without goals keeps a small side alive")
    if d(ins.get(f"{dside}_standings_zone")).get("in_the_mix"):
        risks.append(f"{dog} has something to play for (standings zone {d(ins.get(f'{dside}_standings_zone')).get('zone')})")
    out.append("Factors that raise the upset risk: " + ("; ".join(risks) if risks else "none visible in the data"))
    out += depth_lines(profiles, home, away)
    out.append("Rotation against a weak opponent: a manager facing a side he expects to beat often rests regulars and gives reserves a game, so the XI that starts is weaker than the one the season numbers describe (the reserves have fewer minutes together, lower ratings, lower market value). Managers rarely rest the players who make the difference (the key players listed above: high rating, good xG and xA, a defender who wins the ball, the goalkeeper), so rotation falls first on the lower-impact regulars and the older, heavily used ones: estimate how many are rested (more if this match is the 'easy' one between harder fixtures, or the gap to the next match is short), keep the key players in the XI unless injured or suspended, apply the depth drop above only to the positions likely to change, and cut the favourite's goals and win chance by that, not by the full-strength numbers. Do it for both sides: a weak side usually plays its best XI.")
    out.append("How to read it: big teams underestimate small and weak teams: slow starts, rotation, low intensity, over-possession without penetration, and the small side's low block, set pieces and counters keep it in the game and raise the draw and the upset chance. Weigh it from the factors above and from the favourite's own record against weaker sides (how many of its recent wins against weak opposition were narrow or late, how many draws). It lowers the favourite's win probability and raises the draw; it does not turn the underdog into the favourite. Do the symmetric check: is the underdog's low block and counter actually backed by numbers (xG against, set-piece xG, big chances on the break)?")
    return out


DOUBTFUL = re.compile(r"day.?to.?day|doubt|questionable|knock|discomfort|fitness test|late test|minor", re.I)


def doubtful_tag(*texts) -> str:
    """'' or a warning when an absence reads as a short-term knock: such a player often plays (Manzambi, 'Physical Discomfort
    (dayToDay)' with a return date of 1 Nov from another source, started and played Villa 2-1 City on 2026-10-24)."""
    hit = next((str(t) for t in texts if t and DOUBTFUL.search(str(t))), None)
    return "" if not hit else f"; DOUBTFUL ({hit}): a short-term knock, he may well play; do not price him as out (at most half his absence) and check the confirmed XI"


def replacement_lines(prof: dict, name_side: str, extra_missing=None) -> list[str]:
    """For each absent player: how important he is and who would most likely replace him (same position, healthy), and whether that is a weak replacement."""
    squad = [p for p in (prof.get("squad") or []) if isinstance(p, dict)]
    absent = [x for x in (prof.get("injuries") or []) if isinstance(x, dict) and x.get("name")]
    for x in (extra_missing or []):
        if isinstance(x, dict) and x.get("name") and not any(norm_name(a.get("name")) == norm_name(x.get("name")) for a in absent):
            absent.append({"name": x["name"], "injury": x.get("description") or x.get("absence_type")})
    if not absent:
        return [f"{name_side}: no absentees listed"]
    names_out = {norm_name(a.get("name")) for a in absent}
    by_name = {norm_name(p.get("name")): p for p in squad}
    mins_rank = sorted((num(d(p.get("recent_usage")).get("total_minutes")) or 0 for p in squad), reverse=True)
    out = []
    for a in absent[:8]:
        p = by_name.get(norm_name(a.get("name")), {})
        u = d(p.get("recent_usage"))
        role, mins, rt, val = p.get("role") or a.get("role"), num(u.get("total_minutes")), num(u.get("avg_rating")), num(p.get("market_value"))
        starts = u.get("starts")
        if not p:
            out.append(f"  {name_side}: {a.get('name')} ({a.get('injury')}) is not in the squad data: role, importance and replacement unknown; judge from your own knowledge (unverified)")
            continue
        regular = bool(mins) and mins >= (mins_rank[13] if len(mins_rank) > 13 else 0) and (num(starts) or 0) >= 2
        cands = [q for q in squad if q.get("role") == role and norm_name(q.get("name")) not in names_out and num(d(q.get("recent_usage")).get("total_minutes"))]
        cands.sort(key=lambda q: -(num(d(q.get("recent_usage")).get("total_minutes")) or 0))
        head = f"  {name_side}: {a.get('name')} ({role}, {a.get('injury')}; {int(mins or 0)} min, starts {starts}, rating {rt if rt is not None else 'n/a'}, value {f'{val / 1e6:.1f}m' if val else 'n/a'}; {'a REGULAR' if regular else 'a fringe player'}{doubtful_tag(a.get('injury'))})"
        if not regular:
            out.append(head + ": little lost, the replacement is the existing squad")
            continue
        if not cands:
            out.append(head + ": no healthy same-position player with minutes in the data: a WEAK or unknown replacement (check the bench)")
            continue
        r1 = cands[0]
        ur = d(r1.get("recent_usage"))
        rr, rv = num(ur.get("avg_rating")), num(r1.get("market_value"))
        weak = (rt is not None and rr is not None and rr < rt - 0.3) or (val and rv and rv < 0.5 * val)
        strong = rr is not None and rt is not None and rr >= rt - 0.1 and (not (val and rv) or rv >= 0.8 * val)
        verdict = "WEAK replacement" if weak else "comparable replacement" if strong else "uncertain replacement"
        wide_then, wide_now = num(u.get("wide_back_starts")) or 0, num(d(r1.get("recent_usage")).get("wide_back_starts")) or 0
        func = "" if role != "D" or wide_then == wide_now or (wide_then and wide_now) else (" - DIFFERENT FUNCTION: the absent defender played wide and the stand-in has not" if wide_then and not wide_now else " - DIFFERENT FUNCTION: the absent defender played centrally and the stand-in is a wide defender")
        out.append(head + f"; likely replacement {r1.get('name')} (age {r1.get('age')}, {int(num(ur.get('total_minutes')) or 0)} min, rating {rr if rr is not None else 'n/a'}, value {f'{rv / 1e6:.1f}m' if rv else 'n/a'}) => {verdict}" + (f"; next option {cands[1].get('name')}" if len(cands) > 1 else "") + func)
    return out


def same_player(a, b) -> bool:
    """Two spellings of one name (accents, hyphens, a dropped middle name: 'Marc-Andre Ter Stegen' v 'Marc ter Stegen') are one player: same last word and same first initial."""
    ta = [norm(t) for t in re.split(r"[\s-]+", str(a or "").strip()) if norm(t)]
    tb = [norm(t) for t in re.split(r"[\s-]+", str(b or "").strip()) if norm(t)]
    return bool(ta and tb) and (norm_name(a) == norm_name(b) or (ta[-1] == tb[-1] and ta[0][0] == tb[0][0]))


def keeper_line(prof: dict, lineup: list, name: str) -> str:
    """Is the first-choice goalkeeper (most recent minutes) playing? A change of keeper is a goalkeeper-specific impact the team figures hide."""
    keepers = [(num(d(p.get("recent_usage")).get("total_minutes")) or 0, num(d(p.get("recent_usage")).get("avg_rating")), p) for p in (prof.get("squad") or []) if isinstance(p, dict) and p.get("role") == "G"]
    keepers.sort(key=lambda t: -t[0])
    if not keepers or keepers[0][0] <= 0:
        return f"{name}: no goalkeeper minutes in the data"
    first = keepers[0]
    out_names = {norm_name(x.get("name")) for x in (prof.get("injuries") or []) if isinstance(x, dict)}
    starter = next((p for p in lineup if isinstance(p, dict) and p.get("position") == "G" and not p.get("substitute")), None)
    first_out = norm_name(first[2].get("name")) in out_names
    changed = starter is not None and not same_player(starter.get("name"), first[2].get("name"))
    if not (first_out or changed):
        return f"{name}: first-choice keeper {first[2].get('name')} (rating {fmt(first[1], 2)}, {first[0]:.0f} min) is available"
    other = next((k for k in keepers[1:] if norm_name(k[2].get("name")) not in out_names), None)
    sub_name = starter.get("name") if starter else (other[2].get("name") if other else "unknown")
    sub_r = next((k[1] for k in keepers if norm_name(k[2].get("name")) == norm_name(sub_name)), None)
    return f"{name}: KEEPER CHANGE - first-choice {first[2].get('name')} (rating {fmt(first[1], 2)}, {first[0]:.0f} min) is {'out' if first_out else 'not in the predicted XI'}; replacement {sub_name} (rating {fmt(sub_r, 2)}); the team's save rate and xG against were built with the first choice, so adjust them"


def depth_by_position(prof: dict, name: str) -> str:
    """Quality of the regulars against the next men up, per position: the cover behind each line, not just whether a player is missing."""
    absent = {norm_name(x.get("name")) for x in (prof.get("injuries") or []) if isinstance(x, dict)}
    parts = []
    for role, label, k in (("D", "defence", 4), ("M", "midfield", 3), ("F", "attack", 2), ("G", "goalkeeper", 1)):
        rows = sorted(((num(d(p.get("recent_usage")).get("total_minutes")) or 0, num(d(p.get("recent_usage")).get("avg_rating")), num(p.get("market_value"))) for p in (prof.get("squad") or [])
                       if isinstance(p, dict) and p.get("role") == role and norm_name(p.get("name")) not in absent and num(d(p.get("recent_usage")).get("total_minutes"))), key=lambda t: -t[0])
        reg, res = rows[:k], rows[k:k + 2]
        if not reg or not res:
            parts.append(f"{label} cover thin or unknown ({len(rows)} fit with minutes)")
            continue
        avg = lambda xs: None if not [x for x in xs if x is not None] else sum(x for x in xs if x is not None) / len([x for x in xs if x is not None])
        rr, sr = avg([r[1] for r in reg]), avg([r[1] for r in res])
        parts.append(f"{label}: regulars {fmt(rr, 2)} v cover {fmt(sr, 2)} rating" + ("" if rr is None or sr is None else " (cover is a drop of %.2f)" % (rr - sr) if rr - sr >= 0.3 else " (cover is comparable)"))
    return f"{name}: depth by position - " + "; ".join(parts)


def replacement_section(m: dict, profiles: dict, home, away) -> list[str]:
    out = ["", "# ABSENCES AND REPLACEMENTS (for each missing player: who steps in, and is he a weak replacement?)"]
    out.append(depth_by_position(d(profiles.get("home")), home))
    out.append(depth_by_position(d(profiles.get("away")), away))
    out.append(keeper_line(d(profiles.get("home")), m.get("home_lineup") or [], home))
    out.append(keeper_line(d(profiles.get("away")), m.get("away_lineup") or [], away))
    out += replacement_lines(d(profiles.get("home")), home, m.get("home_missing_players"))
    out += replacement_lines(d(profiles.get("away")), away, m.get("away_missing_players"))
    out.append("How to read it: a missing regular matters only as far as his replacement is worse: a comparable replacement (similar rating and value, regular minutes) means little lost; a weak or unproven one means a real hole, especially for the goalkeeper, a ball-winning defender or the main scorer. Each side's advocate must argue this both ways: what is lost without him, who steps in, and whether the team's pattern (shape, set pieces, the key link) survives the change. Treat unknown roles and replacements as unknown, not as a weakness.")
    return out


def manager_section(r: dict, m: dict, ins: dict, forms: dict, home, away, profiles: dict) -> list[str]:
    """What a manager checks before a match, one block per side, from the report's own data (proxies are named as proxies)."""
    out = ["", "# MANAGER'S PRE-MATCH CHECKLIST (fitness and sharpness, form, system fit, morale, availability and rotation, opponent, importance, bench; do both sides)"]
    ids = {s: team_identity(r, m, ins, s) for s in ("home", "away")}
    names = {"home": home, "away": away}
    for side in ("home", "away"):
        name, other = names[side], names["away" if side == "home" else "home"]
        prof, f = d(profiles.get(side)), d(forms.get(side))
        lineup = [p for p in (m.get(f"{side}_lineup") or []) if isinstance(p, dict) and not p.get("substitute")]
        bench = [p for p in (m.get(f"{side}_lineup") or []) if isinstance(p, dict) and p.get("substitute")]
        squad = [p for p in (prof.get("squad") or []) if isinstance(p, dict)]
        by_name = {norm_name(p.get("name")): p for p in squad}
        use = lambda p: d(d(by_name.get(norm_name(p.get("name")))).get("recent_usage"))
        out.append(f"\n## {name}")
        low = [f"{p.get('name')} {int(num(use(p).get('total_minutes')) or 0)} min" for p in lineup if use(p) and (num(use(p).get("total_minutes")) or 0) < 150]
        heavy = [f"{p.get('name')} {int(num(use(p).get('total_minutes')))} min" for p in lineup if (num(use(p).get("total_minutes")) or 0) >= 270]
        out.append(f"1 fitness and sharpness: predicted starters with little recent football (under 150 min in the window, rusty or just back): {', '.join(low) or 'none'}; starters carrying a heavy load (270+ min): {', '.join(heavy) or 'none'}; matches in the last 7 days {f.get('matches_last7_days', '?')}")
        rated = sorted(((num(use(p).get("avg_rating")), p.get("name")) for p in lineup if num(use(p).get("avg_rating")) is not None and (num(use(p).get("total_minutes")) or 0) >= 90), key=lambda t: (t[0], str(t[1])))
        out.append("2 in form / struggling (average rating, predicted XI): in form " + (", ".join(f"{n} {v:.2f}" for v, n in rated[::-1][:3] if v >= 7.0) or "none above 7.0") + "; struggling " + (", ".join(f"{n} {v:.2f}" for v, n in rated[:3] if v < 6.6) or "none under 6.6"))
        shape = parse_shape(m.get(f"{side}_formation"))
        cnt = {k: sum(1 for p in lineup if p.get("position") == k) for k in "GDMF"}
        if shape and lineup:
            wide = sum(1 for p in lineup if p.get("position") == "D" and (num(use(p).get("wide_back_starts")) or 0) >= 1)
            out.append(f"3 lineup fits the system: formation {m.get(f'{side}_formation')} needs D{shape[0]} M{shape[1]} F{shape[2]}; the predicted XI has D{cnt['D']} M{cnt['M']} F{cnt['F']} -> " + ("fits" if (cnt['D'], cnt['M'], cnt['F']) == shape[:3] else "MISMATCH on the report's position labels (wingers are often labelled midfielders, so check the names)") + f"; defenders who have started wide before: {wide}")
        else:
            out.append(f"3 lineup fits the system: formation {m.get(f'{side}_formation') or 'n/a'}, lineup {'listed' if lineup else 'not listed'} (unknown, judge from the squad)")
        vals = sorted(((num(p.get("market_value")) or 0, p) for p in squad if p.get("role") != "G"), key=lambda t: -t[0])[:6]
        mx = max([num(d(p.get("recent_usage")).get("total_minutes")) or 0 for p in squad] or [0])
        frozen = [p.get("name") for v, p in vals if mx and (num(d(p.get("recent_usage")).get("total_minutes")) or 0) < 0.35 * mx]
        mg = d(m.get(f"{side}_manager"))
        st = d(f.get("current_streak"))
        out.append(f"4 morale and confidence (PROXIES only: the report has no dressing-room data): streak {st.get('count', '?')}{st.get('result', '')}; last 5 {window_line(f.get('last5_overall')).split(' (')[0]}; high-value players with little football (possibly frozen out or unhappy): {', '.join(map(str, frozen)) or 'none'}; manager {'NEW appointment' if mg.get('recent_appointment') else 'settled'}{(', in charge ' + str((parse_day(m.get('kickoff_utc')) - parse_day(mg.get('appointed_date'))).days) + ' days (the system has had that long to bed in)') if parse_day(m.get('kickoff_utc')) and parse_day(mg.get('appointed_date')) else ''}; recent transfers {compact(prof.get('recent_transfers'), 120) if prof.get('recent_transfers') else 'none listed'}")
        absent = [x.get("name") for x in (prof.get("injuries") or []) if isinstance(x, dict)] or [x.get("name") for x in (m.get(f"{side}_missing_players") or []) if isinstance(x, dict)]
        rot = d(ins.get(f"{side}_rotation"))
        out.append(f"5 injuries, suspensions, rotation: {len(absent)} absent (see ABSENCES AND REPLACEMENTS); changed {rot.get('changed_players', '?')} starters between its last two matches, not today's XI (see the GAPS BETWEEN MATCHES section for the rotation logic)")
        out.append(f"6 opponent ({other}): likely setup {m.get('away_formation' if side == 'home' else 'home_formation') or 'n/a'}; its style, key players and weak areas are in the tactical note and the SCOUTING REPORT for {other}")
        z = d(ins.get(f"{side}_standings_zone"))
        nxt = [x for x in (f.get("next5_with_gaps") or []) if isinstance(x, dict)][1:2]
        out.append(f"7 importance: standing {z.get('position', '?')}/{z.get('total_teams', '?')} ({z.get('zone', 'n/a')}, {z.get('points_from_boundary', '?')} pts from the boundary); next match {(nxt[0].get('opponent') + ' in ' + str(nxt[0].get('days_since_previous')) + ' days') if nxt else 'not listed'}")
        dp = depth_profile(prof)
        bench_pos = {k: sum(1 for p in bench if p.get("position") == k) for k in "GDMF"}
        healthy = {k: sum(1 for p in squad if p.get("role") == k and norm_name(p.get("name")) not in {norm_name(a) for a in absent}) for k in "GDMF"}
        out.append(f"8 bench and flexibility: bench listed D{bench_pos['D']} M{bench_pos['M']} F{bench_pos['F']}" + ("" if bench else " (not listed)") + f"; healthy squad D{healthy['D']} M{healthy['M']} F{healthy['F']} (a back-three/back-four switch needs 5+ defenders, an extra striker 3+ forwards); reserves worth {(format(100 * dp['val_res'] / dp['val_reg'], '.0f') + '%') if dp['val_reg'] and dp['val_res'] else 'n/a'} of the regulars in market value")
    out.append("How to read it: for each side say who is rusty, who is flying, whether the XI fits the shape, any morale warning, who is missing, how the opponent will set up, how much the match matters, and whether the bench can change the game; mark every proxy as a proxy.")
    return out


def adjust_section(r: dict, m: dict, ins: dict, forms: dict, home, away, profiles: dict) -> list[str]:
    """Gap analysis (current state, target state, gap, root cause, fix), the tactical adjustments a manager can make and what triggers them, and rotation: both sides, from the data."""
    out = ["", "# TACTICAL ADJUSTMENTS, GAP ANALYSIS AND ROTATION (rule-based prompts from the data, not predictions: confirm or reject each with the evidence)"]
    ids = {s_: team_identity(r, m, ins, s_) for s_ in ("home", "away")}
    names = {"home": home, "away": away}
    eh, ea = class_elo(ins, "home"), class_elo(ins, "away")      # class: ClubElo or eloratings.net, never a form-only Elo
    for side in ("home", "away"):
        oside = "away" if side == "home" else "home"
        name, other = names[side], names[oside]
        me, op = ids[side], ids[oside]
        prof, oprof, f = d(profiles.get(side)), d(profiles.get(oside)), d(forms.get(side))
        shape, oshape = parse_shape(m.get(f"{side}_formation")), parse_shape(m.get(f"{oside}_formation"))
        gap_elo = None if eh is None or ea is None else (eh - ea if side == "home" else ea - eh)
        ad = d(ins.get(f"{side}_advanced_stats"))
        n = num(ad.get("sample_size"))
        ti = None if per(ad.get("team_tackles_for"), n) is None or per(ad.get("team_interceptions_for"), n) is None else per(ad.get("team_tackles_for"), n) + per(ad.get("team_interceptions_for"), n)
        rec = me.get("recoveries")
        press = "n/a" if ti is None else ("high activity" if ti >= 20 else "low activity" if ti <= 13 else "moderate activity")
        out.append(f"\n## {name}")
        out.append(f"CURRENT STATE: build-up {me.get('passing_label', 'n/a')} (pass accuracy {fmt(me.get('pass_acc'))}%, long balls {fmt(me.get('long_ball'))}%); pressing PROXY (no pressing data in the report) {press} (tackles+interceptions {fmt(ti)} and recoveries {fmt(rec)} a game); chance creation {me.get('attack_label', 'n/a')} ({fmt(me.get('xg_for'))} xG, {fmt(me.get('shots_in_box_for'))} shots in the box a game; shot quality {fmt(me.get('xg_per_shot'), 2)} xG per shot created, {fmt(me.get('xg_per_shot_ag'), 2)} conceded); defending transitions {me.get('defence_label', 'n/a')} ({fmt(me.get('xg_against'))} xG and {fmt(me.get('shots_against'))} shots against a game); midfield {me.get('midfield_label', 'n/a')}")
        low_block = bool(oshape and oshape[0] >= 5) or op.get("identity") == "defence-first"
        if gap_elo is not None and gap_elo <= -100:
            tgt, tkey = "the weaker side: stay compact, win set pieces and counters, avoid being stretched", "weaker"
        elif low_block:
            tgt, tkey = f"break a low block: more box touches, crosses and set pieces against {other}'s deep line, with patient circulation", "lowblock"
        elif "possession" in str(op.get("passing_label")):
            tgt, tkey = f"progress under {other}'s possession game and protect the transition behind the ball", "possession"
        elif "direct" in str(op.get("passing_label")):
            tgt, tkey = f"control the midfield and keep a rest defence against {other}'s direct play", "direct"
        else:
            tgt, tkey = "control the midfield and create more xG than it concedes", "balanced"
        out.append(f"TARGET STATE: {tgt}")
        gaps = []
        if tkey in ("lowblock", "balanced") and (me.get("xg_for") or 9) < 1.2:
            gaps.append(f"creates only {fmt(me.get('xg_for'))} xG and {fmt(me.get('box_touches_for'))} box touches a game")
        if tkey == "possession" and (me.get("pass_acc") or 99) < 80:
            gaps.append(f"pass accuracy {fmt(me.get('pass_acc'))}% is low for playing out under pressure")
        if "loses the middle" in str(me.get("midfield_label")):
            gaps.append("loses the midfield battle")
        if (me.get("xg_against") or 0) >= 1.5 or (me.get("shots_against") or 0) >= 14:
            gaps.append(f"concedes {fmt(me.get('xg_against'))} xG and {fmt(me.get('shots_against'))} shots a game, so transitions are exposed")
        if tkey == "weaker":
            gaps.append(f"Elo {abs(gap_elo):.0f} points below {other}")
        out.append("GAP: " + ("; ".join(gaps) or "no clear gap on these indicators"))
        squad = [p for p in (prof.get("squad") or []) if isinstance(p, dict)]
        absent = {norm_name(x.get("name")) for x in (prof.get("injuries") or []) if isinstance(x, dict)}
        wide_d = sum(1 for p in squad if p.get("role") == "D" and norm_name(p.get("name")) not in absent and (num(d(p.get("recent_usage")).get("wide_back_starts")) or 0) >= 1)
        lineup = [p for p in (m.get(f"{side}_lineup") or []) if isinstance(p, dict) and not p.get("substitute")]
        heavy = sum(1 for p in lineup if (num(d(next((q.get("recent_usage") for q in squad if norm_name(q.get("name")) == norm_name(p.get("name"))), None)).get("total_minutes")) or 0) >= 270)
        causes = []
        if wide_d < 2:
            causes.append(f"too few natural full-backs ({wide_d} healthy defenders have started wide)")
        if (num(f.get("matches_last7_days")) or 0) >= 2 or heavy >= 3:
            causes.append(f"fatigue ({f.get('matches_last7_days', '?')} matches in 7 days, {heavy} starters on 270+ minutes)")
        if shape and lineup and (sum(1 for p in lineup if p.get("position") == "D"), sum(1 for p in lineup if p.get("position") == "M"), sum(1 for p in lineup if p.get("position") == "F")) != shape[:3]:
            causes.append("lineup does not match the formation by position labels (player fit or spacing)")
        gone = [x.get("name") for x in (prof.get("injuries") or []) if isinstance(x, dict)][:3]
        if gone:
            causes.append(f"missing players ({', '.join(map(str, gone))})")
        weak = [p.get("name") for p in squad if (num(d(p.get("recent_usage")).get("avg_rating")) or 9) < 6.6 and (num(d(p.get("recent_usage")).get("total_minutes")) or 0) >= 180][:3]
        if weak:
            causes.append(f"players in poor form ({', '.join(map(str, weak))})")
        out.append("ROOT CAUSE candidates: " + ("; ".join(causes) or "none visible in the data (judge from the matchup)"))
        # tactical adjustments and their triggers
        fatigued = (num(f.get("matches_last7_days")) or 0) >= 2
        temp = num(d(m.get("weather_detail")).get("temp_c"))
        hot = temp is not None and temp >= 27
        z = d(ins.get(f"{side}_standings_zone"))
        must = bool(z.get("in_the_mix")) and str(z.get("zone")) in ("relegation-zone", "top-of-table", "promotion", "title")
        key_opp = key_players(oprof, 1)
        aer = num(d(ins.get(f"{side}_set_piece_threat")).get("opponent_aerial_win_pct"))
        adj = []
        adj.append("formation: " + ((f"from {m.get(f'{side}_formation')} add a second forward or a more attacking line-up to occupy the back five" if shape and shape[2] <= 1 else "keep the front line and work the width") if low_block else (f"from {m.get(f'{side}_formation')} go to a five-man midfield or an extra holder" if tkey in ("possession", "weaker") else "no change expected")) + (" (and a back three if full-backs are short)" if wide_d < 2 else ""))
        adj.append("pressing intensity: " + ("press lower and save legs" if fatigued or hot else "press high" if (gap_elo or 0) >= 100 and ti is not None and ti >= 18 else "sit deeper" if tkey in ("weaker", "possession") else "mid-block, press on triggers"))
        adj.append("defensive line: " + ("drop the line to protect space behind" if tkey in ("weaker", "direct") or (me.get("xg_against") or 0) >= 1.5 else "push up to compress the game" if tkey == "lowblock" else "normal height"))
        adj.append("midfield balance: " + ("add an extra holding midfielder" if tkey in ("possession", "weaker", "direct") or "loses the middle" in str(me.get("midfield_label")) else "keep the shape and add a runner for the second balls"))
        adj.append("attacking width: " + ("wingers wide and full-backs high to stretch the five" if low_block else "wingers narrower to crowd the middle" if tkey in ("possession", "weaker") else "keep natural width"))
        adj.append("build-up: " + ("play through midfield, patient circulation" if low_block or tkey == "balanced" else "go more direct to bypass the press" if tkey == "possession" else "play on the counter, direct to the forwards"))
        adj.append("marking plan: " + (f"target {other}'s key player ({key_opp[0].split(' (')[0]})" if key_opp else "no key opposing player identified"))
        adj.append("set pieces: " + (f"attack corners and free kicks, since {other} win only {aer:.0f}% of aerial duels" if aer is not None and aer < 48 else "use short routines and defend the box, since the opponent is strong in the air" if aer is not None and aer >= 54 else "standard routines"))
        out.append("ADJUSTMENTS: " + "; ".join(adj))
        trig = [f"opponent formation {m.get(f'{oside}_formation') or 'n/a'} and style {op.get('passing_label', 'n/a')}", f"{len(gone)} missing", ("weaker" if tkey == "weaker" else "stronger" if (gap_elo or 0) >= 100 else "evenly matched"), f"fatigue {'yes' if fatigued else 'no'}, heat {'yes' if hot else 'no'}, importance {'high' if must else 'normal'}"]
        out.append("TRIGGERS fired: " + "; ".join(trig) + "; game state (decide for each side): if trailing, add a forward and push the full-backs; if leading, add a holder, drop the line and slow the game")
        # rotation
        nxt = [x for x in (f.get("next5_with_gaps") or []) if isinstance(x, dict)][1:2]
        short = bool(nxt) and (num(nxt[0].get("days_since_previous")) or 99) <= 4
        keep = key_players(prof, 3)
        out.append(f"ROTATION: {'LIKELY' if (fatigued or short) and (heavy >= 3 or short) else 'unlikely'} (fatigue {'yes' if fatigued else 'no'}, {heavy} starters on 270+ minutes, next match {'within 4 days' if short else 'not close'}); protect {', '.join(k.split(' (')[0] for k in keep) or 'the key players'}; rest the heavily used lower-impact starters first")
    out.append("How to read it: (1) gap analysis: write the current state, the target state, the gap, the root cause and the fix for each side in the Gap analysis table; (2) tactical adjustments: say which of formation, pressing, line height, midfield balance, width, build-up, marking and set pieces each manager changes and which trigger caused it (opponent formation and pressing style, injuries, stronger/weaker, leading/trailing, fatigue, weather, importance); (3) rotation means changing players in the XI to manage fatigue, fitness and match load, to keep the team fresh over a busy schedule or protect key players before a bigger match: decide who is rested and how much weaker the XI becomes.")
    return out


def scout_section(r: dict, m: dict, ins: dict, forms: dict, home, away, profiles: dict) -> list[str]:
    """A scouting report on each side as its opponent would write it: shape in and out of possession, how it builds up, creates and defends, key players, set pieces, pressing, line and transitions, weak areas."""
    out = ["", "# SCOUTING REPORT (each side as its opponent would study it; PROXIES are named, the report has no tracking or video data)"]
    ids = {s_: team_identity(r, m, ins, s_) for s_ in ("home", "away")}
    names = {"home": home, "away": away}
    for side in ("home", "away"):
        name = names[side]
        me, prof = ids[side], d(profiles.get(side))
        ad = d(ins.get(f"{side}_advanced_stats"))
        n = num(ad.get("sample_size"))
        shape_s = m.get(f"{side}_formation")
        shape = parse_shape(shape_s)
        poss = me.get("possession")
        in_shape = f"{shape_s or 'n/a'}" + (" with the full-backs/wing-backs high" if shape and shape[0] >= 4 and (poss or 0) >= 50 else "")
        out_shape = ("a deeper " + (f"{shape[0]}-{shape[1] + (1 if shape[2] > 1 else 0)}-{max(shape[2] - 1, 1)}" if shape and shape[2] > 1 else str(shape_s or "n/a")) + " block (inferred)") if (poss or 50) < 47 else f"{shape_s or 'n/a'} (a mid-block, inferred)"
        out.append(f"\n## {name}")
        out.append(f"1 shape: in possession {in_shape}; out of possession {out_shape}; possession {fmt(poss)}% and field tilt {fmt(me.get('tilt'))}%")
        out.append(f"2 build-up, creation and defending: {me.get('passing_label', 'n/a')}; {me.get('attack_label', 'n/a')}; {me.get('defence_label', 'n/a')} (numbers under CURRENT STATE below)")
        keys = key_players(prof, 3)
        out.append("3 key players and where they are dangerous: " + ("; ".join(keys) or "none identified") + " (position labels only: the report has no shot locations or heat maps)")
        spf, spa = ad.get("set_piece_xg_for"), ad.get("set_piece_xg_against")
        spt = d(ins.get(f"{side}_set_piece_threat"))
        out.append(f"4 set pieces: set-piece xG for {fmt(spf, 2)} and against {fmt(spa, 2)} over {fmt(n, 0)} games; corners {fmt(spt.get('corners_per_game'))} a game (corner goals for/against {ad.get('corner_goals_for')}/{ad.get('corner_goals_against')}); opponent wins {fmt(spt.get('opponent_aerial_win_pct'), 0)}% of aerial duels; the routines themselves (short, near-post, outswinger) are NOT in the data: say so or label your own knowledge")
        off = per(ad.get("offsides_for"), n)
        ti = None if per(ad.get("team_tackles_for"), n) is None or per(ad.get("team_interceptions_for"), n) is None else per(ad.get("team_tackles_for"), n) + per(ad.get("team_interceptions_for"), n)
        out.append(f"5 pressing, defensive line and transitions (proxies): pressing {'high' if ti is not None and ti >= 20 else 'low' if ti is not None and ti <= 13 else 'moderate'} (tackles+interceptions {fmt(ti)} and recoveries {fmt(me.get('recoveries'))} a game); line height {'high' if off is not None and off >= 2.5 else 'low' if off is not None and off <= 1.0 else 'medium'} (catches {fmt(off)} opponents offside a game); transitions: {fmt(me.get('shots_against'))} shots against a game and {fmt(me.get('xg_against'))} xG against")
        squad = [p for p in (prof.get("squad") or []) if isinstance(p, dict)]
        absent = {norm_name(x.get("name")) for x in (prof.get("injuries") or []) if isinstance(x, dict)}
        wide_d = sum(1 for p in squad if p.get("role") == "D" and norm_name(p.get("name")) not in absent and (num(d(p.get("recent_usage")).get("wide_back_starts")) or 0) >= 1)
        weak = []
        if wide_d < 2:
            weak.append(f"space behind the full-backs (only {wide_d} natural wide defenders fit)")
        ca = per(ad.get("crosses_against"), n)
        if ca is not None and ca >= 18:
            weak.append(f"concedes {ca:.0f} crosses a game (wide areas open)")
        spa_pg = per(spa, n)
        if spa_pg is not None and spa_pg >= 0.4:
            weak.append(f"concedes {spa_pg:.2f} xG a game from set pieces")
        err = num(ad.get("errors_lead_to_goal_against"))
        if (err or 0) >= 2:
            weak.append(f"{int(err)} errors led to goals against (vulnerable under pressure)")
        if me.get("pass_acc") is not None and me["pass_acc"] < 80:
            weak.append(f"pass accuracy {me['pass_acc']:.0f}% (loses the ball when pressed)")
        if me.get("sot_faced") is not None and me["sot_faced"] >= 4.5:
            weak.append(f"{me['sot_faced']:.1f} shots on target faced a game (a leaky defence)")
        if "loses the middle" in str(me.get("midfield_label")):
            weak.append("loses the midfield battle")
        out.append("6 weak areas to attack: " + ("; ".join(weak) or "none visible in the data"))
    out.append("How to read it: for each side say its shape in and out of possession, how it builds, creates and defends, who is dangerous and from where, what its set pieces threaten, how it presses, where its line sits and how it behaves in transition, and where it is weak (space behind full-backs, trouble under pressure); mark inferences and your own knowledge as such, then use it against the OTHER side in the symmetric table.")
    return out


def chaos_exposure(ins: dict, m: dict) -> dict:
    """The chaos advocate's exposure tally and closeness, as numbers (no text): how many of the comparable error/finishing/keeper factors point at
    each side, and the rating-anchor gap. chaos_section() calls this for its printed EXPOSURE TALLY line, so the sheet's tally and this function
    can never disagree on the same report. A 2026-10-25 retroactive check against Palace, Hull and Man Utd's real pre-match data found the tally's
    DIRECTION unreliable (it named the side that went on to benefit, not suffer, in 2 of 3 cases) -- not wired into any pick or stake decision, by
    design, kept only for the advocate's own prose and for backtesting. Returns {"exposed": {"home": int, "away": int}, "gap": float|None}."""
    def side_rate(side, block, key, n_key="sample_size"):
        b = d(ins.get(f"{side}_{block}"))
        n = num(b.get(n_key))
        v = num(b.get(key))
        return (v / n, int(n)) if n and v is not None else (None, 0)
    exposed = {"home": 0, "away": 0}
    for block, key in (("advanced_stats", "errors_lead_to_goal_against"), ("advanced_stats", "errors_lead_to_shot_against"),
                       ("big_chances_estimate", "big_chances_missed_for"), ("fouls_estimate", "fouls_committed_for"),
                       ("advanced_stats", "penalties_awarded_against")):
        vals = {sd: side_rate(sd, block, key) for sd in ("home", "away")}
        if all(v[0] is not None for v in vals.values()) and abs(vals["home"][0] - vals["away"][0]) > 1e-9:
            exposed[max(vals, key=lambda sd: vals[sd][0])] += 1
    keep = {sd: num(d(ins.get(f"{sd}_goalkeeping_estimate")).get("save_pct")) for sd in ("home", "away")}
    if all(v is not None for v in keep.values()) and abs(keep["home"] - keep["away"]) > 1e-9:
        exposed[min(keep, key=keep.get)] += 1
    ra = rating_anchor(ins, m)
    gap = abs(ra[0] - ra[1]) if ra else None
    return {"exposed": exposed, "gap": gap}


def chaos_section(m: dict, ins: dict, home, away) -> list[str]:
    """The chaos advocate's slice: what decides matches the forecast cannot see (errors that gift goals, a keeper's day, set pieces and penalties, cards),
    per side, so the advocate can say which side is more exposed and whether that widens the draw or the underdog. The MW8 misses of Oct 2026 (Villa 2-1 City,
    Palace 0-2 Newcastle, Hull 1-1 Brentford) were all decided this way while the side we favoured had the better or equal open-play chances. Descriptive
    only: none of it moves expected goals (the rating anchor moves only for team news)."""
    out = ["", "# CHAOS EVIDENCE (what the forecast cannot see: errors, keepers, set pieces and penalties, cards; per side, with its sample; never an expected-goals move)"]
    names = {"home": home, "away": away}
    exposed = {"home": 0, "away": 0}
    def side_rate(side, block, key, n_key="sample_size"):
        b = d(ins.get(f"{side}_{block}"))
        n = num(b.get(n_key))
        v = num(b.get(key))
        return (v / n, int(n)) if n and v is not None else (None, 0)
    rows = []
    for label, block, key, worse in (("errors leading to a goal against, a game", "advanced_stats", "errors_lead_to_goal_against", "high"),
                                     ("errors leading to a shot against, a game", "advanced_stats", "errors_lead_to_shot_against", "high"),
                                     ("big chances missed, a game (finishing that can go cold)", "big_chances_estimate", "big_chances_missed_for", "high"),
                                     ("fouls committed, a game (free kicks and penalties given away)", "fouls_estimate", "fouls_committed_for", "high"),
                                     ("penalties conceded, a game (a converted one is close to a certain goal)", "advanced_stats", "penalties_awarded_against", "high")):
        vals = {sd: side_rate(sd, block, key) for sd in ("home", "away")}
        if all(v[0] is None for v in vals.values()):
            continue
        txt = "; ".join(f"{names[sd]} {fmt(v[0])} (n={v[1]})" for sd, v in vals.items() if v[0] is not None)
        if all(v[0] is not None for v in vals.values()) and abs(vals["home"][0] - vals["away"][0]) > 1e-9:
            worst = max(vals, key=lambda sd: vals[sd][0])
            exposed[worst] += 1
            txt += f" -> {names[worst]} more exposed"
        rows.append(f"{label}: {txt}")
    keep = {sd: d(ins.get(f"{sd}_goalkeeping_estimate")) for sd in ("home", "away")}
    if any(num(k.get("save_pct")) is not None for k in keep.values()):
        bits = [f"{names[sd]} {fmt(num(k.get('save_pct')), 1)}% (n={int(num(k.get('sample_size')) or 0)})" for sd, k in keep.items() if num(k.get("save_pct")) is not None]
        line = "keeper save % (about 70% is normal; far below it can bounce back or keep leaking, far above it can run out): " + "; ".join(bits)
        sv = {sd: num(k.get("save_pct")) for sd, k in keep.items() if num(k.get("save_pct")) is not None}
        if len(sv) == 2 and abs(sv["home"] - sv["away"]) > 1e-9:
            low = min(sv, key=sv.get)
            exposed[low] += 1
            line += f" -> {names[low]} more exposed (the lower save rate)"
        rows.append(line)
    sp = {sd: d(ins.get(f"{sd}_advanced_stats")) for sd in ("home", "away")}
    spx = [f"{names[sd]} set-piece xG {fmt(per(b.get('set_piece_xg_for'), num(b.get('sample_size'))))} for / {fmt(per(b.get('set_piece_xg_against'), num(b.get('sample_size'))))} against a game"
           for sd, b in sp.items() if num(b.get("sample_size")) and b.get("set_piece_xg_for") is not None]
    if spx:
        rows.append("set pieces: " + "; ".join(spx))
    cards = {sd: d(ins.get(f"{sd}_card_discipline")) for sd in ("home", "away")}
    if any(cards.values()):
        rows.append("cards a game: " + "; ".join(f"{names[sd]} {fmt(num(c.get('yellow_per_game')))} yellow, {fmt(num(c.get('red_per_game')))} red" for sd, c in cards.items() if c))
    out += rows or ["no chaos evidence in the report"]
    tally = chaos_exposure(ins, m)                          # the authoritative count (also used by anything outside this slice): keeps the printed tally and chaos_exposure() from drifting apart
    out.append(f"EXPOSURE TALLY (factors where one side is worse, out of the comparable ones above): {home} {tally['exposed']['home']}, {away} {tally['exposed']['away']}")
    if tally["gap"] is not None:
        ra = rating_anchor(ins, m)
        out.append(f"how close the forecast is: rating-anchor expected goals {ra[0]:.2f}-{ra[1]:.2f}, gap {tally['gap']:.2f}" + (" (a close game: one error, save or penalty is more likely to decide it)" if tally["gap"] < 0.35 else " (a clear favourite: chaos must be large to overturn it)"))
    out.append("How to read it: these factors decided Villa 2-1 City, Palace 0-2 Newcastle and Hull 1-1 Brentford (Oct 2026) against the side with the better chances. They are rare and streaky, "
               "so they argue a route (a gift goal, a keeper's day, a set piece or penalty, a red card) and whether it widens the draw or the underdog; they never move expected goals.")
    return out


def player_errors_section(m: dict, profiles: dict, home, away, ins: dict | None = None) -> list[str]:
    """Who keeps making the error that gives a goal away: errors leading to an opponent's shot or goal per player over the recent matches with
    player statistics (squad[].recent_usage, Sofascore). Villa 2-1 City, 2026-10-24: the opener was reportedly the third goal in a row from a
    Guehi error, which the team totals (City 0.40 error-goals a game) could not show. Descriptive: it argues a route, it does not move expected goals."""
    out = ["", "# ERROR-PRONE PLAYERS (errors leading to an opponent's shot or goal, per player, recent matches with player statistics; a route for the other side, never an expected-goals move)"]
    for side, team in (("home", home), ("away", away)):
        rows, covered = [], 0
        for pl in d(profiles.get(side)).get("squad") or []:
            u = d(d(pl).get("recent_usage"))
            if not num(u.get("error_stat_appearances")):
                continue
            covered += 1
            g, sh, mins = int(num(u.get("total_errors_lead_to_goal")) or 0), int(num(u.get("total_errors_lead_to_shot")) or 0), num(u.get("total_minutes")) or 0
            if g >= 1 or sh >= 2:
                status = f", {pl.get('injury')}" if pl.get("injury") else ""
                rows.append((g, sh, f"{pl.get('name')} ({pl.get('role') or '?'}{status}): {g} leading to a goal, {sh} to a shot in {int(num(u.get('error_stat_appearances')))} appearances ({int(mins)} min)"))
        if not covered:
            out.append(f"{team}: not in the report (no player statistics with errors; an older report or another source)")
        elif not rows:
            team_g = num(d(d(ins).get(f"{side}_advanced_stats")).get("errors_lead_to_goal_against")) or 0
            out.append(f"{team}: no player with an error leading to a goal, or 2+ to a shot ({covered} players with statistics)"
                       + (f"; CHECK: the team totals show {int(team_g)} error(s) leading to a goal against, so the player figures look incomplete: do not read this as an error-free defence" if team_g else ""))
        else:
            out.append(f"{team}: " + "; ".join(t for _, _, t in sorted(rows, key=lambda x: (-x[0], -x[1]))[:4]))
    out.append("How to read it: a starter who gave away goals by error is a live route for the other side (press him, run at him), worth naming in the underdog and game-state cases; "
               "check he starts (CONFIRMED LINEUPS). Errors are rare and streaky: 1-3 over a few games is a lean, never a reason to move expected goals.")
    return out


def press_section(r: dict, m: dict, ins: dict, home, away) -> list[str]:
    """Where one side's press meets the other's short build-up: the route an early turnover goal comes from (Villa 2-1 City, 2026-10-24: Guehi lost it in his own half at 6')."""
    out = ["", "# PRESS v BUILD-UP (proxies: tackles+interceptions, pass accuracy, long-ball share, own errors; descriptive, no fixed bonus)"]
    names = {"home": home, "away": away}
    row = {}
    for s in ("home", "away"):
        me, ad = team_identity(r, m, ins, s), d(ins.get(f"{s}_advanced_stats"))
        n = num(ad.get("sample_size"))
        t, i = per(ad.get("team_tackles_for"), n), per(ad.get("team_interceptions_for"), n)
        row[s] = {"ti": None if t is None or i is None else t + i, "acc": me.get("pass_acc"), "long": me.get("long_ball"),
                  "err": per(ad.get("errors_lead_to_shot_against"), n), "disp": per(ad.get("dispossessed_for"), n)}
    found = False
    for p, b in (("home", "away"), ("away", "home")):
        P, B = row[p], row[b]
        press_hi = P["ti"] is not None and P["ti"] >= 24                  # unfitted bars: most top-flight sides build short, so only the extremes count
        short = B["long"] is not None and B["long"] <= 4.5 and (B["acc"] or 0) >= 87
        if not (press_hi and short):
            continue
        found = True
        prone = B["err"] is not None and B["err"] >= 0.5
        out.append(f"CLASH: {names[p]} presses high ({fmt(P['ti'])} tackles+interceptions a game) and {names[b]} builds short from the back (pass accuracy {fmt(B['acc'])}%, long balls {fmt(B['long'])}%); "
                   f"{names[b]}'s own errors lead to {fmt(B['err'])} shots against a game, dispossessed {fmt(B['disp'])} a game"
                   + (f" -> a turnover in {names[b]}'s half is a LIVE route for {names[p]} (an early goal against the run of play), even if {names[b]} has the better of the chances" if prone
                      else f" -> {names[b]} looks press-resistant on these numbers: the press costs {names[p]} legs more than it wins goals"))
    if not found:
        out.append("No clash: neither side combines a heavy press (24+ tackles+interceptions a game) with an opponent that builds very short (long balls 4.5% or less, pass accuracy 87%+).")
    out.append("How to read it: the press-v-build-up route widens the underdog's and the draw's tail (an early goal changes the game state) more than it moves the favourite's expected goals; say whether the builder's keeper and centre-backs are the ones who erred, and whether the presser's legs last (fatigue, a midweek game).")
    return out


def venue_style_section(m: dict, ins: dict, forms: dict, home, away) -> list[str]:
    """How home and away change a team's style: initiative, pressing, caution, transitions and running intensity, from the venue splits and the running totals."""
    out = ["", "# HOME v AWAY STYLE AND INTENSITY (home sides usually take the initiative and press higher; away sides are usually more cautious and compact: check whether that holds for THESE teams here)"]
    eh, ea = class_elo(ins, "home"), class_elo(ins, "away")      # class: ClubElo or eloratings.net, never a form-only Elo
    names = {"home": home, "away": away}
    for side in ("home", "away"):
        f = d(forms[side])
        dv = d(f.get("detailed_venue_split"))
        here, there = d(dv.get(side)), d(dv.get("away" if side == "home" else "home"))
        def row(x):
            k = num(x.get("sample_size"))
            if not k:
                return None
            g = lambda key: per(x.get(key), k)
            return {"n": int(k), "poss": num(x.get("possession_pct_avg")), "shots": g("shots_for"), "shots_ag": g("shots_against"), "xg": g("xg_for"), "xg_ag": g("xg_against"), "fouls": g("fouls_for"), "yel": g("yellow_cards_for")}
        a, b = row(here), row(there)
        lab = "home" if side == "home" else "away"
        oth = "away" if side == "home" else "home"
        fm = lambda r_: "no games" if r_ is None else f"{r_['n']} games: possession {fmt(r_['poss'], 0)}%, shots {fmt(r_['shots'])}-{fmt(r_['shots_ag'])}, xG {fmt(r_['xg'], 2)}-{fmt(r_['xg_ag'], 2)}, fouls {fmt(r_['fouls'])}, yellows {fmt(r_['yel'], 2)} a game"
        out.append(f"\n## {names[side]} (playing {lab} here)")
        out.append(f"as {lab} side: {fm(a)}; as {oth} side: {fm(b)}" + ("; swing: possession " + format((a['poss'] or 0) - (b['poss'] or 0), '+.0f') + " points, xG difference " + format(((a['xg'] or 0) - (a['xg_ag'] or 0)) - ((b['xg'] or 0) - (b['xg_ag'] or 0)), '+.2f') + " (thin samples: a tendency only)" if a and b and a['poss'] is not None and b['poss'] is not None else ""))
        ad = d(ins.get(f"{side}_advanced_stats"))
        n = num(ad.get("sample_size"))
        out.append(f"running (overall, not by venue): {fmt(per(ad.get('distance_covered_km_for'), n), 0)} km, {fmt(per(ad.get('sprints_for'), n), 0)} sprints a game v opponents {fmt(per(ad.get('distance_covered_km_against'), n), 0)} km, {fmt(per(ad.get('sprints_against'), n), 0)}; fouls and yellows are the venue proxy")
        strong = (eh is not None and ea is not None) and ((eh - ea >= 100) if side == "home" else (ea - eh >= 100))
        weak = (eh is not None and ea is not None) and ((ea - eh >= 100) if side == "home" else (eh - ea >= 100))
        z = d(ins.get(f"{side}_standings_zone"))
        must = bool(z.get("in_the_mix")) and str(z.get("zone")) in ("relegation-zone", "top-of-table", "promotion", "title")
        if side == "home":
            role = "default: takes the initiative, higher press, more possession" + ("; as the clearly stronger side expect territory and a high line" if strong else "; but as the clearly weaker side it may sit deeper and counter" if weak else "")
        else:
            role = "default: more cautious, compact, focused on transitions" + ("; but as the clearly stronger side it may take the initiative and run more at high intensity" if strong else "") + ("; needing a result (stakes) it may also press and chase the game" if must else "") + ("; as the weaker side expect a low block" if weak else "")
        out.append(f"expected role here: {role}; if it falls behind it tends to raise its tempo and intensity, if it leads it protects the lead")
    out.append("How to read it: location changes initiative, pressing and caution (the crowd, the familiar pitch, less travel) but game state, quality gap and stakes can reverse it: an away side that must win or is clearly stronger can run more at high intensity; say what each side does and why, and use the venue splits only as a tendency (small samples).")
    return out


def sub_bucket(minute) -> str:
    mi = num(minute)
    if mi is None:
        return "unknown"
    return "half-time (45-46)" if 45 <= mi <= 46 else "early second half (47-59)" if 46 < mi < 60 else "around 60-75" if mi <= 75 else "late (76+)" if mi > 75 else "first half"


def subs_section(m: dict, home, away, profiles: dict) -> list[str]:
    """The manager's substitution habits: who comes on and goes off, when, by scoreline, and whether the bench contributes."""
    out = ["", "# SUBSTITUTION PATTERNS (rotation habits, who is likely to start or come on, impact from the bench)"]
    names = {"home": home, "away": away}
    for side in ("home", "away"):
        name = names[side]
        squad = [p for p in (d(profiles.get(side)).get("squad") or []) if isinstance(p, dict)]
        rows = []
        for p in squad:
            u = d(p.get("recent_usage"))
            st, sub, mins = num(u.get("starts")) or 0, num(u.get("sub_appearances")) or 0, num(u.get("total_minutes")) or 0
            if st + sub:
                rows.append({"name": p.get("name"), "role": p.get("role"), "starts": int(st), "subs": int(sub), "avg": mins / (st + sub), "ga": (num(u.get("total_goals")) or 0) + (num(u.get("total_assists")) or 0), "xg90": p90((num(u.get("total_xg")) or 0) + (num(u.get("total_xa")) or 0), mins), "unused": int(num(u.get("unused_bench")) or 0), "mins": mins})
        used = sorted((x for x in rows if x["subs"] >= 1), key=lambda x: (-x["subs"], str(x["name"])))[:4]
        early = sorted((x for x in rows if x["starts"] >= 2 and x["avg"] < 75), key=lambda x: x["avg"])[:4]
        bench_ga = [x for x in rows if x["subs"] >= 1 and x["starts"] <= x["subs"] and x["ga"] > 0]
        out.append(f"\n## {name}")
        out.append("most used as substitutes (sub appearances / starts): " + ("; ".join(f"{x['name']} ({x['role']}) {x['subs']}/{x['starts']}, {x['avg']:.0f} min an appearance" for x in used) or "none identified"))
        out.append("starters usually taken off early (under 75 minutes an appearance, 2+ starts): " + ("; ".join(f"{x['name']} ({x['role']}) {x['avg']:.0f} min over {x['starts'] + x['subs']} games" for x in early) or "none: starters usually play the distance or the data is thin"))
        out.append("bench contribution (goals+assists by players who mostly come on): " + ("; ".join(f"{x['name']} {x['ga']:g}" + (f" (xG+xA {x['xg90']:.2f}/90)" if x['xg90'] is not None else "") for x in sorted(bench_ga, key=lambda x: -x['ga'])[:3]) or "none recorded") + "; unused bench places by player show the manager's rotation limits: " + (", ".join(f"{x['name']} {x['unused']}" for x in sorted(rows, key=lambda x: -x['unused'])[:3] if x['unused']) or "none"))
        buckets: dict[str, int] = {}
        states: dict[str, int] = {}
        games = 0
        for x in [x for x in (m.get("recent_meetings") or []) if isinstance(x, dict) and isinstance(x.get("event_timeline"), list)]:
            lab = "home" if norm_name(x.get("home_team")) == norm_name(name) else "away" if norm_name(x.get("away_team")) == norm_name(name) else None
            if lab is None:
                continue
            games += 1
            ev = [e for e in x["event_timeline"] if isinstance(e, dict)]
            for e in ev:
                if e.get("type") == "substitution" and e.get("team") == lab:
                    b = sub_bucket(e.get("minute"))
                    buckets[b] = buckets.get(b, 0) + 1
                    mi = num(e.get("minute")) or 0
                    mine = sum(1 for g in ev if g.get("type") == "goal" and g.get("team") == lab and (num(g.get("minute")) or 0) <= mi)
                    theirs = sum(1 for g in ev if g.get("type") == "goal" and g.get("team") != lab and (num(g.get("minute")) or 0) <= mi)
                    k = "leading" if mine > theirs else "trailing" if mine < theirs else "level"
                    states[k] = states.get(k, 0) + 1
        out.append(f"timing and scoreline (only the {games} past meetings with a timeline: a thin sample): " + (", ".join(f"{k} {v}" for k, v in sorted(buckets.items(), key=lambda t: -t[1])) + "; score when the changes were made: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items(), key=lambda t: -t[1])) if buckets else "no substitution timeline in the report"))
    out.append("How to read it: the players used most as substitutes and those taken off early show the rotation habit and who may start or come on next; the timing (half-time, about 60, late) and the scoreline when changes are made show whether the manager reacts to the game state; bench goals and assists show impact players; say what this predicts for the next match (who is likely rested or introduced) and mark the thin samples.")
    return out


def draw_section(r: dict, m: dict, ins: dict, home, away, forms: dict | None = None) -> list[str]:
    """What the draw advocate needs: how often each side's games end level or close, how low the totals run, how tight the xG was, and the links between the two sides (a symmetric matchup, a low combined total). Counts and rates only, no odds."""
    import math
    out = ["", "# DRAW EVIDENCE (computed from each side's last games; a count is only as good as its sample, read the n)"]
    stats: dict = {}
    for side, name in (("home", home), ("away", away)):
        rows = [x for x in (d(d(forms or {}).get(side)).get("last10_overall") or []) if isinstance(x, dict) and oriented(x)]
        if not rows:
            out.append(f"\n## {name}: no scored games in the report")
            continue
        n = len(rows)
        gf = [oriented(x)[0] for x in rows]
        ga = [oriented(x)[1] for x in rows]
        draws = sum(1 for a, b in zip(gf, ga) if a == b)
        nonwins = sum(1 for a, b in zip(gf, ga) if a <= b)
        one = sum(1 for a, b in zip(gf, ga) if abs(a - b) <= 1)
        low = sum(1 for a, b in zip(gf, ga) if a + b <= 2)
        zz = sum(1 for a, b in zip(gf, ga) if a == b == 0)
        oo = sum(1 for a, b in zip(gf, ga) if a == b >= 1)
        scored1 = sum(1 for a in gf if a <= 1)
        conc1 = sum(1 for b in ga if b <= 1)
        xr = [x for x in rows if num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
        tight = sum(1 for x in xr if abs(num(x["xg_for"]) - num(x["xg_against"])) < 0.5)
        level_not_draw = sum(1 for x in xr if abs(num(x["xg_for"]) - num(x["xg_against"])) < 0.5 and oriented(x)[0] != oriented(x)[1])
        stats[side] = {"n": n, "draw": draws / n, "one": one / n, "low": low / n, "tight": (tight / len(xr)) if xr else None}
        out.append(f"\n## {name} (last {n} games with a score)")
        out.append(f"level finishes: {draws} of {n} ({draws} = {zz} goalless + {oo} score draws); not won: {nonwins} of {n}; decided by one goal or less: {one} of {n}; 2 goals or fewer in the game: {low} of {n}")
        out.append(f"scored 1 or fewer: {scored1} of {n}; conceded 1 or fewer: {conc1} of {n}; average goals in its games {sum(a + b for a, b in zip(gf, ga)) / n:.2f}")
        out.append(f"xG-tight games (xG within 0.5 either way): {tight} of {len(xr)} with xG" + (f"; of those {level_not_draw} did NOT end level (decided by finishing, not chances)" if xr else "") if xr else "xG-tight games: no xG in the sample")
    est = {s_: d(ins.get(f"{s_}_xg_estimate")) for s_ in ("home", "away")}
    ok_ = all(num(e.get("sample_size")) and num(e.get("xg_for")) is not None and num(e.get("xg_against")) is not None for e in est.values())
    out.append("\n## the two sides together")
    lam = None
    if ok_:
        v = {s_: (shrunk(num(e["xg_for"]) / num(e["sample_size"]), num(e["sample_size"])), shrunk(num(e["xg_against"]) / num(e["sample_size"]), num(e["sample_size"]))) for s_, e in est.items()}
        lh, la = venue_anchor(v["home"][0], v["away"][1], v["away"][0], v["home"][1], neutral=True)      # the draw reading is about how symmetric the sides are, so no venue edge here
        lam = (lh, la)
        pd_ = sum(math.exp(-lh) * lh ** k / math.factorial(k) * math.exp(-la) * la ** k / math.factorial(k) for k in range(0, 12))
        out.append(f"shrunk xG anchors on a NEUTRAL ground, no home edge (the goals and underdog slices add the home edge, so their pair differs): {home} {lh:.2f}, {away} {la:.2f}; total {lh + la:.2f}; gap {abs(lh - la):.2f}; a plain independent-goals model at these numbers gives a level finish {100 * pd_:.1f}% (reference only: the base rate is 23-25%)")
        out.append(f"cross-links: {home} attack {v['home'][0]:.2f} meets {away} defence {v['away'][1]:.2f}; {away} attack {v['away'][0]:.2f} meets {home} defence {v['home'][1]:.2f}; mirror-image matchup if the two anchors are within 0.3 and both attacks are at or below the defences they face")
    sig = []
    if lam and lam[0] + lam[1] <= 2.4:
        sig.append(f"combined expected goals {lam[0] + lam[1]:.2f} is 2.4 or lower")
    if lam and abs(lam[0] - lam[1]) <= 0.5:
        sig.append(f"expected goals gap {abs(lam[0] - lam[1]):.2f} is 0.5 or less")
    if len(stats) == 2:
        if min(stats[s_]["draw"] for s_ in stats) >= 0.3:
            sig.append("both sides drew 30% or more of their games")
        if min(stats[s_]["one"] for s_ in stats) >= 0.6:
            sig.append("both sides play 60% or more of their games to one goal or less")
        if min(stats[s_]["low"] for s_ in stats) >= 0.5:
            sig.append("both sides play 50% or more of their games to 2 goals or fewer")
        if all(stats[s_]["tight"] is not None and stats[s_]["tight"] >= 0.5 for s_ in stats):
            sig.append("half or more of both sides' games were xG-tight")
    out.append("draw signals present from these numbers: " + ("; ".join(sig) if sig else "none") + f" ({len(sig)} of 5 checked)")
    out.append("How to read it: these are counts over small samples, not probabilities. A level finish rate is evidence about how a side's games go (low totals, narrow margins), not a promise; say which signals link (for example low totals AND narrow margins AND a symmetric matchup) and which stand alone. Never use a signal that is absent.")
    return out


def side_case_section(r: dict, m: dict, ins: dict, home, away, forms: dict | None, side: str) -> list[str]:
    """What a side's advocate needs: how this side's games go (margins, xG control, luck), what its opponent concedes and fails at, and the links between the two (this attack against that defence). Counts and rates only, no odds."""
    import math
    me, you = (home, away) if side == "home" else (away, home)
    oside = "away" if side == "home" else "home"
    out = ["", f"# CASE EVIDENCE FOR {me.upper()} (computed from each side's last games; a count is only as good as its sample, read the n)"]
    def rows_of(sd):
        return [x for x in (d(d(forms or {}).get(sd)).get("last10_overall") or []) if isinstance(x, dict) and oriented(x)]
    def prof(rows):
        n = len(rows)
        gf = [oriented(x)[0] for x in rows]
        ga = [oriented(x)[1] for x in rows]
        xr = [x for x in rows if num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
        dom = [x for x in xr if num(x["xg_for"]) - num(x["xg_against"]) >= 0.5]
        got = [x for x in xr if num(x["xg_against"]) - num(x["xg_for"]) >= 0.5]
        return {"n": n, "w": sum(1 for a, b in zip(gf, ga) if a > b), "l": sum(1 for a, b in zip(gf, ga) if a < b), "two": sum(1 for a in gf if a >= 2), "blank": sum(1 for a in gf if a == 0),
                "cs": sum(1 for b in ga if b == 0), "c2": sum(1 for b in ga if b >= 2), "big": sum(1 for a, b in zip(gf, ga) if a - b >= 2), "xr": len(xr), "dom": len(dom),
                "dom_notwon": sum(1 for x in dom if oriented(x)[0] <= oriented(x)[1]), "under": len(got), "under_won": sum(1 for x in got if oriented(x)[0] > oriented(x)[1]),
                "pts": sum(3 if a > b else 1 if a == b else 0 for a, b in zip(gf, ga))}
    mine, theirs = rows_of(side), rows_of(oside)
    if not mine:
        out.append(f"{me}: no scored games in the report")
        return out
    p, q = prof(mine), prof(theirs) if theirs else None
    out.append(f"\n## {me} (last {p['n']} games with a score)")
    out.append(f"won {p['w']}, lost {p['l']}, {p['pts'] / p['n']:.2f} points a game; won by 2 or more {p['big']} times; scored 2 or more in {p['two']} of {p['n']}; failed to score in {p['blank']}; kept a clean sheet in {p['cs']}; conceded 2 or more in {p['c2']}")
    out.append(f"xG control (games with xG: {p['xr']}): ahead by 0.5 xG or more in {p['dom']} and did not win {p['dom_notwon']} of those (chances not turned into wins: results may rise); behind by 0.5 or more in {p['under']} and still won {p['under_won']} (results ahead of the chances: may fall)" if p["xr"] else "xG control: no xG in the sample")
    if q:
        out.append(f"\n## {you}, the opponent (last {q['n']} games with a score)")
        out.append(f"won {q['w']}, lost {q['l']}, {q['pts'] / q['n']:.2f} points a game; failed to score in {q['blank']}; conceded 2 or more in {q['c2']} of {q['n']} (the {me} attack can exploit this); kept a clean sheet in {q['cs']}")
        out.append(f"opponent xG control (games with xG: {q['xr']}): behind by 0.5 xG or more in {q['under']} and still won {q['under_won']}; ahead by 0.5 or more in {q['dom']} and did not win {q['dom_notwon']}" if q["xr"] else "opponent xG control: no xG in the sample")
    est = {s_: d(ins.get(f"{s_}_xg_estimate")) for s_ in ("home", "away")}
    ok_ = all(num(e.get("sample_size")) and num(e.get("xg_for")) is not None and num(e.get("xg_against")) is not None for e in est.values())
    sig = []
    out.append("\n## the two sides together")
    if ok_:
        v = {s_: (shrunk(num(e["xg_for"]) / num(e["sample_size"]), num(e["sample_size"])), shrunk(num(e["xg_against"]) / num(e["sample_size"]), num(e["sample_size"]))) for s_, e in est.items()}
        my_att, my_def, op_att, op_def = v[side][0], v[side][1], v[oside][0], v[oside][1]
        mine_x, their_x = (my_att + op_def) / 2, (op_att + my_def) / 2
        out.append(f"shrunk xG: {me} creates {my_att:.2f} and concedes {my_def:.2f}; {you} creates {op_att:.2f} and concedes {op_def:.2f}")
        out.append(f"cross-links: {me} attack {my_att:.2f} meets {you} defence {op_def:.2f} (anchor {mine_x:.2f}); {you} attack {op_att:.2f} meets {me} defence {my_def:.2f} (anchor {their_x:.2f}); anchor gap in {me}'s favour {mine_x - their_x:+.2f}")
        if mine_x - their_x >= 0.3:
            sig.append(f"the xG anchor gap is {mine_x - their_x:+.2f} for {me} (0.3 or more)")
        if my_att > op_def + 0.15:
            sig.append(f"{me} attack {my_att:.2f} is above the defence it meets {op_def:.2f}")
        if op_att < my_def - 0.15:
            sig.append(f"the attack {me} meets creates {op_att:.2f}, less than the {my_def:.2f} {me} usually concede")
    if q:
        if p["pts"] / p["n"] - q["pts"] / q["n"] >= 0.5:
            sig.append(f"points a game {p['pts'] / p['n']:.2f} v {q['pts'] / q['n']:.2f}")
        if q["c2"] >= 4:
            sig.append(f"the opponent conceded 2 or more in {q['c2']} of {q['n']}")
        if p["dom"] and p["dom_notwon"] >= 1:
            sig.append(f"{me} out-chanced {p['dom_notwon']} opponent(s) without winning (results can rise)")
    out.append(f"case signals present from these numbers for {me}: " + ("; ".join(sig) if sig else "none") + f" ({len(sig)} found)")
    out.append("How to read it: counts over small samples, not probabilities. Build the case from LINKS (this side's attack against the defence it meets, an opponent weakness against this side's strength, results against xG), say which links you checked and found absent, and never use a signal that is not there. The home advocate and the away advocate see the same layout from their own side.")
    return out


def _ht_oriented(row: dict) -> tuple[int, int] | None:
    """The half-time score turned round to this team's goals first; neutral venues are skipped (their half-time score has no side to turn it by)."""
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(row.get("ht_scoreline") or ""))
    if not m or row.get("venue") not in ("home", "away"):
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if row.get("venue") == "home" else (b, a)


def underdog_section(r: dict, m: dict, ins: dict, home, away, forms: dict | None = None) -> list[str]:
    """What the underdog advocate needs: who the underdog is (from the rating gap and the shrunk xG anchors, never from odds), the favourite's defensive errors and weak spots, the underdog's routes to a goal, and how the favourite's games go once the opponent HAS scored (win, draw or loss)."""
    import math
    out = ["", "# UNDERDOG EVIDENCE (who is the underdog, does it score against this defence, and if it scores does the favourite still win or only draw; a count is only as good as its sample, read the n)"]
    est = {s_: d(ins.get(f"{s_}_xg_estimate")) for s_ in ("home", "away")}
    lam = None
    if all(num(e.get("sample_size")) and num(e.get("xg_for")) is not None and num(e.get("xg_against")) is not None for e in est.values()):
        v = {s_: (shrunk(num(e["xg_for"]) / num(e["sample_size"]), num(e["sample_size"])), shrunk(num(e["xg_against"]) / num(e["sample_size"]), num(e["sample_size"]))) for s_, e in est.items()}
        lam = venue_anchor(v["home"][0], v["away"][1], v["away"][0], v["home"][1])
    elo = {s_: class_elo(ins, s_) for s_ in ("home", "away")}      # class: ClubElo first, as the rating anchor does; other Elo sources are form-only, never class
    votes = []                                                  # +1 home is the better side, -1 away is, 0 level or unknown
    if lam:
        votes.append(0 if abs(lam[0] - lam[1]) < 0.15 else (1 if lam[0] > lam[1] else -1))
    if None not in elo.values():
        votes.append(0 if abs(elo["home"] - elo["away"]) < 40 else (1 if elo["home"] > elo["away"] else -1))
    fav = None
    if votes and all(x == votes[0] for x in votes) and votes[0] != 0:
        fav = "home" if votes[0] > 0 else "away"
    elif votes and sum(votes) != 0 and 0 not in votes[:1] and len(votes) == 2 and votes[0] * votes[1] < 0:
        fav = None
    elif votes and sum(votes) != 0:
        fav = "home" if sum(votes) > 0 else "away"
    names = {"home": home, "away": away}
    basis = (f"shrunk xG anchors with the home edge {lam[0]:.2f}-{lam[1]:.2f}" if lam else "no xG anchors") + ("; Elo " + f"{elo['home']:.0f} v {elo['away']:.0f}" if None not in elo.values() else "; no Elo")
    if fav is None:
        out.append(f"No clear favourite ({basis}): the two readings disagree or are level, so the evidence is shown for BOTH sides as the one that might score; choose the side that is the weaker on the ratings and say so.")
        sides = [("home", "away"), ("away", "home")]
    else:
        out.append(f"Favourite: {names[fav]}; underdog: {names['away' if fav == 'home' else 'home']} ({basis}; the rating gap and the data decide this, not any price).")
        sides = [(fav, "away" if fav == "home" else "home")]
    def rows_of(side):
        return [x for x in (d(d(forms or {}).get(side)).get("last10_overall") or []) if isinstance(x, dict) and oriented(x)]
    def wdl(rs):
        w = sum(1 for a_, b_ in rs if a_ > b_); dr = sum(1 for a_, b_ in rs if a_ == b_); lo = sum(1 for a_, b_ in rs if a_ < b_)
        return f"W{w} D{dr} L{lo}" + (f" ({(3 * w + dr) / len(rs):.2f} points a game)" if rs else "")
    for f_, u_ in sides:
        fn, un = names[f_], names[u_]
        out.append(f"\n## {un} (underdog) against {fn} (favourite)")
        ur, fr = rows_of(u_), rows_of(f_)
        f5, u5 = [oriented(x) for x in fr[:5]], [oriented(x) for x in ur[:5]]
        ppg = lambda rs: sum(3 if a_ > b_ else 1 if a_ == b_ else 0 for a_, b_ in rs) / len(rs)
        if len(f5) >= 3 and len(u5) >= 3 and ppg(f5) <= ppg(u5):    # Alavés came in on LLDLL as the favourite and still won the xG 1.84-0.71 (drew 1-1)
            out.append(f"FORM v CLASS: the favourite {fn} took {ppg(f5):.2f} points a game from its last {len(f5)}, the underdog {un} {ppg(u5):.2f} from its last {len(u5)}. "
                       "The backtest found a side on a losing run did slightly worse than its rating expected (no bounce-back), so a small downgrade is fair, a big one is not: class and chances usually outlast a short run. Check that the favourite still creates the chances")
        if ur:
            ug = [oriented(x) for x in ur]
            scored = sum(1 for a_, _ in ug if a_ >= 1)
            out.append(f"{un} scored in {scored} of {len(ur)} recent games ({sum(a_ for a_, _ in ug) / len(ur):.2f} a game); when it scored its record is {wdl([x for x in ug if x[0] >= 1])}")
        else:
            out.append(f"{un}: no scored games in the report")
        if fr:
            fg = [oriented(x) for x in fr]
            kept = sum(1 for _, b_ in fg if b_ == 0)
            out.append(f"{fn} kept a clean sheet in {kept} of {len(fr)} recent games and conceded in {len(fr) - kept}")
            conceded = [x for x in fg if x[1] >= 1]
            blank = [x for x in fg if x[1] == 0]
            out.append(f"IF THE UNDERDOG SCORES: {fn}'s games in which the opponent scored (n={len(conceded)}): {wdl(conceded)}; games in which it did not (n={len(blank)}): {wdl(blank)}. A favourite that still wins after conceding is robust; one that mostly draws or loses is the draw/upset route")
            known = [(oriented(x), x.get("first_goal")) for x in fr if x.get("first_goal") in ("for", "against")]
            if known:
                cf = [o for o, g in known if g == "against"]
                uk = [x for x in ur if x.get("first_goal") in ("for", "against")]
                us = sum(1 for x in uk if x.get("first_goal") == "for")
                out.append(f"IF THE UNDERDOG SCORES FIRST (goal times from the match details, {len(known)} of {len(fr)} games known): {fn} conceded the first goal in {len(cf)}: {wdl(cf)}"
                           + (f" (came back to win {sum(1 for a_, b_ in cf if a_ > b_)}, drew {sum(1 for a_, b_ in cf if a_ == b_)})" if cf else "")
                           + (f"; {un} scored first in {us} of its {len(uk)} known games" if uk else "")
                           + ". This is the real version of calc.py's 'If the underdog scores first' line; under 5 games it is a lean")
            trail = [(oriented(x), _ht_oriented(x)) for x in fr]
            behind = [o for o, h in trail if h and h[0] < h[1]]
            level = [o for o, h in trail if h and h[0] == h[1]]
            if behind or level:
                out.append(f"{fn} after half-time: trailing at the break (n={len(behind)}) {wdl(behind)}; level at the break (n={len(level)}) {wdl(level)}")
            else:
                out.append(f"{fn}: no usable half-time scores (neutral venues or missing)")
        else:
            out.append(f"{fn}: no scored games in the report")
        ad_f, ad_u = d(ins.get(f"{f_}_advanced_stats")), d(ins.get(f"{u_}_advanced_stats"))
        n_f, n_u = num(ad_f.get("sample_size")), num(ad_u.get("sample_size"))
        errs = d(ins.get(f"{f_}_defensive_errors_estimate"))
        bits = []
        if n_f:
            bits.append(f"errors leading to a shot against {fn} {fmt(per(ad_f.get('errors_lead_to_shot_against'), n_f))} a game, to a goal {fmt(per(ad_f.get('errors_lead_to_goal_against'), n_f))} a game over {fmt(n_f, 0)} games")
            bits.append(f"{un}'s own errors lead to {fmt(per(ad_u.get('errors_lead_to_shot_against'), n_u))} shots against a game" if n_u else "")
        if errs:
            bits.append(f"defensive errors estimate: {json.dumps(errs)}")
        out.append("defensive errors (the underdog's gift): " + ("; ".join(b for b in bits if b) or "not in the report"))
        weak = []
        dv = ins.get(f"{f_}_duel_vulnerabilities")
        if isinstance(dv, list) and dv:
            weak.append("duel vulnerabilities " + json.dumps(dv)[:200])
        fb = ins.get(f"{f_}_fullback_exposure")
        if fb:
            weak.append("full-back exposure " + json.dumps(fb)[:160])
        dp = d(ins.get(f"{u_}_direct_play_exposure"))
        if dp:
            weak.append(f"{un} plays {fmt(dp.get('long_ball_share_pct'), 1)}% long balls against opponent aerial wins {fmt(dp.get('opponent_aerial_win_pct'), 1)}%")
        sp_u = per(ad_u.get("set_piece_xg_for"), n_u) if n_u else None
        sp_f = per(ad_f.get("set_piece_xg_against"), n_f) if n_f else None
        if sp_u is not None and sp_f is not None:
            weak.append(f"set pieces: {un} {sp_u:.2f} xG for a game v {fn} {sp_f:.2f} against = {(sp_u + sp_f) / 2:.2f} expected")
        gk = d(ins.get(f"{f_}_goalkeeping_estimate"))
        if gk and num(gk.get("save_pct")) is not None:
            weak.append(f"{fn} goalkeeper saves {fmt(gk.get('save_pct'), 1)}% over {fmt(gk.get('sample_size'), 0)} games")
        out.append("other weak spots and routes: " + ("; ".join(weak) or "none listed"))
        cbng = []                                                   # chances but no goals: Alavés 1.84 xG for 1 goal and Forest 2.33 xG for 1 goal, both drawn (2026-10-23)
        bcf, xgf, gku = d(ins.get(f"{f_}_big_chances_estimate")), d(ins.get(f"{f_}_xg_estimate")), d(ins.get(f"{u_}_goalkeeping_estimate"))
        made, missed = num(bcf.get("big_chances_created_for")), num(bcf.get("big_chances_missed_for"))
        if made and missed is not None:
            cbng.append(f"{fn} missed {missed:g} of {made:g} big chances ({100 * missed / made:.0f}%) over {fmt(bcf.get('sample_size'), 0)} games")
        if num(xgf.get("sample_size")) and num(xgf.get("actual_goals_for")) is not None and num(xgf.get("xg_for")) is not None:
            cbng.append(f"{fn} goals minus xG {per(xgf['actual_goals_for'] - xgf['xg_for'], num(xgf['sample_size'])):+.2f} a game")
        if num(gku.get("save_pct")) is not None:
            cbng.append(f"{un} goalkeeper saves {fmt(gku.get('save_pct'), 1)}% (about 72% is normal)")
        if lam:
            lf = lam[0] if f_ == "home" else lam[1]
            cbng.append(f"at {lf:.2f} expected goals {fn} scores 1 or fewer in {100 * math.exp(-lf) * (1 + lf):.0f}% of matches even when it creates what it should")
        if cbng:
            out.append("CHANCES BUT NO GOALS (the favourite can win the chances and still not win): " + "; ".join(cbng)
                       + ". Finishing and save rates mostly regress (about 10% of a finishing gap carries forward; a save rate far from 72% rarely lasts): read them as the size of the risk, not a sign it repeats")
        if lam:
            lu = lam[1] if u_ == "away" else lam[0]
            out.append(f"expected goals for {un} from the shrunk anchor: {lu:.2f}; a plain independent-goals reading of the chance that it scores at least once is {100 * (1 - math.exp(-lu)):.0f}% (reference only: the calculator has the final numbers)")
    out.append("How to read it: the underdog can score, and the favourite can still win. The questions are (1) does the underdog get a goal (its scoring record, the favourite's clean-sheet rate, the errors it gifts) and (2) once it does, does the favourite win, draw or lose (its own record after conceding, and trailing or level at half-time). Say which links you checked and found absent.")
    return out


def lineups_section(path: str) -> list[str]:
    """The confirmed lineups when lineup_check.py saved lineups.json beside the report (a lineups-review.json, fetched after
    kickoff, is never used): formations, the XIs and what they change (listed absentees who start, regulars left out)."""
    p = Path(path).with_name("lineups.json")
    try:
        lu = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["", "# CONFIRMED LINEUPS: not checked (no lineups.json beside the report): the missing list is the scrape's, taken before the teams were named; treat DOUBTFUL players as possible starters"]
    out = ["", "# CONFIRMED LINEUPS (they override the missing list and any projected XI)",
           f"lineups {'CONFIRMED' if lu.get('confirmed') else 'NOT yet confirmed'}, fetched {lu.get('minutes_before_kickoff', '?')} min before kickoff; they override the missing list and any projected XI"]
    for side in ("home", "away"):
        s = d(lu.get(side))
        out.append(f"{lu.get(f'{side}_team') or side}: {s.get('formation') or '?'}; XI {', '.join(s.get('xi') or []) or 'not published'}; bench {', '.join((s.get('bench') or [])[:12]) or 'n/a'}")
    out += [f"LINEUP CHANGE: {c}" for c in (lu.get("checks") or [])] or ["LINEUP CHANGE: none against the report's missing list and regulars"]
    out.append("How to read it: a listed absentee who STARTS is not an absence (undo any move you made for him); a regular on the bench is a part absence; re-read the formations against the shape lines (the zones that are weak on paper change with the shape).")
    return out


CLASS_BAND = 100            # an opponent counts as "the favourite's class" when rated no more than this below the favourite AND above the underdog itself


def underdog_strength(r: dict, m: dict, ins: dict, home, away, forms: dict | None = None) -> list[str]:
    """Is the underdog really weaker? Its results against sides of the favourite's class and against the top of the table,
    the table and goal difference, its venue record against the favourite's, and its form, ending in a count of the signals
    that say it is stronger than the rating gap. Villa (ClubElo 1906 v City 2027, 12th) had beaten Liverpool 4-2, Brighton 4-0
    and PSG 2-1 in its last 20, was W5 D1 in its last 6, and beat City 2-1 (2026-10-24); none of it was on the sheet."""
    out = ["", "# UNDERDOG STRENGTH (is the underdog really weaker? its results against sides of the favourite's class, the table, goal difference, home advantage and form; counts over small samples, read the n)"]
    names = {"home": home, "away": away}
    elo = {s_: class_elo(ins, s_) for s_ in ("home", "away")}
    table = [t for t in (m.get("standings_table") or []) if isinstance(t, dict) and t.get("team_name")]
    pos = {s_: num(d(m.get(f"{s_}_team_standing")).get("position")) for s_ in ("home", "away")}
    if None not in elo.values() and abs(elo["home"] - elo["away"]) >= 40:
        fav = "home" if elo["home"] > elo["away"] else "away"
        basis = f"ClubElo {elo['home']:.0f} v {elo['away']:.0f}"
    elif None not in pos.values() and abs(pos["home"] - pos["away"]) >= 4 and not unformed_table(ins):
        fav = "home" if pos["home"] < pos["away"] else "away"
        basis = f"table {pos['home']:.0f} v {pos['away']:.0f} (no class rating gap)"
    else:
        out.append("No clear underdog (class ratings within 40 points or missing, table close): nothing to assess.")
        return out
    dog = "away" if fav == "home" else "home"
    fn, un = names[fav], names[dog]
    out.append(f"Underdog: {un}; favourite: {fn} ({basis}).")

    def rows_of(side):
        f = d(d(forms or {}).get(side))
        rs = f.get("last20_overall") or f.get("last10_overall") or []
        return [x for x in rs if isinstance(x, dict) and oriented(x)]
    def rec(rs):
        if not rs:
            return "no games"
        sc = [oriented(x) for x in rs]
        w = sum(1 for a_, b_ in sc if a_ > b_); dr = sum(1 for a_, b_ in sc if a_ == b_)
        return (f"W{w} D{dr} L{len(sc) - w - dr} in {len(sc)} ({(3 * w + dr) / len(sc):.2f} points a game), "
                f"goals {sum(a_ for a_, _ in sc)}-{sum(b_ for _, b_ in sc)}")
    def ppg_of(rs):
        return None if not rs else sum(3 if a_ > b_ else 1 if a_ == b_ else 0 for a_, b_ in map(oriented, rs)) / len(rs)
    def listed(rs, k=6):
        return ", ".join(f"{x.get('result')} {oriented(x)[0]}-{oriented(x)[1]} v {x.get('opponent')} ({str(x.get('venue') or '?')[:1]}"
                         + (f", {num(x['opponent_club_elo']):.0f}" if num(x.get("opponent_club_elo")) is not None else "") + ")" for x in rs[:k])
    ur, fr = rows_of(dog), rows_of(fav)
    signals = []

    # 1. against sides of the favourite's class (and against sides stronger than itself)
    if elo[fav] is not None and ur:
        bar = max(elo[fav] - CLASS_BAND, elo[dog] if elo[dog] is not None else 0)
        top_u = [x for x in ur if (num(x.get("opponent_club_elo")) or 0) >= bar]
        top_f = [x for x in fr if (num(x.get("opponent_club_elo")) or 0) >= bar and norm_name(x.get("opponent")) != norm_name(un)]
        wins = [x for x in top_u if x.get("result") == "W"]
        out.append(f"AGAINST THE FAVOURITE'S CLASS (opponents rated {bar:.0f}+ ClubElo, last {len(ur)} games): {un} {rec(top_u)}"
                   + (f": {listed(top_u)}" if top_u else "") + f". {fn} against the same class: {rec(top_f)}")
        if wins and len(top_u) >= 2 and (ppg_of(top_u) or 0) >= 1.5:
            signals.append(f"{un} has beaten {len(wins)} side(s) of {fn}'s class ({listed(wins, 3)})")
        if elo[dog] is not None:
            up = [x for x in ur if (num(x.get("opponent_club_elo")) or 0) > elo[dog]]
            out.append(f"against sides rated above itself ({elo[dog]:.0f}): {un} {rec(up)}")
        unrated = [x for x in ur if num(x.get("opponent_club_elo")) is None]
        if unrated:
            out.append(f"opponents with no ClubElo (often foreign cup ties; judge their class by name): {listed(unrated)}")

    # 2. against the top of the current table
    if len(table) >= 10 and not unformed_table(ins):
        top_n = 6 if len(table) >= 16 else 4
        top = {norm_name(t["team_name"]) for t in table if (num(t.get("position")) or 99) <= top_n}
        vs_top = [x for x in ur if norm_name(x.get("opponent")) in top and norm_name(x.get("opponent")) != norm_name(fn)]
        out.append(f"against the current top {top_n} (other than {fn}): {un} {rec(vs_top)}" + (f": {listed(vs_top)}" if vs_top else ""))

    # 3. table and goal difference
    st = {s_: d(m.get(f"{s_}_team_standing")) for s_ in ("home", "away")}
    if all(num(st[s_].get("played")) for s_ in st):
        def gd_pg(s_):
            gd = num(st[s_].get("goal_difference"))
            return None if gd is None else gd / num(st[s_]["played"])
        out.append("table: " + "; ".join(f"{names[s_]} {fmt(st[s_].get('position'), 0)} of {fmt(st[s_].get('total_teams'), 0)}, {fmt(st[s_].get('points'), 0)} points from {fmt(st[s_].get('played'), 0)}, goal difference {fmt(st[s_].get('goal_difference'), 0)} ({fmt(gd_pg(s_), 2)} a game)" for s_ in (dog, fav))
                   + ("; early season (under 10 played): the table is mostly noise" if num(st[dog].get("played")) < 10 else ""))
    gd_rows = {s_: [oriented(x) for x in rows_of(s_)] for s_ in ("home", "away")}
    if all(gd_rows.values()):
        g = {s_: sum(a_ - b_ for a_, b_ in v) / len(v) for s_, v in gd_rows.items()}
        out.append(f"goal difference in the recent games: {un} {g[dog]:+.2f} a game over {len(gd_rows[dog])}, {fn} {g[fav]:+.2f} over {len(gd_rows[fav])}")
        if g[dog] >= g[fav] - 0.5:
            signals.append(f"recent goal difference close to or better than the favourite's ({g[dog]:+.2f} v {g[fav]:+.2f} a game)")

    # 4. home advantage: the underdog's record at today's venue against the favourite's
    if not m.get("neutral_venue") and ur and fr:
        uven = "home" if dog == "home" else "away"
        fven = "away" if uven == "home" else "home"
        u_at = [x for x in ur if x.get("venue") == uven and not x.get("neutral_venue")]
        f_at = [x for x in fr if x.get("venue") == fven and not x.get("neutral_venue")]
        out.append(f"VENUE: {un} at {uven} {rec(u_at)}; {fn} at {fven} {rec(f_at)}")
        pu, pf = ppg_of(u_at), ppg_of(f_at)
        if uven == "home" and pu is not None and pf is not None and len(u_at) >= 3 and pu >= pf:
            signals.append(f"{un}'s home record is as good as {fn}'s away record ({pu:.2f} v {pf:.2f} points a game)")

    # 5. form
    if len(ur) >= 3 and len(fr) >= 3:
        u5, f5 = ppg_of(ur[:5]), ppg_of(fr[:5])
        out.append(f"form, last 5: {un} {u5:.2f} points a game ({''.join(str(x.get('result')) for x in ur[:5])}), {fn} {f5:.2f} ({''.join(str(x.get('result')) for x in fr[:5])})")
        if u5 >= f5:
            signals.append(f"better or equal form ({u5:.2f} v {f5:.2f} points a game in the last 5)")

    out.append(f"UNDERDOG STRENGTH: {len(signals)} of 4 signals say {un} is stronger than the rating gap suggests"
               + (": " + "; ".join(signals) if signals else "") + ". "
               + ("This is not an ordinary underdog: weigh its WIN, not only the draw, and if you still back the favourite's side say why not the underdog, naming the evidence."
                  if len(signals) >= 3 else
                  "Some signs of a live underdog: check them against the class gap before you cover only the favourite."
                  if len(signals) == 2 else
                  "An ordinary underdog on this evidence: the class gap stands."))
    out.append("How to read it: the rating anchor counts class over years; these lines count what the underdog has done lately against good sides and at this venue. They are not fitted on our data (untested as a signal): use them to decide whether the underdog's win is a real route, not to move expected goals by themselves.")
    return out


def state_section(r: dict, m: dict, ins: dict, home, away, forms: dict | None = None) -> list[str]:
    """What the game-state advocate needs: how each side's matches swing once a goal is scored (who holds a lead, who comes back), the goals by half, the defensive errors and the shapes (a back three), and a plain reading of how the game may start. Counts only, no odds."""
    import math
    out = ["", "# GAME-STATE EVIDENCE (who holds a lead, who comes back, whose defence cracks under pressure; a count is only as good as its n)"]
    names = {"home": home, "away": away}
    est = {s_: d(ins.get(f"{s_}_xg_estimate")) for s_ in ("home", "away")}
    lam = None
    if all(num(e.get("sample_size")) and num(e.get("xg_for")) is not None and num(e.get("xg_against")) is not None for e in est.values()):
        v = {s_: (shrunk(num(e["xg_for"]) / num(e["sample_size"]), num(e["sample_size"])), shrunk(num(e["xg_against"]) / num(e["sample_size"]), num(e["sample_size"]))) for s_, e in est.items()}
        lam = venue_anchor(v["home"][0], v["away"][1], v["away"][0], v["home"][1])
    wdl = lambda rs: f"W{sum(1 for a_, b_ in rs if a_ > b_)} D{sum(1 for a_, b_ in rs if a_ == b_)} L{sum(1 for a_, b_ in rs if a_ < b_)}"
    fh_share: dict[str, tuple[float, float] | None] = {}
    for side in ("home", "away"):
        nm = names[side]
        fm = d(forms or {}).get(side)
        rows = [x for x in (d(fm).get("last20_overall") or d(fm).get("last10_overall") or []) if isinstance(x, dict) and oriented(x) and _ht_oriented(x)]
        out.append(f"\n## {nm}")
        if rows:
            lead = [(oriented(x), _ht_oriented(x)) for x in rows]
            ahead = [o for o, h in lead if h[0] > h[1]]
            level = [o for o, h in lead if h[0] == h[1]]
            behind = [o for o, h in lead if h[0] < h[1]]
            swung = sum(1 for o, h in lead if (o[0] > o[1]) != (h[0] > h[1]) or (o[0] < o[1]) != (h[0] < h[1]))
            out.append(f"half-time states (n={len(rows)} games with a usable half-time score; neutral venues skipped): leading {len(ahead)} -> {wdl(ahead)} (kept the lead to win in {sum(1 for a_, b_ in ahead if a_ > b_)}, dropped points in {sum(1 for a_, b_ in ahead if a_ <= b_)}); level {len(level)} -> {wdl(level)}; trailing {len(behind)} -> {wdl(behind)} (came back to win or draw in {sum(1 for a_, b_ in behind if a_ >= b_)})")
            out.append(f"the result changed between half-time and full time in {swung} of {len(rows)} games")
            sh_for = sum(o[0] - h[0] for o, h in lead); sh_ag = sum(o[1] - h[1] for o, h in lead)
            out.append(f"second-half goals in those games: {sh_for} for, {sh_ag} against ({sh_for / len(rows):.2f} and {sh_ag / len(rows):.2f} a game)")
        else:
            out.append("no usable half-time scores in the report (neutral venues or missing)")
        hs = d(d(fm).get("half_split"))
        if num(hs.get("sample_size")) and None not in (num(hs.get("first_half_goals_for")), num(hs.get("second_half_goals_for")), num(hs.get("first_half_goals_against")), num(hs.get("second_half_goals_against"))):
            f1, s1, f2, s2 = (num(hs[k]) for k in ("first_half_goals_for", "second_half_goals_for", "first_half_goals_against", "second_half_goals_against"))
            out.append(f"goals by half over {fmt(hs.get('sample_size'), 0)} games: scored {fmt(f1, 0)} in the first half and {fmt(s1, 0)} in the second; conceded {fmt(f2, 0)} and {fmt(s2, 0)}")
            fh_share[side] = ((f1 / (f1 + s1)) if f1 + s1 else None, (f2 / (f2 + s2)) if f2 + s2 else None)
        timed = [x for x in (d(fm).get("last20_overall") or d(fm).get("last10_overall") or []) if isinstance(x, dict) and x.get("late_goals_for") is not None]
        if timed:                                                   # Alavés' 89th-minute equaliser came from a substitute (Mañas, on at 73')
            lf, la = sum(x["late_goals_for"] for x in timed), sum(x["late_goals_against"] for x in timed)
            subbed = [x for x in timed if x.get("sub_goals_for") is not None]
            sg = sum(x["sub_goals_for"] for x in subbed)
            gf = sum((oriented(x) or (0, 0))[0] for x in subbed)
            out.append(f"bench and late goals ({len(timed)} games with goal times; own goals left out): from the 76th minute on {lf} scored and {la} conceded"
                       + (f"; substitutes scored {sg} of its {gf} goals in the {len(subbed)} games with named substitutions" if subbed else "")
                       + ". A side that scores late and from the bench keeps chasing a result; one that concedes late drops leads")
        ad = d(ins.get(f"{side}_advanced_stats"))
        n_ = num(ad.get("sample_size"))
        bits = []
        if n_:
            bits.append(f"errors leading to a shot against {fmt(per(ad.get('errors_lead_to_shot_against'), n_))} a game, to a goal against {fmt(per(ad.get('errors_lead_to_goal_against'), n_))} a game over {fmt(n_, 0)} games")
        errs = d(ins.get(f"{side}_defensive_errors_estimate"))
        if errs:
            bits.append(f"defensive errors estimate: {json.dumps(errs)}")
        out.append("defence under pressure: " + ("; ".join(bits) or "no error figures in the report"))
        form = m.get(f"{side}_formation")
        rot = d(ins.get(f"{side}_rotation"))
        shape = parse_shape(form)
        line = f"expected shape {form or 'n/a'}" + (f" ({shape[0]} at the back{', a BACK THREE: more bodies forward and wide space behind the wing-backs when the ball is lost' if shape[0] == 3 else ''})" if shape else "")
        if rot.get("last_formation"):
            line += f"; last match {rot.get('last_formation')} ({rot.get('last_defender_count')} defenders), the one before {rot.get('previous_formation')} ({rot.get('previous_defender_count')})" + (" - the shape changed, so the back line is less settled" if rot.get("formation_changed") else "")
        out.append(line + ". The report holds no per-game formation record, so how this side's defence has fared in a back three cannot be counted.")
    sm = shape_matchup(m.get("home_formation"), m.get("away_formation"), home, away)
    if sm:
        out.append("\n## shapes against each other")
        out += sm
    if lam:
        hl, al = lam
        hf = [x for x in (fh_share.get("home") or (None, None))[:1] + (fh_share.get("away") or (None, None))[1:] if x is not None]
        af = [x for x in (fh_share.get("away") or (None, None))[:1] + (fh_share.get("home") or (None, None))[1:] if x is not None]
        sh, sa = (sum(hf) / len(hf) if hf else 0.45), (sum(af) / len(af) if af else 0.45)
        ph = lambda k, l_: math.exp(-l_) * l_ ** k / math.factorial(k)
        a1, b1 = hl * sh, al * sa
        up = sum(ph(i, a1) * ph(j, b1) for i in range(12) for j in range(12) if i > j)
        eq = sum(ph(i, a1) * ph(i, b1) for i in range(12))
        out.append(f"\n## how the game may start (reference only)\nfirst-half goals expected from the shrunk anchors and each side's first-half share of its goals: {home} {a1:.2f}, {away} {b1:.2f}; a plain independent-goals reading gives {home} ahead at half-time {100 * up:.0f}%, level {100 * eq:.0f}%, {away} ahead {100 * (1 - up - eq):.0f}% (the calculator has the final numbers)")
    elo_ = {s_: class_elo(ins, s_) for s_ in ("home", "away")}
    votes = []
    if lam:
        votes.append(0 if abs(lam[0] - lam[1]) < 0.15 else (1 if lam[0] > lam[1] else -1))
    if None not in elo_.values():
        votes.append(0 if abs(elo_["home"] - elo_["away"]) < 40 else (1 if elo_["home"] > elo_["away"] else -1))
    tot = sum(votes)
    if tot:
        und = away if tot > 0 else home
        out.append(f"\nUnderdog (from the rating gap and the xG anchors, never from odds): {und}. Your job is the underdog's path to the LEAD: when and how it can score first and what it needs to keep or turn the lead. Do not argue for the favourite taking the lead; the price already holds that.")
    else:
        out.append("\nNo clear underdog on the ratings: pick the weaker side on the numbers, call it the underdog and argue its path to the lead.")
    out.append("How to read it: the leader protects the ball, the trailer attacks; take both from the half-time counts.")
    out.append("A side that keeps its leads wins the games it starts well; one that drops points from the lead, or comes back from behind, makes a match swing.")
    out.append("When the trailer chases, its shape (a back three, wing-backs high) and its defensive errors decide whether the leader punishes it on the break; a strong defence that scores can turn the match round.")
    out.append("Questions: who scores first, does the leader hold, does the trailer pull level, does the lead change hands?")
    return out


def goals_case_section(r: dict, m: dict, ins: dict, home, away, forms: dict | None = None) -> list[str]:
    """What the goals advocate needs: how many goals each side's games produce, how often both score, clean sheets, and the expected-goals total with the plain independent-goals reading of over 2.5 and both teams to score. Counts and rates only, no odds."""
    import math
    out = ["", "# GOALS EVIDENCE (computed from each side's last games; a count is only as good as its sample, read the n)"]
    st: dict = {}
    for side, name in (("home", home), ("away", away)):
        rows = [x for x in (d(d(forms or {}).get(side)).get("last10_overall") or []) if isinstance(x, dict) and oriented(x)]
        if not rows:
            out.append(f"\n## {name}: no scored games in the report")
            continue
        n = len(rows)
        gf = [oriented(x)[0] for x in rows]
        ga = [oriented(x)[1] for x in rows]
        tot = [a + b for a, b in zip(gf, ga)]
        over = sum(1 for t in tot if t >= 3)
        btts = sum(1 for a, b in zip(gf, ga) if a >= 1 and b >= 1)
        cs = sum(1 for b in ga if b == 0)
        blank = sum(1 for a in gf if a == 0)
        four = sum(1 for t in tot if t >= 4)
        low = sum(1 for t in tot if t <= 1)
        st[side] = {"n": n, "over": over / n, "btts": btts / n, "cs": cs / n, "avg": sum(tot) / n, "low2": sum(1 for t in tot if t <= 2) / n}
        out.append(f"\n## {name} (last {n} games with a score)")
        out.append(f"3 or more goals in the game: {over} of {n}; 4 or more: {four}; 2 or fewer: {n - over}; 1 or fewer: {low}; average goals in its games {sum(tot) / n:.2f}")
        out.append(f"both teams scored: {btts} of {n}; this side kept a clean sheet: {cs}; failed to score: {blank}; scored {sum(gf) / n:.2f} and conceded {sum(ga) / n:.2f} a game")
        xr = [x for x in rows if num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
        if xr:
            xt = [num(x["xg_for"]) + num(x["xg_against"]) for x in xr]
            gt = [oriented(x)[0] + oriented(x)[1] for x in xr]
            out.append(f"chance totals (games with xG: {len(xr)}): xG in its games averages {sum(xt) / len(xr):.2f}, goals in the same games {sum(gt) / len(xr):.2f} (goals above the chances: totals may fall; below: they may rise)")
    est = {s_: d(ins.get(f"{s_}_xg_estimate")) for s_ in ("home", "away")}
    ok_ = all(num(e.get("sample_size")) and num(e.get("xg_for")) is not None and num(e.get("xg_against")) is not None for e in est.values())
    out.append("\n## the two sides together")
    lam = None
    if ok_:
        v = {s_: (shrunk(num(e["xg_for"]) / num(e["sample_size"]), num(e["sample_size"])), shrunk(num(e["xg_against"]) / num(e["sample_size"]), num(e["sample_size"]))) for s_, e in est.items()}
        lh, la = venue_anchor(v["home"][0], v["away"][1], v["away"][0], v["home"][1])
        lam = (lh, la)
        pm = lambda k, lam_: math.exp(-lam_) * lam_ ** k / math.factorial(k)
        under = sum(pm(i, lh) * pm(j, la) for i in range(0, 12) for j in range(0, 12) if i + j <= 2)
        bt = (1 - math.exp(-lh)) * (1 - math.exp(-la))
        out.append(f"shrunk xG anchors WITH the home edge (the draw slice shows the neutral-ground pair): {home} {lh:.2f}, {away} {la:.2f}; total {lh + la:.2f}; a plain independent-goals model at these numbers gives over 2.5 {100 * (1 - under):.1f}% and both teams to score {100 * bt:.1f}% (reference only: the calculator has the final numbers and a goals pick needs 60%)")
        out.append(f"cross-links: {home} attack {v['home'][0]:.2f} meets {away} defence {v['away'][1]:.2f}; {away} attack {v['away'][0]:.2f} meets {home} defence {v['home'][1]:.2f}")
    over_sig, under_sig = [], []
    if lam and lam[0] + lam[1] >= 2.8:
        over_sig.append(f"expected goals total {lam[0] + lam[1]:.2f} is 2.8 or more")
    if lam and lam[0] + lam[1] <= 2.3:
        under_sig.append(f"expected goals total {lam[0] + lam[1]:.2f} is 2.3 or less")
    if len(st) == 2:
        if min(st[s_]["over"] for s_ in st) >= 0.6:
            over_sig.append("both sides' games reach 3 or more goals in 60% or more")
        if min(st[s_]["btts"] for s_ in st) >= 0.6:
            over_sig.append("both teams scored in 60% or more of both sides' games (a both-teams-to-score link)")
        if min(st[s_]["low2"] for s_ in st) >= 0.6:
            under_sig.append("both sides' games stay at 2 goals or fewer in 60% or more")
        if min(st[s_]["cs"] for s_ in st) >= 0.4:
            under_sig.append("both sides kept a clean sheet in 40% or more of their games")
    out.append("over signals present: " + ("; ".join(over_sig) if over_sig else "none") + "; under signals present: " + ("; ".join(under_sig) if under_sig else "none"))
    out.append("How to read it: counts over small samples, not probabilities. Argue ONE direction (over 2.5, under 2.5 or both teams to score) from the signals that agree, say which links hold (the totals AND the both-score rate AND the attack-defence links) and which you checked and found absent, and what would break it. Never use a signal that is absent.")
    return out


GROUPS = {
    "team-news": ("lineups_section", "manager_section", "replacement_section", "subs_section", "physiology_section", "fatigue_section", "player_errors_section"),
    "tactical": ("lineups_section", "role_section", "match_stat_profile", "flank_section", "scout_section", "press_section", "adjust_section", "venue_style_section", "h2h_section"),
    "stats": ("key_metrics_table", "stats_section", "match_stat_profile", "shrink_section", "rating_section"),
    "context": ("opposition_section", "underdog_strength", "ground_section", "psychology_section", "complacency_section", "form_windows_section", "fatigue_section", "h2h_section"),
    "advocate": ("key_metrics_table",),
    "home": ("key_metrics_table", "home_case_section", "underdog_strength"),               # the home advocate's slice: how the home side's games go, what the opponent concedes, the links between the two
    "away": ("key_metrics_table", "away_case_section", "underdog_strength"),
    "goals": ("key_metrics_table", "goals_case_section"),             # the goals advocate's slice: totals, both-score rates, clean sheets and the xG total
    "draw": ("key_metrics_table", "draw_section", "h2h_section", "form_windows_section"),      # the draw advocate's extra slice: counts of level finishes, low totals, narrow margins, xG-tight games and the links between the sides
    "underdog": ("key_metrics_table", "lineups_section", "underdog_section", "underdog_strength", "press_section", "player_errors_section", "match_stat_profile"),           # the underdog advocate's slice: who the underdog is from the ratings and the xG anchors, the favourite's defensive errors and its record once the opponent has scored
    "state": ("key_metrics_table", "state_section", "press_section", "player_errors_section", "match_stat_profile"),                  # the game-state advocate's slice: half-time states (who holds a lead, who comes back), goals by half, defensive errors, the shapes (a back three) and a plain reading of how the game starts
    "chaos": ("key_metrics_table", "lineups_section", "chaos_section", "player_errors_section", "underdog_strength"),        # the chaos advocate's slice: errors, keepers, set pieces and penalties, cards; what the forecast cannot see
    "decider": ("key_metrics_table", "lineups_section", "shrink_section", "underdog_strength", "press_section", "player_errors_section", "match_stat_profile"),                       # the decider's own slice: the header, the key metrics and the bookmaker odds (a benchmark only)
}
ONLY: set[str] | None = None            # set by --section: print only these groups (plus the match header and the key metrics)


def _wanted(label: str) -> bool:
    if ONLY is None:
        return True
    if label == "bookmaker odds and head to head":
        return "decider" in ONLY        # no agent but the decider ever sees the bookmaker's odds, and even there it is a post-hoc benchmark only (there is no market advocate any more)
    return label.endswith(" basics") or label == "key_metrics_table" or any(label in GROUPS.get(g, ()) for g in ONLY)


def match_stat_profile(r: dict, m: dict, ins: dict, home, away) -> list[str]:
    """What the plain match stats say, per side and against each other: shots on target (attacking efficiency and how much a defence gives up),
    saves (how busy the keeper is, so how much the defenders let through), possession and passing (can it keep the ball), corners (pressure and
    territory, and a defence that is pinned back) and fouls (a side that cannot contain the other stops attacks by fouling)."""
    out = ["", "# MATCH-STAT PROFILE (shots on target, saves, possession and passing, corners, fouls: what each says about attack, defence, the ball and containment)"]
    p = {}
    for side, name in (("home", home), ("away", away)):
        g = lambda key: d(ins.get(f"{side}_{key}"))
        sh, gk, ps, cn, fo, xg, cd, ad = (g(k) for k in ("shots_estimate", "goalkeeping_estimate", "passing_style", "corners_estimate", "fouls_estimate", "xg_estimate", "card_discipline", "advanced_stats"))
        v = {}
        ib, ob, iba, oba = (num(ad.get(k)) for k in ("shots_inside_box_for", "shots_outside_box_for", "shots_inside_box_against", "shots_outside_box_against"))
        if None not in (ib, ob) and ib + ob:
            v["in_for"] = 100 * ib / (ib + ob)
        if None not in (iba, oba) and iba + oba:
            v["in_ag"], v["box_n"] = 100 * iba / (iba + oba), num(ad.get("sample_size"))
        n = num(sh.get("sample_size"))
        if n and num(sh.get("shots_for")) and num(sh.get("shots_on_target_for")) is not None:
            v["sot"], v["acc"] = per(sh["shots_on_target_for"], n), 100 * num(sh["shots_on_target_for"]) / num(sh["shots_for"])
            if num(sh.get("shots_against")) and num(sh.get("shots_on_target_against")) is not None:
                v["sot_ag"], v["acc_ag"] = per(sh["shots_on_target_against"], n), 100 * num(sh["shots_on_target_against"]) / num(sh["shots_against"])
            if num(xg.get("sample_size")) == n and num(xg.get("actual_goals_for")) is not None and num(sh["shots_on_target_for"]):
                v["conv"] = num(xg["actual_goals_for"]) / num(sh["shots_on_target_for"])
        if num(gk.get("save_pct")) is not None and num(gk.get("sample_size")):
            v["save"], v["saves"] = num(gk["save_pct"]), per(gk.get("saves_for"), num(gk["sample_size"]))
        poss = num(d(m.get(f"{side}_team_season_stats")).get("average_ball_possession"))
        if poss is not None:
            v["poss"] = poss
        if num(ps.get("pass_accuracy_pct")) is not None:
            v["pass"], v["long"] = num(ps["pass_accuracy_pct"]), num(ps.get("long_ball_share_pct"))
        n = num(cn.get("sample_size"))
        if n and num(cn.get("corners_for")) is not None and num(cn.get("corners_against")) is not None:
            v["cf"], v["ca"] = per(cn["corners_for"], n), per(cn["corners_against"], n)
        n = num(fo.get("sample_size"))
        if n and num(fo.get("fouls_committed_for")) is not None and num(fo.get("fouls_committed_against")) is not None:
            v["fc"], v["fs"] = per(fo["fouls_committed_for"], n), per(fo["fouls_committed_against"], n)
        if num(cd.get("yellow_per_game")) is not None:
            v["yel"] = num(cd["yellow_per_game"])
        p[side] = v
        parts = []
        if "sot" in v:
            parts.append(f"attack {v['sot']:.1f} shots on target a game ({v['acc']:.0f}% of its shots on target"
                         + (f", {v['conv']:.2f} goals per shot on target, about 0.30 is normal" if "conv" in v else "") + ")")
        if "sot_ag" in v:
            parts.append(f"defence {v['sot_ag']:.1f} shots on target conceded a game (opponents hit the target with {v['acc_ag']:.0f}%)")
        if "in_for" in v or "in_ag" in v:
            parts.append("box " + ", ".join(x for x in (f"{v['in_for']:.0f}% of its shots from inside the box" if "in_for" in v else "",
                                                      f"{v['in_ag']:.0f}% of shots against from inside the box" if "in_ag" in v else "") if x)
                         + (f" ({v['box_n']:g} games)" if v.get("box_n") else ""))
        if "save" in v:
            parts.append(f"keeper {v['saves']:.1f} saves a game, {v['save']:.1f}% saved (many saves = the defenders let shots through; about 72% is normal)")
        if "poss" in v or "pass" in v:
            parts.append("ball " + ", ".join(x for x in (f"possession {v['poss']:.0f}%" if "poss" in v else "", f"pass accuracy {v['pass']:.0f}%" if "pass" in v else "",
                                                       f"long balls {v['long']:.0f}%" if v.get("long") is not None else "") if x))
        if "cf" in v:
            parts.append(f"corners {v['cf']:.1f} won / {v['ca']:.1f} conceded a game ({100 * v['cf'] / (v['cf'] + v['ca']):.0f}% share)" if v["cf"] + v["ca"] else "")
        if "fc" in v:
            parts.append(f"fouls {v['fc']:.1f} committed / {v['fs']:.1f} suffered a game" + (f", {v['yel']:.2f} yellows a game" if "yel" in v else ""))
        out.append(f"{name}: " + ("; ".join(x for x in parts if x) or "no match stats in the report"))
    h, a = p.get("home", {}), p.get("away", {})
    links = []
    for att, dfn, an, dn in ((h, a, home, away), (a, h, away, home)):
        if "sot" in att and "sot_ag" in dfn:
            links.append(f"{an} attack {att['sot']:.1f} shots on target a game meets {dn} conceding {dfn['sot_ag']:.1f}: about {(att['sot'] + dfn['sot_ag']) / 2:.1f} expected")
    for v, nm in ((h, home), (a, away)):
        if "in_ag" in v:
            links.append(f"{nm} " + ("is compact: it keeps opponents out of the box and forces long shots" if v["in_ag"] <= 55 else
                                     "is open: opponents get into its box for most of their shots" if v["in_ag"] >= 68 else "is about average at keeping shots out of its box")
                         + f" ({v['in_ag']:.0f}% of shots against from inside the box; about 60% is typical)")
    if "poss" in h and "poss" in a:
        links.append(f"possession {h['poss']:.0f}% v {a['poss']:.0f}%: " + ("both like the ball, so one must give it up" if min(h["poss"], a["poss"]) >= 52 else
                     "neither keeps the ball, an open, broken game is likelier" if max(h["poss"], a["poss"]) <= 46 else
                     f"{home if h['poss'] > a['poss'] else away} should keep the ball, {away if h['poss'] > a['poss'] else home} sits off and counters"))
    if "cf" in h and "cf" in a and h["cf"] + a["ca"] + a["cf"] + h["ca"]:
        eh, ea = (h["cf"] + a["ca"]) / 2, (a["cf"] + h["ca"]) / 2
        links.append(f"corners expected {eh:.1f} for {home} and {ea:.1f} for {away}: the side with more corners usually has the territory and the pressure")
    for v, nm in ((h, home), (a, away)):
        if "fc" in v and v["fs"] and v["fc"] / v["fs"] >= 1.15:
            links.append(f"{nm} commits {v['fc'] / v['fs']:.2f} fouls for every foul it suffers: it stops attacks by fouling (it struggles to contain), which gives free kicks near its goal and cards")
    if links:
        out.append("links: " + "; ".join(links))
    out.append("How to read it: shots on target show how efficient an attack is and how much a defence gives up; saves show how much the defenders let through "
               "(a keeper with many saves has a busy defence, not always a good one); possession and pass accuracy show whether a side can keep the ball; the share of shots from inside the box shows compactness (a compact side "
               "keeps opponents to long shots; an attack that shoots mostly from inside the box gets into good areas); corners show "
               "pressure and territory (many conceded = pinned back); fouls show containment (a side fouling far more than it is fouled cannot stop the other side cleanly). "
               "These are averages over the report's games, read the n.")
    return out


def stats_section(r: dict, m: dict, ins: dict, forms: dict, home, away) -> list[str]:
    """Underlying stats in one compact block per side: chance volume and quality, chances conceded, set pieces, luck against performance, goalkeeper."""
    out = ["", "# UNDERLYING STATS (xG, shots, shot quality, chances conceded, set pieces, luck, goalkeeper)"]
    ids = {s_: team_identity(r, m, ins, s_) for s_ in ("home", "away")}
    def xg_trend(rows):
        """xG for and against in the last 5 games with xG against the 5 before: are the underlying numbers rising or falling (sustainable results)?"""
        rr = [x for x in (rows if isinstance(rows, list) else []) if isinstance(x, dict) and num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
        if len(rr) < 4:
            return None
        k = min(5, len(rr) // 2)
        recent, older = rr[:k], rr[k:2 * k]
        avg = lambda xs, key: sum(num(x.get(key)) for x in xs) / len(xs)
        return {"n": k, "xg_r": avg(recent, "xg_for"), "xga_r": avg(recent, "xg_against"), "xg_o": avg(older, "xg_for"), "xga_o": avg(older, "xg_against")}
    for side, name in (("home", home), ("away", away)):
        me = ids[side]
        ad = d(ins.get(f"{side}_advanced_stats"))
        n = num(ad.get("sample_size"))
        gp = gap_profile(d(forms.get(side)).get("last10_overall"), m.get("kickoff_utc"))
        tr = xg_trend(d(forms.get(side)).get("last10_overall"))
        out.append(xpts_line(d(forms.get(side)).get("last10_overall"), name))
        spt = d(ins.get(f"{side}_set_piece_threat"))
        out.append(f"\n## {name}")
        out.append(f"created: {fmt(me.get('xg_for'), 2)} xG, {fmt(me.get('shots_for'))} shots, {fmt(me.get('shots_in_box_for'))} in the box, {fmt(me.get('big_chances_for'))} big chances, {fmt(me.get('xg_per_shot'), 2)} xG per shot; conceded: {fmt(me.get('xg_against'), 2)} xG, {fmt(me.get('shots_against'))} shots, {fmt(me.get('xg_per_shot_ag'), 2)} xG per shot")
        out.append(f"luck against performance (last games with xG): goals {fmt(gp.get('gf_vs_xg'), 2)} against xG scored, {fmt(gp.get('ga_vs_xg'), 2)} against xG conceded; goalkeeper save {fmt(me.get('save_pct'), 0)}% with {fmt(me.get('sot_faced'))} shots on target faced a game ({fmt(me.get('saves'))} saves)")
        out.append("xG / xGA trend (are the results sustainable?): " + (f"last {tr['n']} games xG {tr['xg_r']:.2f} for / {tr['xga_r']:.2f} against against the {tr['n']} before {tr['xg_o']:.2f} / {tr['xga_o']:.2f} ({'creating more' if tr['xg_r'] - tr['xg_o'] >= 0.25 else 'creating less' if tr['xg_r'] - tr['xg_o'] <= -0.25 else 'creating the same'}, {'conceding more' if tr['xga_r'] - tr['xga_o'] >= 0.25 else 'conceding less' if tr['xga_r'] - tr['xga_o'] <= -0.25 else 'conceding the same'})" if tr else "too few games with xG for a trend"))
        out.append(f"set pieces: xG for {fmt(ad.get('set_piece_xg_for'), 2)} and against {fmt(ad.get('set_piece_xg_against'), 2)} over {fmt(n, 0)} games; corners {fmt(spt.get('corners_per_game'))} a game; opponent aerial win {fmt(spt.get('opponent_aerial_win_pct'), 0)}%; crosses {fmt(per(ad.get('crosses_for'), n))} for / {fmt(per(ad.get('crosses_against'), n))} against a game")
    for side, name in (("home", home), ("away", away)):
        fm = d(forms.get(side))
        hs = d(fm.get("half_split"))
        h1, h2 = (num(hs.get("first_half_goals_for")) or 0) + (num(hs.get("first_half_goals_against")) or 0), (num(hs.get("second_half_goals_for")) or 0) + (num(hs.get("second_half_goals_against")) or 0)
        out.append(f"{name} - scoring and concession profile: clean sheets {fm.get('clean_sheet_share_pct', 'n/a')}%, failed to score {fm.get('failed_to_score_share_pct', 'n/a')}%, both teams scored {fm.get('btts_share_pct', 'n/a')}%, over 2.5 {fm.get('over25_share_pct', 'n/a')}%; "
                   + (f"timing: {h1:g} goals in first halves (for + against) and {h2:g} in second halves over {hs.get('sample_size')} games" + (" - decided late" if h2 >= 1.8 * max(h1, 1) else "") + (f"; second-half goals for {hs.get('second_half_goals_for')} against {hs.get('second_half_goals_against')}" if hs else "") if hs else "timing: no half split") + " (minute-level timing and final-15-minute figures are not in the data)")
    sh, sa = per(d(ins.get("home_advanced_stats")).get("set_piece_xg_for"), num(d(ins.get("home_advanced_stats")).get("sample_size"))), per(d(ins.get("away_advanced_stats")).get("set_piece_xg_against"), num(d(ins.get("away_advanced_stats")).get("sample_size")))
    ah, ag = per(d(ins.get("away_advanced_stats")).get("set_piece_xg_for"), num(d(ins.get("away_advanced_stats")).get("sample_size"))), per(d(ins.get("home_advanced_stats")).get("set_piece_xg_against"), num(d(ins.get("home_advanced_stats")).get("sample_size")))
    if None not in (sh, sa, ah, ag):
        e1, e2 = (sh + sa) / 2, (ah + ag) / 2
        out.append(f"\nSET-PIECE EDGE (a separate edge in tight games): {home}'s set-piece xG for {sh:.2f} v {away}'s against {sa:.2f} a game = {e1:.2f} expected; {away}'s for {ah:.2f} v {home}'s against {ag:.2f} = {e2:.2f}; edge {'to ' + home if e1 - e2 >= 0.1 else 'to ' + away if e2 - e1 >= 0.1 else 'none (level)'} ({abs(e1 - e2):.2f} xG a game)")
    for side, name in (("home", home), ("away", away)):
        ad = d(ins.get(f"{side}_advanced_stats"))
        n = num(ad.get("sample_size"))
        pg = lambda k: per(ad.get(k), n)
        def share(a, b):
            x, y = num(ad.get(a)), num(ad.get(b))
            return None if x is None or y is None or x + y == 0 else 100 * x / (x + y)
        errs = d(ins.get(f"{side}_defensive_errors_estimate"))
        out.append(f"{name} - location and quality: {fmt(share('shots_inside_box_for', 'shots_outside_box_for'), 0)}% of its shots from inside the box ({fmt(share('shots_inside_box_against', 'shots_outside_box_against'), 0)}% of those it concedes); xA {fmt(pg('xa_for'), 2)} for / {fmt(pg('xa_against'), 2)} against a game (chance-creation quality); "
                   f"turnovers (times dispossessed) {fmt(pg('dispossessed_for'))} a game v {fmt(pg('dispossessed_against'))} forced on opponents (press resistance proxy); errors leading to a shot {fmt(pg('errors_lead_to_shot_for'), 2)} / against {fmt(pg('errors_lead_to_shot_against'), 2)}, to a goal {fmt(pg('errors_lead_to_goal_for'), 2)} / against {fmt(pg('errors_lead_to_goal_against'), 2)} a game; "
                   f"territory: field tilt {fmt(ad.get('field_tilt_pct'), 0)}%, final-third entries {fmt(pg('final_third_entries_for'), 0)} v {fmt(pg('final_third_entries_against'), 0)} a game, touches in the box {fmt(pg('touches_in_box_for'), 0)} v {fmt(pg('touches_in_box_against'), 0)}")
    out.append("How to read it: compare created against conceded for both sides, shot quality (xG per shot) not just volume, whether results sit above or below xG (regression), the keeper's save rate against the shots on target he faces, and set-piece xG for and against.")
    return out


def xpoints(xg_for: float, xg_against: float) -> float:
    """Expected points of one match from its two xG values (independent Poisson goals): 3 x P(win) + P(draw)."""
    import math
    def pois(k, lam):
        return math.exp(-lam) * lam ** k / math.factorial(k)
    pw = pd = 0.0
    for i in range(0, 11):
        for j in range(0, 11):
            p = pois(i, max(xg_for, 0.05)) * pois(j, max(xg_against, 0.05))
            if i > j:
                pw += p
            elif i == j:
                pd += p
    return 3 * pw + pd


def xpts_line(rows, name: str) -> str:
    rr = [x for x in (rows if isinstance(rows, list) else []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L") and num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
    if len(rr) < 3:
        return f"{name}: too few games with xG for expected points"
    actual = sum({"W": 3, "D": 1, "L": 0}[x["result"]] for x in rr)
    exp = sum(xpoints(num(x["xg_for"]), num(x["xg_against"])) for x in rr)
    gap = actual - exp
    return f"{name}: xPTS {exp:.1f} v actual {actual} points over {len(rr)} games with xG ({gap:+.1f}: " + ("OVERPERFORMING its chances, expect a drop" if gap >= 2 else "UNDERPERFORMING its chances, expect results to return to the chance level, not beyond it" if gap <= -2 else "results match the underlying numbers") + ")"


ELO_ALIASES = {"turkiye": "turkey", "bosniaherzegovina": "bosniaandherzegovina", "czechrepublic": "czechia", "republicofireland": "ireland", "usa": "unitedstates", "korearepublic": "southkorea", "drcongo": "drcongo"}


def load_elo() -> dict:
    """National-team Elo by normalised name from the seed file, found without importing the project: $FOOTBALL_DATA_DIR, then data/ beside the backend, then backend/data."""
    import os
    here = Path(__file__).resolve()
    names = [Path(os.environ["FOOTBALL_DATA_DIR"]) / "national-elo.json"] if os.environ.get("FOOTBALL_DATA_DIR") else []
    names += [p / "data" / "national-elo.json" for p in here.parents[:7]]
    for p in names:
        try:
            ratings = json.loads(p.read_text(encoding="utf-8")).get("ratings") or {}
            if ratings:
                return {norm_name("".join(c for c in unicodedata.normalize("NFKD", k) if not unicodedata.combining(c)).replace("&", "and")): float(v) for k, v in ratings.items() if isinstance(v, (int, float))}
        except (OSError, ValueError, AttributeError):
            continue
    return {}


def elo_of(elo: dict, team) -> float | None:
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(team or "")) if not unicodedata.combining(c))        # Türkiye -> Turkiye
    k = norm_name(plain.replace("&", "and"))
    return elo.get(ELO_ALIASES.get(k, k)) if k else None


def opposition_section(m: dict, ins: dict, forms: dict, home, away) -> list[str]:
    """Strength of the opposition behind each side's last 5 and 10 results, results against stronger and weaker sides, behaviour against similar styles, and the referee."""
    out = ["", "# STRENGTH OF OPPOSITION, SIMILAR OPPONENTS AND THE REFEREE (results mean little without who they came against)"]
    elo = load_elo()
    ownelo = {"home": class_elo(ins, "home"), "away": class_elo(ins, "away")}
    for side, name in (("home", home), ("away", away)):
        f = d(forms.get(side))
        rows = [x for x in (f.get("last10_overall") or []) if isinstance(x, dict) and x.get("result") in ("W", "D", "L")]
        club = num(d(ins.get(f"{side}_club_elo")).get("elo"))
        club_mode = club is not None and any(num(x.get("opponent_club_elo")) is not None for x in rows)      # clubs: each opponent's ClubElo, from the report
        rate = (lambda x: num(x.get("opponent_club_elo"))) if club_mode else (lambda x: elo_of(elo, x.get("opponent")))
        if not club_mode and not elo:
            out.append(f"{name}: no opponent ratings (no ClubElo for the opponents and no national Elo file), so the opposition strength cannot be computed (judge it from the opponents' names)")
            continue
        rated = [(rate(x), x) for x in rows]
        known = [(e, x) for e, x in rated if e is not None]
        def avg(rs):
            es = [e for e, _ in rs]
            return None if not es else sum(es) / len(es)
        a5, a10 = avg(known[:5]), avg(known)
        me = club if club_mode else ownelo[side]
        stronger = [x["result"] for e, x in known if me is not None and e > me]
        weaker = [x["result"] for e, x in known if me is not None and e <= me]
        pts = lambda rs: None if not rs else sum({"W": 3, "D": 1, "L": 0}[r] for r in rs) / len(rs)
        fmtp = lambda rs: "no games" if not rs else f"{pts(rs):.2f} points a game in {len(rs)}"
        out.append(f"{name} ({'ClubElo' if club_mode else 'Elo'} {fmt(me, 0)}): opponents' average {'ClubElo' if club_mode else 'Elo'} last 5 {fmt(a5, 0)}, last 10 {fmt(a10, 0)} ({len(known)} of {len(rows)} opponents rated); against stronger sides {fmtp(stronger)}; against weaker or equal {fmtp(weaker)}"
                   + ("  <-- form built against weaker opposition" if a10 is not None and me is not None and a10 < me - 80 else "  <-- form built against stronger opposition" if a10 is not None and me is not None and a10 > me + 80 else ""))
        xrows = [(rate(x), x) for x in rows if num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
        xrows = [(e, x) for e, x in xrows if e is not None and me is not None]
        if len(xrows) >= 3:
            adj_for = [num(x["xg_for"]) - 0.0011 * (me - e) for e, x in xrows]          # about 0.11 goals per 100 Elo points: weaker opposition inflates raw xG
            adj_ag = [num(x["xg_against"]) + 0.0011 * (me - e) for e, x in xrows]
            raw_for, raw_ag = sum(num(x["xg_for"]) for _, x in xrows) / len(xrows), sum(num(x["xg_against"]) for _, x in xrows) / len(xrows)
            out.append(f"  opponent-adjusted xG (rough, by Elo, {len(xrows)} games with xG): created {raw_for:.2f} raw -> {sum(adj_for) / len(adj_for):.2f} adjusted, conceded {raw_ag:.2f} raw -> {sum(adj_ag) / len(adj_ag):.2f} adjusted (an adjustment of 0.11 goals per 100 Elo points of opposition strength: use it to temper the raw xG, not replace it)")
        if known and me is not None:
            wts = [min(1.5, max(0.5, 1 + (e - me) / 400)) for e, _ in known]
            wpts = sum(w * {"W": 3, "D": 1, "L": 0}[x["result"]] for w, (_, x) in zip(wts, known)) / sum(wts)
            rpts = sum({"W": 3, "D": 1, "L": 0}[x["result"]] for _, x in known) / len(known)
            out.append(f"  difficulty-weighted form: {rpts:.2f} raw points a game -> {wpts:.2f} when each result is weighted by the opponent's strength (a win over a stronger side counts up to 1.5x, over a weaker side down to 0.5x)")
        pm = d(ins.get(f"{side}_possession_matchup"))
        if pm:
            out.append(f"  similar-opponent comparison: {pm.get('high_opponent_possession_ppg', 'n/a')} points a game against high-possession opponents ({pm.get('high_opponent_possession_sample_size', '?')} games) v {pm.get('other_ppg', 'n/a')} against the rest ({pm.get('other_sample_size', '?')}); compare with how today's opponent plays")
    rs = d(m.get("referee_stats"))
    rn = d(ins.get("referee_card_risk_note"))
    out.append(f"referee: {m.get('referee') or 'not named'}; {rs.get('games', '?')} games, {rs.get('yellow_cards_per_game', '?')} yellows and {rs.get('fouls_per_game', '?')} fouls a game, {rs.get('red_cards_per_game', '?')} reds, penalties awarded {rs.get('penalties_awarded') if rs.get('penalties_awarded') is not None else 'unknown'}"
               + ("; ELEVATED card referee" if rn.get("elevated_card_referee") else "") + (f"; flagged players: {', '.join(str(p.get('name')) for p in (rn.get('flagged_players') or [])[:3] if isinstance(p, dict))}" if rn.get("flagged_players") else ""))
    out.append("How to read it: weight the last 5 to 10 results by who they came against; a side that wins only against weaker opposition is overrated, one that holds stronger sides is underrated; a high-card referee raises the chance of a booking or red and slows the tempo.")
    return out


def _guard(label: str, fn) -> None:
    """Run one part of the sheet; if a corrupt field breaks it, say so and carry on with the rest instead of losing the whole sheet."""
    import contextlib
    if not _wanted(label):
        return
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn()
        sys.stdout.write(buf.getvalue())
    except Exception as e:                                   # noqa: BLE001 - any bad field must not stop the sheet
        print(f"\n# {label}: unavailable ({type(e).__name__}); treat it as unknown, not zero")


def own_side_is_home(r: dict, home, away) -> bool:
    """Which side is the report ABOUT? The short name in r['team'] ('Tottenham') rarely equals the match name ('Tottenham Hotspur'), so match the profiles' own team names first
    and fall back to containment; getting this wrong crosses the two squads, forms and profiles. Ambiguous -> the home side."""
    h, a = norm(home), norm(away)
    def fit(x, n):
        return 2 if x and x == n else 1 if x and n and (x in n or n in x) else 0
    own = [norm(d(r.get("teamProfile")).get("team_name")), norm(r.get("team"))]
    opp = norm(d(r.get("opponentProfile")).get("team_name"))
    sh, sa = max(fit(c, h) for c in own), max(fit(c, a) for c in own)
    if sh != sa:
        return sh > sa
    oh, oa = fit(opp, h), fit(opp, a)                              # tie: the OTHER profile names the opposite side
    if oh != oa:
        return oa > oh
    return True


def strip_market(r: dict) -> dict:
    """The report without any bookmaker price or the scraper's market-blended prediction (blind.py's rule)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("blind_for_facts", Path(__file__).with_name("blind.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.blind(r)[0]


def main(path: str, deep: bool = False) -> int:
    try:
        r = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read the report: {e}", file=sys.stderr)
        return 2
    if not isinstance(r, dict):
        print("the file does not hold a JSON report object", file=sys.stderr)
        return 2
    r = strip_market(r)                                          # market-independent: no price or market-blended prediction ever reaches the sheet, whatever report it is given
    set_venue(r)
    m, ins = d(r.get("match")), d(r.get("insights"))
    _table_note = drop_unformed_table(ins)
    home, away = m.get("home_team"), m.get("away_team")
    own_home = own_side_is_home(r, home, away)                   # the report is about one team: its form is "form" and its squad "teamProfile"; the other side's are "opponentForm" and "opponentProfile"
    forms = {"home": r.get("form") if own_home else r.get("opponentForm"), "away": r.get("opponentForm") if own_home else r.get("form")}
    _xg_notes = prefer_larger_xg_sample(ins, forms, {"home": home, "away": away})
    profiles = {"home": d(r.get("teamProfile")) if own_home else d(r.get("opponentProfile")), "away": d(r.get("opponentProfile")) if own_home else d(r.get("teamProfile"))}
    tpn, opn = d(r.get("teamProfile")).get("team_name"), d(r.get("opponentProfile")).get("team_name")
    named = norm(tpn) and norm(opn) and ((norm(tpn) in norm(home) or norm(home) in norm(tpn)) != (norm(tpn) in norm(away) or norm(away) in norm(tpn)))
    print(f"# {home} (home label) v {away} (away label)\ncompetition: {m.get('competition')}; kickoff {m.get('kickoff_utc')}; status {m.get('status')}")
    print(f"SIDE CHECK: squads and forms assigned by name: {tpn or 'n/a'} -> {'home' if own_home else 'away'}, {opn or 'n/a'} -> {'away' if own_home else 'home'}" + ("" if named else "  <-- WARNING: the profile names do not clearly match the two teams, so squads and forms may be crossed: check a player or two against the right club"))
    print(f"venue country: {m.get('venue_country')} (home team's country {m.get('home_team_country')}, away team's {m.get('away_team_country')}); neutral flag {m.get('neutral')}")
    print("HOME EDGE: the home side gets the edge only when the venue is in ITS country; a venue in a third country is neutral; in the away team's country the edge goes to the away team.")
    print(f"lineups confirmed: {bool(m.get('lineup_confirmed'))}")
    _leak = club_elo_after_kickoff(ins, m.get("kickoff_utc"))
    if _leak:
        print(_leak)
    if _table_note:
        print(_table_note)
    for _n in _xg_notes:
        print(_n)
    _h, _label = news_window(r, m)
    if _label:
        print(_label)
    def _side(side, name):
            form = d(forms[side])
            rows = next((form[k] for k in ("last10_overall", "last5_overall", "last20_overall") if form.get(k)), [])
            print(f"\n## {name} ({side})\nlast results (newest first, this team's goals first):")
            print("\n".join(form_lines(rows)))
            print(xg_line(ins.get(f"{side}_xg_estimate")))
            _est = d(ins.get(f"{side}_xg_estimate"))
            _xr = [x for x in rows if isinstance(x, dict) and num(x.get("xg_for")) is not None and num(x.get("xg_against")) is not None]
            if _xr and num(_est.get("sample_size")) and len(_xr) != int(num(_est.get("sample_size"))):
                print(f"xG CONFLICT: the match rows below carry xG for {len(_xr)} games (for {sum(num(x['xg_for']) for x in _xr) / len(_xr):.2f}, against {sum(num(x['xg_against']) for x in _xr) / len(_xr):.2f}) but the xG estimate above covers {int(num(_est.get('sample_size')))} games; the two sources disagree and which is right is unknown: the anchors use the estimate, so treat both as thin")
            _rot = d(ins.get(f"{side}_rotation"))
            _days = {str(x.get("date") or "")[:10] for x in (d(forms[side]).get("last20_overall") or rows) if isinstance(x, dict)}
            _lost = [str(_rot.get(k))[:10] for k in ("last_match_date", "previous_match_date") if _rot.get(k) and str(_rot.get(k))[:10] not in _days]
            if _lost and _days:
                print(f"FORM ROWS INCOMPLETE: the lineup data shows a match on {', '.join(_lost)} that is not in the result rows, so the record, the streaks and the rest days may miss a game; treat them as a lower bound on what was played")
            elo = d(ins.get(f"{side}_elo_rating"))
            _ce = d(ins.get(f"{side}_club_elo")).get("elo")
            _proper = elo.get("sample_source") == "eloratings.net"
            print(f"Elo: {elo.get('elo')} (source {elo.get('sample_source')}; 'eloratings.net' is a proper national-team rating, anything else is form-only" + ("" if _proper else ": do NOT read a gap between two form-only numbers as class") + ")" + (f"; ClubElo (class): {_ce}" if _ce is not None else ""))
            sq = d(ins.get(f"{side}_squad_strength"))
            print(f"squad market value: total {sq.get('total_value')}, attack {sq.get('attack_value')}, midfield {sq.get('midfield_value')}, defence {sq.get('defense_value')}, goalkeeper {sq.get('goalkeeper_value')}")
            st = d(m.get(f"{side}_team_standing"))
            if st and num(st.get("played")) == 0:
                print("table: no games played in this competition yet (the listed position is not a ranking)")
            elif st:
                print(f"table: position {st.get('position')}/{st.get('total_teams')}, {st.get('points')} pts from {st.get('played')} played, GD {st.get('goal_diff')}")
            rot = d(ins.get(f"{side}_rotation"))
            print(f"rotation between this side's LAST TWO matches ({str(rot.get('previous_match_date') or '?')[:10]} to {str(rot.get('last_match_date') or '?')[:10]}; NOT today's XI, which is unknown until the lineups are out): changed {rot.get('changed_players', '?')} of {rot.get('starting_xi_size', 11)} starters, formation {rot.get('previous_formation', '?')} -> {rot.get('last_formation', '?')}" if rot else "rotation: not in the report")
            miss = [x for x in (m.get(f"{side}_missing_players") or []) if isinstance(x, dict)]
            inj = {norm(x.get("name")): x for x in (profiles[side].get("injuries") or []) if isinstance(x, dict)}
            squad = {norm(p.get("name")): p for p in (profiles[side].get("squad") or []) if isinstance(p, dict)}
            print("missing players (role and value shown when the report knows them):")
            pres = {norm(x.get("name")): x for x in (ins.get(f"{side}_presence") or []) if isinstance(x, dict)}
            for x in miss or []:
                k = norm(x.get("name")); p = squad.get(k) or inj.get(k) or {}
                print(f"  - {x.get('name')}: {x.get('description') or x.get('absence_type')}, back {str(x.get('expected_return') or '?')[:10]}; role {p.get('role') or 'UNKNOWN'}, value {p.get('market_value') or 'unknown'}" + ("" if k in squad else "; NOT in the squad list: starter status unknown, never call him a key player")
                      + doubtful_tag(x.get("description"), d(inj.get(k)).get("injury"), d(pres.get(k)).get("reason")))
            if not miss:
                print("  (none listed: unknown, not zero)")
    for side, name in (("home", home), ("away", away)):
        _guard(f"{name} basics", lambda side=side, name=name: _side(side, name))
    def _challenge(mk: list[float]):
        """The data-only challenger: the shrunk xG anchors turned into 1X2 probabilities and set against the market's fair prices, so the decider sees where the data disagrees with the price."""
        est = {s_: d(ins.get(f"{s_}_xg_estimate")) for s_ in ("home", "away")}
        if not all(num(e.get("sample_size")) and num(e.get("xg_for")) is not None and num(e.get("xg_against")) is not None for e in est.values()):
            print("CHALLENGE THE MARKET: no xG sample for one side, so the data cannot challenge the price (say so in the Market challenge line)")
            return
        v = {s_: (shrunk(num(e["xg_for"]) / num(e["sample_size"]), num(e["sample_size"])), shrunk(num(e["xg_against"]) / num(e["sample_size"]), num(e["sample_size"]))) for s_, e in est.items()}
        lh, la = venue_anchor(v["home"][0], v["away"][1], v["away"][0], v["home"][1])
        pm = lambda k, lam_: math.exp(-lam_) * lam_ ** k / math.factorial(k)
        ph = sum(pm(i, lh) * pm(j, la) for i in range(12) for j in range(12) if i > j)
        pd = sum(pm(i, lh) * pm(j, la) for i in range(12) for j in range(12) if i == j)
        pa = sum(pm(i, lh) * pm(j, la) for i in range(12) for j in range(12) if i < j)
        s_ = ph + pd + pa
        mine = [100 * ph / s_, 100 * pd / s_, 100 * pa / s_]
        gaps = [a_ - b_ for a_, b_ in zip(mine, mk)]
        big = max(range(3), key=lambda i: abs(gaps[i]))
        names = (home, "draw", away)
        print(f"CHALLENGE THE MARKET (the odds flow into your anchor, but you may challenge them; this is the data-only view, no odds used: the shrunk xG anchors {lh:.2f}-{la:.2f} as plain independent goals): home {mine[0]:.1f}% / draw {mine[1]:.1f}% / away {mine[2]:.1f}% against the market's {mk[0]:.1f}% / {mk[1]:.1f}% / {mk[2]:.1f}%; "
              f"the data disagrees most on {names[big]} ({gaps[big]:+.1f} points). It ignores home advantage, squad quality and news, and tested worse than the market alone (a method note of this sheet, not a report fact and not your own knowledge), so it is a prompt to look, not a verdict: write a 'Market challenge:' line saying whether the evidence (a note, an advocate, a number) supports moving the price on that outcome, by how many points, or why you kept the market's.")

    def _odds():
        o = d(m.get("betting_odds")) or d(m.get("sofascore_betting_odds"))
        fair = [o.get(k) for k in ("home_win_fair_pct", "draw_fair_pct", "away_win_fair_pct")]
        if not all(num(v) is not None for v in fair):
            raw = [o.get(k) for k in ("home_win_odds", "draw_odds", "away_win_odds")]
            fair = [100 / v for v in raw] if all(num(v) is not None and v > 1 for v in raw) else None
        if fair:
            t = sum(fair)
            print(f"\nBOOKMAKER ODDS (the market's fair prices, margin removed: the ANCHOR for your expected goals, see calc.py --market; move away only for named evidence): home {100 * fair[0] / t:.1f}% / draw {100 * fair[1] / t:.1f}% / away {100 * fair[2] / t:.1f}%")
            _challenge([100 * x / t for x in fair])
        else:
            print("\nno bookmaker odds in the report")
        ou = [o.get(k) for k in ("over_2_5_fair_pct", "under_2_5_fair_pct")]
        if all(num(v) is not None for v in ou):
            print(f"MARKET TOTALS (fair, margin removed): over 2.5 {num(ou[0]):.1f}% / under 2.5 {num(ou[1]):.1f}%: compare with your own total; if the 1X2 and the total tell different stories, find out why")
        h2h = d(m.get("head_to_head_summary"))
        if h2h:
            print(f"head to head (weak evidence): {h2h}")
    _guard("bookmaker odds and head to head", _odds)
    _guard("key_metrics_table", lambda: print("\n".join(key_metrics_table(r, m, ins, home, away, forms, profiles))))
    _guard("role_section", lambda: print("\n".join(role_section(r, m, ins, home, away, profiles))))
    m = dict(m, _insights=ins)
    _guard("h2h_section", lambda: print("\n".join(h2h_section(m, home, away))))
    _guard("form_windows_section", lambda: print("\n".join(form_windows_section(m, forms, home, away))))
    _guard("opposition_section", lambda: print("\n".join(opposition_section(m, ins, forms, home, away))))
    _guard("ground_section", lambda: print("\n".join(ground_section(m, ins, forms, home, away))))
    _guard("shrink_section", lambda: print("\n".join(shrink_section(r, m, ins, home, away, forms))))
    _guard("draw_section", lambda: print("\n".join(draw_section(r, m, ins, home, away, forms))))
    _guard("lineups_section", lambda: print("\n".join(lineups_section(path))))
    _guard("underdog_section", lambda: print("\n".join(underdog_section(r, m, ins, home, away, forms))))
    _guard("underdog_strength", lambda: print("\n".join(underdog_strength(r, m, ins, home, away, forms))))
    _guard("state_section", lambda: print("\n".join(state_section(r, m, ins, home, away, forms))))
    _guard("goals_case_section", lambda: print("\n".join(goals_case_section(r, m, ins, home, away, forms))))
    _guard("home_case_section", lambda: print("\n".join(side_case_section(r, m, ins, home, away, forms, "home"))))
    _guard("away_case_section", lambda: print("\n".join(side_case_section(r, m, ins, home, away, forms, "away"))))
    _guard("rating_section", lambda: print("\n".join(rating_section(home, away, profiles))))
    _guard("flank_section", lambda: print("\n".join(flank_section(m, ins, home, away, profiles))))
    _guard("psychology_section", lambda: print("\n".join(psychology_section(m, ins, forms, home, away))))
    _guard("fatigue_section", lambda: print("\n".join(fatigue_section(m, ins, forms, home, away))))
    _guard("complacency_section", lambda: print("\n".join(complacency_section(m, ins, forms, home, away, profiles))))
    _guard("manager_section", lambda: print("\n".join(manager_section(r, m, ins, forms, home, away, profiles))))
    _guard("venue_style_section", lambda: print("\n".join(venue_style_section(m, ins, forms, home, away))))
    _guard("stats_section", lambda: print("\n".join(stats_section(r, m, ins, forms, home, away))))
    _guard("match_stat_profile", lambda: print("\n".join(match_stat_profile(r, m, ins, home, away))))
    _guard("subs_section", lambda: print("\n".join(subs_section(m, home, away, profiles))))
    _guard("scout_section", lambda: print("\n".join(scout_section(r, m, ins, forms, home, away, profiles))))
    _guard("press_section", lambda: print("\n".join(press_section(r, m, ins, home, away))))
    _guard("player_errors_section", lambda: print("\n".join(player_errors_section(m, profiles, home, away, ins))))
    _guard("chaos_section", lambda: print("\n".join(chaos_section(m, ins, home, away))))
    _guard("adjust_section", lambda: print("\n".join(adjust_section(r, m, ins, forms, home, away, profiles))))
    _guard("replacement_section", lambda: print("\n".join(replacement_section(m, profiles, home, away))))
    _guard("physiology_section", lambda: print("\n".join(physiology_section(r, m, ins, home, away, forms, profiles, own_home))))
    if deep:
        _guard("deep data", lambda: print("\n".join(deep_section(r, m, ins, home, away, profiles))))
    else:
        print("\n# DEEP DATA omitted (about 14 KB of raw JSON that the sections above already summarise): run `python3 scripts/facts.py report.json --deep` for it, or open the report JSON for one field.")
    return 0


class _ShortHints(io.TextIOBase):
    """Keeps only the first sentence of each 'How to read it' hint (the full wording lives in SKILL.md) unless the whole sheet is asked for."""

    def __init__(self, out):
        self.out = out

    def write(self, text):
        def cut(ln):
            if ln.startswith("How to read it:"):
                return ln if len(ln) <= 100 else ln[:100].rsplit(" ", 1)[0] + " ... (the full rule is in SKILL.md)"
            if ln.startswith("# ") and " (" in ln and len(ln) > 90:
                return ln.split(" (", 1)[0]                  # the instruction in the heading lives in SKILL.md
            return ln
        return self.out.write("\n".join(cut(ln) for ln in text.split("\n")))

    def flush(self):
        self.out.flush()


if __name__ == "__main__":
    argv = list(sys.argv[1:])
    if "--section" in argv:                                   # --section team-news,tactical : a slice for a specialist (no bookmaker odds)
        k = argv.index("--section")
        wanted = argv[k + 1].split(",") if k + 1 < len(argv) else []
        if not wanted or any(g not in GROUPS for g in wanted):
            print(f"usage: --section needs one or more of: {', '.join(GROUPS)} (comma separated)", file=sys.stderr)
            sys.exit(2)
        ONLY = set(wanted)
        del argv[k:k + 2]
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    if len(args) != 1 or flags - {"--deep", "--full"}:
        print("usage: python3 facts.py report.json [--deep] [--full] [--section team-news,tactical,stats,context,advocate,home,away,draw,goals,underdog,state,market,decider]   (--deep adds the raw DEEP DATA; --full keeps the long hints; --section prints a slice for a specialist, without odds)", file=sys.stderr)
        sys.exit(2)
    if "--full" not in flags:
        sys.stdout = _ShortHints(sys.stdout)
    sys.exit(main(args[0], deep="--deep" in flags))
