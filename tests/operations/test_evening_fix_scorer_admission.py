"""The workstation offline allowlist admits the evening-fix scorer exactly, in both mirrors, with the B-look refusal kept.

Guards: item 343 (master 2026-11-03: fold ``weather.backtesting.evening_fix_scorer`` into the offline-module
allowlist work; the Stage 1 score ran once as a master one-off direct run because the wrapper refused the module)
and the workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope). ``workload_admission.ps1``
(``Get-WeatherWorkstationOfflineModule``) and the Codex hook mirror list the same modules: this module, but no
child or sibling. Master's ruling of 2026-11-01 (M3/M4, B-1 Clarification 3) stays in force for the new entry:
``b_scorer look`` is refused, ``b_look_wrapper look`` is admitted, and a scorer command that names b_scorer with a
look-like token is refused; ``workstation_heavy.ps1`` still refuses an unlisted module and the
live/execute/place/cancel/promote arguments before any lease.
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
MODULE = "weather.backtesting.evening_fix_scorer"
SCORER = "weather.calibration.b_scorer"
WRAPPER = "weather.calibration.b_look_wrapper"
NEAR = (MODULE + ".child", MODULE + "_x", "weather.backtesting.evening_fix", "weather.backtesting.evening_fix_transfer")
ON_WINDOWS = pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None,
                                reason="runs Windows PowerShell")
STAGE1 = ["--no-market", "--replay", "c=scratch/transfer/replay.jsonl", "--prereg", "docs/research/p.md",
          "--out", "scratch/evening_fix/stage1.json"]
# (module, arguments, refused?) - the same verdict is required from the hook and from the .ps1 mirror.
CASES = [
    (MODULE, STAGE1, False),
    (MODULE, [], False),
    (MODULE, ["--help"], False),
    (MODULE, ["--prereg", "src/weather/calibration/b_scorer.py", "look"], True),
    (MODULE, ["--out", "C:/t/x", "--replay", "b_scorer", "lo"], True),
    (MODULE, ["look"], False),  # no b_scorer named: the raw half does not fire, and the module has no look refusal
    (SCORER, ["look", "--rule", "x"], True),
    (SCORER, ["--", "look"], True),
    (SCORER, ["control", "--out", "C:/t/x"], False),
    (WRAPPER, ["look", "--s0", "src/weather/calibration/b_scorer.py"], False),
]


def _hook():
    spec = importlib.util.spec_from_file_location("efs_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _b64(arguments):
    return base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")


def _powershell(script, tmp_path):
    path = tmp_path / "admission.ps1"
    path.write_text(script, encoding="utf-8")
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_hook_lists_the_scorer_exactly_and_treats_a_direct_launch_as_heavy():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in NEAR:
        assert near not in hook._OFFLINE_WEATHER_MODULES, near
    direct = hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} ' + " ".join(STAGE1)
    }}, constrained_capture_host=False)
    assert direct is not None  # a direct heavy launch is denied: it must go through workstation_heavy.ps1


def test_hook_approves_the_wrapper_call_for_the_scorer_and_refuses_siblings_and_live_arguments():
    hook = _hook()
    assert hook._approved_workstation_arguments("weather_heavy", _b64(["-m", MODULE, *STAGE1]))
    assert not hook._approved_workstation_arguments("weather_heavy", _b64(["-m", MODULE + "_x", *STAGE1]))
    for flag in ("--live", "--execute", "--place", "--cancel", "--promote"):
        assert not hook._approved_workstation_arguments("weather_heavy", _b64(["-m", MODULE, *STAGE1, flag])), flag


@pytest.mark.parametrize(("module", "arguments", "refused"), CASES, ids=repr)
def test_hook_keeps_the_b_look_refusal_for_the_new_entry(module, arguments, refused):
    assert (_hook().offline_argument_refusal(module, arguments) is not None) is refused


@pytest.mark.spawns
@ON_WINDOWS
def test_the_ps1_mirror_lists_the_scorer_matches_the_hook_and_agrees_on_every_refusal(tmp_path):
    hook = _hook()
    (tmp_path / "cases.json").write_text(json.dumps([{"module": m, "arguments": a} for m, a, _ in CASES]),
                                         encoding="utf-8")
    lines = ",".join(f"'python -m {m} --no-market'" for m in (MODULE,) + NEAR)
    result = _powershell(
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        f"$cases = Get-Content -Raw -LiteralPath '{tmp_path / 'cases.json'}' | ConvertFrom-Json\n"
        "$refusals = @(foreach ($case in $cases) {\n"
        "    $r = Get-WeatherWorkstationOfflineArgumentRefusal -Module $case.module -Arguments @($case.arguments)\n"
        "    if ($null -eq $r) { '' } else { [string]$r }\n"
        "})\n"
        "$verdicts = [ordered]@{}\n"
        f"foreach ($line in @({lines})) {{\n"
        "    $verdicts[$line] = [bool](Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine $line)\n"
        "}\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n"
        "ConvertTo-Json -InputObject $verdicts -Compress\n"
        "ConvertTo-Json -InputObject $refusals -Compress\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    listing, verdicts, refusals = result.stdout.strip().splitlines()[-3:]
    listed = json.loads(listing)
    assert listed.count(MODULE) == 1
    assert set(listed) == hook._OFFLINE_WEATHER_MODULES
    by_module = {line.split()[2]: v for line, v in json.loads(verdicts).items()}
    assert by_module[MODULE] is True
    for near in NEAR:
        assert near not in listed and by_module[near] is False, near
    got = json.loads(refusals)
    assert len(got) == len(CASES)
    for (module, arguments, refused), text in zip(CASES, got):
        assert bool(text) is refused, (module, arguments, text)
        if refused:
            assert "python -m weather.calibration.b_look_wrapper look" in text


@pytest.mark.spawns
@ON_WINDOWS
@pytest.mark.parametrize(("arguments", "needle"), [
    (["-m", MODULE + "_x", *STAGE1], "must be an offline training/replay module"),
    (["-m", MODULE, *STAGE1, "--live"], "must be an offline training/replay module"),
    (["-m", MODULE, *STAGE1, "--promote=1"], "must be an offline training/replay module"),
    (["-m", MODULE, "--prereg", "src/weather/calibration/b_scorer.py", "look"], "b_look_wrapper look"),
], ids=["sibling", "live", "promote", "b_scorer_look"])
def test_workstation_heavy_refuses_before_any_lease(arguments, needle):
    """The weather_heavy branch throws before it queues or takes a lease, so nothing runs."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts" / "ops" / "workstation_heavy.ps1"), "-Kind", "weather_heavy",
         "-PythonPath", sys.executable, "-ArgumentsBase64", _b64(arguments), "-RepoRoot", str(ROOT)],
        capture_output=True, text=True, timeout=120)
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert needle in output, output
    assert "admitted to slot" not in output and "enqueue ticket" not in output
