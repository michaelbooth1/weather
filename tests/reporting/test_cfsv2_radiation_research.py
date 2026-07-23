from __future__ import annotations

import json
from datetime import date, datetime, timezone
import os
from pathlib import Path
import subprocess

import pytest

from weather.market.market_registry import BUILTIN_SPECS
from weather.reporting.research.cfsv2_radiation_research import (
    RADIATION_VARIABLES,
    archive_urls,
    build_scratch_backfill,
    derive_radiation_components,
    freeze_design_contract,
    parse_inventory,
    validate_design_contract,
)
from weather.reporting.research.cfsv2_soil_research import (
    freeze_availability_contract,
)


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


def test_archive_url_and_exact_inventory_contracts():
    issue = datetime(2024, 6, 7, 18, tzinfo=timezone.utc)
    dswrf = RADIATION_VARIABLES[0]
    grib, inventory = archive_urls(dswrf, issue)
    assert grib.endswith("/2024060718/dswsfc.01.2024060718.daily.grb2")
    assert inventory.endswith("/2024060718/dswsfc.01.2024060718.daily.inv")

    messages = parse_inventory(
        "1:0:d=2024060718:DSWRF:surface:6 hour fcst:\n"
        "2:100:d=2024060718:DSWRF:surface:12 hour fcst:\n",
        variable=dswrf,
        expected_issue_time=issue,
    )
    assert [item.step_hours for item in messages] == [6, 12]
    with pytest.raises(ValueError, match="no exact field"):
        parse_inventory(
            "1:0:d=2024060718:DSWRF:entire atmosphere:6 hour fcst:\n",
            variable=dswrf,
            expected_issue_time=issue,
        )


def test_total_cloud_inventory_uses_exact_single_layer_descriptor():
    cloud = RADIATION_VARIABLES[-1]
    messages = parse_inventory(
        "1:0:d=2024060718:TCDC:entire atmosphere (considered as a single layer):6 hour fcst:\n"
        "2:100:d=2024060718:TCDC:entire atmosphere (considered as a single layer):12 hour fcst:\n",
        variable=cloud,
    )
    assert len(messages) == 2


def test_predeclared_component_arithmetic_and_zero_clamp():
    spec = BUILTIN_SPECS[0]
    valid = "2026-05-10T08:00:00-04:00"
    common = {"grid_lat": 43.5, "grid_lon": -79.5, "distance_km": 10.0}
    decoded = {
        "dswsfc": {spec.id: {valid: {**common, "total_shortwave_w_m2": 100.0}}},
        "vddsf": {spec.id: {valid: {**common, "visible_diffuse_w_m2": 70.0}}},
        "nddsf": {spec.id: {valid: {**common, "near_ir_diffuse_w_m2": 40.0}}},
        "tcdcclm": {spec.id: {valid: {**common, "total_cloud_percent": 80.0}}},
    }
    merged, audit = derive_radiation_components(decoded, [spec])
    row = merged[spec.id][valid]
    assert row == {
        "shortwave_radiation": 100.0,
        "diffuse_radiation": 110.0,
        "direct_radiation": 0.0,
        "cloud_cover": 80.0,
    }
    assert audit["direct_zero_clamp_count"] == 1
    assert audit["minimum_unclamped_direct_w_m2"] == -10.0


