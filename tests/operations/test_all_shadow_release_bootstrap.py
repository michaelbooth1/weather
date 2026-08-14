import json
import pickle
from datetime import date

import pytest

from weather.operations.all_shadow_release_bootstrap import (
    AllShadowBootstrapError,
    _first_party_research_lineage,
    _runtime_market_inventory,
    _verified_release_research_lineage,
    _verified_release_role_source,
    all_shadow_promotion,
)
from weather.operations.release_candidate_contract import (
    CandidateContractError,
    _corpus_manifest,
)


def test_runtime_inventory_is_exact_twelve_market_native_unit_fleet():
    inventory = _runtime_market_inventory()

    assert inventory["market_count"] == 12
    assert inventory["fahrenheit_market_count"] == 11
    assert inventory["toronto_unit"] == "C"
    assert inventory["market_ids"] == sorted(inventory["market_ids"])


def test_all_shadow_promotion_has_no_promote_or_blocked_market():
    promotion = all_shadow_promotion()

    assert promotion["verdict"] == "shadow"
    assert promotion["promote_markets"] == []
    assert promotion["blocked_markets"] == []
    assert len(promotion["shadow_markets"]) == 12
    assert "toronto" in promotion["shadow_markets"]


def test_verified_source_release_selects_exact_hash_bound_model_role(
    tmp_path,
    monkeypatch,
):
    release = tmp_path / "r1"
    model = release / "model" / "bundle.pkl"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"verified bundle")
    from weather.release_artifacts import sha256_file

    digest = sha256_file(model)
    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap.verify_release",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "manifest_sha256": "a" * 64,
            "manifest": {
                "release_id": "r1",
                "artifacts": {
                    "inventory": [
                        {
                            "role": "pooled_band_model",
                            "path": "model/bundle.pkl",
                            "sha256": digest,
                        }
                    ]
                },
            },
        },
    )

    source, proof = _verified_release_role_source(
        release,
        role="pooled_band_model",
    )

    assert source == model
    assert proof["release_id"] == "r1"
    assert proof["role_sha256"] == digest
    assert proof["integrity_verification_status"] == "PASS"


