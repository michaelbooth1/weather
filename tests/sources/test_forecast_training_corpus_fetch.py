"""Fixture-only tests for the PIT corpus Previous Runs collector and the --fields option.

Guards: docs/operations/PIT_FORECAST_TRAINING_CORPUS.md (Field set; Collector) and EF §4f
(the free Previous Runs surface is temperature-only). No test opens a real socket.
"""

import hashlib
import json
import socket
from datetime import datetime, timedelta, timezone

import pytest

from weather.sources import forecast_training_corpus_fetch as fetch
from weather.sources.forecast_training_corpus import (
    ACTIVE_FORECAST_ARCHIVE_ROOT,
    DEFAULT_SOURCE_FIELDS,
    CorpusVerificationError,
    MaterializationBlocked,
    PlanValidationError,
    StagingValidationError,
    build_plan,
    load_plan,
    materialize_corpus,
    resume_ledger,
    verify_corpus_manifest,
    write_immutable_plan,
)


US11 = (
    "atlanta",
    "austin",
    "chicago",
    "dallas",
    "denver",
    "houston",
    "los-angeles",
    "miami",
    "nyc",
    "san-francisco",
    "seattle",
)

PLAN_KEYS_BEFORE_FIELD_OPTION = {
    "schema_version",
    "planned_at_utc",
    "mode",
    "network_authorized",
    "provider_probe_authorized",
    "corpus_role",
    "target_year",
    "target_year_excluded",
    "years",
    "market_ids",
    "cutoff_hours_local",
    "season_window",
    "issue_contract",
    "normalizer_version",
    "source_fields",
    "expected_dates_by_year",
    "consumer_dispositions",
    "publication_contract",
    "summary",
    "requests",
    "plan_sha256",
}


