"""Landing preflight check runners owned by L-P2: diff hygiene, docs audits, schema, shards, docs transaction.

Each runner takes a :class:`~weather.operations.landing_preflight.PreflightContext`
and returns a :class:`~weather.operations.landing_preflight.CheckResult`.
``register_checks`` adds them to the registry in run order.

Object phase (git objects in the scratch store, no worktree):

* ``diff_check``: ``git diff --check`` over the night span ``base..landing`` (the
  gate, F10) and over every chain step, so each hit names the step that
  introduced it.  ``--span-base`` widens the gate to ``span_base..landing`` for
  mid-night re-runs (production checks ``first_integration..HEAD``).
* ``schema_additive``: when a ``schema_registry*`` file changed, the additive-only
  verdict of :func:`weather.operations.landing_preflight_rollclass.schema_additive_between`
  (the single implementation, ruling R-10).  WARN when not additive.
* ``docs_transaction``: blob OIDs of the documentation transaction's required
  documents as of the night's *final planned tip* and which tips touch them.
* ``whitespace_only`` (M13 evidence, INFO): last in the object phase, after
  ``diff_check`` and L-P4's ``roll_class`` (registered before this module).

Worktree phase (the landing checkout, children run with the worktree interpreter):

* the four audits (``agent_docs_audit``, ``correspondence_index``,
  ``roadmap_backlog``, ``schema_registry``), ``shard_coverage`` and
  ``ps1_param_defaults``.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from weather.operations.landing_preflight import (
    ERROR,
    FAIL,
    INFO,
    PASS,
    PHASE_OBJECTS,
    PHASE_WORKTREE,
    WARN,
    CheckRegistry,
    CheckResult,
    CheckSpec,
    PreflightContext,
    landing_slots,
)
from weather.operations.landing_preflight_rollclass import schema_additive_between
from weather.operations.landing_preflight_rollclass_schema import ADDITIVE, NO_ENTRY_CHANGE, is_schema_family

OWNER = "L-P2"

# --------------------------------------------------------------------------- fix_class (F5)

_REGENERATED_INDEXES = (
    "docs/roadmap/correspondence-index.md",
    "docs/roadmap/active-backlog.md",
)
_REGENERATED_INDEX_DIRS = ("docs/roadmap/correspondence-index/",)
_GENERATED_CONFIG = ("config/location_market_events.json",)


def classify_conflict_path(path: str) -> str:
    """``fix_class`` for a conflicted path (F5): regenerate_index, generated_config, ci_matrix, docs, tests, src.

    Any conflict still FAILs the chain (exit 3, production's ``git merge`` aborts on
    every conflicted path); the class only says how the later PR fixes it.
    """

    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):  # never lstrip("./"): it eats the dot of .github/ and .gitignore
        normalized = normalized[2:]
    if normalized in _REGENERATED_INDEXES or normalized.startswith(_REGENERATED_INDEX_DIRS):
        return "regenerate_index"
    if normalized in _GENERATED_CONFIG or (
        normalized.startswith("config/") and ("generated" in normalized or normalized.endswith(".generated.json"))
    ):
        return "generated_config"
    if normalized.startswith(".github/workflows/"):
        return "ci_matrix"
    if normalized.startswith("docs/") or normalized.endswith(".md") or normalized == ".gitignore":
        return "docs"
    if normalized.startswith("tests/") or normalized == "pytest.ini":
        return "tests"
    return "src"


# --------------------------------------------------------------------------- helpers


def _git_text(ctx: PreflightContext, *args: str, attr_tree: str | None = None, ok: tuple[int, ...] = (0,)) -> str:
    """git against the scratch store; ``attr_tree`` makes ``.gitattributes`` come from that tree (bare store)."""

    prefix = ("-c", f"attr.tree={attr_tree}") if attr_tree else ()
    result = ctx.git(*prefix, *args, check=False)
    if result.exit_code not in ok:
        raise RuntimeError(f"git {' '.join(args[:3])} exited {result.exit_code}: {result.tail(600)}")
    return result.stdout


def _step_trees(ctx: PreflightContext) -> list[tuple[str, str, str]]:
    """``(label, previous tree, step tree)`` for every chain step that changed the tree."""

    rows, prev = [], ctx.base_tree
    for step in ctx.chain:
        if step.tree and prev and step.tree != prev:
            rows.append((step.label, prev, step.tree))
        prev = step.tree or prev
    return rows


_CHECK_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<message>.+?)\.?$")


def parse_diff_check(output: str) -> list[dict[str, Any]]:
    """Parse ``git diff --check`` output into ``{path, line, message, kind, text}`` rows."""

    rows: list[dict[str, Any]] = []
    for raw in output.splitlines():
        if raw.startswith(("+", "-", " ")) and rows:
            rows[-1].setdefault("text", raw[1:])
            continue
        match = _CHECK_LINE.match(raw)
        if not match:
            continue
        message = match["message"]
        kind = "eof_blank_line" if "blank line at EOF" in message else (
            "trailing_whitespace" if "trailing whitespace" in message else (
                "space_before_tab" if "space before tab" in message else (
                    "conflict_marker" if "conflict marker" in message else "other")))
        rows.append({"path": match["path"], "line": int(match["line"]), "message": message, "kind": kind})
    return rows


def _diff_check(ctx: PreflightContext, old: str, new: str) -> tuple[list[dict[str, Any]], list[str]]:
    argv = ("diff", "--check", "--no-color", "--no-ext-diff", old, new)
    result = ctx.git("-c", f"attr.tree={new}", *argv, check=False)
    rows = parse_diff_check(result.stdout)
    if result.exit_code != 0 and not rows:
        raise RuntimeError(f"git diff --check {old[:12]} {new[:12]} exited {result.exit_code}: {result.tail(600)}")
    return rows, ["git", "diff", "--check", old, new]


def _hit_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (row["path"], row["kind"], row.get("text", "").rstrip("\r\n"))


# --------------------------------------------------------------------------- diff_check (F10)


def run_diff_check(ctx: PreflightContext) -> CheckResult:
    """The night-span gate ``git diff --check base..landing`` with per-step attribution."""

    span, command = _diff_check(ctx, ctx.base_tree, ctx.landing_tree)
    per_step: dict[str, list[dict[str, Any]]] = {}
    for label, prev, tree in _step_trees(ctx):
        per_step[label], _ = _diff_check(ctx, prev, tree)

    attribution, details = [], []
    span_keys = set()
    for hit in span:
        key = _hit_key(hit)
        span_keys.add(key)
        steps = [label for label, rows in per_step.items() if any(_hit_key(r) == key for r in rows)]
        if not steps:  # same path and kind, content differs (merge combination)
            steps = [label for label, rows in per_step.items()
                     if any((r["path"], r["kind"]) == key[:2] for r in rows)]
        introduced_by = steps[-1] if steps else "merge_interaction"
        item = f"{hit['path']}:{hit['line']}: {hit['message']}"
        attribution.append({"item": item, "introduced_by": introduced_by})
        details.append({**hit, "introduced_by": introduced_by, "steps_with_hit": steps})
    transient = [{**row, "step": label} for label, rows in per_step.items() for row in rows
                 if _hit_key(row) not in span_keys]

    # Mid-night re-runs: production checks first_integration..HEAD, which is base..landing
    # only while base is the night's first-integration base.  --span-base widens the gate
    # to span_base..landing; hits only in that wider span landed earlier tonight (C8).
    span_base = getattr(ctx, "span_base_sha", "") or ctx.base_sha
    span_base_tree = ctx.base_tree
    if span_base and span_base != ctx.base_sha:
        span_base_tree = ctx.git("rev-parse", f"{span_base}^{{tree}}").stdout.strip()
        wide, command = _diff_check(ctx, span_base_tree, ctx.landing_tree)
        label = f"landed_earlier_tonight({span_base[:12]}..{ctx.base_sha[:12]})"
        for hit in wide:
            if _hit_key(hit) in span_keys:
                continue
            span_keys.add(_hit_key(hit))
            span.append(hit)
            attribution.append({"item": f"{hit['path']}:{hit['line']}: {hit['message']}", "introduced_by": label})
            details.append({**hit, "introduced_by": label, "steps_with_hit": []})
    if span_base == ctx.base_sha:
        note = ("this gate covers base..landing; production's documentation transaction checks "
                "first_integration..HEAD, so this is a superset only while base is the night's first-integration "
                "base. Re-running mid-night against an advanced origin/master, pass --span-base <that base>.")
    else:
        note = (f"this gate covers --span-base {span_base[:12]}..landing, a superset of production's "
                "first_integration..HEAD when --span-base is the night's first-integration base")
    evidence = {"span": {"span_base": span_base, "span_base_tree": span_base_tree, "base_tree": ctx.base_tree,
                         "landing_tree": ctx.landing_tree, "hits": len(span)},
                "per_step_hits": {label: len(rows) for label, rows in per_step.items()},
                "transient_step_hits": transient[:50],
                "note": note}
    if span:
        by_step: dict[str, int] = {}
        for row in attribution:
            by_step[row["introduced_by"]] = by_step.get(row["introduced_by"], 0) + 1
        summary = f"{len(span)} diff --check hit(s) over the night span: " + ", ".join(
            f"{n} from {label}" for label, n in by_step.items())
        return CheckResult(FAIL, summary, details=details, attribution=attribution, evidence=evidence, command=command)
    if transient:
        return CheckResult(WARN, f"span clean; {len(transient)} step hit(s) fixed by a later step", details=transient[:50],
                           attribution=[{"item": f"{r['path']}:{r['line']}: {r['message']}", "introduced_by": r["step"]}
                                        for r in transient[:50]], evidence=evidence, command=command)
    return CheckResult(PASS, f"git diff --check clean over the span and {len(per_step)} step(s)", evidence=evidence,
                       command=command)


# --------------------------------------------------------------------------- whitespace_only (M13)

WHITESPACE_DIFF_FLAGS = ("--ignore-space-at-eol", "--ignore-blank-lines")
ROLL_FREE_EXPECTED = "EXPECTED-ROLL-FREE"


def _raw_changes(ctx: PreflightContext) -> list[dict[str, Any]]:
    out = _git_text(ctx, "diff", "--raw", "-z", "-M", "--no-abbrev", ctx.base_tree, ctx.landing_tree)
    parts, rows, i = out.split("\0"), [], 0
    while i < len(parts) and parts[i]:
        meta = parts[i].lstrip(":").split()
        old_mode, new_mode, status = meta[0], meta[1], meta[4]
        if status[:1] in ("R", "C"):
            rows.append({"old_mode": old_mode, "new_mode": new_mode, "old_oid": meta[2], "new_oid": meta[3],
                         "status": status[:1], "old_path": parts[i + 1], "path": parts[i + 2]})
            i += 3
        else:
            rows.append({"old_mode": old_mode, "new_mode": new_mode, "old_oid": meta[2], "new_oid": meta[3],
                         "status": status[:1], "path": parts[i + 1]})
            i += 2
    return rows


def _name_only(ctx: PreflightContext, *flags: str) -> list[str]:
    out = _git_text(ctx, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", *flags,
                    ctx.base_tree, ctx.landing_tree)
    return sorted(p for p in out.split("\0") if p)


def _numstat(ctx: PreflightContext) -> dict[str, tuple[int | None, int | None]]:
    out = _git_text(ctx, "diff", "--numstat", "-z", "--no-renames", ctx.base_tree, ctx.landing_tree)
    rows: dict[str, tuple[int | None, int | None]] = {}
    for record in filter(None, out.split("\0")):
        added, deleted, path = record.split("\t", 2)
        rows[path] = (None if added == "-" else int(added), None if deleted == "-" else int(deleted))
    return rows


def _lfs_paths(ctx: PreflightContext, paths: list[str]) -> list[str]:
    hits: list[str] = []
    for start in range(0, len(paths), 100):
        chunk = paths[start:start + 100]
        out = _git_text(ctx, "check-attr", "-z", "filter", "diff", "--", *chunk, attr_tree=ctx.landing_tree)
        fields = out.split("\0")
        for j in range(0, len(fields) - 2, 3):
            if fields[j + 2] == "lfs":
                hits.append(fields[j])
    return sorted(set(hits))


def _blank_line_delta(ctx: PreflightContext, paths: list[str]) -> dict[str, dict[str, int]]:
    """Per-file counts of blank-line and whitespace-only line changes (evidence for M13)."""

    if not paths or len(paths) > 500:
        return {}
    out = _git_text(ctx, "diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff", ctx.base_tree, ctx.landing_tree,
                    "--", *paths)
    delta: dict[str, dict[str, int]] = {}
    current = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            current = name[2:] if name.startswith("b/") else None
            if current is not None:
                delta.setdefault(current, {"blank_lines_added": 0, "blank_lines_deleted": 0,
                                           "whitespace_lines_added": 0, "whitespace_lines_deleted": 0})
        elif line.startswith("--- ") or current is None:
            continue
        elif line.startswith("+") or line.startswith("-"):
            body = line[1:]
            sign = "added" if line[0] == "+" else "deleted"
            key = f"blank_lines_{sign}" if not body.strip() else f"whitespace_lines_{sign}"
            delta[current][key] += 1
    return delta


def _roll_expected(ctx: PreflightContext) -> tuple[str | None, str]:
    result = ctx.results.get("roll_class")
    if result is None:
        return None, "roll_class did not run"
    expected = result.evidence.get("expected") or result.evidence.get("expected_class")
    if not expected:
        found = re.search(r"EXPECTED-[A-Z-]+", result.summary or "")
        expected = found.group(0) if found else None
    if result.status not in (PASS, WARN, INFO):
        return expected, f"roll_class status {result.status}"
    return expected, ""


def run_whitespace_only(ctx: PreflightContext) -> CheckResult:
    """M13 evidence: the landing diff changes only trailing whitespace and blank lines.

    ``git diff --ignore-space-at-eol --ignore-blank-lines`` must be empty for every
    file type (never bare ``-w``: an indentation change alters Python and YAML),
    ``diff_check`` clean, no add/delete/rename/copy/type or mode change, no binary
    or LFS path, and the roll-class prediction EXPECTED-ROLL-FREE.  INFO only.
    """

    disqualifiers: list[dict[str, str]] = []

    def disqualify(reason: str, path: str = "") -> None:
        disqualifiers.append({"reason": reason, "path": path})

    raw = _raw_changes(ctx)
    paths = sorted(r["path"] for r in raw)
    if not raw:
        disqualify("empty_diff")
    for row in raw:
        if row["status"] in ("A", "D", "R", "C", "T", "U"):
            name = {"A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "type_changed",
                    "U": "unmerged"}[row["status"]]
            disqualify(name, row["path"] if row["status"] != "R" else f"{row['old_path']} -> {row['path']}")
        elif row["old_mode"] != row["new_mode"]:
            disqualify("mode_changed", row["path"])
        elif row["new_mode"] in ("160000", "120000"):
            disqualify("submodule_or_symlink", row["path"])
    numstat = _numstat(ctx)
    for path, (added, _deleted) in sorted(numstat.items()):
        if added is None:
            disqualify("binary", path)
    for path in _lfs_paths(ctx, paths):
        disqualify("lfs", path)
    substantive = _name_only(ctx, *WHITESPACE_DIFF_FLAGS)
    for path in substantive:
        disqualify("non_whitespace_change", path)
    bare_w = set(_name_only(ctx, "-w", "--ignore-blank-lines"))
    indentation_only = sorted(set(substantive) - bare_w)

    diff_check = ctx.results.get("diff_check")
    if diff_check is None or diff_check.status != PASS:
        status = "missing" if diff_check is None else diff_check.status
        first = diff_check.attribution[0]["item"].split(":")[0] if diff_check and diff_check.attribution else ""
        disqualify(f"diff_check_{status.lower()}", first)
    expected, why = _roll_expected(ctx)
    if expected != ROLL_FREE_EXPECTED:
        disqualify(f"roll_class_{(expected or 'unavailable').lower()}" + (f" ({why})" if why else ""))

    eligible = not disqualifiers
    per_file = [{"path": p, "added": numstat.get(p, (None, None))[0], "deleted": numstat.get(p, (None, None))[1]}
                for p in paths]
    if eligible:
        delta = _blank_line_delta(ctx, paths)
        for row in per_file:
            row.update(delta.get(row["path"], {}))
    first = disqualifiers[0] if disqualifiers else None
    evidence = {
        "whitespace_only": eligible,
        "definition": "git diff --ignore-space-at-eol --ignore-blank-lines empty; diff --check clean; "
                      "no add/delete/rename/copy/type/mode change; no binary or LFS path; EXPECTED-ROLL-FREE",
        "flags": list(WHITESPACE_DIFF_FLAGS),
        "file_count": len(paths),
        "lines_added": sum(a or 0 for a, _ in numstat.values()),
        "lines_deleted": sum(d or 0 for _, d in numstat.values()),
        "first_disqualifier": first,
        "disqualifiers": disqualifiers[:200],
        "indentation_only_paths": indentation_only,
        "roll_class_expected": expected,
        "per_file": per_file[:1000],
        "grants": "nothing until the owner adopts M13",
    }
    if eligible:
        summary = (f"true: {len(paths)} file(s), +{evidence['lines_added']}/-{evidence['lines_deleted']} lines, "
                   "trailing whitespace and blank lines only")
    else:
        where = f" {first['path']}" if first and first["path"] else ""
        summary = f"false: {first['reason']}{where}" + (f" (+{len(disqualifiers) - 1} more)" if len(disqualifiers) > 1 else "")
    return CheckResult(INFO, summary, details=disqualifiers[:50], evidence=evidence,
                       command=["git", "diff", "--name-only", *WHITESPACE_DIFF_FLAGS, ctx.base_tree or "", ctx.landing_tree or ""])


# --------------------------------------------------------------------------- docs_transaction (M3)

REQUIRED_REVIEWED_DOCUMENTS = (
    "docs/operations/ESTABLISHED_FINDINGS.md",
    "docs/operations/RETRACTED_AND_FALSE_LEADS.md",
    "docs/operations/STATE_OF_PLAY.md",
    "docs/roadmap/active-backlog.md",
)
REQUIRED_DISPOSITION_DOCUMENTS = ("docs/operations/STATE_OF_PLAY.md", "docs/roadmap/active-backlog.md")
_TRANSACTION_MODULE = "src/weather/operations/documentation_transaction.py"


def _frozenset_literal(source: str, name: str) -> tuple[str, ...] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            try:
                call = node.value
                if isinstance(call, ast.Call) and call.args:
                    return tuple(sorted(ast.literal_eval(call.args[0])))
                return tuple(sorted(ast.literal_eval(call)))
            except ValueError:
                return None
    return None


def required_documents(ctx: PreflightContext, tree: str) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """The required documents as the landing tree's transaction module declares them (else the known defaults)."""

    result = ctx.git("cat-file", "blob", f"{tree}:{_TRANSACTION_MODULE}", check=False)
    if result.exit_code == 0:
        reviewed = _frozenset_literal(result.stdout, "REQUIRED_REVIEWED_DOCUMENTS")
        disposition = _frozenset_literal(result.stdout, "REQUIRED_DISPOSITION_DOCUMENTS")
        if reviewed and disposition:
            return reviewed, disposition, _TRANSACTION_MODULE
    return REQUIRED_REVIEWED_DOCUMENTS, REQUIRED_DISPOSITION_DOCUMENTS, "default"


