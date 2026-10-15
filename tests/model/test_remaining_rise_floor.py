"""t3-r3 stage ``remaining_rise_floor_v1``: band map, floor mask, fallbacks, cell key, frozen artifact.

Guards: remaining-rise 13-16 pre-registration §1 (t3-r3 rule, d2-r3f serve form) and owner
OD-B1/OD-B2 (2026-10-15): the stage artifact hash is frozen and bound in config/remaining_rise_floor_stage.json.
"""

import json
import math
from datetime import date, datetime, timezone

import pytest

from weather.artifacts import resolve_artifact_path
from weather.calibration import remaining_rise_pmf as builder
from weather.model import remaining_rise_floor as stage
from weather.paths import config_path

BANDS = [
    stage.Band("lte", 79, 79),
    stage.Band("eq", 80, 81),
    stage.Band("eq", 82, 83),
    stage.Band("gte", 84, 84),
]
SERVED = [0.1, 0.3, 0.4, 0.2]
CELL = stage.RiseCell("KLGA", 6, 14, 0, (0.5, 0.3, 0.2), 30)


def _apply(**overrides):
    kwargs = {
        "floor": 80.2,
        "cell": CELL,
        "metar_stale": False,
        "on_target_date": True,
        "artifact_sha256": stage.ARTIFACT_SHA256,
        "unit": "F",
    }
    bands = overrides.pop("bands", BANDS)
    served = overrides.pop("served", SERVED)
    kwargs.update(overrides)
    return stage.apply(bands, served, **kwargs)


class TestBandMap:
    def test_band_probs_anchor_at_bucket_plus_base(self):
        assert stage.band_probs(BANDS, 80, [0.5, 0.3, 0.2]) == pytest.approx([0.0, 0.8, 0.2, 0.0], abs=1e-15)
        assert stage.band_probs(BANDS, 82, [0.5, 0.3, 0.2]) == pytest.approx([0.0, 0.0, 0.8, 0.2], abs=1e-15)

    def test_lte_and_gte_take_open_tails(self):
        bands = [stage.Band("lte", 81, 81), stage.Band("gte", 82, 82)]
        assert stage.band_probs(bands, 78, [0.25] * 8) == pytest.approx([1.0, 1.0], abs=1e-15)

    def test_band_from_row_maps_legacy_c_names_to_native_limits(self):
        assert stage.band_from_row({"bin_kind": "eq", "bin_value_c": 80, "bin_value_hi_c": 81}) == stage.Band("eq", 80, 81)
        assert stage.band_from_row({"bin_kind": "gte", "bin_value_c": 84, "bin_value_hi_c": None}) == stage.Band("gte", 84, 84)
        with pytest.raises(ValueError, match="invalid_band_kind"):
            stage.band_from_row({"bin_kind": "range", "bin_value_c": 80, "bin_value_hi_c": 81})
        with pytest.raises(ValueError, match="noninteger_band_limits"):
            stage.band_from_row({"bin_kind": "eq", "bin_value_c": 80.5, "bin_value_hi_c": 81})

    def test_floor_mask_is_non_gte_high_below_bucket(self):
        assert stage.floor_impossible(BANDS, 82) == [True, True, False, False]
        assert stage.floor_impossible(BANDS, 81) == [True, False, False, False]
        assert stage.floor_impossible(BANDS, 90) == [True, True, True, False]


class TestApply:
    def test_stage_vector_from_round_half_up_bucket(self):
        result = _apply(floor=80.49)
        assert result.status == stage.STATUS_STAGE and result.reason is None
        assert result.floor_bucket == 80
        assert list(result.vector) == pytest.approx([0.0, 0.8, 0.2, 0.0], abs=1e-15)
        result = _apply(floor=80.5)
        assert result.floor_bucket == 81
        assert list(result.vector) == pytest.approx([0.0, 0.5, 0.5, 0.0], abs=1e-15)

    def test_renormalises_only_beyond_tolerance(self):
        gap_bands = [stage.Band("lte", 79, 79), stage.Band("eq", 80, 80), stage.Band("gte", 82, 82)]
        result = _apply(bands=gap_bands, served=[0.2, 0.3, 0.5], floor=80.0)
        assert list(result.vector) == pytest.approx([0.0, 0.5 / 0.7, 0.2 / 0.7], abs=1e-15)
        near = stage.RiseCell("KLGA", 6, 14, 0, (1.0 - 1e-13,), 1)
        assert _apply(cell=near, floor=80.0).vector[1] == 1.0 - 1e-13
        far = stage.RiseCell("KLGA", 6, 14, 0, (1.0 - 1e-11,), 1)
        assert _apply(cell=far, floor=80.0).vector[1] == 1.0

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"unit": "C"}, "unit_not_fahrenheit"),
            ({"artifact_sha256": "0" * 64}, "artifact_hash_mismatch"),
            ({"artifact_sha256": None}, "artifact_hash_mismatch"),
            ({"on_target_date": False}, "snapshot_not_on_target_date"),
            ({"floor": None}, "missing_floor"),
            ({"floor": math.nan}, "missing_floor"),
            ({"metar_stale": True}, "metar_stale"),
            ({"cell": None}, "missing_cell"),
        ],
    )
    def test_each_fallback_returns_the_served_vector_unchanged(self, overrides, reason):
        result = _apply(**overrides)
        assert result.status == stage.STATUS_FALLBACK
        assert result.reason == reason
        assert list(result.vector) == SERVED

    def test_zero_mass_needs_no_band_reaching_the_bucket(self):
        bands = [stage.Band("lte", 79, 79), stage.Band("eq", 80, 81)]
        assert _apply(bands=bands, served=[0.5, 0.5], floor=81.0).status == stage.STATUS_STAGE
        assert _apply(bands=bands, served=[0.5, 0.5], floor=82.0).reason == "zero_mass_after_floor"

    def test_length_mismatch_is_a_programming_error(self):
        with pytest.raises(ValueError):
            _apply(served=[1.0])


