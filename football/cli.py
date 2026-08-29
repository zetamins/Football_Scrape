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


async def _main() -> None:
    team_name = " ".join(sys.argv[1:]).strip()
    if not team_name:
        print('Usage: football-search "Team Name"', file=sys.stderr)
        sys.exit(1)

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


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
