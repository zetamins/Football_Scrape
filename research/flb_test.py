import csv,glob,math,os,random
rows=[]
for f in sorted(glob.glob('.cache/odds/*.csv')):
    season=os.path.basename(f)[3:7] if os.path.basename(f)[2]=='_' else os.path.basename(f).split('_')[-1][:4]
    for r in csv.DictReader(open(f,encoding='utf-8-sig',errors='replace')):
        try:
            o=[float(r['AvgH']),float(r['AvgD']),float(r['AvgA'])]; res={'H':0,'D':1,'A':2}[r['FTR']]
        except (KeyError,ValueError): continue
        if min(o)>1:
            q=[1/x for x in o]; s=sum(q); rows.append((season,[x/s for x in q],res))
print(len(rows),"matches", sorted({r[0] for r in rows}))
train=[r for r in rows if r[0] in('1920','2021','2122')]; test=[r for r in rows if r[0] in('2223','2324','2425')]
print("train",len(train),"test",len(test))
lg=lambda p:math.log(p/(1-p))
def fit(rs):
    # logistic recalibration per outcome class pooled: y ~ sigmoid(a + b*logit(p)), gradient descent
    a,b=0.0,1.0
    data=[(lg(min(max(p[k],1e-4),1-1e-4)), 1.0 if r==k else 0.0) for _,p,r in rs for k in range(3)]
    for it in range(4000):
        ga=gb=0.0
        for x,y in data[::3] if False else data:
            z=a+b*x; pz=1/(1+math.exp(-z)); ga+=pz-y; gb+=(pz-y)*x
        a-=0.5*ga/len(data); b-=0.5*gb/len(data)
        if it>300 and abs(ga)/len(data)<1e-7 and abs(gb)/len(data)<1e-7: break
    return a,b
a,b=fit(train); print("fit a,b",round(a,4),round(b,4))
def adj(p):
    q=[1/(1+math.exp(-(a+b*lg(min(max(x,1e-4),1-1e-4))))) for x in p]; s=sum(q); return [x/s for x in q]
def metrics(rs,fn):
    br=ll=rp=0.0; per=[]
    for _,p,r in rs:
        p=fn(p); o=[1.0 if i==r else 0.0 for i in range(3)]
        b_=sum((p[i]-o[i])**2 for i in range(3)); br+=b_; ll+=-math.log(p[r]); rp+=0.5*((p[0]-o[0])**2+((p[0]+p[1])-(o[0]+o[1]))**2); per.append(b_)
    n=len(rs); return br/n,ll/n,rp/n,per
m0=metrics(test,lambda p:p); m1=metrics(test,adj)
print("test Brier prop %.5f adj %.5f | logloss %.5f %.5f | RPS %.5f %.5f"%(m0[0],m1[0],m0[1],m1[1],m0[2],m1[2]))
d=[x-y for x,y in zip(m1[3],m0[3])]; mu=sum(d)/len(d); sd=math.sqrt(sum((x-mu)**2 for x in d)/(len(d)-1)); print("Brier diff %.5f 95%% CI [%.5f, %.5f]"%(mu,mu-1.96*sd/math.sqrt(len(d)),mu+1.96*sd/math.sqrt(len(d))))
print("--- longshot bins on test: market prob v actual v adjusted")
for lo,hi in((0,.1),(.1,.2),(.2,.3),(.3,.5),(.5,.7),(.7,1)):
    sel=[(p[k],1.0 if r==k else 0.0,adj(p)[k]) for _,p,r in test for k in range(3) if lo<=p[k]<hi]
    if sel: print(f"{lo:.1f}-{hi:.1f} n={len(sel):5} market {100*sum(x[0] for x in sel)/len(sel):5.1f} actual {100*sum(x[1] for x in sel)/len(sel):5.1f} adjusted {100*sum(x[2] for x in sel)/len(sel):5.1f}")
print("--- by season (train fit applied; negative = adjustment better)")
for sea in ('1920','2021','2122','2223','2324','2425'):
    rs=[r for r in rows if r[0]==sea]; a0=metrics(rs,lambda p:p); a1=metrics(rs,adj)
    print(sea,len(rs),"Brier diff %.5f"%(a1[0]-a0[0]),"logloss diff %.5f"%(a1[1]-a0[1]))
# by league: need league code; refit-free
import collections
lg_rows=collections.defaultdict(list)
for f in sorted(glob.glob('.cache/odds/*.csv')):
    code=os.path.basename(f)[:2]
    for r in csv.DictReader(open(f,encoding='utf-8-sig',errors='replace')):
        try:
            o=[float(r['AvgH']),float(r['AvgD']),float(r['AvgA'])]; res={'H':0,'D':1,'A':2}[r['FTR']]
        except (KeyError,ValueError): continue
        if min(o)>1:
            q=[1/x for x in o]; s=sum(q); lg_rows[code].append(('x',[x/s for x in q],res))
print("--- by league: Brier diff (adj - prop), all seasons")
for code,rs in sorted(lg_rows.items()):
    a0=metrics(rs,lambda p:p); a1=metrics(rs,adj); print(code,len(rs),"%.5f"%(a1[0]-a0[0]))
