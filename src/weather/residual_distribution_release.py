"""Neutral immutable, inactive release construction for ResidualDistributionV1.

This module is intentionally separate from training.  Phase one accepts only
an offline-qualified candidate and freezes its exact evidence graph into an
inactive immutable release.  Phase two verifies parity and forward streaming
against that exact release and writes an external self-hashed attestation.
The generic release primitive supplies write-once copying and manifest hashes;
the verifiers here add ResidualDistributionV1-specific cross-file checks.

Neither the builder nor verifier writes an active-release pointer.
"""

from __future__ import annotations

import json
import os
import pickle
import re
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from weather.calibration.residual_distribution_lock import verify_preselection_lock
from weather.calibration.residual_distribution_corpus import MANIFEST_SCHEMA_VERSION
from weather.calibration.residual_distribution_v1 import (
    verify_artifact_training_receipts,
)
from weather.calibration.residual_distribution_stress import (
    SCHEMA_VERSION as STRESS_SCHEMA_VERSION,
)
from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.model.residual_distribution_v1 import (
    PREDICTION_MODE,
    validate_artifact,
)
from weather.operations.release_manifest import (
    DEFAULT_RELEASES_ROOT,
    ReleaseLifecycleError,
    create_release,
    sha256_file,
    validate_release_id,
)
from weather.paths import REPO_ROOT
from weather.model_stage_retirement import (
    ABLATION_HASH_FIELD,
    ABLATION_SCHEMA_VERSION,
    REGISTER_HASH_FIELD,
    REGISTER_SCHEMA_VERSION,
    verify_stage_retirement_register,
)
from weather.release_artifacts import (
    canonical_payload_sha256,
    validate_code_runtime_alignment,
    verify_release,
)
from weather.reporting.validation.point_in_time_evaluation import (
    verify_streaming_evaluation_payload,
)


RELEASE_CONFIG_SCHEMA_VERSION = "residual_distribution_v1_release_config_v1"
RELEASE_CONFIG_HASH_FIELD = "config_snapshot_sha256"
FORWARD_ATTESTATION_SCHEMA_VERSION = (
    "residual_distribution_v1_forward_attestation_v1"
)
FORWARD_ATTESTATION_HASH_FIELD = "attestation_sha256"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ROLE_PATH_KINDS = {
    "residual_distribution_v1_model": ("model/model.pkl", "model"),
    "residual_distribution_v1_requalification": (
        "evidence/requalification.json",
        "audit",
    ),
    "residual_distribution_v1_corpus_manifest": (
        "evidence/corpus_manifest.json",
        "corpus",
    ),
    "residual_distribution_v1_preselection_lock": (
        "evidence/preselection_lock.json",
        "contract",
    ),
    "served_calibration_stage_ablation": (
        "evidence/served_calibration_stage_ablation.json",
        "audit",
    ),
    "weather_model_stage_retirement_register": (
        "evidence/stage_retirement_register.json",
        "audit",
    ),
    "residual_distribution_stress_evaluation": (
        "evidence/residual_distribution_stress.json",
        "audit",
    ),
    "model_variant_registry": ("config/model_variant_registry.json", "registry"),
    "residual_distribution_v1_release_config": (
        "config/residual_distribution_v1_release_config.json",
        "config",
    ),
}

SOURCE_INPUT_ROLES = (
    "residual_distribution_v1_model",
    "residual_distribution_v1_requalification",
    "residual_distribution_v1_corpus_manifest",
    "residual_distribution_v1_preselection_lock",
    "served_calibration_stage_ablation",
    "weather_model_stage_retirement_register",
    "residual_distribution_stress_evaluation",
    "model_variant_registry",
)

REQUIRED_OFFLINE_QUALIFICATION_CRITERIA = frozenset(
    {
        "nested_requalification_pass",
        "all_nested_criteria_pass",
        "minimum_outer_fleet_dates",
        "preselection_lock_registered_before_evaluation",
        "corpus_manifest_verified",
        "corpus_manifest_input_contract_pass",
        "preselection_lock_binds_corpus_manifest",
        "minimum_locked_fleet_dates",
        "locked_window_pass",
        "development_fleet_coverage_complete",
        "locked_fleet_coverage_complete",
        "all_rows_release_bound_and_countable",
        "singular_nonmissing_release_id",
        "singular_nonmissing_runtime_identity",
        "source_health_rows_match_serving_permission",
        "output_bound_training_receipts_verified",
    }
)

REQUIRED_FORWARD_QUALIFICATION_CRITERIA = frozenset(
    {
        "live_replay_parity_pass",
        "release_bound_forward_streaming_pass",
    }
)

REQUIRED_QUALIFICATION_CRITERIA = frozenset(
    REQUIRED_OFFLINE_QUALIFICATION_CRITERIA
    | REQUIRED_FORWARD_QUALIFICATION_CRITERIA
)

REQUIRED_CORPUS_CRITERIA = frozenset(
    {
        "all_rows_release_bound_and_countable",
        "singular_nonmissing_release_id",
        "singular_nonmissing_runtime_identity",
        "required_input_lineage_complete",
    }
)


class ResidualDistributionReleaseError(ReleaseLifecycleError):
    """The V1 candidate release evidence graph is incomplete or inconsistent."""


def _fail(message: str) -> None:
    raise ResidualDistributionReleaseError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        _fail(f"{field} must be a SHA-256 hex digest")
    return text


