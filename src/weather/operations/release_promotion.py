"""Fail-closed active-release pointer promotion and rollback."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from weather.artifacts import (
    CandidateArtifactPathError,
    DEFAULT_CANDIDATE_ARTIFACT_ROOT,
    assert_candidate_artifact_output,
    training_artifact_output_policy,
)
from weather.paths import REPO_ROOT, data_path
from weather.release_contract import (
    NO_ACTIVE_POINTER_STATE,
    PRODUCTION_RELEASE_KIND,
    SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND,
    active_release_kind,
)
from weather.release_artifacts import (
    load_active_release_pointer as load_active_pointer,
    pointer_content_sha256,
    resolve_verified_active_release,
    strict_json_loads,
    validate_release_id,
)
from weather.schema_registry import schema_version
from weather.operations.release_manifest import (
    DEFAULT_RELEASES_ROOT,
    ReleaseLifecycleError,
    _write_json_atomic,
    canonical_payload_sha256,
    capture_code_identity,
    utc_now_iso,
    verify_release,
)


ACTIVE_POINTER_SCHEMA_VERSION = schema_version("active_release_pointer")
PROMOTION_DECISION_SCHEMA_VERSION = schema_version("release_promotion_decision")
MARKET_DAY_BOUNDARY_SCHEMA_VERSION = schema_version("release_market_day_boundary")
ROLLBACK_DRILL_SCHEMA_VERSION = schema_version("release_rollback_drill")
DEFAULT_ACTIVE_POINTER = DEFAULT_RELEASES_ROOT / "current_release.json"
DEFAULT_CANDIDATES_ROOT = DEFAULT_CANDIDATE_ARTIFACT_ROOT
DEFAULT_ROLLBACK_DRILL = data_path("backtest", "release_rollback_drill.json")


def _parse_utc(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ReleaseLifecycleError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReleaseLifecycleError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_promotion_decision(
    decision: Mapping[str, Any],
    *,
    release_id: str,
    manifest_sha256: str,
    expected_release_kind: str | None = None,
) -> dict[str, Any]:
    failures = []
    expected = {
        "schema_version": PROMOTION_DECISION_SCHEMA_VERSION,
        "decision": "PROMOTE",
        "gate_status": "PASS",
        "release_id": release_id,
        "manifest_sha256": manifest_sha256,
        "candidate_only_build": True,
        "reviewed": True,
    }
    for field, value in expected.items():
        if decision.get(field) != value:
            failures.append(f"{field} must be {value!r}")
    if (
        expected_release_kind is not None
        and decision.get("release_kind") != expected_release_kind
    ):
        failures.append(f"release_kind must be {expected_release_kind!r}")
    elif (
        expected_release_kind is None
        and "release_kind" in decision
        and decision.get("release_kind") != PRODUCTION_RELEASE_KIND
    ):
        failures.append(
            f"release_kind must be absent or {PRODUCTION_RELEASE_KIND!r} "
            "for a production-capable release"
        )
    if not str(decision.get("reviewed_by") or "").strip():
        failures.append("reviewed_by is required")
    try:
        _parse_utc(decision.get("reviewed_at_utc"), field="reviewed_at_utc")
    except ReleaseLifecycleError as exc:
        failures.append(str(exc))
    if failures:
        raise ReleaseLifecycleError("promotion decision failed closed: " + "; ".join(failures))
    result = {
        "status": "PASS",
        "sha256": canonical_payload_sha256(decision),
        "reviewed_by": str(decision["reviewed_by"]),
        "reviewed_at_utc": str(decision["reviewed_at_utc"]),
    }
    if expected_release_kind is not None:
        result["release_kind"] = expected_release_kind
    return result


def validate_market_day_boundary(
    proof: Mapping[str, Any],
    *,
    release_id: str,
    manifest_sha256: str,
    now: datetime | None = None,
    max_age_seconds: float = 900.0,
) -> dict[str, Any]:
    """Validate a fresh, target-specific market-day cutover proof."""

    failures = []
    expected = {
        "schema_version": MARKET_DAY_BOUNDARY_SCHEMA_VERSION,
        "status": "PASS",
        "release_id": release_id,
        "manifest_sha256": manifest_sha256,
        "at_market_day_boundary": True,
        "processes_quiesced": True,
        "open_market_days": [],
        "mixed_release_market_days": [],
    }
    for field, value in expected.items():
        if proof.get(field) != value:
            failures.append(f"{field} must be {value!r}")
    try:
        date.fromisoformat(str(proof.get("effective_target_date")))
    except (TypeError, ValueError):
        failures.append("effective_target_date must be an ISO date")
    observed: datetime | None = None
    try:
        observed = _parse_utc(proof.get("observed_at_utc"), field="observed_at_utc")
    except ReleaseLifecycleError as exc:
        failures.append(str(exc))
    if observed is not None:
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            failures.append("current time must include a timezone")
            reference = reference.replace(tzinfo=timezone.utc)
        reference = reference.astimezone(timezone.utc)
        age = (reference - observed).total_seconds()
        if age < -60:
            failures.append("observed_at_utc is in the future")
        elif age > max_age_seconds:
            failures.append(f"market-day boundary proof is stale ({age:.1f}s > {max_age_seconds:.1f}s)")
    if failures:
        raise ReleaseLifecycleError("market-day boundary proof failed closed: " + "; ".join(failures))
    return {
        "status": "PASS",
        "sha256": canonical_payload_sha256(proof),
        "observed_at_utc": str(proof["observed_at_utc"]),
        "effective_target_date": str(proof["effective_target_date"]),
    }


def assert_candidate_only_output(
    output_path: str | Path,
    *,
    candidates_root: str | Path = DEFAULT_CANDIDATES_ROOT,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    active_pointer: str | Path = DEFAULT_ACTIVE_POINTER,
) -> Path:
    """Guard hook for trainers: allow writes only below the candidate root."""

    try:
        return assert_candidate_artifact_output(
            output_path,
            candidates_root=candidates_root,
            releases_root=releases_root,
            active_pointer=active_pointer,
        )
    except CandidateArtifactPathError as exc:
        raise ReleaseLifecycleError(str(exc)) from exc


def assert_training_output_path(
    output_path: str | Path,
    *,
    candidates_root: str | Path = DEFAULT_CANDIDATES_ROOT,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    active_pointer: str | Path = DEFAULT_ACTIVE_POINTER,
    allow_legacy_serving_output: bool = False,
) -> dict[str, Any]:
    """Guard a trainer output, with an explicit quarantined legacy escape hatch.

    Immutable release directories and the active pointer are never writable by
    a trainer, even in compatibility mode.  Compatibility permits an old
    serving path only so operators can migrate incrementally; callers must
    treat the result as quarantined and ineligible for release construction.
    """

    try:
        return training_artifact_output_policy(
            output_path,
            candidates_root=candidates_root,
            releases_root=releases_root,
            active_pointer=active_pointer,
            allow_legacy_serving_output=allow_legacy_serving_output,
        )
    except CandidateArtifactPathError as exc:
        raise ReleaseLifecycleError(str(exc)) from exc


@contextmanager
def _pointer_lock(pointer_path: Path) -> Iterator[None]:
    lock_path = pointer_path.with_name(f".{pointer_path.name}.promotion.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ReleaseLifecycleError(
            f"release pointer is locked; inspect and remove only after confirming no promotion is active: {lock_path}"
        ) from exc
    try:
        os.write(handle, f"pid={os.getpid()} created_at_utc={utc_now_iso()}\n".encode("utf-8"))
        os.fsync(handle)
        yield
    finally:
        os.close(handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _release_dir(releases_root: Path, release_id: str) -> Path:
    return releases_root / validate_release_id(release_id)


def _rollback_drill_path(
    drill_record_path: str | Path,
    *,
    releases_root: Path,
) -> Path:
    """Reject drill outputs that could overwrite immutable release state."""

    candidate = Path(drill_record_path)
    if candidate.is_symlink():
        raise ReleaseLifecycleError(
            f"rollback drill record must not be a symlink: {candidate}"
        )
    path = candidate.resolve()
    try:
        path.relative_to(releases_root)
    except ValueError:
        pass
    else:
        raise ReleaseLifecycleError(
            "rollback drill record must be outside the immutable releases root"
        )
    return path


def _post_rollback_identity_proof(
    *,
    releases_root: Path,
    pointer_path: Path,
    target_release_id: str,
    target_manifest_sha256: str,
    source_release_id: str,
    source_manifest_sha256: str,
    verified_at_utc: str,
) -> dict[str, Any]:
    """Re-read the swapped pointer and release to prove the resulting identity."""

    observed = load_active_pointer(pointer_path)
    expected_pointer_fields = {
        "action": "ROLLBACK",
        "active_release_id": target_release_id,
        "active_manifest_sha256": target_manifest_sha256,
        "previous_release_id": source_release_id,
        "previous_manifest_sha256": source_manifest_sha256,
    }
    mismatches = [
        f"{field}={observed.get(field)!r} (expected {expected!r})"
        for field, expected in expected_pointer_fields.items()
        if observed.get(field) != expected
    ]
    if mismatches:
        raise ReleaseLifecycleError(
            "post-rollback pointer identity mismatch: " + "; ".join(mismatches)
        )
    verified = verify_release(
        _release_dir(releases_root, target_release_id),
        expected_manifest_sha256=target_manifest_sha256,
        check_runtime=False,
    )
    proof: dict[str, Any] = {
        "status": "PASS",
        "verified_at_utc": verified_at_utc,
        "release_id": target_release_id,
        "manifest_sha256": verified["manifest_sha256"],
        "manifest_path": verified["manifest_path"],
        "pointer_path": str(pointer_path),
        "pointer_action": observed["action"],
        "pointer_sequence": observed["sequence"],
        "pointer_sha256": observed["pointer_sha256"],
        "release_kind": active_release_kind(observed),
        "candidate_mode": (verified.get("semantic_contract") or {}).get(
            "candidate_mode"
        ),
        "production_capable": (verified.get("semantic_contract") or {}).get(
            "production_capable"
        ),
        "integrity_verified": True,
        "runtime_compatibility_checked": False,
    }
    proof["proof_sha256"] = canonical_payload_sha256(proof)
    return proof


def _post_deactivation_serving_proof(
    *,
    releases_root: Path,
    pointer_path: Path,
    verified_at_utc: str,
) -> dict[str, Any]:
    """Prove that an absent pointer resolves through the canonical serving path."""

    from weather.release_serving import (
        STATUS_RESEARCH_UNBOUND,
        load_verified_active_serving_bundle,
        serving_bundle_lineage,
    )

    if pointer_path.exists():
        raise ReleaseLifecycleError(
            "post-deactivation serving proof requires the active pointer to be absent"
        )
    bundle = load_verified_active_serving_bundle(
        pointer_path=pointer_path,
        releases_root=releases_root,
        check_runtime=False,
    )
    lineage = serving_bundle_lineage(bundle)
    expected_lineage_status = "research_unbound_non_countable"
    if (
        bundle.status != STATUS_RESEARCH_UNBOUND
        or bundle.pointer_present
        or lineage.get("release_identity_status") != expected_lineage_status
    ):
        raise ReleaseLifecycleError(
            "post-deactivation serving path did not resolve to the canonical "
            "no-active-pointer state"
        )
    proof: dict[str, Any] = {
        "status": "PASS",
        "verified_at_utc": verified_at_utc,
        "target_state": NO_ACTIVE_POINTER_STATE,
        "release_id": None,
        "manifest_sha256": None,
        "pointer_path": str(pointer_path),
        "pointer_present": False,
        "serving_bundle_status": bundle.status,
        "release_identity_status": expected_lineage_status,
        "release_identity_reason": lineage["release_identity_reason"],
        "serving_path_resolved": True,
        "runtime_compatibility_checked": False,
    }
    proof["proof_sha256"] = canonical_payload_sha256(proof)
    return proof


def _rollback_drill_record(
    *,
    started_at_utc: str,
    completed_at_utc: str,
    duration_seconds: float,
    source_pointer: Mapping[str, Any],
    target: Mapping[str, Any],
    identity_proof: Mapping[str, Any],
    rollback_intent: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a truthful pending drill record without claiming worker health."""

    target_manifest = target["manifest"]
    target_release_id = str(identity_proof["release_id"])
    target_manifest_sha256 = str(identity_proof["manifest_sha256"])
    record = {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "evidence_contract": "release_rollback_drill",
        "generated_at_utc": completed_at_utc,
        "status": "PENDING_MANUAL_RESTART",
        "release_id": target_release_id,
        "manifest_sha256": target_manifest_sha256,
        "rollback_status": "PASS",
        "rollback_source_release_id": source_pointer["active_release_id"],
        "rollback_source_manifest_sha256": source_pointer["active_manifest_sha256"],
        "rollback_source_release_kind": active_release_kind(source_pointer),
        "rollback_target_release_id": target_release_id,
        "rollback_target_manifest_sha256": target_manifest_sha256,
        "rollback_target_release_kind": identity_proof["release_kind"],
        "restored_release_id": target_release_id,
        "rollback_started_at_utc": started_at_utc,
        "rollback_completed_at_utc": completed_at_utc,
        "rollback_duration_seconds": duration_seconds,
        "post_rollback_identity_status": "PASS",
        "post_rollback_identity": dict(identity_proof),
        "rollback_intent_sha256": rollback_intent["record_sha256"],
        "rollback_intent": dict(rollback_intent),
        "manual_coordinated_restart": {
            "required": True,
            "status": "PENDING",
            "release_id": target_release_id,
            "required_runtimes": list(target_manifest.get("expected_live_runtimes") or []),
            "completed_at_utc": None,
            "completed_by": None,
            "runtime_identity_proof": None,
        },
        "health_status": "PENDING",
        "health_proof": None,
        "completion_requirements": [
            "set manual_coordinated_restart.status to PASS after every required "
            "worker restarts on the restored release",
            "attach runtime_identity_proof for the restarted workers",
            "set health_status to PASS only after post-restart health checks pass",
            "set status to PASS only after the manual restart and health proof are complete",
        ],
    }
    record["record_sha256"] = canonical_payload_sha256(record)
    return record


