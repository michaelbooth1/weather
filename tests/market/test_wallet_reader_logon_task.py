"""WeatherWalletReader registrar: dedicated worktree, reviewed commit, writable journal.

Runs the real registrar in -WhatIf against a fixture git repository and a linked worktree,
with the network and Scheduler cmdlets mocked. Nothing registers a task or opens a socket.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from weather.paths import REPO_ROOT

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell registrar")

SCRIPT = REPO_ROOT / "scripts/ops/register_wallet_reader_logon_task.ps1"
SHIM = (REPO_ROOT / "weather/__init__.py").read_text(encoding="utf-8")
HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:mutations = 0
function Get-NetIPAddress { param($IPAddress, $ErrorAction) [pscustomobject]@{ IPAddress = $IPAddress } }
function Get-NetFirewallRule { param($Name, $ErrorAction) [pscustomobject]@{ Name = $Name } }
function Get-ScheduledTask { param($TaskName, $ErrorAction) $null }
function Register-ScheduledTask { $global:mutations++ }
function Unregister-ScheduledTask { $global:mutations++ }
$params = $env:REGISTRAR_PARAMS | ConvertFrom-Json
$splat = @{}
foreach ($p in $params.PSObject.Properties) { $splat[$p.Name] = $p.Value }
$out, $err = @(), ''
try { $out = @(& $env:REGISTRAR @splat -WhatIf 6>$null) } catch { $err = $_.Exception.Message }
[pscustomobject]@{ error = $err; mutations = $global:mutations; output = ($out -join "`n") } | ConvertTo-Json -Compress
"""


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "core.autocrlf=false", *args], cwd=cwd, check=True, capture_output=True)


def fixture(tmp_path, *, in_src=True):
    main = tmp_path / "main"
    if in_src:
        files = {"weather/__init__.py": SHIM, "src/weather/market/__init__.py": "",
                 "src/weather/market/wallet_reader.py": ""}
    else:  # a checkout whose reader module would import from outside RepoRoot\src
        files = {"weather/__init__.py": "", "weather/market/__init__.py": "", "weather/market/wallet_reader.py": "",
                 "src/weather/market/wallet_reader.py": ""}
    for name, text in files.items():
        (main / name).parent.mkdir(parents=True, exist_ok=True)
        (main / name).write_text(text, encoding="utf-8")
    git(main, "init", "-q")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "fixture")
    worktree = tmp_path / "reader-wt"
    git(main, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, check=True,
                            capture_output=True, text=True).stdout.strip()
    return main, worktree, commit


def register(repo, commit, *, python=sys.executable, allow="192.168.1.30"):
    params = dict(RepoRoot=str(repo), ExpectedCommit=commit, Bind="192.168.1.20", SignatureType=2)
    if allow is not None:
        params["AllowIp"] = allow
    if python is not None:
        params["PythonPath"] = python
    env = {**os.environ, "REGISTRAR": str(SCRIPT), "REGISTRAR_PARAMS": json.dumps(params)}
    env.pop("PYTHONPATH", None)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", HARNESS], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["mutations"] == 0  # -WhatIf never reaches the Scheduler
    return payload


def test_dedicated_worktree_at_reviewed_commit_plans_main_venv_python(tmp_path):
    _, worktree, commit = fixture(tmp_path)
    payload = register(worktree, commit)
    assert payload["error"] == ""
    plan = payload["output"]
    assert f"python={Path(sys.executable)}" in plan and f"workdir={worktree}" in plan
    assert f"commit={commit}" in plan and str(worktree / "data" / "wallet_reader") in plan
    assert "-m weather.market.wallet_reader serve --bind 192.168.1.20 --allow 192.168.1.30" in plan
    assert not (worktree / "data").exists()  # -WhatIf creates no journal folder
    assert not list(worktree.rglob(".write-probe-*"))  # the writability probe leaves nothing behind


@pytest.mark.spawns
def test_allow_ip_is_optional_and_omitted_from_the_serve_arguments(tmp_path):
    # Owner decision 2026-10-09: without -AllowIp serve admits any RFC1918 or loopback caller.
    _, worktree, commit = fixture(tmp_path)
    payload = register(worktree, commit, allow=None)
    assert payload["error"] == ""
    assert "-m weather.market.wallet_reader serve --bind 192.168.1.20 --port 8765 --signature-type 2" in payload["output"]
    assert "--allow" not in payload["output"]


@pytest.mark.spawns
@pytest.mark.parametrize("allow", ["127.0.0.1", "8.8.8.8", "0.0.0.0"])
def test_a_given_allow_ip_must_still_be_rfc1918(tmp_path, allow):
    _, worktree, commit = fixture(tmp_path)
    assert "RFC1918" in register(worktree, commit, allow=allow)["error"]


