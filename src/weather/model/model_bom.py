"""Deterministic, content-bound bill of materials for weather-model releases.

The BOM describes the runtime serving graph, serialized estimator structure,
and artifact-specific training lineage.  It contains no absolute paths,
timestamps, branch names, or ambient repository lookups.  Release and serving
callers supply every binding explicitly and verify it again at their trust
boundaries.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from weather.model.model_bom_contracts import (
    RUNTIME_LANE_CONTRACTS,
    SERVING_GRAPH_EDGES,
    SERVING_STAGE_CONTRACTS,
)
from weather.model.model_contracts import FORECAST_CONTEXT_SOURCE_ROLES


MODEL_BOM_SCHEMA_VERSION = "weather_model_bill_of_materials_v0.1"
MODEL_BOM_COMPLETE = "COMPLETE"
MODEL_BOM_INCOMPLETE = "INCOMPLETE"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORECAST_CONTEXT_NAMES = tuple(sorted(FORECAST_CONTEXT_SOURCE_ROLES))
_LINEAGE_DISPOSITIONS = {
    "direct_fit_output",
    "deterministic_derivative",
    "verified_parent_inheritance",
    "missing",
}


class ModelBomError(ValueError):
    """A BOM cannot be trusted or disagrees with materialized state."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, child in sorted(value.items(), key=lambda row: str(row[0])):
            normalized_key = str(key)
            if normalized_key in normalized:
                raise ModelBomError(
                    "model BOM mapping key collision after normalization: "
                    f"{normalized_key!r}"
                )
            normalized[normalized_key] = _json_safe(child)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(child) for child in value]
    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ModelBomError(
        "model BOM value is not canonically serializable: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def canonical_payload_sha256(
    payload: Mapping[str, Any], *, omit: Sequence[str] = ()
) -> str:
    omitted = set(omit)
    normalized = {
        str(key): _json_safe(value)
        for key, value in payload.items()
        if key not in omitted
    }
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_release_runtime_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Project a manifest runtime identity onto its path-stable source witness."""

    stable_keys = (
        "schema_version",
        "source_fingerprint",
        "source_file_count",
        "identity_source",
        "python_version",
        "source_scope",
        "source_scope_files",
    )
    return {
        key: _json_safe(identity[key])
        for key in stable_keys
        if key in identity
    }


def feature_order_sha256(feature_names: Sequence[str]) -> str:
    return hashlib.sha256(
        "\n".join(str(value) for value in feature_names).encode("utf-8")
    ).hexdigest()


def _class_name(value: Any) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _attribute(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _normalized_sequence(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(child) for child in value]
    return None


def _nonzero(value: Any) -> bool:
    try:
        return bool(abs(float(value)) > 0.0)
    except (TypeError, ValueError):
        return False


def _structural_feature_use(
    estimator: Any, feature_names: Sequence[str]
) -> dict[str, Any]:
    """Return fitted-feature use without silently trusting unreadable trees."""

    names = [str(value) for value in feature_names]
    used: set[int] = set()
    methods: list[str] = []
    errors: list[str] = []

    predictors = _attribute(estimator, "_predictors")
    if predictors is not None:
        readable_arrays = 0
        try:
            for iteration in predictors:
                for predictor in iteration:
                    nodes = getattr(predictor, "nodes", None)
                    dtype_names = tuple(
                        getattr(getattr(nodes, "dtype", None), "names", ()) or ()
                    )
                    if nodes is None or "feature_idx" not in dtype_names:
                        errors.append("hist_gradient_boosting_nodes_missing_fields")
                        continue
                    readable_arrays += 1
                    for node in nodes:
                        is_leaf = (
                            bool(node["is_leaf"]) if "is_leaf" in dtype_names else False
                        )
                        index = int(node["feature_idx"])
                        if not is_leaf and index >= 0:
                            used.add(index)
            if readable_arrays:
                methods.append("hist_gradient_boosting_predictor_nodes")
            else:
                errors.append("hist_gradient_boosting_predictors_unreadable")
        except (IndexError, KeyError, TypeError, ValueError, AttributeError):
            errors.append("hist_gradient_boosting_predictor_nodes_unreadable")

    coefficients = _attribute(estimator, "coef_")
    if coefficients is not None:
        rows = coefficients.tolist() if hasattr(coefficients, "tolist") else coefficients
        if isinstance(rows, Sequence) and not isinstance(
            rows, (str, bytes, bytearray)
        ):
            flattened = list(rows)
            if flattened and isinstance(flattened[0], Sequence) and not isinstance(
                flattened[0], (str, bytes, bytearray)
            ):
                flattened = [value for row in flattened for value in row]
            width = len(names)
            if width and len(flattened) >= width and len(flattened) % width == 0:
                for index in range(width):
                    if any(
                        _nonzero(flattened[offset])
                        for offset in range(index, len(flattened), width)
                    ):
                        used.add(index)
                methods.append("nonzero_linear_coefficients")
            else:
                errors.append("linear_coefficient_width_mismatch")

    importances = _normalized_sequence(_attribute(estimator, "feature_importances_"))
    if importances is not None:
        if len(importances) != len(names):
            errors.append("feature_importance_width_mismatch")
        else:
            used.update(
                index for index, value in enumerate(importances) if _nonzero(value)
            )
            methods.append("nonzero_feature_importances")

    tree = _attribute(estimator, "tree_")
    tree_features = (
        _normalized_sequence(_attribute(tree, "feature"))
        if tree is not None
        else None
    )
    if tree_features is not None:
        try:
            used.update(int(value) for value in tree_features if int(value) >= 0)
            methods.append("tree_feature_indices")
        except (TypeError, ValueError):
            errors.append("tree_feature_indices_unreadable")

    valid = sorted(index for index in used if 0 <= index < len(names))
    unknown = sorted(index for index in used if index < 0 or index >= len(names))
    if errors:
        status = "UNREADABLE"
    elif unknown:
        status = "INCONSISTENT"
    elif methods:
        status = "COMPLETE"
    else:
        status = "NOT_EXPOSED"
    return {
        "status": status,
        "methods": sorted(set(methods)),
        "errors": sorted(set(errors)),
        "used_feature_indices": valid,
        "used_feature_names": [names[index] for index in valid],
        "unused_feature_names": (
            [name for index, name in enumerate(names) if index not in set(valid)]
            if status == "COMPLETE"
            else None
        ),
        "unknown_feature_indices": unknown,
        "interpretation": (
            "exact_exposed_structure"
            if status == "COMPLETE"
            else "learned_use_not_claimed"
        ),
    }


def summarize_estimator_structure(
    estimator: Any, feature_names: Sequence[str]
) -> dict[str, Any]:
    """Describe a fitted estimator and its exact stored feature order."""

    names = [str(value) for value in feature_names]
    missing: list[str] = []
    if not names:
        missing.append("feature_names")
    if len(names) != len(set(names)):
        missing.append("feature_names:duplicate")
    if estimator is None:
        missing.append("estimator")

    n_features = _attribute(estimator, "n_features_in_") if estimator is not None else None
    try:
        n_features = int(n_features) if n_features is not None else None
    except (TypeError, ValueError):
        n_features = None
    if n_features is None:
        missing.append("estimator.n_features_in_")
    elif n_features != len(names):
        missing.append(
            f"estimator.n_features_in_:expected={len(names)}:actual={n_features}"
        )

    fitted_names = _normalized_sequence(
        _attribute(estimator, "feature_names_in_") if estimator is not None else None
    )
    if fitted_names is not None:
        fitted_names = [str(value) for value in fitted_names]
        if fitted_names != names:
            missing.append("estimator.feature_names_in_:order_mismatch")

    structural_attributes: dict[str, Any] = {}
    for name in (
        "classes_",
        "n_iter_",
        "n_trees_per_iteration_",
        "max_iter",
        "learning_rate",
        "max_leaf_nodes",
        "max_depth",
        "min_samples_leaf",
        "l2_regularization",
        "max_bins",
        "categorical_features",
        "interaction_cst",
        "monotonic_cst",
    ):
        raw = _attribute(estimator, name) if estimator is not None else None
        if raw is not None:
            structural_attributes[name] = _json_safe(raw)

    feature_use = _structural_feature_use(estimator, names)
    if feature_use["status"] in {"UNREADABLE", "INCONSISTENT"}:
        missing.append(f"structural_feature_use:{feature_use['status'].lower()}")
    structure = {
        "estimator_class": _class_name(estimator) if estimator is not None else None,
        "feature_names": names,
        "feature_count": len(names),
        "feature_order_sha256": feature_order_sha256(names),
        "n_features_in": n_features,
        "feature_names_in": fitted_names,
        "structural_attributes": structural_attributes,
        "structural_feature_use": feature_use,
        "status": MODEL_BOM_COMPLETE if not missing else MODEL_BOM_INCOMPLETE,
        "missing_entries": sorted(set(missing)),
    }
    structure["structure_sha256"] = canonical_payload_sha256(
        structure, omit=("structure_sha256",)
    )
    return structure


def summarize_hourly_model_mapping(
    models: Mapping[Any, Any], *, model_key: str = "model"
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    missing: list[str] = []
    for raw_hour, raw_model in sorted(models.items(), key=lambda row: str(row[0])):
        hour = str(raw_hour)
        if hour in summaries:
            raise ModelBomError(
                f"hourly model key collision after normalization: {hour!r}"
            )
        if not isinstance(raw_model, Mapping):
            summaries[hour] = summarize_estimator_structure(None, ())
            missing.append(f"{hour}:model_mapping")
            continue
        summary = summarize_estimator_structure(
            raw_model.get(model_key), raw_model.get("feature_names") or ()
        )
        summaries[hour] = summary
        missing.extend(f"{hour}:{entry}" for entry in summary["missing_entries"])
    if not summaries:
        missing.append("hourly_models")
    return {
        "models": summaries,
        "status": MODEL_BOM_COMPLETE if not missing else MODEL_BOM_INCOMPLETE,
        "missing_entries": sorted(set(missing)),
    }


def coefficient_model_mapping(payload: Mapping[Any, Any]) -> dict[str, Any]:
    """Adapt hash-bound JSON coefficient artifacts to estimator summaries."""

    nodes: dict[str, Any] = {}
    for raw_hour, raw_row in sorted(payload.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_row, Mapping):
            continue
        names = [str(value) for value in raw_row.get("feature_names") or ()]
        coefficients = raw_row.get("coef")
        rows = (
            list(coefficients)
            if isinstance(coefficients, Sequence)
            and not isinstance(coefficients, (str, bytes, bytearray))
            else []
        )
        if rows and isinstance(rows[0], Sequence) and not isinstance(
            rows[0], (str, bytes, bytearray)
        ):
            width = len(rows[0])
        else:
            width = len(rows)
        nodes[str(raw_hour)] = {
            "feature_names": names,
            "model": {
                "n_features_in_": width,
                "feature_names_in_": names,
                "coef_": coefficients,
                "classes_": raw_row.get("classes"),
            },
        }
    return nodes


def _artifact_record(role: str, raw: Any) -> tuple[dict[str, Any], list[str]]:
    row = dict(raw) if isinstance(raw, Mapping) else {}
    path = str(row.get("path") or "")
    kind = str(row.get("kind") or "")
    sha256 = str(row.get("sha256") or "")
    byte_count = row.get("bytes")
    missing: list[str] = []
    if not path:
        missing.append(f"artifacts.{role}.path")
    elif (
        "\\" in path
        or PurePosixPath(path).is_absolute()
        or bool(re.match(r"^[A-Za-z]:/", path))
        or ".." in PurePosixPath(path).parts
        or PurePosixPath(path).as_posix() != path
    ):
        missing.append(f"artifacts.{role}.path:not_candidate_relative")
    if not kind:
        missing.append(f"artifacts.{role}.kind")
    if not _SHA256_RE.fullmatch(sha256):
        missing.append(f"artifacts.{role}.sha256")
    if not isinstance(byte_count, int) or byte_count < 0:
        missing.append(f"artifacts.{role}.bytes")
    return {
        "role": role,
        "path": path,
        "kind": kind,
        "sha256": sha256,
        "bytes": byte_count,
    }, missing


def _evidence_record(section: str, raw: Any) -> tuple[dict[str, Any], list[str]]:
    row = _json_safe(raw) if isinstance(raw, Mapping) else {}
    identity = str(row.get("identity_sha256") or row.get("sha256") or "")
    status = str(row.get("status") or "")
    binding = row.get("binding")
    missing: list[str] = []
    if status not in {MODEL_BOM_COMPLETE, MODEL_BOM_INCOMPLETE}:
        missing.append(f"{section}.status:invalid")
    elif status != MODEL_BOM_COMPLETE:
        missing.append(f"{section}.status")
    if not isinstance(binding, Mapping) or not binding:
        missing.append(f"{section}.binding")
        binding = {}
    binding_sha = canonical_payload_sha256(binding) if binding else ""
    if not _SHA256_RE.fullmatch(identity):
        missing.append(f"{section}.identity_sha256")
    elif identity != binding_sha:
        missing.append(f"{section}.identity_sha256:binding_mismatch")
    declared = row.get("missing_entries")
    if isinstance(declared, list):
        missing.extend(
            f"{section}.{entry}" for entry in sorted(set(map(str, declared)))
        )
    elif status == MODEL_BOM_INCOMPLETE:
        missing.append(f"{section}.missing_entries")
    normalized = {
        **row,
        "identity_sha256": identity,
        "status": status,
        "binding": binding,
    }
    return normalized, missing


def _hash_rows(
    binding: Mapping[str, Any], key: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    raw_rows = binding.get(key)
    missing: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_rows, list):
        return {}, [f"code_constants.{key}"]
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            missing.append(f"code_constants.{key}.row")
            continue
        module = str(raw.get("module") or "")
        status = str(raw.get("status") or MODEL_BOM_COMPLETE)
        sha256 = str(raw.get("sha256") or "")
        byte_count = raw.get("bytes")
        if not module or module in rows:
            missing.append(f"code_constants.{key}.module")
            continue
        if status != MODEL_BOM_COMPLETE or not _SHA256_RE.fullmatch(sha256):
            missing.append(f"code_constants.{key}.{module}.fingerprint")
        row = {"module": module, "status": status, "sha256": sha256}
        if key == "source_files":
            if not isinstance(byte_count, int) or byte_count < 0:
                missing.append(f"code_constants.{key}.{module}.bytes")
            row["bytes"] = byte_count
        rows[module] = row
    if list(rows) != sorted(rows):
        missing.append(f"code_constants.{key}.order")
    return rows, missing


def _code_evidence_gaps(code: Mapping[str, Any]) -> list[str]:
    binding = code.get("binding") if isinstance(code, Mapping) else None
    if not isinstance(binding, Mapping):
        return ["code_constants.binding"]
    source_rows, missing = _hash_rows(binding, "source_files")
    loaded_rows, loaded_missing = _hash_rows(binding, "loaded_modules")
    missing.extend(loaded_missing)
    required_modules = {
        str(stage["owner_module"]) for stage in SERVING_STAGE_CONTRACTS
    } | {str(lane["runtime_owner"]) for lane in RUNTIME_LANE_CONTRACTS}
    for module in sorted(required_modules):
        if module not in source_rows:
            missing.append(f"code_constants.source_files.missing:{module}")
        if module not in loaded_rows:
            missing.append(f"code_constants.loaded_modules.missing:{module}")
    source_list = [source_rows[name] for name in sorted(source_rows)]
    loaded_list = [loaded_rows[name] for name in sorted(loaded_rows)]
    if binding.get("source_file_count") != len(source_list):
        missing.append("code_constants.source_file_count")
    if binding.get("source_fingerprint") != canonical_payload_sha256(
        {"source_files": source_list}
    ):
        missing.append("code_constants.source_fingerprint")
    if binding.get("loaded_code_hash") != canonical_payload_sha256(
        {"loaded_modules": loaded_list}
    ):
        missing.append("code_constants.loaded_code_hash")
    if not _SHA256_RE.fullmatch(str(binding.get("behavior_constants_sha256") or "")):
        missing.append("code_constants.behavior_constants_sha256")
    if not str(binding.get("identity_schema_version") or ""):
        missing.append("code_constants.identity_schema_version")
    return missing


def _runtime_evidence_gaps(runtime: Mapping[str, Any]) -> list[str]:
    binding = runtime.get("binding") if isinstance(runtime, Mapping) else None
    if not isinstance(binding, Mapping):
        return ["runtime_dependencies.binding"]
    missing: list[str] = []
    if not isinstance(binding.get("release_runtime_versions"), Mapping):
        missing.append("runtime_dependencies.release_runtime_versions")
    identity = binding.get("model_runtime_dependency_identity")
    if not isinstance(identity, Mapping):
        missing.append("runtime_dependencies.model_runtime_dependency_identity")
    elif not _SHA256_RE.fullmatch(str(identity.get("runtime_dependency_hash") or "")):
        missing.append(
            "runtime_dependencies.model_runtime_dependency_identity.runtime_dependency_hash"
        )
    return missing


def _resolve_stage_artifacts(
    template: Mapping[str, Any], artifacts: Mapping[str, Mapping[str, Any]]
) -> tuple[list[str], list[str]]:
    roles: list[str] = []
    missing: list[str] = []
    for raw_role in template.get("artifact_roles") or ():
        role = str(raw_role)
        if role in artifacts:
            roles.append(role)
        else:
            missing.append(f"artifact_role:{role}")
    for raw_suffix in template.get("artifact_role_suffixes") or ():
        suffix = str(raw_suffix)
        matches = sorted(role for role in artifacts if role.endswith(suffix))
        if not matches:
            missing.append(f"artifact_role_suffix:{suffix}")
        roles.extend(matches)
    return sorted(set(roles)), missing


def required_training_roles(
    artifacts: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    roles: set[str] = set()
    for template in SERVING_STAGE_CONTRACTS:
        if template.get("training_evidence_required"):
            resolved, _ = _resolve_stage_artifacts(template, artifacts)
            roles.update(resolved)
    return roles


def _lineage_record(
    role: str,
    raw: Any,
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    supplied: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    row = _json_safe(raw) if isinstance(raw, Mapping) else {}
    prefix = f"training_lineage.{role}"
    status = str(row.get("status") or "")
    disposition = str(row.get("disposition") or "")
    artifact_sha = str(row.get("artifact_sha256") or "")
    missing: list[str] = []
    artifact = artifacts.get(role)
    if row.get("artifact_role") != role or artifact is None or artifact_sha != artifact.get(
        "sha256"
    ):
        missing.append(f"{prefix}.artifact_binding")
    if disposition not in _LINEAGE_DISPOSITIONS:
        missing.append(f"{prefix}.disposition")

    if disposition == "direct_fit_output":
        corpus = row.get("corpus_binding")
        fit = row.get("fit_binding")
        if not isinstance(corpus, Mapping):
            missing.append(f"{prefix}.corpus_binding")
            corpus = {}
        if not isinstance(fit, Mapping):
            missing.append(f"{prefix}.fit_binding")
            fit = {}
        corpus_role = str(corpus.get("artifact_role") or "")
        corpus_artifact = artifacts.get(corpus_role)
        if (
            corpus_artifact is None
            or corpus.get("artifact_sha256") != corpus_artifact.get("sha256")
        ):
            missing.append(f"{prefix}.corpus_binding.artifact")
        partition_sha = str(corpus.get("partition_sha256") or "")
        if not str(corpus.get("partition") or "") or not _SHA256_RE.fullmatch(
            partition_sha
        ):
            missing.append(f"{prefix}.corpus_binding.partition")
        if not isinstance(corpus.get("row_count"), int) or corpus.get("row_count") <= 0:
            missing.append(f"{prefix}.corpus_binding.row_count")
        if not _SHA256_RE.fullmatch(str(fit.get("receipt_sha256") or "")):
            missing.append(f"{prefix}.fit_binding.receipt_sha256")
        if not str(fit.get("receipt_schema_version") or ""):
            missing.append(f"{prefix}.fit_binding.receipt_schema_version")
        if fit.get("output_binding_kind") != "artifact_content_sha256":
            missing.append(f"{prefix}.fit_binding.output_binding_kind")
        if fit.get("output_content_sha256") != artifact_sha:
            missing.append(f"{prefix}.fit_binding.output_content_sha256")
        if fit.get("partition_sha256") != partition_sha:
            missing.append(f"{prefix}.fit_binding.partition_sha256")
        if fit.get("row_count") != corpus.get("row_count"):
            missing.append(f"{prefix}.fit_binding.row_count")
    elif disposition == "deterministic_derivative":
        parent = row.get("parent_binding")
        if not isinstance(parent, Mapping):
            missing.append(f"{prefix}.parent_binding")
            parent = {}
        parent_role = str(parent.get("artifact_role") or "")
        parent_artifact = artifacts.get(parent_role)
        parent_lineage = supplied.get(parent_role)
        if (
            parent_artifact is None
            or parent.get("artifact_sha256") != parent_artifact.get("sha256")
            or not isinstance(parent_lineage, Mapping)
            or parent_lineage.get("status") != MODEL_BOM_COMPLETE
        ):
            missing.append(f"{prefix}.parent_binding.artifact")
        expected_parent_identity = (
            parent_lineage.get("identity_sha256")
            if isinstance(parent_lineage, Mapping)
            else None
        )
        if parent.get("lineage_identity_sha256") != expected_parent_identity:
            missing.append(f"{prefix}.parent_binding.lineage_identity_sha256")
        if not _SHA256_RE.fullmatch(str(row.get("derivation_sha256") or "")):
            missing.append(f"{prefix}.derivation_sha256")
    elif disposition == "verified_parent_inheritance":
        parent = row.get("parent_binding")
        if not isinstance(parent, Mapping):
            missing.append(f"{prefix}.parent_binding")
            parent = {}
        if (
            parent.get("artifact_role") != role
            or parent.get("artifact_sha256") != artifact_sha
        ):
            missing.append(f"{prefix}.parent_binding.artifact")
        for key in ("parent_bom_identity_sha256", "parent_manifest_sha256"):
            if not _SHA256_RE.fullmatch(str(parent.get(key) or "")):
                missing.append(f"{prefix}.parent_binding.{key}")
    elif disposition == "missing":
        missing.append(f"{prefix}.candidate_bound_evidence")

    declared = row.get("missing_entries")
    if isinstance(declared, list):
        missing.extend(f"{prefix}.{entry}" for entry in sorted(set(map(str, declared))))
    elif status == MODEL_BOM_INCOMPLETE:
        missing.append(f"{prefix}.missing_entries")
    expected_status = MODEL_BOM_COMPLETE if not missing else MODEL_BOM_INCOMPLETE
    if status != expected_status:
        missing.append(f"{prefix}.status")
        expected_status = MODEL_BOM_INCOMPLETE
    normalized = {
        **row,
        "artifact_role": role,
        "artifact_sha256": artifact_sha,
        "status": status,
        "disposition": disposition,
    }
    identity = str(row.get("identity_sha256") or "")
    expected_identity = canonical_payload_sha256(
        normalized, omit=("identity_sha256",)
    )
    if not _SHA256_RE.fullmatch(identity) or identity != expected_identity:
        missing.append(f"{prefix}.identity_sha256")
    normalized["identity_sha256"] = identity
    return normalized, sorted(set(missing))


def _context_gaps(name: str, context: Mapping[str, Any]) -> list[str]:
    binding = context.get("binding") if isinstance(context, Mapping) else None
    if not isinstance(binding, Mapping):
        return [f"forecast_contexts.{name}.binding"]
    missing: list[str] = []
    if binding.get("source_roles") != list(FORECAST_CONTEXT_SOURCE_ROLES[name]):
        missing.append(f"forecast_contexts.{name}.source_roles")
    if binding.get("runtime_contract_owner") != "weather.model.model_contracts":
        missing.append(f"forecast_contexts.{name}.runtime_contract_owner")
    if binding.get("runtime_contract_symbol") != "FORECAST_CONTEXT_SOURCE_ROLES":
        missing.append(f"forecast_contexts.{name}.runtime_contract_symbol")
    for field in (
        "implementation",
        "input_semantic_contract",
        "output_semantic_contract",
        "native_unit_obligation",
        "cutoff_obligation",
    ):
        if not str(binding.get(field) or ""):
            missing.append(f"forecast_contexts.{name}.{field}")
    return missing


def _serving_graph(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    code: Mapping[str, Any],
    runtime: Mapping[str, Any],
    lineage: Mapping[str, Mapping[str, Any]],
    contexts: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    missing: list[str] = []
    code_binding = code.get("binding") or {}
    source_rows, _ = _hash_rows(code_binding, "source_files")
    loaded_rows, _ = _hash_rows(code_binding, "loaded_modules")
    code_identity = str(code.get("identity_sha256") or "")
    runtime_identity = str(runtime.get("identity_sha256") or "")
    nodes: list[dict[str, Any]] = []
    for template in SERVING_STAGE_CONTRACTS:
        stage_id = str(template["stage_id"])
        roles, stage_missing = _resolve_stage_artifacts(template, artifacts)
        owner = str(template["owner_module"])
        if owner not in source_rows:
            stage_missing.append(f"owner_source:{owner}")
        if owner not in loaded_rows:
            stage_missing.append(f"owner_loaded_module:{owner}")
        context_name = template.get("forecast_context")
        context_binding = None
        if context_name:
            context = contexts.get(str(context_name)) or {}
            if context.get("status") != MODEL_BOM_COMPLETE:
                stage_missing.append(f"forecast_context:{context_name}")
            context_binding = {
                "name": str(context_name),
                "identity_sha256": context.get("identity_sha256"),
                "source_roles": (context.get("binding") or {}).get("source_roles"),
            }
        training_bindings: list[dict[str, Any]] = []
        if template.get("training_evidence_required"):
            for role in roles:
                record = lineage.get(role)
                if not isinstance(record, Mapping) or record.get("status") != MODEL_BOM_COMPLETE:
                    stage_missing.append(f"training_lineage:{role}")
                training_bindings.append(
                    {
                        "artifact_role": role,
                        "artifact_sha256": artifacts[role]["sha256"],
                        "lineage_identity_sha256": (
                            record.get("identity_sha256")
                            if isinstance(record, Mapping)
                            else None
                        ),
                    }
                )
        node = {
            "stage_id": stage_id,
            "lane_id": template.get("lane_id"),
            "owner_module": owner,
            "role": str(template["role"]),
            "input_semantic_contract": str(template["input_semantic_contract"]),
            "output_semantic_contract": str(template["output_semantic_contract"]),
            "native_unit_obligation": str(template["native_unit_obligation"]),
            "cutoff_obligation": str(template["cutoff_obligation"]),
            "artifact_bindings": [
                {
                    "role": role,
                    "kind": artifacts[role]["kind"],
                    "sha256": artifacts[role]["sha256"],
                }
                for role in roles
            ],
            "behavior_binding": {
                "code_constants_identity_sha256": code_identity,
                "behavior_constants_sha256": code_binding.get(
                    "behavior_constants_sha256"
                ),
                "owner_source": source_rows.get(owner),
                "owner_loaded_module": loaded_rows.get(owner),
            },
            "runtime_dependency_identity_sha256": runtime_identity,
            "training_bindings": training_bindings,
            "forecast_context": context_binding,
            "status": (
                MODEL_BOM_COMPLETE if not stage_missing else MODEL_BOM_INCOMPLETE
            ),
            "missing_entries": sorted(set(stage_missing)),
        }
        node["node_identity_sha256"] = canonical_payload_sha256(
            node, omit=("node_identity_sha256",)
        )
        nodes.append(node)
        missing.extend(
            f"serving_graph.nodes.{stage_id}.{entry}"
            for entry in node["missing_entries"]
        )

    stage_ids = {str(row["stage_id"]) for row in SERVING_STAGE_CONTRACTS}
    lanes: list[dict[str, Any]] = []
    for raw in RUNTIME_LANE_CONTRACTS:
        order = [str(value) for value in raw["stage_order"]]
        lane = {
            "lane_id": str(raw["lane_id"]),
            "runtime_owner": str(raw["runtime_owner"]),
            "runtime_contract_symbol": str(raw["runtime_contract_symbol"]),
            "stage_order": order,
        }
        lane["runtime_contract_sha256"] = canonical_payload_sha256(
            {"stage_order": order}
        )
        if any(stage not in stage_ids for stage in order) or len(order) != len(set(order)):
            missing.append(f"serving_graph.lanes.{lane['lane_id']}.stage_order")
        lanes.append(lane)
    edges = [
        {"from": str(left), "to": str(right), "condition": str(condition)}
        for left, right, condition in SERVING_GRAPH_EDGES
    ]
    graph = {"nodes": nodes, "lanes": lanes, "edges": edges}
    graph["graph_identity_sha256"] = canonical_payload_sha256(
        graph, omit=("graph_identity_sha256",)
    )
    return graph, sorted(set(missing))


def _required_model_node_roles(
    artifacts: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    return {
        role
        for role in artifacts
        if role == "pooled_band_model"
        or role.endswith(
            (".feature_hgb", ".feature_lr_coefficients", ".late_day_lr_coefficients")
        )
    }


def _model_records(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    model_nodes: Mapping[str, Mapping[Any, Any]],
    lineage: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    records: dict[str, Any] = {}
    missing: list[str] = []
    required_nodes = _required_model_node_roles(artifacts)
    training_roles = required_training_roles(artifacts)
    for raw_node, models in sorted(model_nodes.items(), key=lambda item: str(item[0])):
        node = str(raw_node)
        if node in records:
            raise ModelBomError(f"model node collision after normalization: {node!r}")
        summary = summarize_hourly_model_mapping(models)
        node_missing = list(summary["missing_entries"])
        artifact = artifacts.get(node)
        if artifact is None:
            node_missing.append("artifact_binding")
        lineage_record = lineage.get(node)
        lineage_identity = None
        if node in training_roles:
            if not isinstance(lineage_record, Mapping) or lineage_record.get(
                "status"
            ) != MODEL_BOM_COMPLETE:
                node_missing.append("training_lineage_binding")
            elif lineage_record.get("artifact_sha256") != artifact.get("sha256"):
                node_missing.append("training_lineage_binding")
            lineage_identity = (
                lineage_record.get("identity_sha256")
                if isinstance(lineage_record, Mapping)
                else None
            )
        summary.update(
            {
                "artifact_role": node,
                "artifact_sha256": artifact.get("sha256") if artifact else None,
                "training_lineage_identity_sha256": lineage_identity,
                "missing_entries": sorted(set(node_missing)),
                "status": (
                    MODEL_BOM_COMPLETE if not node_missing else MODEL_BOM_INCOMPLETE
                ),
            }
        )
        summary["node_identity_sha256"] = canonical_payload_sha256(
            summary, omit=("node_identity_sha256",)
        )
        records[node] = summary
        missing.extend(
            f"model_nodes.{node}.{entry}" for entry in summary["missing_entries"]
        )
    for role in sorted(required_nodes - set(records)):
        missing.append(f"model_nodes.{role}.missing")
    for role in sorted(set(records) - required_nodes):
        missing.append(f"model_nodes.{role}.undeclared")
    if not records:
        missing.append("model_nodes")
    return records, sorted(set(missing))


def _finalize(payload: dict[str, Any]) -> dict[str, Any]:
    material = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "authoritative_identity_sha256",
            "diagnostic_sha256",
            "payload_sha256",
        }
    }
    payload["diagnostic_sha256"] = canonical_payload_sha256(material)
    payload["authoritative_identity_sha256"] = (
        payload["diagnostic_sha256"]
        if payload["status"] == MODEL_BOM_COMPLETE
        else None
    )
    payload["payload_sha256"] = canonical_payload_sha256(
        payload, omit=("payload_sha256",)
    )
    return payload


def build_model_bill_of_materials(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    model_nodes: Mapping[str, Mapping[Any, Any]],
    code_constants: Mapping[str, Any],
    runtime_dependencies: Mapping[str, Any],
    training_lineage: Mapping[str, Mapping[str, Any]],
    forecast_contexts: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic BOM exclusively from explicit evidence."""

    missing: list[str] = []
    artifact_records: dict[str, Any] = {}
    for raw_role, raw in sorted(artifacts.items(), key=lambda item: str(item[0])):
        role = str(raw_role)
        if role in artifact_records:
            raise ModelBomError(f"artifact role collision after normalization: {role!r}")
        artifact_records[role], gaps = _artifact_record(role, raw)
        missing.extend(gaps)
    if not artifact_records:
        missing.append("artifacts")

    code, gaps = _evidence_record("code_constants", code_constants)
    missing.extend(gaps)
    missing.extend(_code_evidence_gaps(code))
    runtime, gaps = _evidence_record("runtime_dependencies", runtime_dependencies)
    missing.extend(gaps)
    missing.extend(_runtime_evidence_gaps(runtime))

    contexts: dict[str, Any] = {}
    for name in _FORECAST_CONTEXT_NAMES:
        contexts[name], gaps = _evidence_record(
            f"forecast_contexts.{name}", forecast_contexts.get(name)
        )
        missing.extend(gaps)
        missing.extend(_context_gaps(name, contexts[name]))
    for name in sorted(set(map(str, forecast_contexts)) - set(_FORECAST_CONTEXT_NAMES)):
        missing.append(f"forecast_contexts.unexpected:{name}")

    required_lineage = required_training_roles(artifact_records)
    normalized_lineage: dict[str, Any] = {}
    supplied = {str(role): raw for role, raw in training_lineage.items()}
    for role in sorted(required_lineage):
        normalized_lineage[role], gaps = _lineage_record(
            role,
            supplied.get(role),
            artifacts=artifact_records,
            supplied=supplied,
        )
        missing.extend(gaps)
    for role in sorted(set(supplied) - required_lineage):
        missing.append(f"training_lineage.unexpected:{role}")

    model_records, gaps = _model_records(
        artifacts=artifact_records,
        model_nodes=model_nodes,
        lineage=normalized_lineage,
    )
    missing.extend(gaps)
    graph, gaps = _serving_graph(
        artifacts=artifact_records,
        code=code,
        runtime=runtime,
        lineage=normalized_lineage,
        contexts=contexts,
    )
    missing.extend(gaps)

    missing = sorted(set(missing))
    payload: dict[str, Any] = {
        "schema_version": MODEL_BOM_SCHEMA_VERSION,
        "status": MODEL_BOM_COMPLETE if not missing else MODEL_BOM_INCOMPLETE,
        "missing_entries": missing,
        "artifacts": artifact_records,
        "serving_graph": graph,
        "model_nodes": model_records,
        "evidence": {
            "code_constants": code,
            "runtime_dependencies": runtime,
        },
        "training_lineage": normalized_lineage,
        "forecast_contexts": contexts,
    }
    return _finalize(payload)


