"""Landing preflight pilots: non-binding shadows the owner approved as pilots (Swarm L M13, M3b).

Nothing here changes a verdict, a check status other than its own INFO row, or an
exit code.  Each pilot reports what an adopted rule *would* conclude so that the
rule can be judged on real nights before anyone relies on it.

* ``eof_newline_only`` (M13 pilot, object phase, always INFO).  Byte-exact: a
  changed file qualifies only when ``new == old.rstrip(b"\\n") + b"\\n"``, i.e. the
  two blobs are equal once their trailing ``\\n``/``\\r\\n`` run is stripped and the
  new blob ends in exactly one LF.  No CR change, no mid-file change, so no
  literal parsing is needed (no Python or PowerShell string can be open at EOF).
  YAML is excluded (``|+`` keep-chomping makes trailing newlines content), as is
  every hash-frozen file, derived from the tree (:func:`hash_frozen_paths`).
  The row reports ``suite_skip_eligible`` and grants nothing.
* ``m3b_binding_shadow`` (M3b pilot): an INFO row inside ``docs_transaction``
  that computes what binding the night's unchanged reviews to the **final**
  integration commit would conclude.  :func:`strictest` combines it with the real
  status, so the shadow can only add a failure, never remove one.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from typing import Any

from weather.operations.landing_preflight import (
    ERROR,
    FAIL,
    GIT_SAFETY_CONFIG,
    GIT_TIMEOUT_SECONDS,
    INFO,
    PASS,
    PHASE_OBJECTS,
    SKIP,
    WARN,
    CheckRegistry,
    CheckResult,
    CheckSpec,
    PreflightContext,
    _git_env,
)

OWNER = "L-pilots"
BINDING_NOTE = "pilot (non-binding shadow): grants nothing; never changes the verdict or the exit code"

GitBytes = Callable[..., bytes]

# --------------------------------------------------------------------------- git as bytes (no newline translation)


def git_bytes_runner(prefix: Iterable[str], env_extra: dict[str, str] | None = None) -> GitBytes:
    """A git runner returning raw stdout bytes (``text=True`` would translate CRLF)."""

    fixed = [str(p) for p in prefix]

    def run(*args: str, stdin: bytes | None = None, ok: tuple[int, ...] = (0,)) -> bytes:
        argv = ["git", *GIT_SAFETY_CONFIG, "-c", "core.quotepath=false", *fixed, *args]
        proc = subprocess.run(argv, input=stdin, capture_output=True, env=_git_env(env_extra),
                              timeout=GIT_TIMEOUT_SECONDS, check=False)
        if proc.returncode not in ok:
            raise RuntimeError(f"git {' '.join(args[:3])} exited {proc.returncode}: "
                               f"{proc.stderr.decode('utf-8', 'replace')[-600:]}")
        return proc.stdout

    return run


def ctx_git_bytes(ctx: PreflightContext) -> GitBytes:
    return git_bytes_runner(["--git-dir", str(ctx.git_dir)], {"GIT_CONFIG_NOSYSTEM": "1"})


def read_blobs(git: GitBytes, oids: Iterable[str]) -> dict[str, bytes | None]:
    """``git cat-file --batch`` for many blobs at once; ``None`` for a missing object."""

    wanted = [o for o in dict.fromkeys(oids) if o]
    if not wanted:
        return {}
    out = git("cat-file", "--batch", stdin=("\n".join(wanted) + "\n").encode("ascii"))
    blobs: dict[str, bytes | None] = {}
    pos = 0
    for oid in wanted:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode("ascii", "replace").split()
        pos = end + 1
        if len(header) < 3 or header[1] == "missing":
            blobs[oid] = None
            continue
        size = int(header[2])
        blobs[oid] = out[pos:pos + size] if header[1] == "blob" else None
        pos += size + 1
    return blobs


def raw_changes(git: GitBytes, old_tree: str, new_tree: str) -> list[dict[str, str]]:
    """``git diff --raw -z -M`` rows: status, modes, oids, path (and old_path for R/C)."""

    parts = git("diff", "--raw", "-z", "-M", "--no-abbrev", old_tree, new_tree).decode("utf-8", "surrogateescape").split("\0")
    rows, i = [], 0
    while i < len(parts) and parts[i]:
        meta = parts[i].lstrip(":").split()
        row = {"old_mode": meta[0], "new_mode": meta[1], "old_oid": meta[2], "new_oid": meta[3], "status": meta[4][:1]}
        if row["status"] in ("R", "C"):
            row.update(old_path=parts[i + 1], path=parts[i + 2])
            i += 3
        else:
            row["path"] = parts[i + 1]
            i += 2
        rows.append(row)
    return rows


def tree_listing(git: GitBytes, tree: str, *pathspec: str) -> dict[str, str]:
    """``{path: blob oid}`` for every blob under ``pathspec`` in ``tree`` (recursive)."""

    out = git("ls-tree", "-r", "-z", tree, "--", *pathspec).decode("utf-8", "surrogateescape")
    rows: dict[str, str] = {}
    for record in filter(None, out.split("\0")):
        meta, path = record.split("\t", 1)
        _mode, kind, oid = meta.split()
        if kind == "blob":
            rows[path] = oid
    return rows


def texts_of(git: GitBytes, oids: dict[str, str]) -> dict[str, str]:
    blobs = read_blobs(git, oids.values())
    return {p: (blobs.get(o) or b"").decode("utf-8", "replace") for p, o in oids.items()}


# --------------------------------------------------------------------------- the byte-exact predicate (M13)


def eof_newline_only_change(old: bytes, new: bytes) -> bool:
    """True only when ``new == old.rstrip(b"\\n") + b"\\n"`` and the blobs differ.

    Equivalent to: the blobs are equal once the trailing ``\\n``/``\\r\\n`` run is
    stripped, the new blob ends in exactly one LF, and no CR byte changes (a CRLF
    tail can only qualify if it is left untouched, i.e. not changed at all).
    """

    return old != new and new == old.rstrip(b"\n") + b"\n"


def eof_delta(old: bytes, new: bytes) -> dict[str, Any]:
    core_old, core_new = old.rstrip(b"\r\n"), new.rstrip(b"\r\n")
    return {"stripped_equal": core_old == core_new, "old_tail": old[len(core_old):].decode("ascii", "replace"),
            "new_tail": new[len(core_new):].decode("ascii", "replace"),
            "newlines_removed": max(0, old[len(core_old):].count(b"\n") - new[len(core_new):].count(b"\n")),
            "newlines_added": max(0, new[len(core_new):].count(b"\n") - old[len(core_old):].count(b"\n"))}


YAML_SUFFIXES = (".yml", ".yaml")

# --------------------------------------------------------------------------- hash-frozen files, derived from the tree

# Always frozen (OD M13 ruling 5): the merge tool (attempts pin -ExpectedSelfSha256) and the
# registered self-checking scripts.  The derivation below finds these too; the list is a floor.
NAMED_HASH_FROZEN = (
    "scripts/ops/quiet_window_merge.ps1",
    "scripts/ops/boot_recovery.ps1",
    "scripts/ops/health_watchdog.ps1",
    "scripts/ops/status.ps1",
)
_SELF_PIN = re.compile(r"\[string\]\s*\$ExpectedSelfSha256\b", re.I)
_PIN_PARAM = re.compile(r"\[string\]\s*\$Expected(?P<name>\w*?)Sha256\b", re.I)
_PS1_NAME = re.compile(r"[\w.-]+\.ps1\b", re.I)
_PIN_SCAN_ROOTS = ("config", "artifacts")
_PIN_SCAN_MAX_BYTES = 8 * 1024 * 1024


def _json_pins(payload: Any, out: set[str]) -> None:
    """Paths a JSON document pins: string values in an object that also has a ``*sha256*`` key."""

    if isinstance(payload, dict):
        if any("sha256" in str(k).lower() for k in payload):
            for value in payload.values():
                if isinstance(value, str) and ("/" in value or "\\" in value):
                    out.add(value.replace("\\", "/").lstrip("./"))
        for value in payload.values():
            _json_pins(value, out)
    elif isinstance(payload, list):
        for value in payload:
            _json_pins(value, out)


def hash_frozen_paths(git: GitBytes, tree: str, candidates: Iterable[str] = ()) -> dict[str, str]:
    """Every path in ``tree`` whose bytes a registered task, attempt or manifest pins, with the reason.

    Derivation (mechanical, from the tree itself):

    1. the named floor :data:`NAMED_HASH_FROZEN`;
    2. any ``.ps1`` that declares a ``[string]$ExpectedSelfSha256`` parameter (it verifies its own bytes);
    3. any ``.ps1`` named by a ``scripts/**/register_*.ps1`` that declares an ``Expected*Sha256``
       parameter (the registration pins the scripts it names);
    4. for the ``candidates`` only (bounded): a tracked JSON under ``config/`` or ``artifacts/`` that
       names the path in an object carrying a ``*sha256*`` key.
    """

    frozen: dict[str, str] = {p: "named hash-frozen script (OD M13 ruling 5)" for p in NAMED_HASH_FROZEN}
    listing = {p: o for p, o in tree_listing(git, tree, "scripts").items() if p.lower().endswith(".ps1")}
    scripts = sorted(listing)
    texts = texts_of(git, listing)
    by_name: dict[str, list[str]] = {}
    for path in scripts:
        by_name.setdefault(PurePosixPath(path).name.lower(), []).append(path)
    for path, text in texts.items():
        if _SELF_PIN.search(text):
            frozen.setdefault(path, "declares -ExpectedSelfSha256 (verifies its own bytes)")
    for path, text in texts.items():
        if not PurePosixPath(path).name.lower().startswith("register_"):
            continue
        pins = [m.group("name") for m in _PIN_PARAM.finditer(text)]
        if not pins:
            continue
        for name in sorted({m.group(0).lower() for m in _PS1_NAME.finditer(text)}):
            for target in by_name.get(name, []):
                if target != path:
                    frozen.setdefault(target, f"pinned by {path} (Expected{pins[0]}Sha256)")
    wanted = {c for c in candidates if c not in frozen}
    if wanted:
        json_oids = {p: o for p, o in tree_listing(git, tree, *_PIN_SCAN_ROOTS).items() if p.lower().endswith(".json")}
        jsons = sorted(json_oids)
        hits = set()
        for start in range(0, len(jsons), 200):
            chunk = jsons[start:start + 200]
            out = git("grep", "-l", "-z", "-F", *sum((["-e", w] for w in sorted(wanted)), []), tree, "--", *chunk,
                      ok=(0, 1))
            for name in filter(None, out.decode("utf-8", "surrogateescape").split("\0")):
                hits.add(name.split(":", 1)[1] if name.startswith(tree + ":") else name)
        for doc_path, text in texts_of(git, {h: json_oids[h] for h in sorted(hits) if h in json_oids}).items():
            if len(text) > _PIN_SCAN_MAX_BYTES:
                continue
            try:
                pinned: set[str] = set()
                _json_pins(json.loads(text), pinned)
            except ValueError:
                continue
            for path in sorted(wanted & pinned):
                frozen.setdefault(path, f"pinned with a sha256 in {doc_path}")
    return frozen


def evaluate_eof_newline_only(git: GitBytes, old_tree: str, new_tree: str) -> dict[str, Any]:
    """The M13 byte-exact predicate over ``old_tree..new_tree`` (pure git objects; no roll or check context)."""

    disqualifiers: list[dict[str, str]] = []
    rows = raw_changes(git, old_tree, new_tree)
    if not rows:
        disqualifiers.append({"reason": "empty_diff", "path": ""})
    modify = []
    for row in rows:
        path = row["path"]
        if row["status"] != "M":
            name = {"A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "type_changed"}.get(
                row["status"], "unmerged")
            disqualifiers.append({"reason": name, "path": path if row["status"] not in ("R", "C")
                                  else f"{row['old_path']} -> {path}"})
        elif row["old_mode"] != row["new_mode"]:
            disqualifiers.append({"reason": "mode_changed", "path": path})
        elif row["new_mode"] not in ("100644", "100755"):
            disqualifiers.append({"reason": "submodule_or_symlink", "path": path})
        else:
            modify.append(row)
    blobs = read_blobs(git, [o for r in modify for o in (r["old_oid"], r["new_oid"])])
    per_file, byte_ok = [], []
    for row in modify:
        old, new = blobs.get(row["old_oid"]), blobs.get(row["new_oid"])
        if old is None or new is None:
            disqualifiers.append({"reason": "blob_unreadable", "path": row["path"]})
            continue
        ok = eof_newline_only_change(old, new)
        per_file.append({"path": row["path"], "eof_newline_only": ok, **eof_delta(old, new)})
        if not ok:
            disqualifiers.append({"reason": "not_eof_newline_only", "path": row["path"]})
        elif row["path"].lower().endswith(YAML_SUFFIXES):
            disqualifiers.append({"reason": "yaml_excluded", "path": row["path"]})
        else:
            byte_ok.append(row["path"])
    lfs = _lfs_paths(git, new_tree, [r["path"] for r in modify])
    for path in lfs:
        disqualifiers.append({"reason": "lfs", "path": path})
    frozen = hash_frozen_paths(git, new_tree, byte_ok)
    old_frozen = hash_frozen_paths(git, old_tree, byte_ok)
    for path in sorted(set(r["path"] for r in modify)):
        reason = frozen.get(path) or old_frozen.get(path)
        if reason:
            disqualifiers.append({"reason": "hash_frozen", "path": path, "why": reason})
    return {"eof_newline_only": not disqualifiers, "file_count": len(rows), "disqualifiers": disqualifiers,
            "per_file": per_file, "hash_frozen_in_tree": sorted(frozen)}


def _lfs_paths(git: GitBytes, tree: str, paths: list[str]) -> list[str]:
    hits: list[str] = []
    for start in range(0, len(paths), 100):
        chunk = paths[start:start + 100]
        if not chunk:
            continue
        out = git("-c", f"attr.tree={tree}", "check-attr", "-z", "filter", "--", *chunk).decode("utf-8", "surrogateescape")
        fields = out.split("\0")
        for j in range(0, len(fields) - 2, 3):
            if fields[j + 2] == "lfs":
                hits.append(fields[j])
    return sorted(set(hits))


def _tree_of(ctx: PreflightContext, commit: str | None) -> str | None:
    if not commit:
        return None
    result = ctx.git("rev-parse", f"{commit}^{{tree}}", check=False)
    return result.stdout.strip() if result.exit_code == 0 else None


def run_eof_newline_only(ctx: PreflightContext) -> CheckResult:
    """M13 pilot: the head step changes only trailing newline bytes at EOF.  Always INFO.

    The span is the head's own step on the cumulative chain (the tree before the head
    step to the landing tree), which is what production lands on top of master.
    """

    evidence: dict[str, Any] = {"suite_skip_eligible": False, "binding": False, "grants": BINDING_NOTE,
                                "predicate": 'new == old.rstrip(b"\\n") + b"\\n" for every changed file; '
                                             "YAML and hash-frozen files excluded; diff_check PASS; "
                                             "EXPECTED-ROLL-FREE; production roll_verdict.ps1 exit 0 still required"}
    try:
        old_tree = _tree_of(ctx, ctx.pre_head_commit) or ctx.base_tree
        if not old_tree or not ctx.landing_tree:
            evidence["error"] = "no landing tree"
            return CheckResult(INFO, "suite_skip_eligible: false (no landing tree)", evidence=evidence)
        result = evaluate_eof_newline_only(ctx_git_bytes(ctx), old_tree, ctx.landing_tree)
        disqualifiers = list(result["disqualifiers"])
        diff_check = ctx.results.get("diff_check")
        if diff_check is None or diff_check.status != PASS:
            disqualifiers.append({"reason": f"diff_check_{(diff_check.status if diff_check else 'missing').lower()}",
                                  "path": ""})
        from weather.operations.landing_preflight_checks import ROLL_FREE_EXPECTED, _roll_expected

        expected, why = _roll_expected(ctx)
        if expected != ROLL_FREE_EXPECTED:
            disqualifiers.append({"reason": f"roll_class_{(expected or 'unavailable').lower()}", "path": "",
                                  "why": why})
        eligible = not disqualifiers
        evidence.update({"suite_skip_eligible": eligible, "byte_predicate": result["eof_newline_only"],
                         "span": {"from_tree": old_tree, "to_tree": ctx.landing_tree},
                         "file_count": result["file_count"], "disqualifiers": disqualifiers[:200],
                         "per_file": result["per_file"][:1000], "roll_class_expected": expected,
                         "hash_frozen_in_tree": result["hash_frozen_in_tree"]})
    except Exception as exc:  # a pilot never errors the run
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        return CheckResult(INFO, f"suite_skip_eligible: false (pilot error: {type(exc).__name__})", evidence=evidence)
    if eligible:
        summary = f"suite_skip_eligible: true ({result['file_count']} file(s), trailing newline bytes at EOF only)"
    else:
        first = disqualifiers[0]
        summary = f"suite_skip_eligible: false ({first['reason']}{(' ' + first['path']) if first.get('path') else ''})"
    return CheckResult(INFO, summary, details=disqualifiers[:50], evidence=evidence)


# --------------------------------------------------------------------------- M3b: unchanged-review binding shadow

_STRICTNESS = {PASS: 0, INFO: 0, SKIP: 0, WARN: 1, ERROR: 2, FAIL: 3}


def strictest(*statuses: str) -> str:
    """The stricter status: FAIL > ERROR > WARN > PASS/INFO.  Combining can never relax."""

    best = PASS
    for status in statuses:
        if _STRICTNESS.get(status, 2) > _STRICTNESS.get(best, 0):
            best = status
    return best


def m3b_binding_shadow(documents: list[dict[str, Any]], current_status: str, *, final_tip_known: bool,
                       reviews: dict[str, str] | None = None) -> dict[str, Any]:
    """What binding unchanged reviews to the night's FINAL integration commit would conclude.

    ``documents`` are ``docs_transaction`` rows (``path``, ``required_disposition``,
    ``landing_oid``, ``final_tip_oid``).  ``reviews`` maps a path to the blob OID an
    unchanged review binds; by default the reviews a handback would carry today, bound
    at this head (``landing_oid``).  A required disposition document passes only with
    a review whose OID equals its blob at the final tip.  The real check's status is
    combined with :func:`strictest`, so ``effective_if_adopted`` is never weaker than
    ``current_status``: the shadow can add a FAIL, never remove one.
    """

    rows, failing = [], []
    for doc in documents:
        if not doc.get("required_disposition"):
            continue
        bound = reviews.get(doc["path"]) if reviews is not None else doc.get("landing_oid")
        final = doc.get("final_tip_oid")
        ok = bool(final_tip_known and final and bound and bound == final)
        rows.append({"path": doc["path"], "review_bound_oid": bound, "final_tip_oid": final, "binds_final_tip": ok})
        if not ok:
            failing.append(doc["path"])
    would = FAIL if failing else PASS
    return {"status": INFO, "binding": False, "rule": "unchanged reviews bind the blob at the night's final "
            "integration commit; a required disposition document whose review is bound anywhere else fails",
            "reviews_assumed": "explicit" if reviews is not None else "bound at this head (landing_oid)",
            "would_conclude": would, "failing_documents": failing, "documents": rows,
            "current_status": current_status, "effective_if_adopted": strictest(current_status, would),
            "never_relaxes": "effective_if_adopted = strictest(current_status, would_conclude)",
            "grants": BINDING_NOTE}


# --------------------------------------------------------------------------- registration


def register_checks(registry: CheckRegistry) -> None:
    registry.register(CheckSpec("eof_newline_only", PHASE_OBJECTS, run_eof_newline_only, OWNER, ("merge_chain",),
                                "M13 pilot: byte-exact EOF-newline-only head step; suite_skip_eligible INFO only"))


__all__ = [
    "NAMED_HASH_FROZEN", "eof_newline_only_change", "evaluate_eof_newline_only", "git_bytes_runner",
    "hash_frozen_paths", "m3b_binding_shadow", "register_checks", "run_eof_newline_only", "strictest",
]
