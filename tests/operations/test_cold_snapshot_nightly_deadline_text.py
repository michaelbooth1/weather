"""The 91a nightly cold-snapshot entrypoint keeps its real 09:00 backstop deadline (text-only).

Guards: docs/operations/cold-snapshot-compression.md and HOST_LOAD_POLICY's 06:50-09:00 nightly window
(owner 2026-10-05). test_cold_snapshot_nightly_schedule.run_entry substitutes the deadline line to
defuse its date time bomb (27e67f6e6), so this separate test asserts that the production script itself
still builds the deadline from the local date at 09:00 America/Toronto and that the wait loop compares
it with the real clock.
"""

from __future__ import annotations

from weather.paths import repo_path

SCRIPT = repo_path("scripts", "ops", "cold_snapshot_nightly_run.ps1")

DEADLINE_LINE = "$deadline = [TimeZoneInfo]::ConvertTimeToUtc($now.Date.AddMinutes($windowEndMinute), $zone)"


def _lines() -> list[str]:
    return [line.strip() for line in SCRIPT.read_text(encoding="utf-8-sig").splitlines()]


def test_production_script_holds_the_real_0900_deadline_line() -> None:
    lines = _lines()
    assert lines.count(DEADLINE_LINE) == 1
    assert lines.count("$windowEndMinute = 9 * 60") == 1
    assert sum(1 for line in lines if line.startswith("$windowEndMinute =")) == 1
    assert sum(1 for line in lines if line.startswith("$deadline =")) == 1


def test_production_script_anchors_the_deadline_to_toronto_and_the_real_clock() -> None:
    lines = _lines()
    assert lines.count("$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')") == 1
    assert lines.count("$now = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)") == 1
    loop = [line for line in lines if line.startswith("while (") and "$deadline" in line]
    assert loop == ["while (-not $child.HasExited -and [DateTime]::UtcNow -lt $deadline) {"]
