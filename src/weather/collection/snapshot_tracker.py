import argparse
import csv
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from forecast_archive import (  # noqa: E402
    FORECAST_COLUMNS,
    append_rows as append_forecast_rows,
    build_forecast_rows,
)
from collection_health import fleet_collection_health, serialize_summary, summarize_folder  # noqa: E402
from feature_store import FEATURE_AUDIT_COLUMNS, audit_row
from market_config import config_for_date, config_from_event
from market_registry import DEFAULT_MARKET_ID, all_specs, spec_for_slug
from model_constants import LIVE_CACHE_MAX_AGE_MINUTES, SOURCE_CACHE_TTL_MINUTES
from model_identity import model_replay_identity
from runtime_identity import format_runtime_identity, get_runtime_identity, identities_match
from toronto_model import MODEL_VERSION_HGB, TORONTO_TZ


SNAPSHOT_INTERVAL = timedelta(minutes=10)
DEFAULT_MARKET_CONFIG = config_for_date()
DEFAULT_SNAPSHOT_ROOT = Path("data") / "snapshots" / DEFAULT_MARKET_CONFIG.event_slug
# Fallback used only when a snapshot's model dict carries no model_version.
MODEL_VERSION = MODEL_VERSION_HGB

# Replay corpus: each snapshot persists the full merged model `sources` plus the
# exact build `now`, so any future model version can be re-run over the captured
# day and scored against settlement. This turns every captured snapshot into a
# permanent, replayable test case (see src/replay.py, src/replay_backtest.py).
REPLAY_SCHEMA_VERSION = "toronto_replay_inputs_v0.1"
SNAPSHOT_PROBABILITY_TOLERANCE = 1e-9
PROCESS_RUNTIME_IDENTITY = get_runtime_identity()


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
    "fetched_at",
    "age_minutes",
    "ttl_minutes",
    "latency_ms",
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
    "fetched_at",
    "provider_issue_time",
    "provider_update_time",
    "payload_hash",
    "payload_bytes",
    "row_count",
    "source_url",
    "raw_payload_path",
]


