import hashlib
import json
import pickle
from datetime import date, timedelta
from pathlib import Path

import pytest

from weather.market.market_registry import all_specs
from weather.operations.base_retrain import (
    BASE_CUTOFF_HOURS,
    EVIDENCE_MANIFEST_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_parser,
    build_plan,
    evaluate_preflight,
    run_base_retrain,
    snapshot_current_evidence,
)


TARGET_DATE = "2026-07-31"
TRAINING_AS_OF = "2026-08-04T22:00:00+00:00"
RUNTIME_ID = "unit-test-runtime"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _identity(path: Path) -> dict:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "exists": True,
    }


def _parity_report(path: Path, *, status: str) -> dict:
    market_ids = [spec.id for spec in all_specs()]
    payload = {
        "schema_version": "train_serve_feature_parity_v0.1",
        "status": status,
        "coverage": {
            "expected_market_ids": market_ids,
            "full_schema_market_ids": market_ids,
        },
        "summary": {
            "blocking_finding_count": 0 if status == "PASS" else 220,
            "coverage_blocker_count": 0,
        },
    }
    _write_json(path, payload)
    return _identity(path)


def _plan(
    candidate: Path,
    manifest_path: Path,
    parent_id: str = "parent-base",
    feature_contract_id: str = "parent-feature-order-v1",
) -> dict:
    return build_plan(
        target_date=TARGET_DATE,
        training_as_of=TRAINING_AS_OF,
        parent_artifact_id=parent_id,
        feature_contract_id=feature_contract_id,
        evidence_manifest=manifest_path,
        candidate_dir=candidate,
        runtime_id=RUNTIME_ID,
    )


def _current_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    parity = tmp_path / "parity-block.json"
    _parity_report(parity, status="BLOCK")
    for spec in all_specs():
        suffix = spec.artifact_suffix
        hgb = artifacts / "models" / "hgb" / f"feature_model_hgb{suffix}.pkl"
        lr = artifacts / "models" / "coefs" / f"feature_model_coefs{suffix}.json"
        calibration = artifacts / "calibration" / f"probability_calibration{suffix}.json"
        hgb.parent.mkdir(parents=True, exist_ok=True)
        hgb.write_bytes(f"legacy-hgb-{spec.id}".encode())
        _write_json(lr, {"market_id": spec.id, "trained_at": "2026-06-13"})
        _write_json(
            calibration,
            {"market_id": spec.id, "generated_at": "2026-06-07T00:00:00+00:00"},
        )
        _write_json(
            data / "forecast_history" / spec.icao.lower() / "manifest.json",
            {
                "market": spec.id,
                "covered_years": list(range(2018, 2027)),
                "season_window": {"start": [5, 10], "end": [6, 30]},
            },
        )
    return data, artifacts, parity


