"""The Linux CI jobs' pytest selections partition the suite: every test runs once, none twice.

``ci.yml`` splits the Linux suite by marker. The ``test`` job runs the whole ``testpaths``
with ``-m "not ratchet and not memory_flatness"``, the parallel ``memory-flatness`` job runs
the whole ``testpaths`` with ``-m "memory_flatness and not ratchet"``, and the fast ``audit``
job runs ``-m ratchet <files>``. A job that also names test files and a marker expression
(``pytest -m <expr> <files>``) is a further partition member that only selects tests in
those files.

The proof is by truth table, so it holds for any test, present or future: for every file
that a file-scoped member names, and for every other file, and for every combination of the
marker names the expressions use, exactly one invocation selects the test. It is sound only
while no full-suite invocation narrows its selection in any other way, which is asserted too.

One exception is allowed: a file-scoped run *without* a marker expression in the fast
``audit`` job is a fail-fast gate that deliberately repeats a few files the ``test`` job also
runs. It is outside the partition (the ``test`` job still runs those files once).

The workflow is read as text and the tests are scanned by AST (no imports).
"""

from __future__ import annotations

import ast
import configparser
import itertools
import re
import shlex
from pathlib import Path

from _pytest.mark.expression import Expression

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MARKER = "memory_flatness"
MEMORY_JOB = "memory-flatness"
# Options that would narrow a run's selection beyond its marker expression and paths.
NARROWING_OPTIONS = (
    "-k", "--deselect", "--ignore", "--ignore-glob", "--lf", "--last-failed", "--ff",
    "--failed-first", "--sw", "--stepwise", "--co", "--collect-only", "-x", "--exitfirst",
    "--maxfail", "--pyargs",
)
# Options whose value is the next token when not written as --option=value.
VALUED_OPTIONS = ("-p", "-o", "--junitxml", "--junit-xml", "--basetemp", "--rootdir", "-c")


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


def pytest_runs() -> dict[str, list[tuple[str | None, list[str], list[str]]]]:
    """{job: [(marker expression, paths, other options)]} for every pytest run in ci.yml."""
    out: dict[str, list[tuple[str | None, list[str], list[str]]]] = {}
    for job, block in _job_blocks(CI_WORKFLOW.read_text(encoding="utf-8")).items():
        for command in _run_commands(block):
            for line in command.splitlines():
                if line.startswith("python -m pytest"):
                    out.setdefault(job, []).append(split_selection(shlex.split(line)[3:]))
    return out


def split_selection(argv: list[str]) -> tuple[str | None, list[str], list[str]]:
    expression, paths, other = None, [], []
    tokens = iter(argv)
    for token in tokens:
        if token == "-m":
            expression = next(tokens)
        elif token in VALUED_OPTIONS:
            other.append(f"{token} {next(tokens)}")
        elif token.startswith("-"):
            other.append(token)
        else:
            paths.append(token)
    return expression, paths, other


def _marker_names(expression: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)) - {"and", "or", "not"}


def _selects(expression: str | None, markers: frozenset[str]) -> bool:
    if not expression:
        return True
    return Expression.compile(expression).evaluate(lambda name, /, **kwargs: name in markers)


def files_using_marker(name: str) -> set[str]:
    """Test files that apply ``pytest.mark.<name>`` anywhere (or add it by name)."""
    found = set()
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            by_attribute = (
                isinstance(node, ast.Attribute) and node.attr == name
                and isinstance(node.value, ast.Attribute) and node.value.attr == "mark"
            )
            by_name = (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_marker"
                and any(isinstance(arg, ast.Constant) and arg.value == name for arg in node.args)
            )
            if by_attribute or by_name:
                found.add(path.relative_to(REPO_ROOT).as_posix())
                break
    return found


