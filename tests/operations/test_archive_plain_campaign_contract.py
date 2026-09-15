"""Native PowerShell contracts refuse altered archive scope and mutable evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
PS = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native PowerShell contract")


def config():
    value = {
        "schema_version": "plain_archive_campaign_config_v1",
        "campaign_id": "plain-20260914-test",
        "source_tip": "a" * 40, "workstation_source_tip": "b" * 40,
        "execution_host_id": "a" * 64, "backup_execution_host_id": "b" * 64,
        "known_hosts_sha256": "c" * 64, "initial_progress_sha256": "d" * 64,
        "production_root": "C:/fixture/production", "workstation_root": "C:/fixture/workstation",
        "remote_host": "192.168.1.106", "remote_user": "Fixture",
        "drive_remote_name": "fixture_drive", "drive_root_folder_id": "fixtureFolderId",
        "start_utc": "2026-09-14T04:30:00Z", "end_utc": "2026-09-14T08:42:00Z",
        "expires_at_utc": "2026-09-14T08:42:00Z",
        "approved_at_utc": "2026-09-13T00:00:00Z", "approved_by": "Fixture owner",
        "target_bytes": 100000000000, "initial_archive_headroom_bytes": 23622320128,
        "owner_approval": {"path": "C:/fixture/owner.json", "sha256": "2878ff1c2e673a539a74f1939a15682c9f624c7f54184ddee63dfb522fc34d7e"},
        "proposal": {"path": "C:/fixture/proposal.json", "sha256": "d47eec8ff7fbd500c720a273339729cb9f8f75eb84be615082d9d39e2b22b927"},
        "selection": {"path": "C:/fixture/selection.json", "sha256": "566e0fd15a0095c131068cc4ef3cf09e715ca570b1205286e6e6fd6927f607c9"},
        "plan": {"path": "C:/fixture/plan.json", "sha256": "2faae41470c42508a8639e98ec17ace7ecebc0b8715c09eaa92d33c0845251d3"},
        "existing_upload": {"path": "C:/fixture/upload.json", "sha256": "e" * 64},
        "capacity": {"source_root": "C:/fixture/capacity", "plan_path": "C:/fixture/capacity.json",
                     "result_root": "C:/fixture/capacity-result", "source_tip": "f" * 40, "plan_sha256": "f" * 64},
        "queue": [
            {"archive_id": f"p11k{n:05}", "chunk_id": f"chunk-{n:05}",
             "start_at": "reclaim" if i == 0 else "copy" if i == 1 else "stage"}
            for i, n in enumerate([85, 90, 86, 101, 127, 125, 104, 93, 113, 116, 129, 83, 94, 91, 50, 105, 117, 114, 102, 71])
        ],
    }
    for key in ("progress_path", "private_key", "known_hosts", "ssh_executable", "scp_executable",
                "workstation_python", "rclone_executable", "drive_config", "drive_secret"):
        value[key] = "C:/fixture/" + key
    return value


def run_ps(tmp_path, body, *args):
    script = tmp_path / "check.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n" + body, encoding="utf-8")
    return subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(script), *map(str, args)],
                          text=True, capture_output=True, timeout=20)


CONTRACT = r"""
. (Join-Path $args[0] 'scripts/ops/archive_plain_campaign_contract.ps1')
$c=Get-Content -LiteralPath $args[1] -Raw|ConvertFrom-Json
$null=Assert-WeatherPlainConfiguration $c
'VALID'
"""


def check_config(tmp_path, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return run_ps(tmp_path, CONTRACT, ROOT, path)


def test_approved_queue_and_existing_phase_resume(tmp_path):
    if datetime.now(timezone.utc) < datetime(2026, 9, 13, tzinfo=timezone.utc):
        pytest.skip("dated approval not yet issued")
    result = check_config(tmp_path, config())
    assert result.returncode == 0, result.stderr
    assert "VALID" in result.stdout


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "cold_archive_campaign_config_v0.1"),
    (("start_utc",), "2026-09-13T22:00:00Z"),
    (("end_utc",), "2026-09-14T09:00:00Z"),
    (("expires_at_utc",), "2026-09-15T08:42:00Z"),
    (("approved_at_utc",), "2099-01-01T00:00:00Z"),
    (("approved_at_utc",), "2026-09-10T00:00:00Z"),
    (("initial_archive_headroom_bytes",), 6 * 1024**3),
    (("target_bytes",), 200000000000),
    (("remote_host",), "example.org"),
    (("private_key",), "C:/fixture/../key"),
    (("remote_user",), "Fixture;whoami"),
    (("proposal", "sha256"), "0" * 64),
    (("plan", "sha256"), "0" * 64),
    (("selection", "sha256"), "0" * 64),
    (("owner_approval", "sha256"), "0" * 64),
    (("backup_execution_host_id",), "a" * 64),
    (("queue", 0, "start_at"), "stage"),
    (("queue", 1, "start_at"), "reclaim"),
    (("queue", 2, "archive_id"), "p11k00085"),
    (("queue", 2, "chunk_id"), "chunk-00087"),
    (("capacity", "plan_sha256"), ""),
])
def test_scope_or_authority_mutation_refused(tmp_path, path, value):
    altered = deepcopy(config())
    node = altered
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    result = check_config(tmp_path, altered)
    assert result.returncode != 0


def test_missing_queue_row_refused(tmp_path):
    altered = config()
    altered["queue"].pop()
    assert check_config(tmp_path, altered).returncode != 0


def test_metadata_hash_bounds_and_create_only(tmp_path):
    result = run_ps(tmp_path, r"""
