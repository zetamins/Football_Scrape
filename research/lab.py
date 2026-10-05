"""Experiment lab: every candidate is a factory(train_matches, as_of) -> predict(match)->(pH,pD,pA)|None.
Rolling-origin evaluation (refit every 6 months on data strictly before the block).
Predictions are cached to disk per candidate so passes can re-rank without refitting."""
import sys, os, json, math, pickle, time, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from datetime import date
from football import history_train as H
from football.history_model import FittedModel, score_grid, expected_goals

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.environ.get('FOOTBALL_LAB_DIR', os.path.join(HERE, '.cache'))   # results archive + prediction caches (gitignored)
CACHE = f'{S}/cache'
os.makedirs(CACHE, exist_ok=True)
_RESULTS = f'{S}/results.csv'
if not os.path.exists(_RESULTS):
    open(_RESULTS, 'w', encoding='utf8').write(H._get_text(H.ARCHIVE_URL))
ALL = [m for m in H.parse_archive(open(_RESULTS, encoding='utf8').read()) if H.tournament_category(m.tournament) != 'nonfifa']
ALL.sort(key=lambda m: m.day)

VAL = (date(2022, 1, 1), date(2024, 1, 1))
TEST = (date(2024, 1, 1), date(2027, 1, 1))

def outcome(m): return 0 if m.hg > m.ag else (1 if m.hg == m.ag else 2)
def brier(p, o): return sum((p[j] - (1 if j == o else 0)) ** 2 for j in range(3))
def logloss(p, o): return -math.log(max(p[o], 1e-9))

