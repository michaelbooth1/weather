"""Small current-schema fixtures for source-family authorization tests."""

from __future__ import annotations

import json
import hashlib
import pickle
from copy import deepcopy
from pathlib import Path

from weather.backtesting.source_ablation_contract import (
    ALL_VARIANTS,
    SourceAblationContractError,
    members_for_variant,
)
from weather.backtesting.source_ablation_evidence import (
    applicable_market_ids_for_variant,
)
from weather.backtesting.replay_ablation import (
    paired_day_inference,
    paired_inference_sensitivities,
    paired_market_inference,
)
from weather.market.market_registry import REGISTRY
from weather.release_artifacts import (
    ACTIVE_POINTER_SCHEMA_VERSION,
    pointer_content_sha256,
)
from weather.reporting.source_gates.source_family_contracts import (
    EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS,
    EXPECTED_SOURCE_FAMILY_IDS,
)


OPERATIONAL_ABLATION_SCHEMA = "source_family_ablation_v0.3"
RESEARCH_ABLATION_SCHEMA = "source_family_ablation_v0.2"
INVENTORY_SCHEMA = "source_family_inventory_v0.2"
RATCHET_SCHEMA = "physical_feature_family_ratchet_v0.2"


def synthetic_receipt(path, digest_character):
    return {
        "path": path,
        "status": "PASS",
        "sha256": str(digest_character) * 64,
        "size_bytes": 100,
        "blockers": [],
    }


def write_active_release_identity(root, ablation_payload):
    """Write a canonical semantic active release matching an ablation fixture."""

    from tests.test_release_serving import _active_fixture
    from weather.release_serving import load_verified_active_serving_bundle

    root = Path(root)
    paths, _frozen, _release, releases_root, pointer_path = _active_fixture(
        root
    )
    serving_bundle = load_verified_active_serving_bundle(
        pointer_path=pointer_path,
        releases_root=releases_root,
        repo_root=paths["repo"],
        check_runtime=False,
    )
    model_binding = ablation_payload.setdefault("model_binding", {})
    market_ids = sorted(str(value) for value in serving_bundle.route["markets"])
    model_binding.update(
        {
            "status": serving_bundle.status,
            "binding_kind": "verified_active_release",
            "pointer_present": serving_bundle.pointer_present,
            "base_model_bound": serving_bundle.base_model_bound,
            "release_id": serving_bundle.release_id,
            "release_manifest_sha256": serving_bundle.manifest_sha256,
            "release_pointer_sha256": serving_bundle.pointer_sha256,
            "release_sequence": serving_bundle.sequence,
            "release_kind": serving_bundle.release_kind,
            "release_production_capable": serving_bundle.production_capable,
            "artifact_hashes": dict(serving_bundle.artifact_hashes),
            "market_ids": market_ids,
            "model_count": len(market_ids),
            "shared_explicit_bundle": True,
            "shared_verified_bundle": True,
            "serving_or_release_authorization": True,
        }
    )
    return pointer_path


