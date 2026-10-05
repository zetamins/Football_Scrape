import sys; sys.path.insert(0, '.')
from lab2 import *
t0 = time.time()
R = {
 'current (ridge1.0)': run_candidate('final_cur', poisson(), TEST),
 'pois_r05': run_candidate('final_r05', poisson(ridge=0.5), TEST),
 'conf_r1': run_candidate('final_conf', poisson_confed(ridge=1.0), TEST),
 'elo_logit_k40': run_candidate('final_elo', elo_logit(k=40, kf=20), TEST),
}
R['blend30 (pois_r05+elo_logit)'] = blend([R['pois_r05'], R['elo_logit_k40']], [0.7, 0.3])
R['blend30 (current+elo_logit)'] = blend([R['current (ridge1.0)'], R['elo_logit_k40']], [0.7, 0.3])
R['blend30 (conf+elo_logit)'] = blend([R['conf_r1'], R['elo_logit_k40']], [0.7, 0.3])
R['blend20 (pois_r05+elo_logit)'] = blend([R['pois_r05'], R['elo_logit_k40']], [0.8, 0.2])
idx = common_index(R)
print('TEST 2024-2026 common matches', len(idx))
rows = sorted(((score(R[n], idx), n) for n in R))
for rank, ((b, l, a), n) in enumerate(rows, 1): print(f'{rank}. {n:32} brier {b:.4f} logloss {l:.4f} acc {a:.3f}')
print()
for n in R:
    if n != 'current (ridge1.0)':
        m, lo, hi = paired_boot(R[n], R['current (ridge1.0)'], idx); print(f'  {n:32} vs current {m:+.4f} 95% CI [{lo:+.4f}, {hi:+.4f}] {"SIGNIFICANT" if hi < 0 or lo > 0 else "not significant"}')
print('secs', round(time.time() - t0))
