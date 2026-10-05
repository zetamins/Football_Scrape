import sys
sys.path.insert(0, '.')
from lab2 import *
SEARCH = (date(2018, 1, 1), date(2022, 1, 1))
V = ('basic', 'split', 'confed')
agg = {v: {'b': [], 'l': []} for v in V}
print(f"{'period':8} {'n':>5} | " + ' | '.join(f'{v:^26}' for v in V), flush=True)
for name, w in (('2018-21', SEARCH), ('2022-23', VAL), ('2024-26', TEST)):
    res = {v: run_candidate(f'venue_{v}_{name}', poisson(ridge=0.5, venue=v), w, months=3) for v in V}
    idx = common_index(res); cells = []
    for v in V:
        d = dict(res[v]); b = sum(brier(d[i], outcome(ALL[i])) for i in idx) / len(idx); l = sum(logloss(d[i], outcome(ALL[i])) for i in idx) / len(idx)
        cells.append(f'Brier {b:.4f} logloss {l:.4f}')
        for i in idx: agg[v]['b'].append(brier(d[i], outcome(ALL[i]))); agg[v]['l'].append(logloss(d[i], outcome(ALL[i])))
    print(f'{name:8} {len(idx):>5} | ' + ' | '.join(f'{c:^26}' for c in cells), flush=True)
rng = random.Random(0)
print('\nPOOLED over all periods, paired vs basic (negative = better):')
for v in V[1:]:
    for key, lab in (('b', 'Brier'), ('l', 'log-loss')):
        d = [a - b for a, b in zip(agg[v][key], agg['basic'][key])]; n = len(d)
        bs = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(1500))
        print(f'  {v:7} {lab:9} {sum(d)/n:+.5f}  95% CI [{bs[37]:+.5f}, {bs[1462]:+.5f}]  n={n}', flush=True)
