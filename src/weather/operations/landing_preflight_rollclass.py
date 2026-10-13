"""Landing preflight roll-class prediction owned by L-P4 (NON-BINDING; the host's roll_verdict binds).

``roll_class`` (P6) predicts what ``scripts/ops/roll_verdict.ps1`` will say when
the head lands on the night's chain: the changed set is the head's own landing
step (the chain commit before the head -> the landing tree, renames off, as
roll_verdict computes it), classified by the engine in
:mod:`weather.operations.landing_preflight_rollclass_graph` from

* the production closure snapshot given by ``--closure-snapshot`` (hash, capture
  date and age recorded); without one the prediction is static graph only,
  labelled ``basis: static_graph_only`` and WARNed;
* a static import graph from the loop entry modules, execution-tape entries
  included by default (``--no-execution-tape`` drops them);
* the ``schema_registry*`` family, always sensitive, with the additive-only check.

EXPECTED-UNDECIDABLE (F9) is a class meaning "schedule as roll-sensitive", never
an exit code.  A declared class (``--declared-roll-class`` or the head's plan slot
``declared_roll_class`` / ``roll_class`` / ``kind``) less conservative than the
expected class is a WARN.  ``light_path_eligible`` is the docs light path's own
rule: the branch diff (``pre_head...head``) is non-empty and only ``docs/**.md``,
and the expected class is ROLL-FREE.  ``landing_path`` turns that into the route
and quotes the rule text.  Both checks are INFO/WARN and never block; every row
carries ``binding: false``.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from weather.operations.landing_preflight import (
    INFO,
    PHASE_OBJECTS,
    WARN,
    CheckRegistry,
    CheckResult,
    CheckSpec,
    PreflightContext,
    landing_slots,
)
from weather.operations.landing_preflight_rollclass_graph import (
    EXECUTION_TAPE_ENTRY_MODULES,
    LOOP_ENTRY_MODULES,
    ROLL_FREE,
    ROLL_SENSITIVE,
    UNDECIDABLE,
    ClosureSnapshot,
    GraphOptions,
    ParseCache,
    RollClassResult,
    TreeView,
    classify,
)
from weather.operations.landing_preflight_rollclass_schema import (
    SchemaAdditiveResult,
    classify_schema_change,
    is_schema_family,
)

OWNER = "L-P4"
CLASSIFIER_VERSION = "L-P4 roll-class engine 0.1 (port of the L-R3 classifier)"
PACKAGE_ROOTS = ("src", "weather")
DOCS_ONLY_PATTERN = re.compile(r"^docs/.+\.md$")  # docs_light_path.ps1 $docsOnlyPattern (case-sensitive)

DOCS_LIGHT, ROLL_FREE_GUARDED, ROLL_SENSITIVE_PATH = "DOCS_LIGHT", "ROLL_FREE_GUARDED", "ROLL_SENSITIVE"
_CONSERVATISM = {DOCS_LIGHT: 0, ROLL_FREE: 1, ROLL_SENSITIVE: 2, UNDECIDABLE: 2}
_DECLARED_ALIASES = {
    "DOCS_LIGHT": DOCS_LIGHT, "DOCS": DOCS_LIGHT, "DOCS_ONLY": DOCS_LIGHT, "LIGHT": DOCS_LIGHT,
    "RF": ROLL_FREE, "ROLL_FREE": ROLL_FREE, "EXPECTED_ROLL_FREE": ROLL_FREE, "ROLL_FREE_GUARDED": ROLL_FREE,
    "RS": ROLL_SENSITIVE, "ROLL_SENSITIVE": ROLL_SENSITIVE, "EXPECTED_ROLL_SENSITIVE": ROLL_SENSITIVE,
    "EXPECTED_UNDECIDABLE": UNDECIDABLE, "UNDECIDABLE": UNDECIDABLE,
}
# Rule text quoted by landing_path (AGENTS.md, docs_light_path.ps1, AGREED F1/F2).
ROUTE_RULES = {
    DOCS_LIGHT: {
        "window": "after the night's last guarded merge, before 12:00 (morning slot 09:00-12:00)",
        "tool": "scripts/ops/docs_light_path.ps1 -Branch <b> -ExpectedTip <sha>",
        "quotes": [
            "A branch whose roll verdict is ROLL-FREE and whose diff is only Markdown under docs/ cannot restart "
            "capture, so it lands without the heavy lease or the quiet window (docs_light_path.ps1)",
            "Docs-light landings are not unlimited: allowed only after the night's last guarded merge and before the "
            "next attempt registration, before 12:00, and they enter the night's git diff --check span (AGREED F2)",
        ],
    },
    ROLL_FREE_GUARDED: {
        "window": "00:30-09:00 (heavy lease)",
        "tool": "scripts/ops/quiet_window_merge.ps1 after the bounded suite",
        "quotes": [
            "A roll-free branch does not need the quiet window (AGENTS.md)",
            "Guarded merges (roll-free included) end at 09:00: the lease returns a window only for 00:30-09:00 (AGREED F1)",
        ],
    },
    ROLL_SENSITIVE_PATH: {
        "window": "01:00-04:00 (quiet window)",
        "tool": "scripts/ops/quiet_window_merge.ps1",
        "quotes": [
            "Roll-sensitive branches merge in the 01:00-04:00 quiet window via scripts/ops/quiet_window_merge.ps1 "
            "(AGENTS.md)",
        ],
    },
}
BINDING_GATE = r"Get the verdict from scripts\ops\roll_verdict.ps1 -Branch <b>; never derive it by hand (AGENTS.md)"


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Options this module reads (wired into the core parser by L-P5); absent options use the defaults."""

    parser.add_argument("--no-execution-tape", action="store_true",
                        help="roll_class: drop the execution-tape entry modules from the static graph")
    parser.add_argument("--declared-roll-class", choices=sorted(_DECLARED_ALIASES),
                        help="roll_class: the class the landing is scheduled under (else the plan slot's)")


