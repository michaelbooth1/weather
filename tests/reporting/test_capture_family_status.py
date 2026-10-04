import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.reporting.market import capture_family_status as fam


NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
GIB = 1024**3
ROOT = Path(__file__).resolve().parents[2]


def _config(tmp_path, **families):
    rows = {family_id: {"markets": {}, "day_ahead": [0], "max_conditions": limits.get("max_conditions", 600),
                        "reward_sweep_minutes": 15, "max_reward_reads_per_cycle": 40,
                        "stop_below_free_gib": limits.get("floor", 70)}
            for family_id, limits in (families or {"lowest_temperature": {}}).items()}
    path = tmp_path / "capture_families.json"
    path.write_text(json.dumps({"format_version": 1, "families": rows}), encoding="utf-8")
    return path


def _status(root, family_id, *, age=10, state="CAPTURING", free_gib=120.0, **extra):
    payload = {"schema_version": "x", "family": family_id, "state": state,
               "updated_at_utc": (NOW - timedelta(seconds=age)).isoformat(),
               "free_bytes": int(free_gib * GIB), "family_floor_bytes": 70 * GIB}
    if state != fam.FLOOR_STATE:
        payload.update(universe_size=312, missing_events=["a"], cycles=40, failed_cycles=0,
                       elapsed_seconds=600.0, http={"requests": 2400, "errors": 0})
    payload.update(extra)
    folder = root / family_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "status.json").write_text(json.dumps(payload), encoding="utf-8")


def _collect(tmp_path, config=None, *, task_states=None):
    return fam.collect(now=NOW, config=config or _config(tmp_path), root=tmp_path / "families",
                       task_states={"WeatherMakerEvidenceLowestTemperature": "Ready"} if task_states is None
                       else task_states)


def test_fresh_capturing_family_is_ok_with_conditions_disk_and_request_rate(tmp_path):
    _status(tmp_path / "families", "lowest_temperature")

    payload = _collect(tmp_path)

    row = payload["families"][0]
    assert payload["flags"] == [] and payload["warns"] == []
    assert row["severity"] == "OK" and row["state"] == "CAPTURING" and row["age_seconds"] == 10
    assert row["conditions"] == 312 and row["missing_events"] == 1 and row["max_conditions"] == 600
    assert row["free_gib"] == 120.0 and row["disk_floor"] == "above" and row["floor_gib"] == 70
    assert row["requests_per_minute"] == 240.0
    assert row["line"].startswith("lowest_temperature: CAPTURING (OK), age 10s, 312/600 conditions, "
                                  "free 120.0 GiB above 70 GiB floor, 240.0 req/min")


@pytest.mark.parametrize("age,state", [(181, "CAPTURING"), (30, "DEGRADED"), (30, "NO_ELIGIBLE_BANDS")])
def test_stale_or_non_capturing_family_flags_like_88a(tmp_path, age, state):
    _status(tmp_path / "families", "lowest_temperature", age=age, state=state, last_error="ValueError: x")

    payload = _collect(tmp_path)

    assert payload["warns"] == []
    assert len(payload["flags"]) == 1 and payload["flags"][0].startswith("CAPTURE_FAMILY lowest_temperature: ")
    assert payload["families"][0]["severity"] == "FLAG"


def test_disk_floor_stop_is_a_warn_with_reason_not_a_capture_failure(tmp_path):
    # The family's pre-journal floor status carries no cycles, http or universe.
    _status(tmp_path / "families", "lowest_temperature", state=fam.FLOOR_STATE, free_gib=65.25)

    payload = _collect(tmp_path)

    row = payload["families"][0]
    assert payload["flags"] == []
    assert payload["warns"] == ["CAPTURE_FAMILY lowest_temperature: stopped at its own 70 GiB free-space floor "
                                "(free 65.2 GiB); a planned brake protecting 88a, not a capture failure"]
    assert row["severity"] == "WARN" and row["disk_floor"] == "stopped"
    assert row["conditions"] is None and row["requests_per_minute"] is None
    assert "STOPPED at 70 GiB floor" in row["line"] and "- req/min" in row["line"]


def test_a_floor_stop_that_stopped_refreshing_is_still_a_freshness_flag(tmp_path):
    # Each one-minute retry rewrites the floor status; a stale one means the retries died.
    _status(tmp_path / "families", "lowest_temperature", state=fam.FLOOR_STATE, free_gib=65, age=600)

    payload = _collect(tmp_path)

    assert payload["warns"] == [] and "status stale (600s" in payload["flags"][0]


@pytest.mark.parametrize("contents", [None, "{not json", "[]", json.dumps({"state": "CAPTURING"})])
def test_missing_or_unreadable_status_of_a_registered_family_flags(tmp_path, contents):
    if contents is not None:
        folder = tmp_path / "families" / "lowest_temperature"
        folder.mkdir(parents=True)
        (folder / "status.json").write_text(contents, encoding="utf-8")

    payload = _collect(tmp_path)

    assert payload["families"][0]["severity"] == "FLAG" and payload["warns"] == []
    assert payload["flags"][0].startswith("CAPTURE_FAMILY lowest_temperature: ")


