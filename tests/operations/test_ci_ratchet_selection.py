"""Every ratchet runs exactly once per CI run.

CI's fast ``audit`` job runs ``pytest -m ratchet <files>`` and the ``test`` job runs
``pytest -m "not ratchet"`` over the whole ``testpaths``. Their union is the full
collection and they are disjoint when (a) the two marker expressions are exact
complements, (b) the ``test`` job applies no other selection, and (c) the audit job's
file list names every file that applies the ``ratchet`` marker. These tests pin all
three by reading ``.github/workflows/ci.yml`` and scanning the test sources by AST.
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
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SELECTION_OPTIONS = ("-k", "--deselect", "--ignore", "--ignore-glob", "--lf", "--last-failed",
                     "--ff", "--sw", "--stepwise", "--co", "--collect-only", "-x", "--exitfirst",
                     "--maxfail", "--pyargs")


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


def pytest_invocations() -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for job, block in _job_blocks(CI_WORKFLOW.read_text(encoding="utf-8")).items():
        for command in _run_commands(block):
            for line in command.splitlines():
                argv = shlex.split(line)
                if argv[:3] == ["python", "-m", "pytest"]:
                    out.setdefault(job, []).append(argv[3:])
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


def test_ratchet_marker_is_registered() -> None:
    config = configparser.ConfigParser()
    config.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    names = [line.split(":", 1)[0].strip() for line in config["pytest"]["markers"].splitlines() if line.strip()]
    assert "ratchet" in names


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
    audit = Expression.compile(split_selection(runs["audit"][0])[0])
    test = Expression.compile(split_selection(runs["test"][0])[0])
    other_markers = ("parametrize", "skipif", "quarantine", "slow")
    for present in itertools.product((False, True), repeat=len(other_markers) + 1):
        markers = {name for name, on in zip(("ratchet",) + other_markers, present) if on}

        def matcher(name: str, /, **kwargs: object) -> bool:
            return name in markers

        assert audit.evaluate(matcher) != test.evaluate(matcher), markers


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
