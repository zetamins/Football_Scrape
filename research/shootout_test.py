import sys, csv, io, urllib.request
sys.path.insert(0, '.')
from lab2 import *
raw = urllib.request.urlopen(urllib.request.Request("https://raw.githubusercontent.com/martj42/international_results/master/shootouts.csv", headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
SH = {(r['date'], H._key(r['home_team']), H._key(r['away_team'])) for r in csv.DictReader(io.StringIO(raw))}
def is_shoot(m): return (m.day.isoformat(), m.home, m.away) in SH or (m.day.isoformat(), m.away, m.home) in SH
def noshoot_factory(train, as_of):
    model = H.fit([m for m in train if not is_shoot(m)], as_of, ridge=0.5)
    return lambda m: H.outcome_probs(model, m.home, m.away, m.neutral)
SEARCH = (date(2018, 1, 1), date(2022, 1, 1)); agg = {'with': [], 'without': []}; dr = {'with': [0, 0], 'without': [0, 0]}
print(f"{'period':8} {'n(non-shootout)':>16} {'Brier trained WITH shootouts':>30} {'trained WITHOUT':>17} {'diff':>9}")
for name, w in (('2018-21', SEARCH), ('2022-23', VAL), ('2024-26', TEST)):
    a = run_candidate(f'so_with_{name}', poisson(ridge=0.5), w, months=3)
    b = run_candidate(f'so_without_{name}', noshoot_factory, w, months=3)
    da, db = dict(a), dict(b); idx = [i for i in common_index({'a': a, 'b': b}) if not is_shoot(ALL[i])]
    ba = sum(brier(da[i], outcome(ALL[i])) for i in idx) / len(idx); bb = sum(brier(db[i], outcome(ALL[i])) for i in idx) / len(idx)
    print(f'{name:8} {len(idx):>16} {ba:>30.4f} {bb:>17.4f} {bb-ba:>+9.4f}', flush=True)
    for i in idx:
        agg['with'].append(brier(da[i], outcome(ALL[i])) ); agg['without'].append(brier(db[i], outcome(ALL[i])))
        dr['with'][0] += da[i][1]; dr['without'][0] += db[i][1]; dr['with'][1] += outcome(ALL[i]) == 1
n = len(agg['with']); d = [b - a for a, b in zip(agg['with'], agg['without'])]; rng = random.Random(0)
bs = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(1500))
print(f"POOLED n={n}: Brier diff {sum(d)/n:+.5f} [{bs[37]:+.5f}, {bs[1462]:+.5f}] | draw rate predicted WITH {100*dr['with'][0]/n:.2f}% / WITHOUT {100*dr['without'][0]/n:.2f}% vs actual {100*dr['with'][1]/n:.2f}% (non-shootout matches)")
