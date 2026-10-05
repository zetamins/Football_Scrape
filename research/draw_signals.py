"""Do team draw tendency / low-scoring form add information about draws beyond the model's draw probability?
Features come only from each team's previous 10 matches (strictly before kickoff); logistic fit on 2018-2023, scored on 2024-26."""
import sys, glob, pickle, math, collections
sys.path.insert(0, '.')
from lab2 import *
from datetime import date
pred = {}
for f in sorted(glob.glob(f'{CACHE}/prod_blend_m1.*.pkl')):
    pred.update({i: p for i, p in pickle.load(open(f, 'rb')) if p is not None})
hist = collections.defaultdict(list)       # team -> [(gf, ga)] oldest..newest
rows = []
for i, m in enumerate(ALL):
    if i in pred:
        h, a = hist[m.home][-10:], hist[m.away][-10:]
        if len(h) >= 6 and len(a) >= 6:
            def feats(g):
                n = len(g)
                return (sum(1 for x, y in g if x == y) / n, sum(x + y for x, y in g) / n, sum(1 for x, y in g if x + y <= 1) / n)
            fh, fa = feats(h), feats(a)
            p = pred[i]
            rows.append({'day': m.day, 'draw': 1 if m.hg == m.ag else 0, 'pd': p[1], 'close': 1 - abs(p[0] - p[2]),
                         'draw_share': (fh[0] + fa[0]) / 2, 'total_goals': (fh[1] + fa[1]) / 2, 'low_share': (fh[2] + fa[2]) / 2})
    hist[m.home].append((m.hg, m.ag)); hist[m.away].append((m.ag, m.hg))
print('matches with both teams having >=6 prior games:', len(rows))
def logit(p): p = min(max(p, 1e-3), 1 - 1e-3); return math.log(p / (1 - p))
def fit(rs, keys, iters=500, lr=0.5):
    w = [0.0] * (len(keys) + 1); mu = [sum(r[k] for r in rs) / len(rs) for k in keys]; sd = [max(1e-6, math.sqrt(sum((r[k] - mu[j]) ** 2 for r in rs) / len(rs))) for j, k in enumerate(keys)]
    for _ in range(iters):
        g = [0.0] * len(w)
        for r in rs:
            x = [1.0] + [(r[k] - mu[j]) / sd[j] for j, k in enumerate(keys)]
            z = sum(a * b for a, b in zip(w, x)); q = 1 / (1 + math.exp(-z))
            for j in range(len(w)): g[j] += (q - r['draw']) * x[j]
        w = [a - lr * b / len(rs) for a, b in zip(w, g)]
    return w, mu, sd
def predict(model, r, keys):
    w, mu, sd = model; x = [1.0] + [(r[k] - mu[j]) / sd[j] for j, k in enumerate(keys)]
    return 1 / (1 + math.exp(-sum(a * b for a, b in zip(w, x))))
def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]; neg = [s for s, l in zip(scores, labels) if not l]
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))
for r in rows: r['lpd'] = logit(r['pd'])
train = [r for r in rows if r['day'] < date(2024, 1, 1)]; test = [r for r in rows if r['day'] >= date(2024, 1, 1)]
print(f'train {len(train)} (2018-23) | test {len(test)} (2024-26), test draw rate {sum(r["draw"] for r in test)/len(test):.3f}')
def ll(rs, ps): return -sum(math.log(max(1e-9, p if r['draw'] else 1 - p)) for r, p in zip(rs, ps)) / len(rs)
base_ll = ll(test, [r['pd'] for r in test]); base_auc = auc([r['pd'] for r in test], [r['draw'] for r in test])
print(f"{'model':46} {'AUC':>6} {'log-loss':>9}")
print(f"{'model draw prob alone':46} {base_auc:>6.3f} {base_ll:>9.4f}")
for name, keys in (('+ team draw tendency', ['lpd', 'draw_share']), ('+ low-scoring tendency', ['lpd', 'low_share']), ('+ expected total goals (recent)', ['lpd', 'total_goals']), ('+ all three', ['lpd', 'draw_share', 'low_share', 'total_goals'])):
    m = fit(train, keys); ps = [predict(m, r, keys) for r in test]
    print(f'{name:46} {auc(ps, [r["draw"] for r in test]):>6.3f} {ll(test, ps):>9.4f}   weights(std) ' + ', '.join(f'{k}={m[0][j+1]:+.2f}' for j, k in enumerate(keys)))
# rule-of-thumb tiers: actual draw rate by combined signal on the test period
tier = sorted(test, key=lambda r: r['pd'])
for lo, hi in ((0, 0.34), (0.34, 0.67), (0.67, 1.0)):
    b = tier[int(lo * len(tier)):int(hi * len(tier))]
    print(f'model draw-prob tercile {lo:.2f}-{hi:.2f}: actual draw {sum(r["draw"] for r in b)/len(b):.3f}  (mean model {sum(r["pd"] for r in b)/len(b):.3f})')
