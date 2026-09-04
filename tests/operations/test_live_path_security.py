from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from ctypes import wintypes

import pytest

from weather.operations import live_path_security as security

WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)


def _process_record(
    pid,
    parent_pid,
    image_path,
    *,
    inspectable=True,
    creation_ticks=None,
):
    return {
        "state": "running",
        "pid": pid,
        "parent_pid": parent_pid,
        "image_path": str(image_path),
        "command_line": f'"{image_path}" reviewed',
        "creation_time_token": f"win32-filetime:{creation_ticks or pid}",
        "inspectable": inspectable,
    }


def test_live_launcher_lineage_accepts_direct_lease_owner(tmp_path):
    owner = tmp_path / "powershell.exe"
    redirector = tmp_path / "python.exe"
    runtime = tmp_path / "runtime-python.exe"
    pyvenv_config = tmp_path / "pyvenv.cfg"
    lease = tmp_path / "heavy_workload.lock"
    owner.write_bytes(b"owner")
    redirector.write_bytes(b"redirector")
    runtime.write_bytes(b"runtime")
    pyvenv_config.write_text("reviewed", encoding="utf-8")
    lease.write_text("{}", encoding="utf-8")
    records = {
        101: _process_record(101, 1, owner),
        303: _process_record(303, 101, runtime),
    }

    result = security.validate_launcher_lease_process_lineage(
        lease_owner_pid=101,
        lease_path=lease,
        expected_owner_creation_time_token="win32-filetime:101",
        expected_owner_executable=owner,
        expected_pyvenv_config=pyvenv_config,
        expected_pyvenv_config_sha256=hashlib.sha256(
            pyvenv_config.read_bytes()
        ).hexdigest(),
        expected_redirector_executable=redirector,
        expected_redirector_sha256=hashlib.sha256(
            redirector.read_bytes()
        ).hexdigest(),
        expected_runtime_executable=runtime,
        expected_runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
        current_pid_reader=lambda: 303,
        parent_pid_reader=lambda: 101,
        process_observer=records.__getitem__,
        lease_active_probe=lambda _path: True,
    )

    assert result["status"] == "PASS"
    assert result["relationship"] == "direct_lease_owner"
    assert result["redirector_creation_token_sha256"] is None


def test_live_launcher_lineage_accepts_one_exact_venv_redirector(tmp_path):
    owner = tmp_path / "powershell.exe"
    redirector = tmp_path / "python.exe"
    runtime = tmp_path / "runtime-python.exe"
    pyvenv_config = tmp_path / "pyvenv.cfg"
    lease = tmp_path / "heavy_workload.lock"
    owner.write_bytes(b"owner")
    redirector.write_bytes(b"redirector")
    runtime.write_bytes(b"runtime")
    pyvenv_config.write_text("reviewed", encoding="utf-8")
    lease.write_text("{}", encoding="utf-8")
    records = {
        101: _process_record(101, 1, owner),
        202: _process_record(202, 101, redirector),
        303: _process_record(303, 202, runtime),
    }

    result = security.validate_launcher_lease_process_lineage(
        lease_owner_pid=101,
        lease_path=lease,
        expected_owner_creation_time_token="win32-filetime:101",
        expected_owner_executable=owner,
        expected_pyvenv_config=pyvenv_config,
        expected_pyvenv_config_sha256=hashlib.sha256(
            pyvenv_config.read_bytes()
        ).hexdigest(),
        expected_redirector_executable=redirector,
        expected_redirector_sha256=hashlib.sha256(
            redirector.read_bytes()
        ).hexdigest(),
        expected_runtime_executable=runtime,
        expected_runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
        current_pid_reader=lambda: 303,
        parent_pid_reader=lambda: 202,
        process_observer=records.__getitem__,
        lease_active_probe=lambda _path: True,
    )

    assert result["status"] == "PASS"
    assert result["relationship"] == "single_sealed_python_redirector"
    assert result["redirector_creation_token_sha256"]