class SnapshotStore:
    def __init__(self, root=None, interval=SNAPSHOT_INTERVAL, event_slug=None):
        self.interval = interval
        self.fixed_root = root is not None
        self._set_paths(Path(root) if root is not None else None, event_slug or DEFAULT_MARKET_CONFIG.event_slug)

    def _set_paths(self, root, event_slug):
        self.event_slug = event_slug
        self.root = Path(root) if root is not None else Path("data") / "snapshots" / self.event_slug
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
        self.replay_inputs_path = self.root / "replay_inputs.jsonl"

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
            return self.write(
                event,
                model,
                model_client,
                now,
                cadence=cadence,
                trigger_context=trigger_context,
            )
        finally:
            self.release_lock(lock_handle)

    def write(self, event, model, model_client, captured_at, cadence="scheduled", trigger_context=None):
        event_config = config_from_event(event)
        if not self.fixed_root and event_config.event_slug != self.event_slug:
            self._set_paths(None, event_config.event_slug)
        self.root.mkdir(parents=True, exist_ok=True)
        snapshot_id = captured_at.strftime("%Y%m%dT%H%M%S%z")
        runtime_guard = self.runtime_identity_guard()
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
        source_values = self.source_values(sources, model_client)
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

        bins = model_client.market_bins(event)
        long_rows = []
        for bin_data in bins:
            value = bin_data.get("value")
            value_hi = bin_data.get("value_hi", value)
            model_probability = model_client.bin_probability(distribution, bin_data)
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

        snapshot_self_check = self.check_snapshot_probabilities(distribution, long_rows, model_client)
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
            "trigger_context": trigger_context,
            "top_temp_c": top_temp,
            "top_probability": top_probability,
            "snapshot_self_check": snapshot_self_check,
            "distribution": distribution,
            "distribution_components": model.get("distribution_components"),
            "source_values": source_values,
            "source_status": source_status_rows,
            "forecast_payloads": forecast_payload_rows,
            "feature_schema_version": feature_schema_version,
            "feature_vector": model.get("feature_vector"),
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
            "source_status_rows": len(source_status_rows),
            "source_status_path": str(self.source_status_long_path),
            "forecast_payload_rows": len(forecast_payload_rows),
            "forecast_payloads_path": str(self.forecast_payloads_long_path),
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

    def source_values(self, sources, model_client):
        history = model_client.source_data(sources, "wu_history")
        current = model_client.source_data(sources, "wu_current")
        eccc = model_client.source_data(sources, "eccc_swob")
        weather_forecast = model_client.source_data(sources, "weather_forecast")
        open_meteo = model_client.source_data(sources, "open_meteo")
        nws_hourly = model_client.source_data(sources, "nws_hourly")
        global_ensemble = model_client.source_data(sources, "global_ensemble")
        eccc_city = model_client.source_data(sources, "eccc_citypage")
        forecast_ensemble = model_client.forecast_ensemble_metrics(
            open_meteo,
            weather_forecast,
            eccc_city,
            nws_hourly=nws_hourly,
            global_ensemble=global_ensemble,
        )
        return {
            "wu_history_high_c": history.get("max_c"),
            "wu_current_c": current.get("temp_c"),
            "wu_max_since_7am_c": current.get("max_since_7am_c"),
            "eccc_swob_max_c": eccc.get("same_day_max_c"),
            "weather_forecast_max_c": model_client.max_row_temp(
                weather_forecast.get("rows")
            ),
            "open_meteo_max_c": model_client.max_row_temp(open_meteo.get("rows")),
            "nws_forecast_max_c": model_client.max_row_temp(nws_hourly.get("rows")),
            "global_ensemble_max_c": model_client.max_row_temp(global_ensemble.get("rows")),
            "forecast_source_count": forecast_ensemble.get("forecast_source_count"),
            "forecast_disagreement": forecast_ensemble.get("forecast_disagreement"),
            "eccc_forecast_high_c": eccc_city.get("forecast_high_c"),
        }

    def source_status_rows(self, sources, model_client, snapshot_id, captured_at, model_version):
        rows = []
        captured_utc = captured_at.astimezone(timezone.utc).isoformat()
        captured_local = captured_at.isoformat()
        for source, item in sorted((sources or {}).items()):
            item = item or {}
            data = item.get("data")
            status = item.get("status")
            if status is None:
                if item.get("ok") and not item.get("stale"):
                    status = "fresh"
                elif item.get("stale"):
                    status = "stale_cache"
                else:
                    status = "failed"
            ttl_minutes = item.get("ttl_minutes")
            if ttl_minutes is None and hasattr(model_client, "source_cache_ttl_minutes"):
                ttl_minutes = model_client.source_cache_ttl_minutes(source)
            age_minutes = item.get("cache_age_minutes")
            if age_minutes is None:
                age_minutes = self.source_age_minutes(item.get("fetched_at"), captured_at, model_client)
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
                "fetched_at": item.get("fetched_at"),
                "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
                "ttl_minutes": ttl_minutes,
                "latency_ms": item.get("latency_ms"),
                "payload_hash": self.payload_hash(data),
                "row_count": self.source_row_count(data),
                "source_url": data.get("url") if isinstance(data, dict) else None,
                "error": item.get("error"),
            })
        return rows

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
                "fetched_at": item.get("fetched_at"),
                "provider_issue_time": data.get("provider_issue_time"),
                "provider_update_time": data.get("provider_update_time") or data.get("last_updated"),
                "payload_hash": payload_hash,
                "payload_bytes": len(raw_text.encode("utf-8")),
                "row_count": self.source_row_count(data),
                "source_url": data.get("url"),
                "raw_payload_path": str(payload_path),
            }
            rows.append(row)
        if rows:
            self.append_csv(self.forecast_payloads_long_path, FORECAST_PAYLOAD_COLUMNS, rows)
            for row in rows:
                self.append_jsonl(self.forecast_payloads_jsonl_path, row)
        return rows

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

    def check_snapshot_probabilities(self, distribution, long_rows, model_client):
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
            recomputed = model_client.bin_probability(distribution, bin_data)
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


