"""Rebuild the main figures straight from report.json and look for them in the sheet slices of a run (an audit, not part of an analysis). Usage: verify_sheet.py report.json run_dir. Covers results, goals per game, xG (estimate v match rows), squad value, Elo, rotation, table, missing players, keeper, formation and match fields; not shots, big chances, passing, aerials or set pieces."""
import json, re, sys, glob, unicodedata
rep = json.load(open(sys.argv[1])); run = sys.argv[2]
m = rep["match"]; ins = rep["insights"]
sheet = open(run + "/evidence/advocate.md").read()
allsheet = " ".join(open(f).read() for f in glob.glob(run + "/evidence/*.md"))
def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())
rows = []
def chk(name, ok, detail=""):
    rows.append(("ok" if ok else "DIFF", name, detail))
# which side is the report's own team
own_is_away = norm(rep["team"]) == norm(m["away_team"])
forms = {"away": rep["form"], "home": rep["opponentForm"]} if own_is_away else {"home": rep["form"], "away": rep["opponentForm"]}
profs = {"away": rep["teamProfile"], "home": rep["opponentProfile"]} if own_is_away else {"home": rep["teamProfile"], "away": rep["opponentProfile"]}
sec = {"home": sheet.split("## ")[1], "away": sheet.split("## ")[2]}
for side in ("home", "away"):
    f = forms[side]; rws = f["last10_overall"]; s = sec[side]
    name = m[side + "_team"]
    chk(f"{side} section is the right club (profile name)", norm(profs[side]["team_name"]) == norm(name) or norm(name) in norm(profs[side]["team_name"]) or norm(profs[side]["team_name"]) in norm(name), f"{profs[side]['team_name']} v {name}")
    # results lines
    lines = [l.strip() for l in s.split("xG per game")[0].splitlines() if re.match(r"\s+\d{4}-\d\d-\d\d [WDL] ", l)]
    bad = []
    for x, l in zip(rws, lines):
        h, a = [int(v) for v in x["scoreline"].split("-")]
        gf, ga = (h, a) if x["venue"] != "away" else (a, h)
        want = f"{x['date'][:10]} {x['result']} {gf}-{ga} v "
        if want not in l or norm(x["opponent"])[:6] not in norm(l):
            bad.append((want, l[:60]))
        res = "W" if gf > ga else "L" if gf < ga else "D"
        if res != x["result"]:
            bad.append(("result letter vs score", x["date"], x["result"], gf, ga))
    chk(f"{side} last results match JSON (count {len(rws)} v sheet {len(lines)})", not bad and len(rws) == len(lines), str(bad[:2]))
    # per game goals
    gfs = [ (int(x['scoreline'].split('-')[0]) if x['venue']!='away' else int(x['scoreline'].split('-')[1])) for x in rws]
    gas = [ (int(x['scoreline'].split('-')[1]) if x['venue']!='away' else int(x['scoreline'].split('-')[0])) for x in rws]
    pts = sum(3 if x["result"] == "W" else 1 if x["result"] == "D" else 0 for x in rws)
    chk(f"{side} goals/game from rows {sum(gfs)/len(rws):.2f} / {sum(gas)/len(rws):.2f}, JSON field {f['goals_for_per_game']}/{f['goals_against_per_game']}", abs(sum(gfs)/len(rws) - f["goals_for_per_game"]) < 0.06 and abs(sum(gas)/len(rws) - f["goals_against_per_game"]) < 0.06)
    km = re.search(r"goals scored per game \(same games\) \| ([\d.]+) \| ([\d.]+)", sheet)
    # xG
    xs = [(x["xg_for"], x["xg_against"]) for x in rws if x.get("xg_for") is not None]
    est = ins[f"{side}_xg_estimate"]
    if len(xs) > est["sample_size"] and "XG SOURCE: " + m[f"{side}_team"] in sheet:      # the sheet switched this side to the larger sample, the rows
        est = {"sample_size": len(xs), "xg_for": sum(a for a, _ in xs), "xg_against": sum(b for _, b in xs)}
    chk(f"{side} the sheet flags the xG conflict when the rows carry other games than the estimate ({len(xs)} v {est['sample_size']})", len(xs) in (0, est["sample_size"]) or "xG CONFLICT" in s)      # rows with no xG at all cannot conflict
    xl = re.search(r"xG per game: for ([\d.]+), against ([\d.]+) over (\d+) games", s)
    chk(f"{side} sheet xG line equals JSON estimate", bool(xl) and abs(float(xl[1]) - est["xg_for"]/est["sample_size"]) < 0.02 and int(xl[3]) == est["sample_size"], xl.group(0) if xl else "none")
    # squad value
    sq = [p for p in profs[side]["squad"] if isinstance(p, dict)]
    tot = sum(p.get("market_value") or 0 for p in sq)
    sv = re.search(r"squad market value: total (\d+)", s)
    chk(f"{side} squad value: sum of players {tot} v sheet {sv.group(1) if sv else None}", bool(sv) and abs(int(sv.group(1)) - tot) <= max(1, 0.001 * tot) , "sheet total may use a different field" )
    # Elo
    e = ins[f"{side}_elo_rating"]
    chk(f"{side} Elo {e['elo']} ({e['sample_source']}) on sheet", f"Elo: {e['elo']}" in s)
    ce = (ins.get(f"{side}_club_elo") or {}).get("elo")
    chk(f"{side} ClubElo {ce} on sheet", ce is None or f"ClubElo (class): {ce}" in s)
    # rotation
    rot = ins[f"{side}_rotation"]["changed_players"]
    chk(f"{side} rotation changed {rot}", f"'changed_players': {rot}," in s)
    # standing
    st = m.get(f"{side}_team_standing") or {}
    if st.get("played") == 0:                                  # a table with no games is not printed as a position
        chk(f"{side} table not formed (0 played)", "table: no games played in this competition yet" in s)
    else:
        chk(f"{side} table {st.get('position')}/{st.get('total_teams')}, {st.get('played')} played", f"position {st.get('position')}/{st.get('total_teams')}, {st.get('points')} pts from {st.get('played')} played" in s)
    # missing players
    miss = m.get(f"{side}_missing_players") or []
    names = [p["name"] for p in miss]
    got = re.findall(r"^\s+- ([^:]+):", s.split("missing players")[1].split("\n\n")[0], re.M) if "missing players" in s else []
    chk(f"{side} missing players {names} v sheet {got}", sorted(map(norm, names)) == sorted(map(norm, got)))
    for p in miss:
        back = (p.get("expected_return") or "")[:10] or "?"
        ok = re.search(re.escape(p["name"]) + r": [^\n]*back " + re.escape(back), s) is not None
        chk(f"  {p['name']}: reason {p['description']}, back {back}", ok)
    # lineup keeper v profile keeper
    gk = [p for p in m[f"{side}_lineup"] if p.get("position") == "G" and not p.get("substitute")]
    keepers = sorted([p for p in sq if p.get("role") == "G"], key=lambda p: -((p.get("recent_usage") or {}).get("total_minutes") or 0))
    if gk and keepers:
        ts = [norm(t) for t in re.split(r"[\s-]+", gk[0]["name"]) if norm(t)]; us = [norm(t) for t in re.split(r"[\s-]+", keepers[0]["name"]) if norm(t)]
        same = ts[-1] == us[-1] and ts[0][0] == us[0][0]
        said_change = f"{name}: KEEPER CHANGE" in allsheet
        chk(f"{side} keeper: lineup {gk[0]['name']} v most minutes {keepers[0]['name']} (same person: {same}); sheet says change: {said_change}", said_change == (not same), "a keeper change on the sheet must match the JSON names" if said_change != (not same) else "")
    chk(f"{side} formation {m.get(side+'_formation')}", (m.get(side+'_formation') or "") in allsheet)
# match-level
chk("kickoff", m["kickoff_utc"][:16] in sheet or m["kickoff_utc"][:10] in sheet)
chk("competition", m["competition"] in sheet)
chk("venue country", f"venue country: {m['venue_country']}" in sheet)
chk("lineups confirmed flag", f"lineups confirmed: {bool(m.get('lineup_confirmed'))}" in sheet)
h = m["head_to_head_summary"]
chk(f"H2H {h}", f"{h['sample_size']} meeting" in allsheet or str(h['sample_size']) in allsheet)
bad = sum(1 for r in rows if r[0] != "ok")
for r in rows: print("|", r[0], "|", r[1], "|", r[2][:140], "|")
print(f"\n{len(rows)} checks, {bad} differences")