@pytest.mark.parametrize(
    ("redirector_parent", "redirector_image", "inspectable", "hash_matches"),
    [
        (303, "expected", True, True),
        (101, "wrong", True, True),
        (101, "expected", False, True),
        (101, "expected", True, False),
    ],
)
def test_live_launcher_lineage_rejects_unsealed_or_extra_hops(
    tmp_path,
    redirector_parent,
    redirector_image,
    inspectable,
    hash_matches,
):
    owner = tmp_path / "powershell.exe"
    redirector = tmp_path / "python.exe"
    runtime = tmp_path / "runtime-python.exe"
    pyvenv_config = tmp_path / "pyvenv.cfg"
    wrong = tmp_path / "wrong-python.exe"
    lease = tmp_path / "heavy_workload.lock"
    owner.write_bytes(b"owner")
    redirector.write_bytes(b"redirector")
    runtime.write_bytes(b"runtime")
    pyvenv_config.write_text("reviewed", encoding="utf-8")
    wrong.write_bytes(b"wrong")
    lease.write_text("{}", encoding="utf-8")
    observed_redirector = redirector if redirector_image == "expected" else wrong
    records = {
        101: _process_record(101, 1, owner),
        202: _process_record(
            202,
            redirector_parent,
            observed_redirector,
            inspectable=inspectable,
        ),
        303: _process_record(303, 202, runtime),
    }
    expected_hash = hashlib.sha256(
        (redirector if hash_matches else wrong).read_bytes()
    ).hexdigest()

    with pytest.raises(security.LivePathSecurityError):
        security.validate_launcher_lease_process_lineage(
            lease_owner_pid=101,
            lease_path=lease,
            expected_owner_creation_time_token="win32-filetime:101",
            expected_owner_executable=owner,
            expected_pyvenv_config=pyvenv_config,
            expected_pyvenv_config_sha256=hashlib.sha256(
                pyvenv_config.read_bytes()
            ).hexdigest(),
            expected_redirector_executable=redirector,
            expected_redirector_sha256=expected_hash,
            expected_runtime_executable=runtime,
            expected_runtime_sha256=hashlib.sha256(
                runtime.read_bytes()
            ).hexdigest(),
            current_pid_reader=lambda: 303,
            parent_pid_reader=lambda: 202,
            process_observer=records.__getitem__,
            lease_active_probe=lambda _path: True,
        )


def test_live_launcher_lineage_rejects_stale_lease_or_reused_owner_pid(tmp_path):
    owner = tmp_path / "powershell.exe"
    redirector = tmp_path / "python.exe"
    runtime = tmp_path / "runtime-python.exe"
    pyvenv_config = tmp_path / "pyvenv.cfg"
    lease = tmp_path / "heavy_workload.lock"
    owner.write_bytes(b"owner")
    redirector.write_bytes(b"redirector")
    runtime.write_bytes(b"runtime")
    pyvenv_config.write_text("reviewed", encoding="utf-8")
    lease.write_text("{}", encoding="utf-8")
    records = {
        101: _process_record(101, 1, owner),
        303: _process_record(303, 101, runtime),
    }
    common = {
        "lease_owner_pid": 101,
        "lease_path": lease,
        "expected_owner_executable": owner,
        "expected_pyvenv_config": pyvenv_config,
        "expected_pyvenv_config_sha256": hashlib.sha256(
            pyvenv_config.read_bytes()
        ).hexdigest(),
        "expected_redirector_executable": redirector,
        "expected_redirector_sha256": hashlib.sha256(
            redirector.read_bytes()
        ).hexdigest(),
        "expected_runtime_executable": runtime,
        "expected_runtime_sha256": hashlib.sha256(
            runtime.read_bytes()
        ).hexdigest(),
        "current_pid_reader": lambda: 303,
        "parent_pid_reader": lambda: 101,
        "process_observer": records.__getitem__,
    }

    with pytest.raises(security.LivePathSecurityError, match="not active"):
        security.validate_launcher_lease_process_lineage(
            **common,
            expected_owner_creation_time_token="win32-filetime:101",
            lease_active_probe=lambda _path: False,
        )
    with pytest.raises(security.LivePathSecurityError, match="instance changed"):
        security.validate_launcher_lease_process_lineage(
            **common,
            expected_owner_creation_time_token="win32-filetime:999",
            lease_active_probe=lambda _path: True,
        )


