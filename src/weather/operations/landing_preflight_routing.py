"""Landing preflight test routing owned by L-P3: ratchets, interaction tests (F6), Windows scripts.

``ratchets`` (worktree phase): the ``-m ratchet`` file list parsed from the
landing tree's ``.github/workflows/ci.yml`` when the landing ``pytest.ini``
declares the marker, else :data:`STATIC_RATCHETS`.  Files that start
PowerShell (or are ``serial``) are deferred to ``windows_scripts``.

``tests`` (heavy phase): the F6 selection.  Base = ``ctx.pre_head_commit`` (the
synthetic chain before the head), head = ``ctx.landing_commit``: test files that
reach the head's changed files over the merged graph, plus the earlier heads'
own changed test files.  The graph comes from the LANDING tree's
``weather.operations.affected_tests`` (#204) run by the worktree interpreter,
never the caller's copy; without it a changed-test-files + direct-importer
heuristic is used with WARN.  A binding cap (affected_tests' full-suite triggers,
or more files than the wrapper's argument contract carries) escalates to
``full``; a selection is never silently truncated.

Routing: a direct run is the workstation focused-run exemption (at most
:data:`DIRECT_FILE_LIMIT` files, none ``serial`` or PowerShell-starting, no xdist,
explicit ``--basetemp`` deleted afterwards, no portable live stage holding the
host mutex).  Everything else goes through the WORKTREE's own
``scripts/ops/workstation_heavy.ps1 -RepoRoot <wt> -Queue``; its queue-timeout
exit 75 (or a missing wrapper) is ``NOT_RUN`` (verdict exit 4).  A full suite
never runs directly.  Failures are read from JUnit and classed ``head`` or
``interaction`` (with the plan's ``known_fix``).

``windows_scripts`` (heavy phase): when the night span touches ``.ps1``,
workflows or PowerShell-starting tests, the deferred spawning ratchets and the
script twins run through the wrapper.  When it does not, deferred spawning
ratchets are listed with WARN, never dropped silently.

A head never shrinks its own gate (Defender C2, C3, C10):

* the ratchet list is the union of the lists in the base tree, the pre-head
  chain tree and the landing tree plus :data:`STATIC_RATCHETS`; the marker filter
  is dropped when the landing tree lost the marker; any shrink is WARNed with
  attribution;
* when the night span (base..landing) changes ``affected_tests.py`` the selection
  is the union with :func:`fallback_selection` (WARN); when it changes the
  host-load hook a file is serial if the base hook (or the fallback mirror) or
  the landing hook says so (WARN);
* when the night span changes the wrapper closure (:data:`WRAPPER_CLOSURE`) the
  base tree's copies are checked out into the scratch worktree before the
  wrapper runs (WARN); a closure file new in the span has no reviewed copy, so
  the wrapper run is ``NOT_RUN``.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

from weather.operations.landing_preflight import (
    ERROR,
    FAIL,
    INFO,
    NOT_RUN,
    PASS,
    PHASE_TESTS,
    PHASE_WORKTREE,
    SKIP,
    WARN,
    CheckRegistry,
    CheckResult,
    CheckSpec,
    CommandResult,
    PreflightContext,
    run_git,
)

OWNER = "L-P3"

DIRECT_FILE_LIMIT = 25            # HOST_LOAD_POLICY focused-run exemption
WRAPPER_MAX_ARGUMENTS = 128       # workstation_heavy.ps1 argument contract
QUEUE_TIMEOUT_EXIT = 75           # workstation_heavy.ps1 -Queue gave up; nothing started
DIRECT_RUN_TIMEOUT_SECONDS = 3600
HEAVY_RUN_SECONDS = 4 * 3600      # added to --queue-timeout-seconds for a wrapper run
PYTEST_FIXED_ARGUMENTS = 12       # -m pytest, options, junit, basetemp and -m ratchet ahead of the files
WRAPPER_RELATIVE = "scripts/ops/workstation_heavy.ps1"
HOOK_RELATIVE = ".codex/hooks/pre_tool_use_host_load.py"
AFFECTED_TESTS_RELATIVE = "src/weather/operations/affected_tests.py"
CI_WORKFLOW_RELATIVE = ".github/workflows/ci.yml"
PYTEST_INI_RELATIVE = "pytest.ini"
WRAPPER_CLOSURE = (WRAPPER_RELATIVE, "scripts/ops/workload_admission.ps1", "scripts/ops/windows_kill_on_close_job.ps1")

# Portable repository ratchets when the landing tree has no `ratchet` marker: the
# CI audit job's list plus #204's always-run set and the hygiene ratchet.
STATIC_RATCHETS = (
    "tests/operations/test_schema_registry.py",
    "tests/operations/test_import_architecture.py",
    "tests/operations/test_path_policy.py",
    "tests/operations/test_module_size_audit.py",
    "tests/operations/test_agent_docs_audit.py",
    "tests/operations/test_ops_script_ratchets.py",
    "tests/operations/test_repo_health_ratchets.py",
    "tests/operations/test_research_harness.py",
    "tests/operations/test_knowledge_structure_audit.py",
    "tests/operations/test_config_inventory.py",
    "tests/operations/test_structure_inventory.py",
    "tests/test_hygiene_ratchet.py",
)

_RATCHET_MARKER = re.compile(r"^\s+ratchet\s*:", re.MULTILINE)
_TEST_PATH = re.compile(r"(?<![\w/.-])(tests/[\w./-]+\.py)\b")
_PS_WORD = re.compile(r"(?i)powershell|pwsh")
_SPAWN_IMPORTS = frozenset({"subprocess", "asyncio", "os", "multiprocessing"})
_MAX_CLOSURE = 64


# --------------------------------------------------------------------------- small helpers


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return path.startswith("tests/") and name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _wt(ctx: PreflightContext) -> Path:
    if ctx.worktree is None:
        raise RuntimeError("landing worktree is not available")
    return ctx.worktree


def _short(text: str, limit: int = 4000) -> str:
    return text[-limit:] if text else ""


def _diff_names(ctx: PreflightContext, a: str | None, b: str | None) -> list[str]:
    if not a or not b or a == b:
        return []
    out = ctx.git("diff", "--name-only", "-z", "--no-renames", a, b).stdout.split("\0")
    return sorted(p for p in out if p)


def _head_label(ctx: PreflightContext) -> str:
    return ctx.chain[-1].label if ctx.chain else ctx.head_ref


def span_paths(ctx: PreflightContext) -> dict[str, list[str]]:
    """``{path: introduced_by}`` over the night span base..landing (both sides of a rename)."""

    out: dict[str, list[str]] = {}
    for row in ctx.changed_files:
        for path in (row.get("path"), row.get("old_path")):
            if path:
                out.setdefault(path, [])
                out[path] = sorted(set(out[path]) | set(row.get("introduced_by") or []))
    return out


def _span_warning(ctx: PreflightContext, path: str, consequence: str) -> str:
    labels = ", ".join(span_paths(ctx).get(path) or ["unattributed"])
    return f"the night span changes {path} (introduced_by {labels}): {consequence}"


def _blob_text(ctx: PreflightContext, commit: str | None, path: str) -> str | None:
    if not commit:
        return None
    result = ctx.git("show", f"{commit}:{path}", check=False)
    return result.stdout if result.exit_code == 0 else None


def _plan_known_fixes(ctx: PreflightContext) -> dict[str, Any]:
    """``{label: known_fix}`` from the earlier steps and the head's own plan slot."""

    fixes: dict[str, Any] = {}
    for step in ctx.chain:
        if step.known_fix:
            fixes[step.label] = step.known_fix
    for slot in (ctx.plan or {}).get("slots") or []:
        if isinstance(slot, dict) and str(slot.get("sha", "")).lower() == ctx.head_sha and slot.get("known_fix"):
            fixes[_head_label(ctx)] = slot["known_fix"]
    return fixes


