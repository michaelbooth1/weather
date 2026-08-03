import argparse
import hashlib
import json
import pickle
from pathlib import Path

import pytest

from weather.calibration.base_model_candidate import contiguous_serving_support
from weather.calibration.forecast_training_contract import (
    pit_selection_binding_sha256,
)
from weather.market.market_registry import BUILTIN_SPECS
from weather.operations.base_retrain import (
    BaseRetrainContractError,
    CORPUS_MANIFEST_SCHEMA_VERSION,
    EXPECTED_MARKETS,
    MARKET_UNITS,
    REPLACED_COMPONENTS,
    _copy_parent_unchanged,
    _finalize_candidate_contract,
    build_parser,
    build_plan,
    evaluate_preflight,
    prove_output_isolation,
    run_base_retrain,
)
from weather.operations.release_candidate_contract import (
    freeze_candidate_semantic_contract,
)
from weather.operations.nightly_retrain import (
    build_parser as build_nightly_parser,
    planned_steps,
)
from weather.release_artifacts import sha256_file


TARGET_DATE = "2099-07-24"
TRAINING_AS_OF = "2099-07-25T04:00:00+00:00"
FEATURE_CONTRACT_ID = "sha256:" + "c" * 64
RUNTIME_ID = "synthetic-runtime-v1"
PIT_CORPUS_ID = "e" * 64


def _support(unit: str) -> dict:
    labels = [20, 21] if unit == "C" else [90, 91]
    forecasts = [21.0] if unit == "C" else [91.0]
    serving_support = contiguous_serving_support(labels, forecasts, unit=unit)
    prior = {str(value): 1.0 / len(serving_support) for value in serving_support}
    row = {
        "label_buckets": labels,
        "cutoff_valid_forecast_highs": forecasts,
        "serving_support": serving_support,
        "model_classes": [labels[0], labels[-1]],
        "alpha_smoothed_prior": prior,
    }
    return {"folds": [dict(row)], "final": dict(row)}


def _parent() -> dict:
    markets = {}
    for spec in BUILTIN_SPECS:
        markets[spec.id] = {
            "unit": spec.unit,
            "hours": {
                "12": {"feature_names": ["forecast_high", "rise_from_7am"]}
            },
            "hgb": {},
            "lr": {},
            "components": {
                "feature_hgb": {
                    "role": f"base_model.{spec.id}.feature_hgb",
                    "path": f"base_model/{spec.id}/hgb.pkl",
                },
                "feature_lr_coefficients": {
                    "role": f"base_model.{spec.id}.feature_lr_coefficients",
                    "path": f"base_model/{spec.id}/lr.json",
                },
                "probability_calibration": {
                    "role": f"base_model.{spec.id}.probability_calibration",
                    "path": f"base_model/{spec.id}/calibration.json",
                },
            },
        }
    return {
        "status": "PASS",
        "parent_release_id": "parent-r1",
        "parent_manifest_sha256": "d" * 64,
        "base_market_component_role_count": 84,
        "feature_contract_id": FEATURE_CONTRACT_ID,
        "markets": markets,
        "manifest": {"expected_live_runtimes": ["snapshot_loop"]},
    }


