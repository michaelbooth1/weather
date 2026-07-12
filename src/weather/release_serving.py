"""Verified active-release loading for production-capable live prediction.

No model or JSON serving input is deserialized until the pointer, complete
release inventory, semantic contract, role bindings, and frozen route all pass.
The process cache is deliberately sticky: a pointer appearance, disappearance,
or byte change requires an explicit cache clear/process restart.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
    ReleaseArtifactVerificationError,
    load_active_release_pointer,
    resolve_verified_active_release,
    sha256_file,
    strict_json_loads,
    verify_release,
)
from weather.release_contract import (
    BASE_MODEL_MARKET_COMPONENT_KINDS,
    BASE_MODEL_SHARED_COMPONENT_ROLES,
    SERVING_ARTIFACT_KINDS,
)


STATUS_BOUND = "BOUND"
STATUS_SHADOW_BOUND = "SHADOW_BOUND"
STATUS_RESEARCH_UNBOUND = "RESEARCH_UNBOUND"
STATUS_BLOCKED = "BLOCKED"
STATUS_RESTART_REQUIRED = "RESTART_REQUIRED"
VERIFIED_PICKLE_BINDING_MARKER = "verified_release_pickle_binding_v0.1"

# Every historical global-path boundary below is now guarded by the verified
# bundle in TorontoHighTempModel/FeatureModelMixin.  The inventory remains
# explicit so a newly added serving loader cannot silently escape the contract.
RELEASE_BOUND_BASE_MODEL_LOADER_BOUNDARIES = (
    "weather.model.model_features:FeatureModelMixin._read_feature_model_hgb",
    "weather.model.model_features:FeatureModelMixin._read_feature_model_coefs",
    "weather.model.model_features:FeatureModelMixin._read_late_day_model_coefs",
    "weather.model.toronto_model:TorontoHighTempModel.load_calibrated_weights",
    "weather.model.toronto_model:TorontoHighTempModel.load_probability_calibration",
    "weather.model.toronto_model:TorontoHighTempModel.load_forecast_error_model",
    "weather.model.toronto_model:TorontoHighTempModel.load_afternoon_residual_centering",
    "weather.model.toronto_model:TorontoHighTempModel.load_settlement_lag_model",
    "weather.model.toronto_model:TorontoHighTempModel.load_family_secondary_artifacts",
)


class ReleaseServingBindingError(ReleaseArtifactVerificationError):
    """An active release cannot be safely loaded for serving."""


@dataclass(frozen=True)
class VerifiedServingBundle:
    status: str
    reason: str
    pointer_present: bool
    pointer_file_sha256: str | None = None
    release_id: str = ""
    manifest_sha256: str = ""
    pointer_sha256: str = ""
    sequence: int | None = None
    release_dir: str = ""
    route: Mapping[str, Any] = field(default_factory=dict)
    model_variant_registry: Mapping[str, Any] = field(default_factory=dict)
    model_bundle: Mapping[str, Any] = field(default_factory=dict)
    json_artifacts: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    artifact_paths: Mapping[str, str] = field(default_factory=dict)
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    base_model_graph: Mapping[str, Any] = field(default_factory=dict)
    base_model_artifacts: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    base_model_shared_artifacts: Mapping[str, Any] = field(default_factory=dict)
    base_model_bound: bool = False
    base_model_binding_reason: str = (
        "no verified active-release base-model serving graph is bound"
    )


_PROCESS_BUNDLES: dict[str, VerifiedServingBundle] = {}


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(child) for child in value)
    return value


def _pointer_state(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, None
    if path.is_symlink() or not path.is_file():
        raise ReleaseServingBindingError(f"active release pointer is not a regular file: {path}")
    try:
        return True, sha256_file(path)
    except OSError as exc:
        raise ReleaseServingBindingError(f"active release pointer cannot be hashed: {path}: {exc}") from exc


def _inventory_by_role(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    inventory = ((manifest.get("artifacts") or {}).get("inventory") or [])
    return {
        str(row.get("role")): row
        for row in inventory
        if isinstance(row, Mapping) and row.get("declared") and row.get("role")
    }


def _verify_route_registry_model_binding(
    *,
    route: Mapping[str, Any],
    registry: Mapping[str, Any],
    model_row: Mapping[str, Any],
    release_id: str,
) -> None:
    if route.get("candidate_release_id") != release_id:
        raise ReleaseServingBindingError(
            "frozen route candidate release does not match active release identity"
        )
    variants = registry.get("variants")
    if not isinstance(variants, list):
        raise ReleaseServingBindingError("frozen model variant registry is missing variants")
    by_id = {
        str(row.get("variant_id")): row
        for row in variants
        if isinstance(row, Mapping) and row.get("variant_id")
    }
    markets = route.get("markets")
    if not isinstance(markets, Mapping) or not markets:
        raise ReleaseServingBindingError("frozen route contains no market routes")
    for market_id, market_route in sorted(markets.items()):
        if not isinstance(market_route, Mapping):
            raise ReleaseServingBindingError(f"frozen route is invalid for market {market_id!r}")
        if market_route.get("decision") not in {"promote", "shadow"}:
            continue
        variant_id = str(market_route.get("candidate_variant_id") or "")
        variant = by_id.get(variant_id)
        if not isinstance(variant, Mapping):
            raise ReleaseServingBindingError(
                f"frozen route candidate {variant_id!r} is absent from model variant registry"
            )
        registry_path = str(variant.get("artifact_path") or "").replace("\\", "/")
        if (
            market_route.get("artifact_role") != "pooled_band_model"
            or variant.get("artifact_role") != "pooled_band_model"
            or variant.get("artifact_sha256") != model_row.get("sha256")
            or registry_path != str(model_row.get("path") or "").replace("\\", "/")
        ):
            raise ReleaseServingBindingError(
                f"frozen route/registry/model role mismatch for market {market_id!r}"
            )


def _checked_json(path: Path, *, expected_sha256: str, label: str) -> dict[str, Any]:
    try:
        before = path.stat()
        if sha256_file(path) != expected_sha256:
            raise ReleaseServingBindingError(f"{label} hash changed before deserialization")
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label=label)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseServingBindingError(f"{label} cannot be deserialized: {exc}") from exc
    try:
        after = path.stat()
        stable = (
            before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            and sha256_file(path) == expected_sha256
        )
    except OSError as exc:
        raise ReleaseServingBindingError(f"{label} disappeared during deserialization: {exc}") from exc
    if not isinstance(payload, dict) or not stable:
        raise ReleaseServingBindingError(f"{label} changed during deserialization")
    return payload


def _checked_pickle(path: Path, *, expected_sha256: str, label: str) -> dict[str, Any]:
    try:
        before = path.stat()
        if sha256_file(path) != expected_sha256:
            raise ReleaseServingBindingError(f"{label} hash changed before deserialization")
        with path.open("rb") as handle:
            payload = pickle.load(handle)  # noqa: S301 - immutable, hash-verified release artifact
    except Exception as exc:  # noqa: BLE001 - unsafe format must fail the serving binding
        raise ReleaseServingBindingError(f"{label} cannot be deserialized: {exc}") from exc
    try:
        after = path.stat()
        stable = (
            before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            and sha256_file(path) == expected_sha256
        )
    except OSError as exc:
        raise ReleaseServingBindingError(f"{label} disappeared during deserialization: {exc}") from exc
    if not isinstance(payload, dict) or not stable:
        raise ReleaseServingBindingError(f"{label} changed during deserialization")
    return payload


def _load_verified_base_model_graph(
    *,
    graph: Mapping[str, Any],
    route: Mapping[str, Any],
    roles: Mapping[str, Mapping[str, Any]],
    json_payloads: Mapping[str, Mapping[str, Any]],
    release_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    markets = graph.get("markets")
    route_markets = route.get("markets")
    if (
        not isinstance(markets, Mapping)
        or not isinstance(route_markets, Mapping)
        or set(markets) != set(route_markets)
    ):
        raise ReleaseServingBindingError(
            "base-model graph markets do not exactly match active release routes"
        )
    loaded_markets: dict[str, dict[str, Any]] = {}
    expected_pickle_roles = {"pooled_band_model"}
    for market_id, market in sorted(markets.items()):
        components = market.get("components") if isinstance(market, Mapping) else None
        if not isinstance(components, Mapping) or set(components) != set(
            BASE_MODEL_MARKET_COMPONENT_KINDS
        ):
            raise ReleaseServingBindingError(
                f"base-model graph is incomplete for market {market_id!r}"
            )
        market_route = route_markets[market_id]
        component_roles = {
            str(component.get("role") or "")
            for component in components.values()
            if isinstance(component, Mapping)
        }
        if (
            not isinstance(market_route, Mapping)
            or market_route.get("base_model_graph_role") != "base_model_serving_graph"
            or market_route.get("base_model_market_id") != market_id
            or set(market_route.get("base_model_component_roles") or []) != component_roles
        ):
            raise ReleaseServingBindingError(
                f"active route has no exact base-model binding for market {market_id!r}"
            )
        if (
            market.get("global_path_fallback_allowed") is not False
            or market.get("calibration_fallback_allowed") is not False
        ):
            raise ReleaseServingBindingError(
                f"active base-model graph permits fallback for market {market_id!r}"
            )
        loaded_components: dict[str, Any] = {}
        for component_name, expected_kind in BASE_MODEL_MARKET_COMPONENT_KINDS.items():
            component = components[component_name]
            role = str(component.get("role") or "")
            row = roles.get(role)
            if (
                not isinstance(row, Mapping)
                or row.get("kind") != expected_kind
                or any(component.get(field) != row.get(field) for field in ("path", "kind", "sha256"))
            ):
                raise ReleaseServingBindingError(
                    f"active base-model component binding is invalid: {market_id}.{component_name}"
                )
            path = release_dir / str(row["path"])
            if component_name == "feature_hgb":
                if path.suffix.casefold() != ".pkl":
                    raise ReleaseServingBindingError(
                        f"base HGB role is not a pickle: {role!r}"
                    )
                expected_pickle_roles.add(role)
                payload = MappingProxyType(
                    {
                        "binding": VERIFIED_PICKLE_BINDING_MARKER,
                        "role": role,
                        "path": str(path),
                        "sha256": str(row["sha256"]),
                    }
                )
            else:
                payload = json_payloads.get(role)
                if not isinstance(payload, Mapping):
                    raise ReleaseServingBindingError(
                        f"verified base-model JSON payload is missing: {role!r}"
                    )
            loaded_components[component_name] = payload
        loaded_markets[str(market_id)] = loaded_components

    actual_pickle_roles = {
        role
        for role, row in roles.items()
        if row.get("kind") in SERVING_ARTIFACT_KINDS
        and (release_dir / str(row.get("path") or "")).suffix.casefold() == ".pkl"
    }
    if actual_pickle_roles != expected_pickle_roles:
        raise ReleaseServingBindingError(
            "active release contains an undeclared or omitted serving pickle role"
        )
    shared = graph.get("shared_components")
    if not isinstance(shared, Mapping):
        raise ReleaseServingBindingError("active base-model graph has no shared components")
    loaded_shared: dict[str, Any] = {}
    for component_name, expected_role in BASE_MODEL_SHARED_COMPONENT_ROLES.items():
        component = shared.get(component_name)
        payload = json_payloads.get(expected_role)
        row = roles.get(expected_role)
        if (
            not isinstance(component, Mapping)
            or component.get("role") != expected_role
            or component.get("kind") != "calibration"
            or not isinstance(payload, Mapping)
            or not isinstance(row, Mapping)
            or any(
                component.get(field) != row.get(field)
                for field in ("path", "kind", "sha256")
            )
        ):
            raise ReleaseServingBindingError(
                f"active shared base-model binding is invalid: {component_name}"
            )
        loaded_shared[component_name] = payload
    if (
        graph.get("global_path_fallback_allowed") is not False
        or graph.get("mixed_bound_unbound_components_allowed") is not False
    ):
        raise ReleaseServingBindingError(
            "active base-model graph permits global fallback or mixed bound/unbound components"
        )
    return loaded_markets, loaded_shared


def materialize_verified_base_model_market(
    bundle: VerifiedServingBundle,
    market_id: str,
) -> dict[str, Any]:
    """Deserialize only one market's HGB after the complete graph is verified."""

    if bundle.status != STATUS_BOUND or not bundle.base_model_bound:
        raise ReleaseServingBindingError(
            "cannot materialize a base model without a verified active-release graph"
        )
    route = bundle.route.get("markets", {}).get(market_id)
    graph_market = bundle.base_model_graph.get("markets", {}).get(market_id)
    components = bundle.base_model_artifacts.get(market_id)
    if (
        not isinstance(route, Mapping)
        or route.get("base_model_market_id") != market_id
        or not isinstance(graph_market, Mapping)
        or not isinstance(components, Mapping)
        or set(components) != set(BASE_MODEL_MARKET_COMPONENT_KINDS)
    ):
        raise ReleaseServingBindingError(
            f"verified base-model market binding is incomplete: {market_id!r}"
        )
    descriptor = components["feature_hgb"]
    graph_component = (graph_market.get("components") or {}).get("feature_hgb")
    role = str(graph_component.get("role") or "") if isinstance(graph_component, Mapping) else ""
    if (
        not isinstance(descriptor, Mapping)
        or descriptor.get("binding") != VERIFIED_PICKLE_BINDING_MARKER
        or descriptor.get("role") != role
        or descriptor.get("path") != bundle.artifact_paths.get(role)
        or descriptor.get("sha256") != bundle.artifact_hashes.get(role)
    ):
        raise ReleaseServingBindingError(
            f"verified base HGB binding is invalid for market {market_id!r}"
        )
    materialized = dict(components)
    materialized["feature_hgb"] = _checked_pickle(
        Path(str(descriptor["path"])),
        expected_sha256=str(descriptor["sha256"]),
        label=role,
    )
    return materialized


