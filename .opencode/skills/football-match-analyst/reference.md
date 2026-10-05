# Reference

## Pipeline (football/oracle/)
`facts.py` JSON -> home/away facts + audit -> `quant.py` rate sources, combine, absences (OFF by default), exact score distribution -> `context.py` evidence-tagged
opinions (agent or LLM panel) -> `oracle.py` adjusted exact score distribution, draw bias, shrink toward base rates, calibrated confidence -> report.

## Rate sources (expected goals per side)
| source | built from | weight |
|---|---|---|
| market | rates whose score grid reproduces the de-vigged H/D/A odds (+ over/under 2.5 when present) | 20 |
| xg | shrunk xG for/against per game, attack x opposing defence | 1.5 |
| results | last 10 results, recency-weighted (0.9 decay, friendlies 0.7), shrunk toward the pooled mean | 1.0 |
| strength | Elo gap (half weight if form-only Elo) + squad market-value ratio -> expected goal difference | 1.0 |
Combined by weighted geometric mean. Home edge +-0.20 on log rates, decided from the VENUE, not the label: venue in the home side's country -> home edge; in the away
side's country -> the AWAY side gets it (label contradicts venue); in a third country or neutral flag -> none. Goals per match are capped at 6 in the rate
estimates (a 10-9 'score' is a shootout/data error and is flagged).

## Player-level absences
Each absentee is matched to the squad list by name. Impact = value share x (0.5 + 0.5 x minutes share of recent games). Attack loss =
forwards + half of midfielders; defence loss = defenders + goalkeepers + half of midfielders. Own rate falls with own attack loss
(sensitivity 0.8); the opponent's rate rises with own defence loss (0.7). A side's rate never moves more than 15% from absences.
The multipliers are applied to the NON-odds sources only (odds already price known absences; applying them to the odds double counted every injury).
Absentees not found in the squad list have unknown, unmodelled impact (flagged in the audit).

## Evidence tags in the brief
`[FIXTURE] [VENUE] [REFEREE] [TRAVEL] [H2H] [LINEUPS] [BASELINE]` and per side `[H.*]` / `[A.*]`: `form table stakes rotation fatigue
manager absent.<Player Name> availability lineup`. Tags exist only when the data exists (no travel info -> no `[TRAVEL]`).

## Opinion JSON
```
{"home_rate_pct": 0, "away_rate_pct": -3, "draw_bias_pct": 0, "confidence": 0.6,
 "factors": [{"effect": "away_rate_pct", "evidence": "[A.rotation]", "note": "changed 5 of 11 starters last match"}],
 "data_gaps": ["confirmed lineups"]}
```
Validation: numbers clamped (rates +-12, draw +-3); an adjustment is scaled by the share of its claims with a real tag and is zero if none;
confidence < 0.2 ignores everything; 1 voice x0.5, 2 voices x0.75 (`--trust` overrides). Rates move the exact score distribution; nothing sets a
probability directly.

## Calibration and evidence (be honest about these)
- Confidence = observed hit rate of picks at that blended probability: 8,054 held-out international matches 2018-2026 (history model). It is
  an approximation for blends that include odds. Rough map: 40% -> ~41, 50% -> ~50, 65% -> ~68, 75% -> ~78, 85% -> ~87.
- Trained history model (separate, uses the results archive): Brier 0.496 on 2,652 held-out matches 2024-26; base rates 0.635; guessing 0.667.
- 36 labelled fixtures with odds: odds alone 0.574; quant blends 0.58-0.60; LLM panels changed Brier by about 0.000 (no measurable value).
- International draw rate 23.5%; a pick-the-largest rule never picks draws, so draw risk must be stated when draw% is high.
- Brier: 0 perfect, 0.667 = always 1/3-1/3-1/3.

## Troubleshooting
- "no rate source could be computed": the report has no odds, xG, usable form or ratings -> no prediction; say so.
- `uv` not found: run from the backend dir with its virtualenv (`.venv/bin/python -m football.oracle ...`).
- Cloud LLM options (only if the user asks): `--llm nvidia` / `--llm openrouter` read NVIDIA_API_KEY / OPENROUTER_API_KEY from the environment
  (free tiers are rate limited; the Gemini key in this environment is denied by Google). Responses are cached on disk.
