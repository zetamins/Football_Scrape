import sys, math, random
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
KS = 0.2
a = score(rows, 0); b = score(rows, KS); rng = random.Random(5)
print('Pooled over all 8,054 matches, log-loss difference with k=0.2 vs k=0 (negative = better):')
for m in ('1X2', 'OU', 'BTTS'):
    d = b[m] - a[m]; n = len(d); bs = sorted(np.mean([d[rng.randrange(n)] for _ in range(n)]) for _ in range(500))
    se = d.std() / math.sqrt(n); print(f"  {m}: {d.mean():+.5f}  (95% CI {bs[12]:+.5f}, {bs[487]:+.5f})  z = {d.mean()/se:+.1f}")
# recommended-bet rule on 2024-26 and all periods, goals markets shrunk, 1X2 untouched
def reco(rs, k):
    hit = []; q = []; mk = {}
    for r in rs:
        p1, _, _ = markets(r, 0); _, over, btts = markets(r, k)
        o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
        c = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over': (over, r['hg'] + r['ag'] > 2), 'Under': (1 - over, r['hg'] + r['ag'] <= 2), 'BTTS Y': (btts, r['hg'] > 0 and r['ag'] > 0), 'BTTS N': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
        best = max(c, key=lambda x: c[x][0]); hit.append(c[best][1]); q.append(c[best][0]); mk[best] = mk.get(best, 0) + 1
    return np.mean(hit), np.mean(q), mk
for name, sel in (('2018-23', lambda y: y <= 2023), ('2024-26', lambda y: y >= 2024), ('all', lambda y: True)):
    rs = [r for r in rows if sel(r['day'].year)]
    h0, q0, m0 = reco(rs, 0); h1, q1, m1 = reco(rs, KS)
    print(f"{name}: recommended-bet hit rate k=0: {100*h0:.1f}% (quoted {100*q0:.1f}%)  ->  k=0.2: {100*h1:.1f}% (quoted {100*q1:.1f}%)   chosen markets k=0.2: {m1}")
