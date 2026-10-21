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


def test_retry_after_beyond_cap_refuses_instead_of_sleeping():
    clock = FakeClock()
    with pytest.raises(fetch.CollectorRefused, match="exceeds the 600s backoff cap"):
        fetch.fetch_with_retries(
            "u",
            http_get=lambda u, t: (429, {"Retry-After": "86400"}, b"later"),
            sleep=clock.sleep,
            backoff_cap_seconds=600,
        )
    assert clock.sleeps == []
    future = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(fetch.CollectorRefused, match="backoff cap"):
        fetch.fetch_with_retries(
            "u",
            http_get=lambda u, t: (
                429,
                {"Retry-After": future.strftime("%a, %d %b %Y %H:%M:%S GMT")},
                b"",
            ),
            sleep=clock.sleep,
        )
    assert clock.sleeps == []


def test_zero_attempts_is_refused(tmp_path):
    with pytest.raises(fetch.CollectorRefused, match="at least 1"):
        fetch.fetch_with_retries("u", http_get=lambda u, t: (200, {}, b""), max_attempts=0)
    _plan_obj, path = _temperature_plan(tmp_path)
    with pytest.raises(fetch.CollectorRefused, match="at least 1"):
        fetch.collect(path, tmp_path / "staging", http_get=lambda u, t: None, max_attempts=0)
    assert fetch.main(["--plan", str(path), "--staging-root", str(tmp_path / "s"), "--max-attempts", "0"]) == 2


def test_http_exception_is_retried():
    import http.client

    clock = FakeClock()
    outcomes = [http.client.RemoteDisconnected("gone"), (200, {}, b"{}")]

    def flaky(url, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    status, _h, _b, attempts = fetch.fetch_with_retries(
        "u", http_get=flaky, sleep=clock.sleep, backoff_base_seconds=7
    )
    assert (status, attempts, clock.sleeps) == (200, 2, [7])


class _FakeResponse:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = _Headers(headers)
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Headers(dict):
    def items(self):
        return list(super().items())


class _FakeOpener:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        return self.handler(req)


def test_redirects_are_not_followed_and_fail_closed(tmp_path, monkeypatch):
    import urllib.error

    handler = fetch._RefuseRedirects()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.test/") is None

    def redirect(req):
        raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://elsewhere.test/"}, None)

    monkeypatch.setattr(fetch, "_OPENER", _FakeOpener(redirect))
    status, headers, body = fetch.urllib_get("https://previous-runs-api.open-meteo.com/v1/forecast?x=1", 5)
    assert status == 302 and body == b""

    plan, path = _temperature_plan(tmp_path)
    transport = FakeTransport(plan, [(302, {"Location": "https://elsewhere.test/"}, b"")])
    with pytest.raises(StagingValidationError, match="http_status_302"):
        fetch.collect(path, tmp_path / "staging", http_get=transport, sleep=lambda _s: None)
    assert len(transport.calls) == 1


def test_main_and_urllib_get_with_a_fake_opener(tmp_path, monkeypatch, capsys):
    plan, path = _temperature_plan(tmp_path)
    request = plan["requests"][0]
    opener = _FakeOpener(
        lambda req: _FakeResponse(200, {"Content-Type": "application/json"}, _body_for(request))
    )
    monkeypatch.setattr(fetch, "_OPENER", opener)
    assert fetch.main(["--plan", str(path), "--staging-root", str(tmp_path / "staging")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["all_complete"] is True and len(result["fetched"]) == 1
    sent = opener.requests[0]
    assert sent.full_url == fetch.request_url(load_plan(path)["requests"][0])
    assert sent.get_method() == "GET"
    assert sent.get_header("User-agent") == fetch.USER_AGENT
    assert not any(
        key.lower() in {"authorization", "cookie"} for key, _value in sent.header_items()
    )


def test_staging_and_publish_roots_refuse_src_and_artifacts(tmp_path):
    from weather.paths import ARTIFACTS_ROOT, SRC_ROOT

    plan, path = _temperature_plan(tmp_path)
    transport = FakeTransport(plan)
    for root in (SRC_ROOT / "pit-staging", ARTIFACTS_ROOT / "pit-staging", SRC_ROOT.parent):
        with pytest.raises(fetch.CollectorRefused):
            fetch.collect(path, root, http_get=transport, sleep=lambda _s: None)
    assert transport.calls == []
    fetch.collect(path, tmp_path / "staging", http_get=transport, sleep=lambda _s: None)
    with pytest.raises(MaterializationBlocked, match="tracked repository root"):
        materialize_corpus(path, tmp_path / "staging", ARTIFACTS_ROOT / "pit-corpus")
    assert not (ARTIFACTS_ROOT / "pit-corpus").exists()


def test_manifest_carries_issue_evidence_basis(tmp_path):
    plan, path = _temperature_plan(tmp_path)
    fetch.collect(path, tmp_path / "staging", http_get=FakeTransport(plan), sleep=lambda _s: None)
    manifest = verify_corpus_manifest(materialize_corpus(path, tmp_path / "staging", tmp_path / "pub"))
    assert manifest["issue_evidence_bases"] == [
        {
            "issue_time_basis": fetch.ISSUE_TIME_BASIS,
            "availability_latency_hours": 6,
            "run_id_exposed": False,
        }
    ]


def test_corrupt_staged_body_is_refetched(tmp_path):
    plan, path = _temperature_plan(tmp_path)
    transport = FakeTransport(plan)
    staging = tmp_path / "staging"
    fetch.collect(path, staging, http_get=transport, sleep=lambda _s: None)
    body = staging / "requests" / plan["requests"][0]["request_hash"] / "response.json"
    body.write_bytes(body.read_bytes()[:-5] + b"XXXXX")
    assert resume_ledger(path, staging)["all_complete"] is False
    result = fetch.collect(path, staging, http_get=transport, sleep=lambda _s: None)
    assert len(result["fetched"]) == 1 and result["all_complete"] is True
    assert len(transport.calls) == 2


def test_relative_and_symlinked_roots(tmp_path, monkeypatch):
    plan, path = _temperature_plan(tmp_path)
    transport = FakeTransport(plan)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fetch.CollectorRefused, match="forecast_history"):
        fetch.collect(path, "x/forecast_history/y", http_get=transport, sleep=lambda _s: None)
    result = fetch.collect(path, "rel-staging", http_get=transport, sleep=lambda _s: None)
    assert result["all_complete"] is True
    assert (tmp_path / "rel-staging" / "requests").is_dir()

    target = tmp_path / "real" / "forecast_history"
    target.mkdir(parents=True)
    link = tmp_path / "innocent-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, AttributeError, OSError):
            pytest.skip("neither a symlink nor a junction can be created on this host")
    with pytest.raises(fetch.CollectorRefused, match="forecast_history"):
        fetch.collect(path, link / "staging", http_get=transport, sleep=lambda _s: None)
    assert not any(target.iterdir())
