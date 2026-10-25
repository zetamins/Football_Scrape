import sys,pickle,math,collections
sys.path.insert(0,'.')
from lab2 import CACHE
import football.history_train as H
rows=pickle.load(open(f'{CACHE}/bias_rows_v2.pkl','rb'))
for r in rows:
    r['o']=0 if r['hg']>r['ag'] else (1 if r['hg']==r['ag'] else 2); r['cat']=H.tournament_category(r['tour'])
train=[r for r in rows if r['day'].year<=2023]; test=[r for r in rows if r['day'].year>=2024]
print(len(train),len(test))
def rates(rs):
    c=collections.Counter(r['o'] for r in rs); n=len(rs); return [(c[i]+1)/(n+3) for i in range(3)]
glob_=rates(train)
by={}
for r in train: by.setdefault((r['cat'],bool(r['neutral'])),[]).append(r)
bymap={k:rates(v) for k,v in by.items() if len(v)>=60}
br=lambda p,o:sum((p[i]-(i==o))**2 for i in range(3)); ll=lambda p,o:-math.log(max(p[o],1e-9))
def ev(fn):
    return sum(br(fn(r),r['o']) for r in test)/len(test), sum(ll(fn(r),r['o']) for r in test)/len(test)
print("global constant      Brier %.4f logloss %.4f"%ev(lambda r:glob_), glob_)
print("category x neutral   Brier %.4f logloss %.4f"%ev(lambda r:bymap.get((r['cat'],bool(r['neutral'])),glob_)))
print("history model p      Brier %.4f logloss %.4f"%ev(lambda r:r['p']))
for k,v in sorted(bymap.items()): print(k,len(by[k]),[round(100*x,1) for x in v])
