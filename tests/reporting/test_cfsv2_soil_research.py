from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

import weather.reporting.research.cfsv2_soil_research as soil
from weather.market.market_registry import MarketSpec
from weather.reporting.research.cfsv2_pressure_research import InventoryMessage
from weather.reporting.research.cfsv2_soil_research import (
    SOIL_VARIABLES,
    archive_urls,
    build_scratch_backfill,
    decode_selected_range,
    enrich_selected_rows,
    freeze_availability_contract,
    parse_inventory,
)
from weather.sources.forecast_history import RICH_FORECAST_COLUMNS, write_csv


def _spec(*, unit: str = "C") -> MarketSpec:
    return MarketSpec(
        id="test-market",
        city_label="Test",
        slug_prefix="test-market",
        timezone="UTC",
        display_unit=unit,
        wu_history_id="KAAA:9:XX",
        icao="KAAA",
        lat=43.0,
        lon=-79.0,
        sources=("wu_history", "open_meteo"),
        leading_obs="wu_history",
    )


class _Response:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class _FakeEccodes:
    def __init__(self, messages):
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
    def codes_grib_find_nearest(handle, lat, lon, npoints=1):
        del lat, lon
        assert npoints == 4
        return [
            {
                "value": handle["nearest_value"],
                "lat": 43.9368,
                "lon": 280.3121,
                "distance": 29.255,
            }
        ] * 4

    def codes_release(self, handle):
        del handle
        self.released += 1


def _message(variable, *, step: int = 36, bottom_scaled: int = 10, units=None):
    issue = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    valid = issue + timedelta(hours=step)
    return {
        "shortName": variable.short_name,
        "units": units or variable.units,
        "typeOfLevel": "depthBelowLandLayer",
        "scaledValueOfFirstFixedSurface": 0,
        "scaleFactorOfFirstFixedSurface": 2,
        "scaledValueOfSecondFixedSurface": bottom_scaled,
        "scaleFactorOfSecondFixedSurface": 2,
        "stepType": "instant",
        "gridType": "regular_gg",
        "Ni": 384,
        "Nj": 190,
        "iDirectionIncrementInDegrees": 0.938,
        "dataDate": 20260101,
        "dataTime": 1800,
        "forecastTime": step,
        "validityDate": int(valid.strftime("%Y%m%d")),
        "validityTime": int(valid.strftime("%H%M")),
        "nearest_value": 283.15 if variable.archive_name == "soilt1" else 0.3376,
    }


@pytest.mark.parametrize("variable", SOIL_VARIABLES)
def test_archive_urls_bind_exact_variable_member_and_cycle(variable):
    grib, inventory = archive_urls(
        variable, datetime(2024, 6, 15, 18, tzinfo=timezone.utc)
    )
    stem = f"{variable.archive_name}.01.2024061518.daily"
    assert grib.endswith(f"/2024061518/{stem}.grb2")
    assert inventory.endswith(f"/2024061518/{stem}.inv")


@pytest.mark.parametrize("variable", SOIL_VARIABLES)
def test_inventory_parser_binds_field_depth_cycle_and_six_hour_steps(variable):
    text = "\n".join(
        f"{index}:{index * 100}:d=2026010118:{variable.inventory_name}:"
        f"0-0.1 m below ground:{step} hour fcst:"
        for index, step in enumerate((6, 12, 18), start=1)
    )
    parsed = parse_inventory(
        text,
        variable=variable,
        expected_issue_time=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
    )
    assert [item.step_hours for item in parsed] == [6, 12, 18]

    wrong_depth = text.replace("0-0.1 m", "0.1-0.4 m")
    with pytest.raises(ValueError, match="no exact 0-0.1 m"):
        parse_inventory(wrong_depth, variable=variable)

    wrong_step = text.replace("18 hour", "19 hour")
    with pytest.raises(ValueError, match="positive 6-hour"):
        parse_inventory(wrong_step, variable=variable)


def test_availability_contract_freezes_complete_pair_before_decode(tmp_path):
    targets = ["2026-05-10", "2026-05-11"]

    def fake_head(url, **kwargs):
        assert kwargs["allow_redirects"] is True
        if "2026050918" in url and "soilm1" in url:
            return _Response(404)
        return _Response(
            200,
            {
                "Content-Length": "1234",
                "ETag": '"frozen"',
                "Last-Modified": "Wed, 22 Jul 2026 12:00:00 GMT",
            },
        )

    path = tmp_path / "availability.json"
    payload = freeze_availability_contract(
        target_dates=targets,
        output_path=path,
        attempts=1,
        workers=2,
        request_head=fake_head,
        sleep_fn=lambda _: None,
    )

    assert payload["complete_pair_target_dates"] == ["2026-05-10"]
    assert payload["complete_pair_date_count"] == 1
    assert payload["missing_pair_date_count"] == 1
    assert payload["frozen_before_grib_decode"] is True
    assert len(payload["contract_sha256"]) == 64
    assert json.loads(path.read_text(encoding="utf-8"))["contract_sha256"] == payload[
        "contract_sha256"
    ]


