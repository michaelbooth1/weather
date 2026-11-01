"""No raw parent-PID tree kill anywhere in tests, scripts, src or tools.

Guards: master ruling 2026-11-01 (lane L33): the Windows task-kill tool's tree switch walks
``ParentProcessId``, so it also kills any long-lived orphan whose dead parent's PID was
reused by the target; that most likely killed all ten workstation forward recorders at
22:06Z on 2026-11-01. Child trees are owned by kill-on-close Jobs instead
(``scripts/ops/windows_kill_on_close_job.ps1``, ``tests/process_job.py``).

The allowlist is empty. This file never spells the tool name literally, so it cannot
flag itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.ratchet

ROOT = Path(__file__).resolve().parents[2]
SCANNED_ROOTS = ("tests", "scripts", "src", "tools")
SCANNED_SUFFIXES = frozenset({
    ".py", ".ps1", ".psm1", ".psd1", ".tmpl", ".cmd", ".bat", ".sh", ".vbs", ".js",
})
SKIPPED_PARTS = frozenset({"__pycache__", "venv", ".venv", "node_modules"})
ALLOWLIST: frozenset[str] = frozenset()

_TOOL = "task" + "kill"
_TOOL_PATTERN = re.compile(r"(?i)\b" + _TOOL + r"(?:\.exe)?\b")
# The tree switch as its own token: "/T" or "-T", any case, quoted or bare.
_TREE_SWITCH = re.compile(r"""(?i)(?:^|[\s"',(\[])[/-]t(?=$|[\s"',)\]])""")
# An invocation ends at a closing bracket, a pipe or statement separator, or a
# line break that is not a continuation (after , ` \ ( [ the call goes on).
_INVOCATION_END = re.compile(r"[\])|;]|(?<![,`\\(\[\s])[ \t]*\r?\n")
_WINDOW = 240


def tree_kill_invocations(text: str) -> list[int]:
    """1-based line numbers where the task-kill tool is invoked with its tree switch."""
    hits = []
    for match in _TOOL_PATTERN.finditer(text):
        window = text[match.end(): match.end() + _WINDOW]
        end = _INVOCATION_END.search(window)
        if end is not None:
            window = window[: end.start()]
        if _TREE_SWITCH.search(window):
            hits.append(text.count("\n", 0, match.start()) + 1)
    return hits


def _scanned_files():
    for name in SCANNED_ROOTS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() in SCANNED_SUFFIXES and path.is_file() and not (
                SKIPPED_PARTS & set(path.relative_to(ROOT).parts)
            ):
                yield path


def test_no_tree_kill_invocation_in_tests_scripts_src_or_tools():
    found = []
    for path in _scanned_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _TOOL not in text.lower():
            continue
        found += [f"{relative}:{line}" for line in tree_kill_invocations(text)]
    assert not found, (
        "parent-PID tree kill found; own the child tree with a kill-on-close Job "
        "(scripts/ops/windows_kill_on_close_job.ps1 or tests/process_job.py) instead:\n"
        + "\n".join(found)
    )


def test_allowlist_stays_empty():
    assert ALLOWLIST == frozenset()


@pytest.mark.parametrize(
    "snippet",
    [
        f'subprocess.run(["{_TOOL}", "/T", "/F", "/PID", str(pid)])',
        f'subprocess.run(["{_TOOL}", "/PID", str(pid), "/T", "/F"])',
        f'_run(["{_TOOL}.exe",\n      "/f", "/t", "/pid", pid])',
        f"{_TOOL.upper()} /PID $child.Id /T /F | Out-Null",
        f"& {_TOOL} -t -f -pid $p",
        f"{_TOOL} /PID $p `\n    /T /F",
        f"cmd /c {_TOOL} /f /t /im python.exe",
    ],
)
def test_detector_flags_tree_switch_in_every_spelling(snippet):
    assert tree_kill_invocations(snippet) == [1]


@pytest.mark.parametrize(
    "snippet",
    [
        f'subprocess.run(["{_TOOL}", "/F", "/PID", str(pid)])',
        f"{_TOOL} /PID $p /F\n$t = '/T'",
        f"{_TOOL} /PID $p /F; Write-Host /T",
        f"# the {_TOOL} tool is never used for trees",
        f'{_TOOL} /FI "WINDOWTITLE eq T" /F',
        f"{_TOOL} /PID $p /F | Select-String /T",
    ],
)
def test_detector_ignores_non_tree_invocations(snippet):
    assert tree_kill_invocations(snippet) == []


def test_detector_reports_each_invocation_line():
    text = f"x = 1\n{_TOOL} /PID 1 /T\ny = 2\n{_TOOL} /PID 2 /F\n{_TOOL} /T /PID 3\n"
    assert tree_kill_invocations(text) == [2, 5]
