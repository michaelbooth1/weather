"""Rule B-1: the one permitted post-binding edit of ``b_scorer.py`` (S0 to S1).

B binds b_scorer sha S0. The only permitted post-binding scorer edit is setting ``MG1_LOOK_ENTRY_SHA256`` by the
dated MG-1 scoring clarification, giving S1 (B-1 clarification of 2026-10-26, section 4). ``s1_problems`` passes
only when S1 differs from S0 in exactly that one assignment line and S1 sets it to a 64-hex string literal. Any
other change fails: another line, a second line, a removed or duplicated constant, a changed line ending.

Pure: it reads the two source files and nothing else. ``python -m weather.calibration.b_scorer_entry_edit
--s0 <bound b_scorer.py> --s1 <b_scorer.py at the look>`` prints the verdict as JSON and exits 1 on a failure.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

CONSTANT = "MG1_LOOK_ENTRY_SHA256"
ASSIGNMENT = re.compile(r"^MG1_LOOK_ENTRY_SHA256 = (?P<value>.+?)(?P<eol>\r?\n)?$")
S1_VALUE = re.compile(r'^"(?P<sha>[0-9a-f]{64})"$')


def _assignments(lines):
    return [i for i, line in enumerate(lines) if ASSIGNMENT.match(line)]


def s1_problems(s0: bytes, s1: bytes):
    """``(problems, recorded_sha)``: ``problems`` is empty when S0 to S1 is exactly the permitted edit."""
    try:
        a = s0.decode("utf-8").splitlines(keepends=True)
        b = s1.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError as exc:
        return [f"a scorer source is not UTF-8: {exc}"], None
    problems = []
    if len(_assignments(a)) != 1:
        problems.append(f"S0 has {len(_assignments(a))} {CONSTANT} assignment lines, not 1")
    if len(_assignments(b)) != 1:
        problems.append(f"S1 has {len(_assignments(b))} {CONSTANT} assignment lines, not 1")
    changes = [op for op in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes() if op[0] != "equal"]
    if not changes:
        problems.append("S1 is identical to S0")
    elif len(changes) != 1 or changes[0][0] != "replace" or changes[0][2] - changes[0][1] != 1 \
            or changes[0][4] - changes[0][3] != 1:
        problems.append(f"S0 to S1 changes {len(changes)} hunk(s) "
                        f"({', '.join(f'{t} S0 {i1 + 1}-{i2} S1 {j1 + 1}-{j2}' for t, i1, i2, j1, j2 in changes)}),"
                        f" not the one {CONSTANT} line")
    else:
        _, i1, _, j1, _ = changes[0]
        old, new = ASSIGNMENT.match(a[i1]), ASSIGNMENT.match(b[j1])
        if not old or not new:
            problems.append(f"the changed line is not the {CONSTANT} assignment (S0 line {i1 + 1})")
        elif (old.group("eol") or "") != (new.group("eol") or ""):
            problems.append(f"the {CONSTANT} line ending changed")
        elif not S1_VALUE.match(new.group("value")):
            problems.append(f"S1 sets {CONSTANT} to {new.group('value')}, not a 64-hex string literal")
    if problems:
        return problems, None
    return [], S1_VALUE.match(ASSIGNMENT.match(b[changes[0][3]]).group("value")).group("sha")


def check(s0_path, s1_path):
    s0, s1 = Path(s0_path).read_bytes(), Path(s1_path).read_bytes()
    problems, recorded = s1_problems(s0, s1)
    return {"pass": not problems, "problems": problems, "s0_sha256": hashlib.sha256(s0).hexdigest(),
            "s1_sha256": hashlib.sha256(s1).hexdigest(), "mg1_look_entry_sha256": recorded}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--s0", required=True, help="b_scorer.py as bound by B-1 (sha S0)")
    parser.add_argument("--s1", required=True, help="b_scorer.py the B look runs (sha S1)")
    args = parser.parse_args(argv)
    result = check(args.s0, args.s1)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
