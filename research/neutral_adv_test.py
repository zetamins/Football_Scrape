import sys
sys.path.insert(0, '.')
from lab2 import *
SEARCH = (date(2018, 1, 1), date(2022, 1, 1))
tot = {'off': [], 'on': []}
print(f"{'period':8} {'n':>5} {'Brier off':>10} {'Brier on':>9} {'diff (95% CI)':>34} | neutral matches only: off / on / diff")
for name, w in (('2018-21', SEARCH), ('2022-23', VAL), ('2024-26', TEST)):
    off = run_candidate(f'na_off_{name}', poisson(ridge=0.5, neutral_adv=False), w, months=3)
    on = run_candidate(f'na_on_{name}', poisson(ridge=0.5, neutral_adv=True), w, months=3)
    idx = common_index({'a': off, 'b': on}); so, sn = score(off, idx), score(on, idx); m, lo, hi = paired_boot(on, off, idx)
    neu = [i for i in idx if ALL[i].neutral]; do_, dn = dict(off), dict(on)
    bo = sum(brier(do_[i], outcome(ALL[i])) for i in neu) / len(neu); bn = sum(brier(dn[i], outcome(ALL[i])) for i in neu) / len(neu)
    print(f'{name:8} {len(idx):>5} {so[0]:>10.4f} {sn[0]:>9.4f} {m:>+12.4f} [{lo:+.4f}, {hi:+.4f}] | n={len(neu)}: {bo:.4f} / {bn:.4f} / {bn-bo:+.4f}')
    for i in idx:
        tot['off'].append(brier(do_[i], outcome(ALL[i]))); tot['on'].append(brier(dn[i], outcome(ALL[i])))
d = [b - a for a, b in zip(tot['off'], tot['on'])]; n = len(d); rng = random.Random(0)
bs = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(2000))
print(f"POOLED n={n}: {sum(d)/n:+.4f} [{bs[50]:+.4f}, {bs[1950]:+.4f}]")