def bind_candidate_replay_to_active_release(
    root,
    *,
    ablation_path,
    candidate_replay_path,
    model_bytes,
):
    """Publish requested model content in a semantic serving release."""

    from tests.operations.test_release_candidate_contract import (
        _fixture,
        _freeze,
        _production_evidence,
    )
    from weather.operations.release_manifest import create_release
    from weather.release_contract import PRODUCTION_CANDIDATE_MODE
    from weather.release_serving import load_verified_active_serving_bundle

    root = Path(root)
    paths = _fixture(root)
    requested_artifact = pickle.loads(model_bytes)
    with paths["bundle"].open("rb") as handle:
        semantic_artifact = pickle.load(handle)
    requested_models = (
        requested_artifact.get("models")
        if isinstance(requested_artifact, dict)
        else None
    )
    if isinstance(requested_models, dict) and requested_models:
        template = deepcopy(next(iter(semantic_artifact["models"].values())))
        merged_models = {}
        for hour, model in requested_models.items():
            merged = {
                **deepcopy(template),
                **(
                    deepcopy(model)
                    if isinstance(model, dict)
                    else {"model": model}
                ),
            }
            names = list(merged.get("feature_names") or [])
            imputer = merged.get("imputer")
            if isinstance(imputer, dict) and len(
                list(imputer.get("statistics") or [])
            ) != len(names):
                merged["imputer"] = {
                    **imputer,
                    "statistics": [0.0 for _name in names],
                }
            merged_models[str(hour)] = merged
        semantic_artifact["models"] = merged_models
    if isinstance(requested_artifact, dict):
        for field, value in requested_artifact.items():
            if field != "models":
                semantic_artifact[field] = deepcopy(value)
    lineage = semantic_artifact.get("corpus_lineage")
    if isinstance(lineage, dict):
        lineage["model_input_fields"] = sorted(
            {
                str(name)
                for model in semantic_artifact["models"].values()
                if isinstance(model, dict)
                for name in (model.get("feature_names") or [])
            }
        )
    with paths["bundle"].open("wb") as handle:
        pickle.dump(semantic_artifact, handle)

    frozen = _freeze(
        paths,
        candidate_mode=PRODUCTION_CANDIDATE_MODE,
        point_in_time_artifacts=_production_evidence(paths),
    )
    release_id = "r1"
    releases_root = root / "releases"
    release = create_release(
        release_id=release_id,
        candidate_dir=paths["candidate"],
        declarations=list(frozen["declarations"]),
        route=frozen["route"],
        expected_live_runtimes=["snapshot_loop"],
        releases_root=releases_root,
        repo_root=paths["repo"],
        code_identity={
            "git_commit": "a" * 40,
            "git_branch": "main",
            "git_dirty": False,
            "dirty_fingerprint": None,
        },
        runtime_versions={
            "python": "3.13.0",
            "implementation": "CPython",
            "platform": "test",
            "direct_dependencies": {
                "scikit-learn": {
                    "version": "1.7.0",
                    "declared": "scikit-learn",
                }
            },
        },
        runtime_identity={
            "source_fingerprint": "source",
            "git_commit": "a" * 40,
        },
    )
    pointer = {
        "schema_version": ACTIVE_POINTER_SCHEMA_VERSION,
        "sequence": 1,
        "action": "PROMOTE",
        "changed_at_utc": "2026-07-23T00:00:00+00:00",
        "active_release_id": release_id,
        "active_manifest_sha256": release["manifest_sha256"],
        "previous_release_id": None,
        "previous_manifest_sha256": None,
    }
    pointer["pointer_sha256"] = pointer_content_sha256(pointer)
    pointer_path = releases_root / "current_release.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    serving_bundle = load_verified_active_serving_bundle(
        pointer_path=pointer_path,
        releases_root=releases_root,
        repo_root=paths["repo"],
        check_runtime=False,
    )
    ablation_payload = json.loads(Path(ablation_path).read_text(encoding="utf-8"))
    model_binding = ablation_payload.setdefault("model_binding", {})
    market_ids = sorted(str(value) for value in serving_bundle.route["markets"])
    model_binding.update(
        {
            "status": serving_bundle.status,
            "binding_kind": "verified_active_release",
            "pointer_present": serving_bundle.pointer_present,
            "base_model_bound": serving_bundle.base_model_bound,
            "release_id": serving_bundle.release_id,
            "release_manifest_sha256": serving_bundle.manifest_sha256,
            "release_pointer_sha256": serving_bundle.pointer_sha256,
            "release_sequence": serving_bundle.sequence,
            "release_kind": serving_bundle.release_kind,
            "release_production_capable": serving_bundle.production_capable,
            "artifact_hashes": dict(serving_bundle.artifact_hashes),
            "market_ids": market_ids,
            "model_count": len(market_ids),
            "shared_explicit_bundle": True,
            "shared_verified_bundle": True,
            "serving_or_release_authorization": True,
        }
    )
    Path(ablation_path).write_text(json.dumps(ablation_payload), encoding="utf-8")

    released_model = Path(
        serving_bundle.artifact_paths["pooled_band_model"]
    ).resolve()
    raw = released_model.read_bytes()
    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    replay_binding = deepcopy(model_binding)
    replay_binding.update(
        {
            "artifact_path": str(released_model),
            "artifact_sha256": artifact_sha256,
            "artifact_size_bytes": len(raw),
            "artifact_role": "pooled_band_model",
            "artifact_kind": "model",
            "prediction_mode": semantic_artifact["prediction_mode"],
            "serving_or_release_authorization": False,
        }
    )
    candidate_replay = {
        "serving_or_release_authorization": False,
        "artifact": {
            "path": str(released_model),
            "sha256": artifact_sha256,
            "size_bytes": len(raw),
            "prediction_mode": semantic_artifact["prediction_mode"],
        },
        "model_binding": replay_binding,
    }
    Path(candidate_replay_path).write_text(
        json.dumps(candidate_replay),
        encoding="utf-8",
    )
    return pointer_path


