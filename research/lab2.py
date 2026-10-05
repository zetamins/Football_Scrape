from lab import *
from lab import _softmax
import collections
KEYS = {
 'CAF': ('african cup of nations', 'cosafa', 'cecafa', 'african nations championship', 'waff', 'unaf', 'uniffac', 'amilcar'),
 'UEFA': ('uefa', 'euro', 'baltic cup', 'balkan cup', 'nordic'),
 'AFC': ('afc', 'asian', 'aff ', 'aff championship', 'gulf cup', 'eaff', 'saff', 'asean', 'waff', 'arab cup', 'merdeka', 'king\'s cup'),
 'CONCACAF': ('concacaf', 'gold cup', 'caribbean', 'ccccf', 'uncaf', 'cfu'),
 'CONMEBOL': ('copa am', 'conmebol', 'south american'),
 'OFC': ('oceania', 'ofc', 'pacific games', 'polynesia', 'melanesian'),
}
def build_confed():
    votes = collections.defaultdict(collections.Counter)
    for m in ALL:
        t = m.tournament.lower()
        if 'world cup' in t and 'qualification' not in t or t == 'friendly': continue
        for c, ks in KEYS.items():
            if any(k in t for k in ks) and not ('nations league' in t and c == 'UEFA' and 'concacaf' in t):
                if 'concacaf nations' in t: c = 'CONCACAF'
                votes[m.home][c] += 1; votes[m.away][c] += 1; break
    return {t: c.most_common(1)[0][0] for t, c in votes.items()}
CONFED = build_confed()

def fit_confed(matches, as_of, half_life_years=4.0, ridge=0.5, start_year=2008, sweeps=40, group_ridge=1.0):
    """Like history_train.fit but each team's attack/defence shrinks toward its confederation's mean (not 0),
    and a hierarchical group mean is itself ridge-shrunk."""
    use = [m for m in matches if start_year <= m.day.year and m.day < as_of]
    w = [H._weight(m, as_of, half_life_years, dict(H.TOURNAMENT_WEIGHTS)) for m in use]
    teams = sorted({m.home for m in use} | {m.away for m in use}); idx = {t: i for i, t in enumerate(teams)}; n = len(teams)
    grp = [CONFED.get(t, 'UNK') for t in teams]; groups = sorted(set(grp))
    hi = [idx[m.home] for m in use]; ai = [idx[m.away] for m in use]
    hg = [m.hg for m in use]; ag = [m.ag for m in use]; hv = [0.0 if m.neutral else 1.0 for m in use]
    att = [0.0] * n; dfn = [0.0] * n
    mu = math.log(sum(wi * (a + b) for wi, a, b in zip(w, hg, ag)) / (2 * sum(w))); hadv = 0.2
    gm_a = {g: 0.0 for g in groups}; gm_d = {g: 0.0 for g in groups}
    K = len(use)
    for _ in range(sweeps):
        lh = [H._exp(mu + hadv * hv[k] + att[hi[k]] - dfn[ai[k]]) for k in range(K)]
        la = [H._exp(mu + att[ai[k]] - dfn[hi[k]]) for k in range(K)]
        mu += sum(w[k] * ((hg[k] - lh[k]) + (ag[k] - la[k])) for k in range(K)) / sum(w[k] * (lh[k] + la[k]) for k in range(K))
        lh = [H._exp(mu + hadv * hv[k] + att[hi[k]] - dfn[ai[k]]) for k in range(K)]
        gH = sum(w[k] * (hg[k] - lh[k]) for k in range(K) if hv[k]); hH = sum(w[k] * lh[k] for k in range(K) if hv[k])
        hadv += gH / hH if hH else 0
        la = [H._exp(mu + att[ai[k]] - dfn[hi[k]]) for k in range(K)]
        ga = [0.0] * n; ha = [0.0] * n; gd = [0.0] * n; hd = [0.0] * n
        for k in range(K):
            ga[hi[k]] += w[k] * (hg[k] - lh[k]); ha[hi[k]] += w[k] * lh[k]
            ga[ai[k]] += w[k] * (ag[k] - la[k]); ha[ai[k]] += w[k] * la[k]
            gd[ai[k]] -= w[k] * (hg[k] - lh[k]); hd[ai[k]] += w[k] * lh[k]
            gd[hi[k]] -= w[k] * (ag[k] - la[k]); hd[hi[k]] += w[k] * la[k]
        for t in range(n):
            att[t] = H._damped(att[t], (ga[t] - ridge * (att[t] - gm_a[grp[t]])) / (ha[t] + ridge))
            dfn[t] = H._damped(dfn[t], (gd[t] - ridge * (dfn[t] - gm_d[grp[t]])) / (hd[t] + ridge))
        for g in groups:  # group mean = shrunk average of its members
            mem = [t for t in range(n) if grp[t] == g]
            gm_a[g] = sum(att[t] for t in mem) / (len(mem) + group_ridge); gm_d[g] = sum(dfn[t] for t in mem) / (len(mem) + group_ridge)
    lh = [H._exp(mu + hadv * hv[k] + att[hi[k]] - dfn[ai[k]]) for k in range(K)]
    la = [H._exp(mu + att[ai[k]] - dfn[hi[k]]) for k in range(K)]
    rho = H._fit_rho(w, hg, ag, lh, la)
    return FittedModel(mu=mu, home_adv=hadv, rho=rho, attack={t: att[i] for t, i in idx.items()}, defence={t: dfn[i] for t, i in idx.items()}, as_of=as_of.isoformat(), matches_used=K)

def poisson_confed(**params):
    def factory(train, as_of):
        model = fit_confed(train, as_of, **params)
        return lambda m: H.outcome_probs(model, m.home, m.away, m.neutral)
    return factory

def elo_logit_x(window_years=12, extra=True, **ep):
    """Elo -> multinomial logit with extra context features computed only from past matches."""
    def factory(train, as_of):
        e = Elo(**ep); last = {}; recent = collections.defaultdict(list)  # team -> list of (day, gf, ga)
        def ctx(team, day):
            lst = recent[team]; rest = min(30, (day - last[team]).days) if team in last else 30
            r365 = [x for x in lst[-25:] if (day - x[0]).days <= 365]
            gd5 = sum(x[1] - x[2] for x in lst[-5:]) / max(1, len(lst[-5:]))
            return rest, len(r365), gd5
        def feats(m):
            d = e.diff(m) / 400.0
            x = [1.0, d, abs(d), d * d, 1.0 if m.neutral else 0.0]
            if extra:
                rh, nh, gh = ctx(m.home, m.day); ra, na, ga_ = ctx(m.away, m.day)
                same = 1.0 if CONFED.get(m.home, 'U1') == CONFED.get(m.away, 'U2') else 0.0
                x += [(rh - ra) / 30.0, (nh - na) / 25.0, (gh - ga_) / 3.0, same, same * d]
            return x
        X = []; y = []
        def advance(m):
            e.update(m); last[m.home] = m.day; last[m.away] = m.day
            recent[m.home].append((m.day, m.hg, m.ag)); recent[m.away].append((m.day, m.ag, m.hg))
        for m in train:
            if m.home in e.r and m.away in e.r and m.day.year >= as_of.year - window_years:
                X.append(feats(m)); y.append(outcome(m))
            advance(m)
        W = fit_softmax(X, y, iters=120)
        def predict(m):
            if m.home not in e.r or m.away not in e.r: return None
            x = feats(m); return tuple(_softmax([sum(W[c][j] * x[j] for j in range(len(x))) for c in range(3)]))
        return predict
    return factory
