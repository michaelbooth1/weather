import csv
import hashlib
import json
from copy import deepcopy
from datetime import date, timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from weather.backtesting.settlement_io import (
    LEDGER_AUTHORITY_STATUS,
    SettlementAuthorityError,
    canonical_winning_band,
)
from weather.calibration import pooled_feature_assembly as assembly
from weather.calibration import pooled_feature_model as facade
from weather.calibration.pooled_candidate_replay import (
    load_bounded_preselection_folder_inputs,
)
from weather.market.market_registry import ATLANTA
from weather.model.toronto_model import TorontoHighTempModel
from weather.operations.nightly_retrain import (
    prepare_candidate_outputs,
    prepare_production_point_in_time_outputs,
    write_json,
)
from weather.reporting.promotion.promotion_corpus import (
    build_promotion_corpus,
    write_manifest,
)
from weather.reporting.validation.point_in_time_evaluation import (
    materialize_production_preselection_source,
    prepare_production_preselection,
)


# Frozen on 2026-07-24 from the current rows for the latest settled Toronto and
# Atlanta market-days in the protected workstation mirror.  The original tape
# hash is retained as evidence of the copied row.  `_bound_ledger_row` changes
# only that binding to the hermetic tape created by this test.
FROZEN_CURRENT_LEDGER_ROWS = {
    "toronto": {
        "schema_version": "settlement_ledger_v2",
        "event_slug": "highest-temperature-in-toronto-on-july-22-2026",
        "market_id": "toronto",
        "city": "Toronto",
        "target_date": "2026-07-22",
        "settlement_high": 22.0,
        "settlement_bucket": 22,
        "settlement_unit": "C",
        "settlement_source": "daily_summary",
        "winning_band": "22 C",
        "winning_band_kind": "eq",
        "winning_band_value": 22,
        "winning_band_value_hi": 22,
        "quality_grade": "complete",
        "quality_reason": "complete enough for headline scoring",
        "promotion_countable": True,
        "material_coverage_grade": "strict_complete",
        "coverage_clean": True,
        "capture_ratio": 1.3680555555555556,
        "snapshot_tape_path": (
            r"C:\Users\micha\Desktop\github\weather\data\snapshots"
            r"\highest-temperature-in-toronto-on-july-22-2026"
            r"\snapshots_long.csv"
        ),
        "_recorded_snapshot_tape_sha256": (
            "88d6c6403c88af360ad580c34b29dcdaf74bac56dcab24403b4a7a7948e30158"
        ),
        "_raw_polymarket_winning_band": "22 C",
    },
    "atlanta": {
        "schema_version": "settlement_ledger_v2",
        "event_slug": "highest-temperature-in-atlanta-on-july-22-2026",
        "market_id": "atlanta",
        "city": "Atlanta",
        "target_date": "2026-07-22",
        "settlement_high": 88.0,
        "settlement_bucket": 88,
        "settlement_unit": "F",
        "settlement_source": "daily_summary",
        "winning_band": "88-89 F",
        "winning_band_kind": "eq",
        "winning_band_value": 88,
        "winning_band_value_hi": 89,
        "quality_grade": "complete",
        "quality_reason": "complete enough for headline scoring",
        "promotion_countable": True,
        "material_coverage_grade": "strict_complete",
        "coverage_clean": True,
        "capture_ratio": 1.2430555555555556,
        "snapshot_tape_path": (
            r"C:\Users\micha\Desktop\github\weather\data\snapshots"
            r"\highest-temperature-in-atlanta-on-july-22-2026"
            r"\snapshots_long.csv"
        ),
        "_recorded_snapshot_tape_sha256": (
            "1dec10bc4a986bb51a7b099c4ee74ff62fbfbe19f9d9170f413d9b28025859ca"
        ),
        "_raw_polymarket_winning_band": "88-89°F",
    },
}


