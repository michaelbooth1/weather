"""Dependency-safe verification for frozen point-in-time qualification evidence.

This module deliberately does not import capture, archive, reporting, model, or
release modules. Producers and release loaders can therefore verify an already
materialized evidence graph without pulling the reporting materializer (and its
capture dependencies) into their import graph.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from weather.io import sha256_file
from weather.schema_registry import schema_version


MATERIALIZER_SCHEMA_VERSION = schema_version("point_in_time_materializer")
VALIDATION_PLAN_SCHEMA_VERSION = schema_version("point_in_time_validation_plan")
FIT_RECEIPT_SCHEMA_VERSION = schema_version("point_in_time_fit_receipt")
EVALUATION_SCHEMA_VERSION = schema_version("point_in_time_streaming_evaluation")
CANDIDATE_TRAINING_GRAPH_SCHEMA_VERSION = schema_version(
    "point_in_time_candidate_training_graph"
)
POOLED_PIT_TRAINING_SCHEMA_VERSION = schema_version(
    "pooled_band_point_in_time_training"
)
POOLED_PIT_FINAL_REFIT_SCHEMA_VERSION = schema_version(
    "pooled_band_final_refit_receipt"
)

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
FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM = "sha256"
FIT_RECEIPT_PAYLOAD_CANONICALIZATION = "canonical_json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COUNTABLE_SOURCE_QUALITIES = frozenset({"healthy", "complete"})
SELECTION_UNIVERSE_EXCLUDED_FIELDS = (
    "variant_id",
    "release_id",
    "prediction_probability",
    "runtime_identity",
    "source_payload_json",
    "source_payload_sha256",
    "source_provenance_json",
)
PRODUCTION_MAX_MARKET_DAYS = 60
PRODUCTION_MAX_ROWS_PER_MARKET_DAY = 250_000


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


def verify_output_bound_fit_receipt(receipt: Mapping[str, Any]) -> None:
    """Recompute one receipt's declared input/output payload hashes."""

    if (
        receipt.get("payload_hash_algorithm") != FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM
        or receipt.get("payload_canonicalization")
        != FIT_RECEIPT_PAYLOAD_CANONICALIZATION
    ):
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt payload hash contract is missing",
        )
    input_payload = receipt.get("stage_input_payload")
    output_payload = receipt.get("stage_output_payload")
    if not isinstance(input_payload, Mapping) or not isinstance(output_payload, Mapping):
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt input/output payloads are missing",
        )
    input_sha = str(receipt.get("stage_input_sha256") or "")
    output_sha = str(receipt.get("stage_output_sha256") or "")
    if (
        not SHA256_RE.fullmatch(input_sha)
        or input_sha != sha256_text(canonical_json(input_payload))
    ):
        raise ContractViolation(
            "fit_receipt_input_payload_hash_mismatch",
            "fit receipt input payload hash does not recompute",
        )
    if (
        not SHA256_RE.fullmatch(output_sha)
        or output_sha != sha256_text(canonical_json(output_payload))
    ):
        raise ContractViolation(
            "fit_receipt_output_payload_hash_mismatch",
            "fit receipt output payload hash does not recompute",
        )
    expected_input = {
        "fit_input_sha256": receipt.get("fit_input_sha256"),
        "validation_input_sha256": receipt.get("validation_input_sha256"),
        "fit_row_count": receipt.get("fit_row_count"),
        "validation_row_count": receipt.get("validation_row_count"),
        "train_dates": list(receipt.get("train_dates") or ()),
        "validation_dates": list(receipt.get("validation_dates") or ()),
        "upstream_stage_output_sha256": input_payload.get(
            "upstream_stage_output_sha256"
        ),
        "declared_stage_input": input_payload.get("declared_stage_input"),
    }
    if dict(input_payload) != expected_input:
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt input payload is inconsistent with its receipt",
        )
    expected_output = {
        "fit_output_sha256": receipt.get("fit_output_sha256"),
        "validation_output_sha256": receipt.get("validation_output_sha256"),
        "fit_output_row_count": receipt.get("fit_output_row_count"),
        "validation_output_row_count": receipt.get("validation_output_row_count"),
        "train_dates": list(receipt.get("train_dates") or ()),
        "validation_dates": list(receipt.get("validation_dates") or ()),
        "declared_stage_output": output_payload.get("declared_stage_output"),
    }
    if dict(output_payload) != expected_output:
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt output payload is inconsistent with its receipt",
        )
    if (
        not SHA256_RE.fullmatch(str(receipt.get("fit_output_sha256") or ""))
        or not SHA256_RE.fullmatch(
            str(receipt.get("validation_output_sha256") or "")
        )
    ):
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt output row hashes are invalid",
        )
    try:
        output_counts_positive = (
            int(receipt.get("fit_output_row_count") or 0) > 0
            and int(receipt.get("validation_output_row_count") or 0) > 0
        )
    except (TypeError, ValueError):
        output_counts_positive = False
    if not output_counts_positive or output_payload.get("declared_stage_output") is None:
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt output declaration is incomplete",
        )


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


def _contiguous_locked_dates(values: Any, *, field: str) -> list[str]:
    raw = list(values or ())
    try:
        parsed = [_parse_date(value, field) for value in raw]
    except TypeError as exc:
        raise ContractViolation("invalid_date", f"{field} must be a date list") from exc
    canonical = [value.isoformat() for value in sorted(parsed)]
    if (
        len(parsed) != 14
        or len(set(parsed)) != 14
        or raw != canonical
        or parsed != [parsed[0] + timedelta(days=offset) for offset in range(14)]
    ):
        raise ContractViolation(
            "invalid_locked_window",
            f"{field} must be one canonical contiguous 14-day window",
        )
    return canonical


