"""Candidate-only release preparation for scheduled retraining."""

from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from weather.operations.release_manifest import (
    DEFAULT_RELEASES_ROOT,
    ReleaseLifecycleError,
    capture_code_identity,
    create_release,
    sha256_file,
    validate_release_id,
)
from weather.operations.release_candidate_contract import (
    freeze_candidate_semantic_contract,
)
from weather.operations.release_promotion import (
    DEFAULT_ACTIVE_POINTER,
    DEFAULT_CANDIDATES_ROOT,
    assert_training_output_path,
    load_active_pointer,
)
from weather.release_contract import (
    CANDIDATE_MODES,
    PRODUCTION_CANDIDATE_MODE,
    PRODUCTION_POINT_IN_TIME_ROLE_KINDS,
    RESEARCH_ONLY_CANDIDATE_MODE,
)
CANDIDATE_OUTPUTS = (
    (
        "pooled_band_artifact",
        "model/feature_model_hgb_f_pooled_v0_3.pkl",
        "model",
        "pooled_band_model",
    ),
    (
        "family_secondary_out",
        "calibration/f_family_secondary_artifacts.json",
        "calibration",
        "family_secondary_calibration",
    ),
    (
        "artifact_registry",
        "config/model_artifact_registry.json",
        "registry",
        "artifact_registry",
    ),
)


