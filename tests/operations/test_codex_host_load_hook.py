from datetime import datetime
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / ".codex" / "hooks" / "pre_tool_use_host_load.py"
INSTALL_PATH = ROOT / "scripts" / "ops" / "install_codex_host_load_hook.ps1"
SPEC = importlib.util.spec_from_file_location("pre_tool_use_host_load", HOOK_PATH)
assert SPEC and SPEC.loader
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)
ZONE = ZoneInfo("America/Toronto")


def payload(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def reason(result: dict | None) -> str:
    assert result is not None
    return result["hookSpecificOutput"]["permissionDecisionReason"]


def test_hook_installer_covers_unified_exec_at_the_user_layer():
    text = INSTALL_PATH.read_text(encoding="utf-8-sig")
    assert '$hookPath = Join-Path $CodexRoot "hooks.json"' in text
    assert 'matcher = "^Bash$"' in text
    assert 'commandWindows = "py -3' in text
    assert "pre_tool_use_host_load.py" in text
    assert "Refusing to overwrite existing Codex hooks" in text
    assert "[System.Text.UTF8Encoding]::new($false)" in text
    assert "WriteAllText($tempPath, $json, $utf8NoBom)" in text
    assert "unexpectedly contains a UTF-8 BOM" in text


def test_protected_window_denies_even_focused_pytest_and_compileall():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    pytest_result = HOOK.evaluate(
        payload(r"& 'C:\repo\venv\Scripts\python.exe' -m pytest tests\operations\test_x.py -q"),
        now=now,
        constrained_capture_host=True,
    )
    compile_result = HOOK.evaluate(
        payload(r"venv\Scripts\python.exe -m compileall -q app src tests"),
        now=now,
        constrained_capture_host=True,
    )
    assert "00:30-09:00" in reason(pytest_result)
    assert "00:30-09:00" in reason(compile_result)


def test_allowed_window_still_denies_full_suite_and_recursive_data_scans():
    now = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    full_suite = HOOK.evaluate(
        payload(r"venv\Scripts\python.exe -m pytest -q"),
        now=now,
        constrained_capture_host=True,
    )
    recursive_scan = HOOK.evaluate(
        payload(r"Get-ChildItem .. -Recurse -Filter python.exe"),
        now=now,
        constrained_capture_host=True,
    )
    assert "bounded 25-file suite" in reason(full_suite)
    assert "Recursive Get-ChildItem" in reason(recursive_scan)


def test_allowed_window_permits_one_focused_test_and_light_commands():
    now = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    assert (
        HOOK.evaluate(
            payload(r"venv\Scripts\python.exe -m pytest tests\operations\test_x.py -q"),
            now=now,
            constrained_capture_host=True,
        )
        is None
    )
    assert (
        HOOK.evaluate(
            payload("git status --short"),
            now=now,
            constrained_capture_host=True,
        )
        is None
    )


def test_policy_is_inactive_on_a_non_capture_host():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    assert (
        HOOK.evaluate(
            payload(r"venv\Scripts\python.exe -m pytest -q"),
            now=now,
            constrained_capture_host=False,
        )
        is None
    )
