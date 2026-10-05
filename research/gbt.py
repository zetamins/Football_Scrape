"""Pi-ratings + gradient boosting / logistic stack experiment (needs numpy, scikit-learn, lightgbm:
   uv run --with scikit-learn --with numpy --with lightgbm python research/gbt.py).
Features are strictly pre-match (computed sequentially, state updated after each match); models are retrained
every 6 months on matches before the block. The Poisson model's out-of-sample rolling probabilities are an
optional stacking feature (NaN before 2014 -> boosting handles missing natively)."""
import sys, os, time, math, pickle, collections, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings('ignore')
import numpy as np
from lab2 import *            # noqa
from lab2 import CONFED
from pi import PiRatings
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
import lightgbm as lgb

PRE = (date(2014, 1, 1), date(2022, 1, 1))
def rps(p, o):
    cum_p = (p[0], p[0] + p[1]); cum_o = (1.0 if o == 0 else 0.0, 1.0 if o <= 1 else 0.0)
    return ((cum_p[0] - cum_o[0]) ** 2 + (cum_p[1] - cum_o[1]) ** 2) / 2

def build_features():
    pi = PiRatings(); elo = Elo(k=40, kf=20)
    last = {}; hist = collections.defaultdict(list)
    cats = H.CATEGORIES; rows = []
    def ctx(t, day):
        h = hist[t]; rest = min(30, (day - last[t]).days) if t in last else 30
        l5 = h[-5:]; l10 = h[-10:]
        gd5 = sum(a - b for a, b in l5) / len(l5) if l5 else 0.0
        gf = sum(a for a, b in l10) / len(l10) if l10 else 1.3
        ga = sum(b for a, b in l10) / len(l10) if l10 else 1.3
        n365 = sum(1 for x in h[-20:] if True)  # games among last 20 (cheap activity proxy)
        return rest, gd5, gf, ga, min(len(h), 20)
    for m in ALL:
        hh, ha, ah, aa, exp = pi.pre(m)
        eh = elo.diff(m)
        rh, g5h, gfh, gah, nh = ctx(m.home, m.day); ra, g5a, gfa, gaa, na = ctx(m.away, m.day)
        cat = H.tournament_category(m.tournament)
        same = 1.0 if CONFED.get(m.home, 'a') == CONFED.get(m.away, 'b') else 0.0
        x = [hh, ha, ah, aa, exp, eh / 400.0, 1.0 if m.neutral else 0.0, (rh - ra) / 30.0, g5h, g5a, gfh, gah, gfa, gaa, nh, na, same] + [1.0 if cat == c else 0.0 for c in cats]
        rows.append(x)
        pi.update(m); elo.update(m)
        last[m.home] = m.day; last[m.away] = m.day
        hist[m.home].append((m.hg, m.ag)); hist[m.away].append((m.ag, m.hg))
    return np.array(rows, dtype=float)

FEATS = build_features()
Y = np.array([outcome(m) for m in ALL])
DAYS = [m.day for m in ALL]
FIRST_TRAIN = date(2010, 1, 1)
base_res = {n: dict(run_candidate(n, f, w)) for n, f, w in [('pois_r05_pre', poisson(ridge=0.5), PRE)] }
def poisson_oos(window):
    return dict(run_candidate('pois_r05_win', poisson(ridge=0.5), window))
POIS = {}
for w in (PRE, VAL, TEST):
    POIS.update({i: p for i, p in poisson_oos(w).items() if p is not None})
def with_pois(idx_list):
    return np.array([list(POIS.get(i, (np.nan,) * 3)) for i in idx_list], dtype=float)

def make_models():
    return {
        'logit_lite': lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500)),
        'logit_pi': lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500)),
        'hgb_pi': lambda: HistGradientBoostingClassifier(max_iter=150, learning_rate=0.04, max_depth=3, min_samples_leaf=60, l2_regularization=3.0, random_state=0),
        'lgb_pi': lambda: lgb.LGBMClassifier(n_estimators=250, learning_rate=0.03, num_leaves=8, min_child_samples=80, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, random_state=0, verbose=-1),
    }

LITE_COLS = [0, 1, 2, 3, 4, 5, 6]   # pi home/away ratings of both teams, expected GD, Elo gap, neutral flag

