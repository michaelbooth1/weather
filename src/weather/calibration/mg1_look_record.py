"""MG-1 release-record writer: commit MG-1's look receipt byte-exact and write the MG-1 look record.

The MG-1 counterpart of ``b_look_record`` (``claude/b-look-record-writer-20261103`` @ ``24a4e70fc``), which mirrors
ruling R14 (4) and B-1 Clarification 6 step 6. MG-1's record is not R14-bound: no R14 registry entry names it, so
the rules below are ``b_look_record``'s rules (cited by name) with MG-1's rule sha and paths. After MG-1's look has
its receipt, master lands ``docs/research/mg1-look-record/mg1-look-record.md`` in a docs head. This module prepares
that head's files in a checkout, without committing:

1. it copies MG-1's receipt (``mg1_look_receipt.json``; on the host ``data/mg1_look/receipt-<rule>.json``)
   unmodified to a repo path (mode "x");
2. it adds the line ``<receipt_path> -text`` at the end of ``.gitattributes``;
3. it writes the record (mode "x") as ``key: value`` lines: ``rule_sha256`` (MG-1's rule sha), ``receipt_path``,
   ``receipt_sha256`` (over those bytes) and ``decision_log_row``.

It never parses the receipt, so no verdict or outcome value is read or written. ``--expect-sha256`` (the copy in
the WS never-cleaned archive) must match the receipt's bytes. Every check runs before anything is written, and the
written files are checked again afterwards with the same rules; on any failure the files this call created are
removed and ``.gitattributes`` is restored. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

MG1_RULE_SHA256 = "b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665"  # = mg1_look's pin
RECORD = "docs/research/mg1-look-record/mg1-look-record.md"
RECEIPT_DEFAULT = "docs/research/mg1-look-record/mg1_look_receipt.json"
DECISION_LOG = "docs/operations/DECISION_LOG.md"
GITATTRIBUTES = ".gitattributes"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
RECORD_FIELD = re.compile(r"^(?P<key>[a-z0-9_]+):[ \t]*(?P<value>\S.*?)[ \t]*$", re.M)
RECORD_KEYS = ("rule_sha256", "receipt_path", "receipt_sha256", "decision_log_row")
RECEIPT_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")
DL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # decision_log_row is a date


class RecordRefused(RuntimeError):
    """The record cannot be written so that its own checks pass; nothing is left behind."""


def sha256_bytes(data: bytes) -> str:
    """Raw bytes, no line-ending normalisation."""
    return hashlib.sha256(data).hexdigest()


def receipt_path_problem(path: str) -> str | None:
    """A repo-relative path with no ``.`` or ``..`` segment (b_look_record.receipt_path_problem)."""
    if not RECEIPT_PATH.match(path) or {".", ".."} & set(path.split("/")):
        return f"receipt_path {path!r} is not a repo-relative path"
    return None


def decision_log_rows(decision_log: str, row: str) -> list[str]:
    """DECISION_LOG lines of the date ``row`` (b_look_record.decision_log_rows)."""
    if not DL_DATE.match(row):
        return []
    return [line for line in decision_log.splitlines() if line.startswith(f"| {row} |")]


def receipt_attribute_problem(gitattributes: str, path: str) -> str | None:
    """``path`` is made non-text by an exact-path line with ``-text`` or ``binary``, with no later line setting text
    again (b_look_record.receipt_attribute_problem; fail-closed, so the line goes last)."""
    exact_at = None
    for index, line in enumerate(gitattributes.splitlines()):
        tokens = line.split()
        if not tokens or tokens[0].startswith(("#", "[attr]")):
            continue
        sets_text = any(t == "text" or t.startswith("text=") or t == "!text" for t in tokens[1:])
        if tokens[0] in (path, "/" + path) and ("-text" in tokens[1:] or "binary" in tokens[1:]) and not sets_text:
            exact_at = index
        elif sets_text:
            exact_at = None
    if exact_at is None:
        return f"receipt must be committed byte-exact: add '{path} -text' to .gitattributes in the same head"
    return None


def with_attribute(gitattributes: bytes, path: str) -> bytes:
    """``.gitattributes`` with ``<path> -text`` appended as its last line, keeping the file's line ending."""
    newline = b"\r\n" if b"\r\n" in gitattributes else b"\n"
    body = gitattributes if not gitattributes or gitattributes.endswith(b"\n") else gitattributes + newline
    return body + f"{path} -text".encode("utf-8") + newline


def record_fields(text: str) -> tuple[dict[str, str], list[str]]:
    """The record's known ``key: value`` fields, and any repeated key."""
    fields: dict[str, str] = {}
    problems = []
    for m in RECORD_FIELD.finditer(text):
        if m.group("key") not in RECORD_KEYS:
            continue
        if m.group("key") in fields:
            problems.append(f"release record field {m.group('key')} appears more than once")
        fields[m.group("key")] = m.group("value")
    return fields, problems


def record_text(fields: dict[str, str]) -> str:
    """The record: a title, one ``key: value`` line per field, and no outcome value."""
    lines = ["# MG-1 look record", "",
             "MG-1 release record (mirrors b_look_record; not R14-bound). No outcome values.", ""]
    lines += [f"{key}: {fields[key]}" for key in RECORD_KEYS if key in fields]
    return "\n".join(lines) + "\n"