def _market_manifest(
    market_id: str,
    *,
    forecast_covered: bool,
    parity_equal: bool,
    records_path: Path | None = None,
) -> dict:
    selected_date = "2098-07-24"
    unit = MARKET_UNITS[market_id]
    rise_historical = {
        "value": 5.0,
        "unit": unit,
        "category": None,
        "missing": False,
        "cutoff_behavior": "at_or_before_cutoff",
    }
    rise_live = dict(rise_historical)
    if not parity_equal:
        rise_live.update({"value": None, "missing": True})
    forecast_value = {
        "value": 92.0,
        "unit": unit,
        "category": None,
        "missing": False,
        "cutoff_behavior": "pit_issue_before_cutoff",
    }
    row = {
        "unit": unit,
        "expected_selected_day_count": 1,
        "minimum_selected_day_count": 1,
        "minimum_hourly_rows_per_day": 1,
        "selected_dates": [
            {
                "local_date": selected_date,
                "daily_sha256": "a" * 64,
                "hourly_sha256": "b" * 64,
                "hourly_row_count": 10,
                "label_bucket": 20 if unit == "C" else 90,
                "cutoff_at": "2098-07-24T16:00:00+00:00",
                "max_predictor_known_at": "2098-07-24T15:59:00+00:00",
            }
        ],
        "feature_names_by_hour": {
            "12": ["forecast_high", "rise_from_7am"]
        },
        "all_missing_features": [],
        "live_only_features": [],
        "forecast_archive": {
            "fields": {
                "forecast_high": {
                    "expected_dates": [selected_date],
                    "covered_dates": [selected_date] if forecast_covered else [],
                    "pit_issue_time_provenance": forecast_covered,
                }
            }
        },
        "parity_samples": [
            {
                "field": "forecast_high",
                "historical": forecast_value,
                "live": dict(forecast_value),
            },
            {
                "field": "rise_from_7am",
                "historical": rise_historical,
                "live": rise_live,
            },
        ],
        "sidecars": [],
        "support": _support(unit),
    }
    if records_path is not None:
        row["records_path"] = str(records_path)
        row["records_sha256"] = sha256_file(records_path)
    return row


def _manifest(
    *,
    forecast_covered: bool,
    parity_equal: bool,
    record_paths: dict[str, Path] | None = None,
) -> dict:
    return {
        "schema_version": CORPUS_MANIFEST_SCHEMA_VERSION,
        "target_date": TARGET_DATE,
        "training_as_of": TRAINING_AS_OF,
        "feature_contract_id": FEATURE_CONTRACT_ID,
        "runtime_id": RUNTIME_ID,
        "markets": {
            market_id: _market_manifest(
                market_id,
                forecast_covered=forecast_covered,
                parity_equal=parity_equal,
                records_path=(record_paths or {}).get(market_id),
            )
            for market_id in EXPECTED_MARKETS
        },
    }


def _record_paths(tmp_path: Path) -> dict[str, Path]:
    paths = {}
    for market_id in EXPECTED_MARKETS:
        path = tmp_path / "corpus" / f"{market_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_pit_record(market_id)) + "\n",
            encoding="utf-8",
        )
        paths[market_id] = path
    return paths


def _pit_binding(market_id: str) -> dict:
    return {
        "market_id": market_id,
        "target_date": "2098-07-24",
        "cutoff_hour_local": 12,
        "forecast_high_native": 21.0 if MARKET_UNITS[market_id] == "C" else 91.0,
        "temperature_unit": MARKET_UNITS[market_id],
        "corpus_id": PIT_CORPUS_ID,
        "request_hash": hashlib.sha256(f"request:{market_id}".encode()).hexdigest(),
        "raw_response_sha256": hashlib.sha256(f"raw:{market_id}".encode()).hexdigest(),
        "issue_time_utc": "2098-07-23T00:00:00+00:00",
        "available_at_utc": "2098-07-23T01:00:00+00:00",
        "feature_as_of_utc": "2098-07-24T16:00:00+00:00",
    }


def _pit_record(market_id: str) -> dict:
    binding = _pit_binding(market_id)
    return {
        "target_date": binding["target_date"],
        "cutoff_hour": binding["cutoff_hour_local"],
        "forecast_high": binding["forecast_high_native"],
        **{
            f"forecast_pit_{field}": value
            for field, value in binding.items()
            if field
            not in {
                "market_id",
                "target_date",
                "cutoff_hour_local",
                "forecast_high_native",
            }
        },
    }


