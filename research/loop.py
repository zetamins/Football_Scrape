"""Autonomous model-search loop (no human input, never edits production code).

    uv run python research/loop.py [--iters 30] [--patience 8] [--minutes 45] [--seed 1]

Each iteration:
  1. PROPOSE  mutate the leaderboard's top genomes into new candidates (parameter nudges, family
              switches, blends, calibration) -- a genome is a plain dict (see build()).
  2. RANK     score every candidate on the SEARCH window (2018-21, rolling refit, past data only);
              rank by Brier + a parsimony penalty (0.0003 per extra component/knob, so complexity
              must earn its keep).
  3. CONFIRM  the best few non-champion candidates are re-scored on the CONFIRM window (2022-23) and
              compared with the champion by paired bootstrap.
  4. PROMOTE  a challenger replaces the champion only if it is better on SEARCH (adjusted) AND its
              CONFIRM paired-Brier 99% CI lies below -0.0005 (repeated testing -> strict gate).
The AUDIT window (2024-26) is never used for selection; it is scored once at the end for the champion
vs the starting model. Outputs (research/results/): leaderboard.json, iterations.jsonl, champion.json,
report.md. Adoption into football/ stays a separate, tested, human-or-agent step.
"""
import sys, os, json, math, time, random, hashlib, argparse, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import date, datetime, timezone
from lab2 import *   # noqa: F401,F403  (ALL, windows, factories, blend, temperature, paired_boot ...)
from lab2 import _softmax  # noqa: F401

SEARCH = (date(2018, 1, 1), date(2022, 1, 1))
CONFIRM = VAL            # 2022-23
AUDIT = TEST             # 2024-26 (never used to select)
PARSIMONY = 0.0003
MIN_EFFECT = 0.0005      # a promotion must beat the champion by at least this much Brier ...
CONF_Q = 0.005           # ... with the paired 99% interval (0.5%-99.5%) excluding zero: many tests -> stricter gate
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
os.makedirs(OUT, exist_ok=True)

TW_DEFAULT = {c: 1.0 for c in H.CATEGORIES}
BASE = {'f': 'pois', 'ridge': 0.5, 'hl': 4.0, 'start': 2008, 'cap': 0, 'tw': dict(TW_DEFAULT), 'confed': False, 'group_ridge': 1.0, 'T': 1.0, 'dm': 1.0}

def key(g): return hashlib.sha1(json.dumps(g, sort_keys=True).encode()).hexdigest()[:14]

def complexity(g):
    c = 0
    if g['f'] == 'blend':
        return 1 + sum(complexity(p) for p in g['parts']) + (g.get('T', 1.0) != 1.0) + (g.get('dm', 1.0) != 1.0)
    if g['f'] == 'pois':
        c += bool(g.get('cap')) + bool(g.get('confed')) + sum(g['tw'].get(k, 1.0) != 1.0 for k in H.CATEGORIES)
        c += g['start'] != 2008
    else:
        c += 1  # a second model family costs one
    return c + (g.get('T', 1.0) != 1.0) + (g.get('dm', 1.0) != 1.0)

def evaluate(g, window):
    """Per-match probability list for genome g on window (cached by genome hash)."""
    if g['f'] == 'blend':
        parts = [evaluate(p, window) for p in g['parts']]
        res = blend(parts, [1 - g['w'], g['w']], geometric=g.get('geo', False))
    elif g['f'] == 'pois':
        params = dict(ridge=g['ridge'], half_life_years=g['hl'], start_year=g['start'], tournament_weights=dict(g['tw']))
        if g.get('confed'):
            res = run_candidate('g' + key({k: g[k] for k in ('f', 'ridge', 'hl', 'start', 'cap', 'tw', 'confed', 'group_ridge')}), poisson_confed(ridge=g['ridge'], half_life_years=g['hl'], start_year=g['start'], group_ridge=g.get('group_ridge', 1.0)), window)
        else:
            res = run_candidate('g' + key({k: g[k] for k in ('f', 'ridge', 'hl', 'start', 'cap', 'tw', 'confed')}), poisson(cap=g.get('cap') or None, **params), window)
    elif g['f'] == 'elo':
        res = run_candidate('g' + key({k: g[k] for k in ('f', 'k', 'kf', 'home', 'margin', 'window')}), elo_logit(window_years=g['window'], k=g['k'], kf=g['kf'], home=g['home'], margin=g['margin']), window)
    else:
        raise ValueError(g['f'])
    if g.get('T', 1.0) != 1.0 or g.get('dm', 1.0) != 1.0:
        res = temperature(res, g.get('T', 1.0), g.get('dm', 1.0))
    return res