def _blob_oid(ctx: PreflightContext, tree: str, path: str) -> str | None:
    result = ctx.git("rev-parse", "--verify", "--quiet", f"{tree}:{path}", check=False)
    return result.stdout.strip() if result.exit_code == 0 else None


def _later_slots(ctx: PreflightContext) -> list[dict[str, Any]]:
    slots = landing_slots(ctx.plan) if ctx.plan else []
    index = next((i for i, s in enumerate(slots) if s["sha"] == ctx.head_sha), None)
    return [] if index is None else slots[index + 1:]


def run_docs_transaction(ctx: PreflightContext) -> CheckResult:
    """Blob OIDs of the transaction's required documents as of the final planned tip (M3)."""

    reviewed, disposition, source = required_documents(ctx, ctx.landing_tree)
    docs = sorted(set(reviewed) | set(disposition))
    touched: dict[str, list[str]] = {d: [] for d in docs}
    for label, prev, tree in _step_trees(ctx):
        out = _git_text(ctx, "diff", "--name-only", "-z", "--no-renames", prev, tree, "--", *docs)
        for path in filter(None, out.split("\0")):
            touched[path].append(label)

    # Continue the synthetic chain over the plan's later slots to reach the final planned tip.
    later, warnings = _later_slots(ctx), []
    cur, final_tree, final_label = ctx.landing_commit, ctx.landing_tree, ctx.head_label or ctx.head_ref
    date = ctx.git("log", "-1", "--format=%at", ctx.head_sha).stdout.strip() + " +0000"
    name, email = "landing-preflight", "landing-preflight@invalid"
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": date}
    for slot in later:
        if ctx.git("cat-file", "-e", f"{slot['sha']}^{{commit}}", check=False).exit_code != 0:
            warnings.append(f"later {slot['label']} @{slot['sha'][:12]} is not available; final tip unknown")
            final_tree = None
            break
        if ctx.git("merge-base", "--is-ancestor", slot["sha"], cur, check=False).exit_code == 0:
            continue
        merged = ctx.git("merge-tree", "--write-tree", "--name-only", "--no-messages", cur, slot["sha"], check=False)
        if merged.exit_code != 0:
            warnings.append(f"later {slot['label']} @{slot['sha'][:12]} does not merge cleanly after this head; "
                            "final tip unknown")
            final_tree = None
            break
        tree = merged.stdout.split()[0]
        out = _git_text(ctx, "diff", "--name-only", "-z", "--no-renames", final_tree, tree, "--", *docs)
        for path in filter(None, out.split("\0")):
            touched[path].append(f"{slot['label']} (later)")
        cur = ctx.git("commit-tree", tree, "-p", cur, "-p", slot["sha"], "-m",
                      f"landing-preflight later {slot['sha']}", env_extra=env).stdout.strip()
        final_tree, final_label = tree, slot["label"]

    rows = []
    for doc in docs:
        landing_oid = _blob_oid(ctx, ctx.landing_tree, doc)
        final_oid = _blob_oid(ctx, final_tree, doc) if final_tree else None
        later_touch = [t for t in touched[doc] if t.endswith("(later)")]
        rows.append({"path": doc, "required_review": doc in reviewed, "required_disposition": doc in disposition,
                     "base_oid": _blob_oid(ctx, ctx.base_tree, doc), "landing_oid": landing_oid,
                     "final_tip_oid": final_oid, "touched_by": touched[doc],
                     "stale_if_bound_at_this_head": bool(later_touch)})
        if later_touch:
            warnings.append(f"{doc} changes after this head ({', '.join(later_touch)}): an unchanged review bound "
                            "at this head will not match the final tip")
        if landing_oid is None:
            warnings.append(f"{doc} is absent from the landing tree")
    evidence = {"required_from": source, "final_tip": final_label, "final_tree": final_tree,
                "later_slots": [{"label": s["label"], "sha": s["sha"]} for s in later], "documents": rows,
                "rule": "bind documents_unchanged blob_oid to final_tip_oid (the night's final integration), never to "
                        "an intermediate tip; STATE_OF_PLAY and active-backlog need an update or a bound review after "
                        "the last integration"}
    status = WARN if warnings else INFO
    summary = (f"{len(docs)} required document(s) as of {'the final planned tip ' + final_label if final_tree else 'an unknown final tip'}"
               + (f"; {len(warnings)} warning(s)" if warnings else ""))
    return CheckResult(status, summary, details=warnings, evidence=evidence)


