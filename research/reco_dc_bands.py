"""New rule: goals bets only at >= 60%; when the best 1X2 outcome is under 50% a double chance is also eligible. Hit rate by chosen kind and probability band (8,054 held-out matches)."""
exec(open('reco_min_goals.py').read().split("print('| Rule")[0])
chosen = []
for c, dc in data:
    elig = {k: v for k, v in c.items() if k == '1X2' or v[0] >= 0.60}
    if c['1X2'][0] < 0.5: elig['DC'] = max(dc.values())
    b = max(elig, key=lambda k: elig[k][0]); kind = 'DC' if b == 'DC' else '1X2' if b == '1X2' else 'goals'
    chosen.append((kind, elig[b][0], elig[b][1]))
n = len(chosen)
print(f"all: hit {100*np.mean([x[2] for x in chosen]):.1f}% quoted {100*np.mean([x[1] for x in chosen]):.1f}%")
for kind in ('1X2', 'goals', 'DC'):
    v = [x for x in chosen if x[0] == kind]
    print(f"{kind}: n={len(v)} ({100*len(v)/n:.0f}%) quoted {100*np.mean([x[1] for x in v]):.1f}% hit {100*np.mean([x[2] for x in v]):.1f}%")
print('\\nDC by band:\\n| band | n | quoted | hit |\\n|---|---|---|---|')
edges = [0, .6, .65, .7, .75, .8, .9, 1.01]
for lo, hi in zip(edges, edges[1:]):
    v = [x for x in chosen if x[0] == 'DC' and lo <= x[1] < hi]
    if v: print(f"| {int(lo*100)}-{int(min(hi,1)*100)} | {len(v)} | {100*np.mean([x[1] for x in v]):.1f} | {100*np.mean([x[2] for x in v]):.1f} |")
print('\\ngoals by band (now >= 60% only):\\n| band | n | quoted | hit |\\n|---|---|---|---|')
for lo, hi in zip([.6, .65, .7, .75, .8, 1.01][:-1], [.65, .7, .75, .8, 1.01]):
    v = [x for x in chosen if x[0] == 'goals' and lo <= x[1] < hi]
    if v: print(f"| {int(lo*100)}-{int(min(hi,1)*100)} | {len(v)} | {100*np.mean([x[1] for x in v]):.1f} | {100*np.mean([x[2] for x in v]):.1f} |")
