from datetime import datetime, timezone
import io
import importlib.util
import json
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
    assert "bounded suite" in reason(full_suite)
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


def test_quoted_search_terms_do_not_impersonate_heavy_commands():
    now = datetime(2026, 8, 24, 14, 0, tzinfo=ZONE)
    harmless = (
        'Get-Content requirements.txt; '
        'rg -n "dependencies|optional-dependencies|pytest|compileall" pyproject.toml'
    )

    assert (
        HOOK.evaluate(
            payload(harmless),
            now=now,
            constrained_capture_host=True,
        )
        is None
    )

    literal_subexpression_search = r"rg -n '\$\(python -m pytest\)' docs"
    assert (
        HOOK.evaluate(
            payload(literal_subexpression_search),
            now=now,
            constrained_capture_host=True,
        )
        is None
    )

    policy_search = (
        'rg -n "Get-ChildItem .* -Recurse|data/|pytest" '
        'docs/operations/HOST_LOAD_POLICY.md'
    )
    assert (
        HOOK.evaluate(
            payload(policy_search),
            now=now,
            constrained_capture_host=True,
        )
        is None
    )


def test_compound_and_nested_shell_commands_cannot_hide_heavy_work():
    protected = datetime(2026, 8, 24, 14, 0, tzinfo=ZONE)
    compound = HOOK.evaluate(
        payload(r"git status --short; python -m pytest tests\operations\test_x.py -q"),
        now=protected,
        constrained_capture_host=True,
    )
    nested = HOOK.evaluate(
        payload(
            r'powershell.exe -NoProfile -Command "python -m compileall -q app src tests"'
        ),
        now=protected,
        constrained_capture_host=True,
    )

    assert "00:30-09:00" in reason(compound)
    assert "00:30-09:00" in reason(nested)

    for command in (
        r'bash -lc "python -m pytest tests\operations\test_x.py -q"',
        r'bash -lc "MODE=test python -m pytest tests\operations\test_x.py -q"',
        r'powershell.exe -NoProfile -com "python -m pytest tests\operations\test_x.py -q"',
        r"uv run -- python -m pytest tests\operations\test_x.py -q",
        r"env MODE=test python -m pytest tests\operations\test_x.py -q",
    ):
        assert "00:30-09:00" in reason(
            HOOK.evaluate(
                payload(command),
                now=protected,
                constrained_capture_host=True,
            )
        )


def test_dynamic_subexpressions_and_executable_indirection_are_opaque():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    for command in (
        r'Write-Output "$(python -m pytest tests\operations\test_x.py -q)"',
        r"& (Get-Command python) -m pytest tests\operations\test_x.py -q",
        r'[Diagnostics.Process]::Start("python", "-m pytest -q")',
        r"powershell.exe -NoProfile -enco cAB5AHQAaABvAG4A",
    ):
        assert "Opaque or dynamically evaluated" in reason(
            HOOK.evaluate(
                payload(command),
                now=admitted,
                constrained_capture_host=True,
            )
        )


def test_runner_and_start_process_wrappers_cannot_hide_heavy_work():
    protected = datetime(2026, 8, 24, 14, 0, tzinfo=ZONE)
    for command in (
        r"uv run python -m pytest tests\operations\test_x.py -q",
        r"poetry run pytest tests\operations\test_x.py -q",
        r"conda run -n weather python -m compileall -q src",
        r"Start-Process python -ArgumentList '-m','pytest','tests\operations\test_x.py'",
        r"Start-Process -Fi uv -Arg 'run','python','-m','pytest','tests\operations\test_x.py'",
        r"Start-Process -WorkingDirectory C:\repo uv -Arg 'run','python','-m','pytest','tests\operations\test_x.py'",
    ):
        result = HOOK.evaluate(
            payload(command),
            now=protected,
            constrained_capture_host=True,
        )
        assert "00:30-09:00" in reason(result)


def test_dynamic_start_process_target_is_refused_as_opaque():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    result = HOOK.evaluate(
        payload(r"Start-Process -FilePath $runner -ArgumentList $arguments"),
        now=admitted,
        constrained_capture_host=True,
    )
    assert "Opaque or dynamically evaluated" in reason(result)

    dynamic_arguments = HOOK.evaluate(
        payload(r"Start-Process python -ArgumentList $arguments"),
        now=admitted,
        constrained_capture_host=True,
    )
    assert "Opaque or dynamically evaluated" in reason(dynamic_arguments)