def load_verified_active_serving_bundle(
    *,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    repo_root: str | Path = REPO_ROOT,
    check_runtime: bool = True,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
) -> VerifiedServingBundle:
    """Load exact manifest roles only after all outer bindings pass."""

    pointer_path = Path(pointer_path).resolve()
    releases_root = Path(releases_root).resolve()
    present, pointer_file_sha = _pointer_state(pointer_path)
    if not present:
        return VerifiedServingBundle(
            status=STATUS_RESEARCH_UNBOUND,
            reason="no active release pointer; diagnostic capture is release-unbound and non-countable",
            pointer_present=False,
        )
    pointer = load_active_release_pointer(pointer_path)
    release_dir = releases_root / str(pointer["active_release_id"])
    verified = verify_release(
        release_dir,
        repo_root=repo_root,
        expected_manifest_sha256=str(pointer["active_manifest_sha256"]),
        check_runtime=check_runtime,
        current_runtime_versions=current_runtime_versions,
        current_runtime_identity=current_runtime_identity,
    )
    if not verified.get("semantic_contract_verified"):
        raise ReleaseServingBindingError(
            "active release has no verified semantic serving contract"
        )
    if not (verified.get("semantic_contract") or {}).get("production_capable"):
        raise ReleaseServingBindingError(
            "active release is research-only and cannot bind a serving runtime"
        )
    manifest = verified["manifest"]
    roles = _inventory_by_role(manifest)
    serving_rows = {
        role: row
        for role, row in roles.items()
        if row.get("kind") in SERVING_ARTIFACT_KINDS
    }
    served_paths = {
        role: release_dir / str(row["path"])
        for role, row in serving_rows.items()
    }
    route_row = roles.get("market_route_table")
    if not route_row or route_row.get("kind") != "route":
        raise ReleaseServingBindingError("active release market route role is missing")
    route = _checked_json(
        release_dir / str(route_row["path"]),
        expected_sha256=str(route_row["sha256"]),
        label="market route table",
    )
    if route != manifest.get("route"):
        raise ReleaseServingBindingError(
            "frozen route artifact does not exactly match release manifest route"
        )
    resolved = resolve_verified_active_release(
        pointer_path=pointer_path,
        releases_root=releases_root,
        repo_root=repo_root,
        check_runtime=check_runtime,
        current_runtime_versions=current_runtime_versions,
        current_runtime_identity=current_runtime_identity,
        served_artifact_paths=served_paths,
        served_route=route,
        require_served_bindings=True,
    )
    # The resolver above re-hashes every serving binding. JSON contracts can
    # now be read and cross-checked before the model pickle is opened.
    model_row = roles.get("pooled_band_model")
    if not model_row or model_row.get("kind") != "model":
        raise ReleaseServingBindingError("active release pooled model role is missing")
    json_payloads: dict[str, Mapping[str, Any]] = {}
    for role, row in sorted(serving_rows.items()):
        if role == "pooled_band_model":
            continue
        path = release_dir / str(row["path"])
        if path.suffix.casefold() == ".pkl":
            continue
        if path.suffix.casefold() != ".json":
            raise ReleaseServingBindingError(
                f"serving role {role!r} is not a supported JSON artifact: {path}"
            )
        json_payloads[role] = _checked_json(
            path,
            expected_sha256=str(row["sha256"]),
            label=role,
        )
    registry = json_payloads.get("model_variant_registry")
    if not isinstance(registry, Mapping):
        raise ReleaseServingBindingError("verified model variant registry is missing")
    _verify_route_registry_model_binding(
        route=route,
        registry=registry,
        model_row=model_row,
        release_id=str(resolved["release_id"]),
    )
    base_model_graph = json_payloads.get("base_model_serving_graph")
    if not isinstance(base_model_graph, Mapping):
        raise ReleaseServingBindingError("verified base-model serving graph is missing")
    base_model_artifacts, base_model_shared_artifacts = _load_verified_base_model_graph(
        graph=base_model_graph,
        route=route,
        roles=roles,
        json_payloads=json_payloads,
        release_dir=release_dir,
    )
    model_bundle = _checked_pickle(
        release_dir / str(model_row["path"]),
        expected_sha256=str(model_row["sha256"]),
        label="pooled band model",
    )
    return VerifiedServingBundle(
        status=STATUS_BOUND,
        reason="all manifest serving roles and frozen route verified before deserialization",
        pointer_present=True,
        pointer_file_sha256=pointer_file_sha,
        release_id=str(resolved["release_id"]),
        manifest_sha256=str(resolved["manifest_sha256"]),
        pointer_sha256=str(resolved["pointer_sha256"]),
        sequence=int(resolved["sequence"]),
        release_dir=str(release_dir),
        route=_deep_freeze(route),
        model_variant_registry=_deep_freeze(registry),
        model_bundle=model_bundle,
        json_artifacts=_deep_freeze(json_payloads),
        artifact_paths=MappingProxyType({role: str(path) for role, path in served_paths.items()}),
        artifact_hashes=MappingProxyType(
            {role: str(row["sha256"]) for role, row in serving_rows.items()}
        ),
        base_model_graph=_deep_freeze(base_model_graph),
        base_model_artifacts=MappingProxyType(
            {
                market_id: MappingProxyType(dict(components))
                for market_id, components in base_model_artifacts.items()
            }
        ),
        base_model_shared_artifacts=MappingProxyType(dict(base_model_shared_artifacts)),
        base_model_bound=True,
        base_model_binding_reason=(
            "complete per-market HGB/LR/calibration graph bound to verified release roles; "
            "routed HGB materializes on demand"
        ),
    )