@pytest.mark.parametrize("fault", ["runtime_image", "runtime_hash", "creation_order"])
def test_live_launcher_lineage_rejects_runtime_or_process_reuse_faults(
    tmp_path,
    fault,
):
    owner = tmp_path / "powershell.exe"
    redirector = tmp_path / "python.exe"
    runtime = tmp_path / "runtime-python.exe"
    wrong_runtime = tmp_path / "wrong-runtime.exe"
    pyvenv_config = tmp_path / "pyvenv.cfg"
    lease = tmp_path / "heavy_workload.lock"
    for path, payload in (
        (owner, b"owner"),
        (redirector, b"redirector"),
        (runtime, b"runtime"),
        (wrong_runtime, b"wrong-runtime"),
    ):
        path.write_bytes(payload)
    pyvenv_config.write_text("reviewed", encoding="utf-8")
    lease.write_text("{}", encoding="utf-8")
    records = {
        101: _process_record(101, 1, owner),
        202: _process_record(
            202,
            101,
            redirector,
            creation_ticks=404 if fault == "creation_order" else 202,
        ),
        303: _process_record(
            303,
            202,
            wrong_runtime if fault == "runtime_image" else runtime,
        ),
    }

    with pytest.raises(security.LivePathSecurityError):
        security.validate_launcher_lease_process_lineage(
            lease_owner_pid=101,
            lease_path=lease,
            expected_owner_creation_time_token="win32-filetime:101",
            expected_owner_executable=owner,
            expected_pyvenv_config=pyvenv_config,
            expected_pyvenv_config_sha256=hashlib.sha256(
                pyvenv_config.read_bytes()
            ).hexdigest(),
            expected_redirector_executable=redirector,
            expected_redirector_sha256=hashlib.sha256(
                redirector.read_bytes()
            ).hexdigest(),
            expected_runtime_executable=runtime,
            expected_runtime_sha256=hashlib.sha256(
                (wrong_runtime if fault == "runtime_hash" else runtime).read_bytes()
            ).hexdigest(),
            current_pid_reader=lambda: 303,
            parent_pid_reader=lambda: 202,
            process_observer=records.__getitem__,
            lease_active_probe=lambda _path: True,
        )


def test_launcher_lineage_receipts_must_be_complete_and_consistent():
    lineage = {
        "status": "PASS",
        "relationship": "single_sealed_python_redirector",
        "lease_owner_creation_token_sha256": "1" * 64,
        "redirector_creation_token_sha256": "2" * 64,
        "runtime_creation_token_sha256": "3" * 64,
    }
    attestations = [
        {"lease_process_lineage": json.loads(json.dumps(lineage))}
        for _index in range(3)
    ]

    assert security.launcher_host_attestations_have_consistent_lease_lineage(
        attestations
    )
    attestations[2]["lease_process_lineage"][
        "runtime_creation_token_sha256"
    ] = "4" * 64
    assert not security.launcher_host_attestations_have_consistent_lease_lineage(
        attestations
    )


def test_complete_launcher_host_attestations_require_identity_and_status_shape():
    lineage = {
        "status": "PASS",
        "relationship": "single_sealed_python_redirector",
        "lease_owner_creation_token_sha256": "1" * 64,
        "redirector_creation_token_sha256": "2" * 64,
        "runtime_creation_token_sha256": "3" * 64,
    }
    attestations = [
        {
            "checked_at_local": "2026-08-30T22:00:00-04:00",
            "status_json_sha256": "9" * 64,
            "status_flag_sha256": [],
            "execution_host_profile": "capture_colocated_v1",
            "execution_host_id": "f" * 64,
            "lease_process_lineage": json.loads(json.dumps(lineage)),
        }
        for _index in range(3)
    ]

    assert security.launcher_host_attestations_are_valid(
        attestations,
        expected_execution_host_profile="capture_colocated_v1",
        expected_execution_host_id="f" * 64,
        expected_status_flag_sha256=[],
    )
    del attestations[1]["checked_at_local"]
    assert not security.launcher_host_attestations_are_valid(
        attestations,
        expected_execution_host_profile="capture_colocated_v1",
        expected_execution_host_id="f" * 64,
        expected_status_flag_sha256=[],
    )