def record_problems(text: str, rule_sha256: str, decision_log: str, root: Path) -> list[str]:
    """The checks on a present record in checkout ``root`` (b_look_record.record_problems, look branch)."""
    fields, problems = record_fields(text)
    row = fields.get("decision_log_row", "")
    if not decision_log_rows(decision_log, row):
        problems.append(f"release record decision_log_row {row!r} names no DECISION_LOG row")
    if not rule_sha256 or fields.get("rule_sha256") != rule_sha256:
        problems.append(f"release record rule_sha256 {fields.get('rule_sha256')!r} is not MG-1's rule sha "
                        f"{rule_sha256!r}")
    receipt_sha = fields.get("receipt_sha256", "")
    if not HEX64.match(receipt_sha):
        problems.append(f"release record receipt_sha256 {receipt_sha!r} is not 64 lowercase hex")
    receipt_path = fields.get("receipt_path", "")
    attributes = root / GITATTRIBUTES
    if (problem := receipt_path_problem(receipt_path)) is not None:
        problems.append(f"release record {problem}")
    elif not (root / receipt_path).is_file():
        problems.append(f"release record receipt_path {receipt_path} is not in the checkout")
    elif attribute := receipt_attribute_problem(
            attributes.read_text(encoding="utf-8") if attributes.is_file() else "", receipt_path):
        problems.append(attribute)
    elif sha256_bytes((root / receipt_path).read_bytes()) != receipt_sha:
        problems.append(f"release record receipt_sha256 is not the sha256 of the bytes of {receipt_path}")
    return problems


def _preflight(root, receipt_path, decision_log_row, rule_sha256):
    problems = []
    if (root / RECORD).exists():
        problems.append(f"{RECORD} exists: one release record")
    if not HEX64.match(rule_sha256 or ""):
        problems.append(f"rule sha {rule_sha256!r} is not 64 lowercase hex")
    log = root / DECISION_LOG
    decision_log = log.read_text(encoding="utf-8") if log.is_file() else ""
    if not decision_log_rows(decision_log, decision_log_row):
        problems.append(f"decision_log_row {decision_log_row!r} names no DECISION_LOG row")
    if (problem := receipt_path_problem(receipt_path)) is not None:
        problems.append(problem)
    elif (root / receipt_path).exists():
        problems.append(f"{receipt_path} exists: the receipt copy is written once")
    return problems, decision_log


def _write_or_undo(root, writes, check):
    """Write ``writes`` [(path, bytes, mode)], run ``check()``; on any failure undo every write and refuse."""
    attributes = root / GITATTRIBUTES
    saved = attributes.read_bytes() if attributes.is_file() else None
    created = []
    try:
        for path, data, mode in writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            if mode == "x":
                with open(path, "xb") as handle:
                    created.append(path)
                    handle.write(data)
            else:
                path.write_bytes(data)
        problems = check()
        if problems:
            raise RecordRefused(f"the written record fails its checks: {problems}")
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        if saved is None:
            attributes.unlink(missing_ok=True)
        else:
            attributes.write_bytes(saved)
        raise


def write_look_record(*, root, receipt, decision_log_row, expect_sha256, receipt_path=RECEIPT_DEFAULT,
                      rule_sha256=MG1_RULE_SHA256):
    """Copy ``receipt`` to ``receipt_path`` in checkout ``root``, add its ``-text`` line and write the record."""
    root = Path(root)
    data = Path(receipt).read_bytes()
    receipt_sha = sha256_bytes(data)
    problems, decision_log = _preflight(root, receipt_path, decision_log_row, rule_sha256)
    if receipt_sha != expect_sha256:
        problems.append(f"the receipt's sha256 {receipt_sha} is not the expected archive copy's {expect_sha256}")
    if problems:
        raise RecordRefused("; ".join(problems))
    attributes = root / GITATTRIBUTES
    fields = {"rule_sha256": rule_sha256, "receipt_path": receipt_path, "receipt_sha256": receipt_sha,
              "decision_log_row": decision_log_row}
    _write_or_undo(root, [(root / receipt_path, data, "x"),
                          (attributes, with_attribute(attributes.read_bytes() if attributes.is_file() else b"",
                                                      receipt_path), "w"),
                          (root / RECORD, record_text(fields).encode("utf-8"), "x")],
                   lambda: record_problems((root / RECORD).read_text(encoding="utf-8"), rule_sha256, decision_log,
                                           root))
    return {"record": RECORD, **fields, "commit": [receipt_path, GITATTRIBUTES, RECORD]}


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.mg1_look_record",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="the checkout that will carry the docs head")
    parser.add_argument("--receipt", required=True, help="MG-1's look receipt (receipt-<rule>.json)")
    parser.add_argument("--expect-sha256", required=True, help="sha256 of the archive copy of the receipt")
    parser.add_argument("--decision-log-row", required=True, help="the date of the DECISION_LOG row (YYYY-MM-DD)")
    parser.add_argument("--receipt-path", default=RECEIPT_DEFAULT)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = write_look_record(root=args.root, receipt=args.receipt, decision_log_row=args.decision_log_row,
                                   expect_sha256=args.expect_sha256, receipt_path=args.receipt_path)
    except (RecordRefused, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
