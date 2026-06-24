"""Snapshot persistence store and schema constants."""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from weather.paths import data_path

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
from weather.runtime_identity import format_runtime_identity, get_runtime_identity, identities_match

SNAPSHOT_INTERVAL = timedelta(minutes=10)
DEFAULT_MARKET_CONFIG = config_for_date()
DEFAULT_SNAPSHOT_ROOT = data_path() / "snapshots" / DEFAULT_MARKET_CONFIG.event_slug
# Fallback used only when a snapshot's model dict carries no model_version.
MODEL_VERSION = MODEL_VERSION_HGB

# Replay corpus: each snapshot persists the full merged model `sources` plus the
# exact build `now`, so any future model version can be re-run over the captured
# day and scored against settlement. This turns every captured snapshot into a
# permanent, replayable test case (see src/replay.py, src/replay_backtest.py).
REPLAY_SCHEMA_VERSION = "toronto_replay_inputs_v0.1"
SNAPSHOT_EXPLANATION_SCHEMA_VERSION = "snapshot_explanations_v0.1"
SNAPSHOT_PROBABILITY_TOLERANCE = 1e-9
PROCESS_RUNTIME_IDENTITY = get_runtime_identity()
OPEN_METEO_SOURCE_FAMILY = {
    "open_meteo",
    "open_meteo_air_quality",
    "open_meteo_global_models",
    "open_meteo_multimodel",
    "global_ensemble",
    "eccc_gem",
}