def test_production_python_runtime_binding_requires_one_canonical_venv_chain(
    tmp_path,
):
    root = tmp_path / "production"
    redirector = root / "venv/Scripts/python.exe"
    redirector.parent.mkdir(parents=True)
    redirector.write_bytes(b"redirector")
    runtime_home = root / "runtime"
    runtime_home.mkdir(parents=True)
    runtime = runtime_home / "python.exe"
    runtime.write_bytes(b"runtime")
    config = root / "venv/pyvenv.cfg"
    config.write_text(
        f"home = {runtime_home}\nexecutable = {runtime}\n",
        encoding="utf-8",
    )

    binding = security.resolve_production_python_runtime_binding(root)
    assert security.validate_production_python_runtime_binding(binding) == binding

    unrelated = tmp_path / "unrelated.cfg"
    unrelated.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    invalid = dict(binding)
    invalid["pyvenv_config"] = str(unrelated.resolve())
    invalid["pyvenv_config_sha256"] = hashlib.sha256(
        unrelated.read_bytes()
    ).hexdigest()
    with pytest.raises(security.LivePathSecurityError):
        security.validate_production_python_runtime_binding(invalid)


@pytest.mark.parametrize(
    ("path_key", "target_key"),
    [
        ("pyvenv_config", "pyvenv_config"),
        ("runtime_process_image", "runtime_process_image"),
    ],
)
def test_production_python_runtime_binding_rejects_reparse_aliases(
    tmp_path,
    path_key,
    target_key,
):
    root = tmp_path / "production"
    redirector = root / "venv/Scripts/python.exe"
    redirector.parent.mkdir(parents=True)
    redirector.write_bytes(b"redirector")
    runtime_home = root / "runtime"
    runtime_home.mkdir(parents=True)
    runtime = runtime_home / "python.exe"
    runtime.write_bytes(b"runtime")
    config = root / "venv/pyvenv.cfg"
    config.write_text(
        f"home = {runtime_home}\nexecutable = {runtime}\n",
        encoding="utf-8",
    )
    binding = security.resolve_production_python_runtime_binding(root)
    alias = tmp_path / f"alias-{path_key}"
    try:
        alias.symlink_to(Path(binding[target_key]))
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")
    invalid = dict(binding)
    # Preserve the lexical alias; Path.resolve would erase the redirection.
    invalid[path_key] = str(alias.absolute())

    with pytest.raises(security.LivePathSecurityError, match="redirected"):
        security.validate_production_python_runtime_binding(invalid)


@WINDOWS_POWERSHELL_REQUIRED
def test_deny_write_probe_rejects_a_permissive_existing_writer(tmp_path):
    lease = tmp_path / "permissive.lock"
    lease.write_bytes(b"reviewed")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(lease),
        0xC0000000,  # GENERIC_READ | GENERIC_WRITE
        0x00000007,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        None,
        3,
        0x00000080,
        None,
    )
    assert handle != ctypes.c_void_p(-1).value
    try:
        assert security._windows_lease_file_is_deny_write_held(lease) is False
    finally:
        close_handle(handle)