def operational_ablation_contract():
    return {
        "status": "PASS",
        "schema_version": OPERATIONAL_ABLATION_SCHEMA,
        "expected_schema_version": OPERATIONAL_ABLATION_SCHEMA,
        "research_schema_version": RESEARCH_ABLATION_SCHEMA,
        "blockers": [],
    }


def operational_ablation_payload(variants, *, market_days_scored=3):
    supplied_variants = [deepcopy(source) for source in variants]
    candidate_reanalysis = [
        row.get("variant") for row in supplied_variants
    ] == ["reanalysis_synoptic"]
    if candidate_reanalysis:
        normalized_sources = supplied_variants
    else:
        supplied_by_variant = {
            row["variant"]: row for row in supplied_variants
        }
        normalized_sources = [
            supplied_by_variant.get(
                variant,
                {"variant": variant, "delta": 0.0},
            )
            for variant in ALL_VARIANTS
        ]
    normalized = []
    for source in normalized_sources:
        row = deepcopy(source)
        row.setdefault("n", 100)
        row.setdefault("delta", 0.01)
        normalized.append(row)
    date_count = max(
        [int(market_days_scored)]
        + [int(row.get("market_days") or 0) for row in normalized]
    )
    if date_count < 2:
        raise ValueError("operational ablation fixture requires at least two dates")
    market_ids = sorted(REGISTRY)
    effective_market_days = len(market_ids) * date_count
    scored_variants = [row["variant"] for row in normalized]
    requested = ["reanalysis_synoptic"] if candidate_reanalysis else list(ALL_VARIANTS)
    variant_market_ids = {}
    for row in normalized:
        try:
            ablated_sources = list(members_for_variant(row["variant"]))
        except SourceAblationContractError:
            if row["variant"] != "reanalysis_synoptic":
                raise
            ablated_sources = ["reanalysis_synoptic"]
        applicable_markets = applicable_market_ids_for_variant(row["variant"])
        if not applicable_markets:
            raise ValueError(
                f"fixture variant has no applicable markets: {row['variant']}"
            )
        variant_market_ids[row["variant"]] = applicable_markets
        variant_market_day_count = len(applicable_markets) * date_count
        row["n"] = max(int(row["n"]), variant_market_day_count)
        row["market_days"] = variant_market_day_count
        row["ablated_sources"] = ablated_sources
        row["market_days_source_helped"] = (
            variant_market_day_count if float(row["delta"]) > 0.0001 else 0
        )
        row["market_days_source_hurt"] = (
            variant_market_day_count if float(row["delta"]) < -0.0001 else 0
        )
    dates = [
        f"2026-06-{day_index + 1:02d}"
        for day_index in range(date_count)
    ]
    market_days = [
        {
            "market_day": f"{market_id} {target_date}",
            "settlement_source": "daily_summary",
        }
        for market_id in market_ids
        for target_date in dates
    ]
    day_effects = {}
    for row in normalized:
        variant_days = [
            {
                "market_day": f"{market_id} {target_date}",
                "settlement_source": "daily_summary",
            }
            for market_id in variant_market_ids[row["variant"]]
            for target_date in dates
        ]
        base_support, extra_support = divmod(row["n"], len(variant_days))
        day_effects[row["variant"]] = [
            {
                "market_day": day["market_day"],
                "n": base_support + (index < extra_support),
                "delta": row["delta"],
                "brier_delta": row["delta"],
                "logloss_delta": row["delta"],
            }
            for index, day in enumerate(variant_days)
        ]
    split_dates = {"tune": [dates[0]], "holdout": dates[1:]}
    paired = paired_day_inference(day_effects, split_dates)
    robustness = paired_inference_sensitivities(
        day_effects,
        market_days,
        split_dates=split_dates,
        required_market_ids=tuple(sorted(REGISTRY)),
    )
    market_inference = paired_market_inference(
        day_effects,
        split_dates,
        day_meta=market_days,
    )
    corpus_receipt = {
        "path": "C:/synthetic/promotion_corpus.json",
        "status": "PASS",
        "sha256": "1" * 64,
        "size_bytes": 100,
        "blockers": [],
    }
    return {
        "schema_version": OPERATIONAL_ABLATION_SCHEMA,
        "evidence_mode": "operational",
        "research_only": False,
        "promotion_preflight_evidence_authorization": True,
        "include_reconstructed": False,
        "model_binding": {
            "status": "BOUND",
            "binding_kind": "verified_active_release",
            "pointer_present": True,
            "base_model_bound": True,
            "release_id": "synthetic-release",
            "release_manifest_sha256": "2" * 64,
            "release_pointer_sha256": "3" * 64,
            "market_ids": market_ids,
            "model_count": len(market_ids),
            "shared_explicit_bundle": True,
            "shared_verified_bundle": True,
            "serving_or_release_authorization": True,
        },
        "serving_or_release_authorization": False,
        "corpus": {
            "path": corpus_receipt["path"],
            "manifest_sha256": corpus_receipt["sha256"],
            "schema_version": "promotion_corpus_v0.2",
            "corpus_hash": "4" * 64,
            "as_of": "2026-06-30",
            "market_day_count": effective_market_days,
            "snapshot_count": 100,
            "target_dates": dates,
            "market_ids": market_ids,
            "input_verification": "PASS",
        },
        "input_receipts": {
            "corpus": corpus_receipt,
            "tune_dates": {
                "path": "C:/synthetic/tune_dates.txt",
                "status": "PASS",
                "sha256": "5" * 64,
                "size_bytes": 10,
                "blockers": [],
            },
            "holdout_dates": {
                "path": "C:/synthetic/holdout_dates.txt",
                "status": "PASS",
                "sha256": "6" * 64,
                "size_bytes": 10,
                "blockers": [],
            },
        },
        "split_dates": split_dates,
        "requested_variants": requested,
        "summary": {
            "variant_count": len(normalized),
            "market_days_scored": effective_market_days,
            "rows_scored": sum(row["n"] for row in normalized),
            "slice_effect_count": 0,
        },
        "variants": normalized,
        "day_effects": day_effects,
        "paired_inference": paired,
        "robustness_contract": {
            "settlement_scope": (
                "promotion_corpus settlement_source exactly equals daily_summary"
            ),
            "complete_panel_scope": (
                "corpus and variant-scored market-ID sets both exactly equal "
                "the sealed 12-market set; support selected without outcomes"
            ),
            "cluster_unit": "fleet target date",
            "primary_market_ids": sorted(REGISTRY),
            "per_market_action_scope": (
                "holdout promotion-corpus daily_summary market-days only"
            ),
            "outcome_independent_scope_selection": True,
        },
        "robustness_inference": robustness,
        "market_inference": market_inference,
        "market_days": market_days,
        "slice_effects": [],
    }


