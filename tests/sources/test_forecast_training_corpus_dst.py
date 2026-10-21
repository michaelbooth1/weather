"""DST handling of provider hourly labels in PIT corpus staging and materialization.

Guards: docs/operations/PIT_FORECAST_TRAINING_CORPUS.md (Collector, DST): Open-Meteo returns one
scalar utc_offset_seconds per response, so a fixed-offset series across a fall-back must map by
UTC instant, never by naive label, and a true-local series must keep its 23/25-hour dates.
Fixture bytes only; no network.
"""

import hashlib
import json
import socket
from datetime import datetime, timedelta

import pytest

from weather.sources import forecast_training_corpus_fetch as fetch
from weather.sources.forecast_training_corpus import (
    PlanValidationError,
    StagingValidationError,
    build_plan,
    hours_in_local_date,
    load_plan,
    materialize_corpus,
    resolve_provider_times,
    resume_ledger,
    stage_response,
    verify_plan,
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


# --- Request padding (master GO 2026-10-21): the pad supplies the edge hour. ---

def _rehash(plan):
    body = {key: value for key, value in plan.items() if key != "plan_sha256"}
    plan["plan_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return plan


def _oct_dec_plan(tmp_path, *, pad, name="plan.json"):
    plan = build_plan(
        years=(2021,),
        target_year=2026,
        market_ids=("nyc",),
        season_start=(10, 1),
        season_end=(12, 31),
        cutoff_hours=(7, 20),
        planned_at_utc="2026-10-21T00:00:00+00:00",
        source_fields=("temperature_2m",),
        pad_request_days=pad,
    )
    path = tmp_path / name
    write_immutable_plan(path, plan)
    return plan, path


def test_default_plan_hash_is_unchanged_with_padding_off():
    kwargs = dict(
        years=(2021,),
        target_year=2026,
        market_ids=("toronto",),
        season_start=(5, 10),
        season_end=(5, 10),
        cutoff_hours=(10,),
        planned_at_utc="2026-01-01T00:00:00+00:00",
    )
    expected = "951b52dc6a543ce70726cc61d152bb9039f5b1f7c139f2e9c8cad5c0973ef5c7"
    assert build_plan(**kwargs)["plan_sha256"] == expected
    assert build_plan(**kwargs, pad_request_days=0)["plan_sha256"] == expected
    assert "request_padding" not in build_plan(**kwargs)


def test_padded_plan_records_pad_and_keeps_target_dates(tmp_path):
    plan, _path = _oct_dec_plan(tmp_path, pad=1)
    request = plan["requests"][0]
    assert plan["request_padding"]["enabled"] is True and plan["request_padding"]["days"] == 1
    assert request["request_pad_days"] == 1
    assert (request["params"]["start_date"], request["params"]["end_date"]) == ("2021-09-30", "2022-01-01")
    assert (request["window_start"], request["window_end"]) == ("2021-10-01", "2021-12-31")
    assert len(request["expected_local_dates"]) == 92
    assert plan["summary"]["expected_market_dates"] == 92
    with pytest.raises(PlanValidationError, match="target year"):
        build_plan(years=(2025,), target_year=2026, market_ids=("nyc",), season_start=(12, 1),
                   season_end=(12, 31), source_fields=("temperature_2m",), pad_request_days=1)
    with pytest.raises(PlanValidationError, match="between 0 and"):
        build_plan(years=(2021,), market_ids=("nyc",), pad_request_days=9)


def test_realistic_edt_labelled_oct_dec_series_passes_with_padding(tmp_path):
    plan, path = _oct_dec_plan(tmp_path, pad=1)
    request = plan["requests"][0]
    labels = _labels("2021-09-30T00:00", 94 * 24)  # 2021-09-30 .. 2022-01-01, EDT-labelled
    body = json.loads(_body(request, labels, utc_offset_seconds=-14400))
    field = request["variables"][0]["request_field"]
    body["hourly"][field][-1] = None  # a null in a pad-only row never fails a planned date
    stage_response(
        path,
        tmp_path / "staging",
        request["request_hash"],
        json.dumps(body).encode("utf-8"),
        http_status=200,
        retrieved_at_utc="2026-10-21T01:00:00Z",
        issue_evidence=fetch.issue_evidence_for(request),
    )
    manifest_path = materialize_corpus(path, tmp_path / "staging", tmp_path / "publish")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["request_padding"] == plan["request_padding"]
    hourly = _rows(manifest_path, "forecast_hourly.jsonl")
    by_date = {}
    for row in hourly:
        by_date.setdefault(row["target_date"], []).append(row)

    # (b) pad rows never reach the output or any completeness count.
    assert sorted(by_date) == request["expected_local_dates"]
    assert len(hourly) == 91 * 24 + 25
    assert manifest["row_counts"]["daily"] == 92 * 2
    assert manifest["row_counts"]["coverage"] == 92 * 2
    assert max(row["values"]["target_temp_native"] for row in hourly) == 2232.0
    assert min(row["values"]["target_temp_native"] for row in hourly) == 24.0

    oct1 = by_date["2021-10-01"]
    assert len(oct1) == 24
    assert oct1[0]["valid_time_utc"] == "2021-10-01T04:00:00+00:00"
    nov7 = by_date["2021-11-07"]
    assert len(nov7) == 25
    assert nov7[0]["valid_time_utc"] == "2021-11-07T04:00:00+00:00"
    assert nov7[-1]["valid_time_utc"] == "2021-11-08T04:00:00+00:00"
    assert nov7[-1]["valid_time_local"] == "2021-11-07T23:00:00-05:00"
    dec31 = by_date["2021-12-31"]
    assert len(dec31) == 24
    assert dec31[0]["valid_time_utc"] == "2021-12-31T05:00:00+00:00"
    assert dec31[-1]["valid_time_utc"] == "2022-01-01T04:00:00+00:00"
    assert dec31[-1]["values"]["target_temp_native"] == 2232.0  # label 2022-01-01T00:00
    daily = {(r["target_date"], r["cutoff_hour_local"]): r for r in _rows(manifest_path, "forecast_daily.jsonl")}
    assert daily[("2021-12-31", 7)]["forecast_high_native"] == 2232.0
    assert daily[("2021-12-31", 7)]["feature_as_of_utc"] == "2021-12-31T12:00:00+00:00"


def test_realistic_series_without_padding_still_fails_closed(tmp_path):
    plan, path = _oct_dec_plan(tmp_path, pad=0)
    request = plan["requests"][0]
    labels = _labels("2021-10-01T00:00", 92 * 24)
    with pytest.raises(StagingValidationError, match="incomplete_hourly_envelope:2021-12-31:23"):
        _stage(path, tmp_path / "staging", request, labels, utc_offset_seconds=-14400)


def test_pad_mismatch_is_refused_by_verify_and_resume(tmp_path):
    padded, padded_path = _oct_dec_plan(tmp_path, pad=1, name="padded.json")
    _plain, plain_path = _oct_dec_plan(tmp_path, pad=0, name="plain.json")

    dropped = _rehash({k: v for k, v in json.loads(json.dumps(padded)).items() if k != "request_padding"})
    with pytest.raises(PlanValidationError, match="request padding differs"):
        verify_plan(dropped)
    widened = json.loads(json.dumps(padded))
    widened["request_padding"]["days"] = 2
    with pytest.raises(PlanValidationError):
        verify_plan(_rehash(widened))
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(dropped), encoding="utf-8")
    with pytest.raises(PlanValidationError):
        resume_ledger(tampered_path, tmp_path / "staging")

    # Units staged for the unpadded plan never resume as complete for the padded one.
    request = load_plan(plain_path)["requests"][0]
    labels = _true_local(request["expected_local_dates"], repeat="2021-11-07T01:00")
    _stage(plain_path, tmp_path / "staging", request, labels)
    assert resume_ledger(plain_path, tmp_path / "staging")["complete_units"] == 1
    assert resume_ledger(padded_path, tmp_path / "staging")["complete_units"] == 0


def test_cli_plan_accepts_pad_request_days(tmp_path, capsys):
    from weather.sources.forecast_training_corpus import main as corpus_main

    out = tmp_path / "cli.json"
    corpus_main(["plan", "--out", str(out), "--years", "2021", "--markets", "nyc",
                 "--season-start", "10-01", "--season-end", "12-31", "--fields", "temperature_2m",
                 "--pad-request-days", "1", "--planned-at-utc", "2026-10-21T00:00:00+00:00"])
    capsys.readouterr()
    assert load_plan(out)["request_padding"]["days"] == 1


@pytest.mark.parametrize("style", ["aware_z", "naive_gmt_offset_zero"])
def test_utc_labelled_series_across_fall_back_maps_correctly(tmp_path, style):
    plan, path = _plan(tmp_path, (11, 6), (11, 8), year=2021)
    request = plan["requests"][0]
    first = datetime.fromisoformat("2021-11-06T04:00")  # local 2021-11-06 00:00 EDT
    hours = [first + timedelta(hours=index) for index in range(73)]
    if style == "aware_z":
        labels = [hour.strftime("%Y-%m-%dT%H:%MZ") for hour in hours]
        offset = None
    else:
        labels = [hour.strftime("%Y-%m-%dT%H:%M") for hour in hours]
        offset = 0
    _stage(path, tmp_path / "staging", request, labels, utc_offset_seconds=offset)
    manifest = materialize_corpus(path, tmp_path / "staging", tmp_path / "publish")
    hourly = _rows(manifest, "forecast_hourly.jsonl")
    counts = {d: sum(r["target_date"] == d for r in hourly) for d in ("2021-11-06", "2021-11-07", "2021-11-08")}
    assert counts == {"2021-11-06": 24, "2021-11-07": 25, "2021-11-08": 24}
    by_utc = {row["valid_time_utc"]: row for row in hourly}
    assert by_utc["2021-11-07T05:00:00+00:00"]["valid_time_local"] == "2021-11-07T01:00:00-04:00"
    assert by_utc["2021-11-07T06:00:00+00:00"]["valid_time_local"] == "2021-11-07T01:00:00-05:00"
    assert by_utc["2021-11-08T04:00:00+00:00"]["target_date"] == "2021-11-07"
    assert by_utc["2021-11-08T05:00:00+00:00"]["valid_time_local"] == "2021-11-08T00:00:00-05:00"