@WINDOWS_POWERSHELL_REQUIRED
def test_live_launcher_lineage_accepts_real_windows_venv_redirector(tmp_path):
    base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    venv_python = Path(sys.executable).resolve()
    pyvenv_config = Path(sys.prefix) / "pyvenv.cfg"
    if base_python == venv_python:
        pytest.skip("the active interpreter has no Windows venv redirector")
    repo = Path(__file__).resolve().parents[2]
    job_script = repo / "scripts/ops/windows_kill_on_close_job.ps1"
    site_packages = Path(sys.prefix) / "Lib/site-packages"
    powershell = security.canonical_windows_powershell()
    probe = tmp_path / "lineage-probe.ps1"
    probe.write_text(
        r'''
param(
    [string]$JobScript,
    [string]$Python,
    [string]$Repo,
    [string]$SitePackages,
    [string]$PyvenvConfig,
    [string]$PyvenvConfigHash,
    [string]$ExpectedHash,
    [string]$RuntimePython,
    [string]$RuntimeHash
)
$ErrorActionPreference = "Stop"
. $JobScript
$job = New-WeatherKillOnCloseJob
try {
    $owner = Join-Path $PSHOME "powershell.exe"
    $leasePath = Join-Path ([IO.Path]::GetTempPath()) ("weather-lineage-" + [guid]::NewGuid().ToString("N") + ".lock")
    $leaseStream = [IO.File]::Open(
        $leasePath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::Read
    )
    $self = [Diagnostics.Process]::GetCurrentProcess()
    try {
        $ownerToken = "win32-filetime:{0}" -f $self.StartTime.ToUniversalTime().ToFileTimeUtc()
    }
    finally { $self.Dispose() }
    $env:PYTHONPATH = @((Join-Path $Repo "src"), $SitePackages) -join `
        [IO.Path]::PathSeparator
    $code = 'import sys;from weather.operations.live_path_security import validate_launcher_lease_process_lineage;r=validate_launcher_lease_process_lineage(lease_owner_pid=int(sys.argv[3]),lease_path=sys.argv[4],expected_owner_creation_time_token=sys.argv[5],expected_owner_executable=sys.argv[6],expected_pyvenv_config=sys.argv[7],expected_pyvenv_config_sha256=sys.argv[8],expected_redirector_executable=sys.argv[9],expected_redirector_sha256=sys.argv[10],expected_runtime_executable=sys.argv[11],expected_runtime_sha256=sys.argv[12]);raise SystemExit(0 if r["relationship"]=="single_sealed_python_redirector" else 9)'
    $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens @(
        "-P", "-S", "-B", "-c", $code, $Repo, $SitePackages,
        [string]$PID, $leasePath, $ownerToken, $owner,
        $PyvenvConfig, $PyvenvConfigHash, $Python, $ExpectedHash,
        $RuntimePython, $RuntimeHash
    )
    $child = Start-WeatherInteractiveProcessInJob `
        -Job $job `
        -FilePath $Python `
        -ArgumentString $arguments `
        -WorkingDirectory $Repo
    $child.WaitForExit()
    exit ([int]$child.ExitCode)
}
finally {
    if ($job) { $job.Dispose() }
    if ($leaseStream) { $leaseStream.Dispose() }
    if ($leasePath -and (Test-Path -LiteralPath $leasePath)) {
        Remove-Item -LiteralPath $leasePath -Force
    }
}
'''.lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe),
            str(job_script),
            str(venv_python),
            str(repo),
            str(site_packages),
            str(pyvenv_config),
            hashlib.sha256(pyvenv_config.read_bytes()).hexdigest(),
            hashlib.sha256(venv_python.read_bytes()).hexdigest(),
            str(base_python),
            hashlib.sha256(base_python.read_bytes()).hexdigest(),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


@WINDOWS_POWERSHELL_REQUIRED
def test_canonical_powershell_ignores_path_shadow(monkeypatch, tmp_path):
    shadow = tmp_path / "powershell.exe"
    shadow.write_text("shadow", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))

    result = security.canonical_windows_powershell()

    assert result != shadow
    assert "System32" in str(result)


def test_private_acl_validator_accepts_only_current_user_owned_root(monkeypatch, tmp_path):
    monkeypatch.setattr(security, "is_reparse", lambda _path: False)
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(
            [], 0, json.dumps({"current_user_write": True, "broad_write_count": 0}), ""
        )

    monkeypatch.setattr(security.subprocess, "run", runner)

    result = security.validate_private_attempt_root(
        tmp_path, powershell_path=tmp_path / "powershell.exe"
    )

    assert result["status"] == "PASS"
    encoded = captured["command"][captured["command"].index("-EncodedCommand") + 1]
    source = base64.b64decode(encoded).decode("utf-16le")
    assert "[IO.Directory]::GetAccessControl($path)" in source
    assert "Get-Acl" not in source