# --------------------------------------------------------------------------- schema_additive (R-10)


def run_schema_additive(ctx: PreflightContext) -> CheckResult:
    """The schema-registry family's additive-only verdict, from L-P4's single implementation."""

    family = sorted(r["path"] for r in ctx.changed_files
                    if is_schema_family(r["path"]) or is_schema_family(r.get("old_path", "")))
    if not family:
        return CheckResult(INFO, "no schema_registry* change", evidence={"applicable": False})
    verdict = schema_additive_between(ctx.git_dir, ctx.base_tree, ctx.landing_tree).to_json()
    attribution = [{"item": r["path"], "introduced_by": label} for r in ctx.changed_files if r["path"] in family
                   for label in (r.get("introduced_by") or ["?"])]
    evidence = {"applicable": True, "changed": family,
                "implementation": "landing_preflight_rollclass.schema_additive_between", **verdict}
    added = len(verdict["entries_added"])
    if verdict["status"] in (ADDITIVE, NO_ENTRY_CHANGE):
        return CheckResult(INFO, f"{verdict['status'].lower()}: {added} new entr{'y' if added == 1 else 'ies'}",
                           attribution=attribution, evidence=evidence)
    reasons = verdict["entries_removed_or_changed"][:4] or list(verdict["parse_errors"])[:4]
    return CheckResult(WARN, f"{verdict['status'].lower()}: " + "; ".join(reasons), attribution=attribution,
                       evidence=evidence)


