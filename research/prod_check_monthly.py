"""Validate the SHIPPED code path (football.history_train.fit_full + outcome_probs_blended, pure Python)
against the Poisson-only model on three windows with paired bootstrap."""
import sys; sys.path.insert(0, '.')
from lab2 import *
def prod(blended):
    def factory(train, as_of):
        mod = H.fit_full(train, as_of, ridge=0.5) if blended else H.fit(train, as_of, ridge=0.5)
        f = H.outcome_probs_blended if blended else H.outcome_probs
        return lambda m: f(mod, m.home, m.away, m.neutral)
    return factory
SEARCH = (date(2018, 1, 1), date(2022, 1, 1))
allm = []; pooled = {'a': [], 'b': []}
for name, w in (('2018-21 (independent)', SEARCH), ('2022-23 (validation)', VAL), ('2024-26 (test)', TEST)):
    t = time.time()
    a = run_candidate('prod_pois_m1', prod(False), w, months=1); b = run_candidate('prod_blend_m1', prod(True), w, months=1)
    idx = common_index({'a': a, 'b': b})
    sa, sb = score(a, idx), score(b, idx); m, lo, hi = paired_boot(b, a, idx)
    print(f'{name:24} n={len(idx)}  poisson {sa[0]:.4f} (acc {sa[2]:.3f})  shipped blend {sb[0]:.4f} (acc {sb[2]:.3f})  diff {m:+.4f} [{lo:+.4f},{hi:+.4f}] {"*" if hi<0 or lo>0 else ""}  ({time.time()-t:.0f}s)', flush=True)
    da, db = dict(a), dict(b)
    for i in idx: pooled['a'].append(brier(da[i], outcome(ALL[i]))); pooled['b'].append(brier(db[i], outcome(ALL[i])))
diffs = [y - x for x, y in zip(pooled['a'], pooled['b'])]; n = len(diffs); rng = random.Random(0)
bs = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(2000))
print(f'POOLED n={n}: diff {sum(diffs)/n:+.4f} [{bs[50]:+.4f},{bs[1950]:+.4f}]')