. (Join-Path $args[0] 'scripts/ops/archive_plain_campaign_contract.ps1')
$path=Join-Path $args[1] 'proof.json'
$first=Write-WeatherPlainNew $path @{status='PASS'} 128
$again=Read-WeatherPlainMetadata $path $first.Sha256 128
if($again.Value.status -cne 'PASS'){throw 'Readback differs'}
$refused=0
try {$null=Write-WeatherPlainNew $path @{status='CHANGED'} 128}catch{$refused++}
try {$null=Read-WeatherPlainMetadata $path ('0'*64) 128}catch{$refused++}
try {$null=Read-WeatherPlainMetadata $path '' 1}catch{$refused++}
if($refused -ne 3){throw 'Mutable, mismatched, or oversized metadata accepted'}
if((Read-WeatherPlainMetadata $path $first.Sha256).Value.status -cne 'PASS'){throw 'Spent evidence was overwritten'}
'PASS'
""", ROOT, tmp_path)
    assert result.returncode == 0, result.stderr


def test_upload_cannot_substitute_different_bytes_or_stale_download(tmp_path):
    result = run_ps(tmp_path, r"""
. (Join-Path $args[0] 'scripts/ops/archive_plain_campaign_contract.ps1')
$c=@{backup_execution_host_id=('b'*64);drive_root_folder_id='fixtureFolderId'}
$stage=@{archive_sha256=('a'*64);archive_bytes=123}
$upload=@{status='PASS';payload_encryption='none';independent_download_verified=$true;originals_deleted=0;execution_host_id=('b'*64);bundle_sha256=('a'*64);bytes=123;drive=@{root_folder_id='fixtureFolderId'};attempt_id='p11k00085u2';completed_at_utc=[DateTimeOffset]::UtcNow.AddMinutes(-1).ToString('o')}
Assert-WeatherPlainUpload $c $stage $upload 'p11k00085'
$refused=0
$upload.bundle_sha256='c'*64
try{Assert-WeatherPlainUpload $c $stage $upload 'p11k00085'}catch{$refused++}
$upload.bundle_sha256='a'*64
$upload.completed_at_utc=[DateTimeOffset]::UtcNow.AddHours(-25).ToString('o')
try{Assert-WeatherPlainUpload $c $stage $upload 'p11k00085'}catch{$refused++}
$upload.completed_at_utc=[DateTimeOffset]::UtcNow.AddHours(1).ToString('o')
try{Assert-WeatherPlainUpload $c $stage $upload 'p11k00085'}catch{$refused++}
if($refused -ne 3){throw 'Upload provenance check failed'}
""", ROOT)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["archive_plain_campaign_contract.ps1", "archive_plain_campaign_worker.ps1",
                                 "archive_plain_campaign_run.ps1", "register_archive_plain_campaign.ps1"])
def test_native_powershell_parse(tmp_path, name):
    result = run_ps(tmp_path, r"""
