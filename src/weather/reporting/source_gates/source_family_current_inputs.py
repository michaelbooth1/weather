"""Current-path verification for source-family inventory dependencies."""

from __future__ import annotations

from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
)
from weather.reporting.promotion.promotion_corpus import load_manifest_bytes
from weather.reporting.source_gates.source_artifact_binding import (
    load_verified_current_artifact,
    load_verified_current_json_artifact,
    verify_current_artifact,
    verify_current_active_release_binding,
    verify_current_candidate_artifact,
)
from weather.reporting.source_gates.source_family_contracts import (
    source_ablation_operational_contract,
    source_family_inventory_ablation_projection_contract,
    source_family_inventory_integrity_contract,
    source_family_inventory_operational_contract,
)
from weather.reporting.source_gates.source_family_inventory import (
    FAMILY_SPECS,
    active_family_usage,
    active_model_usage,
)


def _candidate_model_usage_current_projection(
    inventory_payload,
    ablation_payload,
    active_release_verification,
    *,
    active_release_pointer=DEFAULT_ACTIVE_RELEASE_POINTER,
    active_releases_root=DEFAULT_RELEASES_ROOT,
):
    blockers = []
    stored_receipt = inventory_payload.get("candidate_replay_input_receipt")
    stored_artifact_receipt = inventory_payload.get(
        "candidate_model_artifact_input_receipt"
    )
    candidate_replay_payload, replay_verification = (
        load_verified_current_json_artifact(
            stored_receipt,
            label="candidate replay",
        )
    )
    blockers.extend(replay_verification.get("blockers") or [])
    artifact_verification = verify_current_artifact(
        stored_artifact_receipt,
        label="candidate replay model artifact",
    )
    blockers.extend(artifact_verification.get("blockers") or [])
    recomputed_usage = active_model_usage(
        candidate_replay_payload,
        candidate_replay_receipt=stored_receipt,
        ablation_payload=ablation_payload,
        active_release_verification=active_release_verification,
        active_release_pointer=active_release_pointer,
        active_releases_root=active_releases_root,
    )
    if recomputed_usage.get("verification", {}).get("status") != "PASS":
        blockers.extend(
            recomputed_usage.get("verification", {}).get("blockers") or []
        )
    recomputed_verification = recomputed_usage.get("verification")
    recomputed_verification = (
        recomputed_verification
        if isinstance(recomputed_verification, dict)
        else {}
    )
    if recomputed_verification.get("candidate_replay_receipt") != stored_receipt:
        blockers.append(
            "active_model_usage candidate replay receipt differs from inventory root"
        )
    if (
        recomputed_verification.get("artifact_receipt")
        != stored_artifact_receipt
    ):
        blockers.append(
            "active_model_usage model artifact receipt differs from inventory root"
        )
    if inventory_payload.get("candidate_replay_json") != (
        stored_receipt.get("path") if isinstance(stored_receipt, dict) else None
    ):
        blockers.append(
            "inventory candidate_replay_json differs from its stable receipt path"
        )
    if inventory_payload.get("active_model_usage") != recomputed_usage:
        blockers.append(
            "inventory active_model_usage differs from current verified candidate bytes"
        )
    summary = inventory_payload.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    expected_summary = {
        "active_model_usage_status": recomputed_usage.get("status"),
        "active_model_feature_count": recomputed_usage.get("feature_count"),
        "active_overlay_families": recomputed_usage.get(
            "active_overlay_families"
        ),
    }
    for field, expected in expected_summary.items():
        if summary.get(field) != expected:
            blockers.append(
                f"inventory summary.{field} differs from current model usage"
            )
    rows = inventory_payload.get("inventory")
    rows = rows if isinstance(rows, list) else []
    by_family = {
        row.get("family_id"): row
        for row in rows
        if isinstance(row, dict) and row.get("family_id")
    }
    for spec in FAMILY_SPECS:
        row = by_family.get(spec.family_id)
        if not isinstance(row, dict):
            blockers.append(
                f"current model-usage projection lacks family {spec.family_id}"
            )
            continue
        expected = active_family_usage(spec, recomputed_usage)
        for field, expected_value in expected.items():
            if row.get(field) != expected_value:
                blockers.append(
                    f"{spec.family_id}.{field} differs from current model usage"
                )
    return {
        "status": "BLOCK" if blockers else "PASS",
        "candidate_replay": replay_verification,
        "candidate_model_artifact": artifact_verification,
        "recomputed_active_model_usage": recomputed_usage,
        "blockers": blockers,
    }


def _parse_date_manifest_bytes(raw, *, path):
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"date manifest is not valid UTF-8: {path}") from exc
    values = []
    for raw_line in text.splitlines():
        value = raw_line.split("#", 1)[0].strip()
        if value:
            values.append(value)
    if not values:
        raise ValueError(f"date manifest is empty: {path}")
    if values != sorted(set(values)):
        raise ValueError(f"date manifest must be unique and sorted: {path}")
    return values