@pytest.mark.parametrize("variable", SOIL_VARIABLES)
def test_decoder_binds_variable_depth_time_grid_unit_and_value(tmp_path, variable):
    path = tmp_path / f"{variable.archive_name}.grb2"
    path.write_bytes(b"placeholder")
    issue = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    expected = [InventoryMessage(6, 600, "2026010118", 36)]
    eccodes = _FakeEccodes([_message(variable)])

    decoded, audit = decode_selected_range(
        path,
        variable=variable,
        target_date=date(2026, 1, 3),
        specs=(_spec(),),
        eccodes=eccodes,
        issue_time=issue,
        expected_messages=expected,
    )

    row = decoded["test-market"]["2026-01-03T06:00:00+00:00"]
    expected_value = 10.0 if variable.archive_name == "soilt1" else 0.3376
    assert row[variable.decoded_key] == pytest.approx(expected_value)
    assert audit["physical_depth_m"] == [0.0, 0.1]
    assert audit["forecast_steps_hours"] == [36]
    assert audit["grid"]["grid_type"] == "regular_gg"
    assert eccodes.released == 1


def test_decoder_rejects_wrong_depth_unit_and_implausible_moisture(tmp_path):
    path = tmp_path / "soil.grb2"
    path.write_bytes(b"placeholder")
    issue = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    expected = [InventoryMessage(6, 600, "2026010118", 36)]

    with pytest.raises(ValueError, match="depth layer"):
        decode_selected_range(
            path,
            variable=SOIL_VARIABLES[0],
            target_date=date(2026, 1, 3),
            specs=(_spec(),),
            eccodes=_FakeEccodes([_message(SOIL_VARIABLES[0], bottom_scaled=40)]),
            issue_time=issue,
            expected_messages=expected,
        )

    with pytest.raises(ValueError, match="unit"):
        decode_selected_range(
            path,
            variable=SOIL_VARIABLES[0],
            target_date=date(2026, 1, 3),
            specs=(_spec(),),
            eccodes=_FakeEccodes([_message(SOIL_VARIABLES[0], units="degC")]),
            issue_time=issue,
            expected_messages=expected,
        )

    bad = _message(SOIL_VARIABLES[1])
    bad["nearest_value"] = 1.2
    with pytest.raises(ValueError, match="soil moisture"):
        decode_selected_range(
            path,
            variable=SOIL_VARIABLES[1],
            target_date=date(2026, 1, 3),
            specs=(_spec(),),
            eccodes=_FakeEccodes([bad]),
            issue_time=issue,
            expected_messages=expected,
        )


def test_enrichment_pairs_fields_and_converts_temperature_to_market_unit(tmp_path):
    spec = _spec(unit="F")
    path = tmp_path / "forecast_long.csv"
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
            "issue_time": "2026-01-02T00:00:00+00:00",
            "valid_time": "2026-01-03T06:00:00+00:00",
            "target_temp_native": "68",
            "target_temp_c": "20",
        }
    )
    write_csv(path, RICH_FORECAST_COLUMNS, [row])
    selected = [
        {
            "target_date": row["target_date"],
            "selected_issue_time": row["issue_time"],
            "source": row["source"],
            "source_model": row["source_model"],
        }
    ]
    enriched, coverage = enrich_selected_rows(
        path,
        spec=spec,
        selected_rows=selected,
        values_by_date={
            row["target_date"]: {
                row["valid_time"]: {
                    "soil_temperature_c": 10.0,
                    "soil_moisture_proportion": 0.25,
                }
            }
        },
    )

    assert float(enriched[0]["soil_temperature_0cm"]) == pytest.approx(50.0)
    assert float(enriched[0]["soil_moisture_0_to_1cm"]) == pytest.approx(0.25)
    assert coverage["supported_market_dates"] == 1
    assert coverage["soil_temperature_nonnull_rows"] == 1
    assert coverage["soil_moisture_nonnull_rows"] == 1

    unpaired = {
        row["target_date"]: {row["valid_time"]: {"soil_temperature_c": 10.0}}
    }
    with pytest.raises(ValueError, match="unpaired"):
        enrich_selected_rows(
            path,
            spec=spec,
            selected_rows=selected,
            values_by_date=unpaired,
        )


def test_backfill_rejects_output_inside_source_root_before_read_or_network(tmp_path):
    source = tmp_path / "data"
    source.mkdir()
    with pytest.raises(ValueError, match="resolves inside"):
        build_scratch_backfill(
            source_data_root=source,
            output_root=source / "scratch",
            eccodes_path=None,
            specs=(),
            request_head=lambda *args, **kwargs: pytest.fail("must not probe"),
            request_get=lambda *args, **kwargs: pytest.fail("must not fetch"),
        )
    assert not (source / "scratch").exists()
