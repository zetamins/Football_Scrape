"""Two 'hit rates' are quoted for one pick: the 1X2 pick's calibrated confidence (prediction._CONFIDENCE_KNOTS) and the recommended bet's band rate (mixed markets).
Which is right for a 1X2 pick, and does a mixed-market band mislead for goal markets? Held-out 8,054 matches, goal-market shrink applied."""
import sys, math
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
sys.path.insert(0, '..')
from football.prediction import _CONFIDENCE_KNOTS
def knots(p):
    pts = _CONFIDENCE_KNOTS
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= p <= x1: return y0 + (y1 - y0) * (p - x0) / (x1 - x0)
    return pts[-1][1]
KS = 0.2
recs = []
for r in rows:
    p1, _, _ = markets(r, 0); _, over, btts = markets(r, KS)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    top = max(p1)
    c = {'1X2': (top, int(np.argmax(p1)) == o), 'Over 2.5': (over, r['hg'] + r['ag'] > 2), 'Under 2.5': (1 - over, r['hg'] + r['ag'] <= 2), 'BTTS Yes': (btts, r['hg'] > 0 and r['ag'] > 0), 'BTTS No': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
    b = max(c, key=lambda x: c[x][0]); recs.append((b, c[b][0], c[b][1], c['1X2'][0], c['1X2'][1]))
edges = [0, .45, .5, .55, .6, .65, .7, .75, .8, .9, 1.01]
print('A) EVERY 1X2 top pick (whatever the recommendation): quoted, knots (confidence_pct), actual')
print('| band | n | quoted | knots | actual |\n|---|---|---|---|---|')
for lo, hi in zip(edges, edges[1:]):
    v = [x for x in recs if lo <= x[3] < hi]
    if v: print(f"| {int(lo*100)}-{int(min(hi,1)*100)} | {len(v)} | {100*np.mean([x[3] for x in v]):.1f} | {np.mean([knots(100*x[3]) for x in v]):.1f} | {100*np.mean([x[4] for x in v]):.1f} |")
print('\nB) RECOMMENDED bets, by chosen kind: 1X2 vs goal markets')
print('| band | 1X2 n | 1X2 quoted | 1X2 actual | goals n | goals quoted | goals actual |\n|---|---|---|---|---|---|---|')
for lo, hi in zip(edges, edges[1:]):
    a = [x for x in recs if x[0] == '1X2' and lo <= x[1] < hi]; g = [x for x in recs if x[0] != '1X2' and lo <= x[1] < hi]
    if a or g: print(f"| {int(lo*100)}-{int(min(hi,1)*100)} | {len(a)} | {100*np.mean([x[1] for x in a]) if a else float('nan'):.1f} | {100*np.mean([x[2] for x in a]) if a else float('nan'):.1f} | {len(g)} | {100*np.mean([x[1] for x in g]) if g else float('nan'):.1f} | {100*np.mean([x[2] for x in g]) if g else float('nan'):.1f} |")
