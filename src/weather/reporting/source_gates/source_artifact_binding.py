"""Stable byte receipts for source-gate artifacts and consumer revalidation."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path

from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
    RELEASE_MANIFEST_NAME,
    ReleaseArtifactVerificationError,
    manifest_content_sha256,
)
from weather.release_serving import (
    STATUS_BOUND,
    load_verified_active_serving_bundle,
)


def _identity(stat_result):
    return (
        int(getattr(stat_result, "st_dev", 0)),
        int(getattr(stat_result, "st_ino", 0)),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
        int(getattr(stat_result, "st_ctime_ns", 0)),
    )


def stable_artifact(path):
    """Read and hash one stable byte sequence from *path*."""

    requested = Path(path)
    resolved = requested.resolve(strict=False)
    receipt = {
        "path": str(resolved),
        "status": "MISSING",
        "sha256": None,
        "size_bytes": None,
        "blockers": [],
    }
    try:
        parent = requested.parent.resolve(strict=True)
        parent_before = parent.stat()
        resolved = requested.resolve(strict=True)
        receipt["path"] = str(resolved)
        with resolved.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
        resolved_after = requested.resolve(strict=True)
        parent_after = parent.stat()
    except (OSError, RuntimeError) as exc:
        receipt["blockers"] = [f"artifact could not be read: {exc}"]
        return b"", receipt
    receipt["size_bytes"] = len(raw)
    receipt["sha256"] = hashlib.sha256(raw).hexdigest()
    receipt.update(
        {
            "device": int(getattr(after, "st_dev", 0)),
            "inode": int(getattr(after, "st_ino", 0)),
            "mtime_ns": int(after.st_mtime_ns),
            "ctime_ns": int(getattr(after, "st_ctime_ns", 0)),
            "parent_path": str(parent),
            "parent_device": int(getattr(parent_after, "st_dev", 0)),
            "parent_inode": int(getattr(parent_after, "st_ino", 0)),
        }
    )
    parent_identity_before = (
        int(getattr(parent_before, "st_dev", 0)),
        int(getattr(parent_before, "st_ino", 0)),
        int(parent_before.st_mtime_ns),
        int(getattr(parent_before, "st_ctime_ns", 0)),
    )
    parent_identity_after = (
        int(getattr(parent_after, "st_dev", 0)),
        int(getattr(parent_after, "st_ino", 0)),
        int(parent_after.st_mtime_ns),
        int(getattr(parent_after, "st_ctime_ns", 0)),
    )
    if (
        _identity(before) != _identity(after)
        or len(raw) != after.st_size
        or resolved_after != resolved
        or parent_identity_before != parent_identity_after
    ):
        receipt["status"] = "BLOCK"
        receipt["blockers"] = [
            "artifact path, parent, or opened descriptor changed during stable read"
        ]
        return b"", receipt
    receipt["status"] = "PASS"
    return raw, receipt


def stable_json_artifact(path):
    """Read, hash, and parse the same stable bytes from *path*."""

    raw, receipt = stable_artifact(path)
    if receipt["status"] != "PASS":
        return {}, receipt

    def reject_duplicate_keys(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"duplicate JSON key {key!r}")
            payload[key] = value
        return payload

    def reject_non_finite(value):
        raise ValueError(f"non-finite JSON constant {value!r}")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        receipt["status"] = "BLOCK"
        receipt["blockers"] = [
            f"artifact is not strict UTF-8 JSON: {exc}"
        ]
        return {}, receipt

    def contains_non_finite(value):
        if isinstance(value, float):
            return not math.isfinite(value)
        if isinstance(value, dict):
            return any(contains_non_finite(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_non_finite(item) for item in value)
        return False

    if contains_non_finite(payload):
        receipt["status"] = "BLOCK"
        receipt["blockers"] = [
            "artifact strict JSON contains an out-of-range non-finite number"
        ]
        return {}, receipt
    if not isinstance(payload, dict):
        receipt["status"] = "BLOCK"
        receipt["blockers"] = ["artifact JSON root must be an object"]
        return {}, receipt
    return payload, receipt


def receipt_shape_contract(receipt, *, label="artifact"):
    """Validate a stored receipt without trusting it as a current-file check."""

    blockers = []
    if not isinstance(receipt, dict):
        return {
            "status": "BLOCK",
            "blockers": [f"{label} receipt must be an object"],
        }
    if receipt.get("status") != "PASS":
        blockers.append(f"{label} receipt status is not PASS")
    if not isinstance(receipt.get("path"), str) or not receipt.get("path"):
        blockers.append(f"{label} receipt path must be non-empty")
    sha256 = receipt.get("sha256")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256.lower())
    ):
        blockers.append(f"{label} receipt sha256 must be a 64-character hex digest")
    size_bytes = receipt.get("size_bytes")
    if (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes <= 0
    ):
        blockers.append(f"{label} receipt size_bytes must be a positive integer")
    if receipt.get("blockers") != []:
        blockers.append(f"{label} PASS receipt must have no blockers")
    return {"status": "BLOCK" if blockers else "PASS", "blockers": blockers}


def _verify_current_receipt(receipt, current, *, label):
    shape = receipt_shape_contract(receipt, label=label)
    if shape["status"] != "PASS":
        return {
            **shape,
            "path": receipt.get("path") if isinstance(receipt, dict) else None,
            "expected_sha256": (
                receipt.get("sha256") if isinstance(receipt, dict) else None
            ),
            "actual_sha256": None,
        }
    blockers = list(current.get("blockers") or [])
    if current.get("status") != "PASS" and not blockers:
        blockers.append(f"current {label} artifact is not readable")
    if current.get("sha256") != receipt.get("sha256"):
        blockers.append(f"current {label} sha256 differs from the published receipt")
    if current.get("size_bytes") != receipt.get("size_bytes"):
        blockers.append(f"current {label} size differs from the published receipt")
    return {
        "status": "BLOCK" if blockers else "PASS",
        "path": receipt.get("path"),
        "expected_sha256": receipt.get("sha256"),
        "actual_sha256": current.get("sha256"),
        "blockers": blockers,
    }


def verify_current_artifact(receipt, *, label="artifact"):
    """Require the current bytes at a stored receipt path to match exactly."""

    shape = receipt_shape_contract(receipt, label=label)
    if shape["status"] != "PASS":
        return _verify_current_receipt(receipt, {}, label=label)
    _raw, current = stable_artifact(receipt["path"])
    return _verify_current_receipt(receipt, current, label=label)


def load_verified_current_artifact(receipt, *, label="artifact"):
    """Load current bytes and compare the exact same read with a receipt."""

    shape = receipt_shape_contract(receipt, label=label)
    if shape["status"] != "PASS":
        return b"", _verify_current_receipt(receipt, {}, label=label)
    raw, current = stable_artifact(receipt["path"])
    verification = _verify_current_receipt(
        receipt,
        current,
        label=label,
    )
    return (raw if verification["status"] == "PASS" else b""), verification


def load_verified_current_json_artifact(receipt, *, label="artifact"):
    """Load JSON and compare its receipt without a second path read."""

    shape = receipt_shape_contract(receipt, label=label)
    if shape["status"] != "PASS":
        return {}, _verify_current_receipt(receipt, {}, label=label)
    payload, current = stable_json_artifact(receipt["path"])
    return payload, _verify_current_receipt(receipt, current, label=label)


def verify_current_json_artifact(receipt, *, label="artifact"):
    """Re-read current JSON bytes and require an exact receipt match."""

    _payload, verification = load_verified_current_json_artifact(
        receipt,
        label=label,
    )
    return verification


def verify_current_candidate_artifact(payload, *, label="candidate artifact"):
    """Transitively revalidate a candidate-bound ablation's binary artifact."""

    payload = payload if isinstance(payload, dict) else {}
    model_binding = payload.get("model_binding")
    model_binding = model_binding if isinstance(model_binding, dict) else {}
    applicable = (
        payload.get("evidence_source") == "candidate_artifact_band_ablation"
        or model_binding.get("binding_kind") == "candidate_artifact"
        or model_binding.get("status") == "BOUND_CANDIDATE_ARTIFACT"
    )
    if not applicable:
        return {
            "status": "PASS",
            "applicable": False,
            "path": None,
            "expected_sha256": None,
            "actual_sha256": None,
            "blockers": [],
        }
    input_receipts = payload.get("input_receipts")
    input_receipts = input_receipts if isinstance(input_receipts, dict) else {}
    receipt = input_receipts.get("artifact")
    verification = verify_current_artifact(receipt, label=label)
    blockers = list(verification.get("blockers") or [])
    blockers.append(
        "operational candidate-artifact evidence is disabled until an "
        "independently anchored candidate trust root exists; operational "
        "evidence must bind a verified active release"
    )
    if isinstance(receipt, dict):
        if receipt.get("path") != model_binding.get("artifact_path"):
            blockers.append(f"{label} receipt path differs from model binding")
        if receipt.get("sha256") != model_binding.get("artifact_sha256"):
            blockers.append(f"{label} receipt sha256 differs from model binding")
        artifact = payload.get("artifact")
        if not isinstance(artifact, dict):
            blockers.append(f"{label} metadata must be an object")
        else:
            expected_metadata = {
                "path": receipt.get("path"),
                "sha256": receipt.get("sha256"),
                "size_bytes": receipt.get("size_bytes"),
                "prediction_mode": model_binding.get("prediction_mode"),
            }
            for field, expected_value in expected_metadata.items():
                if artifact.get(field) != expected_value:
                    blockers.append(
                        f"{label} metadata {field} differs from its receipt/model binding"
                    )
    if model_binding.get("serving_or_release_authorization") is not False:
        blockers.append(
            f"{label} model binding serving_or_release_authorization must be false"
        )
    return {
        **verification,
        "status": "BLOCK" if blockers else "PASS",
        "applicable": True,
        "blockers": blockers,
    }