def operational_inventory(rows):
    contract = operational_ablation_contract()
    supplied = {row["family_id"]: deepcopy(row) for row in rows}
    inventory = []
    for family_id in EXPECTED_SOURCE_FAMILY_IDS:
        row = supplied.get(family_id, {"family_id": family_id})
        active_columns = list(row.get("active_model_feature_columns") or [])
        active_status = row.get("active_model_usage_status")
        if not active_status:
            active_status = (
                "ACTIVE_FEATURES" if active_columns else "NOT_USED_BY_ACTIVE_ARTIFACT"
            )
        row["active_model_usage_status"] = active_status
        row["active_model_feature_columns"] = active_columns
        row["active_model_feature_count"] = len(active_columns)
        row["model_influence"] = active_status != "NOT_USED_BY_ACTIVE_ARTIFACT"
        row["configured_model_influence"] = True
        row.setdefault("lineage_status", "PASS")
        row.setdefault("train_serve_parity_status", "PASS")
        row.setdefault("live_only_policy", "parity_required_before_promotion")
        candidate_requested = (
            (row.get("promotion_decision") or {}).get("status")
            == "PROMOTION_CANDIDATE"
        )
        ablation = row.setdefault(
            "ablation",
            {
                "status": "PRESENT",
                "settlement_scored": True,
                "evidence_source": "source_family_ablation",
                "rows": 100,
                "days": 3,
                "delta": 0.01 if candidate_requested else 0.0,
            },
        )
        if candidate_requested:
            ablation.setdefault("status", "PRESENT")
            ablation.setdefault("settlement_scored", True)
            ablation["evidence_source"] = "source_family_ablation"
            ablation["evidence_contract"] = contract
            ablation.setdefault(
                "variant",
                EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS[family_id][0],
            )
            ablation.setdefault("rows", 100)
            ablation.setdefault("days", 3)
            ablation.setdefault("delta", 0.01)
        if "promotion_decision" not in row:
            if row["live_only_policy"] == "historical_only_not_live_serving":
                decision_status = "HOLD_HISTORICAL_ONLY"
            elif row["lineage_status"] != "PASS":
                decision_status = "BLOCK_LINEAGE"
            elif row["train_serve_parity_status"] != "PASS":
                decision_status = "BLOCK_PARITY"
            elif ablation.get("status") == "BLOCKED_UNSAFE_ARTIFACT":
                decision_status = "BLOCK_UNSAFE_ABLATION"
            elif ablation.get("status") != "PRESENT":
                decision_status = "BLOCK_MISSING_ABLATION"
            elif float(ablation.get("delta") or 0.0) <= 0:
                decision_status = "HOLD_NO_LIFT"
            else:
                decision_status = "PROMOTION_CANDIDATE"
            row["promotion_decision"] = {"status": decision_status}
        if family_id == "reanalysis_synoptic":
            row.setdefault("artifact_lane_consistency", {"status": "NO_ARTIFACT_LANE"})
        inventory.append(row)

    blocked_rows = []
    for row in inventory:
        decision = row.get("promotion_decision") or {}
        lane = row.get("artifact_lane_consistency") or {}
        if row["model_influence"] and (
            decision.get("status") != "PROMOTION_CANDIDATE"
            or (
                row["family_id"] == "reanalysis_synoptic"
                and str(lane.get("status") or "").startswith("BLOCK")
            )
        ):
            blocked_rows.append(row)

    blocked_families = [row["family_id"] for row in blocked_rows]
    preflight_status = "BLOCK" if blocked_rows else "PASS"
    preflight = {
        "status": preflight_status,
        "blocked_family_count": len(blocked_rows),
        "blocked_families": blocked_families,
        "blocking_rows": [
            {
                "family_id": row["family_id"],
                "lineage_status": row.get("lineage_status"),
                "train_serve_parity_status": row.get("train_serve_parity_status"),
                "ablation_status": (row.get("ablation") or {}).get("status"),
                "decision": (row.get("promotion_decision") or {}).get("status"),
                "artifact_lane_consistency": (
                    row.get("artifact_lane_consistency") or {}
                ).get("status"),
                "action": (row.get("promotion_decision") or {}).get("action"),
            }
            for row in blocked_rows
        ],
        "ablation_evidence_contract": contract,
        "current_input_verification": {"status": "PASS", "blockers": []},
        "blocking_evidence_count": 0,
        "blocking_evidence": [],
    }
    candidate_replay_receipt = synthetic_receipt(
        "C:/synthetic/candidate_replay.json",
        "9",
    )
    candidate_artifact_receipt = synthetic_receipt(
        "C:/synthetic/candidate_model.pkl",
        "a",
    )
    feature_names = sorted(
        {
            column
            for row in inventory
            for column in (row.get("active_model_feature_columns") or [])
        }
    )
    active_overlay_families = sorted(
        row["family_id"]
        for row in inventory
        if row.get("active_model_usage_status") == "ACTIVE_OVERLAY"
    )
    active_model_usage = {
        "status": "PRESENT",
        "artifact_path": candidate_artifact_receipt["path"],
        "feature_count": len(feature_names),
        "feature_names": feature_names,
        "active_overlay_families": active_overlay_families,
        "reanalysis_promotion_lane": None,
        "error": None,
        "verification": {
            "status": "PASS",
            "candidate_replay_receipt": deepcopy(candidate_replay_receipt),
            "candidate_replay_current_verification": {
                "status": "PASS",
                "blockers": [],
            },
            "artifact_receipt": deepcopy(candidate_artifact_receipt),
            "binding_kind": "verified_active_release",
            "active_release_initial": {"status": "PASS", "blockers": []},
            "active_release_closing": {"status": "PASS", "blockers": []},
            "blockers": [],
        },
    }
    return {
        "schema_version": INVENTORY_SCHEMA,
        "status": preflight_status,
        "serving_or_release_authorization": False,
        "ablation_input_receipt": synthetic_receipt(
            "C:/synthetic/source_family_ablation.json",
            "7",
        ),
        "candidate_replay_json": candidate_replay_receipt["path"],
        "candidate_replay_input_receipt": candidate_replay_receipt,
        "candidate_model_artifact_input_receipt": candidate_artifact_receipt,
        "scan_input_closure": {
            "status": "BLOCK",
            "complete": False,
            "serving_or_release_authorization": False,
            "blockers": [
                "synthetic inventory scan inputs are not an authorizing closure"
            ],
        },
        "ablation_evidence_contract": contract,
        "summary": {
            "family_count": len(inventory),
            "blocking_family_count": len(blocked_rows),
            "ablation_evidence_contract_status": "PASS",
            "active_model_usage_status": active_model_usage["status"],
            "active_model_feature_count": active_model_usage["feature_count"],
            "active_overlay_families": active_overlay_families,
        },
        "inventory": inventory,
        "active_model_usage": active_model_usage,
        "promotion_preflight": preflight,
        "current_input_verification": {"status": "PASS", "blockers": []},
    }


