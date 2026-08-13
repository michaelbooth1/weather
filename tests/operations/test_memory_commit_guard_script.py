from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "memory_commit_guard.ps1"


def test_memory_guard_warns_below_1_5_gib_with_top_working_sets():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "[long]$WarnFreePhysicalBytes = 1536MB" in text
    physical_start = text.index("if ($freeRamMB -lt $warnFreePhysicalMB)")
    commit_warning_start = text.index("if ($commitPercent -ge $WarnPercent)")
    physical_block = text[physical_start:commit_warning_start]
    assert "Sort-Object WorkingSet64 -Descending" in physical_block
    assert "top working set" in physical_block
    assert "$status.physical_warning = $true" in physical_block
    assert "Stop-Process" not in physical_block


def test_memory_guard_termination_stays_commit_gated_and_weather_modules_are_excluded():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    act_start = text.index('if ($commitPercent -ge $ActPercent -and $status.action -eq "none")')
    act_block = text[act_start:text.index("# ---- Orphan sweep")]
    assert 'if ($cmd -match "-m\\s+weather\\.") { return }' in act_block
    assert "Stop-Process -Id $target.Id" in act_block


def test_memory_guard_reaps_only_unowned_evidence_refresh_inside_protected_window():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    start = text.index('$evidenceTaskName = "WeatherEveningEvidenceRefresh"')
    end = text.index("if ($freeRamMB -lt $warnFreePhysicalMB)")
    block = text[start:end]
    assert "$localNow.Hour -ge 12 -and $localNow.Hour -lt 18" in block
    assert '[string]$evidenceTask.State -ne "Running"' in block
    assert "weather\\.operations\\.daily_refresh" in block
    assert "--scheduler-task-name" in block
    assert "$ageMinutes -lt 2" in block
    assert "Sort-Object PrivateBytes -Descending" in block
    assert "Stop-Process -Id $target.Id" in block
