"""Does dropping 'either side to win' from the double-chance choice (always cover the draw: X or draw / draw or Y) cost anything? Held-out 8,054; thresholds as in the engine (double chance below 60%, goals bets from 60%)."""
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
KS = 0.2
data = []
for r in rows:
    p1, _, _ = markets(r, 0); _, over, btts = markets(r, KS)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    c = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over': (over, r['hg'] + r['ag'] > 2), 'Under': (1 - over, r['hg'] + r['ag'] <= 2), 'BTTS': (btts, r['hg'] > 0 and r['ag'] > 0), 'NoBTTS': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
    dcs = {'1X': (p1[0] + p1[1], o in (0, 1)), 'X2': (p1[1] + p1[2], o in (1, 2)), '12': (p1[0] + p1[2], o in (0, 2))}
    data.append((r['day'].year, c, dcs, p1[1], o))
def run(sub, excl_from):
    h = []; q = []; n12 = 0; dmiss = 0
    for _, c, dcs, pd, o in sub:
        elig = {k: v for k, v in c.items() if k == '1X2' or v[0] >= 0.60}
        if c['1X2'][0] < 0.60:
            allowed = {k: v for k, v in dcs.items() if not (k == '12' and excl_from is not None and pd >= excl_from)}
            nm = max(allowed, key=lambda k: allowed[k][0]); elig['DC:' + nm] = allowed[nm]
        b = max(elig, key=lambda k: elig[k][0]); ok = elig[b][1]; h.append(ok); q.append(elig[b][0]); n12 += b == 'DC:12'; dmiss += (not ok and o == 1)
    return np.mean(h), np.mean(q), n12, dmiss, len(h)
print("| rule | sample | hit rate | quoted | 'either side' bets | draws among misses |\n|---|---|---|---|---|---|")
for label, sub in (("all 8,054", data), ("2024 on", [d for d in data if d[0] >= 2024])):
    for name, ex in (("current", None), ("no 'either side' when draw >= 27%", 0.27), ("no 'either side' when draw >= 25%", 0.25), ("never 'either side'", 0.0)):
        hit, q, n12, dm, n = run(sub, ex)
        print(f"| {name} | {label} ({n}) | {100*hit:.1f}% | {100*q:.1f}% | {n12} | {dm} |")
