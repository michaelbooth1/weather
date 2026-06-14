"""Deterministic replay identity for model distributions.

The human model version string is useful for release notes, but it is not
specific enough for replay fidelity: retraining artifacts can change while the
version label stays the same. The replay canary needs the exact distribution
identity that produced a snapshot.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


IDENTITY_SCHEMA_VERSION = "weather_model_replay_identity_v0.1"

SRC_ROOT = Path(__file__).resolve().parent

# Files that can alter estimate_distribution for a fixed captured sources dict.
# Keep this list focused on pure distribution/feature/calibration code; the
# identity helper itself is intentionally excluded so report-only edits do not
# invalidate otherwise faithful captures.
DISTRIBUTION_CODE_FILES = (
    "model_base.py",
    "model_climatology.py",
    "model_constants.py",
    "model_distribution.py",
    "model_features.py",
    "feature_store.py",
    "forecast_error_model.py",
    "family_secondary_artifacts.py",
    "probability_calibration.py",
    "settlement_lag_model.py",
    "market_registry.py",
)

DISTRIBUTION_ARTIFACT_TEMPLATES = (
    "calibrated_weights{suffix}.json",
    "feature_model_coefs{suffix}.json",
    "feature_model_hgb{suffix}.pkl",
    "late_day_model_coefs{suffix}.json",
    "probability_calibration{suffix}.json",
    "forecast_error_model{suffix}.json",
    "settlement_lag_model{suffix}.json",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_payload(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def file_fingerprint(path: Path) -> dict:
    """Stable metadata for one file path, including absence.

    Missing files matter because many US markets intentionally have no
    per-market calibration artifacts yet. If one appears later, the replay
    identity must change.
    """
    path = Path(path)
    rel = path.relative_to(SRC_ROOT.parent).as_posix()
    if not path.exists():
        return {"path": rel, "exists": False, "size": None, "sha256": None}
    data = path.read_bytes()
    return {
        "path": rel,
        "exists": True,
        "size": len(data),
        "sha256": _sha256_bytes(data),
    }


def _combined_hash(items: list[dict]) -> str:
    reduced = [
        {
            "path": item.get("path"),
            "exists": item.get("exists"),
            "sha256": item.get("sha256"),
        }
        for item in items
    ]
    return _hash_payload(reduced)


def model_replay_identity(model) -> dict:
    """Return the deterministic identity of the model's current distribution.

    Call this after ``estimate_distribution`` so ``active_model_kind`` reflects
    the path that actually served the snapshot.
    """
    spec = getattr(model, "spec", None)
    market_id = getattr(model, "market_id", None) or getattr(spec, "id", None)
    suffix = getattr(spec, "artifact_suffix", "")

    code_files = [file_fingerprint(SRC_ROOT / name) for name in DISTRIBUTION_CODE_FILES]
    artifact_files = [
        file_fingerprint(SRC_ROOT / template.format(suffix=suffix))
        for template in DISTRIBUTION_ARTIFACT_TEMPLATES
    ]
    if getattr(spec, "display_unit", None) == "F":
        artifact_files.append(file_fingerprint(SRC_ROOT / "f_family_secondary_artifacts.json"))

    try:
        model_version = model.get_model_version_string()
    except Exception:  # noqa: BLE001 - identity should not break capture
        model_version = None

    payload = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "model_version": model_version,
        "market_id": market_id,
        "active_model_kind": getattr(model, "active_model_kind", None),
        "code_hash": _combined_hash(code_files),
        "artifact_hash": _combined_hash(artifact_files),
    }
    identity_hash = _hash_payload(payload)
    return {
        **payload,
        "identity_hash": identity_hash,
        "code_files": code_files,
        "artifact_files": artifact_files,
    }


def identity_hash(identity) -> str | None:
    if not isinstance(identity, dict):
        return None
    value = identity.get("identity_hash")
    return str(value) if value else None
