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