@pytest.mark.parametrize("case,message", [
    ("main_checkout", "dedicated linked worktree"),
    ("wrong_commit", "is not the reviewed ExpectedCommit"),
    ("short_commit", "full lowercase commit SHA"),
    ("dirty", "uncommitted changes"),
    ("default_python_missing", "PythonPath"),
])
def test_refuses_anything_but_a_clean_reviewed_worktree(tmp_path, case, message):
    main, worktree, commit = fixture(tmp_path)
    repo, python = worktree, sys.executable
    if case == "main_checkout":
        repo = main
    elif case == "wrong_commit":
        commit = "0" * 40
    elif case == "short_commit":
        commit = commit[:12]
    elif case == "dirty":
        (worktree / "src/weather/market/wallet_reader.py").write_text("edited", encoding="utf-8")
    elif case == "default_python_missing":
        python = None  # defaults to <main checkout>\venv\Scripts\python.exe, absent in the fixture
    payload = register(repo, commit, python=python)
    assert message in payload["error"]


def test_refuses_a_reader_module_that_imports_from_outside_the_worktree_src(tmp_path):
    _, worktree, commit = fixture(tmp_path, in_src=False)
    assert "does not import from RepoRoot" in register(worktree, commit)["error"]


def test_refuses_a_journal_path_that_is_not_a_folder(tmp_path):
    _, worktree, commit = fixture(tmp_path)
    (worktree / "data").mkdir()
    (worktree / "data" / "wallet_reader").write_text("", encoding="utf-8")
    assert "not a folder" in register(worktree, commit)["error"]


def test_refuses_write_protected_data_like_the_workstation_mirror(tmp_path):
    _, worktree, commit = fixture(tmp_path)
    data = worktree / "data"
    data.mkdir()
    # Name the current account by SID: USERDOMAIN\USERNAME does not resolve on every host
    # (a workgroup machine reports USERDOMAIN=WORKGROUP, icacls error 1332).
    sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True).stdout
    user = "*" + sid.strip().split(",")[-1].strip('"')
    subprocess.run(["icacls", str(data), "/deny", f"{user}:(OI)(CI)(WD,AD)"], check=True, capture_output=True)
    try:
        assert "not writable" in register(worktree, commit)["error"]
    finally:
        subprocess.run(["icacls", str(data), "/remove:d", user], check=True, capture_output=True)


def test_task_shape_stays_s4u_limited_from_the_reviewed_worktree():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "-LogonType S4U -RunLevel Limited" in script
    assert "New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repo" in script
    assert "Test-WritableFolder" in script and "--git-common-dir" in script


FIREWALL = REPO_ROOT / "scripts/ops/register_wallet_reader_firewall.ps1"
FIREWALL_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:created = @()
function Get-NetFirewallRule { param($Name, $ErrorAction) $null }
function Remove-NetFirewallRule { param($Name, $ErrorAction) }
function New-NetFirewallRule { param($Name, $RemoteAddress, $LocalPort)
    $global:created += [pscustomobject]@{ name = $Name; remote = @($RemoteAddress); port = $LocalPort; rest = ($args -join ' ') } }
$params = $env:FIREWALL_PARAMS | ConvertFrom-Json
$splat = @{}
foreach ($p in $params.PSObject.Properties) { $splat[$p.Name] = $p.Value }
$err = ''
try { & $env:FIREWALL_SCRIPT @splat 6>$null | Out-Null } catch { $err = $_.Exception.Message }
[pscustomobject]@{ error = $err; created = @($global:created) } | ConvertTo-Json -Compress -Depth 4
"""


def firewall(**params):
    env = {**os.environ, "FIREWALL_SCRIPT": str(FIREWALL), "FIREWALL_PARAMS": json.dumps(params)}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", FIREWALL_HARNESS], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    created = payload["created"]
    payload["created"] = created if isinstance(created, list) else [created]
    return payload


@pytest.mark.spawns
@pytest.mark.parametrize("params,name,remote", [
    ({}, "WeatherWalletReader-anylan-8765", ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]),
    ({"AllowIp": "192.168.1.30"}, "WeatherWalletReader-192.168.1.30-8765", ["192.168.1.30"]),
])
def test_firewall_rule_is_any_lan_by_default_or_one_exact_ip(params, name, remote):
    payload = firewall(**params)
    assert payload["error"] == ""
    (rule,) = payload["created"]
    assert rule["name"] == name and rule["remote"] == remote and rule["port"] == 8765
    assert "-Profile Private" in rule["rest"] and "-Direction Inbound" in rule["rest"]


@pytest.mark.spawns
@pytest.mark.parametrize("allow", ["127.0.0.1", "8.8.8.8", "0.0.0.0", "::1", "192.168.001.30"])
def test_firewall_refuses_a_non_rfc1918_allow_ip(allow):
    payload = firewall(AllowIp=allow)
    assert "AllowIp must" in payload["error"] and payload["created"] in ([], [None])
