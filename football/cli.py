"""CLI entry point -- equivalent to the original `npm run search -- "Team
Name"`. Ported from src/search.ts's main().

Console output here is the markdown report printed directly (see
format_markdown.py's module docstring for why the TS original's separate
`print*` console-formatter family was consolidated away rather than
ported 1:1) rather than a distinct console-specific format.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .format_markdown import slugify
from .orchestrate import run_search
from .report import build_report_json, build_report_markdown

_OUTPUT_DIR = Path.cwd() / "output"


def _parse_team_names(raw: str) -> list[str]:
    """Comma-separated so a single unquoted multi-word team name (the
    original, still-supported usage -- `football-search Real Madrid`,
    where argv arrives as two separate words with no delimiter of its own)
    is unambiguous from multiple teams (`football-search "Real Madrid,
    Liverpool, Bayern Munich"`). No comma present -- including the
    original single-team case -- yields the same one-element list as
    before."""
    return [t.strip() for t in raw.split(",") if t.strip()]


async def _run_one(team_name: str, *, announce: bool) -> None:
    if announce:
        print(f"\n=== {team_name} ===")
    print()
    result = await run_search(team_name, lambda msg: print(msg))
    print()

    markdown = build_report_markdown(result)
    print(markdown)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{slugify(team_name)}-{result.generated_at.replace(':', '-').replace('.', '-')}"
    json_path = _OUTPUT_DIR / f"{base}.json"
    md_path = _OUTPUT_DIR / f"{base}.md"

    json_path.write_text(json.dumps(build_report_json(result), indent=2, default=str), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    print(f"Saved:\n  {json_path}\n  {md_path}")


async def _main() -> None:
    raw = " ".join(sys.argv[1:]).strip()
    if not raw:
        print('Usage: football-search "Team Name"[, "Team Name 2", ...]', file=sys.stderr)
        sys.exit(1)

    team_names = _parse_team_names(raw)
    multiple = len(team_names) > 1

    # Sequential, not concurrent: these sites are already rate-limit/block
    # sensitive (Sofascore's Cloudflare edge has 403'd this project's own
    # traffic after sustained volume in the same session) -- running many
    # teams' worth of requests at once would multiply that risk for no
    # benefit an interactive CLI run actually needs. One team failing
    # (network blip, a site blocking, an unmatched team name) doesn't
    # abort the rest of the batch -- each is independent and partial
    # results for N-1 teams are still useful.
    failures: list[str] = []
    for team_name in team_names:
        try:
            await _run_one(team_name, announce=multiple)
        except Exception as e:
            print(f'Failed for "{team_name}": {e}', file=sys.stderr)
            failures.append(team_name)

    if multiple:
        ok = len(team_names) - len(failures)
        summary = f"\nDone: {ok}/{len(team_names)} succeeded"
        if failures:
            summary += f" (failed: {', '.join(failures)})"
        print(summary)

    if failures and len(failures) == len(team_names):
        sys.exit(1)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
