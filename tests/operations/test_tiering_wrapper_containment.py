from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = (
    ROOT / "scripts/ops/clob_tiering_run.ps1",
    ROOT / "scripts/ops/clob_raw_tape_tiering_run.ps1",
)


def test_tiering_wrappers_own_bounded_child_tree_containment():
    for path in WRAPPERS:
        text = path.read_text(encoding="utf-8-sig")
        assert "[int]$MaxRuntimeSeconds" in text
        assert "New-WeatherKillOnCloseJob" in text
        assert "Start-WeatherProcessInJob" in text
        assert "ConvertTo-ScheduledTaskArgumentString" in text
        assert '"HARD_STOPPED"' in text
        assert "$job.Dispose()" in text
        assert "hard_stop_reached = $hardStopped" in text
        assert "task_history.jsonl" in text
        assert "Move-Item -LiteralPath $temporary" in text
        assert "Add-Content -LiteralPath $historyPath" in text
        assert "$localMinute -ge (9 * 60) -or $localMinute -lt 30" in text
        assert "outside the 00:30-09:00 heavy-work window" in text
