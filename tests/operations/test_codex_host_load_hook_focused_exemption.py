"""Workstation focused-run exemption in the Codex host-load hook.

Guards: HOST_LOAD_POLICY "Workstation focused runs, FIFO queue and xdist" (owner decision
2026-10-04, P3) — at most 25 named non-serial test files may skip workstation_heavy.ps1 on the
non-capture workstation only; the capture-host branch (window, bounded suite) is unchanged.
"""

from __future__ import annotations

import base64
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / ".codex" / "hooks" / "pre_tool_use_host_load.py"
SPEC = importlib.util.spec_from_file_location("pre_tool_use_host_load_focused", HOOK_PATH)
assert SPEC and SPEC.loader
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)
ZONE = ZoneInfo("America/Toronto")
PROTECTED = datetime(2026, 10, 4, 14, 15, tzinfo=ZONE)
INSIDE_WINDOW = datetime(2026, 10, 5, 2, 0, tzinfo=ZONE)
PLAIN_TEST = "def test_ok():\n    assert 1 + 1 == 2\n"
POWERSHELL_TEST = (
    "import subprocess\n\n"
    "def test_runs_script():\n"
    "    subprocess.run(['powershell', '-NoProfile', '-Command', 'exit 0'], check=True)\n"
)


def _payload(command: str, cwd: Path) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _reason(result: dict | None) -> str:
    assert result is not None
    return result["hookSpecificOutput"]["permissionDecisionReason"]


def _fake_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _no_host_global_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    marker = tmp_path / "state" / "heavy_workload_v1.poison"
    monkeypatch.setattr(HOOK, "HOST_GLOBAL_STATE_MARKER", marker)
    return marker


def _workstation_command(files: list[Path], *extra: str) -> str:
    targets = " ".join(f"'{path}'" for path in files)
    return (
        f"& '{sys.executable}' -m pytest {targets} -q --basetemp 'C:\\wt\\bt-focused' "
        + " ".join(extra)
    ).strip()


# ----------------------------------------------------------------------------- accept cases
def test_workstation_admits_a_bounded_non_serial_run_at_any_hour(tmp_path: Path) -> None:
    files = [ROOT / "tests" / "test_artifacts.py", ROOT / "tests" / "test_io_streaming.py"]
    command = _workstation_command(files, "-k", "'not slow'")
    for now in (PROTECTED, INSIDE_WINDOW):
        assert HOOK.evaluate(_payload(command, ROOT), now=now, constrained_capture_host=False) is None


def test_relative_targets_resolve_against_the_payload_cwd(tmp_path: Path) -> None:
    command = (
        r".\venv\Scripts\python.exe -m pytest tests\test_artifacts.py::test_x "
        r"--basetemp=C:\wt\bt-rel -q"
    )
    assert HOOK.evaluate(_payload(command, ROOT), now=PROTECTED, constrained_capture_host=False) is None


def test_exactly_25_files_is_the_inclusive_limit(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, {f"tests/test_f{i:02d}.py": PLAIN_TEST for i in range(25)})
    arguments = [str(repo / f"tests/test_f{i:02d}.py") for i in range(25)] + ["--basetemp", "bt"]
    exempt, why = HOOK.focused_pytest_verdict(arguments, repo, repo_root=repo)
    assert exempt is True, why
    assert why == "focused run of 25 non-serial test file(s)"


def test_node_ids_of_one_file_count_once(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, {"tests/test_one.py": PLAIN_TEST})
    arguments = [
        "tests/test_one.py::test_ok",
        "tests/test_one.py::test_other",
        "--basetemp",
        "bt",
    ]
    assert HOOK.focused_pytest_verdict(arguments, repo, repo_root=repo) == (
        True,
        "focused run of 1 non-serial test file(s)",
    )


def test_a_workstation_offline_marker_does_not_block_a_focused_run(
    tmp_path: Path, _no_host_global_marker: Path
) -> None:
    repo = _fake_repo(tmp_path, {"tests/test_one.py": PLAIN_TEST})
    _no_host_global_marker.parent.mkdir(parents=True)
    _no_host_global_marker.write_text(
        json.dumps({"execution_host_profile": "workstation_offline_v1", "state": "ACTIVE"}),
        encoding="utf-8",
    )
    exempt, _why = HOOK.focused_pytest_verdict(["tests/test_one.py", "--basetemp", "bt"], repo, repo_root=repo)
    assert exempt is True


