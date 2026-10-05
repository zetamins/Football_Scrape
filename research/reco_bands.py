"""Observed hit rate of the recommended bet BY PROBABILITY BAND (what a 55% pick can expect), with the goal-market shrink in use. Held-out 8,054 matches."""
import sys, math
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
KS = 0.2
recs = []
for r in rows:
    p1, _, _ = markets(r, 0); _, over, btts = markets(r, KS)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    c = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over 2.5': (over, r['hg'] + r['ag'] > 2), 'Under 2.5': (1 - over, r['hg'] + r['ag'] <= 2), 'BTTS Yes': (btts, r['hg'] > 0 and r['ag'] > 0), 'BTTS No': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
    b = max(c, key=lambda x: c[x][0]); recs.append((b, c[b][0], c[b][1]))
print(f"all {len(recs)}: hit {100*np.mean([x[2] for x in recs]):.1f}%  quoted {100*np.mean([x[1] for x in recs]):.1f}%")
print('| band | n | quoted % | hit % |\n|---|---|---|---|')
edges = [0, .55, .60, .65, .70, .75, .80, .90, 1.01]
for lo, hi in zip(edges, edges[1:]):
    v = [x for x in recs if lo <= x[1] < hi]
    if v: print(f"| {int(lo*100)}-{int(min(hi,1)*100)} | {len(v)} | {100*np.mean([x[1] for x in v]):.1f} | {100*np.mean([x[2] for x in v]):.1f} |")
print('\nBy market within the 50-60% band (where lean bets live):')
for m in ('1X2', 'Under 2.5', 'BTTS Yes', 'BTTS No', 'Over 2.5'):
    v = [x for x in recs if x[0] == m and x[1] < 0.60]
    if v: print(f"  {m}: n={len(v)} quoted {100*np.mean([x[1] for x in v]):.1f}% hit {100*np.mean([x[2] for x in v]):.1f}%")
