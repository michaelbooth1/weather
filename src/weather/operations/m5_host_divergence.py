"""M5 pilot: which tips the CI Windows lane plus the preflight could vouch for (shadow only).

Swarm L option M5 (owner decision 2026-10-05: PILOT_FIRST as a shadow dual run,
NO to adoption now): for roll-free tips, the CI Windows lane plus the landing
preflight might one day replace the host bounded suite. A tip is disqualified
when the CI runner cannot stand in for the capture host:

- it adds or changes a **host-divergent test**: one that exercises identity,
  ACL or Task Scheduler APIs (the 10-04 ``WORKGROUP\\micha`` class), whose
  result depends on the machine account, logon type or ACLs of the host;
- it adds or changes a **Windows-only test in no CI shard** (``windows-
  qualification.yml``), which no CI lane would run at all;
- it touches a **hash-pinned file** (named beside a pinned SHA-256 at the head,
  as ``eof_newline_class`` defines it), whose frozen hash binds host tasks.

``--enumerate`` lists the host-divergent and unsharded Windows-only test files
at a ref; the report asks for that enumeration before any adoption. ``--base``
/``--head`` classifies one tip. Either way the verdict grants nothing: the host
suite still runs, and the concordance (CI, preflight, host suite per landing)
is recorded beside it. Exit codes: 0 eligible (or enumeration done), 1 not
eligible, 2 error.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

from weather.operations.eof_newline_class import ClassError, _git, hash_pinned_paths
from weather.paths import REPO_ROOT

SCHEMA = "m5_host_divergence_v1"
WORKFLOW = ".github/workflows/windows-qualification.yml"
HOST_API_RE = re.compile(
    r"ScheduledTask|schtasks|icacls|Get-Acl|Set-Acl|WindowsIdentity|whoami|WORKGROUP|\bS4U\b|LogonType"
    r"|win32security|GetUserName|getpass\.getuser|USERDOMAIN"
)
_WINDOWS = {("os.name", "nt"), ("sys.platform", "win32"), ("__import__('os').name", "nt")}


def _platform_compare(node: ast.AST) -> str | None:
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1):
        return None
    right = node.comparators[0]
    if isinstance(right, ast.Constant) and (ast.unparse(node.left), right.value) in _WINDOWS:
        return type(node.ops[0]).__name__
    return None


def windows_only(source: str) -> bool:
    """A test module that skips off Windows (the shard test's own rule)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if _platform_compare(node) == "NotEq":
            return True
        if (isinstance(node, ast.Call) and node.args and ast.unparse(node.func).endswith("skipUnless")
                and any(_platform_compare(sub) == "Eq" for sub in ast.walk(node.args[0]))):
            return True
    return False


def _show(repo_root: Path, ref: str, path: str) -> str:
    return _git(repo_root, "show", f"{ref}:{path}").decode("utf-8", errors="replace")


def _sharded(repo_root: Path, ref: str) -> set[str]:
    try:
        text = _show(repo_root, ref, WORKFLOW)
    except ClassError:
        return set()
    return set(re.findall(r"tests/\S+?\.py", text))


def _test_files(repo_root: Path, ref: str) -> list[str]:
    out = _git(repo_root, "ls-tree", "-r", "--name-only", ref, "--", "tests")
    return [p for p in out.decode().splitlines()
            if p.endswith(".py") and p.rsplit("/", 1)[-1].startswith("test_")]


def test_kinds(repo_root: Path, ref: str, paths: list[str]) -> dict[str, list[str]]:
    """``{path: [kinds]}`` for test files that are host-divergent or unsharded Windows-only."""
    sharded = _sharded(repo_root, ref)
    kinds: dict[str, list[str]] = {}
    for path in paths:
        source = _show(repo_root, ref, path)
        found = []
        if HOST_API_RE.search(source):
            found.append("host_divergent_api")
        if windows_only(source) and path not in sharded:
            found.append("windows_only_unsharded")
        if found:
            kinds[path] = found
    return kinds


def enumerate_tests(repo_root: Path, ref: str) -> dict[str, Any]:
    sha = _git(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    kinds = test_kinds(repo_root, sha, _test_files(repo_root, sha))
    return {
        "schema": SCHEMA, "mode": "enumerate", "ref": sha,
        "host_divergent_api": sorted(p for p, k in kinds.items() if "host_divergent_api" in k),
        "windows_only_unsharded": sorted(p for p, k in kinds.items() if "windows_only_unsharded" in k),
    }


def classify_tip(repo_root: Path, base: str, head: str) -> dict[str, Any]:
    base_sha = _git(repo_root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    head_sha = _git(repo_root, "rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
    out = _git(repo_root, "diff", "--name-only", "--no-renames", "--diff-filter=AMRT", base_sha, head_sha)
    changed = [p for p in out.decode().splitlines() if p]
    tests = [p for p in changed if p.startswith("tests/") and p.endswith(".py")
             and p.rsplit("/", 1)[-1].startswith("test_")]
    disqualifiers = [
        {"path": path, "kind": kind}
        for path, found in test_kinds(repo_root, head_sha, tests).items() for kind in found
    ]
    disqualifiers += [{"path": path, "kind": "hash_pinned"}
                      for path in sorted(hash_pinned_paths(repo_root, head_sha, changed))]
    return {
        "schema": SCHEMA, "mode": "tip", "base": base_sha, "head": head_sha,
        "eligible": not disqualifiers, "disqualifiers": disqualifiers, "changed_files": len(changed),
        "grants": "NOTHING: pilot shadow verdict; the host bounded suite still runs",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--enumerate", metavar="REF", help="list host-divergent test files at REF")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--json", type=Path, help="write the result here (a new file)")
    args = parser.parse_args(argv)
    if bool(args.enumerate) == bool(args.base and args.head):
        parser.error("give either --enumerate REF or both --base and --head")
    root = args.repo_root.resolve()
    try:
        result = enumerate_tests(root, args.enumerate) if args.enumerate else classify_tip(root, args.base, args.head)
    except ClassError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.json:
        with args.json.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
    print(text)
    return 0 if args.enumerate or result["eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
