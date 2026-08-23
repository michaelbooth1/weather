"""Shared exact-path validators for fixed International live-session receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from weather.operations.live_path_security import validate_contained_regular_file

EXPECTED_CREDENTIAL_REFERENCES = {
    "POLYMARKET_API_KEY_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/ApiKey",
    "POLYMARKET_API_SECRET_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/ApiSecret",
    "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/Passphrase",
    "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/PrivateKey",
}
EXPECTED_CREDENTIAL_IMPORT_CHECKS = {
    "api_credentials_have_no_whitespace", "chain_id_exact", "clob_host_exact",
    "funder_address_valid", "private_key_matches_wallet_address",
    "private_key_parseable", "signature_topology_supported",
    "wallet_address_valid", "wallet_and_funder_distinct",
}
CREDENTIAL_TOPOLOGY_KEYS = {
    "manifest_wallet_address", "derived_signer_matches_manifest",
    "api_owner_matches_manifest", "order_signer_matches_manifest",
    "funder_matches_identity",
}


def exact_run_lineage(
    run: Mapping[str, Any],
    *,
    attempt_root: Path,
    stage: str,
    seal: Mapping[str, Any],
    seal_path: Path,
    sha256_file: Callable[[Path], str],
) -> bool:
    expected = {
        "session_manifest": attempt_root / "inputs" / f"{stage}-session-manifest.json",
        "composition_receipt": attempt_root / "session" / f"{stage}-composition-receipt.json",
        "run_intent": attempt_root / "session" / f"{stage}-run-intent.json",
        "seal_receipt": seal_path,
    }
    try:
        for role, expected_path in expected.items():
            record = run.get(role) or {}
            observed = validate_contained_regular_file(
                attempt_root, str(record.get("path") or "")
            )
            if observed != expected_path.resolve() or sha256_file(observed) != record.get(
                "sha256"
            ):
                return False
        manifest = run.get("session_manifest") or {}
        sidecar = expected["session_manifest"].with_suffix(
            expected["session_manifest"].suffix + ".sha256"
        )
        observed_sidecar = validate_contained_regular_file(
            attempt_root, str(manifest.get("sidecar_path") or "")
        )
        if (
            observed_sidecar != sidecar.resolve()
            or sha256_file(observed_sidecar) != manifest.get("sidecar_sha256")
            or run.get("wrapper") != seal.get("wrapper")
            or run.get("launcher") != seal.get("launcher")
        ):
            return False
    except (OSError, RuntimeError, ValueError):
        return False
    return True
