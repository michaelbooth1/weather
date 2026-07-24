"""Physical feature-family isolated replay ratchet.

This report consumes the source-family inventory and settlement-scored source
ablation artifact, then translates them into the stricter item-263 vocabulary.
It does not train or replay models; missing evidence remains an explicit block.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.execution_identity import (
    atomic_write_json_exclusive,
    atomic_write_text_exclusive,
)
from weather.paths import data_path
from weather.reporting.formatting import fmt_signed, markdown_table
from weather.reporting.source_gates.source_family_contracts import (
    EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS,
    EXPECTED_SOURCE_FAMILY_IDS,
    source_ablation_operational_contract,
    source_family_inventory_ablation_projection_contract,
    source_family_inventory_integrity_contract,
)
from weather.reporting.source_gates.source_artifact_binding import (
    receipt_shape_contract,
    stable_json_artifact,
    verify_current_candidate_artifact,
)
from weather.reporting.source_gates.source_family_inventory import FAMILY_SPECS
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("physical_feature_family_ratchet")
DEFAULT_READ_ONLY_DATA_ROOT = data_path()
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_SOURCE_FAMILY_INVENTORY = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_SOURCE_FAMILY_ABLATION = DEFAULT_BACKTEST_ROOT / "source_family_ablation.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "physical_feature_family_ratchet.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "physical_feature_family_ratchet.md"

EXCLUDED_OVERLAY_FAMILIES = {"clob_microstructure"}
POSITIVE_LIFT_EPSILON = 0.0001
HARM_EPSILON = -0.0001
REQUIRED_SLICE_KINDS = {"market", "cutoff_regime", "market_cutoff_regime", "settlement_distance"}

CONTRACT_FIELDS = [
    "provider/source keys",
    "raw-payload lineage artifacts",
    "historical availability",
    "live availability policy",
    "feature transforms and active artifact columns",
    "missingness and fallback behavior",
    "train rows and served rows",
    "isolated settlement-scored replay or ablation evidence",
    "market/cutoff/source-health/settlement-distance slices",
]


def physical_feature_family_ratchet_operational_contract(payload):
    """Revalidate a ratchet before it can satisfy an operational promotion gate."""

    if not isinstance(payload, dict) or not payload:
        return {
            "status": "MISSING",
            "schema_version": None,
            "expected_schema_version": SCHEMA_VERSION,
            "serving_or_release_authorization": False,
            "blockers": ["physical feature-family ratchet is missing"],
        }
    blockers = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        blockers.append(f"schema_version must equal {SCHEMA_VERSION}")
    if payload.get("serving_or_release_authorization") is not False:
        blockers.append(
            "serving_or_release_authorization must be explicitly false"
        )
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        blockers.append("inputs must be an object")
        inputs = {}
    inventory_contract = inputs.get("source_family_inventory_contract")
    if not isinstance(inventory_contract, dict):
        blockers.append("source-family inventory contract must be an object")
        inventory_contract = {}
    ablation_contract = inputs.get("ablation_evidence_contract")
    if not isinstance(ablation_contract, dict):
        blockers.append("source-ablation contract must be an object")
        ablation_contract = {}
    if (
        inventory_contract.get("status") != "PASS"
        or inventory_contract.get("schema_version") != schema_version("source_family_inventory")
        or inventory_contract.get("expected_schema_version") != schema_version("source_family_inventory")
    ):
        blockers.append("source-family inventory integrity contract is not PASS")
    elif inventory_contract.get("blockers") != []:
        blockers.append("PASS source-family inventory contract cannot contain blockers")
    if (
        ablation_contract.get("status") != "PASS"
        or ablation_contract.get("schema_version") != schema_version("source_family_ablation")
        or ablation_contract.get("expected_schema_version") != schema_version("source_family_ablation")
    ):
        blockers.append("source-ablation operational contract is not PASS")
    elif ablation_contract.get("blockers") != []:
        blockers.append("PASS source-ablation contract cannot contain blockers")
    inventory_receipt = inputs.get("source_family_inventory_receipt")
    ablation_receipt = inputs.get("source_family_ablation_receipt")
    inventory_ablation_receipt = inputs.get(
        "inventory_source_family_ablation_receipt"
    )
    for label, receipt in (
        ("source-family inventory", inventory_receipt),
        ("source-family ablation", ablation_receipt),
        ("inventory source-family ablation", inventory_ablation_receipt),
    ):
        blockers.extend(receipt_shape_contract(receipt, label=label)["blockers"])
    if (
        isinstance(ablation_receipt, dict)
        and isinstance(inventory_ablation_receipt, dict)
        and any(
            ablation_receipt.get(key) != inventory_ablation_receipt.get(key)
            for key in ("path", "sha256", "size_bytes")
        )
    ):
        blockers.append(
            "inventory ablation receipt differs from the ratchet ablation receipt"
        )
    input_binding_contract = inputs.get("input_binding_contract")
    if not isinstance(input_binding_contract, dict):
        blockers.append("input_binding_contract must be an object")
    elif (
        input_binding_contract.get("status") != "PASS"
        or input_binding_contract.get("blockers") != []
    ):
        blockers.append("input_binding_contract is not PASS")
    current_verification = inputs.get("current_input_verification")
    if (
        not isinstance(current_verification, dict)
        or current_verification.get("status") != "PASS"
        or current_verification.get("blockers") != []
    ):
        blockers.append("current input receipt verification is not PASS")
    derived_rebuild = inputs.get("derived_rebuild_contract")
    if (
        not isinstance(derived_rebuild, dict)
        or derived_rebuild.get("status") != "PASS"
        or derived_rebuild.get("blockers") != []
    ):
        blockers.append("derived rebuild contract is missing or not PASS")
    families = payload.get("families")
    if not isinstance(families, list) or not families:
        blockers.append("families must be a non-empty list")
        families = []
    slices = payload.get("settlement_sliced_lift")
    if not isinstance(slices, list):
        blockers.append("settlement_sliced_lift must be a list")
        slices = []
    valid_slices = []
    for index, row in enumerate(slices):
        if not isinstance(row, dict):
            blockers.append(f"settlement_sliced_lift[{index}] must be an object")
            continue
        if not isinstance(row.get("family_id"), str) or not row.get("family_id"):
            blockers.append(
                f"settlement_sliced_lift[{index}].family_id must be non-empty"
            )
            continue
        family_id = row["family_id"]
        if family_id not in (
            set(EXPECTED_SOURCE_FAMILY_IDS) - EXCLUDED_OVERLAY_FAMILIES
        ):
            blockers.append(
                f"settlement_sliced_lift[{index}].family_id is not a physical family"
            )
            continue
        if not isinstance(row.get("slice"), str) or not row.get("slice"):
            blockers.append(
                f"settlement_sliced_lift[{index}].slice must be non-empty"
            )
            continue
        if row.get("variant") not in EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS.get(
            family_id,
            (),
        ):
            blockers.append(
                f"settlement_sliced_lift[{index}].variant is detached from its family"
            )
        if not _valid_slice_evidence(row):
            blockers.append(
                f"settlement_sliced_lift[{index}] must have positive integer support and finite delta"
            )
        valid_slices.append(row)
    family_ids = []
    status_counts = Counter()
    bucket_counts = Counter()
    for index, row in enumerate(families):
        if not isinstance(row, dict):
            blockers.append(f"families[{index}] must be an object")
            continue
        family_id = row.get("family_id")
        status = row.get("status")
        bucket = row.get("rollup_bucket")
        if not isinstance(family_id, str) or not family_id.strip():
            blockers.append(f"families[{index}].family_id must be non-empty")
        else:
            family_ids.append(family_id)
        if status not in {
            "LIVE_ONLY",
            "LINEAGE_BLOCKED",
            "MISSING_ACTIVE_ARTIFACT",
            "MISSING_SETTLED_REPLAY",
            "ISOLATED_REPLAY_BLOCK",
            "SHADOW_PASS",
            "PROMOTION_ELIGIBLE",
        }:
            blockers.append(f"families[{index}].status is invalid")
        else:
            status_counts[status] += 1
        if bucket not in {"ready_for_retraining", "diagnostic_only", "evidence_blocked"}:
            blockers.append(f"families[{index}].rollup_bucket is invalid")
        else:
            bucket_counts[bucket] += 1
        expected_bucket = (
            "ready_for_retraining"
            if status == "PROMOTION_ELIGIBLE"
            else "diagnostic_only"
            if status in {"SHADOW_PASS", "LIVE_ONLY"}
            else "evidence_blocked"
        )
        if bucket != expected_bucket:
            blockers.append(
                f"families[{index}].rollup_bucket is inconsistent with status"
            )
        family_blockers = row.get("blockers")
        if not isinstance(family_blockers, list):
            blockers.append(f"families[{index}].blockers must be a list")
            family_blockers = []
        elif bucket == "ready_for_retraining" and family_blockers:
            blockers.append(f"families[{index}] is ready but still has blockers")
        ablation = row.get("ablation")
        if not isinstance(ablation, dict):
            blockers.append(f"families[{index}].ablation must be an object")
            ablation = {}
        canonical_variants = EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS.get(
            family_id,
            (),
        )
        observed_variants = row.get("ablation_variants")
        if (
            not isinstance(observed_variants, list)
            or len(observed_variants) != len(set(observed_variants))
            or set(observed_variants) != set(canonical_variants)
        ):
            blockers.append(
                f"families[{index}].ablation_variants differ from the canonical family variants"
            )
            observed_variants = []
        decision_variants = row.get("decision_ablation_variants")
        expected_decision_variants = (
            [ablation.get("variant")]
            if ablation.get("variant") in canonical_variants
            else list(observed_variants)
        )
        if decision_variants != expected_decision_variants:
            blockers.append(
                f"families[{index}].decision_ablation_variants are inconsistent"
            )
            decision_variants = []
        family_slices = [
            slice_row
            for slice_row in valid_slices
            if slice_row.get("family_id") == family_id
        ]
        if any(
            slice_row.get("variant") not in decision_variants
            for slice_row in family_slices
        ):
            blockers.append(
                f"families[{index}] contains a slice outside its decision variants"
            )
        expected_status, expected_blockers, expected_slice_summary = _status_for_family(
            row,
            family_slices,
            ablation=ablation,
        )
        if status != expected_status:
            blockers.append(f"families[{index}].status disagrees with raw evidence")
        if family_blockers != expected_blockers:
            blockers.append(f"families[{index}].blockers disagree with raw evidence")
        if row.get("settlement_slice_summary") != expected_slice_summary:
            blockers.append(
                f"families[{index}].settlement_slice_summary disagrees with raw evidence"
            )
    if len(family_ids) != len(set(family_ids)):
        blockers.append("family identifiers must be unique")
    expected_family_ids = set(EXPECTED_SOURCE_FAMILY_IDS) - EXCLUDED_OVERLAY_FAMILIES
    if set(family_ids) != expected_family_ids:
        missing = sorted(expected_family_ids - set(family_ids))
        unexpected = sorted(set(family_ids) - expected_family_ids)
        blockers.append(
            "physical family set is incomplete or unexpected"
            + (f"; missing={','.join(missing)}" if missing else "")
            + (f"; unexpected={','.join(unexpected)}" if unexpected else "")
        )
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        blockers.append("summary must be an object")
        summary = {}
    if summary.get("family_count") != len(families):
        blockers.append("summary.family_count does not match families")
    if summary.get("blocking_family_count") != bucket_counts["evidence_blocked"]:
        blockers.append("summary.blocking_family_count is inconsistent")
    if summary.get("status_counts") != dict(sorted(status_counts.items())):
        blockers.append("summary.status_counts is inconsistent")
    if summary.get("rollup_bucket_counts") != dict(sorted(bucket_counts.items())):
        blockers.append("summary.rollup_bucket_counts is inconsistent")
    if summary.get("settlement_slice_row_count") != len(slices):
        blockers.append("summary.settlement_slice_row_count is inconsistent")
    excluded = payload.get("excluded_market_overlay_families")
    if not isinstance(excluded, list):
        blockers.append("excluded_market_overlay_families must be a list")
        excluded = []
    if summary.get("excluded_overlay_family_count") != len(excluded):
        blockers.append("summary.excluded_overlay_family_count is inconsistent")
    excluded_ids = [
        row.get("family_id") if isinstance(row, dict) else None
        for row in excluded
    ]
    if (
        len(excluded_ids) != len(set(excluded_ids))
        or set(excluded_ids) != EXCLUDED_OVERLAY_FAMILIES
    ):
        blockers.append(
            "excluded_market_overlay_families must exactly match the canonical excluded set"
        )
    rollup = payload.get("rollup")
    if not isinstance(rollup, dict):
        blockers.append("rollup must be an object")
        rollup = {}
    rollup_ids = []
    for bucket in ("ready_for_retraining", "diagnostic_only", "evidence_blocked"):
        values = rollup.get(bucket)
        if not isinstance(values, list):
            blockers.append(f"rollup.{bucket} must be a list")
            continue
        if any(not isinstance(value, str) or not value for value in values):
            blockers.append(f"rollup.{bucket} entries must be non-empty strings")
            values = [value for value in values if isinstance(value, str) and value]
        rollup_ids.extend(values)
        expected = sorted(
            row.get("family_id")
            for row in families
            if (
                isinstance(row, dict)
                and isinstance(row.get("family_id"), str)
                and row.get("family_id")
                and row.get("rollup_bucket") == bucket
            )
        )
        if sorted(values) != expected:
            blockers.append(f"rollup.{bucket} is inconsistent with families")
    if len(rollup_ids) != len(set(rollup_ids)):
        blockers.append("rollup family identifiers must be unique across buckets")
    if payload.get("status") == "PASS" and bucket_counts["evidence_blocked"]:
        blockers.append("PASS ratchet cannot contain evidence-blocked families")
    if payload.get("status") != "PASS":
        blockers.append("physical feature-family ratchet status is not PASS")
    return {
        "status": "BLOCK" if blockers else "PASS",
        "schema_version": payload.get("schema_version"),
        "expected_schema_version": SCHEMA_VERSION,
        "serving_or_release_authorization": False,
        "blockers": blockers,
    }


RATCHET_DERIVED_FIELDS = (
    "status",
    "contract",
    "summary",
    "rollup",
    "families",
    "settlement_sliced_lift",
    "excluded_market_overlay_families",
)


def physical_feature_family_ratchet_derived_contract(payload, expected):
    """Require every ratchet-derived section to match an exact source rebuild."""

    payload = payload if isinstance(payload, dict) else {}
    expected = expected if isinstance(expected, dict) else {}
    blockers = [
        f"physical feature-family ratchet {field} differs from current input rebuild"
        for field in RATCHET_DERIVED_FIELDS
        if payload.get(field) != expected.get(field)
    ]
    return {
        "status": "BLOCK" if blockers else "PASS",
        "compared_fields": list(RATCHET_DERIVED_FIELDS),
        "blockers": blockers,
    }


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


SPEC_BY_FAMILY = {spec.family_id: spec for spec in FAMILY_SPECS}


def _family_variants(row):
    family_id = row.get("family_id") or ""
    spec = SPEC_BY_FAMILY.get(family_id)
    variants = []
    ablation = row.get("ablation") or {}
    if ablation.get("variant"):
        variants.append(ablation["variant"])
    if spec:
        variants.extend(spec.ablation_variants)
    variants.extend(row.get("source_keys") or [])
    seen = set()
    ordered = []
    for variant in variants:
        if variant and variant not in seen:
            ordered.append(variant)
            seen.add(variant)
    return ordered


def _slice_rows_for_family(ablation_payload, variants):
    variants = set(variants)
    rows = [
        row for row in (ablation_payload.get("slice_effects") or [])
        if row.get("variant") in variants
    ]
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("variant") or ""),
            str(row.get("slice") or ""),
            str(row.get("market_id") or ""),
            str(row.get("cutoff_regime") or ""),
            str(row.get("settlement_distance") or ""),
        ),
    )


def _day_rows_for_family(ablation_payload, variants):
    day_effects = ablation_payload.get("day_effects") or {}
    rows = []
    for variant in variants:
        for row in day_effects.get(variant) or []:
            rows.append({"variant": variant, **row})
    return rows


def _decision_variants_for_family(ablation, variants):
    variant = (ablation or {}).get("variant")
    if variant:
        return [variant]
    return variants


def _current_ablation_for_family(ablation_payload, inventory_ablation, variants):
    by_variant = {
        row.get("variant"): row
        for row in (ablation_payload.get("variants") or [])
        if row.get("variant")
    }
    for variant in variants:
        row = by_variant.get(variant)
        if row:
            return {
                **row,
                "status": "PRESENT",
                "variant": variant,
                "evidence_source": "source_family_ablation",
            }
    return {
        **(inventory_ablation or {}),
        "evidence_source": (inventory_ablation or {}).get("evidence_source") or "source_family_inventory",
        "evidence_container": "source_family_inventory",
    }


def _slice_summary(slice_rows):
    supported_rows = [row for row in slice_rows if _valid_slice_evidence(row)]
    kinds = sorted({row.get("slice") or "unknown" for row in supported_rows})
    harmful = [
        row for row in supported_rows
        if _float(row.get("delta")) < HARM_EPSILON
    ]
    positive = [
        row for row in supported_rows
        if _float(row.get("delta")) > POSITIVE_LIFT_EPSILON
    ]
    positive_kinds = sorted({row.get("slice") for row in positive})
    present_required = set(kinds) & REQUIRED_SLICE_KINDS
    return {
        "slice_count": len(slice_rows),
        "valid_slice_count": len(supported_rows),
        "invalid_slice_count": len(slice_rows) - len(supported_rows),
        "slice_kinds": kinds,
        "required_slice_kinds_present": sorted(present_required),
        "missing_required_slice_kinds": sorted(REQUIRED_SLICE_KINDS - set(kinds)),
        "positive_slice_count": len(positive),
        "positive_slice_kinds": positive_kinds,
        "missing_positive_slice_kinds": sorted(
            present_required - set(positive_kinds)
        ),
        "harmful_slice_count": len(harmful),
        "worst_harm": min((_float(row.get("delta")) for row in harmful), default=None),
    }


def _valid_slice_evidence(row):
    support = row.get("n", row.get("rows"))
    delta = row.get("delta")
    return (
        isinstance(support, int)
        and not isinstance(support, bool)
        and support > 0
        and isinstance(delta, (int, float))
        and not isinstance(delta, bool)
        and math.isfinite(float(delta))
    )


def _status_for_family(row, slice_rows, ablation=None):
    lineage = row.get("lineage_status") or "UNKNOWN"
    parity = row.get("train_serve_parity_status") or "UNKNOWN"
    ablation = ablation or row.get("ablation") or {}
    ablation_status = ablation.get("status") or "MISSING"
    delta = _float(ablation.get("delta"))
    active_count = _int(row.get("active_model_feature_count"))
    active_status = row.get("active_model_usage_status") or ""
    model_influence = bool(row.get("model_influence", row.get("configured_model_influence", True)))
    live_only = bool(row.get("live_only")) or "live_only" in str(row.get("live_only_policy") or "")
    slice_summary = _slice_summary(slice_rows)

    blockers = []
    if not model_influence and active_count == 0:
        blockers.append(f"active_model_usage_status={active_status or 'NOT_USED_BY_ACTIVE_ARTIFACT'}")
        return "LIVE_ONLY", blockers, slice_summary
    if lineage != "PASS":
        blockers.append(f"lineage_status={lineage}")
        return "LINEAGE_BLOCKED", blockers, slice_summary
    if parity != "PASS":
        blockers.append(f"train_serve_parity_status={parity}")
        return "LINEAGE_BLOCKED", blockers, slice_summary
    if live_only and active_count == 0:
        blockers.append(f"live_only_policy={row.get('live_only_policy')}")
        return "LIVE_ONLY", blockers, slice_summary
    if model_influence and active_count == 0 and active_status != "ACTIVE_OVERLAY":
        blockers.append(f"active_model_usage_status={active_status or 'UNKNOWN'}")
        return "MISSING_ACTIVE_ARTIFACT", blockers, slice_summary
    if ablation_status != "PRESENT":
        if ablation_status == "BLOCKED_UNSAFE_ARTIFACT":
            blockers.append("source-ablation input is not operationally authorized")
            return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
        blockers.append(f"ablation_status={ablation_status}")
        return "MISSING_SETTLED_REPLAY", blockers, slice_summary
    if ablation.get("evidence_source") == "item27_feature_value_gate":
        blockers.append(
            "item27 market_details evidence is diagnostic-only and unreceipted"
        )
        return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
    if not slice_rows:
        blockers.append("missing settlement-sliced ablation rows")
        return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
    if slice_summary["invalid_slice_count"]:
        blockers.append(
            f"invalid_slice_evidence_count={slice_summary['invalid_slice_count']}"
        )
    missing_kinds = slice_summary["missing_required_slice_kinds"]
    if missing_kinds:
        blockers.append("missing required slice kinds: " + ", ".join(missing_kinds))
    missing_positive_kinds = slice_summary["missing_positive_slice_kinds"]
    if missing_positive_kinds:
        blockers.append(
            "required slice kinds without positive evidence: "
            + ", ".join(missing_positive_kinds)
        )
    if delta is None or delta <= POSITIVE_LIFT_EPSILON:
        blockers.append(f"pooled_delta={delta}")
    if slice_summary["harmful_slice_count"]:
        blockers.append(f"harmful_slice_count={slice_summary['harmful_slice_count']}")
    if blockers:
        return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
    if active_count > 0:
        return "PROMOTION_ELIGIBLE", blockers, slice_summary
    return "SHADOW_PASS", blockers, slice_summary


def _rollup_bucket(status):
    if status == "PROMOTION_ELIGIBLE":
        return "ready_for_retraining"
    if status in {"SHADOW_PASS", "LIVE_ONLY"}:
        return "diagnostic_only"
    return "evidence_blocked"


def build_ratchet(
    *,
    source_family_inventory=DEFAULT_SOURCE_FAMILY_INVENTORY,
    source_family_ablation=DEFAULT_SOURCE_FAMILY_ABLATION,
    generated_at_utc=None,
    loaded_inventory_payload=None,
    loaded_inventory_receipt=None,
    loaded_ablation_payload=None,
    loaded_ablation_receipt=None,
):
    if (loaded_inventory_payload is None) != (loaded_inventory_receipt is None):
        raise ValueError("loaded inventory payload and receipt must be supplied together")
    if (loaded_ablation_payload is None) != (loaded_ablation_receipt is None):
        raise ValueError("loaded ablation payload and receipt must be supplied together")
    if loaded_inventory_payload is None:
        inventory_payload, inventory_receipt = stable_json_artifact(
            source_family_inventory
        )
    else:
        inventory_payload = loaded_inventory_payload
        inventory_receipt = loaded_inventory_receipt
    if loaded_ablation_payload is None:
        ablation_payload, ablation_receipt = stable_json_artifact(
            source_family_ablation
        )
    else:
        ablation_payload = loaded_ablation_payload
        ablation_receipt = loaded_ablation_receipt
    inventory_contract = source_family_inventory_integrity_contract(
        inventory_payload
    )
    ablation_contract = source_ablation_operational_contract(ablation_payload)
    inventory_projection_contract = (
        source_family_inventory_ablation_projection_contract(
            inventory_payload,
            ablation_payload,
        )
    )
    candidate_artifact_verification = verify_current_candidate_artifact(
        ablation_payload,
    )
    input_binding_blockers = []
    for label, receipt in (
        ("source-family inventory", inventory_receipt),
        ("source-family ablation", ablation_receipt),
    ):
        if receipt.get("status") != "PASS":
            input_binding_blockers.extend(
                receipt.get("blockers") or [f"{label} receipt is not PASS"]
            )
    inventory_ablation_receipt = inventory_payload.get("ablation_input_receipt")
    receipt_contract = receipt_shape_contract(
        inventory_ablation_receipt,
        label="inventory source-family ablation",
    )
    input_binding_blockers.extend(receipt_contract["blockers"])
    input_binding_blockers.extend(
        inventory_projection_contract.get("blockers") or []
    )
    input_binding_blockers.extend(
        candidate_artifact_verification.get("blockers") or []
    )
    if receipt_contract["status"] == "PASS" and any(
        inventory_ablation_receipt.get(key) != ablation_receipt.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        input_binding_blockers.append(
            "inventory source-family ablation receipt differs from current ratchet input"
        )
    input_binding_contract = {
        "status": "BLOCK" if input_binding_blockers else "PASS",
        "blockers": input_binding_blockers,
    }
    input_contract_blocked = (
        inventory_contract["status"] != "PASS"
        or ablation_contract["status"] != "PASS"
        or input_binding_contract["status"] != "PASS"
    )
    effective_ablation_payload = (
        {} if input_contract_blocked else ablation_payload
    )
    source_rows = inventory_payload.get("inventory") or []
    families = []
    excluded = []
    slice_rows = []
    for row in source_rows:
        family_id = row.get("family_id") or ""
        if family_id in EXCLUDED_OVERLAY_FAMILIES:
            excluded.append({
                "family_id": family_id,
                "reason": "market-informed/CLOB-derived overlay excluded from physical-weather ratchet",
                "lineage_status": row.get("lineage_status"),
                "train_serve_parity_status": row.get("train_serve_parity_status"),
            })
            continue
        variants = _family_variants(row)
        if input_contract_blocked:
            contract_blockers = [
                *(inventory_contract.get("blockers") or []),
                *(ablation_contract.get("blockers") or []),
                *(input_binding_contract.get("blockers") or []),
            ]
            ablation = {
                "status": "BLOCKED_UNSAFE_ARTIFACT",
                "variant": next(iter(variants), None),
                "evidence_source": "source_family_ablation",
                "evidence_contract": {
                    "status": "BLOCK",
                    "blockers": contract_blockers,
                    "source_family_inventory": inventory_contract,
                    "source_family_ablation": ablation_contract,
                },
            }
        else:
            ablation = _current_ablation_for_family(
                effective_ablation_payload,
                row.get("ablation") or {},
                variants,
            )
        decision_variants = _decision_variants_for_family(ablation, variants)
        family_slices = _slice_rows_for_family(
            effective_ablation_payload, decision_variants
        )
        family_day_rows = _day_rows_for_family(
            effective_ablation_payload, decision_variants
        )
        status, blockers, summary = _status_for_family(row, family_slices, ablation=ablation)
        bucket = _rollup_bucket(status)
        family = {
            "family_id": family_id,
            "label": row.get("label"),
            "owner": row.get("owner"),
            "status": status,
            "rollup_bucket": bucket,
            "blockers": blockers,
            "source_keys": row.get("source_keys") or [],
            "lineage_artifacts": row.get("lineage_artifacts") or [],
            "lineage_status": row.get("lineage_status"),
            "train_serve_parity_status": row.get("train_serve_parity_status"),
            "historical_archive_status": row.get("historical_archive_status"),
            "live_only_policy": row.get("live_only_policy"),
            "model_influence": row.get("model_influence"),
            "configured_model_influence": row.get("configured_model_influence"),
            "active_model_usage_status": row.get("active_model_usage_status"),
            "active_model_feature_count": row.get("active_model_feature_count"),
            "active_model_feature_columns": row.get("active_model_feature_columns") or [],
            "missing_required_parity_feature_columns": row.get("missing_required_parity_feature_columns") or [],
            "feature_missingness": row.get("feature_missingness") or {},
            "ablation": {
                "status": ablation.get("status"),
                "variant": ablation.get("variant"),
                "rows": ablation.get("n") or ablation.get("rows"),
                "days": ablation.get("days"),
                "delta": ablation.get("delta"),
                "days_source_helped": ablation.get("days_source_helped"),
                "days_source_hurt": ablation.get("days_source_hurt"),
                "evidence_source": ablation.get("evidence_source"),
                "evidence_contract": ablation.get("evidence_contract"),
                "unreceipted_market_details_policy": (
                    "DIAGNOSTIC_ONLY_NOT_CONSUMED"
                    if (
                        ablation.get("evidence_source")
                        == "item27_feature_value_gate"
                        and ablation.get("market_details")
                    )
                    else None
                ),
            },
            "ablation_variants": variants,
            "decision_ablation_variants": decision_variants,
            "settlement_slice_summary": summary,
            "day_effect_count": len(family_day_rows),
        }
        families.append(family)
        for slice_row in family_slices:
            slice_rows.append({"family_id": family_id, **slice_row})

    status_counts = Counter(row["status"] for row in families)
    bucket_counts = Counter(row["rollup_bucket"] for row in families)
    blocked_count = sum(1 for row in families if row["rollup_bucket"] == "evidence_blocked")
    artifact_blocked = input_contract_blocked
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": "BLOCK" if blocked_count or artifact_blocked else "PASS",
        "serving_or_release_authorization": False,
        "authorization_note": (
            "Detached ratchet only; an operational reader must rebuild it from "
            "current verified inputs before serving or release authorization."
        ),
        "inputs": {
            "source_family_inventory": str(source_family_inventory),
            "source_family_ablation": str(source_family_ablation),
            "source_family_inventory_receipt": inventory_receipt,
            "source_family_ablation_receipt": ablation_receipt,
            "inventory_source_family_ablation_receipt": inventory_ablation_receipt,
            "input_binding_contract": input_binding_contract,
            "inventory_ablation_projection_contract": (
                inventory_projection_contract
            ),
            "candidate_artifact_verification": candidate_artifact_verification,
            "inventory_status": inventory_payload.get("status"),
            "source_family_inventory_contract": inventory_contract,
            "ablation_status": ablation_payload.get("status"),
            "ablation_schema_version": ablation_payload.get("schema_version"),
            "ablation_evidence_contract": ablation_contract,
        },
        "contract": {
            "fields": CONTRACT_FIELDS,
            "status_vocabulary": [
                "LIVE_ONLY",
                "LINEAGE_BLOCKED",
                "MISSING_ACTIVE_ARTIFACT",
                "MISSING_SETTLED_REPLAY",
                "ISOLATED_REPLAY_BLOCK",
                "SHADOW_PASS",
                "PROMOTION_ELIGIBLE",
            ],
            "excluded_overlay_families": sorted(EXCLUDED_OVERLAY_FAMILIES),
        },
        "summary": {
            "family_count": len(families),
            "excluded_overlay_family_count": len(excluded),
            "blocking_family_count": blocked_count,
            "status_counts": dict(sorted(status_counts.items())),
            "rollup_bucket_counts": dict(sorted(bucket_counts.items())),
            "settlement_slice_row_count": len(slice_rows),
        },
        "rollup": {
            "ready_for_retraining": [row["family_id"] for row in families if row["rollup_bucket"] == "ready_for_retraining"],
            "diagnostic_only": [row["family_id"] for row in families if row["rollup_bucket"] == "diagnostic_only"],
            "evidence_blocked": [row["family_id"] for row in families if row["rollup_bucket"] == "evidence_blocked"],
        },
        "families": families,
        "settlement_sliced_lift": slice_rows,
        "excluded_market_overlay_families": excluded,
    }


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Physical Feature-Family Isolated Replay Ratchet",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "Serving/release authorization: **false**",
        (
            "This detached ratchet cannot authorize serving or release. An "
            "operational reader must rebuild it from current verified inputs."
        ),
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Physical families", summary.get("family_count")],
            ["Blocking families", summary.get("blocking_family_count")],
            ["Excluded overlay families", summary.get("excluded_overlay_family_count")],
            ["Settlement slice rows", summary.get("settlement_slice_row_count")],
            ["Status counts", json.dumps(summary.get("status_counts") or {}, sort_keys=True)],
            ["Rollup buckets", json.dumps(summary.get("rollup_bucket_counts") or {}, sort_keys=True)],
        ],
    )
    lines += ["", "## Contract", ""]
    for field in (payload.get("contract") or {}).get("fields") or []:
        lines.append(f"- {field}")
    lines += ["", "## Family Ratchet", ""]
    lines += markdown_table(
        ["Family", "Status", "Rollup", "Lineage", "Parity", "Ablation Delta", "Slices", "Blockers"],
        [
            [
                row.get("family_id"),
                row.get("status"),
                row.get("rollup_bucket"),
                row.get("lineage_status"),
                row.get("train_serve_parity_status"),
                fmt_signed((row.get("ablation") or {}).get("delta"), 4),
                (row.get("settlement_slice_summary") or {}).get("slice_count"),
                "; ".join(row.get("blockers") or []) or "-",
            ]
            for row in payload.get("families") or []
        ],
    )
    rollup = payload.get("rollup") or {}
    lines += ["", "## Rollup", ""]
    lines += markdown_table(
        ["Bucket", "Families"],
        [
            ["Ready for retraining", ", ".join(rollup.get("ready_for_retraining") or []) or "-"],
            ["Diagnostic only", ", ".join(rollup.get("diagnostic_only") or []) or "-"],
            ["Evidence blocked", ", ".join(rollup.get("evidence_blocked") or []) or "-"],
        ],
    )
    slices = payload.get("settlement_sliced_lift") or []
    if slices:
        lines += ["", "## Settlement-Sliced Lift And Harm", ""]
        lines += markdown_table(
            ["Family", "Variant", "Slice", "Market", "Regime", "Distance", "Rows", "Delta"],
            [
                [
                    row.get("family_id"),
                    row.get("variant"),
                    row.get("slice"),
                    row.get("market_id") or "-",
                    row.get("cutoff_regime") or "-",
                    row.get("settlement_distance") or "-",
                    row.get("n"),
                    fmt_signed(row.get("delta"), 4),
                ]
                for row in slices[:80]
            ],
        )
    excluded = payload.get("excluded_market_overlay_families") or []
    if excluded:
        lines += ["", "## Excluded Market Overlay Families", ""]
        lines += markdown_table(
            ["Family", "Reason", "Lineage", "Parity"],
            [
                [
                    row.get("family_id"),
                    row.get("reason"),
                    row.get("lineage_status"),
                    row.get("train_serve_parity_status"),
                ]
                for row in excluded
            ],
        )
    return "\n".join(lines) + "\n"


def _is_relative_to(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_output_paths(
    *,
    json_out,
    report_out,
    source_family_inventory,
    source_family_ablation,
    read_only_data_root=DEFAULT_READ_ONLY_DATA_ROOT,
):
    """Resolve inputs/outputs and fail closed around the read-only mirror."""

    data_root = Path(read_only_data_root).expanduser().resolve(strict=True)
    if not data_root.is_dir():
        raise ValueError(f"read-only data root is not a directory: {data_root}")
    protected_inputs = {}
    for label, raw_path in (
        ("source-family inventory", source_family_inventory),
        ("source-family ablation", source_family_ablation),
    ):
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"{label} input is not a file: {path}")
        protected_inputs[label] = path

    outputs = {
        "JSON": Path(json_out).expanduser().resolve(strict=False),
        "report": Path(report_out).expanduser().resolve(strict=False),
    }
    json_path = outputs["JSON"]
    report_path = outputs["report"]
    aliases_companion = json_path == report_path
    if not aliases_companion and json_path.exists() and report_path.exists():
        try:
            aliases_companion = json_path.samefile(report_path)
        except OSError:
            aliases_companion = False
    if aliases_companion:
        raise ValueError("JSON and report outputs must not alias")

    for output_label, output_path in outputs.items():
        if _is_relative_to(output_path, data_root):
            raise ValueError(
                f"{output_label} output resolves inside the read-only data root: "
                f"{output_path}"
            )
        for input_label, input_path in protected_inputs.items():
            aliases_input = output_path == input_path
            if not aliases_input and output_path.exists():
                try:
                    aliases_input = output_path.samefile(input_path)
                except OSError:
                    aliases_input = False
            if aliases_input:
                raise ValueError(
                    f"{output_label} output aliases the {input_label} input: "
                    f"{output_path}"
                )
        if output_path.exists():
            raise ValueError(
                f"{output_label} output already exists; ratchet generations "
                f"refuse overwrite: {output_path}"
            )
    return {
        "read_only_data_root": data_root,
        "source_family_inventory": protected_inputs["source-family inventory"],
        "source_family_ablation": protected_inputs["source-family ablation"],
        "json_out": json_path,
        "report_out": report_path,
    }


def write_outputs(
    payload,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    *,
    source_family_inventory=DEFAULT_SOURCE_FAMILY_INVENTORY,
    source_family_ablation=DEFAULT_SOURCE_FAMILY_ABLATION,
    read_only_data_root=DEFAULT_READ_ONLY_DATA_ROOT,
):
    paths = resolve_output_paths(
        json_out=json_out,
        report_out=report_out,
        source_family_inventory=source_family_inventory,
        source_family_ablation=source_family_ablation,
        read_only_data_root=read_only_data_root,
    )
    # Finish every fallible serialization before creating parents or leaves.
    json.dumps(payload, sort_keys=True, allow_nan=False)
    rendered_report = render_report(payload)
    paths["json_out"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_out"].parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text_exclusive(paths["report_out"], rendered_report)
    # JSON is the completion leaf and appears only after its report.
    atomic_write_json_exclusive(paths["json_out"], payload)
    return paths["json_out"], paths["report_out"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the physical feature-family isolated replay ratchet.")
    parser.add_argument("--source-family-inventory", default=str(DEFAULT_SOURCE_FAMILY_INVENTORY))
    parser.add_argument("--source-family-ablation", default=str(DEFAULT_SOURCE_FAMILY_ABLATION))
    parser.add_argument(
        "--read-only-data-root",
        default=str(DEFAULT_READ_ONLY_DATA_ROOT),
    )
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)
    paths = resolve_output_paths(
        json_out=args.json_out,
        report_out=args.report_out,
        source_family_inventory=args.source_family_inventory,
        source_family_ablation=args.source_family_ablation,
        read_only_data_root=args.read_only_data_root,
    )
    payload = build_ratchet(
        source_family_inventory=paths["source_family_inventory"],
        source_family_ablation=paths["source_family_ablation"],
    )
    json_out, report_out = write_outputs(
        payload,
        paths["json_out"],
        paths["report_out"],
        source_family_inventory=paths["source_family_inventory"],
        source_family_ablation=paths["source_family_ablation"],
        read_only_data_root=paths["read_only_data_root"],
    )
    print(f"Physical feature-family ratchet: {payload.get('status')}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return payload


if __name__ == "__main__":
    main()
