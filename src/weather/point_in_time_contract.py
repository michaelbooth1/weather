"""Dependency-safe verification for frozen point-in-time qualification evidence.

This module deliberately does not import capture, archive, reporting, model, or
release modules. Producers and release loaders can therefore verify an already
materialized evidence graph without pulling the reporting materializer (and its
capture dependencies) into their import graph.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from weather.schema_registry import schema_version


MATERIALIZER_SCHEMA_VERSION = schema_version("point_in_time_materializer")
VALIDATION_PLAN_SCHEMA_VERSION = schema_version("point_in_time_validation_plan")
FIT_RECEIPT_SCHEMA_VERSION = schema_version("point_in_time_fit_receipt")
EVALUATION_SCHEMA_VERSION = schema_version("point_in_time_streaming_evaluation")

CLAIM_LANES = (
    "weather_only",
    "market_benchmark",
    "market_informed",
    "trading",
)
REQUIRED_FIT_STAGES = (
    "feature_selection",
    "scaling_imputation",
    "model",
    "calibration",
    "postprocessing",
    "regime_router",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractViolation(ValueError):
    """A frozen qualification artifact failed closed verification."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_utc(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ContractViolation("invalid_timestamp", f"{field} is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractViolation("invalid_timestamp", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ContractViolation("invalid_timestamp", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ContractViolation("invalid_date", f"{field} must be YYYY-MM-DD") from exc


def _verify_self_hash(payload: Mapping[str, Any], field: str, code: str) -> None:
    actual = str(payload.get(field) or "")
    unhashed = dict(payload)
    unhashed.pop(field, None)
    if not SHA256_RE.fullmatch(actual) or actual != sha256_text(canonical_json(unhashed)):
        raise ContractViolation(code, f"{field} is missing or invalid")


def _read_json(path: str | Path, *, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractViolation(code, f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractViolation(code, f"{path} must contain a JSON object")
    return payload


def verify_materialization_manifest(
    parquet_path: str | Path,
    manifest_path: str | Path,
    *,
    expected_candidate_id: str | None = None,
    expected_release_id: str | None = None,
    inspect_parquet: bool = True,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path, code="invalid_materialization_manifest")
    if (
        manifest.get("schema_version") != MATERIALIZER_SCHEMA_VERSION
        or manifest.get("artifact_type") != "point_in_time_materialization_manifest"
    ):
        raise ContractViolation("invalid_materialization_manifest", "manifest schema/type mismatch")
    _verify_self_hash(
        manifest, "manifest_hash", "materialization_manifest_hash_mismatch"
    )
    if manifest.get("status") != "PASS":
        raise ContractViolation("materialization_not_pass", "materialization is not PASS")
    artifact = manifest.get("derived_artifact")
    if not isinstance(artifact, Mapping):
        raise ContractViolation("invalid_materialization_manifest", "derived artifact missing")
    path = Path(parquet_path)
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise ContractViolation("materialization_hash_mismatch", "corpus is missing or invalid")
    if artifact.get("sha256") != sha256_file(path):
        raise ContractViolation("materialization_hash_mismatch", "Parquet hash mismatch")
    if int(artifact.get("bytes") or -1) != path.stat().st_size:
        raise ContractViolation("materialization_byte_count_mismatch", "byte count mismatch")
    try:
        declared_rows = int(artifact.get("row_count") or -1)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(
            "materialization_row_count_mismatch", "row count is invalid"
        ) from exc
    if declared_rows <= 0:
        raise ContractViolation("materialization_row_count_mismatch", "row count is invalid")
    if inspect_parquet:
        import pyarrow.parquet as pq

        if declared_rows != int(pq.ParquetFile(path).metadata.num_rows):
            raise ContractViolation("materialization_row_count_mismatch", "row count mismatch")
    if expected_candidate_id is not None and manifest.get("candidate_id") != expected_candidate_id:
        raise ContractViolation("materialization_candidate_identity_mismatch", "candidate mismatch")
    if expected_release_id is not None and manifest.get("release_id") != expected_release_id:
        raise ContractViolation("materialization_release_identity_mismatch", "release mismatch")
    return manifest


def collect_parquet_fleet_dates(path: str | Path) -> tuple[str, ...]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    if "target_date" not in parquet.schema_arrow.names:
        raise ContractViolation("missing_target_date", "Parquet target_date column missing")
    dates: set[str] = set()
    for batch in parquet.iter_batches(batch_size=65_536, columns=["target_date"]):
        dates.update(str(value) for value in batch.column(0).to_pylist() if value)
    for value in dates:
        _parse_date(value, "corpus.target_date")
    return tuple(sorted(dates))


def _validate_fold(payload: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    fold_id = str(payload.get("fold_id") or "").strip()
    train = tuple(str(value) for value in payload.get("train_dates") or ())
    embargo = tuple(str(value) for value in payload.get("embargo_dates") or ())
    validation = tuple(str(value) for value in payload.get("validation_dates") or ())
    try:
        embargo_days = int(payload.get("embargo_days"))
    except (TypeError, ValueError) as exc:
        raise ContractViolation("invalid_validation_plan", f"{label} embargo is invalid") from exc
    if not fold_id or not train or not validation or not 3 <= embargo_days <= 7:
        raise ContractViolation("invalid_validation_plan", f"{label} is incomplete")
    combined = train + embargo + validation
    if len(combined) != len(set(combined)):
        raise ContractViolation("invalid_validation_plan", f"{label} overlaps date partitions")
    for value in combined:
        _parse_date(value, f"{label}.date")
    first_validation = _parse_date(validation[0], f"{label}.validation_date")
    if any(
        (first_validation - _parse_date(value, f"{label}.train_date")).days <= embargo_days
        for value in train
    ):
        raise ContractViolation("invalid_validation_plan", f"{label} violates embargo")
    return {
        "fold_id": fold_id,
        "train_dates": train,
        "embargo_dates": embargo,
        "validation_dates": validation,
        "embargo_days": embargo_days,
    }


def verify_validation_plan_payload(
    payload: Mapping[str, Any],
    *,
    expected_candidate_id: str | None = None,
    expected_release_id: str | None = None,
    expected_corpus_sha256: str | None = None,
    expected_manifest_hash: str | None = None,
    expected_fleet_dates: Iterable[str] | None = None,
    require_fit_receipts: bool = False,
) -> dict[str, Any]:
    if (
        payload.get("schema_version") != VALIDATION_PLAN_SCHEMA_VERSION
        or payload.get("artifact_type") != "point_in_time_validation_plan"
    ):
        raise ContractViolation("invalid_validation_plan", "plan schema/type mismatch")
    _verify_self_hash(payload, "plan_hash", "validation_plan_hash_mismatch")
    if payload.get("status") != "PASS" or payload.get("independent_unit") != "fleet_target_date":
        raise ContractViolation("validation_plan_not_pass", "validation plan is not PASS")
    _parse_utc(payload.get("generated_at_utc"), "validation_plan.generated_at_utc")
    config = payload.get("config")
    try:
        embargo_days = int(config.get("embargo_days")) if isinstance(config, Mapping) else 0
    except (TypeError, ValueError) as exc:
        raise ContractViolation("invalid_validation_plan", "embargo is invalid") from exc
    if not 3 <= embargo_days <= 7:
        raise ContractViolation("invalid_validation_plan", "embargo is invalid")
    if expected_candidate_id is not None and payload.get("candidate_id") != expected_candidate_id:
        raise ContractViolation("validation_plan_identity_mismatch", "candidate mismatch")
    if expected_release_id is not None and payload.get("release_id") != expected_release_id:
        raise ContractViolation("validation_plan_identity_mismatch", "release mismatch")
    binding = payload.get("corpus_binding")
    if expected_corpus_sha256 is not None or expected_manifest_hash is not None:
        if not isinstance(binding, Mapping):
            raise ContractViolation("validation_plan_corpus_mismatch", "corpus binding missing")
        if binding.get("corpus_sha256") != expected_corpus_sha256:
            raise ContractViolation("validation_plan_corpus_mismatch", "corpus hash mismatch")
        if binding.get("materialization_manifest_hash") != expected_manifest_hash:
            raise ContractViolation("validation_plan_corpus_mismatch", "manifest hash mismatch")
    fleet_dates = tuple(str(value) for value in payload.get("fleet_dates") or ())
    if not fleet_dates or len(fleet_dates) != len(set(fleet_dates)):
        raise ContractViolation("invalid_validation_plan", "fleet date inventory invalid")
    for value in fleet_dates:
        _parse_date(value, "validation_plan.fleet_date")
    if expected_fleet_dates is not None and set(fleet_dates) != {
        str(value) for value in expected_fleet_dates
    }:
        raise ContractViolation("validation_plan_corpus_mismatch", "fleet dates mismatch")

    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ContractViolation("invalid_validation_plan", "rolling-origin folds missing")
    scopes: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(folds):
        if not isinstance(row, Mapping) or not isinstance(row.get("outer"), Mapping):
            raise ContractViolation("invalid_validation_plan", "outer fold malformed")
        outer = _validate_fold(row["outer"], label=f"folds[{index}].outer")
        outer_scope = f"outer/{outer['fold_id']}"
        if outer_scope in scopes:
            raise ContractViolation("invalid_validation_plan", "duplicate outer fold")
        scopes[outer_scope] = outer
        inner_rows = row.get("inner")
        if not isinstance(inner_rows, list) or not inner_rows:
            raise ContractViolation("invalid_validation_plan", "inner folds missing")
        for inner_index, inner_row in enumerate(inner_rows):
            if not isinstance(inner_row, Mapping):
                raise ContractViolation("invalid_validation_plan", "inner fold malformed")
            inner = _validate_fold(inner_row, label=f"folds[{index}].inner[{inner_index}]")
            if not set(
                inner["train_dates"] + inner["embargo_dates"] + inner["validation_dates"]
            ) <= set(outer["train_dates"]):
                raise ContractViolation("invalid_validation_plan", "inner fold escapes outer train")
            scope = f"{outer_scope}/inner/{inner['fold_id']}"
            if scope in scopes:
                raise ContractViolation("invalid_validation_plan", "duplicate inner fold")
            scopes[scope] = inner

    receipt_contract = payload.get("fit_receipt_contract")
    if not isinstance(receipt_contract, Mapping):
        raise ContractViolation("invalid_fit_receipts", "receipt contract missing")
    stages = tuple(str(value) for value in receipt_contract.get("required_stages") or ())
    declared_scopes = {str(value) for value in receipt_contract.get("required_fold_scopes") or ()}
    if (
        receipt_contract.get("fit_scope") != "training_only"
        or receipt_contract.get("receipt_hash_field") != "receipt_sha256"
        or declared_scopes != set(scopes)
    ):
        raise ContractViolation("invalid_fit_receipts", "receipt contract inconsistent")
    if require_fit_receipts and set(stages) != set(REQUIRED_FIT_STAGES):
        raise ContractViolation("invalid_fit_receipts", "fit stage inventory incomplete")
    receipts = payload.get("fit_receipts")
    if not isinstance(receipts, list):
        raise ContractViolation("invalid_fit_receipts", "fit receipts missing")
    by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise ContractViolation("invalid_fit_receipts", "fit receipt malformed")
        _verify_self_hash(receipt, "receipt_sha256", "fit_receipt_hash_mismatch")
        scope = str(receipt.get("fold_scope") or "")
        stage = str(receipt.get("stage_name") or "")
        key = (scope, stage)
        fold = scopes.get(scope)
        try:
            positive_counts = (
                int(receipt.get("fit_row_count") or 0) > 0
                and int(receipt.get("validation_row_count") or 0) > 0
            )
        except (TypeError, ValueError):
            positive_counts = False
        if key in by_key:
            raise ContractViolation("invalid_fit_receipts", "duplicate fit receipt")
        if (
            fold is None
            or stage not in stages
            or receipt.get("schema_version") != FIT_RECEIPT_SCHEMA_VERSION
            or receipt.get("artifact_type") != "training_only_fit_receipt"
            or receipt.get("fit_scope") != "training_only"
            or receipt.get("fold_id") != fold["fold_id"]
            or tuple(receipt.get("train_dates") or ()) != fold["train_dates"]
            or tuple(receipt.get("embargo_dates") or ()) != fold["embargo_dates"]
            or tuple(receipt.get("validation_dates") or ()) != fold["validation_dates"]
            or receipt.get("embargo_days") != fold["embargo_days"]
            or not str(receipt.get("implementation_identity") or "").strip()
            or not positive_counts
            or not SHA256_RE.fullmatch(str(receipt.get("fit_input_sha256") or ""))
            or not SHA256_RE.fullmatch(str(receipt.get("validation_input_sha256") or ""))
        ):
            raise ContractViolation("invalid_fit_receipts", f"fit receipt invalid: {key}")
        by_key[key] = receipt
    expected_keys = {(scope, stage) for scope in scopes for stage in stages}
    if require_fit_receipts and set(by_key) != expected_keys:
        raise ContractViolation("invalid_fit_receipts", "fold/stage receipt coverage incomplete")
    return dict(payload)


def verify_streaming_evaluation_payload(
    payload: Mapping[str, Any],
    *,
    expected_candidate_id: str | None = None,
    expected_release_id: str | None = None,
    expected_corpus_sha256: str | None = None,
    expected_manifest_hash: str | None = None,
    expected_validation_plan_hash: str | None = None,
    require_production_window: bool = False,
    now_utc: datetime | None = None,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    if (
        payload.get("schema_version") != EVALUATION_SCHEMA_VERSION
        or payload.get("artifact_type") != "point_in_time_streaming_evaluation"
    ):
        raise ContractViolation("invalid_streaming_evaluation", "evaluation schema/type mismatch")
    _verify_self_hash(payload, "evaluation_hash", "streaming_evaluation_hash_mismatch")
    if payload.get("status") != "PASS":
        raise ContractViolation("streaming_evaluation_not_pass", "evaluation is not PASS")
    generated = _parse_utc(payload.get("generated_at_utc"), "evaluation.generated_at_utc")
    started = _parse_utc(
        payload.get("evaluation_started_at_utc"), "evaluation.evaluation_started_at_utc"
    )
    if started > generated:
        raise ContractViolation("evaluation_time_order_invalid", "start is after completion")
    if max_age_days is not None:
        if max_age_days <= 0:
            raise ValueError("max_age_days must be positive")
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if generated > now + timedelta(minutes=5):
            raise ContractViolation("streaming_evaluation_from_future", "evaluation is in the future")
        if now - generated > timedelta(days=max_age_days):
            raise ContractViolation("stale_streaming_evaluation", "evaluation is stale")
    if expected_candidate_id is not None and payload.get("candidate_id") != expected_candidate_id:
        raise ContractViolation("streaming_evaluation_identity_mismatch", "candidate mismatch")
    if expected_release_id is not None and payload.get("release_id") != expected_release_id:
        raise ContractViolation("streaming_evaluation_identity_mismatch", "release mismatch")
    input_row = payload.get("input")
    if expected_corpus_sha256 is not None and (
        not isinstance(input_row, Mapping) or input_row.get("sha256") != expected_corpus_sha256
    ):
        raise ContractViolation("streaming_evaluation_corpus_mismatch", "corpus hash mismatch")
    binding = payload.get("contract_binding")
    if expected_manifest_hash is not None or expected_validation_plan_hash is not None:
        if not isinstance(binding, Mapping):
            raise ContractViolation("streaming_evaluation_contract_mismatch", "binding missing")
        if binding.get("materialization_manifest_hash") != expected_manifest_hash:
            raise ContractViolation("streaming_evaluation_contract_mismatch", "manifest mismatch")
        if binding.get("validation_plan_hash") != expected_validation_plan_hash:
            raise ContractViolation("streaming_evaluation_contract_mismatch", "plan mismatch")
        if not isinstance(input_row, Mapping) or input_row.get(
            "materialization_manifest_hash"
        ) != expected_manifest_hash:
            raise ContractViolation("streaming_evaluation_contract_mismatch", "input manifest mismatch")

    lock = payload.get("window_lock")
    if not isinstance(lock, Mapping):
        raise ContractViolation("invalid_evaluation_window_lock", "window lock missing")
    lock_basis = {
        "input_sha256": lock.get("input_sha256"),
        "window_start": lock.get("window_start"),
        "window_end": lock.get("window_end"),
        "window_days": lock.get("window_days"),
        "target_dates": lock.get("target_dates"),
    }
    if lock.get("window_lock_id") != sha256_text(canonical_json(lock_basis)):
        raise ContractViolation("invalid_evaluation_window_lock", "window lock hash mismatch")
    if _parse_utc(lock.get("generated_at_utc"), "window_lock.generated_at_utc") > started:
        raise ContractViolation(
            "window_selected_after_evaluation", "evaluation window was selected after scoring began"
        )
    target_dates = tuple(str(value) for value in lock.get("target_dates") or ())
    if expected_corpus_sha256 is not None and lock.get("input_sha256") != expected_corpus_sha256:
        raise ContractViolation("invalid_evaluation_window_lock", "window corpus mismatch")
    if require_production_window:
        if (
            lock.get("schema_version") != EVALUATION_SCHEMA_VERSION
            or lock.get("status") != "PASS"
            or lock.get("window_days") != 14
            or len(target_dates) != 14
            or len(set(target_dates)) != 14
            or lock.get("missing_calendar_dates") != []
            or lock.get("candidate_selection_permission") != "forbidden"
            or lock.get("locked_before_scoring") is not True
        ):
            raise ContractViolation("invalid_evaluation_window_lock", "production lock incomplete")
        parsed = [_parse_date(value, "window_lock.target_date") for value in target_dates]
        if parsed != [parsed[0] + timedelta(days=offset) for offset in range(14)]:
            raise ContractViolation("invalid_evaluation_window_lock", "window is not contiguous")
        if lock.get("window_start") != target_dates[0] or lock.get("window_end") != target_dates[-1]:
            raise ContractViolation("invalid_evaluation_window_lock", "window bounds mismatch")

    if payload.get("lane_isolation") != {
        "status": "PASS",
        "lanes": list(CLAIM_LANES),
        "cross_lane_pooling": False,
    }:
        raise ContractViolation("invalid_lane_isolation", "claim lanes are not isolated")
    lanes = payload.get("lanes")
    if not isinstance(lanes, Mapping) or set(lanes) != set(CLAIM_LANES):
        raise ContractViolation("invalid_lane_isolation", "claim lane inventory incomplete")
    for lane, summaries in lanes.items():
        if not isinstance(summaries, list):
            raise ContractViolation("invalid_streaming_evaluation", f"lane {lane} malformed")
        for summary in summaries:
            metrics = summary.get("metrics") if isinstance(summary, Mapping) else None
            if not isinstance(metrics, Mapping):
                raise ContractViolation("invalid_clustered_intervals", "metrics missing")
            for metric_name in ("categorical_brier", "categorical_log_loss"):
                metric = metrics.get(metric_name)
                if not isinstance(metric, Mapping) or set(metric) != {
                    "equal_market_day",
                    "equal_fleet_date",
                }:
                    raise ContractViolation("invalid_clustered_intervals", "weightings incomplete")
                for weighting, interval in metric.items():
                    if (
                        not isinstance(interval, Mapping)
                        or interval.get("cluster_unit") != "fleet_target_date"
                        or interval.get("weighting") != weighting
                        or int(interval.get("fleet_dates") or 0) <= 0
                        or int(interval.get("market_days") or 0) <= 0
                    ):
                        raise ContractViolation("invalid_clustered_intervals", "interval invalid")
    if require_production_window:
        weather = lanes.get("weather_only") or []
        if not weather or any(
            summary.get("release_id") != expected_release_id
            or int(summary.get("fleet_dates") or 0) != 14
            for summary in weather
        ):
            raise ContractViolation(
                "candidate_evaluation_missing", "candidate has no complete weather-only window"
            )
    return dict(payload)


def verify_production_point_in_time_artifacts(
    *,
    corpus_path: str | Path,
    materialization_manifest_path: str | Path,
    validation_plan_path: str | Path,
    streaming_evaluation_path: str | Path,
    expected_candidate_id: str,
    expected_release_id: str,
    now_utc: datetime | None = None,
    max_age_days: int | None = None,
    inspect_corpus_parquet: bool = True,
) -> dict[str, Any]:
    """Verify the canonical hash-linked graph required for production capability."""

    manifest = verify_materialization_manifest(
        corpus_path,
        materialization_manifest_path,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        inspect_parquet=inspect_corpus_parquet,
    )
    corpus_sha = sha256_file(corpus_path)
    manifest_hash = str(manifest.get("manifest_hash") or "")
    plan = _read_json(validation_plan_path, code="invalid_validation_plan")
    fleet_dates = (
        collect_parquet_fleet_dates(corpus_path)
        if inspect_corpus_parquet
        else tuple(str(value) for value in plan.get("fleet_dates") or ())
    )
    verify_validation_plan_payload(
        plan,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_corpus_sha256=corpus_sha,
        expected_manifest_hash=manifest_hash,
        expected_fleet_dates=fleet_dates,
        require_fit_receipts=True,
    )
    evaluation = _read_json(
        streaming_evaluation_path, code="invalid_streaming_evaluation"
    )
    verify_streaming_evaluation_payload(
        evaluation,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_corpus_sha256=corpus_sha,
        expected_manifest_hash=manifest_hash,
        expected_validation_plan_hash=str(plan.get("plan_hash") or ""),
        require_production_window=True,
        now_utc=now_utc,
        max_age_days=max_age_days,
    )
    if _parse_utc(
        plan.get("generated_at_utc"), "validation_plan.generated_at_utc"
    ) > _parse_utc(
        evaluation.get("evaluation_started_at_utc"), "evaluation.evaluation_started_at_utc"
    ):
        raise ContractViolation(
            "plan_selected_after_evaluation", "validation plan was selected after scoring began"
        )
    locked_dates = set((evaluation.get("window_lock") or {}).get("target_dates") or ())
    if not locked_dates <= set(fleet_dates):
        raise ContractViolation("streaming_evaluation_corpus_mismatch", "locked dates escape corpus")
    return {
        "status": "PASS",
        "candidate_id": expected_candidate_id,
        "release_id": expected_release_id,
        "corpus_sha256": corpus_sha,
        "materialization_manifest_hash": manifest_hash,
        "validation_plan_hash": plan["plan_hash"],
        "streaming_evaluation_hash": evaluation["evaluation_hash"],
        "fleet_dates": len(fleet_dates),
        "locked_window_days": len(locked_dates),
        "fit_receipt_count": len(plan.get("fit_receipts") or ()),
        "corpus_structure_reverified": inspect_corpus_parquet,
        "verification_mode": (
            "candidate_build_full_parquet_inspection"
            if inspect_corpus_parquet
            else "immutable_release_hash_graph_reverification"
        ),
    }