def score_on(res, index):
    """Brier/logloss over `index`; a missing prediction counts as uniform (penalises unknown-team failures)."""
    d = dict(res); b = l = 0.0
    for i in index:
        p = d.get(i) or (1 / 3, 1 / 3, 1 / 3); o = outcome(ALL[i]); b += brier(p, o); l += logloss(p, o)
    return b / len(index), l / len(index)

def eval_index(window):
    base = evaluate(BASE, window)
    return [i for i, p in base if p is not None]

def paired(res_a, res_b, index, n=1000, seed=0, q=0.025):
    da, db = dict(res_a), dict(res_b); u = (1 / 3,) * 3
    diffs = [brier(da.get(i) or u, outcome(ALL[i])) - brier(db.get(i) or u, outcome(ALL[i])) for i in index]
    rng = random.Random(seed); m = len(diffs)
    bs = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return sum(diffs) / m, bs[int(q * n)], bs[min(n - 1, int((1 - q) * n))]

# ---------- mutation operators ----------
def _pick(rng, seq): return seq[rng.randrange(len(seq))]

def mutate(g, rng, pool):
    g = copy.deepcopy(g)
    if g['f'] == 'blend':
        r = rng.random()
        if r < 0.4: g['w'] = round(min(0.6, max(0.05, g['w'] + _pick(rng, [-0.15, -0.1, -0.05, 0.05, 0.1, 0.15]))), 2)
        elif r < 0.55: g['geo'] = not g.get('geo', False)
        elif r < 0.9:
            i = rng.randrange(2); g['parts'][i] = mutate(g['parts'][i], rng, pool)
        else: g['T'] = _pick(rng, [0.9, 0.95, 1.0, 1.05, 1.1]); g['dm'] = _pick(rng, [0.95, 1.0, 1.05])
        return g
    r = rng.random()
    if g['f'] == 'pois':
        if r < 0.22: g['ridge'] = round(min(8.0, max(0.1, g['ridge'] * _pick(rng, [0.5, 0.7, 0.85, 1.2, 1.5, 2.0]))), 3)
        elif r < 0.44: g['hl'] = round(min(12.0, max(1.0, g['hl'] + _pick(rng, [-1.5, -1.0, -0.5, 0.5, 1.0, 2.0]))), 2)
        elif r < 0.55: g['start'] = _pick(rng, [1998, 2002, 2005, 2008, 2010, 2012, 2014])
        elif r < 0.65: g['cap'] = _pick(rng, [0, 5, 6, 8])
        elif r < 0.8: g['tw'][_pick(rng, list(H.CATEGORIES))] = _pick(rng, [0.25, 0.5, 0.75, 1.0, 1.5, 2.0])
        elif r < 0.9: g['confed'] = not g.get('confed', False)
        else: g['T'] = _pick(rng, [0.95, 1.0, 1.05, 1.1]); g['dm'] = _pick(rng, [0.95, 1.0, 1.05, 1.1])
        return g
    # elo
    if r < 0.3: g['k'] = _pick(rng, [20, 30, 40, 50, 60])
    elif r < 0.5: g['kf'] = _pick(rng, [10, 20, 25, 30, 40])
    elif r < 0.65: g['home'] = _pick(rng, [60, 80, 100, 120])
    elif r < 0.75: g['margin'] = not g['margin']
    elif r < 0.9: g['window'] = _pick(rng, [8, 10, 12, 16])
    else: g['T'] = _pick(rng, [0.95, 1.0, 1.05]); g['dm'] = _pick(rng, [0.95, 1.0, 1.05])
    return g

