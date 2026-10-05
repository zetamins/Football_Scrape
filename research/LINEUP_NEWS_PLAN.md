# Plan: use lineups and team news (how to analyse and think)

Goal: add the one kind of information the engine does not have yet (who actually plays),
without breaking calibration. Draws stay structural; this only sharpens the H/D/A shape.

## 0. Ground rules (already proven here, do not re-litigate)

| Rule | Why |
|---|---|
| Absence adjustment stays OFF (`ABSENCE_APPLY_SCALE=0.0`) until it passes the gate in section 5 | It hurt on the 38 live matches |
| Never edit probabilities by hand; only the engine moves them | Calibration is verified (23.0% vs 23.2% draws) |
| Missing data is "unknown", never "zero impact" | Scraped lists are often empty |
| Odds are a benchmark only | Engine must stay independent |

## 1. What the report JSON offers (checked on a real report)

| Field | Use | Trust |
|---|---|---|
| `match.lineup_confirmed` | Gate: confirmed vs predicted XI | High, check first |
| `match.home_lineup` / `away_lineup` (11 names) | Who starts | Only if confirmed |
| `match.home_formation` / `away_formation` | Shape, rotation | Medium |
| `match.*_missing_players`, `*_suspended_players` | Known absentees | Medium, often incomplete |
| `teamProfile.injuries`, `key_injuries`, `opponentProfile.*` | Longer-term absences | Medium |
| `teamProfile.squad` (+ `dataWindows.squad_recent_usage`) | Minutes, starter status, value | Medium |
| `insights.*_rotation.changed_players`, `formation_changed` | Rotation vs last match | High (computed) |
| `insights.*_squad_strength` | Squad value totals | Medium |

## 2. Thinking order (the analyst follows this every time)

1. **Is the XI confirmed?** If `lineup_confirmed` is false, treat lineups as a guess. Say so; do not reason from names.
2. **Audit first.** Flag: players listed in both XIs, injured player in the XI, XI name not in squad, 0 listed absentees for a team with a long injury list. Flagged data is *unverified*, not corrected from memory.
3. **Classify each absentee** with the squad data, not reputation:
   - Starter (high recent minutes) / rotation / fringe / unknown.
   - Position group: goalkeeper, centre-back, midfield, forward.
   - Replacement quality: next player's recent minutes and value; "unknown" if absent from squad list.
4. **Size the effect** with the table below. A single absentee rarely moves a match more than a few points.
5. **Check the gap to the engine.** If engine and your absentee view disagree by more than the cap, the data is probably incomplete; report as a data gap, do not push the number.
6. **Write it as evidence tags** (`[X.absent.<name>]`, `[LINEUPS]`) so the validator can accept it. Priced tags stay rejected.

## 3. Effect caps (starting values, to be fitted, not believed)

| Situation | Max shift to that team's win probability |
|---|---|
| Starting goalkeeper out | 3 points |
| Two or more starting defenders out | 3 points |
| Best attacker out | 2 points |
| Mass rotation (8+ changes, nothing at stake) | 3 points |
| Fringe or unknown-role player out | 0 |
| Any combination | 5 points total, and never moves the draw tier more than one step |

These caps are hypotheses. Section 5 decides whether they are used at all.

## 4. Build steps (small, reversible)

| Step | Work | Output |
|---|---|---|
| A | `football/oracle/lineup.py`: pure function turning the report into `{confirmed, absentees[{name,role,starter_score}], rotation}` | Unit tests on the real report fixtures |
| B | Add lineup flags to `facts.audit_facts` | Flags: `xi_unconfirmed`, `xi_overlap`, `injured_in_xi`, `empty_absentee_list` |
| C | Add a "Lineup picture" block to the LLM brief (facts only, no numbers from the model) | Prompt-sync tests updated |
| D | Add the caps from section 3 as an optional engine step behind a scale flag, default 0.0 | No behaviour change by default |
| E | Update SKILL.md (both copies) with the section 2 order; keep under 100 lines | Identical copies |

## 5. Promotion gate (the only way the scale moves above 0)

1. Build a back-test set where lineups or absences were known pre-match. Source must be pre-match only (no leakage).
2. Fit the scale on 2018-21 and 2022-23; evaluate once on 2024-26.
3. Metrics: Brier, log-loss, RPS, paired bootstrap CI against scale 0.
4. Promote only if the improvement is positive on both validation and test with the CI excluding zero, and |z| >= 3.3 if several variants were tried.
5. If it fails, keep flags and brief text (steps A-C, E) and leave the scale at 0. That is still a valid outcome.

## 6. Risks and how we handle them

| Risk | Handling |
|---|---|
| Predicted XI treated as confirmed | Step 2.1 gate, flag `xi_unconfirmed` |
| Leakage in back-test (post-match lineups) | Pre-match timestamps only; otherwise do not test |
| Few matches with real lineup data | Report sample size; no promotion under about 300 matches |
| Over-thinking noise | Caps, "unknown" default, one-step draw-tier limit |
| Data source needed for history | Not yet chosen. Needs a decision before step 1 of section 5 |

## 7. Acceptance criteria

- Tests pass (currently 2,098) plus new tests for steps A-B.
- Default predictions unchanged (scale 0.0) so existing results do not move.
- Skill copies identical; prompt-sync tests pass.
- Evidence log in `research/README.md` records the gate result, pass or fail.

## 8. Open decision

Where to get historical pre-match lineups for the back-test. Without it, only steps A-C and E are possible and the scale stays 0.

Decision (2026-10-04): no historical lineup data exists, so the back-test gate cannot run. ABSENCE_APPLY_SCALE stays 0.0 permanently; lineup work is limited to audit flags, the availability brief tag and skill text. Only a forward test (log engine probabilities with and without absences on live matches, about 300 needed) could change this.
