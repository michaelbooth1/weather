"""DST handling of provider hourly labels in PIT corpus staging and materialization.

Guards: docs/operations/PIT_FORECAST_TRAINING_CORPUS.md (Collector, DST): Open-Meteo returns one
scalar utc_offset_seconds per response, so a fixed-offset series across a fall-back must map by
UTC instant, never by naive label, and a true-local series must keep its 23/25-hour dates.
Fixture bytes only; no network.
"""

import json
import socket
from datetime import datetime, timedelta

import pytest

from weather.sources import forecast_training_corpus_fetch as fetch
from weather.sources.forecast_training_corpus import (
    StagingValidationError,
    build_plan,
    hours_in_local_date,
    materialize_corpus,
    resolve_provider_times,
    stage_response,
    write_immutable_plan,
)


@pytest.fixture(autouse=True)
def _no_real_sockets(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("a real socket was opened in a fixture-only test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _plan(tmp_path, start, end, *, year):
    plan = build_plan(
        years=(year,),
        target_year=2026,
        market_ids=("nyc",),
        season_start=start,
        season_end=end,
        cutoff_hours=(7, 20),
        planned_at_utc="2026-10-21T00:00:00+00:00",
        source_fields=("temperature_2m",),
    )
    path = tmp_path / "plan.json"
    write_immutable_plan(path, plan)
    return plan, path


def _labels(start, count):
    first = datetime.fromisoformat(start)
    return [(first + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M") for index in range(count)]


def _true_local(days, *, repeat=None, skip=None):
    labels = []
    for day in days:
        for hour in range(24):
            label = f"{day}T{hour:02d}:00"
            if label == skip:
                continue
            labels.append(label)
            if label == repeat:
                labels.append(label)
    return labels


def _body(request, labels, *, utc_offset_seconds=None):
    field = request["variables"][0]["request_field"]
    payload = {
        "timezone": request["source_timezone"],
        "hourly": {"time": labels, field: [float(index) for index in range(len(labels))]},
        "hourly_units": {field: "°F"},
    }
    if utc_offset_seconds is not None:
        payload["utc_offset_seconds"] = utc_offset_seconds
    return json.dumps(payload).encode("utf-8")


def _stage(path, staging, request, labels, **kwargs):
    return stage_response(
        path,
        staging,
        request["request_hash"],
        _body(request, labels, **kwargs),
        http_status=200,
        retrieved_at_utc="2026-10-21T01:00:00Z",
        issue_evidence=fetch.issue_evidence_for(request),
    )


def _rows(manifest_path, name):
    return [
        json.loads(line)
        for line in (manifest_path.parent / name).read_text(encoding="utf-8").splitlines()
    ]


def test_hours_in_local_date_counts_real_hours():
    assert hours_in_local_date("2021-11-07", "America/New_York") == 25
    assert hours_in_local_date("2022-03-13", "America/New_York") == 23
    assert hours_in_local_date("2021-11-08", "America/New_York") == 24


def test_fixed_offset_series_across_fall_back_maps_by_utc_instant(tmp_path):
    plan, path = _plan(tmp_path, (11, 6), (11, 8), year=2021)
    request = plan["requests"][0]
    # One EDT offset for the whole series, as the provider sends it; 73 labels
    # cover the three real local dates (24 + 25 + 24 hours).
    labels = _labels("2021-11-06T00:00", 73)
    _stage(path, tmp_path / "staging", request, labels, utc_offset_seconds=-14400)

    manifest = materialize_corpus(path, tmp_path / "staging", tmp_path / "publish")
    hourly = _rows(manifest, "forecast_hourly.jsonl")
    by_utc = {row["valid_time_utc"]: row for row in hourly}
    assert [sum(r["target_date"] == d for r in hourly) for d in ("2021-11-06", "2021-11-07", "2021-11-08")] == [24, 25, 24]
    # Before the transition the label is the local hour.
    assert by_utc["2021-11-07T05:00:00+00:00"]["valid_time_local"] == "2021-11-07T01:00:00-04:00"
    # After it, label 06:00 (EDT-based) is 10:00Z, which is 05:00 EST: no silent 1 h shift.
    assert labels[30] == "2021-11-07T06:00"
    assert by_utc["2021-11-07T10:00:00+00:00"]["values"]["target_temp_native"] == 30.0
    assert by_utc["2021-11-07T10:00:00+00:00"]["valid_time_local"] == "2021-11-07T05:00:00-05:00"
    # Label 2021-11-08T00:00 belongs to local 2021-11-07 23:00 EST.
    assert by_utc["2021-11-08T04:00:00+00:00"]["target_date"] == "2021-11-07"
    daily = {(r["target_date"], r["cutoff_hour_local"]): r for r in _rows(manifest, "forecast_daily.jsonl")}
    assert daily[("2021-11-07", 7)]["forecast_high_native"] == 48.0
    assert daily[("2021-11-08", 20)]["forecast_high_native"] == 72.0
    assert daily[("2021-11-08", 7)]["feature_as_of_utc"] == "2021-11-08T12:00:00+00:00"


def test_fixed_offset_series_missing_a_real_hour_fails_closed(tmp_path):
    plan, path = _plan(tmp_path, (11, 6), (11, 8), year=2021)
    request = plan["requests"][0]
    # The provider's 72 labels end at 03:00Z: local 2021-11-08 23:00 EST is absent.
    labels = _labels("2021-11-06T00:00", 72)
    with pytest.raises(StagingValidationError, match="incomplete_hourly_envelope:2021-11-08:23"):
        _stage(path, tmp_path / "staging", request, labels, utc_offset_seconds=-14400)


@pytest.mark.parametrize("offset", [None, -14400])
def test_true_local_labels_with_a_25_hour_fall_back_date_pass(tmp_path, offset):
    plan, path = _plan(tmp_path, (11, 6), (11, 8), year=2021)
    request = plan["requests"][0]
    labels = _true_local(
        ("2021-11-06", "2021-11-07", "2021-11-08"), repeat="2021-11-07T01:00"
    )
    assert len(labels) == 73
    _stage(path, tmp_path / "staging", request, labels, utc_offset_seconds=offset)
    manifest = materialize_corpus(path, tmp_path / "staging", tmp_path / "publish")
    hourly = _rows(manifest, "forecast_hourly.jsonl")
    nov7 = [r for r in hourly if r["target_date"] == "2021-11-07"]
    assert len(nov7) == 25
    assert [r["valid_time_utc"] for r in nov7 if r["valid_time_local"].startswith("2021-11-07T01:00")] == [
        "2021-11-07T05:00:00+00:00",
        "2021-11-07T06:00:00+00:00",
    ]
    assert nov7[-1]["valid_time_utc"] == "2021-11-08T04:00:00+00:00"


def test_true_local_spring_forward_23_hour_date_passes(tmp_path):
    plan, path = _plan(tmp_path, (3, 12), (3, 14), year=2022)
    request = plan["requests"][0]
    labels = _true_local(("2022-03-12", "2022-03-13", "2022-03-14"), skip="2022-03-13T02:00")
    _stage(path, tmp_path / "staging", request, labels)
    manifest = materialize_corpus(path, tmp_path / "staging", tmp_path / "publish")
    hourly = _rows(manifest, "forecast_hourly.jsonl")
    mar13 = [r for r in hourly if r["target_date"] == "2022-03-13"]
    assert len(mar13) == 23
    assert mar13[2]["valid_time_local"] == "2022-03-13T03:00:00-04:00"
    assert mar13[2]["valid_time_utc"] == "2022-03-13T07:00:00+00:00"


def test_bad_hourly_labels_fail_closed(tmp_path):
    plan, path = _plan(tmp_path, (3, 12), (3, 14), year=2022)
    request = plan["requests"][0]
    days = ("2022-03-12", "2022-03-13", "2022-03-14")
    staging = tmp_path / "staging"
    with pytest.raises(StagingValidationError, match="nonexistent_local_time:2022-03-13T02:00"):
        _stage(path, staging, request, _true_local(days))
    with pytest.raises(StagingValidationError, match="duplicate_hourly_label:2022-03-12T10:00"):
        _stage(path, staging, request, _true_local(days, repeat="2022-03-12T10:00", skip="2022-03-13T02:00"))
    with pytest.raises(StagingValidationError, match="incomplete_hourly_envelope:2022-03-14:23"):
        _stage(
            path,
            staging,
            request,
            [x for x in _true_local(days, skip="2022-03-13T02:00") if x != "2022-03-14T05:00"],
        )
    with pytest.raises(StagingValidationError, match="invalid_utc_offset_seconds"):
        _stage(path, staging, request, _true_local(days, skip="2022-03-13T02:00"), utc_offset_seconds="x")


def test_resolve_provider_times_modes():
    instants, mode, errors = resolve_provider_times(
        ["2021-11-07T01:00", "2021-11-07T02:00"], "America/New_York", -14400
    )
    assert mode == "fixed_offset" and errors == []
    assert [i.isoformat() for i in instants] == ["2021-11-07T01:00:00-04:00", "2021-11-07T01:00:00-05:00"]
    _i, mode, _e = resolve_provider_times(
        ["2021-11-07T01:00", "2021-11-07T01:00"], "America/New_York", -14400
    )
    assert mode == "true_local"