def step_changes(ctx: PreflightContext) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """(head-changed paths, earlier-changed paths, {path: earlier labels}) over the chain."""

    head = _diff_names(ctx, ctx.pre_head_commit, ctx.landing_commit)
    earlier: dict[str, list[str]] = {}
    prev = ctx.base_tree
    for step in ctx.chain:
        if step.role == "earlier" and step.tree and step.tree != prev:
            for path in _diff_names(ctx, prev, step.tree):
                earlier.setdefault(path, []).append(step.label)
        prev = step.tree or prev
    return head, sorted(earlier), earlier


# --------------------------------------------------------------------------- serial / PowerShell classification


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_bytes(), filename=str(path))


def _starts_powershell(tree: ast.AST) -> bool:
    named = spawn = False
    for node in ast.walk(tree):
        text = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            named = named or ".ps1" in text.lower()
        elif isinstance(node, ast.Name):
            text = node.id
        elif isinstance(node, ast.Attribute):
            text = node.attr
        elif isinstance(node, ast.alias):
            text = node.name
            spawn = spawn or node.name.split(".")[0] in _SPAWN_IMPORTS
        elif isinstance(node, ast.ImportFrom) and node.module:
            text = node.module
            spawn = spawn or node.module.split(".")[0] in _SPAWN_IMPORTS
        if text and _PS_WORD.search(text):
            named = True
    return named and spawn


def _marks_serial(tree: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "serial" and isinstance(n.value, ast.Attribute)
               and n.value.attr == "mark" for n in ast.walk(tree))


def _local_imports(tree: ast.AST, path: Path, repo: Path) -> list[Path]:
    found: list[Path] = []

    def add(module: str, base: Path) -> None:
        rel = Path(*module.split("."))
        for cand in (base / rel.with_suffix(".py"), base / rel / "__init__.py"):
            if cand.is_file():
                found.append(cand)
                return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "tests" or alias.name.startswith("tests."):
                    add(alias.name, repo)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                if node.module:
                    add(node.module, base)
                for alias in node.names:
                    add(f"{node.module}.{alias.name}" if node.module else alias.name, base)
            elif node.module and (node.module == "tests" or node.module.startswith("tests.")):
                add(node.module, repo)
                for alias in node.names:
                    add(f"{node.module}.{alias.name}", repo)
    return found


def serial_reason_fallback(repo: Path, rel: str) -> str | None:
    """Mirror of the hook's ``serial_test_file_reason`` for trees without the hook."""

    path = (repo / rel).resolve()
    tests_root = (repo / "tests").resolve()
    pending = [path]
    cursor = path.parent
    while cursor == tests_root or tests_root in cursor.parents:
        if (cursor / "conftest.py").is_file():
            pending.append(cursor / "conftest.py")
        cursor = cursor.parent
    if (repo / "conftest.py").is_file():
        pending.append(repo / "conftest.py")
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        key = os.path.normcase(str(current.resolve()))
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > _MAX_CLOSURE:
            return f"{path.name}: local import closure is too large to classify"
        try:
            tree = _parse(current)
        except (OSError, ValueError, SyntaxError):
            return f"{path.name}: {current.name} cannot be parsed"
        if current == path and _marks_serial(tree):
            return f"{path.name} is marked serial"
        if _starts_powershell(tree):
            return (f"{path.name} starts PowerShell" if current == path
                    else f"{path.name} reaches PowerShell through {current.name}")
        pending.extend(_local_imports(tree, current, repo))
    return None


