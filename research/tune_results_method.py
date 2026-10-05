"""Offline validation of analyze.py's results_poisson method (the archive is used ONLY to validate the
formula's constants here; analyze.py itself never touches it). For each match 2018-2026 rebuild each team's last
10 results strictly before kickoff, run the SAME code path, score Brier vs baselines."""
import sys, math, itertools, collections
sys.path.insert(0, '.'); sys.path.insert(0, '..')
from lab import ALL, outcome, brier
from datetime import date
from football import analyze as A

hist = collections.defaultdict(list)   # team -> list of rows newest first
def row(m, team):
    home = (m.home == team)
    gf, ga = (m.hg, m.ag) if home else (m.ag, m.hg)
    res = 'W' if gf > ga else ('D' if gf == ga else 'L')
    sc = f'{m.hg}-{m.ag}'
    return {'scoreline': sc, 'venue': 'home' if home else 'away', 'result': res, 'competition': m.tournament, 'xg_for': None, 'xg_against': None}
samples = []
for m in ALL:
    if m.day >= date(2018, 1, 1):
        hr, ar = hist[m.home][:10], hist[m.away][:10]
        if len(hr) >= 5 and len(ar) >= 5:
            samples.append((m, hr, ar))
    hist[m.home].insert(0, row(m, m.home)); hist[m.away].insert(0, row(m, m.away))
print('matches', len(samples))
def evaluate(shrink, decay, adv, rho):
    A.SHRINK_GAMES, A.RECENCY_DECAY, A.HOME_LOG_ADV, A.DC_RHO = shrink, decay, adv, rho
    tb = 0.0; n = 0
    for m, hr, ar in samples:
        meth = A._poisson_method('r', A._weighted_rates(hr), A._weighted_rates(ar), m.neutral, 1.0, 'x')
        if meth: tb += brier(meth['probs'], outcome(m)); n += 1
    return tb / n
print('uniform 0.6667 | base-rate brier', round(sum(brier((0.47, 0.25, 0.28), outcome(m)) for m, _, _ in samples) / len(samples), 4))
print('current constants (shrink 4, decay .9, adv .10):', round(evaluate(4.0, 0.9, 0.10, -0.05), 4))
best = []
for shrink, decay, adv in itertools.product((2, 4, 8, 16), (0.8, 0.9, 1.0), (0.10, 0.20, 0.30)):
    best.append((evaluate(shrink, decay, adv, -0.05), shrink, decay, adv))
best.sort()
for b in best[:6]: print('  brier %.4f shrink %s decay %s adv %s' % b)
print('worst', ['%.4f' % best[-1][0]] + list(best[-1][1:]))
