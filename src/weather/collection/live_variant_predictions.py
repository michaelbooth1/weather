"""Live model-variant prediction tape contract."""

from __future__ import annotations

import inspect
from datetime import timezone
from pathlib import Path
from typing import Any

from weather.paths import REPO_ROOT
from weather.reporting.variant_registry import DEFAULT_REGISTRY_PATH, load_registry
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("live_variant_predictions")
SUPPORTED_TRACKS = {"no_market", "market_informed"}

LIVE_VARIANT_PREDICTION_COLUMNS = [
    "schema_version",
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "target_date",
    "event_updated_at",
    "runtime_identity_schema_version",
    "runtime_git_branch",
    "runtime_git_commit",
    "runtime_git_dirty",
    "runtime_dirty_fingerprint",
    "runtime_source_fingerprint",
    "runtime_code_state",
    "snapshot_cadence",
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
    "serving_model_probability",
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
    """Return active non-control variants that should have live tape rows."""
    variants = []
    for row in registry.get("variants") or []:
        roles = {str(role) for role in row.get("roles") or []}
        if row.get("lifecycle") != "active":
            continue
        if not bool(row.get("active_for_headline", True)):
            continue
        if "control" in roles:
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
    runtime_fields: dict[str, Any] | None = None,
    snapshot_cadence: str = "scheduled",
    trigger_summary: dict[str, Any] | None = None,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    runner: Any = None,
) -> list[dict[str, Any]]:
    """Build one probability or explicit skip/failure row per active variant/band."""
    registry = load_registry(registry_path)
    variants = active_live_variants(registry)
    if not variants or not band_rows:
        return []

    runtime_fields = runtime_fields or {}
    trigger_summary = trigger_summary or {}
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
                **runtime_fields,
                "snapshot_cadence": snapshot_cadence,
                **trigger_summary,
                "serving_model_version": serving_model_version,
            },
        ))
    return rows


def _predict_variant_payload(variant: dict[str, Any], context: dict[str, Any], runner: Any = None) -> dict[str, Any]:
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
            "serving_model_probability": band.get("model_probability"),
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
