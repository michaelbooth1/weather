"""Snapshot persistence store and schema constants."""

from __future__ import annotations

import csv
import errno
import hashlib
import inspect
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from weather.paths import data_path

from weather.collection.forecast_payload_cas import (
    CANONICAL_JSON_HASH_ALGORITHM,
    ForecastPayloadCASIntegrityError,
    LOCAL_FORECAST_PAYLOAD_CAS_KIND,
    LOCAL_FORECAST_PAYLOAD_SCOPE,
    RAW_BYTES_HASH_ALGORITHM,
    SHARED_FORECAST_PAYLOAD_CAS_KIND,
    SHARED_FORECAST_PAYLOAD_SCOPE,
    SharedForecastPayloadCAS,
    forecast_payload_byte_summary,
    fanout_prepublish_accounting,
    parse_market_invariant_attestation,
    validate_nbm_shared_manifest_identity,
)
from weather.collection.redaction import redact_sensitive_url_parts
from weather.collection.snapshot_store_backfill import (
    backfill_explanations,
    backfill_snapshot_cadence_quality,
    build_parser,
    main,
)
from weather.collection.forecast_archive import (
    FORECAST_COLUMNS,
    append_rows as append_forecast_rows,
    build_forecast_rows,
)
from weather.collection.live_variant_predictions import (
    LIVE_VARIANT_PREDICTION_COLUMNS,
    build_live_variant_prediction_rows,
)
from weather.market.market_config import config_for_date, config_from_event
from weather.market.snapshot_cadence_quality import snapshot_cadence_quality
from weather.model.feature_store import (
    FEATURE_AUDIT_COLUMNS,
    audit_row,
    row_forecast_high_native,
    row_max_native,
    row_max_since_7am_native,
    row_same_day_max_native,
    row_temp_native,
)
from weather.model.model_constants import LIVE_CACHE_MAX_AGE_MINUTES, SOURCE_CACHE_TTL_MINUTES
from weather.model.model_identity import model_replay_identity
from weather.model.toronto_model import MODEL_VERSION_HGB, TORONTO_TZ
from weather.release_artifacts import canonical_payload_sha256
from weather.release_serving import (
    STATUS_SHADOW_BOUND,
    ReleaseServingBindingError,
    VerifiedServingBundle,
    clear_process_serving_bundle_cache,
    get_process_active_serving_bundle,
    load_verified_residual_distribution_v1_shadow_bundle,
    serving_bundle_lineage,
)
from weather.runtime_identity import (
    current_identity_for,
    format_runtime_identity,
    get_runtime_identity,
    identities_match,
)
from weather.schema_registry import schema_version

SNAPSHOT_INTERVAL = timedelta(minutes=10)
# The managed loop fires on a period equal to SNAPSHOT_INTERVAL, so every
# scheduled capture lands right at the due boundary. With a strict
# `now - last >= interval` predicate, sub-cycle timing jitter makes `now - last`
# fall a few seconds short on a large share of ticks; that near-miss skips the
# write and the market waits a whole extra cycle (~2x interval), pulling
# effective cadence to ~13 min and capture_ratio to ~0.7 even on an on-cadence,
# outage-free loop (item 320). A small due tolerance (a fraction of the
# interval) absorbs that jitter so an on-cadence tick is never rejected, without
# changing the nominal interval or causing cadence creep (the loop period still
# rate-limits writes to one per tick). See item 320.
SNAPSHOT_DUE_TOLERANCE = timedelta(seconds=60)
DEFAULT_MARKET_CONFIG = config_for_date()
DEFAULT_SNAPSHOT_ROOT = data_path() / "snapshots" / DEFAULT_MARKET_CONFIG.event_slug
# Fallback used only when a snapshot's model dict carries no model_version.
MODEL_VERSION = MODEL_VERSION_HGB

# Replay corpus: each snapshot persists the full merged model `sources` plus the
# exact build `now`, so any future model version can be re-run over the captured
# day and scored against settlement. This turns every captured snapshot into a
# permanent, replayable test case (see src/replay.py, src/replay_backtest.py).
REPLAY_SCHEMA_VERSION = schema_version("replay_inputs")
FORECAST_PAYLOAD_SCHEMA_VERSION = schema_version("forecast_payload_manifest")
OBSERVATION_PAYLOAD_SCHEMA_VERSION = schema_version("observation_payload_manifest")
CAPTURED_INPUT_HASH_ALGORITHM = "sha256-canonical-json;omit=captured_input_hash"
REPLAY_RECONSTRUCTED_FILENAME = "replay_inputs_reconstructed.jsonl"
SNAPSHOT_EXPLANATION_SCHEMA_VERSION = "snapshot_explanations_v0.1"
SNAPSHOT_PROBABILITY_TOLERANCE = 1e-9
RESIDUAL_SHADOW_RELEASE_DIR_ENV = (
    "WEATHER_RESIDUAL_DISTRIBUTION_V1_SHADOW_RELEASE_DIR"
)
RESIDUAL_SHADOW_MANIFEST_SHA256_ENV = (
    "WEATHER_RESIDUAL_DISTRIBUTION_V1_SHADOW_MANIFEST_SHA256"
)
_SHADOW_CAPTURE_BUNDLES: dict[tuple[str, str], VerifiedServingBundle] = {}

# ``json.JSONEncoder.iterencode`` bounds allocation by encoder token instead of
# by the whole document. Slice unusually large scalar tokens as well so their
# transient UTF-8 copies stay small. The encoder can still hold the escaped
# representation of one scalar, but never joins all document tokens in memory.
JSON_STREAM_TEXT_CHUNK_CHARS = 1024 * 1024
JSON_STREAM_BYTE_CHUNK_BYTES = 1024 * 1024


def _iter_json_text_chunks(
    payload,
    *,
    sort_keys=True,
    separators=None,
    ensure_ascii=True,
    default=str,
    allow_nan=True,
):
    """Yield the exact text emitted by matching ``json.dumps`` options."""

    encoder = json.JSONEncoder(
        sort_keys=sort_keys,
        separators=separators,
        ensure_ascii=ensure_ascii,
        default=default,
        allow_nan=allow_nan,
    )
    for encoded_token in encoder.iterencode(payload):
        for offset in range(0, len(encoded_token), JSON_STREAM_TEXT_CHUNK_CHARS):
            yield encoded_token[offset : offset + JSON_STREAM_TEXT_CHUNK_CHARS]


def _iter_json_byte_chunks(payload, **encoder_options):
    for text_chunk in _iter_json_text_chunks(payload, **encoder_options):
        yield text_chunk.encode("utf-8")


def _json_digest_and_size(payload, algorithm, **encoder_options):
    digest = hashlib.new(algorithm)
    payload_bytes = 0
    for byte_chunk in _iter_json_byte_chunks(payload, **encoder_options):
        digest.update(byte_chunk)
        payload_bytes += len(byte_chunk)
    return digest.hexdigest(), payload_bytes


def _verified_serving_bundle_once_per_process() -> VerifiedServingBundle:
    """Resolve the sticky process bundle while detecting pointer changes."""

    return get_process_active_serving_bundle()


def _verified_release_lineage_once_per_process():
    return serving_bundle_lineage(_verified_serving_bundle_once_per_process())


def _verified_residual_shadow_bundle_once_per_process() -> VerifiedServingBundle | None:
    """Resolve an opt-in inactive release without changing active serving state."""

    release_dir = str(os.environ.get(RESIDUAL_SHADOW_RELEASE_DIR_ENV) or "").strip()
    if not release_dir:
        return None
    manifest_sha256 = str(
        os.environ.get(RESIDUAL_SHADOW_MANIFEST_SHA256_ENV) or ""
    ).strip().lower()
    if len(manifest_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in manifest_sha256
    ):
        raise ReleaseServingBindingError(
            f"{RESIDUAL_SHADOW_MANIFEST_SHA256_ENV} must pin an exact SHA-256"
        )
    key = (str(Path(release_dir).resolve()), manifest_sha256)
    cached = _SHADOW_CAPTURE_BUNDLES.get(key)
    if cached is not None:
        return cached
    bundle = load_verified_residual_distribution_v1_shadow_bundle(
        key[0],
        expected_manifest_sha256=manifest_sha256,
    )
    _SHADOW_CAPTURE_BUNDLES[key] = bundle
    return bundle


def _assert_snapshot_model_serving_binding(
    serving_bundle: VerifiedServingBundle,
    model_client,
) -> None:
    model_bundle = getattr(model_client, "serving_bundle", None)
    if serving_bundle.pointer_present:
        if (
            model_bundle is not serving_bundle
            or not serving_bundle.base_model_bound
            or not getattr(model_bundle, "base_model_bound", False)
        ):
            raise ReleaseServingBindingError(
                "snapshot model construction and persistence do not share one verified "
                "active-release base-model bundle"
            )
    elif model_bundle is not None and getattr(model_bundle, "pointer_present", False):
        raise ReleaseServingBindingError(
            "snapshot persistence is research-unbound but its model client is release-bound"
        )


# Scope the long-running collection process identity to the code it actually
# imports, so a commit to an unrelated module (reporting/promotion/calibration a
# collection loop never imports) does not flip the loop to stale and tear down
# capture cadence. Only changes to imported code trigger a current-code re-adopt.
PROCESS_RUNTIME_IDENTITY = get_runtime_identity(scope_files="loaded")
OPEN_METEO_SOURCE_FAMILY = {
    "open_meteo",
    "open_meteo_air_quality",
    "open_meteo_global_models",
    "open_meteo_multimodel",
    "global_ensemble",
    "eccc_gem",
}
FORECAST_RAW_PAYLOAD_RETENTION_ENV = "WEATHER_RETAIN_RAW_FORECAST_PAYLOADS"
OBSERVATION_RAW_PAYLOAD_RETENTION_ENV = "WEATHER_RETAIN_RAW_OBSERVATION_PAYLOADS"


RUNTIME_IDENTITY_COLUMNS = [
    "runtime_identity_schema_version",
    "runtime_git_branch",
    "runtime_git_commit",
    "runtime_git_dirty",
    "runtime_dirty_fingerprint",
    "runtime_source_fingerprint",
    "runtime_code_state",
]


def snapshot_id_for_captured_at(captured_at):
    """Return a collision-resistant snapshot id for a captured timestamp."""
    return captured_at.strftime("%Y%m%dT%H%M%S%f%z")


LONG_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "event_updated_at",
    "model_version",
    "feature_schema_version",
    *RUNTIME_IDENTITY_COLUMNS,
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
    "top_temp_c",
    "top_probability",
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
    "model_probability",
    "market_yes",
    "market_no",
    "edge",
    "best_bid",
    "best_ask",
    "last_trade_price",
    "volume",
    "liquidity",
    "market_status",
    "wu_history_high_c",
    "wu_current_c",
    "wu_max_since_7am_c",
    "station_current_c",
    "station_max_since_7am_c",
    "station_observation_source",
    "station_observation_station_id",
    "eccc_swob_max_c",
    "weather_forecast_max_c",
    "open_meteo_max_c",
    "nws_forecast_max_c",
    "global_ensemble_max_c",
    "forecast_source_count",
    "forecast_disagreement",
    "eccc_forecast_high_c",
    "official_canadian_source_gate",
    "official_canadian_sources_available",
    "official_canadian_sources_missing",
]
SNAPSHOT_CADENCE_QUALITY_COLUMNS = [
    "snapshot_cadence",
    "snapshot_cadence_quality_state",
    "snapshot_cadence_gap_count",
    "snapshot_cadence_max_gap_seconds",
    "snapshot_cadence_last_model_age_seconds",
    "snapshot_cadence_confidence_multiplier",
    "snapshot_cadence_permission",
    "snapshot_cadence_reason",
]

COMPONENT_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "model_version",
    *RUNTIME_IDENTITY_COLUMNS,
    "component_schema_version",
    "cutoff_hour",
    "active_model_kind",
    "component_name",
    "range_label",
    "bin_kind",
    "bin_value_c",
    "bin_value_hi_c",
    "component_probability",
    "market_yes",
]

SOURCE_STATUS_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "model_version",
    "source",
    "ok",
    "status",
    "stale",
    "source_family",
    "http_status",
    "retry_after_seconds",
    "degradation_state",
    "cache_status",
    "fallback_source",
    "fetched_at",
    "age_minutes",
    "ttl_minutes",
    "latency_ms",
    "physical_validity_status",
    "physical_validity_floor",
    "physical_validity_gap",
    "impossible_feature_count",
    "impossible_features",
    "payload_hash",
    "row_count",
    "source_url",
    "error",
]

