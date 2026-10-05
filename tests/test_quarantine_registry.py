"""Repository checks for the quarantine marker; run in CI's fast audit job.

* The suite-wide hooks are registered: a bad merge of ``tests/conftest.py`` that drops
  them would otherwise leave quarantined failures fatal (or expiries silent) while the
  pytester tests in ``test_quarantine_marker.py`` stay green.
* ``tests/quarantine_registry.json`` lists exactly the quarantined tests, and every
  marker agrees with its entry (found by AST, without importing the test modules).
* A passed sunset fails here under GitHub Actions and is only reported elsewhere, the
  same rule the plugin applies at collection.
"""

from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path

import pytest

from tests import quarantine_plugin

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS = (
    "pytest_addoption",
    "pytest_configure",
    "pytest_collection_modifyitems",
    "pytest_runtest_makereport",
    "pytest_terminal_summary",
)


def _quarantine_call(node: ast.AST) -> ast.Call | None:
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == quarantine_plugin.MARKER
            and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "mark"):
        return node
    return None


def _markers_in(nodes: list[ast.AST]) -> list[ast.Call]:
    return [call for node in nodes for sub in ast.walk(node) if (call := _quarantine_call(sub))]


def _tests_in(body: list[ast.stmt], prefix: str, inherited: list[ast.Call]):
    for node in body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            yield from _tests_in(node.body, f"{prefix}{node.name}::", inherited + _markers_in(node.decorator_list))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            yield f"{prefix}{node.name}", inherited + _markers_in(node.decorator_list)


def quarantined_tests() -> dict[str, list[ast.Call]]:
    found: dict[str, list[ast.Call]] = {}
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_marks = _markers_in([
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets)
        ])
        if not module_marks and not _markers_in([tree]):
            continue
        prefix = path.relative_to(REPO_ROOT).as_posix() + "::"
        for key, marks in _tests_in(tree.body, prefix, module_marks):
            if marks:
                found[key] = marks
    return found


def test_conftest_registers_every_quarantine_hook(request: pytest.FixtureRequest) -> None:
    plugins = request.config.pluginmanager.get_plugins()
    for name in HOOKS:
        hook = getattr(quarantine_plugin, name)
        assert any(getattr(plugin, name, None) is hook for plugin in plugins), (
            f"tests/conftest.py no longer registers quarantine_plugin.{name}"
        )
    names = [line.split(":", 1)[0].split("(", 1)[0].strip() for line in request.config.getini("markers")]
    assert quarantine_plugin.MARKER in names


def test_registry_lists_exactly_the_quarantined_tests_and_agrees_with_each_marker() -> None:
    entries = quarantine_plugin.load_registry(REPO_ROOT / quarantine_plugin.DEFAULT_REGISTRY)
    found = quarantined_tests()
    assert sorted(entries) == sorted(found), (
        f"{quarantine_plugin.DEFAULT_REGISTRY} must list exactly the quarantined tests"
    )
    on = quarantine_plugin.today()
    expired = []
    for key, marks in found.items():
        assert len(marks) == 1, f"{key}: more than one quarantine marker applies"
        call = marks[0]
        kwargs = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
        args = tuple(ast.literal_eval(arg) for arg in call.args)
        quarantine = quarantine_plugin.parse_arguments(args, kwargs, on=on)
        quarantine_plugin.check_registry(key, quarantine, entries)
        if quarantine.sunset < on:
            expired.append(f"{key}: sunset {quarantine.sunset.isoformat()} has passed")
    if expired and os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        pytest.fail("expired quarantine(s):\n" + "\n".join(expired))
    for message in expired:
        warnings.warn(quarantine_plugin.QuarantineExpiredWarning(message))


def test_registry_scan_finds_function_class_and_module_markers(tmp_path: Path) -> None:
    source = '''
import pytest
pytestmark = [pytest.mark.quarantine(reason="m", added="2026-01-01", sunset="2026-01-02")]

def test_module_level():
    pass

class TestC:
    def test_method(self):
        pass
'''
    tree = ast.parse(source)
    module_marks = _markers_in([tree.body[1].value])
    keys = dict(_tests_in(tree.body, "x.py::", module_marks))
    assert sorted(keys) == ["x.py::TestC::test_method", "x.py::test_module_level"]
    assert all(len(marks) == 1 for marks in keys.values())
