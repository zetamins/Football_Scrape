"""When the non-odds models disagree with the odds, who is closer to reality? (36 labelled fixtures with odds, offline)"""
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
    fa = extract_facts(d)
    if not fa['odds']: continue
    src = Q.rate_sources(fa); non = [s for s in src if s['name'] != 'market']
    if not non: continue
    mh, ma, _ = Q.absence_multipliers(fa)
    lh, la, _ = Q.combine_rates(Q.apply_absences(non, mh, ma)); model = Q.outcome_probs(lh, la)
    mk = (fa['odds']['home'], fa['odds']['draw'], fa['odds']['away'])
    o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    br = lambda p: sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
    gap = max(abs(model[k] - mk[k]) for k in range(3))
    # which way the models lean relative to the odds (home minus away share)
    lean = (model[0] - model[2]) - (mk[0] - mk[2])
    rows.append((gap, lean, br(mk), br(model), o, mk, model))
print(f'{len(rows)} fixtures')
print(f"{'models disagree with odds by':>30} {'n':>3} {'odds Brier':>11} {'models Brier':>13} {'odds closer':>12}")
for lo, hi in ((0, .05), (.05, .10), (.10, .15), (.15, 1)):
    b = [r for r in rows if lo <= r[0] < hi]
    if b: print(f'{lo*100:>10.0f}-{min(hi,1)*100:<3.0f} points             {len(b):>3} {sum(r[2] for r in b)/len(b):>11.3f} {sum(r[3] for r in b)/len(b):>13.3f} {sum(1 for r in b if r[2] < r[3]):>7}/{len(b)}')
big = [r for r in rows if r[0] >= .10]
print('\nwhen models disagree by >= 10 points, which side of the odds-vs-models gap did the RESULT favour?')
fav_models = sum(1 for r in big if (r[1] > 0 and r[4] == 0) or (r[1] < 0 and r[4] == 2))
fav_odds = sum(1 for r in big if (r[1] > 0 and r[4] == 2) or (r[1] < 0 and r[4] == 0))
print(f'  models were right on the direction {fav_models} times, odds {fav_odds} times, draws/other {len(big) - fav_models - fav_odds} (n={len(big)})')