# --------------------------------------------------------------------------- the four audits (worktree interpreter)


def _audit(ctx: PreflightContext, argv: list[str], ok_text: str) -> CheckResult:
    command = [ctx.python, *argv]
    result = ctx.run(command, cwd=ctx.worktree)
    if result.timed_out:
        return CheckResult(ERROR, f"timed out after {ctx.options.check_timeout_seconds}s", command=command,
                           exit_code=result.exit_code, output_tail=result.tail())
    if result.exit_code == 0:
        return CheckResult(PASS, ok_text, command=command, exit_code=0, output_tail=result.tail(800))
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    errors = [line for line in (result.stderr or "").splitlines() if line.strip()]
    first = lines[0] if lines else (errors[-1] if errors else "no output")
    return CheckResult(FAIL, f"exit {result.exit_code}: {first}", details=lines[:60], command=command,
                       exit_code=result.exit_code, output_tail=result.tail())


def run_agent_docs_audit(ctx: PreflightContext) -> CheckResult:
    return _audit(ctx, ["-m", "weather.operations.agent_docs_audit", "--repo-root", str(ctx.worktree)],
                  "agent docs audit clean on the landing tree")


def run_correspondence_index(ctx: PreflightContext) -> CheckResult:
    return _audit(ctx, ["-m", "weather.reporting.roadmap.correspondence_index", "--repo-root", str(ctx.worktree), "--check"],
                  "correspondence index matches the landing tree")