def rolling(window, model_name, stack=False, months=6):
    path = f'{CACHE}/gbt_{model_name}_{int(stack)}.{window[0]}.{window[1]}.pkl'
    if os.path.exists(path): return pickle.load(open(path, 'rb'))
    out = []
    for bs, be in block_starts(window, months):
        tr = [i for i, d in enumerate(DAYS) if FIRST_TRAIN <= d < bs and (not stack or d >= PRE[0])]
        te = [i for i, d in enumerate(DAYS) if bs <= d < be]
        F = FEATS[:, LITE_COLS] if model_name == 'logit_lite' else FEATS
        Xtr, Xte = F[tr], F[te]
        if stack: Xtr = np.hstack([Xtr, with_pois(tr)]); Xte = np.hstack([Xte, with_pois(te)])
        if stack and model_name == 'logit_pi':
            Xtr = np.nan_to_num(Xtr, nan=1 / 3); Xte = np.nan_to_num(Xte, nan=1 / 3)
        mdl = make_models()[model_name](); mdl.fit(Xtr, Y[tr])
        P = mdl.predict_proba(Xte)
        for i, p in zip(te, P): out.append((i, tuple(float(v) for v in p)))
    pickle.dump(out, open(path, 'wb')); return out

def report(R, window_name, idx, ref):
    print(f'\n=== {window_name}  (n={len(idx)})')
    rows = []
    for n, r in R.items():
        d = dict(r); b = l = a = q = 0.0
        for i in idx:
            p = d[i]; o = outcome(ALL[i]); b += brier(p, o); l += logloss(p, o); q += rps(p, o); a += (max(range(3), key=lambda j: p[j]) == o)
        rows.append((b / len(idx), l / len(idx), q / len(idx), a / len(idx), n))
    for rank, (b, l, q, a, n) in enumerate(sorted(rows), 1):
        extra = ''
        if n != ref:
            m, lo, hi = paired_boot(R[n], R[ref], idx); extra = f'  vs {ref}: {m:+.4f} [{lo:+.4f},{hi:+.4f}]' + (' *' if hi < 0 or lo > 0 else '')
        print(f'{rank:2d}. {n:26} brier {b:.4f} rps {q:.4f} logloss {l:.4f} acc {a:.3f}{extra}')

if __name__ == '__main__':
    t0 = time.time()
    SEARCH = (date(2018, 1, 1), date(2022, 1, 1))
    for w in (SEARCH,): POIS.update({i: p for i, p in poisson_oos(w).items() if p is not None})
    for wname, window in (('INDEPENDENT 2018-21 (not used to pick candidates)', SEARCH), ('VALIDATION 2022-23', VAL), ('TEST 2024-26', TEST)):
        R = {'pois_r05 (current)': run_candidate('pois_r05_win', poisson(ridge=0.5), window)}
        R['elo_logit_k40'] = run_candidate('elo_logit_k40', elo_logit(k=40, kf=20), window)
        for mn in ('logit_lite', 'logit_pi', 'hgb_pi', 'lgb_pi'):
            R[mn] = rolling(window, mn); print(mn, 'done', round(time.time() - t0), flush=True)
        for mn in ('logit_pi', 'hgb_pi', 'lgb_pi'):
            R[mn + '+pois_stack'] = rolling(window, mn, stack=True); print(mn, 'stack done', round(time.time() - t0), flush=True)
        R['blend50 pois+lgb_pi'] = blend([R['pois_r05 (current)'], R['lgb_pi']], [0.5, 0.5])
        R['blend50 pois+hgb_pi'] = blend([R['pois_r05 (current)'], R['hgb_pi']], [0.5, 0.5])
        R['blend70 pois+logit_lite'] = blend([R['pois_r05 (current)'], R['logit_lite']], [0.7, 0.3])
        R['blend50 pois+logit_lite'] = blend([R['pois_r05 (current)'], R['logit_lite']], [0.5, 0.5])
        R['blend70 pois+logit_pi'] = blend([R['pois_r05 (current)'], R['logit_pi']], [0.7, 0.3])
        R['blend3 pois+lgb+logit'] = blend([R['pois_r05 (current)'], R['lgb_pi'], R['logit_pi']], [0.5, 0.25, 0.25])
        idx = common_index(R)
        report(R, wname, idx, 'pois_r05 (current)')
    print('secs', round(time.time() - t0))
