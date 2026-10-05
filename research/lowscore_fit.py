import sys, pickle, math, random
sys.path.insert(0, '.')
from lab2 import CACHE
from football.history_model import _poisson
from datetime import date
rows = pickle.load(open(f'{CACHE}/bias_rows_v2.pkl', 'rb'))
MAXG = 10
for r in rows:
    ph = [_poisson(i, r['lh']) for i in range(MAXG + 1)]; pa = [_poisson(j, r['la']) for j in range(MAXG + 1)]
    r['base'] = {(i, j): ph[i] * pa[j] for i in range(MAXG + 1) for j in range(MAXG + 1)}
train = [r for r in rows if r['day'] < date(2024, 1, 1)]; test = [r for r in rows if r['day'] >= date(2024, 1, 1)]
CELLS = [(0, 0), (1, 0), (0, 1), (1, 1)]            # free multipliers; diagonal 2-2, 3-3... get one shared multiplier 'dg'
def adj(r, m, dg):
    g = {}; tot = 0.0
    for k, p in r['base'].items():
        f = m.get(k, 1.0)
        if k[0] == k[1] and k[0] >= 2: f = dg
        g[k] = p * f; tot += g[k]
    return g, tot
def loglik(rs, m, dg, rho=None):
    ll = 0.0
    for r in rs:
        g, tot = adj(r, m, dg); ll += math.log(max(1e-12, g.get((r['hg'], r['ag']), 1e-12) / tot)) if r['hg'] <= MAXG and r['ag'] <= MAXG else 0
    return ll
def dc_loglik(rs, rho):
    from football.history_model import _dc_tau
    ll = 0.0
    for r in rs:
        g = {k: p * max(0, _dc_tau(k[0], k[1], r['lh'], r['la'], rho)) for k, p in r['base'].items()}; tot = sum(g.values())
        ll += math.log(max(1e-12, g.get((r['hg'], r['ag']), 1e-12) / tot)) if r['hg'] <= MAXG and r['ag'] <= MAXG else 0
    return ll
# fit multipliers by coordinate search on the training period
m = {c: 1.0 for c in CELLS}; dg = 1.0; best = loglik(train, m, dg)
for sweep in range(4):
    for key in CELLS + ['dg']:
        for step in (0.08, 0.04, 0.02, 0.01):
            for sign in (1, -1):
                trial_m, trial_dg = dict(m), dg
                if key == 'dg': trial_dg = dg * (1 + sign * step)
                else: trial_m[key] = m[key] * (1 + sign * step)
                v = loglik(train, trial_m, trial_dg)
                if v > best + 1e-9: best, m, dg = v, trial_m, trial_dg
print('free low-score multipliers fitted on 2018-2023:', {f'{k[0]}-{k[1]}': round(v, 3) for k, v in m.items()}, 'diagonal 2-2+ x', round(dg, 3))
print(f'score log-likelihood per match on 2024-26 (higher is better): plain Poisson {loglik(test, {}, 1.0)/len(test):.4f} | Dixon-Coles rho=-0.05 {dc_loglik(test, -0.05)/len(test):.4f} | free multipliers {loglik(test, m, dg)/len(test):.4f}')
def outcome_ll(rs, grid_fn):
    ll = 0.0; b = 0.0; dr = 0.0
    for r in rs:
        g, tot = grid_fn(r); H = sum(p for (i, j), p in g.items() if i > j) / tot; D = sum(p for (i, j), p in g.items() if i == j) / tot; A = 1 - H - D
        o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2); p = (H, D, A); ll += -math.log(max(p[o], 1e-9)); b += sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3)); dr += D
    return ll / len(rs), b / len(rs), dr / len(rs)
from football.history_model import _dc_tau
dc_grid = lambda r: ((lambda g: (g, sum(g.values())))({k: p * max(0, _dc_tau(k[0], k[1], r['lh'], r['la'], -0.05)) for k, p in r['base'].items()}))
free_grid = lambda r: adj(r, m, dg)
for name, fn in (('Dixon-Coles rho=-0.05 (current)', dc_grid), ('free multipliers', free_grid)):
    l, b, d = outcome_ll(test, fn); print(f'  2024-26 outcomes {name:34} log-loss {l:.4f} Brier {b:.4f} mean draw {100*d:.2f}% (actual {100*sum(1 for r in test if r["hg"]==r["ag"])/len(test):.2f}%)')
# paired bootstrap of the outcome log-loss difference
def per_match(fn):
    out = []
    for r in test:
        g, tot = fn(r); H = sum(p for (i, j), p in g.items() if i > j) / tot; D = sum(p for (i, j), p in g.items() if i == j) / tot; A = 1 - H - D
        o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2); out.append(-math.log(max((H, D, A)[o], 1e-9)))
    return out
a, b = per_match(dc_grid), per_match(free_grid); d = [y - x for x, y in zip(a, b)]; n = len(d); rng = random.Random(0)
bs = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(2000))
print(f'outcome log-loss, free minus Dixon-Coles: {sum(d)/n:+.5f}  95% CI [{bs[50]:+.5f}, {bs[1950]:+.5f}] (n={n})')