_HOOK_SNIPPET = r"""
import importlib.util, json, sys
from pathlib import Path
wt = Path(sys.argv[1]); files = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("_landing_preflight_hook", wt / sys.argv[3])
hook = importlib.util.module_from_spec(spec); spec.loader.exec_module(hook)
serial = {f: hook.serial_test_file_reason(wt / f, wt / "tests") for f in files}
live = hook._portable_live_holds_host() if hasattr(hook, "_portable_live_holds_host") else None
print(json.dumps({"serial": serial, "live": live}))
"""


def classify_files(ctx: PreflightContext, files: list[str]) -> tuple[dict[str, str | None], str | None, str]:
    """``({file: serial reason or None}, portable-live reason, source)`` from the landing tree's hook."""

    wt = _wt(ctx)
    if not files:
        return {}, None, "none"
    serial, live, source = _classify_with_hook(ctx, files, wt / HOOK_RELATIVE, "landing_hook")
    if HOOK_RELATIVE not in span_paths(ctx):
        return serial, live, source
    # The night span changes the hook: the base's hook (or the mirror) also classifies (Defender C3).
    base_hook = None
    text = _blob_text(ctx, ctx.base_sha, HOOK_RELATIVE)
    if text is not None:
        base_hook = ctx.run_dir / "base-hook" / HOOK_RELATIVE
        base_hook.parent.mkdir(parents=True, exist_ok=True)
        base_hook.write_text(text, encoding="utf-8")
    base_serial, base_live, base_source = _classify_with_hook(ctx, files, base_hook, "base_hook")
    merged = {f: serial.get(f) or base_serial.get(f) for f in files}
    return merged, live or base_live, f"{source}+{base_source} (span changes the hook)"


def _classify_with_hook(ctx: PreflightContext, files: list[str], hook: Path | None,
                        name: str) -> tuple[dict[str, str | None], str | None, str]:
    wt = _wt(ctx)
    if hook is not None and hook.is_file():
        request = ctx.run_dir / f"classify-{len(ctx.commands)}.json"
        request.write_text(json.dumps(files), encoding="utf-8")
        result = ctx.run([ctx.python, "-c", _HOOK_SNIPPET, str(wt), str(request), str(hook)], cwd=wt, timeout=300)
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            serial = {f: payload["serial"].get(f) for f in files}
            return serial, payload.get("live"), name
        except (ValueError, IndexError, KeyError, AttributeError):
            pass
    return {f: serial_reason_fallback(wt, f) for f in files}, None, f"{name}:fallback_mirror"


def classifier_warnings(ctx: PreflightContext, source: str) -> list[str]:
    if "span changes the hook" not in source:
        return []
    return [_span_warning(ctx, HOOK_RELATIVE, "a file is serial if the base or the landing hook says so")]


# --------------------------------------------------------------------------- JUnit


def _junit_file(case: ET.Element, wt: Path) -> str:
    file_attr = case.get("file")
    if file_attr:
        return file_attr.replace("\\", "/")
    dotted = (case.get("classname") or case.get("name") or "").split(".")
    for i in range(len(dotted), 0, -1):
        cand = "/".join(dotted[:i]) + ".py"
        if (wt / cand).is_file():
            return cand
    return case.get("classname") or ""


def parse_junit(path: Path, wt: Path) -> dict[str, Any]:
    """Totals and failing cases (``failure`` or ``error``) from a pytest JUnit file."""

    out: dict[str, Any] = {"present": path.is_file(), "tests": 0, "failures": [], "skipped": 0}
    if not out["present"]:
        return out
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        out["parse_error"] = str(exc)
        return out
    for case in root.iter("testcase"):
        out["tests"] += 1
        if case.find("skipped") is not None:
            out["skipped"] += 1
        bad = case.find("failure")
        kind = "failure"
        if bad is None:
            bad, kind = case.find("error"), "error"
        if bad is None:
            continue
        file = _junit_file(case, wt)
        cls = case.get("classname") or ""
        module = file[:-3].replace("/", ".") if file.endswith(".py") else ""
        inner = cls[len(module) + 1:] if module and cls.startswith(module + ".") else ""
        nodeid = "::".join(p for p in (file, inner.replace(".", "::"), case.get("name") or "") if p)
        out["failures"].append({"nodeid": nodeid, "file": file, "kind": kind,
                                "message": (bad.get("message") or "")[:300]})
    return out


# --------------------------------------------------------------------------- running


def _pytest_args(ctx: PreflightContext, tag: str, targets: list[str], extra: list[str]) -> tuple[list[str], Path, Path]:
    basetemp = ctx.run_dir / "bt" / tag
    junit = ctx.run_dir / f"junit-{tag}.xml"
    shutil.rmtree(basetemp, ignore_errors=True)
    junit.unlink(missing_ok=True)
    basetemp.parent.mkdir(parents=True, exist_ok=True)  # pytest creates --basetemp itself, not its parents
    args = ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "junit_family=xunit1", f"--junitxml={junit}",
            f"--basetemp={basetemp}", *extra, *targets]
    return args, basetemp, junit


def _is_windows() -> bool:  # test seam
    return os.name == "nt"