def _candidate_args(run_root):
    return SimpleNamespace(
        candidates_root=str(run_root / "candidates"),
        releases_root=str(run_root / "releases"),
        release_pointer=str(run_root / "releases" / "current_release.json"),
        candidate_id="lock-blocker-e2e",
        release_candidate_mode="production",
        allow_legacy_serving_output=False,
        pooled_band_artifact="",
        family_secondary_out="",
        artifact_registry="",
        point_in_time_preselection_lock="",
        point_in_time_source_materialized_corpus="",
        point_in_time_source_materialized_manifest="",
        point_in_time_replay_manifest="",
        point_in_time_promotion_selection_corpus="",
        point_in_time_corpus="",
        point_in_time_materialization_manifest="",
        point_in_time_validation_plan="",
        point_in_time_streaming_evaluation="",
        point_in_time_source_corpus="",
        point_in_time_source_manifest="",
        point_in_time_source_replay_manifest="",
        point_in_time_source_receipt="",
        point_in_time_folder=[],
        ledger_root="",
    )


def _write_market_day_fixture(snapshots_root, frozen):
    folder = snapshots_root / frozen["event_slug"]
    folder.mkdir(parents=True)
    snapshot_id = f"{frozen['market_id']}-{frozen['target_date']}-1600"
    raw_band = frozen["_raw_polymarket_winning_band"]
    tape_row = {
        "snapshot_id": snapshot_id,
        "captured_at_local": f"{frozen['target_date']}T16:00:00-04:00",
        "event_slug": frozen["event_slug"],
        "range_label": raw_band,
        "bin_kind": frozen["winning_band_kind"],
        "bin_value_c": frozen["winning_band_value"],
        "bin_value_hi_c": frozen["winning_band_value_hi"],
    }
    tape = folder / "snapshots_long.csv"
    with tape.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(tape_row))
        writer.writeheader()
        writer.writerow(tape_row)
    replay_record = {
        "schema_version": "captured_replay_inputs_v1",
        "snapshot_id": snapshot_id,
        "captured_at_local": tape_row["captured_at_local"],
        "event_slug": frozen["event_slug"],
        "target_date": frozen["target_date"],
        "source": "captured",
    }
    (folder / "replay_inputs.jsonl").write_text(
        json.dumps(replay_record, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sidecar = {
        "event_slug": frozen["event_slug"],
        "market_id": frozen["market_id"],
        "target_date": frozen["target_date"],
        "settlement_bucket": 999,
        "settlement_unit": frozen["settlement_unit"],
        "winning_band": "SIDE-CAR-MUST-NOT-WIN",
        "quality_grade": "complete",
    }
    (folder / "settlement.json").write_text(
        json.dumps(sidecar, sort_keys=True),
        encoding="utf-8",
    )
    return folder, hashlib.sha256(tape.read_bytes()).hexdigest()


def _synthetic_atlanta_row(target_date, offset):
    row = deepcopy(FROZEN_CURRENT_LEDGER_ROWS["atlanta"])
    parsed = date.fromisoformat(target_date)
    slug = (
        "highest-temperature-in-atlanta-on-"
        f"{parsed.strftime('%B').lower()}-{parsed.day}-{parsed.year}"
    )
    bucket = 84 + offset % 5
    row.update(
        {
            "event_slug": slug,
            "target_date": target_date,
            "settlement_high": float(bucket),
            "settlement_bucket": bucket,
            "winning_band": f"{bucket}-{bucket + 1} F",
            "winning_band_value": bucket,
            "winning_band_value_hi": bucket + 1,
            "snapshot_tape_path": (
                r"C:\Users\micha\Desktop\github\weather\data\snapshots"
                f"\\{slug}\\snapshots_long.csv"
            ),
            "_raw_polymarket_winning_band": f"{bucket}-{bucket + 1}°F",
        }
    )
    return row


def _bound_ledger_row(frozen, tape_sha256):
    row = deepcopy(frozen)
    row.pop("_recorded_snapshot_tape_sha256")
    row.pop("_raw_polymarket_winning_band")
    row["evidence"] = {
        "raw_resolution_hashes": {
            "snapshot_tape_sha256": tape_sha256,
        },
    }
    return row


def _write_ledger_rows(ledger_root, market_id, rows):
    path = ledger_root / market_id / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_current_year_history(data_root, fleet_dates):
    summary_path = data_root / "daily" / "daily_summary.csv"
    summary_path.parent.mkdir(parents=True)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "max_temp_native",
                "max_temp_bucket_native",
            ),
        )
        writer.writeheader()
        for index, target_date in enumerate(fleet_dates):
            final_bucket = 84 + index % 5
            writer.writerow(
                {
                    "schema_version": "wu_daily_native_v2",
                    "local_date": target_date,
                    "temperature_unit": "F",
                    "row_count": 24,
                    "max_temp_native": final_bucket,
                    "max_temp_bucket_native": final_bucket,
                }
            )

    rows_by_month = {}
    for index, target_date in enumerate(fleet_dates):
        local_date = date.fromisoformat(target_date)
        final_bucket = 84 + index % 5
        rows_by_month.setdefault((local_date.year, local_date.month), []).extend(
            [
                {
                    "local_date": target_date,
                    "local_time": "07:00",
                    "temp_native": float(final_bucket - 5),
                    "dewpoint_native": 60.0,
                    "humidity": 65.0,
                    "pressure": 1015.0,
                    "wind_cardinal": "SW",
                    "wind_speed_kmh": 8.0,
                    "condition": "Fair",
                    "clouds": "Clear",
                },
                {
                    "local_date": target_date,
                    "local_time": "12:00",
                    "temp_native": float(final_bucket - 1),
                    "dewpoint_native": 62.0,
                    "humidity": 55.0,
                    "pressure": 1012.0,
                    "wind_cardinal": "SW",
                    "wind_speed_kmh": 12.0,
                    "condition": "Fair",
                    "clouds": "Clear",
                },
            ]
        )
    for (year, month), rows in rows_by_month.items():
        hourly_path = (
            data_root
            / "hourly"
            / f"year={year}"
            / f"month={month:02d}"
            / "observations.jsonl"
        )
        hourly_path.parent.mkdir(parents=True)
        hourly_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )


