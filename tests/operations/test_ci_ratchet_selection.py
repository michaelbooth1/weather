"""Every ratchet runs exactly once per CI run, across every workflow, Windows included.

* ``ci.yml``: the fast ``audit`` job runs ``pytest -m ratchet <files>`` and the ``test``
  job runs ``pytest -m "not ratchet"`` over the whole ``testpaths``. Their union is the
  full Linux collection and they are disjoint when the two marker expressions are exact
  complements, the ``test`` job applies no other selection, and the audit file list names
  every file that applies the ``ratchet`` marker.
* ``windows-qualification.yml``: a ratchet that only executes on Windows (it skips off
  Windows) also carries ``windows_native`` and runs in exactly one shard. Every other
  ratchet executes on Linux only: a shard that lists a ratchet file deselects it.
* ``host-load-hook.yml`` runs no ratchet file.

"Runs" means executes: a ``windows_native`` ratchet is collected but skipped on Linux.
The workflows are read as text and the tests are scanned by AST (no imports).
"""

from __future__ import annotations

import ast
import configparser
import itertools
import re
import shlex
from pathlib import Path

import pytest
from _pytest.mark.expression import Expression

pytestmark = pytest.mark.ratchet

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW = WORKFLOWS / "ci.yml"
WINDOWS_WORKFLOW = WORKFLOWS / "windows-qualification.yml"
HOOK_WORKFLOW = WORKFLOWS / "host-load-hook.yml"
SELECTION_OPTIONS = ("-k", "--deselect", "--ignore", "--ignore-glob", "--lf", "--last-failed",
                     "--ff", "--sw", "--stepwise", "--co", "--collect-only", "-x", "--exitfirst",
                     "--maxfail", "--pyargs")
PORTABLE = frozenset({"ratchet"})
WINDOWS_NATIVE = frozenset({"ratchet", "windows_native"})


def _job_blocks(text: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    start = lines.index("jobs:")
    jobs: dict[str, list[str]] = {}
    current = None
    for line in lines[start + 1:]:
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if match:
            current = match.group(1)
            jobs[current] = []
        elif current is not None:
            jobs[current].append(line)
    return jobs


def _run_commands(block: list[str]) -> list[str]:
    commands = []
    for index, line in enumerate(block):
        match = re.fullmatch(r"(\s*)(?:- )?run:\s*(.*)", line)
        if not match:
            continue
        indent, value = len(match.group(1)), match.group(2).strip()
        if value in (">-", ">", "|", "|-"):
            body = []
            for follow in block[index + 1:]:
                if follow.strip() and len(follow) - len(follow.lstrip()) <= indent:
                    break
                body.append(follow.strip())
            joiner = " " if value.startswith(">") else "\n"
            value = joiner.join(part for part in body if part)
        commands.append(value)
    return commands


def pytest_invocations(workflow: Path = CI_WORKFLOW) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for job, block in _job_blocks(workflow.read_text(encoding="utf-8")).items():
        for command in _run_commands(block):
            for line in command.splitlines():
                if not line.startswith("python -m pytest"):
                    continue
                out.setdefault(job, []).append(shlex.split(line)[3:])
    return out


def split_selection(argv: list[str]) -> tuple[str | None, list[str], list[str]]:
    """Return (marker expression, positional paths, other options) of one pytest argv."""
    expression, paths, other = None, [], []
    tokens = iter(argv)
    for token in tokens:
        if token == "-m":
            expression = next(tokens)
        elif token == "-p":
            other.append(f"-p {next(tokens)}")
        elif token.startswith("-"):
            other.append(token)
        else:
            paths.append(token)
    return expression, paths, other


def windows_shards() -> list[dict[str, object]]:
    """The native-launch matrix: shard, select (-k), mark (-m) and files of each entry."""
    lines = WINDOWS_WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "include:")
    shards: list[dict[str, object]] = []
    in_files = False
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("          "):
            break
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        entry = re.fullmatch(r"- shard:\s*(\S+)", stripped)
        if entry:
            shards.append({"shard": entry.group(1), "select": "", "mark": "", "files": []})
            in_files = False
            continue
        key = re.fullmatch(r"(select|mark|files):\s*(.*)", stripped)
        if key and line.startswith("            ") and not line.startswith("             "):
            in_files = key.group(1) == "files"
            if not in_files:
                value = key.group(2).strip()
                shards[-1][key.group(1)] = value[1:-1] if value[:1] in "'\"" else value
            continue
        if in_files:
            shards[-1]["files"].append(stripped)
    return shards


def _decorator_marks(decorators: list[ast.expr]) -> set[str]:
    marks = set()
    for node in decorators:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Attribute) and sub.value.attr == "mark":
                marks.add(sub.attr)
    return marks


def _skips_off_windows(decorators: list[ast.expr]) -> bool:
    for node in decorators:
        if isinstance(node, ast.Call) and "skipif" in _decorator_marks([node]) and node.args:
            condition = ast.unparse(node.args[0]).replace("'", '"')
            if condition in ('os.name != "nt"', 'sys.platform != "win32"', 'not sys.platform.startswith("win")'):
                return True
    return False


def ratchet_tests() -> dict[str, dict[str, frozenset[str]]]:
    """{file: {test: marker set}} for every test carrying the ratchet marker."""
    found: dict[str, dict[str, frozenset[str]]] = {}
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_marks = _decorator_marks([
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets)
        ])

        def visit(body, prefix, inherited):
            for node in body:
                if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                    yield from visit(node.body, f"{prefix}{node.name}::", inherited | _decorator_marks(node.decorator_list))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                    marks = inherited | _decorator_marks(node.decorator_list)
                    if "windows_native" in marks or "ratchet" in marks:
                        yield f"{prefix}{node.name}", frozenset(marks & {"ratchet", "windows_native"}), \
                            _skips_off_windows(node.decorator_list)

        rows = list(visit(tree.body, "", module_marks))
        if rows:
            found[path.relative_to(REPO_ROOT).as_posix()] = {
                name: marks | ({"skips_off_windows"} if skips else set()) for name, marks, skips in rows
            }
    return found