def _current_ablation_input_verification(ablation_payload):
    """Revalidate exact corpus and split bytes plus their semantic projections."""

    blockers = []
    receipts = ablation_payload.get("input_receipts")
    receipts = receipts if isinstance(receipts, dict) else {}
    corpus_summary = ablation_payload.get("corpus")
    corpus_summary = corpus_summary if isinstance(corpus_summary, dict) else {}
    split_dates = ablation_payload.get("split_dates")
    split_dates = split_dates if isinstance(split_dates, dict) else {}
    results = {}

    corpus_raw, corpus_verification = load_verified_current_artifact(
        receipts.get("corpus"),
        label="source-family ablation corpus",
    )
    corpus_blockers = list(corpus_verification.get("blockers") or [])
    corpus_manifest = {}
    if corpus_verification.get("status") == "PASS":
        try:
            corpus_manifest = load_manifest_bytes(
                corpus_raw,
                path=receipts["corpus"]["path"],
            )
        except (TypeError, ValueError) as exc:
            corpus_blockers.append(
                f"current promotion corpus failed semantic validation: {exc}"
            )
        else:
            entries = corpus_manifest.get("entries")
            entries = entries if isinstance(entries, list) else []
            manifest_summary = corpus_manifest.get("summary")
            manifest_summary = (
                manifest_summary if isinstance(manifest_summary, dict) else {}
            )
            expected_projection = {
                "path": corpus_manifest.get("_path"),
                "schema_version": corpus_manifest.get("schema_version"),
                "corpus_hash": corpus_manifest.get("corpus_hash"),
                "as_of": corpus_manifest.get("as_of"),
                "market_day_count": manifest_summary.get("market_day_count"),
                "snapshot_count": manifest_summary.get("snapshot_count"),
                "target_dates": sorted(
                    {
                        str(row.get("target_date"))
                        for row in entries
                        if isinstance(row, dict) and row.get("target_date")
                    }
                ),
                "market_ids": sorted(
                    {
                        str(row.get("market_id"))
                        for row in entries
                        if isinstance(row, dict) and row.get("market_id")
                    }
                ),
            }
            for field, current_value in expected_projection.items():
                if corpus_summary.get(field) != current_value:
                    corpus_blockers.append(
                        f"source-family ablation corpus.{field} differs from current manifest"
                    )
            if corpus_summary.get("manifest_sha256") != receipts["corpus"].get(
                "sha256"
            ):
                corpus_blockers.append(
                    "source-family ablation corpus.manifest_sha256 differs from its receipt"
                )
            if corpus_manifest.get("include_reconstructed") is not False:
                corpus_blockers.append(
                    "current promotion corpus include_reconstructed must be false"
                )
    corpus_result = {
        **corpus_verification,
        "status": "BLOCK" if corpus_blockers else "PASS",
        "semantic_projection": corpus_manifest,
        "blockers": corpus_blockers,
    }
    results["corpus"] = corpus_result
    blockers.extend(corpus_blockers)

    for receipt_name, split_name in (
        ("tune_dates", "tune"),
        ("holdout_dates", "holdout"),
    ):
        raw, verification = load_verified_current_artifact(
            receipts.get(receipt_name),
            label=f"source-family ablation {receipt_name}",
        )
        semantic_blockers = list(verification.get("blockers") or [])
        current_dates = []
        if verification.get("status") == "PASS":
            try:
                current_dates = _parse_date_manifest_bytes(
                    raw,
                    path=receipts[receipt_name]["path"],
                )
            except (TypeError, ValueError) as exc:
                semantic_blockers.append(str(exc))
            else:
                if current_dates != split_dates.get(split_name):
                    semantic_blockers.append(
                        f"source-family ablation split_dates.{split_name} "
                        f"differs from current {receipt_name} bytes"
                    )
        results[receipt_name] = {
            **verification,
            "status": "BLOCK" if semantic_blockers else "PASS",
            "dates": current_dates,
            "blockers": semantic_blockers,
        }
        blockers.extend(semantic_blockers)
    return results, blockers


