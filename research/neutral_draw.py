import sys, pickle, math, collections
sys.path.insert(0,'.')
from lab2 import CACHE
rows=pickle.load(open(f'{CACHE}/bias_rows_v2.pkl','rb'))
for r in rows:
    r['d']=int(r['hg']==r['ag']); r['pd']=r['p'][1]; r['pf']=max(r['p'][0],r['p'][2]); r['tot']=r['lh']+r['la']
print(len(rows), rows[0].keys())
def rep(name,rs):
    n=len(rs)
    if n<50: print(f"{name:45} n={n} (small)"); return
    a=sum(r['d'] for r in rs); e=sum(r['pd'] for r in rs); v=sum(r['pd']*(1-r['pd']) for r in rs)
    print(f"{name:45} n={n:5} drawn {100*a/n:5.1f}% expected {100*e/n:5.1f}% z {(a-e)/math.sqrt(v):+.2f}")
rep('ALL',rows)
for lab,f in (('neutral',lambda r:r['neutral']),('non-neutral',lambda r:not r['neutral'])):
    rs=[r for r in rows if f(r)]; rep(lab,rs)
    for lo,hi in((0,.45),(.45,.55),(.55,.65),(.65,.8),(.8,1.01)):
        rep(f"  {lab} favourite {int(lo*100)}-{int(hi*100)}%",[r for r in rs if lo<=r['pf']<hi])
mod=lambda r: .40<=r['pf']<.60
print('--- moderately matched (fav 40-60%) neutral, by year')
for y in sorted({r['day'].year for r in rows}):
    rep(f"  {y} neutral moderate",[r for r in rows if r['neutral'] and mod(r) and r['day'].year==y])
rep('neutral moderate, low total (<2.5)',[r for r in rows if r['neutral'] and mod(r) and r['tot']<2.5])
rep('non-neutral moderate, low total (<2.5)',[r for r in rows if not r['neutral'] and mod(r) and r['tot']<2.5])
rep('any, total<2.2',[r for r in rows if r['tot']<2.2])
rep('any, total<2.2 and fav<55%',[r for r in rows if r['tot']<2.2 and r['pf']<.55])
