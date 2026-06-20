"""Runtime code identity helpers for long-running local services.

The loop status files need to answer two different questions:

* Which git revision did this process start from?
* Does the running source tree still match the code on disk?

The source fingerprint deliberately covers Python code, supervisor scripts, the
Streamlit app, and requirements, while excluding model/data artifacts.
"""
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import REPO_ROOT

IDENTITY_SCHEMA_VERSION = "runtime_identity_v0.1"
SOURCE_PATTERNS = (
    "app.py",
    "app/**/*.py",
    "sitecustomize.py",
    "weather/**/*.py",
    "requirements.txt",
    "src/**/*.py",
    "scripts/**/*.ps1",
    "tools/**/*",
)
GENERATED_SOURCE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
GENERATED_SOURCE_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log"}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _git_dir(repo_root):
    marker = Path(repo_root) / ".git"
    if marker.is_dir():
        return marker
    if not marker.is_file():
        return None
    text = _read_text(marker)
    prefix = "gitdir:"
    if not text.lower().startswith(prefix):
        return None
    git_dir = Path(text[len(prefix):].strip())
    if not git_dir.is_absolute():
        git_dir = marker.parent / git_dir
    return git_dir


def _read_git_ref(git_dir, ref):
    if not git_dir or not ref or ".." in Path(ref).parts:
        return ""
    direct = _read_text(Path(git_dir) / ref)
    if direct:
        return direct
    packed = _read_text(Path(git_dir) / "packed-refs")
    for line in packed.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "^")):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == ref:
            return parts[0]
    return ""


def _git_head_identity(repo_root):
    git_dir = _git_dir(repo_root)
    if not git_dir:
        return "unknown", "unknown"
    head = _read_text(Path(git_dir) / "HEAD")
    if not head:
        return "unknown", "unknown"
    if head.startswith("ref:"):
        ref = head.partition(":")[2].strip()
        branch = ref.removeprefix("refs/heads/") or ref
        commit = _read_git_ref(git_dir, ref) or "unknown"
        return branch, commit[:12] if commit != "unknown" else commit
    return "detached", head[:12]


def _source_files(repo_root):
    files = []
    for pattern in SOURCE_PATTERNS:
        files.extend(
            path
            for path in repo_root.glob(pattern)
            if path.is_file() and _is_source_identity_file(path)
        )
    return sorted(set(files), key=lambda path: path.relative_to(repo_root).as_posix())


def _is_source_identity_file(path):
    path = Path(path)
    if any(part in GENERATED_SOURCE_PARTS for part in path.parts):
        return False
    return path.suffix.lower() not in GENERATED_SOURCE_SUFFIXES


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
    branch, commit = _git_head_identity(repo_root)
    source = source_tree_fingerprint(repo_root)
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "captured_at_utc": utc_now_iso(),
        "repo_root": str(repo_root),
        "git_branch": branch,
        "git_commit": commit,
        "git_dirty": None,
        "dirty_fingerprint": None,
        "source_fingerprint": source["fingerprint"],
        "source_file_count": source["file_count"],
        "identity_source": "git_filesystem",
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
    if identity.get("git_dirty") is None:
        return f"{branch}@{commit} src:{source}"
    return f"{branch}@{commit} clean src:{source}"