def evaluate_source_family_inventory_current_inputs(
    inventory_payload,
    ablation_payload,
    ablation_verification,
    active_release_verification=None,
    *,
    active_release_pointer=DEFAULT_ACTIVE_RELEASE_POINTER,
    active_releases_root=DEFAULT_RELEASES_ROOT,
):
    """Evaluate one already-loaded inventory/ablation pair without re-reading."""

    inventory_payload = (
        inventory_payload if isinstance(inventory_payload, dict) else {}
    )
    ablation_payload = ablation_payload if isinstance(ablation_payload, dict) else {}
    ablation_verification = (
        ablation_verification if isinstance(ablation_verification, dict) else {}
    )
    operational_contract = source_ablation_operational_contract(ablation_payload)
    projection_contract = source_family_inventory_ablation_projection_contract(
        inventory_payload,
        ablation_payload,
    )
    candidate_artifact_verification = verify_current_candidate_artifact(
        ablation_payload,
    )
    if not isinstance(active_release_verification, dict):
        active_release_verification = verify_current_active_release_binding(
            ablation_payload,
            pointer_path=active_release_pointer,
            releases_root=active_releases_root,
        )
    current_ablation_inputs, current_ablation_input_blockers = (
        _current_ablation_input_verification(ablation_payload)
    )
    candidate_usage_projection = _candidate_model_usage_current_projection(
        inventory_payload,
        ablation_payload,
        active_release_verification,
        active_release_pointer=active_release_pointer,
        active_releases_root=active_releases_root,
    )
    scan_closure = inventory_payload.get("scan_input_closure")
    scan_closure = scan_closure if isinstance(scan_closure, dict) else {}
    blockers = [
        *(ablation_verification.get("blockers") or []),
        *(operational_contract.get("blockers") or []),
        *(projection_contract.get("blockers") or []),
        *(candidate_artifact_verification.get("blockers") or []),
        *(active_release_verification.get("blockers") or []),
        *current_ablation_input_blockers,
        *(candidate_usage_projection.get("blockers") or []),
    ]
    if any(
        verification.get("status") != "PASS"
        for verification in current_ablation_inputs.values()
    ):
        blockers.append(
            "one or more current corpus/split input receipts are not PASS"
        )
    if (
        scan_closure.get("status") != "PASS"
        or scan_closure.get("complete") is not True
        or scan_closure.get("blockers") != []
    ):
        blockers.append(
            "complete current inventory scan-input closure is unavailable"
        )
    else:
        blockers.append(
            "inventory scan-input closure verification is not implemented; "
            "inventory remains diagnostic and non-authorizing"
        )
    if ablation_verification.get("status") != "PASS" and not (
        ablation_verification.get("blockers")
    ):
        blockers.append("current source-family ablation verification is not PASS")
    if operational_contract.get("status") != "PASS" and not (
        operational_contract.get("blockers")
    ):
        blockers.append("current source-family ablation contract is not PASS")
    return {
        "status": "BLOCK" if blockers else "PASS",
        "source_family_ablation": ablation_verification,
        "source_family_ablation_contract": operational_contract,
        "inventory_ablation_projection": projection_contract,
        "candidate_artifact": candidate_artifact_verification,
        "active_release": active_release_verification,
        "current_ablation_inputs": current_ablation_inputs,
        "candidate_model_usage_projection": candidate_usage_projection,
        "scan_input_closure": scan_closure,
        "serving_or_release_authorization": False,
        "blockers": blockers,
    }


def load_source_family_inventory_current_inputs(
    inventory_payload,
    *,
    active_release_pointer=DEFAULT_ACTIVE_RELEASE_POINTER,
    active_releases_root=DEFAULT_RELEASES_ROOT,
):
    """Load and verify the inventory's exact current ablation dependency once."""

    inventory_payload = (
        inventory_payload if isinstance(inventory_payload, dict) else {}
    )
    ablation_payload, ablation_verification = load_verified_current_json_artifact(
        inventory_payload.get("ablation_input_receipt"),
        label="source-family ablation",
    )
    return ablation_payload, evaluate_source_family_inventory_current_inputs(
        inventory_payload,
        ablation_payload,
        ablation_verification,
        active_release_pointer=active_release_pointer,
        active_releases_root=active_releases_root,
    )


def source_family_inventory_current_integrity_contract(
    inventory_payload,
    *,
    active_release_pointer=DEFAULT_ACTIVE_RELEASE_POINTER,
    active_releases_root=DEFAULT_RELEASES_ROOT,
):
    """Combine pure inventory integrity with current transitive input checks."""

    integrity = source_family_inventory_integrity_contract(inventory_payload)
    _ablation_payload, current_inputs = (
        load_source_family_inventory_current_inputs(
            inventory_payload,
            active_release_pointer=active_release_pointer,
            active_releases_root=active_releases_root,
        )
    )
    operational = source_family_inventory_operational_contract(
        {
            **(
                inventory_payload
                if isinstance(inventory_payload, dict)
                else {}
            ),
            "current_input_verification": current_inputs,
        }
    )
    blockers = [
        *(integrity.get("blockers") or []),
        *(current_inputs.get("blockers") or []),
        *(operational.get("blockers") or []),
    ]
    return {
        **integrity,
        "status": "BLOCK" if blockers else "PASS",
        "current_input_verification": current_inputs,
        "operational_contract": operational,
        "blockers": blockers,
    }