def load_verified_residual_distribution_v1_shadow_bundle(
    release_dir: str | Path,
    *,
    repo_root: str | Path = REPO_ROOT,
    expected_manifest_sha256: str | None = None,
    check_runtime: bool = True,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
) -> VerifiedServingBundle:
    """Bind one immutable residual-v1 release for forward shadow capture only.

    This path is deliberately independent of the active-release pointer.  Its
    distinct status is accepted by the live prediction tape adapter, but not by
    production model serving or base-model materialization.
    """

    from weather.model.residual_distribution_v1 import PREDICTION_MODE
    from weather.residual_distribution_release import (
        ROLE_PATH_KINDS,
        verify_residual_distribution_v1_release,
    )

    release_root = Path(release_dir).resolve()
    verified = verify_residual_distribution_v1_release(
        release_root,
        repo_root=repo_root,
        expected_manifest_sha256=expected_manifest_sha256,
        check_runtime=check_runtime,
        current_runtime_versions=current_runtime_versions,
        current_runtime_identity=current_runtime_identity,
    )
    if verified.get("status") != "PASS" or not verified.get(
        "residual_distribution_v1_verified"
    ):
        raise ReleaseServingBindingError(
            "inactive residual distribution release did not pass exact verification"
        )

    manifest = verified["manifest"]
    roles = _inventory_by_role(manifest)
    model_role = "residual_distribution_v1_model"
    registry_role = "model_variant_registry"
    model_row = roles.get(model_role)
    registry_row = roles.get(registry_role)
    if (
        not isinstance(model_row, Mapping)
        or model_row.get("kind") != "model"
        or model_row.get("path") != ROLE_PATH_KINDS[model_role][0]
    ):
        raise ReleaseServingBindingError(
            "verified residual distribution release has no exact model role"
        )
    if (
        not isinstance(registry_row, Mapping)
        or registry_row.get("kind") != "registry"
        or registry_row.get("path") != ROLE_PATH_KINDS[registry_role][0]
    ):
        raise ReleaseServingBindingError(
            "verified residual distribution release has no exact registry role"
        )

    registry_path = release_root / str(registry_row["path"])
    model_path = release_root / str(model_row["path"])
    registry = _checked_json(
        registry_path,
        expected_sha256=str(registry_row["sha256"]),
        label="residual distribution model variant registry",
    )
    candidate_id = str(verified.get("candidate_id") or "")
    candidates = [
        row
        for row in registry.get("variants") or []
        if isinstance(row, Mapping) and str(row.get("variant_id") or "") == candidate_id
    ]
    if len(candidates) != 1:
        raise ReleaseServingBindingError(
            "verified residual distribution registry has no singular candidate entry"
        )
    candidate = candidates[0]
    if (
        candidate.get("prediction_mode") != PREDICTION_MODE
        or candidate.get("live_runtime") != PREDICTION_MODE
        or candidate.get("lifecycle") != "shadow"
        or candidate.get("active_for_headline") is not False
        or candidate.get("live_capture_enabled") is not False
        or candidate.get("counts_toward_weather_model_promotion") is not False
    ):
        raise ReleaseServingBindingError(
            "verified residual distribution registry candidate is not shadow-only"
        )
    route = manifest.get("route") or {}
    if (
        route.get("candidate_id") != candidate_id
        or route.get("prediction_mode") != PREDICTION_MODE
        or route.get("live_runtime") != PREDICTION_MODE
        or route.get("active_for_headline") is not False
    ):
        raise ReleaseServingBindingError(
            "verified residual distribution route and registry candidate disagree"
        )

    model_bundle = _checked_pickle(
        model_path,
        expected_sha256=str(model_row["sha256"]),
        label="residual distribution v1 model",
    )
    if (
        model_bundle.get("candidate_id") != candidate_id
        or model_bundle.get("prediction_mode") != PREDICTION_MODE
    ):
        raise ReleaseServingBindingError(
            "verified residual distribution model identity disagrees with its release"
        )

    return VerifiedServingBundle(
        status=STATUS_SHADOW_BOUND,
        reason=(
            "immutable residual distribution release model, registry, and manifest "
            "verified for shadow capture only"
        ),
        pointer_present=False,
        release_id=str(verified["release_id"]),
        manifest_sha256=str(verified["manifest_sha256"]),
        release_dir=str(release_root),
        route=_deep_freeze(route),
        model_variant_registry=_deep_freeze(registry),
        model_bundle=model_bundle,
        json_artifacts=MappingProxyType({registry_role: _deep_freeze(registry)}),
        artifact_paths=MappingProxyType(
            {
                model_role: str(model_path),
                registry_role: str(registry_path),
            }
        ),
        artifact_hashes=MappingProxyType(
            {
                model_role: str(model_row["sha256"]),
                registry_role: str(registry_row["sha256"]),
            }
        ),
        base_model_bound=True,
        base_model_binding_reason=(
            "exact immutable residual distribution artifact is the verified shadow base graph"
        ),
    )


