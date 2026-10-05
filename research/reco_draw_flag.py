"""When the draw is flagged (P(draw) >= 27%), is 'Either side to win (no draw)' a good double-chance pick, or should the bet avoid it? Held-out 8,054 (shrink applied)."""
exec(open('total_shrink.py').read().split("print('mean total (train)")[0])
rows_ = []
for r in rows:
    p1, _, _ = markets(r, 0)
    o = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
    rows_.append((r['day'].year, p1, o))
def best(p1, allow12):
    opts = [(p1[0] + p1[1], (0, 1), '1X'), (p1[1] + p1[2], (1, 2), 'X2')]
    if allow12: opts.append((p1[0] + p1[2], (0, 2), '12'))
    return max(opts)
def run(sel, label):
    for allow in (True, False):
        h = []; q = []; n12 = 0
        for _, p1, o in sel:
            pr, outs, name = best(p1, allow); h.append(o in outs); q.append(pr); n12 += name == '12'
        print(f"{label:34s} allow '12': {str(allow):5s} n={len(sel):5d} picks '12': {n12:4d} quoted {100*np.mean(q):.1f}% hit {100*np.mean(h):.1f}%")
flag = [x for x in rows_ if x[1][1] >= 0.27]
weak = [x for x in flag if max(x[1]) < 0.5]            # the matches where the double chance is the recommended bet anyway
run(flag, "draw >= 27%")
run(weak, "draw >= 27% and best 1X2 < 50%")
run([x for x in rows_ if x[1][1] >= 0.29], "draw >= 29% (ALERT)")
run([x for x in weak if x[0] >= 2024], "draw >= 27%, best < 50%, 2024+")
