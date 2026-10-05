"""Out-of-sample check of the recommended-bet thresholds: pick (goals-bet minimum, double-chance trigger) on matches BEFORE 2024, then measure on 2024 onwards only."""
import sys, itertools
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
KS = 0.2
data = []
for r in rows:
    p1, _, _ = markets(r, 0); _, over, btts = markets(r, KS)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    c = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over 2.5': (over, r['hg'] + r['ag'] > 2), 'Under 2.5': (1 - over, r['hg'] + r['ag'] <= 2),
         'BTTS Yes': (btts, r['hg'] > 0 and r['ag'] > 0), 'BTTS No': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
    dc = max(((p1[0] + p1[1], o in (0, 1)), (p1[1] + p1[2], o in (1, 2)), (p1[0] + p1[2], o in (0, 2))))
    data.append((r['day'].year, c, dc))
def hit(sub, gmin, dtrig):
    h = []
    for _, c, dc in sub:
        elig = {k: v for k, v in c.items() if k == '1X2' or v[0] >= gmin}
        if c['1X2'][0] < dtrig: elig['DC'] = dc
        h.append(elig[max(elig, key=lambda k: elig[k][0])][1])
    return np.mean(h)
train = [d for d in data if d[0] < 2024]; test = [d for d in data if d[0] >= 2024]
print(f"train {len(train)} matches (before 2024), test {len(test)} (2024 on)")
grid = list(itertools.product((0.50, 0.55, 0.60, 0.65, 0.70, 1.01), (0.0, 0.40, 0.45, 0.50, 0.55)))
res = sorted(((hit(train, g, t), g, t) for g, t in grid), reverse=True)
print("top 5 on train:"); [print(f"  goals>={g:.2f} dc<{t:.2f}: train {100*a:.1f}%  test {100*hit(test, g, t):.1f}%") for a, g, t in res[:5]]
best = res[0]
print(f"\nselected on train: goals>={best[1]:.2f}, dc<{best[2]:.2f}  ->  TEST hit rate {100*hit(test, best[1], best[2]):.1f}%")
print(f"current rule (0.60, 0.50): train {100*hit(train, .6, .5):.1f}%, TEST {100*hit(test, .6, .5):.1f}%")
print(f"old rule (any probability, no double chance): TEST {100*hit(test, 0.0, 0.0):.1f}%;  1X2 only: TEST {100*hit(test, 1.01, 0.0):.1f}%")