def capture_snapshot(force=False, market_id=DEFAULT_MARKET_ID, cadence="scheduled", trigger_context=None):
    from polymarket_client import PolymarketClient
    from toronto_model import TorontoHighTempModel

    market_client = PolymarketClient(market_id=market_id)
    event = market_client.get_event()
    event_config = config_from_event(event, fallback_date=market_client.config.target_date)
    model_client = TorontoHighTempModel(target_date=event_config.target_date, market_id=market_id)
    historical_sources = model_client.fetch_historical_sources()
    live_sources = model_client.fetch_live_sources()
    model = model_client.build(
        event,
        historical_sources=historical_sources,
        live_sources=live_sources,
    )
    return SnapshotStore(event_slug=event_config.event_slug).maybe_write(
        event,
        model,
        model_client,
        force=force,
        cadence=cadence,
        trigger_context=trigger_context,
    )


SNAPSHOT_DATA_ROOT = Path("data") / "snapshots"
PAUSE_FLAG_PATH = SNAPSHOT_DATA_ROOT / "loop_pause.flag"
LOOP_STATUS_PATH = SNAPSHOT_DATA_ROOT / "loop_status.json"
DIAGNOSTICS_PATH = SNAPSHOT_DATA_ROOT / "diagnostics.jsonl"
LOOP_CONSOLE_LOG_PATH = SNAPSHOT_DATA_ROOT / "loop_console.log"
RECENT_LOOP_CYCLE_COUNT = 12

from weather.paths import REPO_ROOT  # noqa: E402


class SourceStatusContext:
    def __init__(self, spec):
        self.spec = spec

    def source_cache_ttl_minutes(self, name):
        return SOURCE_CACHE_TTL_MINUTES.get(name, LIVE_CACHE_MAX_AGE_MINUTES)


def read_jsonl_records(path):
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def parse_capture_time(record, spec):
    value = record.get("captured_at_local") or record.get("captured_at_utc")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=spec.tz if spec else TORONTO_TZ)
    return parsed


def write_rows_csv(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)


def backfill_source_status_for_folder(folder, overwrite=False):
    folder = Path(folder)
    status_path = folder / "source_status_long.csv"
    if status_path.exists() and not overwrite:
        return {"folder": str(folder), "rows": 0, "skipped": True, "reason": "source_status_long.csv exists"}
    records = read_jsonl_records(folder / "replay_inputs.jsonl")
    if not records:
        return {"folder": str(folder), "rows": 0, "skipped": True, "reason": "no replay_inputs.jsonl"}

    spec = spec_for_slug(folder.name)
    context = SourceStatusContext(spec)
    store = SnapshotStore(root=folder, event_slug=folder.name)
    rows = []
    seen = set()
    for record in records:
        snapshot_id = record.get("snapshot_id")
        sources = record.get("sources") or {}
        captured_at = parse_capture_time(record, spec)
        if not snapshot_id or not sources or captured_at is None:
            continue
        for row in store.source_status_rows(
            sources,
            context,
            snapshot_id,
            captured_at,
            record.get("model_version"),
        ):
            key = (row.get("snapshot_id"), row.get("source"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

    if not rows:
        return {"folder": str(folder), "rows": 0, "skipped": True, "reason": "no source rows"}

    write_rows_csv(status_path, SOURCE_STATUS_COLUMNS, rows)
    with (folder / "source_status.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return {"folder": str(folder), "rows": len(rows), "path": str(status_path)}


def backfill_source_status(snapshots_root=SNAPSHOT_DATA_ROOT, overwrite=False):
    root = Path(snapshots_root)
    results = [
        backfill_source_status_for_folder(folder, overwrite=overwrite)
        for folder in sorted(path for path in root.iterdir() if path.is_dir())
    ]
    return {
        "snapshots_root": str(root),
        "folders": len(results),
        "written_folders": sum(1 for result in results if result.get("rows", 0) > 0),
        "rows": sum(result.get("rows", 0) for result in results),
        "results": results,
    }


def read_loop_status():
    if not LOOP_STATUS_PATH.exists():
        return None
    try:
        with LOOP_STATUS_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None


def write_loop_status(status):
    LOOP_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOOP_STATUS_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True, default=str)
    tmp.replace(LOOP_STATUS_PATH)


def append_diagnostic(record):
    DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DIAGNOSTICS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def _age_minutes(now, iso_value):
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_value))
    except ValueError:
        return None
    return (now - parsed).total_seconds() / 60.0