def _utc_candidate_id(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return "nightly-" + current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def prepare_candidate_outputs(args: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Resolve and guard every scheduled training/export output."""

    candidates_root = Path(getattr(args, "candidates_root", DEFAULT_CANDIDATES_ROOT)).resolve()
    releases_root = Path(getattr(args, "releases_root", DEFAULT_RELEASES_ROOT)).resolve()
    candidate_id = str(getattr(args, "candidate_id", "") or _utc_candidate_id(now))
    candidate_dir = (candidates_root / candidate_id).resolve()
    pointer_value = getattr(args, "release_pointer", "")
    pointer_path = Path(pointer_value).resolve() if pointer_value else releases_root / DEFAULT_ACTIVE_POINTER.name
    allow_legacy = bool(getattr(args, "allow_legacy_serving_output", False))
    candidate_mode = str(
        getattr(args, "release_candidate_mode", RESEARCH_ONLY_CANDIDATE_MODE)
        or RESEARCH_ONLY_CANDIDATE_MODE
    ).strip()
    args.release_candidate_mode = candidate_mode
    args.candidate_id = candidate_id
    args.candidate_dir = str(candidate_dir)
    args.candidates_root = str(candidates_root)
    args.releases_root = str(releases_root)
    args.release_pointer = str(pointer_path)

    rows = []
    failures = []
    try:
        validate_release_id(candidate_id)
    except ReleaseLifecycleError as exc:
        failures.append({"attribute": "candidate_id", "path": candidate_id, "error": str(exc)})
    if candidate_mode not in CANDIDATE_MODES:
        failures.append(
            {
                "attribute": "release_candidate_mode",
                "path": candidate_mode,
                "error": "candidate mode must be production or research_only",
            }
        )
    if pointer_path.parent != releases_root:
        failures.append(
            {
                "attribute": "release_pointer",
                "path": str(pointer_path),
                "error": "release pointer must be directly inside the releases root",
            }
        )
    for attribute, default_relative, kind, role in CANDIDATE_OUTPUTS:
        configured = getattr(args, attribute, "")
        path = Path(configured).resolve() if configured else candidate_dir / default_relative
        setattr(args, attribute, str(path))
        try:
            guard = assert_training_output_path(
                path,
                candidates_root=candidates_root,
                releases_root=releases_root,
                active_pointer=pointer_path,
                allow_legacy_serving_output=allow_legacy,
            )
            if guard["release_eligible"] and not path.is_relative_to(candidate_dir):
                raise ReleaseLifecycleError(
                    f"candidate output must stay within this run's directory {candidate_dir}: {path}"
                )
        except ReleaseLifecycleError as exc:
            failures.append({"attribute": attribute, "path": str(path), "error": str(exc)})
            guard = {"status": "BLOCK", "path": str(path), "release_eligible": False}
        rows.append(
            {
                "attribute": attribute,
                "path": str(path),
                "relative_path": default_relative,
                "kind": kind,
                "role": role,
                **guard,
            }
        )
    output_paths = [row["path"] for row in rows]
    for duplicate in sorted({path for path in output_paths if output_paths.count(path) > 1}):
        failures.append(
            {
                "attribute": "candidate_outputs",
                "path": duplicate,
                "error": "candidate output path is configured for more than one artifact role",
            }
        )
    if failures:
        status = "BLOCK"
    elif any(not row["release_eligible"] for row in rows):
        status = "QUARANTINED_LEGACY_OUTPUT"
    else:
        status = "PASS"
    return {
        "status": status,
        "candidate_id": candidate_id,
        "candidate_dir": str(candidate_dir),
        "candidates_root": str(candidates_root),
        "releases_root": str(releases_root),
        "release_pointer": str(pointer_path),
        "compatibility_flag_enabled": allow_legacy,
        "candidate_mode": candidate_mode,
        "production_capable": candidate_mode == PRODUCTION_CANDIDATE_MODE,
        "release_eligible": status == "PASS",
        "outputs": rows,
        "failures": failures,
    }


def _file_lineage(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return {"path": str(path), "exists": False, "sha256": None}
    return {"path": str(path), "exists": True, "sha256": sha256_file(path)}


def _active_parent(args: Any) -> str | None:
    pointer_path = Path(args.release_pointer)
    active_id = load_active_pointer(pointer_path)["active_release_id"] if pointer_path.exists() else None
    configured = str(getattr(args, "release_parent", "") or "").strip() or None
    if configured is not None and configured != active_id:
        raise ReleaseLifecycleError(
            f"configured release parent {configured!r} does not match active pointer {active_id!r}"
        )
    return active_id


def build_candidate_release(
    args: Any,
    *,
    promotion: Mapping[str, Any],
    candidate_guard: Mapping[str, Any],
    release_builder: Callable[..., dict[str, Any]] = create_release,
    code_identity_provider: Callable[..., dict[str, Any]] = capture_code_identity,
) -> dict[str, Any]:
    """Build an immutable, inactive release after the existing gates pass."""

    if candidate_guard.get("status") != "PASS" or not candidate_guard.get("release_eligible"):
        raise ReleaseLifecycleError("candidate output guard is not release-eligible")
    code = code_identity_provider(repo_root=args.repo_root)
    if code.get("git_dirty") is not False:
        raise ReleaseLifecycleError("nightly release build requires a clean source tree")
    parent_release = _active_parent(args)
    candidate_mode = str(
        candidate_guard.get("candidate_mode")
        or getattr(args, "release_candidate_mode", RESEARCH_ONLY_CANDIDATE_MODE)
    )
    if candidate_mode not in CANDIDATE_MODES:
        raise ReleaseLifecycleError(f"unsupported candidate mode: {candidate_mode!r}")
    point_in_time_artifacts: dict[str, str] = {}
    if candidate_mode == PRODUCTION_CANDIDATE_MODE:
        for role in PRODUCTION_POINT_IN_TIME_ROLE_KINDS:
            value = str(getattr(args, role, "") or "").strip()
            if not value:
                raise ReleaseLifecycleError(
                    f"production candidate is missing point-in-time artifact: {role}"
                )
            point_in_time_artifacts[role] = value
    candidate_dir = Path(args.candidate_dir).resolve()
    output_by_role = {}
    for row in candidate_guard.get("outputs") or []:
        path = Path(row["path"]).resolve()
        try:
            relative = path.relative_to(candidate_dir).as_posix()
        except ValueError as exc:
            raise ReleaseLifecycleError(f"candidate artifact is outside candidate directory: {path}") from exc
        output_by_role[str(row["role"])] = {**row, "relative_path": relative, "path": str(path)}
    expected_runtimes = [
        value.strip()
        for value in str(args.expected_live_runtimes).split(",")
        if value.strip()
    ]
    required_outputs = {
        "pooled_band_model",
        "family_secondary_calibration",
        "artifact_registry",
    }
    if set(output_by_role) != required_outputs:
        raise ReleaseLifecycleError(
            "candidate output guard roles are incomplete: "
            f"missing={sorted(required_outputs - set(output_by_role))}, "
            f"extra={sorted(set(output_by_role) - required_outputs)}"
        )
    semantic = freeze_candidate_semantic_contract(
        candidate_dir=candidate_dir,
        model_bundle_path=output_by_role["pooled_band_model"]["path"],
        family_secondary_path=output_by_role["family_secondary_calibration"]["path"],
        artifact_registry_path=output_by_role["artifact_registry"]["path"],
        repo_root=args.repo_root,
        candidate_id=args.candidate_id,
        parent_release=parent_release,
        promotion=promotion,
        family_unit=args.family_unit,
        candidate_mode=candidate_mode,
        point_in_time_artifacts=point_in_time_artifacts,
    )
    if semantic.get("status") != "PASS" or (semantic.get("audit") or {}).get("status") != "PASS":
        raise ReleaseLifecycleError("candidate semantic contract is not exact PASS")
    declarations = semantic["declarations"]
    route = semantic["route"]
    lineage = {
        "holdout_year": args.holdout_year,
        "quality_grades": args.quality_grades,
        "promotion_refresh": _file_lineage(args.promotion_out),
        "daily_learning": _file_lineage(args.daily_learning_out),
        "settled_day_freshness": _file_lineage(args.settled_day_freshness_out),
        "semantic_contract": _file_lineage(semantic["contract_path"]),
        "candidate_mode": candidate_mode,
        "production_capable": semantic["production_capable"],
        "candidate_input_leakage_audit": {
            "status": semantic["audit"]["status"],
            "sha256": sha256_file(
                candidate_dir / "contract" / "candidate_input_leakage_audit.json"
            ),
            "rejection_count": semantic["audit"]["rejection_count"],
        },
    }
    pointer_path = Path(args.release_pointer)
    pointer_before = sha256_file(pointer_path) if pointer_path.exists() else None
    result = release_builder(
        release_id=args.candidate_id,
        candidate_dir=candidate_dir,
        declarations=declarations,
        route=route,
        expected_live_runtimes=expected_runtimes,
        releases_root=args.releases_root,
        repo_root=args.repo_root,
        parent_release=parent_release,
        rollback_target=parent_release,
        lineage=lineage,
        code_identity=code,
    )
    pointer_after = sha256_file(pointer_path) if pointer_path.exists() else None
    if pointer_after != pointer_before:
        raise ReleaseLifecycleError("candidate release build unexpectedly changed the active pointer")
    return {
        **result,
        "activation": "MANUAL_POINTER_ONLY",
        "promotion_eligibility": (
            "ELIGIBLE_FOR_GATED_PROMOTION"
            if candidate_mode == PRODUCTION_CANDIDATE_MODE
            else "BLOCKED_RESEARCH_ONLY"
        ),
        "candidate_mode": candidate_mode,
        "production_capable": semantic["production_capable"],
        "active_pointer_unchanged": True,
        "active_release_id": parent_release,
    }


def run_candidate_release_step(
    args: Any,
    *,
    promotion: Mapping[str, Any],
    candidate_guard: Mapping[str, Any],
    release_builder: Callable[..., dict[str, Any]] = create_release,
    code_identity_provider: Callable[..., dict[str, Any]] = capture_code_identity,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.time()
    step = {
        "name": "candidate_release_build",
        "command": ["internal", "build_immutable_candidate_release", args.candidate_id],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "finished_at_utc": None,
        "duration_seconds": None,
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    result: dict[str, Any] = {}
    try:
        result = build_candidate_release(
            args,
            promotion=promotion,
            candidate_guard=candidate_guard,
            release_builder=release_builder,
            code_identity_provider=code_identity_provider,
        )
        step["status"] = "ok"
        step["returncode"] = 0
        step["stdout"] = f"immutable inactive release created: {result.get('release_id')}"
    except Exception as exc:  # noqa: BLE001 - lifecycle step must become fail-closed evidence
        step["status"] = "error"
        step["returncode"] = -1
        step["stderr"] = f"{type(exc).__name__}: {exc}"
        step["traceback"] = traceback.format_exc()
        result = {"status": "BLOCK", "error": str(exc), "activation": "NONE"}
    step["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    step["duration_seconds"] = round(time.time() - started, 3)
    return step, result
