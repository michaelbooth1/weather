"""Fail-closed active-release pointer promotion and rollback."""

from __future__ import annotations

import os
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
from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    load_active_release_pointer as load_active_pointer,
    pointer_content_sha256,
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
DEFAULT_ACTIVE_POINTER = DEFAULT_RELEASES_ROOT / "current_release.json"
DEFAULT_CANDIDATES_ROOT = DEFAULT_CANDIDATE_ARTIFACT_ROOT


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
    if not str(decision.get("reviewed_by") or "").strip():
        failures.append("reviewed_by is required")
    try:
        _parse_utc(decision.get("reviewed_at_utc"), field="reviewed_at_utc")
    except ReleaseLifecycleError as exc:
        failures.append(str(exc))
    if failures:
        raise ReleaseLifecycleError("promotion decision failed closed: " + "; ".join(failures))
    return {
        "status": "PASS",
        "sha256": canonical_payload_sha256(decision),
        "reviewed_by": str(decision["reviewed_by"]),
        "reviewed_at_utc": str(decision["reviewed_at_utc"]),
    }


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
        if semantic_contract is not None and not semantic_contract.get("production_capable"):
            raise ReleaseLifecycleError(
                "research-only release cannot be promoted to the active pointer"
            )
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
        )
        boundary_gate = validate_market_day_boundary(
            market_day_boundary,
            release_id=release_id,
            manifest_sha256=verified["manifest_sha256"],
            now=now,
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
        )
        _write_json_atomic(pointer_path, pointer)
    return {
        "status": "PROMOTED",
        "release_id": release_id,
        "previous_release_id": previous_id,
        "pointer_path": str(pointer_path),
        "pointer_sha256": pointer["pointer_sha256"],
        "restart_required": True,
    }


def rollback_release(
    *,
    market_day_boundary: Mapping[str, Any],
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    pointer_path: str | Path = DEFAULT_ACTIVE_POINTER,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically point back to the prior release after full hash verification.

    Runtime compatibility is intentionally checked by the restarted consumer;
    rollback itself cannot assume the old release used the current code runtime.
    """

    releases_root = Path(releases_root).resolve()
    pointer_path = Path(pointer_path).resolve()
    if pointer_path.parent != releases_root:
        raise ReleaseLifecycleError("active pointer must be in the releases root for same-filesystem replacement")
    with _pointer_lock(pointer_path):
        current = load_active_pointer(pointer_path)
        if current.get("action") == "ROLLBACK":
            raise ReleaseLifecycleError(
                "active pointer already records a rollback; refusing to toggle back to the failed release"
            )
        target_id = current.get("previous_release_id")
        target_hash = current.get("previous_manifest_sha256")
        if not target_id or not target_hash:
            raise ReleaseLifecycleError("active release pointer has no verified rollback target")
        target = verify_release(
            _release_dir(releases_root, str(target_id)),
            expected_manifest_sha256=str(target_hash),
            check_runtime=False,
        )
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
            changed_at_utc=(now or datetime.now(timezone.utc)).isoformat(),
        )
        _write_json_atomic(pointer_path, pointer)
    return {
        "status": "ROLLED_BACK",
        "release_id": str(target_id),
        "previous_release_id": current["active_release_id"],
        "pointer_path": str(pointer_path),
        "pointer_sha256": pointer["pointer_sha256"],
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

    releases_root = Path(releases_root).resolve()
    pointer = load_active_pointer(pointer_path)
    verified = verify_release(
        _release_dir(releases_root, pointer["active_release_id"]),
        repo_root=repo_root,
        expected_manifest_sha256=pointer["active_manifest_sha256"],
        check_runtime=True,
        current_runtime_versions=current_runtime_versions,
        current_runtime_identity=current_runtime_identity,
    )
    return {
        "status": "PASS",
        "release_id": pointer["active_release_id"],
        "release_dir": verified["release_dir"],
        "manifest_path": verified["manifest_path"],
        "manifest_sha256": verified["manifest_sha256"],
        "pointer_sha256": pointer["pointer_sha256"],
        "sequence": pointer["sequence"],
        "manifest": verified["manifest"],
    }
