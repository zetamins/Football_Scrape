# Football Scrape

[![CI](https://github.com/zetamins/Football_Scrape/actions/workflows/ci-and-release.yml/badge.svg)](https://github.com/zetamins/Football_Scrape/actions/workflows/ci-and-release.yml)

Multi-source football match scraper, data merger, and pre-match insights/prediction engine — available as a Python CLI and as a native Android app (same Python backend, embedded on-device).

Point it at a team name and it pulls fixtures, lineups, injuries, referee stats, odds, standings, and season form from up to 13 independent public sources, reconciles the overlaps, and produces one merged report: a JSON file for programmatic use and a readable Markdown summary, plus derived insights (fatigue, rest days, Elo-style form rating, home advantage, card risk) and a blended win/draw/loss prediction.

## Data sources

| Source | Provides |
|---|---|
| Sofascore | Base source: fixtures, lineups, formations, referee, standings, H2H, season stats, odds |
| Fotmob | Fixtures, match facts, squad, transfers |
| SoccerDesk | Fixtures, H2H, suspensions |
| Goal.com | Fixtures, squad season stats |
| 365Scores | Fixtures, lineups, standings |
| Squawka | Per-player defensive stats |
| football-data.co.uk | Betting odds, referee cards/bias |
| worldfootball.net | Referee penalty/card history |
| refsradar.com | Referee KPI rates |
| StatsUltra | Club strength ratings |
| StadiumDB | Venue details |
| wttr.in | Match-day weather |
| Wikipedia | Manager tenure history |

Every source is best-effort and independently optional — a report is produced from whatever combination succeeds, with per-source scrape status included in the output.

## Project layout

```
football/            Python backend (this is what gets embedded in the Android app)
  sites/              One scraper module per source, all async
  orchestrate.py       The fetch -> merge -> compute pipeline (run_search)
  merge.py             Cross-source reconciliation
  form.py, elo.py       Recent-form and Elo-style rating computation
  insights.py           Fatigue, rest days, card risk, standings-impact, etc.
  prediction.py         Market/heuristic/xG blended match prediction
  report.py, format_markdown.py   JSON and Markdown report rendering
  cli.py               `football-search` entry point
android/              Native Android app (Kotlin + Jetpack Compose), embeds football/ via Chaquopy
tests/                pytest suite (1000+ tests, no live network calls)
.github/workflows/    CI (tests on every push/PR) + APK release (on version tags)
```

## Getting started (CLI)

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/zetamins/Football_Scrape.git
cd Football_Scrape
uv sync
uv run football-search "Arsenal"
```

Multiple teams in one run:

```bash
uv run football-search "Arsenal, Chelsea, Liverpool"
```

Each run prints a Markdown report to the console and writes both `output/<team>-<timestamp>.json` and `output/<team>-<timestamp>.md`.

Three of the thirteen sources (Sofascore, Squawka, worldfootball.net) drive a real headless browser and need the optional `browser` extra:

```bash
uv sync --extra browser
uv run playwright install chromium
```

Without it, the other ten (plain-HTTP) sources still work — a report is just missing whatever those three would have added.

## Getting started (Android app)

The `android/` project is a standard Gradle build; open it in Android Studio, or from the command line:

```bash
cd android
./gradlew assembleDebug
```

The debug APK lands at `android/app/build/outputs/apk/debug/app-debug.apk`. It bundles the same `football/` package via [Chaquopy](https://chaquo.com/chaquopy/) (Python-on-Android) — no server, no network calls to anything but the scrape targets themselves. Requires JDK 21 and Android SDK (compileSdk 35, minSdk 24).

## Testing

```bash
uv sync --group dev
uv run pytest tests/
```

Every scrape is mocked — no test hits a real site. One exception: a single test genuinely launches a headless Chromium via Playwright (no network calls, just verifying the browser-launch path itself works), so CI installs the `browser` extra and Chromium specifically to run it.

## CI / releases

Every push and pull request to `main` runs the test suite (`.github/workflows/ci-and-release.yml`). Pushing a version tag additionally builds the Android debug APK and publishes it as a GitHub Release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

(Debug-signed only for now — release signing needs a keystore added as a repo secret; see the comment in the workflow file.)

## Status

Actively developed. Output completeness varies by team and league — smaller/non-European competitions naturally have thinner source coverage (fewer of the 13 sources track them), which shows up as more `null` fields in the report rather than fabricated values.