@pytest.fixture(autouse=True)
def _no_real_sockets(monkeypatch):
    opened = []

    def _refuse(*args, **kwargs):
        opened.append(args)
        raise AssertionError("a real socket was opened in a fixture-only test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    yield
    assert opened == []


def _temperature_plan(tmp_path, *, markets=("atlanta",), years=(2021,), cutoffs=(7, 20)):
    plan = build_plan(
        years=years,
        target_year=2026,
        market_ids=markets,
        season_start=(12, 1),
        season_end=(12, 2),
        cutoff_hours=cutoffs,
        planned_at_utc="2026-10-21T00:00:00+00:00",
        source_fields=("temperature_2m",),
    )
    path = tmp_path / "plan.json"
    write_immutable_plan(path, plan)
    return plan, path


def _body_for(request, *, drop_field=None):
    times = [
        f"{day}T{hour:02d}:00"
        for day in request["expected_local_dates"]
        for hour in range(24)
    ]
    hourly = {"time": times}
    units = {}
    for binding in request["variables"]:
        if binding["request_field"] == drop_field:
            continue
        hourly[binding["request_field"]] = [50.0 + (index % 24) for index in range(len(times))]
        units[binding["request_field"]] = "°" + binding["source_unit"]
    return json.dumps(
        {"timezone": request["source_timezone"], "hourly": hourly, "hourly_units": units}
    ).encode("utf-8")


class FakeTransport:
    def __init__(self, plan, responses=None, *, drop_field=None):
        self.by_url = {fetch.request_url(r): r for r in plan["requests"]}
        self.responses = list(responses or [])
        self.calls = []
        self.drop_field = drop_field

    def __call__(self, url, timeout):
        self.calls.append(url)
        assert url.startswith(fetch.PREVIOUS_RUNS_ENDPOINT + "?")
        assert "apikey" not in url.lower()
        if self.responses:
            return self.responses.pop(0)
        request = self.by_url[url]
        return 200, {"Content-Type": "application/json"}, _body_for(
            request, drop_field=self.drop_field
        )


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_default_plan_is_unchanged_without_field_option():
    kwargs = dict(
        years=(2021,),
        target_year=2026,
        market_ids=("toronto",),
        season_start=(5, 10),
        season_end=(5, 10),
        cutoff_hours=(10,),
        planned_at_utc="2026-01-01T00:00:00+00:00",
    )
    default = build_plan(**kwargs)
    explicit = build_plan(**kwargs, source_fields=DEFAULT_SOURCE_FIELDS)
    reordered = build_plan(**kwargs, source_fields=tuple(reversed(DEFAULT_SOURCE_FIELDS)))

    assert default["source_fields"] == list(DEFAULT_SOURCE_FIELDS)
    assert set(default) == PLAN_KEYS_BEFORE_FIELD_OPTION
    assert explicit == default
    assert reordered == default
    assert len(default["requests"][0]["variables"]) == len(DEFAULT_SOURCE_FIELDS)


def test_field_option_validation_and_plan_carries_field_set(tmp_path):
    with pytest.raises(PlanValidationError, match="unknown source fields"):
        build_plan(years=(2021,), market_ids=("atlanta",), source_fields=("bogus",))
    with pytest.raises(PlanValidationError, match="must include: temperature_2m"):
        build_plan(years=(2021,), market_ids=("atlanta",), source_fields=("cloud_cover",))

    plan, path = _temperature_plan(tmp_path)
    loaded = load_plan(path)
    assert loaded["source_fields"] == ["temperature_2m"]
    request = loaded["requests"][0]
    assert [b["request_field"] for b in request["variables"]] == ["temperature_2m_previous_day1"]
    assert request["params"]["hourly"] == "temperature_2m_previous_day1"
    assert loaded["summary"]["variable_bindings"] == 1

    tampered = dict(plan)
    tampered["source_fields"] = ["cloud_cover", "temperature_2m"]
    with pytest.raises(PlanValidationError):
        write_immutable_plan(tmp_path / "other.json", tampered)


def test_cli_plan_accepts_fields(tmp_path, capsys):
    from weather.sources.forecast_training_corpus import main as corpus_main

    out = tmp_path / "cli-plan.json"
    corpus_main(
        [
            "plan",
            "--out",
            str(out),
            "--years",
            "2021,2022,2023",
            "--markets",
            ",".join(US11),
            "--season-start",
            "10-01",
            "--season-end",
            "12-31",
            "--fields",
            "temperature_2m",
            "--planned-at-utc",
            "2026-10-21T00:00:00+00:00",
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["source_fields"] == ["temperature_2m"]
    assert printed["summary"]["request_count"] == 33
    assert printed["summary"]["expected_market_dates"] == 11 * 3 * 92
    plan = load_plan(out)
    assert all(r["year"] in (2021, 2022, 2023) for r in plan["requests"])


def test_issue_evidence_is_cutoff_safe_for_every_us_market_oct_to_dec(tmp_path):
    plan = build_plan(
        years=(2021, 2022, 2023),
        target_year=2026,
        market_ids=US11,
        season_start=(10, 1),
        season_end=(12, 31),
        cutoff_hours=(7,),
        planned_at_utc="2026-10-21T00:00:00+00:00",
        source_fields=("temperature_2m",),
    )
    from zoneinfo import ZoneInfo

    for request in plan["requests"]:
        zone = ZoneInfo(request["source_timezone"])
        evidence = fetch.issue_evidence_for(request)
        assert [row["target_date"] for row in evidence] == request["expected_local_dates"]
        for row in evidence:
            issue = datetime.fromisoformat(row["issue_time_utc"])
            available = datetime.fromisoformat(row["available_at_utc"])
            day = datetime.fromisoformat(row["target_date"])
            cutoff = datetime(day.year, day.month, day.day, 7, tzinfo=zone)
            last_hour = datetime(day.year, day.month, day.day, 23, tzinfo=zone)
            assert issue.hour % 6 == 0 and issue.minute == 0
            assert issue <= last_hour.astimezone(timezone.utc) - timedelta(hours=24)
            assert available == issue + timedelta(hours=6)
            assert available <= cutoff
            assert row["run_id_exposed"] is False
            assert row["issue_evidence_kind"] == "fixed_lead_offset"


def test_refuses_forecast_history_staging_roots(tmp_path):
    plan, path = _temperature_plan(tmp_path)
    transport = FakeTransport(plan)
    for root in (
        ACTIVE_FORECAST_ARCHIVE_ROOT,
        ACTIVE_FORECAST_ARCHIVE_ROOT / "katl",
        tmp_path / "elsewhere" / "data" / "forecast_history",
        tmp_path / "Forecast_History" / "staging",
    ):
        with pytest.raises(fetch.CollectorRefused):
            fetch.collect(path, root, http_get=transport, sleep=lambda _s: None)
    protected = tmp_path / "protected"
    with pytest.raises(fetch.CollectorRefused, match="overlaps"):
        fetch.collect(
            path,
            protected / "x",
            http_get=transport,
            sleep=lambda _s: None,
            active_archive_roots=[protected],
        )
    assert transport.calls == []
    assert not (tmp_path / "elsewhere").exists()


def test_retry_after_is_honoured_and_backoff_is_exponential():
    clock = FakeClock()
    responses = [
        (503, {}, b"busy"),
        (429, {"Retry-After": "120"}, b"slow down"),
        (429, {}, b"slow down"),
        (200, {}, b"{}"),
    ]
    calls = []

    def transport(url, timeout):
        calls.append(url)
        return responses.pop(0)

    status, _headers, body, attempts = fetch.fetch_with_retries(
        "https://previous-runs-api.open-meteo.com/v1/forecast?x=1",
        http_get=transport,
        sleep=clock.sleep,
        max_attempts=5,
        backoff_base_seconds=10,
        backoff_cap_seconds=600,
    )
    assert (status, body, attempts) == (200, b"{}", 4)
    assert clock.sleeps == [10, 120, 40]


def test_retry_after_http_date_and_non_retryable_status():
    future = datetime.now(timezone.utc) + timedelta(seconds=300)
    header = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert 250 <= fetch.retry_after_seconds({"retry-after": header}) <= 301
    assert fetch.retry_after_seconds({}) is None

    clock = FakeClock()
    status, _h, _b, attempts = fetch.fetch_with_retries(
        "u", http_get=lambda u, t: (400, {}, b"bad"), sleep=clock.sleep
    )
    assert (status, attempts, clock.sleeps) == (400, 1, [])


def test_transport_errors_back_off_then_refuse():
    clock = FakeClock()

    def broken(url, timeout):
        raise OSError("connection reset")

    with pytest.raises(fetch.CollectorRefused, match="transport failed after 3"):
        fetch.fetch_with_retries(
            "u", http_get=broken, sleep=clock.sleep, max_attempts=3, backoff_base_seconds=5
        )
    assert clock.sleeps == [5, 10]


def test_exhausted_429_is_staged_as_failure_and_stops(tmp_path):
    plan, path = _temperature_plan(tmp_path, markets=("atlanta", "nyc"))
    clock = FakeClock()
    transport = FakeTransport(plan, [(429, {"Retry-After": "1"}, b"limit")] * 2)
    staging = tmp_path / "staging"
    with pytest.raises(StagingValidationError, match="http_status_429"):
        fetch.collect(
            path,
            staging,
            http_get=transport,
            sleep=clock.sleep,
            clock=clock.monotonic,
            max_attempts=2,
        )
    assert len(transport.calls) == 2
    assert resume_ledger(path, staging)["complete_units"] == 0


def test_collect_is_serial_rate_limited_resumable_and_materializes_field_set(tmp_path):
    plan, path = _temperature_plan(tmp_path, markets=("atlanta", "seattle"), years=(2021, 2022))
    clock = FakeClock()
    transport = FakeTransport(plan)
    staging = tmp_path / "staging"

    first = fetch.collect(
        path,
        staging,
        http_get=transport,
        sleep=clock.sleep,
        clock=clock.monotonic,
        min_interval_seconds=10,
        max_requests=1,
    )
    assert len(first["fetched"]) == 1 and first["all_complete"] is False

    second = fetch.collect(
        path,
        staging,
        http_get=transport,
        sleep=clock.sleep,
        clock=clock.monotonic,
        min_interval_seconds=10,
    )
    assert second["skipped_complete"] == 1
    assert len(second["fetched"]) == 3
    assert second["all_complete"] is True
    assert len(transport.calls) == 4
    assert clock.sleeps == [10, 10]

    third = fetch.collect(path, staging, http_get=transport, sleep=clock.sleep)
    assert third["fetched"] == [] and len(transport.calls) == 4

    publish = tmp_path / "publish"
    manifest_path = materialize_corpus(path, staging, publish)
    manifest = verify_corpus_manifest(manifest_path)
    assert manifest["source_fields"] == ["temperature_2m"]
    assert manifest["coverage"]["expected_field_date_cutoff_cells"] == 2 * 2 * 2 * 2
    assert manifest["row_counts"]["daily"] == 2 * 2 * 2 * 2
    daily = [
        json.loads(line)
        for line in (manifest_path.parent / "forecast_daily.jsonl").read_text().splitlines()
    ]
    assert {row["lead_days"] for row in daily} == {1}
    assert all(row["forecast_high_native"] == 73.0 for row in daily)
    coverage = [
        json.loads(line)
        for line in (manifest_path.parent / "coverage.jsonl").read_text().splitlines()
    ]
    assert all(set(row["field_status"]) == {"temperature_2m"} for row in coverage)

    tampered = json.loads(manifest_path.read_text())
    tampered["source_fields"] = list(DEFAULT_SOURCE_FIELDS)
    body = {key: value for key, value in tampered.items() if key != "manifest_sha256"}
    tampered["manifest_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(json.dumps(tampered))
    with pytest.raises(CorpusVerificationError, match="source-field set"):
        verify_corpus_manifest(manifest_path)


def test_missing_planned_field_fails_staging_and_blocks_materialize(tmp_path):
    plan, path = _temperature_plan(tmp_path)
    transport = FakeTransport(plan, drop_field="temperature_2m_previous_day1")
    staging = tmp_path / "staging"
    with pytest.raises(StagingValidationError, match="missing_field:temperature_2m_previous_day1"):
        fetch.collect(path, staging, http_get=transport, sleep=lambda _s: None)
    with pytest.raises(MaterializationBlocked, match="all request units must be complete"):
        materialize_corpus(path, staging, tmp_path / "publish")


def test_request_url_refuses_non_previous_runs_endpoint(tmp_path):
    plan, _path = _temperature_plan(tmp_path)
    request = dict(plan["requests"][0])
    request["endpoint"] = "https://customer-api.open-meteo.com/v1/forecast"
    with pytest.raises(fetch.CollectorRefused, match="free Previous Runs"):
        fetch.request_url(request)
    url = fetch.request_url(plan["requests"][0])
    assert url.startswith("https://previous-runs-api.open-meteo.com/v1/forecast?")
    assert "models=gfs_seamless" in url