def prepare_wrapper_closure(ctx: PreflightContext) -> str | None:
    """Never run the night span's own wrapper closure (Defender C10).

    When base..landing changes a :data:`WRAPPER_CLOSURE` file, the base tree's copy
    is checked out into the scratch worktree (the wrapper must live under its
    ``-RepoRoot``).  Returns a not-run reason when a changed file has no base copy.
    Idempotent; the outcome is kept in ``ctx.shared["wrapper_closure"]``.
    """

    state = ctx.shared.get("wrapper_closure")
    if state is None:
        changed = span_paths(ctx)
        state = {"swapped_to_base": [], "introduced_by": {}, "not_run": None}
        for path in WRAPPER_CLOSURE:
            if path not in changed:
                continue
            state["introduced_by"][path] = changed[path]
            if _blob_text(ctx, ctx.base_sha, path) is None:
                state["not_run"] = (f"{path} is new in the night span (introduced_by "
                                    f"{', '.join(changed[path]) or 'unattributed'}); no reviewed wrapper copy to run")
                continue
            result = run_git(["-C", str(_wt(ctx)), "checkout", ctx.base_sha, "--", path], check=False)
            if result.exit_code != 0:
                state["not_run"] = f"could not restore the base copy of {path}: {result.tail(300)}"
                continue
            state["swapped_to_base"].append(path)
        ctx.shared["wrapper_closure"] = state
    return state["not_run"]


def wrapper_closure_warnings(ctx: PreflightContext) -> list[str]:
    state = ctx.shared.get("wrapper_closure") or {}
    return [_span_warning(ctx, p, "the wrapper ran the base tree's copy, not the span's; tests of this script "
                                  "exercised the base copy") for p in state.get("swapped_to_base") or []]


def wrapper_available(wt: Path) -> str | None:
    """``None`` when the worktree's wrapper supports ``-Queue``, else why not."""

    if not _is_windows():
        return "workstation_heavy.ps1 runs only on Windows"
    wrapper = wt / WRAPPER_RELATIVE
    if not wrapper.is_file():
        return f"{WRAPPER_RELATIVE} is absent from the landing tree"
    if not re.search(r"\[switch\]\s*\$Queue\b", wrapper.read_text(encoding="utf-8", errors="replace")):
        return f"{WRAPPER_RELATIVE} in the landing tree has no -Queue switch"
    return None


def wrapper_command(ctx: PreflightContext, args: list[str]) -> list[str]:
    wt = _wt(ctx)
    encoded = base64.b64encode(json.dumps(args, separators=(",", ":")).encode("utf-8")).decode("ascii")
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    powershell = str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    return [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(wt / WRAPPER_RELATIVE), "-Kind", "pytest", "-PythonPath", str(Path(ctx.python).resolve()),
            "-ArgumentsBase64", encoded, "-RepoRoot", str(wt), "-Queue",
            "-QueueTimeoutSeconds", str(int(ctx.options.queue_timeout_seconds))]


def route_for(n_files: int, serial: dict[str, str | None], live: str | None, full: bool) -> tuple[str, str]:
    """``("direct"|"wrapper", why)``: direct only inside the focused-run exemption."""

    if full:
        return "wrapper", "full suite never runs directly"
    if n_files > DIRECT_FILE_LIMIT:
        return "wrapper", f"{n_files} files > {DIRECT_FILE_LIMIT} (focused-run limit)"
    blockers = sorted(f for f, why in serial.items() if why)
    if blockers:
        return "wrapper", f"serial or PowerShell-starting: {', '.join(blockers[:5])}"
    if live:
        return "wrapper", f"focused exemption refused: {live}"
    return "direct", f"focused run of {n_files} non-serial file(s)"


def run_pytest(ctx: PreflightContext, tag: str, targets: list[str], *, route: str,
               extra: list[str] | None = None) -> tuple[CommandResult | None, dict[str, Any], str | None]:
    """Run pytest on ``targets`` by ``route``; returns (result, junit summary, not-run reason)."""

    wt = _wt(ctx)
    args, basetemp, junit = _pytest_args(ctx, tag, targets, extra or [])
    try:
        if route == "direct":
            if len(targets) > DIRECT_FILE_LIMIT or not targets or targets == ["tests"]:
                raise RuntimeError("refusing a direct run outside the focused-run exemption")
            timeout = max(DIRECT_RUN_TIMEOUT_SECONDS, int(ctx.options.check_timeout_seconds))
            result = ctx.run([ctx.python, *args], cwd=wt, timeout=timeout)
        else:
            why = prepare_wrapper_closure(ctx) or wrapper_available(wt)
            if why:
                return None, {"present": False}, why
            if len(args) > WRAPPER_MAX_ARGUMENTS:
                raise RuntimeError(f"{len(args)} pytest arguments exceed the wrapper contract")
            timeout = int(ctx.options.queue_timeout_seconds) + HEAVY_RUN_SECONDS
            result = ctx.run(wrapper_command(ctx, args), cwd=wt, timeout=timeout)
            if result.exit_code == QUEUE_TIMEOUT_EXIT and not junit.exists():
                return result, {"present": False}, "workstation_heavy -Queue timed out (exit 75); nothing was started"
        return result, parse_junit(junit, wt), None
    finally:
        shutil.rmtree(basetemp, ignore_errors=True)


def _outcome(result: CommandResult | None, junit: dict[str, Any], not_run: str | None) -> tuple[str, str]:
    """(status, summary) for one pytest run before failure classing."""

    if not_run:
        return NOT_RUN, not_run
    assert result is not None
    if result.timed_out:
        return ERROR, f"pytest timed out after {result.duration_s:.0f} s"
    if junit.get("failures"):
        return FAIL, f"{len(junit['failures'])} failing test(s) of {junit['tests']}"
    if not junit.get("present") or junit.get("parse_error"):
        return ERROR, f"pytest exited {result.exit_code} without a readable JUnit report"
    if result.exit_code == 0:
        return PASS, f"{junit.get('tests', 0)} test(s) passed"
    if result.exit_code == 5:
        return ERROR, "pytest collected no tests (exit 5)"
    return ERROR, f"pytest exited {result.exit_code} without a parsed failure"


# --------------------------------------------------------------------------- ratchets