def _receipt_hash(payload: dict) -> str:
    body = dict(payload)
    body.pop("preflight_sha256", None)
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _pit_preflight(pit_manifest: Path, *, status: str = "PASS") -> dict:
    rows = [_pit_binding(market_id) for market_id in EXPECTED_MARKETS]
    receipt = {
        "status": status,
        "manifest_path": str(pit_manifest.resolve()),
        "manifest_file_sha256": sha256_file(pit_manifest),
        "manifest_sha256": "f" * 64,
        "corpus_id": PIT_CORPUS_ID,
        "selection_row_count": len(rows),
        "selection_binding_sha256": pit_selection_binding_sha256(rows),
    }
    if status != "PASS":
        receipt["error"] = "synthetic PIT verification failure"
    receipt["preflight_sha256"] = _receipt_hash(receipt)
    return receipt


def _plan(candidate_dir: Path, corpus_manifest: Path) -> dict:
    pit_manifest = candidate_dir.parent / "pit-manifest.json"
    pit_manifest.parent.mkdir(parents=True, exist_ok=True)
    if not pit_manifest.exists():
        pit_manifest.write_text("{}\n", encoding="utf-8")
    return build_plan(
        target_date=TARGET_DATE,
        parent_release_id="parent-r1",
        training_as_of=TRAINING_AS_OF,
        feature_contract_id=FEATURE_CONTRACT_ID,
        corpus_manifest=corpus_manifest,
        pit_forecast_corpus_manifest=pit_manifest,
        candidate_dir=candidate_dir,
        runtime_id=RUNTIME_ID,
    )


def _isolation_pass(candidate_dir: Path) -> dict:
    return {
        "status": "PASS",
        "candidate_root": str(candidate_dir),
        "before_inventory_sha256": "1" * 64,
        "after_inventory_sha256": "1" * 64,
        "protected_row_count": 1,
        "outside_write_detected": False,
        "payload_sha256": "2" * 64,
    }


def test_plan_declares_exactly_one_all_market_step_and_every_candidate_output(tmp_path):
    plan = _plan(tmp_path / "candidate-r1", tmp_path / "manifest.json")

    assert plan["step_count"] == 1
    assert plan["step_name"] == "all_market_base_retrain"
    assert [row["market_id"] for row in plan["markets"]] == list(EXPECTED_MARKETS)
    assert len(plan["markets"]) == 12
    assert all(len(row["outputs"]) == 5 for row in plan["markets"])
    assert {row["unit"] for row in plan["markets"]} == {"C", "F"}


