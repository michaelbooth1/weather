import json
from copy import deepcopy

from weather.backtesting.replay_ablation import (
    paired_day_inference,
    paired_inference_sensitivities,
    paired_market_inference,
)
from weather.backtesting.source_ablation_evidence import (
    applicable_market_ids_for_variant,
)
from weather.reporting.promotion.readers import (
    _read_physical_feature_family_ratchet,
)
from weather.reporting.source_gates.physical_feature_family_ratchet import (
    build_ratchet,
    physical_feature_family_ratchet_operational_contract,
)
from weather.reporting.source_gates.source_artifact_binding import (
    stable_json_artifact,
)
from weather.reporting.source_gates.source_family_contracts import (
    source_ablation_operational_contract,
    source_family_inventory_integrity_contract,
    source_family_inventory_operational_contract,
)
from tests.reporting.source_family_contract_fixtures import (
    operational_ablation_payload,
    operational_inventory,
    operational_ratchet_payload,
    synthetic_receipt,
    write_active_release_identity,
)


def test_operational_source_ablation_requires_current_nonempty_coherent_evidence():
    current = operational_ablation_payload([{"variant": "open_meteo"}])
    assert source_ablation_operational_contract(current)["status"] == "PASS"

    empty = {
        "schema_version": "source_family_ablation_v0.3",
        "research_only": False,
        "promotion_preflight_evidence_authorization": True,
        "model_binding": {},
        "requested_variants": [],
        "summary": {"variant_count": 0, "market_days_scored": 0, "rows_scored": 0},
        "variants": [],
    }
    assert source_ablation_operational_contract(empty)["status"] == "BLOCK"

    research = dict(current)
    research.update({
        "schema_version": "source_family_ablation_v0.2",
        "research_only": True,
        "promotion_preflight_evidence_authorization": False,
        "model_binding": "malformed",
    })
    result = source_ablation_operational_contract(research)
    assert result["status"] == "BLOCK"
    assert "model_binding must be an object" in result["blockers"]

    detached = operational_ablation_payload([{"variant": "open_meteo"}])
    detached["slice_effects"] = [
        {
            "variant": "unscored_source",
            "slice": "market",
            "market_id": "test_market",
            "n": 10,
            "market_days": 1,
            "delta": 0.02,
        }
    ]
    detached["summary"]["slice_effect_count"] = 1
    result = source_ablation_operational_contract(detached)
    assert result["status"] == "BLOCK"
    assert any("reference a scored variant" in value for value in result["blockers"])

    empty_binding = operational_ablation_payload([{"variant": "open_meteo"}])
    empty_binding["model_binding"] = {}
    result = source_ablation_operational_contract(empty_binding)
    assert result["status"] == "BLOCK"
    assert "model_binding.status must equal BOUND" in result["blockers"]

    overlapping = operational_ablation_payload([{"variant": "open_meteo"}])
    overlapping["split_dates"]["holdout"] = list(
        overlapping["split_dates"]["tune"]
    )
    result = source_ablation_operational_contract(overlapping)
    assert result["status"] == "BLOCK"
    assert "tune and holdout dates must be disjoint" in result["blockers"]

    detached_inference = operational_ablation_payload(
        [{"variant": "open_meteo"}]
    )
    detached_inference["paired_inference"] = []
    result = source_ablation_operational_contract(detached_inference)
    assert result["status"] == "BLOCK"
    assert "paired_inference differs from recomputation" in result["blockers"]

    malformed_receipt = operational_ablation_payload(
        [{"variant": "open_meteo"}]
    )
    malformed_receipt["input_receipts"]["corpus"]["sha256"] = "short"
    result = source_ablation_operational_contract(malformed_receipt)
    assert result["status"] == "BLOCK"
    assert any("receipt sha256" in value for value in result["blockers"])

    authorized_root = operational_ablation_payload([{"variant": "open_meteo"}])
    authorized_root["serving_or_release_authorization"] = True
    result = source_ablation_operational_contract(authorized_root)
    assert result["status"] == "BLOCK"
    assert any(
        "serving_or_release_authorization must be explicitly false" in value
        for value in result["blockers"]
    )

    selective = operational_ablation_payload([{"variant": "open_meteo"}])
    selective["requested_variants"] = ["open_meteo"]
    result = source_ablation_operational_contract(selective)
    assert result["status"] == "BLOCK"
    assert any("exact ordered canonical family" in value for value in result["blockers"])

    omitted = operational_ablation_payload([{"variant": "open_meteo"}])
    removed_variant = omitted["variants"].pop()
    removed_id = removed_variant["variant"]
    omitted["day_effects"].pop(removed_id)
    omitted["paired_inference"] = [
        row for row in omitted["paired_inference"]
        if row.get("variant") != removed_id
    ]
    omitted["robustness_inference"] = [
        row for row in omitted["robustness_inference"]
        if row.get("variant") != removed_id
    ]
    omitted["market_inference"] = [
        row for row in omitted["market_inference"]
        if row.get("variant") != removed_id
    ]
    omitted["summary"]["variant_count"] -= 1
    omitted["summary"]["rows_scored"] -= removed_variant["n"]
    result = source_ablation_operational_contract(omitted)
    assert result["status"] == "BLOCK"
    assert any("scored variants must exactly equal" in value for value in result["blockers"])

    relabeled = operational_ablation_payload([{"variant": "all_forecasts"}])
    relabeled["variants"][0]["ablated_sources"] = ["open_meteo"]
    result = source_ablation_operational_contract(relabeled)
    assert result["status"] == "BLOCK"
    assert any("canonical membership" in value for value in result["blockers"])

    detached_summary = operational_ablation_payload([{"variant": "open_meteo"}])
    detached_summary["variants"][0]["delta"] = -0.01
    result = source_ablation_operational_contract(detached_summary)
    assert result["status"] == "BLOCK"
    assert any("weighted day effects" in value for value in result["blockers"])