def ratchet_selection(wt: Path) -> tuple[list[str], list[str], str]:
    """(files, extra pytest args, source) for the landing tree."""

    ini = wt / "pytest.ini"
    marker = ini.is_file() and bool(_RATCHET_MARKER.search(ini.read_text(encoding="utf-8", errors="replace")))
    if marker:
        files = ci_ratchet_files(wt / CI_WORKFLOW_RELATIVE)
        if files:
            return [f for f in files if (wt / f).is_file()], ["-m", "ratchet"], "ci.yml -m ratchet"
    files = [f for f in STATIC_RATCHETS if (wt / f).is_file()]
    return files, [], "static list (marker present, ci.yml list absent)" if marker else "static list"


def guarded_ratchet_selection(ctx: PreflightContext) -> tuple[list[str], list[str], str, list[str], list[dict[str, Any]]]:
    """(files, extra args, source, warnings, attribution): the head never shrinks its own ratchet gate (C2).

    Files are the union of the ``-m ratchet`` lists in the base tree, the pre-head
    chain tree and the landing tree, plus :data:`STATIC_RATCHETS`.  The ``-m ratchet``
    filter applies only while the landing tree still declares the marker; a list
    or marker dropped between trees is WARNed and attributed.
    """

    wt = _wt(ctx)
    trees = [("base", ctx.base_sha), ("pre_head", ctx.pre_head_commit), ("landing", ctx.landing_commit)]
    marker: dict[str, bool] = {}
    lists: dict[str, list[str]] = {}
    for name, commit in trees:
        ini = _blob_text(ctx, commit, PYTEST_INI_RELATIVE) or ""
        marker[name] = bool(_RATCHET_MARKER.search(ini))
        ci = _blob_text(ctx, commit, CI_WORKFLOW_RELATIVE)
        lists[name] = ci_ratchet_files_text(ci) if (marker[name] and ci) else []
    union = sorted(set(STATIC_RATCHETS).union(*lists.values()))
    files = [f for f in union if (wt / f).is_file()]
    warnings: list[str] = []
    attribution: list[dict[str, Any]] = []
    earlier_labels = sorted({label for path in (PYTEST_INI_RELATIVE, CI_WORKFLOW_RELATIVE)
                             for label in span_paths(ctx).get(path, []) if label != _head_label(ctx)}) or ["earlier"]
    for (prev_name, _), (next_name, _) in zip(trees, trees[1:]):
        by = [_head_label(ctx)] if next_name == "landing" else earlier_labels
        for path in sorted(set(lists[prev_name]) - set(lists[next_name])):
            warnings.append(f"ratchet file {path} dropped from the ci.yml ratchet list between {prev_name} and "
                            f"{next_name} (introduced_by {', '.join(by)}); still run")
            attribution += [{"item": f"ratchet list: {path}", "introduced_by": label} for label in by]
        if marker[prev_name] and not marker[next_name]:
            warnings.append(f"pytest.ini ratchet marker removed between {prev_name} and {next_name} "
                            f"(introduced_by {', '.join(by)}); ratchet files run without the -m filter")
            attribution += [{"item": "pytest.ini ratchet marker", "introduced_by": label} for label in by]
    for path in sorted(set(union) - set(files)):
        if any(path in lists[n] for n in ("base", "pre_head")) or (path in STATIC_RATCHETS and _blob_text(
                ctx, ctx.base_sha, path) is not None):
            warnings.append(f"ratchet file {path} is absent from the landing tree; it cannot run")
            attribution.append({"item": f"ratchet file deleted: {path}",
                                "introduced_by": ", ".join(span_paths(ctx).get(path) or ["unattributed"])})
    use_marker = marker["landing"] and any(lists.values())
    sources = [n for n in lists if lists[n]]
    source = (f"union of ci.yml -m ratchet lists ({', '.join(sources)}) and the static list" if sources
              else "static list")
    return files, (["-m", "ratchet"] if use_marker else []), source, warnings, attribution


def ci_ratchet_files(workflow: Path) -> list[str]:
    """Test files of the ci.yml step whose pytest command carries ``-m ratchet``."""

    if not workflow.is_file():
        return []
    return ci_ratchet_files_text(workflow.read_text(encoding="utf-8", errors="replace"))


def ci_ratchet_files_text(text: str) -> list[str]:
    """:func:`ci_ratchet_files` over workflow text."""

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "pytest" not in line and not any("pytest" in lines[j] for j in range(max(0, i - 2), i)):
            continue
        if not re.search(r"-m\s+['\"]?ratchet\b", line):
            continue
        indent = len(lines[i]) - len(lines[i].lstrip())
        block = [line]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or (len(nxt) - len(nxt.lstrip())) < indent or nxt.lstrip().startswith("- "):
                break
            block.append(nxt)
        files = _TEST_PATH.findall("\n".join(block))
        if files:
            return sorted(dict.fromkeys(files))
    return []


def _attribute_text(ctx: PreflightContext, text: str) -> list[str]:
    labels: set[str] = set()
    for row in ctx.changed_files:
        if row.get("path") and row["path"] in text:
            labels.update(row.get("introduced_by") or [])
    return sorted(labels)


