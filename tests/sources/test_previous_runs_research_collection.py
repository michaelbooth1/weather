from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.sources.previous_runs_research_collection import (
    CSV_COLUMNS,
    ENDPOINT,
    FIELDS,
    HISTORICAL_AVAILABILITY,
    ISSUE_TIME_BASIS,
    LEADS,
    SOURCE,
    RetainedArtifactError,
    CollectionError,
    TransportFailure,
    TransportResponse,
    collect_unit,
    finalize_collection,
    load_bound_plan,
    payload_sha256,
    run_collection,
    self_hash,
    verify_final,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "docs"
    / "roadmap"
    / "previous-runs-multiyear-collection-plan-2026-09-87a.json"
)
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, *, params, timeout, maximum_bytes):
        self.calls.append(
            {
                "url": url,
                "params": dict(params),
                "timeout": timeout,
                "maximum_bytes": maximum_bytes,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _one_day_request() -> tuple[dict, dict]:
    plan, _ = load_bound_plan(PLAN_PATH)
    request = copy.deepcopy(plan["requests"][0])
    request["parameters"]["start_date"] = "2021-05-10"
    request["parameters"]["end_date"] = "2021-05-10"
    request["day_count"] = 1
    request["expected_long_rows_before_missingness"] = 24 * len(FIELDS) * len(LEADS)
    request["parameters_sha256"] = payload_sha256(request["parameters"])
    request["request_sha256"] = self_hash(request, "request_sha256")
    return plan, request


def _payload(
    request: dict,
    *,
    missing_series: str | None = None,
    wrong_unit_series: str | None = None,
    truncate_series: str | None = None,
    duplicate_time: bool = False,
) -> bytes:
    times = [f"2021-05-10T{hour:02d}:00" for hour in range(24)]
    if duplicate_time:
        times[-1] = times[-2]
    hourly = {"time": times}
    hourly_units = {"time": "iso8601"}
    for field in FIELDS:
        for lead in LEADS:
            name = f"{field}_previous_day{lead}"
            if name == missing_series:
                continue
            values = [float(lead)] * 24
            if name == truncate_series:
                values.pop()
            hourly[name] = values
            hourly_units[name] = (
                "definitely-wrong"
                if name == wrong_unit_series
                else request["expected_units"][field]
            )
    return json.dumps(
        {
            "timezone": request["timezone"],
            "hourly": hourly,
            "hourly_units": hourly_units,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _response(request: dict, **payload_options) -> TransportResponse:
    return TransportResponse(
        status_code=200,
        headers={"ETag": '"fixture"'},
        body=_payload(request, **payload_options),
    )


def _collect(tmp_path: Path, transport: FakeTransport):
    plan, request = _one_day_request()
    result = collect_unit(
        plan_sha256=plan["plan_sha256"],
        request=request,
        output_root=tmp_path,
        transport=transport,
        started_monotonic=0.0,
        overall_runtime_seconds=1000.0,
        monotonic=lambda: 0.0,
        sleeper=lambda _delay: None,
        utcnow=lambda: NOW,
    )
    return plan, request, result


def test_frozen_plan_is_exact_outcome_blind_provider_denominator() -> None:
    plan, plan_bytes = load_bound_plan(PLAN_PATH)

    assert plan["plan_sha256"] == (
        "20b45f3c0d98a57170a66a237de865374309da67371805fc15204d00f354b09e"
    )
    assert len(plan["requests"]) == 120
    assert plan["scope"]["years"] == [2021, 2022, 2023, 2024, 2025]
    assert plan["expected_denominator"]["long_rows_before_missingness"] == 13_789_440
    assert plan["provider_contract"]["endpoint"] == ENDPOINT
    assert plan["provider_contract"]["source"] == SOURCE
    assert plan["provider_contract"]["issue_time_basis"] == ISSUE_TIME_BASIS
    assert plan["provider_contract"]["historical_availability"] == (
        HISTORICAL_AVAILABILITY
    )
    assert plan_bytes
    assert all(request["year"] != 2026 for request in plan["requests"])
    assert all(
        set(request["parameters"])
        == {
            "end_date",
            "hourly",
            "latitude",
            "longitude",
            "start_date",
            "temperature_unit",
            "timezone",
            "wind_speed_unit",
        }
        for request in plan["requests"]
    )


def test_direct_provider_collection_is_refused_without_wrapper(tmp_path: Path) -> None:
    with pytest.raises(CollectionError, match="dedicated bounded wrapper"):
        run_collection(PLAN_PATH, output_root=tmp_path)


def test_success_publishes_exact_contract_and_verified_resume(tmp_path: Path) -> None:
    plan, request = _one_day_request()
    transport = FakeTransport([_response(request)])
    _, _, result = _collect(tmp_path, transport)

    assert result["status"] == "COMPLETE"
    completed = tmp_path / "units" / request["unit_id"] / "completed"
    rows = (completed / "normalized.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split(",") == list(CSV_COLUMNS)
    assert len(rows) == request["expected_long_rows_before_missingness"] + 1
    receipt = json.loads((completed / "receipt.json").read_bytes())
    assert receipt["raw_response_sha256"] == hashlib.sha256(
        _payload(request)
    ).hexdigest()
    assert receipt["caller_supplied_issue_or_availability_time"] is False
    assert receipt["retrieval_is_historical_availability_evidence"] is False

    skipped = collect_unit(
        plan_sha256=plan["plan_sha256"],
        request=request,
        output_root=tmp_path,
        transport=FakeTransport([]),
        started_monotonic=0.0,
        overall_runtime_seconds=1000.0,
        monotonic=lambda: 0.0,
        utcnow=lambda: NOW,
    )
    assert skipped["status"] == "SKIPPED_VERIFIED"


def test_missing_provider_series_remains_an_explicit_gap(tmp_path: Path) -> None:
    _, request = _one_day_request()
    missing = "cape_previous_day7"
    transport = FakeTransport([_response(request, missing_series=missing)])
    _, _, result = _collect(tmp_path, transport)

    assert result["status"] == "COMPLETE_WITH_EXPLICIT_GAPS"
    projection = result["receipt"]["projection"]
    assert projection["missing_series"] == [missing]
    assert projection["missing_count"] == 24
    assert projection["row_count"] == 24 * len(FIELDS) * len(LEADS)


@pytest.mark.parametrize(
    ("body", "options"),
    [
        (b"not-json", {}),
        (None, {"truncate_series": "cape_previous_day1"}),
        (None, {"duplicate_time": True}),
        (None, {"wrong_unit_series": "temperature_2m_previous_day1"}),
    ],
)
def test_response_integrity_failures_are_never_retried(
    tmp_path: Path, body: bytes | None, options: dict
) -> None:
    _, request = _one_day_request()
    response = TransportResponse(
        status_code=200,
        headers={},
        body=body if body is not None else _payload(request, **options),
    )
    transport = FakeTransport([response])

    _, _, result = _collect(tmp_path, transport)

    assert result["status"] == "INTEGRITY_FAILURE"
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("first", "expected_delay", "classification"),
    [
        (TransportFailure("timeout"), 5.0, "TRANSPORT_FAILURE"),
        (
            TransportResponse(429, {"Retry-After": "7"}, b'{"error":true}'),
            7.0,
            "HTTP_429",
        ),
        (TransportResponse(503, {}, b"unavailable"), 5.0, "HTTP_5XX"),
    ],
)
def test_only_transport_429_and_5xx_are_retried(
    tmp_path: Path, first, expected_delay: float, classification: str
) -> None:
    plan, request = _one_day_request()
    transport = FakeTransport([first, _response(request)])
    delays = []
    result = collect_unit(
        plan_sha256=plan["plan_sha256"],
        request=request,
        output_root=tmp_path,
        transport=transport,
        started_monotonic=0.0,
        overall_runtime_seconds=1000.0,
        monotonic=lambda: 0.0,
        sleeper=delays.append,
        utcnow=lambda: NOW,
    )

    assert result["status"] == "COMPLETE"
    assert delays == [expected_delay]
    assert result["receipt"]["retry_history"][0]["classification"] == classification


def test_non_429_4xx_is_terminal_without_retry(tmp_path: Path) -> None:
    transport = FakeTransport(
        [TransportResponse(400, {}, b'{"error":"bad request"}')]
    )
    _, _, result = _collect(tmp_path, transport)

    assert result["status"] == "PERMANENT_FAILURE"
    assert len(transport.calls) == 1


def test_completed_artifact_tamper_fails_closed(tmp_path: Path) -> None:
    plan, request, _ = _collect(
        tmp_path, FakeTransport([_response(_one_day_request()[1])])
    )
    normalized = tmp_path / "units" / request["unit_id"] / "completed" / "normalized.csv"
    normalized.write_bytes(normalized.read_bytes() + b"tamper")

    with pytest.raises(RetainedArtifactError, match="byte count differs"):
        collect_unit(
            plan_sha256=plan["plan_sha256"],
            request=request,
            output_root=tmp_path,
            transport=FakeTransport([]),
            started_monotonic=0.0,
            overall_runtime_seconds=1000.0,
            monotonic=lambda: 0.0,
            utcnow=lambda: NOW,
        )


def test_interrupted_stage_is_preserved_before_resume(tmp_path: Path) -> None:
    _, request = _one_day_request()
    unit_root = tmp_path / "units" / request["unit_id"]
    stage = unit_root / ".attempt-evidence.publishing"
    stage.mkdir(parents=True)
    (stage / "partial.bin").write_bytes(b"partial")

    _, _, result = _collect(tmp_path, FakeTransport([_response(request)]))

    assert result["status"] == "COMPLETE"
    preserved = unit_root / "attempts" / "interrupted-evidence"
    assert (preserved / "partial.bin").read_bytes() == b"partial"


def test_terminal_manifest_preserves_full_denominator_and_rehashes(tmp_path: Path) -> None:
    full_plan, request = _one_day_request()
    _collect(tmp_path, FakeTransport([_response(request)]))
    plan = copy.deepcopy(full_plan)
    plan["requests"] = [request]
    plan["expected_denominator"]["long_rows_before_missingness"] = request[
        "expected_long_rows_before_missingness"
    ]

    result = finalize_collection(plan, tmp_path, utcnow=lambda: NOW)

    assert result["disposition"] == "COMPLETE_RESEARCH_CORPUS"
    assert result["counts"]["requested_rows"] == 2016
    assert result["counts"]["non_null_rows"] == 2016
    assert verify_final(tmp_path) == result