def operational_ratchet_payload():
    physical_ids = [
        family_id
        for family_id in EXPECTED_SOURCE_FAMILY_IDS
        if family_id != "clob_microstructure"
    ]
    slice_kinds = (
        "market",
        "cutoff_regime",
        "market_cutoff_regime",
        "settlement_distance",
    )
    slices = [
        {
            "family_id": family_id,
            "variant": EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS[family_id][0],
            "slice": slice_kind,
            "n": 10,
            "delta": 0.01,
        }
        for family_id in physical_ids
        for slice_kind in slice_kinds
    ]
    slice_summary = {
        "slice_count": len(slice_kinds),
        "valid_slice_count": len(slice_kinds),
        "invalid_slice_count": 0,
        "slice_kinds": sorted(slice_kinds),
        "required_slice_kinds_present": sorted(slice_kinds),
        "missing_required_slice_kinds": [],
        "positive_slice_count": len(slice_kinds),
        "positive_slice_kinds": sorted(slice_kinds),
        "missing_positive_slice_kinds": [],
        "harmful_slice_count": 0,
        "worst_harm": None,
    }
    families = [
        {
            "family_id": family_id,
            "status": "PROMOTION_ELIGIBLE",
            "rollup_bucket": "ready_for_retraining",
            "blockers": [],
            "lineage_status": "PASS",
            "train_serve_parity_status": "PASS",
            "active_model_feature_count": 1,
            "active_model_usage_status": "ACTIVE_FEATURES",
            "model_influence": True,
            "live_only": False,
            "live_only_policy": "parity_required_before_promotion",
            "ablation": {
                "status": "PRESENT",
                "variant": EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS[family_id][0],
                "rows": 100,
                "days": 3,
                "delta": 0.01,
            },
            "ablation_variants": list(
                EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS[family_id]
            ),
            "decision_ablation_variants": [
                EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS[family_id][0]
            ],
            "settlement_slice_summary": deepcopy(slice_summary),
        }
        for family_id in physical_ids
    ]
    inventory_contract = {
        "status": "PASS",
        "schema_version": INVENTORY_SCHEMA,
        "expected_schema_version": INVENTORY_SCHEMA,
        "serving_or_release_authorization": False,
        "blockers": [],
    }
    ablation_contract = operational_ablation_contract()
    inventory_receipt = synthetic_receipt(
        "C:/synthetic/source_family_inventory.json",
        "8",
    )
    ablation_receipt = synthetic_receipt(
        "C:/synthetic/source_family_ablation.json",
        "7",
    )
    return {
        "schema_version": RATCHET_SCHEMA,
        "status": "PASS",
        "serving_or_release_authorization": False,
        "inputs": {
            "source_family_inventory_contract": inventory_contract,
            "ablation_evidence_contract": ablation_contract,
            "source_family_inventory_receipt": inventory_receipt,
            "source_family_ablation_receipt": ablation_receipt,
            "inventory_source_family_ablation_receipt": deepcopy(
                ablation_receipt
            ),
            "input_binding_contract": {"status": "PASS", "blockers": []},
            "current_input_verification": {"status": "PASS", "blockers": []},
            "derived_rebuild_contract": {"status": "PASS", "blockers": []},
        },
        "summary": {
            "family_count": len(families),
            "excluded_overlay_family_count": 1,
            "blocking_family_count": 0,
            "status_counts": {"PROMOTION_ELIGIBLE": len(families)},
            "rollup_bucket_counts": {"ready_for_retraining": len(families)},
            "settlement_slice_row_count": len(slices),
        },
        "rollup": {
            "ready_for_retraining": physical_ids,
            "diagnostic_only": [],
            "evidence_blocked": [],
        },
        "families": families,
        "settlement_sliced_lift": slices,
        "excluded_market_overlay_families": [
            {
                "family_id": "clob_microstructure",
                "reason": (
                    "market-informed/CLOB-derived overlay excluded from "
                    "physical-weather ratchet"
                ),
                "lineage_status": "PASS",
                "train_serve_parity_status": "PASS",
            }
        ],
    }