# ----------------------------------------------------------------------------- reject cases
def test_26_files_exceed_the_limit(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, {f"tests/test_f{i:02d}.py": PLAIN_TEST for i in range(26)})
    arguments = [str(repo / f"tests/test_f{i:02d}.py") for i in range(26)] + ["--basetemp", "bt"]
    assert HOOK.focused_pytest_verdict(arguments, repo, repo_root=repo) == (
        False,
        "26 test files exceed the 25-file focused-run limit",
    )
    command = _workstation_command([Path(value) for value in arguments[:-2]])
    denied = HOOK.evaluate(_payload(command, repo), now=PROTECTED, constrained_capture_host=False)
    assert "workstation_heavy.ps1" in _reason(denied)
    assert "26 test files exceed the 25-file focused-run limit" in _reason(denied)


def test_a_file_that_starts_powershell_is_serial(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, {"tests/test_plain.py": PLAIN_TEST, "tests/test_ps.py": POWERSHELL_TEST})
    exempt, why = HOOK.focused_pytest_verdict(
        ["tests/test_plain.py", "tests/test_ps.py", "--basetemp", "bt"], repo, repo_root=repo
    )
    assert exempt is False
    assert why == "test_ps.py starts PowerShell (serial until the marker exists)"


def test_the_real_powershell_admission_tests_are_serial() -> None:
    command = _workstation_command([ROOT / "tests/operations/test_workload_admission_script.py"])
    denied = HOOK.evaluate(_payload(command, ROOT), now=PROTECTED, constrained_capture_host=False)
    assert "test_workload_admission_script.py starts PowerShell" in _reason(denied)


def test_powershell_reached_through_a_local_helper_or_conftest_is_serial(tmp_path: Path) -> None:
    helper = "import subprocess\nSHELL = 'pwsh'\n\ndef run():\n    subprocess.run([SHELL])\n"
    repo = _fake_repo(
        tmp_path,
        {
            "tests/__init__.py": "",
            "tests/helpers/__init__.py": "",
            "tests/helpers/shell.py": helper,
            "tests/test_via_helper.py": "from tests.helpers.shell import run\n\ndef test_x():\n    run()\n",
            "tests/sub/conftest.py": "import subprocess\nPS = 'powershell.exe'\n",
            "tests/sub/test_via_conftest.py": PLAIN_TEST,
        },
    )
    assert HOOK.focused_pytest_verdict(
        ["tests/test_via_helper.py", "--basetemp", "bt"], repo, repo_root=repo
    ) == (False, "test_via_helper.py reaches PowerShell through shell.py")
    assert HOOK.focused_pytest_verdict(
        ["tests/sub/test_via_conftest.py", "--basetemp", "bt"], repo, repo_root=repo
    ) == (False, "test_via_conftest.py reaches PowerShell through conftest.py")


def test_powershell_names_without_a_spawn_import_are_not_serial(tmp_path: Path) -> None:
    text_only = (
        "from pathlib import Path\n\ndef test_x():\n"
        "    assert Path('a.ps1').suffix == '.ps1', 'PowerShell script expected'\n"
    )
    spawning = "import subprocess\n\ndef test_x():\n    subprocess.run(['run.ps1'])\n"
    repo = _fake_repo(tmp_path, {"tests/test_text.py": text_only, "tests/test_spawn.py": spawning})
    assert HOOK.focused_pytest_verdict(["tests/test_text.py", "--basetemp", "bt"], repo, repo_root=repo) == (
        True,
        "focused run of 1 non-serial test file(s)",
    )
    assert HOOK.focused_pytest_verdict(
        ["tests/test_spawn.py", "--basetemp", "bt"], repo, repo_root=repo
    ) == (False, "test_spawn.py starts PowerShell (serial until the marker exists)")


