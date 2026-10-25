# Answer rules and template

## Keep it short and exact

There is no word limit: be as thorough as the evidence needs, but keep it exact and readable. Each table cell is a short phrase with its numbers; each case 100 to 160 words; each data link one line. Long answers hide errors and no reader checks them. Every statistic names its team in the same sentence ("Austria won 104 of 196 aerial duels (53%)"). Every past result you cite gives the opponent, the date, the score from that team's side and whether that team was home or away, copied from the sheet's result rows ("Kosovo 0-0 Israel, 1 Oct, away"). Every number that is not in the sheet is worked out with `python3 -c` and written with its arithmetic in the same sentence (\"15.7 points below the baseline (72 - 56.3 = 15.7)\"): the checker verifies shown arithmetic and fails three or more unexplained derived numbers. Do not describe a draw as a win or a loss as a draw, and do not move a statistic from one team to the other: re-read the row before you quote it.

## Answer template

```
**{Home} {h}% / Draw {d}% / {Away} {a}%** (my probabilities; expected goals {lh}-{la})
Symmetric table: | lens | {Home} | {Away} | favours (and by how much) |  (one row per lens: luck vs performance, attack, defence, style, opposition quality, stakes, schedule and fatigue, physiology and load, personnel, environment)
Home v away: {one line per side: initiative and press at this venue, caution and transitions, intensity, and whether game state or stakes reverse the default}
Substitutions: {one line per manager: who is rested or comes on, when and at what scoreline he changes, bench impact; thin samples labelled}
Scouting report: {one line per side: shape in and out of possession, build-up and chance creation, key players and where dangerous, set pieces, pressing/line/transitions, weak areas; proxies labelled}
Deciding factors: {the highest-priority areas that decided it (team news, tactical matchup, underlying stats, home v away split, motivation), then the secondary adjustments you applied (fatigue, bench, head to head) and by how much}
Specialist notes: {only if notes exist: for each note what it favours, its strength, and the xG change you accepted or rejected and why}
Gap analysis: | step | {Home} | {Away} |  (current state, target state, gap, root cause, fix; one short phrase each; then one line for the tactical adjustments with their triggers and one for rotation: who is rested, who is protected)
Media focus: {only if you ran media.py: the topics the media dwell on and two or three dated headlines with source, each marked (unverified)}
Manager's checklist: | item | {Home} | {Away} |  (the eight items: fitness and sharpness, form, system fit, morale (proxies), availability and rotation, opponent setup, importance, bench; one short phrase each)
Flank map: | flank | {Home} attack / defence | {Away} attack / defence | mirror pair and who can exploit it |  (left, centre, right; both sides, same depth; label your own knowledge)
Data links: {at least 3 chains: signal A (number) + signal B (number) => implication}
Case for {Home}: {strongest honest case, 4-6 sentences, linked evidence, and what it must overcome}
Case for {Away}: {the same depth for the other side}
My view: {3-5 sentences: who is better, by how much, and why the one case beats the other; say which side each of these favours and whether you counted it: the rebound (xG delta over three or more games), rest, head to head, the opponent's defensive weakness}
Expected goals adjustment: {only when your expected goals move from the anchor (more than 0.05 from the rating anchor, which moves ONLY for team news): the anchor, each change with its arithmetic and reason; an absence is capped at the absentee's share of team xG minus what the replacement adds}
Own odds: home {x}, draw {y}, away {z} (your own price; no bookmaker price is used).
Best bet: {bet} ({probability}%), confidence {low|medium|high}. Why this bet: {...}. What would change my mind: {...}
Goals bet: {Over 2.5 goals|Under 2.5 goals|Both teams to score: Yes|Both teams to score: No} ({probability}%), confidence {low|medium|high}. Why: {the likeliest of the four from calc.py's 'Goals markets' line, with the evidence for the goal level}
Value: UNMEASURED (always: the analysis is price-free; value.py's market scoreboard compares the finished answer afterwards, for reference only)
Draw risk: {your draw probability, which signals push it up or down from the 23-25% base rate, and what that means for the bet}
Draw cover: {why a single-outcome bet below 50% is not undone by a draw, only when the draw is 25%+}
Underdog first: {only for a favourite-to-win bet below 60%: calc.py's 'If the underdog scores first' numbers against the sheet's IF THE UNDERDOG SCORES record; does the favourite come back, settle for a draw or lose, and does the bet hold}
Why a double chance: {only if you bet one: the specific risk to the single outcome, with its number}
Underlying evidence: {at least five signals BEYOND results and ratings, each with its number and what it implies, covering both sides}
From the report: {the other facts you relied on, each with its number}
Own knowledge (unverified): {anything you used that is not in the report, or "none"}
Risks and data gaps: {lineups, unknown players, small samples, shootout rows, anything uncertain}
```

## Compact template (collection mode: 3 or more specialist notes exist)

There is no word limit. The notes hold the detail, so the answer does not need to repeat the specialist blocks.

```
**{Home} {h}% / Draw {d}% / {Away} {a}%** (my probabilities; expected goals {lh}-{la})
Specialist notes: {one line per note: what it favours, its strength, and the xG change you accepted or rejected and why}
Advocates: {only if advocate briefs exist: what the home, away and draw advocates argued, which case is strongest and why, and whether each one's verify fact held}
Symmetric table: | lens | {Home} | {Away} | favours |  (short rows: luck vs performance, attack, defence, style, opposition, stakes, schedule, physiology, personnel, environment)
Data links: {at least 3 chains: signal A (number) + signal B (number) => implication}
Case for {Home}: {linked evidence, what it must overcome}
Case for {Away}: {the same for the other side}
My view: {3-5 sentences: who is better, by how much, why}
Expected goals adjustment: {only if you moved from the anchor (more than 0.05 from the rating anchor, for team news only): arithmetic and reason}
Own odds: home {x}, draw {y}, away {z} (your own price; no bookmaker price is used).
Best bet: {bet} ({probability}%), confidence {low|medium|high}. Why this bet: {...}. What would change my mind: {...}
Goals bet: {Over 2.5 goals|Under 2.5 goals|Both teams to score: Yes|Both teams to score: No} ({probability}%), confidence {low|medium|high}. Why: {the likeliest of the four from calc.py's 'Goals markets' line, with the evidence for the goal level}
Value: UNMEASURED (always: the analysis is price-free; value.py's market scoreboard compares the finished answer afterwards, for reference only)
Draw risk: {draw probability and the signals}
Draw cover: {only if a single bet is below 50% with the draw at 25%+}
Underdog first: {only for a favourite-to-win bet below 60%: the comeback numbers and the real record after conceding; does the bet hold}
Why a double chance: {only if you bet one: the risk to the single outcome, with its number}
Underlying evidence: {at least five signals beyond results and ratings, each with its number}
From the report: {the other facts you relied on, each with its number}
Own knowledge (unverified): {anything not in the report, or "none"}
Risks and data gaps: {lineups, unknown players, small samples}
```