def _partition_members():
    """(full-suite expressions, [(expression, files)] file-scoped members) of the partition."""
    full, scoped = [], []
    for job, runs in pytest_runs().items():
        for expression, paths, _ in runs:
            if not paths:
                full.append(expression)
            elif expression:
                scoped.append((expression, paths))
            else:
                assert job == "audit", f"{job}: a file-scoped pytest run needs a marker expression"
    return full, scoped


def test_memory_flatness_marker_is_registered() -> None:
    config = configparser.ConfigParser()
    config.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    names = [line.split(":", 1)[0].strip() for line in config["pytest"]["markers"].splitlines() if line.strip()]
    assert MARKER in names


def test_full_suite_runs_are_split_only_by_marker() -> None:
    runs = pytest_runs()
    assert sorted(runs) == ["audit", MEMORY_JOB, "test"]
    for job, job_runs in runs.items():
        for expression, paths, other in job_runs:
            for option in other:
                flag = option.split()[0].split("=", 1)[0]
                assert flag not in NARROWING_OPTIONS, f"{job}: {option} narrows the selection"
            assert all(path.startswith("tests/") for path in paths), (job, paths)
    for job in ("test", MEMORY_JOB):
        assert len(runs[job]) == 1, f"{job}: exactly one pytest run"
        expression, paths, _ = runs[job][0]
        assert paths == [], f"{job}: runs the whole configured testpaths"
        assert expression and MARKER in _marker_names(expression), job


def test_ci_selections_partition_the_suite() -> None:
    full, scoped = _partition_members()
    # The partition spans all three Linux jobs: two full-suite runs plus the audit
    # job's file-scoped ratchet run (test_ci_ratchet_selection.py pins its file list).
    assert len(full) == 2 and len(scoped) == 1
    assert _marker_names(scoped[0][0]) == {"ratchet"}
    names = {MARKER}
    for expression in full + [expression for expression, _ in scoped]:
        if expression:
            names |= _marker_names(expression)
    names = sorted(names)

    # A marker a file-scoped member selects on must only be used in files it names;
    # otherwise a test elsewhere carrying it could be dropped.
    scoped_markers: set[str] = set()
    for expression, files in scoped:
        for name in _marker_names(expression):
            stray = files_using_marker(name) - set(files)
            assert not stray, f"marker {name!r} is used outside the run that selects it: {sorted(stray)}"
            scoped_markers.add(name)

    def count(path: str | None, markers: frozenset[str]) -> int:
        total = sum(_selects(expression, markers) for expression in full)
        total += sum(path in files and _selects(expression, markers) for expression, files in scoped)
        return total

    scoped_files = sorted({path for _, files in scoped for path in files})
    for path in [*scoped_files, None]:
        usable = names if path is not None else [name for name in names if name not in scoped_markers]
        for present in itertools.product((False, True), repeat=len(usable)):
            markers = frozenset(name for name, on in zip(usable, present) if on)
            runs = count(path, markers)
            where = path or "any other file"
            assert runs == 1, f"a test in {where} with markers {sorted(markers)} runs {runs} time(s)"


def test_memory_flatness_job_matches_the_test_job_environment() -> None:
    blocks = _job_blocks(CI_WORKFLOW.read_text(encoding="utf-8"))

    def setup(job: str) -> list[str]:
        lines = []
        for line in blocks[job]:
            if line.strip().startswith("- name: Run"):
                break
            if line.strip() and not line.strip().startswith("#"):
                lines.append(line)
        return lines

    assert setup(MEMORY_JOB) == setup("test")
    assert "linux-junit" in "\n".join(blocks[MEMORY_JOB]), "the memory job uploads its JUnit"


def test_the_memory_job_selects_marked_tests_only_in_test_functions() -> None:
    files = files_using_marker(MARKER)
    assert files, "no test carries the memory_flatness marker; drop the memory-flatness job"
    for relative in sorted(files):
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Attribute) and decorator.attr == MARKER:
                        assert node.name.startswith(("test", "Test")), f"{relative}::{node.name}"