def _ratchets(ctx: PreflightContext) -> CheckResult:
    wt = _wt(ctx)
    files, extra, source, warnings, guard_attribution = guarded_ratchet_selection(ctx)
    serial, live, classifier = classify_files(ctx, files)
    warnings += classifier_warnings(ctx, classifier)
    deferred = sorted(f for f, why in serial.items() if why)
    direct = [f for f in files if f not in deferred]
    evidence: dict[str, Any] = {"source": source, "files": direct, "deferred_to_windows_scripts": deferred,
                                "serial_reasons": {f: serial[f] for f in deferred}, "classifier": classifier,
                                "warnings": warnings}
    if not direct:
        return CheckResult(ERROR, f"no ratchet file to run ({source})", evidence=evidence, attribution=guard_attribution)
    route, why = route_for(len(direct), {f: None for f in direct}, live, False)
    evidence.update({"route": route, "route_reason": why})
    result, junit, not_run = run_pytest(ctx, "ratchets", direct, route=route, extra=extra)
    if route == "wrapper":
        warnings += wrapper_closure_warnings(ctx)
    status, summary = _outcome(result, junit, not_run)
    if status == PASS and warnings:
        status, summary = WARN, f"{summary}; {len(warnings)} warning(s): {warnings[0]}"
    attribution, details = list(guard_attribution), []
    if status == FAIL:
        tail = result.tail(20000) if result else ""
        for failure in junit["failures"]:
            labels = _attribute_text(ctx, failure["message"] + "\n" + tail) or ["unattributed"]
            details.append({**failure, "introduced_by": labels})
            attribution += [{"item": failure["nodeid"], "introduced_by": label} for label in labels]
        report = ctx.run([ctx.python, "-m", "tests.hygiene_ratchet", "--report"], cwd=wt, timeout=600)
        evidence["hygiene_ratchet_report"] = {"exit_code": report.exit_code, "tail": report.tail(3000)}
    return CheckResult(status, f"{summary} [{source}, {route}]", details=details, attribution=attribution,
                       evidence={**evidence, "junit": {k: v for k, v in junit.items() if k != "failures"}},
                       command=result.argv if result else None, exit_code=result.exit_code if result else None,
                       output_tail=_short(result.tail() if result else ""))


# --------------------------------------------------------------------------- F6 selection


def _affected_from_landing_tree(ctx: PreflightContext, base: str, head: str) -> dict[str, Any] | None:
    """Run #204's selector from the landing tree with the worktree interpreter; ``None`` if absent."""

    wt = _wt(ctx)
    if not (wt / AFFECTED_TESTS_RELATIVE).is_file():
        return None
    result = ctx.run([ctx.python, "-m", "weather.operations.affected_tests", "--repo", str(wt), "--base", base,
                      "--head", head, "--no-merge-base", "--format", "json"], cwd=wt, timeout=900)
    if result.exit_code != 0:
        raise RuntimeError(f"landing-tree affected_tests exited {result.exit_code}: {result.tail(600)}")
    payload = json.loads(result.stdout)
    payload["_source"] = "landing_tree affected_tests"
    return payload


def _module_names(path: str) -> set[str]:
    if not path.endswith(".py"):
        return set()
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return {".".join(parts)} if parts and all(p.isidentifier() for p in parts) else set()


def fallback_selection(wt: Path, changed: list[str]) -> dict[str, Any]:
    """Changed test files plus test files that import a changed module directly (one hop)."""

    tests: dict[str, str] = {p: "changed test file" for p in changed if is_test_file(p) and (wt / p).is_file()}
    modules = {m: p for p in changed for m in _module_names(p)}
    if modules:
        for path in sorted((wt / "tests").rglob("*.py")):
            rel = path.relative_to(wt).as_posix()
            if not is_test_file(rel) or rel in tests:
                continue
            try:
                tree = _parse(path)
            except (OSError, ValueError, SyntaxError):
                tests[rel] = "unparsable test file (selected fail-safe)"
                continue
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
                hit = next((m for n in names for m in modules if n == m or n.startswith(m + ".")), None)
                if hit:
                    tests[rel] = f"{modules[hit]} changed: imports {hit} (direct-importer fallback)"
                    break
    full = [p for p in changed if PurePosixPath(p).name == "conftest.py" or p in ("pytest.ini", "pyproject.toml")]
    return {"tests": [{"file": f, "reason": r} for f, r in sorted(tests.items())], "full_suite": bool(full),
            "full_suite_reasons": full, "_source": "fallback: changed tests + direct importers"}