def verify_current_active_release_binding(
    payload,
    *,
    pointer_path=DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root=DEFAULT_RELEASES_ROOT,
    repo_root=REPO_ROOT,
):
    """Bind ablation evidence through the canonical trusted serving loader."""

    payload = payload if isinstance(payload, dict) else {}
    model_binding = payload.get("model_binding")
    model_binding = model_binding if isinstance(model_binding, dict) else {}
    if model_binding.get("binding_kind") != "verified_active_release":
        return {
            "status": "PASS",
            "applicable": False,
            "pointer": {},
            "manifest": {},
            "serving_model": {},
            "blockers": [],
        }

    blockers = []
    pointer = {}
    pointer_receipt = {}
    manifest = {}
    manifest_receipt = {}
    serving_model = {}
    active_release_id = None
    try:
        bundle = load_verified_active_serving_bundle(
            pointer_path=pointer_path,
            releases_root=releases_root,
            repo_root=repo_root,
            check_runtime=False,
            deserialize_model_artifacts=False,
        )
    except (
        OSError,
        ReleaseArtifactVerificationError,
        TypeError,
        ValueError,
    ) as exc:
        blockers.append(
            "current active release failed canonical trusted serving "
            f"verification: {exc}"
        )
        bundle = None

    if bundle is not None:
        if bundle.status != STATUS_BOUND:
            blockers.append(
                "current active release is not a canonically verified BOUND "
                "serving bundle"
            )
        else:
            active_release_id = bundle.release_id
            pointer, pointer_receipt = stable_json_artifact(pointer_path)
            blockers.extend(pointer_receipt.get("blockers") or [])
            manifest_path = Path(bundle.release_dir) / RELEASE_MANIFEST_NAME
            manifest, manifest_receipt = stable_json_artifact(manifest_path)
            blockers.extend(manifest_receipt.get("blockers") or [])
            if pointer_receipt.get("sha256") != bundle.pointer_file_sha256:
                blockers.append(
                    "current active-release pointer bytes changed after "
                    "canonical serving verification"
                )
            if (
                manifest_receipt.get("sha256")
                != bundle.manifest_file_sha256
            ):
                blockers.append(
                    "current active-release manifest bytes changed after "
                    "canonical serving verification"
                )
            try:
                current_manifest_sha256 = manifest_content_sha256(manifest)
            except (TypeError, ValueError) as exc:
                blockers.append(
                    "current active-release manifest content hash cannot be "
                    f"verified: {exc}"
                )
            else:
                if current_manifest_sha256 != bundle.manifest_sha256:
                    blockers.append(
                        "current active-release manifest content differs from "
                        "canonical serving verification"
                    )
            expected_binding_fields = {
                "status": bundle.status,
                "pointer_present": bundle.pointer_present,
                "base_model_bound": bundle.base_model_bound,
                "release_id": bundle.release_id,
                "release_manifest_sha256": bundle.manifest_sha256,
                "release_pointer_sha256": bundle.pointer_sha256,
                "release_sequence": bundle.sequence,
                "release_kind": bundle.release_kind,
                "release_production_capable": bundle.production_capable,
            }
            for field, expected_value in expected_binding_fields.items():
                if model_binding.get(field) != expected_value:
                    blockers.append(
                        f"current active-release {field} differs from "
                        "ablation model binding"
                    )
            route_markets = bundle.route.get("markets")
            route_markets = (
                route_markets if isinstance(route_markets, Mapping) else {}
            )
            expected_market_ids = sorted(str(value) for value in route_markets)
            if model_binding.get("market_ids") != expected_market_ids:
                blockers.append(
                    "current active-release route markets differ from "
                    "ablation model binding"
                )
            if model_binding.get("model_count") != len(expected_market_ids):
                blockers.append(
                    "current active-release route model count differs from "
                    "ablation model binding"
                )
            if model_binding.get("artifact_hashes") != dict(
                bundle.artifact_hashes
            ):
                blockers.append(
                    "current active-release serving artifact hashes differ "
                    "from ablation model binding"
                )

            inventory = (manifest.get("artifacts") or {}).get("inventory")
            inventory = inventory if isinstance(inventory, list) else []
            model_rows = [
                row
                for row in inventory
                if isinstance(row, dict)
                and row.get("declared") is True
                and row.get("role") == "pooled_band_model"
                and row.get("kind") == "model"
            ]
            if len(model_rows) != 1:
                blockers.append(
                    "canonical active release lacks one declared "
                    "pooled_band_model role of kind model"
                )
            else:
                [model_row] = model_rows
                canonical_model_path = str(
                    (Path(bundle.release_dir) / str(model_row["path"])).resolve(
                        strict=False
                    )
                )
                if (
                    bundle.artifact_paths.get("pooled_band_model")
                    != canonical_model_path
                    or bundle.artifact_hashes.get("pooled_band_model")
                    != model_row.get("sha256")
                ):
                    blockers.append(
                        "canonical serving model role differs from verified "
                        "release inventory"
                    )
                serving_model = {
                    "status": "PASS",
                    "role": "pooled_band_model",
                    "kind": "model",
                    "path": canonical_model_path,
                    "sha256": model_row.get("sha256"),
                    "size_bytes": model_row.get("bytes"),
                    "route_registry_verified": True,
                }

    return {
        "status": "BLOCK" if blockers else "PASS",
        "applicable": True,
        "pointer": pointer_receipt,
        "pointer_payload": pointer,
        "manifest": manifest_receipt,
        "manifest_payload": manifest,
        "serving_model": serving_model,
        "release_id": active_release_id,
        "blockers": blockers,
    }


