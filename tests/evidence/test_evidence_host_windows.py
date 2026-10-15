"""PL-6 evidence host on Windows: a real over-cap child is killed by its Job, and the registrar arms nothing.

Guards: docs/operations/EVIDENCE_HOST.md (DLv2 plan S4 verify row "kill receipt for a child exceeding its
cap": a real child inside the kill-on-close Job with a hard commit cap allocates past the cap, dies, and
leaves an evidence_kill_receipt_v1; WeatherEvidenceHost registrar contract: S4U/Limited, idle priority,
IgnoreNew 1-minute respawn, ShouldProcess before registration, executed only with -WhatIf on a fake root).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from weather.evidence.host import KILL_RECEIPT_SCHEMA, run_kill_receipt_proof

ROOT = Path(__file__).resolve().parents[2]
REGISTRAR = ROOT / "scripts" / "ops" / "register_evidence_host.ps1"
WINDOWS_POWERSHELL = shutil.which("powershell.exe")
WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Job-object containment is Windows-only")
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None, reason="requires Windows PowerShell"
)
# Never a real task name: the registrar runs only under -WhatIf here.
TEST_TASK_NAME = "WeatherEvidenceHostPytestWhatIfOnly"


@WINDOWS_ONLY
@pytest.mark.spawns
def test_a_child_past_its_commit_cap_is_killed_and_leaves_a_receipt(tmp_path):
    proof = run_kill_receipt_proof(tmp_path, cap_bytes=96 * 1024**2)
    assert proof["killed"], proof
    receipt = json.loads(Path(proof["receipt"]).read_text(encoding="utf-8"))
    assert receipt["schema_version"] == KILL_RECEIPT_SCHEMA and receipt["deliberate"] is True
    assert receipt["cap_bytes"] == 96 * 1024**2 and receipt["returncode"] != 0
    assert receipt["resource_limit_exceeded"] or receipt["memory_error_in_stderr"]


def test_registrar_contract_is_idle_priority_respawn_only_and_whatif_safe():
    text = REGISTRAR.read_text(encoding="utf-8")
    assert "'-m weather.evidence.host --config \"{0}\" run'" in text
    assert '$TaskName = "WeatherEvidenceHost"' in text and r"venv\Scripts\pythonw.exe" in text
    assert "-MultipleInstances IgnoreNew" in text and "-Priority 10" in text
    assert "-LogonType S4U -RunLevel Limited" in text and "-RepetitionInterval (New-TimeSpan -Minutes 1)" in text
    assert text.index("$PSCmdlet.ShouldProcess(") < text.index("Register-ScheduledTask ")
    assert text.isascii()


def _run_ps1(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [WINDOWS_POWERSHELL or "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(REGISTRAR), *args],
        capture_output=True, text=True, timeout=180, check=False, cwd=str(cwd),
    )


def _fake_root(tmp_path: Path, mutate=None) -> Path:
    root = tmp_path / "repo"
    (root / "venv" / "Scripts").mkdir(parents=True)
    (root / "venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
    config = json.loads((ROOT / "config" / "evidence_host.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(config)
    (root / "config").mkdir()
    (root / "config" / "evidence_host.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _fingerprint(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob("*")) if p.is_file()}


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_registrar_whatif_validates_the_config_and_registers_nothing(tmp_path):
    root = _fake_root(tmp_path)
    before = _fingerprint(tmp_path)
    result = _run_ps1("-RepoRoot", str(root), "-TaskName", TEST_TASK_NAME, "-WhatIf", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "What if" in result.stdout and TEST_TASK_NAME in result.stdout, result.stdout
    assert "Registered" not in result.stdout
    assert _fingerprint(tmp_path) == before


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_registrar_refuses_a_parent_cap_above_64_mib(tmp_path):
    root = _fake_root(tmp_path, lambda c: c["host"].update(parent_ram_cap_mib=65))
    result = _run_ps1("-RepoRoot", str(root), "-TaskName", TEST_TASK_NAME, "-WhatIf", cwd=tmp_path)
    assert result.returncode != 0 and "parent cap must be 1-64 MiB" in result.stdout + result.stderr
    assert "What if" not in result.stdout
