"""List merged topic branches that are past the retirement deadline.

Read-only. The branch lifecycle rule in ``docs/git-workflow.md`` retires a
merged ``codex/*`` branch within seven days of landing. A branch is overdue when
its tip is already an ancestor of the first-parent ``master`` commit that was
current seven days ago, so the whole check is three git calls over the cached
remote-tracking refs: it never fetches, deletes or writes anything.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from weather.paths import REPO_ROOT

DEFAULT_REMOTE = "origin"
DEFAULT_BASE = "master"
DEFAULT_PREFIX = "codex/"
DEFAULT_MAX_AGE_DAYS = 7


class GitReadError(RuntimeError):
    """A read-only git query failed."""


def _git(repo_root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise GitReadError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _merged_refs(repo_root: Path, commit: str, ref_prefix: str) -> dict[str, str]:
    rows = _git(
        repo_root,
        "for-each-ref",
        f"--merged={commit}",
        "--format=%(refname)%09%(objectname)",
        ref_prefix,
    )
    refs: dict[str, str] = {}
    for row in rows:
        name, _, sha = row.partition("\t")
        refs[name] = sha
    return refs


def find_overdue_branches(
    repo_root: Path,
    *,
    now: datetime,
    remote: str = DEFAULT_REMOTE,
    base: str = DEFAULT_BASE,
    prefix: str = DEFAULT_PREFIX,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Return merged and overdue ``<remote>/<prefix>*`` branches against ``<remote>/<base>``."""

    base_ref = f"refs/remotes/{remote}/{base}"
    ref_prefix = f"refs/remotes/{remote}/{prefix}"
    strip = f"refs/remotes/{remote}/"
    cutoff = now - timedelta(days=max_age_days)
    base_tip = _git(repo_root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")[0]
    cutoff_rows = _git(
        repo_root,
        "rev-list",
        "-1",
        "--first-parent",
        f"--before={int(cutoff.timestamp())}",
        base_ref,
    )
    cutoff_commit = cutoff_rows[0] if cutoff_rows else None
    merged = _merged_refs(repo_root, base_tip, ref_prefix)
    overdue = _merged_refs(repo_root, cutoff_commit, ref_prefix) if cutoff_commit else {}
    return {
        "ok": True,
        "remote": remote,
        "base": f"{remote}/{base}",
        "base_commit": base_tip,
        "max_age_days": max_age_days,
        "cutoff_utc": cutoff.astimezone(timezone.utc).isoformat(),
        "cutoff_base_commit": cutoff_commit,
        "merged_count": len(merged),
        "overdue": [
            {"branch": name[len(strip):], "tip": sha} for name, sha in sorted(overdue.items())
        ],
        "source": "cached remote-tracking refs; run `git fetch --prune` first for a current view",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--json", action="store_true", help="print the JSON payload")
    args = parser.parse_args(argv)
    try:
        payload = find_overdue_branches(
            args.repo_root,
            now=datetime.now(timezone.utc),
            remote=args.remote,
            base=args.base,
            prefix=args.prefix,
            max_age_days=args.max_age_days,
        )
    except (GitReadError, OSError) as exc:
        payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload) if args.json else f"merged-branch check failed: {exc}")
        return 1
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(
        f"{payload['merged_count']} merged {args.prefix}* branch(es) on {payload['base']}; "
        f"{len(payload['overdue'])} merged more than {args.max_age_days} days ago"
    )
    for row in payload["overdue"]:
        print(f"  {row['branch']} {row['tip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
