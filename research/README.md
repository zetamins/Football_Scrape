# Technique search log (2026-10-04, overnight)

Harness: `lab.py`/`lab2.py` (rolling-origin refit every 6 months, predictions only from data strictly
before each block; paired bootstrap for differences). `passN.py` rank candidates on the 2022-23
VALIDATION window; `final_test.py` scores finalists ONCE on 2024-26. Paths inside the scripts point at the
session scratchpad (`results.csv` = martj42 archive) -- edit `S` in lab.py to re-run.

Ranking rule: rank on validation (Brier), prune, refine/combine the top, then a single test-window run.
Adopt only if the paired 95% CI on the test window excludes zero.

| Pass | Tested | Result (validation Brier; current model 0.5156) |
|---|---|---|
| 1 | half-life 3/6/8y, ridge .5/2, goal cap 4/6, start year, Elo K/nu/margin, Elo->logit mapping | Poisson variants all within 0.5153-0.5189; Elo 0.521-0.532 (worse) |
| 2 | finer ridge/half-life, bagged Poisson, Poisson+Elo-logit blends (arith/geo, 15-50%) | best blend 0.5139 (-0.0017); bagging no gain |
| 3 | temperature + draw-multiplier calibration, stacked softmax | calibration no gain (model already calibrated); stack 0.5137 |
| 4 | confederation-mean shrinkage, rest/congestion/form/same-confed features in Elo-logit | confed -0.0002 (noise); extra features HURT (+0.0069) |
| final (2024-26, n=2652) | finalists vs current | ridge 0.5: -0.0008 SIGNIFICANT (adopted); confed prior -0.0011 (not adopted: complexity, not shown better than ridge 0.5); Elo blends: not significant (validation gain did not replicate) |

Also found: Newton fit diverged (OverflowError / Brier 0.675 at half-life 8y); fixed with step damping + rate clamp.

Conclusion: archive-only information plateaus near Brier 0.496 on 2024-26; remaining gains need new
information (market odds, squad values, lineups), which is what the prediction log is for.

## Autonomous loop (`loop.py`)

`uv run python research/loop.py --iters 40 --patience 10 --minutes 40 --seed 7`

Propose (mutate top genomes: parameters, family, blends, calibration) -> rank on SEARCH 2018-21
(Brier + 0.0003 per extra component/knob) -> confirm the top challengers on 2022-23 with a paired
bootstrap -> promote only if the 99% CI is below -0.0005 Brier. The 2024-26 AUDIT window is never used for
selection. Writes `results/{leaderboard.json,iterations.jsonl,champion.json,report.md}`; it never edits
`football/`. The first version of the gate (95% CI, no minimum effect) promoted a blend that the audit window
then showed was noise -- hence the stricter rule. First run (seed 7): no challenger cleared the gate; the
production model (Poisson, ridge 0.5, half-life 4y) stayed champion.

Needs: `uv run` (allowed), network once to download the archive into `research/.cache/` (gitignored).

## Pi-ratings + gradient boosting (research/pi.py, gbt.py, prod_check*.py)

Needs `uv run --with scikit-learn --with numpy --with lightgbm python research/gbt.py` (throwaway env; the
project itself gained no dependency). Literature motivation: CatBoost/GBM on pi-ratings won the Soccer
Prediction Challenge; Groll-style hybrids feed ratings + odds + squad covariates into forests.

Prototype (ratings updated online inside each 6-month block, models refit every 6 months), Brier diff vs the
Poisson model [95% CI]: 70/30 Poisson + logistic-on-pi/Elo-features: 2018-21 -0.0025*, 2022-23 -0.0029*,
2024-26 -0.0013. Standalone GBT/logit on pi features were WORSE than Poisson (+0.007 on test, significant);
stacking the Poisson probabilities as a feature did not help; LightGBM/HistGB no better than logistic.

That prototype flattered pi-ratings (fresh online ratings vs a frozen Poisson). The shipped pure-Python code
(football/pi_ratings.py, history_train.fit_pi; features = 4 pi ratings, expected GD, Elo gap, neutral) refit
monthly for BOTH models: -0.0012, -0.0014, -0.0002; pooled n=8054 -0.0009 [-0.0018, +0.0000] -> consistent in
sign but NOT significant. Shipped at PI_BLEND_WEIGHT=0.3, flagged unproven; revisit with the prediction log.

Side finding: refitting monthly instead of every 6 months improves the plain Poisson model too
(0.5010->0.4993, 0.5156->0.5139, 0.4963->0.4952): refit with `python -m football.history_train fit` often (5 s).

## JSON-in analyst (`football/analyze.py`)

`python -m football.analyze report.json [more.json | folder/] [--deep] [--json]` -- no training, no archive, no seed
files, no network: audit -> independent calculations (de-vigged odds, xG Poisson, results Poisson, Elo gap with
rest/absence/travel, squad value) -> weighted combine, shrunk toward base rates when data is poor -> calibrated
chance-the-pick-is-right -> Monte Carlo ranges (`--deep` = 100k draws). Works for any league.

