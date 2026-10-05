"""Evaluate the Oracle on labelled report JSONs: odds alone vs quant-only vs quant+LLM panel (+ the old analyzer / pipeline blend).
Resumable (appends to a jsonl); LLM answers are cached on disk so reruns are free and exact.
usage: eval_oracle.py <reports dir> <results.csv> <out.jsonl> [panel spec]"""
import sys, json, glob, os, time
sys.path.insert(0, '..')
from datetime import date
from football.oracle import oracle as O
from football.prediction_log import parse_results_csv
from football.national_elo import canonical_name as C
folder, results_csv, out = sys.argv[1:4]
panel = sys.argv[4] if len(sys.argv) > 4 else "nvidia:nvidia/nemotron-3-super-120b-a12b,nvidia:openai/gpt-oss-20b,nvidia:nvidia/nemotron-3-ultra-550b-a55b"
results = {(r['home'], r['away']): r for r in parse_results_csv(open(results_csv, encoding='utf8').read())}
done = set()
if os.path.exists(out):
    done = {json.loads(l)['file'] for l in open(out)}
for f in sorted(glob.glob(f'{folder}/*.json')):
    name = os.path.basename(f)
    if name in done: continue
    d = json.load(open(f)); m = d['match']
    r = results.get((C(m['home_team']), C(m['away_team'])))
    if not r or abs((r['day'] - date.fromisoformat(m['kickoff_utc'][:10])).days) > 1: continue
    t = time.time()
    quant = O.predict(d, panel="none", sims=60_000)
    full = O.predict(d, panel=panel, sims=60_000)
    if not quant['prediction']: continue
    o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    pr = lambda x: [x['prediction']['home_win_pct'] / 100, x['prediction']['draw_pct'] / 100, x['prediction']['away_win_pct'] / 100]
    odds = (d['match'].get('betting_odds') or d['match'].get('sofascore_betting_odds') or {})
    mk = [odds.get('home_win_fair_pct'), odds.get('draw_fair_pct'), odds.get('away_win_fair_pct')]
    mk = [v / 100 for v in mk] if all(isinstance(v, (int, float)) for v in mk) else None
    bl = (d['insights'].get('prediction') or {}).get('blended')
    rec = {'file': name, 'outcome': o, 'quant': pr(quant), 'full': pr(full), 'market': mk,
           'pipeline': [bl['home_win_pct'] / 100, bl['draw_pct'] / 100, bl['away_win_pct'] / 100] if bl else None,
           'conf_quant': quant['prediction']['confidence_pct'], 'conf_full': full['prediction']['confidence_pct'],
           'panel_adjust': full['panel']['adjust'] if full['panel'] else None, 'panel_n': full['panel']['n'] if full['panel'] else 0,
           'members_ok': [m['ok'] for m in (full['panel'] or {}).get('members', [])], 'secs': round(time.time() - t, 1)}
    open(out, 'a').write(json.dumps(rec) + '\n')
    print(name[:22], 'n_ok', rec['panel_n'], 'adjust', rec['panel_adjust'], rec['secs'], 's', flush=True)
