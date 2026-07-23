from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import sys

import pytest

import weather.reporting.research.cfsv2_pressure_research as cfsv2
from weather.market.market_registry import MarketSpec
from weather.reporting.research.cfsv2_pressure_research import (
    InventoryMessage,
    archive_urls,
    assert_cutoff_safe,
    buffered_available_time,
    build_scratch_backfill,
    decode_selected_range,
    enrich_selected_rows,
    feature_issue_time,
    fetch_or_load,
    load_eccodes,
    parse_inventory,
    selected_inventory_span,
)
from weather.sources.forecast_history import RICH_FORECAST_COLUMNS, write_csv


def _spec(
    market_id: str,
    *,
    station: str,
    timezone_name: str,
    unit: str = "C",
) -> MarketSpec:
    return MarketSpec(
        id=market_id,
        city_label=market_id,
        slug_prefix=f"{market_id}-slug",
        timezone=timezone_name,
        display_unit=unit,
        wu_history_id=f"{station}:9:XX",
        icao=station,
        lat=43.0,
        lon=-79.0,
        sources=("wu_history", "open_meteo"),
        leading_obs="wu_history",
    )


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeEccodes:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = list(messages)
        self.index = 0
        self.released = 0

    def codes_grib_new_from_file(self, source):
        del source
        if self.index >= len(self.messages):
            return None
        handle = self.messages[self.index]
        self.index += 1
        return handle

    @staticmethod
    def codes_get(handle, key):
        return handle[key]

    @staticmethod
    def codes_grib_find_nearest(handle, lat, lon):
        del handle, lat, lon
        return [{"value": 283.15, "lat": 43.0, "lon": -79.0, "distance": 4.0}]

    def codes_release(self, handle):
        del handle
        self.released += 1


def _grib_message(*, step: int, level: int = 850) -> dict[str, object]:
    issue = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    valid = issue + timedelta(hours=step)
    return {
        "shortName": "t",
        "units": "K",
        "typeOfLevel": "isobaricInhPa",
        "level": level,
        "stepType": "instant",
        "gridType": "regular_ll",
        "Ni": 360,
        "Nj": 181,
        "iDirectionIncrementInDegrees": 1.0,
        "jDirectionIncrementInDegrees": 1.0,
        "dataDate": 20260101,
        "dataTime": 1800,
        "forecastTime": step,
        "validityDate": int(valid.strftime("%Y%m%d")),
        "validityTime": int(valid.strftime("%H%M")),
    }


def test_two_day_18z_cycle_plus_buffer_is_strictly_before_all_local_cutoffs():
    specs = (
        _spec("east", station="KEEE", timezone_name="America/Toronto"),
        _spec("west", station="KWWW", timezone_name="America/Los_Angeles"),
    )
    target = date(2026, 7, 22)
    issue = feature_issue_time(target)

    assert issue == datetime(2026, 7, 20, 18, tzinfo=timezone.utc)
    assert buffered_available_time(issue) == datetime(
        2026, 7, 21, 6, tzinfo=timezone.utc
    )
    assert_cutoff_safe(target, issue, specs)


def test_cutoff_check_uses_the_supplied_local_cutoff_exactly():
    spec = _spec("utc", station="KUTC", timezone_name="UTC")
    target = date(2026, 7, 22)
    issue = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="not strictly before"):
        assert_cutoff_safe(target, issue, (spec,), cutoff_local="00:00")
    assert_cutoff_safe(target, issue, (spec,), cutoff_local="00:01")


def test_cutoff_check_rejects_naive_issue_times_and_zoned_local_cutoffs():
    target = date(2026, 7, 22)
    spec = _spec("east", station="KEEE", timezone_name="America/Toronto")

    with pytest.raises(ValueError, match="timezone-aware"):
        assert_cutoff_safe(target, datetime(2026, 7, 21, 12), (spec,))
    with pytest.raises(ValueError, match="must not contain a timezone offset"):
        assert_cutoff_safe(
            target,
            feature_issue_time(target),
            (spec,),
            cutoff_local="00:00-04:00",
        )


def test_archive_url_is_bound_to_nominal_cycle_and_control_member():
    grib, inventory = archive_urls(
        datetime(2024, 6, 15, 0, tzinfo=timezone.utc)
    )
    expected_root = (
        "https://www.ncei.noaa.gov/data/climate-forecast-system/access/"
        "operational-9-month-forecast/time-series/2024/202406/20240615/2024061500/"
        "t850.01.2024061500.daily"
    )
    assert grib == f"{expected_root}.grb2"
    assert inventory == f"{expected_root}.inv"


