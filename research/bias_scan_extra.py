import sys, pickle, math, collections
sys.path.insert(0, '.')
from lab2 import ALL, CACHE
rows = pickle.load(open(f'{CACHE}/bias_rows_v2.pkl', 'rb'))
by_key = {(m.day, m.home, m.away): i for i, m in enumerate(ALL)}
last = {}; played = collections.defaultdict(list)           # team -> list of match days (chronological)
rest = {}                                                     # (day, home, away) -> (home rest, away rest, home matches 4y, away matches 4y)
for m in ALL:
    def r(t):
        lst = played[t]; gap = (m.day - lst[-1]).days if lst else 999
        recent = sum(1 for d in lst[-60:] if (m.day - d).days <= 1460)
        return min(gap, 400), recent
    (hr, hn), (ar, an) = r(m.home), r(m.away)
    rest[(m.day, m.home, m.away)] = (hr, ar, hn, an)
    played[m.home].append(m.day); played[m.away].append(m.day)
for x in rows:
    x['o'] = 0 if x['hg'] > x['ag'] else (1 if x['hg'] == x['ag'] else 2)
    x['hr'], x['ar'], x['hn'], x['an'] = rest[(x['day'], x['home'], x['away'])]
def stats(name, rs, min_n=150):
    n = len(rs)
    if n < min_n: return
    out = []
    for k, label in ((0, 'home win'), (1, 'draw'), (2, 'away win')):
        e = sum(r['p'][k] for r in rs); a = sum(1 for r in rs if r['o'] == k); v = sum(r['p'][k] * (1 - r['p'][k]) for r in rs)
        out.append((label, a / n, e / n, (a - e) / math.sqrt(v)))
    for key, gk, label in (('lh', 'hg', 'home goals'), ('la', 'ag', 'away goals')):
        res = [r[gk] - r[key] for r in rs]; mean = sum(res) / n; var = sum((q - mean) ** 2 for q in res) / n
        out.append((label, sum(r[gk] for r in rs) / n, sum(r[key] for r in rs) / n, mean / math.sqrt(var / n)))
    flag = [o for o in out if abs(o[3]) >= 3.3]
    print(f'{name:56} n={n:5d}  ' + ('FLAGGED: ' + '; '.join(f'{l} {a:.3f} vs {e:.3f} (z {z:+.1f})' for l, a, e, z in flag) if flag else 'no flag (max |z| %.1f)' % max(abs(o[3]) for o in out)))
D = lambda f: [r for r in rows if f(r)]
print('rest days (days since each side last played, capped at 400)')
stats('home rested 3+ days LESS than away', D(lambda r: r['hr'] - r['ar'] <= -3 and r['hr'] < 60 and r['ar'] < 60))
stats('similar rest (within 2 days)', D(lambda r: abs(r['hr'] - r['ar']) <= 2 and r['hr'] < 60))
stats('home rested 3+ days MORE than away', D(lambda r: r['hr'] - r['ar'] >= 3 and r['hr'] < 60 and r['ar'] < 60))
stats('home side first match after 90+ days off', D(lambda r: r['hr'] >= 90)); stats('away side first match after 90+ days off', D(lambda r: r['ar'] >= 90))
stats('both sides played in the last 5 days (window match 2)', D(lambda r: r['hr'] <= 5 and r['ar'] <= 5)); stats('neither played in the last 20 days', D(lambda r: r['hr'] > 20 and r['ar'] > 20))
print('rating uncertainty (matches in the last 4 years)')
for lo, hi in ((0, 12), (12, 25), (25, 40), (40, 999)):
    stats(f'home side {lo}-{hi} matches in 4y', D(lambda r, lo=lo, hi=hi: lo <= r['hn'] < hi)); stats(f'away side {lo}-{hi} matches in 4y', D(lambda r, lo=lo, hi=hi: lo <= r['an'] < hi))
stats('either side < 12 matches in 4y (thin data)', D(lambda r: min(r['hn'], r['an']) < 12))
stats('both sides < 20 matches in 4y', D(lambda r: max(r['hn'], r['an']) < 20))
print('goal-total by match type')
for lab, fn in (('both sides weak (rating gap small, both attack < -0.3)', lambda r: r['att_h'] < -0.3 and r['att_a'] < -0.3), ('both sides strong (attack > 0.3)', lambda r: r['att_h'] > 0.3 and r['att_a'] > 0.3)):
    stats(lab, D(fn), 100)
