import sys, pickle, math
sys.path.insert(0, '.')
from lab2 import CACHE
from football.history_model import score_grid
rows = pickle.load(open(f'{CACHE}/bias_rows_v2.pkl', 'rb'))
for r in rows: r['grid'] = score_grid(r['lh'], r['la'], -0.05); r['tot'] = r['lh'] + r['la']; r['o'] = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
n = len(rows); print(n, 'held-out matches (venue-aware Poisson + Dixon-Coles, rolling out-of-sample)')
print('\nA) EXACT SCORELINES: predicted vs actual frequency (%)')
print(f"{'score':>6} {'predicted':>10} {'actual':>8} {'z':>6}")
for sc in [(0,0),(1,0),(0,1),(1,1),(2,0),(0,2),(2,1),(1,2),(2,2),(3,0),(0,3),(3,1),(1,3),(3,3)]:
    e = sum(r['grid'].get(sc, 0) for r in rows); a = sum(1 for r in rows if (r['hg'], r['ag']) == sc); v = sum(r['grid'].get(sc, 0) * (1 - r['grid'].get(sc, 0)) for r in rows)
    flag = '  <--' if abs((a - e) / math.sqrt(v)) >= 3 else ''
    print(f'{sc[0]}-{sc[1]:>3} {100*e/n:>10.2f} {100*a/n:>8.2f} {(a - e)/math.sqrt(v):>+6.1f}{flag}')
print('\nB) DRAWS BY THE MODEL\'S EXPECTED TOTAL GOALS (lambda home + lambda away), deciles')
rs = sorted(rows, key=lambda r: r['tot']); m = n // 10
print(f"{'total goals (mean)':>20} {'n':>5} {'draw pred':>10} {'draw act':>9} {'z':>5} | {'0-0 pred/act':>13} | {'1-1 pred/act':>13} | {'2-2+ pred/act':>14}")
for i in range(10):
    b = rs[i * m:(i + 1) * m if i < 9 else n]
    e = sum(r['p'][1] for r in b); a = sum(1 for r in b if r['o'] == 1); v = sum(r['p'][1] * (1 - r['p'][1]) for r in b)
    z00 = (sum(r['grid'].get((0, 0), 0) for r in b), sum(1 for r in b if r['hg'] == r['ag'] == 0)); z11 = (sum(r['grid'].get((1, 1), 0) for r in b), sum(1 for r in b if r['hg'] == r['ag'] == 1))
    hi = (sum(sum(p for (x, y), p in r['grid'].items() if x == y and x >= 2) for r in b), sum(1 for r in b if r['hg'] == r['ag'] >= 2))
    print(f"{sum(r['tot'] for r in b)/len(b):>20.2f} {len(b):>5} {100*e/len(b):>9.1f}% {100*a/len(b):>8.1f}% {(a-e)/math.sqrt(v):>+5.1f} | {100*z00[0]/len(b):>5.1f}/{100*z00[1]/len(b):<5.1f} | {100*z11[0]/len(b):>5.1f}/{100*z11[1]/len(b):<5.1f} | {100*hi[0]/len(b):>6.1f}/{100*hi[1]/len(b):<6.1f}")
print('\nC) DRAWS BY HOW LEVEL THE SIDES ARE (|lambda home - lambda away|), quintiles')
rs = sorted(rows, key=lambda r: abs(r['lh'] - r['la'])); m = n // 5
for i in range(5):
    b = rs[i * m:(i + 1) * m if i < 4 else n]; e = sum(r['p'][1] for r in b); a = sum(1 for r in b if r['o'] == 1); v = sum(r['p'][1] * (1 - r['p'][1]) for r in b)
    print(f"  gap {sum(abs(r['lh']-r['la']) for r in b)/len(b):.2f}: n={len(b)} draw predicted {100*e/len(b):.1f}% actual {100*a/len(b):.1f}% z {(a-e)/math.sqrt(v):+.1f}")