def runtime_identity_status(process_identity, current_identity=None):
    if not process_identity:
        return {
            "runtime_code_state": "unknown",
            "runtime_identity_matches_current": None,
            "current_runtime_identity": current_identity,
            "detail": "no runtime identity recorded",
        }
    current_identity = current_identity or get_runtime_identity()
    matches = identities_match(process_identity, current_identity)
    return {
        "runtime_code_state": "current" if matches else "stale_code",
        "runtime_identity_matches_current": matches,
        "current_runtime_identity": current_identity,
        "detail": None if matches else (
            "running process code identity differs from current source tree: "
            f"process={format_runtime_identity(process_identity)}; "
            f"current={format_runtime_identity(current_identity)}"
        ),
    }


def loop_health(status, now, interval_minutes=10.0, current_identity=None):
    """Judge collection liveness from the heartbeat. Liveness is decided by
    heartbeat freshness, not PID (a stale heartbeat means dead regardless, and
    PIDs get reused across reboots)."""
    if not status:
        return {"state": "UNKNOWN", "detail": "no status file (loop never ran or was cleaned)"}
    interval = status.get("interval_minutes", interval_minutes)
    hb_age = _age_minutes(now, status.get("last_heartbeat"))
    snap_age = _age_minutes(now, status.get("last_snapshot_written_at"))
    errors = status.get("consecutive_errors", 0)
    dead_after = 2 * interval + 2  # tolerate one full sleep cycle plus slack
    runtime = runtime_identity_status(status.get("runtime_identity"), current_identity)
    if runtime.get("runtime_code_state") == "stale_code":
        state = "STALE_CODE"
    elif status.get("paused"):
        state = "PAUSED"
    elif hb_age is None or hb_age > dead_after:
        state = "DEAD"
    elif errors >= 3:
        state = "ERRORING"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "pid": status.get("pid"),
        "heartbeat_age_min": round(hb_age, 1) if hb_age is not None else None,
        "last_snapshot_age_min": round(snap_age, 1) if snap_age is not None else None,
        "consecutive_errors": errors,
        "last_error": status.get("last_error"),
        "started_at": status.get("started_at"),
        "last_iteration_elapsed_minutes": status.get("last_iteration_elapsed_minutes"),
        "max_recent_iteration_elapsed_minutes": status.get("max_recent_iteration_elapsed_minutes"),
        "last_sleep_seconds": status.get("last_sleep_seconds"),
        **runtime,
    }


def current_collection_health(now=None, interval_minutes=10.0, tolerance=1.5):
    now = now or datetime.now(TORONTO_TZ)
    config = config_for_date(now.date())
    folder = SNAPSHOT_DATA_ROOT / config.event_slug
    summary = summarize_folder(
        folder,
        interval_minutes=interval_minutes,
        tolerance=tolerance,
        live=True,
        as_of=now,
    )
    return serialize_summary(summary)


def current_fleet_collection_health(now=None, interval_minutes=10.0, tolerance=1.5):
    now = now or datetime.now(TORONTO_TZ)
    return fleet_collection_health(
        snapshots_root=SNAPSHOT_DATA_ROOT,
        interval_minutes=interval_minutes,
        tolerance=tolerance,
        live=True,
        as_of=now,
    )


