"""Neutral immutable-release verification for all runtime layers.

This module is read-only: it validates manifests, artifacts, runtime
compatibility, and the active pointer. Promotion mutations remain owned by
``weather.operations.release_promotion``.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.paths import ARTIFACTS_ROOT, REPO_ROOT
from weather.point_in_time_contract import (
    ContractViolation as PointInTimeContractViolation,
    verify_production_point_in_time_artifacts,
)
from weather.runtime_identity import get_runtime_identity
from weather.release_contract import (
    BASE_MODEL_MARKET_COMPONENT_KINDS,
    BASE_MODEL_SERVING_GRAPH_SCHEMA_VERSION,
    BASE_MODEL_SHARED_COMPONENT_ROLES,
    CANDIDATE_MODES,
    PRODUCTION_CANDIDATE_MODE,
    PRODUCTION_POINT_IN_TIME_ROLE_KINDS,
    SEMANTIC_CONTRACT_SCHEMA_VERSION,
    SEMANTIC_SERVING_ROLE_KINDS,
    SERVING_ARTIFACT_KINDS,
)
from weather.schema_registry import schema_version


RELEASE_MANIFEST_SCHEMA_VERSION = schema_version("release_manifest")
ACTIVE_POINTER_SCHEMA_VERSION = schema_version("active_release_pointer")
RELEASE_MANIFEST_NAME = "release_manifest.json"
DEFAULT_RELEASES_ROOT = ARTIFACTS_ROOT / "releases"
DEFAULT_ACTIVE_RELEASE_POINTER = DEFAULT_RELEASES_ROOT / "current_release.json"
RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DEPENDENCY_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_KINDS = frozenset(
    {
        "model",
        "calibration",
        "config",
        "imputer",
        "feature_schema",
        "postprocessor",
        "route",
        "registry",
        "settlement_rules",
        "corpus",
        "audit",
        "contract",
        "other",
    }
)


class ReleaseArtifactVerificationError(RuntimeError):
    """An immutable release or pointer failed closed verification."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_payload_sha256(payload: Mapping[str, Any], *, omit: Sequence[str] = ()) -> str:
    normalized = {key: value for key, value in payload.items() if key not in set(omit)}
    try:
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReleaseArtifactVerificationError(
            f"payload is not canonical-JSON serializable: {exc}"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def manifest_content_sha256(manifest: Mapping[str, Any]) -> str:
    return canonical_payload_sha256(manifest, omit=("manifest_sha256",))


def pointer_content_sha256(pointer: Mapping[str, Any]) -> str:
    return canonical_payload_sha256(pointer, omit=("pointer_sha256",))


def strict_json_loads(text: str, *, label: str) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"{label} contains duplicate JSON key: {key!r}")
            payload[key] = value
        return payload

    def reject_constant(value: str) -> None:
        raise ValueError(f"{label} contains non-finite JSON value: {value}")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def _direct_dependencies(repo_root: Path) -> list[tuple[str, str]]:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return []
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseArtifactVerificationError(
            f"cannot read direct dependencies from {pyproject}: {exc}"
        ) from exc
    declarations = (payload.get("project") or {}).get("dependencies") or []
    rows: list[tuple[str, str]] = []
    for declaration in declarations:
        match = DEPENDENCY_NAME_RE.match(str(declaration))
        if not match:
            raise ReleaseArtifactVerificationError(
                f"cannot parse direct dependency declaration: {declaration!r}"
            )
        rows.append((match.group(1), str(declaration)))
    return rows


def capture_runtime_versions(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    dependencies: dict[str, dict[str, str | None]] = {}
    declarations = _direct_dependencies(Path(repo_root))
    if not any(name.lower().replace("_", "-") == "scikit-learn" for name, _ in declarations):
        declarations.append(("scikit-learn", "scikit-learn (runtime-required)"))
    for name, declaration in declarations:
        canonical_name = name.lower().replace("_", "-")
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = None
        dependencies[canonical_name] = {"version": version, "declared": declaration}
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "direct_dependencies": dict(sorted(dependencies.items())),
    }


def validate_release_id(release_id: str) -> str:
    release_id = str(release_id)
    if release_id in {".", ".."} or not RELEASE_ID_RE.fullmatch(release_id):
        raise ReleaseArtifactVerificationError(
            "release_id must start with an alphanumeric character and contain only "
            "letters, digits, dot, underscore, or hyphen (maximum 128 characters)"
        )
    return release_id


