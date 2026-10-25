"""Does following the lite skill's written recipe give the engine's own per-source expected goals? Uses the engine's facts as inputs and the recipe's formulas (from SKILL.md) as the calculation."""
import glob, json, math, sys
sys.path.insert(0, ".")
from football.oracle import quant as Q
from football.oracle.facts import extract_facts
clamp = lambda x, lo, hi: max(lo, min(hi, x))
def rows_stats(rows):
    pos = [(i, r) for i, r in enumerate(rows[:10]) if not r.get("shootout")]      # a skipped row still counts as a position
    use = [r for _, r in pos]
    ws = [0.9 ** i * (0.7 if "friendl" in (r.get("competition") or "").lower() else 1.0) for i, r in pos]
    if not use: return None
    sw = sum(ws)
    gf = sum(w * min(r["gf"], 6) for w, r in zip(ws, use)) / sw; ga = sum(w * min(r["ga"], 6) for w, r in zip(ws, use)) / sw
    return gf, ga, sw
def recipe_pair(h, a, E):
    base = max(0.8, (h[0] + h[1] + a[0] + a[1]) / 4)
    att = lambda gf, n: (n * gf + 4 * base) / (n + 4)
    adv = 0.2 * E
    return (clamp(att(h[0], h[2]) * att(a[1], a[2]) / base * math.exp(adv), 0.2, 4.0), clamp(att(a[0], a[2]) * att(h[1], h[2]) / base * math.exp(-adv), 0.2, 4.0))
def recipe_strength(f):
    h, a, E = f["sides"]["home"], f["sides"]["away"], f["edge"]
    gap, any_ = 0.0, False
    if h["elo"] and a["elo"]:
        gap += (h["elo"]["rating"] - a["elo"]["rating"]) * (1.0 if h["elo"]["national"] and a["elo"]["national"] else 0.5); any_ = True
    if h["squad_value"] and a["squad_value"]:
        gap += clamp(100 * math.log(h["squad_value"] / a["squad_value"]), -400, 400); any_ = True
    if not any_: return None
    diff = clamp(gap * 0.0022, -2.5, 2.5) + E * 0.26
    return clamp((2.6 + diff) / 2, 0.2, 4.0), clamp((2.6 - diff) / 2, 0.2, 4.0)
worst = 0; n = 0; bad = []
for f in sorted(glob.glob("output/*.json")):
    facts = extract_facts(json.load(open(f))); E = facts["edge"]
    eng = {s["name"]: s["lam"] for s in Q.rate_sources(facts, use_market=False)}
    hs, as_ = facts["sides"]["home"], facts["sides"]["away"]
    mine = {}
    hr, ar = rows_stats(hs["form"]), rows_stats(as_["form"])
    if hr and ar: mine["results"] = recipe_pair(hr, ar, E)
    if hs["xg"] and as_["xg"]: mine["xg"] = recipe_pair((hs["xg"]["for_pg"], hs["xg"]["against_pg"], hs["xg"]["n"]), (as_["xg"]["for_pg"], as_["xg"]["against_pg"], as_["xg"]["n"]), E)
    st = recipe_strength(facts)
    if st: mine["strength"] = st
    for k, v in mine.items():
        if k in eng:
            d = max(abs(v[0] - eng[k][0]), abs(v[1] - eng[k][1])); worst = max(worst, d); n += 1
            if d > 0.01: bad.append((f.split("/")[-1][:14], k, [round(x, 3) for x in v], [round(x, 3) for x in eng[k]]))
        else: bad.append((f.split("/")[-1][:14], k, "recipe has it, engine does not"))
    for k in eng:
        if k not in mine and k != "history": bad.append((f.split("/")[-1][:14], k, "engine has it, recipe does not"))
print(f"{n} source estimates compared on {len(glob.glob('output/*.json'))} reports; largest difference {worst:.4f} goals; {len(bad)} mismatches")
for b in bad[:10]: print(b)
