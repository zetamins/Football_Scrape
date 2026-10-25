"""Where to read/write the small pre-fetched seed caches (fotmob-teams.json,
goal-teams.json, stadiumdb-countries.json).

Ported from src/dataDir.ts, simplified: the original had a Vercel-vs-local
branch (read-only deployment filesystem falling back to /tmp) because that
version had to run as a server. This rewrite targets a library embedded
directly in a client (CLI today, an Android app later, no server) with a
normal writable local filesystem, so both read and write resolve to the
same directory -- no fallback branch needed.
"""

from __future__ import annotations

import os
from pathlib import Path

# Anchored to this file's own location, not the current working directory --
# matches dataDir.ts's reasoning: a caller can be invoked from anywhere, but
# the seed data directory is always relative to this package.
_PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_ROOT.parent.parent


def data_dir() -> Path:
    """The committed data/ directory (repo root), shared with the original
    TS implementation's seed caches."""
    return _PROJECT_ROOT / "data"


def seed_path(name: str) -> Path:
    """Where a seed file (history-model.json, national-elo.json) is read from. First match wins:
    1. $FOOTBALL_DATA_DIR/<name>, 2. the shared data/ directory next to the backend (where retraining writes),
    3. backend/data/<name>, a vendored copy so a checkout of the backend alone still gets the trained models.
    When nothing exists the shared data/ path is returned, so a first training run writes there exactly as before."""
    env = os.environ.get("FOOTBALL_DATA_DIR")
    for folder in ([Path(env)] if env else []) + [data_dir(), _PACKAGE_ROOT.parent / "data"]:
        if (folder / name).exists():
            return folder / name
    return data_dir() / name
