"""Pin of today's null last pre-cutoff temperature train/serve MISMATCH (item 344, EF §10ay).

Guards: item 344 / EF §10ay. The trainer builder (``feature_store.build_historical_feature_record``) keeps a null
temperature on the last row at or before the cutoff as a null ``current_temp``, while the serve helper
(``mg_serve_core.observations_at_cutoff``) and the replay helpers (``r0_ols_floor_challenger.observations_at_cutoff``,
reached by the B-bound ``mg2_p3d_n._observations``, and ``pooled_residual_model.scan_replay_n``) take the latest
NON-null temperature. History rate: 2 of 28,936 (market, date, hour) keys (nyc 2024-03-13 h13, san-francisco
2022-03-17 h13).

This file PINS the divergence; it is not parity. It is tests-only and edits no source. At the next retrain or model
change (master), the trainer adopts the serve semantics and these pins flip to assert agreement
(``docs/research/item344-null-temp-plan-2026-11-05/design.md``).
"""

import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from tests.host_guard import import_or_skip_on_capture_host
from weather.model import mg_serve_core
from weather.model.feature_store import build_historical_feature_record
from weather.reporting.scorecards.train_serve_feature_parity import compare_feature_records

TARGET = date(2024, 3, 13)
CUTOFF_HOUR = 13
TZ = ZoneInfo("America/New_York")

# (minute of day, temperature) per unit: the last row at or before 13:00 has a NULL temperature.
SERIES = {
    "F": [(420, 60.0), (720, 70.0), (773, 72.0), (780, None)],
    "C": [(420, 15.0), (720, 21.0), (773, 22.0), (780, None)],
}
LAST_NON_NULL = {"F": 72.0, "C": 22.0}


def _trainer_rows(unit):
    return [{"minute_of_day": minute, "temp_native": temp} for minute, temp in SERIES[unit]]


def _metar_rows(unit):
    rows = []
    for minute, temp in SERIES[unit]:
        stamp = datetime(TARGET.year, TARGET.month, TARGET.day, minute // 60, minute % 60, tzinfo=TZ)
        rows.append({"datetime": stamp.isoformat(), "temp_native": temp})
    return rows


def _trainer_record(unit):
    temps = [temp for _, temp in SERIES[unit] if temp is not None]
    return build_historical_feature_record(
        TARGET.isoformat(),
        _trainer_rows(unit),
        {"bucket": max(temps) + 3},
        CUTOFF_HOUR,
        forecast_high=max(temps) + 3,
        unit=unit,
    )


@pytest.mark.parametrize("unit", ["F", "C"])
def test_trainer_keeps_the_null_last_pre_cutoff_temperature(unit):
    record = _trainer_record(unit)
    assert record is not None
    assert record["current_temp"] is None  # MISMATCH pinned (item 344): serve and replay skip this row
    assert record["high_so_far"] == LAST_NON_NULL[unit]  # high_so_far already skips the null (feature_store :1234)


@pytest.mark.parametrize("unit", ["F", "C"])
def test_serve_helper_takes_the_latest_non_null_temperature(unit):
    current, high, n = mg_serve_core.observations_at_cutoff(_metar_rows(unit), TARGET, CUTOFF_HOUR, TZ)
    assert (current, high, n) == (LAST_NON_NULL[unit], LAST_NON_NULL[unit], 3)


@pytest.mark.parametrize("unit", ["F", "C"])
def test_replay_helper_takes_the_latest_non_null_temperature(unit):
    l3 = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")
    current, high, n = l3.observations_at_cutoff(_metar_rows(unit), TARGET, CUTOFF_HOUR, TZ)
    assert (current, high, n) == (LAST_NON_NULL[unit], LAST_NON_NULL[unit], 3)


def test_scan_replay_n_takes_the_latest_non_null_temperature(tmp_path):
    prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")
    l3 = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")
    captured = datetime(TARGET.year, TARGET.month, TARGET.day, CUTOFF_HOUR, 5, tzinfo=TZ)
    snapshot = {"captured_at_local": captured.isoformat(), "snapshot_id": "s-item344",
                "sources": {"metar": {"data": {"rows": _metar_rows("F")}}}}
    (tmp_path / "replay_inputs.jsonl").write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    def running_max(station, metar, **_kwargs):
        temps = [row["temp_native"] for row in metar["rows"] if row["temp_native"] is not None]
        return max(temps), None

    out = prm.scan_replay_n(tmp_path, "nyc", TARGET, TZ, {CUTOFF_HOUR}, "F", running_max, l3.observations_at_cutoff)
    assert out[CUTOFF_HOUR]["current_temp"] == LAST_NON_NULL["F"]
    assert out[CUTOFF_HOUR]["n_rows"] == 3


@pytest.mark.parametrize("unit", ["F", "C"])
def test_parity_gate_sees_the_null_last_row_when_fed_the_serve_helper(unit):
    """Parity-gate fixture: the gate's comparator, fed the trainer record and the serve helper's value on the same
    null-last-row case, reports the mismatch. The gate itself builds its training side with the trainer and its
    serving side from the model's WU surface, so it never feeds the serve helper (EF §10ay)."""
    current, _, _ = mg_serve_core.observations_at_cutoff(_metar_rows(unit), TARGET, CUTOFF_HOUR, TZ)
    case = {"case_id": "item344-null-last-pre-cutoff-temp", "kind": "unit_test", "market_id": "nyc",
            "market_unit": unit, "cutoff_at": datetime(2024, 3, 13, 17, 0, tzinfo=timezone.utc).isoformat()}
    meta = {"current_temp": {"source_id": "metar", "available_at": case["cutoff_at"], "provenance_state": "verified"}}
    findings, coverage = compare_feature_records(
        case=case,
        training_record={"current_temp": _trainer_record(unit)["current_temp"]},
        serving_record={"current_temp": current},
        training_metadata=meta,
        serving_metadata=meta,
        features=("current_temp",),
    )
    assert not coverage
    assert [(row["field"], row["dimension"]) for row in findings] == [("current_temp", "missingness")]
