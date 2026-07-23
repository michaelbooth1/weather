from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest

import weather.reporting.research.hrrr_smoke_research as hrrr
from weather.market.market_registry import MarketSpec
from weather.reporting.research.hrrr_smoke_research import (
    FIELDS,
    HRRR_AOD_COLUMN,
    HRRR_FORECAST_COLUMNS,
    HRRR_SMOKE_COLUMN,
    archive_urls,
    assert_cutoff_safe,
    build_scratch_backfill,
    decode_message,
    enrich_selected_rows,
    feature_issue_time,
    freeze_design_contract,
    normalize_massden_ug_m3,
    parse_index,
    select_messages,
    validate_design_contract,
)
from weather.sources.forecast_history import write_csv


def _spec(*, unit="C") -> MarketSpec:
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
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeEccodes:
    def __init__(self, message):
        self.message = message
        self.calls = 0
        self.released = 0

    def codes_grib_new_from_file(self, source):
        del source
        self.calls += 1
        return self.message if self.calls == 1 else None

    @staticmethod
    def codes_get(handle, key):
        return handle[key]

    @staticmethod
    def codes_grib_find_nearest_multiple(handle, is_lsm, lats, lons):
        assert is_lsm is False
        assert len(lats) == len(lons)
        return tuple(
            {
                "value": handle["nearest_value"],
                "lat": 43.01,
                "lon": 281.0,
                "distance": handle.get("nearest_distance", 1.2),
                "index": index,
            }
            for index, _ in enumerate(lats)
        )

    @staticmethod
    def codes_get_elements(handle, key, indexes):
        assert key == "values"
        return [handle["nearest_value"] for _ in indexes]

    def codes_release(self, handle):
        del handle
        self.released += 1


def _message(field, *, issue=None, step=18, parameter_number=None, units="unknown"):
    issue = issue or datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    valid = issue + timedelta(hours=step)
    return {
        "discipline": 0,
        "parameterCategory": 20,
        "parameterNumber": field.parameter_number if parameter_number is None else parameter_number,
        "shortName": "unknown",
        "name": "unknown",
        "units": units,
        "typeOfLevel": field.type_of_level,
        "level": field.level,
        "stepType": "instant",
        "typeOfGeneratingProcess": 2,
        "generatingProcessIdentifier": 83,
        "gridType": "lambert",
        "Nx": 1799,
        "Ny": 1059,
        "DxInMetres": 3000.0,
        "DyInMetres": 3000.0,
        "dataDate": int(issue.strftime("%Y%m%d")),
        "dataTime": int(issue.strftime("%H%M")),
        "forecastTime": step,
        "validityDate": int(valid.strftime("%Y%m%d")),
        "validityTime": int(valid.strftime("%H%M")),
        "nearest_value": 0.25 if field.name == "AOTK" else 2e-9,
    }


def _index_text(issue_text: str, step: int) -> str:
    return "\n".join(
        (
            f"1:0:d={issue_text}:MASSDEN:8 m above ground:{step} hour fcst:",
            f"2:100:d={issue_text}:UGRD:10 m above ground:{step} hour fcst:",
            f"3:200:d={issue_text}:AOTK:entire atmosphere (considered as a single layer):{step} hour fcst:",
            f"4:300:d={issue_text}:COLMD:entire atmosphere (considered as a single layer):{step} hour fcst:",
        )
    )


def test_fixed_issue_rule_cutoff_and_archive_urls():
    target = date(2026, 7, 22)
    issue = feature_issue_time(target)
    assert issue == datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    assert_cutoff_safe(target, issue, (_spec(),))
    grib, index = archive_urls(issue, 42)
    assert grib.endswith("/hrrr.20260721/conus/hrrr.t12z.wrfsfcf42.grib2")
    assert index == f"{grib}.idx"


def test_index_parser_selects_exact_fields_and_bounded_offsets():
    text = _index_text("2026010112", 18)
    messages = parse_index(
        text,
        expected_issue_time=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
    )
    selected = select_messages(messages, step_hours=18)
    assert selected["MASSDEN"].offset == 0
    assert selected["MASSDEN"].end_offset == 99
    assert selected["AOTK"].offset == 200
    assert selected["AOTK"].end_offset == 299

    with pytest.raises(ValueError, match="one exact AOTK"):
        select_messages(
            parse_index(text.replace("AOTK:", "COLMD:")), step_hours=18
        )


