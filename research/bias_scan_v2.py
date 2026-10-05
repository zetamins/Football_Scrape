import sys, pickle, math, collections
sys.path.insert(0, '.')
from lab2 import CONFED, CACHE
import football.history_train as H
rows = pickle.load(open(f'{CACHE}/bias_rows_v2.pkl', 'rb'))
for r in rows:
    r['o'] = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    r['hc'], r['ac'] = CONFED.get(r['home'], '?'), CONFED.get(r['away'], '?')
    r['cat'] = H.tournament_category(r['tour'])
    r['gap'] = (r['att_h'] - r['def_h']) - (r['att_a'] - r['def_a'])
    r['fav_home'] = r['p'][0] >= r['p'][2]
    r['pf'] = max(r['p'][0], r['p'][2])
tests = []
def stats(name, rs, min_n=150):
    n = len(rs)
    if n < min_n: return
    out = {}
    for k, label in ((0, 'home win'), (1, 'draw'), (2, 'away win')):
        e = sum(r['p'][k] for r in rs); a = sum(1 for r in rs if r['o'] == k); v = sum(r['p'][k] * (1 - r['p'][k]) for r in rs)
        out[label] = (a / n, e / n, (a - e) / math.sqrt(v) if v > 0 else 0)
    for key, gk, label in (('lh', 'hg', 'home goals'), ('la', 'ag', 'away goals')):
        res = [r[gk] - r[key] for r in rs]; mean = sum(res) / n; var = sum((x - mean) ** 2 for x in res) / n
        out[label] = (sum(r[gk] for r in rs) / n, sum(r[key] for r in rs) / n, mean / math.sqrt(var / n))
    tests.append((name, n, out))
D = lambda f: [r for r in rows if f(r)]
stats('ALL', rows)
stats('neutral', D(lambda r: r['neutral'])); stats('non-neutral', D(lambda r: not r['neutral']))
for c in ('CAF', 'UEFA', 'AFC', 'CONCACAF', 'CONMEBOL', 'OFC', '?'):
    stats(f'home conf {c} (non-neutral)', D(lambda r, c=c: r['hc'] == c and not r['neutral']))
    stats(f'away conf {c} (non-neutral)', D(lambda r, c=c: r['ac'] == c and not r['neutral']))
    stats(f'neutral, home conf {c}', D(lambda r, c=c: r['hc'] == c and r['neutral']))
stats('cross-confederation', D(lambda r: r['hc'] != r['ac'])); stats('same-confederation', D(lambda r: r['hc'] == r['ac']))
for hc in ('CAF', 'UEFA', 'AFC', 'CONCACAF', 'CONMEBOL'):
    for ac in ('CAF', 'UEFA', 'AFC', 'CONCACAF', 'CONMEBOL'):
        if hc != ac: stats(f'{hc} (home) v {ac} (away)', D(lambda r, hc=hc, ac=ac: r['hc'] == hc and r['ac'] == ac), 120)
for cat in ('friendly', 'qualifier', 'nations_league', 'major', 'other'):
    stats(f'tournament {cat}', D(lambda r, cat=cat: r['cat'] == cat))
for key in ('FIFA World Cup', 'UEFA Euro', 'African Cup of Nations', 'Copa América', 'AFC Asian Cup', 'Gold Cup', 'UEFA Nations League', 'CONCACAF Nations League', 'FIFA World Cup qualification', 'African Cup of Nations qualification', 'UEFA Euro qualification', 'AFC Asian Cup qualification', 'Friendly'):
    stats(f'tournament "{key}"', D(lambda r, key=key: r['tour'] == key), 120)
for y in range(2018, 2027): stats(f'year {y}', D(lambda r, y=y: r['day'].year == y))
for mth in range(1, 13): stats(f'month {mth:02d}', D(lambda r, mth=mth: r['day'].month == mth))
gs = sorted(rows, key=lambda r: r['gap']); n = len(gs)
for i in range(8):
    b = gs[i * n // 8:(i + 1) * n // 8]; stats(f'rating gap octile {i+1} (home weaker -> stronger)', b)
for lo, hi in ((0.33, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.01)):
    for ven, fn in (('favourite at home', lambda r: r['fav_home'] and not r['neutral']), ('favourite away', lambda r: (not r['fav_home']) and not r['neutral']), ('neutral', lambda r: r['neutral'])):
        stats(f'favourite {lo:.2f}-{min(hi,1):.2f}, {ven}', D(lambda r, lo=lo, hi=hi, fn=fn: lo <= r['pf'] < hi and fn(r)))
# team-level residuals
team = collections.defaultdict(list)
for r in rows: team[r['home']].append((r, True)); team[r['away']].append((r, False))
tflags = []
for t, lst in team.items():
    if len(lst) < 60: continue
    # points residual: actual points - expected points
    ex = sum((3 * r['p'][0] + r['p'][1]) if h else (3 * r['p'][2] + r['p'][1]) for r, h in lst); ac = sum(((3 if r['o'] == 0 else 1 if r['o'] == 1 else 0) if h else (3 if r['o'] == 2 else 1 if r['o'] == 1 else 0)) for r, h in lst)
    var = sum(((3 - (3 * r['p'][0] + r['p'][1])) ** 2 * r['p'][0] + (1 - (3 * r['p'][0] + r['p'][1])) ** 2 * r['p'][1] + (0 - (3 * r['p'][0] + r['p'][1])) ** 2 * r['p'][2]) if h else
              ((3 - (3 * r['p'][2] + r['p'][1])) ** 2 * r['p'][2] + (1 - (3 * r['p'][2] + r['p'][1])) ** 2 * r['p'][1] + (0 - (3 * r['p'][2] + r['p'][1])) ** 2 * r['p'][0]) for r, h in lst)
    z = (ac - ex) / math.sqrt(var); tflags.append((z, t, len(lst), ac / len(lst), ex / len(lst)))
# report
THR = 3.3
print(f'{len(rows)} held-out matches; {len(tests)} slices x 5 measures + {len(tflags)} teams tested; flag threshold |z| >= {THR} (multiple-testing guard)\n')
print('FLAGGED SLICES  (actual vs predicted; z-score)')
print(f"{'slice':58} {'n':>5}  measure       actual  pred    z")
cnt = 0
for name, n, out in tests:
    for label, (a, e, z) in out.items():
        if abs(z) >= THR and name != 'ALL':
            cnt += 1; print(f'{name:58} {n:>5}  {label:12} {a:6.3f} {e:6.3f} {z:+5.1f}')
print(f'\n({cnt} flagged measures; expected by chance at this threshold across ~{len(tests)*5} tests: about {len(tests)*5*0.001:.1f})')
print('\nTEAMS with persistent points residual (|z| >= 3, n >= 60):', [(t, f'{z:+.1f}', f'{ac:.2f} vs {ex:.2f} pts/g', n) for z, t, n, ac, ex in sorted(tflags, key=lambda x: -abs(x[0])) if abs(z) >= 3][:12] or 'none')
a = [x for x in tests if x[0] == 'ALL'][0][2]
print('\nOVERALL', {k: f'{v[0]:.3f} vs {v[1]:.3f} (z {v[2]:+.1f})' for k, v in a.items()})