Validation: `eval_analyze.py` (38 labelled fixtures): analyzer Brier 0.597 vs odds alone 0.574 vs old pipeline blend
0.593 on the 36 with odds (diff vs odds +0.0235, CI [-0.019,+0.061]: not distinguishable). On those 38 the
results/xG/form-Elo methods each scored worse than guessing, squad value was the best non-odds method (0.598).
`tune_results_method.py` re-checks the results-Poisson formula offline on 8,041 historical matches (Brier 0.571 vs
base rate 0.635): home-advantage constant 0.10 -> 0.20 (0.5711 -> 0.5675) adopted; the 38 got slightly worse
(0.6037 -> 0.6118) -- small sample, 13 draws -- the larger sample wins. The archive is used only to validate
constants offline, never at run time.

## Local LLM audit (`football/llm_audit.py`, `analyze --llm [model]`)

Hardware found: i7-1255U (AVX2, no discrete GPU), 7.5 GB RAM (~2 GB free), Ollama 0.30 with qwen3:1.7b (1.4 GB),
qwen2.5:3b (1.9 GB). Default model qwen3:1.7b with thinking on (~85 s/report on CPU; `--fast` = ~28 s, `--llm qwen2.5:3b`
to switch). The model never touches the numbers: it reads a condensed brief and returns a schema-constrained JSON opinion
(verdict, concerns, missing context, lean) shown as advisory. Same brief, Spain-Croatia: qwen3 no-think invented a concern
("exact venue not specified" though given); qwen2.5:3b returned label-like, less useful output ("insufficient_data");
qwen3 + thinking cited real items (H2H 5-2, three absentees, 16% market gap) -> default. `eval_llm.py` measures whether its
verdict/lean carries any signal on the 38 labelled fixtures (results/llm_eval.jsonl).

## Oracle (`football/oracle/`) -- from-scratch JSON-in predictor with a cloud LLM panel

`python -m football.oracle report.json [--llm auto|none|nvidia|openrouter|ollama|provider:model,...] [--sims N] [--json]`

facts.py (JSON -> home/away facts, player-level absence impact, data audit) -> quant.py (4 goal-rate sources: odds-implied rates via
grid inversion, xG, results, Elo+squad-value strength; weighted geometric combine; absence multipliers capped at +-15%;
Poisson-Gamma Monte Carlo with shared tempo factor) -> context.py (LLM panel: bounded +-12% rate / +-3pp draw adjustments, each must
cite an evidence tag that exists in the brief, aggregated by median/mean x trust) -> oracle.py (adjusted simulation, draw bias,
shrink toward base rates when data is poor, calibrated confidence) -> markdown report with the whole trace.

LLM providers (llm.py): keys only from env (never logged); disk cache keyed by (provider, model, prompts); per-provider throttle;
retry on 429/5xx. Free-tier research (Oct 2026): OpenRouter free 20 req/min, ~50/day (1,000/day after a one-off $10); Groq 30 req/min,
1,000/day, 200K tokens/day/model; Google AI Studio varies by model, prompts may train outside EU; Mistral ~1B tokens/month but training
opt-in; Cloudflare 10K neurons/day; NVIDIA NIM ~40 req/min. No provider is unlimited. This account: NVIDIA (works: nemotron-3-super 1.6 s,
nemotron-3-ultra 12 s, gpt-oss-20b 38 s; several listed models 404; kimi-k3 64 s and deepseek-v4.1-flash/glm-5.3-flash time out),
OpenRouter free (qwen3.8-27b 3 s; gemma 429), Gemini key = project denied (HTTP 403 PERMISSION_DENIED).

`eval_oracle.py` + `summarize_oracle_eval.py` evaluate odds vs quant-only vs quant+panel on the 38 labelled fixtures.

## Skill test on the 38 (blind agents following .claude/skills/football-match-analyst/SKILL.md)
8 batches (Sonnet x4, Haiku x4), each agent ran the engine, audited, wrote an opinion JSON; opinions re-applied by `score_skilltest.py`.
Result: skill workflow works (38/38 valid, 31 evidenced factors, 1 rejected); agent opinions add no measurable accuracy (+0.0008 Brier, CI -0.0014..+0.0036).
The audits found real engine defects, now fixed (tests/test_oracle.py, last block): absences double counted over odds; home edge from label instead of venue;
10-9 score inflating rates; artefact flags; tolerant multi-tag evidence. Engine alone on 36 fixtures with odds: 0.5860 -> 0.5789 (odds alone 0.5739).
Market weight curve re-run (market_weight_curve.py) after the fix: monotone again (0.6576 at 0% odds ... 0.5757 at 85% ... 0.5724 at 100%).

## Draws (research/draw_analysis.py, draw_signals.py)
Draw probability already calibrated (23.2% vs 23.2%), AUC 0.645; team draw tendency / low-scoring form add nothing; picking draws loses (31% vs 44% right);
toss-up draw call +3.6pp on 5% of matches, not significant -> engine keeps its pick and prints a "Draw lens" (tier + observed rate, double chance, 0-0/1-1/2-2,
toss-up flag). Skill gets matching rules (draw_bias only for cited draw-specific context; draw lens in every answer).