def test_design_is_frozen_from_upstream_cohort_before_outcomes(tmp_path):
    upstream = tmp_path / "soil_contract.json"

    class Response:
        status_code = 200
        headers = {"Content-Length": "10"}

    freeze_availability_contract(
        target_dates=["2026-05-10", "2026-05-11"],
        output_path=upstream,
        workers=2,
        request_head=lambda *args, **kwargs: Response(),
    )
    output_root = tmp_path / "radiation"
    design = freeze_design_contract(
        upstream_contract_path=upstream,
        output_path=output_root / "design_contract.json",
        workers=2,
        request_head=lambda *args, **kwargs: Response(),
    )
    assert design["candidate_date_count"] == 2
    assert design["complete_date_count"] == 2
    assert len(design["availability_records"]) == 8
    assert design["frozen_before_grib_decode"] is True
    assert design["frozen_before_outcome_join"] is True
    assert design["arithmetic_contract"]["chosen_before_outcome_join"] is True
    assert design["feature_contract"]["family"] == "radiation"

    hash_tamper = json.loads(json.dumps(design))
    hash_tamper["arithmetic_contract"]["direct_radiation"] = "tampered"
    with pytest.raises(ValueError, match="canonical hash mismatch"):
        validate_design_contract(
            hash_tamper,
            upstream_contract_path=upstream,
        )

    count_tamper = json.loads(json.dumps(design))
    count_tamper["complete_date_count"] += 1
    with pytest.raises(ValueError, match="complete_date_count mismatch"):
        validate_design_contract(
            count_tamper,
            upstream_contract_path=upstream,
        )

    (output_root / "design_contract.json").write_text(
        json.dumps(hash_tamper), encoding="utf-8"
    )
    source_root = tmp_path / "data"
    source_root.mkdir()
    with pytest.raises(ValueError, match="canonical hash mismatch"):
        build_scratch_backfill(
            source_data_root=source_root,
            output_root=output_root,
            upstream_contract_path=upstream,
            eccodes_path=None,
            specs=(),
            request_get=lambda *args, **kwargs: pytest.fail("must not acquire"),
        )


def test_backfill_rejects_design_output_equal_to_upstream_contract(tmp_path):
    source_root = tmp_path / "data"
    source_root.mkdir()
    output_root = tmp_path / "output"
    output_root.mkdir()
    upstream = output_root / "design_contract.json"
    original = "sealed upstream"
    upstream.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="collides with upstream soil contract"):
        build_scratch_backfill(
            source_data_root=source_root,
            output_root=output_root,
            upstream_contract_path=upstream,
            eccodes_path=None,
            specs=(),
            request_get=lambda *args, **kwargs: pytest.fail("must not acquire"),
        )
    assert upstream.read_text(encoding="utf-8") == original


def test_backfill_rejects_aliased_design_output_equal_to_upstream(tmp_path):
    source_root = tmp_path / "data"
    source_root.mkdir()
    sealed_root = tmp_path / "sealed"
    sealed_root.mkdir()
    upstream = sealed_root / "design_contract.json"
    original = "sealed upstream"
    upstream.write_text(original, encoding="utf-8")
    alias = tmp_path / "sealed-alias"
    _make_directory_alias(alias, sealed_root)

    with pytest.raises(ValueError, match="collides with upstream soil contract"):
        build_scratch_backfill(
            source_data_root=source_root,
            output_root=alias,
            upstream_contract_path=upstream,
            eccodes_path=None,
            specs=(),
            request_get=lambda *args, **kwargs: pytest.fail("must not acquire"),
        )
    assert upstream.read_text(encoding="utf-8") == original


def test_backfill_rejects_hardlinked_manifest_output_to_upstream(tmp_path):
    source_root = tmp_path / "data"
    source_root.mkdir()
    sealed_root = tmp_path / "sealed"
    sealed_root.mkdir()
    upstream = sealed_root / "soil_contract.json"

    class Response:
        status_code = 200
        headers = {"Content-Length": "10"}

    freeze_availability_contract(
        target_dates=["2026-05-10"],
        output_path=upstream,
        workers=1,
        request_head=lambda *args, **kwargs: Response(),
    )
    original = upstream.read_text(encoding="utf-8")
    output_root = tmp_path / "output"
    output_root.mkdir()
    try:
        os.link(upstream, output_root / "manifest.json")
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    with pytest.raises(ValueError, match="manifest output collides with upstream"):
        build_scratch_backfill(
            source_data_root=source_root,
            output_root=output_root,
            upstream_contract_path=upstream,
            eccodes_path=None,
            specs=(),
            request_get=lambda *args, **kwargs: pytest.fail("must not acquire"),
            request_head=lambda *args, **kwargs: pytest.fail("must not probe"),
        )
    assert upstream.read_text(encoding="utf-8") == original