def _regular_file(path: str | Path, role: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.exists() or not candidate.is_file():
        _fail(f"{role} evidence file is missing or invalid: {candidate}")
    return candidate.resolve()


def _json_mapping(path: str | Path, role: str) -> dict[str, Any]:
    source = _regular_file(path, role)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResidualDistributionReleaseError(
            f"{role} evidence is not valid JSON: {source}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        _fail(f"{role} evidence must be a JSON object")
    return dict(payload)


def _load_artifact(path: str | Path) -> dict[str, Any]:
    source = _regular_file(path, "residual_distribution_v1_model")
    try:
        with source.open("rb") as handle:
            payload = pickle.load(handle)
        validated = validate_artifact(payload)
        verify_artifact_training_receipts(validated)
        return validated
    except Exception as exc:
        raise ResidualDistributionReleaseError(
            f"ResidualDistributionV1 artifact is invalid: {type(exc).__name__}: {exc}"
        ) from exc


def _exact_pass_criteria(
    payload: Any,
    *,
    required: frozenset[str],
    field: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        _fail(f"{field} must be a criteria object")
    criteria = dict(payload)
    missing = sorted(required - set(criteria))
    if missing:
        _fail(f"{field} is missing required criteria: {missing}")
    failed = sorted(key for key, value in criteria.items() if value is not True)
    if failed:
        _fail(f"{field} is not exact PASS: {failed}")
    return criteria


def _exact_offline_criteria(payload: Any, *, field: str) -> dict[str, Any]:
    """Require phase-one criteria true and phase-two criteria still false."""

    if not isinstance(payload, Mapping):
        _fail(f"{field} must be a criteria object")
    criteria = dict(payload)
    missing = sorted(REQUIRED_QUALIFICATION_CRITERIA - set(criteria))
    if missing:
        _fail(f"{field} is missing required criteria: {missing}")
    failed_offline = sorted(
        key
        for key in REQUIRED_OFFLINE_QUALIFICATION_CRITERIA
        if criteria.get(key) is not True
    )
    if failed_offline:
        _fail(f"{field} is not exact offline PASS: {failed_offline}")
    premature_forward = sorted(
        key
        for key in REQUIRED_FORWARD_QUALIFICATION_CRITERIA
        if criteria.get(key) is not False
    )
    if premature_forward:
        _fail(
            f"{field} contains forward evidence before the immutable release exists: "
            f"{premature_forward}"
        )
    unexpected_failures = sorted(
        key
        for key, value in criteria.items()
        if key not in REQUIRED_FORWARD_QUALIFICATION_CRITERIA and value is not True
    )
    if unexpected_failures:
        _fail(f"{field} has failed offline criteria: {unexpected_failures}")
    return criteria


def _status_pass(payload: Mapping[str, Any], field: str) -> None:
    _require(payload.get("status") == "PASS", f"{field} is not exact PASS")


def _named_candidate(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("candidate_id")
        or payload.get("variant_id")
        or payload.get("model_version")
        or ""
    ).strip()


def _canonical_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_json(left) == canonical_json(right)
    except (TypeError, ValueError):
        return False


def _parse_utc(value: Any, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResidualDistributionReleaseError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _verify_self_hash(payload: Mapping[str, Any], field: str, description: str) -> str:
    expected = finalize_self_hash(
        {key: value for key, value in payload.items() if key != field},
        hash_field=field,
    )
    actual = _sha256(payload.get(field), f"{description}.{field}")
    _require(actual == expected.get(field), f"{description} self-hash mismatch")
    return actual


def _verify_parity(
    payload: Mapping[str, Any],
    *,
    candidate_id: str,
    release_id: str,
    manifest_sha256: str,
    artifact_sha256: str,
) -> None:
    _status_pass(payload, "live/replay parity evidence")
    _verify_self_hash(payload, "parity_sha256", "live/replay parity evidence")
    _require(
        payload.get("mode") == "captured_input_replay_vs_served_parity",
        "live/replay parity mode mismatch",
    )
    _require(
        payload.get("release_id") == release_id,
        "live/replay parity release_id mismatch",
    )
    _require(
        payload.get("manifest_sha256") == manifest_sha256,
        "live/replay parity manifest_sha256 mismatch",
    )
    _require(
        payload.get("candidate_id") == candidate_id,
        "live/replay parity candidate_id mismatch",
    )
    _require(
        payload.get("candidate_artifact_sha256") == artifact_sha256,
        "live/replay parity candidate artifact hash mismatch",
    )
    candidate_ids = {
        str(value)
        for value in payload.get("candidate_ids") or payload.get("variant_ids") or []
        if str(value)
    }
    named_candidate = _named_candidate(payload)
    if named_candidate:
        candidate_ids.add(named_candidate)
    _require(
        candidate_id in candidate_ids,
        "live/replay parity does not include the released candidate",
    )
    artifact_hashes = {
        str(value).lower()
        for value in payload.get("artifact_sha256s") or []
        if str(value)
    }
    _require(
        artifact_sha256.lower() in artifact_hashes,
        "live/replay parity does not include the released artifact hash",
    )
    coverage_contract = payload.get("coverage_contract")
    _require(
        isinstance(coverage_contract, Mapping)
        and coverage_contract.get("status") == "PASS"
        and coverage_contract.get("candidate_id") == candidate_id
        and bool(coverage_contract.get("expected_market_ids"))
        and bool(coverage_contract.get("expected_branch_scenarios"))
        and bool(coverage_contract.get("expected_band_count_by_market"))
        and not coverage_contract.get("missing_market_branch_pairs")
        and not coverage_contract.get("unexpected_market_branch_pairs")
        and int(coverage_contract.get("missing_branch_scenario_row_count") or 0)
        == 0
        and all(
            value is True
            for value in (coverage_contract.get("checks") or {}).values()
        ),
        "live/replay parity coverage contract is not exhaustive PASS",
    )
    summary = payload.get("summary") or {}
    inputs = payload.get("inputs") or {}
    mismatch_count = int(payload.get("mismatch_count") or summary.get("mismatch_count") or 0)
    served_rows = int(inputs.get("served_row_count") or 0)
    replay_rows = int(inputs.get("replay_row_count") or 0)
    compared_rows = int(summary.get("compared_row_count") or 0)
    _require(mismatch_count == 0, "live/replay parity contains mismatches")
    _require(
        served_rows > 0 and served_rows == replay_rows == compared_rows,
        "live/replay parity row coverage is not complete",
    )


def _verify_streaming(
    payload: Mapping[str, Any],
    *,
    candidate_id: str,
    minimum_dates: int,
    release_id: str,
    manifest_sha256: str,
    artifact_sha256: str,
) -> None:
    try:
        verify_streaming_evaluation_payload(
            payload,
            expected_candidate_id=candidate_id,
            expected_release_id=release_id,
            expected_manifest_sha256=manifest_sha256,
            expected_candidate_artifact_sha256=artifact_sha256,
            require_production_window=True,
        )
    except Exception as exc:
        raise ResidualDistributionReleaseError(
            "point-in-time streaming evidence failed canonical verification: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    _status_pass(payload, "point-in-time streaming evidence")
    _require(
        _named_candidate(payload) == candidate_id,
        "point-in-time streaming candidate_id mismatch",
    )
    _require(
        payload.get("release_id") == release_id,
        "point-in-time streaming release_id mismatch",
    )
    _require(
        payload.get("manifest_sha256") == manifest_sha256,
        "point-in-time streaming manifest_sha256 mismatch",
    )
    _require(
        payload.get("candidate_artifact_sha256") == artifact_sha256,
        "point-in-time streaming candidate artifact hash mismatch",
    )
    counts = payload.get("counts") or {}
    complete_dates = int(
        payload.get("complete_fleet_dates")
        or counts.get("complete_fleet_dates")
        or counts.get("fleet_dates")
        or counts.get("target_dates")
        or 0
    )
    unsupported = int(
        payload.get("unsupported_runtime_skips")
        or counts.get("unsupported_runtime_skips")
        or 0
    )
    runtime_identities = list(payload.get("runtime_identities") or [])
    identity_count = int(payload.get("runtime_identity_count") or len(runtime_identities))
    input_rows = int(counts.get("input_rows") or 0)
    window_rows = int(counts.get("window_rows") or 0)
    outside_rows = int(counts.get("outside_window_rows") or 0)
    excluded_rows = int(counts.get("excluded_rows") or 0)
    excluded_cutoffs = int(counts.get("excluded_cutoffs") or 0)
    window_lock = payload.get("window_lock") or {}
    locked_dates = list(window_lock.get("target_dates") or [])
    _require(
        complete_dates >= int(minimum_dates),
        "point-in-time streaming evidence has too few complete fleet dates",
    )
    _require(unsupported == 0, "point-in-time streaming evidence has unsupported skips")
    _require(identity_count == 1, "point-in-time streaming runtime identity is not singular")
    _require(
        input_rows > 0
        and input_rows == window_rows
        and outside_rows == 0
        and excluded_rows == 0
        and excluded_cutoffs == 0,
        "point-in-time streaming eligible row coverage is not complete",
    )
    _require(
        len(set(locked_dates)) >= int(minimum_dates),
        "point-in-time streaming lock has too few fleet dates",
    )
    _require(
        not window_lock.get("status") or window_lock.get("status") == "PASS",
        "point-in-time streaming window lock is not PASS",
    )


def _registry_entry(registry: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in registry.get("variants") or []
        if isinstance(row, Mapping) and str(row.get("variant_id") or "") == candidate_id
    ]
    _require(len(rows) == 1, "model registry must contain exactly one candidate entry")
    entry = rows[0]
    _require(entry.get("prediction_mode") == PREDICTION_MODE, "registry prediction_mode mismatch")
    _require(entry.get("live_runtime") == PREDICTION_MODE, "registry live_runtime mismatch")
    _require(entry.get("lifecycle") == "shadow", "registry candidate must remain shadow")
    for field in (
        "active_for_headline",
        "live_capture_enabled",
        "counts_toward_weather_model_promotion",
    ):
        _require(entry.get(field) is False, f"registry {field} must remain false")
    return entry


def _input_paths(
    *,
    artifact_path: str | Path,
    requalification_report_path: str | Path,
    corpus_manifest_path: str | Path,
    preselection_lock_path: str | Path,
    served_calibration_stage_ablation_path: str | Path,
    stage_retirement_register_path: str | Path,
    stress_report_path: str | Path,
    model_registry_path: str | Path,
) -> dict[str, Path]:
    configured = {
        "residual_distribution_v1_model": artifact_path,
        "residual_distribution_v1_requalification": requalification_report_path,
        "residual_distribution_v1_corpus_manifest": corpus_manifest_path,
        "residual_distribution_v1_preselection_lock": preselection_lock_path,
        "served_calibration_stage_ablation": served_calibration_stage_ablation_path,
        "weather_model_stage_retirement_register": stage_retirement_register_path,
        "residual_distribution_stress_evaluation": stress_report_path,
        "model_variant_registry": model_registry_path,
    }
    return {role: _regular_file(path, role) for role, path in configured.items()}


def _validate_evidence_graph(
    paths: Mapping[str, Path],
    *,
    release_id: str,
    rollback_target: str,
    code_identity: Mapping[str, Any],
    runtime_versions: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    repo_root: str | Path = REPO_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    release_id = validate_release_id(release_id)
    rollback_target = validate_release_id(rollback_target)
    _require(rollback_target != release_id, "rollback_target must differ from release_id")

    code = dict(code_identity)
    versions = dict(runtime_versions)
    identity = dict(runtime_identity)
    _require(code.get("git_dirty") is False, "candidate release requires clean code identity")
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40,64}", str(code.get("git_commit") or ""))),
        "code identity git_commit is invalid",
    )
    _require(bool(str(code.get("git_branch") or "").strip()), "code identity git_branch is missing")
    _require(code.get("dirty_fingerprint") is None, "clean code identity has a dirty fingerprint")
    _require(
        bool(versions.get("python")) and bool(versions.get("implementation")),
        "runtime_versions is missing Python identity",
    )
    dependencies = versions.get("direct_dependencies")
    _require(
        isinstance(dependencies, Mapping) and "scikit-learn" in dependencies,
        "runtime_versions is missing scikit-learn",
    )
    incomplete_dependencies = sorted(
        str(name)
        for name, row in (dependencies or {}).items()
        if not isinstance(row, Mapping) or not row.get("version") or not row.get("declared")
    )
    _require(
        not incomplete_dependencies,
        f"runtime_versions has incomplete dependencies: {incomplete_dependencies}",
    )
    _require(bool(identity.get("source_fingerprint")), "runtime identity is missing source_fingerprint")
    try:
        validate_code_runtime_alignment(code, identity)
    except Exception as exc:
        raise ResidualDistributionReleaseError(
            f"code/runtime identity mismatch: {exc}"
        ) from exc
    identity.update(
        {
            "git_commit": code["git_commit"],
            "git_branch": code["git_branch"],
            "git_dirty": code["git_dirty"],
            "dirty_fingerprint": code["dirty_fingerprint"],
        }
    )

    artifact = _load_artifact(paths["residual_distribution_v1_model"])
    candidate_id = str(artifact.get("candidate_id") or "").strip()
    _require(bool(candidate_id), "artifact candidate_id is required")
    artifact_qualification = artifact.get("qualification")
    _require(isinstance(artifact_qualification, Mapping), "artifact qualification is missing")
    _require(
        artifact_qualification.get("status") == "OFFLINE_PASS"
        and artifact_qualification.get("offline_status") == "PASS"
        and artifact_qualification.get("forward_status") == "BLOCK",
        "artifact is not exact two-phase OFFLINE_PASS",
    )
    artifact_criteria = _exact_offline_criteria(
        artifact_qualification.get("criteria"),
        field="artifact qualification criteria",
    )

    report = _json_mapping(
        paths["residual_distribution_v1_requalification"],
        "residual_distribution_v1_requalification",
    )
    _require(report.get("status") == "OFFLINE_PASS", "requalification report is not OFFLINE_PASS")
    _require(report.get("candidate_id") == candidate_id, "requalification candidate_id mismatch")
    report_qualification = report.get("qualification")
    _require(isinstance(report_qualification, Mapping), "requalification qualification is missing")
    _require(
        report_qualification.get("status") == "OFFLINE_PASS"
        and report_qualification.get("offline_status") == "PASS"
        and report_qualification.get("forward_status") == "BLOCK",
        "requalification qualification is not exact two-phase OFFLINE_PASS",
    )
    report_criteria = _exact_offline_criteria(
        report_qualification.get("criteria"),
        field="requalification criteria",
    )
    _require(
        _canonical_equal(artifact_criteria, report_criteria),
        "artifact and requalification criteria mismatch",
    )
    artifact_sha = sha256_file(paths["residual_distribution_v1_model"])
    candidate_artifact = report.get("candidate_artifact")
    _require(isinstance(candidate_artifact, Mapping), "report candidate_artifact receipt is missing")
    _require(
        candidate_artifact.get("sha256") == artifact_sha,
        "requalification artifact hash mismatch",
    )
    _require(
        candidate_artifact.get("qualification_status") == "OFFLINE_PASS"
        and candidate_artifact.get("offline_qualification_status") == "PASS"
        and candidate_artifact.get("forward_qualification_status") == "BLOCK",
        "requalification artifact receipt is not exact OFFLINE_PASS",
    )
    _require(
        candidate_artifact.get("candidate_release_eligible") is True
        and candidate_artifact.get("promotion_eligible") is False,
        "offline-qualified artifact must not be promotion eligible",
    )
    requalification_sha = sha256_file(
        paths["residual_distribution_v1_requalification"]
    )
    ablation = _json_mapping(
        paths["served_calibration_stage_ablation"],
        "served calibration/stage ablation",
    )
    _require(
        ablation.get("schema_version") == ABLATION_SCHEMA_VERSION
        and ablation.get("artifact_type") == "served_calibration_stage_ablation"
        and ablation.get("status") == "PASS",
        "served calibration/stage ablation is not exact PASS",
    )
    _verify_self_hash(
        ablation,
        ABLATION_HASH_FIELD,
        "served calibration/stage ablation",
    )
    _require(
        ablation.get("candidate_id") == candidate_id
        and ablation.get("candidate_artifact_sha256") == artifact_sha
        and ablation.get("requalification_report_sha256")
        == requalification_sha,
        "served calibration/stage ablation binding mismatch",
    )
    register = _json_mapping(
        paths["weather_model_stage_retirement_register"],
        "stage retirement register",
    )
    _require(
        register.get("schema_version") == REGISTER_SCHEMA_VERSION,
        "stage retirement register schema mismatch",
    )
    _verify_self_hash(
        register,
        REGISTER_HASH_FIELD,
        "stage retirement register",
    )
    try:
        verified_register = verify_stage_retirement_register(
            register,
            paths["residual_distribution_v1_requalification"],
            paths["served_calibration_stage_ablation"],
            repo_root=repo_root,
        )
    except Exception as exc:
        raise ResidualDistributionReleaseError(
            "stage retirement register failed bound verification: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    _require(
        verified_register.get("status") == "PASS"
        and verified_register.get("retirement_permission")
        == "AUTHORIZED_BY_EVIDENCE_REGISTER"
        and verified_register.get("mutation_performed") is False,
        "stage retirement selection evidence is not exact PASS",
    )
    stress = _json_mapping(
        paths["residual_distribution_stress_evaluation"],
        "residual distribution stress evaluation",
    )
    _require(
        stress.get("schema_version") == STRESS_SCHEMA_VERSION
        and stress.get("status") == "PASS",
        "residual distribution stress evaluation is not exact PASS",
    )
    _verify_self_hash(
        stress,
        "report_sha256",
        "residual distribution stress evaluation",
    )
    stress_statuses = stress.get("control_statuses")
    stress_required = list((stress.get("criteria") or {}).get("required_controls") or [])
    _require(
        stress.get("candidate_id") == candidate_id
        and stress.get("candidate_artifact_sha256") == artifact_sha
        and stress.get("requalification_report_sha256")
        == requalification_sha
        and isinstance(stress_statuses, Mapping)
        and bool(stress_required)
        and all(stress_statuses.get(name) == "PASS" for name in stress_required)
        and all(value != "BLOCK" for value in stress_statuses.values()),
        "residual distribution stress evaluation binding mismatch",
    )

    corpus = _json_mapping(
        paths["residual_distribution_v1_corpus_manifest"],
        "residual_distribution_v1_corpus_manifest",
    )
    _require(corpus.get("schema_version") == MANIFEST_SCHEMA_VERSION, "corpus manifest schema mismatch")
    manifest_sha = _verify_self_hash(corpus, "manifest_sha256", "corpus manifest")
    corpus_sha = _sha256(corpus.get("corpus_sha256"), "corpus_manifest.corpus_sha256")
    corpus_contract = corpus.get("qualification_input_contract")
    _require(isinstance(corpus_contract, Mapping), "corpus qualification input contract is missing")
    _status_pass(corpus_contract, "corpus qualification input contract")
    _exact_pass_criteria(
        corpus_contract.get("criteria"),
        required=REQUIRED_CORPUS_CRITERIA,
        field="corpus qualification input criteria",
    )
    _require(
        int((corpus.get("counts") or {}).get("accepted_rows") or 0) > 0,
        "corpus manifest contains no accepted rows",
    )

    lock_payload = _json_mapping(
        paths["residual_distribution_v1_preselection_lock"],
        "residual_distribution_v1_preselection_lock",
    )
    try:
        lock = verify_preselection_lock(lock_payload)
    except Exception as exc:
        raise ResidualDistributionReleaseError(
            f"preselection lock is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    _require(lock.get("candidate_id") == candidate_id, "preselection lock candidate mismatch")
    _require(lock.get("corpus_sha256") == corpus_sha, "preselection lock corpus hash mismatch")
    _require(
        lock.get("corpus_manifest_sha256") == manifest_sha,
        "preselection lock corpus manifest hash mismatch",
    )

    training_lineage = artifact.get("training_lineage")
    _require(isinstance(training_lineage, Mapping), "artifact training_lineage is missing")
    _require(
        training_lineage.get("full_corpus_sha256") == corpus_sha,
        "artifact training corpus hash mismatch",
    )
    _require(
        training_lineage.get("corpus_manifest_sha256") == manifest_sha,
        "artifact corpus manifest hash mismatch",
    )
    _require(
        _canonical_equal(training_lineage.get("preselection_lock"), lock),
        "artifact preselection lock mismatch",
    )
    locked_dates = list(lock.get("locked_dates") or [])
    _require(
        sorted(training_lineage.get("locked_dates") or []) == locked_dates,
        "artifact locked dates mismatch",
    )

    _require(report.get("corpus_sha256") == corpus_sha, "report corpus hash mismatch")
    _require(
        report_qualification.get("corpus_manifest_sha256") == manifest_sha,
        "report corpus manifest hash mismatch",
    )
    _require(
        _canonical_equal(report_qualification.get("preselection_lock"), lock),
        "report preselection lock mismatch",
    )
    _require(sorted(report.get("locked_dates") or []) == locked_dates, "report locked dates mismatch")
    locked_at = _parse_utc(lock.get("created_at_utc"), "preselection_lock.created_at_utc")
    evaluated_at = _parse_utc(report.get("generated_at_utc"), "report.generated_at_utc")
    _require(locked_at < evaluated_at, "preselection lock was not recorded before evaluation")

    registry = _json_mapping(paths["model_variant_registry"], "model_variant_registry")
    registry_entry = _registry_entry(registry, candidate_id)
    evidence_hashes = {role: sha256_file(path) for role, path in sorted(paths.items())}
    snapshot = finalize_self_hash(
        {
            "schema_version": RELEASE_CONFIG_SCHEMA_VERSION,
            "artifact_type": "residual_distribution_v1_release_config",
            "release_id": release_id,
            "candidate_id": candidate_id,
            "prediction_mode": PREDICTION_MODE,
            "live_runtime": PREDICTION_MODE,
            "qualification_status": "OFFLINE_PASS",
            "forward_evidence_status": "PENDING_EXTERNAL_ATTESTATION",
            "activation": "MANUAL_POINTER_ONLY",
            "active_for_headline": False,
            "live_capture_enabled": False,
            "counts_toward_weather_model_promotion": False,
            "rollback_target": rollback_target,
            "registry_entry": registry_entry,
            "evidence_sha256": evidence_hashes,
            "code_identity_sha256": canonical_payload_sha256(code),
            "runtime_versions_sha256": canonical_payload_sha256(versions),
            "runtime_identity_sha256": canonical_payload_sha256(identity),
        },
        hash_field=RELEASE_CONFIG_HASH_FIELD,
    )
    summary = {
        "candidate_id": candidate_id,
        "artifact_sha256": artifact_sha,
        "corpus_sha256": corpus_sha,
        "corpus_manifest_sha256": manifest_sha,
        "preselection_lock_sha256": lock["lock_sha256"],
        "qualification_criteria_count": len(artifact_criteria),
        "evidence_sha256": evidence_hashes,
    }
    return summary, snapshot


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ResidualDistributionReleaseError(f"candidate bundle path already exists: {path}") from exc


def _pointer_state(path: Path) -> tuple[bool, str | None]:
    return (path.exists(), sha256_file(path) if path.exists() and path.is_file() else None)


def build_residual_distribution_v1_candidate_release(
    *,
    release_id: str,
    candidate_bundle_dir: str | Path,
    artifact_path: str | Path,
    requalification_report_path: str | Path,
    corpus_manifest_path: str | Path,
    preselection_lock_path: str | Path,
    served_calibration_stage_ablation_path: str | Path,
    stage_retirement_register_path: str | Path,
    stress_report_path: str | Path,
    model_registry_path: str | Path,
    rollback_target: str,
    code_identity: Mapping[str, Any],
    runtime_versions: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    active_pointer_path: str | Path | None = None,
    repo_root: str | Path = REPO_ROOT,
    created_at_utc: str | None = None,
    release_builder: Callable[..., dict[str, Any]] = create_release,
) -> dict[str, Any]:
    """Freeze exact offline-PASS evidence before any forward run exists."""

    release_id = validate_release_id(release_id)
    rollback_target = validate_release_id(rollback_target)
    sources = _input_paths(
        artifact_path=artifact_path,
        requalification_report_path=requalification_report_path,
        corpus_manifest_path=corpus_manifest_path,
        preselection_lock_path=preselection_lock_path,
        served_calibration_stage_ablation_path=served_calibration_stage_ablation_path,
        stage_retirement_register_path=stage_retirement_register_path,
        stress_report_path=stress_report_path,
        model_registry_path=model_registry_path,
    )
    summary, snapshot = _validate_evidence_graph(
        sources,
        release_id=release_id,
        rollback_target=rollback_target,
        code_identity=code_identity,
        runtime_versions=runtime_versions,
        runtime_identity=runtime_identity,
        repo_root=repo_root,
    )

    releases_root = Path(releases_root).resolve()
    bundle_dir = Path(candidate_bundle_dir).resolve()
    try:
        bundle_dir.relative_to(releases_root)
    except ValueError:
        pass
    else:
        _fail("candidate bundle directory cannot be inside the immutable releases root")
    if bundle_dir.exists():
        _fail(f"candidate bundle directory already exists: {bundle_dir}")

    pointer = Path(active_pointer_path).resolve() if active_pointer_path else releases_root / "current_release.json"
    pointer_before = _pointer_state(pointer)
    staged = False
    try:
        bundle_dir.mkdir(parents=True, exist_ok=False)
        staged = True
        for role in SOURCE_INPUT_ROLES:
            relative, _kind = ROLE_PATH_KINDS[role]
            destination = bundle_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sources[role], destination, follow_symlinks=False)
            _require(
                sha256_file(destination) == summary["evidence_sha256"][role],
                f"source evidence changed while staging role {role}",
            )
        config_relative, _kind = ROLE_PATH_KINDS["residual_distribution_v1_release_config"]
        _write_json_exclusive(bundle_dir / config_relative, snapshot)
    except Exception:
        if staged:
            shutil.rmtree(bundle_dir, ignore_errors=True)
        raise

    declarations = [
        {"role": role, "path": relative, "kind": kind}
        for role, (relative, kind) in ROLE_PATH_KINDS.items()
    ]
    route = {
        "candidate_release_id": release_id,
        "candidate_id": summary["candidate_id"],
        "prediction_mode": PREDICTION_MODE,
        "live_runtime": PREDICTION_MODE,
        "activation": "MANUAL_POINTER_ONLY",
        "active_for_headline": False,
        "live_capture_enabled": False,
        "counts_toward_weather_model_promotion": False,
    }
    result = release_builder(
        release_id=release_id,
        candidate_dir=bundle_dir,
        declarations=declarations,
        route=route,
        expected_live_runtimes=[PREDICTION_MODE],
        releases_root=releases_root,
        repo_root=repo_root,
        parent_release=rollback_target,
        rollback_target=rollback_target,
        lineage={
            "artifact_family": PREDICTION_MODE,
            "qualification_status": "OFFLINE_PASS",
            "forward_evidence_status": "PENDING_EXTERNAL_ATTESTATION",
            "release_config_sha256": snapshot[RELEASE_CONFIG_HASH_FIELD],
            **summary,
        },
        code_identity=code_identity,
        runtime_versions=runtime_versions,
        runtime_identity=runtime_identity,
        created_at_utc=created_at_utc,
    )
    pointer_after = _pointer_state(pointer)
    _require(pointer_after == pointer_before, "candidate release build changed current_release.json")
    verified = verify_residual_distribution_v1_release(result["release_dir"], check_runtime=False)
    return {
        **result,
        "activation": "MANUAL_POINTER_ONLY",
        "active_pointer_unchanged": True,
        "qualification_status": "OFFLINE_PASS",
        "forward_evidence_status": "PENDING_EXTERNAL_ATTESTATION",
        "candidate_id": summary["candidate_id"],
        "rollback_target": rollback_target,
        "verification_status": verified["status"],
    }


def run_residual_distribution_v1_candidate_release(**kwargs: Any) -> dict[str, Any]:
    """Fail-closed wrapper used by automation and focused evidence tests."""

    pointer_value = kwargs.get("active_pointer_path")
    releases_value = kwargs.get("releases_root", DEFAULT_RELEASES_ROOT)
    pointer = (
        Path(pointer_value).resolve()
        if pointer_value
        else Path(releases_value).resolve() / "current_release.json"
    )
    before = _pointer_state(pointer)
    try:
        return build_residual_distribution_v1_candidate_release(**kwargs)
    except Exception as exc:  # noqa: BLE001 - release automation must emit BLOCK evidence
        return {
            "status": "BLOCK",
            "error": f"{type(exc).__name__}: {exc}",
            "activation": "NONE",
            "active_pointer_unchanged": _pointer_state(pointer) == before,
        }


def verify_residual_distribution_v1_release(
    release_dir: str | Path,
    *,
    repo_root: str | Path = REPO_ROOT,
    expected_manifest_sha256: str | None = None,
    check_runtime: bool = True,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reverify the immutable manifest and every V1 cross-evidence binding."""

    verified = verify_release(
        release_dir,
        repo_root=repo_root,
        expected_manifest_sha256=expected_manifest_sha256,
        check_runtime=check_runtime,
        current_runtime_versions=current_runtime_versions,
        current_runtime_identity=current_runtime_identity,
    )
    manifest = verified["manifest"]
    _require(manifest.get("state") == "IMMUTABLE_CANDIDATE", "release is not immutable-candidate state")
    _require(
        manifest.get("expected_live_runtimes") == [PREDICTION_MODE],
        "release runtime inventory is not ResidualDistributionV1-only",
    )
    route = manifest.get("route") or {}
    _require(route.get("candidate_release_id") == manifest.get("release_id"), "route release mismatch")
    _require(route.get("prediction_mode") == PREDICTION_MODE, "route prediction mode mismatch")
    _require(route.get("live_runtime") == PREDICTION_MODE, "route runtime mismatch")
    _require(route.get("activation") == "MANUAL_POINTER_ONLY", "route activation is not manual-only")
    for field in (
        "active_for_headline",
        "live_capture_enabled",
        "counts_toward_weather_model_promotion",
    ):
        _require(route.get(field) is False, f"route {field} must remain false")
    rollback_target = str(manifest.get("rollback_target") or "")
    _require(bool(rollback_target), "release rollback_target is required")
    _require(
        manifest.get("parent_release") == rollback_target,
        "release parent and rollback_target mismatch",
    )

    inventory = (manifest.get("artifacts") or {}).get("inventory") or []
    declared = {
        str(row.get("role")): row
        for row in inventory
        if isinstance(row, Mapping) and row.get("declared")
    }
    expected_roles = set(ROLE_PATH_KINDS)
    _require(set(declared) == expected_roles, "ResidualDistributionV1 release role set mismatch")
    release_root = Path(release_dir).resolve()
    paths: dict[str, Path] = {}
    for role, (relative, kind) in ROLE_PATH_KINDS.items():
        row = declared[role]
        _require(row.get("path") == relative, f"release role path mismatch: {role}")
        _require(row.get("kind") == kind, f"release role kind mismatch: {role}")
        paths[role] = release_root / relative

    source_paths = {role: paths[role] for role in SOURCE_INPUT_ROLES}
    summary, expected_snapshot = _validate_evidence_graph(
        source_paths,
        release_id=str(manifest["release_id"]),
        rollback_target=rollback_target,
        code_identity=manifest["code"],
        runtime_versions=manifest["runtime_versions"],
        runtime_identity=manifest["runtime_identity"],
        repo_root=repo_root,
    )
    _require(route.get("candidate_id") == summary["candidate_id"], "route candidate mismatch")
    snapshot = _json_mapping(
        paths["residual_distribution_v1_release_config"],
        "residual_distribution_v1_release_config",
    )
    _require(
        snapshot.get("schema_version") == RELEASE_CONFIG_SCHEMA_VERSION,
        "release config snapshot schema mismatch",
    )
    _verify_self_hash(snapshot, RELEASE_CONFIG_HASH_FIELD, "release config snapshot")
    _require(
        _canonical_equal(snapshot, expected_snapshot),
        "release config snapshot does not match immutable evidence/code/runtime bindings",
    )
    lineage = manifest.get("lineage") or {}
    _require(
        lineage.get("qualification_status") == "OFFLINE_PASS",
        "release lineage is not offline qualification PASS",
    )
    _require(
        lineage.get("forward_evidence_status") == "PENDING_EXTERNAL_ATTESTATION",
        "release lineage does not declare pending external forward evidence",
    )
    _require(lineage.get("candidate_id") == summary["candidate_id"], "release lineage candidate mismatch")
    _require(
        lineage.get("artifact_sha256") == summary["artifact_sha256"],
        "release lineage artifact hash mismatch",
    )
    _require(
        lineage.get("release_config_sha256") == snapshot[RELEASE_CONFIG_HASH_FIELD],
        "release lineage config snapshot hash mismatch",
    )
    return {
        **verified,
        "status": "PASS",
        "residual_distribution_v1_verified": True,
        "qualification_status": "OFFLINE_PASS",
        "forward_evidence_status": "PENDING_EXTERNAL_ATTESTATION",
        "candidate_id": summary["candidate_id"],
        "rollback_target": rollback_target,
    }


def build_residual_distribution_v1_offline_release(**kwargs: Any) -> dict[str, Any]:
    """Named phase-one entry point; retained candidate name remains an alias."""

    return build_residual_distribution_v1_candidate_release(**kwargs)


def _require_external_path(path: Path, release_root: Path, role: str) -> None:
    try:
        path.resolve().relative_to(release_root.resolve())
    except ValueError:
        return
    _fail(f"{role} must be external to the immutable release directory")


def _validate_forward_evidence(
    *,
    release_dir: str | Path,
    live_replay_parity_path: str | Path,
    point_in_time_streaming_path: str | Path,
    repo_root: str | Path = REPO_ROOT,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate post-freeze evidence against one exact inactive release."""

    release_root = Path(release_dir).resolve()
    parity_path = _regular_file(
        live_replay_parity_path, "external live/replay parity"
    )
    streaming_path = _regular_file(
        point_in_time_streaming_path, "external point-in-time streaming"
    )
    _require_external_path(parity_path, release_root, "live/replay parity evidence")
    _require_external_path(
        streaming_path, release_root, "point-in-time streaming evidence"
    )
    verified = verify_residual_distribution_v1_release(
        release_root,
        repo_root=repo_root,
        expected_manifest_sha256=expected_manifest_sha256,
        check_runtime=False,
    )
    manifest = verified["manifest"]
    release_id = str(manifest.get("release_id") or "")
    manifest_sha = _sha256(
        verified.get("manifest_sha256"), "release.manifest_sha256"
    )
    candidate_id = str(verified.get("candidate_id") or "")
    artifact_path = release_root / ROLE_PATH_KINDS[
        "residual_distribution_v1_model"
    ][0]
    artifact_sha = sha256_file(artifact_path)
    _require(
        (manifest.get("lineage") or {}).get("artifact_sha256") == artifact_sha,
        "release lineage artifact hash mismatch",
    )
    lock = verify_preselection_lock(
        _json_mapping(
            release_root
            / ROLE_PATH_KINDS["residual_distribution_v1_preselection_lock"][0],
            "released preselection lock",
        )
    )
    parity = _json_mapping(parity_path, "external live/replay parity")
    streaming = _json_mapping(
        streaming_path, "external point-in-time streaming"
    )
    _verify_parity(
        parity,
        candidate_id=candidate_id,
        release_id=release_id,
        manifest_sha256=manifest_sha,
        artifact_sha256=artifact_sha,
    )
    _verify_streaming(
        streaming,
        candidate_id=candidate_id,
        release_id=release_id,
        manifest_sha256=manifest_sha,
        artifact_sha256=artifact_sha,
        minimum_dates=int(lock.get("minimum_locked_dates") or 0),
    )
    release_created = _parse_utc(
        manifest.get("created_at_utc"), "release.created_at_utc"
    )
    parity_generated = _parse_utc(
        parity.get("generated_at_utc"), "parity.generated_at_utc"
    )
    streaming_started = _parse_utc(
        streaming.get("evaluation_started_at_utc"),
        "streaming.evaluation_started_at_utc",
    )
    _require(
        parity_generated >= release_created,
        "live/replay parity predates the immutable release",
    )
    _require(
        streaming_started >= release_created,
        "point-in-time streaming evaluation predates the immutable release",
    )
    return {
        "release_id": release_id,
        "release_manifest_sha256": manifest_sha,
        "candidate_id": candidate_id,
        "candidate_artifact_sha256": artifact_sha,
        "minimum_forward_fleet_dates": int(
            lock.get("minimum_locked_dates") or 0
        ),
        "parity_evidence_sha256": sha256_file(parity_path),
        "streaming_evidence_sha256": sha256_file(streaming_path),
        "parity_generated_at_utc": parity.get("generated_at_utc"),
        "streaming_started_at_utc": streaming.get(
            "evaluation_started_at_utc"
        ),
        "streaming_generated_at_utc": streaming.get("generated_at_utc"),
    }


def build_residual_distribution_v1_forward_attestation(
    *,
    release_dir: str | Path,
    live_replay_parity_path: str | Path,
    point_in_time_streaming_path: str | Path,
    attestation_path: str | Path,
    active_pointer_path: str | Path | None = None,
    repo_root: str | Path = REPO_ROOT,
    expected_manifest_sha256: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Write one external PASS attestation without mutating release or pointer."""

    release_root = Path(release_dir).resolve()
    output = Path(attestation_path).resolve()
    _require_external_path(output, release_root, "forward attestation")
    pointer = (
        Path(active_pointer_path).resolve()
        if active_pointer_path
        else release_root.parent / "current_release.json"
    )
    pointer_before = _pointer_state(pointer)
    summary = _validate_forward_evidence(
        release_dir=release_root,
        live_replay_parity_path=live_replay_parity_path,
        point_in_time_streaming_path=point_in_time_streaming_path,
        repo_root=repo_root,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    generated = _parse_utc(
        generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "attestation.generated_at_utc",
    ).isoformat()
    payload = finalize_self_hash(
        {
            "schema_version": FORWARD_ATTESTATION_SCHEMA_VERSION,
            "artifact_type": "residual_distribution_v1_forward_attestation",
            "generated_at_utc": generated,
            "status": "PASS",
            "activation": "NONE",
            "active_pointer_unchanged": True,
            "criteria": {
                "offline_release_verified": True,
                "exact_candidate_identity_bound": True,
                "exact_release_identity_bound": True,
                "exact_manifest_identity_bound": True,
                "exact_artifact_identity_bound": True,
                "live_replay_parity_pass": True,
                "release_bound_forward_streaming_pass": True,
            },
            **summary,
        },
        hash_field=FORWARD_ATTESTATION_HASH_FIELD,
    )
    _require(
        _pointer_state(pointer) == pointer_before,
        "current_release.json changed while forward evidence was verified",
    )
    _write_json_exclusive(output, payload)
    if _pointer_state(pointer) != pointer_before:
        output.unlink(missing_ok=True)
        _fail("current_release.json changed while the forward attestation was written")
    return payload


def verify_residual_distribution_v1_forward_attestation(
    attestation_path: str | Path,
    *,
    release_dir: str | Path,
    live_replay_parity_path: str | Path,
    point_in_time_streaming_path: str | Path,
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Recompute an external attestation from its exact release and evidence."""

    payload = _json_mapping(attestation_path, "forward attestation")
    _require(
        payload.get("schema_version") == FORWARD_ATTESTATION_SCHEMA_VERSION,
        "forward attestation schema mismatch",
    )
    _status_pass(payload, "forward attestation")
    _verify_self_hash(
        payload,
        FORWARD_ATTESTATION_HASH_FIELD,
        "forward attestation",
    )
    summary = _validate_forward_evidence(
        release_dir=release_dir,
        live_replay_parity_path=live_replay_parity_path,
        point_in_time_streaming_path=point_in_time_streaming_path,
        repo_root=repo_root,
        expected_manifest_sha256=str(
            payload.get("release_manifest_sha256") or ""
        ),
    )
    for field, expected in summary.items():
        _require(
            payload.get(field) == expected,
            f"forward attestation binding mismatch: {field}",
        )
    required_criteria = {
        "offline_release_verified",
        "exact_candidate_identity_bound",
        "exact_release_identity_bound",
        "exact_manifest_identity_bound",
        "exact_artifact_identity_bound",
        "live_replay_parity_pass",
        "release_bound_forward_streaming_pass",
    }
    _exact_pass_criteria(
        payload.get("criteria"),
        required=frozenset(required_criteria),
        field="forward attestation criteria",
    )
    _require(payload.get("activation") == "NONE", "forward attestation activates a release")
    return dict(payload)


__all__ = [name for name in globals() if not name.startswith("_")]
