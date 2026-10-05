"""Pi-ratings (Constantinou & Fenton 2013): separate home/away ratings per team, updated on goal-difference
error with diminishing returns; the home-team's home rating also nudges its away rating (and vice versa)."""
import math

class PiRatings:
    def __init__(self, c=3.0, lam=0.06, gamma=0.5):
        self.c, self.lam, self.gamma = c, lam, gamma
        self.home = {}; self.away = {}

    def _g(self, r):  # rating -> expected goal difference vs an average side
        return math.copysign(10 ** (abs(r) / self.c) - 1.0, r)

    def pre(self, m):
        """(R_home_of_home_team, R_away_of_home_team, R_home_of_away_team, R_away_of_away_team, expected GD)."""
        hh, ha = self.home.get(m.home, 0.0), self.away.get(m.home, 0.0)
        ah, aa = self.home.get(m.away, 0.0), self.away.get(m.away, 0.0)
        if m.neutral:
            exp = self._g((hh + ha) / 2) - self._g((ah + aa) / 2)
        else:
            exp = self._g(hh) - self._g(aa)
        return hh, ha, ah, aa, exp

    def update(self, m):
        hh, ha, ah, aa, exp = self.pre(m)
        e = (m.hg - m.ag) - exp
        psi = self.c * math.log10(1 + abs(e)) * (1 if e >= 0 else -1)
        d = self.lam * psi
        if m.neutral:  # no venue information: move both of a team's ratings equally
            self.home[m.home] = hh + d; self.away[m.home] = ha + d
            self.home[m.away] = ah - d; self.away[m.away] = aa - d
        else:
            self.home[m.home] = hh + d; self.away[m.home] = ha + self.gamma * d
            self.away[m.away] = aa - d; self.home[m.away] = ah - self.gamma * d
