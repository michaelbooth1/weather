"""Freeze and audit the semantic contract of a nightly model candidate."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from weather.model.feature_safety import audit_recursive_model_inputs
from weather.point_in_time_contract import (
    ContractViolation as PointInTimeContractViolation,
    verify_embedded_point_in_time_training_evidence,
    verify_point_in_time_selection_binding,
    verify_production_point_in_time_artifacts,
)
from weather.release_artifacts import ReleaseArtifactVerificationError, sha256_file, strict_json_loads
from weather.release_contract import (
    BASE_MODEL_MARKET_COMPONENT_KINDS,
    BASE_MODEL_SERVING_GRAPH_SCHEMA_VERSION,
    BASE_MODEL_SHARED_COMPONENT_ROLES,
    CANDIDATE_LEAKAGE_AUDIT_SCHEMA_VERSION,
    CANDIDATE_MODES,
    PRODUCTION_CANDIDATE_MODE,
    PRODUCTION_POINT_IN_TIME_ROLE_KINDS,
    RESEARCH_ONLY_CANDIDATE_MODE,
    SEMANTIC_CONTRACT_SCHEMA_VERSION,
    SEMANTIC_SERVING_ROLE_KINDS,
)
from weather.schema_registry import schema_version


SEMANTIC_PATHS = {
    "model_variant_registry": "contract/model_variant_registry.json",
    "locations_config": "contract/locations.json",
    "location_market_events_config": "contract/location_market_events.json",
    "markets_config": "contract/markets.json",
    "market_route_table": "contract/market_route_table.json",
    "base_model_serving_graph": "contract/base_model_serving_graph.json",
    "pooled_feature_schema": "contract/pooled_feature_schema.json",
    "pooled_imputer_metadata": "contract/pooled_imputer_metadata.json",
    "pooled_calibrator_metadata": "contract/pooled_calibrator_metadata.json",
    "pooled_postprocessor_metadata": "contract/pooled_postprocessor_metadata.json",
    "settlement_rules": "contract/settlement_rules.json",
    "training_evaluation_corpus": "contract/training_evaluation_corpus.json",
    "candidate_input_leakage_audit": "contract/candidate_input_leakage_audit.json",
    "point_in_time_corpus": "contract/point_in_time/corpus.parquet",
    "point_in_time_materialization_manifest": (
        "contract/point_in_time/materialization_manifest.json"
    ),
    "point_in_time_validation_plan": "contract/point_in_time/validation_plan.json",
    "point_in_time_streaming_evaluation": (
        "contract/point_in_time/streaming_evaluation.json"
    ),
    "semantic_serving_contract": "contract/semantic_serving_contract.json",
}

MAX_PRODUCTION_EVALUATION_AGE_DAYS = 7
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

INTERNALLY_HASHED_ROLES = {
    "market_route_table",
    "base_model_serving_graph",
    "pooled_feature_schema",
    "pooled_imputer_metadata",
    "pooled_calibrator_metadata",
    "pooled_postprocessor_metadata",
    "settlement_rules",
    "training_evaluation_corpus",
    "candidate_input_leakage_audit",
}


class CandidateContractError(ReleaseArtifactVerificationError):
    """A candidate cannot become an immutable semantic release."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(child)
            for key, child in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(child) for child in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _canonical_bytes(payload: Mapping[str, Any], *, omit: Sequence[str] = ()) -> bytes:
    normalized = {key: value for key, value in payload.items() if key not in set(omit)}
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(payload: Mapping[str, Any], *, omit: Sequence[str] = ()) -> str:
    return hashlib.sha256(_canonical_bytes(payload, omit=omit)).hexdigest()


def _finalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    finalized = _json_safe(payload)
    finalized["payload_sha256"] = _payload_sha256(finalized, omit=("payload_sha256",))
    return finalized


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CandidateContractError(f"candidate semantic artifact already exists: {path}") from exc


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise CandidateContractError(f"{label} is missing or invalid: {path}")
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label=label)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CandidateContractError(f"{label} must be a JSON object: {path}")
    return payload


def _copy_canonical_json(source: Path, destination: Path, *, label: str) -> dict[str, Any]:
    payload = _read_json(source, label=label)
    _write_json_exclusive(destination, payload)
    return payload


def _freeze_model_variant_registry(
    source: Path,
    destination: Path,
    *,
    candidate_id: str,
    bundle: Mapping[str, Any],
    bundle_sha256: str,
    model_relative_path: str,
) -> dict[str, Any]:
    payload = _read_json(source, label="model variant registry")
    variants = payload.get("variants")
    if not isinstance(variants, list):
        raise CandidateContractError("model variant registry variants list is missing")
    variant_id = f"{candidate_id}.pooled_band"
    if any(isinstance(row, Mapping) and row.get("variant_id") == variant_id for row in variants):
        raise CandidateContractError(f"model variant registry already contains {variant_id!r}")
    frozen = _json_safe(payload)
    frozen["variants"] = [
        *frozen["variants"],
        {
            "variant_id": variant_id,
            "variant_family": "nightly_pooled_band",
            "lifecycle": "shadow",
            "track": "no_market",
            "roles": ["candidate", "release-bound"],
            "active_for_headline": False,
            "counts_toward_weather_model_promotion": True,
            "artifact_required": True,
            "artifact_role": "pooled_band_model",
            "artifact_path": model_relative_path,
            "artifact_sha256": bundle_sha256,
            "feature_schema_role": "pooled_feature_schema",
            "imputer_role": "pooled_imputer_metadata",
            "calibrator_role": "pooled_calibrator_metadata",
            "postprocessor_role": "pooled_postprocessor_metadata",
            "prediction_function": (
                "weather.collection.live_variant_predictions:_pooled_candidate_replay_payload"
            ),
            "prediction_mode": bundle.get("prediction_mode"),
            "live_runtime": "pooled_candidate_replay",
        },
    ]
    _write_json_exclusive(destination, frozen)
    return frozen


def _load_verified_bundle(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise CandidateContractError(f"candidate model bundle is missing or invalid: {path}")
    before_stat = path.stat()
    expected_sha = sha256_file(path)
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)  # noqa: S301 - trusted local trainer output, hash-guarded
    except Exception as exc:  # noqa: BLE001 - format failures must become release evidence
        raise CandidateContractError(f"candidate model bundle cannot be deserialized: {exc}") from exc
    after_stat = path.stat()
    if (
        before_stat.st_size != after_stat.st_size
        or before_stat.st_mtime_ns != after_stat.st_mtime_ns
        or sha256_file(path) != expected_sha
    ):
        raise CandidateContractError("candidate model bundle changed while semantic metadata was extracted")
    if not isinstance(payload, dict):
        raise CandidateContractError("candidate model bundle must deserialize to an object mapping")
    return payload, expected_sha


def _copy_file_exclusive(source: Path, destination: Path, *, label: str) -> str:
    if source.is_symlink() or not source.exists() or not source.is_file():
        raise CandidateContractError(f"{label} is missing or invalid: {source}")
    expected_sha = sha256_file(source)
    expected_size = source.stat().st_size
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as read_handle, destination.open("xb") as write_handle:
            shutil.copyfileobj(read_handle, write_handle, length=1024 * 1024)
            write_handle.flush()
            os.fsync(write_handle.fileno())
    except FileExistsError as exc:
        raise CandidateContractError(f"candidate base artifact already exists: {destination}") from exc
    if (
        source.stat().st_size != expected_size
        or sha256_file(source) != expected_sha
        or destination.stat().st_size != expected_size
        or sha256_file(destination) != expected_sha
    ):
        raise CandidateContractError(f"{label} changed while it was frozen")
    return expected_sha


