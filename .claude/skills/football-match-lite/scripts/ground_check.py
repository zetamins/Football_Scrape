"""Audit tool (not part of an analysis): list the numbers in a run's notes, advocate briefs and answer that appear nowhere in the run's evidence sheets or report. A number matches when it has the same value (22.8 = 22.80). It proves a figure is in the data, NOT that it is used for the right thing (read the answer for direction). Usage: ground_check.py run_dir"""
import glob
import os
import re
import sys

NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def values(text: str) -> set:
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)      # 233,029,999 is one number, not 999
    return {float(n) for n in NUM.findall(text)}


def ungrounded(run: str) -> dict:
    pool = set()
    for f in glob.glob(run + "/evidence/*.md") + [run + "/decision.md", run + "/report.json"]:
        if os.path.exists(f):
            pool |= values(open(f, encoding="utf-8").read())
    pool |= {round(p / 1e6, 1) for p in pool if p >= 1e5}      # a squad value of 34181000 is written "34.2m"
    out = {}
    for f in sorted(glob.glob(run + "/notes/*.md") + glob.glob(run + "/advocates/*.md") + [run + "/answer.md"]):
        if os.path.exists(f):
            body = open(f, encoding="utf-8").read().split("\n\nMarket comparison after the run", 1)[0]      # the stamped market line is value.py's, not the analyst's
            miss = sorted(v for v in values(body) if v not in pool and not any(abs(v - p) < 0.051 * max(1, abs(p)) / 10 for p in pool if abs(v - p) < 0.06))
            out[os.path.relpath(f, run)] = miss
    return out


if __name__ == "__main__":
    for name, miss in ungrounded(sys.argv[1]).items():
        print(f"{name}: {len(miss)} not in the evidence {miss[:40]}")
