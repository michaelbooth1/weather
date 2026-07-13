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

    act_start = text.index("if ($commitPercent -ge $ActPercent)")
    first_stop = text.index("Stop-Process")
    act_block = text[act_start:text.index("# ---- Orphan sweep")]
    assert first_stop > act_start
    assert 'if ($cmd -match "-m\\s+weather\\.") { return }' in act_block
    assert "Stop-Process -Id $target.Id" in act_block