def artifact_path_from_candidate_replay(payload):
    artifact = (payload or {}).get("artifact") or {}
    path = artifact.get("path") or artifact.get("artifact_path")
    if not path:
        return None
    return Path(path)


def _is_missing_imputer_stat(value):
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return False


def _retained_feature_names(bundle, names):
    imputer = bundle.get("imputer") if isinstance(bundle, dict) else None
    statistics = getattr(imputer, "statistics_", None)
    if statistics is None:
        return set(names)
    stats = list(statistics)
    if len(stats) != len(names):
        raise ValueError(
            "candidate artifact feature/imputer statistics length mismatch: "
            f"feature_names={len(names)}; statistics_={len(stats)}"
        )
    return {
        name
        for name, stat in zip(names, stats)
        if not _is_missing_imputer_stat(stat)
    }


def collect_artifact_feature_names(artifact):
    names = set()
    if not isinstance(artifact, dict):
        return names
    for key in (
        "feature_names",
        "feature_columns",
        "features",
        "numeric_features",
        "categorical_features",
    ):
        values = artifact.get(key)
        if isinstance(values, (list, tuple, set)):
            raw_names = [str(value) for value in values if value]
            names.update(_retained_feature_names(artifact, raw_names))
    models = artifact.get("models") or {}
    if isinstance(models, dict):
        for bundle in models.values():
            if isinstance(bundle, dict):
                names.update(collect_artifact_feature_names(bundle))
    return names