def _artifact_suffix(market_id: str) -> str:
    return "" if market_id == "toronto" else f"_{market_id}"


def _base_model_source_components(repo_root: Path, market_id: str) -> dict[str, tuple[Path, str]]:
    suffix = _artifact_suffix(market_id)
    artifacts = repo_root / "artifacts"
    return {
        "feature_hgb": (
            artifacts / "models" / "hgb" / f"feature_model_hgb{suffix}.pkl",
            BASE_MODEL_MARKET_COMPONENT_KINDS["feature_hgb"],
        ),
        "feature_lr_coefficients": (
            artifacts / "models" / "coefs" / f"feature_model_coefs{suffix}.json",
            BASE_MODEL_MARKET_COMPONENT_KINDS["feature_lr_coefficients"],
        ),
        "late_day_lr_coefficients": (
            artifacts / "models" / "coefs" / f"late_day_model_coefs{suffix}.json",
            BASE_MODEL_MARKET_COMPONENT_KINDS["late_day_lr_coefficients"],
        ),
        "calibrated_weights": (
            artifacts / "calibration" / f"calibrated_weights{suffix}.json",
            BASE_MODEL_MARKET_COMPONENT_KINDS["calibrated_weights"],
        ),
        "probability_calibration": (
            artifacts / "calibration" / f"probability_calibration{suffix}.json",
            BASE_MODEL_MARKET_COMPONENT_KINDS["probability_calibration"],
        ),
        "forecast_error_model": (
            artifacts / "calibration" / f"forecast_error_model{suffix}.json",
            BASE_MODEL_MARKET_COMPONENT_KINDS["forecast_error_model"],
        ),
        "settlement_lag_model": (
            artifacts / "calibration" / f"settlement_lag_model{suffix}.json",
            BASE_MODEL_MARKET_COMPONENT_KINDS["settlement_lag_model"],
        ),
    }


def _pickle_feature_contract(path: Path, *, expected_sha256: str, label: str) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)  # noqa: S301 - copied, hash-verified repository artifact
    except Exception as exc:  # noqa: BLE001
        raise CandidateContractError(f"{label} cannot be deserialized: {exc}") from exc
    if sha256_file(path) != expected_sha256 or not isinstance(payload, Mapping):
        raise CandidateContractError(f"{label} changed during metadata extraction")
    feature_names = sorted(
        {
            str(name)
            for row in payload.values()
            if isinstance(row, Mapping)
            for name in row.get("feature_names") or []
        }
    )
    if not feature_names:
        raise CandidateContractError(f"{label} contains no feature-name contract")
    return {
        "model_input_fields": feature_names,
        "feature_names_sha256": hashlib.sha256("\n".join(feature_names).encode("utf-8")).hexdigest(),
        "feature_count": len(feature_names),
    }


def _family_secondary_output_role(entry: Mapping[str, Any]) -> str:
    tokens = [
        str(entry.get("fit_scope") or "scope"),
        str(entry.get("market_id") or "family"),
        str(entry.get("artifact_kind") or "artifact"),
    ]
    suffix = ".".join(
        re.sub(r"[^a-z0-9_-]+", "_", token.casefold()).strip("_")
        for token in tokens
    )
    return f"family_secondary_output.{suffix}"


