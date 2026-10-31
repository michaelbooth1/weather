"""M13 pilot: tool-verified "EOF-newline-only" diff class (shadow only, grants nothing).

Swarm L option M13 (owner decision 2026-10-05, PILOT_FIRST with the narrower
predicate): a branch whose only change is a byte-exact end-of-file newline fix
could one day skip the bounded suite. No ``git diff`` flag set may grant that:
``-w`` hides Python re-indentation, and ``--ignore-space-at-eol
--ignore-blank-lines`` hides whitespace removed inside Python triple-quoted
strings and PowerShell here-strings. The predicate is therefore per file and
byte-exact:

    new == old.rstrip(b"\\n") + b"\\n"  and  new != old

for every changed file, with only in-place modifications (no add, delete,
rename or mode change) and with these paths excluded:

- YAML (``*.yml``/``*.yaml``): workflow and config semantics;
- ``scripts/ops/**``: executed by scheduled tasks and bound by hash into
  integration attempts, so even a newline changes a frozen hash;
- any path named on a line that also carries a 64-hex SHA-256 literal in a
  tracked file at the head (a pinned hash).

This module only classifies. The host ``roll_verdict.ps1`` must still exit 0,
and the bounded suite still runs: during the pilot a landing records this
verdict beside its real suite result. Exit codes: 0 in class, 1 not in class,
2 error.

CLI: ``python -m weather.operations.eof_newline_class --base <ref> --head <ref>
[--repo-root <path>] [--json <out>]``
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from weather.paths import REPO_ROOT

SCHEMA = "eof_newline_class_v1"
EXCLUDED_SUFFIXES = (".yml", ".yaml")
EXCLUDED_PREFIXES = ("scripts/ops/",)
SHA256_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")


class ClassError(RuntimeError):
    """The classification could not be computed (bad ref, git failure)."""


def _git(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, check=False)
    if result.returncode:
        raise ClassError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def eof_newline_only(old: bytes, new: bytes) -> bool:
    """The M13 byte predicate for one file."""
    return new != old and new == old.rstrip(b"\n") + b"\n"


PIN_SOURCES = ("*.ps1", "*.psm1", "*.py", "*.json")


def hash_pinned_paths(repo_root: Path, head: str, candidates: list[str]) -> set[str]:
    """Candidates named on a line with a 64-hex literal in code or config at ``head``.

    Pins live in code and config (PowerShell, Python, JSON), never in prose, where
    receipts cite hashes beside document names. A full repo path (either slash)
    must appear on the line; a bare file name counts only for PowerShell scripts,
    which pins name through ``Join-Path``.
    """
    if not candidates:
        return set()
    pinned: set[str] = set()
    # One grep for lines carrying a 64-hex literal; -I skips binaries.
    try:
        out = _git(repo_root, "grep", "-I", "-h", "-E", "[0-9a-fA-F]{64}", head, "--", *PIN_SOURCES)
    except ClassError:
        out = b""  # no matching line: git grep exits 1
    lines = [line for line in out.decode("utf-8", errors="replace").splitlines() if SHA256_RE.search(line)]
    for path in candidates:
        names = {path, path.replace("/", "\\")}
        base = path.rsplit("/", 1)[-1]
        if base.lower().endswith((".ps1", ".psm1")):
            names.add(base)
        if any(name in line for line in lines for name in names):
            pinned.add(path)
    return pinned


def classify(repo_root: Path, base: str, head: str) -> dict[str, Any]:
    base_sha = _git(repo_root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    head_sha = _git(repo_root, "rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
    raw = _git(repo_root, "diff", "--raw", "--no-renames", "-z", base_sha, head_sha)
    fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
    changes = []
    for index in range(0, len(fields) - 1, 2):
        meta, path = fields[index], fields[index + 1]
        if not meta:
            continue
        old_mode, new_mode, old_blob, new_blob, status = meta.lstrip(":").split()
        changes.append({"path": path, "status": status, "old_mode": old_mode, "new_mode": new_mode,
                        "old_blob": old_blob, "new_blob": new_blob})
    pinned = hash_pinned_paths(repo_root, head_sha, [change["path"] for change in changes])
    files = []
    for change in changes:
        path = change["path"]
        reason = None
        if change["status"] != "M":
            reason = f"status {change['status']} (only in-place modifications qualify)"
        elif change["old_mode"] != change["new_mode"]:
            reason = "mode change"
        elif path.lower().endswith(EXCLUDED_SUFFIXES):
            reason = "YAML is excluded"
        elif path.startswith(EXCLUDED_PREFIXES):
            reason = "scripts/ops is hash-bound by integration attempts"
        elif path in pinned:
            reason = "named beside a pinned SHA-256"
        else:
            old = _git(repo_root, "cat-file", "blob", change["old_blob"])
            new = _git(repo_root, "cat-file", "blob", change["new_blob"])
            if not eof_newline_only(old, new):
                reason = "not a byte-exact EOF-newline-only change"
        files.append({"path": path, "status": change["status"], "in_class": reason is None, "reason": reason})
    in_class = bool(files) and all(item["in_class"] for item in files)
    return {
        "schema": SCHEMA, "base": base_sha, "head": head_sha, "in_class": in_class,
        "reason": None if in_class else ("no changed files" if not files else "a file is outside the class"),
        "files": files,
        "grants": "NOTHING: pilot shadow verdict; roll_verdict and the bounded suite still decide",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--json", type=Path, help="write the verdict here (a new file)")
    args = parser.parse_args(argv)
    try:
        verdict = classify(args.repo_root.resolve(), args.base, args.head)
    except ClassError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = json.dumps(verdict, indent=2, sort_keys=True)
    if args.json:
        with args.json.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
    print(text)
    return 0 if verdict["in_class"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
