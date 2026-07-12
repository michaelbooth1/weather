"""Live model-variant prediction tape contract."""

from __future__ import annotations

import inspect
import pickle
from datetime import timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from weather.paths import REPO_ROOT
from weather.release_serving import (
    STATUS_BOUND,
    STATUS_RESEARCH_UNBOUND,
    STATUS_SHADOW_BOUND,
    VerifiedServingBundle,
    serving_bundle_lineage,
)
from weather.variant_registry import DEFAULT_REGISTRY_PATH, load_registry
from weather.schema_registry import schema_version
from weather.market.snapshot_cadence_quality import cadence_adjusted_probability, snapshot_cadence_quality
from weather.model.current_blend import (
    blend_with_current,
    source_freshness_state_from_diagnostics,
)


SCHEMA_VERSION = schema_version("live_variant_predictions")
SUPPORTED_TRACKS = {"no_market", "market_informed"}
KNOWN_LIVE_RUNTIMES = {
    "pooled_candidate_replay",
    "residual_distribution_v1",
    "conservative_bridge_policy",
    "microstructure_shadow_report",
}

LIVE_VARIANT_PREDICTION_COLUMNS = [
    "schema_version",
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "target_date",
    "event_updated_at",
    "release_id",
    "release_manifest_sha256",
    "release_pointer_sha256",
    "release_sequence",
    "release_identity_status",
    "release_identity_reason",
    "captured_input_hash",
    "runtime_identity_schema_version",
    "runtime_git_branch",
    "runtime_git_commit",
    "runtime_git_dirty",
    "runtime_dirty_fingerprint",
    "runtime_source_fingerprint",
    "runtime_code_state",
    "snapshot_cadence",
    "snapshot_cadence_quality_state",
    "snapshot_cadence_gap_count",
    "snapshot_cadence_max_gap_seconds",
    "snapshot_cadence_last_model_age_seconds",
    "snapshot_cadence_confidence_multiplier",
    "snapshot_cadence_permission",
    "snapshot_cadence_reason",
    "trigger_reason",
    "trigger_source",
    "trigger_previous_value",
    "trigger_current_value",
    "trigger_observed_at",
    "variant_id",
    "variant_family",
    "registry_lifecycle",
    "registry_track",
    "registry_roles",
    "active_for_headline",
    "model_version",
    "serving_model_version",
    "serving_model_binding_status",
    "serving_model_binding_reason",
    "artifact_hash",
    "artifact_path",
    "postprocess_config_hash",
    "live_runtime",
    "prediction_status",
    "failure_reason",
    "failure_detail",
    "band_key",
    "range_label",
    "polymarket_market_id",
    "condition_id",
    "clob_token_ids",
    "clob_yes_token_id",
    "clob_no_token_id",
    "enable_order_book",
    "bin_kind",
    "bin_value_c",
    "bin_value_hi_c",
    "variant_probability",
    "cadence_adjusted_variant_probability",
    "serving_model_probability",
    "cadence_adjusted_serving_model_probability",
    "market_yes",
    "market_no",
    "variant_edge",
    "best_bid",
    "best_ask",
    "last_trade_price",
    "volume",
    "liquidity",
    "market_status",
]