def test_base_retrain_cli_has_no_defaults_for_run_identity():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_preflight_demonstrates_zero_forecast_coverage_and_wu_blind_value_mismatch(
    tmp_path,
):
    manifest = _manifest(
        forecast_covered=False,
        parity_equal=False,
        record_paths=_record_paths(tmp_path),
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    plan = _plan(tmp_path / "candidate-r1", path)
    pit_path = Path(plan["pit_forecast_corpus_manifest"])
    result = evaluate_preflight(
        plan=plan,
        manifest=manifest,
        manifest_sha256=sha256_file(path),
        pit_forecast_manifest_sha256=sha256_file(pit_path),
        pit_forecast_preflight=_pit_preflight(pit_path, status="BLOCK"),
        parent=_parent(),
        output_isolation=_isolation_pass(tmp_path / "candidate-r1"),
    )

    checks = {row["name"]: row for row in result["checks"]}
    assert result["status"] == "BLOCK"
    assert checks["pit_forecast_corpus"]["status"] == "BLOCK"
    assert checks["train_serve_parity"]["status"] == "BLOCK"
    assert any(
        row["code"] == "PIT_FORECAST_CORPUS_UNVERIFIED"
        for row in checks["pit_forecast_corpus"]["blockers"]
    )
    mismatch = checks["train_serve_parity"]["blockers"]
    assert all(row["code"] == "TRAIN_SERVE_PARITY_MISMATCH" for row in mismatch)
    assert {row["field"] for row in mismatch} == {"rise_from_7am"}
    assert all("value" in row["mismatches"] for row in mismatch)
    assert all("missing" in row["mismatches"] for row in mismatch)
    assert result["fit_authorized"] is False


def test_synthetic_repaired_manifest_clears_all_executable_preflights(tmp_path):
    manifest = _manifest(
        forecast_covered=True,
        parity_equal=True,
        record_paths=_record_paths(tmp_path),
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    plan = _plan(tmp_path / "candidate-r1", path)
    pit_path = Path(plan["pit_forecast_corpus_manifest"])
    result = evaluate_preflight(
        plan=plan,
        manifest=manifest,
        manifest_sha256=sha256_file(path),
        pit_forecast_manifest_sha256=sha256_file(pit_path),
        pit_forecast_preflight=_pit_preflight(pit_path),
        parent=_parent(),
        output_isolation=_isolation_pass(tmp_path / "candidate-r1"),
    )

    assert result["status"] == "PASS"
    assert result["fit_authorized"] is True
    assert all(row["status"] == "PASS" for row in result["checks"])


def test_legacy_feature_records_without_pit_provenance_block_preflight(tmp_path):
    record_paths = _record_paths(tmp_path)
    record_paths["toronto"].write_text(
        json.dumps(
            {
                "target_date": "2098-07-24",
                "cutoff_hour": 12,
                "forecast_high": 21.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = _manifest(
        forecast_covered=True,
        parity_equal=True,
        record_paths=record_paths,
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    plan = _plan(tmp_path / "candidate-r1", path)
    pit_path = Path(plan["pit_forecast_corpus_manifest"])

    result = evaluate_preflight(
        plan=plan,
        manifest=manifest,
        manifest_sha256=sha256_file(path),
        pit_forecast_manifest_sha256=sha256_file(pit_path),
        pit_forecast_preflight=_pit_preflight(pit_path),
        parent=_parent(),
        output_isolation=_isolation_pass(tmp_path / "candidate-r1"),
    )

    gate = next(row for row in result["checks"] if row["name"] == "pit_forecast_corpus")
    assert gate["status"] == "BLOCK"
    assert any(
        row["code"] == "PIT_FEATURE_RECORD_PROVENANCE_MISSING"
        for row in gate["blockers"]
    )


def test_output_isolation_probe_detects_legacy_global_write(tmp_path):
    repo = tmp_path / "repo"
    global_path = repo / "artifacts" / "models" / "feature.pkl"
    data_path = repo / "data" / "evidence.json"
    pointer = repo / "artifacts" / "releases" / "current_release.json"
    parent = repo / "artifacts" / "releases" / "parent-r1"
    for path, content in (
        (global_path, b"parent model"),
        (data_path, b"evidence"),
        (pointer, b"pointer"),
        (parent / "component.json", b"component"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    candidate = tmp_path / "run" / "candidate-r1"
    candidate.mkdir(parents=True)

    result = prove_output_isolation(
        candidate_dir=candidate,
        repo_root=repo,
        active_pointer=pointer,
        parent_release_dir=parent,
        probe=lambda _candidate: global_path.write_bytes(b"legacy trainer mutation"),
    )

    assert result["status"] == "BLOCK"
    assert result["outside_write_detected"] is True
    assert result["before_inventory_sha256"] != result["after_inventory_sha256"]


def test_contiguous_support_is_native_margin_complete_and_not_model_classes():
    assert contiguous_serving_support([20, 22], [23.1], unit="C") == list(
        range(20, 27)
    )
    assert contiguous_serving_support([90, 92], [94.1], unit="F") == list(
        range(90, 100)
    )


def _run_fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    parent_dir = repo / "artifacts" / "releases" / "parent-r1"
    pointer = repo / "artifacts" / "releases" / "current_release.json"
    parent_dir.mkdir(parents=True)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    (parent_dir / "component.json").write_text("{}", encoding="utf-8")
    pointer.write_text("{}", encoding="utf-8")
    record_paths = _record_paths(tmp_path)
    for market_id, path in record_paths.items():
        path.write_text(
            json.dumps(
                {
                    **_pit_record(market_id),
                    "final_bucket": 20 if MARKET_UNITS[market_id] == "C" else 90,
                }
            )
            + "\n",
            encoding="utf-8",
        )
    manifest = _manifest(
        forecast_covered=True,
        parity_equal=True,
        record_paths=record_paths,
    )
    manifest_path = tmp_path / "corpus" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    pit_manifest_path = tmp_path / "corpus" / "pit-manifest.json"
    pit_manifest_path.write_text("{}\n", encoding="utf-8")
    parent = _parent()
    parent["parent_release_dir"] = str(parent_dir)
    args = argparse.Namespace(
        target_date=TARGET_DATE,
        parent_release_id="parent-r1",
        training_as_of=TRAINING_AS_OF,
        feature_contract_id=FEATURE_CONTRACT_ID,
        corpus_manifest=str(manifest_path),
        pit_forecast_corpus_manifest=str(pit_manifest_path),
        candidate_dir=str(tmp_path / "run" / "candidate-r1"),
        runtime_id=RUNTIME_ID,
        releases_root=str(repo / "artifacts" / "releases"),
        active_pointer=str(pointer),
        repo_root=str(repo),
    )
    return args, parent, repo


def test_toronto_nyc_only_success_is_not_releasable(tmp_path):
    args, parent, _repo = _run_fixture(tmp_path)
    release_calls = []

    def fake_fitter(**kwargs):
        market_id = kwargs["market_id"]
        passed = market_id in {"toronto", "nyc"}
        return {
            "status": "PASS" if passed else "BLOCK",
            "market_id": market_id,
            "outputs": (
                {
                    "feature_hgb": {},
                    "feature_lr_coefficients": {},
                    "probability_calibration": {},
                }
                if passed
                else {}
            ),
        }

    with pytest.raises(BaseRetrainContractError, match="all 12"):
        run_base_retrain(
            args,
            parent_loader=lambda **_kwargs: parent,
            pit_preflight_loader=lambda *_args, **_kwargs: _pit_preflight(
                Path(args.pit_forecast_corpus_manifest)
            ),
            market_fitter=fake_fitter,
            release_builder=lambda **kwargs: release_calls.append(kwargs),
        )

    assert release_calls == []


def test_missing_pit_manifest_blocks_before_any_market_fit(tmp_path):
    args, parent, _repo = _run_fixture(tmp_path)
    Path(args.pit_forecast_corpus_manifest).unlink()
    fit_calls = []

    result = run_base_retrain(
        args,
        parent_loader=lambda **_kwargs: parent,
        market_fitter=lambda **kwargs: fit_calls.append(kwargs),
    )

    assert result["status"] == "BLOCK"
    assert fit_calls == []
    gate = next(
        row
        for row in result["preflight"]["checks"]
        if row["name"] == "pit_forecast_corpus"
    )
    assert gate["status"] == "BLOCK"


def test_fit_scope_inventory_aborts_when_a_runner_touches_global_artifacts(tmp_path):
    args, parent, repo = _run_fixture(tmp_path)
    global_path = repo / "artifacts" / "models" / "feature_model_hgb.pkl"
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_bytes(b"incumbent")
    release_calls = []

    def legacy_writer(**kwargs):
        global_path.write_bytes(b"mutated")
        return {
            "status": "PASS",
            "market_id": kwargs["market_id"],
            "outputs": {
                "feature_hgb": {},
                "feature_lr_coefficients": {},
                "probability_calibration": {},
            },
        }

    with pytest.raises(BaseRetrainContractError, match="outside-candidate write"):
        run_base_retrain(
            args,
            parent_loader=lambda **_kwargs: parent,
            pit_preflight_loader=lambda *_args, **_kwargs: _pit_preflight(
                Path(args.pit_forecast_corpus_manifest)
            ),
            market_fitter=legacy_writer,
            release_builder=lambda **kwargs: release_calls.append(kwargs),
        )

    assert release_calls == []


def test_nightly_plan_contains_exactly_one_unskippable_base_step():
    args = build_nightly_parser().parse_args(
        ["run", "--dry-run", "--skip-promotion-refresh"]
    )
    steps = planned_steps(args)
    base_steps = [row for row in steps if row[0] == "all_market_base_retrain"]

    assert len(base_steps) == 1
    command = base_steps[0][1]
    assert command[1:3] == ["-m", "weather.operations.base_retrain"]
    assert command.count("--target-date") == 1
    assert command.count("--candidate-dir") == 1
    assert command.count("--pit-forecast-corpus-manifest") == 1
    assert "--skip-base-retrain" not in command


def test_empty_nightly_bindings_do_not_acquire_ambient_path_defaults(tmp_path):
    plan = build_plan(
        target_date="",
        parent_release_id="",
        training_as_of="",
        feature_contract_id="",
        corpus_manifest="",
        pit_forecast_corpus_manifest="",
        candidate_dir="",
        runtime_id="",
    )

    assert plan["candidate_dir"] == ""
    assert plan["candidate_release_id"] == ""
    assert plan["corpus_manifest"] == ""
    assert plan["pit_forecast_corpus_manifest"] == ""


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _semantic_parent_fixture(tmp_path: Path) -> dict:
    repo = tmp_path / "semantic-repo"
    config = repo / "config"
    _write_json(
        config / "model_variant_registry.json",
        {
            "schema_version": "model_variant_registry_v0.1",
            "variants": [
                {
                    "variant_id": "candidate",
                    "feature_manifest": {"feature_families": ["forecast_profile"]},
                }
            ],
        },
    )
    _write_json(
        config / "locations.json",
        {
            "schema_version": "locations_v0.1",
            "locations": [
                {
                    "id": spec.id,
                    "market_unit": spec.unit,
                    "polymarket": {
                        "event_slug_prefix": spec.slug_prefix,
                    },
                    "settlement": {
                        "unit": spec.unit,
                        "precision": "whole_degree",
                        "source_type": "wunderground_history",
                        "station_id": spec.icao,
                        "resolution_source_url": f"https://example.test/{spec.icao}",
                    },
                }
                for spec in BUILTIN_SPECS
            ],
        },
    )
    _write_json(
        config / "location_market_events.json",
        {"schema_version": "events_v0.1", "locations": []},
    )
    _write_json(
        config / "markets.json",
        {"schema_version": "markets_v0.1", "markets": []},
    )
    artifacts = repo / "artifacts"
    for spec in BUILTIN_SPECS:
        suffix = "" if spec.id == "toronto" else f"_{spec.id}"
        hgb = artifacts / "models" / "hgb" / f"feature_model_hgb{suffix}.pkl"
        hgb.parent.mkdir(parents=True, exist_ok=True)
        with hgb.open("wb") as handle:
            pickle.dump(
                {"12": {"feature_names": ["forecast_high", "high_so_far"]}},
                handle,
            )
        for path in (
            artifacts / "models" / "coefs" / f"feature_model_coefs{suffix}.json",
            artifacts / "models" / "coefs" / f"late_day_model_coefs{suffix}.json",
            artifacts / "calibration" / f"calibrated_weights{suffix}.json",
            artifacts / "calibration" / f"probability_calibration{suffix}.json",
            artifacts / "calibration" / f"forecast_error_model{suffix}.json",
            artifacts / "calibration" / f"settlement_lag_model{suffix}.json",
        ):
            _write_json(
                path,
                {
                    "schema_version": "synthetic_v0.1",
                    "market_id": spec.id,
                    "path_name": path.name,
                },
            )
    _write_json(
        artifacts / "misc" / "afternoon_residual_centering.json",
        {"schema_version": "synthetic_v0.1", "market_id": "shared"},
    )

    parent_dir = tmp_path / "parent-release"
    bundle_path = parent_dir / "model" / "pooled.pkl"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with bundle_path.open("wb") as handle:
        pickle.dump(
            {
                "schema_version": "pooled_feature_band_hgb_v0.1",
                "feature_schema_version": "toronto_feature_store_v1.6",
                "family_unit": "F",
                "prediction_mode": "band_binary",
                "feature_subset": "all",
                "feature_subset_contract": {
                    "feature_families": ["forecast_profile"]
                },
                "models": {
                    "8": {
                        "feature_schema_version": "toronto_feature_store_v1.6",
                        "feature_names": [
                            "forecast_high",
                            "band_mid_minus_forecast",
                        ],
                        "imputer": {"statistics": [80.0, 0.0]},
                        "temperature": 1.0,
                    }
                },
                "postprocess": {"market_bias_calibration": {"enabled": False}},
                "corpus_lineage": {
                    "selection_training": {
                        "row_count": 20,
                        "sha256": "1" * 64,
                        "target_date_min": "2096-07-17",
                        "target_date_max": "2096-07-31",
                    },
                    "evaluation": {
                        "row_count": 10,
                        "sha256": "2" * 64,
                        "target_date_min": "2097-07-17",
                        "target_date_max": "2097-07-31",
                    },
                    "final_refit": {
                        "row_count": 30,
                        "sha256": "3" * 64,
                        "target_date_min": "2096-07-17",
                        "target_date_max": "2097-07-31",
                    },
                    "model_input_fields": [
                        "forecast_high",
                        "band_mid_minus_forecast",
                    ],
                    "evaluation_only_label_fields": ["outcome"],
                },
            },
            handle,
        )
    family = parent_dir / "calibration" / "family.json"
    registry = parent_dir / "config" / "registry.json"
    _write_json(family, {"schema_version": "family_calibration_v0.1"})
    _write_json(registry, {"schema_version": "artifact_registry_v0.1", "artifacts": []})
    frozen = freeze_candidate_semantic_contract(
        candidate_dir=parent_dir,
        model_bundle_path=bundle_path,
        family_secondary_path=family,
        artifact_registry_path=registry,
        repo_root=repo,
        candidate_id="parent-r1",
        parent_release=None,
        promotion={
            "verdict": "shadow",
            "promote_markets": [],
            "shadow_markets": list(EXPECTED_MARKETS),
            "blocked_markets": [],
        },
        family_unit="F",
    )
    role_rows = {}
    inventory = []
    for declaration in frozen["declarations"]:
        path = parent_dir / declaration["path"]
        row = {
            **declaration,
            "declared": True,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        inventory.append(row)
        role_rows[declaration["role"]] = row
    graph = json.loads(
        (parent_dir / role_rows["base_model_serving_graph"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    semantic = json.loads(
        (parent_dir / role_rows["semantic_serving_contract"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    return {
        "parent_release_dir": str(parent_dir),
        "inventory": inventory,
        "role_rows": role_rows,
        "graph": graph,
        "semantic": semantic,
        "markets": {
            market_id: {"components": graph["markets"][market_id]["components"]}
            for market_id in EXPECTED_MARKETS
        },
    }


def test_complete_fleet_rebinds_parent_graph_and_preserves_every_unchanged_hash(
    tmp_path,
):
    parent = _semantic_parent_fixture(tmp_path)
    child = tmp_path / "candidate-r2"
    child.mkdir()
    replaced_roles = set()
    for market_id in EXPECTED_MARKETS:
        components = parent["markets"][market_id]["components"]
        for component_name in REPLACED_COMPONENTS:
            component = components[component_name]
            replaced_roles.add(component["role"])
            destination = child / component["path"]
            if component_name == "feature_hgb":
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    pickle.dump(
                        {
                            "12": {
                                "feature_names": ["forecast_high", "high_so_far"],
                                "candidate_market": market_id,
                            }
                        },
                        handle,
                    )
            else:
                _write_json(
                    destination,
                    {
                        "schema_version": "synthetic_candidate_v0.1",
                        "market_id": market_id,
                        "component": component_name,
                    },
                )

    _copy_parent_unchanged(parent, child)
    verified = _finalize_candidate_contract(
        parent=parent,
        candidate_dir=child,
        candidate_id="candidate-r2",
    )

    assert verified["status"] == "PASS"
    assert verified["candidate_mode"] == "research_only"
    for role, row in parent["role_rows"].items():
        if role in replaced_roles or role in {
            "base_model_serving_graph",
            "candidate_input_leakage_audit",
            "semantic_serving_contract",
        }:
            continue
        assert sha256_file(child / row["path"]) == row["sha256"], role