def get_process_active_serving_bundle(
    *,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    repo_root: str | Path = REPO_ROOT,
    check_runtime: bool = True,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
) -> VerifiedServingBundle:
    """Return the sticky process binding, rejecting any pointer-state change."""

    pointer = Path(pointer_path).resolve()
    key = str(pointer)
    try:
        present, file_sha = _pointer_state(pointer)
    except ReleaseServingBindingError as exc:
        return VerifiedServingBundle(
            status=STATUS_BLOCKED,
            reason=f"{type(exc).__name__}: {exc}",
            pointer_present=True,
        )
    cached = _PROCESS_BUNDLES.get(key)
    if cached is not None:
        if cached.pointer_present != present or cached.pointer_file_sha256 != file_sha:
            return VerifiedServingBundle(
                status=STATUS_RESTART_REQUIRED,
                reason="active release pointer changed; restart process or explicitly clear serving cache",
                pointer_present=present,
                pointer_file_sha256=file_sha,
            )
        return cached
    try:
        bundle = load_verified_active_serving_bundle(
            pointer_path=pointer,
            releases_root=releases_root,
            repo_root=repo_root,
            check_runtime=check_runtime,
            current_runtime_versions=current_runtime_versions,
            current_runtime_identity=current_runtime_identity,
        )
    except (ReleaseArtifactVerificationError, OSError) as exc:
        bundle = VerifiedServingBundle(
            status=STATUS_BLOCKED,
            reason=f"{type(exc).__name__}: {exc}",
            pointer_present=present,
            pointer_file_sha256=file_sha,
        )
    _PROCESS_BUNDLES[key] = bundle
    return bundle


