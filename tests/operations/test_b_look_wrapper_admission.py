"""The workstation offline allowlist admits the B look wrapper and refuses ``b_scorer look``, in both mirrors.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope) and master's ruling of
2026-11-01 on B-1 Clarification 3 (M3: admit ``weather.calibration.b_look_wrapper``; M4: refuse module
``weather.calibration.b_scorer`` when its first positional subcommand token is ``look`` or a prefix of it, or when
an option precedes the subcommand and a later token is, pointing to the wrapper;
``control`` and the other subcommands stay admitted). The Codex hook (``offline_subcommand_refusal``) and
``workload_admission.ps1`` (``Get-WeatherWorkstationOfflineArgumentRefusal``, called by ``workstation_heavy.ps1``)
must agree on every case below. The second adversarial pass (2026-11-01) added the fail-closed raw-text half: any
command naming b_scorer together with a look-like token is refused (launcher, env, path, ``-c`` and runpy forms),
except the exact b_look_wrapper form and read-only tooling; a look-like token is ``look``, a conservative ASCII
prefix of it, or any non-ASCII token.
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
    ["control", "look"],  # raw half: b_scorer named with a look token anywhere
    ["control", "--mode", "look"],
    ["control", "--out", "C:/t/look"],
    ["LOO\u212a"],  # Kelvin sign: non-ASCII in the subcommand position is refused on both sides
    ["control", "--out", "C:/t/caf\u00e9"],
]
ADMITTED = [
    [],
    ["control", "--out", "C:/t/x"],
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


def _evaluate(hook, command, capture=False):
    return hook.evaluate({"tool_name": "Bash", "tool_input": {"command": command}}, constrained_capture_host=capture)


S0_PATH = "src/weather/calibration/b_scorer.py"
BYPASS_FORMS = [
    f"python -m {SCORER} look --rule x",
    f"python -m{SCORER} look",
    f"python -m {SCORER} lo",
    f"PYTHONPATH=src python -m {SCORER} look --rule x",
    f"PYTHONPATH=src PYTHONUTF8=1 python -m {SCORER} look",
    f"env python -m {SCORER} look",
    f"env -i PYTHONPATH=src python -m {SCORER} look",
    f"uv run python -m {SCORER} look",
    f"uv run --frozen python -m {SCORER} look",
    f"uv run --with x python -m {SCORER} look",
    f"python {S0_PATH} look --rule x",
    "python src\\weather\\calibration\\b_scorer.py look",
    f"& \"{sys.executable}\" {S0_PATH} look",
    f"python -c \"from {SCORER} import main; main(['look', '--rule', 'x'])\"",
    "python -c \"from weather.calibration import b_scorer; b_scorer.look(rule='x')\"",
    "python -c \"import importlib; importlib.import_module('weather.calibration.b_scorer').main(['LOOK'])\"",
    f"python - <<'EOF'\nimport runpy, sys\nsys.argv = ['b', 'look']\nrunpy.run_module('{SCORER}', run_name='__main__')\nEOF",
    f"python -m runpy {SCORER} look",
    f"git show HEAD:{S0_PATH} | python - look",
    f"$py = 'python'; & $py -m {SCORER} look",
    "python b_scorer.py look --rule x",
    "cd src/weather/calibration && python b_scorer.py look",
    "cd src\\weather\\calibration; python .\\b_scorer.py LOOK",
    "python b_scorer.pyc look",
    # the read-only exemption is void on a comment, a newline or a backslash-escaped quote
    f"grep -n look {S0_PATH} # it's here\npython -m {SCORER} look --rule x",
    f"grep x \\' ; python -m {SCORER} look \\'",
    f"grep -n look {S0_PATH}\r\npython {S0_PATH} look",
    # sed and git global options are not inspection tooling
    f"sed -n '1e python -m {SCORER} look' {S0_PATH}",
    f"git -c core.pager='python -m {SCORER} look' show HEAD:{S0_PATH}",
    f"git -c alias.x='!python -m {SCORER} look' x",
]
STILL_ALLOWED_OR_ROUTED = [
    f"grep -n \"def look\" {S0_PATH}",
    f"git show 7da85e8cc3e9cecd00ab931cf5eca14ed12eb7a7:{S0_PATH} | Select-String look",
    f"Get-Content src\\weather\\calibration\\b_scorer.py | Select-String look",
    f"python -m weather.calibration.b_scorer_entry_edit --s0 C:/t/s0.py --s1 {S0_PATH}",
    f"& \"{sys.executable}\" -m {WRAPPER} look --s0 {S0_PATH} --rule docs/operations/B_FORWARD_TEST_DESIGN.md",
    f"python -m {WRAPPER} look --s0 C:/t/s0/b_scorer.py --rule x 2>&1",
    f"python -m {WRAPPER} look --s0 C:/t/s0/b_scorer.py --rule x 2>&1 | tee C:/t/b_look_log.txt",
    f"python -m {WRAPPER} look --s0 C:/t/s0/b_scorer.py --rule x | Tee-Object -FilePath C:\\t\\log.txt",
    "python -m weather.calibration.mg2_composite --x b_scorer_entry_edit look",
]


def test_hook_admits_the_wrapper_exactly():
    hook = _hook()
    assert WRAPPER in hook._OFFLINE_WEATHER_MODULES and SCORER in hook._OFFLINE_WEATHER_MODULES
    for near in (WRAPPER + ".child", WRAPPER + "_x", "weather.calibration.b_look"):
        assert near not in hook._OFFLINE_WEATHER_MODULES


@pytest.mark.parametrize("arguments", REFUSED, ids=repr)
def test_hook_refuses_b_scorer_look_and_options_before_the_subcommand(arguments):
    hook = _hook()
    reason = hook.offline_argument_refusal(SCORER, arguments)
    assert reason is not None and "python -m weather.calibration.b_look_wrapper look" in reason
    assert not hook._approved_workstation_arguments("weather_heavy", _b64(["-m", SCORER, *arguments]))


@pytest.mark.parametrize("arguments", ADMITTED, ids=repr)
def test_hook_keeps_the_other_b_scorer_subcommands_admitted(arguments):
    hook = _hook()
    assert hook.offline_argument_refusal(SCORER, arguments) is None
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
    cases = [(SCORER, a) for a in REFUSED + ADMITTED] + [
        (WRAPPER, ["look", "--s0", "x"]),
        (WRAPPER, ["look", "--s0", S0_PATH]),
        ("weather.calibration.mg2_composite", ["look"]),
        ("weather.calibration.mg2_composite", ["--x", S0_PATH, "look"]),
        ("weather.calibration.mg2_composite", ["--x", "src\\WEATHER\\Calibration\\B_SCORER.py", "Lo"]),
        ("weather.calibration.mg2_composite", ["--x", "weather.calibration.b_s\u017fcorer", "look"]),
        ("weather.calibration.mg2_composite", ["--x", "from weather.calibration import b_scorer", "l"]),
        ("weather.calibration.b_scorer_entry_edit", ["--s0", "C:/t/s0.py", "--s1", S0_PATH]),
        ("weather.calibration.b_scorer_entry_edit", ["--s1", S0_PATH, "look"]),
        ("weather.calibration.mg2_composite", ["--x", "b_scorer.py", "look"]),
        ("weather.calibration.mg2_composite", ["--x", "B_SCORER", "lo"]),
        ("weather.calibration.mg2_composite", ["--x", ".\\b_scorer.pyw", "look"]),
        ("weather.calibration.mg2_composite", ["--x", "b_scorer_entry_edit", "look"]),
        ("weather.calibration.mg2_composite", ["--x", "my_b_scorer.py", "look"]),
    ]
    (tmp_path / "cases.json").write_text(json.dumps([{"module": m, "arguments": a} for m, a in cases]),
                                         encoding="utf-8")  # ASCII JSON (\\u escapes): codepage-proof
    script = tmp_path / "refusals.ps1"
    script.write_text(
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"  # decoded as UTF-8 below, whatever PYTHONUTF8
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
                             "-File", str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    listing, refusals = result.stdout.strip().splitlines()[-2:]
    assert set(json.loads(listing)) == hook._OFFLINE_WEATHER_MODULES
    got = json.loads(refusals)
    assert len(got) == len(cases)
    for (module, arguments), text in zip(cases, got):
        expected = hook.offline_argument_refusal(module, arguments)
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


@pytest.mark.parametrize("capture", [False, True], ids=["workstation", "capture_host"])
@pytest.mark.parametrize("command", BYPASS_FORMS, ids=repr)
def test_hook_denies_every_bypass_form_on_both_host_kinds(command, capture):
    denied = _evaluate(_hook(), command, capture)
    assert denied is not None and denied["hookSpecificOutput"]["permissionDecision"] == "deny", command
    assert "b_look_wrapper look" in denied["hookSpecificOutput"]["permissionDecisionReason"], command


@pytest.mark.parametrize("capture", [False, True], ids=["workstation", "capture_host"])
@pytest.mark.parametrize("command", STILL_ALLOWED_OR_ROUTED, ids=repr)
def test_hook_does_not_refuse_reads_the_entry_edit_check_or_the_exact_wrapper(command, capture):
    """Allowlisted inspection tooling and the S0 to S1 checker are not refused by the b_scorer rule; the exact
    wrapper form is not refused by it either (it may still be routed through workstation_heavy.ps1 as heavy
    work)."""
    result = _evaluate(_hook(), command, capture)
    assert result is None or "b_look_wrapper look" not in result["hookSpecificOutput"]["permissionDecisionReason"]


def test_the_wrapper_exemption_is_exact():
    hook = _hook()
    for command in (f"python -m {WRAPPER} look --s0 {S0_PATH}; python {S0_PATH} look",
                    f"python -m {WRAPPER}x look --s0 {S0_PATH}",
                    f"python -m {WRAPPER} look --s0 $(echo {S0_PATH})",
                    f"python -m {WRAPPER} look --s0 x # it's here\npython -m {SCORER} look --rule x",
                    f"python -m {WRAPPER} look --s0 x \\' ; python -m {SCORER} look \\'",
                    f"python -m {WRAPPER} look --s0 x\rpython {S0_PATH} look",
                    f"python -m {WRAPPER} look --s0 x 2>&1 | tee C:/t/l.txt; python {S0_PATH} look",
                    f"python -m {WRAPPER} look --s0 x 2>&1 | python {S0_PATH} look",
                    f"python -m {WRAPPER} look --s0 {S0_PATH} > {S0_PATH} look"):
        assert "b_look_wrapper look" in _evaluate(hook, command)["hookSpecificOutput"]["permissionDecisionReason"]
    for allowed in (f"python -m {WRAPPER} look --s0 {S0_PATH} --rule x 2>&1",
                    f"python -m {WRAPPER} look --s0 {S0_PATH} --rule x 2>&1 | tee C:/t/log.txt",
                    f"python -m {WRAPPER} look --s0 {S0_PATH} | tee C:/t/log.txt"):
        assert hook._exact_b_look_wrapper_command(allowed), allowed
    assert hook.offline_argument_refusal(WRAPPER, ["look", "--s0", S0_PATH]) is None
    assert hook.offline_argument_refusal("weather.calibration.mg2_composite", ["--x", S0_PATH, "look"]) is not None


def test_the_read_only_exemption_is_narrow():
    hook = _hook()
    for command in (f"grep -n look {S0_PATH}", f"git show HEAD:{S0_PATH}", f"git log -p -- {S0_PATH}",
                    f"git diff HEAD~1 -- {S0_PATH}", f"Get-Content {S0_PATH} | Select-String look"):
        assert hook._read_only_command(command), command
    for command in (f"grep -n look {S0_PATH} # it's here\npython -m {SCORER} look --rule x",
                    f"grep x \\' ; python -m {SCORER} look \\'",
                    f"grep -n look {S0_PATH}\rpython {S0_PATH} look",
                    f"sed -n '1e python -m {SCORER} look' {S0_PATH}",
                    f"sed -n 1,5p {S0_PATH}",
                    f"git -c core.pager=cat show HEAD:{S0_PATH}",
                    f"git -c alias.x='!python -m {SCORER} look' x",
                    f"git -C src show HEAD:{S0_PATH}",
                    "git config core.pager x",
                    f"git grep -O look -- {S0_PATH}",
                    f"rg --pre ./x look {S0_PATH}",
                    f"less {S0_PATH}"):
        assert not hook._read_only_command(command), command
