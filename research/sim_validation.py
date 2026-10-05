"""Validate the Monte Carlo layer exactly (no sampling): goals ~ Negative Binomial(mean*tempo, k) per side with a shared lognormal tempo factor
(5-point Gauss-Hermite), Dixon-Coles low-score correction. Evaluated on the 8,054 held-out matches (venue-aware model, bias_rows_v2)."""
import sys, math, pickle
sys.path.insert(0, '.')
from lab2 import CACHE
from football.history_model import _dc_tau
rows = pickle.load(open(f'{CACHE}/bias_rows_v2.pkl', 'rb'))
GH = ((0.0, 0.5333333333), (0.9585724646, 0.2220759220), (-0.9585724646, 0.2220759220), (2.0201828705, 0.0112574113), (-2.0201828705, 0.0112574113))
MAXG = 10
def nb_pmf(mean, k):
    if k > 1e5:
        return [math.exp(-mean + n * math.log(mean) - math.lgamma(n + 1)) for n in range(MAXG + 1)]
    p = k / (k + mean); lg = math.lgamma(k)
    return [math.exp(math.lgamma(n + k) - lg - math.lgamma(n + 1) + k * math.log(p) + n * math.log(1 - p)) for n in range(MAXG + 1)]
def grid(lh, la, rho, k, s):
    g = [[0.0] * (MAXG + 1) for _ in range(MAXG + 1)]
    for x, w in (GH if s > 0 else ((0.0, 1.0),)):
        t = math.exp(s * x); ph, pa = nb_pmf(lh * t, k), nb_pmf(la * t, k)
        for i in range(MAXG + 1):
            for j in range(MAXG + 1): g[i][j] += w * ph[i] * pa[j]
    tot = 0.0
    for i in range(MAXG + 1):
        for j in range(MAXG + 1):
            g[i][j] = max(0.0, g[i][j] * _dc_tau(i, j, lh, la, rho)); tot += g[i][j]
    return [[v / tot for v in row] for row in g]
def evaluate(k, s, sub):
    b = l = 0.0; pd = ad = 0.0; mk = {'o15': [0, 0], 'o25': [0, 0], 'o35': [0, 0], 'btts': [0, 0], 'z': [0, 0], 'big': [0, 0]}
    for r in sub:
        g = grid(r['lh'], r['la'], -0.05, k, s); o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
        H = sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i > j); D = sum(g[i][i] for i in range(MAXG + 1)); A = 1 - H - D
        p = (H, D, A); b += sum((p[q] - (1 if q == o else 0)) ** 2 for q in range(3)); l += -math.log(max(p[o], 1e-9)); pd += D; ad += (o == 1)
        tg = r['hg'] + r['ag']
        for key, pred, act in (('o15', sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i + j > 1), tg > 1), ('o25', sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i + j > 2), tg > 2),
                               ('o35', sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i + j > 3), tg > 3), ('btts', sum(g[i][j] for i in range(1, MAXG + 1) for j in range(1, MAXG + 1)), r['hg'] > 0 and r['ag'] > 0),
                               ('z', g[0][0], tg == 0), ('big', sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i >= 5 or j >= 5), r['hg'] >= 5 or r['ag'] >= 5)):
            mk[key][0] += pred; mk[key][1] += act
    n = len(sub)
    return b / n, l / n, pd / n, ad / n, {k_: (v[0] / n, v[1] / n) for k_, v in mk.items()}
sub = rows[::2]          # every second held-out match (4,027) keeps this to a couple of minutes
print(f'{len(sub)} held-out matches. Production settings: dispersion k=14, tempo sd 0.08. k=inf & tempo 0 = plain Poisson + Dixon-Coles')
print(f"{'k':>6} {'tempo':>6} {'Brier':>8} {'logloss':>8} {'draw pred/act':>14} | over1.5 | over2.5 | over3.5 | BTTS | 0-0 | 5+ goals (predicted / actual %)")
res = {}
for k, s in ((1e9, 0.0), (14, 0.08), (14, 0.0), (30, 0.0), (8, 0.0), (1e9, 0.08), (30, 0.08), (60, 0.04)):
    b, l, pd, ad, mk = evaluate(k, s, sub); res[(k, s)] = (b, l)
    print(f"{('inf' if k > 1e5 else k):>6} {s:>6} {b:>8.4f} {l:>8.4f} {100*pd:>6.1f}/{100*ad:<5.1f} | " + ' | '.join(f'{100*mk[x][0]:4.1f}/{100*mk[x][1]:4.1f}' for x in ('o15', 'o25', 'o35', 'btts', 'z', 'big')), flush=True)