def clear_process_serving_bundle_cache() -> None:
    """Explicitly clear process binding; production callers should restart."""

    _PROCESS_BUNDLES.clear()


def serving_bundle_lineage(bundle: VerifiedServingBundle) -> dict[str, Any]:
    if bundle.status in {STATUS_BOUND, STATUS_SHADOW_BOUND}:
        return {
            "release_id": bundle.release_id,
            "release_manifest_sha256": bundle.manifest_sha256,
            "release_pointer_sha256": bundle.pointer_sha256,
            "release_sequence": bundle.sequence,
            "release_identity_status": (
                "verified_variant_serving_bundle"
                if bundle.status == STATUS_BOUND
                else "verified_inactive_shadow_bundle"
            ),
            "release_identity_reason": bundle.reason,
            "base_model_release_bound": bundle.base_model_bound,
            "base_model_binding_reason": bundle.base_model_binding_reason,
        }
    status = {
        STATUS_RESEARCH_UNBOUND: "research_unbound_non_countable",
        STATUS_RESTART_REQUIRED: "release_restart_required",
        STATUS_BLOCKED: "release_binding_failed",
    }.get(bundle.status, "release_binding_failed")
    return {
        "release_id": "",
        "release_manifest_sha256": "",
        "release_pointer_sha256": "",
        "release_sequence": None,
        "release_identity_status": status,
        "release_identity_reason": bundle.reason,
        "base_model_release_bound": False,
        "base_model_binding_reason": bundle.base_model_binding_reason,
    }
