"""Native PowerShell primitive contracts without production or Scheduler access."""

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="native PowerShell contract")
ROOT = Path(__file__).resolve().parents[2]


def test_actual_parent_freshness_gate_refuses_stale_future_and_wrong_boundary(tmp_path):
    script = tmp_path / "fixture.ps1"
    contract = str(ROOT / "scripts/ops/qualification_merge_contract.ps1").replace("'", "''")
    script.write_text("$ErrorActionPreference='Stop'\n. '" + contract + "'\n" + r'''
# Fixed native wall clock stays within the quiet window; the gate still uses
# DateTimeOffset.UtcNow for the actual five-second validation interval.
function Get-Date { return [datetime]::Today.AddHours(2) }
$context = [pscustomobject]@{ Last = [pscustomobject]@{ phase='before-stage'; data_final=[DateTimeOffset]::UtcNow.ToString('o') } }
Assert-WeatherQualificationMutationFresh -Context $context -Phase before-stage
foreach ($seconds in @(-6, 60)) {
    $context.Last.data_final = [DateTimeOffset]::UtcNow.AddSeconds($seconds).ToString('o')
    $refused = $false
    try { Assert-WeatherQualificationMutationFresh -Context $context -Phase before-stage } catch { $refused=$true }
    if (-not $refused) { throw 'Invalid freshness accepted' }
}
$context.Last.data_final = [DateTimeOffset]::UtcNow.ToString('o')
$refused = $false
try { Assert-WeatherQualificationMutationFresh -Context $context -Phase before-config } catch { $refused=$true }
if (-not $refused) { throw 'Another boundary borrowed the current-input proof' }
''', encoding="utf-8")
    exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, timeout=20)
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")


def test_all_modified_native_entrypoints_parse_without_execution(tmp_path):
    names = ("quiet_window_merge.ps1", "roll_verdict.ps1", "qualification_merge_contract.ps1")
    script = tmp_path / "parse.ps1"
    targets = ",".join("'" + str(ROOT / "scripts/ops" / name).replace("'", "''") + "'" for name in names)
    script.write_text("$ErrorActionPreference='Stop'\nforeach($path in @(" + targets + ")) {\n"
        "$tokens=$null; $failures=$null\n"
        "[void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$failures)\n"
        "if($failures.Count -gt 0) { throw ($failures | Out-String) }\n}\n", encoding="utf-8")
    exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, timeout=20)
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")
