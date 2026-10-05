"""Overdispersion instead of a fixed shrink: the goal rates of a match are uncertain, so average the goal markets over a lognormal scale on both rates (shared factor).
Compare with the shrink now in use (k = 0.2). Fit on 2018-23, test 2024-26 and pooled; paired z against the shrink."""
import sys, math, random
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
Z, W = np.polynomial.hermite_e.hermegauss(7); W = W / W.sum()
def mix_markets(r, s, k=0.0):
    over = btts = 0.0; p1 = np.zeros(3)
    for z, w in zip(Z, W):
        f = math.exp(s * z - s * s / 2)
        t = r['lh'] + r['la']; f2 = (t + k * (MU - t)) / t if k else 1.0
        g = grid(r['lh'] * f * f2, r['la'] * f * f2)
        over += w * g[(I + J) > 2].sum(); btts += w * g[(I > 0) & (J > 0)].sum(); p1 += w * np.array([np.tril(g, -1).sum(), np.trace(g), np.triu(g, 1).sum()])
    return p1, over, btts
def ll(rs, s, k=0.0):
    ou, bt, x2 = [], [], []
    for r in rs:
        p1, over, btts = mix_markets(r, s, k) if s else markets(r, k)
        o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
        ou.append(-math.log(max(over if r['hg'] + r['ag'] > 2 else 1 - over, 1e-9))); bt.append(-math.log(max(btts if (r['hg'] > 0 and r['ag'] > 0) else 1 - btts, 1e-9))); x2.append(-math.log(max(p1[o], 1e-9)))
    return {'OU': np.array(ou), 'BTTS': np.array(bt), '1X2': np.array(x2)}
cfgs = {'none': (0, 0.0), 'shrink k=0.2 (current)': (0, 0.2), 'mixture s=0.10': (0.10, 0.0), 'mixture s=0.15': (0.15, 0.0), 'mixture s=0.20': (0.20, 0.0), 'mixture s=0.25': (0.25, 0.0), 'mixture s=0.15 + shrink 0.1': (0.15, 0.1)}
tr = {n: ll(train, *c) for n, c in cfgs.items()}
print('TRAIN log-loss (OU, BTTS, 1X2):')
for n, v in tr.items(): print(f"  {n}: {v['OU'].mean():.5f}  {v['BTTS'].mean():.5f}  {v['1X2'].mean():.5f}")
good = [n for n in cfgs if n.startswith('mixture')]
best = min(good, key=lambda n: tr[n]['OU'].mean() + tr[n]['BTTS'].mean()); print('best mixture on train (OU+BTTS):', best)
allr = {n: ll(rows, *cfgs[n]) for n in ('shrink k=0.2 (current)', best, 'none')}
cur, new = allr['shrink k=0.2 (current)'], allr[best]
print(f"\nPooled 8,054 matches: {best} vs current shrink (negative = mixture better)")
for m in ('OU', 'BTTS', '1X2'):
    d = new[m] - cur[m]; print(f"  {m}: {d.mean():+.5f}  z = {d.mean()/(d.std()/math.sqrt(len(d))):+.1f}")
print('by period (OU, BTTS):')
yrs = np.array([r['day'].year for r in rows])
for name, mask in (('2018-21', yrs <= 2021), ('2022-23', (yrs >= 2022) & (yrs <= 2023)), ('2024-26', yrs >= 2024)):
    print(f"  {name}: OU {np.mean((new['OU'] - cur['OU'])[mask]):+.5f}  BTTS {np.mean((new['BTTS'] - cur['BTTS'])[mask]):+.5f}")
