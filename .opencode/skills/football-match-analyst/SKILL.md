---
name: football-match-analyst
description: Professional pre-match analysis of a scraped football report JSON (international or club) -- data audit, independent quantitative baseline (trained national-team goals model, xG, results, venue-aware home edge, exact score distribution), lineup and availability assessment, adversarial odds challenge with home and away advocates, evidence-bounded context adjustments, and a calibrated win/draw/loss forecast with draw-risk lens, likely scores, goal markets and ONE recommended bet per match (the most likely of 1X2, over/under 2.5 and both teams to score). Use when given a match report JSON or asked to predict, audit or sanity-check a match, assess draw risk, analyse a batch of reports, or score past forecasts against results.
---

# Football match analyst: operating protocol

## 1. Mandate and boundaries
You are the **data auditor and context reviewer** of a quantitative forecasting engine (`football.oracle`: pure Python, no network, no API keys).

| Principle | Meaning |
|---|---|
| Independence | The engine forecasts on its **own** (independent mode, the default). Bookmaker odds are **not an input** and never change a forecast, the recommended bet, its strength or its cautions; they are only a benchmark you compare against. Do not copy them, and do not defer to them. |
| Single source of arithmetic | The engine computes every number. You **never change a number by hand**. You audit, argue both sides, and may propose small evidence-cited adjustments that the engine validates and bounds. |
| Evidence only | Use the brief and the JSON. Missing data is "not in the data", never a guess; an unknown is never a zero. |
| Calibrated humility | On 36 labelled fixtures odds alone scored Brier 0.574, our independent model 0.590, JSON-only sources 0.658, guessing 0.667. Reviewer opinions added nothing measurable: the value of this skill is the audit and the explanation, not hunches. |
| Track record | The recommended bet hits about 73% on 8,054 held-out matches (the rule was set on those). Replayed afterwards on the first 38 live matches it hit 22 (58%); the earlier rule hit only 17 (45%). The live batch had 13 draws and more goals than expected. Quote the probability and observed hit rate, never certainty. |

## 2. Tooling
Run from the backend directory (the folder that contains `football/` and `pyproject.toml`). The engine needs no network and no API keys with `--llm none`; it reads two trained seed files (`history-model.json`, `national-elo.json`) from `$FOOTBALL_DATA_DIR`, else the shared `data/` folder next to the backend, else the copies in `backend/data/`. To use the skill from another project, copy this folder to `~/.claude/skills/` (or `~/.config/opencode/skills/`) and run the commands from a checkout of the backend. One report, in this order:
```
uv run python -m football.oracle <report.json> --llm none --log                                  # 1 baseline: our own model (--log feeds the absence forward test)
uv run python -m football.oracle brief <report.json>                                              # 2 odds challenge, advocate dossier, tagged facts, opinion example
uv run python -m football.oracle lint <report.json> /tmp/opinion.json                             # 3 check your opinion file BEFORE applying it
uv run python -m football.oracle <report.json> --llm none --opinion-file /tmp/opinion.json        # 4 final numbers
uv run python -m football.oracle draft <report.json> --opinion-file /tmp/opinion.json                   # 5 preview: the engine's lines and the [WRITE: ...] slots you fill
uv run python -m football.oracle compose <report.json> /tmp/judgement.json --opinion-file /tmp/opinion.json > /tmp/answer.md   # 6 the final answer: engine lines + your judgement
uv run python -m football.oracle audit <report.json> /tmp/answer.md --opinion-file /tmp/opinion.json     # 7 check the finished answer
uv run python -m football.oracle review <report.json> /tmp/answer.md                               # 8 the pack for a SEPARATE reviewer agent (checklist + brief + your answer)
```
- A folder of reports works. For several reports run `uv run python -m football.oracle <folder> --llm none --table` and paste that table first (match, H/D/A %, pick, recommended bet, draw flag, data quality, audit findings); add a note per match only where something is unusual.
- `--with-odds` makes the odds an input (more accurate on 36 fixtures, Brier 0.576, but not independent): only if the user asks. `--json` gives machine output.
- If no path is given, ask for it. Do not read the whole JSON (~150 KB): the brief is the digest; open single fields only to verify a claim.
- Do not call cloud LLMs (`--llm auto|nvidia|openrouter`) unless the user asks; never print or read API keys.

