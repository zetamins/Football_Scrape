"""Pi-ratings (Constantinou & Fenton 2013, "Determining the level of ability of football teams by dynamic
ratings based on the relative discrepancies in scores between adversaries"): every team has a separate
home and away rating, updated from the goal-difference error with diminishing returns; a team's home
rating result also nudges its away rating (and vice versa) by `gamma`. Neutral venues move both ratings of
a team equally. Pure Python, state is two dicts."""

from __future__ import annotations

import math


class PiRatings:
    def __init__(self, c: float = 3.0, lam: float = 0.06, gamma: float = 0.5):
        self.c, self.lam, self.gamma = c, lam, gamma
        self.home: dict[str, float] = {}
        self.away: dict[str, float] = {}

    def _expected_gd(self, rating: float) -> float:
        return math.copysign(10 ** (abs(rating) / self.c) - 1.0, rating)

    def pre(self, home: str, away: str, neutral: bool) -> tuple[float, float, float, float, float]:
        """(home team's home rating, home team's away rating, away team's home rating,
        away team's away rating, expected goal difference) before the match."""
        hh, ha = self.home.get(home, 0.0), self.away.get(home, 0.0)
        ah, aa = self.home.get(away, 0.0), self.away.get(away, 0.0)
        if neutral:
            expected = self._expected_gd((hh + ha) / 2) - self._expected_gd((ah + aa) / 2)
        else:
            expected = self._expected_gd(hh) - self._expected_gd(aa)
        return hh, ha, ah, aa, expected

    def update(self, home: str, away: str, home_goals: int, away_goals: int, neutral: bool) -> None:
        hh, ha, ah, aa, expected = self.pre(home, away, neutral)
        error = (home_goals - away_goals) - expected
        delta = self.lam * self.c * math.log10(1 + abs(error)) * (1 if error >= 0 else -1)
        if neutral:
            self.home[home], self.away[home] = hh + delta, ha + delta
            self.home[away], self.away[away] = ah - delta, aa - delta
        else:
            self.home[home], self.away[home] = hh + delta, ha + self.gamma * delta
            self.away[away], self.home[away] = aa - delta, ah - self.gamma * delta