FORECAST_PAYLOAD_COLUMNS = [
    "schema_version",
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "target_date",
    "model_version",
    "source",
    "status",
    "stale",
    "source_family",
    "degradation_state",
    "cache_status",
    "fetched_at",
    "age_minutes",
    "ttl_minutes",
    "provider_issue_time",
    "provider_update_time",
    "request_started_at",
    "response_received_at",
    "first_seen_at",
    "first_seen_basis",
    "forecast_run_time",
    "ensemble_member",
    "grid_id",
    "parser_version",
    "payload_schema_version",
    "payload_hash_algorithm",
    "payload_hash",
    "payload_bytes",
    "payload_storage_scope",
    "payload_cas_kind",
    "payload_ref",
    "payload_media_type",
    "payload_encoding",
    "request_key",
    "cycle_key",
    "single_fetch_reused",
    "single_fetch_fetched",
    "single_fetch_coordination_status",
    "single_fetch_wait_timed_out",
    "single_fetch_scope",
    "coordinator_evidence_id",
    "coordinator_receipt_ref",
    "coordinator_receipt_sha256",
    "coordinator_attribution_status",
    "coordinator_network_fetch_count",
    "coordinator_payload_blob_created",
    "coordinator_payload_blob_reused",
    "coordinator_physical_bytes_written",
    "extraction_schema",
    "extraction_identity",
    "raw_payload_retained",
    "payload_blob_created",
    "payload_blob_reused",
    "physical_bytes_written",
    "logical_referenced_bytes",
    "avoided_bytes",
    "row_count",
    "source_url",
    "raw_payload_path",
    *RUNTIME_IDENTITY_COLUMNS,
    "release_id",
    "release_manifest_sha256",
    "release_pointer_sha256",
    "release_sequence",
    "release_identity_status",
    "config_identity_hash",
    "model_identity_hash",
    "provenance_complete",
    "provenance_missing_fields",
]

OBSERVATION_PAYLOAD_SOURCES = {
    "wu_history",
    "wu_current",
    "metar",
    "eccc_swob",
    "eccc_hourly",
    "nws_observations",
}

OBSERVATION_PAYLOAD_COLUMNS = [
    "schema_version",
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "model_version",
    "source",
    "status",
    "stale",
    "source_family",
    "degradation_state",
    "cache_status",
    "fetched_at",
    "age_minutes",
    "ttl_minutes",
    "provider_observed_at",
    "provider_station_id",
    "provider_update_time",
    "request_started_at",
    "response_received_at",
    "first_seen_at",
    "first_seen_basis",
    "forecast_run_time",
    "ensemble_member",
    "grid_id",
    "parser_version",
    "payload_schema_version",
    "payload_hash_algorithm",
    "payload_hash",
    "payload_bytes",
    "raw_payload_retained",
    "payload_blob_created",
    "row_count",
    "source_url",
    "raw_payload_path",
    *RUNTIME_IDENTITY_COLUMNS,
    "release_id",
    "release_manifest_sha256",
    "release_pointer_sha256",
    "release_sequence",
    "release_identity_status",
    "config_identity_hash",
    "model_identity_hash",
    "provenance_complete",
    "provenance_missing_fields",
]

SNAPSHOT_EXPLANATION_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "target_date",
    "model_version",
    "feature_schema_version",
    *RUNTIME_IDENTITY_COLUMNS,
    "explanation_schema_version",
    "model_identity_hash",
    "source_hash",
    "section",
    "item_key",
    "item_subkey",
    "value_text",
    "value_number",
    "value_bool",
    "payload_hash",
    "payload_json",
]


