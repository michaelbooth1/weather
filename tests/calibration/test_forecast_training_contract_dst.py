"""The PIT preflight's hourly-profile matrix follows the real hours of each local date.

Guards: docs/operations/PIT_FORECAST_TRAINING_CORPUS.md (Collector, DST) and retrain memo R0.1 step 1 -
  a published corpus whose fall-back date keeps 25 rows (spring-forward 23) must pass the consumer
  preflight; before 2026-10-21 the preflight demanded 24 rows and refused both published R0 corpora.
Fixture bytes only; no network.
"""

import json
import socket
from datetime import datetime, timedelta

import pytest

from weather.calibration.forecast_training_contract import preflight_pit_forecast_training_corpus
from weather.sources import forecast_training_corpus_fetch as fetch
from weather.sources.forecast_training_corpus import (
    build_plan,
    materialize_corpus,
    stage_response,
    write_immutable_plan,
)


@pytest.fixture(autouse=True)
def _no_real_sockets(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("a real socket was opened in a fixture-only test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


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


def _published(tmp_path, year, start, end, labels):
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
    request = plan["requests"][0]
    field = request["variables"][0]["request_field"]
    body = json.dumps({
        "timezone": request["source_timezone"],
        "hourly": {"time": labels, field: [float(index) for index in range(len(labels))]},
        "hourly_units": {field: "°F"},
    }).encode("utf-8")
    stage_response(
        path,
        tmp_path / "staging",
        request["request_hash"],
        body,
        http_status=200,
        retrieved_at_utc="2026-10-21T01:00:00Z",
        issue_evidence=fetch.issue_evidence_for(request),
    )
    return materialize_corpus(path, tmp_path / "staging", tmp_path / "publish")


def _hours_by_date(manifest):
    counts = {}
    for line in (manifest.parent / "forecast_hourly.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        counts[row["target_date"]] = counts.get(row["target_date"], 0) + 1
    return counts


def _preflight(manifest):
    return preflight_pit_forecast_training_corpus(
        manifest, target_year=2026, required_market_ids=["nyc"], required_cutoff_hours=[7, 20],
    )


def test_fall_back_date_with_25_rows_passes_preflight(tmp_path):
    days = ("2021-11-06", "2021-11-07", "2021-11-08")
    manifest = _published(tmp_path, 2021, (11, 6), (11, 8), _true_local(days, repeat="2021-11-07T01:00"))
    assert _hours_by_date(manifest) == {"2021-11-06": 24, "2021-11-07": 25, "2021-11-08": 24}
    receipt = _preflight(manifest)
    assert receipt["status"] == "PASS"
    assert receipt["hourly_rows"] == 73


def test_spring_forward_date_with_23_rows_passes_preflight(tmp_path):
    days = ("2022-03-12", "2022-03-13", "2022-03-14")
    manifest = _published(tmp_path, 2022, (3, 12), (3, 14), _true_local(days, skip="2022-03-13T02:00"))
    assert _hours_by_date(manifest)["2022-03-13"] == 23
    assert _preflight(manifest)["hourly_rows"] == 71
