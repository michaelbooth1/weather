import base64
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / ".codex" / "hooks" / "pre_tool_use_host_load.py"
INSTALL_PATH = ROOT / "scripts" / "ops" / "install_codex_host_load_hook.ps1"
ADMISSION_PATH = ROOT / "scripts" / "ops" / "workload_admission.ps1"
SPEC = importlib.util.spec_from_file_location("pre_tool_use_host_load", HOOK_PATH)
assert SPEC and SPEC.loader
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)
ZONE = ZoneInfo("America/Toronto")


def payload(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def workstation_wrapper_command(
    kind: str,
    arguments: list[str],
    *,
    repo_root: Path = ROOT,
    wrapper_path: Path | None = None,
) -> str:
    encoded = base64.b64encode(
        json.dumps(arguments, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return (
        f"& '{wrapper_path or repo_root / 'scripts/ops/workstation_heavy.ps1'}' "
        f"-Kind {kind} "
        f"-PythonPath '{Path(sys.executable).resolve()}' "
        f"-ArgumentsBase64 '{encoded}' "
        f"-RepoRoot '{repo_root.resolve()}'"
    )


def reason(result: dict | None) -> str:
    assert result is not None
    return result["hookSpecificOutput"]["permissionDecisionReason"]


def assignment_payload(dedicated_id: str) -> dict:
    return {
        "active_portable_execution_host_id": None,
        "active_portable_execution_principal_id": None,
        "assignment_status": "UNASSIGNED",
        "dedicated_capture_execution_host_id": dedicated_id,
        "reassignment_requires_new_production_tip": True,
        "schema_version": "international_live_execution_host_assignment_v0.1",
    }


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
    assert "portable-live/workstation-heavy exclusion" in text


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
    attached_full_suite = HOOK.evaluate(
        payload(r"python -mpytest -q"),
        now=now,
        constrained_capture_host=True,
    )
    clustered_full_suite = HOOK.evaluate(
        payload(r"python -Bmpytest -q"),
        now=now,
        constrained_capture_host=True,
    )
    separated_cluster_full_suite = HOOK.evaluate(
        payload(r"python -BIm pytest -q"),
        now=now,
        constrained_capture_host=True,
    )
    quoted_cluster_full_suite = HOOK.evaluate(
        payload(r'''python "-Bm"pytest -q'''),
        now=now,
        constrained_capture_host=True,
    )
    assert "bounded 25-file suite" in reason(full_suite)
    assert "bounded 25-file suite" in reason(attached_full_suite)
    assert "bounded 25-file suite" in reason(clustered_full_suite)
    assert "bounded 25-file suite" in reason(separated_cluster_full_suite)
    assert "bounded 25-file suite" in reason(quoted_cluster_full_suite)
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


def test_non_capture_host_has_no_time_window_but_requires_shared_mutex_wrapper():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    direct = HOOK.evaluate(
        payload(r"venv\Scripts\python.exe -m pytest -q"),
        now=now,
        constrained_capture_host=False,
    )
    assert "workstation_heavy.ps1" in reason(direct)
    assert "time window does not apply" in reason(direct)

    for kind, arguments in (
        ("pytest", ["-m", "pytest", "-q"]),
        ("compileall", ["-m", "compileall", "-q", "app", "src", "tests"]),
        (
            "weather_heavy",
            ["-m", "weather.operations.density_live_replay_parity", "--dry-run"],
        ),
    ):
        assert (
            HOOK.evaluate(
                payload(workstation_wrapper_command(kind, arguments)),
                now=now,
                constrained_capture_host=False,
            )
            is None
        )


def test_common_windows_heavy_entrypoints_require_wrapper_off_capture_host():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    commands = (
        r"py -3 -m pytest tests\operations\test_x.py -q",
        r"py.exe -3.11 -m pytest tests\operations\test_x.py -q",
        r"& 'C:\Windows\py.exe' -3 -m pytest tests\operations\test_x.py -q",
        'python.exe "-m" pytest -q',
        r"python.exe -m 'pytest' -q",
        r"$p='C:\Python311\python.exe'; & $p -m pytest -q",
        r"& (Resolve-Path .\venv\Scripts\python.exe) -m pytest -q",
        r"& (Get-Command python) '-m' pytest -q",
        r"${runner}='python.exe'; & ${runner} -m pytest -q",
        r"coverage run -m pytest tests\operations\test_x.py",
        r"& 'C:\repo\venv\Scripts\coverage.exe' run -m pytest tests\operations\test_x.py",
        "tox -e py311",
        "nox -s tests",
        "python -m weather.operations.experimental_training --dry-run",
        r"python -mpytest tests\operations\test_x.py -q",
        r'''python "-mpytest" tests\operations\test_x.py -q''',
        r'''python "-m"pytest tests\operations\test_x.py -q''',
        r"python '-m'pytest tests\operations\test_x.py -q",
        r"python -mcompileall -q src",
        r"python -mweather.operations.nightly_retrain --dry-run",
        r"python -Bmpytest tests\operations\test_x.py -q",
        r"python -Impytest tests\operations\test_x.py -q",
        r"python -BImweather.operations.nightly_retrain --dry-run",
        r"python -Bm pytest tests\operations\test_x.py -q",
        r"python -BIm weather.operations.nightly_retrain --dry-run",
        r'''python "-Bm" pytest tests\operations\test_x.py -q''',
        r"python '-Im' pytest tests\operations\test_x.py -q",
        r'''python "-Bm"pytest tests\operations\test_x.py -q''',
        r"python '-Bm'pytest tests\operations\test_x.py -q",
        r'''python "-BIm"weather.operations.nightly_retrain --dry-run''',
    )
    for command in commands:
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(blocked), command


def test_multiline_heavy_commands_cannot_bypass_host_policy():
    protected = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    commands = (
        "Write-Output ready\npython -m pytest tests\\operations\\test_x.py -q",
        "Write-Output ready\r\npython -m compileall -q src",
        "Write-Output ready\npython -m pytest; Write-Output done",
    )
    for command in commands:
        workstation = HOOK.evaluate(
            payload(command),
            now=protected,
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(workstation), command

        capture = HOOK.evaluate(
            payload(command),
            now=protected,
            constrained_capture_host=True,
        )
        capture_reason = reason(capture)
        assert (
            "00:30-09:00" in capture_reason
            or "bounded 25-file suite" in capture_reason
        ), command


def test_script_block_heavy_commands_are_nested_and_cannot_bypass_policy():
    commands = (
        r"& { python -m pytest tests\operations\test_x.py -q }",
        r"Invoke-Command -ScriptBlock { python -m pytest tests\operations\test_x.py -q }",
        r"Start-Job { python -m pytest tests\operations\test_x.py -q }",
        (
            r"Start-ThreadJob -ScriptBlock { python -m "
            r"weather.operations.nightly_retrain --dry-run }"
        ),
    )
    for command in commands:
        workstation = HOOK.evaluate(
            payload(command),
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(workstation), command

        capture = HOOK.evaluate(
            payload(command),
            now=datetime(2026, 8, 24, 2, 0, tzinfo=ZONE),
            constrained_capture_host=True,
        )
        assert "Nested shell or process launchers" in reason(capture), command


def test_parenthesized_heavy_commands_are_nested_and_cannot_bypass_policy():
    commands = (
        r"$(python -m pytest tests\operations\test_x.py -q)",
        r"(python -m pytest tests\operations\test_x.py -q)",
    )
    for command in commands:
        workstation = HOOK.evaluate(
            payload(command),
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(workstation), command

        capture = HOOK.evaluate(
            payload(command),
            now=datetime(2026, 8, 24, 2, 0, tzinfo=ZONE),
            constrained_capture_host=True,
        )
        assert "Nested shell or process launchers" in reason(capture), command


def test_dynamic_python_modules_are_fail_closed_on_both_host_roles():
    commands = (
        r"$m='pytest'; python -m $m tests\operations\test_x.py -q",
        r"$m='pytest'; python -m ${m} tests\operations\test_x.py -q",
        r'''$m='pytest'; python "-m" "$m" tests\operations\test_x.py -q''',
        r'''$m='pytest'; python -m "${m}" tests\operations\test_x.py -q''',
        r'''python -m "$env:WEATHER_MODULE" tests\operations\test_x.py -q''',
        r'''$m='pytest'; python -m "$($m)" tests\operations\test_x.py -q''',
        r'''$tail='test'; python -m "py$tail" tests\operations\test_x.py -q''',
        r'''$task='nightly_retrain'; python -m "weather.operations.$task" --dry-run''',
        r'''$prefix='weather.operations.'; python -m "${prefix}nightly_retrain" --dry-run''',
        r'''$a='py'; $b='test'; python -m "$a$b" tests\operations\test_x.py -q''',
        r'''$m='pytest'; python -m "$($m.ToString())" -q''',
        r'''$m='test'; python -m "py$($($m))" -q''',
        r'''$tail='test'; python -mpy"$tail" -q''',
        r'''$m='pytest'; python "-m"$m -q''',
        r'''$m='pytest'; python -Bm $m -q''',
        r'''$m='pytest'; python "-Bm"$m -q''',
        r'''$m='pytest'; python '-Im'$m -q''',
        r'''$tail='test'; python -Bmpy"$tail" -q''',
        r'''python -B"m"pytest -q''',
        r"python -B'm'pytest -q",
        r'''python -"Bm"pytest -q''',
        r"python -'Bm'pytest -q",
        r'''python -"m"pytest -q''',
        r"python -'m'pytest -q",
        r'''python "-B"mpytest -q''',
        r"python '-B'mpytest -q",
        r'''$x='m'; python -B"$x"pytest -q''',
        r'''$x='m'; python -B"${x}"pytest -q''',
        r'''python -B`mpytest -q''',
        r'''$tag='PythonCore/3.12'; py -V:"$tag" -m pytest -q''',
        r'''py -V:"PythonCore/3.12" -m pytest -q''',
        r'''& "$p" -mpytest -q''',
        r'''& "${p}" -BImweather.operations.nightly_retrain --dry-run''',
        r"python @args",
        r"python @pythonArgs",
        r"python -m @args",
        r"python -Bm @args",
        r"python -W $warningArgs -m pip --version",
        r"python -X $xOptions -m pip --version",
        r"python --check-hash-based-pycs $mode -m pip --version",
        r"python -W @warningArgs -m pip --version",
        r"pymanager @managerArgs",
        r'''python -m py"test" -q''',
        r"python -m py'test' -q",
        r"python -m $(Write-Output pytest) tests\operations\test_x.py -q",
        r"python -m (Get-Content .\module-name.txt) --dry-run",
        r"$m='pytest'; $p='python'; & $p -m $m tests\operations\test_x.py -q",
    )
    for command in commands:
        workstation = HOOK.evaluate(
            payload(command),
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(workstation), command

        capture = HOOK.evaluate(
            payload(command),
            now=datetime(2026, 8, 24, 2, 0, tzinfo=ZONE),
            constrained_capture_host=True,
        )
        assert "Nested shell or process launchers" in reason(capture), command


def test_single_quoted_module_variable_is_not_treated_as_expansion():
    for command in (
        r"python -m '$m' tests\operations\test_x.py -q",
        r"python -m pip --version",
        r'''python -m "pip" --version''',
        r"python -m 'pip' --version",
        r"python -mpip --version",
        r'''python "-mpip" --version''',
        r'''python "-m"pip --version''',
        r"python '-m'pip --version",
        r"python -Bmpip --version",
        r"python -Bm pip --version",
        r"python -BIm pip --version",
        r'''python "-Bm" pip --version''',
        r'''python "-Bm"pip --version''',
        r"python '-Im' pip --version",
        r"python '-Bm'pip --version",
        r"py -V:PythonCore/3.12 -m pip --version",
        r'''py "-V:PythonCore/3.12" -m pip --version''',
        r"py -3.13t -m pip --version",
        r"py exec -m pip --version",
        r"pymanager exec -m pip --version",
        r"py-manager.exe exec -m pip --version",
        r"pyw-manager.exe exec -m pip --version",
        r"python3.13-64.exe -m pip --version",
        r"pythonw3t-arm64.exe -m pip --version",
        r"py /V:3.14 -m pip --version",
        r"py /3.14 -m pip --version",
        r"py -V: -m pip --version",
        r"py /V: -m pip --version",
        r"py exec --quiet -m pip --version",
        r"pymanager exec --config C:\tmp\pymanager.json -m pip --version",
        r"& 'python ' -m pip --version",
        "& 'python\u00a0' -m pip --version",
        "& 'python\u0085' -m pip --version",
        "python.exe -m \u201cpip\u201d --version",
        "python.exe \u201c-m\u201d pip --version",
        "python.exe \u2018-m\u2019 \u2018pip\u2019 --version",
    ):
        assert HOOK.evaluate(payload(command), constrained_capture_host=False) is None
        assert (
            HOOK.evaluate(
                payload(command),
                now=datetime(2026, 8, 24, 2, 0, tzinfo=ZONE),
                constrained_capture_host=True,
            )
            is None
        )


def test_mixed_python_switch_construction_fails_closed_for_nonheavy_module():
    commands = (
        r'''python -B"m"pip --version''',
        r"python -B'm'pip --version",
        r'''python -"Bm"pip --version''',
        r'''$x='m'; python -B"$x"pip --version''',
    )
    for command in commands:
        workstation = HOOK.evaluate(
            payload(command),
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(workstation), command

        capture = HOOK.evaluate(
            payload(command),
            now=datetime(2026, 8, 24, 2, 0, tzinfo=ZONE),
            constrained_capture_host=True,
        )
        assert "Nested shell or process launchers" in reason(capture), command


def test_python_option_arity_selects_the_actual_module_and_stops_at_scripts():
    heavy = (
        r"python -W -mpip -mpytest -q",
        r"python -X -mpip -BImweather.operations.nightly_retrain --dry-run",
        r"python -Wignore -m pytest.__main__ -q",
        r"python -m coverage run -m pytest",
        r"python -m tox -e py311",
        r"python -m nox -s tests",
        r"py -V:PythonCore/3.12 -m pytest -q",
        r"py -V:3.12 -m weather.operations.nightly_retrain --dry-run",
        r"py -V:Distributor\1.0 -m pytest -q",
        r"py -V:distrib/ -m pytest -q",
        r"py exec -V:Distributor\1.0 -m weather.operations.nightly_retrain --dry-run",
        r"py -3.13t -m pytest -q",
        r"pyw.exe -V:3.12 -m pytest -q",
        r"py exec -m pytest -q",
        r"pymanager exec -m pytest -q",
        r"pywmanager exec -m weather.operations.nightly_retrain --dry-run",
        r"py-manager.exe exec -m pytest -q",
        r"pyw-manager.exe exec -m weather.operations.nightly_retrain --dry-run",
        r"python3.13-64.exe -m pytest -q",
        r"pythonw3.13t-arm64.exe -m weather.operations.nightly_retrain --dry-run",
        r"py /V:3.14 -m pytest -q",
        r"py /3.14 -m weather.operations.nightly_retrain --dry-run",
        r"py -V: -m pytest -q",
        r"py /V: -m weather.operations.nightly_retrain --dry-run",
        r"py exec --quiet -m pytest -q",
        r"py exec --verbose -m pytest -q",
        r"py exec --config=C:\tmp\pymanager.json -m pytest -q",
        r"pymanager exec --config C:\tmp\pymanager.json -m weather.operations.nightly_retrain --dry-run",
        r'''venv\Scripts\py"thon".exe -m pytest -q''',
        "venv\\Scripts\\py\u201cthon\u201d.exe -m pytest -q",
        "python -m \u201cpytest\u201d -q",
        "python \u201c-m\u201d pytest -q",
        "python \u2018-m\u2019 \u2018weather.operations.nightly_retrain\u2019 --dry-run",
        r'''venv\Scripts\py"$('thon')".exe -m pytest -q''',
        r'''venv\Scripts\py"$([string]'thon')".exe -m pytest -q''',
        r"python -m coverage.__main__ run -m pytest",
        r"python -m tox.__main__ -e py311",
        r"python -m nox.__main__ -s tests",
        r"python -m cProfile -m pytest -q",
        r"python -m pdb -c continue -m pytest",
        r"python -m trace --module pytest",
        r"python3.13t.exe -m pytest -q",
        r"python3.13t.exe -m weather.operations.nightly_retrain --dry-run",
        r"python_d.exe -m pytest -q",
        r"pythonw_d.exe -m weather.operations.nightly_retrain --dry-run",
        r"python3.13t_d.exe -m pytest -q",
        r"python -x -mpytest -mpip --version",
        r"& 'python ' -m pytest -q",
        "& 'python\u00a0' -m pytest -q",
        "& 'python\u0085' -m pytest -q",
        "& 'python\t' -m weather.operations.nightly_retrain --dry-run",
        r"& 'pytest ' -q",
        r"& 'coverage3 ' run -m pytest -q",
        r"& 'tox ' -e py311",
    )
    for command in heavy:
        assert "workstation_heavy.ps1" in reason(
            HOOK.evaluate(payload(command), constrained_capture_host=False)
        ), command

    light = (
        r"python -W -mpytest -mpip --version",
        r"python service.py -mpytest -q",
        r"python -c print(1) -mpytest -q",
        r"python -- service.py -mpytest -q",
        r"python - service.py -mpytest -q",
        r"python -x -mpip -mpytest -q",
        r"python -V -mpytest -q",
    )
    for command in light:
        assert HOOK.evaluate(payload(command), constrained_capture_host=False) is None


def test_pytest_main_alias_is_subject_to_the_unbounded_suite_guard():
    now = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    for command in (
        r"python -m pytest.__main__ -q",
        r"python -mpytest.__main__ -q",
        r"python -BIm pytest.__main__ -q",
        r"python -m cProfile -o NUL -m pytest -q",
        r"python -m pdb -c continue -m pytest -q",
        r"python -m trace --module pytest -q",
        r"python -m coverage run -m pytest -q",
        r"python -m coverage.__main__ run --module pytest.__main__ -q",
        r"coverage run -m pytest -q",
        r"coverage3 run -m pytest -q",
        r"coverage-3.11.exe run -m pytest -q",
        r"coverage run -pm pytest -q",
        r"coverage3 run -apm pytest -q",
        r"python -m coverage run -Lpm pytest -q",
        r"coverage run -mp pytest -q",
        r"python -m cProfile -moNUL pytest -q",
        r"python -m profile -moNUL pytest -q",
        r"python -m pdb -mccontinue pytest -q",
        r"python -m trace -t --mod pytest -q",
        r"coverage run --mod pytest -q",
        r"coverage run --m pytest -q",
        r"coverage run --mo pytest -q",
        r"python -m trace -t --mo pytest -q",
        r"python -m coverage run --mod pytest -q",
        r"python -m cProfile --out NUL -m pytest -q",
        r"python -m cProfile --sort cumulative -m pytest -q",
        r"python -m profile --outfile NUL -m pytest -q",
        r"python -m pdb --command continue -m pytest -q",
        r"python -m trace -t --ignore-m ignored --mo pytest -q",
        r"coverage run --sou src -m pytest -q",
        r"python -m cProfile -m coverage run -m pytest -q",
        r"python -m cProfile -m cProfile -m pytest -q",
        r"python -m pdb -m coverage run -m pytest -q",
        r"coverage run -m cProfile -m pytest -q",
        r"python -m coverage run -m pdb -m pytest -q",
    ):
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=True,
        )
        assert "bounded 25-file suite" in reason(blocked), command

    for command in (
        r"python -m cProfile -o NUL -m pytest tests/operations/test_x.py -q",
        r"python -m pdb -c continue -m pytest tests/operations/test_x.py -q",
        r"python -m trace --module pytest tests/operations/test_x.py -q",
        r"python -m coverage run -m pytest tests/operations/test_x.py -q",
        r"coverage run -m pytest tests/operations/test_x.py -q",
        r"coverage3 run -m pytest tests/operations/test_x.py -q",
        r"coverage-3.11.exe run -m pytest tests/operations/test_x.py -q",
        r"coverage run -pm pytest tests/operations/test_x.py -q",
        r"coverage3 run -apm pytest tests/operations/test_x.py -q",
        r"python -m coverage run -Lpm pytest tests/operations/test_x.py -q",
        r"coverage run -mp pytest tests/operations/test_x.py -q",
        r"python -m cProfile -moNUL pytest tests/operations/test_x.py -q",
        r"python -m profile -moNUL pytest tests/operations/test_x.py -q",
        r"python -m pdb -mccontinue pytest tests/operations/test_x.py -q",
        r"python -m trace -t --mod pytest tests/operations/test_x.py -q",
        r"coverage run --mod pytest tests/operations/test_x.py -q",
        r"coverage run --m pytest tests/operations/test_x.py -q",
        r"coverage run --mo pytest tests/operations/test_x.py -q",
        r"python -m trace -t --mo pytest tests/operations/test_x.py -q",
        r"python -m coverage run --mod pytest tests/operations/test_x.py -q",
        r"python -m cProfile --out NUL -m pytest tests/operations/test_x.py -q",
        r"python -m cProfile --sort cumulative -m pytest tests/operations/test_x.py -q",
        r"python -m profile --outfile NUL -m pytest tests/operations/test_x.py -q",
        r"python -m pdb --command continue -m pytest tests/operations/test_x.py -q",
        r"python -m trace -t --ignore-m ignored --mo pytest tests/operations/test_x.py -q",
        r"coverage run --sou src -m pytest tests/operations/test_x.py -q",
        r"python -m cProfile -m coverage run -m pytest tests/operations/test_x.py -q",
        r"coverage run -m cProfile -m pytest tests/operations/test_x.py -q",
    ):
        assert (
            HOOK.evaluate(
                payload(command),
                now=now,
                constrained_capture_host=True,
            )
            is None
        ), command


def test_pytest_option_values_do_not_prove_a_focused_target():
    now = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    commands = (
        r"python -m pytest --ignore tests/test_x.py -q",
        r"python -m pytest --ignore-glob tests/test_x.py -q",
        r"python -m pytest --deselect tests/test_x.py -q",
        r"python -m pytest -k tests/test_x.py -q",
        r"python -m pytest -c tests/test_x.py -q",
        r"python -m pytest --config-file tests/test_x.py -q",
        r"python -m pytest --rootdir tests/test_x.py -q",
        r"python -m pytest --basetemp tests/test_x.py -q",
        r"python -m pytest --junitxml test_results.py -q",
        r"pytest --ignore tests/test_x.py -q",
        r"pytest tests/test_x.py . -q",
        r"pytest tests/test_*.py -q",
        r"python -m pytest -vvk tests/operations/test_x.py -q",
        r"pytest -qk tests/operations/test_x.py",
        r"coverage run -m pytest -sxk tests/operations/test_x.py",
        r"Write-Output test_x.py ; pytest -q",
        "Write-Output test_x.py\npytest -q",
    )
    for command in commands:
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=True,
        )
        assert "bounded 25-file suite" in reason(blocked), command


def test_every_offline_weather_module_is_classified_and_wrapper_allowlisted():
    protected = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    for module in sorted(HOOK._OFFLINE_WEATHER_MODULES):
        direct = HOOK.evaluate(
            payload(f"python -m {module} --dry-run"),
            now=protected,
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(direct), module

        capture = HOOK.evaluate(
            payload(f"python -m {module} --dry-run"),
            now=protected,
            constrained_capture_host=True,
        )
        assert "00:30-09:00" in reason(capture), module

        attached = HOOK.evaluate(
            payload(f"python -m{module} --dry-run"),
            now=protected,
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(attached), module

        wrapped = HOOK.evaluate(
            payload(
                workstation_wrapper_command(
                    "weather_heavy",
                    ["-m", module, "--dry-run"],
                )
            ),
            now=protected,
            constrained_capture_host=False,
        )
        assert wrapped is None, module


def test_hook_and_workstation_wrapper_share_the_same_offline_module_set():
    admission = ADMISSION_PATH.read_text(encoding="utf-8-sig")
    allowlist_body = admission.split(
        "function Get-WeatherWorkstationOfflineModule {", 1
    )[1].split("function Test-WeatherWorkstationOfflineModuleCommandLine {", 1)[0]
    powershell_modules = frozenset(
        re.findall(r'"(weather\.[A-Za-z0-9_.-]+)"', allowlist_body)
    )
    assert powershell_modules == HOOK._OFFLINE_WEATHER_MODULES


def test_identical_wrapper_closure_is_approved_from_a_sibling_worktree(
    tmp_path: Path,
):
    sibling = tmp_path / "sibling-worktree"
    for relative in HOOK._WORKSTATION_WRAPPER_CLOSURE:
        target = sibling / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    command = workstation_wrapper_command(
        "pytest",
        ["-m", "pytest", "-q"],
        repo_root=sibling,
    )
    assert (
        HOOK.evaluate(
            payload(command),
            constrained_capture_host=False,
        )
        is None
    )

    (sibling / "scripts/ops/workload_admission.ps1").write_text(
        "# changed helper\n",
        encoding="utf-8",
    )
    blocked = HOOK.evaluate(
        payload(command),
        constrained_capture_host=False,
    )
    assert "workstation_heavy.ps1" in reason(blocked)


def test_nested_shell_and_process_heavy_launches_require_wrapper_off_capture_host():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    commands = (
        r"powershell.exe -NoProfile -Command python -m pytest -q",
        r"cmd.exe /d /c python -m compileall -q src",
        r"Start-Process python.exe -ArgumentList '-m','pytest','-q'",
        r"start $python -ArgumentList '-m','pytest','-q'",
        (
            r"pwsh.exe -Command \"Start-Process python.exe "
            r"-ArgumentList '-m','weather.operations.nightly_retrain'\""
        ),
        r"powershell.exe -Command cmd.exe /c py -3 -m pytest -q",
    )
    for command in commands:
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(blocked), command


def test_chained_nested_shell_launches_cannot_bypass_host_policy():
    separators = ("\n", "\r\n", "; ", " | ")
    nested_launches = (
        r'powershell.exe -NoProfile -Command "python -m pytest -q"',
        r'pw"sh".exe -Command "python -m pytest -q"',
        r'power"shell".exe -Command "python -m weather.operations.nightly_retrain --dry-run"',
        r'c"m"d.exe /cpython -m pytest -q',
        r'ba"sh".exe -c "python -m pytest -q"',
        r"& 'pwsh ' -NoProfile -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=",
        "& 'pwsh\u00a0' -NoProfile -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=",
        "& 'pwsh\u0085' -NoProfile -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=",
        r"& ' powershell ' -Command \"python -m pytest -q\"",
        r"& 'cmd ' /cpython -m pytest -q",
        r"& 'bash ' -c \"python -m pytest -q\"",
        r'''pwsh.exe -"Com"mand "python -m pytest -q"''',
        r'''pwsh.exe -Com"mand" "python -m weather.operations.nightly_retrain --dry-run"''',
        r'''cmd.exe /"c"python -m pytest -q''',
        r'''bash.exe -l"c" "python -m pytest -q"''',
        r'''$p='Com'; pwsh.exe -"$p"mand "python -m pytest -q"''',
        r'pwsh.exe -Com "python -m pytest -q"',
        r'powershell.exe -Comm "python -m weather.operations.nightly_retrain --dry-run"',
        r'pwsh.exe -CommandWithArgs "python -m pytest -q"',
        r'pwsh.exe -cwa "python -m pytest -q"',
        r'pwsh.exe -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=',
        r"""pwsh ('-'+'EncodedCommand') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r'pwsh.exe -ec cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=',
        r'pwsh.exe /Command "python -m pytest -q"',
        r'powershell.exe /C "python -m weather.operations.nightly_retrain --dry-run"',
        r'pwsh.exe /EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=',
        r'pwsh.exe --command "python -m pytest -q"',
        r'pwsh.exe --cwa "python -m weather.operations.nightly_retrain --dry-run"',
        r'pwsh.exe --ec cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=',
        "pwsh.exe \u2013Command \"python -m pytest -q\"",
        "powershell.exe \u2014C \"python -m weather.operations.nightly_retrain --dry-run\"",
        "pwsh.exe \u2015EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=",
        "pwsh.exe \u2014ec cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=",
        "pw\u201csh\u201d.exe \u2013Command \u201cpython -m pytest -q\u201d",
        r'''& (Get-Command pwsh) -ec cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=''',
        r'''& $(Get-Command pwsh) --encodedcommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=''',
        r'''& $($(Get-Command pwsh)) -ec cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=''',
        r'''& (Resolve-Path C:\tools\pwsh.exe) --encodedcommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=''',
        r'''$s='pwsh'; & $s -ec cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=''',
        r'''i"ex" "python -m pytest -q"''',
        r'''Invoke-"Expression" "python -m weather.operations.nightly_retrain --dry-run"''',
        r"""s"aps" pwsh.exe -ArgumentList '-ec','cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='""",
        r"""Start-Process pwsh.exe -ArgumentList '-ec','cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='""",
        r"""Start-Process pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh -ArgumentList ('--'+'encodedcommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh -ArgumentList @('-'+'ec','cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=')""",
        r"""$a='-'; Start-Process pwsh -ArgumentList ($a+'ec'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='""",
        r'''Start-Process pwsh -ArgumentList "-`EncodedCommand",'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait''',
        r"""Start-Process pwsh -a ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh -ar ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh -ArgumentList:('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh -a:('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh -a $args -Wait""",
        r"""Start-Process pwsh -a @('-'+'ec','cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=') -Wait""",
        r"""Start-Process pwsh -a ('-{0}' -f 'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process pwsh -a ('-','ec' -join ''),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        "Start-Process pwsh -ArgumentList \u201c-EncodedCommand\u201d,\u201ccAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=\u201d -Wait",
        r"""$p=@{FilePath='pwsh';ArgumentList=@(('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=')}; Start-Process @p""",
        r"""Start-Process -ErrorAction Stop pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process -ErrorAction Stop pwsh ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Start-Process -Path pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""$exe='pwsh'; Start-Process -PSP $exe -ArgumentList '-NoProfile','-Command','Write-Output ok' -Wait""",
        r"""$exe='pwsh'; Start-Process -Pat $exe -ArgumentList '-NoProfile','-Command','Write-Output ok' -Wait""",
        r"""$exe='pwsh'; Start-Process -ArgumentList '-NoProfile','-Command','Write-Output ok' -FilePath $exe -Wait""",
        r"""$sp=Get-Alias start; & $sp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""& (Get-Alias start) pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r""". Start-Process pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""$sp=Get-Alias start; . $sp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r""". (Get-Alias start) pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r""". pwsh -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        "Write-Output prefix;\u1680. Start-Process pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait",
        "Write-Output prefix;\u2000. Start-Process pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait",
        "Write-Output prefix;\u2007. Start-Process pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait",
        "Write-Output prefix;\u202f. Start-Process pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait",
        "Write-Output prefix;\u3000. Start-Process pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait",
        r"""Start-Process pwsh -ArgumentList '-WorkingDirectory' , '.' , ('-'+'EncodedCommand') , 'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""$env:PAYLOAD='python -m pytest -q'; Start-Process cmd.exe -ArgumentList '/c','%PAYLOAD%' -Wait -NoNewWindow""",
        r"""$env:PAYLOAD='python -m weather.operations.nightly_retrain --dry-run'; Start-Process cmd.exe -ArgumentList '/v:on','/c','!PAYLOAD!' -Wait -NoNewWindow""",
        r"""$env:PAYLOAD='python -m pytest -q'; Start-Process cmd.exe -ArgumentList '/c%PAYLOAD%' -Wait -NoNewWindow""",
        r"""$env:PAYLOAD='python -m pytest -q'; Start-Process cmd.exe -ArgumentList '/d/s/c%PAYLOAD%' -Wait -NoNewWindow""",
        r"""$env:PAYLOAD='python -m pytest -q'; Start-Process pwsh -ArgumentList '-Command','iex $env:PAYLOAD' -Wait""",
        r"""Start-Process bash -ArgumentList '-c','python -m py${TAIL} -q' -Wait""",
        r"""Set-Alias zzsp Start-Process; zzsp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""New-Alias -Name zzsp -Value Start-Process; zzsp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""sal zzsp Start-Process; zzsp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""nal zzpw pwsh; zzpw -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Set-Alias zzpw2 pwsh -ErrorAction Stop; zzpw2 -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Set-Item Alias:zzsp2 Start-Process; zzsp2 pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""New-Item Alias:zzsp3 -Value Start-Process; zzsp3 pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""si Alias:zzsp4 Start-Process; zzsp4 pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""ni Alias:zzsp5 -Value Start-Process; zzsp5 pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Copy-Item Alias:start Alias:zzcopy; zzcopy pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""cp Alias:start Alias:zzcopy; zzcopy pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Set-Content Alias:zzcontent Start-Process; zzcontent pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""$p='Alias:zzvar'; $v='pwsh'; Set-Item $p $v; zzvar -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Push-Location $env:AP; Set-Item zzpush pwsh; Pop-Location; zzpush -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""pushd ('Ali'+'as:'); cp start zzpushd; popd; zzpushd pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Set-Location -Path $env:AP; Set-Item zznamed pwsh; zznamed -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""sl -Path ('Ali'+'as:'); cp start zznamedsl; zznamedsl pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Push-Location -LiteralPath $env:AP; Set-Item zzliteral pwsh; zzliteral -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Set-Location Al`ias:; Set-Item zzescaped pwsh; zzescaped -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Push-Location Alia`s:; Copy-Item start zzescapedpush; Pop-Location; zzescapedpush pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""Set-Location A"li"as:; Set-Item zzdoublequoted pwsh; zzdoublequoted -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Push-Location A'lia's:; Copy-Item start zzsinglequoted; Pop-Location; zzsinglequoted pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""('Ali'+'as:') | Set-Location; Set-Item zzpipe pwsh; zzpipe -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Write-Output ('Ali'+'as:') | sl; Copy-Item start zzpipe2; zzpipe2 pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""[pscustomobject]@{Path=('Ali'+'as:')} | Push-Location; Set-Item zzpipe3 pwsh; zzpipe3 -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""& Set-Location ((Get-PSDrive Alias).Name + ':'); Set-Item zzamp pwsh; zzamp -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r""". Push-Location ((Get-PSDrive Alias).Name + ':'); Copy-Item start zzdot; zzdot pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""[pscustomobject]@{Path=('Ali'+'as:zzpipeitem')} | New-Item -Value pwsh; zzpipeitem -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""$alias:zzdirect='Start-Process'; zzdirect pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""($alias:zzparen='Start-Process'); zzparen pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""$($alias:zzsubexpression='pwsh'); zzsubexpression -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Set-Item Function:zzfunction -Value 'pwsh -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='; zzfunction""",
        r"""New-Item Function:zzfunction2 -Value 'python -m pytest -q'; zzfunction2""",
        r"""$function:zzfunction3={ pwsh -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA= }; zzfunction3""",
        r"""$mutator='Set-Item'; & $mutator Alias:zzdynamic pwsh; zzdynamic -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""& (Get-Command New-Item) Function:zzgrouped -Value 'python -m pytest -q'; zzgrouped""",
        r"""$mutator='Set-Item'; . $mutator Function:zzdotdynamic -Value 'python -m pytest -q'; zzdotdynamic""",
        r""". (Get-Command New-Item) Alias:zzdotgrouped pwsh; zzdotgrouped -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Invoke-Expression 'Set-Item Function:zziex -Value "pwsh (''-''+''EncodedCommand'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA="; zziex'""",
        r"""iex 'Set-Item Alias:zziexalias pwsh; zziexalias -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='""",
        r"""iex 'pwsh (''-''+''EncodedCommand'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='""",
        r""". iex 'pwsh (''-''+''EncodedCommand'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='""",
        r"""Invoke-Expression('pwsh ('+'\''-\''+\''EncodedCommand\'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=')""",
        r"""iex(('pw'+'sh (\''-\''+\''EncodedCommand\'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='))""",
        r"""& ([scriptblock]::Create('pwsh (''-''+''EncodedCommand'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='))""",
        r"""& ([scriptblock]::'Create'('python -m pytest -q'))""",
        r'''& ([scriptblock]::"Create"("python -m pytest -q"))''',
        r"""& (([type]'System.Management.Automation.ScriptBlock')::Create('python -m pytest -q'))""",
        r"""& (([type]'System.Management.Automation.ScriptBlock')::'Create'('python -m pytest -q'))""",
        r"""& ([type]::GetType('System.Management.Automation.ScriptBlock')::Create('python -m pytest -q'))""",
        r"""$member='Create'; & ([scriptblock]::$member('python -m pytest -q'))""",
        r"""& ([scriptblock]::$(('Cre'+'ate'))('python -m pytest -q'))""",
        r"""& ([scriptblock]::('Create')('python -m pytest -q'))""",
        r"""& ([scriptblock]::('Cre'+'ate')('python -m pytest -q'))""",
        r"""& ($opaqueType::Create('python -m pytest -q'))""",
        r"""& ((Get-Variable opaqueType -ValueOnly)::Create('python -m pytest -q'))""",
        r"""& ($opaqueType::$opaqueMember('python -m pytest -q'))""",
        r"""& (($opaqueType)::($opaqueMember)('python -m pytest -q'))""",
        r"""Start-Job -ScriptBlock ([scriptblock]::Create('pwsh (''-''+''EncodedCommand'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='))""",
        r"""Start-Job -ScriptBlock ([scriptblock]::('Cre'+'ate')('python -m pytest -q'))""",
        r"""Start-Job -ScriptBlock ([scriptblock]::'Create'('python -m pytest -q'))""",
        r"""Start-Job -ScriptBlock (([type]'System.Management.Automation.ScriptBlock')::Create('python -m pytest -q'))""",
        r"""Invoke-Command -ScriptBlock ([System.Management.Automation.ScriptBlock]::Create('pwsh (''-''+''EncodedCommand'') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA='))""",
        r"""[powershell]::Create().AddScript('python -m pytest -q').Invoke()""",
        r"""[System.Management.Automation.PowerShell]::Create().AddScript($env:PAYLOAD).Invoke()""",
        r"""([type]'System.Management.Automation.PowerShell')::Create().AddScript(('python -m '+'pytest -q')).BeginInvoke()""",
        r"""[powershell]::('Cre'+'ate')().AddCommand('python').AddArgument('-m').AddArgument('pytest').Invoke()""",
        r"""[powershell]:: <# executor factory #> Create().AddScript('python -m pytest -q').Invoke()""",
        "[powershell]:: # executor factory\n Create().AddScript('python -m pytest -q').Invoke()",
        "[powershell]::#factory\nCreate().#sink\nAddScript('python -m pytest -q').#invoke\nInvoke()",
        r'''[PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@()).AddScript("python -m pytest -q").Invoke()''',
        r'''[System.Management.Automation.PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@()).AddCommand("python").AddArgument("-m").AddArgument("pytest").Invoke()''',
        r'''([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())).GetType().GetMethod("AddScript",[type[]]@([string])).Invoke(([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())),@("python -m pytest -q")).Invoke()''',
        r'''([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())).GetType().GetMethod((("Add","Script") -join ""),[type[]]@([string])).Invoke(([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())),@("python -m pytest -q")).Invoke()''',
        r'''([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())).GetType().GetMethod(("Add{0}" -f "Script"),[type[]]@([string])).Invoke(([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())),@("python -m pytest -q")).Invoke()''',
        r'''([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())).GetType()."GetMethod"("AddScript",[type[]]@([string])).Invoke(([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())),@("python -m pytest -q")).Invoke()''',
        r'''([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())).GetType().('Get'+'Method')('AddScript',[type[]]@([string])).Invoke(([PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@())),@("python -m pytest -q")).Invoke()''',
        r'''[PowerShell].GetMethod("Create",[type[]]@()).Invoke(0,@()).PSObject.Methods["AddScript"].Invoke(@("python -m pytest -q")).Invoke()''',
        r'''$type.GetRuntimeMethod('Add'+'Command',[type[]]@([string])).Invoke($pipeline,@('python')).Invoke()''',
        r'''$type.InvokeMember("AddScript",$flags,$null,$pipeline,@($env:PAYLOAD)).Invoke()''',
        r"""$pipeline = Get-OpaquePipeline; $pipeline.'AddScript'($env:PAYLOAD).Invoke()""",
        r'''$pipeline = Get-OpaquePipeline; $pipeline."AddCommand"("python").AddArgument("-m").AddArgument("pytest").Invoke()''',
        r"""$pipeline = Get-OpaquePipeline; $pipeline.('Add'+'Script')($env:PAYLOAD).Invoke()""",
        r"""$pipeline = Get-OpaquePipeline; $pipeline.('Add'+'Command')('python').AddArgument('-m').AddArgument('pytest').Invoke()""",
        r"""$member = $env:METHOD; $pipeline = Get-OpaquePipeline; $pipeline.$member($env:PAYLOAD).Invoke()""",
        r"""$pipeline = Get-OpaquePipeline; $pipeline.($env:METHOD)($env:PAYLOAD).BeginInvoke()""",
        r"""& { pwsh ('-'+'EncodedCommand') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA= }""",
        r"""1 | ForEach-Object { pwsh ('-'+'EncodedCommand') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA= }""",
        r"""Start-Job { pwsh ('-'+'EncodedCommand') cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA= }""",
        r'''Write-Output "$(python -m pytest -q)"''',
        r"""Import-Alias aliases.csv; zzimported -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Set-Alias zzexpr (Get-Command pwsh); zzexpr -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Set-Alias ('zz'+'name') pwsh; zzname -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=""",
        r"""Se`t-Alias zzsp Start-Process; zzsp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""$setter='Set-Alias'; & $setter zzsp Start-Process; zzsp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r"""& (Get-Command Set-Alias) zzsp Start-Process; zzsp pwsh -ArgumentList ('-'+'EncodedCommand'),'cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=' -Wait""",
        r'''Write-Output "python -m pytest -q" | pwsh.exe -Command -''',
        r'''Write-Output "python -m pytest -q" | powershell.exe /C -''',
        r'''Write-Output "python -m weather.operations.nightly_retrain" | pwsh.exe -File -''',
        r'''Write-Output "python -m pytest -q" | pwsh.exe --file -''',
        r'''Write-Output "python -m pytest -q" | cmd.exe /q''',
        r'''Write-Output "python -m pytest -q" | bash.exe -s''',
        r'''Write-Output "python -m pytest -q" | sh.exe''',
        r'''Write-Output "python -m pytest -q" | pwsh.exe -Command -; Write-Output done''',
        "Write-Output 'python -m pytest -q' | pwsh.exe -File -\nWrite-Output done",
        r'''Write-Output "python -m pytest -q" | pwsh.exe -Command - & Write-Output done''',
        r'''Write-Output "python -m pytest -q" | pwsh.exe -Command - | Write-Output done''',
        r'cmd.exe /d /c "python -m compileall -q src"',
        r'cmd.exe /d /c "python -m %WEATHER_TEST_MODULE% -q"',
        r'cmd.exe /v:on /c "python -m !WEATHER_TEST_MODULE! -q"',
        r"cmd.exe /d /c python -mpytest -q",
        r'''cmd.exe /d /c python "-m"pytest -q''',
        r"cmd.exe /d /c python -Bmpytest -q",
        r"cmd.exe /d/s/c python -m pytest -q",
        r"""cmd.exe ('/'+'c') 'python -m pytest -q'""",
        r"cmd.exe /q/d/s/c python -m weather.operations.nightly_retrain --dry-run",
        r'''cmd.exe /d/s/c"python -m pytest -q"''',
        r"cmd.exe /cpython -m pytest -q",
        r"cmd.exe /d/cpython -m weather.operations.nightly_retrain --dry-run",
        r"cmd.exe /cC:\Python311\python.exe -m pytest -q",
        r"cmd.exe /rpython -m pytest -q",
        r"cmd.exe /y/cpython -m pytest -q",
        r"cmd.exe /t:0a/cpython -m weather.operations.nightly_retrain --dry-run",
        r"cmd.exe /z/cpython -m pytest -q",
        r"cmd.exe /c cmd.exe /c cmd.exe /c cmd.exe /c pwsh.exe -EncodedCommand cAB5AHQAaABvAG4AIAAtAG0AIABwAHkAdABlAHMAdAAgAC0AcQA=",
        r'cmd.exe /d /c "python -m py%TAIL% -q"',
        r'cmd.exe /d /c "python -m py^test -q"',
        r'bash.exe -c "python -m weather.operations.nightly_retrain --dry-run"',
        r"""bash.exe ('-'+'c') 'python -m pytest -q'""",
        r"""sh.exe ('-'+'c') 'python -m pytest -q'""",
        r'bash.exe -lc "python -m pytest -q"',
        r'bash.exe -xec "python -m weather.operations.nightly_retrain --dry-run"',
        r'bash.exe -c "python -m py${TAIL} -q"',
        r'bash.exe -c "python -m py$(printf %s $(printf test)) -q"',
        r"bash.exe -c 'python -m py\test -q'",
        "bash.exe -c 'python -m py\"test\" -q'",
    )
    for separator in separators:
        for nested_launch in nested_launches:
            command = f"Write-Output ready{separator}{nested_launch}"
            workstation = HOOK.evaluate(
                payload(command),
                constrained_capture_host=False,
            )
            assert workstation is not None, command
            assert "workstation_heavy.ps1" in reason(workstation), command

            capture = HOOK.evaluate(
                payload(command),
                now=datetime(2026, 8, 24, 2, 0, tzinfo=ZONE),
                constrained_capture_host=True,
            )
            assert capture is not None, command
            assert "Nested shell or process launchers" in reason(capture), command


def test_outer_expandable_shell_strings_do_not_preserve_inner_single_quotes():
    commands = (
        r'''$m='pytest'; bash.exe -c "python -m '$m' tests/operations/test_x.py -q"''',
        r'''$m='pytest'; pwsh.exe -Command "python -m '$m' tests/operations/test_x.py -q"''',
        r'''$m='pytest'; powershell.exe -Command "python '-m$m' -q"''',
    )
    for command in commands:
        workstation = HOOK.evaluate(
            payload(command),
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(workstation), command

        capture = HOOK.evaluate(
            payload(command),
            now=datetime(2026, 8, 24, 2, 0, tzinfo=ZONE),
            constrained_capture_host=True,
        )
        assert "Nested shell or process launchers" in reason(capture), command


def test_static_process_argument_literals_with_metacharacters_remain_light():
    for command in (
        r"Start-Process cmd.exe -ArgumentList '/c','echo (ready)' -Wait -NoNewWindow",
        r"Start-Process cmd.exe -ArgumentList '/c','echo C++' -Wait -NoNewWindow",
        r"Start-Process cmd.exe -ArgumentList '/c','echo literal@example.com' -Wait -NoNewWindow",
        r"Start-Process cmd.exe -ArgumentList '/c','echo $literal' -Wait -NoNewWindow",
        r'''Start-Process cmd.exe -a '/c',"echo C++" -Wait -NoNewWindow''',
        r"Start-Process cmd.exe -a '/c','echo literal ` backtick' -Wait -NoNewWindow",
        r"Start-Process cmd.exe -a '/c','echo ready' -WorkingDirectory $pwd -Wait",
        r"Start-Process cmd.exe -ArgumentList '/c','echo it''s ready' -Wait -NoNewWindow",
        r"Start-Job -ScriptBlock { Write-Output ok } | Wait-Job",
        r". Start-Job -ScriptBlock { Write-Output ok } | Wait-Job",
        r"Set-Item Env:WEATHER_LIGHT_CONTROL ready",
        r"Write-Output ready | Set-Content .\light.txt",
        r"Write-Output '; function Say-Light { Write-Output ready }'",
        r"Write-Output '[scriptblock]::Create('",
        r"Write-Output '[scriptblock]::''Create'''",
        r'''Write-Output "[scriptblock]::('Create')"''',
        r"Write-Output '$opaqueType::Create('",
        r"Write-Output '$opaqueType::$opaqueMember('",
        r"Write-Output '{ pwsh (''-''+''EncodedCommand'') harmless }'",
        r"Write-Output '$(python -m pytest -q)'",
        r'''Write-Output ('python -m pytest -q')''',
        r'''$h=@{message='python -m pytest -q'}''',
        r"Write-Output '[powershell]::Create().AddScript(''python -m pytest -q'').Invoke()'",
        r'''$h=@{message='[System.Management.Automation.PowerShell]::Create().AddScript($env:PAYLOAD).Invoke()'}''',
        r'''Write-Output "System.Management.Automation.PowerShell"; [WidgetFactory]::Create()''',
        r'''Write-Output '[powershell]'; [tuple]::Create(1,2)''',
        r'''Write-Output '[System.Management.Automation.PowerShell]'; [tuple]::Create(1,2)''',
        r'''Write-Output '[scriptblock]'; [tuple]::Create(1,2)''',
        r'''[PowerShell].FullName; [WidgetFactory]::Create()''',
        r'''Write-Output '$pipeline.AddScript("python -m pytest -q").Invoke()' ''',
        r'''$h=@{message='$pipeline.AddCommand("python").Invoke()'}''',
        r'''Write-Output '.GetMethod("AddScript")' ''',
        r'''Write-Output "literal `"; function Say-Light {"''',
    ):
        assert HOOK.evaluate(payload(command), constrained_capture_host=False) is None


def test_nested_heavy_launches_are_categorically_denied_on_capture_host():
    now = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    for command in (
        r"powershell.exe -Command python -m pytest tests\operations\test_x.py -q",
        r"cmd /c python -m compileall -q src",
        r"Start-Process python.exe -ArgumentList '-m','pytest','-q'",
    ):
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=True,
        )
        assert "Nested shell or process launchers" in reason(blocked), command


def test_common_windows_heavy_entrypoints_remain_capture_time_gated():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    for command in (
        r"py -3 -m pytest tests\operations\test_x.py -q",
        r"py.test tests\operations\test_x.py -q",
        "coverage run -m pytest tests\\operations\\test_x.py",
        "coverage3 run -m pytest tests\\operations\\test_x.py",
        "coverage-3.11.exe run -m pytest tests\\operations\\test_x.py",
        "tox -e py311",
        "nox -s tests",
    ):
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=True,
        )
        assert "00:30-09:00" in reason(blocked), command


def test_capture_host_categorically_rejects_workstation_wrapper():
    now = datetime(2026, 8, 24, 2, 0, tzinfo=ZONE)
    commands = (
        workstation_wrapper_command("pytest", ["-m", "pytest", "-q"]),
        r"& 'C:\other\workstation_heavy.ps1' -Kind pytest",
    )
    for command in commands:
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=True,
        )
        assert "forbidden" in reason(blocked), command
        assert "dedicated capture host" in reason(blocked), command


def test_non_capture_wrapper_shape_and_offline_scope_are_fail_closed():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    valid = workstation_wrapper_command("pytest", ["-m", "pytest", "-q"])
    malformed = (
        valid + "; venv\\Scripts\\python.exe -m pytest -q",
        valid.replace(str(HOOK.WORKSTATION_WRAPPER_PATH), r"C:\other\workstation_heavy.ps1"),
        valid.replace(str(ROOT.resolve()), r"C:\other\weather"),
        workstation_wrapper_command(
            "weather_heavy",
            ["-m", "weather.replay_daily", "--live"],
        ),
    )
    for command in malformed:
        blocked = HOOK.evaluate(
            payload(command),
            now=now,
            constrained_capture_host=False,
        )
        assert "workstation_heavy.ps1" in reason(blocked)


def test_command_recognition_does_not_mistake_messages_for_python_execution():
    now = datetime(2026, 8, 23, 14, 15, tzinfo=ZONE)
    for command in (
        "git commit -m pytest",
        "Write-Output 'python -m pytest'",
        "Write-Output 'py -3 -m pytest'",
        "Write-Output 'coverage tox nox'",
        "git commit -m 'python -m weather.operations.nightly_retrain'",
    ):
        assert (
            HOOK.evaluate(
                payload(command),
                now=now,
                constrained_capture_host=True,
            )
            is None
        )


def test_automatic_non_windows_hook_is_inactive(monkeypatch):
    monkeypatch.setattr(HOOK, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(
        HOOK,
        "_capture_host_policy_state",
        lambda: (_ for _ in ()).throw(AssertionError("must not probe host identity")),
    )
    assert HOOK.evaluate(payload("python -m pytest -q")) is None


def test_automatic_policy_uses_exact_host_identity_not_ram(tmp_path: Path):
    capture_guid = "11111111-2222-3333-4444-555555555555"
    workstation_guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    capture_id = "cbf93e84ec69a10cb04b0c8f8a00297a1ba050b0ebb7535b2c667292896d21db"
    assert HOOK._derive_execution_host_id(capture_guid) == capture_id
    assignment_path = tmp_path / "international_live_execution_host.json"
    assignment_path.write_text(
        json.dumps(assignment_payload(capture_id)),
        encoding="utf-8",
    )

    assert (
        HOOK._capture_host_policy_state(
            assignment_path=assignment_path,
            machine_guid=capture_guid,
            windows=True,
        )
        is True
    )
    assert (
        HOOK._capture_host_policy_state(
            assignment_path=assignment_path,
            machine_guid=workstation_guid,
            windows=True,
        )
        is False
    )
    source = HOOK_PATH.read_text(encoding="utf-8")
    assert "GlobalMemoryStatusEx" not in source
    assert "CAPTURE_HOST_MAX_PHYSICAL_BYTES" not in source
    assert "WEATHER_CODEX_HOST_LOAD_POLICY" not in source


def test_malformed_host_role_proof_is_indeterminate_and_blocks_heavy_work(
    tmp_path: Path,
    monkeypatch,
):
    assignment_path = tmp_path / "international_live_execution_host.json"
    assignment_path.write_text("{}", encoding="utf-8")
    assert (
        HOOK._capture_host_policy_state(
            assignment_path=assignment_path,
            machine_guid="11111111-2222-3333-4444-555555555555",
            windows=True,
        )
        is None
    )

    monkeypatch.setattr(HOOK, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(HOOK, "_capture_host_policy_state", lambda: None)
    blocked = HOOK.evaluate(payload(r"venv\Scripts\python.exe -m pytest -q"))
    assert "blocked fail-closed" in reason(blocked)
    assert HOOK.evaluate(payload("git status --short")) is None


def test_assignment_role_proof_rejects_bom_duplicate_and_unstable_files(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "international_live_execution_host.json"
    capture_id = "f" * 64
    malformed = (
        b"\xef\xbb\xbf" + json.dumps(assignment_payload(capture_id)).encode("utf-8"),
        (
            '{"schema_version":"international_live_execution_host_assignment_v0.1",'
            '"schema_version":"international_live_execution_host_assignment_v0.1",'
            '"assignment_status":"UNASSIGNED",'
            f'"dedicated_capture_execution_host_id":"{capture_id}",'
            '"active_portable_execution_host_id":null,'
            '"active_portable_execution_principal_id":null,'
            '"reassignment_requires_new_production_tip":true}'
        ).encode("utf-8"),
    )
    for raw in malformed:
        path.write_bytes(raw)
        assert (
            HOOK._capture_host_policy_state(
                assignment_path=path,
                machine_guid="11111111-2222-3333-4444-555555555555",
                windows=True,
            )
            is None
        )

    path.write_text(json.dumps(assignment_payload(capture_id)), encoding="utf-8")
    monkeypatch.setattr(HOOK.os.path, "samestat", lambda *_args: False)
    assert (
        HOOK._capture_host_policy_state(
            assignment_path=path,
            machine_guid="11111111-2222-3333-4444-555555555555",
            windows=True,
        )
        is None
    )