def run_roadmap_backlog(ctx: PreflightContext) -> CheckResult:
    roadmap = Path(ctx.worktree) / "docs" / "roadmap"
    result = _audit(ctx, ["-m", "weather.reporting.roadmap.roadmap_backlog", "--roadmap-root", str(roadmap),
                          "--report-out", str(roadmap / "active-backlog.md"),
                          "--json-out", str(ctx.run_dir / "roadmap_backlog.json"), "--fail-on-lint", "--check"],
                    "roadmap backlog lint OK and generated report current")
    if result.status == FAIL:
        result.evidence["failure"] = {1: "lint", 2: "stale"}.get(result.exit_code, "other")
    return result


def run_schema_registry(ctx: PreflightContext) -> CheckResult:
    out = ctx.run_dir / "schema_registry_audit.json"
    command = [ctx.python, "-m", "weather.schema_registry", "audit", "--out", str(out)]
    result = ctx.run(command, cwd=ctx.worktree)
    try:
        payload = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CheckResult(ERROR, f"schema registry audit wrote no JSON (exit {result.exit_code})", command=command,
                           exit_code=result.exit_code, output_tail=result.tail())
    unregistered = payload.get("unregistered_versions") or []
    evidence = {key: payload.get(key) for key in ("registered_count", "discovered_literal_count",
                                                  "unregistered_version_count", "excluded_version_count")}
    evidence["unregistered_versions"] = unregistered
    additive = ctx.results.get("schema_additive")
    if additive is not None:
        evidence["schema_additive"] = additive.evidence.get("status") if additive.evidence.get("applicable") else None
    if result.exit_code != 0 or unregistered:
        return CheckResult(FAIL, f"unregistered schema versions: {', '.join(unregistered[:8]) or 'exit ' + str(result.exit_code)}",
                           details=unregistered, evidence=evidence, command=command, exit_code=result.exit_code,
                           output_tail=result.tail(800))
    return CheckResult(PASS, f"unregistered_versions == [] ({evidence['registered_count']} registered)", evidence=evidence,
                       command=command, exit_code=0)


