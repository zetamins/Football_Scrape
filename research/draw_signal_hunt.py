"""Is there learnable information about draws that the Poisson/Dixon-Coles model misses? Out of sample: fit on matches before 2024, score on 2024-26."""
import sys, pickle, math, collections, warnings, random
sys.path.insert(0, '.'); warnings.filterwarnings('ignore')
import numpy as np
from datetime import date
from lab2 import ALL, CACHE, CONFED
import football.history_train as H
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score, log_loss
rows = pickle.load(open(f'{CACHE}/bias_rows_v2.pkl', 'rb'))
# ---- pre-match history features from the archive (strictly before each match)
hist = collections.defaultdict(list)       # team -> [(day, gf, ga)]
pair = collections.defaultdict(list)       # frozenset -> [(day, drew)]
feat = {}
for m in ALL:
    def tf(t, n=10):
        h = hist[t][-n:]
        if len(h) < 3: return (0.23, 2.6, 0.09, 0.5, 400.0, 0)
        draws = sum(1 for d, a, b in h if a == b) / len(h); tot = sum(a + b for d, a, b in h) / len(h); zz = sum(1 for d, a, b in h if a + b == 0) / len(h)
        low = sum(1 for d, a, b in h if a + b <= 1) / len(h); gap = min(400.0, (m.day - hist[t][-1][0]).days); n4 = sum(1 for d, a, b in hist[t][-60:] if (m.day - d).days <= 1460)
        return (draws, tot, zz, low, gap, n4)
    th, ta = tf(m.home), tf(m.away); pr = pair[frozenset((m.home, m.away))][-5:]
    feat[(m.day, m.home, m.away)] = (th, ta, (sum(1 for d, x in pr if x) / len(pr)) if pr else 0.23, len(pr))
    hist[m.home].append((m.day, m.hg, m.ag)); hist[m.away].append((m.day, m.ag, m.hg)); pair[frozenset((m.home, m.away))].append((m.day, m.hg == m.ag))
CATS = ('friendly', 'qualifier', 'nations_league', 'major', 'other'); CONFS = ('CAF', 'UEFA', 'AFC', 'CONCACAF', 'CONMEBOL', 'OFC')
def vec(r):
    th, ta, h2h, nh = feat[(r['day'], r['home'], r['away'])]; p = r['p']; cat = H.tournament_category(r['tour'])
    hc, ac = CONFED.get(r['home'], '?'), CONFED.get(r['away'], '?')
    return [math.log(p[1] / (1 - p[1])), p[0], p[2], abs(p[0] - p[2]), r['lh'] + r['la'], abs(r['lh'] - r['la']), r['att_h'] + r['att_a'], r['def_h'] + r['def_a'],
            float(r['neutral']), float(hc == ac), r['day'].month, (r['day'].year - 2018),
            (th[0] + ta[0]) / 2, (th[1] + ta[1]) / 2, (th[2] + ta[2]) / 2, (th[3] + ta[3]) / 2, min(th[4], ta[4]), max(th[4], ta[4]), min(th[5], ta[5]), h2h, nh] + \
           [float(cat == c) for c in CATS] + [float(hc == c) for c in CONFS]
NAMES = ['logit(model draw)', 'P(home)', 'P(away)', '|H-A| closeness', 'expected total goals', '|lambda gap|', 'attack sum', 'defence sum', 'neutral', 'same confederation', 'month', 'year trend',
         'teams recent draw share', 'teams recent total goals', 'teams recent 0-0 share', 'teams recent low-scoring share', 'min days since last match', 'max days since last match', 'min matches in 4y',
         'head-to-head draw share', 'head-to-head meetings'] + [f'tournament {c}' for c in CATS] + [f'host confed {c}' for c in CONFS]
tr = [r for r in rows if r['day'] < date(2024, 1, 1)]; te = [r for r in rows if r['day'] >= date(2024, 1, 1)]
Xtr, Xte = np.array([vec(r) for r in tr]), np.array([vec(r) for r in te]); ytr = np.array([int(r['hg'] == r['ag']) for r in tr]); yte = np.array([int(r['hg'] == r['ag']) for r in te])
print(f'train {len(tr)} (2018-23), test {len(te)} (2024-26); draw rate train {ytr.mean():.3f} test {yte.mean():.3f}; features {len(NAMES)}')
base_p = np.array([r['p'][1] for r in te]); res = {}
res['model draw probability as is'] = base_p
lr1 = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=500)).fit(Xtr[:, :1], ytr); res['recalibrated (stretch/shift of the draw logit)'] = lr1.predict_proba(Xte[:, :1])[:, 1]
lr2 = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=800)).fit(Xtr, ytr); res['+ all features (logistic, L2)'] = lr2.predict_proba(Xte)[:, 1]
gb = HistGradientBoostingClassifier(max_iter=120, learning_rate=0.03, max_depth=3, min_samples_leaf=120, l2_regularization=5.0, random_state=0).fit(Xtr, ytr); res['+ all features (gradient boosting)'] = gb.predict_proba(Xte)[:, 1]
rng = random.Random(0); n = len(te)
def per(p): return [-(math.log(max(x, 1e-9)) if y else math.log(max(1 - x, 1e-9))) for x, y in zip(p, yte)]
b = per(base_p)
print(f"\n{'model':48} {'AUC':>6} {'log-loss':>9} {'mean pred':>9} {'diff vs as-is (95% CI)':>34}")
for name, p in res.items():
    ll = per(p); d = [x - y for x, y in zip(ll, b)]; bs = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(1500))
    print(f'{name:48} {roc_auc_score(yte, p):>6.3f} {sum(ll)/n:>9.4f} {p.mean():>9.3f} ' + (f'{sum(d)/n:+.5f} [{bs[37]:+.5f}, {bs[1462]:+.5f}]' if name != 'model draw probability as is' else '-'))
print('\nlogistic recalibration of the draw logit: ' + ', '.join(f'{k}={v:.3f}' for k, v in zip(('intercept', 'slope (per std dev)'), (lr1[-1].intercept_[0], lr1[-1].coef_[0][0]))))
# permutation importance of the boosted model (drop in AUC when a feature is shuffled)
base_auc = roc_auc_score(yte, res['+ all features (gradient boosting)']); imp = []
rs = np.random.RandomState(0)
for j, nm in enumerate(NAMES):
    drops = []
    for _ in range(5):
        Xp = Xte.copy(); Xp[:, j] = rs.permutation(Xp[:, j]); drops.append(base_auc - roc_auc_score(yte, gb.predict_proba(Xp)[:, 1]))
    imp.append((sum(drops) / 5, nm))
print('\npermutation importance in the boosted model (AUC drop when shuffled), top 8:', [(nm, f'{d:+.4f}') for d, nm in sorted(imp, reverse=True)[:8]])
