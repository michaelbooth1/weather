from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "staleness_sweep.ps1"


def test_historical_operations_evidence_is_not_reported_as_unreachable_canonical_docs():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$historicalUnindexedNames" in text
    assert '"OVERNIGHT_BRIEFINGS.md"' in text
    assert "(?:19|20)\\d{2}[-_]\\d{2}[-_]\\d{2}" in text


def test_state_of_play_ranges_cover_individual_commission_references():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Test-StateOfPlayMissionReference" in text
    assert "[^0-9\\r\\n]{1,8}" in text
    assert "Windows PowerShell 5.1" in text
    assert "Test-StateOfPlayMissionReference $sopText $short" in text


def test_unapproved_remote_branches_do_not_imply_an_armed_merge_queue():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Add-Finding "git/no_merge_trigger"' not in text
    assert "branch -r --no-merged origin/master" not in text


def test_execution_tape_closure_is_required_only_while_armed_or_active():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '[string]$executionTask.State -ne "Disabled"' in text
    assert '"data\\snapshots\\.execution_tape_status.json.writer.lock"' in text
    assert '[string]$executionWorker.state -ne "STOPPED"' in text
    assert '$closureFiles["execution-tape"]' in text