def _rollback_drill_intent(
    *,
    started_at_utc: str,
    source_pointer: Mapping[str, Any],
    target: Mapping[str, Any],
    planned_pointer: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist reconciliation evidence before changing the active pointer.

    A pointer and a drill record cannot be replaced as one filesystem atomic
    operation.  This intent is therefore written first.  If finalization later
    fails, operators still have a durable, self-hashed record containing the
    exact planned pointer identity to reconcile against the active pointer.
    """

    target_manifest = target["manifest"]
    record = {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "evidence_contract": "release_rollback_drill",
        "generated_at_utc": started_at_utc,
        "status": "PENDING_POINTER_RECONCILIATION",
        "release_id": planned_pointer["active_release_id"],
        "manifest_sha256": planned_pointer["active_manifest_sha256"],
        "rollback_status": "PENDING",
        "rollback_source_release_id": source_pointer["active_release_id"],
        "rollback_source_manifest_sha256": source_pointer[
            "active_manifest_sha256"
        ],
        "rollback_source_release_kind": active_release_kind(source_pointer),
        "rollback_target_release_id": planned_pointer["active_release_id"],
        "rollback_target_manifest_sha256": planned_pointer[
            "active_manifest_sha256"
        ],
        "rollback_target_release_kind": active_release_kind(planned_pointer),
        "planned_pointer_sequence": planned_pointer["sequence"],
        "planned_pointer_sha256": planned_pointer["pointer_sha256"],
        "rollback_started_at_utc": started_at_utc,
        "manual_coordinated_restart": {
            "required": True,
            "status": "PENDING",
            "release_id": planned_pointer["active_release_id"],
            "required_runtimes": list(
                target_manifest.get("expected_live_runtimes") or []
            ),
            "completed_at_utc": None,
            "completed_by": None,
            "runtime_identity_proof": None,
        },
        "health_status": "PENDING",
        "health_proof": None,
        "reconciliation_action": (
            "compare planned_pointer_sha256 with the active pointer, verify the "
            "target release, and rerun/complete the rollback drill record"
        ),
    }
    record["record_sha256"] = canonical_payload_sha256(record)
    return record


def _no_pointer_rollback_intent(
    *,
    started_at_utc: str,
    source_pointer: Mapping[str, Any],
    source: Mapping[str, Any],
    boundary: Mapping[str, Any],
    pointer_path: Path,
) -> dict[str, Any]:
    """Journal a first-release deactivation before removing its pointer."""

    source_manifest = source["manifest"]
    record = {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "evidence_contract": "release_rollback_drill",
        "generated_at_utc": started_at_utc,
        "status": "PENDING_POINTER_RECONCILIATION",
        "release_id": source_pointer["active_release_id"],
        "manifest_sha256": source_pointer["active_manifest_sha256"],
        "rollback_status": "PENDING",
        "rollback_source_release_id": source_pointer["active_release_id"],
        "rollback_source_manifest_sha256": source_pointer[
            "active_manifest_sha256"
        ],
        "rollback_source_release_kind": active_release_kind(source_pointer),
        "rollback_source_pointer_sha256": source_pointer["pointer_sha256"],
        "rollback_source_pointer_sequence": source_pointer["sequence"],
        "rollback_target_state": NO_ACTIVE_POINTER_STATE,
        "rollback_target_release_id": None,
        "rollback_target_manifest_sha256": None,
        "rollback_target_release_kind": None,
        "planned_pointer_state": "ABSENT",
        "planned_pointer_path": str(pointer_path),
        "market_day_boundary_sha256": boundary["sha256"],
        "market_day_boundary_observed_at_utc": boundary["observed_at_utc"],
        "effective_target_date": boundary["effective_target_date"],
        "rollback_started_at_utc": started_at_utc,
        "manual_coordinated_restart": {
            "required": True,
            "status": "PENDING",
            "release_id": None,
            "target_state": NO_ACTIVE_POINTER_STATE,
            "required_runtimes": list(
                source_manifest.get("expected_live_runtimes") or []
            ),
            "completed_at_utc": None,
            "completed_by": None,
            "runtime_identity_proof": None,
        },
        "health_status": "PENDING",
        "health_proof": None,
        "reconciliation_action": (
            "verify rollback_source_pointer_sha256 when the pointer is present; "
            "otherwise prove the pointer is absent, resolve the canonical serving "
            "path as research-unbound/non-countable, and finalize the drill"
        ),
    }
    record["record_sha256"] = canonical_payload_sha256(record)
    return record


def _load_no_pointer_rollback_intent(
    drill_record_path: Path,
    *,
    pointer_path: Path,
    source_pointer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and verify the journal for a first-release deactivation."""

    try:
        payload = strict_json_loads(
            drill_record_path.read_text(encoding="utf-8"),
            label="no-active-pointer rollback reconciliation intent",
        )
    except (OSError, TypeError, ValueError) as exc:
        state = "present" if source_pointer is not None else "absent"
        raise ReleaseLifecycleError(
            f"active pointer is {state}, but a recoverable no-active-pointer "
            f"rollback intent cannot be loaded from {drill_record_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ReleaseLifecycleError(
            "no-active-pointer rollback reconciliation intent must be a JSON object"
        )
    expected = {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "evidence_contract": "release_rollback_drill",
        "status": "PENDING_POINTER_RECONCILIATION",
        "rollback_target_state": NO_ACTIVE_POINTER_STATE,
        "rollback_target_release_id": None,
        "rollback_target_manifest_sha256": None,
        "rollback_target_release_kind": None,
        "planned_pointer_state": "ABSENT",
        "planned_pointer_path": str(pointer_path),
    }
    if source_pointer is not None:
        expected.update(
            {
                "release_id": source_pointer.get("active_release_id"),
                "manifest_sha256": source_pointer.get("active_manifest_sha256"),
                "rollback_source_release_id": source_pointer.get(
                    "active_release_id"
                ),
                "rollback_source_manifest_sha256": source_pointer.get(
                    "active_manifest_sha256"
                ),
                "rollback_source_release_kind": active_release_kind(
                    source_pointer
                ),
                "rollback_source_pointer_sha256": source_pointer.get(
                    "pointer_sha256"
                ),
                "rollback_source_pointer_sequence": source_pointer.get(
                    "sequence"
                ),
            }
        )
    mismatches = [
        f"{field}={payload.get(field)!r} (expected {value!r})"
        for field, value in expected.items()
        if payload.get(field) != value
    ]
    expected_record_sha256 = canonical_payload_sha256(
        payload,
        omit=("record_sha256",),
    )
    if payload.get("record_sha256") != expected_record_sha256:
        mismatches.append("record_sha256 does not match the canonical intent payload")
    if mismatches:
        raise ReleaseLifecycleError(
            "no-active-pointer rollback state does not match its durable drill "
            "intent: " + "; ".join(mismatches)
        )
    return payload


def _no_pointer_rollback_drill_record(
    *,
    completed_at_utc: str,
    duration_seconds: float,
    source: Mapping[str, Any],
    identity_proof: Mapping[str, Any],
    rollback_intent: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the pending-restart proof for rollback to an absent pointer."""

    source_manifest = source["manifest"]
    source_release_id = str(rollback_intent["rollback_source_release_id"])
    source_manifest_sha256 = str(
        rollback_intent["rollback_source_manifest_sha256"]
    )
    record = {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "evidence_contract": "release_rollback_drill",
        "generated_at_utc": completed_at_utc,
        "status": "PENDING_MANUAL_RESTART",
        "release_id": source_release_id,
        "manifest_sha256": source_manifest_sha256,
        "rollback_status": "PASS",
        "rollback_source_release_id": source_release_id,
        "rollback_source_manifest_sha256": source_manifest_sha256,
        "rollback_source_release_kind": rollback_intent[
            "rollback_source_release_kind"
        ],
        "rollback_source_pointer_sha256": rollback_intent[
            "rollback_source_pointer_sha256"
        ],
        "rollback_source_pointer_sequence": rollback_intent[
            "rollback_source_pointer_sequence"
        ],
        "rollback_target_state": NO_ACTIVE_POINTER_STATE,
        "rollback_target_release_id": None,
        "rollback_target_manifest_sha256": None,
        "rollback_target_release_kind": None,
        "restored_release_id": None,
        "active_pointer_present": False,
        "rollback_started_at_utc": rollback_intent["rollback_started_at_utc"],
        "rollback_completed_at_utc": completed_at_utc,
        "rollback_duration_seconds": max(duration_seconds, 1e-9),
        "post_rollback_identity_status": "PASS",
        "post_rollback_serving_status": "PASS",
        "post_rollback_identity": dict(identity_proof),
        "rollback_intent_sha256": rollback_intent["record_sha256"],
        "rollback_intent": dict(rollback_intent),
        "manual_coordinated_restart": {
            "required": True,
            "status": "PENDING",
            "release_id": None,
            "target_state": NO_ACTIVE_POINTER_STATE,
            "required_runtimes": list(
                source_manifest.get("expected_live_runtimes") or []
            ),
            "completed_at_utc": None,
            "completed_by": None,
            "runtime_identity_proof": None,
        },
        "health_status": "PENDING",
        "health_proof": None,
        "completion_requirements": [
            "restart every required worker after the active pointer is absent",
            "attach runtime_identity_proof showing research_unbound_non_countable",
            "set health_status to PASS only after post-restart serving health passes",
            "set status to PASS only after the manual restart and health proof are complete",
        ],
    }
    record["record_sha256"] = canonical_payload_sha256(record)
    return record


def _load_rollback_drill_intent(
    drill_record_path: Path,
    *,
    active_pointer: Mapping[str, Any],
) -> dict[str, Any]:
    """Load the pre-swap journal and bind it to the observed rollback pointer."""

    try:
        payload = strict_json_loads(
            drill_record_path.read_text(encoding="utf-8"),
            label="rollback drill reconciliation intent",
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ReleaseLifecycleError(
            "active pointer already records a rollback, but its durable drill "
            f"intent cannot be loaded from {drill_record_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ReleaseLifecycleError("rollback drill reconciliation intent must be a JSON object")
    if payload.get("status") != "PENDING_POINTER_RECONCILIATION":
        raise ReleaseLifecycleError(
            "active pointer already records a completed rollback; refusing to toggle "
            "back to the failed release"
        )
    expected = {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "evidence_contract": "release_rollback_drill",
        "status": "PENDING_POINTER_RECONCILIATION",
        "release_id": active_pointer.get("active_release_id"),
        "manifest_sha256": active_pointer.get("active_manifest_sha256"),
        "rollback_source_release_id": active_pointer.get("previous_release_id"),
        "rollback_source_manifest_sha256": active_pointer.get(
            "previous_manifest_sha256"
        ),
        "rollback_source_release_kind": (
            active_pointer.get("previous_release_kind") or PRODUCTION_RELEASE_KIND
        ),
        "rollback_target_release_id": active_pointer.get("active_release_id"),
        "rollback_target_manifest_sha256": active_pointer.get(
            "active_manifest_sha256"
        ),
        "rollback_target_release_kind": active_release_kind(active_pointer),
        "planned_pointer_sequence": active_pointer.get("sequence"),
        "planned_pointer_sha256": active_pointer.get("pointer_sha256"),
    }
    mismatches = [
        f"{field}={payload.get(field)!r} (expected {value!r})"
        for field, value in expected.items()
        if payload.get(field) != value
    ]
    expected_record_sha256 = canonical_payload_sha256(
        payload,
        omit=("record_sha256",),
    )
    if payload.get("record_sha256") != expected_record_sha256:
        mismatches.append("record_sha256 does not match the canonical intent payload")
    if mismatches:
        raise ReleaseLifecycleError(
            "active rollback pointer does not match its durable drill intent: "
            + "; ".join(mismatches)
        )
    return payload


def _finalize_rollback_drill(
    *,
    releases_root: Path,
    pointer_path: Path,
    drill_record_path: Path,
    active_pointer: Mapping[str, Any],
    rollback_intent: Mapping[str, Any],
    operation_time: datetime,
    duration_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the committed pointer and replace its journal with the drill."""

    target_id = str(active_pointer["active_release_id"])
    target_hash = str(active_pointer["active_manifest_sha256"])
    target = verify_release(
        _release_dir(releases_root, target_id),
        expected_manifest_sha256=target_hash,
        check_runtime=False,
    )
    completed_at_utc = operation_time.astimezone(timezone.utc).isoformat()
    identity_proof = _post_rollback_identity_proof(
        releases_root=releases_root,
        pointer_path=pointer_path,
        target_release_id=target_id,
        target_manifest_sha256=target_hash,
        source_release_id=str(active_pointer["previous_release_id"]),
        source_manifest_sha256=str(active_pointer["previous_manifest_sha256"]),
        verified_at_utc=completed_at_utc,
    )
    drill_record = _rollback_drill_record(
        started_at_utc=str(rollback_intent["rollback_started_at_utc"]),
        completed_at_utc=completed_at_utc,
        duration_seconds=max(duration_seconds, 1e-9),
        source_pointer={
            "active_release_id": active_pointer["previous_release_id"],
            "active_manifest_sha256": active_pointer["previous_manifest_sha256"],
            "release_kind": (
                active_pointer.get("previous_release_kind")
                or PRODUCTION_RELEASE_KIND
            ),
            "release_kind_provenance": active_pointer.get(
                "previous_release_kind_provenance"
            ),
        },
        target=target,
        identity_proof=identity_proof,
        rollback_intent=rollback_intent,
    )
    try:
        _write_json_atomic(drill_record_path, drill_record)
    except (OSError, TypeError, ValueError) as exc:
        raise ReleaseLifecycleError(
            "release pointer was rolled back and identity-verified, but the drill record "
            f"could not be finalized at {drill_record_path}; the durable reconciliation "
            f"intent remains and the same rollback command can retry finalization: {exc}"
        ) from exc
    return identity_proof, drill_record


def _finalize_no_pointer_rollback_drill(
    *,
    releases_root: Path,
    pointer_path: Path,
    drill_record_path: Path,
    rollback_intent: Mapping[str, Any],
    operation_time: datetime,
    duration_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify pointer absence and serving resolution, then finalize the journal."""

    if pointer_path.exists():
        raise ReleaseLifecycleError(
            "cannot finalize no-active-pointer rollback while the pointer exists"
        )
    source_release_id = str(rollback_intent["rollback_source_release_id"])
    source_manifest_sha256 = str(
        rollback_intent["rollback_source_manifest_sha256"]
    )
    source = verify_release(
        _release_dir(releases_root, source_release_id),
        expected_manifest_sha256=source_manifest_sha256,
        check_runtime=False,
    )
    if (
        source["manifest"].get("parent_release") is not None
        or source["manifest"].get("rollback_target") is not None
    ):
        raise ReleaseLifecycleError(
            "no-active-pointer rollback source is not a verified first release"
        )
    completed_at_utc = operation_time.astimezone(timezone.utc).isoformat()
    identity_proof = _post_deactivation_serving_proof(
        releases_root=releases_root,
        pointer_path=pointer_path,
        verified_at_utc=completed_at_utc,
    )
    drill_record = _no_pointer_rollback_drill_record(
        completed_at_utc=completed_at_utc,
        duration_seconds=duration_seconds,
        source=source,
        identity_proof=identity_proof,
        rollback_intent=rollback_intent,
    )
    try:
        _write_json_atomic(drill_record_path, drill_record)
    except (OSError, TypeError, ValueError) as exc:
        raise ReleaseLifecycleError(
            "active pointer was removed and the canonical no-pointer serving state "
            "was verified, but the drill record could not be finalized at "
            f"{drill_record_path}; the durable reconciliation intent remains and "
            f"the same rollback command can retry finalization: {exc}"
        ) from exc
    return identity_proof, drill_record


def _new_pointer(
    *,
    sequence: int,
    action: str,
    active_release_id: str,
    active_manifest_sha256: str,
    previous_release_id: str | None,
    previous_manifest_sha256: str | None,
    boundary: Mapping[str, Any],
    decision: Mapping[str, Any] | None,
    changed_at_utc: str | None,
    release_kind: str | None = None,
    release_kind_provenance: Mapping[str, Any] | None = None,
    previous_release_kind: str | None = None,
    previous_release_kind_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pointer: dict[str, Any] = {
        "schema_version": ACTIVE_POINTER_SCHEMA_VERSION,
        "sequence": sequence,
        "action": action,
        "changed_at_utc": changed_at_utc or utc_now_iso(),
        "active_release_id": active_release_id,
        "active_manifest_sha256": active_manifest_sha256,
        "previous_release_id": previous_release_id,
        "previous_manifest_sha256": previous_manifest_sha256,
        "market_day_boundary_sha256": boundary["sha256"],
        "market_day_boundary_observed_at_utc": boundary["observed_at_utc"],
        "effective_target_date": boundary["effective_target_date"],
        "promotion_decision_sha256": decision["sha256"] if decision else None,
        "reviewed_by": decision["reviewed_by"] if decision else None,
    }
    if release_kind == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND:
        provenance = release_kind_provenance
        if provenance is None:
            if action != "PROMOTE" or sequence != 1 or decision is None:
                raise ReleaseLifecycleError(
                    "bootstrap release-kind provenance must originate from the first promotion"
                )
            provenance = {
                "origin_action": "PROMOTE",
                "origin_sequence": 1,
                "origin_release_id": active_release_id,
                "origin_manifest_sha256": active_manifest_sha256,
                "promotion_decision_sha256": decision["sha256"],
                "market_day_boundary_sha256": boundary["sha256"],
                "reviewed_by": decision["reviewed_by"],
            }
        pointer["release_kind"] = release_kind
        pointer["release_kind_provenance"] = dict(provenance)
    elif release_kind not in {None, PRODUCTION_RELEASE_KIND}:
        raise ReleaseLifecycleError(f"unsupported active release kind: {release_kind!r}")
    if previous_release_kind is not None:
        pointer["previous_release_kind"] = previous_release_kind
        if previous_release_kind == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND:
            if previous_release_kind_provenance is None:
                raise ReleaseLifecycleError(
                    "previous bootstrap release kind requires its origin provenance"
                )
            pointer["previous_release_kind_provenance"] = dict(
                previous_release_kind_provenance
            )
    pointer["pointer_sha256"] = pointer_content_sha256(pointer)
    return pointer


def promote_release(
    release_id: str,
    *,
    decision: Mapping[str, Any],
    market_day_boundary: Mapping[str, Any],
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    pointer_path: str | Path = DEFAULT_ACTIVE_POINTER,
    repo_root: str | Path = REPO_ROOT,
    now: datetime | None = None,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
    current_code_identity: Mapping[str, Any] | None = None,
    bootstrap_first_release: bool = False,
) -> dict[str, Any]:
    """Verify and atomically activate a release through one pointer file."""

    release_id = validate_release_id(release_id)
    releases_root = Path(releases_root).resolve()
    pointer_path = Path(pointer_path).resolve()
    if pointer_path.parent != releases_root:
        raise ReleaseLifecycleError("active pointer must be in the releases root for same-filesystem replacement")
    with _pointer_lock(pointer_path):
        existing = load_active_pointer(pointer_path) if pointer_path.exists() else None
        if existing and existing["active_release_id"] == release_id:
            raise ReleaseLifecycleError(f"release is already active: {release_id}")
        verified = verify_release(
            _release_dir(releases_root, release_id),
            repo_root=repo_root,
            check_runtime=True,
            current_runtime_versions=current_runtime_versions,
            current_runtime_identity=current_runtime_identity,
        )
        semantic_contract = verified.get("semantic_contract")
        release_kind = None
        if semantic_contract is not None and not semantic_contract.get("production_capable"):
            if not bootstrap_first_release:
                raise ReleaseLifecycleError(
                    "research-only release cannot be promoted to the active pointer"
                )
            if existing is not None:
                raise ReleaseLifecycleError(
                    "--bootstrap-first-release is valid only when no active pointer exists"
                )
            release_kind = SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
        manifest = verified["manifest"]
        if manifest["code"].get("git_dirty") is not False:
            raise ReleaseLifecycleError("dirty or unknown source attestations cannot be promoted")
        current_code = dict(
            current_code_identity
            if current_code_identity is not None
            else capture_code_identity(repo_root)
        )
        if current_code.get("git_dirty") is not False:
            raise ReleaseLifecycleError("current repository is dirty; promotion fails closed")
        if current_code.get("git_commit") != manifest["code"].get("git_commit"):
            raise ReleaseLifecycleError("current git commit does not match the candidate release")
        previous_id = existing["active_release_id"] if existing else None
        previous_hash = existing["active_manifest_sha256"] if existing else None
        if manifest.get("rollback_target") != previous_id:
            raise ReleaseLifecycleError(
                "candidate rollback_target must exactly match the currently active release "
                f"({previous_id!r})"
            )
        if existing:
            verify_release(
                _release_dir(releases_root, previous_id),
                expected_manifest_sha256=previous_hash,
                check_runtime=False,
            )
        decision_gate = validate_promotion_decision(
            decision,
            release_id=release_id,
            manifest_sha256=verified["manifest_sha256"],
            expected_release_kind=release_kind,
        )
        boundary_gate = validate_market_day_boundary(
            market_day_boundary,
            release_id=release_id,
            manifest_sha256=verified["manifest_sha256"],
            now=now,
        )
        previous_release_kind = active_release_kind(existing) if existing else None
        previous_release_kind_provenance = (
            existing.get("release_kind_provenance")
            if existing
            and previous_release_kind == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
            else None
        )
        pointer = _new_pointer(
            sequence=(existing["sequence"] + 1) if existing else 1,
            action="PROMOTE",
            active_release_id=release_id,
            active_manifest_sha256=verified["manifest_sha256"],
            previous_release_id=previous_id,
            previous_manifest_sha256=previous_hash,
            boundary=boundary_gate,
            decision=decision_gate,
            changed_at_utc=(now or datetime.now(timezone.utc)).isoformat(),
            release_kind=release_kind,
            previous_release_kind=previous_release_kind,
            previous_release_kind_provenance=previous_release_kind_provenance,
        )
        _write_json_atomic(pointer_path, pointer)
    return {
        "status": "PROMOTED",
        "release_id": release_id,
        "previous_release_id": previous_id,
        "pointer_path": str(pointer_path),
        "pointer_sha256": pointer["pointer_sha256"],
        "release_kind": active_release_kind(pointer),
        "restart_required": True,
    }


def rollback_release(
    *,
    market_day_boundary: Mapping[str, Any],
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    pointer_path: str | Path = DEFAULT_ACTIVE_POINTER,
    drill_record_path: str | Path = DEFAULT_ROLLBACK_DRILL,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return to the prior release, or remove a first-release pointer, with proof.

    Runtime compatibility is intentionally checked by the restarted consumer;
    rollback itself cannot assume the old release used the current code runtime.
    The drill record therefore remains pending until the coordinated worker
    restart and post-restart health proof are completed manually.  A verified
    first activation has an explicit ``NO_ACTIVE_POINTER`` target: its pointer
    is removed only after a durable intent is written, then the canonical
    serving loader must resolve the absent-pointer state successfully.
    """

    started_monotonic = time.perf_counter()
    operation_time = now or datetime.now(timezone.utc)
    if operation_time.tzinfo is None:
        raise ReleaseLifecycleError("current time must include a timezone")
    operation_time = operation_time.astimezone(timezone.utc)
    started_at_utc = operation_time.isoformat()
    releases_root = Path(releases_root).resolve()
    pointer_path = Path(pointer_path).resolve()
    if pointer_path.parent != releases_root:
        raise ReleaseLifecycleError("active pointer must be in the releases root for same-filesystem replacement")
    drill_record_path = _rollback_drill_path(
        drill_record_path,
        releases_root=releases_root,
    )
    with _pointer_lock(pointer_path):
        if not pointer_path.exists():
            rollback_intent = _load_no_pointer_rollback_intent(
                drill_record_path,
                pointer_path=pointer_path,
            )
            completed_time = (
                operation_time if now is not None else datetime.now(timezone.utc)
            )
            intent_started = _parse_utc(
                rollback_intent.get("rollback_started_at_utc"),
                field="rollback_started_at_utc",
            )
            identity_proof, drill_record = _finalize_no_pointer_rollback_drill(
                releases_root=releases_root,
                pointer_path=pointer_path,
                drill_record_path=drill_record_path,
                rollback_intent=rollback_intent,
                operation_time=completed_time,
                duration_seconds=(completed_time - intent_started).total_seconds(),
            )
            return {
                "status": "ROLLED_BACK",
                "release_id": None,
                "previous_release_id": rollback_intent[
                    "rollback_source_release_id"
                ],
                "rollback_target_state": NO_ACTIVE_POINTER_STATE,
                "pointer_path": str(pointer_path),
                "pointer_sha256": None,
                "active_pointer_present": False,
                "release_kind": None,
                "release_identity_proof": identity_proof,
                "drill_record_path": str(drill_record_path),
                "drill_status": drill_record["status"],
                "restart_required": True,
            }
        current = load_active_pointer(pointer_path)
        if current.get("action") == "ROLLBACK":
            rollback_intent = _load_rollback_drill_intent(
                drill_record_path,
                active_pointer=current,
            )
            completed_time = (
                operation_time if now is not None else datetime.now(timezone.utc)
            )
            intent_started = _parse_utc(
                rollback_intent.get("rollback_started_at_utc"),
                field="rollback_started_at_utc",
            )
            identity_proof, drill_record = _finalize_rollback_drill(
                releases_root=releases_root,
                pointer_path=pointer_path,
                drill_record_path=drill_record_path,
                active_pointer=current,
                rollback_intent=rollback_intent,
                operation_time=completed_time,
                duration_seconds=(completed_time - intent_started).total_seconds(),
            )
            pointer = current
            target_id = current["active_release_id"]
            source_release_id = current["previous_release_id"]
        else:
            target_id = current.get("previous_release_id")
            target_hash = current.get("previous_manifest_sha256")
            if not target_id or not target_hash:
                if (
                    current.get("action") != "PROMOTE"
                    or current.get("sequence") != 1
                    or target_id is not None
                    or target_hash is not None
                ):
                    raise ReleaseLifecycleError(
                        "active release pointer has no verified rollback target "
                        "and is not a first activation"
                    )
                source = verify_release(
                    _release_dir(
                        releases_root,
                        str(current["active_release_id"]),
                    ),
                    expected_manifest_sha256=str(
                        current["active_manifest_sha256"]
                    ),
                    check_runtime=False,
                )
                if (
                    source["manifest"].get("parent_release") is not None
                    or source["manifest"].get("rollback_target") is not None
                ):
                    raise ReleaseLifecycleError(
                        "first-activation pointer does not bind a null "
                        "parent/rollback target"
                    )
                boundary_gate = validate_market_day_boundary(
                    market_day_boundary,
                    release_id=str(current["active_release_id"]),
                    manifest_sha256=str(current["active_manifest_sha256"]),
                    now=now,
                )
                rollback_intent = _no_pointer_rollback_intent(
                    started_at_utc=started_at_utc,
                    source_pointer=current,
                    source=source,
                    boundary=boundary_gate,
                    pointer_path=pointer_path,
                )
                _write_json_atomic(drill_record_path, rollback_intent)
                try:
                    pointer_path.unlink()
                except OSError as exc:
                    raise ReleaseLifecycleError(
                        "no-active-pointer rollback intent was persisted, but "
                        f"the active pointer could not be removed: {exc}"
                    ) from exc
                if pointer_path.exists():
                    raise ReleaseLifecycleError(
                        "active pointer still exists after first-release deactivation"
                    )
                completed_time = (
                    operation_time
                    if now is not None
                    else datetime.now(timezone.utc)
                )
                identity_proof, drill_record = (
                    _finalize_no_pointer_rollback_drill(
                        releases_root=releases_root,
                        pointer_path=pointer_path,
                        drill_record_path=drill_record_path,
                        rollback_intent=rollback_intent,
                        operation_time=completed_time,
                        duration_seconds=time.perf_counter()
                        - started_monotonic,
                    )
                )
                return {
                    "status": "ROLLED_BACK",
                    "release_id": None,
                    "previous_release_id": current["active_release_id"],
                    "rollback_target_state": NO_ACTIVE_POINTER_STATE,
                    "pointer_path": str(pointer_path),
                    "pointer_sha256": None,
                    "active_pointer_present": False,
                    "release_kind": None,
                    "release_identity_proof": identity_proof,
                    "drill_record_path": str(drill_record_path),
                    "drill_status": drill_record["status"],
                    "restart_required": True,
                }
            if not target_id or not target_hash:
                raise ReleaseLifecycleError(
                    "active release pointer has no verified rollback target"
                )
            target = verify_release(
                _release_dir(releases_root, str(target_id)),
                expected_manifest_sha256=str(target_hash),
                check_runtime=False,
            )
            target_release_kind = (
                str(current.get("previous_release_kind") or "")
                if "previous_release_kind" in current
                else PRODUCTION_RELEASE_KIND
            )
            target_release_kind_provenance = current.get(
                "previous_release_kind_provenance"
            )
            target_semantic_contract = target.get("semantic_contract")
            target_production_capable = bool(
                target_semantic_contract
                and target_semantic_contract.get("production_capable") is True
            )
            if target_release_kind == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND:
                if target_semantic_contract is None or target_production_capable:
                    raise ReleaseLifecycleError(
                        "bootstrap rollback target is not a verified research-only release"
                    )
            elif (
                target_semantic_contract is not None
                and not target_production_capable
            ):
                raise ReleaseLifecycleError(
                    "research-only rollback target lacks serving-identity bootstrap provenance"
                )
            source_release_kind = active_release_kind(current)
            source_release_kind_provenance = current.get("release_kind_provenance")
            boundary_gate = validate_market_day_boundary(
                market_day_boundary,
                release_id=str(target_id),
                manifest_sha256=target["manifest_sha256"],
                now=now,
            )
            pointer = _new_pointer(
                sequence=current["sequence"] + 1,
                action="ROLLBACK",
                active_release_id=str(target_id),
                active_manifest_sha256=target["manifest_sha256"],
                previous_release_id=current["active_release_id"],
                previous_manifest_sha256=current["active_manifest_sha256"],
                boundary=boundary_gate,
                decision=None,
                changed_at_utc=operation_time.isoformat(),
                release_kind=target_release_kind,
                release_kind_provenance=target_release_kind_provenance,
                previous_release_kind=source_release_kind,
                previous_release_kind_provenance=source_release_kind_provenance,
            )
            rollback_intent = _rollback_drill_intent(
                started_at_utc=started_at_utc,
                source_pointer=current,
                target=target,
                planned_pointer=pointer,
            )
            _write_json_atomic(drill_record_path, rollback_intent)
            _write_json_atomic(pointer_path, pointer)
            completed_time = (
                operation_time if now is not None else datetime.now(timezone.utc)
            )
            identity_proof, drill_record = _finalize_rollback_drill(
                releases_root=releases_root,
                pointer_path=pointer_path,
                drill_record_path=drill_record_path,
                active_pointer=pointer,
                rollback_intent=rollback_intent,
                operation_time=completed_time,
                duration_seconds=time.perf_counter() - started_monotonic,
            )
            source_release_id = current["active_release_id"]
    return {
        "status": "ROLLED_BACK",
        "release_id": str(target_id),
        "previous_release_id": source_release_id,
        "pointer_path": str(pointer_path),
        "pointer_sha256": pointer["pointer_sha256"],
        "release_kind": active_release_kind(pointer),
        "release_identity_proof": identity_proof,
        "drill_record_path": str(drill_record_path),
        "drill_status": drill_record["status"],
        "restart_required": True,
    }


def resolve_active_release(
    *,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    pointer_path: str | Path = DEFAULT_ACTIVE_POINTER,
    repo_root: str | Path = REPO_ROOT,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve an active release only after complete integrity/runtime checks."""

    resolved = resolve_verified_active_release(
        pointer_path=pointer_path,
        releases_root=releases_root,
        repo_root=repo_root,
        check_runtime=True,
        current_runtime_versions=current_runtime_versions,
        current_runtime_identity=current_runtime_identity,
        require_served_bindings=False,
    )
    return {
        "status": "PASS",
        "release_id": resolved["release_id"],
        "release_dir": resolved["release_dir"],
        "manifest_path": resolved["manifest_path"],
        "manifest_sha256": resolved["manifest_sha256"],
        "pointer_sha256": resolved["pointer_sha256"],
        "sequence": resolved["sequence"],
        "release_kind": resolved["release_kind"],
        "candidate_mode": resolved["candidate_mode"],
        "production_capable": resolved["production_capable"],
        "manifest": resolved["manifest"],
    }