def test_a_serial_marked_file_is_refused(tmp_path: Path) -> None:
    marked = "import pytest\n\n@pytest.mark.serial\ndef test_x():\n    pass\n"
    repo = _fake_repo(tmp_path, {"tests/test_marked.py": marked})
    assert HOOK.focused_pytest_verdict(["tests/test_marked.py", "--basetemp", "bt"], repo, repo_root=repo) == (
        False,
        "test_marked.py is marked serial",
    )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["tests", "--basetemp", "bt"], "target 'tests' is not a test file; directories and globs cannot be bounded"),
        (["-k", "slow", "--basetemp", "bt"], "no explicit test file is named"),
        (["-m", "not serial", "--basetemp", "bt"], "no explicit test file is named"),
        (["tests/test_*.py", "--basetemp", "bt"], "target 'tests/test_*.py' is not a test file; directories and globs cannot be bounded"),
        (["tests/test_one.py", "-n", "4", "--basetemp", "bt"], "xdist runs only through workstation_heavy.ps1"),
        (["tests/test_one.py", "-n4", "--basetemp", "bt"], "xdist runs only through workstation_heavy.ps1"),
        (["tests/test_one.py", "--dist=loadfile", "--basetemp", "bt"], "xdist runs only through workstation_heavy.ps1"),
        (["tests/test_one.py", "-p", "xdist", "--basetemp", "bt"], "only -p no:<plugin> is allowed in a focused run"),
        (["tests/test_one.py", "--pyargs", "--basetemp", "bt"], "option --pyargs is not in the focused-run allowlist"),
        (["@args.txt", "--basetemp", "bt"], "argument files cannot be bounded"),
        (["tests/test_one.py"], "a focused run needs an explicit --basetemp deleted afterwards"),
        (["tests/test_missing.py", "--basetemp", "bt"], "test file 'tests/test_missing.py' does not exist"),
    ],
)
def test_unbounded_or_unsafe_selections_are_refused(tmp_path: Path, arguments: list[str], expected: str) -> None:
    repo = _fake_repo(tmp_path, {"tests/test_one.py": PLAIN_TEST})
    assert HOOK.focused_pytest_verdict(arguments, repo, repo_root=repo) == (False, expected)


def test_a_portable_live_marker_or_unreadable_state_blocks_the_exemption(
    tmp_path: Path, _no_host_global_marker: Path
) -> None:
    repo = _fake_repo(tmp_path, {"tests/test_one.py": PLAIN_TEST})
    _no_host_global_marker.parent.mkdir(parents=True)
    _no_host_global_marker.write_text(json.dumps({"execution_host_profile": "portable_execution_v1"}), encoding="utf-8")
    arguments = ["tests/test_one.py", "--basetemp", "bt"]
    assert HOOK.focused_pytest_verdict(arguments, repo, repo_root=repo) == (
        False,
        "a portable live stage holds the host-global mutex",
    )
    _no_host_global_marker.write_text("{not json", encoding="utf-8")
    assert HOOK.focused_pytest_verdict(arguments, repo, repo_root=repo) == (
        False,
        "the host-global workload state cannot be read",
    )


def test_compound_dynamic_or_full_suite_commands_never_qualify() -> None:
    file = ROOT / "tests" / "test_artifacts.py"
    for command in (
        f"Write-Output go; python -m pytest '{file}' --basetemp bt",
        f"python -m pytest '{file}' --basetemp bt | Out-Null",
        f"$p='python'; & $p -m pytest '{file}' --basetemp bt",
        f"python -m pytest '{file}' --basetemp $env:TEMP",
        f"coverage run -m pytest '{file}' --basetemp bt",
        "python -m pytest -q --basetemp bt",
        "python -m compileall -q src",
    ):
        denied = HOOK.evaluate(_payload(command, ROOT), now=PROTECTED, constrained_capture_host=False)
        assert "workstation_heavy.ps1" in _reason(denied), command
        assert "Focused-run exemption not available" in _reason(denied), command


