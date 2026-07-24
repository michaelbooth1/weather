import json
import pickle
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tests.reporting.source_family_contract_fixtures import (
    bind_candidate_replay_to_active_release,
    operational_ablation_payload,
    operational_inventory,
)
from weather.reporting.source_gates.source_artifact_binding import (
    stable_artifact,
    stable_json_artifact,
    verify_current_active_release_binding,
)
from weather.reporting.source_gates.source_family_current_inputs import (
    _candidate_model_usage_current_projection,
    _current_ablation_input_verification,
    source_family_inventory_current_integrity_contract,
)
from weather.reporting.source_gates.source_family_contracts import (
    source_family_inventory_integrity_contract,
)
from weather.reporting.source_gates.source_family_inventory import (
    FAMILY_SPECS,
    active_family_usage,
    active_model_usage,
)
from weather.market.market_registry import REGISTRY
from weather.reporting.promotion.promotion_corpus import (
    corpus_hash,
    summarize_entries,
)


def _write_candidate_bound_chain(tmp_path, artifact):
    artifact_path = (tmp_path / "candidate.pkl").resolve()
    artifact_path.write_bytes(pickle.dumps(artifact))
    _raw, artifact_receipt = stable_artifact(artifact_path)
    artifact_metadata = {
        "path": artifact_receipt["path"],
        "sha256": artifact_receipt["sha256"],
        "size_bytes": artifact_receipt["size_bytes"],
        "prediction_mode": "band_binary",
    }
    model_binding = {
        "status": "BOUND_CANDIDATE_ARTIFACT",
        "binding_kind": "candidate_artifact",
        "promotion_evidence_binding": True,
        "artifact_path": artifact_receipt["path"],
        "artifact_sha256": artifact_receipt["sha256"],
        "artifact_size_bytes": artifact_receipt["size_bytes"],
        "prediction_mode": "band_binary",
        "serving_or_release_authorization": False,
    }
    ablation_payload = {
        "evidence_source": "candidate_artifact_band_ablation",
        "artifact": deepcopy(artifact_metadata),
        "model_binding": deepcopy(model_binding),
        "input_receipts": {"artifact": deepcopy(artifact_receipt)},
    }
    replay_payload = {
        "serving_or_release_authorization": False,
        "artifact": deepcopy(artifact_metadata),
        "model_binding": deepcopy(model_binding),
    }
    replay_path = (tmp_path / "candidate_replay.json").resolve()
    replay_path.write_text(
        json.dumps(replay_payload, sort_keys=True),
        encoding="utf-8",
    )
    loaded_replay, replay_receipt = stable_json_artifact(replay_path)
    return {
        "ablation": ablation_payload,
        "artifact_path": artifact_path,
        "artifact_receipt": artifact_receipt,
        "replay_path": replay_path,
        "replay_payload": loaded_replay,
        "replay_receipt": replay_receipt,
    }


def test_detached_candidate_bound_usage_never_deserializes_pickle(tmp_path):
    chain = _write_candidate_bound_chain(
        tmp_path,
        {"models": {"12": {"feature_names": ["forecast_high"]}}},
    )

    with patch(
        "weather.reporting.source_gates.source_family_inventory.pickle.loads"
    ) as deserialize:
        result = active_model_usage(
            chain["replay_payload"],
            candidate_replay_receipt=chain["replay_receipt"],
            ablation_payload=chain["ablation"],
            active_release_verification={},
        )

    deserialize.assert_not_called()
    assert result["status"] == "BLOCK_UNTRUSTED"
    assert result["feature_names"] == []
    assert result["verification"]["status"] == "BLOCK"
    assert any(
        "independently anchored operational candidate-evidence trust root"
        in blocker
        for blocker in result["verification"]["blockers"]
    )


def test_payload_not_parsed_from_replay_receipt_is_never_deserialized(tmp_path):
    chain = _write_candidate_bound_chain(
        tmp_path,
        {"models": {"12": {"feature_names": ["forecast_high"]}}},
    )
    substituted = deepcopy(chain["replay_payload"])
    substituted["microstructure"] = {"aggregate": {"n": 10}}

    with patch(
        "weather.reporting.source_gates.source_family_inventory.pickle.loads"
    ) as deserialize:
        result = active_model_usage(
            substituted,
            candidate_replay_receipt=chain["replay_receipt"],
            ablation_payload=chain["ablation"],
            active_release_verification={},
        )

    deserialize.assert_not_called()
    assert result["status"] == "BLOCK_UNTRUSTED"
    assert any(
        "was not parsed from the receipted current bytes" in blocker
        for blocker in result["verification"]["blockers"]
    )