def test_inventory_parser_and_span_cover_eastern_and_pacific_local_days():
    inventory = "\n".join(
        f"{index}:{index * 100}:d=2026010118:TMP:850 mb:{step} hour fcst:"
        for index, step in enumerate(range(6, 72, 6), start=1)
    )
    messages = parse_inventory(inventory)
    specs = (
        _spec("east", station="KEEE", timezone_name="America/Toronto"),
        _spec("west", station="KWWW", timezone_name="America/Los_Angeles"),
    )

    selected, start, end = selected_inventory_span(
        messages,
        target_date=date(2026, 1, 3),
        issue_time=feature_issue_time(date(2026, 1, 3)),
        specs=specs,
    )

    assert [message.step_hours for message in selected] == [36, 42, 48, 54, 60]
    assert start == 600
    assert end == 1099


def test_inventory_rejects_non_monotonic_offsets():
    text = "\n".join(
        (
            "1:100:d=2026010212:TMP:850 mb:6 hour fcst:",
            "2:100:d=2026010212:TMP:850 mb:12 hour fcst:",
        )
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_inventory(text)


def test_inventory_rejects_wrong_cycle_and_non_six_hour_steps():
    text = "\n".join(
        (
            "1:0:d=2026010212:TMP:850 mb:6 hour fcst:",
            "2:100:d=2026010212:TMP:850 mb:13 hour fcst:",
        )
    )
    with pytest.raises(ValueError, match="positive 6-hour"):
        parse_inventory(text)

    valid = "\n".join(
        (
            "1:0:d=2026010212:TMP:850 mb:6 hour fcst:",
            "2:100:d=2026010212:TMP:850 mb:12 hour fcst:",
        )
    )
    with pytest.raises(ValueError, match="does not match the requested cycle"):
        parse_inventory(
            valid,
            expected_issue_time=datetime(2026, 1, 2, 18, tzinfo=timezone.utc),
        )


def test_inventory_rejects_gaps_in_message_numbers_and_mixed_cycles():
    with pytest.raises(ValueError, match="not contiguous"):
        parse_inventory(
            "\n".join(
                (
                    "1:0:d=2026010212:TMP:850 mb:6 hour fcst:",
                    "3:100:d=2026010212:TMP:850 mb:12 hour fcst:",
                )
            )
        )
    with pytest.raises(ValueError, match="mixed nominal issue"):
        parse_inventory(
            "\n".join(
                (
                    "1:0:d=2026010212:TMP:850 mb:6 hour fcst:",
                    "2:100:d=2026010218:TMP:850 mb:12 hour fcst:",
                )
            )
        )


def test_bounded_fetch_requires_exact_content_range_and_records_provenance(tmp_path):
    content = b"0123456789"
    path = tmp_path / "span.grb2"

    loaded, record, fetched = fetch_or_load(
        path=path,
        url="https://example.test/span.grb2",
        byte_range=(100, 109),
        attempts=1,
        request_get=lambda *args, **kwargs: _Response(
            content,
            status_code=206,
            headers={
                "Content-Range": "bytes 100-109/1000",
                "ETag": '"example"',
                "Last-Modified": "Wed, 22 Jul 2026 12:00:00 GMT",
            },
        ),
        sleep_fn=lambda _: None,
    )

    assert loaded == content
    assert fetched is True
    assert record["content_range"] == "bytes 100-109/1000"
    assert record["etag"] == '"example"'
    assert record["last_modified"] == "Wed, 22 Jul 2026 12:00:00 GMT"
    assert record["sha256"] == cfsv2.sha256_bytes(content)
    assert record["local_mtime_utc"]


@pytest.mark.parametrize(
    "header",
    (None, "bytes 101-110/1000", "not-a-content-range", "bytes 100-109/109"),
)
def test_bounded_fetch_rejects_missing_or_incorrect_content_range(tmp_path, header):
    headers = {} if header is None else {"Content-Range": header}
    with pytest.raises(ValueError, match="Content-Range"):
        fetch_or_load(
            path=tmp_path / "span.grb2",
            url="https://example.test/span.grb2",
            byte_range=(100, 109),
            attempts=1,
            request_get=lambda *args, **kwargs: _Response(
                b"0123456789",
                status_code=206,
                headers=headers,
            ),
            sleep_fn=lambda _: None,
        )
    assert not (tmp_path / "span.grb2").exists()


def test_bounded_fetch_rejects_wrong_length_for_fresh_and_cached_ranges(tmp_path):
    with pytest.raises(ValueError, match="wrong length"):
        fetch_or_load(
            path=tmp_path / "fresh.grb2",
            url="https://example.test/span.grb2",
            byte_range=(100, 109),
            attempts=1,
            request_get=lambda *args, **kwargs: _Response(
                b"short",
                status_code=206,
                headers={"Content-Range": "bytes 100-109/1000"},
            ),
            sleep_fn=lambda _: None,
        )

    cached = tmp_path / "cached.grb2"
    cached.write_bytes(b"short")
    with pytest.raises(ValueError, match="wrong length"):
        fetch_or_load(
            path=cached,
            url="https://example.test/span.grb2",
            byte_range=(100, 109),
            attempts=1,
            request_get=lambda *args, **kwargs: pytest.fail("cache must be reused"),
            sleep_fn=lambda _: None,
        )


def test_normal_eccodes_import_does_not_mutate_process_search_path(monkeypatch):
    sentinel = object()
    before = list(sys.path)
    monkeypatch.setattr(
        cfsv2.importlib,
        "import_module",
        lambda name: sentinel if name == "eccodes" else pytest.fail(name),
    )

    assert load_eccodes() is sentinel
    assert sys.path == before


def test_decoder_binds_cycle_step_valid_time_level_and_temperature(tmp_path):
    path = tmp_path / "span.grb2"
    path.write_bytes(b"placeholder")
    issue = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    expected = [
        InventoryMessage(6, 600, "2026010118", 36),
        InventoryMessage(7, 700, "2026010118", 42),
    ]
    eccodes = _FakeEccodes([_grib_message(step=36), _grib_message(step=42)])
    spec = _spec("utc", station="KUTC", timezone_name="UTC")

    decoded, audit = decode_selected_range(
        path,
        target_date=date(2026, 1, 3),
        specs=(spec,),
        eccodes=eccodes,
        issue_time=issue,
        expected_messages=expected,
    )

    assert audit["decoded_messages"] == 2
    assert audit["forecast_steps_hours"] == [36, 42]
    assert audit["reference_times_utc"] == [issue.isoformat(), issue.isoformat()]
    assert audit["valid_times_utc"] == [
        "2026-01-03T06:00:00+00:00",
        "2026-01-03T12:00:00+00:00",
    ]
    assert audit["grid"] == {
        "grid_type": "regular_ll",
        "longitude_points": 360,
        "latitude_points": 181,
        "longitude_increment_degrees": 1.0,
        "latitude_increment_degrees": 1.0,
    }
    assert decoded["utc"]["2026-01-03T06:00:00+00:00"][
        "temperature_850_c"
    ] == pytest.approx(10.0)
    assert eccodes.released == 2


def test_decoder_rejects_wrong_pressure_level_and_releases_handle(tmp_path):
    path = tmp_path / "span.grb2"
    path.write_bytes(b"placeholder")
    eccodes = _FakeEccodes([_grib_message(step=36, level=925)])
    spec = _spec("utc", station="KUTC", timezone_name="UTC")

    with pytest.raises(ValueError, match="pressure level"):
        decode_selected_range(
            path,
            target_date=date(2026, 1, 3),
            specs=(spec,),
            eccodes=eccodes,
            issue_time=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
            expected_messages=[InventoryMessage(6, 600, "2026010118", 36)],
        )
    assert eccodes.released == 1


def test_decoder_rejects_wrong_grid_contract(tmp_path):
    path = tmp_path / "span.grb2"
    path.write_bytes(b"placeholder")
    message = _grib_message(step=36)
    message["Ni"] = 720
    eccodes = _FakeEccodes([message])
    spec = _spec("utc", station="KUTC", timezone_name="UTC")

    with pytest.raises(ValueError, match="grid contract"):
        decode_selected_range(
            path,
            target_date=date(2026, 1, 3),
            specs=(spec,),
            eccodes=eccodes,
            issue_time=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
            expected_messages=[InventoryMessage(6, 600, "2026010118", 36)],
        )
    assert eccodes.released == 1


def test_decoder_rejects_inventory_step_mismatch(tmp_path):
    path = tmp_path / "span.grb2"
    path.write_bytes(b"placeholder")
    eccodes = _FakeEccodes([_grib_message(step=42)])
    spec = _spec("utc", station="KUTC", timezone_name="UTC")

    with pytest.raises(ValueError, match="forecast steps do not match"):
        decode_selected_range(
            path,
            target_date=date(2026, 1, 3),
            specs=(spec,),
            eccodes=eccodes,
            issue_time=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
            expected_messages=[InventoryMessage(6, 600, "2026010118", 36)],
        )


def test_enrichment_writes_850_temperature_in_market_native_unit(tmp_path):
    spec = _spec(
        "fahrenheit",
        station="KFFF",
        timezone_name="America/New_York",
        unit="F",
    )
    source = tmp_path / "forecast_long.csv"
    row = {field: "" for field in RICH_FORECAST_COLUMNS}
    row.update(
        {
            "schema_version": "forecast_history_long_v3",
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_previous_runs",
            "source_model": "best_match",
            "temperature_unit": "F",
            "target_date": "2026-01-03",
            "issue_time": "2026-01-02T23:00:00-05:00",
            "issue_time_basis": "fixed_lead_day_offset",
            "valid_time": "2026-01-03T13:00:00-05:00",
            "forecast_kind": "hourly",
            "target_temp_native": "68",
            "target_temp_c": "20",
        }
    )
    write_csv(source, RICH_FORECAST_COLUMNS, [row])
    selected = [
        {
            "target_date": "2026-01-03",
            "selected_issue_time": row["issue_time"],
            "source": row["source"],
            "source_model": row["source_model"],
        }
    ]
    enriched, coverage = enrich_selected_rows(
        source,
        spec=spec,
        selected_rows=selected,
        values_by_date={
            "2026-01-03": {
                row["valid_time"]: {"temperature_850_c": 10.0}
            }
        },
    )

    assert len(enriched) == 1
    assert float(enriched[0]["temperature_850hpa"]) == pytest.approx(50.0)
    assert coverage["selected_market_dates"] == 1
    assert coverage["supported_market_dates"] == 1
    assert coverage["temperature_850_nonnull_rows"] == 1


def test_enrichment_preserves_celsius_and_rejects_row_market_unit_mismatch(tmp_path):
    spec = _spec(
        "celsius",
        station="KCCC",
        timezone_name="America/Toronto",
        unit="C",
    )
    source = tmp_path / "forecast_long.csv"
    row = {field: "" for field in RICH_FORECAST_COLUMNS}
    row.update(
        {
            "schema_version": "forecast_history_long_v3",
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_previous_runs",
            "source_model": "best_match",
            "temperature_unit": "C",
            "target_date": "2026-01-03",
            "issue_time": "2026-01-02T23:00:00-05:00",
            "issue_time_basis": "fixed_lead_day_offset",
            "valid_time": "2026-01-03T13:00:00-05:00",
            "forecast_kind": "hourly",
            "target_temp_native": "20",
            "target_temp_c": "20",
        }
    )
    write_csv(source, RICH_FORECAST_COLUMNS, [row])
    selected = [
        {
            "target_date": row["target_date"],
            "selected_issue_time": row["issue_time"],
            "source": row["source"],
            "source_model": row["source_model"],
        }
    ]
    values = {
        row["target_date"]: {
            row["valid_time"]: {"temperature_850_c": 10.0}
        }
    }

    enriched, _ = enrich_selected_rows(
        source,
        spec=spec,
        selected_rows=selected,
        values_by_date=values,
    )
    assert float(enriched[0]["temperature_850hpa"]) == pytest.approx(10.0)

    row["temperature_unit"] = "F"
    write_csv(source, RICH_FORECAST_COLUMNS, [row])
    with pytest.raises(ValueError, match="does not match its market"):
        enrich_selected_rows(
            source,
            spec=spec,
            selected_rows=selected,
            values_by_date=values,
        )


def test_backfill_rejects_output_inside_source_root_before_any_read_or_network(tmp_path):
    source_root = tmp_path / "data"
    source_root.mkdir()

    with pytest.raises(ValueError, match="resolves inside"):
        build_scratch_backfill(
            source_data_root=source_root,
            output_root=source_root / "scratch",
            eccodes_path=None,
            specs=(),
            request_get=lambda *args, **kwargs: pytest.fail(
                "path guard must run before network access"
            ),
        )
    assert not (source_root / "scratch").exists()


def test_selected_baseline_provenance_includes_exact_source_hashes(
    tmp_path, monkeypatch
):
    forecast = tmp_path / "forecast.csv"
    settlement = tmp_path / "settlement.csv"
    forecast.write_bytes(b"forecast-input")
    settlement.write_bytes(b"settlement-input")
    spec = _spec("market", station="KAAA", timezone_name="UTC")

    def fake_load_market_rows(**kwargs):
        assert kwargs["data_root"] == tmp_path
        return (
            [],
            {
                "market_id": spec.id,
                "provenance": {
                    "forecast_history": {"path": str(forecast)},
                    "wu_daily_summary": {"path": str(settlement)},
                },
            },
            [],
        )

    monkeypatch.setattr(cfsv2, "load_market_rows", fake_load_market_rows)
    _, _, audits = cfsv2._selected_baselines(tmp_path, (spec,), "00:00")

    provenance = audits[0]["provenance"]
    assert provenance["forecast_history"]["sha256"] == cfsv2.sha256_file(
        forecast
    )
    assert provenance["wu_daily_summary"]["sha256"] == cfsv2.sha256_file(
        settlement
    )


def test_inventory_message_value_object_is_immutable():
    message = InventoryMessage(1, 0, "2026010212", 6)
    with pytest.raises(AttributeError):
        message.offset = 1