def union_selection(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Union of two selections; the first selection's reason wins for a file both choose."""

    rows: dict[str, str] = {}
    for selection in (first, second):
        for row in selection.get("tests") or []:
            rows.setdefault(row["file"], str(row.get("reason", "")))
    reasons = list(first.get("full_suite_reasons") or []) + [
        r for r in second.get("full_suite_reasons") or [] if r not in (first.get("full_suite_reasons") or [])]
    return {"tests": [{"file": f, "reason": r} for f, r in sorted(rows.items())],
            "full_suite": bool(first.get("full_suite") or second.get("full_suite")),
            "full_suite_reasons": reasons, "_source": f"{first.get('_source')} + {second.get('_source')}"}


def f6_selection(ctx: PreflightContext) -> dict[str, Any]:
    """The F6 selection with its provenance; ``files`` excludes the always-run ratchets."""

    wt = _wt(ctx)
    if not ctx.pre_head_commit or not ctx.landing_commit:
        raise RuntimeError("merge chain did not produce pre_head_commit/landing_commit")
    head_changed, earlier_changed, earlier_by = step_changes(ctx)
    warnings: list[str] = []
    try:
        selection = _affected_from_landing_tree(ctx, ctx.pre_head_commit, ctx.landing_commit)
    except (RuntimeError, ValueError) as exc:
        warnings.append(f"landing-tree affected_tests failed ({exc}); fallback heuristic used")
        selection = None
    if selection is None:
        if not warnings:
            warnings.append("affected_tests (#204) is not in the landing tree; fallback heuristic used")
        selection = fallback_selection(wt, head_changed)
    elif AFFECTED_TESTS_RELATIVE in span_paths(ctx):
        # The span edits its own selector: never let it alone decide the test set (Defender C3).
        warnings.append(_span_warning(ctx, AFFECTED_TESTS_RELATIVE,
                                      "selection is the union with the fallback heuristic"))
        selection = union_selection(selection, fallback_selection(wt, head_changed))
    chosen: dict[str, str] = {}
    for row in selection.get("tests") or []:
        reason = str(row.get("reason", ""))
        if reason.startswith("always run"):
            continue  # the ratchets check owns the repository ratchets
        chosen[row["file"]] = reason
    earlier_tests = [p for p in earlier_changed if is_test_file(p) and (wt / p).is_file()]
    for path in earlier_tests:
        chosen.setdefault(path, "earlier head's own test file: " + ", ".join(earlier_by[path]))
    files = sorted(p for p in chosen if (wt / p).is_file())
    full_reasons = list(selection.get("full_suite_reasons") or [])
    if len(files) + PYTEST_FIXED_ARGUMENTS > WRAPPER_MAX_ARGUMENTS:
        full_reasons.append(f"{len(files)} selected files exceed the wrapper's {WRAPPER_MAX_ARGUMENTS}-argument cap")
    return {"source": selection.get("_source"), "head_changed": head_changed, "earlier_test_files": earlier_tests,
            "files": files, "reasons": {f: chosen[f] for f in files}, "full_suite": bool(full_reasons),
            "full_suite_reasons": full_reasons, "warnings": warnings, "earlier_by": earlier_by}


def _earlier_reach(ctx: PreflightContext) -> set[str]:
    """Test files reached by the earlier heads' changes (base..pre_head) for interaction classing."""

    if not ctx.earlier or ctx.pre_head_commit == ctx.base_sha:
        return set()
    wt = _wt(ctx)
    try:
        selection = _affected_from_landing_tree(ctx, ctx.base_sha, ctx.pre_head_commit)
    except (RuntimeError, ValueError):
        selection = None
    if selection is None:
        selection = fallback_selection(wt, _diff_names(ctx, ctx.base_sha, ctx.pre_head_commit))
    return {row["file"] for row in selection.get("tests") or [] if not str(row.get("reason", "")).startswith("always run")}


def classify_failures(ctx: PreflightContext, failures: list[dict[str, Any]], earlier_by: dict[str, list[str]],
                      head_changed: list[str]) -> list[dict[str, Any]]:
    """Class each failure ``head`` or ``interaction`` and attach the plan's ``known_fix``."""

    fixes = _plan_known_fixes(ctx)
    head = _head_label(ctx)
    reach: set[str] | None = None
    rows = []
    for failure in failures:
        file = failure["file"]
        if file in earlier_by:
            cls, basis, labels = "interaction", "test file changed by an earlier head", list(earlier_by[file])
        elif file in head_changed:
            cls, basis, labels = "head", "test file changed by the head only", [head]
        else:
            if reach is None:
                reach = _earlier_reach(ctx)
            if file in reach:
                cls, basis = "interaction", "test reaches both the head's and an earlier head's changes"
                labels = [s.label for s in ctx.chain if s.role == "earlier" and s.result == "clean"]
            else:
                cls, basis, labels = "head", "test reaches only the head's changes", [head]
        known = {lab: fixes[lab] for lab in [*labels, head] if lab in fixes} if cls == "interaction" else (
            {head: fixes[head]} if head in fixes else {})
        rows.append({**failure, "class": cls, "basis": basis, "introduced_by": labels, "known_fix": known or None})
    return rows


def _tests(ctx: PreflightContext) -> CheckResult:
    mode = ctx.options.tests
    if mode == "none":
        return CheckResult(SKIP, "--tests none: no test ran (the verdict is PASS_NO_TESTS at best, exit 4)")
    wt = _wt(ctx)
    warnings: list[str] = []
    head_changed, _, earlier_by = step_changes(ctx)
    evidence: dict[str, Any] = {"mode_requested": mode, "base": ctx.pre_head_commit, "head": ctx.landing_commit}
    if mode == "affected":
        sel = f6_selection(ctx)
        warnings += sel["warnings"]
        evidence.update({k: sel[k] for k in ("source", "head_changed", "earlier_test_files", "reasons",
                                             "full_suite_reasons")})
        files, full = sel["files"], sel["full_suite"]
        if full:
            warnings.append("binding cap: selection escalated to the full suite (" + "; ".join(sel["full_suite_reasons"]) + ")")
    elif mode == "changed":
        files = sorted(r["path"] for r in ctx.changed_files if is_test_file(r["path"]) and (wt / r["path"]).is_file())
        full = len(files) + PYTEST_FIXED_ARGUMENTS > WRAPPER_MAX_ARGUMENTS
        evidence["source"] = "changed test files over the night span"
    else:
        files, full = [], True
        evidence["source"] = "--tests full"
    evidence["mode_effective"] = "full" if full else mode
    if not full and not files:
        return CheckResult(WARN if warnings else PASS, "no test file selected", evidence={**evidence, "warnings": warnings})
    serial, live, classifier = classify_files(ctx, [] if full else files)
    warnings += classifier_warnings(ctx, classifier)
    route, why = route_for(len(files), serial, live, full)
    evidence.update({"files": files, "route": route, "route_reason": why, "classifier": classifier,
                     "serial_reasons": {f: r for f, r in serial.items() if r}, "warnings": warnings})
    result, junit, not_run = run_pytest(ctx, "tests", ["tests"] if full else files, route=route)
    if route == "wrapper":
        warnings += wrapper_closure_warnings(ctx)
    status, summary = _outcome(result, junit, not_run)
    details, attribution = [], []
    if status == FAIL:
        details = classify_failures(ctx, junit["failures"], earlier_by, head_changed)
        attribution = [{"item": d["nodeid"], "introduced_by": ",".join(d["introduced_by"]) or d["class"],
                        "class": d["class"]} for d in details]
        counts = {c: sum(1 for d in details if d["class"] == c) for c in ("head", "interaction")}
        summary += f" (head {counts['head']}, interaction {counts['interaction']})"
    elif status == PASS and warnings:
        status = WARN
    return CheckResult(status, f"{summary} [{evidence['mode_effective']}, {route}]", details=details,
                       attribution=attribution,
                       evidence={**evidence, "junit": {k: v for k, v in junit.items() if k != "failures"}},
                       command=result.argv if result else None, exit_code=result.exit_code if result else None,
                       output_tail=_short(result.tail() if result else ""))


# --------------------------------------------------------------------------- windows scripts


def _windows_trigger(ctx: PreflightContext, serial_tests: set[str]) -> list[str]:
    hits = []
    for row in ctx.changed_files:
        path = row["path"]
        if path.lower().endswith((".ps1", ".psm1")) or path.startswith(".github/workflows/") or path in serial_tests:
            hits.append(path)
    return sorted(hits)


def script_twins(wt: Path, scripts: list[str]) -> list[str]:
    """Test files whose source names a changed PowerShell script's file name."""

    names = {PurePosixPath(s).name.lower() for s in scripts if s.lower().endswith((".ps1", ".psm1"))}
    if not names:
        return []
    twins = []
    for path in sorted((wt / "tests").rglob("test_*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(n in text for n in names):
            twins.append(path.relative_to(wt).as_posix())
    return twins


def _windows_scripts(ctx: PreflightContext) -> CheckResult:
    if ctx.options.tests == "none":
        return CheckResult(SKIP, "--tests none: no test ran (the verdict is PASS_NO_TESTS at best, exit 4)")
    wt = _wt(ctx)
    ratchets = ctx.results.get("ratchets")
    deferred = list((ratchets.evidence.get("deferred_to_windows_scripts") if ratchets else None) or [])
    if ratchets is None or "deferred_to_windows_scripts" not in ratchets.evidence:
        files = guarded_ratchet_selection(ctx)[0]
        serial, _, _ = classify_files(ctx, files)
        deferred = sorted(f for f, why in serial.items() if why)
    changed_tests = [r["path"] for r in ctx.changed_files if is_test_file(r["path"]) and (wt / r["path"]).is_file()]
    serial_changed, _, _ = classify_files(ctx, changed_tests)
    trigger = _windows_trigger(ctx, {f for f, why in serial_changed.items() if why})
    if not trigger:
        if deferred:  # never drop deferred spawning ratchets silently (Defender C11)
            return CheckResult(WARN, f"{len(deferred)} PowerShell-spawning ratchet(s) deferred from ratchets did not "
                               f"run (no .ps1, workflow or PowerShell-starting test in the night span): "
                               f"{', '.join(deferred)}", details=deferred,
                               evidence={"deferred_ratchets": deferred, "not_run": deferred})
        return CheckResult(INFO, "no .ps1, workflow or PowerShell-starting test in the night span",
                           evidence={"deferred_ratchets": deferred})
    twins = script_twins(wt, trigger)
    tests = ctx.results.get("tests")
    ran = tests is not None and tests.status in (PASS, WARN, FAIL)
    full_ran = ran and tests.evidence.get("mode_effective") == "full"
    covered = set(tests.evidence.get("files") or []) if ran else set()
    files = sorted(set(deferred) | set(twins) | {t for t in trigger if is_test_file(t)})
    files = [] if full_ran else [f for f in files if (wt / f).is_file() and f not in covered]
    evidence = {"trigger": trigger, "deferred_ratchets": deferred, "twins": twins, "already_run_by_tests": sorted(covered),
                "files": files}
    if not files:
        return CheckResult(WARN, "PowerShell surface covered by the tests run; local full suite until the Windows lane",
                           evidence=evidence)
    full = len(files) + PYTEST_FIXED_ARGUMENTS > WRAPPER_MAX_ARGUMENTS
    result, junit, not_run = run_pytest(ctx, "winps", ["tests"] if full else files, route="wrapper")
    closure_warnings = wrapper_closure_warnings(ctx)
    evidence["warnings"] = closure_warnings
    status, summary = _outcome(result, junit, not_run)
    details, attribution = [], []
    if status == FAIL:
        head_changed, _, earlier_by = step_changes(ctx)
        details = classify_failures(ctx, junit["failures"], earlier_by, head_changed)
        attribution = [{"item": d["nodeid"], "introduced_by": ",".join(d["introduced_by"]) or d["class"],
                        "class": d["class"]} for d in details]
    elif status == PASS:
        status, summary = WARN, summary + "; local full suite until the Windows lane" + (
            "; " + closure_warnings[0] if closure_warnings else "")
    return CheckResult(status, f"{summary} [wrapper]", details=details, attribution=attribution,
                       evidence={**evidence, "route": "wrapper", "junit": {k: v for k, v in junit.items() if k != "failures"}},
                       command=result.argv if result else None, exit_code=result.exit_code if result else None,
                       output_tail=_short(result.tail() if result else ""))


def register_checks(registry: CheckRegistry) -> None:
    registry.register(CheckSpec("ratchets", PHASE_WORKTREE, _ratchets, OWNER, ("import_probe",),
                                "-m ratchet files (or the static list) direct, <= 25 files, no PowerShell spawners"))
    registry.register(CheckSpec("tests", PHASE_TESTS, _tests, OWNER, ("import_probe",),
                                "F6 interaction selection; direct or workstation_heavy -Queue; head/interaction classes"))
    registry.register(CheckSpec("windows_scripts", PHASE_TESTS, _windows_scripts, OWNER, ("import_probe",),
                                "PowerShell-spawning ratchets via the wrapper when .ps1/workflows change"))
