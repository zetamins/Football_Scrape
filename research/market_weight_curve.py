import sys, json, glob, math, random
sys.path.insert(0, '..')
from datetime import date
from football.oracle import quant as Q
from football.oracle.facts import extract_facts
from football.prediction_log import parse_results_csv
from football.national_elo import canonical_name as C
folder, results_csv = sys.argv[1:3]
results = {(r['home'], r['away']): r for r in parse_results_csv(open(results_csv, encoding='utf8').read())}
rows = []
for f in sorted(glob.glob(f'{folder}/*.json')):
    d = json.load(open(f)); m = d['match']; r = results.get((C(m['home_team']), C(m['away_team'])))
    if not r or abs((r['day'] - date.fromisoformat(m['kickoff_utc'][:10])).days) > 1: continue
    fa = extract_facts(d)
    if not fa['odds']: continue
    o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    rows.append((fa, o, Q.rate_sources(fa)))
print('matches with odds', len(rows))
def brier(p, o): return sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
def run(wm, others_scale=1.0):
    tot = 0; per = []
    for fa, o, src in rows:
        s2 = [dict(s, weight=(wm if s['name'] == 'market' else s['weight'] * others_scale)) for s in src]
        mh, ma, _ = Q.absence_multipliers(fa)
        lh, la, _ = Q.combine_rates(Q.apply_absences(s2, mh, ma))     # absences on the non-odds sources only
        b = brier(Q.outcome_probs(lh, la), o); per.append(b); tot += b
    return tot / len(rows), per
mk = sum(brier((fa['odds']['home'], fa['odds']['draw'], fa['odds']['away']), o) for fa, o, _ in rows) / len(rows)
print(f'odds alone (direct probabilities): brier {mk:.4f}')
print('market weight (others total ~3.5)  -> quant brier   share of market')
base, per_base = run(4.0)
for wm in (0.0001, 2, 4, 6, 8, 12, 20, 40, 1000):
    b, per = run(wm)
    share = wm / (wm + 3.5 * 1.0) if wm > 0.01 else 0
    print(f'  {wm:8.1f}   {b:.4f}   {share:5.0%}')