def test_assignment_and_dynamic_invocation_cannot_hide_heavy_work():
    protected = datetime(2026, 8, 24, 14, 0, tzinfo=ZONE)
    assigned = HOOK.evaluate(
        payload(r"$result = python -m pytest tests\operations\test_x.py -q"),
        now=protected,
        constrained_capture_host=True,
    )
    dynamic = HOOK.evaluate(
        payload(r"& $runner -m pytest tests\operations\test_x.py -q"),
        now=protected,
        constrained_capture_host=True,
    )

    assert "00:30-09:00" in reason(assigned)
    assert "Opaque or dynamically evaluated" in reason(dynamic)


def test_admitted_window_refuses_more_than_25_or_broad_test_targets():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    too_many = "python -m pytest " + " ".join(
        f"tests\\operations\\test_{index}.py" for index in range(26)
    )
    for command in (
        too_many,
        r"python -m pytest tests\operations tests\operations\test_x.py",
        r"python -m pytest @test-files.txt tests\operations\test_x.py",
        r"tox -e py311",
        r"python -m unittest",
        r"python -m pytest --ignore tests\operations\test_x.py",
        r"python -m pytest -c tests\operations\test_x.py",
    ):
        result = HOOK.evaluate(
            payload(command),
            now=admitted,
            constrained_capture_host=True,
        )
        assert "unbounded test run" in reason(result)


def test_python_code_string_cannot_hide_test_or_weather_entrypoint():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    for command in (
        'python -c "import pytest; pytest.main()"',
        'python -c "import compileall; compileall.compile_dir(\'src\')"',
        'python -c "import weather.training"',
    ):
        result = HOOK.evaluate(
            payload(command),
            now=admitted,
            constrained_capture_host=True,
        )
        assert "Opaque or dynamically evaluated" in reason(result)


def test_opaque_shell_evaluation_is_refused_even_in_admitted_window():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    encoded = HOOK.evaluate(
        payload("powershell.exe -EncodedCommand cAB5AHQAaABvAG4A"),
        now=admitted,
        constrained_capture_host=True,
    )
    dynamic = HOOK.evaluate(
        payload(r"Invoke-Expression $command"),
        now=admitted,
        constrained_capture_host=True,
    )

    assert "Opaque or dynamically evaluated" in reason(encoded)
    assert "Opaque or dynamically evaluated" in reason(dynamic)


def test_module_matching_is_case_insensitive_without_losing_argument_position():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    assert (
        HOOK.evaluate(
            payload(r"python -m PyTest tests\operations\test_x.py -q"),
            now=admitted,
            constrained_capture_host=True,
        )
        is None
    )
    assert (
        HOOK.evaluate(
            payload(r"python3.11 -m pytest tests\operations\test_x.py -q"),
            now=admitted,
            constrained_capture_host=True,
        )
        is None
    )


def test_heavy_wrapper_is_time_gated_even_without_literal_test_runner_name():
    protected = datetime(2026, 8, 24, 14, 0, tzinfo=ZONE)
    result = HOOK.evaluate(
        payload(
            r"& C:\repo\scripts\ops\bounded_worktree_test_suite.ps1 "
            r"-RepoRoot C:\repo -WorktreeRoot C:\worktree"
        ),
        now=protected,
        constrained_capture_host=True,
    )

    assert "00:30-09:00" in reason(result)

    file_result = HOOK.evaluate(
        payload(
            r"powershell.exe -NoProfile -File "
            r"C:\repo\scripts\ops\integration_attempt_suite.ps1"
        ),
        now=protected,
        constrained_capture_host=True,
    )
    assert "00:30-09:00" in reason(file_result)


def test_recursive_scan_detection_uses_command_and_target_positions():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    recursive = HOOK.evaluate(
        payload(r"Get-ChildItem C:\repo -Recurse -Filter *.py"),
        now=admitted,
        constrained_capture_host=True,
    )
    broad_data = HOOK.evaluate(
        payload(r'rg -n "needle" data'),
        now=admitted,
        constrained_capture_host=True,
    )
    bounded_data = HOOK.evaluate(
        payload(r'rg -n "needle" data\logs\known-status.json'),
        now=admitted,
        constrained_capture_host=True,
    )
    files_data = HOOK.evaluate(
        payload(r"rg --files C:\repo\data"),
        now=admitted,
        constrained_capture_host=True,
    )

    assert "Recursive Get-ChildItem" in reason(recursive)
    abbreviated_recursive = HOOK.evaluate(
        payload(r"dir C:\repo -Rec -Filter *.py"),
        now=admitted,
        constrained_capture_host=True,
    )
    assert "Recursive Get-ChildItem" in reason(abbreviated_recursive)
    assert "broad scans of data/" in reason(broad_data)
    assert "broad scans of data/" in reason(files_data)
    absolute_glob_data = HOOK.evaluate(
        payload(r'rg -n "needle" C:\repo\data\*'),
        now=admitted,
        constrained_capture_host=True,
    )
    assert "broad scans of data/" in reason(absolute_glob_data)
    assert bounded_data is None


