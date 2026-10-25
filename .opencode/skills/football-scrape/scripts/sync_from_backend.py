#!/usr/bin/env python3
"""Refresh the ported scraping layer from backend/football (run from the repo after changing the backend).
    python3 sync_from_backend.py            copy football/ -> ./football (no android_*, no oracle) and the seed json -> ../data
    python3 sync_from_backend.py --check    exit 1 when the copy differs (the test suite runs this)"""
import filecmp
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[3]
SRC, DST = BACKEND / "football", HERE / "football"
SEEDS = ["fotmob-teams.json", "goal-teams.json", "history-model.json", "national-elo.json", "stadiumdb-countries.json"]


def wanted(p: Path) -> bool:
    rel = p.relative_to(SRC)
    return p.suffix == ".py" and "__pycache__" not in rel.parts and rel.parts[0] != "oracle" and not rel.name.startswith("android_")


def pairs() -> list[tuple[Path, Path]]:
    out = [(p, DST / p.relative_to(SRC)) for p in sorted(SRC.rglob("*.py")) if wanted(p)]
    return out + [(BACKEND.parent / "data" / n, HERE.parent / "data" / n) for n in SEEDS]


def main(check: bool) -> int:
    diff = [d for s, d in pairs() if not d.exists() or not filecmp.cmp(s, d, shallow=False)]
    extra = [p for p in DST.rglob("*.py") if "__pycache__" not in p.parts and not (SRC / p.relative_to(DST)).exists()]
    if check:
        for p in diff + extra:
            print("differs:", p)
        return 1 if diff or extra else 0
    for s, d in pairs():
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
    for p in extra:
        p.unlink()
    print(f"synced {len(pairs())} files")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
