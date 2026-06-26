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


def _module_source_files(repo_root):
    """Repo source files currently imported in this process (``sys.modules``).

    This is the code a long-running loop actually depends on. Scoping the source
    fingerprint to these files means a commit to an unrelated module (e.g. a
    reporting or calibration module a collection loop never imports) does not
    flip the loop to stale and tear down collection cadence. Only changes to code
    the loop runs trigger a current-code re-adoption.
    """
    repo_root = Path(repo_root).resolve()
    # Restrict to the project's own source files (the same set the whole-tree
    # fingerprint covers). This excludes third-party dependencies under venv/
    # site-packages, which live inside the repo root and would otherwise dwarf
    # the scope and never change anyway.
    source_set = set()
    for path in _source_files(repo_root):
        try:
            source_set.add(path.resolve())
        except OSError:
            continue
    rels = set()
    for module in list(sys.modules.values()):
        file_attr = getattr(module, "__file__", None)
        if not file_attr:
            continue
        try:
            path = Path(file_attr).resolve()
        except OSError:
            continue
        if path not in source_set:
            continue
        rels.add(path.relative_to(repo_root).as_posix())
    return sorted(rels)


def _fingerprint_relpaths(repo_root, rel_paths):
    repo_root = Path(repo_root)
    digest = hashlib.sha256()
    count = 0
    for rel in sorted(set(rel_paths)):
        path = repo_root / rel
        try:
            with path.open("rb") as handle:
                digest.update(rel.encode("utf-8"))
                digest.update(b"\0")
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
                digest.update(b"\0")
                count += 1
        except OSError:
            # A scoped file that vanished is itself a change; fold its name in so
            # deletion is detected rather than silently ignored.
            digest.update(rel.encode("utf-8"))
            digest.update(b"\1")
    return {"fingerprint": digest.hexdigest()[:16], "file_count": count}


def get_runtime_identity(repo_root=None, scope_files=None):
    """Capture runtime code identity.

    ``scope_files`` controls the source fingerprint scope:

    * ``None`` (default): the whole source tree, unchanged for all existing
      consumers (taker, soak gates, fleet, etc.).
    * ``"loaded"``: only the repo source files this process has imported.
    * an explicit iterable of repo-relative paths: re-fingerprint exactly those
      files (used to recompute a comparable "current" identity for a recorded,
      scoped identity).
    """
    repo_root = Path(repo_root or REPO_ROOT)
    branch, commit = _git_head_identity(repo_root)
    scope = None
    scope_list = None
    if scope_files is None:
        source = source_tree_fingerprint(repo_root)
    else:
        scope = "loaded_modules"
        scope_list = _module_source_files(repo_root) if scope_files == "loaded" else sorted(set(scope_files))
        source = _fingerprint_relpaths(repo_root, scope_list)
    identity = {
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
    if scope is not None:
        identity["source_scope"] = scope
        identity["source_scope_files"] = scope_list
    return identity


def current_identity_for(recorded, repo_root=None):
    """Build a 'current' identity comparable to ``recorded``'s fingerprint scope.

    If ``recorded`` was captured with a scoped (loaded-modules) fingerprint, the
    current identity is re-fingerprinted over exactly the same recorded file set,
    so the comparison reflects only changes to that code. Legacy whole-tree
    identities fall back to the whole-tree fingerprint, preserving behaviour.
    """
    root = repo_root or (recorded or {}).get("repo_root") or REPO_ROOT
    scope_files = (recorded or {}).get("source_scope_files")
    if scope_files:
        return get_runtime_identity(root, scope_files=scope_files)
    return get_runtime_identity(root)


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