def pid_is_python(pid):
    """True when ``pid`` exists AND is a python process. Guards against PID
    reuse by unrelated processes before --stop terminates anything.

    CREATE_NO_WINDOW is load-bearing: the supervisor task runs under
    pythonw.exe (no console), and a console child like tasklist spawned from
    a console-less parent makes Windows allocate a NEW VISIBLE console -- a
    cmd window flashing on the user's screen every 10-minute ensure tick."""
    if not pid:
        return False
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=creationflags,
        ).stdout
        return "python" in out.lower()
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def stop_loop(now=None):
    """Terminate the managed loop recorded in the status file, if it is alive.
    Returns a result dict; never raises for an already-dead loop."""
    now = now or datetime.now(TORONTO_TZ)
    status = read_loop_status()
    pid = (status or {}).get("pid")
    if not pid_is_python(pid):
        return {"stopped": False, "reason": f"no live loop process (pid={pid})"}
    os.kill(int(pid), signal.SIGTERM)
    if status is not None:
        status["last_stop_requested_at"] = now.isoformat()
        write_loop_status(status)
    append_diagnostic({"time": now.isoformat(), "supervisor": "stop", "pid": pid})
    return {"stopped": True, "pid": pid}


def start_loop_detached(interval_minutes=10.0, now=None):
    """Spawn the loop as a detached process (survives this process exiting),
    console output appended to ``loop_console.log``. Writes a provisional
    status immediately so a racing --ensure does not double-start."""
    now = now or datetime.now(TORONTO_TZ)
    LOOP_CONSOLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = LOOP_CONSOLE_LOG_PATH.open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    child = subprocess.Popen(
        [sys.executable, "-m", "src.snapshot_tracker", "--loop",
         "--interval-minutes", str(interval_minutes)],
        cwd=str(REPO_ROOT),
        stdout=log_handle,
        stderr=log_handle,
        creationflags=creationflags,
    )
    log_handle.close()
    write_loop_status({
        "pid": child.pid,
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "runtime_identity": get_runtime_identity(),
        "interval_minutes": interval_minutes,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "last_snapshot_id": None,
        "last_snapshot_written_at": None,
        "paused": PAUSE_FLAG_PATH.exists(),
        "started_by": "supervisor",
    })
    append_diagnostic({"time": now.isoformat(), "supervisor": "start", "pid": child.pid})
    return {"started": True, "pid": child.pid}


def ensure_decision(health_state, pid_alive):
    """Pure supervisor decision: what --ensure should do given loop health.

    RUNNING/PAUSED are healthy (paused is operator intent); ERRORING is alive
    and already logging failures, so leave it visible rather than masking it
    with restarts. A stale heartbeat with a live PID is a HUNG process: kill
    and start fresh. Dead or never-started: start.
    """
    if health_state in ("RUNNING", "PAUSED", "ERRORING"):
        return "noop"
    if pid_alive:
        return "restart"
    return "start"


def ensure_loop(interval_minutes=10.0, now=None):
    """The supervisor verb Task Scheduler runs every few minutes: keep exactly
    one healthy loop alive across silent deaths, hangs, and reboots."""
    now = now or datetime.now(TORONTO_TZ)
    status = read_loop_status()
    health = loop_health(status, now, interval_minutes)
    alive = pid_is_python((status or {}).get("pid"))
    action = ensure_decision(health["state"], alive)
    result = {"action": action, "state": health["state"], "pid": health.get("pid")}
    if action == "restart":
        result["stop"] = stop_loop(now=now)
        result["start"] = start_loop_detached(interval_minutes, now=now)
    elif action == "start":
        result["start"] = start_loop_detached(interval_minutes, now=now)
    if action != "noop":
        append_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
    return result


def _numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_recent_elapsed(status, elapsed_minutes):
    elapsed_rounded = round(float(elapsed_minutes), 3)
    recent = []
    for value in status.get("recent_iteration_elapsed_minutes") or []:
        numeric = _numeric(value)
        if numeric is not None:
            recent.append(float(numeric))
    recent.append(elapsed_rounded)
    recent = recent[-RECENT_LOOP_CYCLE_COUNT:]
    status["last_iteration_elapsed_minutes"] = elapsed_rounded
    status["recent_iteration_elapsed_minutes"] = recent
    status["max_recent_iteration_elapsed_minutes"] = round(max(recent), 3)


