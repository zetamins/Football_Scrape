import sys, math
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
KS = 0.2
by = {}; allh = []; allq = []
for r in rows:
    p1, _, _ = markets(r, 0); _, over, btts = markets(r, KS)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    c = {'1X2': (max(p1), int(np.argmax(p1)) == o), 'Over 2.5': (over, r['hg'] + r['ag'] > 2), 'Under 2.5': (1 - over, r['hg'] + r['ag'] <= 2), 'BTTS Yes': (btts, r['hg'] > 0 and r['ag'] > 0), 'BTTS No': (1 - btts, not (r['hg'] > 0 and r['ag'] > 0))}
    b = max(c, key=lambda x: c[x][0]); by.setdefault(b, []).append((c[b][0], c[b][1])); allh.append(c[b][1]); allq.append(c[b][0])
print(f"all {len(rows)}: hit {100*np.mean(allh):.1f}% quoted {100*np.mean(allq):.1f}%; MU (train) = {MU:.3f}")
for m, v in sorted(by.items(), key=lambda kv: -len(kv[1])): print(f"{m}: n={len(v)} quoted {100*np.mean([x[0] for x in v]):.1f}% hit {100*np.mean([x[1] for x in v]):.1f}%")
