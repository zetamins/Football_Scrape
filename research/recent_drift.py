"""Is the model overrating home sides lately? Expected vs actual outcomes by year on the held-out rows (shrink not needed for 1X2)."""
import math
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
import collections
by = collections.defaultdict(list)
for r in rows:
    p1, _, _ = markets(r, 0)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    by[r['day'].year].append((p1, o, r['neutral']))
print("| Year | n | home exp/act (z) | draw exp/act (z) | away exp/act (z) |\n|---|---|---|---|---|")
def cells(sel):
    out = []
    for k in range(3):
        e = sum(x[0][k] for x in sel); v = sum(x[0][k] * (1 - x[0][k]) for x in sel); a = sum(1 for x in sel if x[1] == k)
        out.append(f"{e:.0f}/{a} ({(a - e) / math.sqrt(v):+.1f})")
    return out
for y in sorted(by): print(f"| {y} | {len(by[y])} | " + " | ".join(cells(by[y])) + " |")
recent = [x for y in (2025, 2026) for x in by[y]]
print("| 2025-26 non-neutral | %d | " % len([x for x in recent if not x[2]]) + " | ".join(cells([x for x in recent if not x[2]])) + " |")
print("| 2025-26 neutral | %d | " % len([x for x in recent if x[2]]) + " | ".join(cells([x for x in recent if x[2]])) + " |")