- Reports for the same match generated at different times can differ; use the newest before kickoff.

## Evidence from testing this skill (38 labelled fixtures, blind agents followed SKILL.md; 20 Sonnet + 18 Haiku)
- Compliance: 38/38 opinions valid; 31 evidenced factors accepted, 1 rejected (a rate source cited as evidence); 22 opinions all-zero. Haiku followed the
  skill as reliably as Sonnet (one multi-tag evidence field, now accepted).
- Accuracy: engine + agent opinion vs engine alone, Brier diff +0.0008 (95% CI -0.0014..+0.0036); better on 8, worse on 8, same on 22. No measurable value from
  the opinions, by either model. LLM panels (earlier test) were also ~0.000.
- What the audit step found (and fixed in the engine): absences double counted on top of odds (Isak, Sesko cut rates by up to 15% although the odds priced them);
  home edge awarded by label although the match was played in the away side's country (Botswana v Tunisia, Somalia v Cote d'Ivoire) or in a third country
  (Ukraine, Israel, Lesotho); a 10-9 score inflating a goal rate; "11 of 11 starters changed" artefacts; squads with many 0M-value players.
- Fixed engine, 36 fixtures with odds: engine alone 0.5789 (was 0.5860), odds alone 0.5739; quant Brier now falls monotonically with odds weight down to 0.5724 at 100% odds.

## Draw evidence (8,054 held-out matches 2018-2026, history model; research/draw_analysis.py, draw_signals.py)
| model draw probability | matches | actual draw rate |
|---|---|---|
| < 15% | 1,242 | 7.7% |
| 15-19% | 723 | 12.3% |
| 19-22% | 801 | 19.0% |
| 22-25% | 1,099 | 24.5% |
| 25-28% | 1,735 | 27.8% |
| 28-31% | 1,755 | 32.3% |
| >= 31% | 699 | 29.9% |
- Situations: sides within 10 points 30.5% draws; favourite above 70% 11.0%; favourite 45-60% 28.9%; friendlies 25.9%, qualifiers 21.2%, Nations League 21.9%.
- Signals that did NOT help (logistic on top of the model, fit 2018-23, tested 2024-26, AUC 0.645 -> 0.645): each team's recent draw share, share of 0/1-goal
  games, average total goals. Recalibrating the draw probability gained 0.001 log-loss (not applied).
- Picking the draw: when draw prob >= 26%, 28%, 30%, 32% the draw pick was right 30.7%, 31.6%, 30.4%, 31.1% vs 45.9%, 44.2%, 44.0%, 43.4% for the normal pick.
  Toss-up rule (|home-away| < 5 pts and draw >= 28%): fires on 5.2% of matches, draw call 36.3% vs normal 32.7% (+3.6 pp, 95% CI -4.3..+10.9; +3.1 / -5.8 / +11.8
  in 2018-21 / 2022-23 / 2024-26): label only.
