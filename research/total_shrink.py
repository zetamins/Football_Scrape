"""Does shrinking low total-goal rates toward the mean fix the overconfident-Under tail? Fit k on 2018-23, test 2024-26 (and per period)."""
import sys, pickle, math, random
import numpy as np
sys.path.insert(0, '..')
exec(open('recommend_eval.py').read().split("out = []")[0])
train = [r for r in rows if r['day'].year <= 2023]; test = [r for r in rows if r['day'].year >= 2024]
MU = float(np.mean([r['lh'] + r['la'] for r in train]))
def markets(r, k):
    t = r['lh'] + r['la']; t2 = t + k * (MU - t); f = t2 / t
    g = grid(r['lh'] * f, r['la'] * f)
    return [np.tril(g, -1).sum(), np.trace(g), np.triu(g, 1).sum()], g[(I + J) > 2].sum(), g[(I > 0) & (J > 0)].sum()
def score(rs, k):
    ll = {'1X2': [], 'OU': [], 'BTTS': []}
    for r in rs:
        p1, over, btts = markets(r, k); o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
        ll['1X2'].append(-math.log(max(p1[o], 1e-9)))
        ll['OU'].append(-math.log(max(over if r['hg'] + r['ag'] > 2 else 1 - over, 1e-9)))
        ll['BTTS'].append(-math.log(max(btts if (r['hg'] > 0 and r['ag'] > 0) else 1 - btts, 1e-9)))
    return {m: np.array(v) for m, v in ll.items()}
print('mean total (train) =', round(MU, 3))
best = {}
for k in (0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4):
    s = score(train, k); print(f"train k={k}: log-loss 1X2 {s['1X2'].mean():.5f}  O/U {s['OU'].mean():.5f}  BTTS {s['BTTS'].mean():.5f}")
    for m in s: best.setdefault(m, []).append((s[m].mean(), k))
kb = {m: min(v)[1] for m, v in best.items()}; print('best k on train per market:', kb)
k = kb['OU']
print(f"\nUsing k={k} (best for O/U on train). Log-loss difference vs k=0, by period (negative = better):")
rng = random.Random(3)
for name, sel in (('2018-21', lambda y: y <= 2021), ('2022-23', lambda y: 2022 <= y <= 2023), ('2024-26', lambda y: y >= 2024)):
    rs = [r for r in rows if sel(r['day'].year)]; a = score(rs, 0); b = score(rs, k)
    for m in ('1X2', 'OU', 'BTTS'):
        d = b[m] - a[m]; n = len(d); bs = sorted(np.mean([d[rng.randrange(n)] for _ in range(300)]) for _ in range(300))
        print(f"  {name} {m}: {d.mean():+.5f}  (95% CI {bs[7]:+.5f}, {bs[292]:+.5f})")
# does it fix the tail? Under >=70% band on test
def under_tail(k):
    ps = []; hs = []
    for r in test:
        p1, over, btts = markets(r, k)
        if 1 - over >= 0.70: ps.append(1 - over); hs.append(r['hg'] + r['ag'] <= 2)
    return len(ps), 100 * np.mean(ps) if ps else float('nan'), 100 * np.mean(hs) if hs else float('nan')
print('Test 2024-26 Under>=70% band: k=0 ->', under_tail(0), '| k=%s ->' % k, under_tail(k))
