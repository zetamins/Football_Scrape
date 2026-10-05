import sys; sys.path.insert(0, '.')
from lab import *
t0 = time.time()
cands = {
 'pois_base':   poisson(),
 'pois_hl3':    poisson(half_life_years=3.0),
 'pois_hl6':    poisson(half_life_years=6.0),
 'pois_hl8':    poisson(half_life_years=8.0),
 'pois_r05':    poisson(ridge=0.5),
 'pois_r2':     poisson(ridge=2.0),
 'pois_cap4':   poisson(cap=4),
 'pois_cap6':   poisson(cap=6),
 'pois_start14':poisson(start_year=2014),
 'pois_start00':poisson(start_year=2000, half_life_years=6.0),
 'elo_k30':     elo_davidson(k=30, kf=15),
 'elo_k40':     elo_davidson(k=40, kf=20),
 'elo_k20':     elo_davidson(k=20, kf=10),
 'elo_nomargin':elo_davidson(k=30, kf=15, margin=False),
 'elo_nu70':    elo_davidson(nu=0.70, k=30, kf=15),
 'elo_nu85':    elo_davidson(nu=0.85, k=30, kf=15),
 'elo_logit_k30': elo_logit(k=30, kf=15),
 'elo_logit_k40': elo_logit(k=40, kf=20),
}
R = {}
for name, f in cands.items():
    t = time.time(); R[name] = run_candidate(name, f, VAL); print(f'{name:14} done {time.time()-t:5.1f}s', flush=True)
idx = common_index(R)
print('common matches', len(idx))
rows = sorted(((score(R[n], idx), n) for n in R))
print('\nPASS 1 RANKING (validation 2022-23, Brier / logloss / acc)')
for rank, ((b, l, a), n) in enumerate(rows, 1):
    print(f'{rank:2d}. {n:14} {b:.4f} {l:.4f} {a:.3f}')
json.dump([n for _, n in rows], open(f'{S}/lab/pass1_rank.json', 'w'))
print('total secs', round(time.time() - t0))
