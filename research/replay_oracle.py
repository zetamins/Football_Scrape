"""Offline replay: recompute quant-only and quant+RECORDED-LLM-adjustments with the CURRENT code (no new LLM calls) from a
previous eval run's jsonl. The panel's recorded adjustments are applied to the new baseline rates, which is valid because
the adjustments are percentages of rate and (nearly) independent of the exact baseline."""
import sys, json, glob, os, random, math
sys.path.insert(0, '..')
from datetime import date
from football.oracle import quant as Q
from football.oracle.facts import extract_facts
folder, jsonl = sys.argv[1:3]
rec = {json.loads(l)['file']: json.loads(l) for l in open(jsonl)}
def brier(p, o): return sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
def acc(p, o): return max(range(3), key=lambda k: p[k]) == o
rows = []
for name, r in rec.items():
    d = json.load(open(os.path.join(folder, name))); fa = extract_facts(d)
    src = Q.rate_sources(fa)
    if not src: continue
    lh, la, _ = Q.combine_rates(src); mh, ma, _ = Q.absence_multipliers(fa)
    quant = Q.outcome_probs(lh * mh, la * ma)
    adj = r['panel_adjust'] or {'home_rate_pct': 0, 'away_rate_pct': 0, 'draw_bias_pct': 0}
    full = list(Q.outcome_probs(lh * mh * (1 + adj['home_rate_pct'] / 100), la * ma * (1 + adj['away_rate_pct'] / 100)))
    pp = adj['draw_bias_pct'] / 100
    dec = full[0] + full[2]
    full = [full[0] - pp * full[0] / dec, full[1] + pp, full[2] - pp * full[2] / dec]
    rows.append({'o': r['outcome'], 'quant': quant, 'full': full, 'market': r['market'], 'pipeline': r['pipeline'], 'old_full': r['full']})
common = [x for x in rows if x['market'] and x['pipeline']]
print('replayed', len(rows), 'matches;', len(common), 'with odds')
for title, sub, keys in (('all', rows, ['quant', 'full', 'old_full', 'pipeline']), ('with odds (same matches)', common, ['market', 'quant', 'full', 'old_full', 'pipeline'])):
    print(f'\n{title} (n={len(sub)})  [old_full = previous run with market weight 4]')
    for k in keys:
        s = [(x[k], x['o']) for x in sub if x[k]]
        print(f'  {k:9} brier {sum(brier(p, o) for p, o in s)/len(s):.4f}  acc {sum(acc(p, o) for p, o in s)/len(s):.3f}')
rng = random.Random(0)
def paired(a, b, sub, label):
    d = [brier(x[a], x['o']) - brier(x[b], x['o']) for x in sub]
    bs = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(4000))
    print(f'  {label:36} {sum(d)/len(d):+.4f}  95% CI [{bs[100]:+.4f}, {bs[3900]:+.4f}]  n={len(d)}')
print('\nPaired Brier differences (negative = first better)')
paired('full', 'quant', rows, 'LLM panel vs quant only')
paired('full', 'market', common, 'Oracle(full) vs odds alone')
paired('quant', 'market', common, 'quant only vs odds alone')
paired('full', 'pipeline', common, 'Oracle(full) vs old pipeline blend')