ELO0 = {'f': 'elo', 'k': 40, 'kf': 20, 'home': 100, 'margin': True, 'window': 12, 'T': 1.0, 'dm': 1.0}

def propose(elites, rng, n):
    out = {}
    tries = 0
    while len(out) < n and tries < n * 20:
        tries += 1
        r = rng.random(); parent = _pick(rng, elites)
        if r < 0.65: child = mutate(parent, rng, elites)
        elif r < 0.85: child = {'f': 'blend', 'parts': [copy.deepcopy(parent), mutate(copy.deepcopy(ELO0), rng, elites)], 'w': _pick(rng, [0.15, 0.2, 0.3, 0.4]), 'geo': False, 'T': 1.0, 'dm': 1.0}
        else:
            other = _pick(rng, elites); child = {'f': 'blend', 'parts': [copy.deepcopy(parent), mutate(copy.deepcopy(other), rng, elites)], 'w': _pick(rng, [0.2, 0.3, 0.5]), 'geo': rng.random() < 0.3, 'T': 1.0, 'dm': 1.0}
            if child['parts'][0] == child['parts'][1]: continue
        out[key(child)] = child
    return list(out.values())

def describe(g):
    if g['f'] == 'blend': return f"blend[{describe(g['parts'][0])} | {describe(g['parts'][1])}] w={g['w']}{' geo' if g.get('geo') else ''}" + (f" T={g['T']} dm={g['dm']}" if g.get('T', 1) != 1 or g.get('dm', 1) != 1 else '')
    if g['f'] == 'pois':
        tw = {k: v for k, v in g['tw'].items() if v != 1.0}
        return f"pois r={g['ridge']} hl={g['hl']} st={g['start']}" + (f" cap={g['cap']}" if g.get('cap') else '') + (' confed' if g.get('confed') else '') + (f' tw={tw}' if tw else '') + (f" T={g['T']} dm={g['dm']}" if g.get('T', 1) != 1 or g.get('dm', 1) != 1 else '')
    return f"elo k={g['k']} kf={g['kf']} h={g['home']} {'margin' if g['margin'] else 'nomargin'} w={g['window']}" + (f" T={g['T']} dm={g['dm']}" if g.get('T', 1) != 1 or g.get('dm', 1) != 1 else '')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--iters', type=int, default=30); ap.add_argument('--patience', type=int, default=8)
    ap.add_argument('--minutes', type=float, default=45); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--pop', type=int, default=12)
    args = ap.parse_args()
    rng = random.Random(args.seed); t0 = time.time()
    s_idx, c_idx = eval_index(SEARCH), eval_index(CONFIRM)
    print(f'search matches {len(s_idx)}, confirm matches {len(c_idx)}, seed {args.seed}', flush=True)
    champion = copy.deepcopy(BASE); start = copy.deepcopy(BASE)
    board = {key(BASE): {'g': BASE, 'adj': None}}
    def adj_score(g, idx_res):
        b, l = idx_res; return b + PARSIMONY * complexity(g)
    sb = score_on(evaluate(BASE, SEARCH), s_idx); board[key(BASE)].update(brier=sb[0], logloss=sb[1], adj=adj_score(BASE, sb))
    stale = 0; log = open(os.path.join(OUT, 'iterations.jsonl'), 'a', encoding='utf8'); promotions = []
    for it in range(1, args.iters + 1):
        if (time.time() - t0) / 60 > args.minutes: print('time budget reached'); break
        elites = [e['g'] for e in sorted(board.values(), key=lambda e: e['adj'])[:5]]
        cands = [c for c in propose(elites, rng, args.pop) if key(c) not in board]
        for c in cands:
            try:
                b, l = score_on(evaluate(c, SEARCH), s_idx)
            except Exception as e:  # a broken candidate must not kill the loop
                print('  candidate failed:', describe(c), type(e).__name__, e, flush=True); continue
            board[key(c)] = {'g': c, 'brier': b, 'logloss': l, 'adj': b + PARSIMONY * complexity(c)}
        ranked = sorted(board.items(), key=lambda kv: kv[1]['adj'])
        champ_key = key(champion)
        challengers = [(k, e) for k, e in ranked if k != champ_key][:3]
        champ_entry = board[champ_key]
        promoted = None; confirm_rows = []
        champ_conf = evaluate(champion, CONFIRM)
        for k, e in challengers:
            if e['adj'] >= champ_entry['adj']: continue          # must beat the champion on SEARCH (adjusted)
            conf = evaluate(e['g'], CONFIRM)
            m, lo, hi = paired(conf, champ_conf, c_idx, q=CONF_Q)
            confirm_rows.append((describe(e['g']), round(m, 4), round(lo, 4), round(hi, 4)))
            if hi < -MIN_EFFECT and promoted is None: promoted = (k, e, m, lo, hi)
        if promoted:
            k, e, m, lo, hi = promoted; champion = copy.deepcopy(e['g']); stale = 0
            promotions.append({'iter': it, 'genome': champion, 'confirm_diff': m, 'ci': [lo, hi], 'search_adj': e['adj']})
            print(f'iter {it:2d}  PROMOTED  {describe(champion)}  confirm Brier {m:+.4f} CI [{lo:+.4f},{hi:+.4f}]', flush=True)
        else:
            stale += 1
            top = ranked[0][1]
            print(f'iter {it:2d}  champion kept ({stale}/{args.patience}); best candidate {describe(ranked[0][1]["g"])[:90]} search adj {top["adj"]:.4f} vs champion {champ_entry["adj"]:.4f}; confirmed {len(confirm_rows)}', flush=True)
        log.write(json.dumps({'iter': it, 'time': datetime.now(timezone.utc).isoformat(), 'evaluated': len(cands), 'champion': describe(champion),
                              'top5': [(describe(e['g']), round(e['brier'], 4), round(e['adj'], 4)) for _, e in ranked[:5]], 'confirm': confirm_rows, 'promoted': bool(promoted)}) + '\n'); log.flush()
        if stale >= args.patience: print('patience exhausted'); break
    # ---- outputs
    ranked = sorted(board.values(), key=lambda e: e['adj'])
    json.dump([{'rank': i + 1, 'model': describe(e['g']), 'search_brier': round(e['brier'], 4), 'adj': round(e['adj'], 4), 'genome': e['g']} for i, e in enumerate(ranked[:25])], open(os.path.join(OUT, 'leaderboard.json'), 'w'), indent=1)
    a_idx = eval_index(AUDIT); ares, sres = evaluate(champion, AUDIT), evaluate(start, AUDIT)
    am, alo, ahi = paired(ares, sres, a_idx)
    ab, al = score_on(ares, a_idx); sb2, sl = score_on(sres, a_idx)
    json.dump({'champion': champion, 'description': describe(champion), 'promotions': promotions, 'audit': {'n': len(a_idx), 'champion_brier': ab, 'start_brier': sb2, 'diff': am, 'ci': [alo, ahi]}}, open(os.path.join(OUT, 'champion.json'), 'w'), indent=1)
    with open(os.path.join(OUT, 'report.md'), 'w', encoding='utf8') as f:
        f.write(f'# Loop report ({datetime.now(timezone.utc).isoformat()}, seed {args.seed})\n\nEvaluated {len(board)} distinct models in {round((time.time()-t0)/60,1)} min; {len(promotions)} promotion(s).\n\n')
        f.write('| rank | model | search Brier | adj (parsimony) |\n|---|---|---|---|\n')
        for i, e in enumerate(ranked[:15]): f.write(f"| {i+1} | {describe(e['g'])} | {e['brier']:.4f} | {e['adj']:.4f} |\n")
        f.write(f"\nChampion: **{describe(champion)}**\n\nAUDIT 2024-26 (n={len(a_idx)}, never used for selection): champion {ab:.4f} vs start {sb2:.4f}, paired diff {am:+.4f} CI [{alo:+.4f}, {ahi:+.4f}]\n")
    print(f'\nChampion: {describe(champion)}\nAUDIT (n={len(a_idx)}): champion {ab:.4f} vs start {sb2:.4f}; diff {am:+.4f} CI [{alo:+.4f},{ahi:+.4f}]\nresults in {OUT}', flush=True)

if __name__ == '__main__':
    main()