def test_verified_source_release_supplies_model_bound_research_lineage(
    tmp_path,
    monkeypatch,
):
    release = tmp_path / "r1"
    corpus_path = release / "contract" / "training_evaluation_corpus.json"
    corpus_path.parent.mkdir(parents=True)
    bundle_sha = "b" * 64
    lineage = {
        "selection_training": {
            "sha256": "1" * 64,
            "row_count": 10,
            "target_date_min": "2026-06-01",
            "target_date_max": "2026-06-10",
        },
        "evaluation": {
            "sha256": "2" * 64,
            "row_count": 5,
            "target_date_min": "2026-06-11",
            "target_date_max": "2026-06-15",
        },
        "final_refit": {
            "sha256": "3" * 64,
            "row_count": 15,
            "target_date_min": "2026-06-01",
            "target_date_max": "2026-06-15",
        },
        "model_input_fields": ["forecast_high"],
    }
    corpus_path.write_text(
        json.dumps(
            {
                "bundle_sha256": bundle_sha,
                "corpus_lineage": lineage,
                "payload_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    from weather.release_artifacts import sha256_file

    digest = sha256_file(corpus_path)
    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap.verify_release",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "manifest_sha256": "a" * 64,
            "manifest": {
                "release_id": "r1",
                "artifacts": {
                    "inventory": [
                        {
                            "role": "training_evaluation_corpus",
                            "path": "contract/training_evaluation_corpus.json",
                            "sha256": digest,
                        }
                    ]
                },
            },
        },
    )

    observed, proof = _verified_release_research_lineage(
        release,
        expected_bundle_sha256=bundle_sha,
    )
    frozen = _corpus_manifest(
        {},
        bundle_sha,
        research_corpus_lineage=observed,
        research_corpus_lineage_provenance={
            "kind": "verified_immutable_release",
            "verification_status": "PASS",
            "source_release_id": "r1",
            "source_release_manifest_sha256": "a" * 64,
            "source_role_sha256": digest,
            "source_payload_sha256": "c" * 64,
        },
    )

    assert observed == lineage
    assert proof["lineage_source_release_id"] == "r1"
    assert frozen["lineage_source"]["kind"] == "verified_immutable_release"
    assert frozen["lineage_source"]["source_release_id"] == "r1"
    assert frozen["corpus_lineage"] == lineage


def test_first_party_lineage_binds_exact_code_owned_corpus_and_model_inputs(
    tmp_path,
    monkeypatch,
):
    history = tmp_path / "forecast-history"
    history.mkdir()
    bundle = tmp_path / "bundle.pkl"
    with bundle.open("wb") as handle:
        pickle.dump(
            {
                "models": {
                    "7": {"feature_names": ["forecast_high", "high_so_far"]}
                }
            },
            handle,
        )
    market_ids = list(_runtime_market_inventory()["market_ids"])
    selected_dates = ["2024-06-10", "2025-06-10"]
    population = {
        "policy_id": "test-first-party",
        "years": [2024, 2025],
        "selected_dates": selected_dates,
        "cutoff_hours_local": [7],
        "market_ids": market_ids,
        "station_day_exclusions": [],
        "expected_market_date_cutoff_count": len(market_ids) * 2,
    }

    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap._training_population_for_target",
        lambda _target: population,
    )
    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap.ForecastTrainingVariantResolver",
        lambda *_args, **_kwargs: object(),
    )

    def fake_build(spec, *, cutoff_hours, included_target_dates, **_kwargs):
        return [
            {
                "market_id": spec.id,
                "target_date": date.fromisoformat(target_date),
                "year": int(target_date[:4]),
                "cutoff_hour": cutoff_hours[0],
                "forecast_high": 80.0,
                "high_so_far": 75.0,
                "final_bucket": 81,
            }
            for target_date in sorted(included_target_dates)
        ]

    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap.build_market_records",
        fake_build,
    )

    lineage, proof = _first_party_research_lineage(
        model_bundle_path=bundle,
        forecast_history_root=history,
        target_date="2026-06-10",
        holdout_year=2025,
        forecast_training_variant="rich",
    )
    frozen = _corpus_manifest(
        {},
        "b" * 64,
        research_corpus_lineage=lineage,
        research_corpus_lineage_provenance=proof,
    )

    assert lineage["selection_training"]["row_count"] == len(market_ids)
    assert lineage["evaluation"]["row_count"] == len(market_ids)
    assert lineage["final_refit"]["row_count"] == len(market_ids) * 2
    assert lineage["model_input_fields"] == ["forecast_high", "high_so_far"]
    assert frozen["lineage_source"]["kind"] == "first_party_corpus_assembly"
    assert frozen["lineage_source"]["assembled_corpus_sha256"] == lineage[
        "final_refit"
    ]["sha256"]
    tampered = {**proof, "assembled_row_count": proof["assembled_row_count"] - 1}
    with pytest.raises(CandidateContractError, match="does not match the assembled corpus"):
        _corpus_manifest(
            {},
            "b" * 64,
            research_corpus_lineage=lineage,
            research_corpus_lineage_provenance=tampered,
        )


def test_first_party_lineage_blocks_an_incomplete_matrix(tmp_path, monkeypatch):
    history = tmp_path / "forecast-history"
    history.mkdir()
    bundle = tmp_path / "bundle.pkl"
    with bundle.open("wb") as handle:
        pickle.dump(
            {"models": {"7": {"feature_names": ["forecast_high"]}}},
            handle,
        )
    market_ids = list(_runtime_market_inventory()["market_ids"])
    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap._training_population_for_target",
        lambda _target: {
            "years": [2024, 2025],
            "selected_dates": ["2024-06-10", "2025-06-10"],
            "cutoff_hours_local": [7],
            "market_ids": market_ids,
            "station_day_exclusions": [],
            "expected_market_date_cutoff_count": len(market_ids) * 2,
        },
    )
    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap.ForecastTrainingVariantResolver",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "weather.operations.all_shadow_release_bootstrap.build_market_records",
        lambda *_args, **_kwargs: [],
    )

    with pytest.raises(AllShadowBootstrapError, match="exact code-owned matrix"):
        _first_party_research_lineage(
            model_bundle_path=bundle,
            forecast_history_root=history,
            target_date="2026-06-10",
            holdout_year=2025,
            forecast_training_variant="rich",
        )
