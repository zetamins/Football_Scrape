"""Does the local LLM audit carry any signal? Runs analyzer + local LLM on labelled reports, saves one JSON line each
(resumable), then compares: verdict/lean vs actual results. Slow by design (CPU, thinking mode)."""
import sys, json, glob, os, time
sys.path.insert(0, '..')
from datetime import date
from football.analyze import analyze_report
from football import llm_audit
from football.prediction_log import parse_results_csv
from football.national_elo import canonical_name as C
folder, results_csv, out = sys.argv[1], sys.argv[2], sys.argv[3]
results = {(r['home'], r['away']): r for r in parse_results_csv(open(results_csv, encoding='utf8').read())}
done = set()
if os.path.exists(out):
    done = {json.loads(l)['file'] for l in open(out)}
for f in sorted(glob.glob(f'{folder}/*.json')):
    name = os.path.basename(f)
    if name in done: continue
    d = json.load(open(f)); m = d['match']
    r = results.get((C(m['home_team']), C(m['away_team'])))
    if not r: continue
    a = analyze_report(d, draws=1000)
    if not a['prediction']: continue
    t = time.time(); llm = llm_audit.audit_with_llm(llm_audit.build_brief(d, a))
    o = 0 if r['hg'] > r['ag'] else (1 if r['hg'] == r['ag'] else 2)
    rec = {'file': name, 'outcome': o, 'pred': [a['prediction']['home_win_pct'], a['prediction']['draw_pct'], a['prediction']['away_win_pct']], 'pick': a['prediction']['pick'], 'conf': a['prediction']['confidence_pct'], 'llm': llm, 'secs': round(time.time() - t, 1)}
    open(out, 'a').write(json.dumps(rec) + '\n')
    print(name[:20], llm.get('opinion', {}).get('verdict'), llm.get('opinion', {}).get('lean_if_any'), rec['secs'], flush=True)
