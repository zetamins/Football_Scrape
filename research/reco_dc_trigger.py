"""The double-chance trigger: use the best double chance whenever the top 1X2 outcome is below T. Held-out 2024+ (goals bets from 60%) and the 38 live matches. Hit rate always rises with T because a double chance covers two outcomes: the question is how much and at what price."""
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
KS = 0.2
data = []
for r in rows:
    p1, _, _ = markets(r, 0); _, over, btts = markets(r, KS)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    c = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over': (over, r['hg'] + r['ag'] > 2), 'Under': (1 - over, r['hg'] + r['ag'] <= 2), 'BTTS': (btts, r['hg'] > 0 and r['ag'] > 0), 'NoBTTS': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
    dc = max(((p1[0] + p1[1], o in (0, 1), 'dc'), (p1[1] + p1[2], o in (1, 2), 'dc'), (p1[0] + p1[2], o in (0, 2), 'dc')))
    data.append((r['day'].year, c, dc, p1))
test = [d for d in data if d[0] >= 2024]
print("| DC trigger T | share of bets that are double chances | hit rate 2024+ | mean quoted probability |\n|---|---|---|---|")
for T in (0.0, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 1.01):
    h = []; q = []; ndc = 0
    for _, c, dc, p1 in test:
        elig = {k: v for k, v in c.items() if k == '1X2' or v[0] >= 0.60}
        if c['1X2'][0] < T: elig['DC'] = dc[:2]
        b = max(elig, key=lambda k: elig[k][0]); h.append(elig[b][1]); q.append(elig[b][0]); ndc += b == 'DC'
    print(f"| {T:.2f}{' (current: 0.50)' if T == 0.50 else ''} | {100*ndc/len(test):.0f}% | {100*np.mean(h):.1f}% | {100*np.mean(q):.1f}% |")
