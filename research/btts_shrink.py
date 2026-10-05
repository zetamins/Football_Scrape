"""Does BTTS want a stronger total-goal shrink than Over/Under? (k = 0.2 is in use for both.) Fit on 2018-23, test 2024-26, pooled paired z."""
import sys, math, random
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
def btts_ll(rs, k):
    out = []
    for r in rs:
        _, _, btts = markets(r, k); y = r['hg'] > 0 and r['ag'] > 0
        out.append(-math.log(max(btts if y else 1 - btts, 1e-9)))
    return np.array(out)
base = {}
for k in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6):
    tr = btts_ll(train, k); te = btts_ll(test, k); base[k] = (tr.mean(), te.mean())
    print(f"k={k}: BTTS log-loss train {tr.mean():.5f}  test {te.mean():.5f}")
print('best on train:', min(base, key=lambda k: base[k][0]))
rng = random.Random(7)
print('\nk=0.4 vs k=0.2 (negative = 0.4 better), by period and pooled:')
for name, sel in (('2018-21', lambda y: y <= 2021), ('2022-23', lambda y: 2022 <= y <= 2023), ('2024-26', lambda y: y >= 2024), ('pooled', lambda y: True)):
    rs = [r for r in rows if sel(r['day'].year)]; d = btts_ll(rs, 0.4) - btts_ll(rs, 0.2); n = len(d)
    bs = sorted(np.mean([d[rng.randrange(n)] for _ in range(n)]) for _ in range(300))
    print(f"  {name}: {d.mean():+.5f}  (95% CI {bs[7]:+.5f}, {bs[292]:+.5f})  z={d.mean()/(d.std()/math.sqrt(n)):+.1f}")
# calibration of BTTS Yes/No at the two settings on all matches
for k in (0.2, 0.4):
    ps = []; ys = []
    for r in rows:
        _, _, b = markets(r, k); ps.append(b); ys.append(r['hg'] > 0 and r['ag'] > 0)
    ps = np.array(ps); ys = np.array(ys, float)
    print(f"k={k}: BTTS No quoted>=65%: n={int(((1-ps)>=.65).sum())} quoted {100*(1-ps[(1-ps)>=.65]).mean():.1f}% actual {100*(1-ys[(1-ps)>=.65]).mean():.1f}%  | Yes>=55%: n={int((ps>=.55).sum())} quoted {100*ps[ps>=.55].mean():.1f}% actual {100*ys[ps>=.55].mean():.1f}%")