def block_starts(window, months=6):
    s, e = window; out = []; cur = s
    while cur < e:
        mm = cur.month - 1 + months
        nxt = date(cur.year + mm // 12, mm % 12 + 1, 1)
        out.append((cur, min(nxt, e))); cur = nxt
    return out

def run_candidate(name, factory, window, months=6):
    """Returns list of (match_index_in_ALL, probs|None) for matches in window."""
    path = f'{CACHE}/{name}.{window[0]}.{window[1]}.pkl'
    if os.path.exists(path):
        return pickle.load(open(path, 'rb'))
    out = []
    for bs, be in block_starts(window, months):
        train = [m for m in ALL if m.day < bs]
        predict = factory(train, bs)
        for i, m in enumerate(ALL):
            if bs <= m.day < be:
                out.append((i, predict(m)))
    pickle.dump(out, open(path, 'wb'))
    return out

def common_index(results_by_name):
    sets = [{i for i, p in r if p is not None} for r in results_by_name.values()]
    return sorted(set.intersection(*sets))

def score(results, idx):
    d = dict(results); b = l = a = 0.0
    for i in idx:
        p = d[i]; o = outcome(ALL[i])
        b += brier(p, o); l += logloss(p, o); a += (max(range(3), key=lambda j: p[j]) == o)
    n = len(idx); return b / n, l / n, a / n

def paired_boot(res_a, res_b, idx, n=2000, seed=0):
    da, db = dict(res_a), dict(res_b)
    diffs = [brier(da[i], outcome(ALL[i])) - brier(db[i], outcome(ALL[i])) for i in idx]
    rng = random.Random(seed); m = len(diffs)
    bs = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return sum(diffs) / m, bs[int(0.025 * n)], bs[int(0.975 * n)]

# ---------- candidate factories ----------
def poisson(cap=None, goal_transform=None, **params):
    def factory(train, as_of):
        tr = train
        if cap:
            tr = [H.Match(m.day, m.home, m.away, min(m.hg, cap), min(m.ag, cap), m.tournament, m.neutral) for m in train]
        model = H.fit(tr, as_of, **params)
        def predict(m):
            p = H.outcome_probs(model, m.home, m.away, m.neutral)
            return p
        return predict
    return factory

class Elo:
    def __init__(self, k=40, kf=20, home=100, margin=True, init=1500.0, decay_to_mean=0.0):
        self.r = {}; self.k = k; self.kf = kf; self.home = home; self.margin = margin; self.init = init
    def expect(self, m):
        return 1 / (1 + 10 ** (-(self.r.get(m.home, self.init) + (0 if m.neutral else self.home) - self.r.get(m.away, self.init)) / 400))
    def diff(self, m):
        return self.r.get(m.home, self.init) + (0 if m.neutral else self.home) - self.r.get(m.away, self.init)
    def update(self, m):
        e = self.expect(m); s = 1.0 if m.hg > m.ag else (0.5 if m.hg == m.ag else 0.0)
        k = self.kf if m.tournament == 'Friendly' else self.k
        d = abs(m.hg - m.ag)
        g = 1.0 if (not self.margin or d <= 1) else (1.5 if d == 2 else (11 + d) / 8)
        delta = k * g * (s - e)
        self.r[m.home] = self.r.get(m.home, self.init) + delta
        self.r[m.away] = self.r.get(m.away, self.init) - delta

def elo_davidson(nu=0.75, **ep):
    def factory(train, as_of):
        e = Elo(**ep)
        for m in train: e.update(m)
        def predict(m):
            if m.home not in e.r or m.away not in e.r: return None
            d = e.diff(m); ph = 10 ** (d / 800); pa = 10 ** (-d / 800)  # sqrt-scaled strengths
            dr = nu * 1.0
            z = ph + pa + dr; return (ph / z, dr / z, pa / z)
        return predict
    return factory

def _softmax(z):
    m = max(z); ex = [math.exp(v - m) for v in z]; s = sum(ex); return [v / s for v in ex]

def fit_softmax(X, y, iters=300, lr=0.5, l2=1e-3):
    k = len(X[0]); W = [[0.0] * k for _ in range(3)]
    n = len(X)
    for _ in range(iters):
        G = [[0.0] * k for _ in range(3)]
        for xi, yi in zip(X, y):
            p = _softmax([sum(W[c][j] * xi[j] for j in range(k)) for c in range(3)])
            for c in range(3):
                err = p[c] - (1 if c == yi else 0)
                for j in range(k): G[c][j] += err * xi[j]
        for c in range(3):
            for j in range(k): W[c][j] -= lr * (G[c][j] / n + l2 * W[c][j])
    return W

def elo_logit(window_years=12, **ep):
    """Elo ratings -> outcome probs via multinomial logit fitted on past (diff, |diff|, neutral) features."""
    def feats(d, neutral): x = d / 400.0; return [1.0, x, abs(x), x * x, 1.0 if neutral else 0.0]
    def factory(train, as_of):
        e = Elo(**ep); X = []; y = []
        for m in train:
            if m.home in e.r and m.away in e.r and m.day.year >= as_of.year - window_years:
                X.append(feats(e.diff(m), m.neutral)); y.append(outcome(m))
            e.update(m)
        W = fit_softmax(X, y, iters=120)
        def predict(m):
            if m.home not in e.r or m.away not in e.r: return None
            x = feats(e.diff(m), m.neutral)
            return tuple(_softmax([sum(W[c][j] * x[j] for j in range(len(x))) for c in range(3)]))
        return predict
    return factory

def blend(parts, weights, geometric=False):
    """parts: list of result lists (same matches); returns result list."""
    dicts = [dict(p) for p in parts]
    out = []
    for i, _ in parts[0]:
        ps = [d.get(i) for d in dicts]
        if any(p is None for p in ps): out.append((i, None)); continue
        tw = sum(weights)
        if geometric:
            v = [math.exp(sum(w * math.log(max(p[j], 1e-9)) for p, w in zip(ps, weights)) / tw) for j in range(3)]
            s = sum(v); out.append((i, tuple(x / s for x in v)))
        else:
            out.append((i, tuple(sum(p[j] * w for p, w in zip(ps, weights)) / tw for j in range(3))))
    return out

def temperature(res, T, draw_mult=1.0):
    out = []
    for i, p in res:
        if p is None: out.append((i, None)); continue
        v = [max(p[0], 1e-9) ** T, max(p[1], 1e-9) ** T * draw_mult, max(p[2], 1e-9) ** T]; s = sum(v)
        out.append((i, tuple(x / s for x in v)))
    return out
