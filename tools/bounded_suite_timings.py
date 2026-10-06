"""Regenerate ``tests/bounded_suite_file_timings.json`` from Windows JUnit XML.

The bounded worktree suite (``scripts/ops/bounded_worktree_test_suite.ps1``)
packs test files into chunks by these per-file seconds. Only grouping depends
on the table: the file set, the per-chunk cap and the chunk count do not.

Each ``--run`` is a glob for the JUnit files of one complete Windows run (for
example the 24 chunk files of one bounded-suite run). A file's seconds are the
sum of its test cases in a run, and the median across runs. Files absent from
every run fall back to ``default_seconds`` in the suite, which is the median of
the measured files. Output is deterministic for the same inputs.

    python tools/bounded_suite_timings.py --run "C:/path/run1/*.xml" \
        --source "workstation bounded-suite emulation, <date>, <sha>"
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TABLE = REPO_ROOT / "tests" / "bounded_suite_file_timings.json"
TEST_FILE = re.compile(r"^tests/(?:.*/)?test_[^/]*\.py$")


def tracked_test_files(repo: Path) -> set[str]:
    rows = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--", "tests"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    return {row.replace("\\", "/") for row in rows if TEST_FILE.match(row.replace("\\", "/"))}


def file_for_classname(classname: str, tracked: set[str]) -> str | None:
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end]) + ".py"
        if candidate in tracked:
            return candidate
    return None


def run_seconds(pattern: str, tracked: set[str]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise SystemExit(f"no JUnit files match {pattern}")
    for path in paths:
        for case in ET.parse(path).getroot().iter("testcase"):
            file = file_for_classname(case.get("classname") or "", tracked)
            if file is not None:
                totals[file] += float(case.get("time") or 0.0)
    return dict(totals)


def build_table(runs: list[dict[str, float]], source: str) -> dict:
    files = sorted({name for run in runs for name in run})
    seconds = {
        name: round(statistics.median([run[name] for run in runs if name in run]), 1)
        for name in files
    }
    default = round(statistics.median(seconds.values()), 1) if seconds else 1.0
    return {
        "format_version": 1,
        "source": source,
        "default_seconds": max(default, 0.1),
        "files": seconds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", type=Path, default=TABLE)
    args = parser.parse_args()
    tracked = tracked_test_files(REPO_ROOT)
    table = build_table([run_seconds(pattern, tracked) for pattern in args.run], args.source)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(table, indent=1, sort_keys=False) + "\n")
    print(f"wrote {args.out} files={len(table['files'])} default={table['default_seconds']}")


if __name__ == "__main__":
    main()
