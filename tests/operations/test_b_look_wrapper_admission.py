"""The workstation offline allowlist admits the B look wrapper and refuses ``b_scorer look``, in both mirrors.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope) and master's ruling of
2026-11-01 on B-1 Clarification 3 (M3: admit ``weather.calibration.b_look_wrapper``; M4: refuse module
``weather.calibration.b_scorer`` when its first positional subcommand token is ``look`` or a prefix of it, or when
an option precedes the subcommand and a later token is, pointing to the wrapper;
``control`` and the other subcommands stay admitted). The Codex hook (``offline_subcommand_refusal``) and
``workload_admission.ps1`` (``Get-WeatherWorkstationOfflineArgumentRefusal``, called by ``workstation_heavy.ps1``)
must agree on every case below.
"""
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = "weather.calibration.b_look_wrapper"
SCORER = "weather.calibration.b_scorer"
ON_WINDOWS = pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None,
                                reason="runs Windows PowerShell")

REFUSED = [
    ["look"],
    ["look", "--rule", "x", "--out", "C:/t/x"],
    ["LOOK"],
    ["Look", "--rule", "x"],
    ["lo"],
    ["l"],
    [""],
    ["--", "look"],
    ["-h", "look"],
    ["--help", "look"],
    ["--out=C:/t/x", "look"],
    ["--rule", "x", "look"],
    ["--rule", "x", "LO"],
    ["--dry-run", "control", "look"],
]
ADMITTED = [
    [],
    ["control", "--out", "C:/t/x"],
    ["control", "look"],
    ["control", "--mode", "look"],
    ["check-rule", "--rule", "x"],
    ["lookup"],
    ["--dry-run"],
    ["-h"],
    ["-x"],
    ["--", "control"],
    ["--dry-run", "control", "--out", "C:/t/x"],
]