def _repaired_manifest(tmp_path: Path) -> tuple[dict, Path]:
    target = date.fromisoformat(TARGET_DATE)
    seasonal_dates = [target.replace(year=2025) + timedelta(days=offset) for offset in range(-7, 8)]
    markets = {}
    for spec in all_specs():
        market_root = tmp_path / "evidence" / spec.id
        source = market_root / "forecast-source.json"
        _write_json(
            source,
            {
                "market": spec.id,
                "covered_years": [2025, 2026],
                "season_window": {"start": [5, 10], "end": [8, 31]},
            },
        )
        source_sha = _sha256(source)
        cells = []
        feature_rows = []
        for local_date in seasonal_dates:
            for hour in BASE_CUTOFF_HOURS:
                cell_sha = hashlib.sha256(
                    f"{spec.id}|{local_date}|{hour}".encode()
                ).hexdigest()
                cutoff = f"{local_date.isoformat()}T{hour:02d}:00:00+00:00"
                issue = f"{local_date.isoformat()}T00:00:00+00:00"
                cells.append(
                    {
                        "target_date": local_date.isoformat(),
                        "cutoff_hour": hour,
                        "cutoff_at": cutoff,
                        "issue_time": issue,
                        "available_at": issue,
                        "point_in_time": True,
                        "provenance_state": "verified",
                        "issue_identity": f"run-{local_date.isoformat()}",
                        "source_manifest_sha256": source_sha,
                        "matrix_cell_sha256": cell_sha,
                    }
                )
                feature_rows.append(
                    {
                        "target_date": local_date.isoformat(),
                        "cutoff_hour": hour,
                        "final_bucket": 25 if spec.unit == "C" else 90,
                        "forecast_high": (
                            27
                            if spec.unit == "C"
                            else max((95, *({
                                "dallas": (108,),
                                "denver": (101, 102),
                                "houston": (103, 104),
                                "seattle": (95,),
                            }.get(spec.id, ()))))
                        ),
                        "forecast_provenance": {
                            "source_manifest_sha256": source_sha,
                            "matrix_cell_sha256": cell_sha,
                        },
                        "artifact_regime_id": "post-2026-07-31-current-code",
                        "code_identity_sha256": "a" * 64,
                        "source_artifact_sha256": "b" * 64,
                    }
                )
        coverage = market_root / "coverage.json"
        _write_json(coverage, {"cells": cells})
        records = market_root / "features.jsonl"
        records.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in feature_rows),
            encoding="utf-8",
        )
        hgb = market_root / "parent.pkl"
        with hgb.open("wb") as handle:
            pickle.dump({"parent": spec.id}, handle)
        lr = market_root / "parent.json"
        _write_json(lr, {"parent": spec.id})
        incumbent = market_root / "incumbent-calibration.json"
        _write_json(incumbent, {"generated_at": "2026-06-07T00:00:00+00:00"})
        if spec.unit == "C":
            support_values = list(range(25, 30))
        else:
            forecast_ceiling = max((95, *({
                "dallas": (108,),
                "denver": (101, 102),
                "houston": (103, 104),
                "seattle": (95,),
            }.get(spec.id, ()))))
            support_values = list(range(90, forecast_ceiling + 5))
        markets[spec.id] = {
            "unit": spec.unit,
            "parent_hgb": _identity(hgb),
            "parent_lr": _identity(lr),
            "forecast_archive": {
                "source_manifest": _identity(source),
                "coverage_manifest": _identity(coverage),
            },
            "feature_records": _identity(records),
            "serving_support": {
                "unit": spec.unit,
                "source": "declared_separate_from_model_classes",
                "values": support_values,
                "model_classes": [25, 26] if spec.unit == "C" else [90, 91],
            },
            "incumbent_calibration": {
                **_identity(incumbent),
                "generated_at": "2026-06-07T00:00:00+00:00",
            },
            "candidate_calibration": {
                "mode": "candidate_specific_blocked_oof",
                "inherit_incumbent": False,
                "bind_to_candidate_fit_receipt": True,
            },
        }
    parity_path = tmp_path / "parity-pass.json"
    parity = _parity_report(parity_path, status="PASS")
    manifest = {
        "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
        "target_date": TARGET_DATE,
        "training_as_of": TRAINING_AS_OF,
        "parent_artifact_id": "parent-base",
        "runtime_id": RUNTIME_ID,
        "feature_contract_id": "parent-feature-order-v1",
        "markets": markets,
        "train_serve_parity": parity,
    }
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest, manifest_path


def test_plan_uses_exact_live_registry_and_is_not_scheduled(tmp_path):
    plan = _plan(tmp_path / "candidate", tmp_path / "manifest.json")

    assert plan["schema_version"] == SCHEMA_VERSION
    assert plan["step_name"] == "all_market_base_retrain"
    assert plan["step_count"] == 1
    assert plan["scheduled"] is False
    assert plan["registered_task"] is False
    assert [row["market_id"] for row in plan["markets"]] == [
        spec.id for spec in all_specs()
    ]
    assert [row["unit"] for row in plan["markets"]].count("C") == 1
    assert [row["unit"] for row in plan["markets"]].count("F") == 11
    assert all(len(row["outputs"]) == 5 for row in plan["markets"])

    nightly_source = Path(__file__).parents[2] / "src" / "weather" / "operations" / "nightly_retrain.py"
    assert "weather.operations.base_retrain" not in nightly_source.read_text(encoding="utf-8")


def test_current_evidence_refuses_on_every_named_contaminant(tmp_path):
    data, artifacts, parity = _current_layout(tmp_path)
    manifest = snapshot_current_evidence(
        target_date=TARGET_DATE,
        training_as_of=TRAINING_AS_OF,
        data_root=data,
        artifact_root=artifacts,
        parity_report=parity,
        runtime_id=RUNTIME_ID,
    )
    manifest_path = tmp_path / "current-manifest.json"
    _write_json(manifest_path, manifest)
    plan = _plan(
        tmp_path / "candidate",
        manifest_path,
        parent_id=manifest["parent_artifact_id"],
        feature_contract_id=manifest["feature_contract_id"],
    )

    result = evaluate_preflight(
        plan=plan,
        manifest=manifest,
        manifest_sha256=_sha256(manifest_path),
    )
    checks = {row["name"]: row for row in result["checks"]}

    assert result["status"] == "BLOCK"
    assert result["fit_authorized"] is False
    assert result["ambient_forecast_daily_reachable"] is False
    assert result["release_path_reachable"] is False
    for name in (
        "forecast_archive_coverage",
        "point_in_time_forecast_binding",
        "train_serve_feature_parity",
        "class_support",
        "candidate_specific_calibration",
        "artifact_regime_boundary",
    ):
        assert checks[name]["status"] == "BLOCK", name
    codes = {row["code"] for row in result["blockers"]}
    assert {
        "FORECAST_SEASON_WINDOW_MISS",
        "FORECAST_MATRIX_MANIFEST_MISSING",
        "PIT_COVERAGE_EVIDENCE_MISSING",
        "TRAIN_SERVE_PARITY_BLOCK",
        "SERVING_SUPPORT_UNDECLARED",
        "CANDIDATE_OOF_CALIBRATION_UNDECLARED",
        "ARTIFACT_REGIME_PROVENANCE_MISSING",
    }.issubset(codes)


