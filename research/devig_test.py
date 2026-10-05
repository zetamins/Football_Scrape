import csv, glob, math, random, os
def read():
    rows = []
    for f in sorted(glob.glob('.cache/odds/*.csv')):
        for r in csv.DictReader(open(f, encoding='utf-8-sig', errors='replace')):
            try:
                o = [float(r['AvgH']), float(r['AvgD']), float(r['AvgA'])]; res = {'H': 0, 'D': 1, 'A': 2}[r['FTR']]
            except (KeyError, ValueError): continue
            if min(o) > 1: rows.append((os.path.basename(f)[:2], o, res))
    return rows
def proportional(o):
    q = [1 / x for x in o]; s = sum(q); return [x / s for x in q]
def additive(o):
    q = [1 / x for x in o]; m = (sum(q) - 1) / 3; p = [max(1e-6, x - m) for x in q]; s = sum(p); return [x / s for x in p]
def power(o):
    q = [1 / x for x in o]; lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if sum(x ** k for x in q) > 1: lo = k
        else: hi = k
    p = [x ** ((lo + hi) / 2) for x in q]; s = sum(p); return [x / s for x in p]
def shin(o):
    q = [1 / x for x in o]; B = sum(q); lo, hi = 0.0, 0.4
    def probs(z): return [(math.sqrt(z * z + 4 * (1 - z) * x * x / B) - z) / (2 * (1 - z)) for x in q]
    for _ in range(60):
        z = (lo + hi) / 2
        if sum(probs(z)) > 1: lo = z
        else: hi = z
    p = probs((lo + hi) / 2); s = sum(p); return [x / s for x in p]
METHODS = {'proportional (current)': proportional, 'additive (equal margin)': additive, 'power': power, 'Shin': shin}
rows = read(); n = len(rows)
print(f'{n} matches with average odds ({len(set(r[0] for r in rows))} leagues, 3 seasons); mean margin {100*(sum(sum(1/x for x in r[1]) for r in rows)/n-1):.1f}%')
def brier(p, o): return sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
def ll(p, o): return -math.log(max(p[o], 1e-9))
def rps(p, o):
    c = (p[0], p[0] + p[1]); t = (1.0 if o == 0 else 0.0, 1.0 if o <= 1 else 0.0); return ((c[0] - t[0]) ** 2 + (c[1] - t[1]) ** 2) / 2
P = {name: [fn(r[1]) for r in rows] for name, fn in METHODS.items()}
rng = random.Random(0)
print(f"\n{'method':26} {'Brier':>8} {'log-loss':>9} {'RPS':>8} {'Brier diff vs proportional (95% CI)':>40}")
base = [brier(p, r[2]) for p, r in zip(P['proportional (current)'], rows)]
for name in METHODS:
    b = [brier(p, r[2]) for p, r in zip(P[name], rows)]; l = sum(ll(p, r[2]) for p, r in zip(P[name], rows)) / n; q = sum(rps(p, r[2]) for p, r in zip(P[name], rows)) / n
    d = [x - y for x, y in zip(b, base)]; bs = sorted(sum(rng.choice(d) for _ in range(1500)) / 1500 for _ in range(300)) if name != 'proportional (current)' else None
    ci = f'{sum(d)/n:+.5f}  [{bs[7]:+.5f}, {bs[292]:+.5f}]' if bs else '-'
    print(f'{name:26} {sum(b)/n:>8.4f} {l:>9.4f} {q:>8.4f} {ci:>40}')
print('\nreliability of the odds-implied DRAW probability (Shin) and how well it ranks draws')
pd = [(P['Shin'][i][1], rows[i][2] == 1) for i in range(n)]
edges = [0, .22, .25, .27, .29, .31, .34, 1]
print(f"{'draw prob':>12} {'n':>5} {'mean pred':>10} {'actual':>8}")
for lo, hi in zip(edges, edges[1:]):
    b = [x for x in pd if lo <= x[0] < hi]
    if b: print(f'{lo:.2f}-{min(hi,1):.2f}   {len(b):>5} {sum(x[0] for x in b)/len(b):>10.3f} {sum(x[1] for x in b)/len(b):>8.3f}')
pos = [s for s, l in pd if l]; neg = [s for s, l in pd if not l]
auc = sum((a > b) + 0.5 * (a == b) for a in pos[:800] for b in neg[:2000]) / (len(pos[:800]) * len(neg[:2000]))
print(f'AUC of the odds draw probability for draws: {auc:.3f} (history model on internationals: 0.645); draw rate {100*sum(1 for _,l in pd if l)/n:.1f}%, mean predicted {100*sum(s for s,_ in pd)/n:.1f}%')
print('\nfavourite-longshot check: actual vs implied win rate of the LONGSHOT side (proportional)')
for lo, hi in ((0, .10), (.10, .20), (.20, .35)):
    b = [(min(p[0], p[2]), (rows[i][2] == (0 if p[0] < p[2] else 2))) for i, p in enumerate(P['proportional (current)']) if lo <= min(p[0], p[2]) < hi]
    print(f'  longshot implied {lo:.2f}-{hi:.2f}: n={len(b):4d} implied {sum(x[0] for x in b)/len(b):.3f} actual {sum(x[1] for x in b)/len(b):.3f}')