def _pooled_artifact_serving_contract(
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Reproduce the dependency-safe subset hashed by pooled final refits."""

    fit_contract = artifact.get("postprocess_fit_contract") or {}
    static_context = artifact.get("production_static_context") or {}
    return _pooled_contract_jsonable({
        "schema_version": artifact.get("schema_version"),
        "feature_schema_version": artifact.get("feature_schema_version"),
        "family_unit": artifact.get("family_unit"),
        "prediction_mode": artifact.get("prediction_mode"),
        "objective": artifact.get("objective"),
        "feature_subset": artifact.get("feature_subset"),
        "feature_subset_contract": artifact.get("feature_subset_contract"),
        "dynamic_source_state_enabled": artifact.get(
            "dynamic_source_state_enabled"
        ),
        "postprocess": artifact.get("postprocess"),
        "production_static_context_sha256": static_context.get("context_sha256"),
        "production_external_sidecar_policy": static_context.get(
            "external_sidecar_policy"
        ),
        "postprocess_fit_contract": {
            key: fit_contract.get(key)
            for key in (
                "schema_version",
                "status",
                "policy",
                "served_parameters",
                "preselection_hash",
                "window_lock_id",
                "locked_dates",
                "promotion_permission",
            )
            if key in fit_contract
        },
    })


def _pooled_contract_jsonable(value: Any) -> Any:
    """Match the pooled trainer's JSON normalization without importing it."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _pooled_contract_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, set):
        values = [_pooled_contract_jsonable(item) for item in value]
        return sorted(values, key=canonical_json)
    if isinstance(value, (list, tuple)):
        return [_pooled_contract_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _pooled_contract_jsonable(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        return _pooled_contract_jsonable(value.tolist())
    return str(value)


def _verify_pooled_self_hash(
    payload: Mapping[str, Any],
    field: str,
    code: str,
) -> None:
    actual = str(payload.get(field) or "")
    unhashed = dict(payload)
    unhashed.pop(field, None)
    expected = sha256_text(canonical_json(_pooled_contract_jsonable(unhashed)))
    if not SHA256_RE.fullmatch(actual) or actual != expected:
        raise ContractViolation(code, f"{field} is missing or invalid")


def verify_embedded_point_in_time_training_evidence(
    model_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the self-hashed PIT evidence embedded in one exact model bundle.

    This intentionally mirrors only the serialization-level graph invariants.
    The trainer owns estimator-specific checks; release verification owns the
    independent evidence/receipt/serving-contract bindings below.
    """

    evidence = model_bundle.get("point_in_time_training")
    if not isinstance(evidence, Mapping):
        raise ContractViolation(
            "candidate_training_evidence_missing",
            "candidate model bundle has no embedded point-in-time training evidence",
        )
    _verify_pooled_self_hash(
        evidence,
        "evidence_sha256",
        "candidate_training_evidence_hash_mismatch",
    )
    if (
        evidence.get("schema_version") != POOLED_PIT_TRAINING_SCHEMA_VERSION
        or evidence.get("status") != "PASS"
    ):
        raise ContractViolation(
            "invalid_candidate_training_evidence",
            "embedded point-in-time training evidence schema or status is invalid",
        )
    _parse_utc(
        evidence.get("generated_at_utc"),
        "point_in_time_training.generated_at_utc",
    )

    lock = evidence.get("preselection_lock")
    if not isinstance(lock, Mapping):
        raise ContractViolation(
            "candidate_training_preselection_mismatch",
            "embedded point-in-time training evidence has no preselection lock",
        )
    locked_dates = _contiguous_locked_dates(
        lock.get("locked_dates"),
        field="point_in_time_training.preselection_lock.locked_dates",
    )
    selection_dates = list(lock.get("selection_universe_dates") or ())
    training_dates = list(lock.get("training_universe_dates") or ())
    try:
        canonical_selection_dates = sorted(
            {
                _parse_date(value, "selection_universe_dates").isoformat()
                for value in selection_dates
            }
        )
        canonical_training_dates = sorted(
            {_parse_date(value, "training_universe_dates").isoformat() for value in training_dates}
        )
    except TypeError as exc:
        raise ContractViolation(
            "candidate_training_preselection_mismatch",
            "embedded point-in-time training date inventories are malformed",
        ) from exc
    if (
        not SHA256_RE.fullmatch(str(lock.get("preselection_hash") or ""))
        or not SHA256_RE.fullmatch(str(lock.get("window_lock_id") or ""))
        or not SHA256_RE.fullmatch(
            str(lock.get("selection_universe_sha256") or "")
        )
        or lock.get("locked_dates_used_for_selection") is not False
        or lock.get("candidate_selection_permission") != "forbidden"
        or not selection_dates
        or selection_dates != canonical_selection_dates
        or not set(locked_dates) <= set(selection_dates)
        or training_dates != canonical_training_dates
        or training_dates != sorted(set(selection_dates) - set(locked_dates))
        or lock.get("training_universe_sha256")
        != sha256_text(canonical_json(training_dates))
        or len(selection_dates) > PRODUCTION_MAX_MARKET_DAYS
        or int(lock.get("selection_universe_row_count") or 0) <= 0
    ):
        raise ContractViolation(
            "candidate_training_preselection_mismatch",
            "embedded point-in-time training preselection lock is invalid",
        )

    folds = evidence.get("folds")
    receipts = evidence.get("fit_receipts")
    if not isinstance(folds, list) or not folds or not isinstance(receipts, list) or not receipts:
        raise ContractViolation(
            "candidate_training_evidence_mismatch",
            "embedded point-in-time folds or fit receipts are missing",
        )
    receipt_hashes: list[str] = []
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise ContractViolation(
                "candidate_training_evidence_mismatch",
                "embedded point-in-time fit receipt is malformed",
            )
        _verify_pooled_self_hash(
            receipt,
            "receipt_sha256",
            "candidate_training_evidence_hash_mismatch",
        )
        receipt_hashes.append(str(receipt["receipt_sha256"]))
    if len(set(receipt_hashes)) != len(receipt_hashes):
        raise ContractViolation(
            "candidate_training_evidence_mismatch",
            "embedded point-in-time fit receipts are duplicated",
        )

    final_receipt = evidence.get("final_fit_receipt")
    if not isinstance(final_receipt, Mapping):
        raise ContractViolation(
            "candidate_final_fit_receipt_missing",
            "embedded point-in-time final-refit receipt is missing",
        )
    _verify_pooled_self_hash(
        final_receipt,
        "receipt_sha256",
        "candidate_final_fit_receipt_hash_mismatch",
    )
    if (
        final_receipt.get("schema_version") != POOLED_PIT_FINAL_REFIT_SCHEMA_VERSION
        or final_receipt.get("artifact_type") != "pooled_band_final_refit_receipt"
        or final_receipt.get("payload_hash_algorithm") != "sha256"
        or final_receipt.get("payload_canonicalization") != "canonical_json"
    ):
        raise ContractViolation(
            "invalid_candidate_final_fit_receipt",
            "embedded final-refit receipt schema or payload contract is invalid",
        )
    _parse_utc(
        final_receipt.get("generated_at_utc"),
        "point_in_time_training.final_fit_receipt.generated_at_utc",
    )
    final_train_dates = list(final_receipt.get("train_dates") or ())
    final_locked_dates = list(final_receipt.get("locked_dates") or ())
    parent_receipts_sha256 = sha256_text(
        canonical_json(sorted(receipt_hashes))
    )
    stage_input = final_receipt.get("stage_input_payload")
    stage_output = final_receipt.get("stage_output_payload")
    model_hashes = final_receipt.get("model_sha256_by_hour")
    models = model_bundle.get("models")
    if (
        not isinstance(stage_input, Mapping)
        or not isinstance(stage_output, Mapping)
        or not isinstance(model_hashes, Mapping)
        or not model_hashes
        or not isinstance(models, Mapping)
        or set(str(key) for key in models) != set(model_hashes)
        or any(not SHA256_RE.fullmatch(str(value or "")) for value in model_hashes.values())
    ):
        raise ContractViolation(
            "invalid_candidate_final_fit_receipt",
            "embedded final-refit payload or fitted-model inventory is invalid",
        )
    serving_contract = _pooled_artifact_serving_contract(model_bundle)
    serving_contract_sha256 = sha256_text(canonical_json(serving_contract))
    model_payload_sha256 = sha256_text(
        canonical_json(
            {
                "model_sha256_by_hour": dict(model_hashes),
                "artifact_serving_contract_sha256": serving_contract_sha256,
            }
        )
    )
    expected_stage_input = {
        "fit_input_sha256": final_receipt.get("fit_input_sha256"),
        "fit_row_count": final_receipt.get("fit_row_count"),
        "train_dates": final_train_dates,
        "locked_dates": final_locked_dates,
        "preselection_hash": final_receipt.get("preselection_hash"),
        "window_lock_id": final_receipt.get("window_lock_id"),
        "parent_fit_receipts_sha256": parent_receipts_sha256,
    }
    if (
        final_locked_dates != locked_dates
        or final_train_dates != training_dates
        or set(final_train_dates) & set(locked_dates)
        or final_receipt.get("preselection_hash") != lock.get("preselection_hash")
        or final_receipt.get("window_lock_id") != lock.get("window_lock_id")
        or final_receipt.get("selection_universe_sha256")
        != lock.get("selection_universe_sha256")
        or final_receipt.get("parent_fit_receipts_sha256")
        != parent_receipts_sha256
        or dict(stage_input) != expected_stage_input
        or final_receipt.get("stage_input_sha256")
        != sha256_text(canonical_json(stage_input))
        or final_receipt.get("stage_output_sha256")
        != sha256_text(canonical_json(stage_output))
        or final_receipt.get("artifact_serving_contract_sha256")
        != serving_contract_sha256
        or stage_output.get("artifact_serving_contract") != serving_contract
        or stage_output.get("artifact_serving_contract_sha256")
        != serving_contract_sha256
        or final_receipt.get("model_payload_sha256") != model_payload_sha256
        or stage_output.get("model_payload_sha256") != model_payload_sha256
        or stage_output.get("model_sha256_by_hour") != model_hashes
        or int(stage_output.get("model_count") or 0) != len(model_hashes)
        or stage_output.get("feature_schema_version")
        != model_bundle.get("feature_schema_version")
        or stage_output.get("support_sha256")
        != sha256_text(
            canonical_json(_pooled_contract_jsonable(model_bundle.get("support")))
        )
    ):
        raise ContractViolation(
            "candidate_final_fit_receipt_mismatch",
            "embedded final-refit receipt is not bound to the exact served bundle",
        )

    fit_contract = model_bundle.get("postprocess_fit_contract")
    if (
        not isinstance(fit_contract, Mapping)
        or fit_contract.get("preselection_hash") != lock.get("preselection_hash")
        or fit_contract.get("window_lock_id") != lock.get("window_lock_id")
        or list(fit_contract.get("locked_dates") or ()) != locked_dates
        or fit_contract.get("evidence_sha256") != evidence.get("evidence_sha256")
        or fit_contract.get("final_fit_receipt_sha256")
        != final_receipt.get("receipt_sha256")
        or fit_contract.get("model_payload_sha256") != model_payload_sha256
    ):
        raise ContractViolation(
            "candidate_final_fit_receipt_mismatch",
            "served postprocess contract is not bound to its embedded training evidence",
        )
    return dict(evidence)


def verify_point_in_time_selection_binding(
    artifact_payload: Mapping[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    """Verify and compact one calibration/routing locked-exclusion proof."""

    binding = artifact_payload.get("point_in_time_selection_binding")
    if not isinstance(binding, Mapping):
        raise ContractViolation(
            "candidate_selection_binding_missing",
            f"{stage} artifact has no production preselection proof",
        )
    _verify_self_hash(
        binding,
        "binding_sha256",
        "candidate_selection_binding_hash_mismatch",
    )
    locked_dates = _contiguous_locked_dates(
        binding.get("locked_dates"),
        field=f"{stage}.point_in_time_selection_binding.locked_dates",
    )
    inventory = binding.get("source_inventory")
    if not isinstance(inventory, Mapping):
        raise ContractViolation(
            "candidate_selection_binding_invalid",
            f"{stage} source inventory is missing",
        )
    unhashed_inventory = dict(inventory)
    inventory_sha256 = str(unhashed_inventory.pop("sha256", "") or "")
    entries = inventory.get("entries")
    if (
        not SHA256_RE.fullmatch(inventory_sha256)
        or inventory_sha256 != sha256_text(canonical_json(unhashed_inventory))
        or binding.get("source_folder_date_inventory_sha256")
        != inventory_sha256
        or not isinstance(entries, list)
        or not entries
        or int(inventory.get("entry_count") or -1) != len(entries)
    ):
        raise ContractViolation(
            "candidate_selection_binding_invalid",
            f"{stage} source inventory hash or entry count is invalid",
        )
    inventory_dates: set[str] = set()
    pending: list[Any] = [inventory]
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            target_date = value.get("target_date")
            if target_date not in (None, ""):
                inventory_dates.add(
                    _parse_date(
                        target_date,
                        f"{stage}.point_in_time_selection_binding.source_inventory.target_date",
                    ).isoformat()
                )
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    overlap = sorted(set(locked_dates) & inventory_dates)
    if overlap:
        raise ContractViolation(
            "locked_window_reused_for_selection",
            f"{stage} source inventory includes locked dates: {', '.join(overlap)}",
        )
    if (
        not SHA256_RE.fullmatch(str(binding.get("preselection_hash") or ""))
        or not SHA256_RE.fullmatch(str(binding.get("window_lock_id") or ""))
        or binding.get("used_for_selection") is not False
    ):
        raise ContractViolation(
            "locked_window_reused_for_selection",
            f"{stage} selection is not bound to a valid preselected exclusion window",
        )
    return {
        "preselection_hash": str(binding["preselection_hash"]),
        "window_lock_id": str(binding["window_lock_id"]),
        "locked_dates": locked_dates,
        "used_for_selection": False,
        "binding_sha256": str(binding["binding_sha256"]),
        "source_folder_date_inventory_sha256": inventory_sha256,
    }


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
    require_manifest_backed_inputs: bool = False,
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
    if require_manifest_backed_inputs:
        inputs = manifest.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            raise ContractViolation(
                "materialization_inputs_not_proof_grade",
                "manifest-backed input inventory is missing",
            )
        for index, row in enumerate(inputs):
            if not isinstance(row, Mapping):
                raise ContractViolation(
                    "materialization_inputs_not_proof_grade",
                    f"inputs[{index}] is malformed",
                )
            source_mode = str(row.get("source_mode") or "")
            common_valid = (
                SHA256_RE.fullmatch(str(row.get("manifest_hash") or ""))
                and SHA256_RE.fullmatch(str(row.get("source_file_hash") or ""))
                and SHA256_RE.fullmatch(str(row.get("parquet_file_hash") or ""))
                and SHA256_RE.fullmatch(str(row.get("event_manifest_hash") or ""))
                and str(row.get("release_id") or "").strip()
                and str(row.get("runtime_identity_key") or "").strip()
            )
            if source_mode == "validated_parquet":
                mode_valid = bool(common_valid)
            elif source_mode == "promotion_manifest_pinned_candidate_replay":
                mode_valid = bool(
                    common_valid
                    and SHA256_RE.fullmatch(
                        str(row.get("candidate_artifact_sha256") or "")
                    )
                    and SHA256_RE.fullmatch(
                        str(row.get("source_replay_manifest_sha256") or "")
                    )
                    and SHA256_RE.fullmatch(
                        str(row.get("replay_record_set_sha256") or "")
                    )
                    and SHA256_RE.fullmatch(
                        str(row.get("tape_row_set_sha256") or "")
                    )
                )
            else:
                mode_valid = False
            if not mode_valid:
                raise ContractViolation(
                    "materialization_inputs_not_proof_grade",
                    f"inputs[{index}] is not backed by a supported proof-grade manifest chain",
                )
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


def collect_parquet_selection_universe(path: str | Path) -> dict[str, Any]:
    """Recompute the candidate-independent population hash with bounded batches."""

    import pyarrow.parquet as pq

    columns = (
        "target_date",
        "market_id",
        "cutoff_or_snapshot",
        "band",
        "feature_available_at_utc",
        "prediction_made_at_utc",
        "label_quality",
        "countable",
        "claim_lane",
        "source_quality",
        "label",
    )
    parquet = pq.ParquetFile(path)
    missing = set(columns) - set(parquet.schema_arrow.names)
    if missing:
        raise ContractViolation(
            "invalid_selection_universe",
            f"Parquet selection-universe columns missing: {sorted(missing)}",
        )
    digest = hashlib.sha256()
    row_count = 0
    dates: set[str] = set()
    previous_coordinate: tuple[str, str, str, str] | None = None
    for batch in parquet.iter_batches(batch_size=65_536, columns=list(columns)):
        for raw in batch.to_pylist():
            if raw.get("claim_lane") != "weather_only" or not raw.get("countable"):
                continue
            coordinate = tuple(
                str(raw[field])
                for field in ("target_date", "market_id", "cutoff_or_snapshot", "band")
            )
            if previous_coordinate is not None and coordinate <= previous_coordinate:
                code = (
                    "duplicate_selection_coordinate"
                    if coordinate == previous_coordinate
                    else "unsorted_selection_universe"
                )
                raise ContractViolation(
                    code,
                    "production corpus must contain one sorted weather-only row per coordinate",
                )
            previous_coordinate = coordinate
            basis = {
                "target_date": str(raw["target_date"]),
                "market_id": str(raw["market_id"]),
                "cutoff_or_snapshot": str(raw["cutoff_or_snapshot"]),
                "band": str(raw["band"]),
                "feature_available_at_utc": str(raw["feature_available_at_utc"]),
                "prediction_made_at_utc": str(raw["prediction_made_at_utc"]),
                "label_quality": str(raw["label_quality"]),
                "countable": bool(raw["countable"]),
                "claim_lane": str(raw["claim_lane"]),
                "source_quality": (
                    "countable"
                    if str(raw["source_quality"]) in COUNTABLE_SOURCE_QUALITIES
                    else str(raw["source_quality"])
                ),
                "label": raw.get("label"),
            }
            digest.update(canonical_json(basis).encode("utf-8"))
            digest.update(b"\n")
            row_count += 1
            dates.add(coordinate[0])
    if not row_count:
        raise ContractViolation(
            "empty_selection_universe",
            "production corpus has no countable weather-only rows",
        )
    for value in dates:
        _parse_date(value, "selection_universe.target_date")
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "hash_algorithm": "sha256",
        "canonicalization": "canonical_json_lines",
        "sha256": digest.hexdigest(),
        "row_count": row_count,
        "fleet_dates": sorted(dates),
        "candidate_dependent_fields_excluded": list(
            SELECTION_UNIVERSE_EXCLUDED_FIELDS
        ),
    }


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

    selection_contract = payload.get("candidate_selection_contract")
    if require_fit_receipts:
        if not isinstance(selection_contract, Mapping):
            raise ContractViolation(
                "invalid_candidate_selection_contract",
                "production validation plan is missing its locked selection contract",
            )
        locked_selection_dates = tuple(
            str(value)
            for value in selection_contract.get("locked_evaluation_dates") or ()
        )
        locked_set = set(locked_selection_dates)
        if (
            selection_contract.get("status") != "PASS"
            or len(locked_selection_dates) != 14
            or len(locked_set) != 14
            or selection_contract.get("locked_dates_used_for_selection") is not False
            or selection_contract.get("candidate_selection_permission") != "forbidden"
            or not str(selection_contract.get("window_lock_id") or "")
        ):
            raise ContractViolation(
                "invalid_candidate_selection_contract",
                "production candidate selection lock is incomplete",
            )
        for value in locked_selection_dates:
            _parse_date(value, "candidate_selection_contract.locked_date")
        if not locked_set <= set(fleet_dates):
            raise ContractViolation(
                "invalid_candidate_selection_contract",
                "locked selection dates escape the frozen corpus",
            )
        if any(
            locked_set
            & set(
                fold["train_dates"]
                + fold["embargo_dates"]
                + fold["validation_dates"]
            )
            for fold in scopes.values()
        ):
            raise ContractViolation(
                "locked_window_reused_for_selection",
                "locked evaluation dates appear in a model-selection fold",
            )
        locked_at = _parse_utc(
            selection_contract.get("window_locked_at_utc"),
            "candidate_selection_contract.window_locked_at_utc",
        )
        plan_generated = _parse_utc(
            payload.get("generated_at_utc"), "validation_plan.generated_at_utc"
        )
        if locked_at > plan_generated:
            raise ContractViolation(
                "window_locked_after_candidate_selection",
                "evaluation window was locked after the validation plan was selected",
            )
        resources = payload.get("resource_contract")
        if (
            not isinstance(resources, Mapping)
            or resources.get("corpus_read_mode") != "market_day_streaming"
            or int(resources.get("raw_market_days_retained_at_once") or 0) != 1
            or not 0 < int(resources.get("private_memory_budget_bytes") or 0) <= 8 * 1024**3
            or not 0 < int(resources.get("max_market_days") or 0) <= 60
            or not 0 < int(resources.get("max_fold_scopes") or 0) <= 128
        ):
            raise ContractViolation(
                "invalid_point_in_time_resource_contract",
                "production point-in-time resource bounds are missing or unsafe",
            )

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
    if require_fit_receipts and (
        tuple(stages) != REQUIRED_FIT_STAGES
        or receipt_contract.get("payload_binding_required") is not True
        or receipt_contract.get("payload_hash_algorithm")
        != FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM
        or receipt_contract.get("payload_canonicalization")
        != FIT_RECEIPT_PAYLOAD_CANONICALIZATION
        or tuple(receipt_contract.get("stage_order") or ()) != REQUIRED_FIT_STAGES
    ):
        raise ContractViolation(
            "invalid_fit_receipts",
            "production fit receipt stage/output binding contract is incomplete",
        )
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
        has_payload_binding = any(
            field in receipt
            for field in (
                "stage_input_payload",
                "stage_input_sha256",
                "stage_output_payload",
                "stage_output_sha256",
            )
        )
        if require_fit_receipts or has_payload_binding:
            verify_output_bound_fit_receipt(receipt)
        by_key[key] = receipt
    expected_keys = {(scope, stage) for scope in scopes for stage in stages}
    if require_fit_receipts and set(by_key) != expected_keys:
        raise ContractViolation("invalid_fit_receipts", "fold/stage receipt coverage incomplete")
    if require_fit_receipts:
        for scope in scopes:
            prior: Mapping[str, Any] | None = None
            for stage in stages:
                receipt = by_key[(scope, stage)]
                input_payload = receipt["stage_input_payload"]
                upstream = input_payload.get("upstream_stage_output_sha256")
                if prior is None:
                    if upstream is not None:
                        raise ContractViolation(
                            "fit_receipt_stage_chain_mismatch",
                            f"first fit stage declares an upstream output: {(scope, stage)}",
                        )
                elif (
                    upstream != prior.get("stage_output_sha256")
                    or receipt.get("fit_input_sha256")
                    != prior.get("fit_output_sha256")
                    or receipt.get("validation_input_sha256")
                    != prior.get("validation_output_sha256")
                    or receipt.get("fit_row_count")
                    != prior.get("fit_output_row_count")
                    or receipt.get("validation_row_count")
                    != prior.get("validation_output_row_count")
                ):
                    raise ContractViolation(
                        "fit_receipt_stage_chain_mismatch",
                        f"fit stage input is not bound to the prior output: {(scope, stage)}",
                    )
                prior = receipt
    return dict(payload)


def verify_streaming_evaluation_payload(
    payload: Mapping[str, Any],
    *,
    expected_candidate_id: str | None = None,
    expected_release_id: str | None = None,
    expected_corpus_sha256: str | None = None,
    expected_selection_universe_sha256: str | None = None,
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
    if expected_selection_universe_sha256 is not None and (
        not isinstance(input_row, Mapping)
        or input_row.get("selection_universe_sha256")
        != expected_selection_universe_sha256
    ):
        raise ContractViolation(
            "streaming_evaluation_corpus_mismatch",
            "selection-universe hash mismatch",
        )
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
    if "input_kind" in lock:
        lock_basis["input_kind"] = lock.get("input_kind")
    if lock.get("window_lock_id") != sha256_text(canonical_json(lock_basis)):
        raise ContractViolation("invalid_evaluation_window_lock", "window lock hash mismatch")
    if _parse_utc(lock.get("generated_at_utc"), "window_lock.generated_at_utc") > started:
        raise ContractViolation(
            "window_selected_after_evaluation", "evaluation window was selected after scoring began"
        )
    target_dates = tuple(str(value) for value in lock.get("target_dates") or ())
    lock_input_kind = str(lock.get("input_kind") or "corpus_sha256")
    if lock_input_kind == "corpus_sha256":
        if (
            expected_corpus_sha256 is not None
            and lock.get("input_sha256") != expected_corpus_sha256
        ):
            raise ContractViolation(
                "invalid_evaluation_window_lock", "window corpus mismatch"
            )
    elif lock_input_kind == "selection_universe_sha256":
        if (
            expected_selection_universe_sha256 is not None
            and lock.get("input_sha256")
            != expected_selection_universe_sha256
        ):
            raise ContractViolation(
                "invalid_evaluation_window_lock",
                "window selection-universe mismatch",
            )
    else:
        raise ContractViolation(
            "invalid_evaluation_window_lock", "window input kind is unsupported"
        )
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
            or lock_input_kind != "selection_universe_sha256"
            or not SHA256_RE.fullmatch(
                str(expected_selection_universe_sha256 or "")
            )
        ):
            raise ContractViolation("invalid_evaluation_window_lock", "production lock incomplete")
        parsed = [_parse_date(value, "window_lock.target_date") for value in target_dates]
        if parsed != [parsed[0] + timedelta(days=offset) for offset in range(14)]:
            raise ContractViolation("invalid_evaluation_window_lock", "window is not contiguous")
        if lock.get("window_start") != target_dates[0] or lock.get("window_end") != target_dates[-1]:
            raise ContractViolation("invalid_evaluation_window_lock", "window bounds mismatch")
        if max_age_days is not None:
            target_age_days = (
                (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
                - parsed[-1]
            ).days
            if not 0 <= target_age_days <= max_age_days:
                raise ContractViolation(
                    "stale_streaming_evaluation_target_window",
                    "evaluation target window is stale or future-dated",
                )

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


def _normalized_route_selection(payload: Mapping[str, Any]) -> dict[str, Any]:
    promote = sorted({str(value) for value in payload.get("promote_markets") or ()})
    shadow = sorted({str(value) for value in payload.get("shadow_markets") or ()})
    blocked = sorted({str(value) for value in payload.get("blocked_markets") or ()})
    verdict = "blocked" if blocked else "promote_ready" if promote else "shadow"
    normalized = {
        "verdict": verdict,
        "promote_markets": promote,
        "shadow_markets": shadow,
        "blocked_markets": blocked,
    }
    if dict(payload) != normalized:
        raise ContractViolation(
            "candidate_route_selection_mismatch",
            "candidate route decision is not canonical",
        )
    return normalized


def _verify_candidate_training_graph(
    graph: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    selection_universe_sha256: str,
    expected_candidate_id: str,
    expected_release_id: str,
    expected_candidate_artifact_sha256: str | None = None,
    expected_calibration_artifact_sha256: str | None = None,
    expected_routing_artifact_sha256: str | None = None,
    expected_route_selection: Mapping[str, Any] | None = None,
    expected_training_evidence: Mapping[str, Any] | None = None,
    expected_selection_stage_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify the immutable bridge from real trainer output to production scoring."""

    if (
        graph.get("schema_version") != CANDIDATE_TRAINING_GRAPH_SCHEMA_VERSION
        or graph.get("artifact_type") != "point_in_time_candidate_training_graph"
        or graph.get("status") != "PASS"
        or graph.get("candidate_id") != expected_candidate_id
        or graph.get("release_id") != expected_release_id
        or graph.get("locked_dates_used_for_selection") is not False
    ):
        raise ContractViolation(
            "invalid_candidate_training_graph",
            "candidate training graph identity or selection contract is invalid",
        )
    _verify_self_hash(
        graph,
        "graph_hash",
        "candidate_training_graph_hash_mismatch",
    )
    graph_hash = str(graph.get("graph_hash") or "")
    evaluation_binding = evaluation.get("contract_binding")
    if (
        manifest.get("candidate_training_graph_hash") != graph_hash
        or manifest.get("candidate_training_graph") != graph
        or plan.get("candidate_training_graph_hash") != graph_hash
        or plan.get("candidate_training_graph") != graph
        or not isinstance(evaluation_binding, Mapping)
        or evaluation_binding.get("candidate_training_graph_hash") != graph_hash
    ):
        raise ContractViolation(
            "candidate_training_graph_mismatch",
            "materialization, plan, and evaluation do not share one training graph",
        )

    if (
        not SHA256_RE.fullmatch(selection_universe_sha256)
        or graph.get("selection_universe_sha256") != selection_universe_sha256
        or evaluation_binding.get("selection_universe_sha256")
        != selection_universe_sha256
    ):
        raise ContractViolation(
            "candidate_training_population_mismatch",
            "candidate training graph is not bound to the replayed selection universe",
        )
    selection_contract = plan.get("candidate_selection_contract")
    evaluation_lock = evaluation.get("window_lock")
    if not isinstance(selection_contract, Mapping) or not isinstance(
        evaluation_lock, Mapping
    ):
        raise ContractViolation(
            "candidate_training_preselection_mismatch",
            "candidate graph is missing its preselected evaluation lock",
        )
    preselection_hash = str(graph.get("preselection_hash") or "")
    locked_values = list(evaluation_lock.get("target_dates") or ())
    stage_bindings = graph.get("selection_stage_bindings")
    if (
        not isinstance(stage_bindings, Mapping)
        or set(stage_bindings) != {"calibration", "routing"}
        or graph.get("selection_stage_bindings_sha256")
        != sha256_text(canonical_json(stage_bindings))
        or any(
            not isinstance(binding, Mapping)
            or binding.get("preselection_hash") != preselection_hash
            or binding.get("window_lock_id") != graph.get("window_lock_id")
            or list(binding.get("locked_dates") or ()) != locked_values
            or binding.get("used_for_selection") is not False
            or not SHA256_RE.fullmatch(str(binding.get("binding_sha256") or ""))
            or not SHA256_RE.fullmatch(
                str(binding.get("source_folder_date_inventory_sha256") or "")
            )
            for binding in stage_bindings.values()
        )
    ):
        raise ContractViolation(
            "locked_window_reused_for_selection",
            "calibration or routing selection is not bound to the locked exclusion",
        )
    if expected_selection_stage_bindings is not None:
        normalized_expected_bindings = {
            str(stage): dict(binding)
            for stage, binding in expected_selection_stage_bindings.items()
            if isinstance(binding, Mapping)
        }
        if (
            set(normalized_expected_bindings) != {"calibration", "routing"}
            or dict(stage_bindings) != normalized_expected_bindings
        ):
            raise ContractViolation(
                "candidate_selection_binding_mismatch",
                "candidate training graph selection bindings differ from the exact fitted artifacts",
            )
    if (
        not SHA256_RE.fullmatch(preselection_hash)
        or graph.get("window_lock_id") != evaluation_lock.get("window_lock_id")
        or selection_contract.get("window_lock_id")
        != evaluation_lock.get("window_lock_id")
        or evaluation_lock.get("input_kind") != "selection_universe_sha256"
        or evaluation_lock.get("input_sha256") != selection_universe_sha256
        or preselection_hash != manifest.get("preselection_hash")
    ):
        raise ContractViolation(
            "candidate_training_preselection_mismatch",
            "candidate graph does not preserve the preselected evaluation lock",
        )
    locked_at = _parse_utc(
        selection_contract.get("window_locked_at_utc"),
        "candidate_selection_contract.window_locked_at_utc",
    )
    trained_at = _parse_utc(
        graph.get("training_evidence_generated_at_utc"),
        "candidate_training_graph.training_evidence_generated_at_utc",
    )
    plan_generated = _parse_utc(
        plan.get("generated_at_utc"), "validation_plan.generated_at_utc"
    )
    if not locked_at <= trained_at <= plan_generated:
        raise ContractViolation(
            "candidate_training_time_order_invalid",
            "the selection lock, training evidence, and validation plan are out of order",
        )

    expected_folds_hash = sha256_text(canonical_json(plan.get("folds") or []))
    expected_receipts_hash = sha256_text(
        canonical_json(
            sorted(
                str(receipt.get("receipt_sha256") or "")
                for receipt in plan.get("fit_receipts") or ()
            )
        )
    )
    if (
        graph.get("folds_sha256") != expected_folds_hash
        or graph.get("fit_receipts_sha256") != expected_receipts_hash
        or not SHA256_RE.fullmatch(
            str(graph.get("final_fit_receipt_sha256") or "")
        )
        or not SHA256_RE.fullmatch(
            str(graph.get("training_evidence_sha256") or "")
        )
    ):
        raise ContractViolation(
            "candidate_training_evidence_mismatch",
            "folds or fit receipts differ from the real trainer evidence",
        )
    if expected_training_evidence is not None:
        evidence_lock = expected_training_evidence.get("preselection_lock")
        evidence_folds = expected_training_evidence.get("folds")
        evidence_receipts = expected_training_evidence.get("fit_receipts")
        evidence_final_receipt = expected_training_evidence.get("final_fit_receipt")
        if (
            not isinstance(evidence_lock, Mapping)
            or not isinstance(evidence_folds, list)
            or not isinstance(evidence_receipts, list)
            or not isinstance(evidence_final_receipt, Mapping)
            or plan.get("folds") != evidence_folds
            or plan.get("fit_receipts") != evidence_receipts
            or graph.get("preselection_hash")
            != evidence_lock.get("preselection_hash")
            or graph.get("window_lock_id") != evidence_lock.get("window_lock_id")
            or graph.get("selection_universe_sha256")
            != evidence_lock.get("selection_universe_sha256")
            or graph.get("training_evidence_sha256")
            != expected_training_evidence.get("evidence_sha256")
            or graph.get("training_evidence_generated_at_utc")
            != expected_training_evidence.get("generated_at_utc")
            or graph.get("folds_sha256")
            != sha256_text(canonical_json(evidence_folds))
            or graph.get("fit_receipts_sha256")
            != sha256_text(
                canonical_json(
                    sorted(
                        str(receipt.get("receipt_sha256") or "")
                        for receipt in evidence_receipts
                    )
                )
            )
            or graph.get("final_fit_receipt_sha256")
            != evidence_final_receipt.get("receipt_sha256")
        ):
            raise ContractViolation(
                "candidate_training_evidence_mismatch",
                "candidate training graph or validation plan differs from the exact model bundle evidence",
            )

    artifacts = graph.get("candidate_artifacts")
    if not isinstance(artifacts, Mapping) or any(
        not SHA256_RE.fullmatch(str(artifacts.get(key) or ""))
        for key in ("model_sha256", "calibration_sha256", "routing_sha256")
    ):
        raise ContractViolation(
            "invalid_candidate_training_graph",
            "candidate artifact hash inventory is incomplete",
        )
    expected_hashes = {
        "model_sha256": expected_candidate_artifact_sha256,
        "calibration_sha256": expected_calibration_artifact_sha256,
        "routing_sha256": expected_routing_artifact_sha256,
    }
    if any(
        expected is not None and artifacts.get(key) != expected
        for key, expected in expected_hashes.items()
    ):
        raise ContractViolation(
            "candidate_training_artifact_mismatch",
            "candidate training graph names a different fitted artifact",
        )
    if evaluation.get("candidate_artifact_sha256") != artifacts.get(
        "model_sha256"
    ):
        raise ContractViolation(
            "candidate_training_artifact_mismatch",
            "streaming evaluation did not score the graph's exact model artifact",
        )

    route_selection = graph.get("route_selection")
    if not isinstance(route_selection, Mapping):
        raise ContractViolation(
            "candidate_route_selection_mismatch",
            "candidate route decision is missing",
        )
    normalized_route = _normalized_route_selection(route_selection)
    if (
        graph.get("route_selection_sha256")
        != sha256_text(canonical_json(normalized_route))
        or (
            expected_route_selection is not None
            and normalized_route
            != _normalized_route_selection(expected_route_selection)
        )
    ):
        raise ContractViolation(
            "candidate_route_selection_mismatch",
            "candidate route decision is not bound to the training graph",
        )

    source_manifest_sha = str(graph.get("source_replay_manifest_sha256") or "")
    source_corpus_hash = str(graph.get("source_replay_corpus_hash") or "")
    inputs = manifest.get("inputs")
    if (
        not SHA256_RE.fullmatch(source_manifest_sha)
        or not SHA256_RE.fullmatch(source_corpus_hash)
        or not isinstance(inputs, list)
        or not inputs
        or any(
            not isinstance(row, Mapping)
            or row.get("source_mode")
            != "promotion_manifest_pinned_candidate_replay"
            or row.get("candidate_artifact_sha256")
            != artifacts.get("model_sha256")
            or row.get("source_replay_manifest_sha256") != source_manifest_sha
            or row.get("manifest_hash") != source_corpus_hash
            or row.get("release_id") != expected_release_id
            or not str(row.get("target_date") or "")
            or not str(row.get("market_id") or "")
            for row in inputs
        )
    ):
        raise ContractViolation(
            "candidate_replay_provenance_mismatch",
            "fresh replay inputs are not pinned to the graph's source and model",
        )

    resources = plan.get("resource_contract")
    bounds = manifest.get("streaming_bounds")
    if not isinstance(resources, Mapping) or not isinstance(bounds, Mapping):
        raise ContractViolation(
            "invalid_point_in_time_resource_contract",
            "production resource declarations are missing",
        )
    try:
        declared_scopes = int(resources.get("max_fold_scopes") or 0)
        observed_scopes = sum(
            1 + len(row.get("inner") or ()) for row in plan.get("folds") or ()
        )
        declared_days = int(resources.get("max_market_days") or 0)
        declared_rows = int(resources.get("max_rows_per_market_day") or 0)
        bounded_days = int(bounds.get("max_market_days") or 0)
        bounded_rows = int(bounds.get("max_rows_per_market_day") or 0)
        observed_days = int(bounds.get("observed_market_days") or 0)
        observed_rows = int(
            bounds.get("observed_peak_rows_per_market_day") or 0
        )
        input_row_counts = [int(row.get("source_row_count") or 0) for row in inputs]
        derived_rows = int(
            ((manifest.get("derived_artifact") or {}).get("row_count")) or 0
        )
    except (TypeError, ValueError) as exc:
        raise ContractViolation(
            "invalid_point_in_time_resource_contract",
            "production resource counts are malformed",
        ) from exc
    input_coordinates = {
        (str(row.get("target_date") or ""), str(row.get("market_id") or ""))
        for row in inputs
        if isinstance(row, Mapping)
    }
    if (
        int(resources.get("observed_fold_scopes") or 0) != observed_scopes
        or observed_scopes <= 0
        or observed_scopes > declared_scopes
        or not 0 < declared_days <= PRODUCTION_MAX_MARKET_DAYS
        or not 0 < declared_rows <= PRODUCTION_MAX_ROWS_PER_MARKET_DAY
        or int(resources.get("observed_market_days") or 0) != observed_days
        or int(resources.get("observed_peak_rows_per_market_day") or 0)
        != observed_rows
        or int(bounds.get("raw_market_days_retained_at_once") or 0) != 1
        or bounded_days != declared_days
        or bounded_rows != declared_rows
        or observed_days <= 0
        or observed_rows <= 0
        or observed_days > declared_days
        or observed_rows > declared_rows
        or observed_days != len(inputs)
        or len(input_coordinates) != len(inputs)
        or any(value <= 0 for value in input_row_counts)
        or observed_rows != max(input_row_counts, default=0)
        or derived_rows != sum(input_row_counts)
    ):
        raise ContractViolation(
            "invalid_point_in_time_resource_contract",
            "observed production replay or fold usage exceeds its declared bound",
        )
    return dict(graph)


def verify_production_point_in_time_artifacts(
    *,
    corpus_path: str | Path,
    materialization_manifest_path: str | Path,
    validation_plan_path: str | Path,
    streaming_evaluation_path: str | Path,
    expected_candidate_id: str,
    expected_release_id: str,
    expected_candidate_artifact_sha256: str | None = None,
    expected_calibration_artifact_sha256: str | None = None,
    expected_routing_artifact_sha256: str | None = None,
    expected_route_selection: Mapping[str, Any] | None = None,
    expected_training_evidence: Mapping[str, Any] | None = None,
    expected_selection_stage_bindings: Mapping[str, Mapping[str, Any]] | None = None,
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
        require_manifest_backed_inputs=True,
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
    graph = manifest.get("candidate_training_graph")
    if not isinstance(graph, Mapping):
        raise ContractViolation(
            "invalid_candidate_training_graph",
            "production materialization is missing the real trainer graph",
        )
    if inspect_corpus_parquet:
        selection_universe = collect_parquet_selection_universe(corpus_path)
        if set(selection_universe["fleet_dates"]) != set(fleet_dates):
            raise ContractViolation(
                "candidate_training_population_mismatch",
                "the countable selection universe does not cover the frozen fleet dates",
            )
        selection_universe_sha = str(selection_universe["sha256"])
    else:
        selection_universe_sha = str(graph.get("selection_universe_sha256") or "")
    verified_graph = _verify_candidate_training_graph(
        graph,
        manifest=manifest,
        plan=plan,
        evaluation=evaluation,
        selection_universe_sha256=selection_universe_sha,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_candidate_artifact_sha256=expected_candidate_artifact_sha256,
        expected_calibration_artifact_sha256=expected_calibration_artifact_sha256,
        expected_routing_artifact_sha256=expected_routing_artifact_sha256,
        expected_route_selection=expected_route_selection,
        expected_training_evidence=expected_training_evidence,
        expected_selection_stage_bindings=expected_selection_stage_bindings,
    )
    verify_streaming_evaluation_payload(
        evaluation,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_corpus_sha256=corpus_sha,
        expected_selection_universe_sha256=selection_universe_sha,
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
    if (
        not locked_dates <= set(fleet_dates)
        or (evaluation.get("window_lock") or {}).get("window_end")
        != max(fleet_dates)
    ):
        raise ContractViolation("streaming_evaluation_corpus_mismatch", "locked dates escape corpus")
    selection_contract = plan.get("candidate_selection_contract") or {}
    evaluation_lock = evaluation.get("window_lock") or {}
    if (
        set(selection_contract.get("locked_evaluation_dates") or ()) != locked_dates
        or selection_contract.get("window_lock_id")
        != evaluation_lock.get("window_lock_id")
        or selection_contract.get("window_locked_at_utc")
        != evaluation_lock.get("generated_at_utc")
    ):
        raise ContractViolation(
            "locked_window_reused_for_selection",
            "candidate-selection exclusion is not bound to the evaluated window",
        )
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
        "fit_receipt_output_binding_verified": True,
        "candidate_training_graph_hash": verified_graph["graph_hash"],
        "candidate_artifacts": dict(verified_graph["candidate_artifacts"]),
        "training_evidence_identity": {
            "evidence_sha256": verified_graph["training_evidence_sha256"],
            "generated_at_utc": verified_graph[
                "training_evidence_generated_at_utc"
            ],
            "folds_sha256": verified_graph["folds_sha256"],
            "fit_receipts_sha256": verified_graph["fit_receipts_sha256"],
            "final_fit_receipt_sha256": verified_graph[
                "final_fit_receipt_sha256"
            ],
        },
        "selection_stage_bindings": {
            str(stage): dict(binding)
            for stage, binding in verified_graph[
                "selection_stage_bindings"
            ].items()
        },
        "selection_universe_sha256": selection_universe_sha,
        "corpus_structure_reverified": inspect_corpus_parquet,
        "verification_mode": (
            "candidate_build_full_parquet_inspection"
            if inspect_corpus_parquet
            else "immutable_release_hash_graph_reverification"
        ),
    }