## Odds challenge + advocates (football/oracle/debate.py, research/odds_challenge_check.py)
Engine: `challenge()` (odds vs models without odds: gap per outcome, who the models lean to, total-goals/tempo disagreement, base rate), `dossier()` (deterministic
evidence per side, priced / NOT priced, strength), `check_advocates()` (tags verified, text shown, never moves a probability). Brief and report both print them; the
opinion JSON takes an optional `advocates` {home, away, odds_challenge, verdict}. Evidence: of 30 fixtures where models differed from the odds by >= 10 points the
result went the odds' way 17 times, the models' 3 (10 draws/neither) -> default verdict `odds_right`; burden of proof on the challenge. Skill step 4 added (both copies).

## De-vig methods and bookmaker draw skill (research/devig_test.py; football-data.co.uk, 8 leagues x 3 seasons, 8,822 matches, average odds)
| method | Brier | log-loss | RPS | Brier diff vs proportional (95% CI) |
|---|---|---|---|---|
| proportional (current) | 0.5761 | 0.9683 | 0.1954 | - |
| additive | 0.5757 | 0.9674 | 0.1952 | -0.00038 [-0.00105, +0.00034] |
| power | 0.5757 | 0.9674 | 0.1952 | -0.00037 [-0.00112, +0.00051] |
| Shin | 0.5757 | 0.9675 | 0.1953 | -0.00032 [-0.00079, +0.00015] |
No method is significantly better -> unchanged. Longshots are over-rated by the odds (implied 7.3% vs actual 4.1% under 10%; 15.4% vs 13.6%; 27.8% vs 26.2%), which the
alternative methods only partly remove. Bookmakers' own draw probability is calibrated (24.5% vs 25.1% actual) but ranks draws weakly: AUC 0.564 (our history model on
internationals 0.645): even the market cannot foresee draws.

## International model checks (research/goal_bias.py, neutral_adv_test.py) -- 2024-26 held-out, monthly refit
- Expected goals are calibrated by rate bin (home 0.57->0.61 ... 3.01->3.12; away within 0.01-0.1), total 2.641 predicted vs 2.739 actual, P(0-0) 9.0% vs 9.0%, over 2.5 47.6% vs 50.5%.
- The only systematic gap: neutral-venue matches, where the side listed as home scores 14-17% more than the model expects (ratio 1.144 / 1.136 / 1.165 in 2018-21 / 2022-23 / 2024-26,
  n = 946 / 650 / 962); genuine home matches are calibrated (1.015 / 1.019 / 1.012).
- A neutral-label advantage term fixes the goal count but not the outcomes: Brier diff +0.0006 / -0.0007 / -0.0002, pooled 0.0000 [-0.0010, +0.0010] -> option kept, default off.
- The live results archive ends 2026-08-26 (no newer international results are public), and all 65 teams in the 38 reports map to a trained team.

## Bias hunt on the international model (research/bias_rows.py, bias_scan.py, venue_test.py) -- 8,054 held-out matches 2018-2026, refit every 2 months
Scan: 76 slices (confederation of host / visitor, confederation pairings, tournament and tournament category, year, month, rating-gap octiles, favourite strength x venue)
x 5 measures (home/draw/away share, home goals, away goals) + 148 teams; flag |z| >= 3.3 (about 0.4 chance flags expected).
BEFORE (single home-advantage parameter): 34 flagged measures. Overall home win 47.6% actual vs 45.6% predicted (z +4.2), away win 29.2% vs 31.1% (z -4.2), home goals 1.601 vs 1.527.
Drivers: away goals at genuine home matches over-predicted 6.5% (z -5.1), by confederation: CAF -14.5%, AFC -16%, CONMEBOL -29% (n=251); neutral venues: listed-home side +16% goals and
away side +7%; cross-confederation matches home goals +14%; friendlies / qualifiers / World Cup home-win under-prediction (all the same venue effect).
FIX: venue model with an away-side drag, a neutral-label boost and per-host-confederation deviations (shrunk toward the global value), now the default (`fit(venue="confed")`).
Backtest vs the old model, paired, 8,053 matches: Brier -0.00142 [-0.00256, -0.00038], log-loss -0.00244 [-0.00422, -0.00081]; better in each of 2018-21 / 2022-23 / 2024-26
(split without confederations: -0.00067 [-0.00150, +0.00020], not significant). Fitted: home boost 0.186, away drag -0.211, neutral-label boost +0.050; CONMEBOL host +0.099 / visitor -0.103
(drag -0.31 in total), UEFA visitor drag only -0.11.
AFTER: 1 flagged measure (expected by chance ~0.4): home win 47.6% vs 47.4% (z +0.4), draw 23.2% vs 23.0%, away 29.2% vs 29.6% (z -0.8), home goals 1.601 vs 1.577 (z +1.6);
no team is persistently mis-rated (0 of 148 at |z| >= 3). Remaining flag: draws in neutral-venue matches between moderately matched sides, 34.1% vs 27.6% (n=566, z +3.4):
one flag among ~380 tests is not conclusive; watch it.
Live 38 fixtures: independent engine 0.5885 on the 36 with odds (was 0.5896), i.e. unchanged within noise; the evidence is the large set.

