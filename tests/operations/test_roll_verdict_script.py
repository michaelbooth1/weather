from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "roll_verdict.ps1"


def test_execution_tape_closure_is_required_only_while_armed_or_active() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '[string]$executionTask.State -ne "Disabled"' in text
    assert '"data\\snapshots\\.execution_tape_status.json.writer.lock"' in text
    assert 'Get-OptionalPropertyValue -InputObject $executionWorker -Name "state"' in text
    assert '$statusFiles += "data\\snapshots\\execution_tape_supervisor_status.json"' in text


def test_sparse_retained_closure_status_is_safe_under_inherited_strict_mode() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Get-OptionalPropertyValue" in text
    for name in ("state", "ensure_status", "reason"):
        assert f'Get-OptionalPropertyValue -InputObject $doc -Name "{name}"' in text
    assert 'Get-OptionalPropertyValue -InputObject $identity -Name "source_scope_files"' in text
    assert "$doc.state" not in text
    assert "$doc.ensure_status" not in text
    assert "$doc.reason" not in text
