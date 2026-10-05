"""Is the Under 2.5 recommendation systematically overconfident when the predicted total is low? Held-out 8,054 matches."""
import sys, pickle, math
import numpy as np
sys.path.insert(0, '..')
exec(open('recommend_eval.py').read().split("out = []")[0])
data = []
for r in rows:
    g = grid(r['lh'], r['la']); over = g[(I + J) > 2].sum(); btts = g[(I > 0) & (J > 0)].sum()
    data.append((r['lh'] + r['la'], abs(r['lh'] - r['la']), 1 - over, r['hg'] + r['ag'] <= 2, r['hg'] + r['ag'], btts, r['hg'] > 0 and r['ag'] > 0))
D = np.array(data, dtype=float)
print('Predicted total goals band | Matches | Predicted total | Actual total | Pred Under % | Actual Under %')
for lo, hi in ((0, 2.0), (2.0, 2.3), (2.3, 2.6), (2.6, 3.0), (3.0, 9)):
    s = D[(D[:, 0] >= lo) & (D[:, 0] < hi)]
    if len(s): print(f"{lo}-{hi} | {len(s)} | {s[:,0].mean():.2f} | {s[:,4].mean():.2f} | {100*s[:,2].mean():.1f} | {100*s[:,3].mean():.1f}")
print('\nxG gap band (mismatch) | Matches | Predicted total | Actual total | Pred Under % | Actual Under %')
for lo, hi in ((0, 0.4), (0.4, 0.8), (0.8, 1.2), (1.2, 9)):
    s = D[(D[:, 1] >= lo) & (D[:, 1] < hi)]
    if len(s): print(f"{lo}-{hi} | {len(s)} | {s[:,0].mean():.2f} | {s[:,4].mean():.2f} | {100*s[:,2].mean():.1f} | {100*s[:,3].mean():.1f}")
# live-style: matches where Under 2.5 is the single most likely selection among markets
sel = D[(D[:, 2] >= 0.5)]
print(f"\nUnder 2.5 pred >=50%: {len(sel)} matches, mean pred {100*sel[:,2].mean():.1f}% vs actual {100*sel[:,3].mean():.1f}%")
for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)):
    s = D[(D[:, 2] >= lo) & (D[:, 2] < hi)]
    if len(s): print(f"  Under prob {int(lo*100)}-{int(min(hi,1)*100)}: {len(s)} matches, pred {100*s[:,2].mean():.1f}% actual {100*s[:,3].mean():.1f}%")
# binomial tails for the live shortfalls
def tail_le(n, k, p): return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
print(f"\nLive: P(<=5 Under hits of 13 | p=0.636) = {tail_le(13,5,0.636):.3f};  P(<=9 1X2 hits of 17 | p=0.68) = {tail_le(17,9,0.68):.3f};  P(<=18 of 38 | p=0.63) = {tail_le(38,18,0.63):.3f}")
