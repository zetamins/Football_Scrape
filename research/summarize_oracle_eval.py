import sys, json, random, math, collections
rows = [json.loads(l) for l in open(sys.argv[1])]
def brier(p, o): return sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
def ll(p, o): return -math.log(max(p[o], 1e-9))
def acc(p, o): return max(range(3), key=lambda k: p[k]) == o
print('matches', len(rows), '| avg secs', round(sum(r['secs'] for r in rows) / len(rows), 1), '| panel voices ok:', collections.Counter(r['panel_n'] for r in rows))
common = [r for r in rows if r['market'] and r['pipeline']]
def table(title, subset, keys):
    print(f'\n{title} (n={len(subset)})')
    for k in keys:
        s = [(r[k], r['outcome']) for r in subset if r.get(k)]
        print(f'  {k:10} brier {sum(brier(p, o) for p, o in s)/len(s):.4f}  logloss {sum(ll(p, o) for p, o in s)/len(s):.4f}  acc {sum(acc(p, o) for p, o in s)/len(s):.3f}')
table('ALL matches', rows, ['quant', 'full', 'pipeline'])
table('Matches with odds (same matches for every method)', common, ['market', 'quant', 'full', 'pipeline'])
rng = random.Random(0)
def paired(a, b, subset, label):
    d = [brier(r[a], r['outcome']) - brier(r[b], r['outcome']) for r in subset]
    bs = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(4000))
    print(f'  {label:32} {sum(d)/len(d):+.4f}  95% CI [{bs[100]:+.4f}, {bs[3900]:+.4f}]  n={len(d)}')
print('\nPaired Brier differences (negative = first is better)')
paired('full', 'quant', rows, 'LLM panel vs quant only (all)')
paired('full', 'market', common, 'Oracle(full) vs odds alone')
paired('quant', 'market', common, 'quant only vs odds alone')
paired('full', 'pipeline', common, 'Oracle(full) vs old pipeline blend')
print('\nPanel adjustments actually applied (mean abs): home %.2f%% away %.2f%% draw %.2fpp' % tuple(sum(abs(r['panel_adjust'][k]) for r in rows if r['panel_adjust']) / len(rows) for k in ('home_rate_pct', 'away_rate_pct', 'draw_bias_pct')))
helped = sum(1 for r in rows if brier(r['full'], r['outcome']) < brier(r['quant'], r['outcome']) - 1e-6)
hurt = sum(1 for r in rows if brier(r['full'], r['outcome']) > brier(r['quant'], r['outcome']) + 1e-6)
print(f'LLM panel changed the Brier for the better on {helped}, worse on {hurt}, ~same on {len(rows)-helped-hurt}')
print('\nCalibrated confidence vs accuracy (full):')
for lo, hi in ((0, 45), (45, 60), (60, 75), (75, 101)):
    b = [r for r in rows if lo <= r['conf_full'] < hi]
    if b: print(f"  {lo:>3}-{hi:<3} n={len(b):2d} mean conf {sum(r['conf_full'] for r in b)/len(b):5.1f}%  accuracy {100*sum(acc(r['full'], r['outcome']) for r in b)/len(b):5.1f}%")
print('overall mean confidence', round(sum(r['conf_full'] for r in rows)/len(rows), 1), '% vs accuracy', round(100*sum(acc(r['full'], r['outcome']) for r in rows)/len(rows), 1), '%')
