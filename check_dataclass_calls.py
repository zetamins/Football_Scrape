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

import football


def _all_dataclasses() -> dict[str, list[type]]:
    """Import every module under football/ and collect every dataclass
    type defined anywhere in the package (types.py plus locally-defined
    ones in merge.py/insights.py/orchestrate.py/form.py/report.py and
    several site modules). Keyed by bare class name, but the value is a
    LIST -- several site modules independently define their own
    same-named-but-differently-shaped local class (e.g. two unrelated
    `_MatchMeta`, one in soccerdesk.py with a stage_id field, one in
    three65scores.py with competition_id) -- collapsing to a single dict
    entry silently let one module's definition mask another's, producing
    false "missing field" reports against the wrong class entirely.
    check_file() below picks the same-module candidate first."""
    result: dict[str, list[type]] = {}
    for mod_info in pkgutil.walk_packages(football.__path__, prefix="football."):
        try:
            mod = importlib.import_module(mod_info.name)
        except Exception as e:  # noqa: BLE001
            print(f"  (skipping {mod_info.name}: import failed: {e})")
            continue
        for name, obj in vars(mod).items():
            if dataclasses.is_dataclass(obj) and isinstance(obj, type) and obj.__module__ == mod_info.name:
                result.setdefault(name, []).append(obj)
    return result


def _required_fields(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls) if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}


def _resolve_candidate(candidates: list[type], module_name: str) -> type:
    """Prefer the class actually defined in the file being checked --
    see _all_dataclasses' own doc comment for why this matters when two
    unrelated modules define a same-named local class. Falls back to the
    first candidate for genuinely shared classes (e.g. types.py's own),
    where there's only ever one candidate anyway."""
    for cls in candidates:
        if cls.__module__ == module_name:
            return cls
    return candidates[0]


def check_file(path: Path, known: dict[str, list[type]], module_name: str) -> list[str]:
    problems = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name not in known:
            continue
        cls = _resolve_candidate(known[name], module_name)
        required = _required_fields(cls)
        if not required:
            continue
        has_spread = any(kw.arg is None for kw in node.keywords)  # **something
        # A starred positional (*a) can unpack to any number of values --
        # statically counting it as "1 positional arg" undercounts the
        # fields it actually supplies at runtime, producing a false
        # "missing field" report for a call that's actually fine.
        has_starred_positional = any(isinstance(a, ast.Starred) for a in node.args)
        if has_spread or has_starred_positional:
            continue  # can't statically verify what a spread/starred-unpack supplies
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
    package_root = football_dir.parent
    for py_file in sorted(football_dir.rglob("*.py")):
        parts = py_file.relative_to(package_root).with_suffix("").parts
        module_name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        all_problems.extend(check_file(py_file, known, module_name))

    if all_problems:
        print(f"{len(all_problems)} POTENTIAL PROBLEM(S):\n")
        for p in all_problems:
            print(f"  {p}")
    else:
        print("No missing-required-field construction calls found.")


if __name__ == "__main__":
    main()
