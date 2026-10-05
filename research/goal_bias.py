import sys, math, pickle, os
sys.path.insert(0, '.')
from lab2 import *
from football.history_model import expected_goals, score_grid
from datetime import date
W = {'2018-21': (date(2018, 1, 1), date(2022, 1, 1)), '2022-23': (date(2022, 1, 1), date(2024, 1, 1)), '2024-26': TEST}
cache = f'{CACHE}/goal_bias_rows.pkl'
if os.path.exists(cache): rows = pickle.load(open(cache, 'rb'))
else:
    rows = {}
    for name, w in W.items():
        rs = []
        for bs, be in block_starts(w, 1):
            model = H.fit(ALL, bs, ridge=0.5)
            for m in ALL:
                if bs <= m.day < be:
                    r = expected_goals(model, m.home, m.away, m.neutral)
                    if r: rs.append((r[0], r[1], m.hg, m.ag, model.rho, m.neutral, m.tournament))
        rows[name] = rs
    pickle.dump(rows, open(cache, 'wb'))
print(f"{'period':8} {'n':>5} | home goals pred / actual / ratio | away pred / actual / ratio | non-neutral home ratio | neutral home ratio")
for name, rs in rows.items():
    n = len(rs); hp, ha = sum(r[0] for r in rs) / n, sum(r[2] for r in rs) / n; ap, aa = sum(r[1] for r in rs) / n, sum(r[3] for r in rs) / n
    nn = [r for r in rs if not r[5]]; ne = [r for r in rs if r[5]]
    rr = lambda b: sum(r[2] for r in b) / sum(r[0] for r in b) if b else float('nan')
    print(f'{name:8} {n:>5} | {hp:.3f} / {ha:.3f} / {ha/hp:.3f}       | {ap:.3f} / {aa:.3f} / {aa/ap:.3f}   | {rr(nn):.3f} (n={len(nn)})      | {rr(ne):.3f} (n={len(ne)})')
def probs(r, kh, ka):
    g = score_grid(min(6.0, r[0] * kh), min(6.0, r[1] * ka), r[4])
    return (sum(p for (i, j), p in g.items() if i > j), sum(p for (i, j), p in g.items() if i == j), sum(p for (i, j), p in g.items() if i < j))
def score(rs, kh, ka):
    b = l = 0
    for r in rs:
        p = probs(r, kh, ka); o = 0 if r[2] > r[3] else (1 if r[2] == r[3] else 2)
        b += sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3)); l += -math.log(max(p[o], 1e-9))
    return b / len(rs), l / len(rs)
fit = rows['2018-21'] + rows['2022-23']; kh = sum(r[2] for r in fit) / sum(r[0] for r in fit); ka = sum(r[3] for r in fit) / sum(r[1] for r in fit)
print(f'\nmultipliers fitted on 2018-23 only: home x{kh:.3f}, away x{ka:.3f}')
test = rows['2024-26']
print(f"{'2024-26 held-out':24} {'Brier':>8} {'log-loss':>9}")
for name, (a, b) in (('model as is', (1.0, 1.0)), ('home multiplier only', (kh, 1.0)), ('both multipliers', (kh, ka))):
    s = score(test, a, b); print(f'{name:24} {s[0]:>8.4f} {s[1]:>9.4f}')