# --------------------------------------------------------------------------- object-store trees


def _store_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                                        "GIT_ALTERNATE_OBJECT"))}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "LC_ALL": "C"})
    return env


class StoreTrees:
    """Read-only tree listing and blob reads from a git object store (``--git-dir``)."""

    def __init__(self, git_dir: Path, timeout: float = 900) -> None:
        self.git_dir, self.timeout = Path(git_dir), timeout
        self._batch: subprocess.Popen | None = None
        self._blobs: dict[str, bytes] = {}
        self._trees: dict[str, dict[str, str]] = {}

    def _argv(self, *args: str) -> list[str]:
        return ["git", "-c", "core.quotepath=false", "--git-dir", str(self.git_dir), *args]

    def run(self, *args: str) -> str:
        proc = subprocess.run(self._argv(*args), capture_output=True, env=_store_env(), timeout=self.timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} exited {proc.returncode}: "
                               f"{proc.stderr.decode('utf-8', 'replace')[:400]}")
        return proc.stdout.decode("utf-8", "replace")

    def list_tree(self, treeish: str, roots: tuple[str, ...] = PACKAGE_ROOTS) -> dict[str, str]:
        """``path -> blob oid`` for regular files below ``roots``."""

        key = f"{treeish}|{','.join(roots)}"
        if key not in self._trees:
            result: dict[str, str] = {}
            for record in self.run("ls-tree", "-r", "-z", "--full-tree", treeish, "--", *roots).split("\0"):
                if not record:
                    continue
                meta, path = record.split("\t", 1)
                mode, kind, oid = meta.split()
                if kind == "blob" and mode in ("100644", "100755"):
                    result[path] = oid
            self._trees[key] = result
        return self._trees[key]

    def read_blob(self, oid: str) -> bytes:
        if oid in self._blobs:
            return self._blobs[oid]
        if self._batch is None:
            self._batch = subprocess.Popen(self._argv("cat-file", "--batch"), stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_store_env())
        assert self._batch.stdin is not None and self._batch.stdout is not None
        self._batch.stdin.write(oid.encode("ascii") + b"\n")
        self._batch.stdin.flush()
        header = self._batch.stdout.readline().decode("ascii", "replace").split()
        if len(header) < 3 or header[1] != "blob":
            raise RuntimeError(f"cat-file: unexpected header {header!r} for {oid}")
        data = self._batch.stdout.read(int(header[2]))
        self._batch.stdout.read(1)
        self._blobs[oid] = data
        return data

    def view(self, treeish: str, label: str) -> TreeView:
        return TreeView(label, self.list_tree(treeish), self.read_blob)

    def changed(self, left: str, right: str) -> list[tuple[str, str]]:
        """``(status, path)`` with renames off, so a rename is a delete plus an add (roll_verdict's set)."""

        fields = self.run("diff", "--no-renames", "--name-status", "-z", left, right).split("\0")
        return [(fields[i][0], fields[i + 1]) for i in range(0, len(fields) - 1, 2) if fields[i]]

    def names_three_dot(self, left: str, right: str) -> list[str]:
        return [p for p in self.run("diff", "--no-renames", "--name-only", "-z", f"{left}...{right}").split("\0") if p]

    def close(self) -> None:
        if self._batch is not None:
            try:
                if self._batch.stdin:
                    self._batch.stdin.close()
                self._batch.wait(timeout=10)
            except Exception:  # best-effort teardown; never leave the child behind
                self._batch.kill()
            self._batch = None

    def __enter__(self) -> "StoreTrees":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def schema_additive_between(git_dir: Path, reference_tree: str, candidate_tree: str,
                            changed_paths: list[str] | None = None) -> SchemaAdditiveResult:
    """The additive-only verdict for the schema-registry family between two trees (for L-P2's check)."""

    with StoreTrees(git_dir) as store:
        ref, cand = store.view(reference_tree, "reference"), store.view(candidate_tree, "candidate")
        if changed_paths is None:
            changed_paths = [path for _, path in store.changed(reference_tree, candidate_tree)]
        return classify_schema_change(ref.paths, cand.paths, ref.reader, cand.reader, changed_paths=changed_paths,
                                      reference_label="reference", candidate_label="candidate")