## Audit of the audit (research/sim_validation.py, shootout_test.py, bias_scan_extra.py)
See skill reference "Audit of the audit": simulation layer replaced by the exact Poisson + Dixon-Coles grid (the Monte Carlo was worse and biased), calibration tables re-measured, shootout handling
tested (not adopted), rest / thin-data / goal-total slices clean, selection-bias and not-covered list.

## Draw scorecard and draw-shape tests (research/draw_scorecard.py, draw_bias.py, lowscore_fit.py)
Live 38 (exact-grid independent engine): 13 draws (34%) vs 9.2 expected (24.1%), 10% chance event; no draw as the pick; 11 flagged (7 watch + 4 alert) caught 4 draws (recall 31%, precision 36%).
Held-out 8,054: 1,865 draws vs 1,853 expected; draw as the pick 68 times, right 23. Exact scorelines calibrated; free low-score multipliers worse than Dixon-Coles out of sample (rejected).

## Prompt audit and fixes (tests/test_prompts.py)
Defects found: the cloud-panel system prompt still claimed the engine prices the odds and the value of absent players (false in independent mode); SKILL.md contradicted itself on absentees
("all modelled" vs "not applied"); the opinion format had no concrete example (Haiku put several tags in one field); the brief showed the odds without saying they are only a benchmark;
no copy-ready answer template or self-check. Fixes: `context.system_prompt(mode)` (mode-aware, built from the validator's own bounds), `EXAMPLE_OPINION` shown in the brief and the system prompt,
BASELINE line labelled by mode, SKILL.md rewritten (91 lines: quick start, 8 steps, opinion example, answer template, hard rules, self-check). tests/test_prompts.py keeps them in sync: the prompt's bounds equal the
validator's, the examples validate, every flag in the skill exists, no removed flag/word appears, both skill copies are identical, and every quick-start command in the skill actually runs.
Verification of the rewritten skill (1 Haiku agent, 3 reports, blind): all files valid, advocates' tags accepted, no factor rejected. It found four gaps, now fixed: `[BASELINE]` / `[FIXTURE]` (what the engine already
priced) are enforced by the engine (a factor citing them is rejected; advocates may still cite them to explain the odds), the draw-lens flags (heavy favourite, low-scoring, toss-up) are documented, the verdict for
a report without odds is `unclear` ("no odds, challenge not possible"), and `weak_model` is explained (only when the trained model does not know the teams; then factors <= +-2 and confidence <= 0.4).

## Why draws are not "got" (research/draw_signal_hunt.py)
No hidden bias: draw is the model's 2nd most likely outcome in 84% of matches (most likely only 68 of 8,054), draws are only 3.9 points more predictable than non-draws (26.0% vs 22.1% mean predicted draw probability),
and 32 extra pre-match features (linear and gradient boosting) do not improve the draw forecast out of sample (AUC 0.642 -> 0.637). Top-2 coverage 84% (80% for draws). Live: 13 draws, 9 were the 2nd most likely outcome, 4 the least likely.