class TestInputs:
    def test_floor_value_is_max_of_finite_floor_fields(self):
        assert stage.floor_value({"guidance_physical_floor": 78.0, "high_so_far": 80.2, "trusted_current_max": None}) == 80.2
        assert stage.floor_value({"guidance_physical_floor": 81.0, "high_so_far": math.inf}) == 81.0
        assert stage.floor_value({"guidance_physical_floor": True, "other": 99.0}) is None
        assert stage.floor_value({}) is None
        assert stage.floor_value(None) is None

    def test_cell_key_uses_local_clock_hour_and_target_month(self):
        key = stage.cell_key("klga", "America/New_York", datetime(2026, 6, 18, 14, 0, tzinfo=timezone.utc), date(2026, 6, 18))
        assert (key.station, key.month, key.hour, key.on_target_date) == ("KLGA", 6, 10, True)

    def test_cell_key_target_date_boundary(self):
        late = stage.cell_key("KLGA", "America/New_York", datetime(2026, 6, 19, 3, 59, tzinfo=timezone.utc), "2026-06-18")
        assert (late.hour, late.captured_local_date, late.on_target_date) == (23, "2026-06-18", True)
        after = stage.cell_key("KLGA", "America/New_York", datetime(2026, 6, 19, 4, 0, tzinfo=timezone.utc), "2026-06-18")
        assert (after.hour, after.on_target_date) == (0, False)

    def test_cell_key_follows_dst(self):
        edt = stage.cell_key("KLGA", "America/New_York", datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc), "2026-11-01")
        est = stage.cell_key("KLGA", "America/New_York", datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc), "2026-11-01")
        assert (edt.hour, est.hour) == (1, 1)
        spring = stage.cell_key("KLGA", "America/New_York", datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc), "2026-03-08")
        assert spring.hour == 3

    def test_cell_key_without_timezone_cannot_match(self):
        naive = stage.cell_key("KLGA", "America/New_York", datetime(2026, 6, 18, 14, 0), "2026-06-18")
        assert (naive.hour, naive.on_target_date) == (None, False)
        no_tz = stage.cell_key("KLGA", None, datetime(2026, 6, 18, 14, 0, tzinfo=timezone.utc), "2026-06-18")
        assert no_tz.hour is None


class TestFrozenArtifact:
    def test_committed_artifact_hash_is_the_bound_hash(self):
        table = stage.load_table()
        assert table.sha256 == stage.ARTIFACT_SHA256

    def test_artifact_shape(self):
        document = json.loads(resolve_artifact_path(stage.ARTIFACT_FILENAME).read_text(encoding="utf-8"))
        table = stage.load_table()
        assert document["cell_count"] == len(table.cells) == 3036
        assert {station for station, _, _ in table.cells} == set(builder.STATION_TIMEZONES)
        assert all(hour != 0 for _, _, hour in table.cells)
        for cell in table.cells.values():
            assert cell.base >= 0 and cell.n_days > 0
            assert abs(sum(cell.pmf) - 1.0) < 1e-9

    def test_artifact_records_the_current_builder(self):
        document = json.loads(resolve_artifact_path(stage.ARTIFACT_FILENAME).read_text(encoding="utf-8"))
        assert document["build_code_sha256"] == builder.build_code_sha256(), (
            "remaining_rise_pmf.py changed: rebuild the artifact and re-bind ARTIFACT_SHA256 and the frozen config"
        )
        assert document["definition"] == builder.DEFINITION
        assert document["registry_sha256"] == stage.REGISTRY_SHA256 == builder.REGISTRY_SHA256

    def test_parse_table_rejects_other_artifacts(self):
        with pytest.raises(ValueError):
            stage.parse_table(json.dumps({"artifact_id": "other", "unit": "F"}).encode())
        with pytest.raises(ValueError):
            stage.parse_table(json.dumps({"artifact_id": stage.ARTIFACT_ID, "unit": "C"}).encode())
        bad = {"artifact_id": stage.ARTIFACT_ID, "unit": "F",
               "cells": {"KLGA": {"6": {"14": {"base": 0, "n_days": 1, "pmf": [1.5, -0.5]}}}}}
        with pytest.raises(ValueError, match="invalid cell"):
            stage.parse_table(json.dumps(bad).encode())


class TestFrozenConfig:
    def test_frozen_config_matches_the_stage_module(self):
        frozen = json.loads(config_path("remaining_rise_floor_stage.json").read_text(encoding="utf-8"))
        assert frozen["stage_id"] == stage.STAGE_ID
        assert frozen["constants"] == stage.STAGE_CONSTANTS
        assert frozen["config_sha256"] == stage.stage_config_sha256()
        assert frozen["artifact"]["sha256"] == stage.ARTIFACT_SHA256
        assert frozen["artifact"]["build_code_sha256"] == builder.build_code_sha256()
        assert frozen["code_sha256"] == stage.stage_code_sha256(), (
            "remaining_rise_floor.py changed: a rule change needs a new stage id and pre-registration, "
            "a non-rule change needs an owner-reviewed re-freeze of config/remaining_rise_floor_stage.json"
        )
