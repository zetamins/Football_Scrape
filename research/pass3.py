import sys; sys.path.insert(0, '.')
from lab import *
from lab import _softmax
t0 = time.time()
PRE = (date(2014, 1, 1), date(2022, 1, 1))   # training window for calibrators/stackers (strictly before VAL)
mk = {'pois_r05': poisson(ridge=0.5), 'elo_logit_k40': elo_logit(k=40, kf=20), 'elo_logit_k50': elo_logit(k=50, kf=25)}
RV = {n: run_candidate(n, f, VAL) for n, f in mk.items()}
RP = {n: run_candidate(n, f, PRE) for n, f in mk.items()}
print('pre-window preds done', round(time.time() - t0), flush=True)

def mix(R, w=0.3): return blend([R['pois_r05'], R['elo_logit_k40']], [1 - w, w])
base_val = mix(RV); base_pre = mix(RP)

# --- calibration: fit temperature T and draw multiplier on PRE, apply to VAL
idx_pre = [i for i, p in base_pre if p is not None]
dpre = dict(base_pre)
best = (9, 1, 1)
for T in [0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2]:
    for dm in [0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.3]:
        cal = dict(temperature(base_pre, T, dm))
        b = sum(brier(cal[i], outcome(ALL[i])) for i in idx_pre) / len(idx_pre)
        if b < best[0]: best = (b, T, dm)
print('calibration fitted on 2014-21: T=%.2f draw_mult=%.2f (brier %.4f, uncalibrated %.4f)' % (best[1], best[2], best[0],
      sum(brier(dpre[i], outcome(ALL[i])) for i in idx_pre) / len(idx_pre)))
cal_val = temperature(base_val, best[1], best[2])

# --- stacker: softmax on log-probs of both models + neutral flag, refit per validation block on all earlier predictions
def feats(i, parts):
    x = [1.0, 1.0 if ALL[i].neutral else 0.0]
    for p in parts: x += [math.log(max(q, 1e-6)) for q in p]
    return x
def stack_train(upto_day, include_val=None):
    X = []; y = []
    dp = {n: dict(RP[n]) for n in ('pois_r05', 'elo_logit_k40')}
    for i in idx_pre:
        parts = [dp[n].get(i) for n in ('pois_r05', 'elo_logit_k40')]
        if all(parts): X.append(feats(i, parts)); y.append(outcome(ALL[i]))
    if include_val:
        dv = {n: dict(RV[n]) for n in ('pois_r05', 'elo_logit_k40')}
        for i in include_val:
            if ALL[i].day < upto_day:
                parts = [dv[n].get(i) for n in ('pois_r05', 'elo_logit_k40')]
                if all(parts): X.append(feats(i, parts)); y.append(outcome(ALL[i]))
    return X, y
stack_out = []
dv = {n: dict(RV[n]) for n in ('pois_r05', 'elo_logit_k40')}
val_idx = [i for i, _ in RV['pois_r05']]
for bs, be in block_starts(VAL):
    X, y = stack_train(bs, val_idx)
    W = fit_softmax(X, y, iters=150, lr=0.3, l2=1e-2)
    for i in val_idx:
        if bs <= ALL[i].day < be:
            parts = [dv[n].get(i) for n in ('pois_r05', 'elo_logit_k40')]
            if all(parts):
                x = feats(i, parts); stack_out.append((i, tuple(_softmax([sum(W[c][j] * x[j] for j in range(len(x))) for c in range(3)]))))
            else: stack_out.append((i, None))
print('stacker done', round(time.time() - t0), flush=True)

R = {'pois_r05 (current)': RV['pois_r05'], 'blend30': base_val, 'blend30+calib': cal_val, 'stack(pois,elo)': stack_out,
     'blend30_elok50': blend([RV['pois_r05'], RV['elo_logit_k50']], [0.7, 0.3])}
for w in (0.2, 0.4): R[f'blend{int(w*100)}'] = mix(RV, w)
idx = common_index(R)
print('common matches', len(idx))
rows = sorted(((score(R[n], idx), n) for n in R))
print('\nPASS 3 RANKING (validation 2022-23)')
for rank, ((b, l, a), n) in enumerate(rows, 1):
    print(f'{rank}. {n:22} {b:.4f} {l:.4f} {a:.3f}')
ref = R['pois_r05 (current)']
for n in R:
    if n != 'pois_r05 (current)':
        m, lo, hi = paired_boot(R[n], ref, idx)
        print(f'  {n:22} brier diff vs current {m:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]')
pickle.dump({'T': best[1], 'dm': best[2]}, open(f'{S}/lab/cache/calib.pkl', 'wb'))
print('secs', round(time.time() - t0))
