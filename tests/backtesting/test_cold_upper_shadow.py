from types import SimpleNamespace

import pytest

from weather.backtesting.cold_upper_shadow import evaluate_cold_upper_shadow


def fixture(hour=18):
    now = f"2025-01-05T{hour:02d}:00:00Z"
    captured_current = f"2025-01-05T{hour - 1:02d}:52:00Z"
    identity = dict(market="cold-test", station="KZZZ", unit="F", family="highest", target_date="2025-01-05", as_of=now)
    provenance = dict(capture_sha256="1" * 64, model_sha256="2" * 64)
    spec = SimpleNamespace(slug="cold-test", station_id="KZZZ", market_unit="F", settlement_kind="metar_routine",
                           timezone="UTC", families=("highest", "lowest"))
    serving = SimpleNamespace(icao="KZZZ", display_unit="F", timezone="UTC", scale_delta=lambda c: c * 9 / 5)
    # -5 C = 23 F; -8 C = 17.6 F. The latest routine comes eight minutes before capture.
    reports = [
        dict(raw="METAR KZZZ 051352Z M05/M10", receipt_time="2025-01-05T13:55:00Z"),
        dict(raw=f"METAR KZZZ 05{hour - 1:02d}52Z M08/M10", receipt_time=f"2025-01-05T{hour - 1:02d}:57:00Z"),
        dict(raw="SPECI KZZZ 051358Z M02/M10", receipt_time="2025-01-05T14:00:00Z"),
        dict(raw="METAR COR KZZZ 051352Z M02/M10", receipt_time="2025-01-05T23:00:00Z"),
    ]
    floor = dict(**identity, event_id="cold-test-event", incumbent_bound=23,
                 prior=dict(**identity, **provenance, stage="input_to_apply_lockin_observed_floor", mass={"23": 1.0}),
                 rule=dict(**identity, basis="dated_event", effective_from="2025-01-01",
                           recorded_at="2024-12-31T22:00:00Z", sha256="3" * 64),
                 evidence=dict(source="awc_raw_metar", station="KZZZ", complete=True, reports=reports,
                               through=now, capture_sha256="4" * 64, **{"from": "2025-01-05T00:00:00Z"}))
    stage = dict(**identity, **provenance, event_id=floor["event_id"], stage="input_to_apply_late_day_lockin",
                 mass={"23": .5, "24": .25, "25": .25, "26": 0}, wu_history_state="empty_at_effective_cutoff",
                 incumbent_anchor=None, incumbent_lockin_strength=0, official_current_stale=False,
                 selected_current_source="metar", current_native=17.6, current_observation_time=captured_current)
    return floor, stage, spec, serving


def test_evening_shaper_changes_probabilities_with_same_positive_support():
    result = evaluate_cold_upper_shadow(*fixture())
    assert result["status"] == "projected" and result["unchanged_hard_bound"] == 23
    assert result["current_native"] == pytest.approx(17.6) and result["high_native"] == 23
    assert result["candidate"][23] > .5 and 0 < result["candidate"][25] < .25
    assert {k for k, p in result["candidate"].items() if p > 0} == {23, 24, 25}
    assert sum(result["candidate"].values()) == pytest.approx(1)
    assert result["total_variation"] == pytest.approx(result["candidate"][23] - .5)


@pytest.mark.parametrize("field,value", [
    ("wu_history_state", "unknown"), ("wu_history_state", "present"), ("incumbent_anchor", 23),
    ("incumbent_lockin_strength", .3), ("selected_current_source", "wu"), ("official_current_stale", True),
    ("current_native", 10), ("current_observation_time", "2025-01-05T17:51:00Z"),
])
def test_missing_or_competing_context_preserves_incumbent(field, value):
    floor, stage, spec, serving = fixture()
    stage[field] = value
    result = evaluate_cold_upper_shadow(floor, stage, spec, serving)
    assert result["status"] == "unchanged" and result["candidate"] == result["incumbent"]


@pytest.mark.parametrize("case", ["daytime", "different_station", "floor_still_missing", "late_receipt", "stale",
                                  "incomplete", "same_time_conflict", "wrong_station_current", "unknown_clock"])
def test_ineligible_source_or_hour_preserves_support(case):
    floor, stage, spec, serving = fixture(15 if case == "daytime" else 18)
    if case == "different_station":
        serving.icao = "KYYY"
    elif case == "floor_still_missing":
        floor["incumbent_bound"] = 19
    elif case == "late_receipt":
        floor["evidence"]["reports"][1]["receipt_time"] = "2025-01-05T18:02:00Z"
    elif case == "stale":
        floor["evidence"]["reports"][1] = dict(raw="METAR KZZZ 051500Z M08/M10", receipt_time="2025-01-05T15:05:00Z")
    elif case == "incomplete":
        floor["evidence"]["complete"] = False
    elif case == "same_time_conflict":
        floor["evidence"]["reports"].append(dict(raw="METAR KZZZ 051752Z M06/M10", receipt_time="2025-01-05T17:57:00Z"))
    elif case == "wrong_station_current":
        floor["evidence"]["reports"][1]["raw"] = "METAR KYYY 051752Z M08/M10"
    elif case == "unknown_clock":
        floor["evidence"]["reports"][1]["receipt_time"] = None
    result = evaluate_cold_upper_shadow(floor, stage, spec, serving)
    assert result["status"] == "unchanged" and result["total_variation"] == 0
    assert result["candidate"] == result["incumbent"]


@pytest.mark.parametrize("key,value", [("stage", "p_served"), ("capture_sha256", "5" * 64),
                                      ("event_id", "other"), ("model_sha256", "9" * 64)])
def test_mismatched_stage_cannot_substitute_for_captured_upper_prior(key, value):
    floor, stage, spec, serving = fixture()
    stage[key] = value
    with pytest.raises(ValueError, match="both stages"):
        evaluate_cold_upper_shadow(floor, stage, spec, serving)