def test_operational_ablation_uses_applicability_bounds_without_claiming_full_support():
    payload = operational_ablation_payload([{"variant": "eccc_citypage"}])
    assert {
        row["market_day"].split()[0]
        for row in payload["day_effects"]["eccc_citypage"]
    } == set(applicable_market_ids_for_variant("eccc_citypage"))
    assert set(applicable_market_ids_for_variant("eccc_citypage")) == {"toronto"}
    assert set(applicable_market_ids_for_variant("nws_grid")) < set(
        payload["corpus"]["market_ids"]
    )

    rows = payload["day_effects"]["eccc_citypage"]
    retained_dates = {
        payload["split_dates"]["tune"][0],
        payload["split_dates"]["holdout"][0],
    }
    sparse_rows = [
        row
        for row in rows
        if row["market_day"].rsplit(" ", 1)[-1] in retained_dates
    ]
    payload["day_effects"]["eccc_citypage"] = sparse_rows
    variant = next(
        row
        for row in payload["variants"]
        if row["variant"] == "eccc_citypage"
    )
    variant["n"] = sum(row["n"] for row in sparse_rows)
    variant["market_days"] = len(sparse_rows)
    variant["market_days_source_helped"] = len(sparse_rows)
    payload["summary"]["rows_scored"] = sum(
        row["n"] for row in payload["variants"]
    )
    payload["paired_inference"] = paired_day_inference(
        payload["day_effects"],
        payload["split_dates"],
    )
    payload["robustness_inference"] = paired_inference_sensitivities(
        payload["day_effects"],
        payload["market_days"],
        split_dates=payload["split_dates"],
        required_market_ids=tuple(payload["corpus"]["market_ids"]),
    )
    payload["market_inference"] = paired_market_inference(
        payload["day_effects"],
        payload["split_dates"],
        day_meta=payload["market_days"],
    )

    assert source_ablation_operational_contract(payload)["status"] == "PASS"


def test_candidate_ablation_binds_all_artifact_metadata_and_forbids_authorization():
    payload = operational_ablation_payload(
        [{"variant": "reanalysis_synoptic"}]
    )
    receipt = synthetic_receipt("C:/synthetic/candidate.pkl", "a")
    payload["evidence_source"] = "candidate_artifact_band_ablation"
    payload["input_receipts"]["artifact"] = receipt
    payload["model_binding"] = {
        "status": "BOUND_CANDIDATE_ARTIFACT",
        "binding_kind": "candidate_artifact",
        "promotion_evidence_binding": True,
        "artifact_path": receipt["path"],
        "artifact_sha256": receipt["sha256"],
        "prediction_mode": "band_binary",
        "serving_or_release_authorization": False,
    }
    payload["artifact"] = {
        "path": receipt["path"],
        "sha256": receipt["sha256"],
        "size_bytes": receipt["size_bytes"],
        "prediction_mode": "band_binary",
    }
    result = source_ablation_operational_contract(payload)
    assert result["status"] == "BLOCK"
    assert any(
        "verified_active_release" in value
        and "research-only" in value
        for value in result["blockers"]
    )

    contradictory = deepcopy(payload)
    contradictory["model_binding"]["serving_or_release_authorization"] = True
    contradictory["artifact"]["size_bytes"] += 1
    result = source_ablation_operational_contract(contradictory)
    assert result["status"] == "BLOCK"
    assert any("must be false" in value for value in result["blockers"])
    assert any("size_bytes differs" in value for value in result["blockers"])


