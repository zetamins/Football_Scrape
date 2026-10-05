"""Draw-identification techniques from the literature, tested out of sample on the 8,054 held-out internationals.
Fit on 2018-2023, score once on 2024-26. Techniques: diagonal inflation (Karlis & Ntzoufras 2009), bivariate Poisson with a shared
component, and a draw boost that grows as the sides get closer in strength (the Elo-closeness idea)."""
import sys, pickle, math, random
import numpy as np
sys.path.insert(0, '..')
from football.oracle import quant as Q

rows = pickle.load(open('.cache/cache/bias_rows_v2.pkl', 'rb'))
K = 11
FACT = np.array([math.factorial(i) for i in range(K)], dtype=float)
def pois(l): return np.exp(-l) * l ** np.arange(K) / FACT

def dc_grid(lh, la):
    g = np.outer(pois(lh), pois(la))
    rho = Q.DC_RHO
    g[0, 0] *= 1 - lh * la * rho; g[0, 1] *= 1 + lh * rho; g[1, 0] *= 1 + la * rho; g[1, 1] *= 1 - rho
    return g / g.sum()

def bivar_grid(lh, la, c):
    l3 = c * min(lh, la); a, b = lh - l3, la - l3
    pa, pb, p3 = pois(a), pois(b), pois(l3)
    g = np.zeros((K, K))
    for k in range(K):
        if p3[k] < 1e-9: break
        g[k:, k:] += p3[k] * np.outer(pa[:K - k], pb[:K - k])
    rho = Q.DC_RHO
    g[0, 0] *= 1 - lh * la * rho; g[0, 1] *= 1 + lh * rho; g[1, 0] *= 1 + la * rho; g[1, 1] *= 1 - rho
    return g / g.sum()

def outcome(g):
    return np.array([np.tril(g, -1).sum(), np.trace(g), np.triu(g, 1).sum()])

def diag_inflate(g, w):
    d = np.trace(g); out = g * (1 - w)
    out[np.diag_indices(K)] = np.diag(g) * ((1 - w) + w / d)
    return out / out.sum()

def gap_inflate(g, w0, gap):
    return diag_inflate(g, w0 * math.exp(-gap))

def evaluate(rs, fn):
    P = np.array([fn(r) for r in rs]); O = np.array([0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2 for r in rs])
    pc = P[np.arange(len(rs)), O]; onehot = np.eye(3)[O]
    brier = ((P - onehot) ** 2).sum(1); ll = -np.log(np.maximum(pc, 1e-9))
    rps = ((np.cumsum(P, 1)[:, :2] - np.cumsum(onehot, 1)[:, :2]) ** 2).sum(1) / 2
    dr = (O == 1); pos, neg = P[dr, 1], P[~dr, 1]
    auc = ((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())
    return dict(brier=brier, ll=ll, rps=rps, draw_pred=P[:, 1].mean(), draw_act=dr.mean(), auc=auc, P=P)

train = [r for r in rows if r['day'].year <= 2023]; test = [r for r in rows if r['day'].year >= 2024]
base = lambda r: outcome(dc_grid(r['lh'], r['la']))
def best(label, grid, make):
    best_v, best_ll = None, 9
    for v in grid:
        ll = evaluate(train, make(v))['ll'].mean()
        if ll < best_ll: best_v, best_ll = v, ll
    print(f"fit {label}: best on train = {best_v}  (train log-loss {best_ll:.5f})"); return best_v
w = best('diagonal inflation w', [-0.1, -0.05, -0.02, 0.0, 0.02, 0.05, 0.1, 0.15, 0.2], lambda v: (lambda r: outcome(diag_inflate(dc_grid(r['lh'], r['la']), v))))
c = best('bivariate shared share c', [0.0, 0.05, 0.1, 0.15, 0.2, 0.3], lambda v: (lambda r: outcome(bivar_grid(r['lh'], r['la'], v))))
g0 = best('closeness boost w0 (w0*exp(-|lh-la|))', [-0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.5], lambda v: (lambda r: outcome(gap_inflate(dc_grid(r['lh'], r['la']), v, abs(r['lh'] - r['la'])))))
methods = {'current (Poisson + Dixon-Coles)': base,
           f'diagonal inflation w={w}': lambda r: outcome(diag_inflate(dc_grid(r['lh'], r['la']), w)),
           f'bivariate Poisson c={c}': lambda r: outcome(bivar_grid(r['lh'], r['la'], c)),
           f'closeness boost w0={g0}': lambda r: outcome(gap_inflate(dc_grid(r['lh'], r['la']), g0, abs(r['lh'] - r['la'])))}
res = {k: evaluate(test, f) for k, f in methods.items()}
b = res['current (Poisson + Dixon-Coles)']
rng = random.Random(1); n = len(test)
print(f"\nTEST 2024-26 ({n} matches)\n| Method | Brier | Log-loss | RPS | Draw pred % | Draw actual % | Draw AUC | Log-loss diff vs current (95% CI) |\n|---|---|---|---|---|---|---|---|")
for k, r in res.items():
    d = r['ll'] - b['ll']; m = d.mean()
    bs = sorted(np.mean([d[rng.randrange(n)] for _ in range(n)]) for _ in range(400))
    ci = '-' if k == 'current (Poisson + Dixon-Coles)' else f"{m:+.5f} ({bs[10]:+.5f}, {bs[389]:+.5f})"
    print(f"| {k} | {r['brier'].mean():.4f} | {r['ll'].mean():.4f} | {r['rps'].mean():.4f} | {100*r['draw_pred']:.1f} | {100*r['draw_act']:.1f} | {r['auc']:.3f} | {ci} |")