def run_loop(
    force=False,
    interval_minutes=10.0,
    max_iterations=None,
    capture_fn=None,
    sleep_fn=time.sleep,
    now_fn=None,
):
    """Crash-proof managed snapshot loop: a capture failure is logged and the
    loop continues, so collection never silently dies on a transient error. A
    heartbeat + diagnostics record is written every iteration."""
    now_fn = now_fn or (lambda: datetime.now(TORONTO_TZ))
    capture_fn = capture_fn or capture_snapshot
    status = {
        "pid": os.getpid(),
        "started_at": now_fn().isoformat(),
        "runtime_identity": PROCESS_RUNTIME_IDENTITY,
        "interval_minutes": interval_minutes,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "last_snapshot_id": None,
        "last_snapshot_written_at": None,
        "paused": False,
    }
    while True:
        now = now_fn()
        iteration_started = now
        status["iterations"] += 1
        status["last_heartbeat"] = now.isoformat()
        status["paused"] = PAUSE_FLAG_PATH.exists()
        runtime = runtime_identity_status(status.get("runtime_identity"))
        status["runtime_guard"] = runtime
        if runtime.get("runtime_code_state") == "stale_code":
            status["last_error"] = runtime.get("detail")
            status["consecutive_errors"] += 1
            write_loop_status(status)
            append_diagnostic({
                "time": now.isoformat(),
                "status": "stale_code",
                "detail": runtime.get("detail"),
            })
            print(json.dumps({
                "status": "stale_code",
                "time": now.isoformat(),
                "detail": runtime.get("detail"),
            }, sort_keys=True), flush=True)
        elif status["paused"]:
            write_loop_status(status)
            append_diagnostic({"time": now.isoformat(), "status": "paused"})
            print(json.dumps({"status": "paused", "time": now.isoformat()}), flush=True)
        else:
            # Capture every registered market each tick; one market's failure is
            # isolated so it never kills the loop or the other markets.
            market_results = {}
            for spec in all_specs():
                try:
                    status["last_market_in_progress"] = spec.id
                    status["last_heartbeat"] = now_fn().isoformat()
                    write_loop_status(status)
                    result = capture_fn(force=force, market_id=spec.id)
                    market_results[spec.id] = result
                    progress_now = now_fn()
                    status["last_heartbeat"] = progress_now.isoformat()
                    if result.get("written"):
                        status["last_snapshot_id"] = result.get("snapshot_id")
                        status["last_snapshot_written_at"] = progress_now.isoformat()
                except Exception as exc:  # noqa: BLE001 - keep the loop alive
                    market_results[spec.id] = {"error": f"{type(exc).__name__}: {exc}"}
                    status["last_heartbeat"] = now_fn().isoformat()
                status["last_market_results"] = {
                    mid: {
                        "written": bool(result.get("written")),
                        "snapshot_id": result.get("snapshot_id"),
                        "error": result.get("error"),
                    }
                    for mid, result in market_results.items()
                }
                write_loop_status(status)
            errors = {mid: r["error"] for mid, r in market_results.items() if r.get("error")}
            if errors:
                status["consecutive_errors"] += 1
                status["last_error"] = "; ".join(f"{mid}: {err}" for mid, err in errors.items())
            else:
                status["consecutive_errors"] = 0
                status["last_error"] = None
            status["last_market_in_progress"] = None
            elapsed_minutes = (now_fn() - iteration_started).total_seconds() / 60.0
            _record_recent_elapsed(status, elapsed_minutes)
            try:
                fleet_health = current_fleet_collection_health(
                    now=now_fn(),
                    interval_minutes=interval_minutes,
                )
                status["fleet_collection"] = {
                    "schema_version": fleet_health.get("schema_version"),
                    "summary": fleet_health.get("summary"),
                    "attention_markets": [
                        row["market_id"]
                        for row in fleet_health.get("markets", [])
                        if row.get("action_required")
                    ],
                }
            except Exception as exc:  # noqa: BLE001 - observability must not kill collection
                status["fleet_collection"] = {
                    "error": f"{type(exc).__name__}: {exc}",
                }
            write_loop_status(status)
            append_diagnostic({
                "time": now.isoformat(),
                "markets": {
                    mid: {"written": bool(r.get("written")), "snapshot_id": r.get("snapshot_id"), "error": r.get("error")}
                    for mid, r in market_results.items()
                },
            })
            print(json.dumps({
                "time": now.isoformat(),
                "markets": {mid: {"written": bool(r.get("written")), "snapshot_id": r.get("snapshot_id")} for mid, r in market_results.items()},
            }, sort_keys=True), flush=True)
        elapsed_seconds = (now_fn() - iteration_started).total_seconds()
        sleep_seconds = max(1.0, interval_minutes * 60.0 - elapsed_seconds)
        status["last_sleep_seconds"] = round(sleep_seconds, 1)
        write_loop_status(status)
        if max_iterations is not None and status["iterations"] >= max_iterations:
            return status
        sleep_fn(sleep_seconds)