def _hook():
    spec = importlib.util.spec_from_file_location("b_wrapper_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _b64(arguments):
    return base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")


def _wrapper_call(arguments):
    return (f"& '{ROOT / 'scripts' / 'ops' / 'workstation_heavy.ps1'}' -Kind weather_heavy "
            f"-PythonPath '{sys.executable}' -ArgumentsBase64 '{_b64(arguments)}' -RepoRoot '{ROOT}' -Queue")


def _evaluate(hook, command):
    return hook.evaluate({"tool_name": "Bash", "tool_input": {"command": command}}, constrained_capture_host=False)


def test_hook_admits_the_wrapper_exactly():
    hook = _hook()
    assert WRAPPER in hook._OFFLINE_WEATHER_MODULES and SCORER in hook._OFFLINE_WEATHER_MODULES
    for near in (WRAPPER + ".child", WRAPPER + "_x", "weather.calibration.b_look"):
        assert near not in hook._OFFLINE_WEATHER_MODULES


@pytest.mark.parametrize("arguments", REFUSED, ids=repr)
def test_hook_refuses_b_scorer_look_and_options_before_the_subcommand(arguments):
    hook = _hook()
    reason = hook.offline_subcommand_refusal(SCORER, arguments)
    assert reason is not None and "python -m weather.calibration.b_look_wrapper look" in reason
    assert not hook._approved_workstation_arguments("weather_heavy", _b64(["-m", SCORER, *arguments]))


@pytest.mark.parametrize("arguments", ADMITTED, ids=repr)
def test_hook_keeps_the_other_b_scorer_subcommands_admitted(arguments):
    hook = _hook()
    assert hook.offline_subcommand_refusal(SCORER, arguments) is None
    assert hook._approved_workstation_arguments("weather_heavy", _b64(["-m", SCORER, *arguments]))


def test_hook_admits_the_wrapper_look_and_refuses_nothing_else_by_subcommand():
    hook = _hook()
    assert hook.offline_subcommand_refusal(WRAPPER, ["look", "--s0", "x"]) is None
    assert hook._approved_workstation_arguments("weather_heavy", _b64(["-m", WRAPPER, "look", "--s0", "x"]))
    assert hook.offline_subcommand_refusal("weather.calibration.mg2_composite", ["look"]) is None


def test_hook_denies_a_wrapper_call_carrying_b_scorer_look_with_the_wrapper_named():
    hook = _hook()
    denied = _evaluate(hook, _wrapper_call(["-m", SCORER, "look", "--rule", "x"]))
    reason = denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "b_scorer look is refused" in reason and "b_look_wrapper look" in reason
    option_first = _evaluate(hook, _wrapper_call(["-m", SCORER, "--", "look"]))
    assert "b_look_wrapper look" in option_first["hookSpecificOutput"]["permissionDecisionReason"]


def test_hook_lets_the_wrapper_call_run_b_scorer_control_and_the_look_wrapper():
    hook = _hook()
    assert _evaluate(hook, _wrapper_call(["-m", SCORER, "control", "--out", "C:/t/x"])) is None
    assert _evaluate(hook, _wrapper_call(["-m", WRAPPER, "look", "--s0", "C:/t/s0.py"])) is None


def test_hook_denies_a_direct_b_scorer_look_with_the_wrapper_named():
    hook = _hook()
    for command in (f'& "{sys.executable}" -m {SCORER} look --rule x',
                    f'& "{sys.executable}" -m {SCORER} -h look',
                    f"python -m {SCORER} look"):
        reason = _evaluate(hook, command)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "b_look_wrapper look" in reason, command
    control = _evaluate(hook, f'& "{sys.executable}" -m {SCORER} control --out C:/t/x')
    assert control is not None  # heavy: it must go through workstation_heavy.ps1, not refused by subcommand
    assert "b_look_wrapper" not in control["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.spawns
@ON_WINDOWS
def test_the_ps1_mirror_agrees_with_the_hook_on_every_case(tmp_path):
    hook = _hook()
    cases = [(SCORER, a) for a in REFUSED + ADMITTED] + [(WRAPPER, ["look", "--s0", "x"]),
                                                         ("weather.calibration.mg2_composite", ["look"])]
    (tmp_path / "cases.json").write_text(json.dumps([{"module": m, "arguments": a} for m, a in cases]),
                                         encoding="utf-8")
    script = tmp_path / "refusals.ps1"
    script.write_text(
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        f"$cases = Get-Content -Raw -LiteralPath '{tmp_path / 'cases.json'}' | ConvertFrom-Json\n"
        "$out = @(foreach ($case in $cases) {\n"
        "    $r = Get-WeatherWorkstationOfflineArgumentRefusal -Module $case.module -Arguments @($case.arguments)\n"
        "    if ($null -eq $r) { '' } else { [string]$r }\n"
        "})\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n"
        "ConvertTo-Json -InputObject $out -Compress\n",
        encoding="utf-8",
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(script)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    listing, refusals = result.stdout.strip().splitlines()[-2:]
    assert set(json.loads(listing)) == hook._OFFLINE_WEATHER_MODULES
    got = json.loads(refusals)
    assert len(got) == len(cases)
    for (module, arguments), text in zip(cases, got):
        expected = hook.offline_subcommand_refusal(module, arguments)
        assert bool(text) == (expected is not None), (module, arguments, text)
        if text:
            assert "python -m weather.calibration.b_look_wrapper look" in text


@pytest.mark.spawns
@ON_WINDOWS
@pytest.mark.parametrize("arguments", [["look", "--rule", "x"], ["--", "look"]], ids=repr)
def test_workstation_heavy_refuses_b_scorer_look_before_any_lease(arguments):
    """The weather_heavy branch throws on the arguments before it queues or takes a lease (nothing runs)."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts" / "ops" / "workstation_heavy.ps1"), "-Kind", "weather_heavy",
         "-PythonPath", sys.executable, "-ArgumentsBase64", _b64(["-m", SCORER, *arguments]),
         "-RepoRoot", str(ROOT)],
        capture_output=True, text=True, timeout=120)
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "b_look_wrapper look" in output, output
    assert "admitted to slot" not in output and "enqueue ticket" not in output
