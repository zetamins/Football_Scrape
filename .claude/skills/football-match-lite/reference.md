# Anchor formulas (an input to your judgement, not a replacement for it)

Use any of the three sources you have data for, then combine with `python3 scripts/calc.py --src xg LH LA 1.5 --src results LH LA 1.0 --src strength LH LA 1.0` or simply use them to inform your own final numbers. Home edge `E`: +1 if the venue is in the home team's country, -1 if it is in the away team's country, 0 if neutral or a third country. `adv = 0.2 * E`.

**Results.** For each team use the results the sheet lists (newest first, up to 10; skip a row marked as penalty goals; cap every side at 6 goals). Weight result i by `w = 0.9**i`, where i is its position in the list (0 = newest; a skipped row still counts as a position), times 0.7 if the competition is a friendly. Weighted goals scored `gf` and conceded `ga` per game = sum(w * goals) / sum(w); `n` = sum(w) (effective games). `base = max(0.8, (gf_h + ga_h + gf_a + ga_a) / 4)`. Shrink toward base: `att = (n*gf + 4*base) / (n+4)`, `def = (n*ga + 4*base) / (n+4)` for each team. Then `lam_home = att_h * def_a / base * exp(adv)` and `lam_away = att_a * def_h / base * exp(-adv)`, each clamped to 0.2-4.0.

**xG.** The same with xG for and against per game from the sheet (n = its games), only if both teams have it.

**Strength.** `gap = Elo_home - Elo_away`, times 0.5 unless BOTH Elo sources are `eloratings.net`; plus `100 * ln(value_home / value_away)` (squad market values; clamp that term to +-400). `diff = clamp(gap * 0.0022, -2.5, 2.5) + E * 0.26`. `lam_home = (2.6 + diff) / 2`, `lam_away = (2.6 - diff) / 2`, each clamped to 0.2-4.0. Skip the Elo or the value part if a side lacks it.

## Where the anchor is weak (and what to do)

- **Few results or a new level** (promoted clubs, early season, a nation's first matches in a group): the results and xG sources lean on 1-3 games. Weight the squad-quality view more and say so.
- **Squad value is a ratio, not quality:** a team worth twice as much usually wins more often than a log-ratio of 100 points suggests in club football; use your knowledge of the players.
- **Opponent strength is ignored** in the results source: a run of wins against weak sides inflates it.
- **Early-season and international-break matches:** lineups and fitness matter more than season form.
- **Friendlies:** motivation and rotation dominate; down-weight everything.

## Sanity checks for your final numbers

- Typical internationals: favourite 45-65%, draw 20-30%, underdog 15-35%. A 1X2 favourite above 80% means a mismatch you can name (for example Spain v a micro-state).
- Club leagues: home win about 45%, draw 25%, away 30% on average; the better team away from home is rarely above 55%.
- Expected goals together usually 2.3-3.1; below 2.2 raises 0-0 and 1-1, above 3.2 needs a reason.