# --------------------------------------------------------------------------- shard_coverage

WINDOWS_WORKFLOW = ".github/workflows/windows-qualification.yml"
SHARD_RATCHET_TEST = "tests/operations/test_windows_qualification_shards.py"  # lands with #209
_SPAWN_PROBE = r"""
import ast, json, re, sys
try:
    from tests.hygiene_ratchet import module_runs_powershell
except Exception:
    module_runs_powershell = None
out = {}
for path in sys.argv[1:]:
    text = open(path, encoding="utf-8").read()
    if module_runs_powershell is not None:
        out[path] = bool(module_runs_powershell(ast.parse(text)))
    else:
        out[path] = bool(re.search(r"powershell|pwsh", text, re.I))
print(json.dumps({"rule": "hygiene_ratchet" if module_runs_powershell else "regex", "modules": out}))
"""


def shard_plan_files(text: str) -> list[str]:
    """Every path listed under a ``files: >-`` block of the Windows workflow."""

    files: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^(\s*)files:\s*[>|]-?\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        for follow in lines[i + 1:]:
            if not follow.strip():
                continue
            if len(follow) - len(follow.lstrip()) <= indent:
                break
            files.extend(follow.split())
    return files


def run_shard_coverage(ctx: PreflightContext) -> CheckResult:
    wt = Path(ctx.worktree)
    workflow = wt / WINDOWS_WORKFLOW
    if not workflow.is_file():
        return CheckResult(INFO, f"{WINDOWS_WORKFLOW} absent", evidence={"applicable": False})
    listed = shard_plan_files(workflow.read_text(encoding="utf-8"))
    missing = sorted({p for p in listed if not (wt / p).is_file()})
    post_209 = (wt / SHARD_RATCHET_TEST).is_file()
    changed_tests = sorted(r["path"] for r in ctx.changed_files
                           if r["status"] != "D" and re.match(r"^tests/.*test_[^/]*\.py$", r["path"]))
    spawning: dict[str, bool] = {}
    rule = "none"
    if changed_tests:
        probe = ctx.run([ctx.python, "-c", _SPAWN_PROBE, *changed_tests], cwd=wt, timeout=300)
        try:
            payload = json.loads(probe.stdout.strip().splitlines()[-1])
            spawning, rule = payload["modules"], payload["rule"]
        except (ValueError, IndexError, KeyError):
            return CheckResult(ERROR, f"spawn probe failed: {probe.tail(400)}", output_tail=probe.tail())
    sharded = set(listed)
    unsharded = sorted(p for p, runs in spawning.items() if runs and p not in sharded)
    introduced = {r["path"]: r.get("introduced_by") or [] for r in ctx.changed_files}
    attribution = [{"item": f"missing shard file {p}", "introduced_by": ",".join(introduced.get(WINDOWS_WORKFLOW, []))
                    or "?"} for p in missing]
    attribution += [{"item": f"PowerShell-spawning test not sharded: {p}", "introduced_by": ",".join(introduced.get(p, []))
                     or "?"} for p in unsharded]
    evidence = {"listed": len(listed), "missing": missing, "changed_test_modules": changed_tests,
                "spawning_rule": rule, "unsharded_spawning": unsharded, "post_209": post_209}
    if missing:
        return CheckResult(FAIL, f"{len(missing)} shard-listed file(s) do not exist: {', '.join(missing[:5])}",
                           details=missing, attribution=attribution, evidence=evidence)
    if unsharded:
        status = FAIL if post_209 else WARN
        return CheckResult(status, f"{len(unsharded)} changed PowerShell-spawning test module(s) in no Windows shard"
                           + ("" if post_209 else " (WARN until #209 lands)"), details=unsharded,
                           attribution=attribution, evidence=evidence)
    return CheckResult(PASS, f"{len(listed)} shard file(s) exist; no unsharded spawning test changed", evidence=evidence)