def files_using_ratchet_marker() -> set[str]:
    found = set()
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            marks_attribute = (
                isinstance(node, ast.Attribute) and node.attr == "ratchet"
                and isinstance(node.value, ast.Attribute) and node.value.attr == "mark"
            )
            adds_marker_by_name = (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_marker"
                and any(isinstance(arg, ast.Constant) and arg.value == "ratchet" for arg in node.args)
            )
            if marks_attribute or adds_marker_by_name:
                found.add(path.relative_to(REPO_ROOT).as_posix())
                break
    return found


def _selects(expression: str | None, markers: frozenset[str]) -> bool:
    if not expression:
        return True
    return Expression.compile(expression).evaluate(lambda name, /, **kwargs: name in markers)


def test_ratchet_markers_are_registered() -> None:
    config = configparser.ConfigParser()
    config.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    names = [line.split(":", 1)[0].strip() for line in config["pytest"]["markers"].splitlines() if line.strip()]
    assert {"ratchet", "windows_native"} <= set(names)


def test_each_ci_job_has_one_pytest_run_split_only_by_the_ratchet_marker() -> None:
    runs = pytest_invocations()
    assert sorted(runs) == ["audit", "test"]
    assert len(runs["audit"]) == 1 and len(runs["test"]) == 1

    audit_expression, audit_paths, audit_other = split_selection(runs["audit"][0])
    test_expression, test_paths, test_other = split_selection(runs["test"][0])
    assert audit_expression == "ratchet"
    assert test_expression == "not ratchet"
    # The test job runs the whole configured testpaths; neither job narrows further.
    assert test_paths == []
    for option in audit_other + test_other:
        assert option.split()[0] not in SELECTION_OPTIONS, option
        assert not option.startswith(("-k", "--deselect=", "--ignore=", "--maxfail=")), option
    assert audit_paths and all(path.startswith("tests/") for path in audit_paths)


def test_the_two_marker_expressions_are_exact_complements() -> None:
    runs = pytest_invocations()
    audit = split_selection(runs["audit"][0])[0]
    test = split_selection(runs["test"][0])[0]
    names = ("ratchet", "windows_native", "parametrize", "skipif", "quarantine", "slow")
    for present in itertools.product((False, True), repeat=len(names)):
        markers = frozenset(name for name, on in zip(names, present) if on)
        assert _selects(audit, markers) != _selects(test, markers), markers


def test_audit_job_lists_exactly_the_files_that_use_the_ratchet_marker() -> None:
    runs = pytest_invocations()
    _, audit_paths, _ = split_selection(runs["audit"][0])
    assert len(audit_paths) == len(set(audit_paths))
    for path in audit_paths:
        assert (REPO_ROOT / path).is_file(), path
    missing = files_using_ratchet_marker() - set(audit_paths)
    stale = set(audit_paths) - files_using_ratchet_marker()
    assert not missing, f"add these files to the audit job's ratchet step in ci.yml: {sorted(missing)}"
    assert not stale, f"these audit-job files no longer use the ratchet marker: {sorted(stale)}"


def test_windows_native_marks_exactly_the_ratchets_that_skip_off_windows() -> None:
    for path, tests in ratchet_tests().items():
        for name, marks in tests.items():
            assert "ratchet" in marks, f"{path}::{name}: windows_native is only for ratchets"
            assert ("windows_native" in marks) == ("skips_off_windows" in marks), (
                f"{path}::{name}: a ratchet that skips off Windows must be marked windows_native, and only it"
            )


def test_every_ratchet_executes_exactly_once_across_all_workflows() -> None:
    runs = pytest_invocations()
    audit_expression, audit_paths, _ = split_selection(runs["audit"][0])
    test_expression = split_selection(runs["test"][0])[0]
    shards = windows_shards()
    assert shards and len({shard["shard"] for shard in shards}) == len(shards)
    for path, tests in ratchet_tests().items():
        for name, marks in tests.items():
            category = WINDOWS_NATIVE if "windows_native" in marks else PORTABLE
            linux = 0
            if category == PORTABLE:  # a windows_native ratchet only skips on Linux
                linux += path in audit_paths and _selects(audit_expression, category)
                linux += _selects(test_expression, category)
            windows = 0
            for shard in shards:
                if path in shard["files"] and _selects(shard["mark"], category):
                    assert not shard["select"], f"{shard['shard']}: do not split a ratchet file with -k"
                    windows += 1
            assert linux + windows == 1, (
                f"{path}::{name} ({sorted(category)}) executes {linux} time(s) on Linux and "
                f"{windows} time(s) in Windows shards"
            )


def test_no_other_workflow_runs_a_ratchet_file() -> None:
    ratchet_files = set(ratchet_tests())
    with_pytest = sorted(path.name for path in WORKFLOWS.glob("*.yml") if "pytest" in path.read_text(encoding="utf-8"))
    assert with_pytest == ["ci.yml", "host-load-hook.yml", "windows-qualification.yml"]
    hook_text = HOOK_WORKFLOW.read_text(encoding="utf-8")
    hook_files = set(re.findall(r"tests/\S+\.py", hook_text))
    assert hook_files and not hook_files & ratchet_files
