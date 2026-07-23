from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.market.market_registry import MarketSpec
from weather.reporting.research.radiation_previous_runs_research import (
    API_TO_ROW_FIELD,
    build_scratch_backfill,
    request_params,
    sha256_file,
)
from weather.sources.forecast_history import RICH_FORECAST_COLUMNS


class FakeResponse:
    def __init__(self, payload, url="https://previous-runs-api.open-meteo.com/fake"):
        self.content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.url = url
        self.status_code = 200

    def raise_for_status(self):
        return None


def _spec():
    return MarketSpec(
        id="test-market",
        city_label="Test Market",
        slug_prefix="test-market-on",
        timezone="America/Toronto",
        display_unit="C",
        wu_history_id="KAAA:9:XX",
        icao="KAAA",
        lat=43.0,
        lon=-79.0,
        sources=("wu_history", "open_meteo"),
        leading_obs="wu_history",
    )


def _write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _make_directory_alias(alias: Path, target: Path) -> None:
    try:
        alias.symlink_to(target, target_is_directory=True)
        return
    except (NotImplementedError, OSError) as symlink_error:
        if os.name == "nt":
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if junction.returncode == 0:
                return
        pytest.skip(f"directory aliases unavailable: {symlink_error}")


def _forecast_row(valid_time, temperature):
    row = {field: "" for field in RICH_FORECAST_COLUMNS}
    row.update({
        "schema_version": "forecast_history_long_v3",
        "market": "test-market",
        "station": "KAAA",
        "source": "open_meteo_previous_runs",
        "source_model": "best_match",
        "temperature_unit": "C",
        "target_date": "2026-06-10",
        "issue_time": "2026-06-09T00:00:00-04:00",
        "issue_time_basis": "fixed_lead_day_offset",
        "lead_hours": "24",
        "lead_days": "1",
        "valid_time": valid_time,
        "forecast_kind": "hourly",
        "target_temp_native": str(temperature),
        "target_temp_c": str(temperature),
        "source_url": "https://previous-runs-api.open-meteo.com/v1/forecast",
        "payload_hash": "old",
    })
    return row


def _source_fixture(root, spec):
    forecast = root / "forecast_history" / spec.icao.lower() / "forecast_long.csv"
    _write_csv(forecast, RICH_FORECAST_COLUMNS, [
        _forecast_row("2026-06-10T12:00:00-04:00", 20.0),
        _forecast_row("2026-06-10T13:00:00-04:00", 22.0),
    ])
    settlement = root / "wunderground" / spec.icao.lower() / "daily" / "daily_summary.csv"
    _write_csv(
        settlement,
        ("schema_version", "local_date", "temperature_unit", "max_temp_native", "max_temp_c", "row_count"),
        [{
            "schema_version": "wu_daily_native_v2",
            "local_date": "2026-06-10",
            "temperature_unit": "C",
            "max_temp_native": "23",
            "max_temp_c": "23",
            "row_count": "24",
        }],
    )


def _payload():
    return {
        "hourly": {
            "time": ["2026-06-10T12:00", "2026-06-10T13:00"],
            "shortwave_radiation_previous_day1": [500.0, 600.0],
            "direct_radiation_previous_day1": [350.0, 420.0],
            "diffuse_radiation_previous_day1": [150.0, 180.0],
            "cloud_cover_previous_day1": [25.0, 35.0],
        }
    }


def test_request_is_capped_to_fixed_lead_radiation_fields():
    params = request_params(_spec(), "2026-05-10", "2026-06-10")
    assert params == {
        "latitude": 43.0,
        "longitude": -79.0,
        "start_date": "2026-05-10",
        "end_date": "2026-06-10",
        "hourly": ",".join(API_TO_ROW_FIELD),
        "timezone": "America/Toronto",
    }


def test_scratch_backfill_caches_raw_payload_and_builds_hashed_derived_root(tmp_path):
    spec = _spec()
    source_root = tmp_path / "source"
    output_root = tmp_path / "scratch-output"
    _source_fixture(source_root, spec)
    calls = []

    def fake_get(url, *, params, timeout):
        calls.append((url, dict(params), timeout))
        return FakeResponse(_payload())

    payload = build_scratch_backfill(
        source_data_root=source_root,
        output_root=output_root,
        specs=(spec,),
        pause_seconds=0.0,
        request_get=fake_get,
        sleep_fn=lambda _: None,
    )

    assert len(calls) == 1
    assert payload["source_mirror_mutated"] is False
    assert payload["network_used"] is True
    assert payload["request_count"] == 1
    assert payload["error_count"] == 0
    assert payload["derived_rows"] == 2
    assert payload["dates_with_any_complete_hour"] == 1
    raw_path = output_root / "raw" / spec.id / "2026.json"
    assert raw_path.exists()
    request_record = payload["markets"][0]["requests"][0]
    assert request_record["raw_sha256"] == sha256_file(raw_path)
    assert request_record["params"]["start_date"] == "2026-06-10"
    assert request_record["params"]["end_date"] == "2026-06-10"

    derived_forecast = (
        output_root / "derived_data" / "forecast_history" / "kaaa" / "forecast_long.csv"
    )
    with derived_forecast.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["issue_time_basis"] == "fixed_lead_day_offset"
    assert rows[0]["shortwave_radiation"] == "500.0"
    assert rows[0]["direct_radiation"] == "350.0"
    assert rows[0]["diffuse_radiation"] == "150.0"
    assert rows[0]["cloud_cover"] == "25.0"
    assert rows[0]["payload_hash"] != "old"

    def forbidden_network(*args, **kwargs):
        raise AssertionError("raw cache should make the second run network-free")

    cached = build_scratch_backfill(
        source_data_root=source_root,
        output_root=output_root,
        specs=(spec,),
        pause_seconds=0.0,
        request_get=forbidden_network,
        sleep_fn=lambda _: None,
    )
    assert cached["network_used"] is False
    assert cached["markets"][0]["requests"][0]["cache_status"] == "reused"


def test_backfill_rejects_relative_output_alias_before_read_or_network(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    network_calls = []

    def forbidden_network(*_args, **_kwargs):
        network_calls.append(True)
        raise AssertionError("unsafe output must fail before network access")

    with pytest.raises(ValueError, match="output_root resolves inside"):
        build_scratch_backfill(
            source_data_root=Path("..") / "source",
            output_root=Path("..") / "working" / ".." / "source" / "scratch",
            specs=(_spec(),),
            pause_seconds=0.0,
            request_get=forbidden_network,
            sleep_fn=lambda _: None,
        )
    assert network_calls == []
    assert not (source_root / "scratch").exists()


@pytest.mark.parametrize("aliased_child", ["raw", "derived_data"])
def test_backfill_rejects_nested_symlink_aliases(tmp_path, aliased_child):
    source_root = tmp_path / "source"
    source_root.mkdir()
    output_root = tmp_path / "scratch-output"
    output_root.mkdir()
    alias = output_root / aliased_child
    _make_directory_alias(alias, source_root)

    with pytest.raises(ValueError, match=f"{aliased_child.replace('_data', '')}.*resolves inside"):
        build_scratch_backfill(
            source_data_root=source_root,
            output_root=output_root,
            specs=(_spec(),),
            pause_seconds=0.0,
            request_get=lambda *_args, **_kwargs: pytest.fail("network must not run"),
            sleep_fn=lambda _: None,
        )
