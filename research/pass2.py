import sys; sys.path.insert(0, '.')
from lab import *
t0 = time.time()
base = {
 'pois_r05': poisson(ridge=0.5), 'pois_base': poisson(), 'pois_start00': poisson(start_year=2000, half_life_years=6.0), 'pois_hl3': poisson(half_life_years=3.0),
 'elo_logit_k40': elo_logit(k=40, kf=20),
}
new = {
 'pois_r03': poisson(ridge=0.3), 'pois_r07': poisson(ridge=0.7),
 'pois_hl25': poisson(half_life_years=2.5), 'pois_hl35': poisson(half_life_years=3.5), 'pois_hl5': poisson(half_life_years=5.0),
 'pois_r05_hl3': poisson(ridge=0.5, half_life_years=3.0), 'pois_r05_hl5': poisson(ridge=0.5, half_life_years=5.0),
 'pois_start10': poisson(start_year=2010), 'pois_start04_hl5': poisson(start_year=2004, half_life_years=5.0),
 'elo_logit_k50': elo_logit(k=50, kf=25), 'elo_logit_k60': elo_logit(k=60, kf=30), 'elo_logit_k50_f40': elo_logit(k=50, kf=40),
 'elo_logit_k40_h80': elo_logit(k=40, kf=20, home=80), 'elo_logit_k40_h120': elo_logit(k=40, kf=20, home=120),
}
R = {}
for name, f in {**base, **new}.items():
    t = time.time(); R[name] = run_candidate(name, f, VAL); print(f'{name:18} {time.time()-t:5.1f}s', flush=True)
# ensembles built from cached members
E = {}
E['ens_pois4'] = blend([R['pois_r05'], R['pois_base'], R['pois_start00'], R['pois_hl3']], [1, 1, 1, 1])
E['ens_pois_bag'] = blend([R['pois_r05'], R['pois_hl3'], R['pois_hl5'], R['pois_start04_hl5'], R['pois_r05_hl3']], [1] * 5)
for w in (0.15, 0.3, 0.5):
    E[f'blend_r05_elologit40_{int(w*100)}'] = blend([R['pois_r05'], R['elo_logit_k40']], [1 - w, w])
    E[f'geo_r05_elologit40_{int(w*100)}'] = blend([R['pois_r05'], R['elo_logit_k40']], [1 - w, w], geometric=True)
E['blend_bag_elologit50_30'] = blend([E['ens_pois_bag'], R['elo_logit_k50']], [0.7, 0.3])
R.update(E)
idx = common_index(R)
print('common matches', len(idx))
rows = sorted(((score(R[n], idx), n) for n in R))
print('\nPASS 2 RANKING (validation 2022-23)')
for rank, ((b, l, a), n) in enumerate(rows, 1):
    print(f'{rank:2d}. {n:26} {b:.4f} {l:.4f} {a:.3f}')
pickle.dump({n: R[n] for n in R if n.startswith(('ens', 'blend', 'geo'))}, open(f'{S}/lab/cache/pass2_ens.pkl', 'wb'))
json.dump([n for _, n in rows], open(f'{S}/lab/pass2_rank.json', 'w'))
print('secs', round(time.time() - t0))