def test_queue_flags_are_part_of_the_approved_wrapper_form() -> None:
    encoded = base64.b64encode(json.dumps(["-m", "pytest", "-q"]).encode()).decode("ascii")
    base = (
        f"& '{ROOT / 'scripts/ops/workstation_heavy.ps1'}' -Kind pytest "
        f"-PythonPath '{Path(sys.executable).resolve()}' -ArgumentsBase64 '{encoded}' "
        f"-RepoRoot '{ROOT}'"
    )
    for suffix in ("", " -Queue", " -Queue -QueueTimeoutSeconds 600"):
        assert HOOK.evaluate(_payload(base + suffix, ROOT), constrained_capture_host=False) is None, suffix
    for suffix in (" -Queue -QueueTimeoutSeconds 0", " -QueueTimeoutSeconds 600", " -Queue; whoami"):
        assert HOOK.evaluate(_payload(base + suffix, ROOT), constrained_capture_host=False) is not None, suffix


# ------------------------------------------------------------------ capture host is unchanged
def test_capture_host_never_grants_the_exemption() -> None:
    files = [ROOT / "tests" / "test_artifacts.py"]
    command = _workstation_command(files)
    protected = HOOK.evaluate(_payload(command, ROOT), now=PROTECTED, constrained_capture_host=True)
    assert _reason(protected) == (
        "Agent-started pytest, compileall, replay, backtest, or training work is allowed only "
        "00:30-09:00 America/Toronto on this capture host."
    )
    # Inside the window a bounded focused run was already allowed on the capture host.
    assert HOOK.evaluate(_payload(command, ROOT), now=INSIDE_WINDOW, constrained_capture_host=True) is None


def test_capture_host_keeps_the_bounded_suite_rule_for_26_files(tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, {f"tests/test_f{i:02d}.py": PLAIN_TEST for i in range(26)})
    command = _workstation_command([repo / f"tests/test_f{i:02d}.py" for i in range(26)])
    for now in (PROTECTED, INSIDE_WINDOW):
        denied = HOOK.evaluate(_payload(command, repo), now=now, constrained_capture_host=True)
        assert _reason(denied) == (
            "An unbounded pytest run is forbidden on the 16 GB capture host; use the "
            "repository-owned bounded 25-file suite wrapper."
        )


def test_capture_host_still_forbids_the_wrapper_and_its_queue() -> None:
    encoded = base64.b64encode(json.dumps(["-m", "pytest", "-q"]).encode()).decode("ascii")
    command = (
        f"& '{ROOT / 'scripts/ops/workstation_heavy.ps1'}' -Kind pytest "
        f"-PythonPath '{Path(sys.executable).resolve()}' -ArgumentsBase64 '{encoded}' "
        f"-RepoRoot '{ROOT}' -Queue"
    )
    denied = HOOK.evaluate(_payload(command, ROOT), now=INSIDE_WINDOW, constrained_capture_host=True)
    assert "forbidden on the tracked dedicated capture host" in _reason(denied)


def test_unprovable_host_identity_stays_fail_closed_for_a_focused_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _workstation_command([ROOT / "tests" / "test_artifacts.py"])
    monkeypatch.setattr(HOOK, "_capture_host_policy_state", lambda: None)
    denied = HOOK.evaluate(_payload(command, ROOT), now=INSIDE_WINDOW)
    if sys.platform != "win32":
        assert denied is None  # the hook is inert off Windows, exactly as before
    else:
        assert _reason(denied) == (
            "Cannot prove this Windows installation differs from the tracked "
            "dedicated capture host; recognized heavy work is blocked fail-closed."
        )


def test_classifier_cli_reports_the_same_verdict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _fake_repo(tmp_path, {"tests/test_one.py": PLAIN_TEST})
    request = {"arguments": [str(repo / "tests/test_one.py"), "--basetemp", "bt"], "cwd": str(repo)}
    encoded = base64.b64encode(json.dumps(request).encode("utf-8")).decode("ascii")
    original = sys.argv
    try:
        sys.argv = ["hook", "--classify-focused-pytest", encoded]
        assert HOOK.main() == 0
    finally:
        sys.argv = original
    assert json.loads(capsys.readouterr().out) == {
        "exempt": True,
        "reason": "focused run of 1 non-serial test file(s)",
    }
    sys.argv = ["hook", "--classify-focused-pytest", "not-base64!"]
    try:
        assert HOOK.main() == 0
    finally:
        sys.argv = original
    assert json.loads(capsys.readouterr().out)["exempt"] is False
