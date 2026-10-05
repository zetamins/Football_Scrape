"""Odds-free variants on the labelled fixtures: how much weight should our own history model get against the JSON-only sources?"""
import sys, json, glob
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
    fa = extract_facts(d); o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    rows.append((fa, o, Q.rate_sources(fa, use_market=False), fa['odds']))
n = len(rows); print(n, 'fixtures;', sum(1 for r in rows if any(s['name'] == 'history' for s in r[2])), 'have a history-model source')
def brier(p, o): return sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
def run(wh, scale=1.0, sub=rows):
    t = 0
    for fa, o, src, _ in sub:
        s2 = [dict(s, weight=(wh if s['name'] == 'history' else s['weight'] * scale)) for s in src]
        mh, ma, _ = Q.absence_multipliers(fa); lh, la, _ = Q.combine_rates(Q.apply_absences(s2, mh, ma)); t += brier(Q.outcome_probs(lh, la), o)
    return t / len(sub)
withodds = [r for r in rows if r[3]]
print('uniform guess 0.6667 | odds alone on the', len(withodds), 'with odds:', round(sum(brier((r[3]['home'], r[3]['draw'], r[3]['away']), r[1]) for r in withodds) / len(withodds), 4))
print(f"\n{'history weight (others ~3.5)':>30} {'share':>6} {'Brier all '+str(n):>14} {'Brier with-odds '+str(len(withodds)):>20}")
for wh in (0.0001, 2, 6, 12, 25, 60, 1000):
    print(f'{wh:>30.1f} {wh/(wh+3.5):>6.0%} {run(wh):>14.4f} {run(wh, sub=withodds):>20.4f}')