def test_rg_ignore_bypass_requires_an_explicit_bounded_target():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    for command in (
        r"rg --files --no-ignore",
        r"rg --files --no-ignore-vcs",
        r"rg --files --hidden",
        r"rg -uu --files",
        r'rg --no-ignore "needle"',
        r'rg --unrestricted "needle"',
        r'rg --no-ignore-vcs "needle" .',
    ):
        assert "broad scans of data/" in reason(
            HOOK.evaluate(
                payload(command),
                now=admitted,
                constrained_capture_host=True,
            )
        )

    for command in (
        r"rg --files --hidden src\weather\paths.py",
        r'rg --no-ignore "needle" src\weather\paths.py',
        r'rg -n -e "--no-ignore" docs\operations\HOST_LOAD_POLICY.md',
        r'rg -n "rg --files --hidden" docs\operations\HOST_LOAD_POLICY.md',
    ):
        assert (
            HOOK.evaluate(
                payload(command),
                now=admitted,
                constrained_capture_host=True,
            )
            is None
        )


def test_explicit_interactive_processes_are_refused_as_opaque():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    for command in (
        "python",
        "python -I",
        "python --check-hash-based-pycs always",
        "powershell.exe -NoProfile",
        "powershell.exe -NoExit -Command exit",
        "bash",
        "bash --rcfile profile.sh",
        "bash -s ignored-positional-parameter",
        "cmd.exe /k",
    ):
        assert "Opaque or dynamically evaluated" in reason(
            HOOK.evaluate(
                payload(command),
                now=admitted,
                constrained_capture_host=True,
            )
        )


def test_python_option_arity_preserves_a_finite_script_entrypoint():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    for command in (
        r"python -x tools\bounded_script.py",
        r"python -X dev tools\bounded_script.py",
        r"python -W error tools\bounded_script.py",
    ):
        assert (
            HOOK.evaluate(
                payload(command),
                now=admitted,
                constrained_capture_host=True,
            )
            is None
        )


def test_heavy_window_is_always_interpreted_in_america_toronto():
    assert not HOOK._inside_heavy_window(
        datetime(2026, 8, 24, 4, 29, tzinfo=timezone.utc)
    )
    assert HOOK._inside_heavy_window(
        datetime(2026, 8, 24, 4, 30, tzinfo=timezone.utc)
    )
    assert not HOOK._inside_heavy_window(
        datetime(2026, 8, 24, 13, 0, tzinfo=timezone.utc)
    )


def test_focused_suffix_style_test_file_is_bounded():
    admitted = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    assert (
        HOOK.evaluate(
            payload(r"python -m pytest tests\operations\integration_test.py -q"),
            now=admitted,
            constrained_capture_host=True,
        )
        is None
    )
    assert (
        HOOK.evaluate(
            payload(
                r"python -m pytest "
                r"tests\operations\test_x.py::test_one_case -q"
            ),
            now=admitted,
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


def test_installed_windows_hook_does_not_use_ram_or_env_as_host_identity(monkeypatch):
    monkeypatch.setattr(HOOK.os, "name", "nt")
    monkeypatch.setenv("WEATHER_CODEX_HOST_LOAD_POLICY", "0")

    assert HOOK._is_constrained_capture_host() is True


def test_hook_internal_error_fails_closed_without_crashing_protocol(
    monkeypatch, capsys
):
    monkeypatch.setattr(HOOK.sys, "stdin", io.StringIO(json.dumps(payload("git status"))))

    def broken_evaluate(_payload):
        raise RuntimeError("synthetic policy failure")

    monkeypatch.setattr(HOOK, "evaluate", broken_evaluate)
    assert HOOK.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert "could not classify" in reason(result)


def test_hook_malformed_protocol_input_fails_closed(monkeypatch, capsys):
    monkeypatch.setattr(HOOK.sys, "stdin", io.StringIO("{not-json"))

    assert HOOK.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert "invalid JSON" in reason(result)

    malformed_bash = HOOK.evaluate(
        {"tool_name": "Bash", "tool_input": {}},
        constrained_capture_host=True,
    )
    assert "empty shell command" in reason(malformed_bash)
