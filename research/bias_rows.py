import sys, pickle, os
sys.path.insert(0, '.')
from lab2 import *
from football.history_model import expected_goals, score_grid
out = f'{CACHE}/bias_rows.pkl'
if not os.path.exists(out):
    rows = []
    for bs, be in block_starts((date(2018, 1, 1), date(2027, 1, 1)), 2):
        model = H.fit(ALL, bs, ridge=0.5)
        for m in ALL:
            if bs <= m.day < be:
                r = expected_goals(model, m.home, m.away, m.neutral)
                if r:
                    g = score_grid(r[0], r[1], model.rho)
                    p = (sum(v for (i, j), v in g.items() if i > j), sum(v for (i, j), v in g.items() if i == j), sum(v for (i, j), v in g.items() if i < j))
                    rows.append(dict(day=m.day, home=m.home, away=m.away, hg=m.hg, ag=m.ag, lh=r[0], la=r[1], p=p, neutral=m.neutral, tour=m.tournament,
                                     att_h=model.attack[m.home], att_a=model.attack[m.away], def_h=model.defence[m.home], def_a=model.defence[m.away]))
    pickle.dump(rows, open(out, 'wb'))
print(len(pickle.load(open(out, 'rb'))), 'rows')