def _freeze_base_model_serving_graph(
    *,
    candidate_dir: Path,
    repo_root: Path,
    market_ids: Sequence[str],
    family_secondary_path: Path,
    family_secondary_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    role_paths: dict[str, str] = {}
    role_kinds: dict[str, str] = {}
    audit_payloads: dict[str, Any] = {}
    markets: dict[str, Any] = {}
    for market_id in sorted({str(value) for value in market_ids if str(value)}):
        components: dict[str, Any] = {}
        for component, (source, kind) in _base_model_source_components(repo_root, market_id).items():
            role = f"base_model.{market_id}.{component}"
            relative = f"base_model/{market_id}/{source.name}"
            destination = candidate_dir / relative
            if source.suffix.casefold() == ".json":
                payload = _copy_canonical_json(source, destination, label=role)
                audit_payloads[role] = payload
                artifact_sha = sha256_file(destination)
            else:
                artifact_sha = _copy_file_exclusive(source, destination, label=role)
                audit_payloads[role] = _pickle_feature_contract(
                    destination,
                    expected_sha256=artifact_sha,
                    label=role,
                )
            role_paths[role] = relative
            role_kinds[role] = kind
            components[component] = {
                "role": role,
                "kind": kind,
                "path": relative,
                "sha256": artifact_sha,
            }
        markets[market_id] = {
            "market_id": market_id,
            "artifact_suffix": _artifact_suffix(market_id),
            "components": components,
            "model_fallback_order": [
                "bound_feature_hgb",
                "bound_feature_lr_coefficients",
                "code_constant_empirical",
            ],
            "calibration_fallback_allowed": False,
            "global_path_fallback_allowed": False,
        }

    shared_source = repo_root / "artifacts" / "misc" / "afternoon_residual_centering.json"
    shared_role = BASE_MODEL_SHARED_COMPONENT_ROLES["afternoon_residual_centering"]
    shared_relative = f"base_model/shared/{shared_source.name}"
    shared_payload = _copy_canonical_json(
        shared_source,
        candidate_dir / shared_relative,
        label=shared_role,
    )
    role_paths[shared_role] = shared_relative
    role_kinds[shared_role] = "calibration"
    audit_payloads[shared_role] = shared_payload
    family_secondary_path = family_secondary_path.resolve()
    if (
        family_secondary_path.is_symlink()
        or not family_secondary_path.is_file()
        or not family_secondary_path.is_relative_to(candidate_dir)
    ):
        raise CandidateContractError(
            "family-secondary calibration is not a regular candidate artifact"
        )
    family_relative = family_secondary_path.relative_to(candidate_dir).as_posix()
    family_output_components: dict[str, Any] = {}
    output_inventory = family_secondary_manifest.get("output_artifact_inventory")
    if isinstance(output_inventory, Mapping):
        for entry in output_inventory.get("entries") or ():
            if not isinstance(entry, Mapping):
                raise CandidateContractError(
                    "family-secondary output inventory entry is invalid"
                )
            source = Path(str(entry.get("path") or "")).resolve()
            if (
                source.is_symlink()
                or not source.is_file()
                or not source.is_relative_to(candidate_dir)
                or sha256_file(source) != entry.get("sha256")
                or source.stat().st_size != int(entry.get("bytes") or -1)
            ):
                raise CandidateContractError(
                    "family-secondary output is not an exact candidate artifact"
                )
            role = _family_secondary_output_role(entry)
            if role in role_paths:
                raise CandidateContractError(
                    f"duplicate family-secondary output role: {role}"
                )
            relative = source.relative_to(candidate_dir).as_posix()
            component = {
                "role": role,
                "kind": "calibration",
                "path": relative,
                "sha256": str(entry["sha256"]),
                "bytes": int(entry["bytes"]),
                "artifact_kind": str(entry.get("artifact_kind") or ""),
                "fit_scope": str(entry.get("fit_scope") or ""),
                "market_id": str(entry.get("market_id") or ""),
            }
            role_paths[role] = relative
            role_kinds[role] = "calibration"
            family_output_components[role] = component
            audit_payloads[role] = _read_json(
                source, label=f"family-secondary output {role}"
            )
    graph = _finalize_payload(
        {
            "schema_version": BASE_MODEL_SERVING_GRAPH_SCHEMA_VERSION,
            "status": "PASS",
            "markets": markets,
            "shared_components": {
                "afternoon_residual_centering": {
                    "role": shared_role,
                    "kind": "calibration",
                    "path": shared_relative,
                    "sha256": sha256_file(candidate_dir / shared_relative),
                },
                "family_secondary_artifacts": {
                    "role": BASE_MODEL_SHARED_COMPONENT_ROLES["family_secondary_artifacts"],
                    "kind": "calibration",
                    "path": family_relative,
                    "sha256": sha256_file(family_secondary_path),
                },
                **(
                    {
                        "family_secondary_outputs": {
                            "inventory_sha256": output_inventory.get("sha256"),
                            "components": family_output_components,
                        }
                    }
                    if family_output_components
                    else {}
                ),
            },
            "code_constant_components": {
                "empirical_distribution": {
                    "implementation": "weather.model.model_distribution:DistributionMixin",
                    "allowed_only_after_bound_hgb_and_lr_runtime_failure": True,
                    "release_code_identity_required": True,
                },
                "climatology_and_live_signal_transforms": {
                    "implementation": "weather.model.model_distribution:DistributionMixin",
                    "release_code_identity_required": True,
                },
                "market_spec_and_event_config": {
                    "implementation": (
                        "weather.market.market_registry:BUILTIN_SPECS;"
                        "weather.market.market_config:MarketConfig"
                    ),
                    "release_code_identity_required": True,
                    "frozen_location_roles": [
                        "locations_config",
                        "location_market_events_config",
                        "markets_config",
                    ],
                },
                "calibration_transform_defaults": {
                    "implementation": "weather.model.calibration_runtime",
                    "release_code_identity_required": True,
                    "artifact_presence_required": True,
                },
            },
            "global_path_fallback_allowed": False,
            "mixed_bound_unbound_components_allowed": False,
        }
    )
    graph_path = candidate_dir / SEMANTIC_PATHS["base_model_serving_graph"]
    _write_json_exclusive(graph_path, graph)
    return {
        "graph": graph,
        "role_paths": role_paths,
        "role_kinds": role_kinds,
        "audit_payloads": audit_payloads,
    }


def _component_hash(payload: Mapping[str, Any]) -> str:
    return _payload_sha256(_json_safe(payload))


def _imputer_record(imputer: Any) -> dict[str, Any]:
    statistics = getattr(imputer, "statistics_", None)
    if statistics is None and isinstance(imputer, Mapping):
        statistics = imputer.get("statistics") or imputer.get("imputer_median")
    if hasattr(statistics, "tolist"):
        statistics = statistics.tolist()
    record = {
        "class": f"{type(imputer).__module__}.{type(imputer).__qualname__}",
        "strategy": getattr(imputer, "strategy", None),
        "keep_empty_features": getattr(imputer, "keep_empty_features", None),
        "n_features_in": getattr(imputer, "n_features_in_", None),
        "statistics": statistics,
        "missing_value_behavior": "median_imputation_then_model_transform",
    }
    safe = _json_safe(record)
    safe["component_sha256"] = _component_hash(safe)
    return safe


def _bundle_sidecars(bundle: Mapping[str, Any], bundle_sha256: str) -> dict[str, dict[str, Any]]:
    models = bundle.get("models")
    if not isinstance(models, Mapping) or not models:
        raise CandidateContractError("candidate model bundle has no hourly model components")
    feature_models: dict[str, Any] = {}
    imputer_models: dict[str, Any] = {}
    temperatures: dict[str, Any] = {}
    for raw_hour, raw_model in sorted(models.items(), key=lambda row: str(row[0])):
        hour = str(raw_hour)
        if not isinstance(raw_model, Mapping):
            raise CandidateContractError(f"candidate hourly model {hour!r} is not a mapping")
        feature_names = [str(value) for value in raw_model.get("feature_names") or []]
        if not feature_names:
            raise CandidateContractError(f"candidate hourly model {hour!r} has no feature contract")
        feature_models[hour] = {
            "feature_names": feature_names,
            "feature_names_sha256": hashlib.sha256(
                "\n".join(feature_names).encode("utf-8")
            ).hexdigest(),
            "feature_count": len(feature_names),
            "feature_schema_version": raw_model.get("feature_schema_version")
            or bundle.get("feature_schema_version"),
            "input_unit": bundle.get("family_unit"),
            "missing_value_behavior": "pooled_imputer_metadata",
        }
        imputer = raw_model.get("imputer")
        if imputer is None:
            raise CandidateContractError(f"candidate hourly model {hour!r} has no imputer")
        imputer_models[hour] = _imputer_record(imputer)
        temperatures[hour] = _json_safe(raw_model.get("temperature", 1.0))
    feature_schema = _finalize_payload(
        {
            "schema_version": schema_version("pooled_feature_serving_schema"),
            "bundle_sha256": bundle_sha256,
            "feature_schema_version": bundle.get("feature_schema_version"),
            "family_unit": bundle.get("family_unit"),
            "prediction_mode": bundle.get("prediction_mode"),
            "feature_subset": bundle.get("feature_subset"),
            "feature_subset_contract": bundle.get("feature_subset_contract") or {},
            "models": feature_models,
        }
    )
    imputer = _finalize_payload(
        {
            "schema_version": schema_version("pooled_imputer_metadata"),
            "bundle_sha256": bundle_sha256,
            "models": imputer_models,
        }
    )
    postprocess = _json_safe(bundle.get("postprocess") or {})
    calibrator = _finalize_payload(
        {
            "schema_version": schema_version("pooled_calibrator_metadata"),
            "bundle_sha256": bundle_sha256,
            "temperature_by_hour": temperatures,
            "adjacent_calibration": postprocess.get("adjacent_calibration") or {},
            "market_bias_calibration": postprocess.get("market_bias_calibration") or {},
            "exact_winner_calibration": postprocess.get("exact_winner_catchup") or {},
        }
    )
    postprocessor = _finalize_payload(
        {
            "schema_version": schema_version("pooled_postprocessor_metadata"),
            "bundle_sha256": bundle_sha256,
            "postprocess": postprocess,
        }
    )
    return {
        "pooled_feature_schema": feature_schema,
        "pooled_imputer_metadata": imputer,
        "pooled_calibrator_metadata": calibrator,
        "pooled_postprocessor_metadata": postprocessor,
    }


def _route_table(
    *,
    candidate_id: str,
    parent_release: str | None,
    promotion: Mapping[str, Any],
    family_unit: str,
    base_model_graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    decision_markets = {
        "promote": sorted({str(value) for value in promotion.get("promote_markets") or []}),
        "shadow": sorted({str(value) for value in promotion.get("shadow_markets") or []}),
        "blocked": sorted({str(value) for value in promotion.get("blocked_markets") or []}),
    }
    memberships: dict[str, list[str]] = {}
    for decision, markets in decision_markets.items():
        for market_id in markets:
            memberships.setdefault(market_id, []).append(decision)
    overlaps = {market: values for market, values in memberships.items() if len(values) != 1}
    if overlaps:
        raise CandidateContractError(f"promotion market routes overlap: {overlaps}")
    if not memberships:
        raise CandidateContractError("promotion decision contains no market routes")
    routes = {}
    for market_id, values in sorted(memberships.items()):
        decision = values[0]
        routes[market_id] = {
            "decision": decision,
            "artifact_role": "pooled_band_model" if decision in {"promote", "shadow"} else None,
            "candidate_variant_id": f"{candidate_id}.pooled_band" if decision in {"promote", "shadow"} else None,
            "serving_release": candidate_id if decision == "promote" else parent_release,
            "counts_toward_promotion": decision == "promote",
            "base_model_graph_role": "base_model_serving_graph",
            "base_model_market_id": market_id,
            "base_model_component_roles": sorted(
                {
                    str(row.get("role"))
                    for row in (
                        (
                            ((base_model_graph or {}).get("markets") or {}).get(market_id)
                            or {}
                        ).get("components")
                        or {}
                    ).values()
                    if isinstance(row, Mapping) and row.get("role")
                }
            ),
        }
    return _finalize_payload(
        {
            "schema_version": schema_version("release_market_route_table"),
            "contract": "nightly_candidate_only",
            "candidate_release_id": candidate_id,
            "parent_release_id": parent_release,
            "family_unit": family_unit,
            "objective": "band",
            "promotion_verdict": promotion.get("verdict"),
            "markets": routes,
        }
    )


def _point_in_time_route_selection(route: Mapping[str, Any]) -> dict[str, Any]:
    decisions = {"promote": [], "shadow": [], "blocked": []}
    for market_id, row in (route.get("markets") or {}).items():
        if not isinstance(row, Mapping) or row.get("decision") not in decisions:
            raise CandidateContractError(
                "market route table has an invalid point-in-time decision"
            )
        decisions[str(row["decision"])].append(str(market_id))
    for values in decisions.values():
        values.sort()
    verdict = (
        "blocked"
        if decisions["blocked"]
        else "promote_ready"
        if decisions["promote"]
        else "shadow"
    )
    return {
        "verdict": verdict,
        "promote_markets": decisions["promote"],
        "shadow_markets": decisions["shadow"],
        "blocked_markets": decisions["blocked"],
    }


def _settlement_rules(locations: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for raw in locations.get("locations") or []:
        if not isinstance(raw, Mapping) or not raw.get("id"):
            continue
        settlement = raw.get("settlement") or {}
        polymarket = raw.get("polymarket") or {}
        rows.append(
            {
                "location_id": str(raw["id"]),
                "market_unit": raw.get("market_unit"),
                "settlement_unit": settlement.get("unit"),
                "precision": settlement.get("precision"),
                "source_type": settlement.get("source_type"),
                "station_id": settlement.get("station_id"),
                "resolution_source_url": settlement.get("resolution_source_url"),
                "event_slug_prefix": polymarket.get("event_slug_prefix"),
            }
        )
    if not rows:
        raise CandidateContractError("locations config contains no settlement contracts")
    invalid_units = sorted(
        row["location_id"]
        for row in rows
        if row.get("market_unit") not in {"C", "F"}
        or row.get("settlement_unit") != row.get("market_unit")
    )
    if invalid_units:
        raise CandidateContractError(
            f"settlement and market units are missing or inconsistent: {invalid_units}"
        )
    return _finalize_payload(
        {
            "schema_version": schema_version("release_settlement_rules"),
            "band_contract": {
                "kinds": ["eq", "gte", "lte"],
                "probability_partition": "mutually_exclusive_exhaustive_native_unit_bands",
                "rounding": "whole_degree_half_up",
                "binary_yes_outcome_index": 0,
            },
            "locations": sorted(rows, key=lambda row: row["location_id"]),
        }
    )


def _corpus_manifest(
    bundle: Mapping[str, Any],
    bundle_sha256: str,
    *,
    production_evaluation: Mapping[str, Any] | None = None,
    research_corpus_lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if production_evaluation is not None and research_corpus_lineage is not None:
        raise CandidateContractError(
            "production evaluation and research corpus lineage overrides are mutually exclusive"
        )
    lineage = _json_safe(
        research_corpus_lineage
        if research_corpus_lineage is not None
        else bundle.get("corpus_lineage") or {}
    )
    if production_evaluation is not None:
        trainer_evaluation = lineage.get("evaluation")
        lineage["evaluation"] = _json_safe(production_evaluation)
        lineage["evaluation_source"] = (
            "production_point_in_time_locked_candidate_corpus"
        )
        if (
            isinstance(trainer_evaluation, Mapping)
            and int(trainer_evaluation.get("row_count") or 0) > 0
        ):
            lineage["trainer_diagnostic_evaluation"] = trainer_evaluation
    required_partitions = ("selection_training", "evaluation", "final_refit")
    failures = []
    for name in required_partitions:
        row = lineage.get(name) if isinstance(lineage, Mapping) else None
        if not isinstance(row, Mapping) or not row.get("sha256"):
            failures.append(f"{name}:missing_hash")
            continue
        if not row.get("row_count") or not row.get("target_date_min") or not row.get("target_date_max"):
            failures.append(f"{name}:missing_rows_or_date_bounds")
    model_inputs = lineage.get("model_input_fields") if isinstance(lineage, Mapping) else None
    if not isinstance(model_inputs, list) or not model_inputs:
        failures.append("model_input_fields:missing")
    if failures:
        raise CandidateContractError(
            "candidate bundle has incomplete training/evaluation corpus lineage: " + ", ".join(failures)
        )
    return _finalize_payload(
        {
            "schema_version": schema_version("release_training_evaluation_corpus"),
            "bundle_sha256": bundle_sha256,
            "corpus_lineage": lineage,
            "lineage_source": (
                "verified_immutable_release"
                if research_corpus_lineage is not None
                else "production_point_in_time_qualification"
                if production_evaluation is not None
                else "candidate_bundle"
            ),
        }
    )


def _production_evaluation_lineage(
    manifest: Mapping[str, Any],
    qualification: Mapping[str, Any],
) -> dict[str, Any]:
    derived = manifest.get("derived_artifact")
    inputs = manifest.get("inputs")
    if not isinstance(derived, Mapping) or not isinstance(inputs, list):
        raise CandidateContractError(
            "production point-in-time evaluation lineage is incomplete"
        )
    graph = manifest.get("candidate_training_graph")
    stage_bindings = (
        graph.get("selection_stage_bindings")
        if isinstance(graph, Mapping)
        else None
    )
    calibration_binding = (
        stage_bindings.get("calibration")
        if isinstance(stage_bindings, Mapping)
        else None
    )
    dates = sorted(
        str(value)
        for value in (
            calibration_binding.get("locked_dates")
            if isinstance(calibration_binding, Mapping)
            else ()
        )
    )
    locked_inputs = [
        row
        for row in inputs
        if isinstance(row, Mapping)
        and str(row.get("target_date") or "") in set(dates)
    ]
    observed_dates = {
        str(row.get("target_date") or "") for row in locked_inputs
    }
    row_count = sum(int(row.get("source_row_count") or 0) for row in locked_inputs)
    corpus_sha256 = str(qualification.get("corpus_sha256") or "")
    manifest_hash = str(
        qualification.get("materialization_manifest_hash") or ""
    )
    failures = []
    if row_count <= 0:
        failures.append("empty_corpus")
    if len(dates) != 14 or observed_dates != set(dates):
        failures.append(f"locked_fleet_dates={len(observed_dates)}/{len(dates)}")
    if not _SHA256_RE.fullmatch(corpus_sha256):
        failures.append("invalid_corpus_sha256")
    if not _SHA256_RE.fullmatch(manifest_hash):
        failures.append("invalid_manifest_hash")
    if failures:
        raise CandidateContractError(
            "production point-in-time evaluation lineage is invalid: "
            + ", ".join(failures)
        )
    evaluation_binding = {
        "corpus_sha256": corpus_sha256,
        "locked_dates": dates,
        "streaming_evaluation_hash": qualification.get(
            "streaming_evaluation_hash"
        ),
    }
    return {
        "row_count": row_count,
        "sha256": _payload_sha256(evaluation_binding),
        "hash_algorithm": "sha256_canonical_binding",
        "corpus_sha256": corpus_sha256,
        "evaluation_binding": evaluation_binding,
        "target_date_min": dates[0],
        "target_date_max": dates[-1],
        "target_date_count": len(dates),
        "window_days": int(qualification.get("locked_window_days") or 0),
        "materialization_manifest_hash": manifest_hash,
        "validation_plan_hash": qualification.get("validation_plan_hash"),
        "streaming_evaluation_hash": qualification.get(
            "streaming_evaluation_hash"
        ),
        "candidate_training_graph_hash": qualification.get(
            "candidate_training_graph_hash"
        ),
        "selection_universe_sha256": qualification.get(
            "selection_universe_sha256"
        ),
    }


def _verify_payload_hash(payload: Mapping[str, Any], *, label: str) -> None:
    expected = payload.get("payload_sha256")
    actual = _payload_sha256(payload, omit=("payload_sha256",))
    if expected != actual:
        raise CandidateContractError(f"{label} payload hash is invalid")


def _verify_component_sidecars(sidecars: Mapping[str, Mapping[str, Any]]) -> None:
    feature = sidecars["pooled_feature_schema"]
    imputer = sidecars["pooled_imputer_metadata"]
    calibrator = sidecars["pooled_calibrator_metadata"]
    corpus = sidecars["training_evaluation_corpus"]
    feature_models = feature.get("models")
    imputer_models = imputer.get("models")
    temperatures = calibrator.get("temperature_by_hour")
    if not all(isinstance(value, Mapping) for value in (feature_models, imputer_models, temperatures)):
        raise CandidateContractError("semantic component sidecars omit hourly metadata")
    hours = set(feature_models)
    if not hours or set(imputer_models) != hours or set(temperatures) != hours:
        raise CandidateContractError("feature, imputer, and calibrator hour contracts disagree")
    all_feature_names: set[str] = set()
    for hour in sorted(hours):
        feature_row = feature_models[hour]
        imputer_row = imputer_models[hour]
        names = [str(value) for value in feature_row.get("feature_names") or []]
        if (
            not names
            or feature_row.get("feature_count") != len(names)
            or feature_row.get("feature_names_sha256")
            != hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
        ):
            raise CandidateContractError(f"feature sidecar metadata is invalid for hour {hour}")
        expected_component = _payload_sha256(imputer_row, omit=("component_sha256",))
        if imputer_row.get("component_sha256") != expected_component:
            raise CandidateContractError(f"imputer component hash is invalid for hour {hour}")
        statistics = imputer_row.get("statistics")
        if not isinstance(statistics, list) or len(statistics) != len(names):
            raise CandidateContractError(
                f"imputer statistics do not match feature order for hour {hour}"
            )
        all_feature_names.update(names)
    lineage = corpus.get("corpus_lineage")
    model_inputs = lineage.get("model_input_fields") if isinstance(lineage, Mapping) else None
    if sorted({str(value) for value in model_inputs or []}) != sorted(all_feature_names):
        raise CandidateContractError(
            "training corpus model inputs do not match the frozen feature schema"
        )


def _verify_base_model_graph(
    *,
    graph: Mapping[str, Any],
    route: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    required_role_kinds: Mapping[str, Any],
) -> None:
    if graph.get("schema_version") != BASE_MODEL_SERVING_GRAPH_SCHEMA_VERSION:
        raise CandidateContractError("base model serving graph schema is unsupported")
    markets = graph.get("markets")
    route_markets = route.get("markets")
    if (
        not isinstance(markets, Mapping)
        or not markets
        or not isinstance(route_markets, Mapping)
        or set(markets) != set(route_markets)
    ):
        raise CandidateContractError(
            "base model serving graph markets do not exactly match candidate routes"
        )
    dynamic_roles: set[str] = set()
    for market_id, market in sorted(markets.items()):
        components = market.get("components") if isinstance(market, Mapping) else None
        if not isinstance(components, Mapping) or set(components) != set(
            BASE_MODEL_MARKET_COMPONENT_KINDS
        ):
            raise CandidateContractError(
                f"base model serving graph component inventory is incomplete for {market_id!r}"
            )
        component_roles: set[str] = set()
        for component_name, component in sorted(components.items()):
            if not isinstance(component, Mapping):
                raise CandidateContractError(
                    f"base model serving graph component is invalid: {market_id}.{component_name}"
                )
            role = str(component.get("role") or "")
            expected_kind = BASE_MODEL_MARKET_COMPONENT_KINDS[component_name]
            artifact = artifacts.get(role)
            if (
                component.get("kind") != expected_kind
                or required_role_kinds.get(role) != expected_kind
                or not isinstance(artifact, Mapping)
                or any(component.get(field) != artifact.get(field) for field in ("path", "kind", "sha256"))
            ):
                raise CandidateContractError(
                    f"base model serving graph binding is invalid: {market_id}.{component_name}"
                )
            component_roles.add(role)
            dynamic_roles.add(role)
        market_route = route_markets[market_id]
        if (
            not isinstance(market_route, Mapping)
            or market_route.get("base_model_graph_role") != "base_model_serving_graph"
            or market_route.get("base_model_market_id") != market_id
            or set(market_route.get("base_model_component_roles") or []) != component_roles
        ):
            raise CandidateContractError(
                f"base model route binding is invalid for market {market_id!r}"
            )
        if (
            market.get("global_path_fallback_allowed") is not False
            or market.get("calibration_fallback_allowed") is not False
        ):
            raise CandidateContractError(
                f"base model fallback policy is invalid for market {market_id!r}"
            )
    shared = graph.get("shared_components")
    if not isinstance(shared, Mapping):
        raise CandidateContractError("base model shared component inventory is missing")
    afternoon = shared.get("afternoon_residual_centering")
    afternoon_role = BASE_MODEL_SHARED_COMPONENT_ROLES["afternoon_residual_centering"]
    afternoon_artifact = artifacts.get(afternoon_role)
    if (
        not isinstance(afternoon, Mapping)
        or afternoon.get("role") != afternoon_role
        or not isinstance(afternoon_artifact, Mapping)
        or any(
            afternoon.get(field) != afternoon_artifact.get(field)
            for field in ("path", "kind", "sha256")
        )
    ):
        raise CandidateContractError("base model shared afternoon binding is invalid")
    dynamic_roles.add(afternoon_role)
    family = shared.get("family_secondary_artifacts")
    family_role = BASE_MODEL_SHARED_COMPONENT_ROLES["family_secondary_artifacts"]
    if (
        not isinstance(family, Mapping)
        or family.get("role") != family_role
        or family.get("kind") != "calibration"
        or not isinstance(artifacts.get(family_role), Mapping)
        or any(
            family.get(field) != artifacts[family_role].get(field)
            for field in ("path", "kind", "sha256")
        )
    ):
        raise CandidateContractError("base model shared family-secondary binding is invalid")
    family_outputs = shared.get("family_secondary_outputs")
    production_graph = bool(
        set(required_role_kinds) & set(PRODUCTION_POINT_IN_TIME_ROLE_KINDS)
    )
    if production_graph:
        components = (
            family_outputs.get("components")
            if isinstance(family_outputs, Mapping)
            else None
        )
        if (
            not isinstance(components, Mapping)
            or not components
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(family_outputs.get("inventory_sha256") or ""),
            )
        ):
            raise CandidateContractError(
                "base model family-secondary output inventory is missing"
            )
        for role, component in sorted(components.items()):
            artifact = artifacts.get(role)
            if (
                not str(role).startswith("family_secondary_output.")
                or not isinstance(component, Mapping)
                or component.get("role") != role
                or component.get("kind") != "calibration"
                or required_role_kinds.get(role) != "calibration"
                or not isinstance(artifact, Mapping)
                or any(
                    component.get(field) != artifact.get(field)
                    for field in ("path", "kind", "sha256", "bytes")
                )
            ):
                raise CandidateContractError(
                    f"base model family-secondary output binding is invalid: {role}"
                )
            dynamic_roles.add(role)
    elif family_outputs is not None:
        raise CandidateContractError(
            "research-only base graph declares production family-secondary outputs"
        )
    expected_dynamic_roles = (
        set(required_role_kinds)
        - set(SEMANTIC_SERVING_ROLE_KINDS)
        - set(PRODUCTION_POINT_IN_TIME_ROLE_KINDS)
    )
    if dynamic_roles != expected_dynamic_roles:
        raise CandidateContractError("base model dynamic role inventory is incomplete")
    if (
        graph.get("global_path_fallback_allowed") is not False
        or graph.get("mixed_bound_unbound_components_allowed") is not False
    ):
        raise CandidateContractError("base model graph permits unsafe fallback or mixed binding")
    code_constants = graph.get("code_constant_components")
    if (
        not isinstance(code_constants, Mapping)
        or set(code_constants)
        != {
            "empirical_distribution",
            "climatology_and_live_signal_transforms",
            "market_spec_and_event_config",
            "calibration_transform_defaults",
        }
        or any(
            not isinstance(component, Mapping)
            or component.get("release_code_identity_required") is not True
            or not component.get("implementation")
            for component in code_constants.values()
        )
    ):
        raise CandidateContractError("base model code-constant contract is incomplete")


def verify_candidate_semantic_contract(candidate_dir: str | Path) -> dict[str, Any]:
    """Verify sidecar hashes and exact-PASS audit before release construction."""

    root = Path(candidate_dir).resolve()
    contract_path = root / SEMANTIC_PATHS["semantic_serving_contract"]
    contract = _read_json(contract_path, label="semantic serving contract")
    _verify_payload_hash(contract, label="semantic serving contract")
    if contract.get("schema_version") != SEMANTIC_CONTRACT_SCHEMA_VERSION:
        raise CandidateContractError("semantic serving contract schema is unsupported")
    if contract.get("status") != "PASS":
        raise CandidateContractError("semantic serving contract is not exact PASS")
    candidate_mode = str(contract.get("candidate_mode") or "")
    if candidate_mode not in CANDIDATE_MODES:
        raise CandidateContractError("semantic serving contract candidate mode is invalid")
    production_capable = contract.get("production_capable")
    if production_capable is not (candidate_mode == PRODUCTION_CANDIDATE_MODE):
        raise CandidateContractError("semantic serving contract production capability is invalid")
    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise CandidateContractError("semantic serving contract artifact map is missing")
    required_role_kinds = contract.get("required_role_kinds")
    if not isinstance(required_role_kinds, Mapping):
        raise CandidateContractError("semantic serving contract required role map is missing")
    if any(required_role_kinds.get(role) != kind for role, kind in SEMANTIC_SERVING_ROLE_KINDS.items()):
        raise CandidateContractError("semantic serving contract fixed role map is invalid")
    point_in_time_roles = set(required_role_kinds) & set(PRODUCTION_POINT_IN_TIME_ROLE_KINDS)
    if candidate_mode == PRODUCTION_CANDIDATE_MODE:
        if any(
            required_role_kinds.get(role) != kind
            for role, kind in PRODUCTION_POINT_IN_TIME_ROLE_KINDS.items()
        ):
            raise CandidateContractError(
                "production candidate point-in-time role map is incomplete"
            )
    elif point_in_time_roles:
        raise CandidateContractError(
            "research-only candidate cannot declare production point-in-time roles"
        )
    if set(artifacts) != set(required_role_kinds) - {"semantic_serving_contract"}:
        raise CandidateContractError("semantic serving contract role inventory is incomplete")
    sidecars: dict[str, dict[str, Any]] = {}
    for role, expected_kind in sorted(required_role_kinds.items()):
        if role == "semantic_serving_contract":
            continue
        row = artifacts.get(role)
        if not isinstance(row, Mapping) or row.get("kind") != expected_kind:
            raise CandidateContractError(f"semantic serving role {role!r} has the wrong kind")
        path = root / str(row.get("path") or "")
        if not path.exists() or path.is_symlink() or sha256_file(path) != row.get("sha256"):
            raise CandidateContractError(f"semantic serving role {role!r} hash verification failed")
        if role in INTERNALLY_HASHED_ROLES:
            sidecar = _read_json(path, label=role)
            _verify_payload_hash(sidecar, label=role)
            sidecars[role] = sidecar
    _verify_component_sidecars(sidecars)
    _verify_base_model_graph(
        graph=sidecars["base_model_serving_graph"],
        route=sidecars["market_route_table"],
        artifacts=artifacts,
        required_role_kinds=required_role_kinds,
    )
    qualification: dict[str, Any] | None = None
    if candidate_mode == PRODUCTION_CANDIDATE_MODE:
        frozen_qualification = contract.get("point_in_time_qualification")
        if not isinstance(frozen_qualification, Mapping):
            raise CandidateContractError(
                "production candidate has no frozen point-in-time qualification identity"
            )
        frozen_candidate_artifacts = frozen_qualification.get("candidate_artifacts")
        if not isinstance(frozen_candidate_artifacts, Mapping):
            raise CandidateContractError(
                "production candidate point-in-time artifact identities are missing"
            )
        frozen_stage_bindings = frozen_qualification.get(
            "selection_stage_bindings"
        )
        if (
            not isinstance(frozen_stage_bindings, Mapping)
            or not isinstance(frozen_stage_bindings.get("routing"), Mapping)
        ):
            raise CandidateContractError(
                "production candidate frozen routing selection binding is missing"
            )
        release_bundle, _ = _load_verified_bundle(
            root / str(artifacts["pooled_band_model"]["path"])
        )
        release_family_secondary = _read_json(
            root / str(artifacts["family_secondary_calibration"]["path"]),
            label="family secondary calibration",
        )
        family_inventory = release_family_secondary.get(
            "output_artifact_inventory"
        )
        family_output_graph = (
            sidecars["base_model_serving_graph"].get("shared_components") or {}
        ).get("family_secondary_outputs")
        family_components = (
            family_output_graph.get("components")
            if isinstance(family_output_graph, Mapping)
            else None
        )
        inventory_entries = (
            family_inventory.get("entries")
            if isinstance(family_inventory, Mapping)
            else None
        )
        if (
            not isinstance(inventory_entries, list)
            or not isinstance(family_components, Mapping)
            or family_inventory.get("sha256")
            != family_output_graph.get("inventory_sha256")
            or int(family_inventory.get("entry_count") or -1)
            != len(inventory_entries)
            or {
                _family_secondary_output_role(entry)
                for entry in inventory_entries
                if isinstance(entry, Mapping)
            }
            != set(family_components)
        ):
            raise CandidateContractError(
                "production family-secondary output inventory differs from the frozen graph"
            )
        for entry in inventory_entries:
            if not isinstance(entry, Mapping):
                raise CandidateContractError(
                    "production family-secondary output inventory is malformed"
                )
            component = family_components[_family_secondary_output_role(entry)]
            if any(
                component.get(graph_field) != entry.get(inventory_field)
                for graph_field, inventory_field in (
                    ("sha256", "sha256"),
                    ("bytes", "bytes"),
                    ("artifact_kind", "artifact_kind"),
                    ("fit_scope", "fit_scope"),
                    ("market_id", "market_id"),
                )
            ):
                raise CandidateContractError(
                    "production family-secondary component differs from its manifest"
                )
        try:
            embedded_training_evidence = (
                verify_embedded_point_in_time_training_evidence(release_bundle)
            )
            expected_stage_bindings = {
                "calibration": verify_point_in_time_selection_binding(
                    release_family_secondary,
                    stage="calibration",
                ),
                "routing": dict(frozen_stage_bindings["routing"]),
            }
            qualification = verify_production_point_in_time_artifacts(
                corpus_path=root / str(artifacts["point_in_time_corpus"]["path"]),
                materialization_manifest_path=(
                    root / str(artifacts["point_in_time_materialization_manifest"]["path"])
                ),
                validation_plan_path=(
                    root / str(artifacts["point_in_time_validation_plan"]["path"])
                ),
                streaming_evaluation_path=(
                    root / str(artifacts["point_in_time_streaming_evaluation"]["path"])
                ),
                expected_candidate_id=str(contract.get("candidate_id") or ""),
                expected_release_id=str(contract.get("candidate_id") or ""),
                expected_candidate_artifact_sha256=str(
                    artifacts["pooled_band_model"]["sha256"]
                ),
                expected_calibration_artifact_sha256=str(
                    artifacts["family_secondary_calibration"]["sha256"]
                ),
                expected_routing_artifact_sha256=str(
                    frozen_candidate_artifacts.get("routing_sha256") or ""
                ),
                expected_route_selection=_point_in_time_route_selection(
                    sidecars["market_route_table"]
                ),
                expected_training_evidence=embedded_training_evidence,
                expected_selection_stage_bindings=expected_stage_bindings,
                max_age_days=MAX_PRODUCTION_EVALUATION_AGE_DAYS,
                inspect_corpus_parquet=True,
            )
        except (PointInTimeContractViolation, OSError, ValueError) as exc:
            raise CandidateContractError(
                f"production point-in-time qualification failed: {exc}"
            ) from exc
        if qualification != dict(frozen_qualification):
            raise CandidateContractError(
                "production point-in-time qualification differs from the frozen identity"
            )
    audit = _read_json(
        root / SEMANTIC_PATHS["candidate_input_leakage_audit"],
        label="candidate input leakage audit",
    )
    _verify_payload_hash(audit, label="candidate input leakage audit")
    if audit.get("status") != "PASS" or audit.get("rejection_count") != 0:
        raise CandidateContractError("candidate input leakage audit is not exact PASS")
    return {
        "status": "PASS",
        "contract_path": str(contract_path),
        "contract_sha256": sha256_file(contract_path),
        "declarations": [
            {
                "path": SEMANTIC_PATHS["semantic_serving_contract"],
                "kind": "contract",
                "role": "semantic_serving_contract",
            },
            *[
                {"path": row["path"], "kind": row["kind"], "role": role}
                for role, row in sorted(artifacts.items())
            ],
        ],
        "route": _read_json(root / SEMANTIC_PATHS["market_route_table"], label="market route table"),
        "audit": audit,
        "candidate_mode": candidate_mode,
        "production_capable": production_capable,
        "point_in_time_qualification": qualification,
    }


def freeze_candidate_semantic_contract(
    *,
    candidate_dir: str | Path,
    model_bundle_path: str | Path,
    family_secondary_path: str | Path,
    artifact_registry_path: str | Path,
    repo_root: str | Path,
    candidate_id: str,
    parent_release: str | None,
    promotion: Mapping[str, Any],
    family_unit: str,
    candidate_mode: str = RESEARCH_ONLY_CANDIDATE_MODE,
    point_in_time_artifacts: Mapping[str, str | Path] | None = None,
    research_corpus_lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze configs/sidecars, persist leakage evidence, and verify exact PASS."""

    started = time.time()
    root = Path(candidate_dir).resolve()
    mode = str(candidate_mode).strip()
    if mode not in CANDIDATE_MODES:
        raise CandidateContractError(f"unsupported candidate mode: {mode!r}")
    point_in_time_sources = dict(point_in_time_artifacts or {})
    if mode == PRODUCTION_CANDIDATE_MODE:
        if research_corpus_lineage is not None:
            raise CandidateContractError(
                "production candidate cannot use a research corpus-lineage override"
            )
        if set(point_in_time_sources) != set(PRODUCTION_POINT_IN_TIME_ROLE_KINDS):
            raise CandidateContractError(
                "production candidate requires the exact point-in-time artifact role set"
            )
    elif point_in_time_sources:
        raise CandidateContractError(
            "research-only candidate cannot include production point-in-time artifacts"
        )
    config_root = Path(repo_root).resolve() / "config"
    model_path = Path(model_bundle_path).resolve()
    bundle, bundle_sha = _load_verified_bundle(model_path)
    family_secondary = _read_json(
        Path(family_secondary_path).resolve(),
        label="family secondary calibration",
    )
    if mode == PRODUCTION_CANDIDATE_MODE:
        try:
            from weather.calibration.family_secondary_artifacts import (
                verify_production_family_manifest,
            )

            verify_production_family_manifest(family_secondary)
        except (OSError, TypeError, ValueError) as exc:
            raise CandidateContractError(
                f"production family-secondary calibration failed verification: {exc}"
            ) from exc
    sidecars = _bundle_sidecars(bundle, bundle_sha)
    model_relative_path = model_path.relative_to(root).as_posix()
    source_documents = {
        "model_variant_registry": _freeze_model_variant_registry(
            config_root / "model_variant_registry.json",
            root / SEMANTIC_PATHS["model_variant_registry"],
            candidate_id=candidate_id,
            bundle=bundle,
            bundle_sha256=bundle_sha,
            model_relative_path=model_relative_path,
        ),
        "locations_config": _copy_canonical_json(
            config_root / "locations.json",
            root / SEMANTIC_PATHS["locations_config"],
            label="locations config",
        ),
        "location_market_events_config": _copy_canonical_json(
            config_root / "location_market_events.json",
            root / SEMANTIC_PATHS["location_market_events_config"],
            label="location market-events config",
        ),
        "markets_config": _copy_canonical_json(
            config_root / "markets.json",
            root / SEMANTIC_PATHS["markets_config"],
            label="markets config",
        ),
    }
    route_without_base = _route_table(
        candidate_id=candidate_id,
        parent_release=parent_release,
        promotion=promotion,
        family_unit=family_unit,
    )
    base_graph_info = _freeze_base_model_serving_graph(
        candidate_dir=root,
        repo_root=Path(repo_root).resolve(),
        market_ids=list((route_without_base.get("markets") or {}).keys()),
        family_secondary_path=Path(family_secondary_path),
        family_secondary_manifest=family_secondary,
    )
    base_graph = base_graph_info["graph"]
    route = _route_table(
        candidate_id=candidate_id,
        parent_release=parent_release,
        promotion=promotion,
        family_unit=family_unit,
        base_model_graph=base_graph,
    )
    settlement = _settlement_rules(source_documents["locations_config"])
    frozen_point_in_time_paths: dict[str, Path] = {}
    for role, source_value in sorted(point_in_time_sources.items()):
        source = Path(source_value).resolve()
        destination = root / SEMANTIC_PATHS[role]
        if source != destination.resolve():
            _copy_file_exclusive(source, destination, label=role)
        elif source.is_symlink() or not source.exists() or not source.is_file():
            raise CandidateContractError(f"{role} is missing or invalid: {source}")
        frozen_point_in_time_paths[role] = destination
    frozen_point_in_time_qualification: dict[str, Any] | None = None
    if mode == PRODUCTION_CANDIDATE_MODE:
        routing_source = Path(str(promotion.get("path") or "")).resolve()
        if not routing_source.is_file() or routing_source.is_symlink():
            raise CandidateContractError(
                "production promotion routing artifact is missing or invalid"
            )
        routing_payload = _read_json(
            routing_source,
            label="production promotion routing artifact",
        )
        try:
            embedded_training_evidence = (
                verify_embedded_point_in_time_training_evidence(bundle)
            )
            expected_stage_bindings = {
                "calibration": verify_point_in_time_selection_binding(
                    family_secondary,
                    stage="calibration",
                ),
                "routing": verify_point_in_time_selection_binding(
                    routing_payload,
                    stage="routing",
                ),
            }
            frozen_point_in_time_qualification = verify_production_point_in_time_artifacts(
                corpus_path=frozen_point_in_time_paths["point_in_time_corpus"],
                materialization_manifest_path=frozen_point_in_time_paths[
                    "point_in_time_materialization_manifest"
                ],
                validation_plan_path=frozen_point_in_time_paths[
                    "point_in_time_validation_plan"
                ],
                streaming_evaluation_path=frozen_point_in_time_paths[
                    "point_in_time_streaming_evaluation"
                ],
                expected_candidate_id=candidate_id,
                expected_release_id=candidate_id,
                expected_candidate_artifact_sha256=bundle_sha,
                expected_calibration_artifact_sha256=sha256_file(
                    Path(family_secondary_path).resolve()
                ),
                expected_routing_artifact_sha256=sha256_file(routing_source),
                expected_route_selection=_point_in_time_route_selection(route),
                expected_training_evidence=embedded_training_evidence,
                expected_selection_stage_bindings=expected_stage_bindings,
                max_age_days=MAX_PRODUCTION_EVALUATION_AGE_DAYS,
                inspect_corpus_parquet=True,
            )
        except (PointInTimeContractViolation, OSError, ValueError) as exc:
            raise CandidateContractError(
                f"production point-in-time qualification failed: {exc}"
            ) from exc

    production_evaluation = None
    if frozen_point_in_time_qualification is not None:
        frozen_manifest = _read_json(
            frozen_point_in_time_paths[
                "point_in_time_materialization_manifest"
            ],
            label="point-in-time materialization manifest",
        )
        production_evaluation = _production_evaluation_lineage(
            frozen_manifest,
            frozen_point_in_time_qualification,
        )
    corpus = _corpus_manifest(
        bundle,
        bundle_sha,
        production_evaluation=production_evaluation,
        research_corpus_lineage=research_corpus_lineage,
    )
    generated = {
        **sidecars,
        "market_route_table": route,
        "settlement_rules": settlement,
        "training_evaluation_corpus": corpus,
    }
    for role, payload in generated.items():
        _write_json_exclusive(root / SEMANTIC_PATHS[role], payload)

    artifact_registry = _read_json(
        Path(artifact_registry_path).resolve(),
        label="artifact registry",
    )

    audit_payloads = {
        "bundle_feature_schema": sidecars["pooled_feature_schema"],
        "bundle_imputer": sidecars["pooled_imputer_metadata"],
        "bundle_calibrator": sidecars["pooled_calibrator_metadata"],
        "bundle_postprocessor": sidecars["pooled_postprocessor_metadata"],
        "market_route_table": route,
        "model_variant_registry": source_documents["model_variant_registry"],
        "family_secondary_calibration": family_secondary,
        "artifact_registry": artifact_registry,
        "training_evaluation_corpus": corpus,
        "base_model_serving_graph": base_graph,
        **base_graph_info["audit_payloads"],
    }
    scan = audit_recursive_model_inputs(audit_payloads)
    input_roles = {
        "pooled_band_model": model_path,
        "family_secondary_calibration": Path(family_secondary_path).resolve(),
        "artifact_registry": Path(artifact_registry_path).resolve(),
        **{
            role: root / SEMANTIC_PATHS[role]
            for role in [*source_documents, *generated]
        },
        "base_model_serving_graph": root / SEMANTIC_PATHS["base_model_serving_graph"],
        **{
            role: root / relative
            for role, relative in base_graph_info["role_paths"].items()
        },
        **frozen_point_in_time_paths,
    }
    input_hashes = []
    for role, path in sorted(input_roles.items()):
        if path.is_symlink() or not path.exists() or not path.is_file():
            raise CandidateContractError(f"semantic contract input is missing or invalid: {role}: {path}")
        input_hashes.append(
            {
                "role": role,
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    audit = _finalize_payload(
        {
            "schema_version": CANDIDATE_LEAKAGE_AUDIT_SCHEMA_VERSION,
            "status": scan["status"],
            "policy": "weather.model.feature_safety",
            "scope": [
                "model",
                "calibration",
                "imputer",
                "postprocessor_guardrail",
                "route",
                "registry",
                "feature_hash_manifest",
            ],
            "evaluation_only_labels_are_model_inputs": False,
            "input_hashes": input_hashes,
            "inspected_value_count": scan["inspected_value_count"],
            "rejection_count": scan["rejection_count"],
            "rejections": scan["rejections"],
        }
    )
    _write_json_exclusive(root / SEMANTIC_PATHS["candidate_input_leakage_audit"], audit)
    if audit["status"] != "PASS":
        reasons = "; ".join(
            f"{row['source']}:{row['path']}={row['value']}"
            for row in audit["rejections"][:10]
        )
        raise CandidateContractError(f"candidate input leakage audit BLOCK: {reasons}")

    role_paths = {
        "pooled_band_model": model_path.relative_to(root).as_posix(),
        "family_secondary_calibration": Path(family_secondary_path).resolve().relative_to(root).as_posix(),
        "artifact_registry": Path(artifact_registry_path).resolve().relative_to(root).as_posix(),
        **{
            role: SEMANTIC_PATHS[role]
            for role in SEMANTIC_SERVING_ROLE_KINDS
            if role
            not in {
                "pooled_band_model",
                "family_secondary_calibration",
                "artifact_registry",
                "semantic_serving_contract",
            }
        },
        **base_graph_info["role_paths"],
        **{
            role: SEMANTIC_PATHS[role]
            for role in PRODUCTION_POINT_IN_TIME_ROLE_KINDS
            if mode == PRODUCTION_CANDIDATE_MODE
        },
    }
    required_role_kinds = {
        **SEMANTIC_SERVING_ROLE_KINDS,
        **base_graph_info["role_kinds"],
        **(
            PRODUCTION_POINT_IN_TIME_ROLE_KINDS
            if mode == PRODUCTION_CANDIDATE_MODE
            else {}
        ),
    }
    artifact_rows = {}
    for role, expected_kind in sorted(required_role_kinds.items()):
        if role == "semantic_serving_contract":
            continue
        relative = role_paths[role]
        path = root / relative
        artifact_rows[role] = {
            "path": relative,
            "kind": expected_kind,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    contract = _finalize_payload(
        {
            "schema_version": SEMANTIC_CONTRACT_SCHEMA_VERSION,
            "status": "PASS",
            "candidate_id": candidate_id,
            "candidate_mode": mode,
            "production_capable": mode == PRODUCTION_CANDIDATE_MODE,
            "bundle_sha256": bundle_sha,
            "leakage_audit_status": audit["status"],
            "required_role_kinds": required_role_kinds,
            "artifacts": artifact_rows,
            **(
                {
                    "point_in_time_qualification": (
                        frozen_point_in_time_qualification
                    )
                }
                if frozen_point_in_time_qualification is not None
                else {}
            ),
            "generated_in_seconds": round(time.time() - started, 3),
        }
    )
    _write_json_exclusive(root / SEMANTIC_PATHS["semantic_serving_contract"], contract)
    return verify_candidate_semantic_contract(root)
