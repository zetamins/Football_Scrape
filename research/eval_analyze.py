"""Score football.analyze (JSON-only) on a folder of report JSONs against a results CSV
(date,home_team,away_team,home_score,away_score). Compares with the report's own pipeline blend and the odds."""
import sys, json, glob, random, math
sys.path.insert(0, '..')
from datetime import date
from football.analyze import analyze_report
from football.prediction_log import parse_results_csv
from football.national_elo import canonical_name as C

folder, results_csv = sys.argv[1], sys.argv[2]
results = parse_results_csv(open(results_csv, encoding='utf8').read())
idx = {(r['home'], r['away']): r for r in results}
def brier(p, o): return sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
def ll(p, o): return -math.log(max(p[o], 1e-9))
rows = []
for f in sorted(glob.glob(f'{folder}/*.json')):
    d = json.load(open(f)); m = d.get('match') or {}
    r = idx.get((C(m.get('home_team') or ''), C(m.get('away_team') or '')))
    if not r or abs((r['day'] - date.fromisoformat(m['kickoff_utc'][:10])).days) > 1: continue
    o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    a = analyze_report(d, draws=2000)
    p = a['prediction']
    if not p: continue
    mine = (p['home_win_pct'] / 100, p['draw_pct'] / 100, p['away_win_pct'] / 100)
    bl = (d['insights'].get('prediction') or {}).get('blended')
    pipe = (bl['home_win_pct'] / 100, bl['draw_pct'] / 100, bl['away_win_pct'] / 100) if bl else None
    mk = next((x['probs'] for x in a['methods'] if x['name'] == 'market'), None)
    rows.append(dict(f=f.split('/')[-1][:14], o=o, mine=mine, pipe=pipe, mk=mk, conf=p['confidence_pct'], pick=max(range(3), key=lambda k: mine[k]), q=a['audit']['quality'], methods={x['name']: x['probs'] for x in a['methods']}))
print('matched reports with results:', len(rows))
def summary(name, key, subset):
    s = [(r[key], r['o']) for r in subset if r[key]]
    b = sum(brier(p, o) for p, o in s) / len(s); l = sum(ll(p, o) for p, o in s) / len(s)
    acc = sum(max(range(3), key=lambda k: p[k]) == o for p, o in s) / len(s)
    print(f'{name:28} n={len(s):2d} brier {b:.4f} logloss {l:.4f} acc {acc:.3f}')
    return s
print('\nall matches')
summary('analyzer (JSON only)', 'mine', rows); summary('pipeline blend (in JSON)', 'pipe', rows)
common = [r for r in rows if r['mk'] and r['pipe']]
print('\nmatches with odds (same matches for all)')
summary('analyzer (JSON only)', 'mine', common); summary('pipeline blend (in JSON)', 'pipe', common); summary('bookmaker odds alone', 'mk', common)
for name in ('results_poisson', 'xg_poisson', 'elo', 'squad_value'):
    sub = [dict(r, x=r['methods'].get(name)) for r in common if r['methods'].get(name)]
    if sub: summary(f'  method: {name}', 'x', sub)
rng = random.Random(0)
d = [brier(r['mine'], r['o']) - brier(r['mk'], r['o']) for r in common]
bs = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(3000))
print(f'\nanalyzer minus odds Brier: {sum(d)/len(d):+.4f}  95% CI [{bs[75]:+.4f}, {bs[2925]:+.4f}]  (n={len(d)})')
print('\nconfidence vs accuracy (analyzer):')
for lo, hi in ((0, 45), (45, 60), (60, 75), (75, 101)):
    b = [r for r in rows if lo <= r['conf'] < hi]
    if b: print(f'  {lo:>3}-{hi:<3} n={len(b):2d} mean conf {sum(r["conf"] for r in b)/len(b):5.1f}%  accuracy {100*sum(r["pick"]==r["o"] for r in b)/len(b):5.1f}%')
print('overall mean confidence', round(sum(r['conf'] for r in rows)/len(rows), 1), '% vs accuracy', round(100*sum(r['pick']==r['o'] for r in rows)/len(rows), 1), '%')
