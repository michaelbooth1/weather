import json

from weather.operations.all_shadow_release_bootstrap import (
    _runtime_market_inventory,
    _verified_release_research_lineage,
    _verified_release_role_source,
    all_shadow_promotion,
)
from weather.operations.release_candidate_contract import _corpus_manifest


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
    )

    assert observed == lineage
    assert proof["lineage_source_release_id"] == "r1"
    assert frozen["lineage_source"] == "verified_immutable_release"
    assert frozen["corpus_lineage"] == lineage