# --------------------------------------------------------------------------- ps1_param_defaults

PS1_RATCHET_TEST = "tests/operations/test_ps_script_root_param_defaults.py"  # lands with #222
_ADVANCED = re.compile(r"\[\s*(?:CmdletBinding|Parameter)\s*\(", re.I)
_SCRIPT_LOCATION = re.compile(r"\$(?:PSScriptRoot|PSCommandPath|MyInvocation)\b", re.I)


def _strip_ps_comments(text: str) -> str:
    text = re.sub(r"<#.*?#>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    out = []
    for line in text.splitlines():
        in_single = in_double = False
        cut = len(line)
        for i, ch in enumerate(line):
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "#" and not in_single and not in_double:
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def param_block(text: str) -> str | None:
    """The script-level ``param(...)`` block (balanced parentheses), comments stripped."""

    code = _strip_ps_comments(text)
    match = re.search(r"(?im)^\s*param\s*\(", code)
    if not match:
        return None
    depth, start = 0, match.end() - 1
    for i in range(start, len(code)):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return code[start:i + 1]
    return code[start:]


def ps1_param_default_offender(text: str) -> bool:
    """An advanced script whose ``param()`` defaults read the script location (empty under PS 5.1 ``-File``)."""

    code = _strip_ps_comments(text)
    block = param_block(text)
    return bool(block and _ADVANCED.search(code) and _SCRIPT_LOCATION.search(block))


def run_ps1_param_defaults(ctx: PreflightContext) -> CheckResult:
    wt = Path(ctx.worktree)
    offenders = []
    for path in sorted(wt.rglob("*.ps1")):
        rel = path.relative_to(wt).as_posix()
        if rel.startswith((".git/", "venv/")):
            continue
        try:
            if ps1_param_default_offender(path.read_text(encoding="utf-8-sig", errors="replace")):
                offenders.append(rel)
        except OSError:
            continue
    changed = {r["path"]: r.get("introduced_by") or [] for r in ctx.changed_files if r["status"] != "D"}
    touched = [p for p in offenders if p in changed]
    post_222 = (wt / PS1_RATCHET_TEST).is_file()
    evidence = {"offenders": offenders, "touched_offenders": touched, "post_222": post_222}
    attribution = [{"item": p, "introduced_by": ",".join(changed[p]) or "?"} for p in touched]
    if post_222 and offenders:
        return CheckResult(FAIL, f"{len(offenders)} advanced script(s) derive a param() default from the script location",
                           details=offenders, attribution=attribution, evidence=evidence)
    if touched:
        return CheckResult(WARN, f"{len(touched)} changed advanced script(s) with $PSScriptRoot/$PSCommandPath in param() "
                           "(empty under PS 5.1 -File; WARN until #222 lands)", details=touched,
                           attribution=attribution, evidence=evidence)
    return CheckResult(PASS, f"no changed advanced script reads its location in param() ({len(offenders)} pre-existing)",
                       evidence=evidence)


# --------------------------------------------------------------------------- registration


def register_checks(registry: CheckRegistry) -> None:
    # Object phase (no worktree): the night-span gate and its attribution per step (F10).
    registry.register(CheckSpec("diff_check", PHASE_OBJECTS, run_diff_check, OWNER, ("merge_chain",),
                                "git diff --check base..landing_tree and per chain step"))
    registry.register(CheckSpec("schema_additive", PHASE_OBJECTS, run_schema_additive, OWNER, ("merge_chain",),
                                "schema_registry* change additive-only (AST over SchemaSpec entries); WARN when not"))
    registry.register(CheckSpec("docs_transaction", PHASE_OBJECTS, run_docs_transaction, OWNER, ("merge_chain",),
                                "blob OIDs of the transaction's required docs as of the final planned tip"))
    # whitespace_only reads diff_check (above) and roll_class (L-P4, registered before this module).
    registry.register(CheckSpec("whitespace_only", PHASE_OBJECTS, run_whitespace_only, OWNER, ("merge_chain",),
                                "M13 evidence: --ignore-space-at-eol --ignore-blank-lines empty, no add/rename/mode/binary"))
    # Worktree phase.
    for check_id, runner, text in (
        ("agent_docs_audit", run_agent_docs_audit, "-m weather.operations.agent_docs_audit --repo-root <wt>"),
        ("correspondence_index", run_correspondence_index, "-m weather.reporting.roadmap.correspondence_index --check"),
        ("roadmap_backlog", run_roadmap_backlog, "-m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check"),
        ("schema_registry", run_schema_registry, "-m weather.schema_registry audit: unregistered_versions == []"),
        ("shard_coverage", run_shard_coverage, "windows-qualification.yml shard files exist; spawning tests sharded"),
        ("ps1_param_defaults", run_ps1_param_defaults, "advanced scripts with $PSScriptRoot in param() (WARN pre-#222)"),
    ):
        registry.register(CheckSpec(check_id, PHASE_WORKTREE, runner, OWNER, ("import_probe",), text))