## Lineup and availability (built, not promoted)
Plan: `research/LINEUP_NEWS_PLAN.md`. Built: `football/oracle/lineup.py` (absentees classified starter/rotation/fringe/unknown from recent minutes), six audit flags
(`xi_overlap`, `missing_in_xi`, `injured_in_xi`, `xi_not_in_squad`, `empty_absentee_list`, `heavy_rotation`), an `[H|A.availability]` brief tag, skill text in both copies.
On the 38 live reports the flags fire on 17 (mostly `xi_not_in_squad` and `heavy_rotation`; one clear data error: Somalia v Côte d'Ivoire has a missing player in the XI).
Engine effect: none. `ABSENCE_APPLY_SCALE` stays 0.0: promotion needs pre-match historical lineups for a back-test (source not chosen), gate in the plan, section 5.

### Forward test of the absence adjustment (no historical lineups exist)
`--log` on the baseline command appends, per live match, the engine probabilities with absences OFF (used) and ON (counterfactual) to `output/oracle-forward-log.jsonl`
(`football/oracle/forward_log.py`). Score with `python -m football.oracle.forward_log score results.csv` (martj42 layout). Paired Brier and log-loss difference with a bootstrap interval,
on matches where the two differ by >= 0.5 points; the gate needs 300 such matches and an interval below zero on both metrics, then a fresh-batch confirmation. Until then: OFF.

## Draw-identification techniques from the literature (tested 2026-10-04; no change to the engine)
Searched: diagonal-inflated bivariate Poisson (Karlis & Ntzoufras 2009), ordered probit/logit thresholds, Elo-closeness, Bayesian-network draw classifiers. Scripts: `draw_techniques.py`, `draw_bivariate_check.py`.
Fit on 2018-23, scored on 2024-26 (2,652 matches): diagonal inflation fits at w = 0 (draws already calibrated: 23.0% predicted, 23.6% actual); a draw boost that grows as the sides get closer fits at 0;
bivariate Poisson with a shared goal component (c = 0.1) gains 0.0012 log-loss on 2024-26 (interval -0.0025 to +0.0001) but is NOT consistent: -0.0010 (2018-21), +0.0008 (2022-23), -0.0012 (2024-26),
it only raises the draw level by ~0.4-1 point, and draw AUC is unchanged (0.643). It fails the gate (positive in every period, |z| >= 3.3 after several variants), so it is not adopted.
Literature agrees: diagonal inflation improves draw counts but not overall accuracy; models capture strength direction, not draw likelihood; closeness in rating is the main draw feature and the engine already uses it.

## Recommended bet on the 38 live matches (all 38 run through the skill with the audit loop, 2026-10-04)
The most likely selection among 1X2 / Over-Under 2.5 / BTTS hit 18 of 38 (47%) against 63% quoted (held-out 68.2%). By market: 1X2 9/17, Under 2.5 5/13, BTTS Yes 4/8.
The live set had 13 draws (34%) and 2.87 goals per match against 2.62 expected: both are within chance, and 38 matches cannot justify retuning. Agent adjustments changed none of the 38 recommended bets.
Process: 38/38 answers audit with 0 FAIL rows (5 WARN lines left, justified by the agents). The audit tool had two bugs found by agents' persistent failures (own-side absence check read past the Case line; headline parsed from the first line only), both fixed.

## Why the misses happened, and the goal-market shrink (2026-10-04)
Of the 20 missed recommended bets: 9 were draws (6 of them 1X2 bets, plus Greece-Netherlands and Ireland-Austria 2-2 on Under, Israel-Kosovo 0-0 on BTTS), 8 Under 2.5 bets had 3+ goals (5 had 4+), 2 were upsets (Ghana-Gambia, Kazakhstan-Moldova), 4 BTTS bets had a scoreless side or 0-0.
Only 1 miss gave the real result under 15% (Ghana-Gambia 14%); in 10 the engine gave it 25%+, and the bookmaker was equally wrong on the 1X2 in most. On the 13 Under bets the engine expected 2.31 goals and 3.08 were scored.
Held-out check (`under_check.py`): the Under tail IS overconfident: predicted total < 2.0 -> 1.84 expected vs 2.10 actual, Under quoted 72% vs 63% actual; quoted 70%+ happened 64% of the time.
Fix (adopted, goal markets only): pull the total goal rate 20% toward the training mean 2.676 (same factor on both sides). Pooled over 8,054 matches: Over/Under log-loss -0.0025 (z = -3.6), BTTS -0.0026 (z = -5.5), 1X2 +0.0001 (z = +0.5); same sign in all three periods; recommended-bet hit rate unchanged (68.2%) but better calibrated (Under quoted 61.0 vs hit 61.2). Scripts: `total_shrink.py`, `total_shrink_pooled.py`, `reco_after_shrink.py`.

## BTTS shrink and tooling added from past interactions (2026-10-05)
BTTS with a stronger total-goal shrink (k = 0.4 instead of 0.2): pooled log-loss -0.0009 (z = -2.0), same sign in all periods, below the |z| >= 3.3 gate: not adopted (`btts_shrink.py`). Remaining weakness: BTTS Yes quoted >= 55% happened 54.6% of the time (59.9% quoted): those bets are near coin flips.
Added because the same questions kept coming up: `oracle score <folder> --results csv` (token-free scorecard with miss causes), a plain-words line in every draft, `draft`, `lint`, `audit`, `--table`.

## Goal-rate overdispersion vs the shrink (2026-10-05, tested while unattended)
Averaging the goal markets over a lognormal scale on both rates (7-point quadrature, s = 0.10-0.25, with and without a small shrink) is WORSE than the simple shrink in use (k = 0.2): pooled over 8,054 matches, best mixture (s = 0.15 + shrink 0.1) vs shrink: Over/Under +0.0006 (z = +2.1), BTTS +0.0010 (z = +3.9), 1X2 unchanged, same sign in all three periods. Kept: the shrink (`goal_mixture.py`).

## Independence rule (2026-10-05)
The earlier "odds disagree" caution (one strength level lower) was removed: the model must not rely on the odds. Bets, strength and cautions are the same with or without odds (test-pinned); the gap to the odds is a printed benchmark only. Context: on 36 live fixtures the odds beat the independent engine (Brier 0.574 vs 0.589) and won 17 of 20 big disagreements, so independence has a measurable cost that we accept by choice.

## Goals bets need 60%; double chance fallback (2026-10-05, user rule: no BTTS / Over-Under recommendations in the 50s)
Held-out 8,054 matches (`reco_min_goals.py`, `reco_dc_bands.py`): "most likely of everything" hit 68.2%; goals bets only from 60% with the 1X2 pick as fallback hit 65.1% (the matches that lose their goals bet get a 1X2 pick of mean probability 45.7% that hits 44.7%, worse than the 56.7% of the 50s goals bets); goals bets from 60% plus the better double chance when no outcome reaches 50% hit 72.8% (quoted 71.7%): mix 55% 1X2 / 36% double chance / 10% goals; double chance by band 65-70% 64.8, 70-75% 73.2, 75-80% 78.7, 80-90% 86.5.
Replayed on the first 38 live matches (token-free `oracle score`): 22 of 38 (58%) vs 17 with the previous rule; double chances 12 of 17, 1X2 picks 9 of 20 (13 draws). The rule was set on the held-out data, not tuned on the 38.

## 2026-10-05: online research on draws, draw routes in the skill, stronger advocates
- Published methods (Dixon-Coles diagonal inflation, xG/Skellam, low-xG flags, neural nets on shot data): all already in the engine, already rejected here, or need data we lack. Draws stay the hardest class (about 40% at best with shot-level data).
- Post-match reports of the 13 live draws: late equaliser/comeback after a lead 5, dominant side vs deep low-xG defence 4, deflection/own goal/disallowed goal 3. Mostly in-match events; written into the skill's draw doctrine as a reading aid, not a predictor.
- Results fix: France v Italy was 1-1 (our file said 0-0); scorecard now skips non-report JSON files.
- Advocates: brief prints a "How to argue" kit (LEAD with the two best points, SCENARIO, REBUT the opponent's best, CONCEDE the weak spot); lint rejects a case with fewer than two of its side's dossier points or under 15 words; the odds track-record line is no longer printed in the brief.

## 2026-10-05: psychology, "bounce back after losing form" (research/bounce_back.py)
Held-out internationals (8,054 matches, team form built from the same rows, >= 5 prior matches). Points per game vs the model: lost last match -0.033 (z -2.35, n 5,689); lost last 2 -0.058 (z -2.82); lost last 3 -0.066 (z -2.43); no win in 4 -0.044; lost last by 3+ goals -0.071 (z -2.79); won last 3 +0.023 (z +0.7). Goals vs expected about zero. Same sign in every period but |z| < 3.3. Verdict: no bounce-back effect, no adjustment; the idea is context only. The audit now fails predictive bounce-back / hungry / desperate language, and the dossier adds a context line for sides on a losing run.

## 2026-10-05: fix-all loop (author agent, audit, separate reviewer), 5 rounds on Cyprus v Latvia
Rounds 1-3 (free-text judgement by a Haiku author): every answer passed the audit yet carried 1-8 new reasoning errors (xG read backwards, verdict contradicting its text, "heavy rotation" for 5 changes, numbers under the wrong tag, invented tactics, "may/could" consequences, causes given for the odds gap). Each round added checks to the audit (now ~25 patterns plus tag/number matching) but new kinds kept appearing, so the loop did not converge. Reviewer recall on known errors: 3/6, 4/5, 1/6, 2/8.
Change of approach (round 4): `compose` builds case_home, case_away, weak_points, odds_challenge, why, vs_odds, risks and data_note from the tagged dossier and the engine's numbers (draft.auto_judgement); the agent may override any key. Token-free harness (/tmp/auto_all.py pattern): all 26 real reports compose and pass the audit with 0 failures and 0 warnings. Bugs it exposed: dossier cited absentee tags beyond the brief's 8-absentee cap, absentee check merged lines, dossier text contained "probably price them", odds_right wording contradicted its own sentence. Round 5 reviewer findings were format-only (scenario sentence, concession detail); checklist aligned. 2189 tests pass.

## 2026-10-05: loop continued (rounds 6-7, Wales and Iceland)
Round 6: an agent told to "override only if needed" rewrote all 7 judgement lines and reported "no overrides"; the answer passed the audit yet had an invented number (home edge "adds 1.5 points"), ungrounded general claims, causes for the odds, characterising words. Fix: the command-line `compose` now IGNORES free text (only an optional `analyst_note`, 60 words, labelled and audited; `--free-text` restores the old behaviour); audit gains modal-verb, general-truth and unsigned-decimal checks. Round 7 (Iceland): the agent used `{}`; audit clean; my read and the reviewer found builder bugs only (top-of-table treated as a weak spot, "role unknown, unknown" label, no rebuttal fallback), all fixed in draft.auto_judgement. 26 real reports: 0 audit failures, 0 warnings. 2190 tests pass.

## 2026-10-05: reviewer sentence table, end-to-end run on Ukraine v Hungary
Review packs now end with a SENTENCE TABLE (each author sentence + the brief lines of the tags it cites). Reviewer recall on answers with known errors: 5/5 and 3/6 (before the table 3/6, 4/5, 1/6, 2/8), no false alarms. Misses turned into audit checks (control/possession/scepticism words, absentee tag, odds direction). Fresh agent on Ukraine (used `{}` plus a 2-sentence analyst note): audit clean, my read clean, reviewer found one real builder bug (winning scores taken from the top 6 while the Goals line shows 4); fixed and audited ("scores quoted in the judgement lines are the Goals line's own"). 2194 tests pass; 26 real reports 0 audit failures.

## 2026-10-05: weakness hunt (token-free sweep of the 26 reports)
Invariants hold on all 26 (probabilities sum to 100, double chance = sum, no 1X2 bet under 50%, no goals bet under 60%). Findings: (1) the scraper adds penalty-shootout goals to the scoreline of a match decided on penalties (England v France 6-4 with equal xG 2.88; Azerbaijan v Sierra Leone 10-9; Czechia v Ireland 6-5, Germany v Paraguay 4-5, Latvia v Lithuania 5-6): about 10 distinct rows, 19 of 26 reports carried an "implausible score" warning. Now read as a draw with ignored goals (facts._shootout_like; qualifier scores such as Italy 5-4 Israel stay). (2) 13 of 26 matches have 3+ absentees outside the squad list (England 7): their impact cannot be weighed, and the absence adjustment is off anyway. (3) Sweden has 11 absentees, only 8 are tagged. (4) Romania v Sweden: engine differs from the odds by 20 points. (5) Results file had France-Italy wrong; the other 37 scores are unverified. 2195 tests pass.

## 2026-10-05: fix-all pass after the weakness hunt
- Results file: the other 37 scores were checked against ESPN and others by two researcher agents; one more error found and confirmed by a second search (Czechia 0-2 England, our file had 0-5). Only France-Italy (1-1) and this one were wrong; both are fixed. 1X2 and double-chance scoring are unaffected.
- Threshold check out of sample (research/reco_split.py): chosen before 2024, measured from 2024 on, the current rule hits 72.4% (72.8% on all data); old rule 68.6%; 1X2 only 61.0%. A train-selected variant (goals >= 70%, double chance below 55%) reaches 74.7% but adds more double chances; thresholds left as they are.
- The 8-absentee tag cap is now 30 (debate.MAX_ABSENTEES) so every listed absentee is tagged.
- A gap of 10+ points to the odds adds a benchmark-only note to the answer (changes nothing in forecast, bet or cautions; test pinned).
- Not fixable from the data: unknown-role absentees (87 across the 26 reports; 28 appear elsewhere only as old head-to-head lineups, which would misclassify current players), draws, and the forward test sample (about 28 of 300). 2196 tests pass.

## 2026-10-05: unknown absentees and the forward test
- Correction: an earlier count said 83 of 87 unknown absentees were identified by the injury lists; that counted entries with no role or value. Real coverage was 12 of 87. Two research agents then looked up the position of the other 57 distinct players on the web; positions only are stored (football/oracle/player_roles.json, dated 2026-10-05, display only, no probability changes); their starter flags were unreliable (Stones and Rashford "no") and are NOT stored. Now 87 of 87 absentees have a position; `oracle roles <report|folder>` lists new ones to look up. Starter status stays unknown.
- Forward test: all 26 current reports logged token-free (`oracle output --llm none --log`): 65 records, 62 usable pre-kickoff, against about 300 needed; only time and results can close this. 2198 tests pass.

## 2026-10-05: forums and prototypes search (draws, absences)
Draws: every technique people report (Dixon-Coles tau, bivariate Poisson, ordered logit/probit, Skellam, threshold tuning, class weighting, boosting/stacking, draw-propensity features) was already in the engine or already tested here with no out-of-sample gain; best reported draw accuracy about 37-40%, no validated international result. Absences: practitioner methods (market-value share, XI Elo shift, Bayesian playing-time priors, minutes-denominator Poisson, confirmed-XI re-forecast, replacement-quality interaction) are within-sample or unvalidated; all insist on chronological out-of-sample validation, which is our forward test. Added a descriptive per-tier breakdown (confirmed vs predicted lineup, a starter out or not) to the forward-test output. 2199 tests pass.

## 2026-10-05: analysis of the 16 misses among 38 live matches (reco_dc_trigger.py, recent_drift.py, reco_draw_flag.py)
12 of 16 misses were draws (13 draws in 38; model expected 9.2, chance of 13+ about 10%), 4 were upsets. Home wins 10 vs 14.7 expected (z -1.7), bets hit 22 vs 26.4 implied (z -1.6): nothing significant. Held-out by year the model is calibrated through 2025-26 (home 472/470 non-neutral). Draw flags at the time: ALERT 4 matches 2 draws, WATCH 7 matches 2 draws, no flag 27 matches 9 draws. The only lever that lowers misses is the double-chance trigger: held-out 2024+ hit rate 72.4% at T=50% (current), 74.8% at 55%, 77.4% at 60%, 81.3% at 70%, 84.4% always double chance; quoted probability tracks the hit rate (honest) but a double chance pays less than a single outcome. Live 38: 22 / 24 / 26 / 28 hits at T=50 / 55 / 60 / 70%. No change made: the trigger is a risk-versus-price choice, not a model fault.

## 2026-10-05: double-chance trigger set to 60% (user's choice)
DOUBLE_CHANCE_BELOW_PCT 50 -> 60: the better double chance is recommended whenever no single outcome reaches 60%. Held-out 8,054: hit 77.7% (quoted 76.3%), 55% of bets are double chances (before: 72.8%, 36%); live 38 replay would be 26 hits of 38 (before 22). Trade-off: a double chance pays less than a single outcome. Goals bets still need 60%. Skill text and tests updated; 2199 tests pass. Of the 26 current reports 5 keep a single-outcome bet.

## 2026-10-05: bug hunt (fuzz of 6 real reports with ~1,500 corruptions, property tests, static lint, garbage-file CLI run)
Fixed: (1) numeric fields holding text/None crashed every command (dataCompleteness.populated, rest days, xG sample size): facts.as_number; (2) wrong-typed sections (standing, stakes, rotation, odds, squad, lineup names, form fields, recent meetings, missing-player entries): facts._sanitize/_dict and per-field guards; (3) unparseable reports now give "No prediction: the report could not be analysed" (oracle.predict/brief wrappers) and a plain message from the CLI instead of a traceback; lint on a non-object report; (4) forward test compared timestamps as text, so a report generated after kickoff could count as pre-kickoff when offsets differed (leak): now parsed as UTC datetimes; (5) forward test and scorecard silently skipped fixtures the results file lists the other way round: now settled with home/away swapped; (6) audit xG-direction regex was quadratic: 296 s on one 219k-character sentence, now 0.7 s; (7) unused imports. Checked and clean: 4,000 random bet-rule cases (0 violations), 500 probability grids, form rows newest-first on all 26 reports, deterministic output. 2204 tests pass.

## 2026-10-06: first club test (9 Premier League reports, 8 played 5-6 Sep 2026, scored token-free)
weak_model on all (the trained goals model covers national teams only): bets hit 3 of 8 (quoted ~75%), 1X2 pick right 2 of 8, five draws against 1.9 expected, Brier engine 0.792 vs odds 0.670 vs guessing 0.667. Overclaim fixed: answers for weak_model matches no longer quote the national-team held-out hit rate or a calibrated confidence ("no validated hit rate for these teams"). Results from ESPN via a research agent; Hull 0-0 Aston Villa and Newcastle 2-2 Bournemouth confirmed by a second search. Club model stays paused: it needs club ratings and club history that the repo does not have.

## 2026-10-06: draws kept failing, so the recommended double chance now always covers the draw
Live (61 settled matches, 38 + 23): 11 of 15 misses were draws, and the bet "either side to win (no draw)" lost on every one of them. research/reco_no_either.py (held-out 8,054): removing "either side to win" leaves the hit rate unchanged (77.7% to 77.5% overall, 77.4% to 77.6% from 2024) and cuts draws among the misses from 860 to 511 (2024 on: 300 to 179). On the live 61: 46 to 48 hits, draw misses 11 to 4. Engine and the lite calculator never recommend it now; the analyst skill gets a draw lens (signals that raise or lower the draw against the 23-25% base rate), a draw-cover rule (a single outcome below 60% with the draw at 25%+ needs a double chance or a "Draw cover:" line) and checker enforcement.

## 2026-10-09: neutral-venue draw lead re-tested (research/neutral_draw.py, 8,054 held-out matches)
Neutral matches with a 45-55% favourite: 34.1% drawn v 27.6% expected (n=566, z +3.44), the same flag as before. By year (fav 40-60%, neutral): positive in 7 of 8 sized years but small (z -0.57 to +0.89, only 2024 at +2.42), 2018 negative, so it fails the "positive in every period" gate; non-neutral level matches are on the model (30.0% v 28.0%, z +1.5). Low-total slices are on the model too (total under 2.2: 31.2% v 30.6%). Even at 34% a draw never becomes the likeliest outcome, so a flag would change nothing the draw cover does not already do. Not adopted; no probability change.

## 2026-10-09: favourite-longshot correction of the market prices (research/flb_test.py; 39,295 matches, 18 leagues, 2019-25, average odds)
Logit stretch p' = sigmoid(0.0508 + 1.0777 x logit(p)) fitted on 2019-22 (21,502), tested on 2022-25 (17,793): Brier 0.59208 -> 0.59167 (diff -0.00041, 95% CI [-0.00067, -0.00014]), log loss 0.99162 -> 0.99082, RPS 0.20138 -> 0.20117.
Test bins (market -> actual): under 10% 7.4 -> 4.2; 10-20% 15.9 -> 14.3; 50-70% 57.9 -> 60.0; 70%+ 76.8 -> 81.9. By season: worse in 2019-20 (+0.00023), better in the other five; by league: mixed (Premier League +0.00002, Bundesliga +0.00066, Portugal -0.00117).
Gate (positive in every period) not met and the gain is tiny, so the anchor stays the plain market; `calc.py --market` prints the corrected prices as a reference line for judging edges on heavy favourites and longshots. The old rule that favourites are "the most over-bet outcomes" is not supported by these prices: favourites win MORE often than priced.

## 2026-10-10: outside-view base rates and run ensembles tested, neither adopted (research/baserate_test.py)
Base rates by competition type and neutral flag (fitted on 5,402 internationals to 2023, tested on 2,652 from 2024): Brier 0.6333 against 0.6359 for one global constant and 0.4946 for the history model (log loss 1.0514 / 1.0541 / 0.8432). Category priors carry almost nothing; team strength carries the information. Not added to the sheet.
Ensemble of repeated analyst runs (16 matches with 2+ saved answer versions from different code versions, so confounded): individual answers Brier 0.4486, median of versions 0.4515, mean 0.4470, market 0.4003; the versions differ by 5 points on the home probability on average. No gain from the median or the mean, so `--ensemble` was not built. The market anchor does the work.
