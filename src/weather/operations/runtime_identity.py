"""Runtime code identity helpers for long-running local services.

The loop status files need to answer two different questions:

* Which git revision did this process start from?
* Does the running source tree still match the code on disk?

The source fingerprint deliberately covers Python code, supervisor scripts, the
Streamlit app, and requirements, while excluding model/data artifacts.
"""
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import REPO_ROOT

IDENTITY_SCHEMA_VERSION = "runtime_identity_v0.1"
SOURCE_PATTERNS = (
    "app.py",
    "app/**/*.py",
    "requirements.txt",
    "src/**/*.py",
    "scripts/**/*.ps1",
    "tools/**/*",
)
GIT_STATUS_PATHS = ("app.py", "app", "requirements.txt", "src", "scripts", "tools")


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _creationflags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run_git(args, repo_root):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=_creationflags(),
        )
    except (OSError, TypeError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip() if isinstance(result.stdout, str) else ""


def _source_files(repo_root):
    files = []
    for pattern in SOURCE_PATTERNS:
        files.extend(path for path in repo_root.glob(pattern) if path.is_file())
    return sorted(set(files), key=lambda path: path.relative_to(repo_root).as_posix())


def source_tree_fingerprint(repo_root=None):
    repo_root = Path(repo_root or REPO_ROOT)
    digest = hashlib.sha256()
    count = 0
    for path in _source_files(repo_root):
        try:
            rel = path.relative_to(repo_root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
            digest.update(b"\0")
            count += 1
        except OSError:
            continue
    return {
        "fingerprint": digest.hexdigest()[:16],
        "file_count": count,
    }


def get_runtime_identity(repo_root=None):
    repo_root = Path(repo_root or REPO_ROOT)
    commit = _run_git(["rev-parse", "--short=12", "HEAD"], repo_root) or "unknown"
    branch = (
        _run_git(["branch", "--show-current"], repo_root)
        or _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
        or "unknown"
    )
    status = _run_git(["status", "--porcelain", "--", *GIT_STATUS_PATHS], repo_root)
    diff = "\n".join(
        item
        for item in (
            _run_git(["diff", "--", *GIT_STATUS_PATHS], repo_root),
            _run_git(["diff", "--cached", "--", *GIT_STATUS_PATHS], repo_root),
            status,
        )
        if item
    )
    dirty_fingerprint = hashlib.sha256(diff.encode("utf-8")).hexdigest()[:12] if diff else None
    source = source_tree_fingerprint(repo_root)
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "captured_at_utc": utc_now_iso(),
        "repo_root": str(repo_root),
        "git_branch": branch,
        "git_commit": commit,
        "git_dirty": bool(status),
        "dirty_fingerprint": dirty_fingerprint,
        "source_fingerprint": source["fingerprint"],
        "source_file_count": source["file_count"],
        "python_version": sys.version.split()[0],
    }


def identity_key(identity):
    if not identity:
        return None
    source = identity.get("source_fingerprint")
    if source:
        return ("source", source)
    return (
        "git",
        identity.get("git_commit"),
        identity.get("dirty_fingerprint"),
        bool(identity.get("git_dirty")),
    )


def identities_match(left, right):
    left_key = identity_key(left)
    right_key = identity_key(right)
    return bool(left_key and right_key and left_key == right_key)


def format_runtime_identity(identity):
    if not identity:
        return "unknown"
    branch = identity.get("git_branch") or "unknown"
    commit = identity.get("git_commit") or "unknown"
    source = identity.get("source_fingerprint") or "unknown"
    if identity.get("git_dirty"):
        dirty = identity.get("dirty_fingerprint") or "dirty"
        return f"{branch}@{commit} dirty:{dirty} src:{source}"
    return f"{branch}@{commit} clean src:{source}"