def verify_model_bill_of_materials(
    payload: Mapping[str, Any],
    *,
    expected_artifacts: Mapping[str, Mapping[str, Any]],
    production_required: bool,
    expected_runtime_versions: Mapping[str, Any] | None = None,
    expected_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild the BOM from its evidence, then enforce release bindings."""

    if payload.get("schema_version") != MODEL_BOM_SCHEMA_VERSION:
        raise ModelBomError("model BOM schema is unsupported")
    if payload.get("payload_sha256") != canonical_payload_sha256(
        payload, omit=("payload_sha256",)
    ):
        raise ModelBomError("model BOM payload hash is invalid")
    expected_records = {
        str(role): _artifact_record(str(role), row)[0]
        for role, row in sorted(expected_artifacts.items())
    }
    if payload.get("artifacts") != expected_records:
        raise ModelBomError("model BOM artifact inventory disagrees with the release")
    evidence = payload.get("evidence")
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "code_constants",
        "runtime_dependencies",
    }:
        raise ModelBomError("model BOM evidence inventory is incomplete or ambiguous")
    contexts = payload.get("forecast_contexts")
    lineage = payload.get("training_lineage")
    model_nodes = payload.get("model_nodes")
    if not isinstance(contexts, Mapping) or not isinstance(lineage, Mapping) or not isinstance(
        model_nodes, Mapping
    ):
        raise ModelBomError("model BOM semantic inventory is incomplete")

    rebuilt = build_model_bill_of_materials(
        artifacts=expected_records,
        model_nodes={
            str(node): {
                str(hour): {
                    "feature_names": structure.get("feature_names") or (),
                    "model": {
                        "n_features_in_": structure.get("n_features_in"),
                        "feature_names_in_": structure.get("feature_names_in"),
                        **dict(structure.get("structural_attributes") or {}),
                        # Preserve the already summarized feature-use section below.
                    },
                }
                for hour, structure in (summary.get("models") or {}).items()
            }
            for node, summary in model_nodes.items()
        },
        code_constants=evidence["code_constants"],
        runtime_dependencies=evidence["runtime_dependencies"],
        training_lineage=lineage,
        forecast_contexts=contexts,
    )
    # Estimators cannot be reconstructed from a BOM.  Validate their summaries
    # independently, then compare the evidence-derived sections exactly.
    for section in (
        "artifacts",
        "serving_graph",
        "evidence",
        "training_lineage",
        "forecast_contexts",
    ):
        if payload.get(section) != rebuilt.get(section):
            raise ModelBomError(f"model BOM {section} is not canonical")
    node_gaps = _model_node_gaps(model_nodes, artifacts=expected_records, lineage=lineage)
    recomputed_missing = [
        entry
        for entry in rebuilt["missing_entries"]
        if not entry.startswith("model_nodes.")
    ] + node_gaps
    recomputed_missing = sorted(set(recomputed_missing))
    missing = payload.get("missing_entries")
    if not isinstance(missing, list) or missing != sorted(set(map(str, missing))):
        raise ModelBomError("model BOM missing-entry inventory is invalid")
    if missing != recomputed_missing:
        raise ModelBomError("model BOM missing-entry inventory disagrees with its evidence")
    status = payload.get("status")
    expected_status = MODEL_BOM_COMPLETE if not missing else MODEL_BOM_INCOMPLETE
    if status != expected_status:
        raise ModelBomError("model BOM completeness disagrees with missing entries")
    diagnostic_material = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "authoritative_identity_sha256",
            "diagnostic_sha256",
            "payload_sha256",
        }
    }
    diagnostic = canonical_payload_sha256(diagnostic_material)
    if payload.get("diagnostic_sha256") != diagnostic:
        raise ModelBomError("model BOM diagnostic identity is invalid")
    authoritative = payload.get("authoritative_identity_sha256")
    if status == MODEL_BOM_COMPLETE and authoritative != diagnostic:
        raise ModelBomError("complete model BOM authoritative identity is invalid")
    if status == MODEL_BOM_INCOMPLETE and authoritative is not None:
        raise ModelBomError("incomplete model BOM must not expose authoritative identity")

    runtime_binding = evidence["runtime_dependencies"].get("binding") or {}
    if expected_runtime_versions is not None and runtime_binding.get(
        "release_runtime_versions"
    ) != _json_safe(expected_runtime_versions):
        raise ModelBomError("model BOM runtime versions disagree with release manifest")
    if expected_runtime_identity is not None:
        stable = runtime_binding.get("release_runtime_identity")
        if stable != stable_release_runtime_identity(expected_runtime_identity):
            raise ModelBomError("model BOM runtime identity disagrees with release manifest")
    if production_required and status != MODEL_BOM_COMPLETE:
        raise ModelBomError(
            "production model BOM is incomplete: " + ", ".join(map(str, missing))
        )
    return dict(payload)


def _model_node_gaps(
    model_nodes: Mapping[str, Any],
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    lineage: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    missing: list[str] = []
    required = _required_model_node_roles(artifacts)
    actual = set(map(str, model_nodes))
    missing.extend(f"model_nodes.{role}.missing" for role in sorted(required - actual))
    missing.extend(f"model_nodes.{role}.undeclared" for role in sorted(actual - required))
    training_roles = required_training_roles(artifacts)
    for node, summary in sorted(model_nodes.items()):
        prefix = f"model_nodes.{node}"
        if not isinstance(summary, Mapping):
            missing.append(f"{prefix}.summary")
            continue
        declared = summary.get("missing_entries")
        if not isinstance(declared, list) or declared != sorted(set(map(str, declared))):
            missing.append(f"{prefix}.missing_entries")
            declared = []
        missing.extend(f"{prefix}.{entry}" for entry in declared)
        artifact = artifacts.get(str(node))
        if (
            artifact is None
            or summary.get("artifact_role") != str(node)
            or summary.get("artifact_sha256") != artifact.get("sha256")
        ):
            missing.append(f"{prefix}.artifact_binding")
        expected_lineage = lineage.get(str(node)) if str(node) in training_roles else None
        expected_lineage_identity = (
            expected_lineage.get("identity_sha256")
            if isinstance(expected_lineage, Mapping)
            else None
        )
        if summary.get("training_lineage_identity_sha256") != expected_lineage_identity:
            missing.append(f"{prefix}.training_lineage_binding")
        models = summary.get("models")
        if not isinstance(models, Mapping) or not models:
            missing.append(f"{prefix}.hourly_models")
            models = {}
        for hour, structure in sorted(models.items()):
            structure_prefix = f"{prefix}.models.{hour}"
            if not isinstance(structure, Mapping):
                missing.append(f"{structure_prefix}.structure")
                continue
            names = structure.get("feature_names")
            if not isinstance(names, list) or any(not isinstance(v, str) for v in names):
                missing.append(f"{structure_prefix}.feature_names")
                names = []
            if len(names) != len(set(names)):
                missing.append(f"{structure_prefix}.feature_names:duplicate")
            if structure.get("feature_count") != len(names):
                missing.append(f"{structure_prefix}.feature_count")
            if structure.get("feature_order_sha256") != feature_order_sha256(names):
                missing.append(f"{structure_prefix}.feature_order_sha256")
            feature_use = structure.get("structural_feature_use")
            if not isinstance(feature_use, Mapping) or feature_use.get("status") not in {
                "COMPLETE",
                "INCONSISTENT",
                "UNREADABLE",
                "NOT_EXPOSED",
            }:
                missing.append(f"{structure_prefix}.structural_feature_use")
            if structure.get("structure_sha256") != canonical_payload_sha256(
                structure, omit=("structure_sha256",)
            ):
                missing.append(f"{structure_prefix}.structure_sha256")
        expected_summary_status = (
            MODEL_BOM_COMPLETE if not declared else MODEL_BOM_INCOMPLETE
        )
        if summary.get("status") != expected_summary_status:
            missing.append(f"{prefix}.status")
        if summary.get("node_identity_sha256") != canonical_payload_sha256(
            summary, omit=("node_identity_sha256",)
        ):
            missing.append(f"{prefix}.node_identity_sha256")
    if not model_nodes:
        missing.append("model_nodes")
    return sorted(set(missing))


def verify_loaded_environment_binding(
    payload: Mapping[str, Any],
    *,
    loaded_modules: Sequence[Mapping[str, Any]],
    runtime_dependency_identity: Mapping[str, Any],
) -> None:
    """Bind a verified BOM to code and dependencies loaded in this process."""

    evidence = payload.get("evidence")
    code = evidence.get("code_constants") if isinstance(evidence, Mapping) else None
    runtime = evidence.get("runtime_dependencies") if isinstance(evidence, Mapping) else None
    code_binding = code.get("binding") if isinstance(code, Mapping) else None
    runtime_binding = runtime.get("binding") if isinstance(runtime, Mapping) else None
    if not isinstance(code_binding, Mapping) or not isinstance(runtime_binding, Mapping):
        raise ModelBomError("model BOM loaded-environment evidence is missing")
    normalized_loaded = _json_safe(list(loaded_modules))
    if normalized_loaded != code_binding.get("loaded_modules"):
        raise ModelBomError("loaded module fingerprints disagree with model BOM")
    if _json_safe(runtime_dependency_identity) != runtime_binding.get(
        "model_runtime_dependency_identity"
    ):
        raise ModelBomError("loaded runtime dependency identity disagrees with model BOM")


def _loaded_expected_structure(summary: Mapping[str, Any]) -> dict[str, Any]:
    ignored = {"artifact_binding", "training_lineage_binding"}
    missing = [
        str(value)
        for value in summary.get("missing_entries") or ()
        if str(value) not in ignored
    ]
    return {
        "models": summary.get("models"),
        "status": MODEL_BOM_COMPLETE if not missing else MODEL_BOM_INCOMPLETE,
        "missing_entries": missing,
    }


def verify_loaded_model_structure(
    payload: Mapping[str, Any],
    *,
    loaded_model_nodes: Mapping[str, Mapping[Any, Any]],
) -> None:
    expected = payload.get("model_nodes")
    if not isinstance(expected, Mapping) or set(expected) != set(
        map(str, loaded_model_nodes)
    ):
        raise ModelBomError("loaded model-node inventory disagrees with the BOM")
    for node, models in sorted(loaded_model_nodes.items()):
        actual = summarize_hourly_model_mapping(models)
        if canonical_payload_sha256(actual) != canonical_payload_sha256(
            _loaded_expected_structure(expected[str(node)])
        ):
            raise ModelBomError(
                f"loaded estimator structure or feature order disagrees with BOM: {node}"
            )


def verify_loaded_model_node(
    payload: Mapping[str, Any], *, node: str, loaded_models: Mapping[Any, Any]
) -> None:
    expected_nodes = payload.get("model_nodes")
    expected = expected_nodes.get(node) if isinstance(expected_nodes, Mapping) else None
    if not isinstance(expected, Mapping):
        raise ModelBomError(f"loaded model node is absent from the BOM: {node}")
    actual = summarize_hourly_model_mapping(loaded_models)
    if canonical_payload_sha256(actual) != canonical_payload_sha256(
        _loaded_expected_structure(expected)
    ):
        raise ModelBomError(
            f"loaded estimator structure or feature order disagrees with BOM: {node}"
        )
