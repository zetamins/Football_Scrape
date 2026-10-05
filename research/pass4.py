import sys; sys.path.insert(0, '.')
from lab2 import *
t0 = time.time()
print('confed coverage', collections.Counter(CONFED.values()), flush=True)
cands = {
 'pois_r05': poisson(ridge=0.5),
 'conf_r05': poisson_confed(ridge=0.5),
 'conf_r1': poisson_confed(ridge=1.0),
 'conf_r2': poisson_confed(ridge=2.0),
 'conf_r05_g3': poisson_confed(ridge=0.5, group_ridge=3.0),
 'elo_logit_k40': elo_logit(k=40, kf=20),
 'elox_k40': elo_logit_x(k=40, kf=20),
 'elox_k50': elo_logit_x(k=50, kf=25),
 'elox_noextra': elo_logit_x(k=40, kf=20, extra=False),
}
R = {}
for n, f in cands.items():
    t = time.time(); R[n] = run_candidate(n, f, VAL); print(f'{n:14} {time.time()-t:5.1f}s', flush=True)
R['blend30_r05_elo'] = blend([R['pois_r05'], R['elo_logit_k40']], [0.7, 0.3])
R['blend30_conf_elox'] = blend([R['conf_r1'], R['elox_k40']], [0.7, 0.3])
R['blend30_r05_elox'] = blend([R['pois_r05'], R['elox_k40']], [0.7, 0.3])
R['blend40_r05_elox'] = blend([R['pois_r05'], R['elox_k40']], [0.6, 0.4])
R['blend3way'] = blend([R['pois_r05'], R['conf_r1'], R['elox_k40']], [0.35, 0.35, 0.3])
idx = common_index(R)
print('common', len(idx))
rows = sorted(((score(R[n], idx), n) for n in R))
print('\nPASS 4 RANKING (validation 2022-23)')
for rank, ((b, l, a), n) in enumerate(rows, 1): print(f'{rank:2d}. {n:20} {b:.4f} {l:.4f} {a:.3f}')
for n in R:
    if n != 'pois_r05':
        m, lo, hi = paired_boot(R[n], R['pois_r05'], idx); print(f'  {n:20} vs pois_r05 {m:+.4f} [{lo:+.4f},{hi:+.4f}]')
print('secs', round(time.time() - t0))
