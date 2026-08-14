from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "bounded_execution_tape_probe.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_probe_is_exact_commit_and_quiet_window_bound() -> None:
    script = _text()

    assert '[ValidatePattern("^[0-9a-fA-F]{40}$")]' in script
    assert "production HEAD must equal origin/master before the probe" in script
    assert "merge-base --is-ancestor $RequiredAncestor $head" in script
    assert "probe must start inside the 01:00-04:00 quiet window" in script


def test_probe_owns_child_and_enforces_resource_bounds() -> None:
    script = _text()

    assert "windows_kill_on_close_job.ps1" in script
    assert "Start-WeatherProcessInJob" in script
    assert '@{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720 }' in script
    assert '@{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180 }' in script
    assert '@{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180 }' in script
    assert "working set $workingSetMB MB exceeds" in script
    assert "host commit $commit% exceeds abort ceiling" in script


def test_probe_requires_new_rows_connected_seed_set_and_clean_integrity() -> None:
    script = _text()

    assert '[string]$Status.state -ne "CONNECTED"' in script
    assert "$activeRows.Count -ne $expectedCount" in script
    assert '[string]$row.connection_state -ne "CONNECTED"' in script
    assert "connected_seed_set_proved" in script
    assert "evidence_integrity" not in script
    assert "bounded capture produced no new execution observations" in script
    assert 'foreach ($name in @("parse_rejections", "unrouted_trades", "ambiguous_routes"))' in script


def test_probe_requires_clean_stop_and_capture_survival() -> None:
    script = _text()

    assert '[string]$final.state -ne "STOPPED"' in script
    assert "capture worker health degraded during probe" in script
    assert "snapshot heartbeat did not advance during probe" in script


def test_probe_persists_latest_and_append_only_history() -> None:
    script = _text()

    assert "execution_tape_probe_last.json" in script
    assert "execution_tape_probe_history.jsonl" in script
    assert "Set-Content -LiteralPath $ReportPath" in script
    assert "Add-Content -LiteralPath $HistoryPath" in script