def artifact_reanalysis_lane(artifact):
    if not isinstance(artifact, dict):
        return None
    direct = artifact.get("reanalysis_promotion_lane")
    if isinstance(direct, dict):
        return direct
    lanes = artifact.get("source_family_lanes") or {}
    lane = lanes.get("reanalysis_synoptic") if isinstance(lanes, dict) else None
    if isinstance(lane, dict):
        return lane
    models = artifact.get("models") or {}
    if isinstance(models, dict):
        for bundle in models.values():
            lane = artifact_reanalysis_lane(bundle)
            if lane:
                return lane
    return None


def candidate_replay_model_bytes(
    candidate_replay_payload,
    *,
    candidate_replay_receipt,
    ablation_payload,
    active_release_verification,
    active_release_pointer=DEFAULT_ACTIVE_RELEASE_POINTER,
    active_releases_root=DEFAULT_RELEASES_ROOT,
    repo_root=REPO_ROOT,
):
    """Authenticate exact candidate bytes before permitting deserialization."""

    blockers = []
    candidate_replay_payload = (
        candidate_replay_payload
        if isinstance(candidate_replay_payload, dict)
        else {}
    )
    replay_shape = receipt_shape_contract(
        candidate_replay_receipt,
        label="candidate replay",
    )
    blockers.extend(replay_shape.get("blockers") or [])
    replay_current_verification = {}
    if replay_shape.get("status") == "PASS":
        current_replay_payload, replay_current_verification = (
            load_verified_current_json_artifact(
                candidate_replay_receipt,
                label="candidate replay",
            )
        )
        blockers.extend(replay_current_verification.get("blockers") or [])
        if replay_current_verification.get("status") != "PASS" and not (
            replay_current_verification.get("blockers")
        ):
            blockers.append(
                "candidate replay current-byte verification is not PASS"
            )
        if current_replay_payload != candidate_replay_payload:
            blockers.append(
                "candidate replay payload was not parsed from the receipted current bytes"
            )
    if (
        candidate_replay_payload.get("serving_or_release_authorization")
        is not False
    ):
        blockers.append(
            "candidate replay serving_or_release_authorization must be false"
        )
    artifact_claim = candidate_replay_payload.get("artifact")
    if not isinstance(artifact_claim, dict):
        blockers.append("candidate replay artifact metadata must be an object")
        artifact_claim = {}
    claim_shape = receipt_shape_contract(
        {
            "status": "PASS",
            "path": artifact_claim.get("path"),
            "sha256": artifact_claim.get("sha256"),
            "size_bytes": artifact_claim.get("size_bytes"),
            "blockers": [],
        },
        label="candidate replay model artifact",
    )
    blockers.extend(claim_shape.get("blockers") or [])
    prediction_mode = artifact_claim.get("prediction_mode")
    if not isinstance(prediction_mode, str) or not prediction_mode.strip():
        blockers.append(
            "candidate replay model artifact prediction_mode must be non-empty"
        )

    ablation_payload = (
        ablation_payload if isinstance(ablation_payload, dict) else {}
    )
    ablation_binding = ablation_payload.get("model_binding")
    ablation_binding = (
        ablation_binding if isinstance(ablation_binding, dict) else {}
    )
    replay_binding = candidate_replay_payload.get("model_binding")
    if not isinstance(replay_binding, dict):
        blockers.append("candidate replay model_binding must be an object")
        replay_binding = {}
    if replay_binding.get("serving_or_release_authorization") is not False:
        blockers.append(
            "candidate replay model_binding serving_or_release_authorization must be false"
        )
    for field, expected_value in {
        "artifact_path": artifact_claim.get("path"),
        "artifact_sha256": artifact_claim.get("sha256"),
        "artifact_size_bytes": artifact_claim.get("size_bytes"),
        "prediction_mode": prediction_mode,
    }.items():
        if replay_binding.get(field) != expected_value:
            blockers.append(
                f"candidate replay model_binding {field} differs from artifact metadata"
            )

    binding_kind = ablation_binding.get("binding_kind")
    active_release_initial = {}
    active_release_closing = {}
    if binding_kind == "candidate_artifact":
        candidate_verification = verify_current_candidate_artifact(
            ablation_payload,
        )
        blockers.extend(candidate_verification.get("blockers") or [])
        if candidate_verification.get("status") != "PASS" and not (
            candidate_verification.get("blockers")
        ):
            blockers.append("current candidate artifact verification is not PASS")
        expected = {
            "status": ablation_binding.get("status"),
            "binding_kind": "candidate_artifact",
            "promotion_evidence_binding": ablation_binding.get(
                "promotion_evidence_binding"
            ),
            "artifact_path": ablation_binding.get("artifact_path"),
            "artifact_sha256": ablation_binding.get("artifact_sha256"),
            "prediction_mode": ablation_binding.get("prediction_mode"),
        }
        for field, expected_value in expected.items():
            if replay_binding.get(field) != expected_value:
                blockers.append(
                    f"candidate replay model binding {field} differs from ablation"
                )
        if artifact_claim.get("path") != ablation_binding.get("artifact_path"):
            blockers.append(
                "candidate replay model artifact path differs from candidate ablation"
            )
        if artifact_claim.get("sha256") != ablation_binding.get(
            "artifact_sha256"
        ):
            blockers.append(
                "candidate replay model artifact sha256 differs from candidate ablation"
            )
        ablation_receipts = ablation_payload.get("input_receipts")
        ablation_receipts = (
            ablation_receipts if isinstance(ablation_receipts, dict) else {}
        )
        candidate_receipt = ablation_receipts.get("artifact")
        candidate_receipt = (
            candidate_receipt if isinstance(candidate_receipt, dict) else {}
        )
        if artifact_claim.get("size_bytes") != candidate_receipt.get(
            "size_bytes"
        ):
            blockers.append(
                "candidate replay model artifact size differs from candidate ablation receipt"
            )
        ablation_artifact = ablation_payload.get("artifact")
        ablation_artifact = (
            ablation_artifact if isinstance(ablation_artifact, dict) else {}
        )
        for field, expected_value in {
            "path": artifact_claim.get("path"),
            "sha256": artifact_claim.get("sha256"),
            "size_bytes": artifact_claim.get("size_bytes"),
            "prediction_mode": prediction_mode,
        }.items():
            if ablation_artifact.get(field) != expected_value:
                blockers.append(
                    f"candidate ablation artifact {field} differs from candidate replay"
                )
        blockers.append(
            "candidate-artifact pickle deserialization is disabled until an "
            "independently anchored operational candidate-evidence trust root "
            "is implemented; matching claims across detached JSON artifacts "
            "are not an independent trust anchor"
        )
    elif binding_kind == "verified_active_release":
        active_release_verification = (
            active_release_verification
            if isinstance(active_release_verification, dict)
            else {}
        )
        active_release_initial = verify_current_active_release_binding(
            ablation_payload,
            pointer_path=active_release_pointer,
            releases_root=active_releases_root,
            repo_root=repo_root,
        )
        blockers.extend(active_release_initial.get("blockers") or [])
        if active_release_initial.get("status") != "PASS" and not (
            active_release_initial.get("blockers")
        ):
            blockers.append("current active release verification is not PASS")
        if active_release_verification:
            for field in ("status", "release_id", "serving_model"):
                if active_release_verification.get(
                    field
                ) != active_release_initial.get(field):
                    blockers.append(
                        "supplied active-release verification differs from "
                        f"fresh canonical verification for {field}"
                    )
        for field in (
            "status",
            "binding_kind",
            "pointer_present",
            "base_model_bound",
            "release_id",
            "release_manifest_sha256",
            "release_pointer_sha256",
            "market_ids",
            "model_count",
            "shared_explicit_bundle",
            "shared_verified_bundle",
        ):
            if replay_binding.get(field) != ablation_binding.get(field):
                blockers.append(
                    f"candidate replay model binding {field} differs from ablation"
                )
        serving_model = active_release_initial.get("serving_model")
        serving_model = (
            serving_model if isinstance(serving_model, dict) else {}
        )
        if (
            serving_model.get("status") != "PASS"
            or serving_model.get("role") != "pooled_band_model"
            or serving_model.get("kind") != "model"
            or serving_model.get("route_registry_verified") is not True
        ):
            blockers.append(
                "candidate replay lacks a canonical route/registry-verified "
                "pooled_band_model role of kind model"
            )
        for field, expected_value in {
            "path": serving_model.get("path"),
            "sha256": serving_model.get("sha256"),
            "size_bytes": serving_model.get("size_bytes"),
        }.items():
            if artifact_claim.get(field) != expected_value:
                blockers.append(
                    "candidate replay model artifact "
                    f"{field} differs from canonical serving model"
                )
        if replay_binding.get("artifact_role") != "pooled_band_model":
            blockers.append(
                "candidate replay model artifact_role must equal "
                "pooled_band_model"
            )
        if replay_binding.get("artifact_kind") != "model":
            blockers.append(
                "candidate replay model artifact_kind must equal model"
            )
    else:
        blockers.append(
            "candidate replay model binding is not candidate-artifact or verified-active-release bound"
        )

    raw = b""
    current = {}
    if not blockers:
        raw, current = stable_artifact(artifact_claim["path"])
        blockers.extend(current.get("blockers") or [])
        if current.get("status") != "PASS" and not current.get("blockers"):
            blockers.append(
                "candidate replay model artifact stable read is not PASS"
            )
        if current.get("path") != artifact_claim.get("path"):
            blockers.append(
                "candidate replay model artifact resolved path differs from metadata"
            )
        if current.get("sha256") != artifact_claim.get("sha256"):
            blockers.append(
                "candidate replay model artifact sha256 differs from metadata"
            )
        if current.get("size_bytes") != artifact_claim.get("size_bytes"):
            blockers.append(
                "candidate replay model artifact size differs from metadata"
            )
    if binding_kind == "verified_active_release" and not blockers:
        active_release_closing = verify_current_active_release_binding(
            ablation_payload,
            pointer_path=active_release_pointer,
            releases_root=active_releases_root,
            repo_root=repo_root,
        )
        blockers.extend(active_release_closing.get("blockers") or [])
        if active_release_closing.get("status") != "PASS" and not (
            active_release_closing.get("blockers")
        ):
            blockers.append(
                "active release failed closing verification before deserialization"
            )
        for field in ("release_id", "pointer", "manifest", "serving_model"):
            if active_release_closing.get(field) != active_release_initial.get(
                field
            ):
                blockers.append(
                    "active release changed between opening and closing "
                    f"verification for {field}"
                )
    verification = {
        "status": "BLOCK" if blockers else "PASS",
        "candidate_replay_receipt": candidate_replay_receipt,
        "candidate_replay_current_verification": replay_current_verification,
        "artifact_receipt": current,
        "binding_kind": binding_kind,
        "active_release_initial": active_release_initial,
        "active_release_closing": active_release_closing,
        "blockers": blockers,
    }
    return (raw if not blockers else b""), verification