def _market_partition_payload():
    payload = operational_ablation_payload([{"variant": "open_meteo"}])
    summary = next(
        row for row in payload["variants"] if row["variant"] == "open_meteo"
    )
    summary["base_brier"] = 0.2
    summary["variant_brier"] = 0.21
    summary["delta"] = 0.01
    markets = sorted(
        {
            row["market_day"].split()[0]
            for row in payload["day_effects"]["open_meteo"]
        }
    )
    base_n, extra_n = divmod(summary["n"], len(markets))
    payload["slice_effects"] = [
        {
            "variant": "open_meteo",
            "slice": "market",
            "market_id": market_id,
            "n": base_n + (index < extra_n),
            "market_days": len(payload["corpus"]["target_dates"]),
            "base_brier": 0.2,
            "variant_brier": 0.21,
            "delta": 0.01,
        }
        for index, market_id in enumerate(markets)
    ]
    payload["summary"]["slice_effect_count"] = len(payload["slice_effects"])
    return payload


def test_source_ablation_slice_partitions_reject_omission_duplicates_and_reweighting():
    valid = _market_partition_payload()
    assert source_ablation_operational_contract(valid)["status"] == "PASS"

    deleted = deepcopy(valid)
    deleted["slice_effects"].pop()
    deleted["summary"]["slice_effect_count"] -= 1
    result = source_ablation_operational_contract(deleted)
    assert result["status"] == "BLOCK"
    assert any("slice support differs" in value for value in result["blockers"])
    assert any("slice IDs differ" in value for value in result["blockers"])

    duplicate = deepcopy(valid)
    duplicate["slice_effects"].append(deepcopy(duplicate["slice_effects"][0]))
    duplicate["summary"]["slice_effect_count"] += 1
    result = source_ablation_operational_contract(duplicate)
    assert result["status"] == "BLOCK"
    assert any("grouping keys must be unique" in value for value in result["blockers"])

    inflated = deepcopy(valid)
    inflated["slice_effects"][0]["n"] += 1
    result = source_ablation_operational_contract(inflated)
    assert result["status"] == "BLOCK"
    assert any("slice support differs" in value for value in result["blockers"])

    reweighted = deepcopy(valid)
    reweighted["slice_effects"][0].update(
        {"base_brier": 0.2, "variant_brier": 0.22, "delta": 0.02}
    )
    result = source_ablation_operational_contract(reweighted)
    assert result["status"] == "BLOCK"
    assert any("weighted" in value for value in result["blockers"])


