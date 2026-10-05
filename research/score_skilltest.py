"""Score the opinions that skill-following agents wrote (blind) on the labelled reports: engine alone vs engine + agent opinion
(default trust 0.5, and trust 1.0), vs odds, vs the old pipeline blend. Also reports compliance (evidenced vs rejected factors, size of adjustments).
usage: score_skilltest.py <reports dir> <results.csv> <opinions dir>"""
import sys, json, glob, os, random, math, collections
sys.path.insert(0, '..')
from datetime import date
from football.oracle import oracle as O
from football.prediction_log import parse_results_csv
from football.national_elo import canonical_name as C
folder, results_csv, opdir = sys.argv[1:4]
results = {(r['home'], r['away']): r for r in parse_results_csv(open(results_csv, encoding='utf8').read())}
def brier(p, o): return sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
def acc(p, o): return max(range(3), key=lambda k: p[k]) == o
rows, comp = [], collections.Counter()
for f in sorted(glob.glob(f'{folder}/*.json')):
    stem = os.path.basename(f)[:-5]
    opf = os.path.join(opdir, stem + '.json')
    d = json.load(open(f)); m = d['match']
    r = results.get((C(m['home_team']), C(m['away_team'])))
    if not r or abs((r['day'] - date.fromisoformat(m['kickoff_utc'][:10])).days) > 1: continue
    if not os.path.exists(opf): continue
    try:
        op = json.load(open(opf))
    except ValueError:
        comp['unparseable opinion'] += 1; continue
    o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    P = lambda **kw: O.predict(d, panel="none", sims=60_000, **kw)
    base = P(); half = P(opinions=[op]); full = P(opinions=[op], opinion_trust=1.0)
    if not base['prediction']: continue
    pr = lambda x: [x['prediction']['home_win_pct'] / 100, x['prediction']['draw_pct'] / 100, x['prediction']['away_win_pct'] / 100]
    odds = (m.get('betting_odds') or m.get('sofascore_betting_odds') or {})
    mk = [odds.get(k) for k in ('home_win_fair_pct', 'draw_fair_pct', 'away_win_fair_pct')]
    mk = [v / 100 for v in mk] if all(isinstance(v, (int, float)) for v in mk) else None
    bl = (d['insights'].get('prediction') or {}).get('blended')
    mem = half['panel']['members'][0]
    comp['factors accepted'] += len(mem['factors']); comp['factors rejected'] += len(mem['rejected'])
    comp['opinions'] += 1; comp['all-zero opinions'] += all(abs(op.get(k, 0) or 0) < 1e-9 for k in ('home_rate_pct', 'away_rate_pct', 'draw_bias_pct'))
    comp['abs adj sum (x100)'] += int(100 * sum(abs(half['panel']['adjust'][k]) for k in half['panel']['adjust']))
    rows.append({'stem': stem, 'o': o, 'base': pr(base), 'half': pr(half), 'full': pr(full), 'market': mk, 'pipeline': [bl['home_win_pct'] / 100, bl['draw_pct'] / 100, bl['away_win_pct'] / 100] if bl else None,
                 'conf': half['prediction']['confidence_pct'], 'adjust': half['panel']['adjust']})
print('opinions scored', len(rows), '| compliance:', dict(comp))
def table(title, sub, keys):
    print(f'\n{title} (n={len(sub)})')
    for k in keys:
        s = [(x[k], x['o']) for x in sub if x.get(k)]
        print(f'  {k:9} brier {sum(brier(p, o) for p, o in s)/len(s):.4f}  acc {sum(acc(p, o) for p, o in s)/len(s):.3f}')
common = [x for x in rows if x['market'] and x['pipeline']]
table('All scored', rows, ['base', 'half', 'full', 'pipeline'])
table('With odds (same matches)', common, ['market', 'base', 'half', 'full', 'pipeline'])
rng = random.Random(0)
def paired(a, b, sub, label):
    if not sub: return
    dd = [brier(x[a], x['o']) - brier(x[b], x['o']) for x in sub]
    bs = sorted(sum(rng.choice(dd) for _ in dd) / len(dd) for _ in range(4000))
    print(f'  {label:42} {sum(dd)/len(dd):+.4f}  95% CI [{bs[100]:+.4f}, {bs[3900]:+.4f}]  n={len(dd)}')
print('\nPaired Brier differences (negative = first better)')
paired('half', 'base', rows, 'engine + agent opinion (x0.5) vs engine alone')
paired('full', 'base', rows, 'engine + agent opinion (x1.0) vs engine alone')
paired('half', 'market', common, 'engine + agent opinion (x0.5) vs odds alone')
paired('half', 'pipeline', common, 'engine + agent opinion (x0.5) vs old pipeline')
helped = sum(1 for x in rows if brier(x['half'], x['o']) < brier(x['base'], x['o']) - 1e-6)
hurt = sum(1 for x in rows if brier(x['half'], x['o']) > brier(x['base'], x['o']) + 1e-6)
print(f'\nagent opinion improved the Brier on {helped}, worsened it on {hurt}, ~same on {len(rows)-helped-hurt}')
print('mean |adjustment| applied: home %.2f%% away %.2f%% draw %.2fpp' % tuple(sum(abs(x['adjust'][k]) for x in rows) / len(rows) for k in ('home_rate_pct', 'away_rate_pct', 'draw_bias_pct')))
print('\nCalibrated confidence vs accuracy (engine + opinion x0.5):')
for lo, hi in ((0, 45), (45, 60), (60, 75), (75, 101)):
    b = [x for x in rows if lo <= x['conf'] < hi]
    if b: print(f"  {lo:>3}-{hi:<3} n={len(b):2d} mean conf {sum(x['conf'] for x in b)/len(b):5.1f}%  accuracy {100*sum(acc(x['half'], x['o']) for x in b)/len(b):5.1f}%")
print('overall mean confidence', round(sum(x['conf'] for x in rows)/len(rows), 1), '% vs accuracy', round(100*sum(acc(x['half'], x['o']) for x in rows)/len(rows), 1), '%')
