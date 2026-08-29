"""Static checker: finds every dataclass constructor call in football/ and
verifies all required (no-default) fields are supplied as keyword args.
Catches the class of bug found live (SeasonAdvancedStatsEstimate missing
errors_lead_to_goal_for/against) without needing another expensive
live/network run to reproduce each one. Not part of the pytest suite --
a one-off audit tool.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import pkgutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import football  # noqa: E402


def _all_dataclasses() -> dict[str, type]:
    """Import every module under football/ and collect every dataclass
    type defined anywhere in the package (types.py plus locally-defined
    ones in merge.py/insights.py/orchestrate.py/form.py/report.py)."""
    result: dict[str, type] = {}
    for mod_info in pkgutil.walk_packages(football.__path__, prefix="football."):
        try:
            mod = importlib.import_module(mod_info.name)
        except Exception as e:  # noqa: BLE001
            print(f"  (skipping {mod_info.name}: import failed: {e})")
            continue
        for name, obj in vars(mod).items():
            if dataclasses.is_dataclass(obj) and isinstance(obj, type):
                result[name] = obj
    return result


def _required_fields(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls) if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}


def check_file(path: Path, known: dict[str, type]) -> list[str]:
    problems = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name not in known:
            continue
        cls = known[name]
        required = _required_fields(cls)
        if not required:
            continue
        has_spread = any(kw.arg is None for kw in node.keywords)  # **something
        if has_spread:
            continue  # can't statically verify what a spread supplies
        given = {kw.arg for kw in node.keywords if kw.arg is not None}
        # Positional args count toward the first N dataclass fields in order.
        field_names_in_order = [f.name for f in dataclasses.fields(cls)]
        given |= set(field_names_in_order[: len(node.args)])
        missing = required - given
        if missing:
            problems.append(f"{path}:{node.lineno}: {name}(...) missing required field(s): {sorted(missing)}")
    return problems


def main() -> None:
    print("Collecting dataclass types...")
    known = _all_dataclasses()
    print(f"Found {len(known)} dataclass types.\n")

    all_problems = []
    football_dir = Path(football.__file__).parent
    for py_file in sorted(football_dir.rglob("*.py")):
        all_problems.extend(check_file(py_file, known))

    if all_problems:
        print(f"{len(all_problems)} POTENTIAL PROBLEM(S):\n")
        for p in all_problems:
            print(f"  {p}")
    else:
        print("No missing-required-field construction calls found.")


if __name__ == "__main__":
    main()
