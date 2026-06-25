import csv
import json
from pathlib import Path

from weather.reporting.candidate_lifecycle.active_variant_shadow_refresh import execute_registry_prediction_exports
from weather.reporting.promotion.promotion_refresh import (
    _candidate_summary,
    build_promotion_allowlist,
    load_precomputed_candidate_report,
    promotion_readiness,
)
from weather.reporting.candidate_lifecycle.repair_integration import (
    LIVE_RUNTIME,
    SCHEMA_VERSION,
    build_payload,
    write_json_report,
)


FIELDNAMES = [
    "variant_id",
    "variant_family",
    "uses_market_features",
    "is_control",
    "claim_lane",
    "counts_toward_weather_model_promotion",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "captured_at_local",
    "bin_type",
    "bin_value",
    "validation_mode",
]


def _row(market, date, band, probability, market_yes, outcome):
    return {
        "variant_id": "surrogate_repair_v1",
        "variant_family": "surrogate_repair",
        "uses_market_features": "false",
        "is_control": "false",
        "claim_lane": "weather_only_core_model",
        "counts_toward_weather_model_promotion": "true",
        "market_id": market,
        "target_date": date,
        "snapshot_id": f"{market}-{date}-0400",
        "band_key": band,
        "probability": str(probability),
        "current_probability": "0.5",
        "recorded_probability": str(probability),
        "market_yes": str(market_yes),
        "outcome": str(outcome),
        "captured_at_local": f"{date}T04:00:00-04:00",
        "bin_type": "eq",
        "bin_value": band.split(":")[-1],
        "validation_mode": "row_export_surrogate",
    }


def _write_rows(path: Path, market: str) -> None:
    rows = []
    for date in ["2026-06-01", "2026-06-02"]:
        rows.append(_row(market, date, "eq:80", 0.9, 0.7, 1))
        rows.append(_row(market, date, "eq:81", 0.1, 0.3, 0))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _write_surrogate_summary(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "validation_evidence": "row_export_surrogate",
                "row_export_metric_passed": True,
                "verdict": "BLOCK",
                "blocked_validation": {
                    "passed": False,
                    "metric_passed": True,
                    "validation_evidence": "row_export_surrogate",
                },
            }
        ),
        encoding="utf-8",
    )


def _base_registry(path: Path, variants=None) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "model_variant_registry_v0.1",
                "updated_at_utc": "2026-06-25T00:00:00+00:00",
                "variants": variants or [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _source_candidate(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "artifact": {"artifact_path": "artifacts/models/demo.pkl"},
                "corpus": {"corpus_hash": "source-corpus"},
                "candidate_shadow_variants": {"variant_id": "source_active"},
            }
        ),
        encoding="utf-8",
    )
    return path


def _repair_specs(root: Path):
    predawn_rows = root / "predawn_rows.csv"
    location_rows = root / "location_rows.csv"
    predawn_summary = root / "predawn_summary.json"
    location_summary = root / "location_summary.json"
    _write_rows(predawn_rows, "nyc")
    _write_rows(location_rows, "austin")
    _write_surrogate_summary(predawn_summary)
    _write_surrogate_summary(location_summary)
    return [
        {
            "repair_id": "predawn_weak_slot",
            "rows_path": str(predawn_rows),
            "summary_path": str(predawn_summary),
            "priority": 20,
        },
        {
            "repair_id": "bottom_location_centering",
            "rows_path": str(location_rows),
            "summary_path": str(location_summary),
            "priority": 10,
        },
    ]