def test_private_acl_validator_rejects_broad_write_or_reparse(monkeypatch, tmp_path):
    monkeypatch.setattr(security, "is_reparse", lambda _path: False)
    monkeypatch.setattr(
        security.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, json.dumps({"current_user_write": True, "broad_write_count": 1}), ""
        ),
    )
    with pytest.raises(security.LivePathSecurityError, match="broadly writable"):
        security.validate_private_attempt_root(
            tmp_path, powershell_path=tmp_path / "powershell.exe"
        )

    monkeypatch.setattr(security, "is_reparse", lambda _path: True)
    with pytest.raises(security.LivePathSecurityError, match="redirected"):
        security.validate_private_attempt_root(
            tmp_path, powershell_path=tmp_path / "powershell.exe"
        )


def test_contained_file_rejects_redirect_before_resolve(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    artifact = target / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    redirected = tmp_path / "redirected"
    try:
        redirected.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(security.LivePathSecurityError, match="redirected"):
        security.validate_contained_regular_file(
            tmp_path, redirected / artifact.name
        )


def test_no_ambient_proxy_configuration_accepts_exact_direct_state():
    result = security.assert_no_ambient_proxy_configuration(
        environment={"PATH": "ignored"},
        user_proxy_reader=lambda: {
            "proxy_enabled": False,
            "automatic_configuration": False,
            "automatic_detection": False,
        },
        winhttp_direct_reader=lambda: True,
    )

    assert result == {
        "status": "PASS",
        "market_registry_override": False,
        "environment_proxy_variables": [],
        "current_user_proxy": "DIRECT",
        "winhttp_proxy": "DIRECT",
    }


@pytest.mark.parametrize(
    "environment_key",
    [
        "HTTP_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "NO_PROXY",
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ],
)
def test_no_ambient_proxy_configuration_rejects_process_redirects(environment_key):
    with pytest.raises(security.LivePathSecurityError, match="ambient proxy"):
        security.assert_no_ambient_proxy_configuration(
            environment={environment_key: "configured"},
            user_proxy_reader=lambda: {
                "proxy_enabled": False,
                "automatic_configuration": False,
                "automatic_detection": False,
            },
            winhttp_direct_reader=lambda: True,
        )


def test_no_ambient_market_registry_override_is_case_insensitive():
    with pytest.raises(security.LivePathSecurityError, match="market-registry"):
        security.assert_no_ambient_market_registry_override(
            environment={"weather_market_registry": "C:/untracked/markets.json"}
        )


def test_proxy_gate_also_rejects_market_registry_override():
    with pytest.raises(security.LivePathSecurityError, match="market-registry"):
        security.assert_no_ambient_proxy_configuration(
            environment={"WEATHER_MARKET_REGISTRY": "C:/untracked/markets.json"},
            user_proxy_reader=lambda: {
                "proxy_enabled": False,
                "automatic_configuration": False,
                "automatic_detection": False,
            },
            winhttp_direct_reader=lambda: True,
        )


@pytest.mark.parametrize(
    "user_state",
    [
        {
            "proxy_enabled": True,
            "automatic_configuration": False,
            "automatic_detection": False,
        },
        {
            "proxy_enabled": False,
            "automatic_configuration": True,
            "automatic_detection": False,
        },
        {
            "proxy_enabled": False,
            "automatic_configuration": False,
            "automatic_detection": True,
        },
    ],
)
def test_no_ambient_proxy_configuration_rejects_windows_user_proxy(user_state):
    with pytest.raises(security.LivePathSecurityError, match="Windows proxy"):
        security.assert_no_ambient_proxy_configuration(
            environment={},
            user_proxy_reader=lambda: user_state,
            winhttp_direct_reader=lambda: True,
        )


def test_no_ambient_proxy_configuration_rejects_winhttp_proxy():
    with pytest.raises(security.LivePathSecurityError, match="WinHTTP proxy"):
        security.assert_no_ambient_proxy_configuration(
            environment={},
            user_proxy_reader=lambda: {
                "proxy_enabled": False,
                "automatic_configuration": False,
                "automatic_detection": False,
            },
            winhttp_direct_reader=lambda: False,
        )
