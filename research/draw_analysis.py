import sys, glob, pickle, math, collections
sys.path.insert(0, '.')
from lab2 import *
from datetime import date
res = []
for f in sorted(glob.glob(f'{CACHE}/prod_blend_m1.*.pkl')):
    res += [(i, p) for i, p in pickle.load(open(f, 'rb')) if p is not None]
rows = [(p, outcome(ALL[i]) == 1, ALL[i]) for i, p in res]
n = len(rows); base = sum(r[1] for r in rows) / n
print(f'{n} held-out matches 2018-26 | actual draw rate {base:.3f} | mean predicted draw {sum(r[0][1] for r in rows)/n:.3f}')
def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]; neg = [s for s, l in zip(scores, labels) if not l]
    wins = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg[:1500]) / (len(pos) * len(neg[:1500]))
    return wins
print('AUC of predicted draw prob for draws:', round(auc([r[0][1] for r in rows], [r[1] for r in rows]), 3), '(0.5 = no information)')
print('\nreliability of the draw probability')
print(f"{'predicted draw':>16} {'n':>5} {'mean pred':>10} {'actual':>8}")
edges = [0, .15, .19, .22, .25, .28, .31, 1]
for lo, hi in zip(edges, edges[1:]):
    b = [r for r in rows if lo <= r[0][1] < hi]
    if b: print(f'{lo:.2f}-{min(hi,1):.2f}       {len(b):>5} {sum(r[0][1] for r in b)/len(b):>10.3f} {sum(r[1] for r in b)/len(b):>8.3f}')
print('\nsimple draw-prone signals (do they raise the draw rate beyond the model?)')
def best(p): return max(p)
def closeness(p): return abs(p[0] - p[2])
groups = {
 'close match (|H-A| < 0.10)': lambda r: closeness(r[0]) < 0.10,
 'mismatch (favourite > 0.70)': lambda r: best(r[0]) > 0.70,
 'both: favourite 0.45-0.60': lambda r: 0.45 <= best(r[0]) <= 0.60,
}
for name, fn in groups.items():
    b = [r for r in rows if fn(r)]
    print(f'  {name:32} n={len(b):4d} actual draw {sum(r[1] for r in b)/len(b):.3f}  model draw {sum(r[0][1] for r in b)/len(b):.3f}')
# context signals from the archive itself: friendlies vs competitive, neutral, low-scoring teams
def tournament(r): return H.tournament_category(r[2].tournament)
for cat in ('friendly', 'qualifier', 'nations_league', 'major', 'other'):
    b = [r for r in rows if tournament(r) == cat]
    if b: print(f'  {cat:16} n={len(b):4d} actual draw {sum(r[1] for r in b)/len(b):.3f}  model draw {sum(r[0][1] for r in b)/len(b):.3f}')
b = [r for r in rows if r[2].neutral]; print(f'  neutral venue    n={len(b):4d} actual draw {sum(r[1] for r in b)/len(b):.3f}  model draw {sum(r[0][1] for r in b)/len(b):.3f}')
# recalibration of the draw probability: logistic on logit(pD): fit 2018-2023, test 2024-26
def logit(p): return math.log(p / (1 - p))
train = [r for r in rows if r[2].day < date(2024, 1, 1)]; test = [r for r in rows if r[2].day >= date(2024, 1, 1)]
a, b_ = 0.0, 1.0
for _ in range(400):
    ga = gb = 0.0
    for p, d, _m in train:
        x = logit(min(max(p[1], 1e-3), 1 - 1e-3)); q = 1 / (1 + math.exp(-(a + b_ * x)))
        ga += q - d; gb += (q - d) * x
    a -= 1.0 * ga / len(train); b_ -= 1.0 * gb / len(train)
print(f'\nlogistic recalibration of P(draw) fit on {len(train)} (2018-23): intercept {a:+.3f} slope {b_:.3f}')
def ll(rs, f): return -sum(math.log(max(1e-9, (f(p) if d else 1 - f(p)))) for p, d, _ in rs) / len(rs)
f0 = lambda p: p[1]; f1 = lambda p: 1 / (1 + math.exp(-(a + b_ * logit(min(max(p[1], 1e-3), 1 - 1e-3)))))
print(f'test 2024-26 draw log-loss: raw {ll(test, f0):.4f}  recalibrated {ll(test, f1):.4f}  | mean pred raw {sum(f0(r[0]) for r in test)/len(test):.3f} recal {sum(f1(r[0]) for r in test)/len(test):.3f} actual {sum(r[1] for r in test)/len(test):.3f}')
