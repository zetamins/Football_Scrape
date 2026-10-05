import sys, json, glob, math, pickle, collections
sys.path.insert(0, '..'); sys.path.insert(0, '.')
from datetime import date
from football.oracle import oracle as O
from football.prediction_log import parse_results_csv
from football.national_elo import canonical_name as C
R = '/tmp/claude-1000/-home-seerish-football-backend-output/c75bcdf1-2bb6-4525-88f5-cdf303e339c7/scratchpad'
res = {(r['home'], r['away']): r for r in parse_results_csv(open(f'{R}/demo/results.csv', encoding='utf8').read())}
live = []
for f in sorted(glob.glob('/home/seerish/Downloads/team-reports-2026-09-28/*.json')):
    d = json.load(open(f)); m = d['match']; r = res.get((C(m['home_team']), C(m['away_team'])))
    if not r or abs((r['day'] - date.fromisoformat(m['kickoff_utc'][:10])).days) > 1: continue
    p = O.predict(d, panel='none')['prediction']; dl = p['draw']
    live.append((f"{m['home_team']} v {m['away_team']}", f"{r['hg']}-{r['ag']}", r['hg'] == r['ag'], dl['draw_pct'], dl['alert'], p['pick']))
live.sort(key=lambda x: -x[3]); n = len(live); draws = sum(1 for x in live if x[2])
print('=== A. LIVE: 38 fixtures, independent engine (exact grid), ranked by predicted draw probability ===')
print('| # | Match | Score | Draw predicted | Flag | Engine pick | Draw? |'); print('|---|---|---|---|---|---|---|')
for i, x in enumerate(live, 1): print(f"| {i} | {x[0]} | {x[1]} | {x[3]:.1f}% | {x[4]} | {x[5]} | {'DRAW' if x[2] else ''} |")
exp = sum(x[3] / 100 for x in live)
# Poisson-binomial tail P(draws >= actual)
dist = [1.0]
for x in live:
    p = x[3] / 100; new = [0.0] * (len(dist) + 1)
    for k, v in enumerate(dist): new[k] += v * (1 - p); new[k + 1] += v * p
    dist = new
print(f"\nLIVE SUMMARY: matches {n} | actual draws {draws} ({100*draws/n:.0f}%) | expected draws by the engine {exp:.1f} ({100*exp/n:.1f}% mean) | draws predicted as the PICK: {sum(1 for x in live if x[5] == 'draw')} | "
      f"flagged WATCH {sum(1 for x in live if x[4]=='watch')} ALERT {sum(1 for x in live if x[4]=='alert')} | draws among flagged: {sum(1 for x in live if x[2] and x[4] != 'none')} | chance of >= {draws} draws given these probabilities: {100*sum(dist[draws:]):.1f}%")
rows = pickle.load(open(f'{R}/../../../../../../home/seerish/football/backend/research/.cache/cache/bias_rows_v2.pkl', 'rb')) if False else pickle.load(open('/home/seerish/football/backend/research/.cache/cache/bias_rows_v2.pkl', 'rb'))
import football.history_train as H
for r in rows: r['o'] = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2); r['cat'] = H.tournament_category(r['tour'])
N = len(rows); D = sum(1 for r in rows if r['o'] == 1)
argmax_draw = [r for r in rows if max(range(3), key=lambda k: r['p'][k]) == 1]
print(f"\n=== B. HELD-OUT: {N} international matches 2018-2026 ===")
print(f"actual draws {D} ({100*D/N:.1f}%) | expected by the model {sum(r['p'][1] for r in rows):.0f} ({100*sum(r['p'][1] for r in rows)/N:.1f}%) | draws as the PICK: {len(argmax_draw)} times, right {sum(1 for r in argmax_draw if r['o']==1)}")
print('\n| Segment | Matches | Draws predicted | Draws actual | Predicted % | Actual % |'); print('|---|---|---|---|---|---|')
def seg(name, rs):
    if rs: print(f"| {name} | {len(rs)} | {sum(r['p'][1] for r in rs):.0f} | {sum(1 for r in rs if r['o']==1)} | {100*sum(r['p'][1] for r in rs)/len(rs):.1f} | {100*sum(1 for r in rs if r['o']==1)/len(rs):.1f} |")
seg('All', rows); seg('Neutral venue', [r for r in rows if r['neutral']]); seg('Home venue', [r for r in rows if not r['neutral']])
for c in ('friendly', 'qualifier', 'nations_league', 'major', 'other'): seg(f'Tournament: {c}', [r for r in rows if r['cat'] == c])
for y in (2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026): seg(f'Year {y}', [r for r in rows if r['day'].year == y])
for lo, hi in ((0, 15), (15, 19), (19, 22), (22, 25), (25, 28), (28, 31), (31, 101)): seg(f'Model draw prob {lo}-{min(hi,100)}%', [r for r in rows if lo <= 100 * r['p'][1] < hi])