# --------------------------------------------------------------------------- inputs


def load_snapshot(path: str | None) -> ClosureSnapshot:
    """``--closure-snapshot``: absent -> static graph only; unreadable -> treated as stale (F9)."""

    if not path:
        return ClosureSnapshot.static_only()
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return ClosureSnapshot.unreadable(str(path), f"{type(exc).__name__}: {exc}")
    try:
        return ClosureSnapshot.from_json_bytes(raw, source=str(path))
    except (ValueError, UnicodeDecodeError) as exc:
        return ClosureSnapshot.unreadable(str(path), f"{type(exc).__name__}: {exc}", hashlib.sha256(raw).hexdigest())


def normalize_declared(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return _DECLARED_ALIASES.get(re.sub(r"[\s\-]+", "_", str(value).strip().upper()))


def declared_class(ctx: PreflightContext) -> tuple[str | None, str | None, dict[str, Any]]:
    """``(declared, source, head_slot)``: the CLI option wins, then the head's plan slot."""

    try:
        slot = next((s for s in landing_slots(ctx.plan) if s["sha"] == ctx.head_sha), {}) if ctx.plan else {}
    except ValueError:
        slot = {}
    option = getattr(ctx.options, "declared_roll_class", None)
    if normalize_declared(option):
        return normalize_declared(option), "--declared-roll-class", slot
    for key in ("declared_roll_class", "roll_class", "kind"):
        if normalize_declared(slot.get(key)):
            return normalize_declared(slot.get(key)), f"plan slot {key}={slot.get(key)!r}", slot
    return None, None, slot


def _as_of(ctx: PreflightContext) -> datetime:
    value = getattr(ctx.options, "rollclass_as_of", None)  # test seam: naive local ISO time
    return datetime.fromisoformat(value) if value else datetime.now()


# --------------------------------------------------------------------------- checks


def predict(ctx: PreflightContext, store: StoreTrees) -> tuple[RollClassResult, list[str], str, str]:
    """Classify the head's landing step; returns ``(result, branch_paths, pre_tree, landing_tree)``."""

    pre_commit = ctx.pre_head_commit or ctx.base_sha
    pre_tree = store.run("rev-parse", f"{pre_commit}^{{tree}}").strip()
    landing_tree = ctx.landing_tree or store.run("rev-parse", f"{ctx.landing_commit}^{{tree}}").strip()
    options = GraphOptions(loop_entries=LOOP_ENTRY_MODULES,
                           include_execution_tape=not getattr(ctx.options, "no_execution_tape", False))
    result = classify(store.changed(pre_tree, landing_tree), store.view(pre_tree, "pre_head"),
                      store.view(landing_tree, "landing"), load_snapshot(ctx.options.closure_snapshot), _as_of(ctx),
                      options, ParseCache())
    branch_paths = store.names_three_dot(pre_commit, ctx.head_sha)
    return result, branch_paths, pre_tree, landing_tree


def _roll_class(ctx: PreflightContext) -> CheckResult:
    with StoreTrees(ctx.git_dir, ctx.options.check_timeout_seconds) as store:
        result, branch_paths, pre_tree, landing_tree = predict(ctx, store)
    body = result.to_json()
    rows = body.pop("rows")
    expected = result.expected
    non_docs = [p for p in branch_paths if not DOCS_ONLY_PATTERN.match(p)]
    light = bool(branch_paths) and not non_docs and expected == ROLL_FREE
    declared, declared_source, slot = declared_class(ctx)
    warnings: list[str] = []
    if not result.snapshot.supplied:
        warnings.append("no --closure-snapshot: static graph only (it misses function-level loop imports)")
    elif result.snapshot.load_error:
        warnings.append(f"closure snapshot unreadable ({result.snapshot.load_error}); treated as stale")
    elif result.snapshot_stale:
        warnings.append(f"closure snapshot is stale (age {body['snapshot']['age_days']} d > 7 d)")
    if not result.graph_complete:
        warnings.append("static graph incomplete (missing entry module or unparseable reached module)")
    if expected == UNDECIDABLE:
        warnings.append("EXPECTED-UNDECIDABLE: schedule as roll-sensitive")
    expected_route = DOCS_LIGHT if light else expected
    if declared is not None and _CONSERVATISM[declared] < _CONSERVATISM[expected_route]:
        detail = f"; first non-docs path {non_docs[0]}" if declared == DOCS_LIGHT and non_docs else ""
        warnings.append(f"declared {declared} ({declared_source}) but expected {expected_route}{detail}")
    body.update({
        "classifier_version": CLASSIFIER_VERSION,
        "changed_basis": "git diff --no-renames <tree before the head step> <landing tree> (roll_verdict's set)",
        "pre_head_tree": pre_tree, "landing_tree": landing_tree,
        "execution_tape_entries": list(EXECUTION_TAPE_ENTRY_MODULES) if not getattr(
            ctx.options, "no_execution_tape", False) else [],
        "declared": declared, "declared_source": declared_source,
        "declared_matches": None if declared is None else declared == expected_route,
        "light_path_eligible": light,
        "light_path_basis": {"branch_diff": "pre_head...head", "paths": len(branch_paths),
                             "first_non_docs": non_docs[0] if non_docs else None},
        "hold": slot.get("hold") or slot.get("holds"),
        "warnings": warnings,
        "binding_gate": BINDING_GATE,
    })
    summary = (f"{expected} (binding: false; {result.snapshot.basis}); {result.importable_count} importable of "
               f"{result.changed_count} changed; sensitive {len(result.sensitive_files)}; light_path_eligible {light}")
    return CheckResult(WARN if warnings else INFO, summary, details=rows, evidence=body)


def landing_route(expected: str, light: bool) -> str:
    if light:
        return DOCS_LIGHT
    return ROLL_FREE_GUARDED if expected == ROLL_FREE else ROLL_SENSITIVE_PATH


def _landing_path(ctx: PreflightContext) -> CheckResult:
    evidence = ctx.results["roll_class"].evidence
    expected, light = evidence["expected"], bool(evidence["light_path_eligible"])
    route = landing_route(expected, light)
    rule = ROUTE_RULES[route]
    hold = evidence.get("hold")
    payload = {
        "path": route, "expected": expected, "undecidable_as_roll_sensitive": expected == UNDECIDABLE,
        "light_path_eligible": light, "window": rule["window"], "tool": rule["tool"], "quotes": rule["quotes"],
        "hold_quotes": ([hold] if isinstance(hold, str) else list(hold or [])),
        "declared": evidence.get("declared"), "binding": False, "binding_gate": BINDING_GATE,
    }
    declared = evidence.get("declared")
    route_rank = {DOCS_LIGHT: 0, ROLL_FREE_GUARDED: 1, ROLL_SENSITIVE_PATH: 2}
    status = WARN if declared is not None and _CONSERVATISM[declared] < route_rank[route] else INFO
    suffix = " (EXPECTED-UNDECIDABLE -> roll-sensitive)" if expected == UNDECIDABLE else ""
    return CheckResult(status, f"{route}{suffix}: {rule['window']} (binding: false)", evidence=payload)


def register_checks(registry: CheckRegistry) -> None:
    registry.register(CheckSpec("roll_class", PHASE_OBJECTS, _roll_class, OWNER, ("merge_chain",),
                                "expected roll class from snapshot union static graph; binding false"))
    registry.register(CheckSpec("landing_path", PHASE_OBJECTS, _landing_path, OWNER, ("roll_class",),
                                "DOCS_LIGHT / ROLL_FREE_GUARDED / ROLL_SENSITIVE / UNDECIDABLE -> RS"))


__all__ = [
    "BINDING_GATE", "ClosureSnapshot", "DOCS_LIGHT", "ROLL_FREE", "ROLL_FREE_GUARDED", "ROLL_SENSITIVE",
    "ROLL_SENSITIVE_PATH", "StoreTrees", "UNDECIDABLE", "add_cli_arguments", "classify_schema_change",
    "declared_class", "is_schema_family", "landing_route", "load_snapshot", "normalize_declared", "predict",
    "register_checks", "schema_additive_between",
]