def test_index_parser_rejects_wrong_cycle_and_noncontiguous_messages():
    text = _index_text("2026010112", 18)
    with pytest.raises(ValueError, match="does not match"):
        parse_index(
            text,
            expected_issue_time=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="not contiguous"):
        parse_index(text.replace("3:200", "5:200"))


def test_massden_unit_boundary_is_cycle_exact_and_normalizes_to_ug_m3():
    before = datetime(2021, 12, 21, 11, 59, tzinfo=timezone.utc)
    boundary = datetime(2021, 12, 21, 12, tzinfo=timezone.utc)
    assert normalize_massden_ug_m3(4.0, before) == (
        4.0,
        "pre_boundary_numeric_ug_m3_identity",
    )
    normalized, rule = normalize_massden_ug_m3(4e-9, boundary)
    assert normalized == pytest.approx(4.0)
    assert rule == "post_boundary_numeric_kg_m3_times_1e9"
    with pytest.raises(ValueError, match="nonnegative"):
        normalize_massden_ug_m3(-1.0, boundary)


@pytest.mark.parametrize("field", FIELDS)
def test_decoder_binds_parameter_unit_level_time_grid_and_value(tmp_path, field):
    path = tmp_path / f"{field.name}.grib2"
    path.write_bytes(b"placeholder")
    issue = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    fake = _FakeEccodes(_message(field, issue=issue))
    decoded, audit = decode_message(
        path,
        field=field,
        target_date=date(2026, 1, 2),
        specs=(_spec(),),
        eccodes=fake,
        issue_time=issue,
        step_hours=18,
    )
    row = decoded["test-market"]["2026-01-02T06:00:00+00:00"]
    expected = 0.25 if field.name == "AOTK" else 2.0
    assert row[field.output_key] == pytest.approx(expected)
    assert audit["parameter"]["parameter_number"] == field.parameter_number
    assert audit["grid"]["nx"] == 1799
    assert audit["forecast_step_hours"] == 18
    assert fake.released == 1


def test_decoder_rejects_parameter_unit_and_grid_distance(tmp_path):
    path = tmp_path / "AOTK.grib2"
    path.write_bytes(b"placeholder")
    issue = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    field = next(item for item in FIELDS if item.name == "AOTK")
    for message, match in (
        (_message(field, parameter_number=999), "parameter/unit"),
        (_message(field, units="1"), "parameter/unit"),
    ):
        with pytest.raises(ValueError, match=match):
            decode_message(
                path,
                field=field,
                target_date=date(2026, 1, 2),
                specs=(_spec(),),
                eccodes=_FakeEccodes(message),
                issue_time=issue,
                step_hours=18,
            )
    far = _message(field)
    far["nearest_distance"] = 6.0
    with pytest.raises(ValueError, match="nearest-grid"):
        decode_message(
            path,
            field=field,
            target_date=date(2026, 1, 2),
            specs=(_spec(),),
            eccodes=_FakeEccodes(far),
            issue_time=issue,
            step_hours=18,
        )


