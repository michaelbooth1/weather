"""The live runner must keep sharing the operator's console with its PowerShell child.

Guards: cooperative Ctrl+Break cleanup of the live launcher (#229, docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md).
Ctrl+Break is a console event: it only reaches processes on the sender's console. The
repository ``sitecustomize.py`` and ``weather.operations.windows_silent`` wrap
``subprocess.Popen`` to add CREATE_NO_WINDOW, which gives the child its own console and
silently drops the break (root cause of the 2026-10-06 host failures). The live
template starts the runner with ``python -I -S`` so neither patch can load. These
guards fail if the template loses isolation or if the runner's import closure ever
reaches a console-silencing module.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from weather.operations import international_live_session_runner as runner

pytestmark = pytest.mark.spawns

SRC = Path(runner.__file__).resolve().parents[2]
REPO = SRC.parent
TEMPLATE = REPO / "scripts" / "ops" / "international_live_templates" / "fixed_session_launcher.ps1.tmpl"
RUNNER_MODULE = "weather.operations.international_live_session_runner"
SILENCER_MODULE = "weather.operations.windows_silent"
SILENCER_CALL = "apply_windows_silent_subprocess_defaults"
POWERSHELL = os.path.join(os.environ.get("SystemRoot", "C:" + os.sep + "Windows"),
                          "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
BLOCK_START = "$runnerArguments = ConvertTo-WeatherWindowsArgumentString -Tokens @("
BLOCK_END = "\n        )"
windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell evaluates the live template")


def _runner_tokens() -> list[str]:
    """The runner's argument tokens as Windows PowerShell itself evaluates the template's @(...) block."""
    text = TEMPLATE.read_text(encoding="utf-8-sig")
    start = text.index(BLOCK_START)
    block = text[text.index("@(", start): text.index(BLOCK_END, start) + len(BLOCK_END)]
    script = "\n".join([
        "$manifest = 'manifest.json'; $expectedManifestSha256 = 'sha'; $candidate = 'candidate'",
        "$tokens = " + block,
        "ConvertTo-Json -InputObject @($tokens) -Compress",
    ])
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@windows_only
def test_live_template_starts_the_runner_isolated():
    tokens = _runner_tokens()
    head = tokens[: tokens.index("-c")]
    assert "-I" in head and "-S" in head, head  # never loads sitecustomize or site .pth hooks
    bootstrap = tokens[tokens.index("-c") + 1]
    assert "runpy.run_module('" + RUNNER_MODULE + "'" in bootstrap
    assert "sys.path.insert(0,os.environ['WEATHER_FIXED_SESSION_SRC'])" in bootstrap


@windows_only
def test_runner_import_under_isolation_leaves_popen_unpatched():
    """Execution twin of the template check: the template's own flags and bootstrap, then the import."""
    tokens = _runner_tokens()
    flags = tokens[: tokens.index("-c")]
    prefix = tokens[tokens.index("-c") + 1].split("runpy.run_module(")[0]
    probe = prefix + (
        "import json,subprocess;before=subprocess.Popen;"
        "import " + RUNNER_MODULE + " as r;"
        "print(json.dumps({'patched': subprocess.Popen is not before or "
        "bool(getattr(subprocess.Popen,'_weather_silent_windows_children',False)),"
        "'silencer': '" + SILENCER_MODULE + "' in sys.modules,'sitecustomize': 'sitecustomize' in sys.modules}))"
    )
    env = {k: v for k, v in os.environ.items() if k != "WEATHER_ALLOW_CONSOLE_CHILDREN"}
    env.update(WEATHER_FIXED_SESSION_SRC=str(SRC),
               WEATHER_FIXED_SESSION_SITE_PACKAGES=sysconfig.get_paths()["purelib"],
               PYTHONPATH=str(REPO))  # isolation must ignore it
    result = subprocess.run([sys.executable, *flags, "-c", probe], capture_output=True, text=True,
                            env=env, cwd=str(REPO), timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {
        "patched": False, "silencer": False, "sitecustomize": False}


def _module_path(module: str) -> Path | None:
    base = SRC.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imports(module: str, tree: ast.AST, is_package: bool) -> set[str]:
    found: set[str] = set()
    package = module if is_package else module.rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                target = base + "." + node.module if node.module else base
            else:
                target = node.module or ""
            found.add(target)
            found.update(target + "." + alias.name for alias in node.names)
    return found


def test_runner_import_closure_never_reaches_a_console_silencer():
    seen: set[str] = set()
    calls: list[str] = []
    stack = [RUNNER_MODULE]
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        path = _module_path(module)
        if path is None:
            continue
        seen.add(module)
        if "." in module:  # importing a submodule runs its packages' __init__ too
            stack.append(module.rsplit(".", 1)[0])
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Call)
               and getattr(node.func, "id", getattr(node.func, "attr", None)) == SILENCER_CALL
               for node in ast.walk(tree)):
            calls.append(module)
        stack.extend(name for name in _imports(module, tree, path.name == "__init__.py")
                     if name.startswith("weather") or name == "sitecustomize")
    assert RUNNER_MODULE in seen and len(seen) > 5, sorted(seen)
    assert SILENCER_MODULE not in seen, "the live runner's import closure reaches windows_silent"
    assert "sitecustomize" not in seen
    assert not calls, "modules in the runner's closure call " + SILENCER_CALL + ": " + str(calls)


def test_the_closure_check_sees_a_silencer_when_one_is_imported(monkeypatch):
    """Mutant: a closure that does reach windows_silent must be reported."""
    real = _imports

    def with_silencer(module, tree, is_package):
        found = real(module, tree, is_package)
        return found | {SILENCER_MODULE} if module == RUNNER_MODULE else found

    monkeypatch.setattr(sys.modules[__name__], "_imports", with_silencer)
    with pytest.raises(AssertionError, match="reaches windows_silent"):
        test_runner_import_closure_never_reaches_a_console_silencer()
