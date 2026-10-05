"""Recommended selection per match = the most likely of: 1X2 top outcome, Over/Under 2.5, Both teams to score (Yes/No).
Held-out evaluation on the 8,054 international matches (rates stored from the rolling out-of-sample fit): hit rate by market and by probability band."""
import sys, pickle, math
from collections import defaultdict
import numpy as np
sys.path.insert(0, '..')
from football.oracle import quant as Q
rows = pickle.load(open('.cache/cache/bias_rows_v2.pkl', 'rb'))
K = 11; FACT = np.array([math.factorial(i) for i in range(K)], dtype=float)
def pois(l): return np.exp(-l) * l ** np.arange(K) / FACT
def grid(lh, la):
    g = np.outer(pois(lh), pois(la)); r = Q.DC_RHO
    g[0, 0] *= 1 - lh * la * r; g[0, 1] *= 1 + lh * r; g[1, 0] *= 1 + la * r; g[1, 1] *= 1 - r
    return g / g.sum()
I, J = np.indices((K, K))
out = []
for r in rows:
    g = grid(r['lh'], r['la']); hg, ag = r['hg'], r['ag']
    p1 = [np.tril(g, -1).sum(), np.trace(g), np.triu(g, 1).sum()]; o = 0 if hg > ag else 1 if hg == ag else 2
    over = g[(I + J) > 2].sum(); btts = g[(I > 0) & (J > 0)].sum()
    cands = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over 2.5': (over, hg + ag > 2), 'Under 2.5': (1 - over, hg + ag <= 2),
             'BTTS Yes': (btts, hg > 0 and ag > 0), 'BTTS No': (1 - btts, not (hg > 0 and ag > 0))}
    best = max(cands, key=lambda k: cands[k][0])
    out.append((best, cands[best][0], cands[best][1], cands['1X2']))
n = len(out)
print(f"{n} matches. Recommended = most likely of 1X2 / O-U 2.5 / BTTS.")
print(f"Hit rate of the recommended selection: {100*np.mean([o[2] for o in out]):.1f}% (mean quoted probability {100*np.mean([o[1] for o in out]):.1f}%)")
print(f"Always the 1X2 pick: {100*np.mean([o[3][1] for o in out]):.1f}% (mean probability {100*np.mean([o[3][0] for o in out]):.1f}%)\n")
print('| Chosen market | Matches | Share | Mean prob % | Hit rate % |\n|---|---|---|---|---|')
by = defaultdict(list)
for b, p, h, _ in out: by[b].append((p, h))
for b, v in sorted(by.items(), key=lambda kv: -len(kv[1])): print(f"| {b} | {len(v)} | {100*len(v)/n:.0f}% | {100*np.mean([x[0] for x in v]):.1f} | {100*np.mean([x[1] for x in v]):.1f} |")
print('\n| Probability band | Matches | Mean prob % | Hit rate % |\n|---|---|---|---|')
bands = [(0, .55), (.55, .6), (.6, .65), (.65, .7), (.7, .8), (.8, 1.01)]
for lo, hi in bands:
    v = [(p, h) for _, p, h, _ in out if lo <= p < hi]
    if v: print(f"| {int(lo*100)}-{int(min(hi,1)*100)} | {len(v)} | {100*np.mean([x[0] for x in v]):.1f} | {100*np.mean([x[1] for x in v]):.1f} |")