def test_fully_bound_synthetic_evidence_is_the_only_preflight_pass(tmp_path):
    manifest, manifest_path = _repaired_manifest(tmp_path)
    result = evaluate_preflight(
        plan=_plan(tmp_path / "candidate", manifest_path),
        manifest=manifest,
        manifest_sha256=_sha256(manifest_path),
    )

    assert result["status"] == "PASS"
    assert result["fit_authorized"] is True
    assert all(row["status"] == "PASS" for row in result["checks"])


def test_release_and_global_artifact_roots_are_rejected(tmp_path, monkeypatch):
    from weather.operations import base_retrain

    monkeypatch.setattr(base_retrain, "ARTIFACTS_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(base_retrain, "DATA_ROOT", tmp_path / "data")
    manifest, manifest_path = _repaired_manifest(tmp_path)
    plan = _plan(tmp_path / "artifacts" / "releases" / "candidate", manifest_path)
    result = evaluate_preflight(
        plan=plan,
        manifest=manifest,
        manifest_sha256=_sha256(manifest_path),
    )

    check = next(row for row in result["checks"] if row["name"] == "candidate_output_isolation")
    assert check["status"] == "BLOCK"
    assert {row["code"] for row in check["blockers"]} == {"CANDIDATE_ROOT_PROTECTED"}


def _fake_fitter(*, fail_market: str | None = None, **kwargs):
    market_id = kwargs["market_id"]
    if market_id == fail_market:
        return {"status": "BLOCK", "market_id": market_id, "outputs": {}}
    paths = {
        "feature_hgb": Path(kwargs["hgb_path"]),
        "feature_lr_coefficients": Path(kwargs["lr_path"]),
        "probability_calibration": Path(kwargs["probability_calibration_path"]),
        "fit_receipt": Path(kwargs["receipt_path"]),
        "fit_report": Path(kwargs["report_path"]),
    }
    for role, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if role == "probability_calibration":
            path.write_text(
                json.dumps(
                    {
                        "market_id": market_id,
                        "exact_distribution": {"fit_scope": "candidate_blocked_oof"},
                    }
                ),
                encoding="utf-8",
            )
        else:
            path.write_text(f"{market_id}:{role}", encoding="utf-8")
    return {
        "status": "PASS",
        "market_id": market_id,
        "outputs": {role: {"path": str(path)} for role, path in paths.items()},
    }


def test_partial_fleet_never_becomes_the_declared_candidate(tmp_path):
    manifest, manifest_path = _repaired_manifest(tmp_path)
    candidate = tmp_path / "candidate"

    with pytest.raises(Exception, match="complete five-output"):
        run_base_retrain(
            plan=_plan(candidate, manifest_path),
            manifest=manifest,
            manifest_sha256=_sha256(manifest_path),
            execute_fit=True,
            market_fitter=lambda **kwargs: _fake_fitter(fail_market="nyc", **kwargs),
        )

    assert not candidate.exists()


def test_complete_fake_fleet_is_atomically_published_candidate_only(tmp_path):
    manifest, manifest_path = _repaired_manifest(tmp_path)
    candidate = tmp_path / "candidate"
    result = run_base_retrain(
        plan=_plan(candidate, manifest_path),
        manifest=manifest,
        manifest_sha256=_sha256(manifest_path),
        execute_fit=True,
        market_fitter=_fake_fitter,
    )

    assert result["status"] == "PASS"
    assert candidate.is_dir()
    receipt = json.loads((candidate / "fleet-fit-receipt.json").read_text(encoding="utf-8"))
    assert receipt["market_count"] == 12
    assert receipt["release_created"] is False
    assert receipt["release_pointer_modified"] is False


def test_run_parser_requires_the_explicit_fit_flag():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run",
                "--target-date",
                TARGET_DATE,
                "--training-as-of",
                TRAINING_AS_OF,
                "--parent-artifact-id",
                "parent-base",
                "--evidence-manifest",
                "manifest.json",
                "--feature-contract-id",
                "parent-feature-order-v1",
                "--candidate-dir",
                "candidate",
                "--runtime-id",
                RUNTIME_ID,
                "--output",
                "result.json",
            ]
        )