- Double chance (best of home-or-draw / draw-or-away) covers the result: favourite 33-45% 70.8%; 45-55% 79.0%; 55-70% 88.3%; above 70% 95.7%.
- Your 38 fixtures: 13 draws (34%) against 23% expected: about an 8% chance event at the 23% base rate (about 12% with the engine's own probabilities); none predicted, as normal for a most-likely-outcome pick.

## Draw alert levels (measured on 8,054 held-out matches; stable in 2018-21 / 2022-23 / 2024-26)
| rule | flags % of matches | precision (flagged that ended level) | recall (all draws caught) |
|---|---|---|---|
| draw >= 27% (WATCH) | 38.6 | 30.9% (30.6 / 29.6 / 32.5) | 51.6% |
| draw >= 29% (ALERT) | 22.1 | 32.2% (31.8 / 30.7 / 33.8) | 30.8% |
| draw >= 31% | 8.7 | 29.9% | 11.2% |
| toss-up (|H-A| < 5 pts, draw >= 28%) | 5.2 | 36.3% (37.0 / 31.1 / 39.4) | 8.2% |
| level (|H-A| < 10) and draw >= 27% | 11.8 | 31.3% | 16.0% |
Base draw rate 23.2%. No rule gets precision above ~36%: a draw alert is a 1-in-3 flag, not a prediction.
On the 38 fixtures (13 draws), exact-grid engine: mean draw probability 24.1% = 9.2 expected draws vs 13 actual (about a 12% chance event); 0 draws as the pick; 11 matches flagged (7 watch, 4 alert) caught 4 of the 13 draws (recall 31%, precision 36%): NI-Hungary 31.1% and Ireland-Austria 30.2% (alert), Faroe-Slovakia 27.7% and Greece-Netherlands 27.1% (watch); 7 flagged matches were not draws; 9 draws were unflagged (draw probability 17-26%).

## Odds challenge evidence (36 labelled fixtures with odds, research/odds_challenge_check.py)
| models (without odds) differ from the odds by | matches | odds Brier | models Brier | odds closer |
|---|---|---|---|---|
| 0-5 points | 2 | 0.627 | 0.648 | 2/2 |
| 5-10 | 4 | 0.588 | 0.696 | 4/4 |
| 10-15 | 9 | 0.792 | 0.787 | 5/9 |
| 15+ | 21 | 0.473 | 0.595 | 16/21 |
Where they differed by >= 10 points (30 matches) the result went the odds' way 17 times, the models' way 3, and 10 were draws or neither. Overall the models
without odds scored 0.658 against 0.574 for the odds. The challenge round is therefore a discipline for finding specific, unpriced evidence, not a licence to
override the market; the engine's 85% odds weight already reflects this.
Dossier statuses: priced = inside the engine's numbers (form, xG, squad value, Elo, home edge, modelled absences); NOT priced = rest, travel, H2H, rotation,
stakes, and absentees missing from the squad list (the odds probably price those too).

Bookmakers cannot foresee draws either (8,822 league matches 2022-25, average odds, football-data.co.uk): the odds-implied draw probability is calibrated (24.5% predicted vs
25.1% actual) but ranks draws with AUC 0.564 only. The method used to strip the bookmaker margin (proportional, power, Shin, additive) changes Brier by <= 0.0004, not significant.

## Independent mode (default) -- own model, odds only as the benchmark (38 labelled fixtures; research/independent_curve.py)
| model | Brier (36 with odds) | note |
|---|---|---|
| uniform guess | 0.6667 | |
| odds alone | 0.5739 | the benchmark |
| JSON sources only (xG, results, strength), no absences | 0.6445 | with absences 0.6576 |
| history-led independent (history 25 : others ~3.5) | 0.5896 | default; 0.6172 on all 38 |
| history model alone | ~0.589 | the weaker sources only dilute it |
| odds-led with history 6 (--with-odds) | 0.5763 | odds 20 : history 6 |
| odds 20 + history 25 | 0.5800 | history adds nothing once odds are in |
Absence adjustment (my player-level model) at 0 / 0.25x / 0.5x / 1x strength: 0.6176 / 0.6207 / 0.6237 / 0.6278 (history-led, odds-free): it hurts as it grows, so it is off
(ABSENCE_APPLY_SCALE = 0) and only reported. Teams without a trained model (all clubs): weak_model warning, extra shrink toward base rates.

## International model bias hunt (8,054 held-out matches 2018-26)
A systematic scan (76 slices x 5 measures + 148 teams) found 34 significant biases in the old single-home-advantage model: home wins under-predicted (47.6% vs 45.6%), away wins over-predicted,
away goals at genuine home matches 6.5% too high (CAF -14.5%, AFC -16%, CONMEBOL -29%), neutral-venue home label +16% goals, cross-confederation home goals +14%. The venue is now modelled
per host confederation (away-side drag, neutral-label boost); after the fix 1 slice is flagged (chance level ~0.4) and overall shares match (home 47.6 vs 47.4, draw 23.2 vs 23.0, away 29.2 vs 29.6).
Brier improved 0.00142 (CI -0.00256..-0.00038), better in all three periods. Still watch: draws at neutral venues between moderately matched sides (34% actual vs 28% predicted, n=566, z 3.4).

## Audit of the audit (what was wrong or missing, and what was checked)
- The score distribution used a Poisson-Gamma Monte Carlo (dispersion 14, tempo 0.08) chosen by hand and never validated. Exact evaluation on 4,027 held-out matches: it was WORSE than plain Poisson
  (Brier 0.4955 vs 0.4943, log-loss 0.8464 vs 0.8442), over-predicted draws (23.5% vs 22.6%) and 0-0 (10.0% vs 8.8%); the tempo term did nothing. Replaced by the exact Poisson + Dixon-Coles grid,
  whose markets are calibrated (predicted/actual %: over 1.5 72.4/71.6, over 2.5 48.1/47.9, over 3.5 28.0/28.3, both score 42.2/41.2, 0-0 8.9/8.8, 5+ goals 7.1/7.8).
- Confidence knots, draw tiers and alert precision/recall were fitted on an older model; re-measured on the current one (8,054 held-out matches): pick 37.3->36.1, 52.4->50.7, 64.9->67.1, 84.7->86.8;
  draw tiers observed 7.8 / 14.2 / 20.2 / 23.7 / 28.6 / 31.8 / 31.0%; watch (>=27%) fires 38.5% precision 31.2% recall 51.9%; alert (>=29%) fires 23.7% precision 31.8% recall 32.6%.
- Penalty shootouts: 155 held-out matches (8% of draws) are recorded as draws, and knockout games are recorded after extra time. The one remaining bias flag (neutral-venue draws, z 3.4) shrinks to z 1.5
  without the 29 shootout matches. Training without shootouts changes Brier by -0.0001 (CI -0.0004..+0.0002): not adopted; knockout matches get an audit note ("level after 120 minutes").
- No significant bias for rest days (rested more/less, 90+ days off, both sides on short rest), for thin-history teams (<12 matches in 4 years) or for weak-v-weak / strong-v-strong goal totals (max |z| 3.0 < 3.3).
- Selection bias, stated plainly: the venue model was chosen on the 2018-21 and 2022-23 periods (better in both) and confirmed on 2024-26 (also better); but several other choices (absence model off,
  source weights, independent-mode weights) were made looking at the same 38 live fixtures, so their live numbers are optimistic. Not covered at all: altitude, tournament stage, 90-minute results for knockouts,
  uncertainty of the team ratings themselves (the printed ranges use source disagreement only), anything about clubs (no trained club model yet).

## Draw scorecard (compiled by research/draw_scorecard.py)
Held-out 8,054 matches 2018-26: actual draws 1,865 (23.2%), expected by the model 1,853 (23.0%); the draw was the single most likely outcome 68 times and right 23 (34%).
Segments, predicted vs actual draw % : neutral 23.8/25.0, home venue 22.6/22.3, friendlies 24.1/25.9, qualifiers 21.6/21.2, Nations League 23.9/21.9, major tournaments 24.7/24.8;
by model draw probability: 8.7/7.8 (<15%), 17.1/14.2 (15-19), 20.6/20.2 (19-22), 23.6/23.7 (22-25), 26.6/28.6 (25-28), 29.4/31.8 (28-31), 32.9/31.0 (31+).
Tested and rejected: free low-score multipliers (0-0, 1-0, 0-1, 1-1, 2-2+) fitted 2018-23 are WORSE than Dixon-Coles on 2024-26 (outcome log-loss +0.00098, CI +0.00045..+0.00153); the draw-by-expected-total
pattern (over-predicted at the lowest totals, under-predicted at 2.05-2.44) is not a fixable shape; exact-scoreline calibration is within chance for all 14 common scores.

## Why draws are not "got" (investigation: research/draw_signal_hunt.py + rank analysis; 8,054 held-out matches, train 2018-23, test 2024-26)
The cause is structural, not a hidden bias:
- The draw is the model's 2nd most likely outcome in 84% of matches (6,755), the most likely in 0.8% (68), the least likely in 15.3% (1,231). A pick-the-largest rule can therefore only ever choose it ~1% of the time.
  Actual draws by that slot (actual / expected): most likely 23 / 25, 2nd 1,474 / 1,488, least likely 368 / 340 (+8%, z ~1.6, not significant). 79% of all draws are the 2nd most likely outcome.
- Draws are only weakly predictable beforehand: mean predicted draw probability 26.0% for matches that were draws vs 22.1% for those that were not (a 3.9-point gap); 33.5% of draws come from matches given < 25% draw probability.
- Hidden signal hunt: 32 pre-match features (team draw habits, head-to-head draws, rest, thin data, goal-total tendencies, rating levels, tournament, host confederation, month, year trend) added to the model's draw probability
  do NOT help out of sample: AUC 0.642 as is vs 0.637 (logistic) / 0.637 (gradient boosting); log-loss +0.0018 / +0.0007 (worse); recalibrating the draw logit -0.0002 [-0.0007, +0.0003]; the only important feature is closeness of
  the sides, already in the model. Bookmakers' own draw probability reaches AUC 0.564 (clubs).
- Top-2 coverage: the actual result is among the model's two likeliest outcomes in 84.3% of matches, and for draws in 80.3% (top-1: 61.0% overall, 1.2% for draws): this is what the double chance expresses.
- Live fixtures: 13 draws, none the engine's most likely outcome, 9 its 2nd most likely, 4 its least likely; 4 of 13 (31%) in matches with a >= 60% favourite (held-out 28.8%): the live draws are distributed like normal draws,
  there are just more of them than expected (13 vs 9.2).

## Lineup and availability (built, not promoted)
- `lineup.py` labels each missing player starter (>= 60% of recent minutes), rotation (>= 25%), fringe, or unknown (not in the squad list). Audit flags: `xi_overlap`, `missing_in_xi`, `injured_in_xi`, `xi_not_in_squad`, `empty_absentee_list`, `heavy_rotation`.
- No historical lineups exist, so the absence adjustment cannot be back-tested and stays OFF (`ABSENCE_APPLY_SCALE` = 0). `--log` stores the engine probabilities with absences off and on for every live match; `football.oracle.forward_log score` compares them.
  Gate: 300 matches where they differ, interval below zero on Brier and log-loss, then a fresh-batch confirmation.
- First look at the 38 live matches (27 differ): ON is slightly worse (Brier +0.015, log-loss +0.028, intervals include zero). Too few to decide.
- Plan and reasoning: `research/LINEUP_NEWS_PLAN.md` in the repository.

## Draw-identification techniques from the literature (tested, not adopted)
Diagonal inflation, a closeness-driven draw boost and a bivariate Poisson with a shared goal component were fitted on 2018-23 and scored on 2024-26 (2,652 matches). The first two fit at zero (draws are already calibrated: 23.0% predicted, 23.6% actual).
The bivariate Poisson gained 0.0012 log-loss on 2024-26 but lost 0.0008 in 2022-23 and only shifts the draw level by about a point; draw ranking (AUC 0.643) is unchanged. Not adopted. Details: `research/README.md` in the repository.

## Goal markets: total-goal shrink (adopted)
Over/Under 2.5, both-teams-to-score and clean-sheet probabilities come from a score distribution whose total goal rate is pulled 20% toward the mean total (2.676 goals); 1X2, the draw lens, expected goals and the likeliest scores are not changed.
Reason: at low predicted totals the engine was overconfident in Under (predicted total under 2.0 -> 1.84 goals expected, 2.10 scored; Under quoted 70%+ happened 64%). Held-out effect over 8,054 matches: Over/Under log-loss -0.0025 (z = -3.6), BTTS -0.0026 (z = -5.5), 1X2 unchanged. Details: `research/README.md` in the repository.