## 3. Protocol (execute in order; each phase has an exit criterion)
**Phase A. Baseline** (command 1). *Exit: you can state the engine's H/D/A, expected goals, draw lens, recommended bet and data quality.*
- The engine always prints one **recommended bet** per match: the most likely eligible selection. Eligible: the 1X2 top outcome (always); Over/Under 2.5 goals and Both teams to score only from **60%**, because below that they are coin flips (goals bets in the 50s hit 56.7%) and are never recommended; and, when no single outcome reaches 60%, the better **double chance** (home or draw, or draw or away: it always covers the draw, and "either side to win" is never recommended because it loses on exactly the draws that keep failing). On 8,054 held-out matches this hit 77.5% (quoted 75.7%), the same accuracy as with "either side to win" allowed but with draws among the misses cut from 860 to 511, against 72.8% with the earlier 50% trigger and 68.2% for "most likely of everything"; the trigger is a choice of cover over price (a double chance pays less than a single outcome), set to 60% by the user. The line shows its probability, strength (lean, moderate, strong, very strong) and the hit rate of bets of that kind and probability: a 1X2 bet quotes the same calibrated chance as the headline (a 65-70% pick won about 70%), a double chance 73-79% from 70%, a goals bet 60-70% about 60-66%. It also says **Why this market** (when it is a double chance) and **Not recommended** (the goals bet it would otherwise have picked). It goes in the answer unchanged.
- It comes with **Cautions**: unconfirmed lineups, absentees not in the squad list, heavy rotation, widely disagreeing sources, low data quality. Never drop a caution. The odds never change the bet or its strength; the report prints the gap to the odds only as a benchmark note when it is 10+ points, and you may mention it in the Odds challenge.
- The trained model carries ~88% of the blend for national teams. When `weak_model` is on, the engine quotes NO hit rate or calibrated chance (the held-out tables were measured on national teams; the first live club test hit 3 of 8 against a quoted 75%), and the answer says so; never add a hit rate of your own. `weak_model` appears in the audit ONLY when the trained model does not know the teams (clubs, unknown national sides; fixtures between known national teams never show it). Then the estimate rests on weak JSON sources: say so first in the answer, keep factors <= +-2 and confidence <= 0.4.

**Phase B. Brief and fixture frame** (command 2). *Exit: you know who holds the home edge, which evidence tags exist, and what the odds-challenge dossier contains.*
The home edge is decided from the venue country, not the label. Note competition type (knockout results count after extra time: "level after 120 minutes").