$tokens=$null;$parseErrors=$null
$null=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$parseErrors)
if(@($parseErrors).Count){throw ($parseErrors|Out-String)}
""", ROOT / "scripts/ops" / name)
    assert result.returncode == 0, result.stderr

def test_immediate_config_retains_scope_and_requires_new_timing_authority(tmp_path):
    value = config()
    value.update(campaign_id="plain-20260913-test",
                 start_utc="2026-09-13T22:46:00Z",
                 end_utc="2026-09-14T04:30:00Z",
                 expires_at_utc="2026-09-14T04:30:00Z",
                 approved_at_utc="2026-09-13T22:45:43.134584Z")
    if datetime.now(timezone.utc) < datetime.fromisoformat(value["approved_at_utc"]):
        pytest.skip("owner timing correction not yet issued")
    result = check_config(tmp_path, value)
    assert result.returncode == 0, result.stderr
    for key, altered in (("approved_at_utc", "2026-09-13T22:00:00Z"),
                         ("end_utc", "2026-09-14T08:42:00Z"),
                         ("campaign_id", "plain-20260914-test")):
        assert check_config(tmp_path, {**value, key: altered}).returncode != 0



def capacity_config():
    value = config()
    value.update(
        campaign_id="plain-20260916-cap150", start_utc="2026-09-16T04:30:00Z",
        end_utc="2026-09-16T08:42:00Z", expires_at_utc="2026-09-16T08:42:00Z",
        approved_at_utc="2026-09-15T23:17:20.425091Z", target_bytes=150000000000,
        initial_archive_headroom_bytes=30*1024**3, initial_progress_sha256="0"*64,
        execution_host_id="6a085bc0e2017a1a619eead39f9daa9ffe0822b9add353d94cf2c06acb8889a7",
        backup_execution_host_id="a740ee7dc03165b0c88094f8b313aa6676f0984b30737ec5bcd9f723709fe5dc",
        drive_root_folder_id="1-HZZb9QuRB1AlK9UYSWB_JdeUabhza9H",
    )
    bindings = {
        "owner_approval": "0bae773d078f4ad2a0ee3f537a75fb8e5b6a0253da74476f4452f4b09c12d66e",
        "proposal": "5d47113237e50854b4c73cdc089b19e56b5ed8402c5d42622d7f39201c0d9c4c",
        "plan": "bc30c32fc0403fd3f836501cbbe454aa791e025a29ef796b5ee8737f09043027",
        "selection": "ce4d38697e1d24e7ba66a53cb41f407f074bfdd58fcf7118b926d9cd2b31f214",
        "current_owner_approval": "2eb7309a03b9b5383f1bd848a43b9a268f6ffd390c236b3a27361f58d445cef5",
        "disk_exception": "e"*64,
    }
    for key, digest in bindings.items():
        value[key] = {"path": "C:/fixture/"+key+".json", "sha256": digest}
    value["queue"] = [
        {"archive_id": f"p16m{n:05}", "chunk_id": f"chunk-{n:05}", "start_at": "stage"}
        for n in range(56)
    ]
    return value


def test_capacity_current_approval_exact_selection_and_window(tmp_path):
    if datetime.now(timezone.utc) < datetime(2026,9,15,23,18,tzinfo=timezone.utc):
        pytest.skip("dated owner approval not yet issued")
    result = check_config(tmp_path, capacity_config())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path,value", [
    (("current_owner_approval","sha256"), "0"*64),
    (("plan","sha256"), "0"*64), (("selection","sha256"), "0"*64),
    (("drive_root_folder_id",), "differentPrivateFolder"),
    (("execution_host_id",), "e"*64),
    (("end_utc",), "2026-09-16T09:00:00Z"),
    (("target_bytes",), 200000000000),
    (("initial_archive_headroom_bytes",), 25*1024**3),
    (("queue",0,"start_at"), "reclaim"),
    (("queue",0,"archive_id"), "p11m00000"),
    (("queue",0,"chunk_id"), "chunk-00056"),
    (("initial_progress_sha256",), "a"*64),
])
def test_capacity_changed_scope_refused(tmp_path, path, value):
    altered = capacity_config()
    node = altered
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    assert check_config(tmp_path, altered).returncode != 0


def test_capacity_duplicate_or_missing_chunk_refused(tmp_path):
    value = capacity_config()
    value["queue"][1] = value["queue"][0]
    assert check_config(tmp_path, value).returncode != 0
    value = capacity_config()
    value["queue"].pop()
    assert check_config(tmp_path, value).returncode != 0
