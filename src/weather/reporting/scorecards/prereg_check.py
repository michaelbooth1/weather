"""Pre-registration checker: refuse a rule file that lacks any section the checklist requires.

The checklist is ``docs/operations/PREREGISTRATION_CHECKLIST.md``. A rule file must carry five headed
sections (any Markdown heading level; an optional ``(a)``..``(e)`` prefix is allowed), each with the
content named below. A section containing ``TBD`` or ``TODO`` does not count.

- (a) ``Positive control``: the control and its expected values (at least one decimal number).
- (b) ``Comparator fairness``: the comparator gets the same floor and calibration as the candidate
  (must name both ``floor`` and ``calibration``).
- (c) ``Targeted loss slice``: the slice and its expected size from the loss atlas (an atlas sha256
  prefix of >= 12 hex characters and a number).
- (d) ``MDE and clusters``: the MDE (a decimal number) and the cluster count (``N clusters`` or
  ``clusters: N``).
- (e) ``Dev-window reuse``: the reuse count from ``DEV_WINDOW_LEDGER.md`` (names the ledger and an integer).

Text-only and offline; it reads one file and prints one JSON line.

    python -m weather.reporting.scorecards.prereg_check <rule.md>

Exit 0 when every section is present, 2 when any is missing or the file cannot be read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
PLACEHOLDER = re.compile(r"\b(TBD|TODO)\b")
DECIMAL = re.compile(r"[-+−]?\d*\.\d+")
NUMBER = re.compile(r"[-+−]?\d+(?:\.\d+)?")

SECTIONS = (
    ("a", "positive control", re.compile(r"positive\s+control", re.I),
     (("expected values (a decimal number)", lambda b: DECIMAL.search(b)),)),
    ("b", "comparator fairness", re.compile(r"comparator\s+fairness", re.I),
     (("the comparator's floor", lambda b: re.search(r"\bfloor", b, re.I)),
      ("the comparator's calibration", lambda b: re.search(r"calibrat", b, re.I)))),
    ("c", "targeted loss slice", re.compile(r"targeted\s+loss\s+slice", re.I),
     (("a loss-atlas sha256 (>= 12 hex)", lambda b: re.search(r"\b[0-9a-f]{12,64}\b", b)),
      ("the expected size (a number)", lambda b: NUMBER.search(re.sub(r"\b[0-9a-f]{12,64}\b", "", b))))),
    ("d", "MDE and clusters", re.compile(r"\bMDE\b", re.I),
     (("the MDE (a decimal number)", lambda b: DECIMAL.search(b)),
      ("the cluster count", lambda b: re.search(r"\d+\s+(?:\w+\s+)?clusters?\b|clusters?\s*[:=]\s*\d+", b, re.I)))),
    ("e", "dev-window reuse", re.compile(r"dev[-\s]window\s+reuse", re.I),
     (("the ledger (DEV_WINDOW_LEDGER)", lambda b: re.search(r"DEV_WINDOW_LEDGER", b)),
      ("the reuse count (an integer)", lambda b: re.search(r"\b\d+\b", b)))),
)


def split_sections(text):
    """[(heading title, body)] for every Markdown heading outside fenced code."""
    out, title, body, fenced = [], None, [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else HEADING.match(line)
        if m:
            if title is not None:
                out.append((title, "\n".join(body)))
            title, body = m.group(2), []
        elif title is not None:
            body.append(line)
    if title is not None:
        out.append((title, "\n".join(body)))
    return out


def check_text(text):
    """Return a list of human-readable problems (empty when the rule file passes)."""
    sections = split_sections(text)
    problems = []
    for letter, name, pattern, requirements in SECTIONS:
        found = [body for title, body in sections if pattern.search(title)]
        if not found:
            problems.append(f"({letter}) {name}: section missing")
            continue
        body = "\n".join(found)
        if PLACEHOLDER.search(body):
            problems.append(f"({letter}) {name}: contains a TBD/TODO placeholder")
            continue
        for what, test in requirements:
            if not test(body):
                problems.append(f"({letter}) {name}: does not state {what}")
    return problems


def check_file(path):
    raw = Path(path).read_bytes()
    problems = check_text(raw.decode("utf-8-sig"))
    return {"rule": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "verdict": "PASS" if not problems else "REFUSED", "problems": problems}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.reporting.scorecards.prereg_check",
                                     description="Refuse a pre-registration rule file missing a required section.")
    parser.add_argument("rule")
    args = parser.parse_args(argv)
    try:
        result = check_file(args.rule)
    except (OSError, UnicodeDecodeError) as exc:
        print(json.dumps({"rule": args.rule, "verdict": "REFUSED", "problems": [f"unreadable: {exc}"]}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
