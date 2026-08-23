from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "memory_commit_guard.ps1"
REGISTER = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "register_memory_commit_guard.ps1"
)


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


def test_memory_guard_warning_cannot_disable_the_critical_action_path():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    warning_start = text.index("if ($commitPercent -ge $WarnPercent)")
    act_start = text.index("if ($commitPercent -ge $ActPercent -and -not $terminationPerformed)")
    warning_block = text[warning_start:act_start]
    act_block = text[act_start:text.index("# ---- Orphan sweep")]
    assert '$status.memory_warning = $true' in warning_block
    assert '$status.action = "warned"' not in warning_block
    assert '$status.action -eq "none"' not in text
    assert "Test-GovernedWeatherProcess" in act_block
    assert "pytest|compileall|coverage|tox|nox" in act_block
    assert "Stop-VerifiedProcessTree $target.RootRow" in act_block


def test_memory_guard_attributes_and_reaps_codex_heavy_tool_trees():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    start = text.index("$agentRootNames =")
    end = text.index("# A scheduled PowerShell wrapper")
    block = text[start:end]
    assert '"codex.exe", "chatgpt.exe", "claude.exe"' in block
    assert "function Get-AgentToolRoot" in block
    assert "function Stop-VerifiedProcessTree" in block
    assert "ProcessId = {0}" in block
    assert "CreationDate -ne" in block
    assert "$minuteOfDay -ge 30.0" in block
    assert "$minuteOfDay -lt 540.0" in block
    assert "$MaxConcurrentAgentHeavyWorkloads" in block
    assert "Codex heavy workload is outside the 00:30-09:00 host window" in block
    assert "Test-GovernedWeatherProcess" in block
    assert "Get-ChildItem" in block
    assert "-Recurse" in block
    assert "daily_refresh|score_all" in block
    assert "Get-ProcessTreePrivateBytes" in block
    assert "$agentTreeBytes" in block
    assert "$MinKillPrivateBytes" in block
    assert "Stop-VerifiedProcessTree $target $allProcesses $reason $true" in block


def test_memory_guard_preserves_event_history_without_raw_commands():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    start = text.index("# Preserve incident-bearing samples")
    block = text[start:]
    assert "memory_commit_guard_history.jsonl" in text
    assert "agent_heavy_workload_count" in block
    assert "actions = @($guardActions)" in block
    assert "CommandLine" not in block
    assert "Move-Item -LiteralPath $statusTempPath" in block


def test_memory_guard_is_registered_every_minute():
    text = REGISTER.read_text(encoding="utf-8-sig")

    assert "[int]$IntervalMinutes = 1" in text
    assert "-RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)" in text
    assert "-MultipleInstances IgnoreNew" in text


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