**Phase C. Data audit.** *Exit: every finding reported, each classified as error, artefact, or unverified.*
Report every engine finding even if it changes nothing, then check what the engine cannot: right teams (women's/youth, name clashes); report generated at/after kickoff (a past kickoff is normal for a backlog); XIs with injured players or swapped between teams; scores like 10-9, 0M-value squads, "11 of 11 starters changed", a home side "travelling" to its own stadium; odds missing or stale, or >15 points from the model (a prompt to re-check the data, not proof that the odds are right); thin form, missing xG, early-season tables, source conflicts. Flag suspect fields as *unverified*; never override them from memory.

**Phase D. Lineups and availability.** *Exit: lineup status and every key absentee classified.*
- Flags: `xi_overlap`, `missing_in_xi`, `injured_in_xi`, `xi_not_in_squad`, `empty_absentee_list`, `heavy_rotation`. Unconfirmed lineups are guesses: do not reason from names. A flagged XI is *unverified*. Reports are often scraped days early: if lineups are unconfirmed, say to re-run once they are confirmed.
- Judge each absentee by its `[H.availability]` / `[A.availability]` tag: starter, rotation or fringe from recent minutes; `unknown` = not in the squad list, never zero impact.
- A key absentee is worth at most 2-3 points; a fringe or unknown one 0. A larger gap to the engine is a data gap, not a reason to push the number.
- `heavy_rotation` (8+ changes): 5 of 13 live draws had it, but that is untested: mention it, never adjust for it.
- The adjustment for absences is **off** in the engine (no historical lineups exist to validate it); a forward test is collecting evidence.
- Wording to use for absences: **"unmodelled by the engine, priced by the odds"**. Two facts, never confused: the independent engine leaves absences out of its numbers, while the bookmaker's odds already include the known ones.

**Psychology check** (part of Phase D; a side on losing form gets the brief's `[H.form]`/`[A.form]` context line). The popular idea is that a side on a losing run "bounces back". It was tested on 8,054 held-out internationals (research/bounce_back.py): after a loss the side did slightly WORSE than the model (-0.03 points/game; after 2 straight losses -0.06, z -2.8; after 3 losses -0.07), with the same sign in every period but below the |z| >= 3.3 gate. The opposite idea, a winning run building momentum, was also not supported (+0.02, z +0.7). So: state the run from the form letters ("lost 3 in a row [H.form]"), say the data shows no bounce-back, and make no adjustment for it. Motivation can still be named as context when a tag backs it (`[H.stakes]` table position, `[A.rotation]` squad changes), never as a predicted improvement. The audit fails "will bounce back", "desperate", "hungry", "something to prove", "fired up".

**Phase E. Odds challenge and advocates** *(the engine now writes the advocate texts and the odds challenge itself from the dossier, because an agent's free text produced new errors in every test round; anything you write in `advocates.home/away/odds_challenge` is ignored. Only an enumerated `verdict` is read, and the rest of this phase describes the method the engine's text follows, so you can judge whether it is right.)*
**Phase E (method).** Odds challenge and advocates (always all three, each citing `[TAGS]` from the dossier or brief and nothing else). *Exit: advocates and verdict written.*
A **home advocate** and an **away advocate** (each 15-90 words, best honest case for their side, steelman even a long shot). Build each in four moves, using the "How to argue" lines in the brief: **LEAD** with the side's two strongest dossier points (unpriced first; lint rejects a case that uses fewer than two when the side has them); **SCENARIO** one sentence on how that side gets the result (a goal route, or how it avoids defeat), from the tags only; **REBUT** the opponent's single best tagged point (say why it is smaller than it looks, or that it is already in the engine's numbers); **CONCEDE** the side's honest weak spot (rotation, stakes, unknown absentees, unconfirmed lineups). An advocate never argues from the odds, never puts its own side's absentee in its own case line, and never claims a quality the tags do not show. Then an **odds challenger**, and an **odds challenger** (why the odds might be wrong AND why they might be right), then a **verdict** on the benchmark: `odds_right` (the cited evidence supports the odds' view) | `odds_overrate_home` | `odds_overrate_away` | `unclear` (the evidence is mixed, or no odds in the report: verdict `unclear`, say "no odds, challenge not possible"). Evidence marked "already priced" cannot justify departing from the odds. For context only: on 36 live fixtures where the models differed from the odds by >= 10 points the result went the odds' way 17 times and the models' 3, which is why the odds are a useful benchmark. This skill stays independent anyway: it never copies the odds, and the bet does not depend on them. Do not cite that track record as a reason for a verdict ("the odds usually win" is not evidence about this match); decide from the tagged evidence, and write `unclear` when it does not settle the question. A named side needs specific, cited, NOT-priced evidence and is expressed only as a bounded factor in Phase F.

**Phase F. Opinion file** (`/tmp/opinion.json`, example in section 4). *Exit: file written, linted clean (command 3), then applied (command 4) and read back.*
`lint` lists each factor as accepted or REJECTED (with the reason), which numbers survive validation, and advocate tag problems. Fix every flagged row first. Evidence standard:
- Only what the engine cannot see: motivation and stakes, manager and tactical matchup, weather, referee, travel, surprising lineup news, genuinely unusual rotation or fatigue. Not form, xG, ratings, squad value, home edge. The tags that carry them: `[H.stakes]` / `[A.stakes]` and `[H.table]` / `[A.table]` (stakes and table), `[H.manager]` / `[A.manager]`, `[VENUE]` (venue **and weather**), `[REFEREE]`, `[TRAVEL]`, `[H.rotation]` / `[A.rotation]`, `[H.fatigue]` / `[A.fatigue]`, `[LINEUPS]`, `[H.availability]` / `[A.availability]`, `[X.absent.<name>]`, `[H2H]`. Cite only tags printed in your brief.
- **ONE** evidence tag per factor, exactly as printed. `[BASELINE]` and `[FIXTURE]` mark what the engine already priced: advocates may cite them to explain the odds, but a factor citing them is rejected by the engine, as is a claim without a real tag.
- A number only counts if a factor with the SAME effect cites a real tag (a `-2` on `away_rate_pct` with only a `home_rate_pct` factor is ignored).
- Size: the expected answer is **0**. A single weak factor stays 0; typical 1-3; hard bounds +-12 (rates) and +-3 (draw). A lone reviewer counts half: the "Panel result" line shows what was applied.
- Absentees: independent mode does NOT apply them, so a clearly important absentee (starter or key player) may justify at most +-3, citing `[X.absent.<name>]` (that tag is accepted). The engine REJECTS a factor citing a fringe or `unknown` absentee (worth 0). Pick the matching effect: a missing attacker lowers that side's rate, a missing defender or keeper raises the OPPONENT's rate. With `--with-odds` do not adjust: the odds DO price known injuries, so never describe absences as "unpriced by the odds"; a gap to the odds is not explained by absences the odds already include.
- Rotation tags describe the PREVIOUS match; use one only if the pattern clearly carries over, and never for heavy rotation (8+ changes, Phase D: mention it, do not adjust for it; `lint` rejects it).
- Draws: `draw_bias_pct` only for draw-specific cited context (a table scenario where a draw suits both, a dead rubber, a clearly defensive matchup), never because a team "draws a lot" (tested: no information). `lint` questions a draw adjustment with any other evidence.
- `confidence` 0..1 is how much YOU trust your own adjustments, nothing else. Below 0.2 the engine ignores every adjustment. At 0.2 or more they are applied, but one reviewer counts half (the engine's "trust x0.5"), so a +2 becomes +1. With all numbers 0 it changes nothing, so never present it as confidence in the forecast. Typical: 0.3-0.5 for one weak cited factor, 0.5-0.7 for a clearly evidenced one.
- Empty `factors` with zeros is valid and the usual answer. Put the advocates and verdict in the same file; list `data_gaps`.

**Phase G. Answer and verification.** *Exit: the audit (command 7) is clean and the self-check below passes.*
1. **The engine writes every judgement line; you do not.** `compose` (command 6) builds `case_home`, `case_away`, `weak_points`, `odds_challenge`, `why`, `vs_odds`, `risks` and `data_note` from the tagged dossier and the engine's numbers. By default it IGNORES free text in those keys (free text caused new errors in every test round, and agents that were asked to override only when needed overrode everything). An empty judgement file `{}` is the normal input. It takes NO free text at all (not even a note): every line of the answer is the engine's, built from the tagged dossier and the numbers. Your judgement is expressed only through the bounded, evidenced factors in the opinion file, the `data_gaps` list and an enumerated verdict. Do not use `--free-text` unless the user asks for it.
   **Write only your judgement.** Command 5 (`football.oracle draft`) previews the answer: every number is already filled from the engine and your eight slots are marked `[WRITE: ...]`. Put your reasoning in `/tmp/judgement.json` (keys `vs_odds`, `case_home`, `case_away`, `weak_points`, `odds_challenge`, `why`, `risks`, `data_note`; example in section 4). Then run **command 6, `compose`**: it builds the final answer and keeps every engine line (headline, **In plain words:**, Recommended bet with its Cautions, Draw, Goals, the numbers of Own model vs odds, Lineups, the start of Data audit) **word for word**. You cannot change a number and do not retype one. A missing key leaves its `[WRITE: ...]` placeholder, which the audit refuses.
2. **Reason from the printed numbers.** Probabilities sum to ~100; the pick is the largest of the three. If the engine differs from the odds by > 10 points, report the gap and what the evidence says about it; do not move toward the odds. Recompute every comparison you write (differences to the odds, to the baseline) from the printed percentages: a gap you state must match them.
3. **The recommended bet is the engine's most likely selection:** never replace it with another market. When lineups are unconfirmed, `weak_model` is on or the strength is `lean`, say it is a lean, not a confident call.
4. **Audit** (command 7). It checks that the draft's lines are kept as drafted, that every tag exists, the headline, double-chance and recommended-bet numbers equal the engine's, the draw level is right, no side's own absence sits in its Case line, and no banned claim appears (staking advice or guarantees, "we predict a draw", the odds' track record used as an argument). Fix every FAIL row before replying by editing `/tmp/judgement.json` (or the opinion file) and running `compose` again; never edit `/tmp/answer.md` by hand. Verify every WARN line against the tag lines (a score or opponent not in the form data, a characterising word, a head-to-head record quoted without its full wins-draws-losses and n (checked against the `[H2H]` record, never against recent form), a manager or a "missing" player not in the data, a "by N points" comparison that matches no real gap ON THE OUTCOME IT NAMES between the final forecast, the baseline and the odds, a guess about why the odds differ, a form adjective such as "strong" or "poor" that the last six results do not support, an absentee count that exceeds the named side's); "unbeaten", "winless" and streak claims that the form letters contradict are FAIL rows.

**Phase H. Independent review** (after the audit is clean). *Exit: the reviewer says PASS, or every fix it listed has been made and the audit re-run clean.*
The audit knows only the mistakes we have already seen. A second reader catches the rest (a number read backwards, a claim the tags do not show). Run command 8 and give its whole output to a SEPARATE reviewer agent (a fresh subagent, low-cost model, no tools beyond reading; it must not be the agent that wrote the answer). It replies `VERDICT: PASS` or `VERDICT: FIX` with quoted problems. For each problem check the quoted tag line yourself: fix it in `/tmp/judgement.json` (or the opinion file) and re-run compose and audit; if the reviewer is wrong, say so in one line and keep the text. One review round only (no endless loops). When no subagent can be spawned, do the checklist yourself line by line and say that the review was self-run.

**Mistakes agents made most often** (all caught by the audit; avoid them up front)
| Mistake | Instead |
|---|---|
| A side's own absence or weakness in its own `Case for` line | Put it in `Weak points` / `Lineups`; a specific cited opponent absence is fine in a Case line |
| "stable", "dominant", "overwhelming", "resilient", "momentum" | The number or tag line it rests on |
| Head-to-head record without its sample size | `home 3, draws 1, away 1 (n=5)` once, then bare `[H2H]` is fine |
| Head-to-head described as recent form, or the reverse | Two different things: head-to-head = past meetings between these two sides (tag `[H2H]`: `home` = wins by this fixture's home TEAM, `away` = wins by its away TEAM, whichever stadium each meeting was in; the venues of past meetings are not in the data, so never write "on the road" or "at home" about them); recent form = each side's last results against anyone (`[H.form]` / `[A.form]`, letters). Quote each with its own tag; never write "won 7 of the last 10" for meetings and call it form |
| "unpriced by the odds" / "priced into Elo" about absences | The odds DO price them; the independent engine leaves them unmodelled |
| Combined tags `[A.form, A.table]`, or a tag that is not in the brief | One tag per bracket, exactly as printed |
| A wrong "by N points" or "N of the last M" count | Recompute from the printed percentages or form letters |
| A real gap attached to the wrong outcome ("leans away by 3 points" when 3 is the home gap) | Name the outcome and quote that outcome's own gap |
| A guess dressed as an explanation ("likely explained by", "likely priced by the odds", "odds optimistic", "explained by rounding", "typically excludes", "key absentee" for an unknown-role player). The audit FAILS these | What the tags and numbers show, or "the gap is unexplained"; "unknown role" for players not in the squad list |
| "Will bounce back / hungry / desperate after losses" (tested: no such effect; the audit FAILS it) | State the losing run from the form letters; say it is context and the data shows no bounce-back |
| A number under the wrong tag (a goal difference under `[A.table]`, an xG figure under `[H.form]`), or a tag placed BEFORE its claim (audit warns) | Put each tag right AFTER the claim it supports and quote numbers only from that tag's own line |
| Invented tactics, feelings or consequences ("physical 5-4-1", "hit on the counter", "adds stress", "may create fragility", "could get routed") and a cause for the odds gap ("explain", "account for") | Nothing: state the tagged number, say "the gap is unexplained" |
| A context tag (stakes, rotation, fatigue, travel) named as a driver of the forecast (audit warns) | The forecast comes from history, xG, results and strength; say these are context |
| "Strong form" for a side with 2 wins in 6 (or "poor form" for 4 wins) | Quote the letters: `DLLLWW`, not an adjective |
| "Unbeaten" for a side with a loss in its last six, or a streak the letters do not show | Quote the letters (`WWDWLL`); a streak is only the run of identical letters from the left |
| An absentee count credited to the wrong team ("eight Dutch absentees" when 6 are Dutch and 2 Greek) | Count per side; the engine's Lineups line lists them by side |
| Draw level written from memory | Copy the engine's level (ALERT / WATCH / no alert) |
| Recommending Over/Under or BTTS below 60%, or swapping in your own market | The engine never does; the double chance is the fallback when no outcome reaches 60% |
| Rewriting the plain-words line, the Recommended bet line or a number the draft filled | Keep them word for word; reason only inside the `[WRITE: ...]` parts |
| "Safe bet", "guaranteed", a stake size, "the odds usually win" | The probability and hit rate as printed; the odds are a benchmark, not an argument |

## 4. Opinion file example (tags illustrative: use the tags of YOUR brief)
```json
{
  "home_rate_pct": 0, "away_rate_pct": -3, "draw_bias_pct": 0, "confidence": 0.5,
  "factors": [{"effect": "away_rate_pct", "evidence": "[A.rotation]", "note": "changed 6 of 11 starters in the previous match"}],
  "advocates": {
    "home": "Strong form [H.form] and a short trip for the visitors [TRAVEL]; the case rests on small unpriced effects.",
    "away": "Better table position [A.table] and a 3-1 head-to-head [H2H], but that is priced.",
    "odds_challenge": "Lineups are unconfirmed [LINEUPS] so the odds may move, but nothing specific outweighs the base rate.",
    "verdict": "odds_right"
  },
  "data_gaps": ["confirmed lineups"]
}
```

Judgement file example (`/tmp/judgement.json`; tags illustrative: use the tags of YOUR brief; one tag per bracket; each text short and from the tags and numbers only):
```json
{
  "vs_odds": "The engine is 6 points less confident in the favourite than the odds [BASELINE]; the table and form do not explain it.",
  "case_home": "Strong form [H.form] and a short trip for the visitors [TRAVEL].",
  "case_away": "Better table position [A.table] and a 3-1 head-to-head record (n=4) [H2H].",
  "weak_points": "Home: changed 6 of 11 starters last match [H.rotation]. Away: one absentee not in the squad list [A.absent.Example Player].",
  "odds_challenge": "unclear - the cited evidence is mixed and nothing unpriced settles it.",
  "why": "Squad strength [BASELINE], home venue [FIXTURE], and the table [A.table].",
  "risks": "Lineups are unconfirmed [LINEUPS]: re-run once they are.",
  "data_note": "The unconfirmed lineups and the absentee missing from the squad list are data limits, not errors."
}
```

## 5. Deliverable (`compose` builds this shape; you write only the judgement slots)
```
**{Home} {h}% / Draw {d}% / {Away} {a}%**  - most likely 1X2: {pick} ({p}%); calibrated chance the pick is right {c}% (observed hit rate of such picks in held-out matches, not a guarantee)
In plain words: {who is favoured, the draw risk, the best bet and how often such bets won, the first caution; as drafted}
Recommended bet: {selection} - {prob}% ({market: 1X2, Double chance, Over/Under 2.5 or BTTS}); strength {lean|moderate|strong|very strong}; bets of this kind at this probability hit {obs}% in held-out matches; next best: {two alternatives with their %}. {Why this market / Not recommended, when printed}. Cautions: {as printed}. Copy it from the engine, one line, every match.
Own model vs odds: {one line; odds are the benchmark, not an input. Quote the FINAL percentages from the headline and attribute each set to its source (engine baseline, final, odds), never one source's numbers to another; if you also mention the engine baseline, label it "baseline" (the final is pulled toward base rates when data quality < 100%)}
Draw: {ALERT|WATCH|no alert} - draw {d}% ({tier}: ~{obs}% of such matches end level); double chance {1X}% / {X2}%; drawn scores 0-0 {x}% 1-1 {y}% 2-2 {z}%; {toss-up / low-scoring / heavy-favourite flag if any}
Case for {Home}: {1-2 sentences, tags; only evidence FOR the home side: its own strengths, or a specific cited opponent absence/travel/rotation, never a general "the opponent is weak"; an absence or weakness of THAT side never belongs in its own case}      Case for {Away}: {same, for the away side}
Weak points: {each side's OWN absences, rotation and risks, with tags: this is where they go, not in its Case line}
Odds challenge: {verdict} - {why}
Goals: expected {x}-{y}; likeliest scores {..}; over 2.5 {..}%, both score {..}%
Why: {3 biggest drivers, each tied to a tag or number}
Lineups: {confirmed or guessed; starters out per side; absentees `unknown` (not in the squad list: usually called-up lists drop injured players, so these may be the key absences the engine cannot weigh) named as a data gap; any lineup flag}
Risks and data gaps: {what could make this wrong; what to re-check before kickoff}
Data audit: {one line per finding that matters; mark data artefacts as such}
```

## 6. Draw doctrine
| Level | Rule | Observed (held-out internationals) |
|---|---|---|
| **ALERT** | draw >= 29% | 32% of flagged matches end level; catches ~33% of draws |
| **WATCH** | draw >= 27% | 31% end level; catches ~52% of draws |
| **Toss-up** | home and away win within 5 points AND draw >= 28% (use exactly this test; do not say "all three within N points") | combine with the level above |
| **heavy favourite** | a side >= 70% | draws rare (~11%); the usual way the favourite fails to win is a 0-0 or 1-1: name it |
| **low-scoring game expected** | < 2.2 expected goals | more 0-0 and 1-1 |

**How draws actually happen** (post-match reports of 13 live draws, 2026-10; a reading aid, not a predictor: only the pre-kickoff column can be used, and only as risk wording):
| Route | Seen in | Knowable before kickoff? |
|---|---|---|
| Comeback or late equaliser after the favourite led (incl. from 2-0) | 5 of 13 | No; say "a lead can be lost" only for a strong side facing a side that keeps scoring (`[H.form]` or `[A.form]` goals) |
| Dominant side wastes chances against a deep, low-xG defence | 4 of 13 | Partly: the underdog's low xG / low goals against shows in the tags and in the low-scoring flag; the engine already uses it |
| Deflection, own goal, disallowed goal | 3 of 13 | No |
Name which route is plausible for THIS match from the tags (a heavy favourite with a low-scoring opponent: the wasted-chances route; two sides that both score: the comeback route). Never invent a cause the tags do not show, and never use these routes to predict a draw: low-scoring and team draw-tendency signals add nothing out of sample (research/README.md), and 68 of 8,054 held-out matches had a draw as the most likely outcome. The published literature agrees: draws are the hardest class (about 40% at best even for models with shot-level data we lack); our answer to that is the draw flag plus the double-chance bet, not a draw pick.

A flag is a 1-in-3 hint, never "predicted draw". A draw is almost never the most likely outcome (68 of 8,054 held-out matches; it is the 2nd most likely in 84%), yet 23% of internationals end level; draws with no flag are normal. State that. Quote any flag the engine prints on the Draw line.
Other cases: no odds in the report: say so, the odds challenge is not possible. Knockout games: the model was trained on results after extra time ("level after 120 minutes").

## 7. Prohibited conduct
- Never invent facts, injuries, results or numbers; never edit probabilities yourself; never change a number by hand.
- Do not claim to predict draws or promise outcomes. The recommended bet is the model's most likely selection with its probability and observed hit rate, not staking advice: never suggest a stake size, never guarantee a result, never call it a sure thing.
- Every factual claim (a score, record, streak, manager trait) must be copied from a tag line; do not characterise beyond the data. In independent mode absences are unmodelled: never say they are "priced into Elo" or into the model.
- Do not use reputation or memory as evidence; do not treat a scraped value you flagged *unverified* as fact.

## 8. Self-check before you answer
[ ] used the engine's numbers unchanged   [ ] audit findings listed   [ ] both advocates + challenger + verdict written with real tags   [ ] draw alert level stated with its meaning
[ ] pick = largest probability   [ ] differences from the odds explained   [ ] weak_model / no-odds / knockout notes included when they apply   [ ] risks and data gaps named   [ ] lineup status stated   [ ] every figure and gap quoted matches the engine output and its source   [ ] each Case line holds only evidence for that side   [ ] the recommended bet and its cautions are copied unchanged   [ ] audit clean

## 9. Related tasks
- Second opinion from the older analyst: `uv run python -m football.analyze <file>`. Run tests: `uv run pytest -q`.
- Score past predictions: `uv run python -m football.prediction_log import <reports dir>` then `uv run python -m football.prediction_log score --results <results.csv>` (csv: `date,home_team,away_team,home_score,away_score`).
- Absentees with no position: `uv run python -m football.oracle roles <report.json|folder>` lists them; look their position up (position only, with a source) and add it to `football/oracle/player_roles.json`. It is display only and never changes a number.
- Token-free scorecard (runs the engine only, matches results, lists every miss with its cause): `uv run python -m football.oracle score <reports folder> --results <results.csv>`.
- Absence forward test and accuracy summary (needs live results): `uv run python -m football.oracle.forward_log score <results.csv>`; the absence adjustment stays OFF until it passes (see reference.md).
- Evidence, calibration tables, bias hunt, draw scorecard: [reference.md](reference.md).