def test_inventory_contract_rejects_empty_missing_malformed_and_spoofed_candidate():
    valid = operational_inventory([])
    assert source_family_inventory_integrity_contract(valid)["status"] == "PASS"
    assert source_family_inventory_operational_contract(valid)["status"] == "PASS"

    empty = {
        "schema_version": "source_family_inventory_v0.2",
        "status": "PASS",
        "ablation_evidence_contract": {"status": "PASS"},
        "summary": {"family_count": 0, "blocking_family_count": 0},
        "promotion_preflight": {
            "status": "PASS",
            "blocked_family_count": 0,
            "blocked_families": [],
            "blocking_rows": [],
            "blocking_evidence_count": 0,
            "blocking_evidence": [],
            "ablation_evidence_contract": {"status": "PASS"},
        },
        "inventory": [],
    }
    assert source_family_inventory_integrity_contract(empty)["status"] == "BLOCK"

    missing_family = operational_inventory([])
    missing_family["inventory"] = missing_family["inventory"][:-1]
    missing_family["summary"]["family_count"] -= 1
    result = source_family_inventory_integrity_contract(missing_family)
    assert result["status"] == "BLOCK"
    assert any("family set" in value for value in result["blockers"])

    malformed = operational_inventory([])
    malformed["ablation_evidence_contract"] = "PASS"
    malformed["promotion_preflight"]["ablation_evidence_contract"] = "PASS"
    assert source_family_inventory_integrity_contract(malformed)["status"] == "BLOCK"

    malformed_receipt = operational_inventory([])
    malformed_receipt["ablation_input_receipt"]["size_bytes"] = 0
    result = source_family_inventory_integrity_contract(malformed_receipt)
    assert result["status"] == "BLOCK"
    assert any("size_bytes" in value for value in result["blockers"])

    spoofed = operational_inventory([])
    candidate = spoofed["inventory"][0]
    candidate["promotion_decision"] = {"status": "PROMOTION_CANDIDATE"}
    candidate["lineage_status"] = "PARTIAL_SOURCE_STATUS"
    candidate["ablation"] = {
        "status": "PRESENT",
        "settlement_scored": True,
        "evidence_source": "candidate_replay",
        "rows": 100,
        "days": 3,
        "delta": 0.01,
    }
    result = source_family_inventory_operational_contract(spoofed)
    assert result["status"] == "BLOCK"
    assert any("decision disagrees" in value for value in result["blockers"])


def test_inventory_contract_derives_global_ablation_fence():
    payload = operational_inventory([])
    blocked_contract = dict(payload["ablation_evidence_contract"])
    blocked_contract.update({"status": "BLOCK", "blockers": ["research_only"]})
    payload["ablation_evidence_contract"] = blocked_contract
    payload["promotion_preflight"]["ablation_evidence_contract"] = blocked_contract
    result = source_family_inventory_integrity_contract(payload)
    assert result["status"] == "BLOCK"
    assert any("blocking_evidence" in value for value in result["blockers"])


def test_inventory_preflight_blocks_active_hold_without_blocking_inactive_hold():
    active_hold = {
        "family_id": "forecast_baseline",
        "active_model_feature_columns": ["forecast_feature"],
        "ablation": {
            "status": "PRESENT",
            "variant": "all_forecasts",
            "settlement_scored": True,
            "rows": 100,
            "days": 3,
            "delta": 0.0,
        },
    }
    payload = operational_inventory([active_hold])

    assert payload["status"] == "BLOCK"
    assert payload["promotion_preflight"]["blocked_families"] == [
        "forecast_baseline"
    ]
    assert source_family_inventory_integrity_contract(payload)["status"] == "PASS"

    inactive = operational_inventory([])
    assert inactive["status"] == "PASS"
    assert inactive["promotion_preflight"]["blocked_families"] == []