def test_hash_drifted_candidate_pickle_is_never_deserialized(tmp_path):
    chain = _write_candidate_bound_chain(
        tmp_path,
        {"models": {"12": {"feature_names": ["forecast_high"]}}},
    )
    chain["artifact_path"].write_bytes(
        pickle.dumps({"models": {"12": {"feature_names": ["nws_grid_high"]}}})
    )

    with patch(
        "weather.reporting.source_gates.source_family_inventory.pickle.loads"
    ) as deserialize:
        result = active_model_usage(
            chain["replay_payload"],
            candidate_replay_receipt=chain["replay_receipt"],
            ablation_payload=chain["ablation"],
            active_release_verification={},
        )

    deserialize.assert_not_called()
    assert result["status"] == "BLOCK_UNTRUSTED"
    assert any(
        "sha256 differs" in blocker
        for blocker in result["verification"]["blockers"]
    )


def test_current_projection_cannot_elevate_detached_candidate_receipts(tmp_path):
    chain = _write_candidate_bound_chain(
        tmp_path,
        {"models": {"12": {"feature_names": ["forecast_high"]}}},
    )
    usage = active_model_usage(
        chain["replay_payload"],
        candidate_replay_receipt=chain["replay_receipt"],
        ablation_payload=chain["ablation"],
        active_release_verification={},
    )
    rows = []
    for spec in FAMILY_SPECS:
        rows.append(
            {
                "family_id": spec.family_id,
                **active_family_usage(spec, usage),
            }
        )
    inventory = {
        "candidate_replay_json": chain["replay_receipt"]["path"],
        "candidate_replay_input_receipt": chain["replay_receipt"],
        "candidate_model_artifact_input_receipt": chain["artifact_receipt"],
        "active_model_usage": usage,
        "summary": {
            "active_model_usage_status": usage["status"],
            "active_model_feature_count": usage["feature_count"],
            "active_overlay_families": usage["active_overlay_families"],
        },
        "inventory": rows,
    }

    result = _candidate_model_usage_current_projection(
        inventory,
        chain["ablation"],
        {},
    )
    assert result["status"] == "BLOCK"
    assert any(
        "independently anchored operational candidate-evidence trust root"
        in blocker
        for blocker in result["blockers"]
    )

    chain["replay_path"].write_text(
        json.dumps(
            {
                **chain["replay_payload"],
                "serving_or_release_authorization": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with patch(
        "weather.reporting.source_gates.source_family_inventory.pickle.loads"
    ) as deserialize:
        result = _candidate_model_usage_current_projection(
            inventory,
            chain["ablation"],
            {},
        )
    deserialize.assert_not_called()
    assert result["status"] == "BLOCK"
    assert any("sha256 differs" in blocker for blocker in result["blockers"])


def test_current_ablation_inputs_revalidate_corpus_and_split_semantics(tmp_path):
    dates = ["2026-06-01", "2026-06-02"]
    entries = [
        {
            "event_slug": f"{market_id}-{target_date}",
            "market_id": market_id,
            "target_date": target_date,
            "snapshot_count": 1,
            "settlement_source": "daily_summary",
            "snapshot_ids": [f"{market_id}-{target_date}-snapshot"],
        }
        for market_id in sorted(REGISTRY)
        for target_date in dates
    ]
    manifest = {
        "schema_version": "promotion_corpus_v0.2",
        "as_of": "2026-06-03",
        "include_reconstructed": False,
        "entries": entries,
        "summary": summarize_entries(entries),
    }
    manifest["corpus_hash"] = corpus_hash(entries)
    corpus_path = (tmp_path / "promotion_corpus.json").resolve()
    corpus_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    _raw, corpus_receipt = stable_artifact(corpus_path)

    tune_path = (tmp_path / "tune_dates.txt").resolve()
    tune_path.write_text(dates[0] + "\n", encoding="utf-8")
    _raw, tune_receipt = stable_artifact(tune_path)
    holdout_path = (tmp_path / "holdout_dates.txt").resolve()
    holdout_path.write_text(dates[1] + "\n", encoding="utf-8")
    _raw, holdout_receipt = stable_artifact(holdout_path)
    ablation_payload = {
        "corpus": {
            "path": corpus_receipt["path"],
            "manifest_sha256": corpus_receipt["sha256"],
            "schema_version": manifest["schema_version"],
            "corpus_hash": manifest["corpus_hash"],
            "as_of": manifest["as_of"],
            "market_day_count": manifest["summary"]["market_day_count"],
            "snapshot_count": manifest["summary"]["snapshot_count"],
            "target_dates": dates,
            "market_ids": sorted(REGISTRY),
            "input_verification": "PASS",
        },
        "split_dates": {"tune": [dates[0]], "holdout": [dates[1]]},
        "input_receipts": {
            "corpus": corpus_receipt,
            "tune_dates": tune_receipt,
            "holdout_dates": holdout_receipt,
        },
    }

    results, blockers = _current_ablation_input_verification(
        ablation_payload
    )
    assert blockers == []
    assert all(result["status"] == "PASS" for result in results.values())

    tune_path.write_text(dates[1] + "\n", encoding="utf-8")
    results, blockers = _current_ablation_input_verification(
        ablation_payload
    )
    assert results["tune_dates"]["status"] == "BLOCK"
    assert any("sha256 differs" in blocker for blocker in blockers)


def test_current_integrity_cannot_bypass_blocked_root_preflight(monkeypatch):
    payload = operational_inventory(
        [
            {
                "family_id": "forecast_baseline",
                "active_model_feature_columns": ["forecast_high"],
                "ablation": {
                    "status": "PRESENT",
                    "variant": "all_forecasts",
                    "settlement_scored": True,
                    "rows": 100,
                    "days": 3,
                    "delta": 0.0,
                },
            }
        ]
    )
    assert payload["status"] == "BLOCK"
    assert source_family_inventory_integrity_contract(payload)["status"] == "PASS"
    current_pass = {
        "status": "PASS",
        "serving_or_release_authorization": False,
        "blockers": [],
    }
    monkeypatch.setattr(
        "weather.reporting.source_gates.source_family_current_inputs."
        "load_source_family_inventory_current_inputs",
        lambda *_args, **_kwargs: ({}, current_pass),
    )

    result = source_family_inventory_current_integrity_contract(payload)

    assert result["status"] == "BLOCK"
    assert result["operational_contract"]["status"] == "BLOCK"
    assert any(
        "inventory status is not PASS" in blocker
        for blocker in result["blockers"]
    )
    assert any(
        "promotion preflight is not PASS" in blocker
        for blocker in result["blockers"]
    )


def test_active_release_graph_is_reverified_before_deserialization(tmp_path):
    ablation_path = tmp_path / "source_family_ablation.json"
    ablation_path.write_text(
        json.dumps(
            operational_ablation_payload(
                [{"variant": "all_forecasts", "delta": 0.01}]
            )
        ),
        encoding="utf-8",
    )
    replay_path = tmp_path / "candidate_replay.json"
    pointer_path = bind_candidate_replay_to_active_release(
        tmp_path,
        ablation_path=ablation_path,
        candidate_replay_path=replay_path,
        model_bytes=pickle.dumps(
            {"models": {"12": {"feature_names": ["forecast_high"]}}}
        ),
    )
    ablation, _ablation_receipt = stable_json_artifact(ablation_path)
    replay, replay_receipt = stable_json_artifact(replay_path)
    active_release = verify_current_active_release_binding(
        ablation,
        pointer_path=pointer_path,
        releases_root=pointer_path.parent,
    )
    assert active_release["status"] == "PASS"
    initial_usage = active_model_usage(
        replay,
        candidate_replay_receipt=replay_receipt,
        ablation_payload=ablation,
        active_release_verification=active_release,
        active_release_pointer=pointer_path,
        active_releases_root=pointer_path.parent,
    )
    assert initial_usage["status"] == "PRESENT", initial_usage

    generic_role_replay = deepcopy(replay)
    generic_role_replay["model_binding"]["artifact_role"] = "weather_model"
    replay_path.write_text(
        json.dumps(generic_role_replay),
        encoding="utf-8",
    )
    generic_role_replay, generic_role_receipt = stable_json_artifact(
        replay_path
    )
    with patch(
        "weather.reporting.source_gates.source_family_inventory.pickle.loads"
    ) as deserialize:
        generic_role_result = active_model_usage(
            generic_role_replay,
            candidate_replay_receipt=generic_role_receipt,
            ablation_payload=ablation,
            active_release_verification=active_release,
            active_release_pointer=pointer_path,
            active_releases_root=pointer_path.parent,
        )
    deserialize.assert_not_called()
    assert generic_role_result["status"] == "BLOCK_UNTRUSTED"
    assert any(
        "artifact_role must equal pooled_band_model" in blocker
        for blocker in generic_role_result["verification"]["blockers"]
    )

    replay_path.write_text(json.dumps(replay), encoding="utf-8")
    replay, replay_receipt = stable_json_artifact(replay_path)
    released_model = Path(replay["artifact"]["path"])
    released_model.write_bytes(pickle.dumps({"models": {}}))
    with patch(
        "weather.reporting.source_gates.source_family_inventory.pickle.loads"
    ) as deserialize:
        result = active_model_usage(
            replay,
            candidate_replay_receipt=replay_receipt,
            ablation_payload=ablation,
            active_release_verification=active_release,
            active_release_pointer=pointer_path,
            active_releases_root=pointer_path.parent,
        )

    deserialize.assert_not_called()
    assert result["status"] == "BLOCK_UNTRUSTED"
    assert any(
        "canonical trusted serving verification" in blocker
        for blocker in result["verification"]["blockers"]
    )