def test_design_contract_freezes_fields_transform_boundary_split_and_support(
    tmp_path, monkeypatch
):
    targets = ["2026-01-02", "2026-01-03"]

    def fake_get(url, **kwargs):
        del kwargs
        step = int(re.search(r"wrfsfcf(\d+)\.grib2\.idx$", url).group(1))
        issue_text = re.search(r"hrrr\.t12z", url) and re.search(
            r"hrrr\.(\d{8})", url
        ).group(1) + "12"
        if "hrrr.20260102" in url and step == 42:
            return _Response(status_code=404)
        content = _index_text(issue_text, step).encode()
        return _Response(content, headers={"ETag": '"idx"'})

    monkeypatch.setattr(
        hrrr,
        "_split_contract",
        lambda dates: {"date_plan": {"all_dates": list(dates)}, "policy": "test"},
    )
    output_root = tmp_path / "hrrr"
    path = output_root / "design_contract.json"
    payload = freeze_design_contract(
        target_dates=targets,
        output_path=path,
        raw_root=output_root / "raw",
        specs=(_spec(),),
        attempts=1,
        workers=4,
        request_get=fake_get,
        sleep_fn=lambda _: None,
    )

    assert payload["complete_target_dates"] == ["2026-01-02"]
    assert payload["complete_date_count"] == 1
    assert payload["missing_date_count"] == 1
    assert payload["transform_contract"]["chosen_before_outcome_evaluation"] is True
    assert payload["unit_contract"]["boundary_cycle_utc"] == "2021-12-21T12:00:00+00:00"
    assert payload["acceptance_contract"]["single_opening"] is True
    assert payload["frozen_before_grib_decode"] is True
    assert len(payload["contract_sha256"]) == 64

    count_tamper = json.loads(json.dumps(payload))
    count_tamper["complete_date_count"] += 1
    with pytest.raises(ValueError, match="complete_date_count mismatch"):
        validate_design_contract(count_tamper)

    hash_tamper = json.loads(json.dumps(payload))
    hash_tamper["transform_contract"]["massden"] = "tampered"
    with pytest.raises(ValueError, match="canonical hash mismatch"):
        validate_design_contract(hash_tamper)

    path.write_text(json.dumps(hash_tamper), encoding="utf-8")
    source_root = tmp_path / "data"
    source_root.mkdir()
    with pytest.raises(ValueError, match="canonical hash mismatch"):
        build_scratch_backfill(
            source_data_root=source_root,
            output_root=output_root,
            eccodes_path=None,
            specs=(_spec(),),
            request_get=lambda *args, **kwargs: pytest.fail("must not fetch"),
        )


def test_enrichment_writes_four_honest_paired_samples(tmp_path):
    spec = _spec()
    path = tmp_path / "forecast_long.csv"
    rows = []
    valid_times = [
        "2026-01-02T00:00:00+00:00",
        "2026-01-02T06:00:00+00:00",
        "2026-01-02T12:00:00+00:00",
        "2026-01-02T18:00:00+00:00",
    ]
    for valid_time in valid_times:
        row = {field: "" for field in HRRR_FORECAST_COLUMNS}
        row.update(
            {
                "schema_version": "forecast_history_long_v3",
                "market": spec.id,
                "station": spec.icao,
                "source": "open_meteo_previous_runs",
                "source_model": "best_match",
                "temperature_unit": "C",
                "target_date": "2026-01-02",
                "issue_time": "2026-01-01T00:00:00+00:00",
                "valid_time": valid_time,
                "target_temp_native": "20",
                "target_temp_c": "20",
            }
        )
        rows.append(row)
    write_csv(path, HRRR_FORECAST_COLUMNS, rows)
    selected = [
        {
            "target_date": "2026-01-02",
            "selected_issue_time": "2026-01-01T00:00:00+00:00",
            "source": "open_meteo_previous_runs",
            "source_model": "best_match",
        }
    ]
    values = {
        "2026-01-02": {
            valid: {HRRR_AOD_COLUMN: 0.2, HRRR_SMOKE_COLUMN: 5.0}
            for valid in valid_times
        }
    }
    enriched, coverage = enrich_selected_rows(
        path,
        spec=spec,
        selected_rows=selected,
        values_by_date=values,
    )
    assert all(float(row[HRRR_AOD_COLUMN]) == pytest.approx(0.2) for row in enriched)
    assert all(float(row[HRRR_SMOKE_COLUMN]) == pytest.approx(5.0) for row in enriched)
    assert coverage["supported_market_dates"] == 1
    assert coverage["paired_nonnull_rows"] == 4


def test_backfill_path_guard_runs_before_read_or_network(tmp_path):
    source = tmp_path / "data"
    source.mkdir()
    with pytest.raises(ValueError, match="resolves inside"):
        build_scratch_backfill(
            source_data_root=source,
            output_root=source / "scratch",
            eccodes_path=None,
            specs=(),
            request_get=lambda *args, **kwargs: pytest.fail("must not fetch"),
        )
    assert not (source / "scratch").exists()
