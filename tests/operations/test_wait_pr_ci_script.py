"""Executes wait_pr_ci.ps1 against a stub gh that returns canned PR JSON."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "wait_pr_ci.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None,
    reason="Windows PowerShell 5.1 is required",
)

HEAD = "a" * 40


def _check(name: str, status: str = "COMPLETED", conclusion: str = "SUCCESS") -> dict[str, str]:
    return {"__typename": "CheckRun", "name": name, "workflowName": "CI", "status": status, "conclusion": conclusion}


def _run(tmp_path: Path, rollup: list[dict[str, str]] | None, *extra: str, head: str = HEAD,
         gh_fails: bool = False) -> subprocess.CompletedProcess[str]:
    payload = {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN",
               "headRefOid": head, "statusCheckRollup": rollup or []}
    (tmp_path / "pr.json").write_text(json.dumps(payload), encoding="utf-8")
    gh = tmp_path / "gh.cmd"
    gh.write_text("@echo off\r\nexit /b 1\r\n" if gh_fails else '@echo off\r\ntype "%~dp0pr.json"\r\n',
                  encoding="ascii")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-Pr", "7", "-Gh", str(gh), "-PollSeconds", "1", "-TimeoutSeconds", "1", *extra],
        capture_output=True, text=True, timeout=60,
    )


def test_green_on_expected_head(tmp_path: Path) -> None:
    rollup = [_check("tests"), _check("lint", conclusion="SKIPPED"),
              {"__typename": "StatusContext", "context": "ext", "state": "SUCCESS"}]
    result = _run(tmp_path, rollup, "-ExpectedHead", HEAD)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT: GREEN" in result.stdout


def test_any_failure_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, [_check("tests"), _check("lint", conclusion="FAILURE"), _check("slow", "IN_PROGRESS", "")])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RESULT: FAILED" in result.stdout


def test_moved_head_is_refused_even_when_green(tmp_path: Path) -> None:
    result = _run(tmp_path, [_check("tests")], "-ExpectedHead", "b" * 40)
    assert result.returncode == 4, result.stdout + result.stderr


def test_pending_times_out(tmp_path: Path) -> None:
    result = _run(tmp_path, [_check("tests"), _check("slow", "QUEUED", "")])
    assert result.returncode == 2, result.stdout + result.stderr


def test_no_checks_after_grace(tmp_path: Path) -> None:
    result = _run(tmp_path, None, "-NoChecksGraceSeconds", "0")
    assert result.returncode == 3, result.stdout + result.stderr


def test_gh_failures_are_bounded(tmp_path: Path) -> None:
    result = _run(tmp_path, None, "-MaxGhFailures", "1", gh_fails=True)
    assert result.returncode == 5, result.stdout + result.stderr


def test_script_is_read_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    for verb in ("pr merge", "pr comment", "run rerun", "pr review", "pr edit"):
        assert verb not in text