RUNTIME_IDENTITY_COLUMNS = [
    "runtime_identity_schema_version",
    "runtime_git_branch",
    "runtime_git_commit",
    "runtime_git_dirty",
    "runtime_dirty_fingerprint",
    "runtime_source_fingerprint",
    "runtime_code_state",
]


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
    "provider_issue_time",
    "provider_update_time",
    "payload_hash",
    "payload_bytes",
    "row_count",
    "source_url",
    "raw_payload_path",
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
    "payload_hash",
    "payload_bytes",
    "row_count",
    "source_url",
    "raw_payload_path",
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
    def __init__(self, root=None, interval=SNAPSHOT_INTERVAL, event_slug=None):
        self.interval = interval
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
        snapshot_id = captured_at.strftime("%Y%m%dT%H%M%S%z")
        runtime_guard = runtime_guard or self.runtime_identity_guard()
        if not runtime_guard.get("ok"):
            raise RuntimeError(runtime_guard.get("detail") or "stale snapshot runtime identity")
        runtime_identity = runtime_guard.get("process_identity") or {}
        runtime_fields = self.runtime_identity_fields(runtime_identity, runtime_guard.get("state"))
        trigger_context = self.normalized_trigger_context(trigger_context)
        trigger_summary = self.trigger_summary(trigger_context)
        distribution = model.get("distribution", {}) or {}
        model_version = model.get("model_version") or MODEL_VERSION
        model_identity = model.get("model_identity") or self.model_identity(model_client)
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
        )
        observation_payload_rows = self.write_observation_payloads(
            sources,
            snapshot_id,
            captured_at,
            model_version,
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
        variant_prediction_rows = []
        variant_prediction_error = None
        try:
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
                runtime_fields=runtime_fields,
                snapshot_cadence=cadence,
                cadence_quality=cadence_quality,
                trigger_summary=trigger_summary,
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

        if variant_prediction_rows:
            self.append_csv(
                self.variant_predictions_long_path,
                LIVE_VARIANT_PREDICTION_COLUMNS,
                variant_prediction_rows,
            )
            for row in variant_prediction_rows:
                self.append_jsonl(self.variant_predictions_jsonl_path, row)

        self.write_replay_input(
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
        )

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
            "observation_payload_rows": len(observation_payload_rows),
            "observation_payloads_path": str(self.observation_payloads_long_path),
            "observation_payloads_jsonl_path": str(self.observation_payloads_jsonl_path),
            "variant_prediction_rows": len(variant_prediction_rows),
            "variant_predictions_path": str(self.variant_predictions_long_path),
            "variant_predictions_jsonl_path": str(self.variant_predictions_jsonl_path),
            "variant_prediction_error": variant_prediction_error,
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
        return last is None or now - last >= self.interval

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
        return (base + self.interval).isoformat()

    def source_values(self, sources, model_client, captured_at=None):
        history = model_client.source_data(sources, "wu_history")
        current = model_client.source_data(sources, "wu_current")
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
                "source_url": data.get("url") if isinstance(data, dict) else None,
                "error": item.get("error"),
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
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

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

    def write_forecast_payloads(self, sources, snapshot_id, captured_at, model_version):
        rows = []
        captured_utc = captured_at.astimezone(timezone.utc).isoformat()
        captured_local = captured_at.isoformat()
        for source, item in sorted((sources or {}).items()):
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
            raw_text = json.dumps(payload, sort_keys=True, default=str)
            payload_hash = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()
            safe_source = self.safe_filename_part(source)
            filename = f"{snapshot_id}_{safe_source}_{payload_hash[:12]}.json"
            payload_path = self.forecast_payload_dir / filename
            self.forecast_payload_dir.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(raw_text + "\n", encoding="utf-8")
            row = {
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
                "provider_issue_time": data.get("provider_issue_time") or data.get("issued_at"),
                "provider_update_time": (
                    data.get("provider_update_time")
                    or data.get("last_updated")
                    or data.get("valid_time_utc")
                ),
                "payload_hash": payload_hash,
                "payload_bytes": len(raw_text.encode("utf-8")),
                "row_count": self.source_row_count(data),
                "source_url": data.get("url") or data.get("source_url"),
                "raw_payload_path": str(payload_path),
            }
            rows.append(row)
        if rows:
            self.append_csv(self.forecast_payloads_long_path, FORECAST_PAYLOAD_COLUMNS, rows)
            for row in rows:
                self.append_jsonl(self.forecast_payloads_jsonl_path, row)
        return rows

    def write_observation_payloads(self, sources, snapshot_id, captured_at, model_version):
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
            raw_text = json.dumps(payload, sort_keys=True, default=str)
            payload_hash = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()
            safe_source = self.safe_filename_part(source)
            filename = f"{snapshot_id}_{safe_source}_{payload_hash[:12]}.json"
            payload_path = self.observation_payload_dir / filename
            self.observation_payload_dir.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(raw_text + "\n", encoding="utf-8")
            row = {
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
                "provider_observed_at": (
                    data.get("provider_observed_at")
                    or data.get("observation_time")
                    or data.get("observed_at")
                    or data.get("local_time")
                ),
                "provider_station_id": data.get("station_id") or data.get("station") or data.get("icao"),
                "provider_update_time": data.get("provider_update_time") or data.get("last_updated"),
                "payload_hash": payload_hash,
                "payload_bytes": len(raw_text.encode("utf-8")),
                "row_count": self.source_row_count(data),
                "source_url": data.get("url") or data.get("source_url"),
                "raw_payload_path": str(payload_path),
            }
            rows.append(row)
        if rows:
            self.append_csv(self.observation_payloads_long_path, OBSERVATION_PAYLOAD_COLUMNS, rows)
            for row in rows:
                self.append_jsonl(self.observation_payloads_jsonl_path, row)
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
        current_identity = current_identity or get_runtime_identity()
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
            try:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    existing_header = next(csv.reader(handle), None)
                if existing_header:
                    missing_columns = [column for column in columns if column not in existing_header]
                    columns = list(existing_header) + missing_columns
                    if missing_columns:
                        with path.open("r", encoding="utf-8", newline="") as handle:
                            existing_rows = list(csv.DictReader(handle))
                        tmp_path = path.with_name(f"{path.name}.tmp")
                        with tmp_path.open("w", encoding="utf-8", newline="") as handle:
                            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", restval="")
                            writer.writeheader()
                            writer.writerows(existing_rows)
                        tmp_path.replace(path)
                else:
                    write_header = True
            except (OSError, csv.Error):
                pass
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", restval="")
            if write_header:
                writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def append_jsonl(self, path, payload):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

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
        return {
            row.get("snapshot_id"): row
            for row in self.read_jsonl(self.replay_inputs_path)
            if row.get("snapshot_id")
        }

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
                output["provider_observed_at"] = row.get("provider_observed_at") or row.get("provider_update_time")
                output["provider_station_id"] = row.get("provider_station_id")
                rows.append(output)
                if all(key):
                    existing.add(key)
        if rows:
            self.append_csv(self.observation_payloads_long_path, OBSERVATION_PAYLOAD_COLUMNS, rows)
            for row in rows:
                self.append_jsonl(self.observation_payloads_jsonl_path, row)
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
    ):
        """Persist the full model inputs for this snapshot so it can be replayed.

        The merged ``sources`` dict is exactly what ``estimate_distribution`` consumes
        (it is pure given sources + the build ``now``), and it is already
        JSON-serializable. ``recorded_distribution`` is kept alongside as a fidelity
        canary: replaying with the same code version must reproduce it.
        """
        sources = self.strip_raw_payloads(model.get("sources"))
        if not sources:
            return
        target_date = getattr(model_client, "target_date", None)
        self.append_jsonl(self.replay_inputs_path, {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
            "captured_at_local": captured_at.isoformat(),
            "event_slug": self.event_slug,
            "target_date": target_date.isoformat() if hasattr(target_date, "isoformat") else target_date,
            "model_version": model_version,
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
        })

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