def main():
    # Under pythonw.exe (the windowless interpreter the supervisor task uses so
    # no console flashes every 10 minutes) sys.stdout/stderr are None and any
    # print would crash. Route them to devnull; file/JSONL logging is unaffected.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Capture Toronto weather-market model/market odds snapshots."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write even if the 10-minute interval has not elapsed.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously and check for due snapshots every interval.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=10.0,
        help="Loop interval in minutes.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the managed loop's health (from the heartbeat) and exit.",
    )
    parser.add_argument(
        "--status-tolerance",
        type=float,
        default=1.5,
        help="Collection gap tolerance multiplier used by --status.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Terminate the managed loop process recorded in loop_status.json.",
    )
    parser.add_argument(
        "--start-detached",
        action="store_true",
        help="Start the loop as a detached background process (refuses if one is healthy).",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Stop the managed loop (if alive) and start a fresh detached one with current code.",
    )
    parser.add_argument(
        "--ensure",
        action="store_true",
        help="Supervisor check: start/restart the loop only if it is dead or hung. "
             "Run this from Task Scheduler every few minutes.",
    )
    parser.add_argument(
        "--backfill-source-status",
        action="store_true",
        help="Rebuild source_status_long.csv/jsonl from replay_inputs.jsonl under --snapshots-root.",
    )
    parser.add_argument(
        "--snapshots-root",
        default=str(SNAPSHOT_DATA_ROOT),
        help="Snapshot root used by --backfill-source-status.",
    )
    parser.add_argument(
        "--overwrite-source-status",
        action="store_true",
        help="Overwrite existing source_status_long.csv/jsonl during --backfill-source-status.",
    )
    args = parser.parse_args()

    if args.status:
        health = loop_health(read_loop_status(), datetime.now(TORONTO_TZ), args.interval_minutes)
        health["collection"] = current_collection_health(
            interval_minutes=args.interval_minutes,
            tolerance=args.status_tolerance,
        )
        health["fleet_collection"] = current_fleet_collection_health(
            interval_minutes=args.interval_minutes,
            tolerance=args.status_tolerance,
        )
        print(json.dumps(health, indent=2, sort_keys=True, default=str))
        return
    if args.stop:
        print(json.dumps(stop_loop(), indent=2, sort_keys=True))
        return
    if args.restart:
        result = {"stop": stop_loop(), "start": start_loop_detached(args.interval_minutes)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.start_detached:
        health = loop_health(read_loop_status(), datetime.now(TORONTO_TZ), args.interval_minutes)
        if health["state"] in ("RUNNING", "PAUSED", "ERRORING") and pid_is_python(health.get("pid")):
            print(json.dumps({"started": False, "reason": f"loop already {health['state']}"}, indent=2))
            return
        print(json.dumps(start_loop_detached(args.interval_minutes), indent=2, sort_keys=True))
        return
    if args.ensure:
        print(json.dumps(ensure_loop(args.interval_minutes), indent=2, sort_keys=True, default=str))
        return
    if args.backfill_source_status:
        print(json.dumps(
            backfill_source_status(args.snapshots_root, overwrite=args.overwrite_source_status),
            indent=2,
            sort_keys=True,
            default=str,
        ))
        return
    if not args.loop:
        print(json.dumps(capture_snapshot(force=args.force), indent=2, sort_keys=True))
        return

    run_loop(force=args.force, interval_minutes=args.interval_minutes)


if __name__ == "__main__":
    main()
