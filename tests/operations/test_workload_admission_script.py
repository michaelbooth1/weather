from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LEASE_SCRIPT = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"
WRAPPERS = (
    "training_window.ps1",
    "quiet_window_merge.ps1",
    "bounded_worktree_test_suite.ps1",
    "bounded_execution_tape_probe.ps1",
    "clob_tiering_run.ps1",
    "clob_raw_tape_tiering_run.ps1",
)


def test_every_heavy_wrapper_uses_the_shared_lease() -> None:
    for name in WRAPPERS:
        text = (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "workload_admission.ps1" in text, name
        assert "Enter-WeatherHeavyWorkloadLease" in text, name
        assert "Exit-WeatherHeavyWorkloadLease" in text, name


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows lease")
def test_lease_is_exclusive_and_recovers_when_owner_exits(tmp_path: Path) -> None:
    holder = tmp_path / "holder.ps1"
    holder.write_text(
        f". '{LEASE_SCRIPT}'\n"
        f"$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{tmp_path}' -Workload holder\n"
        "if ($null -eq $lease) { Write-Output 'BLOCKED'; exit 3 }\n"
        "Write-Output 'ACQUIRED'\n"
        "Start-Sleep -Seconds 2\n"
        "Exit-WeatherHeavyWorkloadLease -Lease $lease\n",
        encoding="utf-8",
    )
    contender = tmp_path / "contender.ps1"
    contender.write_text(
        f". '{LEASE_SCRIPT}'\n"
        f"$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{tmp_path}' -Workload contender\n"
        "if ($null -eq $lease) { Write-Output 'BLOCKED'; exit 3 }\n"
        "Write-Output 'ACQUIRED'\n"
        "Exit-WeatherHeavyWorkloadLease -Lease $lease\n",
        encoding="utf-8",
    )

    owner = subprocess.Popen(
        ["powershell", "-NoProfile", "-File", str(holder)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert owner.stdout is not None
    assert owner.stdout.readline().strip() == "ACQUIRED"
    blocked = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(contender)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 3
    assert blocked.stdout.strip() == "BLOCKED"
    assert owner.wait(timeout=10) == 0

    recovered = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(contender)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert recovered.returncode == 0
    assert recovered.stdout.strip() == "ACQUIRED"


def test_forced_tiering_cannot_bypass_protected_host_window() -> None:
    for name in ("clob_tiering_run.ps1", "clob_raw_tape_tiering_run.ps1"):
        text = (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "$localMinute -ge (12 * 60) -or $localMinute -lt 30" in text
        assert "-Forced cannot bypass host policy" in text