def backfill_explanations(root, *, event_slug=None, limit=None):
    store = SnapshotStore(root=root, event_slug=event_slug or Path(root).name)
    return store.backfill_snapshot_explanations(limit=limit)


def build_parser():
    parser = argparse.ArgumentParser(description="Snapshot persistence utilities.")
    sub = parser.add_subparsers(dest="command", required=True)
    core = sub.add_parser("backfill-core-sidecars")
    core.add_argument("folders", nargs="+", help="Snapshot folder(s) containing snapshots.jsonl.")
    core.add_argument("--limit", type=int, default=None)
    backfill = sub.add_parser("backfill-explanations")
    backfill.add_argument("folders", nargs="+", help="Snapshot folder(s) containing snapshots.jsonl.")
    backfill.add_argument("--limit", type=int, default=None)
    obs = sub.add_parser("backfill-observation-payloads")
    obs.add_argument("folders", nargs="+", help="Snapshot folder(s) containing forecast_payloads_long.csv.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "backfill-core-sidecars":
        results = [
            SnapshotStore(root=folder, event_slug=Path(folder).name).backfill_feature_component_sidecars(limit=args.limit)
            for folder in args.folders
        ]
        print(json.dumps({
            "schema_version": "snapshot_core_sidecar_backfill_batch_v0.1",
            "folder_count": len(results),
            "written_feature_row_count": sum(item.get("written_feature_row_count", 0) for item in results),
            "written_component_row_count": sum(item.get("written_component_row_count", 0) for item in results),
            "folders": results,
        }, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "backfill-explanations":
        results = [
            backfill_explanations(folder, limit=args.limit)
            for folder in args.folders
        ]
        print(json.dumps({
            "schema_version": "snapshot_explanation_backfill_batch_v0.1",
            "folder_count": len(results),
            "written_snapshot_count": sum(item.get("written_snapshot_count", 0) for item in results),
            "error_count": sum(item.get("error_count", 0) for item in results),
            "folders": results,
        }, indent=2, sort_keys=True, default=str))
        return 1 if any(item.get("error_count") for item in results) else 0
    if args.command == "backfill-observation-payloads":
        results = [
            SnapshotStore(root=folder, event_slug=Path(folder).name).backfill_observation_payloads_from_forecast_payloads()
            for folder in args.folders
        ]
        print(json.dumps({
            "schema_version": "observation_payload_backfill_batch_v0.1",
            "folder_count": len(results),
            "written_row_count": sum(item.get("written_row_count", 0) for item in results),
            "folders": results,
        }, indent=2, sort_keys=True, default=str))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