class SnapshotStore:
    def __init__(
        self,
        root=None,
        interval=SNAPSHOT_INTERVAL,
        event_slug=None,
        due_tolerance=SNAPSHOT_DUE_TOLERANCE,
        retain_raw_forecast_payloads=None,
        retain_raw_observation_payloads=None,
        shared_forecast_payload_cas_root=None,
        forecast_payload_physical_write_budget_bytes=None,
    ):
        self.interval = interval
        # A scheduled capture is due once at least `interval - due_tolerance` has
        # elapsed since the last write, so an on-cadence loop tick is not skipped
        # for landing a few seconds short of the boundary (item 320). Pass
        # due_tolerance=timedelta(0) for the strict zero-tolerance behaviour.
        self.due_tolerance = due_tolerance or timedelta(0)
        self.retain_raw_forecast_payloads = (
            self.raw_forecast_payload_retention_enabled()
            if retain_raw_forecast_payloads is None
            else bool(retain_raw_forecast_payloads)
        )
        self.retain_raw_observation_payloads = (
            self.raw_observation_payload_retention_enabled()
            if retain_raw_observation_payloads is None
            else bool(retain_raw_observation_payloads)
        )
        self.shared_forecast_payload_cas = SharedForecastPayloadCAS(
            shared_forecast_payload_cas_root
        )
        self.forecast_payload_physical_write_budget_bytes = (
            None
            if forecast_payload_physical_write_budget_bytes is None
            else max(0, int(forecast_payload_physical_write_budget_bytes))
        )
        self.fixed_root = root is not None
        self._set_paths(Path(root) if root is not None else None, event_slug or DEFAULT_MARKET_CONFIG.event_slug)

    def _set_paths(self, root, event_slug):
        self.event_slug = event_slug
        self.root = Path(root) if root is not None else data_path() / "snapshots" / self.event_slug
        self.long_path = self.root / "snapshots_long.csv"
        self.wide_path = self.root / "snapshots_wide.csv"
        self.jsonl_path = self.root / "snapshots.jsonl"
        self.lock_path = self.root / ".snapshot.lock"
        self.forecasts_long_path = self.root / "forecasts_long.csv"
        self.forecasts_jsonl_path = self.root / "forecasts.jsonl"
        self.features_long_path = self.root / "features_long.csv"
        self.features_jsonl_path = self.root / "features.jsonl"
        self.components_long_path = self.root / "components_long.csv"
        self.components_jsonl_path = self.root / "components.jsonl"
        self.source_status_long_path = self.root / "source_status_long.csv"
        self.source_status_jsonl_path = self.root / "source_status.jsonl"
        self.forecast_payload_dir = self.root / "forecast_payloads"
        self.forecast_payloads_long_path = self.root / "forecast_payloads_long.csv"
        self.forecast_payloads_jsonl_path = self.root / "forecast_payloads.jsonl"
        self.observation_payload_dir = self.root / "observation_payloads"
        self.observation_payloads_long_path = self.root / "observation_payloads_long.csv"
        self.observation_payloads_jsonl_path = self.root / "observation_payloads.jsonl"
        self.variant_predictions_long_path = self.root / "variant_predictions_long.csv"
        self.variant_predictions_jsonl_path = self.root / "variant_predictions.jsonl"
        self.replay_inputs_path = self.root / "replay_inputs.jsonl"
        self.snapshot_explanations_long_path = self.root / "snapshot_explanations_long.csv"
        self.snapshot_explanations_jsonl_path = self.root / "snapshot_explanations.jsonl"
        self._payload_first_seen_cache = {}

    def maybe_write(self, event, model, model_client, force=False, cadence="scheduled", trigger_context=None):
        event_config = config_from_event(event, fallback_date=getattr(model_client, "target_date", None))
        if not self.fixed_root and event_config.event_slug != self.event_slug:
            self._set_paths(None, event_config.event_slug)
        now = datetime.now(TORONTO_TZ)
        lock_handle = self.acquire_lock()
        if lock_handle is None:
            return {
                "written": False,
                "locked": True,
                "path": str(self.long_path),
                "next_due_at": self.next_due_at(),
            }
        try:
            if not force and not self.is_due(now, cadence=cadence):
                return {
                    "written": False,
                    "path": str(self.long_path),
                    "next_due_at": self.next_due_at(cadence=cadence),
                }
            runtime_guard = self.runtime_identity_guard()
            if not runtime_guard.get("ok"):
                return self.runtime_identity_blocked_result(runtime_guard, cadence=cadence)
            return self.write(
                event,
                model,
                model_client,
                now,
                cadence=cadence,
                trigger_context=trigger_context,
                runtime_guard=runtime_guard,
            )
        finally:
            self.release_lock(lock_handle)

    def write(
        self,
        event,
        model,
        model_client,
        captured_at,
        cadence="scheduled",
        trigger_context=None,
        runtime_guard=None,
    ):
        event_config = config_from_event(event)
        if not self.fixed_root and event_config.event_slug != self.event_slug:
            self._set_paths(None, event_config.event_slug)
        self.root.mkdir(parents=True, exist_ok=True)
        snapshot_id = snapshot_id_for_captured_at(captured_at)
        runtime_guard = runtime_guard or self.runtime_identity_guard()
        if not runtime_guard.get("ok"):
            raise RuntimeError(runtime_guard.get("detail") or "stale snapshot runtime identity")
        runtime_identity = runtime_guard.get("process_identity") or {}
        runtime_fields = self.runtime_identity_fields(runtime_identity, runtime_guard.get("state"))
        serving_bundle = self.verified_serving_bundle()
        _assert_snapshot_model_serving_binding(serving_bundle, model_client)
        release_lineage = serving_bundle_lineage(serving_bundle)
        trigger_context = self.normalized_trigger_context(trigger_context)
        trigger_summary = self.trigger_summary(trigger_context)
        distribution = model.get("distribution", {}) or {}
        model_version = model.get("model_version") or MODEL_VERSION
        model_identity = model.get("model_identity") or self.model_identity(model_client)
        config_identity = {
            "event_slug": self.event_slug,
            "market_id": getattr(event_config, "market_id", None),
            "polymarket_url": getattr(event_config, "polymarket_url", None),
            "target_date": (
                event_config.target_date.isoformat()
                if hasattr(getattr(event_config, "target_date", None), "isoformat")
                else getattr(event_config, "target_date", None)
            ),
        }
        feature_schema_version = (model.get("feature_vector") or {}).get("feature_schema_version")
        top_temp = model.get("top_temp")
        top_probability = distribution.get(top_temp) if top_temp is not None else None
        sources = model.get("sources", {}) or {}
        calibration_context = model.get("probability_calibration_context") or {}
        source_values = self.source_values(sources, model_client, captured_at=captured_at)
        source_health = self.source_health_summary(sources, model_client, captured_at)
        source_status_rows = self.source_status_rows(
            sources,
            model_client,
            snapshot_id,
            captured_at,
            model_version,
        )
        forecast_payload_rows = self.write_forecast_payloads(
            sources,
            snapshot_id,
            captured_at,
            model_version,
            runtime_identity=runtime_identity,
            release_lineage=release_lineage,
            model_identity=model_identity,
            config_identity=config_identity,
        )
        observation_payload_rows = self.write_observation_payloads(
            sources,
            snapshot_id,
            captured_at,
            model_version,
            runtime_identity=runtime_identity,
            release_lineage=release_lineage,
            model_identity=model_identity,
            config_identity=config_identity,
        )
        forecast_payload_storage = forecast_payload_byte_summary(
            forecast_payload_rows,
            physical_write_budget_bytes=(
                self.forecast_payload_physical_write_budget_bytes
            ),
        )
        previous_scheduled = self.last_snapshot_time(cadence="scheduled")
        cadence_gap_seconds = None
        cadence_gap_count = 0
        if previous_scheduled is not None:
            cadence_gap_seconds = (
                captured_at.astimezone(timezone.utc) - previous_scheduled.astimezone(timezone.utc)
            ).total_seconds()
            if cadence == "scheduled" and cadence_gap_seconds > SNAPSHOT_INTERVAL.total_seconds() * 1.5:
                cadence_gap_count = 1
        cadence_quality = snapshot_cadence_quality({
            "snapshot_cadence": cadence,
            "snapshot_cadence_gap_count": cadence_gap_count,
            "snapshot_cadence_max_gap_seconds": cadence_gap_seconds if cadence_gap_count else None,
            "snapshot_cadence_last_model_age_seconds": 0.0,
        })

        bins = model_client.market_bins(event)
        long_rows = []
        for bin_data in bins:
            value = bin_data.get("value")
            value_hi = bin_data.get("value_hi", value)
            model_probability = self.model_bin_probability(
                model_client,
                distribution,
                bin_data,
                calibration_context=calibration_context,
            )
            market_yes = bin_data.get("market_yes")
            edge = (
                model_probability - market_yes
                if model_probability is not None and market_yes is not None
                else None
            )
            long_rows.append({
                "snapshot_id": snapshot_id,
                "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
                "captured_at_local": captured_at.isoformat(),
                "event_slug": self.event_slug,
                "event_updated_at": event.get("updatedAt"),
                "model_version": model_version,
                "feature_schema_version": feature_schema_version,
                **runtime_fields,
                "snapshot_cadence": cadence,
                **cadence_quality,
                **trigger_summary,
                "top_temp_c": top_temp,
                "top_probability": top_probability,
                "range_label": bin_data.get("label"),
                "polymarket_market_id": bin_data.get("polymarket_market_id"),
                "condition_id": bin_data.get("condition_id"),
                "clob_token_ids": bin_data.get("clob_token_ids"),
                "clob_yes_token_id": bin_data.get("clob_yes_token_id"),
                "clob_no_token_id": bin_data.get("clob_no_token_id"),
                "enable_order_book": bin_data.get("enable_order_book"),
                "bin_kind": bin_data.get("kind"),
                "bin_value_c": value,
                "bin_value_hi_c": value_hi,
                "model_probability": model_probability,
                "market_yes": market_yes,
                "market_no": bin_data.get("market_no"),
                "edge": edge,
                "best_bid": bin_data.get("best_bid"),
                "best_ask": bin_data.get("best_ask"),
                "last_trade_price": bin_data.get("last_trade_price"),
                "volume": bin_data.get("volume"),
                "liquidity": bin_data.get("liquidity"),
                "market_status": bin_data.get("status"),
                **source_values,
            })

        snapshot_self_check = self.check_snapshot_probabilities(
            distribution,
            long_rows,
            model_client,
            calibration_context=calibration_context,
        )
        replay_input_payload = self.build_replay_input_payload(
            snapshot_id,
            captured_at,
            model,
            model_client,
            model_version,
            model_identity,
            runtime_identity,
            runtime_guard,
            cadence=cadence,
            cadence_quality=cadence_quality,
            trigger_context=trigger_context,
            release_lineage=release_lineage,
        )
        captured_input_hash = (
            str(replay_input_payload.get("captured_input_hash") or "")
            if replay_input_payload
            else ""
        )
        variant_prediction_rows = []
        variant_prediction_error = None
        try:
            shadow_capture_bundle = self.verified_shadow_capture_bundle()
            variant_capture_bundle = shadow_capture_bundle or serving_bundle
            if (
                shadow_capture_bundle is not None
                and shadow_capture_bundle.status != STATUS_SHADOW_BOUND
            ):
                raise ReleaseServingBindingError(
                    "shadow capture loader returned a non-shadow serving status"
                )
            variant_prediction_rows = build_live_variant_prediction_rows(
                snapshot_id=snapshot_id,
                captured_at=captured_at,
                event=event,
                model=model,
                model_client=model_client,
                band_rows=long_rows,
                event_slug=self.event_slug,
                market_id=event_config.market_id,
                target_date=event_config.target_date,
                serving_model_version=model_version,
                release_lineage=release_lineage,
                captured_input_hash=captured_input_hash,
                runtime_fields=runtime_fields,
                snapshot_cadence=cadence,
                cadence_quality=cadence_quality,
                trigger_summary=trigger_summary,
                serving_bundle=variant_capture_bundle,
            )
        except Exception as exc:  # noqa: BLE001 - variant tape must not block serving snapshots
            variant_prediction_error = f"{type(exc).__name__}: {exc}"
        self.append_csv(self.long_path, LONG_COLUMNS, long_rows)
        self.append_csv(
            self.wide_path,
            self.wide_columns(long_rows),
            [self.wide_row(long_rows)],
        )
        self.append_jsonl(self.jsonl_path, {
            "snapshot_id": snapshot_id,
            "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
            "captured_at_local": captured_at.isoformat(),
            "event_slug": self.event_slug,
            "event_updated_at": event.get("updatedAt"),
            "model_version": model_version,
            "runtime_identity": runtime_identity,
            "runtime_guard": runtime_guard,
            "model_identity": model_identity,
            "snapshot_cadence": cadence,
            "snapshot_cadence_quality": cadence_quality,
            "trigger_context": trigger_context,
            "top_temp_c": top_temp,
            "top_probability": top_probability,
            "snapshot_self_check": snapshot_self_check,
            "distribution": distribution,
            "distribution_components": model.get("distribution_components"),
            "source_values": source_values,
            "source_status": source_status_rows,
            "source_health": source_health,
            "forecast_payloads": forecast_payload_rows,
            "forecast_payload_storage": forecast_payload_storage,
            "observation_payloads": observation_payload_rows,
            "feature_schema_version": feature_schema_version,
            "feature_vector": model.get("feature_vector"),
            "variant_prediction_rows": len(variant_prediction_rows),
            "variant_prediction_error": variant_prediction_error,
            "bands": long_rows,
        })

        feature_vector = model.get("feature_vector")
        if feature_vector:
            feature_row = audit_row(
                {
                    "snapshot_id": snapshot_id,
                    "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
                    "captured_at_local": captured_at.isoformat(),
                    "event_slug": self.event_slug,
                    "model_version": model_version,
                },
                feature_vector,
            )
            self.append_csv(self.features_long_path, FEATURE_AUDIT_COLUMNS, [feature_row])
            self.append_jsonl(self.features_jsonl_path, feature_row)

        component_rows = self.component_rows(
            model.get("distribution_components"),
            bins,
            snapshot_id,
            captured_at,
            model_version,
            runtime_fields,
        )
        if component_rows:
            self.append_csv(self.components_long_path, COMPONENT_COLUMNS, component_rows)
            for row in component_rows:
                self.append_jsonl(self.components_jsonl_path, row)

        explanation_payload, explanation_rows = self.snapshot_explanation_payload(
            snapshot_id=snapshot_id,
            captured_at=captured_at,
            model=model,
            model_client=model_client,
            event_config=event_config,
            model_version=model_version,
            model_identity=model_identity,
            runtime_identity=runtime_identity,
            runtime_fields=runtime_fields,
            feature_schema_version=feature_schema_version,
        )
        if explanation_payload:
            self.append_jsonl(self.snapshot_explanations_jsonl_path, explanation_payload)
            if explanation_rows:
                self.append_csv(
                    self.snapshot_explanations_long_path,
                    SNAPSHOT_EXPLANATION_COLUMNS,
                    explanation_rows,
                )

        forecast_rows = build_forecast_rows(
            sources,
            model_client,
            captured_at,
            snapshot_id,
            self.event_slug,
            archive_path=self.forecasts_long_path,
            target_date=getattr(model_client, "target_date", event_config.target_date),
        )

        if forecast_rows:
            append_forecast_rows(self.forecasts_long_path, FORECAST_COLUMNS, forecast_rows)
            self.append_jsonl(self.forecasts_jsonl_path, {
                "snapshot_id": snapshot_id,
                "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
                "captured_at_local": captured_at.isoformat(),
                "forecasts": forecast_rows,
            })

        if source_status_rows:
            self.append_csv(self.source_status_long_path, SOURCE_STATUS_COLUMNS, source_status_rows)
            for row in source_status_rows:
                self.append_jsonl(self.source_status_jsonl_path, row)

        # The replay payload is built and hashed before variant inference, then
        # persisted first so no served row can reference an absent captured
        # input.  Both artifacts receive the exact same fail-closed lineage
        # status and input hash; release_id stays blank until serving loaders
        # are demonstrably bound to the verified manifest.
        if replay_input_payload:
            self.append_jsonl(self.replay_inputs_path, replay_input_payload)

        if variant_prediction_rows:
            self.append_csv(
                self.variant_predictions_long_path,
                LIVE_VARIANT_PREDICTION_COLUMNS,
                variant_prediction_rows,
            )
            for row in variant_prediction_rows:
                self.append_jsonl(self.variant_predictions_jsonl_path, row)

        return {
            "written": True,
            "snapshot_id": snapshot_id,
            "snapshot_cadence": cadence,
            "trigger_context": trigger_context,
            "bands": len(long_rows),
            "path": str(self.long_path),
            "wide_path": str(self.wide_path),
            "jsonl_path": str(self.jsonl_path),
            "features_path": str(self.features_long_path),
            "components_path": str(self.components_long_path),
            "snapshot_explanation_rows": len(explanation_rows),
            "snapshot_explanations_path": str(self.snapshot_explanations_long_path),
            "snapshot_explanations_jsonl_path": str(self.snapshot_explanations_jsonl_path),
            "source_status_rows": len(source_status_rows),
            "source_status_path": str(self.source_status_long_path),
            "forecast_payload_rows": len(forecast_payload_rows),
            "forecast_payloads_path": str(self.forecast_payloads_long_path),
            "forecast_payload_storage": forecast_payload_storage,
            "observation_payload_rows": len(observation_payload_rows),
            "observation_payloads_path": str(self.observation_payloads_long_path),
            "observation_payloads_jsonl_path": str(self.observation_payloads_jsonl_path),
            "variant_prediction_rows": len(variant_prediction_rows),
            "variant_predictions_path": str(self.variant_predictions_long_path),
            "variant_predictions_jsonl_path": str(self.variant_predictions_jsonl_path),
            "variant_prediction_error": variant_prediction_error,
            "release_id": release_lineage.get("release_id") or "",
            "release_identity_status": release_lineage.get("release_identity_status"),
            "base_model_release_bound": bool(
                release_lineage.get("base_model_release_bound", False)
            ),
            "base_model_binding_reason": release_lineage.get("base_model_binding_reason") or "",
            "captured_input_hash": captured_input_hash,
            "next_due_at": self.next_due_at(
                captured_at if cadence == "scheduled" else None,
                cadence="scheduled",
            ),
            "event_slug": self.event_slug,
            "model_version": model_version,
            "runtime_identity": runtime_identity,
            "runtime_guard": runtime_guard,
            "snapshot_self_check": snapshot_self_check,
            "model_identity": model_identity,
            "top_temp_c": top_temp,
            "top_probability": top_probability,
            "distribution": distribution,
        }

    def is_due(self, now, cadence="scheduled"):
        last = self.last_snapshot_time(cadence="scheduled" if cadence == "scheduled" else None)
        return last is None or now - last >= self.interval - self.due_tolerance

    def last_snapshot_time(self, cadence=None):
        if not self.long_path.exists():
            return None
        last_time = None
        with self.long_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if cadence == "scheduled":
                    row_cadence = row.get("snapshot_cadence") or "scheduled"
                    if row_cadence != "scheduled":
                        continue
                value = row.get("captured_at_local")
                if value:
                    try:
                        last_time = datetime.fromisoformat(value)
                    except ValueError:
                        continue
        return last_time

    def next_due_at(self, from_time=None, cadence="scheduled"):
        base = from_time or self.last_snapshot_time(cadence="scheduled" if cadence == "scheduled" else None)
        if base is None:
            return None
        # Consistent with is_due: the next scheduled capture becomes due one
        # interval minus the due tolerance after the last write (item 320).
        return (base + self.interval - self.due_tolerance).isoformat()

    def source_values(self, sources, model_client, captured_at=None):
        history = model_client.source_data(sources, "wu_history")
        current = model_client.source_data(sources, "wu_current")
        station_method = getattr(model_client, "station_observation_data", None)
        station = (
            station_method(sources)
            if callable(station_method)
            else model_client.source_data(sources, "station_observations")
        )
        eccc = model_client.source_data(sources, "eccc_swob")
        weather_forecast = model_client.source_data(sources, "weather_forecast")
        open_meteo = model_client.source_data(sources, "open_meteo")
        nws_hourly = model_client.source_data(sources, "nws_hourly")
        global_ensemble = model_client.source_data(sources, "global_ensemble")
        eccc_city = model_client.source_data(sources, "eccc_citypage")
        guidance_floor = None
        physical_floor_method = getattr(model_client, "guidance_physical_floor", None)
        if callable(physical_floor_method):
            guidance_floor = physical_floor_method(sources=sources)
        forecast_ensemble = model_client.forecast_ensemble_metrics(
            open_meteo,
            weather_forecast,
            eccc_city,
            nws_hourly=nws_hourly,
            global_ensemble=global_ensemble,
            observed_floor_native=guidance_floor,
        )
        return {
            "wu_history_high_c": row_max_native(history),
            "wu_current_c": row_temp_native(current),
            "wu_max_since_7am_c": row_max_since_7am_native(current),
            "station_current_c": row_temp_native(station),
            "station_max_since_7am_c": row_max_since_7am_native(station),
            "station_observation_source": station.get("station_observation_source") or station.get("source"),
            "station_observation_station_id": station.get("station_id"),
            "eccc_swob_max_c": row_same_day_max_native(eccc),
            "weather_forecast_max_c": model_client.max_row_temp(
                weather_forecast.get("rows")
            ),
            "open_meteo_max_c": model_client.max_row_temp(open_meteo.get("rows")),
            "nws_forecast_max_c": model_client.max_row_temp(nws_hourly.get("rows")),
            "global_ensemble_max_c": model_client.max_row_temp(global_ensemble.get("rows")),
            "forecast_source_count": forecast_ensemble.get("forecast_source_count"),
            "forecast_disagreement": forecast_ensemble.get("forecast_disagreement"),
            "eccc_forecast_high_c": row_forecast_high_native(eccc_city),
            **self.official_canadian_source_fields(sources, model_client, captured_at),
        }

    def source_health_summary(self, sources, model_client, captured_at=None):
        method = getattr(model_client, "toronto_official_source_health", None)
        if not callable(method):
            return {}
        try:
            return method(sources, now=captured_at)
        except TypeError:
            return method(sources)

    def official_canadian_source_fields(self, sources, model_client, captured_at=None):
        health = self.source_health_summary(sources, model_client, captured_at)
        if not health or health.get("status") == "NOT_APPLICABLE":
            return {
                "official_canadian_source_gate": None,
                "official_canadian_sources_available": None,
                "official_canadian_sources_missing": None,
            }
        return {
            "official_canadian_source_gate": health.get("status"),
            "official_canadian_sources_available": health.get("official_sources_available"),
            "official_canadian_sources_missing": health.get("official_sources_missing"),
        }

    def source_status_rows(self, sources, model_client, snapshot_id, captured_at, model_version):
        rows = []
        captured_utc = captured_at.astimezone(timezone.utc).isoformat()
        captured_local = captured_at.isoformat()
        physical_states = {}
        physical_state_method = getattr(model_client, "guidance_physical_states", None)
        if callable(physical_state_method):
            try:
                physical_states = physical_state_method(sources)
            except Exception:
                physical_states = {}
        for source, item in sorted((sources or {}).items()):
            item = item or {}
            data = item.get("data")
            status = self.source_status(item)
            ttl_minutes = item.get("ttl_minutes")
            if ttl_minutes is None and hasattr(model_client, "source_cache_ttl_minutes"):
                ttl_minutes = model_client.source_cache_ttl_minutes(source)
            if ttl_minutes is None:
                ttl_minutes = self.source_ttl_minutes(source)
            age_minutes = item.get("cache_age_minutes")
            if age_minutes is None:
                age_minutes = self.source_age_minutes(item.get("fetched_at"), captured_at, model_client)
            physical_state = physical_states.get(source) or {}
            rows.append({
                "snapshot_id": snapshot_id,
                "captured_at_utc": captured_utc,
                "captured_at_local": captured_local,
                "event_slug": self.event_slug,
                "model_version": model_version,
                "source": source,
                "ok": bool(item.get("ok")),
                "status": status,
                "stale": bool(item.get("stale")),
                "source_family": self.source_family(source, item),
                "http_status": item.get("http_status"),
                "retry_after_seconds": item.get("retry_after_seconds"),
                "degradation_state": self.source_degradation_state(status, item),
                "cache_status": self.source_cache_status(status, item),
                "fallback_source": item.get("fallback_source"),
                "fetched_at": item.get("fetched_at"),
                "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
                "ttl_minutes": ttl_minutes,
                "latency_ms": item.get("latency_ms"),
                "physical_validity_status": physical_state.get("physical_validity_status"),
                "physical_validity_floor": physical_state.get("observed_floor"),
                "physical_validity_gap": physical_state.get("floor_gap"),
                "impossible_feature_count": physical_state.get("impossible_feature_count"),
                "impossible_features": ",".join(physical_state.get("impossible_features") or []),
                "payload_hash": self.payload_hash(data),
                "row_count": self.source_row_count(data),
                "source_url": redact_sensitive_url_parts(data.get("url")) if isinstance(data, dict) else None,
                "error": redact_sensitive_url_parts(item.get("error")),
            })
        return rows

    def source_status(self, item):
        status = item.get("status")
        if status is not None:
            return status
        if item.get("ok") and not item.get("stale"):
            return "fresh"
        if item.get("stale"):
            return "stale_cache"
        if item.get("http_status") == 429:
            return "rate_limited"
        return "failed"

    def source_family(self, source, item=None):
        item = item or {}
        if item.get("source_family"):
            return item.get("source_family")
        if source in OPEN_METEO_SOURCE_FAMILY:
            return "open_meteo"
        return source

    def source_degradation_state(self, status, item):
        if status in {"expected_current_day_unavailable", "expected_unavailable"}:
            return status
        if item.get("degradation_state") in {
            "expected_current_day_unavailable",
            "expected_unavailable",
            "settlement_source_auth_failure",
        }:
            return item.get("degradation_state")
        if status == "settlement_source_auth_failure":
            return status
        if status == "rate_limited_cache":
            return "rate_limited_fallback"
        if status == "stale_cache":
            return "stale_fallback"
        if status == "rate_limited":
            return "rate_limited"
        if status in {"failed", "error", "missing"} or not item.get("ok"):
            return "failed"
        if item.get("degradation_state"):
            return item.get("degradation_state")
        return "healthy"

    def source_cache_status(self, status, item):
        if item.get("cache_status"):
            return item.get("cache_status")
        if status == "fresh_cache":
            return "fresh_cache"
        if status in {"stale_cache", "rate_limited_cache"}:
            return "fallback"
        return "live" if item.get("ok") else "miss"

    def source_ttl_minutes(self, source):
        return SOURCE_CACHE_TTL_MINUTES.get(source, LIVE_CACHE_MAX_AGE_MINUTES)

    def source_age_minutes(self, fetched_at, captured_at, model_client):
        if not fetched_at:
            return None
        try:
            parsed = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            tz = getattr(getattr(model_client, "spec", None), "tz", captured_at.tzinfo)
            parsed = parsed.replace(tzinfo=tz)
        return max(0.0, (captured_at.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60.0)

    def payload_hash(self, payload):
        digest, _ = _json_digest_and_size(
            payload,
            "sha1",
            sort_keys=True,
            default=str,
        )
        return digest

    @staticmethod
    def canonical_raw_payload(payload):
        """Return the exact canonical bytes addressed by raw-evidence hashes."""

        return b"".join(
            _iter_json_byte_chunks(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            )
        )

    @staticmethod
    def canonical_raw_payload_digest(payload):
        """Hash and count canonical raw evidence without joining its bytes."""

        return _json_digest_and_size(
            payload,
            "sha256",
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def content_addressed_file_digest(path):
        """Hash a stored payload without materializing the blob in memory.

        Content-addressed payload files have one durability newline which is
        not part of the addressed bytes.  Retaining a one-byte tail lets us
        preserve that contract while keeping validation memory bounded.
        """

        digest = hashlib.sha256()
        pending = b""
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                data = pending + chunk
                if len(data) <= 1:
                    pending = data
                    continue
                digest.update(data[:-1])
                pending = data[-1:]
        if pending != b"\n":
            digest.update(pending)
        return digest.hexdigest()

    def write_content_addressed_payload(
        self,
        directory,
        payload=None,
        *,
        canonical_bytes=None,
        payload_hash=None,
    ):
        """Stream and atomically publish one immutable SHA-256 JSON blob.

        The complete, fsynced blob is staged before a hard link makes its
        digest path visible. Concurrent writers may reuse that path, but no
        reader can observe a partially serialized evidence file.
        """

        if canonical_bytes is None and payload is None:
            raise ValueError("payload or canonical_bytes is required")

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        staging = directory / (
            f".payload-staging-{os.getpid()}-{uuid.uuid4().hex}.json"
        )
        digest_state = hashlib.sha256()
        payload_bytes = 0
        created = False
        try:
            with staging.open("xb") as handle:
                if canonical_bytes is None:
                    byte_chunks = _iter_json_byte_chunks(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        default=str,
                    )
                else:
                    raw = (
                        canonical_bytes
                        if isinstance(canonical_bytes, bytes)
                        else bytes(canonical_bytes)
                    )
                    view = memoryview(raw)
                    byte_chunks = (
                        view[offset : offset + JSON_STREAM_BYTE_CHUNK_BYTES]
                        for offset in range(
                            0,
                            len(view),
                            JSON_STREAM_BYTE_CHUNK_BYTES,
                        )
                    )
                for byte_chunk in byte_chunks:
                    digest_state.update(byte_chunk)
                    payload_bytes += len(byte_chunk)
                    handle.write(byte_chunk)
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())

            digest = digest_state.hexdigest()
            if payload_hash is not None and str(payload_hash) != digest:
                raise RuntimeError(
                    "precomputed content-addressed payload hash mismatch"
                )
            path = directory / "sha256" / digest[:2] / f"{digest}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(staging, path)
                created = True
            except FileExistsError:
                created = False
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    created = False
                else:
                    raise

            if path.is_symlink() or not path.is_file():
                raise RuntimeError(
                    f"content-addressed payload is not a regular file: {path}"
                )
            if path.stat().st_size != payload_bytes + 1:
                raise RuntimeError(
                    f"content-addressed payload byte-count mismatch: {path}"
                )
            if self.content_addressed_file_digest(path) != digest:
                raise RuntimeError(
                    f"content-addressed payload hash mismatch: {path}"
                )
            return path, digest, payload_bytes, created
        finally:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def provenance_value(item, data, payload, *keys):
        containers = [item, data]
        if isinstance(payload, dict):
            containers.append(payload)
            if isinstance(payload.get("provenance"), dict):
                containers.append(payload["provenance"])
        for key in keys:
            for container in containers:
                if not isinstance(container, dict):
                    continue
                value = container.get(key)
                if value not in (None, "", [], {}):
                    if isinstance(value, (dict, list, tuple)):
                        return json.dumps(value, sort_keys=True, default=str)
                    return value
        return None

    def payload_first_seen(self, kind, payload_hash, candidate, captured_utc):
        cache = self._payload_first_seen_cache.get(kind)
        if cache is None:
            cache = {}
            manifest_path = (
                self.forecast_payloads_jsonl_path
                if kind == "forecast"
                else self.observation_payloads_jsonl_path
            )
            if manifest_path.exists():
                for row in self.read_jsonl(manifest_path):
                    digest = row.get("payload_hash")
                    first_seen = row.get("first_seen_at") or row.get("captured_at_utc")
                    if digest and first_seen and digest not in cache:
                        cache[digest] = (
                            first_seen,
                            row.get("first_seen_basis") or "existing_manifest",
                        )
            self._payload_first_seen_cache[kind] = cache
        if payload_hash not in cache:
            cache[payload_hash] = (
                candidate or captured_utc,
                "provider_first_seen" if candidate else "snapshot_capture",
            )
        return cache[payload_hash]

    def payload_provenance(
        self,
        *,
        kind,
        item,
        data,
        payload,
        payload_hash,
        captured_utc,
        provider_time,
        runtime_identity=None,
        release_lineage=None,
        model_identity=None,
        config_identity=None,
    ):
        request_started_at = self.provenance_value(
            item,
            data,
            payload,
            "request_started_at",
            "request_start_time",
            "requested_at",
        )
        response_received_at = self.provenance_value(
            item,
            data,
            payload,
            "response_received_at",
            "response_received_time",
            "received_at",
            "fetched_at",
        )
        explicit_first_seen = self.provenance_value(
            item,
            data,
            payload,
            "first_seen_at",
            "available_at",
            "availability_time",
        )
        first_seen_at, first_seen_basis = self.payload_first_seen(
            kind,
            payload_hash,
            explicit_first_seen,
            captured_utc,
        )
        forecast_run_time = self.provenance_value(
            item,
            data,
            payload,
            "forecast_run_time",
            "model_run_time",
            "run_time",
            "cycle_time",
            "provider_issue_time",
            "issued_at",
        )
        parser_version = self.provenance_value(
            item,
            data,
            payload,
            "parser_version",
            "decoder_version",
            "parser",
        )
        payload_schema_version = self.provenance_value(
            item,
            data,
            payload,
            "payload_schema_version",
            "schema_version",
            "api_version",
        )
        runtime_fields = self.runtime_identity_fields(runtime_identity)
        release_lineage = release_lineage or {}
        model_identity = model_identity or {}
        config_identity = config_identity or {}
        model_identity_hash = model_identity.get("identity_hash") or (
            canonical_payload_sha256(model_identity) if model_identity else ""
        )
        config_identity_hash = (
            canonical_payload_sha256(config_identity) if config_identity else ""
        )
        required = {
            "request_started_at": request_started_at,
            "response_received_at": response_received_at,
            "first_seen_at": first_seen_at,
            "provider_time": provider_time,
            "runtime_identity": runtime_identity,
            "release_identity": release_lineage.get("release_id"),
            "config_identity": config_identity_hash,
            "parser_version": parser_version,
            "payload_schema_version": payload_schema_version,
        }
        missing = sorted(key for key, value in required.items() if value in (None, "", {}, []))
        return {
            "request_started_at": request_started_at,
            "response_received_at": response_received_at,
            "first_seen_at": first_seen_at,
            "first_seen_basis": first_seen_basis,
            "forecast_run_time": forecast_run_time,
            "ensemble_member": self.provenance_value(
                item, data, payload, "ensemble_member", "member", "model_member"
            ),
            "grid_id": self.provenance_value(
                item, data, payload, "grid_id", "grid_name", "gridpoint", "grid_resolution"
            ),
            "parser_version": parser_version,
            "payload_schema_version": payload_schema_version,
            "payload_hash_algorithm": "sha256-canonical-json",
            **runtime_fields,
            "release_id": release_lineage.get("release_id") or "",
            "release_manifest_sha256": release_lineage.get("release_manifest_sha256") or "",
            "release_pointer_sha256": release_lineage.get("release_pointer_sha256") or "",
            "release_sequence": release_lineage.get("release_sequence"),
            "release_identity_status": release_lineage.get("release_identity_status") or "unavailable",
            "config_identity_hash": config_identity_hash,
            "model_identity_hash": model_identity_hash,
            "provenance_complete": not missing,
            "provenance_missing_fields": json.dumps(missing, separators=(",", ":")),
        }

    def source_row_count(self, data):
        if data is None:
            return 0
        if isinstance(data, list):
            return len(data)
        if not isinstance(data, dict):
            return 1
        for key in ("rows", "observations", "periods", "forecasts", "history"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
        if data.get("available") is False:
            return 0
        return 1 if data else 0

    def write_forecast_payloads(
        self,
        sources,
        snapshot_id,
        captured_at,
        model_version,
        *,
        runtime_identity=None,
        release_lineage=None,
        model_identity=None,
        config_identity=None,
    ):
        rows = []
        captured_utc = captured_at.astimezone(timezone.utc).isoformat()
        captured_local = captured_at.isoformat()
        for source, item in sorted((sources or {}).items()):
            # Observation payloads have their own manifest/blob family. Do not
            # duplicate the same bytes into the forecast blob tree.
            if source in OBSERVATION_PAYLOAD_SOURCES:
                continue
            item = item or {}
            data = item.get("data") or {}
            if not isinstance(data, dict) or "raw_payload" not in data:
                continue
            payload = data.get("raw_payload")
            if payload is None:
                continue
            status = self.source_status(item)
            age_minutes = item.get("cache_age_minutes")
            if age_minutes is None:
                age_minutes = self.source_age_minutes(item.get("fetched_at"), captured_at, None)
            ttl_minutes = item.get("ttl_minutes")
            if ttl_minutes is None:
                ttl_minutes = self.source_ttl_minutes(source)
            attested = parse_market_invariant_attestation(source, payload)
            if attested is not None:
                raw_bytes = attested["payload_bytes"]
                payload_hash = hashlib.sha256(raw_bytes).hexdigest()
                payload_bytes = len(raw_bytes)
                payload_storage_scope = SHARED_FORECAST_PAYLOAD_SCOPE
                payload_cas_kind = SHARED_FORECAST_PAYLOAD_CAS_KIND
                payload_media_type = attested["media_type"]
                payload_encoding = attested["encoding"]
                request_key = attested["request_key"]
                cycle_key = attested["cycle_key"]
                extraction_schema = attested["extraction_schema"]
                extraction_identity = attested["extraction_identity"]
                config_target_date = str(
                    (config_identity or {}).get("target_date") or ""
                ).strip()
                if (
                    config_target_date
                    and extraction_identity.get("target_date") != config_target_date
                ):
                    raise ForecastPayloadCASIntegrityError(
                        "forecast extraction target_date does not match market configuration"
                    )
            else:
                raw_bytes = None
                payload_storage_scope = LOCAL_FORECAST_PAYLOAD_SCOPE
                payload_cas_kind = LOCAL_FORECAST_PAYLOAD_CAS_KIND
                payload_media_type = "application/json"
                payload_encoding = "utf-8"
                request_key = ""
                cycle_key = ""
                extraction_schema = ""
                extraction_identity = {}
            raw_payload_path = ""
            payload_blob_created = False
            payload_blob_reused = False
            physical_bytes_written = 0
            avoided_bytes = 0
            payload_ref = ""
            if self.retain_raw_forecast_payloads:
                if attested is not None:
                    stored = self.shared_forecast_payload_cas.put(
                        raw_bytes,
                        expected_digest=payload_hash,
                    )
                    raw_payload_path = stored["path"]
                    payload_ref = stored["payload_ref"]
                    accounting = fanout_prepublish_accounting(
                        stored,
                        attested.get("single_fetch"),
                    )
                    payload_blob_created = accounting["payload_blob_created"]
                    payload_blob_reused = accounting["payload_blob_reused"]
                    physical_bytes_written = accounting["physical_bytes_written"]
                    avoided_bytes = accounting["avoided_bytes"]
                else:
                    payload_path, stored_hash, payload_bytes, payload_blob_created = self.write_content_addressed_payload(
                        self.forecast_payload_dir,
                        payload=payload,
                    )
                    payload_hash = stored_hash
                    raw_payload_path = str(payload_path)
                    payload_ref = (
                        f"sha256/{payload_hash[:2]}/{payload_hash}.json"
                    )
                    payload_blob_reused = not payload_blob_created
                    physical_bytes_written = payload_bytes if payload_blob_created else 0
                    avoided_bytes = 0 if payload_blob_created else payload_bytes
            elif attested is None:
                payload_hash, payload_bytes = self.canonical_raw_payload_digest(payload)
            logical_referenced_bytes = payload_bytes
            provider_issue_time = data.get("provider_issue_time") or data.get("issued_at")
            provider_update_time = (
                data.get("provider_update_time")
                or data.get("last_updated")
                or data.get("valid_time_utc")
            )
            provenance = self.payload_provenance(
                kind="forecast",
                item=item,
                data=data,
                payload=payload,
                payload_hash=payload_hash,
                captured_utc=captured_utc,
                provider_time=provider_issue_time or provider_update_time,
                runtime_identity=runtime_identity,
                release_lineage=release_lineage,
                model_identity=model_identity,
                config_identity=config_identity,
            )
            source_fetched_at = item.get("fetched_at")
            if attested is not None:
                single_fetch = attested.get("single_fetch") or {}
                source_fetched_at = (
                    single_fetch.get("fetched_at")
                    or data.get("fetched_at")
                    or source_fetched_at
                )
                for field in ("request_started_at", "response_received_at"):
                    if single_fetch.get(field):
                        provenance[field] = single_fetch[field]
                if item.get("cache_age_minutes") is None:
                    age_minutes = self.source_age_minutes(
                        source_fetched_at,
                        captured_at,
                        None,
                    )
            row = {
                "schema_version": FORECAST_PAYLOAD_SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "captured_at_utc": captured_utc,
                "captured_at_local": captured_local,
                "event_slug": self.event_slug,
                "market_id": (config_identity or {}).get("market_id"),
                "target_date": (
                    extraction_identity.get("target_date")
                    or (config_identity or {}).get("target_date")
                ),
                "model_version": model_version,
                "source": source,
                "status": status,
                "stale": bool(item.get("stale")),
                "source_family": self.source_family(source, item),
                "degradation_state": self.source_degradation_state(status, item),
                "cache_status": self.source_cache_status(status, item),
                "fetched_at": source_fetched_at,
                "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
                "ttl_minutes": ttl_minutes,
                "provider_issue_time": provider_issue_time,
                "provider_update_time": provider_update_time,
                **provenance,
                "payload_hash_algorithm": (
                    stored["payload_hash_algorithm"]
                    if attested is not None and self.retain_raw_forecast_payloads
                    else (
                        RAW_BYTES_HASH_ALGORITHM
                        if attested is not None
                        else CANONICAL_JSON_HASH_ALGORITHM
                    )
                ),
                "payload_hash": payload_hash,
                "payload_bytes": payload_bytes,
                "payload_storage_scope": payload_storage_scope,
                "payload_cas_kind": payload_cas_kind,
                "payload_ref": payload_ref,
                "payload_media_type": payload_media_type,
                "payload_encoding": payload_encoding,
                "request_key": request_key,
                "cycle_key": cycle_key,
                "single_fetch_reused": bool(
                    attested.get("single_fetch_reused")
                    if attested is not None
                    else (data.get("single_fetch_fanout") or {}).get("reused")
                ),
                "single_fetch_fetched": bool(
                    (attested.get("single_fetch") or {}).get("fetched")
                    if attested is not None
                    else False
                ),
                "single_fetch_coordination_status": (
                    (attested.get("single_fetch") or {}).get(
                        "coordination_status"
                    )
                    if attested is not None
                    else None
                ),
                "single_fetch_wait_timed_out": bool(
                    (attested.get("single_fetch") or {}).get("wait_timed_out")
                    if attested is not None
                    else False
                ),
                "single_fetch_scope": (
                    (attested.get("single_fetch") or {}).get(
                        "capture_pass_scope"
                    )
                    if attested is not None
                    else None
                ),
                "coordinator_evidence_id": (
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_evidence_id"
                    )
                    if attested is not None
                    else None
                ),
                "coordinator_receipt_ref": (
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_receipt_ref"
                    )
                    if attested is not None
                    else None
                ),
                "coordinator_receipt_sha256": (
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_receipt_sha256"
                    )
                    if attested is not None
                    else None
                ),
                "coordinator_attribution_status": (
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_attribution_status"
                    )
                    if attested is not None
                    else "not_applicable"
                ),
                "coordinator_network_fetch_count": (
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_network_fetch_count"
                    )
                    if attested is not None
                    else 0
                ),
                "coordinator_payload_blob_created": bool(
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_payload_blob_created"
                    )
                    if attested is not None
                    else False
                ),
                "coordinator_payload_blob_reused": bool(
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_payload_blob_reused"
                    )
                    if attested is not None
                    else False
                ),
                "coordinator_physical_bytes_written": (
                    (attested.get("single_fetch") or {}).get(
                        "coordinator_physical_bytes_written"
                    )
                    if attested is not None
                    else 0
                ),
                "extraction_schema": extraction_schema,
                "extraction_identity": json.dumps(
                    extraction_identity,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "raw_payload_retained": bool(raw_payload_path),
                "payload_blob_created": payload_blob_created,
                "payload_blob_reused": payload_blob_reused,
                "physical_bytes_written": physical_bytes_written,
                "logical_referenced_bytes": logical_referenced_bytes,
                "avoided_bytes": avoided_bytes,
                "row_count": self.source_row_count(data),
                "source_url": redact_sensitive_url_parts(data.get("url") or data.get("source_url")),
                "raw_payload_path": raw_payload_path,
            }
            if attested is not None:
                validate_nbm_shared_manifest_identity(row)
            rows.append(row)
        if rows:
            self.append_csv(self.forecast_payloads_long_path, FORECAST_PAYLOAD_COLUMNS, rows)
            for row in rows:
                self.append_jsonl(self.forecast_payloads_jsonl_path, row, durable=True)
        return rows

    def write_observation_payloads(
        self,
        sources,
        snapshot_id,
        captured_at,
        model_version,
        *,
        runtime_identity=None,
        release_lineage=None,
        model_identity=None,
        config_identity=None,
    ):
        rows = []
        captured_utc = captured_at.astimezone(timezone.utc).isoformat()
        captured_local = captured_at.isoformat()
        for source, item in sorted((sources or {}).items()):
            if source not in OBSERVATION_PAYLOAD_SOURCES:
                continue
            item = item or {}
            data = item.get("data") or {}
            if not isinstance(data, dict) or "raw_payload" not in data:
                continue
            payload = data.get("raw_payload")
            if payload is None:
                continue
            status = self.source_status(item)
            age_minutes = item.get("cache_age_minutes")
            if age_minutes is None:
                age_minutes = self.source_age_minutes(item.get("fetched_at"), captured_at, None)
            ttl_minutes = item.get("ttl_minutes")
            if ttl_minutes is None:
                ttl_minutes = self.source_ttl_minutes(source)
            raw_payload_path = ""
            payload_blob_created = False
            if self.retain_raw_observation_payloads:
                payload_path, payload_hash, payload_bytes, payload_blob_created = self.write_content_addressed_payload(
                    self.observation_payload_dir,
                    payload=payload,
                )
                raw_payload_path = str(payload_path)
            else:
                payload_hash, payload_bytes = self.canonical_raw_payload_digest(payload)
            provider_observed_at = (
                data.get("provider_observed_at")
                or data.get("observation_time")
                or data.get("observed_at")
                or data.get("local_time")
            )
            provider_update_time = data.get("provider_update_time") or data.get("last_updated")
            provenance = self.payload_provenance(
                kind="observation",
                item=item,
                data=data,
                payload=payload,
                payload_hash=payload_hash,
                captured_utc=captured_utc,
                provider_time=provider_observed_at or provider_update_time,
                runtime_identity=runtime_identity,
                release_lineage=release_lineage,
                model_identity=model_identity,
                config_identity=config_identity,
            )
            row = {
                "schema_version": OBSERVATION_PAYLOAD_SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "captured_at_utc": captured_utc,
                "captured_at_local": captured_local,
                "event_slug": self.event_slug,
                "model_version": model_version,
                "source": source,
                "status": status,
                "stale": bool(item.get("stale")),
                "source_family": self.source_family(source, item),
                "degradation_state": self.source_degradation_state(status, item),
                "cache_status": self.source_cache_status(status, item),
                "fetched_at": item.get("fetched_at"),
                "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
                "ttl_minutes": ttl_minutes,
                "provider_observed_at": provider_observed_at,
                "provider_station_id": data.get("station_id") or data.get("station") or data.get("icao"),
                "provider_update_time": provider_update_time,
                **provenance,
                "payload_hash": payload_hash,
                "payload_bytes": payload_bytes,
                "raw_payload_retained": bool(raw_payload_path),
                "payload_blob_created": payload_blob_created,
                "row_count": self.source_row_count(data),
                "source_url": redact_sensitive_url_parts(data.get("url") or data.get("source_url")),
                "raw_payload_path": raw_payload_path,
            }
            rows.append(row)
        if rows:
            self.append_csv(self.observation_payloads_long_path, OBSERVATION_PAYLOAD_COLUMNS, rows)
            for row in rows:
                self.append_jsonl(self.observation_payloads_jsonl_path, row, durable=True)
        return rows

    def snapshot_explanation_payload(
        self,
        *,
        snapshot_id,
        captured_at,
        model,
        model_client,
        event_config,
        model_version,
        model_identity,
        runtime_identity,
        runtime_fields,
        feature_schema_version,
    ):
        explanation = {
            "analog_search": model.get("analog_search") or {},
            "boundary_transitions": model.get("boundary_transitions") or {},
            "late_day_risk": model.get("late_day_risk") or {},
            "source_diagnostics": model.get("source_diagnostics") or [],
            "source_health": model.get("source_health") or {},
            "family_secondary_gate": model.get("family_secondary_gate")
            or ((model.get("distribution_result") or {}).get("family_secondary_gate") or {}),
            "model_explanation": model.get("model_explanation") or {},
            "probability_calibration_context": model.get("probability_calibration_context") or {},
            "distribution_component_metadata": self.distribution_component_metadata(
                model.get("distribution_components") or {},
            ),
        }
        explanation = {
            key: value
            for key, value in explanation.items()
            if value not in (None, {}, [])
        }
        if not explanation:
            return None, []

        sources = self.strip_raw_payloads(model.get("sources")) or {}
        source_hash = self.payload_hash(sources)
        model_identity_hash = self.payload_hash(model_identity or {})
        target_date = getattr(model_client, "target_date", None) or getattr(event_config, "target_date", None)
        if hasattr(target_date, "isoformat"):
            target_date = target_date.isoformat()
        base = {
            "snapshot_id": snapshot_id,
            "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
            "captured_at_local": captured_at.isoformat(),
            "event_slug": self.event_slug,
            "market_id": getattr(event_config, "market_id", None),
            "target_date": target_date,
            "model_version": model_version,
            "feature_schema_version": feature_schema_version,
            **runtime_fields,
            "explanation_schema_version": SNAPSHOT_EXPLANATION_SCHEMA_VERSION,
            "model_identity_hash": model_identity_hash,
            "source_hash": source_hash,
        }
        rows = self.snapshot_explanation_rows(base, explanation)
        payload = {
            "schema_version": SNAPSHOT_EXPLANATION_SCHEMA_VERSION,
            **base,
            "runtime_identity": runtime_identity,
            "model_identity": model_identity,
            "source_hash": source_hash,
            "explanation_hash": self.payload_hash(explanation),
            "sections": sorted(explanation),
            "row_count": len(rows),
            "explanations": explanation,
        }
        return payload, rows

    def distribution_component_metadata(self, bundle):
        if not bundle:
            return {}
        metadata = {
            "schema_version": bundle.get("schema_version"),
            "cutoff_hour": bundle.get("cutoff_hour"),
            "active_model_kind": bundle.get("active_model_kind"),
            "latest_wu_history_time": bundle.get("latest_wu_history_time"),
            "latest_wu_history_temp": bundle.get("latest_wu_history_temp"),
            "high_has_stood_lockin": bundle.get("high_has_stood_lockin"),
        }
        pipeline = bundle.get("pipeline_state") or bundle.get("stage_metadata") or {}
        if pipeline:
            metadata["pipeline_state"] = pipeline
        components = bundle.get("components") or {}
        if components:
            metadata["component_names"] = sorted(str(name) for name in components)
        return {
            key: value
            for key, value in metadata.items()
            if value not in (None, {}, [])
        }

    def snapshot_explanation_rows(self, base, explanation):
        rows = []
        for section, value in sorted((explanation or {}).items()):
            rows.extend(self.explanation_section_rows(base, section, value))
        return rows

    def explanation_section_rows(self, base, section, value):
        if isinstance(value, dict):
            rows = []
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
                rows.append(self.explanation_value_row(base, section, key, None, item))
            return rows
        if isinstance(value, list):
            rows = []
            for index, item in enumerate(value):
                item_key = self.explanation_item_key(item, index)
                if isinstance(item, dict):
                    rows.append(self.explanation_value_row(base, section, item_key, None, item))
                    for subkey, subvalue in sorted(item.items(), key=lambda pair: str(pair[0])):
                        if self.is_scalar(subvalue):
                            rows.append(self.explanation_value_row(base, section, item_key, subkey, subvalue))
                else:
                    rows.append(self.explanation_value_row(base, section, item_key, None, item))
            return rows
        return [self.explanation_value_row(base, section, "value", None, value)]

    def explanation_item_key(self, item, index):
        if isinstance(item, dict):
            for key in ("source", "family", "name", "bucket", "Driver", "Question", "stage", "gate"):
                value = item.get(key)
                if value not in (None, ""):
                    return str(value)
        return str(index)

    def explanation_value_row(self, base, section, item_key, item_subkey, value):
        payload_json = ""
        payload_hash = ""
        value_text = None
        value_number = None
        value_bool = None
        if isinstance(value, bool):
            value_bool = value
            value_text = str(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            value_number = value
            value_text = str(value)
        elif value is None:
            value_text = None
        elif isinstance(value, (dict, list)):
            payload_json = json.dumps(value, sort_keys=True, default=str)
            payload_hash = hashlib.sha1(payload_json.encode("utf-8")).hexdigest()
            value_text = None
        else:
            value_text = str(value)
        return {
            **base,
            "section": section,
            "item_key": item_key,
            "item_subkey": item_subkey,
            "value_text": value_text,
            "value_number": value_number,
            "value_bool": value_bool,
            "payload_hash": payload_hash,
            "payload_json": payload_json,
        }

    def is_scalar(self, value):
        return value is None or isinstance(value, (str, int, float, bool))

    def safe_filename_part(self, value):
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value))

    @staticmethod
    def raw_forecast_payload_retention_enabled():
        value = os.environ.get(FORECAST_RAW_PAYLOAD_RETENTION_ENV)
        if value is None:
            return True
        return str(value).strip().lower() not in {"0", "false", "no", "off"}

    @staticmethod
    def raw_observation_payload_retention_enabled():
        value = os.environ.get(OBSERVATION_RAW_PAYLOAD_RETENTION_ENV)
        if value is None:
            return True
        return str(value).strip().lower() not in {"0", "false", "no", "off"}

    def strip_raw_payloads(self, value):
        if isinstance(value, dict):
            return {
                key: self.strip_raw_payloads(item)
                for key, item in value.items()
                if key != "raw_payload"
            }
        if isinstance(value, list):
            return [self.strip_raw_payloads(item) for item in value]
        return value

    def runtime_identity_guard(self, current_identity=None, process_identity=None):
        process_identity = process_identity or PROCESS_RUNTIME_IDENTITY
        current_identity = current_identity or current_identity_for(process_identity)
        ok = identities_match(process_identity, current_identity)
        state = "current" if ok else "stale_code"
        return {
            "ok": ok,
            "state": state,
            "process_identity": process_identity,
            "current_identity": current_identity,
            "detail": None if ok else (
                "snapshot process code identity differs from current source tree: "
                f"process={format_runtime_identity(process_identity)}; "
                f"current={format_runtime_identity(current_identity)}"
            ),
        }

    def runtime_identity_blocked_result(self, runtime_guard, cadence="scheduled"):
        return {
            "written": False,
            "blocked": True,
            "status": runtime_guard.get("state") or "stale_code",
            "path": str(self.long_path),
            "next_due_at": self.next_due_at(cadence=cadence),
            "runtime_guard": runtime_guard,
            "detail": runtime_guard.get("detail"),
        }

    def runtime_identity_fields(self, identity, code_state="current"):
        identity = identity or {}
        return {
            "runtime_identity_schema_version": identity.get("schema_version"),
            "runtime_git_branch": identity.get("git_branch"),
            "runtime_git_commit": identity.get("git_commit"),
            "runtime_git_dirty": identity.get("git_dirty"),
            "runtime_dirty_fingerprint": identity.get("dirty_fingerprint"),
            "runtime_source_fingerprint": identity.get("source_fingerprint"),
            "runtime_code_state": code_state,
        }

    def row_bin_data(self, row):
        value = row.get("bin_value_c")
        if value is None:
            return None
        value = int(float(value))
        value_hi = row.get("bin_value_hi_c")
        if value_hi is None or value_hi == "":
            value_hi = value
        else:
            value_hi = int(float(value_hi))
        return {
            "kind": row.get("bin_kind"),
            "value": value,
            "value_hi": value_hi,
            "label": row.get("range_label"),
            "market_yes": row.get("market_yes"),
            "market_no": row.get("market_no"),
        }

    def check_snapshot_probabilities(self, distribution, long_rows, model_client, calibration_context=None):
        checked = 0
        max_abs_diff = 0.0
        failures = []
        if not distribution:
            return {"status": "skipped", "rows_checked": 0, "reason": "empty distribution"}
        for row in long_rows:
            stored = row.get("model_probability")
            bin_data = self.row_bin_data(row)
            if stored is None or bin_data is None:
                continue
            recomputed = self.model_bin_probability(
                model_client,
                distribution,
                bin_data,
                calibration_context=calibration_context or {},
            )
            diff = abs(float(stored) - float(recomputed))
            checked += 1
            max_abs_diff = max(max_abs_diff, diff)
            if diff > SNAPSHOT_PROBABILITY_TOLERANCE:
                failures.append({
                    "range_label": row.get("range_label"),
                    "stored": stored,
                    "recomputed": recomputed,
                    "abs_diff": diff,
                })
        if failures:
            first = failures[0]
            raise ValueError(
                "snapshot probability self-check failed for "
                f"{first['range_label']}: stored={first['stored']} "
                f"recomputed={first['recomputed']} diff={first['abs_diff']}"
            )
        return {
            "status": "pass",
            "rows_checked": checked,
            "max_abs_diff": max_abs_diff,
            "tolerance": SNAPSHOT_PROBABILITY_TOLERANCE,
        }

    def model_bin_probability(self, model_client, distribution, bin_data, calibration_context=None):
        calibration_context = calibration_context or {}
        method = model_client.bin_probability
        if not calibration_context:
            return method(distribution, bin_data)
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(distribution, bin_data, calibration_context=calibration_context)
        parameters = signature.parameters
        accepts_context = (
            "calibration_context" in parameters
            or any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        )
        if accepts_context:
            return method(distribution, bin_data, calibration_context=calibration_context)
        raise TypeError("model_client.bin_probability must accept calibration_context for calibrated snapshots")

    def component_rows(self, bundle, bins, snapshot_id, captured_at, model_version, runtime_fields=None):
        bundle = bundle or {}
        components = bundle.get("components") or {}
        if not components or not bins:
            return []
        runtime_fields = runtime_fields or {}
        base = {
            "snapshot_id": snapshot_id,
            "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
            "captured_at_local": captured_at.isoformat(),
            "event_slug": self.event_slug,
            "model_version": model_version,
            **runtime_fields,
            "component_schema_version": bundle.get("schema_version"),
            "cutoff_hour": bundle.get("cutoff_hour"),
            "active_model_kind": bundle.get("active_model_kind"),
        }
        rows = []
        for component_name, distribution in sorted(components.items()):
            if not distribution:
                continue
            for bin_data in bins:
                rows.append({
                    **base,
                    "component_name": component_name,
                    "range_label": bin_data.get("label"),
                    "bin_kind": bin_data.get("kind"),
                    "bin_value_c": bin_data.get("value"),
                    "bin_value_hi_c": bin_data.get("value_hi", bin_data.get("value")),
                    "component_probability": self.raw_bin_probability(distribution, bin_data),
                    "market_yes": bin_data.get("market_yes"),
                })
        return rows

    def raw_bin_probability(self, distribution, bin_data):
        if not distribution:
            return None
        kind = bin_data.get("kind")
        value = bin_data.get("value")
        if value is None:
            return None
        value = int(value)
        value_hi = int(bin_data.get("value_hi", value))
        items = {
            int(float(bucket)): float(probability)
            for bucket, probability in distribution.items()
            if probability is not None
        }
        if kind == "lte":
            return sum(prob for temp, prob in items.items() if temp <= value)
        if kind == "gte":
            return sum(prob for temp, prob in items.items() if temp >= value)
        return sum(prob for temp, prob in items.items() if value <= temp <= value_hi)

    def wide_columns(self, long_rows):
        columns = [
            "snapshot_id",
            "captured_at_utc",
            "captured_at_local",
            "event_slug",
            "event_updated_at",
            "model_version",
            "feature_schema_version",
            *RUNTIME_IDENTITY_COLUMNS,
            "snapshot_cadence",
            "snapshot_cadence_quality_state",
            "snapshot_cadence_gap_count",
            "snapshot_cadence_max_gap_seconds",
            "snapshot_cadence_last_model_age_seconds",
            "snapshot_cadence_confidence_multiplier",
            "snapshot_cadence_permission",
            "snapshot_cadence_reason",
            "trigger_reason",
            "top_temp_c",
            "top_probability",
            "wu_history_high_c",
            "wu_current_c",
            "wu_max_since_7am_c",
            "station_current_c",
            "station_max_since_7am_c",
            "station_observation_source",
            "station_observation_station_id",
            "eccc_swob_max_c",
            "weather_forecast_max_c",
            "open_meteo_max_c",
            "eccc_forecast_high_c",
        ]
        for row in long_rows:
            suffix = self.band_key(row)
            columns.extend([
                f"model_{suffix}",
                f"market_yes_{suffix}",
                f"market_no_{suffix}",
                f"edge_{suffix}",
                f"best_bid_{suffix}",
                f"best_ask_{suffix}",
                f"last_{suffix}",
            ])
        return columns

    def wide_row(self, long_rows):
        first = long_rows[0] if long_rows else {}
        row = {
            "snapshot_id": first.get("snapshot_id"),
            "captured_at_utc": first.get("captured_at_utc"),
            "captured_at_local": first.get("captured_at_local"),
            "event_slug": first.get("event_slug"),
            "event_updated_at": first.get("event_updated_at"),
            "model_version": first.get("model_version"),
            "feature_schema_version": first.get("feature_schema_version"),
            **{column: first.get(column) for column in RUNTIME_IDENTITY_COLUMNS},
            "snapshot_cadence": first.get("snapshot_cadence"),
            "snapshot_cadence_quality_state": first.get("snapshot_cadence_quality_state"),
            "snapshot_cadence_gap_count": first.get("snapshot_cadence_gap_count"),
            "snapshot_cadence_max_gap_seconds": first.get("snapshot_cadence_max_gap_seconds"),
            "snapshot_cadence_last_model_age_seconds": first.get("snapshot_cadence_last_model_age_seconds"),
            "snapshot_cadence_confidence_multiplier": first.get("snapshot_cadence_confidence_multiplier"),
            "snapshot_cadence_permission": first.get("snapshot_cadence_permission"),
            "snapshot_cadence_reason": first.get("snapshot_cadence_reason"),
            "trigger_reason": first.get("trigger_reason"),
            "top_temp_c": first.get("top_temp_c"),
            "top_probability": first.get("top_probability"),
            "wu_history_high_c": first.get("wu_history_high_c"),
            "wu_current_c": first.get("wu_current_c"),
            "wu_max_since_7am_c": first.get("wu_max_since_7am_c"),
            "station_current_c": first.get("station_current_c"),
            "station_max_since_7am_c": first.get("station_max_since_7am_c"),
            "station_observation_source": first.get("station_observation_source"),
            "station_observation_station_id": first.get("station_observation_station_id"),
            "eccc_swob_max_c": first.get("eccc_swob_max_c"),
            "weather_forecast_max_c": first.get("weather_forecast_max_c"),
            "open_meteo_max_c": first.get("open_meteo_max_c"),
            "eccc_forecast_high_c": first.get("eccc_forecast_high_c"),
        }
        for band in long_rows:
            suffix = self.band_key(band)
            row[f"model_{suffix}"] = band.get("model_probability")
            row[f"market_yes_{suffix}"] = band.get("market_yes")
            row[f"market_no_{suffix}"] = band.get("market_no")
            row[f"edge_{suffix}"] = band.get("edge")
            row[f"best_bid_{suffix}"] = band.get("best_bid")
            row[f"best_ask_{suffix}"] = band.get("best_ask")
            row[f"last_{suffix}"] = band.get("last_trade_price")
        return row

    def band_key(self, row):
        kind = row.get("bin_kind")
        value = row.get("bin_value_c")
        value_hi = row.get("bin_value_hi_c")
        value_text = self.band_key_value(value)
        value_hi_text = self.band_key_value(value_hi)
        if kind == "lte":
            return f"lte_{value_text}c"
        if kind == "gte":
            return f"gte_{value_text}c"
        if value_hi_text and value_hi_text != value_text:
            return f"eq_{value_text}_{value_hi_text}c"
        return f"eq_{value_text}c"

    def band_key_value(self, value):
        if value is None or value == "":
            return "unknown"
        try:
            numeric = float(value)
            if abs(numeric - round(numeric)) < 1e-9:
                return str(int(round(numeric)))
            return str(numeric).replace(".", "p")
        except (TypeError, ValueError):
            return self.safe_filename_part(value)

    def append_csv(self, path, columns, rows):
        """Append rows, widening an existing header when the schema grows.

        Older snapshot files may lack newly added audit columns. Rewriting the
        file with the union header preserves existing rows and prevents the new
        values from being silently dropped on append.
        """
        write_header = not path.exists()
        columns = list(columns)
        if not write_header:
            with path.open("r", encoding="utf-8", newline="") as handle:
                existing_header = next(csv.reader(handle), None)
            if existing_header:
                missing_columns = [column for column in columns if column not in existing_header]
                columns = list(existing_header) + missing_columns
                if missing_columns:
                    # Never materialize a live day-wide CSV in memory. Some
                    # retained projections are already large enough to hit the
                    # isolated capture tree cap. Stream the schema migration to
                    # a unique sibling and atomically replace only after fsync.
                    tmp_path = path.with_name(
                        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
                    )
                    try:
                        with (
                            path.open("r", encoding="utf-8", newline="") as source,
                            tmp_path.open("x", encoding="utf-8", newline="") as destination,
                        ):
                            reader = csv.DictReader(source)
                            writer = csv.DictWriter(
                                destination,
                                fieldnames=columns,
                                extrasaction="ignore",
                                restval="",
                            )
                            writer.writeheader()
                            for existing_row in reader:
                                writer.writerow(existing_row)
                            destination.flush()
                            os.fsync(destination.fileno())
                        os.replace(tmp_path, path)
                    except BaseException:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise
            else:
                write_header = True
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", restval="")
            if write_header:
                writer.writeheader()
            for row in rows:
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())

    def append_jsonl(self, path, payload, *, durable=False):
        with path.open("a", encoding="utf-8") as handle:
            for text_chunk in _iter_json_text_chunks(
                payload,
                sort_keys=True,
                default=str,
            ):
                handle.write(text_chunk)
            handle.write("\n")
            if durable:
                handle.flush()
                os.fsync(handle.fileno())

    def existing_explanation_snapshot_ids(self):
        ids = set()
        for path in (self.snapshot_explanations_long_path, self.snapshot_explanations_jsonl_path):
            if not path.exists():
                continue
            if path.suffix == ".csv":
                try:
                    with path.open("r", encoding="utf-8", newline="") as handle:
                        for row in csv.DictReader(handle):
                            if row.get("snapshot_id"):
                                ids.add(row["snapshot_id"])
                except (OSError, csv.Error):
                    continue
            else:
                for payload in self.read_jsonl(path):
                    if payload.get("snapshot_id"):
                        ids.add(payload["snapshot_id"])
        return ids

    def existing_snapshot_ids_for_sidecar(self, path):
        path = Path(path)
        if not path.exists():
            return set()
        ids = set()
        if path.suffix == ".csv":
            try:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        if row.get("snapshot_id"):
                            ids.add(row["snapshot_id"])
            except (OSError, csv.Error):
                return set()
        else:
            for payload in self.read_jsonl(path):
                if payload.get("snapshot_id"):
                    ids.add(payload["snapshot_id"])
        return ids

    def read_jsonl(self, path):
        path = Path(path)
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
        return rows

    def replay_inputs_by_snapshot(self):
        rows_by_snapshot = {
            row.get("snapshot_id"): row
            for row in self.read_jsonl(self.replay_inputs_path)
            if row.get("snapshot_id")
        }
        reconstructed_path = self.root / REPLAY_RECONSTRUCTED_FILENAME
        for row in self.read_jsonl(reconstructed_path):
            snapshot_id = row.get("snapshot_id")
            if snapshot_id and snapshot_id not in rows_by_snapshot:
                rows_by_snapshot[snapshot_id] = row
        return rows_by_snapshot

    def snapshot_band_bins(self, snapshot):
        bins = []
        for row in snapshot.get("bands") or []:
            value = self.safe_number(row.get("bin_value_c") or row.get("bin_value"))
            value_hi = self.safe_number(row.get("bin_value_hi_c") or row.get("bin_value_hi") or value)
            bins.append({
                "label": row.get("range_label"),
                "kind": row.get("bin_kind") or row.get("kind"),
                "value": value,
                "value_hi": value_hi,
                "market_yes": row.get("market_yes"),
            })
        return bins

    def safe_number(self, value):
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number.is_integer():
            return int(number)
        return number

    def backfill_feature_component_sidecars(self, *, limit=None):
        feature_existing = self.existing_snapshot_ids_for_sidecar(self.features_long_path)
        component_existing = self.existing_snapshot_ids_for_sidecar(self.components_long_path)
        feature_rows = []
        component_rows = []
        skipped_existing_features = 0
        skipped_existing_components = 0
        missing_feature_vector = 0
        missing_components = 0
        invalid_snapshot_rows = 0
        processed = 0
        for snapshot in self.read_jsonl(self.jsonl_path):
            snapshot_id = snapshot.get("snapshot_id")
            if not snapshot_id:
                invalid_snapshot_rows += 1
                continue
            if limit is not None and processed >= int(limit):
                break
            processed += 1
            captured_text = snapshot.get("captured_at_local") or snapshot.get("captured_at_utc")
            try:
                captured_at = datetime.fromisoformat(str(captured_text).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                invalid_snapshot_rows += 1
                continue
            model_version = snapshot.get("model_version") or MODEL_VERSION
            feature_vector = snapshot.get("feature_vector")
            if snapshot_id in feature_existing:
                skipped_existing_features += 1
            elif feature_vector:
                feature_rows.append(audit_row(
                    {
                        "snapshot_id": snapshot_id,
                        "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
                        "captured_at_local": captured_at.isoformat(),
                        "event_slug": snapshot.get("event_slug") or self.event_slug,
                        "model_version": model_version,
                    },
                    feature_vector,
                ))
                feature_existing.add(snapshot_id)
            else:
                missing_feature_vector += 1

            if snapshot_id in component_existing:
                skipped_existing_components += 1
                continue
            bins = self.snapshot_band_bins(snapshot)
            rows = self.component_rows(
                snapshot.get("distribution_components"),
                bins,
                snapshot_id,
                captured_at,
                model_version,
                runtime_fields={},
            )
            if rows:
                component_rows.extend(rows)
                component_existing.add(snapshot_id)
            else:
                missing_components += 1
        if feature_rows:
            self.append_csv(self.features_long_path, FEATURE_AUDIT_COLUMNS, feature_rows)
            for row in feature_rows:
                self.append_jsonl(self.features_jsonl_path, row)
        if component_rows:
            self.append_csv(self.components_long_path, COMPONENT_COLUMNS, component_rows)
            for row in component_rows:
                self.append_jsonl(self.components_jsonl_path, row)
        status = "OK" if (feature_rows or component_rows or processed) else "NO_SNAPSHOTS_JSONL"
        return {
            "schema_version": "snapshot_core_sidecar_backfill_v0.1",
            "folder": str(self.root),
            "status": status,
            "processed_snapshot_count": processed,
            "written_feature_row_count": len(feature_rows),
            "written_component_row_count": len(component_rows),
            "skipped_existing_feature_snapshot_count": skipped_existing_features,
            "skipped_existing_component_snapshot_count": skipped_existing_components,
            "missing_feature_vector_count": missing_feature_vector,
            "missing_distribution_component_count": missing_components,
            "invalid_snapshot_row_count": invalid_snapshot_rows,
            "features_path": str(self.features_long_path),
            "components_path": str(self.components_long_path),
        }

    def existing_observation_payload_keys(self):
        keys = set()
        if not self.observation_payloads_long_path.exists():
            return keys
        try:
            with self.observation_payloads_long_path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    key = (row.get("snapshot_id"), row.get("source"), row.get("payload_hash"))
                    if all(key):
                        keys.add(key)
        except (OSError, csv.Error):
            return keys
        return keys

    def backfill_observation_payloads_from_forecast_payloads(self):
        if not self.forecast_payloads_long_path.exists():
            return {
                "schema_version": "observation_payload_backfill_v0.1",
                "folder": str(self.root),
                "written_row_count": 0,
                "skipped_existing_row_count": 0,
                "source": "forecast_payloads_long.csv",
                "status": "NO_SOURCE_MANIFEST",
            }
        existing = self.existing_observation_payload_keys()
        rows = []
        skipped_existing = 0
        with self.forecast_payloads_long_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                source = row.get("source")
                if source not in OBSERVATION_PAYLOAD_SOURCES:
                    continue
                key = (row.get("snapshot_id"), source, row.get("payload_hash"))
                if all(key) and key in existing:
                    skipped_existing += 1
                    continue
                output = {
                    column: row.get(column)
                    for column in OBSERVATION_PAYLOAD_COLUMNS
                }
                output["schema_version"] = OBSERVATION_PAYLOAD_SCHEMA_VERSION
                output["provider_observed_at"] = row.get("provider_observed_at") or row.get("provider_update_time")
                output["provider_station_id"] = row.get("provider_station_id")
                rows.append(output)
                if all(key):
                    existing.add(key)
        if rows:
            self.append_csv(self.observation_payloads_long_path, OBSERVATION_PAYLOAD_COLUMNS, rows)
            for row in rows:
                self.append_jsonl(self.observation_payloads_jsonl_path, row, durable=True)
        return {
            "schema_version": "observation_payload_backfill_v0.1",
            "folder": str(self.root),
            "written_row_count": len(rows),
            "skipped_existing_row_count": skipped_existing,
            "source": "forecast_payloads_long.csv",
            "status": "OK",
            "observation_payloads_path": str(self.observation_payloads_long_path),
            "observation_payloads_jsonl_path": str(self.observation_payloads_jsonl_path),
        }

    def backfill_snapshot_explanations(self, *, limit=None):
        existing = self.existing_explanation_snapshot_ids()
        replay_inputs = self.replay_inputs_by_snapshot()
        written = 0
        skipped_existing = 0
        skipped_missing_payload = 0
        errors = []
        for snapshot in self.read_jsonl(self.jsonl_path):
            snapshot_id = snapshot.get("snapshot_id")
            if not snapshot_id:
                skipped_missing_payload += 1
                continue
            if snapshot_id in existing:
                skipped_existing += 1
                continue
            if limit is not None and written >= int(limit):
                break
            replay = replay_inputs.get(snapshot_id) or {}
            captured_text = snapshot.get("captured_at_local") or snapshot.get("captured_at_utc")
            try:
                captured_at = datetime.fromisoformat(str(captured_text).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                errors.append({"snapshot_id": snapshot_id, "error": "invalid captured_at"})
                continue
            event_slug = snapshot.get("event_slug") or self.event_slug
            event_config = config_from_event(
                {"slug": event_slug},
                fallback_date=replay.get("target_date"),
            )
            runtime_guard = snapshot.get("runtime_guard") or {}
            runtime_identity = snapshot.get("runtime_identity") or replay.get("runtime_identity")
            runtime_fields = self.runtime_identity_fields(
                runtime_identity,
                runtime_guard.get("state"),
            )
            model = {
                "sources": replay.get("sources") or {},
                "distribution": snapshot.get("distribution") or replay.get("recorded_distribution") or {},
                "distribution_components": snapshot.get("distribution_components") or {},
                "probability_calibration_context": snapshot.get("probability_calibration_context") or {},
                "feature_vector": snapshot.get("feature_vector") or {},
                "model_version": snapshot.get("model_version") or replay.get("model_version") or MODEL_VERSION,
                "model_explanation": snapshot.get("model_explanation") or {},
                "analog_search": snapshot.get("analog_search") or {},
                "boundary_transitions": snapshot.get("boundary_transitions") or {},
                "late_day_risk": snapshot.get("late_day_risk") or {},
                "source_diagnostics": snapshot.get("source_diagnostics") or [],
                "source_health": snapshot.get("source_health") or {},
                "family_secondary_gate": snapshot.get("family_secondary_gate") or {},
                "distribution_result": snapshot.get("distribution_result") or {},
            }
            model_client = SimpleNamespace(target_date=replay.get("target_date") or getattr(event_config, "target_date", None))
            explanation_payload, explanation_rows = self.snapshot_explanation_payload(
                snapshot_id=snapshot_id,
                captured_at=captured_at,
                model=model,
                model_client=model_client,
                event_config=event_config,
                model_version=model["model_version"],
                model_identity=snapshot.get("model_identity") or replay.get("model_identity"),
                runtime_identity=runtime_identity,
                runtime_fields=runtime_fields,
                feature_schema_version=snapshot.get("feature_schema_version")
                or (model["feature_vector"] or {}).get("feature_schema_version"),
            )
            if not explanation_payload:
                skipped_missing_payload += 1
                continue
            self.append_jsonl(self.snapshot_explanations_jsonl_path, explanation_payload)
            if explanation_rows:
                self.append_csv(
                    self.snapshot_explanations_long_path,
                    SNAPSHOT_EXPLANATION_COLUMNS,
                    explanation_rows,
                )
            existing.add(snapshot_id)
            written += 1
        return {
            "schema_version": "snapshot_explanation_backfill_v0.1",
            "folder": str(self.root),
            "event_slug": self.event_slug,
            "written_snapshot_count": written,
            "skipped_existing_snapshot_count": skipped_existing,
            "skipped_missing_payload_count": skipped_missing_payload,
            "error_count": len(errors),
            "errors": errors[:20],
            "snapshot_explanations_path": str(self.snapshot_explanations_long_path),
            "snapshot_explanations_jsonl_path": str(self.snapshot_explanations_jsonl_path),
        }

    def model_identity(self, model_client):
        try:
            return model_replay_identity(model_client)
        except Exception:  # noqa: BLE001 - capture must continue without identity
            return None

    def normalized_trigger_context(self, trigger_context):
        if not trigger_context:
            return None
        context = dict(trigger_context)
        reasons = context.get("reasons")
        if reasons is None and context.get("reason"):
            reasons = [context.get("reason")]
        if reasons is not None:
            context["reasons"] = sorted({str(reason) for reason in reasons if reason})
        if not context.get("reason") and context.get("reasons"):
            context["reason"] = context["reasons"][0]
        return context

    def trigger_summary(self, trigger_context):
        context = trigger_context or {}
        primary = context.get("primary_trigger") or {}
        previous_value = primary.get("previous_value")
        if previous_value is None:
            previous_value = context.get("previous_value")
        current_value = primary.get("current_value")
        if current_value is None:
            current_value = context.get("current_value")
        return {
            "trigger_reason": context.get("reason"),
            "trigger_source": primary.get("source") or context.get("source"),
            "trigger_previous_value": previous_value,
            "trigger_current_value": current_value,
            "trigger_observed_at": primary.get("observed_at") or context.get("observed_at"),
        }

    @staticmethod
    def verified_release_lineage():
        """Resolve immutable serving lineage without crossing into operations."""

        # Return a copy so a caller cannot mutate process-global cached state.
        return dict(_verified_release_lineage_once_per_process())

    @staticmethod
    def verified_serving_bundle():
        """Return the process-frozen serving bundle or explicit unbound state."""

        return _verified_serving_bundle_once_per_process()

    @staticmethod
    def verified_shadow_capture_bundle():
        """Return the optional residual-only bundle used for variant tape rows."""

        return _verified_residual_shadow_bundle_once_per_process()

    @staticmethod
    def clear_verified_release_lineage_cache():
        """Reset process lineage state for tests or an explicit runtime restart."""

        clear_process_serving_bundle_cache()
        _SHADOW_CAPTURE_BUNDLES.clear()

    def build_replay_input_payload(
        self,
        snapshot_id,
        captured_at,
        model,
        model_client,
        model_version,
        model_identity=None,
        runtime_identity=None,
        runtime_guard=None,
        cadence="scheduled",
        cadence_quality=None,
        trigger_context=None,
        release_lineage=None,
    ):
        """Build and canonically hash the exact captured-input replay payload.

        The merged ``sources`` dict is exactly what ``estimate_distribution`` consumes
        (it is pure given sources + the build ``now``), and it is already
        JSON-serializable. ``recorded_distribution`` is kept alongside as a fidelity
        canary: replaying with the same code version must reproduce it.
        """
        sources = self.strip_raw_payloads(model.get("sources"))
        if not sources:
            return None
        release_lineage = release_lineage or self.verified_release_lineage()
        target_date = getattr(model_client, "target_date", None)
        payload = {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
            "captured_at_local": captured_at.isoformat(),
            "event_slug": self.event_slug,
            "target_date": target_date.isoformat() if hasattr(target_date, "isoformat") else target_date,
            "model_version": model_version,
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
            "base_model_release_bound": bool(
                release_lineage.get("base_model_release_bound", False)
            ),
            "base_model_binding_reason": str(
                release_lineage.get("base_model_binding_reason") or ""
            ),
            "captured_input_hash_algorithm": CAPTURED_INPUT_HASH_ALGORITHM,
            "model_identity": model_identity if model_identity is not None else self.model_identity(model_client),
            "runtime_identity": runtime_identity,
            "runtime_guard": runtime_guard,
            "snapshot_cadence": cadence,
            "snapshot_cadence_quality": cadence_quality or snapshot_cadence_quality({"snapshot_cadence": cadence}),
            "trigger_context": trigger_context,
            # The timestamp the build actually used (falls back to the write time).
            "built_at": model.get("built_at") or captured_at.isoformat(),
            "recorded_distribution": model.get("distribution") or {},
            "sources": sources,
        }
        payload["captured_input_hash"] = canonical_payload_sha256(payload)
        return payload

    def write_replay_input(
        self,
        snapshot_id,
        captured_at,
        model,
        model_client,
        model_version,
        model_identity=None,
        runtime_identity=None,
        runtime_guard=None,
        cadence="scheduled",
        cadence_quality=None,
        trigger_context=None,
        release_lineage=None,
    ):
        """Build and persist one captured-input replay payload."""

        payload = self.build_replay_input_payload(
            snapshot_id,
            captured_at,
            model,
            model_client,
            model_version,
            model_identity,
            runtime_identity,
            runtime_guard,
            cadence=cadence,
            cadence_quality=cadence_quality,
            trigger_context=trigger_context,
            release_lineage=release_lineage,
        )
        if payload:
            self.append_jsonl(self.replay_inputs_path, payload)
        return payload

    def acquire_lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for _ in range(30):
            try:
                handle = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(handle, str(os.getpid()).encode("ascii"))
                return handle
            except FileExistsError:
                if self.lock_is_stale():
                    try:
                        self.lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                time.sleep(0.1)
        return None

    def release_lock(self, handle):
        os.close(handle)
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass

    def lock_is_stale(self):
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age > 300


if __name__ == "__main__":
    raise SystemExit(main())