def active_live_variants(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return non-control variants explicitly eligible for live tape rows."""
    variants = []
    for row in registry.get("variants") or []:
        roles = {str(role) for role in row.get("roles") or []}
        if "control" in roles:
            continue
        lifecycle = str(row.get("lifecycle") or "")
        headline_active = lifecycle == "active" and bool(row.get("active_for_headline", True))
        diagnostic_live = lifecycle in {"active", "shadow"} and bool(
            row.get("live_capture_enabled", False)
        )
        if not headline_active and not diagnostic_live:
            continue
        variants.append(dict(row))
    return variants


def build_live_variant_prediction_rows(
    *,
    snapshot_id: str,
    captured_at,
    event: dict[str, Any],
    model: dict[str, Any],
    model_client: Any,
    band_rows: list[dict[str, Any]],
    event_slug: str,
    market_id: str,
    target_date: Any,
    serving_model_version: str,
    release_lineage: dict[str, Any] | None = None,
    captured_input_hash: str = "",
    runtime_fields: dict[str, Any] | None = None,
    snapshot_cadence: str = "scheduled",
    cadence_quality: dict[str, Any] | None = None,
    trigger_summary: dict[str, Any] | None = None,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    runner: Any = None,
    serving_bundle: VerifiedServingBundle | None = None,
) -> list[dict[str, Any]]:
    """Build one probability or explicit skip/failure row per active variant/band."""
    binding = (
        serving_bundle
        if isinstance(serving_bundle, VerifiedServingBundle)
        else VerifiedServingBundle(
            status=STATUS_RESEARCH_UNBOUND,
            reason="no verified serving bundle supplied; diagnostic capture is non-countable",
            pointer_present=False,
        )
    )
    if binding.status in {STATUS_BOUND, STATUS_SHADOW_BOUND}:
        variants = _release_bound_variants(binding, market_id)
    elif binding.status == STATUS_RESEARCH_UNBOUND:
        registry = load_registry(registry_path)
        variants = active_live_variants(registry)
    else:
        variants = [_binding_failure_variant(binding)]
    if not variants or not band_rows:
        return []

    runtime_fields = runtime_fields or {}
    # Never trust caller-provided identity. Only the opaque verified bundle
    # returned by weather.release_serving may stamp a release on tape rows.
    del release_lineage
    release_lineage = serving_bundle_lineage(binding)
    trigger_summary = trigger_summary or {}
    cadence_quality = snapshot_cadence_quality({
        "snapshot_cadence": snapshot_cadence,
        **(cadence_quality or {}),
    })
    captured_utc = captured_at.astimezone(timezone.utc).isoformat()
    captured_local = captured_at.isoformat()
    target_date_value = target_date.isoformat() if hasattr(target_date, "isoformat") else target_date
    rows: list[dict[str, Any]] = []
    context = {
        "event": event,
        "model": model,
        "model_client": model_client,
        "captured_at": captured_at,
        "band_rows": band_rows,
        "snapshot_id": snapshot_id,
        "event_slug": event_slug,
        "market_id": market_id,
        "target_date": target_date_value,
        "serving_model_version": serving_model_version,
        "serving_bundle": binding,
    }
    for variant in variants:
        try:
            payload = _predict_variant_payload(variant, context, runner=runner)
        except Exception as exc:  # noqa: BLE001 - serving snapshot persistence must continue
            payload = {
                "status": "failed",
                "failure_reason": "runtime_exception",
                "failure_detail": f"{type(exc).__name__}: {exc}",
            }
        rows.extend(_rows_for_variant(
            variant=variant,
            payload=payload or {},
            band_rows=band_rows,
            model_client=model_client,
            base={
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "captured_at_utc": captured_utc,
                "captured_at_local": captured_local,
                "event_slug": event_slug,
                "market_id": market_id,
                "target_date": target_date_value,
                "event_updated_at": (event or {}).get("updatedAt"),
                "release_id": str(release_lineage.get("release_id") or ""),
                "release_manifest_sha256": str(
                    release_lineage.get("release_manifest_sha256") or ""
                ),
                "release_pointer_sha256": str(
                    release_lineage.get("release_pointer_sha256") or ""
                ),
                "release_sequence": release_lineage.get("release_sequence"),
                "release_identity_status": str(
                    release_lineage.get("release_identity_status") or "unavailable"
                ),
                "release_identity_reason": str(
                    release_lineage.get("release_identity_reason") or ""
                ),
                "captured_input_hash": str(captured_input_hash or ""),
                **runtime_fields,
                "snapshot_cadence": snapshot_cadence,
                **cadence_quality,
                **trigger_summary,
                "serving_model_version": serving_model_version,
                "serving_model_binding_status": (
                    "release_unbound_legacy_base_model"
                    if not binding.base_model_bound
                    else "verified_release_base_model"
                ),
                "serving_model_binding_reason": binding.base_model_binding_reason,
            },
        ))
    return rows


def _release_bound_variants(
    bundle: VerifiedServingBundle,
    market_id: str,
) -> list[dict[str, Any]]:
    if bundle.status == STATUS_SHADOW_BOUND:
        return _residual_distribution_release_bound_variants(bundle)
    markets = bundle.route.get("markets") if isinstance(bundle.route, Mapping) else None
    route = markets.get(str(market_id)) if isinstance(markets, Mapping) else None
    if not isinstance(route, Mapping):
        return [
            {
                "variant_id": "release_route_missing",
                "variant_family": "release_binding",
                "lifecycle": "shadow",
                "track": "no_market",
                "roles": ["release-bound", "skip"],
                "active_for_headline": False,
                "_release_bound": True,
                "_binding_skip_reason": "release_route_missing",
                "_binding_skip_detail": f"verified release has no route for market {market_id!r}",
            }
        ]
    decision = str(route.get("decision") or "")
    variant_id = str(route.get("candidate_variant_id") or "release_route_blocked")
    if decision not in {"promote", "shadow"}:
        return [
            {
                "variant_id": variant_id,
                "variant_family": "release_binding",
                "lifecycle": "shadow",
                "track": "no_market",
                "roles": ["release-bound", "skip"],
                "active_for_headline": False,
                "_release_bound": True,
                "_binding_skip_reason": "release_route_not_candidate",
                "_binding_skip_detail": (
                    f"verified release route decision for {market_id!r} is {decision!r}"
                ),
            }
        ]
    registry_rows = (
        bundle.model_variant_registry.get("variants")
        if isinstance(bundle.model_variant_registry, Mapping)
        else None
    )
    registry_variant = next(
        (
            row
            for row in registry_rows or []
            if isinstance(row, Mapping) and str(row.get("variant_id") or "") == variant_id
        ),
        None,
    )
    model_path = bundle.artifact_paths.get("pooled_band_model")
    model_hash = bundle.artifact_hashes.get("pooled_band_model")
    postprocess_hash = bundle.artifact_hashes.get("pooled_postprocessor_metadata")
    registry_path = str((registry_variant or {}).get("artifact_path") or "").replace("\\", "/")
    if (
        not isinstance(registry_variant, Mapping)
        or registry_variant.get("artifact_role") != "pooled_band_model"
        or registry_variant.get("artifact_sha256") != model_hash
        or not model_path
        or not str(model_path).replace("\\", "/").endswith("/" + registry_path)
    ):
        return [
            {
                "variant_id": variant_id,
                "variant_family": "release_binding",
                "lifecycle": "shadow",
                "track": "no_market",
                "roles": ["release-bound", "skip"],
                "active_for_headline": False,
                "_release_bound": True,
                "_binding_skip_reason": "release_registry_route_mismatch",
                "_binding_skip_detail": (
                    "frozen route candidate does not exactly bind the verified registry/model role"
                ),
            }
        ]
    return [
        {
            **dict(registry_variant),
            "variant_id": variant_id,
            "lifecycle": "active" if decision == "promote" else "shadow",
            "roles": [*list(registry_variant.get("roles") or []), decision],
            "active_for_headline": decision == "promote",
            "artifact_path": model_path,
            "artifact_sha256": model_hash,
            "postprocess_config_hash": postprocess_hash,
            "live_runtime": "pooled_candidate_replay",
            "_release_bound": True,
            "_bound_artifact": bundle.model_bundle,
            "_bound_artifact_path": model_path,
        }
    ]


def _residual_distribution_release_bound_variants(
    bundle: VerifiedServingBundle,
) -> list[dict[str, Any]]:
    """Materialize the single verified residual candidate as shadow-only."""

    candidate_id = str(bundle.route.get("candidate_id") or "")
    registry_rows = (
        bundle.model_variant_registry.get("variants")
        if isinstance(bundle.model_variant_registry, Mapping)
        else None
    )
    candidates = [
        row
        for row in registry_rows or []
        if isinstance(row, Mapping) and str(row.get("variant_id") or "") == candidate_id
    ]
    model_role = "residual_distribution_v1_model"
    model_path = bundle.artifact_paths.get(model_role)
    model_hash = bundle.artifact_hashes.get(model_role)
    if (
        len(candidates) != 1
        or candidates[0].get("live_runtime") != "residual_distribution_v1"
        or candidates[0].get("lifecycle") != "shadow"
        or candidates[0].get("active_for_headline") is not False
        or not model_path
        or not model_hash
        or not isinstance(bundle.model_bundle, Mapping)
    ):
        return [
            {
                "variant_id": candidate_id or "residual_release_binding",
                "variant_family": "release_binding",
                "lifecycle": "shadow",
                "track": "no_market",
                "roles": ["release-bound", "shadow", "skip"],
                "active_for_headline": False,
                "_release_bound": True,
                "_binding_skip_reason": "release_registry_route_mismatch",
                "_binding_skip_detail": (
                    "verified residual release does not exactly bind its registry/model role"
                ),
            }
        ]
    registry_variant = dict(candidates[0])
    return [
        {
            **registry_variant,
            "variant_id": candidate_id,
            "lifecycle": "shadow",
            "roles": [*list(registry_variant.get("roles") or []), "shadow"],
            "active_for_headline": False,
            "artifact_role": model_role,
            "artifact_path": model_path,
            "artifact_sha256": model_hash,
            "live_runtime": "residual_distribution_v1",
            "_release_bound": True,
            "_bound_artifact": bundle.model_bundle,
            "_bound_artifact_path": model_path,
        }
    ]


def _binding_failure_variant(bundle: VerifiedServingBundle) -> dict[str, Any]:
    return {
        "variant_id": "active_release_binding",
        "variant_family": "release_binding",
        "lifecycle": "shadow",
        "track": "no_market",
        "roles": ["release-binding-failed", "skip"],
        "active_for_headline": False,
        "_release_bound": True,
        "_binding_skip_reason": (
            "release_restart_required"
            if bundle.status == "RESTART_REQUIRED"
            else "release_binding_failed"
        ),
        "_binding_skip_detail": bundle.reason,
    }


def _predict_variant_payload(variant: dict[str, Any], context: dict[str, Any], runner: Any = None) -> dict[str, Any]:
    if variant.get("_binding_skip_reason"):
        return {
            "status": "skipped",
            "failure_reason": variant["_binding_skip_reason"],
            "failure_detail": variant.get("_binding_skip_detail") or "",
            "live_runtime": "release_binding",
        }
    if variant.get("_release_bound"):
        runtime_payload = _runtime_variant_payload(variant, context)
        if runtime_payload is not None:
            return runtime_payload
        return _prediction_failure(
            "release_binding",
            "unsupported_release_runtime",
            "verified release route selected an unsupported runtime",
        )
    # The residual-v1 contract is a self-contained shadow runtime.  Do not let
    # generic model-client hooks, caller runners, or embedded model payloads
    # substitute another implementation or fallback before it executes.
    if str(variant.get("live_runtime") or "") == "residual_distribution_v1":
        return _residual_distribution_v1_payload(variant, context)
    if callable(runner):
        return _call_prediction_callable(runner, variant, context)

    model_client = context.get("model_client")
    for method_name in ("predict_live_variant", "predict_variant_distribution"):
        method = getattr(model_client, method_name, None)
        if callable(method):
            return _call_prediction_callable(method, variant, context)

    model_payload = _model_variant_payload(context.get("model") or {}, variant.get("variant_id"))
    if model_payload is not None:
        return model_payload

    runtime_payload = _runtime_variant_payload(variant, context)
    if runtime_payload is not None:
        return runtime_payload

    reason, detail = _skip_reason_for_variant(variant)
    return {
        "status": "skipped",
        "failure_reason": reason,
        "failure_detail": detail,
    }


def _call_prediction_callable(func: Any, variant: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(variant, **context)
    parameters = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return func(variant, **context)
    kwargs = {
        name: value
        for name, value in context.items()
        if name in parameters
    }
    return func(variant, **kwargs)


def _model_variant_payload(model: dict[str, Any], variant_id: Any) -> dict[str, Any] | None:
    if not variant_id:
        return None
    for key in ("live_variant_predictions", "variant_predictions"):
        payloads = model.get(key)
        if isinstance(payloads, dict) and variant_id in payloads:
            payload = payloads[variant_id]
            return payload if isinstance(payload, dict) else {"distribution": payload}
    return None


def _runtime_variant_payload(variant: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    runtime = str(variant.get("live_runtime") or "")
    if runtime == "pooled_candidate_replay":
        return _pooled_candidate_replay_payload(variant, context)
    if runtime == "residual_distribution_v1":
        return _residual_distribution_v1_payload(variant, context)
    if runtime == "conservative_bridge_policy":
        return _serving_passthrough_payload(
            variant,
            context,
            runtime=runtime,
            detail="policy overlay uses serving probabilities until a base candidate live payload is available",
        )
    if runtime == "microstructure_shadow_report":
        return _microstructure_shadow_payload(variant, context)
    return None


def _prediction_failure(runtime: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_reason": reason,
        "failure_detail": detail,
        "live_runtime": runtime,
    }


def _serving_passthrough_payload(
    variant: dict[str, Any],
    context: dict[str, Any],
    *,
    runtime: str,
    detail: str,
) -> dict[str, Any]:
    probabilities = {}
    for band in context.get("band_rows") or []:
        probability = _maybe_float(band.get("model_probability"))
        if probability is not None:
            probabilities[band_key(band)] = probability
    if not probabilities:
        return _prediction_failure(runtime, "missing_serving_probabilities", detail)
    return {
        "status": "predicted",
        "probabilities": probabilities,
        "model_version": variant.get("variant_id"),
        "live_runtime": runtime,
        "failure_detail": detail,
    }


@lru_cache(maxsize=32)
def _load_pickle_artifact(path_text: str, mtime_ns: int) -> dict[str, Any]:
    del mtime_ns
    with Path(path_text).open("rb") as handle:
        artifact = pickle.load(handle)
    if not isinstance(artifact, dict):
        raise ValueError(f"{path_text} is not a dictionary artifact")
    return artifact


def _load_variant_artifact(variant: dict[str, Any]) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    if variant.get("_release_bound"):
        artifact = variant.get("_bound_artifact")
        path_text = variant.get("_bound_artifact_path")
        if not isinstance(artifact, dict) or not path_text:
            return None, Path(path_text) if path_text else None, "verified release model binding is missing"
        return artifact, Path(path_text), None
    artifact_path = _variant_artifact_path(variant)
    if not artifact_path:
        return None, None, "registry entry has no artifact path"
    resolved = _resolve_artifact_path(artifact_path)
    if resolved is None:
        return None, None, f"remote artifact path is not supported for live prediction: {artifact_path}"
    if not resolved.exists():
        return None, resolved, f"artifact path does not exist: {artifact_path}"
    return _load_pickle_artifact(str(resolved), resolved.stat().st_mtime_ns), resolved, None


def _artifact_hash(path: Path | None, variant: dict[str, Any]) -> str | None:
    if variant.get("artifact_hash") or variant.get("artifact_sha256"):
        return variant.get("artifact_hash") or variant.get("artifact_sha256")
    if path is None:
        return None
    try:
        from weather.artifacts import sha256_file

        return sha256_file(path)
    except Exception:  # noqa: BLE001 - hash is metadata, not a live prediction blocker
        return None


def _feature_vector(context: dict[str, Any]) -> dict[str, Any]:
    model = context.get("model") or {}
    vector = model.get("feature_vector") or {}
    return dict(vector) if isinstance(vector, dict) else {}


def _band_value(band: dict[str, Any], key: str) -> Any:
    value = band.get(key)
    if value is not None:
        return value
    aliases = {
        "bin_value_c": ("value", "bin_value"),
        "bin_value_hi_c": ("value_hi", "bin_value_hi"),
        "bin_kind": ("kind",),
    }
    for alias in aliases.get(key, ()):
        if band.get(alias) is not None:
            return band.get(alias)
    return value


def _band_prediction_records(feature_vector: dict[str, Any], band_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from weather.model.variant_prediction_runtime import band_prediction_record

    records = []
    for band in band_rows:
        records.append(band_prediction_record(
            feature_vector,
            _band_value(band, "bin_kind"),
            _band_value(band, "bin_value_c"),
            value_hi=_band_value(band, "bin_value_hi_c"),
        ))
    return records


def _postprocess_enabled(config: dict[str, Any]) -> bool:
    return any(
        key in (config or {})
        for key in (
            "hard_floor_enabled",
            "support_floor_enabled",
            "late_lockin_enabled",
            "adjacent_calibration_enabled",
            "exact_winner_catchup_enabled",
            "forecast_centering_enabled",
        )
    )


def _normalize_probability_partition(probabilities: dict[str, float], gamma: float) -> dict[str, float]:
    if not probabilities:
        return probabilities
    weights = {
        key: max(1e-12, float(value)) ** max(0.1, float(gamma or 1.0))
        for key, value in probabilities.items()
    }
    total = sum(weights.values())
    if total <= 0:
        return probabilities
    return {key: value / total for key, value in weights.items()}


def _apply_current_blend(
    probabilities: dict[str, float],
    band_rows: list[dict[str, Any]],
    postprocess: dict[str, Any],
    market_id: str | None,
    *,
    feature_vector: dict[str, Any] | None = None,
    source_diagnostics: Any = None,
) -> dict[str, float]:
    if not postprocess.get("current_blend_enabled", False):
        return probabilities
    output = dict(probabilities)
    records = _band_prediction_records(feature_vector or {}, band_rows)
    source_state = (
        (feature_vector or {}).get("source_freshness_state")
        or (feature_vector or {}).get("source_status_group")
        or source_freshness_state_from_diagnostics(source_diagnostics)
    )
    for band, record in zip(band_rows, records):
        key = band_key(band)
        candidate = _maybe_float(output.get(key))
        current = _maybe_float(band.get("model_probability"))
        if candidate is None or current is None:
            continue
        blend_context = dict(record)
        blend_context["market_id"] = str(market_id or "")
        blend_context["source_freshness_state"] = source_state
        output[key] = blend_with_current(
            candidate,
            current,
            row=blend_context,
            config=postprocess,
        )
    return output


def _pooled_candidate_replay_payload(variant: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    runtime = "pooled_candidate_replay"
    artifact, artifact_path, error = _load_variant_artifact(variant)
    if error:
        return _prediction_failure(runtime, "missing_artifact", error)
    feature_vector = _feature_vector(context)
    if not feature_vector:
        return _prediction_failure(runtime, "missing_feature_vector", "live snapshot model did not include feature_vector")
    band_rows = list(context.get("band_rows") or [])
    if not band_rows:
        return _prediction_failure(runtime, "missing_band_rows", "live snapshot has no band rows")
    mode = str((artifact or {}).get("prediction_mode") or "band_binary")
    try:
        if mode == "continuous_density_f":
            probabilities = _density_probabilities(
                artifact or {},
                feature_vector,
                band_rows,
                market_id=str(context.get("market_id") or ""),
            )
        else:
            probabilities = _band_binary_probabilities(artifact or {}, feature_vector, band_rows, context)
    except Exception as exc:  # noqa: BLE001 - one variant must not block serving tape
        return _prediction_failure(runtime, "runtime_exception", f"{type(exc).__name__}: {exc}")
    if not probabilities:
        return _prediction_failure(runtime, "missing_band_probability", "artifact produced no live band probabilities")
    return {
        "status": "predicted",
        "probabilities": probabilities,
        "model_version": variant.get("variant_id"),
        "artifact_path": str(artifact_path) if artifact_path else _variant_artifact_path(variant),
        "artifact_hash": _artifact_hash(artifact_path, variant),
        "postprocess_config_hash": variant.get("postprocess_config_hash"),
        "live_runtime": runtime,
    }


def _residual_distribution_v1_payload(
    variant: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run the residual-v1 shadow adapter without touching incumbent stages.

    The core predictor owns feature validation, source-health policy, probability
    construction, and its status taxonomy.  This adapter only binds the verified
    artifact and registered market unit, forwards the exact live inputs, and
    attaches tape metadata.  In particular, it must not route the result through
    the legacy density calibration, pooled postprocessing, partition
    normalization, current blending, or any serving fallback.
    """

    runtime = "residual_distribution_v1"
    try:
        artifact, artifact_path, error = _load_variant_artifact(variant)
    except Exception as exc:  # noqa: BLE001 - shadow artifact failure is isolated
        return _prediction_failure(
            runtime,
            "artifact_load_failed",
            f"{type(exc).__name__}: {exc}",
        )
    if error:
        return _prediction_failure(runtime, "missing_artifact", error)

    market_id = str(context.get("market_id") or "").strip()
    try:
        from weather.market.market_registry import REGISTRY

        spec = REGISTRY.get(market_id)
    except Exception as exc:  # noqa: BLE001 - registry lookup cannot affect serving
        return _prediction_failure(
            runtime,
            "market_registry_unavailable",
            f"{type(exc).__name__}: {exc}",
        )
    if spec is None:
        return {
            "status": "skipped",
            "failure_reason": "abstain_unknown_market",
            "failure_detail": (
                "residual distribution requires a registered market_id, "
                f"got {market_id!r}"
            ),
            "live_runtime": runtime,
        }

    model = context.get("model") or {}
    feature_vector = model.get("feature_vector") or {}
    source_diagnostics = model.get("source_diagnostics")
    band_rows = list(context.get("band_rows") or [])
    unit = str(spec.display_unit).upper()

    try:
        from weather.model.residual_distribution_v1 import predict_residual_distribution_v1

        result = predict_residual_distribution_v1(
            artifact=artifact or {},
            feature_vector=dict(feature_vector) if isinstance(feature_vector, dict) else {},
            source_diagnostics=(
                list(source_diagnostics)
                if isinstance(source_diagnostics, (list, tuple))
                else source_diagnostics
            ),
            market_id=market_id,
            unit=unit,
            band_rows=band_rows,
        )
    except Exception as exc:  # noqa: BLE001 - a shadow model must never affect incumbent serving
        return _prediction_failure(
            runtime,
            "runtime_exception",
            f"{type(exc).__name__}: {exc}",
        )

    if not isinstance(result, dict):
        return _prediction_failure(
            runtime,
            "invalid_runtime_payload",
            "predict_residual_distribution_v1 did not return a dictionary payload",
        )

    payload = dict(result)
    payload.setdefault("model_version", variant.get("variant_id"))
    payload.setdefault(
        "artifact_path",
        str(artifact_path) if artifact_path else _variant_artifact_path(variant),
    )
    payload.setdefault("artifact_hash", _artifact_hash(artifact_path, variant))
    payload.setdefault("postprocess_config_hash", variant.get("postprocess_config_hash"))
    payload["live_runtime"] = runtime
    return payload


def _band_binary_probabilities(
    artifact: dict[str, Any],
    feature_vector: dict[str, Any],
    band_rows: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, float]:
    from weather.model.variant_prediction_runtime import apply_band_postprocessing, predict_band_rows_for_bundle

    records = _band_prediction_records(feature_vector, band_rows)
    if not records:
        return {}
    hour = str(records[0].get("cutoff_hour") or (context.get("captured_at").hour if context.get("captured_at") else ""))
    bundle = (artifact.get("models") or {}).get(hour)
    if not bundle:
        raise ValueError(f"artifact has no live model for cutoff hour {hour!r}")
    raw = predict_band_rows_for_bundle(bundle, records, postprocess=False)
    postprocess = artifact.get("postprocess") or {}
    probabilities = {}
    for band, record, probability in zip(band_rows, records, raw):
        p = _maybe_float(probability)
        if p is None:
            continue
        if _postprocess_enabled(postprocess):
            p = apply_band_postprocessing(p, record, config=postprocess)
        probabilities[band_key(band)] = max(0.0, min(1.0, float(p)))
    if postprocess.get("partition_normalization_enabled", True):
        probabilities = _normalize_probability_partition(
            probabilities,
            float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    probabilities = _apply_current_blend(
        probabilities,
        band_rows,
        postprocess,
        str(feature_vector.get("market_id") or context.get("market_id") or ""),
        feature_vector=feature_vector,
        source_diagnostics=(context.get("model") or {}).get("source_diagnostics"),
    )
    return probabilities


def _density_probabilities(
    artifact: dict[str, Any],
    feature_vector: dict[str, Any],
    band_rows: list[dict[str, Any]],
    *,
    market_id: str,
) -> dict[str, float]:
    from weather.market.market_registry import REGISTRY
    from weather.model.variant_prediction_runtime import (
        apply_continuous_density_calibration,
        apply_density_band_postprocessing,
        density_band_probability_from_distribution,
        density_projection_index,
        density_projection_probability,
        predict_density_rows_for_bundle,
    )

    market_id = str(market_id or "").strip()
    spec = REGISTRY.get(market_id)
    if spec is None:
        raise ValueError(f"density runtime requires a registered market_id, got {market_id!r}")
    unit = str(spec.display_unit).upper()
    existing_market_id = str(feature_vector.get("market_id") or "").strip()
    if existing_market_id and existing_market_id != market_id:
        raise ValueError(
            "density runtime market_id mismatch: "
            f"feature_vector={existing_market_id!r}, context={market_id!r}"
        )
    for field in ("display_unit", "unit"):
        existing_unit = str(feature_vector.get(field) or "").strip().upper()
        if existing_unit and existing_unit != unit:
            raise ValueError(
                "density runtime unit mismatch: "
                f"feature_vector.{field}={existing_unit!r}, registry={unit!r}"
            )

    runtime_features = dict(feature_vector)
    runtime_features["market_id"] = market_id
    runtime_features["display_unit"] = unit
    runtime_features["unit"] = unit
    records = _band_prediction_records(runtime_features, band_rows)
    if not records:
        return {}

    payloads = predict_density_rows_for_bundle(artifact, [runtime_features])
    payload = payloads[0] if payloads else None
    if not payload:
        return {}
    postprocess = artifact.get("density_postprocess") or {}
    context_record = records[0]
    payload = apply_continuous_density_calibration(
        payload,
        artifact,
        floor_bucket=context_record.get("observed_floor_bucket"),
        unit=unit,
        resolution_weight=context_record.get("late_lockin_strength", 0.0),
        cutoff_hour=runtime_features.get("cutoff_hour"),
    )
    index = density_projection_index(payload)
    probabilities = {}
    for band, record in zip(band_rows, records):
        kind = _band_value(band, "bin_kind")
        value = _band_value(band, "bin_value_c")
        value_hi = _band_value(band, "bin_value_hi_c")
        probability = density_projection_probability(index, unit, kind, value, value_hi=value_hi)
        if probability is None:
            probability = density_band_probability_from_distribution(
                payload,
                spec,
                {"kind": kind, "value": value, "value_hi": value_hi, "unit": unit},
            )
        if _maybe_float(probability) is not None:
            probability = apply_density_band_postprocessing(
                probability,
                record,
                config=postprocess,
            )
            probabilities[band_key(band)] = max(0.0, min(1.0, float(probability)))
    if postprocess.get("enabled") and postprocess.get("partition_normalization_enabled", False):
        probabilities = _normalize_probability_partition(
            probabilities,
            float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    return probabilities


def _microstructure_shadow_payload(variant: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    runtime = "microstructure_shadow_report"
    if str(variant.get("postprocess_config_hash") or "") == "taxonomy_gate":
        return {
            "status": "skipped",
            "failure_reason": "taxonomy_gate_unavailable_live",
            "failure_detail": "taxonomy-gated CLOB overlay requires casebook taxonomy unavailable at live snapshot time",
            "live_runtime": runtime,
        }
    artifact, artifact_path, error = _load_variant_artifact(variant)
    if error:
        return _prediction_failure(runtime, "missing_artifact", error)
    band_rows = list(context.get("band_rows") or [])
    records = []
    for band in band_rows:
        serving_p = _maybe_float(band.get("model_probability"))
        market_yes = _maybe_float(band.get("market_yes"))
        if serving_p is None or market_yes is None:
            continue
        bid = _maybe_float(band.get("best_bid"))
        ask = _maybe_float(band.get("best_ask"))
        midpoint = ((bid + ask) / 2.0) if bid is not None and ask is not None else market_yes
        spread = (ask - bid) if bid is not None and ask is not None else None
        records.append({
            "_band_key": band_key(band),
            "candidate_p": serving_p,
            "replayed_p": serving_p,
            "market_yes": market_yes,
            "clob_feature_available": 1.0,
            "clob_midpoint": midpoint,
            "clob_spread": spread,
            "clob_liquidity_score": _maybe_float(band.get("liquidity") or band.get("volume")),
            "source_freshness_state": "live_snapshot",
            "forecast_source_count_bucket": "unknown",
            "forecast_disagreement_bucket": "unknown",
            "forecast_bucket_pressure": "unknown",
            "casebook_taxonomy": "live_unlabeled",
        })
    if not records:
        return _prediction_failure(
            runtime,
            "missing_microstructure_features",
            "live CLOB overlay requires serving probability and market probability",
        )
    try:
        from weather.model.variant_prediction_runtime import microstructure_feature_frame

        feature_names = artifact.get("feature_names") or []
        frame = microstructure_feature_frame(records, feature_names=feature_names)
        x_eval = artifact["imputer"].transform(frame)
        probabilities = artifact["model"].predict_proba(x_eval)
        classes = [int(value) for value in artifact.get("classes") or artifact["model"].classes_]
        idx = classes.index(1) if 1 in classes else 0
        band_probabilities = {
            record["_band_key"]: max(0.0, min(1.0, float(prob[idx])))
            for record, prob in zip(records, probabilities)
        }
    except Exception as exc:  # noqa: BLE001
        return _prediction_failure(runtime, "runtime_exception", f"{type(exc).__name__}: {exc}")
    return {
        "status": "predicted",
        "probabilities": band_probabilities,
        "model_version": variant.get("variant_id"),
        "artifact_path": str(artifact_path) if artifact_path else _variant_artifact_path(variant),
        "artifact_hash": _artifact_hash(artifact_path, variant),
        "postprocess_config_hash": variant.get("postprocess_config_hash"),
        "live_runtime": runtime,
    }


def _skip_reason_for_variant(variant: dict[str, Any]) -> tuple[str, str]:
    track = variant.get("track")
    if track not in SUPPORTED_TRACKS:
        return "unsupported_track", f"registry track {track!r} is not supported by the live variant tape"

    artifact_path = _variant_artifact_path(variant)
    if artifact_path:
        resolved = _resolve_artifact_path(artifact_path)
        if resolved is not None and not resolved.exists():
            return "missing_artifact", f"artifact path does not exist: {artifact_path}"
    elif bool(variant.get("artifact_required", True)) and not (
        variant.get("artifact_hash") or variant.get("artifact_sha256")
    ):
        return "missing_artifact", "registry entry has no artifact path or artifact hash"

    runtime = variant.get("live_runtime") or variant.get("prediction_function")
    if not runtime:
        return "unsupported_runtime", "registry entry has no live runtime contract"
    if str(runtime) in KNOWN_LIVE_RUNTIMES:
        return "runtime_unavailable", f"live runtime {runtime!r} could not produce a bounded prediction"
    return "unsupported_runtime", f"live runtime {runtime!r} requires an explicit prediction runner"


def _variant_artifact_path(variant: dict[str, Any]) -> str | None:
    for key in ("artifact_path", "model_artifact_path", "artifact_uri"):
        value = variant.get(key)
        if value:
            return str(value)
    return None


def _resolve_artifact_path(value: str) -> Path | None:
    if "://" in value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _rows_for_variant(
    *,
    variant: dict[str, Any],
    payload: dict[str, Any],
    band_rows: list[dict[str, Any]],
    model_client: Any,
    base: dict[str, Any],
) -> list[dict[str, Any]]:
    status = _normalized_status(payload)
    failure_reason = payload.get("failure_reason")
    failure_detail = payload.get("failure_detail")
    artifact_path = payload.get("artifact_path") or _variant_artifact_path(variant)
    artifact_hash = payload.get("artifact_hash") or variant.get("artifact_hash") or variant.get("artifact_sha256")
    postprocess_hash = (
        payload.get("postprocess_config_hash")
        or payload.get("postprocess_hash")
        or variant.get("postprocess_config_hash")
        or variant.get("postprocess_hash")
    )
    rows = []
    for band in band_rows:
        probability = None
        row_status = status
        row_failure_reason = failure_reason
        row_failure_detail = failure_detail
        if status == "predicted":
            probability = _payload_band_probability(payload, band, model_client)
            if probability is None:
                row_status = "failed"
                row_failure_reason = "missing_band_probability"
                row_failure_detail = f"variant payload did not include probability for {band_key(band)}"
        market_yes = _maybe_float(band.get("market_yes"))
        variant_edge = probability - market_yes if probability is not None and market_yes is not None else None
        multiplier = (base or {}).get("snapshot_cadence_confidence_multiplier")
        rows.append({
            **base,
            "variant_id": variant.get("variant_id"),
            "variant_family": variant.get("variant_family"),
            "registry_lifecycle": variant.get("lifecycle"),
            "registry_track": variant.get("track"),
            "registry_roles": "|".join(str(role) for role in (variant.get("roles") or [])),
            "active_for_headline": bool(variant.get("active_for_headline", True)),
            "model_version": payload.get("model_version") or variant.get("model_version"),
            "artifact_hash": artifact_hash,
            "artifact_path": artifact_path,
            "postprocess_config_hash": postprocess_hash,
            "live_runtime": payload.get("live_runtime") or variant.get("live_runtime"),
            "prediction_status": row_status,
            "failure_reason": row_failure_reason,
            "failure_detail": row_failure_detail,
            "band_key": band_key(band),
            "range_label": band.get("range_label"),
            "polymarket_market_id": band.get("polymarket_market_id"),
            "condition_id": band.get("condition_id"),
            "clob_token_ids": band.get("clob_token_ids"),
            "clob_yes_token_id": band.get("clob_yes_token_id"),
            "clob_no_token_id": band.get("clob_no_token_id"),
            "enable_order_book": band.get("enable_order_book"),
            "bin_kind": band.get("bin_kind"),
            "bin_value_c": band.get("bin_value_c"),
            "bin_value_hi_c": band.get("bin_value_hi_c"),
            "variant_probability": probability,
            "cadence_adjusted_variant_probability": cadence_adjusted_probability(
                probability,
                market_yes,
                multiplier,
            ),
            "serving_model_probability": band.get("model_probability"),
            "cadence_adjusted_serving_model_probability": cadence_adjusted_probability(
                band.get("model_probability"),
                market_yes,
                multiplier,
            ),
            "market_yes": band.get("market_yes"),
            "market_no": band.get("market_no"),
            "variant_edge": variant_edge,
            "best_bid": band.get("best_bid"),
            "best_ask": band.get("best_ask"),
            "last_trade_price": band.get("last_trade_price"),
            "volume": band.get("volume"),
            "liquidity": band.get("liquidity"),
            "market_status": band.get("market_status"),
        })
    return rows


def _normalized_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"predicted", "ok", "success"}:
        return "predicted"
    if status in {"failed", "failure", "error"}:
        return "failed"
    if status in {"skipped", "skip"}:
        return "skipped"
    if payload.get("distribution") is not None or payload.get("probabilities") is not None:
        return "predicted"
    return "skipped"


def _payload_band_probability(payload: dict[str, Any], band: dict[str, Any], model_client: Any) -> float | None:
    probabilities = payload.get("probabilities") or payload.get("band_probabilities")
    if isinstance(probabilities, dict):
        keys = [
            band_key(band),
            band.get("range_label"),
            str(band.get("range_label") or ""),
        ]
        for key in keys:
            if key in probabilities:
                return _maybe_float(probabilities.get(key))
    distribution = payload.get("distribution")
    if distribution is None:
        return _maybe_float(payload.get("probability"))
    bin_data = {
        "kind": band.get("bin_kind"),
        "value": band.get("bin_value_c"),
        "value_hi": band.get("bin_value_hi_c") or band.get("bin_value_c"),
        "label": band.get("range_label"),
        "market_yes": band.get("market_yes"),
        "market_no": band.get("market_no"),
    }
    method = getattr(model_client, "bin_probability", None)
    if callable(method):
        try:
            return _maybe_float(method(distribution, bin_data))
        except TypeError:
            return _maybe_float(method(distribution, bin_data, calibration_context=payload.get("calibration_context") or {}))
    return _raw_bin_probability(distribution, bin_data)


def _raw_bin_probability(distribution: dict[Any, Any], bin_data: dict[str, Any]) -> float | None:
    if not isinstance(distribution, dict):
        return None
    items = {}
    for bucket, probability in distribution.items():
        numeric_bucket = _maybe_float(bucket)
        numeric_probability = _maybe_float(probability)
        if numeric_bucket is not None and numeric_probability is not None:
            items[int(numeric_bucket)] = numeric_probability
    value = _maybe_float(bin_data.get("value"))
    if value is None:
        return None
    value = int(value)
    value_hi = int(_maybe_float(bin_data.get("value_hi")) or value)
    kind = bin_data.get("kind")
    if kind == "lte":
        return sum(prob for temp, prob in items.items() if temp <= value)
    if kind == "gte":
        return sum(prob for temp, prob in items.items() if temp >= value)
    return sum(prob for temp, prob in items.items() if value <= temp <= value_hi)


def band_key(row: dict[str, Any]) -> str:
    kind = row.get("bin_kind")
    value = _band_key_value(row.get("bin_value_c"))
    value_hi = _band_key_value(row.get("bin_value_hi_c"))
    if kind == "lte":
        return f"lte_{value}c"
    if kind == "gte":
        return f"gte_{value}c"
    if value_hi and value_hi != value:
        return f"eq_{value}_{value_hi}c"
    return f"eq_{value}c"


def _band_key_value(value: Any) -> str:
    if value in (None, ""):
        return "unknown"
    numeric = _maybe_float(value)
    if numeric is None:
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value))
    if abs(numeric - round(numeric)) < 1e-9:
        return str(int(round(numeric)))
    return str(numeric).replace(".", "p")


def _maybe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
