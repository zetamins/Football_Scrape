"""Is the bivariate-Poisson gain consistent across periods? Per-period log-loss difference vs the current Poisson + Dixon-Coles."""
import sys, random
sys.argv = ['x']
exec(open('draw_techniques.py').read().split("train = [r for r in rows")[0])
periods = {'2018-21': lambda y: y <= 2021, '2022-23': lambda y: 2022 <= y <= 2023, '2024-26': lambda y: y >= 2024}
rng = random.Random(2)
print('| c | Period | Matches | Log-loss diff vs current | 95% CI | Draw pred % | Draw actual % |\n|---|---|---|---|---|---|---|')
for c in (0.05, 0.1, 0.15):
    for name, sel in periods.items():
        rs = [r for r in rows if sel(r['day'].year)]
        a = evaluate(rs, lambda r: outcome(dc_grid(r['lh'], r['la']))); b = evaluate(rs, lambda r: outcome(bivar_grid(r['lh'], r['la'], c)))
        d = b['ll'] - a['ll']; n = len(rs); m = d.mean()
        bs = sorted(np.mean([d[rng.randrange(n)] for _ in range(n)]) for _ in range(300))
        print(f"| {c} | {name} | {n} | {m:+.5f} | ({bs[7]:+.5f}, {bs[292]:+.5f}) | {100*b['draw_pred']:.1f} vs base {100*a['draw_pred']:.1f} | {100*b['draw_act']:.1f} |")
