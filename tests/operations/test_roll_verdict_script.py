from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "roll_verdict.ps1"


def test_execution_tape_closure_is_required_only_while_armed_or_active() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '[string]$executionTask.State -ne "Disabled"' in text
    assert '"data\\snapshots\\.execution_tape_status.json.writer.lock"' in text
    assert '[string]$executionWorker.state -ne "STOPPED"' in text
    assert '$statusFiles += "data\\snapshots\\execution_tape_supervisor_status.json"' in text
