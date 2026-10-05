# Which skill rule is enforced how (2026-10-05)

The skill (`.claude/skills/football-match-analyst/SKILL.md`) states rules; agents (Haiku) repeatedly broke the ones nothing enforced. This table says what enforces each rule now.
**By construction** = the agent cannot break it (`compose` writes the line from the engine). **Audit / lint** = a tool fails or warns. **Judgement** = only a human can check.

| Rule | Enforced by |
|---|---|
| Never change a number by hand | By construction: `compose` writes headline, plain words, recommended bet, draw lens, goals, lineups and the numbers of "Own model vs odds" from the engine; audit also compares them word for word |
| Recommended bet and its cautions copied unchanged | By construction + audit (selection, probability, whole line) |
| Plain-words line kept as drafted | By construction + audit |
| Draw flag called a risk hint; knockout = level after 120 minutes; weak model = rough lean | By construction (draft adds the notes) + audit (lines kept) |
| Every audit finding reported; unconfirmed lineups and unknown absentees named | By construction (Data audit and Lineups lines list them) |
| Independence: odds never change a forecast, bet, strength or caution | Engine test (same report with any odds gives the same output); audit bans citing the odds' track record |
| No staking advice, no guarantees, no "we predict a draw" | Audit (banned claims) |
| A side's own absence not in its own Case line | Audit (FAIL) |
| "Unmodelled by the engine, priced by the odds"; never "unpriced by the odds" / "priced into Elo" | Audit (banned claims) |
| Facts only from tag lines: scorelines, form counts, form adjectives, H2H with n, managers, "missing" players, point gaps, characterising words | Audit (FAIL for wrong scores and counts; WARN for the rest) |
| One tag per bracket, tags exist, no `[WRITE ...]` left | Audit |
| Opinion: same-effect numbers, ONE tag per factor, priced tags and weak absentees rejected, bounds, draw bias only for draw context, absentee <= +-3, weak_model <= +-2 and confidence <= 0.4 | Engine validator + `lint` |
| Advocates: all three, cite tags, valid verdict, <= 90 words | `lint` |
| Lint clean before applying; audit clean before replying | Skill order; `compose` + `audit` commands (a judgement file is the only input) |
| Quality of the reasoning; "Case for" holds only evidence FOR that side beyond absence tags; advocates really steelman; unknown facts about players invented without a pattern the audit knows | **Judgement only: not enforced** |

Measured on 4 recent agent answers before this change: 4 of 4 changed a draft line (usually the Data audit line), 3 of 4 cited the odds' track record.

First run of the compose flow (Belgium v France, Haiku agent): 0 engine lines changed, final audit clean, but the agent fixed its audit findings by hand-editing answer.md instead of the judgement file (the skill now says to edit judgement.json and re-run compose). Cost 92,700 tokens for a single match, the same as before: compose removes errors, not cost.

## Inconsistencies found and fixed on 2026-10-05 (the same word or number meaning two things)
| Inconsistency | Fix |
|---|---|
| Head-to-head counts judged as recent form (Belgium v France: "won 7 of the last 10" about meetings failed against the form letters) | Audit: a sentence about meetings is checked against the H2H record (home, draws, away, n); form counts against the form letters of the side whose tag is cited |
| Venue claims about past meetings ("on the road") | The H2H counts are per fixture team, not per stadium (report.py documents this): audit warns |
| H2H orientation (home = the fixture's home team?) | Verified in 19 of 19 testable reports (none flipped, 9 of them for away-side reports); skill says so |
| Source summary smaller than the meetings listed in the same report | New audit finding `h2h_conflict` (1 of 39 reports: Spain v Croatia, summary 0 draws but a draw is listed) |
| Two hit rates for one 1X2 pick (headline 70.9% vs bet line 66.2%); mixed-market band flattered goal bets (75-80% quoted, 72.5% real) | A 1X2 bet quotes the headline's calibrated chance; goal bets a flatter table (research/reco_bands_by_kind.py) |
| "Toss-up" in the plain words for any <45% favourite, but a strict definition in the draw lens (gap < 5 and draw >= 28%) | Plain words says "toss-up" only when the draw lens does; otherwise "No side is a clear favourite" |
| Skill: "never adjust for heavy rotation" yet any rotation factor allowed | Skill and lint: a factor citing a heavy-rotation tag (8+ changes) is rejected |
| Lineups line listed starters only, though every absentee must be classified | Draft adds "other absentees: name (rotation/fringe)" |
| Lint looked for a `[WEATHER]` tag that never existed (weather is inside `[VENUE]`) | Fixed; skill lists the tags that carry each kind of evidence |
| Skill template, draft and audit could drift apart; skill could name tags the code never prints | Tests: template labels = draft lines = audit REQUIRED; every tag the skill names is producible; lint's tags are real |
