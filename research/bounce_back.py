"""Does a team on losing form beat the model after it (the 'bounce back' idea)?  Out-of-sample rows only; z on points and goals; gate = same sign in every period and |z| >= 3.3."""
import sys, pickle, math, collections
sys.path.insert(0, '.'); sys.path.insert(0, '..')
from lab2 import CACHE
rows = sorted(pickle.load(open(f'{CACHE}/bias_rows_v2.pkl', 'rb')), key=lambda r: r['day'])
hist = collections.defaultdict(list)       # team -> [(points, gf, ga)] before this match
obs = []                                    # (features, pts_actual, pts_exp, pts_var, goals_actual, goals_exp, year)
for r in rows:
    for team, home in ((r['home'], True), (r['away'], False)):
        p = r['p'] if home else r['p'][::-1]
        gf, ga = (r['hg'], r['ag']) if home else (r['ag'], r['hg'])
        lam = r['lh'] if home else r['la']
        h = hist[team]
        if len(h) >= 5:
            last = h[-5:]
            pts = [x[0] for x in last]
            f = {
                'lost last match': pts[-1] == 0,
                'lost last 2': pts[-1] == 0 and pts[-2] == 0,
                'lost last 3': all(x == 0 for x in pts[-3:]),
                'no win in last 4': all(x < 3 for x in pts[-4:]),
                'lost last by 3+ goals': last[-1][0] == 0 and last[-1][2] - last[-1][1] >= 3,
                'points last 5 <= 3': sum(pts) <= 3,
                'won last 3': all(x == 3 for x in pts[-3:]),
                'won last 5': all(x == 3 for x in pts),
                'unbeaten last 5': all(x > 0 for x in pts),
            }
            e = 3 * p[0] + p[1]
            v = (3 - e) ** 2 * p[0] + (1 - e) ** 2 * p[1] + e ** 2 * p[2]
            a = 3 if gf > ga else 1 if gf == ga else 0
            obs.append((f, a, e, v, gf, lam, r['day'].year))
        h.append((3 if gf > ga else 1 if gf == ga else 0, gf, ga))
def z(sel):
    n = len(sel)
    if n < 100: return None
    a = sum(o[1] for o in sel); e = sum(o[2] for o in sel); v = sum(o[3] for o in sel)
    ga = sum(o[4] for o in sel) - sum(o[5] for o in sel)
    return n, (a - e) / n, (a - e) / math.sqrt(v), ga / n
periods = {'2018-20': (2018, 2020), '2021-23': (2021, 2023), '2024-26': (2024, 2026)}
print(f"{'feature':26s}{'n':>6s}{'pts/game vs model':>19s}{'z':>7s}{'goals/game':>12s}   per period (z)")
for name in next(iter(obs))[0]:
    sel = [o for o in obs if o[0][name]]
    t = z(sel)
    if not t: continue
    per = []
    for lab, (lo, hi) in periods.items():
        s = z([o for o in sel if lo <= o[6] <= hi]); per.append(f"{s[2]:+.1f}" if s else "n/a")
    print(f"{name:26s}{t[0]:6d}{t[1]:+19.3f}{t[2]:+7.2f}{t[3]:+12.3f}   {' '.join(per)}")
