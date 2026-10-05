"""What if goal-market bets (Over/Under 2.5, BTTS) must reach a minimum probability before they can be recommended? Held-out 8,054 matches, shrink applied.
Fallback = the 1X2 top outcome (always eligible). Compare overall hit rate, and what the fallback looks like for the matches that lose their goals bet."""
import sys
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
KS = 0.2
data = []
for r in rows:
    p1, _, _ = markets(r, 0); _, over, btts = markets(r, KS)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    c = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over 2.5': (over, r['hg'] + r['ag'] > 2), 'Under 2.5': (1 - over, r['hg'] + r['ag'] <= 2),
         'BTTS Yes': (btts, r['hg'] > 0 and r['ag'] > 0), 'BTTS No': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
    dc = {'1X': (p1[0] + p1[1], o in (0, 1)), 'X2': (p1[1] + p1[2], o in (1, 2)), '12': (p1[0] + p1[2], o in (0, 2))}
    data.append((c, dc))
print('| Rule | Bets that are goals markets | Overall hit rate | Mean quoted |\n|---|---|---|---|')
def run(minp, extra=None):
    hits = []; q = []; goals = 0; fb = []
    for c, dc in data:
        elig = {k: v for k, v in c.items() if k == '1X2' or v[0] >= minp}
        if extra == 'dc':
            best_dc = max(dc.values())
            if c['1X2'][0] < 0.5: elig['DC'] = best_dc
        b = max(elig, key=lambda k: elig[k][0]); hits.append(elig[b][1]); q.append(elig[b][0]); goals += b not in ('1X2', 'DC')
        if b == '1X2' and max(c, key=lambda k: c[k][0]) != '1X2': fb.append((c['1X2'][0], c['1X2'][1]))
    return np.mean(hits), np.mean(q), goals, fb
for label, minp, extra in (('current: any probability', 0.0, None), ('goals bets need >= 55%', 0.55, None), ('goals bets need >= 60%', 0.60, None), ('goals bets need >= 65%', 0.65, None), ('goals >= 60%, else best double chance if 1X2 < 50%', 0.60, 'dc')):
    h, qv, g, fb = run(minp, extra)
    print(f"| {label} | {g} of {len(data)} ({100*g/len(data):.0f}%) | {100*h:.1f}% | {100*qv:.1f}% |")
h, qv, g, fb = run(0.60)
fbp = np.array([x[0] for x in fb]); fbh = np.array([x[1] for x in fb])
print(f"\nMatches whose goals bet is dropped at 60% ({len(fb)}): fallback 1X2 pick has mean prob {100*fbp.mean():.1f}%, hit rate {100*fbh.mean():.1f}%; under 40%: {int((fbp<.4).sum())}, 40-50%: {int(((fbp>=.4)&(fbp<.5)).sum())}, 50%+: {int((fbp>=.5).sum())}")
print('goals bets at 50-60% (current rule), hit rate:', f"{100*np.mean([c[b][1] for c, _ in data for b in [max(c, key=lambda k: c[k][0])] if b != '1X2' and c[b][0] < .6]):.1f}%")
