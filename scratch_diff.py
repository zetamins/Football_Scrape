"""Manual diff helper for parity checks -- not part of the pytest suite."""
import json
import re
import sys


def camel_to_snake(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


def normalize(obj):
    if isinstance(obj, dict):
        return {camel_to_snake(k): normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    return obj


def diff(a, b, path=""):
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        for k in sorted(keys):
            diffs += diff(a.get(k, "<<MISSING>>"), b.get(k, "<<MISSING>>"), f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append((path, f"len {len(a)} vs {len(b)}"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diffs += diff(x, y, f"{path}[{i}]")
    else:
        if a != b:
            diffs.append((path, f"{a!r} vs {b!r}"))
    return diffs


if __name__ == "__main__":
    ts_path, py_path = sys.argv[1], sys.argv[2]
    with open(ts_path) as f:
        ts = normalize(json.load(f))
    with open(py_path) as f:
        py = json.load(f)
    d = diff(ts, py)
    print(f"{len(d)} differences")
    for p, msg in d[:80]:
        print(f"  {p}: {msg}")