def test_current_ledger_rows_stage_and_train_with_contained_outputs(
    tmp_path,
    monkeypatch,
):
    run_root = tmp_path / "run"
    args = _candidate_args(run_root)
    guard = prepare_candidate_outputs(args)
    assert guard["status"] == "PASS"
    candidate_dir = Path(guard["candidate_dir"]).resolve()

    first_date = date(2026, 6, 17)
    fleet_dates = [
        (first_date + timedelta(days=offset)).isoformat()
        for offset in range(36)
    ]
    assert fleet_dates[-1] == FROZEN_CURRENT_LEDGER_ROWS["atlanta"]["target_date"]

    inputs_root = candidate_dir / "inputs"
    snapshots_root = inputs_root / "snapshots"
    ledger_root = inputs_root / "settlements"
    market_days = {}
    folders = []
    valid_rows_by_market = {"atlanta": [], "toronto": []}
    fixture_rows = [
        _synthetic_atlanta_row(target_date, offset)
        for offset, target_date in enumerate(fleet_dates[:-1])
    ]
    fixture_rows.extend(
        (
            FROZEN_CURRENT_LEDGER_ROWS["atlanta"],
            FROZEN_CURRENT_LEDGER_ROWS["toronto"],
        )
    )
    for frozen in fixture_rows:
        folder, tape_sha256 = _write_market_day_fixture(snapshots_root, frozen)
        valid_row = _bound_ledger_row(frozen, tape_sha256)
        valid_rows_by_market[frozen["market_id"]].append(valid_row)
        folders.append(folder)
        if frozen["event_slug"] == FROZEN_CURRENT_LEDGER_ROWS[
            frozen["market_id"]
        ]["event_slug"]:
            market_days[frozen["market_id"]] = folder
        assert Path(frozen["snapshot_tape_path"]) != (
            folder / "snapshots_long.csv"
        ).resolve()
        assert len(frozen["_recorded_snapshot_tape_sha256"]) == 64
    for market_id, rows in valid_rows_by_market.items():
        _write_ledger_rows(ledger_root, market_id, rows)

    monkeypatch.setenv("SETTLEMENT_LEDGER_ROOT", str(ledger_root))
    args.ledger_root = str(ledger_root)
    args.point_in_time_folder = [str(folder) for folder in folders]
    guard = prepare_production_point_in_time_outputs(args, guard)
    assert guard["status"] == "PASS"

    bounded_loader = partial(
        load_bounded_preselection_folder_inputs,
        snapshots_root=snapshots_root,
        max_rows_per_market_day=100,
    )
    manifest = build_promotion_corpus(
        args.point_in_time_folder,
        snapshots_root=snapshots_root,
        as_of="2026-07-23",
        admit_promotion_countable=False,
        input_loader=bounded_loader,
    )
    assert manifest["summary"]["market_day_count"] == 37
    assert manifest["summary"]["settlement_label_authority"] == {
        LEDGER_AUTHORITY_STATUS: 37,
    }
    entries = {
        entry["event_slug"]: entry
        for entry in manifest["entries"]
    }
    for market_id, frozen in FROZEN_CURRENT_LEDGER_ROWS.items():
        entry = entries[frozen["event_slug"]]
        assert entry["settlement_bucket"] == frozen["settlement_bucket"]
        assert entry["winning_band"] == frozen["winning_band"]
        assert entry["winning_band"] != "SIDE-CAR-MUST-NOT-WIN"
        assert entry["settlement_label_authority"] == {
            "status": LEDGER_AUTHORITY_STATUS,
            "ledger_row_exists": True,
            "sidecar_fallback": False,
        }
        assert canonical_winning_band(
            frozen["_raw_polymarket_winning_band"]
        ) == frozen["winning_band"]

    current_atlanta_index = next(
        index
        for index, row in enumerate(valid_rows_by_market["atlanta"])
        if row["event_slug"]
        == FROZEN_CURRENT_LEDGER_ROWS["atlanta"]["event_slug"]
    )
    bad_rows = deepcopy(valid_rows_by_market["atlanta"])
    bad_binding = bad_rows[current_atlanta_index]
    bad_binding["evidence"]["raw_resolution_hashes"][
        "snapshot_tape_sha256"
    ] = "0" * 64
    _write_ledger_rows(ledger_root, "atlanta", bad_rows)
    with pytest.raises(SettlementAuthorityError, match="binding is invalid"):
        bounded_loader(market_days["atlanta"])

    missing_rows = deepcopy(valid_rows_by_market["atlanta"])
    missing_binding = missing_rows[current_atlanta_index]
    missing_binding.pop("evidence")
    missing_binding.pop("snapshot_tape_path")
    _write_ledger_rows(ledger_root, "atlanta", missing_rows)
    with pytest.raises(SettlementAuthorityError, match="binding is invalid"):
        bounded_loader(market_days["atlanta"])
    _write_ledger_rows(
        ledger_root,
        "atlanta",
        valid_rows_by_market["atlanta"],
    )

    manifest_path = write_manifest(
        manifest,
        args.point_in_time_promotion_selection_corpus,
    )
    materialized = materialize_production_preselection_source(
        replay_manifest=manifest_path,
        parquet_out=args.point_in_time_source_materialized_corpus,
        manifest_out=args.point_in_time_source_materialized_manifest,
        snapshots_root=snapshots_root,
        max_market_days=60,
        max_rows_per_market_day=100,
        batch_rows=100,
        generated_at_utc="2026-07-23T12:00:00+00:00",
    )
    assert materialized["status"] == "PASS"
    assert materialized["derived_artifact"]["row_count"] == 37
    preselection = prepare_production_preselection(
        source_corpus=args.point_in_time_source_materialized_corpus,
        source_manifest=args.point_in_time_source_materialized_manifest,
        replay_manifest=manifest_path,
        lock_out=args.point_in_time_preselection_lock,
        window_end=fleet_dates[-1],
        batch_rows=100,
        max_market_days=60,
        max_rows_per_market_day=100,
        generated_at_utc="2026-07-23T12:00:00+00:00",
    )
    assert preselection["selection_universe"]["fleet_dates"] == fleet_dates
    assert preselection["selection_universe"]["row_count"] == 37
    locked_dates = set(preselection["window_lock"]["target_dates"])
    assert len(locked_dates) == 14
    assert fleet_dates[-1] in locked_dates

    history_root = inputs_root / "wunderground" / "katl"
    _write_current_year_history(history_root, fleet_dates)
    spec = SimpleNamespace(
        id=ATLANTA.id,
        city_label=ATLANTA.city_label,
        display_unit=ATLANTA.display_unit,
        icao=ATLANTA.icao,
        lat=ATLANTA.lat,
        lon=ATLANTA.lon,
        coastal=ATLANTA.coastal,
        data_root=history_root,
        c_to_native=ATLANTA.c_to_native,
    )
    model = TorontoHighTempModel(
        market_id=ATLANTA.id,
        target_date="2026-12-31",
    )
    model.spec = spec

    try:
        TorontoHighTempModel.clear_historical_cache()
        with (
            patch.object(assembly, "family_specs", return_value=[spec]),
            patch.object(assembly, "TorontoHighTempModel", return_value=model),
            patch.object(assembly, "source_daily_indexes", return_value={}),
            patch.object(facade, "source_daily_indexes", return_value={}),
            patch.object(assembly, "load_forecast_daily", return_value={}),
            patch.object(assembly, "load_forecast_profiles", return_value={}),
            patch.object(
                assembly,
                "load_marine_water_contrast_features",
                return_value={},
            ),
            patch.object(
                assembly,
                "load_reanalysis_synoptic_features",
                return_value={},
            ),
        ):
            records, counts = assembly.build_family_dataset(
                unit="F",
                cutoff_hours=(12,),
                excluded_target_dates=locked_dates,
                included_target_dates=set(fleet_dates),
                prior_as_of_exclusive=fleet_dates[0],
            )

        training_dates = set(fleet_dates) - locked_dates
        assert counts == {ATLANTA.id: len(training_dates)}
        assert {
            row["target_date"].isoformat()
            for row in records
        } == training_dates
        assert all("date" not in row for row in records)

        artifact, validation_rows = facade.train_pooled_band_models(
            records,
            holdout_year=None,
            production_preselection=preselection,
        )
        evidence = facade.verify_pooled_point_in_time_training_evidence(artifact)
        assert evidence["status"] == "PASS"
        assert not locked_dates & set(
            evidence["final_fit_receipt"]["train_dates"]
        )
        artifact_path = facade.write_artifact(artifact, args.pooled_band_artifact)
        evidence_path = write_json(
            args.point_in_time_streaming_evaluation,
            {
                "status": evidence["status"],
                "record_count": len(records),
                "validation_row_count": len(validation_rows),
                "locked_target_dates": sorted(locked_dates),
            },
        )
    finally:
        TorontoHighTempModel.clear_historical_cache()

    guarded_output_paths = [
        *(row["path"] for row in guard["outputs"]),
        *(row["path"] for row in guard["point_in_time_outputs"]),
        args.point_in_time_preselection_lock,
        args.point_in_time_source_materialized_corpus,
        args.point_in_time_source_materialized_manifest,
        args.point_in_time_replay_manifest,
        args.point_in_time_promotion_selection_corpus,
    ]
    for output_path in guarded_output_paths:
        Path(output_path).resolve().relative_to(candidate_dir)
    for written_path in (manifest_path, artifact_path, evidence_path):
        assert Path(written_path).is_file()
        Path(written_path).resolve().relative_to(candidate_dir)
    assert all(
        path.resolve().is_relative_to(candidate_dir)
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