def safe_relative_artifact_path(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    path = Path(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseArtifactVerificationError(
            f"artifact path must be a normalized relative path: {value!r}"
        )
    return path.as_posix()


def validate_code_runtime_alignment(code: Mapping[str, Any], identity: Mapping[str, Any]) -> None:
    code_commit = str(code.get("git_commit") or "")
    runtime_commit = str(identity.get("git_commit") or "")
    if runtime_commit and runtime_commit != "unknown" and not code_commit.startswith(runtime_commit):
        raise ReleaseArtifactVerificationError(
            "code and runtime identity commits disagree: "
            f"code={code_commit!r}, runtime={runtime_commit!r}"
        )


def load_release_manifest(release_dir: str | Path) -> dict[str, Any]:
    path = Path(release_dir) / RELEASE_MANIFEST_NAME
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label="release manifest")
    except FileNotFoundError as exc:
        raise ReleaseArtifactVerificationError(f"release manifest is missing: {path}") from exc
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseArtifactVerificationError(
            f"release manifest is unreadable: {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ReleaseArtifactVerificationError(f"release manifest must be a JSON object: {path}")
    return payload


def _validate_runtime_versions(expected: Mapping[str, Any]) -> None:
    if not expected.get("python") or not expected.get("implementation"):
        raise ReleaseArtifactVerificationError("runtime Python version inventory is missing")
    dependencies = expected.get("direct_dependencies")
    if not isinstance(dependencies, Mapping) or "scikit-learn" not in dependencies:
        raise ReleaseArtifactVerificationError(
            "runtime direct dependency inventory is missing scikit-learn"
        )
    for name, row in dependencies.items():
        if not isinstance(row, Mapping) or not row.get("version") or not row.get("declared"):
            raise ReleaseArtifactVerificationError(
                f"runtime dependency inventory is incomplete for {name}"
            )


def _verify_runtime_versions(expected: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    _validate_runtime_versions(expected)
    _validate_runtime_versions(current)
    for field in ("python", "implementation"):
        if not expected.get(field) or expected.get(field) != current.get(field):
            raise ReleaseArtifactVerificationError(
                f"runtime version mismatch for {field}: expected {expected.get(field)!r}, "
                f"found {current.get(field)!r}"
            )
    expected_dependencies = expected["direct_dependencies"]
    current_dependencies = current["direct_dependencies"]
    for name, row in expected_dependencies.items():
        expected_version = row.get("version") if isinstance(row, Mapping) else None
        current_row = current_dependencies.get(name)
        current_version = current_row.get("version") if isinstance(current_row, Mapping) else None
        if expected_version is None or current_version != expected_version:
            raise ReleaseArtifactVerificationError(
                f"runtime dependency mismatch for {name}: expected {expected_version!r}, "
                f"found {current_version!r}"
            )


def _verify_payload_hash(payload: Mapping[str, Any], *, label: str) -> None:
    expected = payload.get("payload_sha256")
    actual = canonical_payload_sha256(payload, omit=("payload_sha256",))
    if expected != actual:
        raise ReleaseArtifactVerificationError(f"{label} payload hash is invalid")


def _load_verified_json_sidecar(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label=label)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseArtifactVerificationError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseArtifactVerificationError(f"{label} must be a JSON object: {path}")
    return payload


def _verify_semantic_component_metadata(sidecars: Mapping[str, Mapping[str, Any]]) -> None:
    feature = sidecars["pooled_feature_schema"]
    imputer = sidecars["pooled_imputer_metadata"]
    calibrator = sidecars["pooled_calibrator_metadata"]
    corpus = sidecars["training_evaluation_corpus"]
    feature_models = feature.get("models")
    imputer_models = imputer.get("models")
    temperatures = calibrator.get("temperature_by_hour")
    if not all(isinstance(value, Mapping) for value in (feature_models, imputer_models, temperatures)):
        raise ReleaseArtifactVerificationError(
            "semantic component sidecars omit hourly metadata"
        )
    hours = set(feature_models)
    if not hours or set(imputer_models) != hours or set(temperatures) != hours:
        raise ReleaseArtifactVerificationError(
            "feature, imputer, and calibrator hour contracts disagree"
        )
    all_feature_names: set[str] = set()
    for hour in sorted(hours):
        feature_row = feature_models[hour]
        imputer_row = imputer_models[hour]
        names = [str(value) for value in feature_row.get("feature_names") or []]
        names_sha = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
        if (
            not names
            or feature_row.get("feature_count") != len(names)
            or feature_row.get("feature_names_sha256") != names_sha
        ):
            raise ReleaseArtifactVerificationError(
                f"feature sidecar metadata is invalid for hour {hour}"
            )
        component_sha = canonical_payload_sha256(
            imputer_row,
            omit=("component_sha256",),
        )
        if imputer_row.get("component_sha256") != component_sha:
            raise ReleaseArtifactVerificationError(
                f"imputer component hash is invalid for hour {hour}"
            )
        statistics = imputer_row.get("statistics")
        if not isinstance(statistics, list) or len(statistics) != len(names):
            raise ReleaseArtifactVerificationError(
                f"imputer statistics do not match feature order for hour {hour}"
            )
        all_feature_names.update(names)
    lineage = corpus.get("corpus_lineage")
    model_inputs = lineage.get("model_input_fields") if isinstance(lineage, Mapping) else None
    if sorted({str(value) for value in model_inputs or []}) != sorted(all_feature_names):
        raise ReleaseArtifactVerificationError(
            "training corpus model inputs do not match the frozen feature schema"
        )


def _verify_base_model_graph_metadata(
    *,
    graph: Mapping[str, Any],
    route: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
    required_role_kinds: Mapping[str, str],
) -> None:
    if graph.get("schema_version") != BASE_MODEL_SERVING_GRAPH_SCHEMA_VERSION:
        raise ReleaseArtifactVerificationError("base model serving graph schema is unsupported")
    markets = graph.get("markets")
    route_markets = route.get("markets")
    if not isinstance(markets, Mapping) or not markets:
        raise ReleaseArtifactVerificationError("base model serving graph contains no markets")
    if not isinstance(route_markets, Mapping) or set(route_markets) != set(markets):
        raise ReleaseArtifactVerificationError(
            "base model serving graph markets do not exactly match release routes"
        )
    graph_dynamic_roles: set[str] = set()
    for market_id, market in sorted(markets.items()):
        components = market.get("components") if isinstance(market, Mapping) else None
        if not isinstance(components, Mapping):
            raise ReleaseArtifactVerificationError(
                f"base model serving graph components are missing for {market_id!r}"
            )
        if set(components) != set(BASE_MODEL_MARKET_COMPONENT_KINDS):
            raise ReleaseArtifactVerificationError(
                f"base model serving graph component inventory is incomplete for {market_id!r}"
            )
        component_roles = set()
        for component_name, component in sorted(components.items()):
            if not isinstance(component, Mapping):
                raise ReleaseArtifactVerificationError(
                    f"base model component is invalid: {market_id}.{component_name}"
                )
            role = str(component.get("role") or "")
            expected_kind = BASE_MODEL_MARKET_COMPONENT_KINDS[component_name]
            if component.get("kind") != expected_kind:
                raise ReleaseArtifactVerificationError(
                    f"base model component kind is invalid: {market_id}.{component_name}"
                )
            component_roles.add(role)
            graph_dynamic_roles.add(role)
            artifact = artifacts.get(role)
            if not isinstance(artifact, Mapping):
                raise ReleaseArtifactVerificationError(
                    f"base model component role is undeclared: {role!r}"
                )
            for field in ("path", "kind", "sha256"):
                if component.get(field) != artifact.get(field):
                    raise ReleaseArtifactVerificationError(
                        f"base model component {role!r} disagrees on {field}"
                    )
        market_route = route_markets[market_id]
        if (
            not isinstance(market_route, Mapping)
            or market_route.get("base_model_graph_role") != "base_model_serving_graph"
            or market_route.get("base_model_market_id") != market_id
            or set(market_route.get("base_model_component_roles") or []) != component_roles
        ):
            raise ReleaseArtifactVerificationError(
                f"base model route binding is invalid for market {market_id!r}"
            )
        if market.get("global_path_fallback_allowed") is not False:
            raise ReleaseArtifactVerificationError(
                f"base model graph permits global fallback for market {market_id!r}"
            )
        if market.get("calibration_fallback_allowed") is not False:
            raise ReleaseArtifactVerificationError(
                f"base model graph permits calibration fallback for market {market_id!r}"
            )
        if market.get("model_fallback_order") != [
            "bound_feature_hgb",
            "bound_feature_lr_coefficients",
            "code_constant_empirical",
        ]:
            raise ReleaseArtifactVerificationError(
                f"base model fallback order is invalid for market {market_id!r}"
            )
    shared = graph.get("shared_components")
    afternoon = shared.get("afternoon_residual_centering") if isinstance(shared, Mapping) else None
    if not isinstance(afternoon, Mapping):
        raise ReleaseArtifactVerificationError("base model shared afternoon calibration is missing")
    afternoon_role = str(afternoon.get("role") or "")
    graph_dynamic_roles.add(afternoon_role)
    afternoon_artifact = artifacts.get(afternoon_role)
    if not isinstance(afternoon_artifact, Mapping):
        raise ReleaseArtifactVerificationError("base model shared afternoon role is undeclared")
    for field in ("path", "kind", "sha256"):
        if afternoon.get(field) != afternoon_artifact.get(field):
            raise ReleaseArtifactVerificationError(
                f"base model shared afternoon component disagrees on {field}"
            )
    family = shared.get("family_secondary_artifacts") if isinstance(shared, Mapping) else None
    family_role = BASE_MODEL_SHARED_COMPONENT_ROLES["family_secondary_artifacts"]
    family_artifact = artifacts.get(family_role)
    if (
        not isinstance(family, Mapping)
        or family.get("role") != family_role
        or family.get("kind") != "calibration"
        or not isinstance(family_artifact, Mapping)
        or family_artifact.get("kind") != "calibration"
        or any(
            family.get(field) != family_artifact.get(field)
            for field in ("path", "kind", "sha256")
        )
    ):
        raise ReleaseArtifactVerificationError(
            "base model shared family-secondary calibration binding is invalid"
        )
    dynamic_roles = (
        set(required_role_kinds)
        - set(SEMANTIC_SERVING_ROLE_KINDS)
        - set(PRODUCTION_POINT_IN_TIME_ROLE_KINDS)
    )
    if dynamic_roles != graph_dynamic_roles:
        raise ReleaseArtifactVerificationError(
            "base model dynamic role inventory does not match its serving graph"
        )
    if graph.get("global_path_fallback_allowed") is not False:
        raise ReleaseArtifactVerificationError("base model serving graph permits global fallback")
    if graph.get("mixed_bound_unbound_components_allowed") is not False:
        raise ReleaseArtifactVerificationError(
            "base model serving graph permits mixed bound/unbound components"
        )
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
        raise ReleaseArtifactVerificationError(
            "base model code-constant contract is incomplete"
        )


def _verify_semantic_contract_after_inventory(
    release_dir: Path,
    inventory: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Verify internal semantic hashes only after the full file set is trusted."""

    by_role = {
        str(row.get("role")): row
        for row in inventory
        if row.get("declared") and row.get("role")
    }
    contract_row = by_role.get("semantic_serving_contract")
    if contract_row is None:
        return None
    if contract_row.get("kind") != "contract":
        raise ReleaseArtifactVerificationError(
            "semantic_serving_contract role must have contract artifact kind"
        )
    contract = _load_verified_json_sidecar(
        release_dir / str(contract_row["path"]),
        label="semantic serving contract",
    )
    _verify_payload_hash(contract, label="semantic serving contract")
    if contract.get("schema_version") != SEMANTIC_CONTRACT_SCHEMA_VERSION:
        raise ReleaseArtifactVerificationError("semantic serving contract schema is unsupported")
    if contract.get("status") != "PASS" or contract.get("leakage_audit_status") != "PASS":
        raise ReleaseArtifactVerificationError("semantic serving contract is not exact PASS")
    candidate_mode = str(contract.get("candidate_mode") or "")
    if candidate_mode not in CANDIDATE_MODES:
        raise ReleaseArtifactVerificationError(
            "semantic serving contract candidate mode is invalid"
        )
    production_capable = contract.get("production_capable")
    if production_capable is not (candidate_mode == PRODUCTION_CANDIDATE_MODE):
        raise ReleaseArtifactVerificationError(
            "semantic serving contract production capability is invalid"
        )
    required_role_kinds = contract.get("required_role_kinds")
    if not isinstance(required_role_kinds, Mapping) or any(
        required_role_kinds.get(role) != kind
        for role, kind in SEMANTIC_SERVING_ROLE_KINDS.items()
    ):
        raise ReleaseArtifactVerificationError("semantic serving contract fixed role map is invalid")
    point_in_time_roles = set(required_role_kinds) & set(PRODUCTION_POINT_IN_TIME_ROLE_KINDS)
    if candidate_mode == PRODUCTION_CANDIDATE_MODE:
        if any(
            required_role_kinds.get(role) != kind
            for role, kind in PRODUCTION_POINT_IN_TIME_ROLE_KINDS.items()
        ):
            raise ReleaseArtifactVerificationError(
                "production release point-in-time role map is incomplete"
            )
    elif point_in_time_roles:
        raise ReleaseArtifactVerificationError(
            "research-only release declares production point-in-time roles"
        )
    missing_roles = sorted(set(required_role_kinds) - set(by_role))
    if missing_roles:
        raise ReleaseArtifactVerificationError(
            f"semantic serving contract is missing declared roles: {missing_roles}"
        )
    wrong_kinds = sorted(
        role
        for role, kind in required_role_kinds.items()
        if by_role[role].get("kind") != kind
    )
    if wrong_kinds:
        raise ReleaseArtifactVerificationError(
            f"semantic serving contract roles have incorrect kinds: {wrong_kinds}"
        )
    artifacts = contract.get("artifacts")
    expected_component_roles = set(required_role_kinds) - {"semantic_serving_contract"}
    if not isinstance(artifacts, Mapping) or set(artifacts) != expected_component_roles:
        raise ReleaseArtifactVerificationError(
            "semantic serving contract component role inventory is incomplete"
        )
    for role, component in artifacts.items():
        if not isinstance(component, Mapping):
            raise ReleaseArtifactVerificationError(
                f"semantic serving contract component is invalid: {role}"
            )
        inventory_row = by_role[role]
        for field in ("path", "kind", "sha256", "bytes"):
            if component.get(field) != inventory_row.get(field):
                raise ReleaseArtifactVerificationError(
                    f"semantic serving contract component {role!r} disagrees on {field}"
                )
    bundle_sha = str(by_role["pooled_band_model"].get("sha256") or "")
    if contract.get("bundle_sha256") != bundle_sha:
        raise ReleaseArtifactVerificationError(
            "semantic serving contract bundle hash disagrees with release inventory"
        )
    internally_hashed_roles = {
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
    bundle_bound_roles = {
        "pooled_feature_schema",
        "pooled_imputer_metadata",
        "pooled_calibrator_metadata",
        "pooled_postprocessor_metadata",
        "training_evaluation_corpus",
    }
    sidecars: dict[str, dict[str, Any]] = {}
    for role in sorted(internally_hashed_roles):
        row = by_role[role]
        payload = _load_verified_json_sidecar(release_dir / str(row["path"]), label=role)
        _verify_payload_hash(payload, label=role)
        if role in bundle_bound_roles and payload.get("bundle_sha256") != bundle_sha:
            raise ReleaseArtifactVerificationError(
                f"semantic sidecar {role!r} is not bound to the verified model bundle"
            )
        sidecars[role] = payload
    _verify_semantic_component_metadata(sidecars)
    _verify_base_model_graph_metadata(
        graph=sidecars["base_model_serving_graph"],
        route=sidecars["market_route_table"],
        artifacts=artifacts,
        required_role_kinds=required_role_kinds,
    )
    audit = sidecars["candidate_input_leakage_audit"]
    if audit.get("status") != "PASS" or audit.get("rejection_count") != 0:
        raise ReleaseArtifactVerificationError(
            "candidate input leakage audit is not exact PASS"
        )
    expected_audit_roles = expected_component_roles - {
        "candidate_input_leakage_audit",
    }
    audit_hashes = audit.get("input_hashes")
    if not isinstance(audit_hashes, list):
        raise ReleaseArtifactVerificationError("candidate input leakage audit hashes are missing")
    audit_by_role = {
        str(row.get("role")): row
        for row in audit_hashes
        if isinstance(row, Mapping) and row.get("role")
    }
    if set(audit_by_role) != expected_audit_roles:
        raise ReleaseArtifactVerificationError(
            "candidate input leakage audit role hashes are incomplete"
        )
    for role, row in audit_by_role.items():
        inventory_row = by_role[role]
        if (
            row.get("path") != inventory_row.get("path")
            or row.get("sha256") != inventory_row.get("sha256")
            or row.get("bytes") != inventory_row.get("bytes")
        ):
            raise ReleaseArtifactVerificationError(
                f"candidate input leakage audit hash disagrees for role {role!r}"
            )
    corpus_lineage = sidecars["training_evaluation_corpus"].get("corpus_lineage")
    if not isinstance(corpus_lineage, Mapping):
        raise ReleaseArtifactVerificationError("training/evaluation corpus lineage is missing")
    for partition in ("selection_training", "evaluation", "final_refit"):
        row = corpus_lineage.get(partition)
        if (
            not isinstance(row, Mapping)
            or not SHA256_RE.fullmatch(str(row.get("sha256") or ""))
            or not row.get("row_count")
            or not row.get("target_date_min")
            or not row.get("target_date_max")
        ):
            raise ReleaseArtifactVerificationError(
                f"training/evaluation corpus partition is incomplete: {partition}"
            )
    qualification: dict[str, Any] | None = None
    if candidate_mode == PRODUCTION_CANDIDATE_MODE:
        try:
            qualification = verify_production_point_in_time_artifacts(
                corpus_path=release_dir / str(by_role["point_in_time_corpus"]["path"]),
                materialization_manifest_path=(
                    release_dir
                    / str(by_role["point_in_time_materialization_manifest"]["path"])
                ),
                validation_plan_path=(
                    release_dir / str(by_role["point_in_time_validation_plan"]["path"])
                ),
                streaming_evaluation_path=(
                    release_dir
                    / str(by_role["point_in_time_streaming_evaluation"]["path"])
                ),
                expected_candidate_id=str(contract.get("candidate_id") or ""),
                expected_release_id=str(contract.get("candidate_id") or ""),
                max_age_days=None,
                inspect_corpus_parquet=False,
            )
        except (PointInTimeContractViolation, OSError, ValueError) as exc:
            raise ReleaseArtifactVerificationError(
                f"production point-in-time qualification failed: {exc}"
            ) from exc
    return {
        "status": "PASS",
        "contract_role": "semantic_serving_contract",
        "contract_sha256": contract_row["sha256"],
        "role_count": len(required_role_kinds),
        "leakage_audit_sha256": by_role["candidate_input_leakage_audit"]["sha256"],
        "candidate_mode": candidate_mode,
        "production_capable": production_capable,
        "point_in_time_qualification": qualification,
    }


def verify_release(
    release_dir: str | Path,
    *,
    repo_root: str | Path = REPO_ROOT,
    expected_manifest_sha256: str | None = None,
    check_runtime: bool = True,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify manifest structure, every release file/hash, and runtime."""

    release_input = Path(release_dir)
    if release_input.is_symlink():
        raise ReleaseArtifactVerificationError(
            f"release directory must not be a symlink: {release_input}"
        )
    release_dir = release_input.resolve()
    if not release_dir.exists() or not release_dir.is_dir():
        raise ReleaseArtifactVerificationError(f"release directory is missing or invalid: {release_dir}")
    manifest = load_release_manifest(release_dir)
    required_fields = {
        "schema_version",
        "release_id",
        "manifest_sha256",
        "code",
        "runtime_versions",
        "runtime_identity",
        "route",
        "route_sha256",
        "expected_live_runtimes",
        "artifacts",
        "config_hashes",
        "rollback_target",
    }
    missing_fields = sorted(required_fields - set(manifest))
    if missing_fields:
        raise ReleaseArtifactVerificationError(
            f"release manifest is missing required fields: {missing_fields}"
        )
    if manifest["schema_version"] != RELEASE_MANIFEST_SCHEMA_VERSION:
        raise ReleaseArtifactVerificationError(
            f"unsupported release manifest schema: {manifest['schema_version']!r}"
        )
    release_id = validate_release_id(str(manifest["release_id"]))
    if release_dir.name != release_id:
        raise ReleaseArtifactVerificationError(
            f"release directory/name mismatch: directory={release_dir.name!r}, manifest={release_id!r}"
        )
    manifest_sha = manifest_content_sha256(manifest)
    if manifest.get("manifest_sha256") != manifest_sha:
        raise ReleaseArtifactVerificationError("release manifest content hash is invalid")
    if expected_manifest_sha256 is not None and expected_manifest_sha256 != manifest_sha:
        raise ReleaseArtifactVerificationError(
            "release manifest does not match the trusted pointer hash"
        )

    artifacts = manifest.get("artifacts")
    inventory = artifacts.get("inventory") if isinstance(artifacts, Mapping) else None
    if not isinstance(inventory, list) or not inventory:
        raise ReleaseArtifactVerificationError("release artifact inventory is missing or empty")
    expected_paths: set[str] = set()
    kind_counts: Counter[str] = Counter()
    declared_kind_counts: Counter[str] = Counter()
    declared_roles: set[str] = set()
    total_bytes = 0
    config_hashes: dict[str, str] = {}
    for row in inventory:
        if not isinstance(row, Mapping):
            raise ReleaseArtifactVerificationError(
                "release artifact inventory contains a non-object row"
            )
        rel = safe_relative_artifact_path(str(row.get("path") or ""))
        if rel in expected_paths:
            raise ReleaseArtifactVerificationError(
                f"release artifact inventory contains duplicate path: {rel}"
            )
        expected_paths.add(rel)
        kind = str(row.get("kind") or "")
        if kind not in ARTIFACT_KINDS:
            raise ReleaseArtifactVerificationError(
                f"release artifact has invalid kind: {rel}: {kind!r}"
            )
        expected_hash = str(row.get("sha256") or "")
        if not SHA256_RE.fullmatch(expected_hash):
            raise ReleaseArtifactVerificationError(f"release artifact has invalid SHA-256: {rel}")
        expected_bytes = row.get("bytes")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise ReleaseArtifactVerificationError(
                f"release artifact has invalid byte count: {rel}"
            )
        path = release_dir / rel
        if not path.exists() or not path.is_file() or path.is_symlink():
            raise ReleaseArtifactVerificationError(
                f"release artifact is missing or invalid: {rel}"
            )
        if path.stat().st_size != expected_bytes:
            raise ReleaseArtifactVerificationError(
                f"release artifact byte count mismatch: {rel}"
            )
        if sha256_file(path) != expected_hash:
            raise ReleaseArtifactVerificationError(f"release artifact hash mismatch: {rel}")
        kind_counts[kind] += 1
        total_bytes += expected_bytes
        if row.get("declared"):
            role = str(row.get("role") or "")
            if not role:
                raise ReleaseArtifactVerificationError(
                    f"declared artifact is missing its role: {rel}"
                )
            if role in declared_roles:
                raise ReleaseArtifactVerificationError(
                    f"declared artifact role appears more than once: {role}"
                )
            declared_roles.add(role)
            declared_kind_counts[kind] += 1
            if kind == "config":
                config_hashes[role] = expected_hash

    actual_paths = {
        path.relative_to(release_dir).as_posix()
        for path in release_dir.rglob("*")
        if path.is_file() and path != release_dir / RELEASE_MANIFEST_NAME
    }
    if any(path.is_symlink() for path in release_dir.rglob("*")):
        raise ReleaseArtifactVerificationError("release contains a symlink")
    if actual_paths != expected_paths:
        raise ReleaseArtifactVerificationError(
            "release file set does not match manifest; "
            f"missing={sorted(expected_paths - actual_paths)}, "
            f"extra={sorted(actual_paths - expected_paths)}"
        )
    if artifacts.get("file_count") != len(inventory) or artifacts.get("total_bytes") != total_bytes:
        raise ReleaseArtifactVerificationError("release artifact inventory totals are invalid")
    if artifacts.get("kind_counts") != dict(sorted(kind_counts.items())):
        raise ReleaseArtifactVerificationError("release artifact kind counts are invalid")
    if manifest.get("config_hashes") != dict(sorted(config_hashes.items())):
        raise ReleaseArtifactVerificationError("release config hash index is invalid")
    if not {"model", "config"}.issubset(declared_kind_counts):
        raise ReleaseArtifactVerificationError(
            "release inventory must contain declared model and config artifacts"
        )
    code = manifest.get("code")
    if not isinstance(code, Mapping) or not isinstance(code.get("git_dirty"), bool):
        raise ReleaseArtifactVerificationError(
            "release code dirty-state attestation is missing"
        )
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(code.get("git_commit") or "")):
        raise ReleaseArtifactVerificationError("release code commit attestation is invalid")
    if not str(code.get("git_branch") or "").strip():
        raise ReleaseArtifactVerificationError("release code branch attestation is missing")
    dirty_fingerprint = code.get("dirty_fingerprint")
    if code["git_dirty"] and not SHA256_RE.fullmatch(str(dirty_fingerprint or "")):
        raise ReleaseArtifactVerificationError(
            "dirty release code is missing a valid dirty fingerprint"
        )
    if not code["git_dirty"] and dirty_fingerprint is not None:
        raise ReleaseArtifactVerificationError(
            "clean release code must not contain a dirty fingerprint"
        )
    identity = manifest.get("runtime_identity")
    if not isinstance(identity, Mapping) or not identity.get("source_fingerprint"):
        raise ReleaseArtifactVerificationError("release runtime identity is missing")
    if not isinstance(manifest.get("route"), Mapping) or not manifest.get("route"):
        raise ReleaseArtifactVerificationError("release route metadata is missing")
    if manifest.get("route_sha256") != canonical_payload_sha256(manifest["route"]):
        raise ReleaseArtifactVerificationError("release route metadata hash is invalid")
    runtimes = manifest.get("expected_live_runtimes")
    if not isinstance(runtimes, list) or not runtimes or any(
        not isinstance(value, str) or not value.strip() for value in runtimes
    ):
        raise ReleaseArtifactVerificationError(
            "release expected runtime inventory is invalid"
        )
    rollback_target = manifest.get("rollback_target")
    if rollback_target is not None:
        validate_release_id(str(rollback_target))
    _validate_runtime_versions(manifest["runtime_versions"])
    validate_code_runtime_alignment(code, identity)
    semantic_contract = _verify_semantic_contract_after_inventory(release_dir, inventory)

    if check_runtime:
        current_versions = dict(
            current_runtime_versions
            if current_runtime_versions is not None
            else capture_runtime_versions(repo_root)
        )
        _verify_runtime_versions(manifest["runtime_versions"], current_versions)
        current_identity = dict(
            current_runtime_identity
            if current_runtime_identity is not None
            else get_runtime_identity(repo_root)
        )
        if current_identity.get("source_fingerprint") != identity.get("source_fingerprint"):
            raise ReleaseArtifactVerificationError(
                "runtime source identity is incompatible with release: "
                f"expected {identity.get('source_fingerprint')!r}, "
                f"found {current_identity.get('source_fingerprint')!r}"
            )
        expected_commit = str(code.get("git_commit") or "")
        current_commit = str(current_identity.get("git_commit") or "")
        if current_commit and current_commit != "unknown" and not expected_commit.startswith(current_commit):
            raise ReleaseArtifactVerificationError(
                f"runtime git commit is incompatible with release: "
                f"expected {expected_commit!r}, found {current_commit!r}"
            )
    return {
        "status": "PASS",
        "release_id": release_id,
        "release_dir": str(release_dir),
        "manifest_path": str(release_dir / RELEASE_MANIFEST_NAME),
        "manifest_sha256": manifest_sha,
        "file_count": len(inventory),
        "total_bytes": total_bytes,
        "runtime_checked": bool(check_runtime),
        "semantic_contract_verified": semantic_contract is not None,
        "semantic_contract": semantic_contract,
        "manifest": manifest,
    }


def _parse_utc(value: Any, *, field: str) -> None:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ReleaseArtifactVerificationError(
            f"{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ReleaseArtifactVerificationError(f"{field} must include a timezone")


def load_active_release_pointer(
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
) -> dict[str, Any]:
    path = Path(pointer_path)
    if path.is_symlink():
        raise ReleaseArtifactVerificationError(
            f"active release pointer must not be a symlink: {path}"
        )
    try:
        pointer = strict_json_loads(
            path.read_text(encoding="utf-8"),
            label="active release pointer",
        )
    except FileNotFoundError as exc:
        raise ReleaseArtifactVerificationError(
            f"active release pointer is missing: {path}"
        ) from exc
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseArtifactVerificationError(
            f"active release pointer is unreadable: {path}: {exc}"
        ) from exc
    if not isinstance(pointer, dict):
        raise ReleaseArtifactVerificationError("active release pointer must be a JSON object")
    required = {
        "schema_version",
        "sequence",
        "action",
        "changed_at_utc",
        "active_release_id",
        "active_manifest_sha256",
        "previous_release_id",
        "previous_manifest_sha256",
        "pointer_sha256",
    }
    missing = sorted(required - set(pointer))
    if missing:
        raise ReleaseArtifactVerificationError(
            f"active release pointer is missing required fields: {missing}"
        )
    if pointer.get("schema_version") != ACTIVE_POINTER_SCHEMA_VERSION:
        raise ReleaseArtifactVerificationError(
            f"unsupported active release pointer schema: {pointer.get('schema_version')!r}"
        )
    if not isinstance(pointer.get("sequence"), int) or pointer["sequence"] < 1:
        raise ReleaseArtifactVerificationError("active release pointer sequence is invalid")
    if pointer.get("action") not in {"PROMOTE", "ROLLBACK"}:
        raise ReleaseArtifactVerificationError("active release pointer action is invalid")
    _parse_utc(pointer.get("changed_at_utc"), field="changed_at_utc")
    active_id = validate_release_id(str(pointer.get("active_release_id") or ""))
    if not SHA256_RE.fullmatch(str(pointer.get("active_manifest_sha256") or "")):
        raise ReleaseArtifactVerificationError(
            "active release pointer manifest hash is invalid"
        )
    previous = pointer.get("previous_release_id")
    if previous is not None:
        validate_release_id(str(previous))
        if previous == active_id:
            raise ReleaseArtifactVerificationError(
                "active and previous releases must be different"
            )
        if not SHA256_RE.fullmatch(str(pointer.get("previous_manifest_sha256") or "")):
            raise ReleaseArtifactVerificationError(
                "active release pointer previous manifest hash is invalid"
            )
    elif pointer.get("previous_manifest_sha256") is not None:
        raise ReleaseArtifactVerificationError(
            "active release pointer has a previous hash without a previous release"
        )
    if pointer.get("pointer_sha256") != pointer_content_sha256(pointer):
        raise ReleaseArtifactVerificationError(
            "active release pointer content hash is invalid"
        )
    return pointer


def resolve_verified_active_release(
    *,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    repo_root: str | Path = REPO_ROOT,
    check_runtime: bool = True,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
    served_artifact_paths: Mapping[str, str | Path] | None = None,
    served_route: Mapping[str, Any] | None = None,
    require_served_bindings: bool = True,
) -> dict[str, Any]:
    """Resolve identity only after immutable and actual served bindings pass.

    The default fails closed unless the caller supplies every serving-semantic
    artifact role and the actual route metadata used by its runtime. This
    prevents a valid pointer from laundering identity onto legacy global model
    paths. Read-only inspection tools may explicitly set
    ``require_served_bindings=False``; serving/capture code must not.
    """

    releases_root = Path(releases_root).resolve()
    pointer_path = Path(pointer_path)
    if pointer_path.resolve().parent != releases_root:
        raise ReleaseArtifactVerificationError(
            "active release pointer must be directly inside the releases root"
        )
    pointer = load_active_release_pointer(pointer_path)
    verified = verify_release(
        releases_root / pointer["active_release_id"],
        repo_root=repo_root,
        expected_manifest_sha256=pointer["active_manifest_sha256"],
        check_runtime=check_runtime,
        current_runtime_versions=current_runtime_versions,
        current_runtime_identity=current_runtime_identity,
    )
    manifest = verified["manifest"]
    required_roles = {
        str(row["role"]): row
        for row in manifest["artifacts"]["inventory"]
        if row.get("declared") and row.get("kind") in SERVING_ARTIFACT_KINDS
    }
    binding_rows = []
    if require_served_bindings:
        observed = dict(served_artifact_paths or {})
        missing_roles = sorted(set(required_roles) - set(observed))
        if missing_roles:
            raise ReleaseArtifactVerificationError(
                f"actual served artifact bindings are missing manifest roles: {missing_roles}"
            )
        if served_route is None:
            raise ReleaseArtifactVerificationError(
                "actual served route metadata is required for release identity"
            )
        if canonical_payload_sha256(served_route) != manifest["route_sha256"]:
            raise ReleaseArtifactVerificationError(
                "actual served route metadata does not match the release manifest"
            )
        for role, row in sorted(required_roles.items()):
            actual_path = Path(observed[role]).resolve()
            if not actual_path.exists() or not actual_path.is_file() or actual_path.is_symlink():
                raise ReleaseArtifactVerificationError(
                    f"actual served artifact for role {role!r} is missing or invalid: {actual_path}"
                )
            actual_sha = sha256_file(actual_path)
            if actual_sha != row["sha256"]:
                raise ReleaseArtifactVerificationError(
                    f"actual served artifact hash mismatch for role {role!r}"
                )
            binding_rows.append(
                {
                    "role": role,
                    "kind": row["kind"],
                    "path": str(actual_path),
                    "sha256": actual_sha,
                }
            )
    binding_sha = (
        canonical_payload_sha256(
            {
                "artifacts": binding_rows,
                "route_sha256": manifest["route_sha256"],
            }
        )
        if require_served_bindings
        else None
    )
    return {
        "status": "PASS",
        "release_id": pointer["active_release_id"],
        "release_dir": verified["release_dir"],
        "manifest_path": verified["manifest_path"],
        "manifest_sha256": verified["manifest_sha256"],
        "pointer_sha256": pointer["pointer_sha256"],
        "sequence": pointer["sequence"],
        "runtime_checked": verified["runtime_checked"],
        "served_bindings_verified": bool(require_served_bindings),
        "served_binding_sha256": binding_sha,
        "served_artifact_roles": sorted(required_roles) if require_served_bindings else [],
    }