def test_physical_contract_recomputes_family_evidence_and_survives_reader_projection(tmp_path):
    valid = operational_ratchet_payload()
    assert physical_feature_family_ratchet_operational_contract(valid)["status"] == "PASS"

    ablation_path = tmp_path / "source_family_ablation.json"
    ablation_payload = operational_ablation_payload([{"variant": "open_meteo"}])
    active_release_pointer = write_active_release_identity(
        tmp_path,
        ablation_payload,
    )
    ablation_path.write_text(
        json.dumps(ablation_payload),
        encoding="utf-8",
    )
    _ablation, ablation_receipt = stable_json_artifact(ablation_path)
    inventory_path = tmp_path / "source_family_inventory.json"
    inventory = operational_inventory([])
    inventory["ablation_input_receipt"] = ablation_receipt
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    _inventory, inventory_receipt = stable_json_artifact(inventory_path)
    valid = build_ratchet(
        source_family_inventory=inventory_path,
        source_family_ablation=ablation_path,
        generated_at_utc="2026-07-23T00:00:00+00:00",
    )
    path = tmp_path / "ratchet.json"
    path.write_text(json.dumps(valid), encoding="utf-8")
    projected = _read_physical_feature_family_ratchet(
        path,
        active_release_pointer=active_release_pointer,
        active_releases_root=active_release_pointer.parent,
    )
    assert projected["status"] == "BLOCK"
    assert projected["operational_contract"]["status"] == "BLOCK"
    assert (
        physical_feature_family_ratchet_operational_contract(projected)[
            "status"
        ]
        == "BLOCK"
    )
    assert any(
        "scan-input closure" in blocker
        for blocker in projected["operational_contract"]["blockers"]
    )

    forged = operational_ratchet_payload()
    forged["settlement_sliced_lift"] = []
    forged["summary"]["settlement_slice_row_count"] = 0
    for row in forged["families"]:
        row["settlement_slice_summary"] = {
            "slice_count": 0,
            "valid_slice_count": 0,
            "invalid_slice_count": 0,
            "slice_kinds": [],
            "required_slice_kinds_present": [],
            "missing_required_slice_kinds": [
                "cutoff_regime",
                "market",
                "market_cutoff_regime",
                "settlement_distance",
            ],
            "positive_slice_count": 0,
            "positive_slice_kinds": [],
            "missing_positive_slice_kinds": [],
            "harmful_slice_count": 0,
            "worst_harm": None,
        }
    result = physical_feature_family_ratchet_operational_contract(forged)
    assert result["status"] == "BLOCK"
    assert any("status disagrees" in value for value in result["blockers"])

    malformed = operational_ratchet_payload()
    malformed["inputs"] = "PASS"
    assert physical_feature_family_ratchet_operational_contract(malformed)["status"] == "BLOCK"

    mismatched_receipt = operational_ratchet_payload()
    mismatched_receipt["inputs"][
        "inventory_source_family_ablation_receipt"
    ] = deepcopy(
        mismatched_receipt["inputs"]["inventory_source_family_ablation_receipt"]
    )
    mismatched_receipt["inputs"][
        "inventory_source_family_ablation_receipt"
    ]["sha256"] = "9" * 64
    result = physical_feature_family_ratchet_operational_contract(
        mismatched_receipt
    )
    assert result["status"] == "BLOCK"
    assert any("receipt differs" in value for value in result["blockers"])


def test_physical_contract_rejects_invalid_or_zero_support_slice_evidence():
    zero_support = operational_ratchet_payload()
    for slice_row in zero_support["settlement_sliced_lift"]:
        slice_row["n"] = 0
        slice_row["delta"] = None
    result = physical_feature_family_ratchet_operational_contract(zero_support)
    assert result["status"] == "BLOCK"
    assert any("positive integer support and finite delta" in value for value in result["blockers"])

    malformed_kind = operational_ratchet_payload()
    malformed_kind["settlement_sliced_lift"][0]["slice"] = 1
    result = physical_feature_family_ratchet_operational_contract(malformed_kind)
    assert result["status"] == "BLOCK"
    assert any("slice must be non-empty" in value for value in result["blockers"])

    unknown_family = operational_ratchet_payload()
    unknown_family["settlement_sliced_lift"][0]["family_id"] = "invented_family"
    result = physical_feature_family_ratchet_operational_contract(unknown_family)
    assert result["status"] == "BLOCK"
    assert any("not a physical family" in value for value in result["blockers"])

    detached_variant = operational_ratchet_payload()
    detached_variant["settlement_sliced_lift"][0]["variant"] = "all_forecasts"
    result = physical_feature_family_ratchet_operational_contract(detached_variant)
    assert result["status"] == "BLOCK"
    assert any("detached from its family" in value for value in result["blockers"])

    incomplete_family_variants = operational_ratchet_payload()
    incomplete_family_variants["families"][0]["ablation_variants"].pop()
    result = physical_feature_family_ratchet_operational_contract(
        incomplete_family_variants
    )
    assert result["status"] == "BLOCK"
    assert any("canonical family variants" in value for value in result["blockers"])


def test_physical_contract_rejects_missing_family_even_when_counts_are_self_consistent():
    payload = operational_ratchet_payload()
    removed = payload["families"].pop()
    payload["settlement_sliced_lift"] = [
        row
        for row in payload["settlement_sliced_lift"]
        if row["family_id"] != removed["family_id"]
    ]
    payload["summary"]["family_count"] -= 1
    payload["summary"]["status_counts"]["PROMOTION_ELIGIBLE"] -= 1
    payload["summary"]["rollup_bucket_counts"]["ready_for_retraining"] -= 1
    payload["summary"]["settlement_slice_row_count"] -= 4
    payload["rollup"]["ready_for_retraining"].remove(removed["family_id"])
    result = physical_feature_family_ratchet_operational_contract(payload)
    assert result["status"] == "BLOCK"
    assert any("family set" in value for value in result["blockers"])