def test_validated_surrogate_repairs_integrate_into_active_replay_contract(tmp_path):
    specs = _repair_specs(tmp_path)
    source = _source_candidate(tmp_path / "source_candidate.json")
    registry = _base_registry(tmp_path / "registry.json")

    payload = build_payload(
        specs,
        rows_out=tmp_path / "integrated_rows.csv",
        registry_out=tmp_path / "integrated_registry.json",
        contract_out=tmp_path / "integrated_contract.json",
        source_candidate_json=source,
        base_registry=registry,
        variant_id="integrated_repair_v1",
        variant_family="integrated_repair",
    )
    json_path, report_path = write_json_report(
        payload,
        tmp_path / "integration.json",
        tmp_path / "integration.md",
        active_replay_json_out=tmp_path / "active_replay.json",
        active_replay_report_out=tmp_path / "active_replay.md",
    )
    loaded_replay = load_precomputed_candidate_report(
        tmp_path / "active_replay.json",
        {"corpus_hash": "source-corpus"},
    )
    candidate = _candidate_summary(loaded_replay, tmp_path / "active_replay.json", tmp_path / "active_replay.md")
    readiness = promotion_readiness(
        candidate,
        None,
        {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
    )
    allowlist = build_promotion_allowlist(
        {
            "family_unit": "F",
            "markets": [
                {
                    "market_id": "nyc",
                    "action": "PROMOTE_CANDIDATE",
                    "verdict": "PASS",
                    "reason": "integrated active contract passed",
                    "metrics": {"candidate_brier": 0.01, "market_brier": 0.09},
                }
            ],
        },
        candidate,
        generated_at_utc="2026-06-25T00:00:00+00:00",
    )

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "PASS"
    assert payload["active_contract"]["live_runtime"] == LIVE_RUNTIME
    assert payload["summary"]["integrated_repair_count"] == 2
    assert payload["summary"]["source_validation_evidence_counts"] == {"row_export_surrogate": 2}
    assert payload["summary"]["integration_status_counts"] == {"integrated": 2}
    assert payload["summary"]["aggregate_delta_vs_market"] < 0
    assert json.loads(json_path.read_text(encoding="utf-8"))["promotion_candidate_json"].endswith("active_replay.json")
    assert loaded_replay["validation_evidence"] == "active_replay_contract"
    assert payload["active_replay_summary"]["validation_evidence"] == "active_replay_contract"
    assert payload["active_replay_summary"]["blocked_validation"]["passed"] is True
    assert payload["active_replay_summary"]["candidate_shadow_variants"]["active_registry_contract"]["variant_id"] == "integrated_repair_v1"
    assert "row_export_surrogate" not in (tmp_path / "integrated_rows.csv").read_text(encoding="utf-8")
    assert candidate["repair_integration"]["repair_ids"] == [
        "bottom_location_centering",
        "predawn_weak_slot",
    ]
    assert readiness["status"] == "READY"
    assert allowlist["markets"][0]["candidate_serving_allowed"] is True


def test_preview_only_repair_reports_not_yet_integrated_status(tmp_path):
    specs = _repair_specs(tmp_path)
    specs[1]["preview_only"] = True
    source = _source_candidate(tmp_path / "source_candidate.json")
    registry = _base_registry(tmp_path / "registry.json")

    payload = build_payload(
        specs,
        rows_out=tmp_path / "integrated_rows.csv",
        registry_out=tmp_path / "integrated_registry.json",
        contract_out=tmp_path / "integrated_contract.json",
        source_candidate_json=source,
        base_registry=registry,
        variant_id="integrated_repair_v1",
        variant_family="integrated_repair",
    )

    by_repair = {row["repair_id"]: row for row in payload["repairs"]}
    assert by_repair["predawn_weak_slot"]["integration_status"] == "integrated"
    assert by_repair["bottom_location_centering"]["integration_status"] == "not_yet_integrated"
    assert "preview-only" in by_repair["bottom_location_centering"]["reason"]
    assert payload["summary"]["integration_status_counts"] == {
        "integrated": 1,
        "not_yet_integrated": 1,
    }


def test_row_export_surrogate_preview_cannot_satisfy_promotion_countability():
    candidate = {
        "verdict": "PASS",
        "cutover_decision": "PER_MARKET_ONLY",
        "validation_evidence": "row_export_surrogate",
        "row_export_metric_passed": True,
        "aggregate": {"delta_vs_market": -0.01},
        "blocked_validation": {"passed": True, "validation_evidence": "row_export_surrogate"},
        "candidate_shadow_variants": {"variant_id": "preview_repair_v1"},
    }
    decisions = {
        "family_unit": "F",
        "shadow_markets": [],
        "blocked_markets": [],
        "markets": [
            {
                "market_id": "nyc",
                "action": "PROMOTE_CANDIDATE",
                "verdict": "PASS",
                "reason": "preview metrics pass",
                "metrics": {"candidate_brier": 0.01, "market_brier": 0.09},
            }
        ],
    }

    readiness = promotion_readiness(candidate, None, decisions)
    allowlist = build_promotion_allowlist(
        decisions,
        candidate,
        generated_at_utc="2026-06-25T00:00:00+00:00",
    )

    assert readiness["status"] == "OPEN"
    assert "repair_integration" in {row["category"] for row in readiness["blockers"]}
    assert allowlist["markets"][0]["candidate_serving_allowed"] is False
    assert "row_export_surrogate" in allowlist["markets"][0]["candidate_cutover_blocker"]


def test_active_variant_refresh_executes_repair_integration_runtime(tmp_path):
    specs = _repair_specs(tmp_path)
    specs_path = tmp_path / "repair_specs.json"
    specs_path.write_text(json.dumps({"repairs": specs}), encoding="utf-8")
    source = _source_candidate(tmp_path / "source_candidate.json")
    export_path = tmp_path / "active_integrated_rows.csv"
    registry = _base_registry(
        tmp_path / "registry.json",
        variants=[
            {
                "variant_id": "integrated_repair_v1",
                "variant_family": "integrated_repair",
                "lifecycle": "active",
                "track": "no_market",
                "roles": ["candidate", "no-market", "repair-integrated"],
                "active_for_headline": True,
                "artifact_required": False,
                "prediction_function": "weather.reporting.candidate_lifecycle.repair_integration:build_payload",
                "prediction_mode": "band_binary",
                "export_family": "integrated_repair",
                "default_export_path": str(export_path),
                "live_runtime": LIVE_RUNTIME,
                "repair_specs_path": str(specs_path),
                "source_candidate_json": str(source),
            }
        ],
    )
    corpus = tmp_path / "promotion_corpus.json"
    corpus.write_text("{}", encoding="utf-8")

    execution = execute_registry_prediction_exports(
        registry_path=registry,
        corpus_path=corpus,
        out_dir=tmp_path / "runs",
    )

    assert execution["status"] == "OK"
    assert execution["executions"][0]["live_runtime"] == LIVE_RUNTIME
    assert execution["executions"][0]["status"] == "OK"
    assert export_path.exists()
