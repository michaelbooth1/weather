"""The R0 2024-2025 Previous Runs fetch path, end to end on fixture bytes (owner M6 2026-10-23).

Guards: retrain memo R0.2 M6 option (c) and docs/operations/PIT_FORECAST_TRAINING_CORPUS.md
("R0 2024-2025 corpus"): the exact plan command (US 11, 2024-2025, Oct 1-Dec 30, temperature only,
one-day pad) builds, never reaches the target year (a Dec 31 end with 2025 is refused), shares
every union-compatibility field with the 2021-2023 corpora, and a corpus collected and
materialized from that plan unions with a 2021 corpus for the per-market trainer. Fixture bytes
only: no test opens a socket, and nothing reads data/.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta

import pytest

from weather.calibration.feature_model_training_inputs import (
    UNION_COMPATIBILITY_FIELDS,
    PITForecastCorpusUnion,
)
from weather.model.model_constants import INTRADAY_CUTOFF_HOURS
from weather.sources import forecast_training_corpus_fetch as fetch
from weather.sources.forecast_training_corpus import (
    PlanValidationError,
    load_plan,
    main as corpus_main,
    materialize_corpus,
    verify_corpus_manifest,
)

US11 = "atlanta,austin,chicago,dallas,denver,houston,los-angeles,miami,nyc,san-francisco,seattle"
# The exact R0 2024-2025 plan arguments (the report's command, minus --out).
R0_2024_2025_PLAN = [
    "--years", "2024,2025", "--markets", US11, "--season-start", "10-01", "--season-end", "12-30",
    "--fields", "temperature_2m", "--pad-request-days", "1",
]
# The 2021-2023 collection's arguments (runbook "Collector").
R0_2021_PLAN = [
    "--years", "2021", "--markets", US11, "--season-start", "10-01", "--season-end", "12-31",
    "--fields", "temperature_2m", "--pad-request-days", "1",
]
PLANNED_AT = ["--planned-at-utc", "2026-10-23T00:00:00+00:00"]


@pytest.fixture(autouse=True)
def _no_real_sockets(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("a real socket was opened in a fixture-only test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _plan(tmp_path, name, argv, capsys=None):
    out = tmp_path / name
    assert corpus_main(["plan", "--out", str(out), *argv, *PLANNED_AT]) in (None, 0)
    if capsys is not None:
        capsys.readouterr()
    return load_plan(out), out


class RetrievalTimeOffsetTransport:
    """Emulates the provider: contiguous hourly labels from the padded start, all in one offset.

    The offset is the market zone's at retrieval (October 2026: daylight time), as measured in
    the runbook's "DST and provider time labels" section.
    """

    def __init__(self, plan, offset_seconds=-14400):
        self.by_url = {fetch.request_url(request): request for request in plan["requests"]}
        self.offset = offset_seconds
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        assert url.startswith(fetch.PREVIOUS_RUNS_ENDPOINT + "?") and "apikey" not in url.lower()
        request = self.by_url[url]
        params = request["params"]
        first = datetime.fromisoformat(f"{params['start_date']}T00:00")
        last = datetime.fromisoformat(f"{params['end_date']}T23:00")
        count = int((last - first).total_seconds() // 3600) + 1
        labels = [(first + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M") for index in range(count)]
        field = request["variables"][0]["request_field"]
        body = {
            "timezone": request["source_timezone"],
            "utc_offset_seconds": self.offset,
            "hourly": {"time": labels, field: [40.0 + (index % 24) for index in range(count)]},
            "hourly_units": {field: "°F"},
        }
        return 200, {"Content-Type": "application/json"}, json.dumps(body).encode("utf-8")


class _Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _collect_and_materialize(tmp_path, plan, plan_path, name):
    transport = RetrievalTimeOffsetTransport(plan)
    clock = _Clock()
    staging = tmp_path / f"{name}-staging"
    result = fetch.collect(
        plan_path, staging, http_get=transport, sleep=clock.sleep, clock=clock.monotonic,
        min_interval_seconds=10,
    )
    assert result["all_complete"] is True
    assert len(transport.calls) == len(plan["requests"])
    return materialize_corpus(plan_path, staging, tmp_path / f"{name}-publish")


def test_r0_2024_2025_plan_is_us11_temperature_only_padded_and_inside_the_years(tmp_path, capsys):
    plan, _ = _plan(tmp_path, "plan-2024-2025.json", R0_2024_2025_PLAN, capsys)
    assert plan["years"] == [2024, 2025]
    assert plan["target_year"] == 2026
    assert plan["market_ids"] == US11.split(",")
    assert plan["source_fields"] == ["temperature_2m"]
    assert plan["request_padding"]["days"] == 1
    assert plan["summary"]["request_count"] == 22
    assert plan["summary"]["expected_market_dates"] == 11 * (91 + 91)  # Oct 1-Dec 30, both years
    for request in plan["requests"]:
        assert request["params"]["hourly"] == "temperature_2m_previous_day1"
        assert request["params"]["models"] == "gfs_seamless"
        assert request["lead_days"] == 1
        assert request["window_start"].endswith("-10-01") and request["window_end"].endswith("-12-30")
        assert request["params"]["end_date"] <= "2025-12-31"  # never the target year
        assert "apikey" not in fetch.request_url(request).lower()
    # The R0 centre windows (11-17..12-01, 12-03..12-17) sit wholly inside every year's dates.
    dates = set(plan["requests"][0]["expected_local_dates"])
    assert {"2024-11-17", "2024-12-17"} <= dates and "2024-12-31" not in dates


def test_a_december_31_end_with_2025_is_refused(tmp_path):
    argv = [arg if arg != "12-30" else "12-31" for arg in R0_2024_2025_PLAN]
    with pytest.raises(PlanValidationError, match="target year"):
        corpus_main(["plan", "--out", str(tmp_path / "bad.json"), *argv, *PLANNED_AT])
    assert not (tmp_path / "bad.json").exists()


def test_the_plan_shares_every_union_field_with_the_2021_2023_collection(tmp_path, capsys):
    new, _ = _plan(tmp_path, "plan-2024-2025.json", R0_2024_2025_PLAN, capsys)
    old, _ = _plan(tmp_path, "plan-2021.json", R0_2021_PLAN, capsys)
    plan_level = [field for field in UNION_COMPATIBILITY_FIELDS if field != "schema_version"]
    for field in plan_level:
        assert new.get(field) == old.get(field), field
    assert new["request_padding"] == old["request_padding"]


def test_collected_corpus_unions_with_a_2021_corpus_for_the_trainer(tmp_path, capsys):
    one_market = ["--markets", "atlanta"]
    new_argv = [*R0_2024_2025_PLAN[:2], *one_market, *R0_2024_2025_PLAN[4:]]
    old_argv = [*R0_2021_PLAN[:2], *one_market, *R0_2021_PLAN[4:]]
    new_plan, new_path = _plan(tmp_path, "plan-new.json", new_argv, capsys)
    old_plan, old_path = _plan(tmp_path, "plan-old.json", old_argv, capsys)
    new_manifest = _collect_and_materialize(tmp_path, new_plan, new_path, "new")
    old_manifest = _collect_and_materialize(tmp_path, old_plan, old_path, "old")

    manifest = verify_corpus_manifest(new_manifest)
    assert manifest["years"] == [2024, 2025]
    hourly = [
        json.loads(line)
        for line in (new_manifest.parent / "forecast_hourly.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_date = {}
    for row in hourly:
        by_date.setdefault(row["target_date"], []).append(row)
    assert max(by_date) == "2025-12-30" and min(by_date) == "2024-10-01"
    assert len(by_date["2024-11-03"]) == 25 and len(by_date["2025-11-02"]) == 25  # fall-back dates
    assert len(by_date["2024-12-30"]) == 24

    union = PITForecastCorpusUnion(
        [old_manifest, new_manifest], "atlanta", target_year=2026,
        required_cutoff_hours=INTRADAY_CUTOFF_HOURS,
    )
    assert union.years == (2021, 2024, 2025)
    resolved = union.resolve("2025-11-24", 12)
    assert resolved is not None
    record = union.record()
    assert [row["years"] for row in record["corpora"]] == [[2021], [2024, 2025]]
