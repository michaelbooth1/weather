"""Fail-fast current-input contract for detached inventory consumers."""

from __future__ import annotations

from pathlib import Path

from weather.reporting.source_gates.source_artifact_binding import (
    receipt_shape_contract,
)
from weather.reporting.source_gates.source_family_contracts import (
    source_family_inventory_integrity_contract,
)
from weather.reporting.source_gates.source_family_current_inputs import (
    source_family_inventory_current_integrity_contract,
)


def source_family_inventory_consumer_contract(payload):
    """Require a plausible current receipt before expensive transitive checks.

    A missing or nonexistent receipt is already conclusive evidence that the
    detached inventory cannot authorize a downstream decision.  Existing files
    still go through the complete current-integrity verifier, including hashes,
    candidate/model bindings, corpus splits, and the active release graph.
    """

    payload = payload if isinstance(payload, dict) else {}
    receipt = payload.get("ablation_input_receipt")
    receipt_contract = receipt_shape_contract(
        receipt,
        label="source-family inventory ablation input",
    )
    receipt_path = (
        receipt.get("path")
        if isinstance(receipt, dict) and isinstance(receipt.get("path"), str)
        else None
    )
    path_exists = False
    if receipt_contract["status"] == "PASS" and receipt_path:
        try:
            path_exists = Path(receipt_path).is_file()
        except OSError:
            path_exists = False
    if receipt_contract["status"] == "PASS" and path_exists:
        return source_family_inventory_current_integrity_contract(payload)

    integrity = source_family_inventory_integrity_contract(payload)
    current_blockers = list(receipt_contract.get("blockers") or [])
    if receipt_contract["status"] == "PASS" and not path_exists:
        current_blockers.append(
            "source-family inventory ablation input receipt path does not exist"
        )
    blockers = [
        *(integrity.get("blockers") or []),
        *current_blockers,
    ]
    return {
        **integrity,
        "status": "BLOCK",
        "serving_or_release_authorization": False,
        "current_input_verification": {
            "status": "BLOCK",
            "serving_or_release_authorization": False,
            "blockers": current_blockers,
        },
        "blockers": blockers,
    }
