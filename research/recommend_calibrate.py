"""Does per-market calibration improve the 'most likely selection' rule? Fit on 2018-23, test 2024-26."""
import sys, pickle, math
import numpy as np
sys.path.insert(0, '..')
exec(open('recommend_eval.py').read().split("out = []")[0])
NAMES = ['1X2 home', '1X2 draw', '1X2 away', 'Over 2.5', 'Under 2.5', 'BTTS Yes', 'BTTS No']
def cands(r):
    g = grid(r['lh'], r['la']); hg, ag = r['hg'], r['ag']
    p1 = [np.tril(g, -1).sum(), np.trace(g), np.triu(g, 1).sum()]; o = 0 if hg > ag else 1 if hg == ag else 2
    over = g[(I + J) > 2].sum(); btts = g[(I > 0) & (J > 0)].sum()
    ps = p1 + [over, 1 - over, btts, 1 - btts]
    hs = [o == 0, o == 1, o == 2, hg + ag > 2, hg + ag <= 2, hg > 0 and ag > 0, not (hg > 0 and ag > 0)]
    return ps, hs
data = [(r['day'].year, *cands(r)) for r in rows]
train = [d for d in data if d[0] <= 2023]; test = [d for d in data if d[0] >= 2024]
def fit(x, y):
    X = np.column_stack([np.ones(len(x)), np.log(np.clip(x, 1e-4, 1 - 1e-4) / (1 - np.clip(x, 1e-4, 1 - 1e-4)))]); w = np.array([0.0, 1.0])
    for _ in range(30):
        p = 1 / (1 + np.exp(-X @ w)); H = X.T @ (X * (p * (1 - p))[:, None]) + 1e-6 * np.eye(2); w += np.linalg.solve(H, X.T @ (y - p))
    return w
def apply(w, p):
    z = w[0] + w[1] * math.log(min(max(p, 1e-4), 1 - 1e-4) / (1 - min(max(p, 1e-4), 1 - 1e-4))); return 1 / (1 + math.exp(-z))
# one calibrator per selection group: 1X2 (all three outcomes pooled), Over/Under pooled, BTTS pooled
groups = {'1X2': [0, 1, 2], 'OU': [3, 4], 'BTTS': [5, 6]}
cal = {}
for g, idx in groups.items():
    xs = np.array([d[1][i] for d in train for i in idx]); ys = np.array([float(d[2][i]) for d in train for i in idx]); cal[g] = fit(xs, ys); print(g, 'calibrator a,b =', np.round(cal[g], 3))
gof = {i: g for g, idx in groups.items() for i in idx}
def choose(d, calibrated):
    ps = d[1]
    if calibrated:
        # 1X2 competes with its single best outcome
        c = [apply(cal[gof[i]], ps[i]) for i in range(7)]
    else: c = list(ps)
    top1 = max(range(3), key=lambda i: c[i]); idx = [top1, 3, 4, 5, 6]
    return max(idx, key=lambda i: c[i]), c
res = {}
for label, cal_on in (('raw model probability', False), ('per-market calibrated', True)):
    hits = []; probs = []; chosen = {}
    for d in test:
        i, c = choose(d, cal_on); hits.append(d[2][i]); probs.append(c[i]); chosen[NAMES[i]] = chosen.get(NAMES[i], 0) + 1
    res[label] = (np.mean(hits), np.mean(probs), chosen)
    print(f"{label}: hit rate {100*np.mean(hits):.2f}% (mean quoted {100*np.mean(probs):.1f}%) on {len(test)}; chosen {chosen}")
d = np.array([1.0 * choose(x, True)[0] is not None for x in test])
h_raw = np.array([x[2][choose(x, False)[0]] for x in test], float); h_cal = np.array([x[2][choose(x, True)[0]] for x in test], float)
diff = h_cal - h_raw; rng = np.random.default_rng(1); bs = np.sort([diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(2000)])
print(f"hit-rate difference calibrated - raw: {100*diff.mean():+.2f} points, 95% CI ({100*bs[50]:+.2f}, {100*bs[1949]:+.2f})")