def test_oversized_status_is_refused_not_parsed(tmp_path):
    _status(tmp_path / "families", "lowest_temperature", padding="x" * fam.STATUS_MAX_BYTES)

    assert _collect(tmp_path)["flags"] == ["CAPTURE_FAMILY lowest_temperature: status exceeds byte bound"]


@pytest.mark.parametrize("task_state,reason", [("absent", "task not registered"), ("Disabled", "task disabled")])
def test_unregistered_or_disabled_family_is_informational_even_when_stale(tmp_path, task_state, reason):
    _status(tmp_path / "families", "lowest_temperature", age=86400, state="FAILED")

    payload = _collect(tmp_path, task_states={} if task_state == "absent"
                       else {"WeatherMakerEvidenceLowestTemperature": task_state})

    assert payload["flags"] == [] and payload["warns"] == []
    assert payload["families"][0]["severity"] == "INFO" and payload["families"][0]["reason"] == reason


def test_unregistered_family_without_status_is_quiet(tmp_path):
    payload = _collect(tmp_path, task_states={})

    row = payload["families"][0]
    assert payload["flags"] == [] and row["severity"] == "INFO" and row["state"] is None
    assert row["line"].startswith("lowest_temperature: - (INFO), age -, -/600 conditions")


def test_rows_are_generic_over_every_configured_family(tmp_path):
    config = _config(tmp_path, lowest_temperature={}, rain_total={"floor": 90, "max_conditions": 50})
    _status(tmp_path / "families", "lowest_temperature")
    _status(tmp_path / "families", "rain_total", state=fam.FLOOR_STATE, free_gib=80)

    payload = _collect(tmp_path, config, task_states={"WeatherMakerEvidenceLowestTemperature": "Running",
                                                      "WeatherMakerEvidenceRainTotal": "Ready"})

    assert [row["family"] for row in payload["families"]] == ["lowest_temperature", "rain_total"]
    assert [row["task_name"] for row in payload["families"]] == ["WeatherMakerEvidenceLowestTemperature",
                                                                 "WeatherMakerEvidenceRainTotal"]
    assert payload["flags"] == [] and "own 90 GiB free-space floor" in payload["warns"][0]


def test_cockpit_mode_without_scheduler_holds_a_written_status_to_the_alarms(tmp_path):
    _status(tmp_path / "families", "lowest_temperature", age=900)

    payload = fam.collect(now=NOW, config=_config(tmp_path), root=tmp_path / "families")

    assert payload["families"][0]["severity"] == "FLAG" and payload["families"][0]["task_state"] is None


def test_alarm_text_never_matches_the_watchdog_capture_or_capacity_classes(tmp_path):
    # health_watchdog.ps1 Get-FlagClass escalates these patterns to CRITICAL/HIGH capture or capacity.
    watchdog = (ROOT / "scripts" / "ops" / "health_watchdog.ps1").read_text(encoding="utf-8-sig")
    patterns = re.findall(r'if \(\$text -match "([^"]+)"\) \{ return "(capture|capacity|observability)" \}', watchdog)
    assert {klass for _, klass in patterns} == {"capture", "capacity", "observability"}
    _status(tmp_path / "families", "lowest_temperature", state=fam.FLOOR_STATE, free_gib=41)
    texts = _collect(tmp_path)["warns"]
    _status(tmp_path / "families", "lowest_temperature", age=900)
    texts += _collect(tmp_path)["flags"]
    assert len(texts) == 2
    for text in texts:
        assert not any(re.search(pattern, text, re.IGNORECASE) for pattern, _ in patterns), text


def test_registrar_default_task_name_matches_the_reader_convention():
    registrar = (ROOT / "scripts" / "ops" / "register_maker_evidence_family_capture.ps1").read_text(encoding="utf-8")
    assert '$TaskName = "WeatherMakerEvidence" +' in registrar
    assert fam.task_name("lowest_temperature") == "WeatherMakerEvidenceLowestTemperature"
    registry = json.loads((ROOT / "config" / "scheduled_tasks.json").read_text(encoding="utf-8"))
    names = {task["name"] for task in registry["tasks"]}
    for family in fam.configured_families():
        assert family["task_name"] in names


def test_cli_reports_task_states_and_never_crashes(tmp_path, capsys):
    _status(tmp_path / "families", "lowest_temperature", age=0)
    config = _config(tmp_path)

    assert fam.main(["--config", str(config), "--root", str(tmp_path / "families"),
                     "--task-state", "WeatherMakerEvidenceCapture=Ready",
                     "--task-state", "WeatherMakerEvidenceLowestTemperature=Running"]) == 0
    ok = json.loads(capsys.readouterr().out)
    assert ok["families"][0]["task_state"] == "Running"

    assert fam.main(["--config", str(tmp_path / "absent.json")]) == 0
    broken = json.loads(capsys.readouterr().out)
    assert broken["families"] == [] and broken["flags"][0].startswith("CAPTURE_FAMILY status unavailable: ")
