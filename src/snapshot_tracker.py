import argparse
import csv
import json
import os
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
from collection_health import serialize_summary, summarize_folder  # noqa: E402
from feature_store import FEATURE_AUDIT_COLUMNS, audit_row
from market_config import config_for_date, config_from_event
from market_registry import DEFAULT_MARKET_ID, all_specs
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


LONG_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "event_updated_at",
    "model_version",
    "top_temp_c",
    "top_probability",
    "range_label",
    "bin_kind",
    "bin_value_c",
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
    "eccc_forecast_high_c",
]

COMPONENT_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "model_version",
    "component_schema_version",
    "cutoff_hour",
    "active_model_kind",
    "component_name",
    "range_label",
    "bin_kind",
    "bin_value_c",
    "component_probability",
    "market_yes",
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
        self.replay_inputs_path = self.root / "replay_inputs.jsonl"

    def maybe_write(self, event, model, model_client, force=False):
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
            if not force and not self.is_due(now):
                return {
                    "written": False,
                    "path": str(self.long_path),
                    "next_due_at": self.next_due_at(),
                }
            return self.write(event, model, model_client, now)
        finally:
            self.release_lock(lock_handle)

    def write(self, event, model, model_client, captured_at):
        event_config = config_from_event(event)
        if not self.fixed_root and event_config.event_slug != self.event_slug:
            self._set_paths(None, event_config.event_slug)
        self.root.mkdir(parents=True, exist_ok=True)
        snapshot_id = captured_at.strftime("%Y%m%dT%H%M%S%z")
        distribution = model.get("distribution", {}) or {}
        model_version = model.get("model_version") or MODEL_VERSION
        top_temp = model.get("top_temp")
        top_probability = distribution.get(top_temp) if top_temp is not None else None
        sources = model.get("sources", {}) or {}
        source_values = self.source_values(sources, model_client)

        bins = model_client.market_bins(event)
        long_rows = []
        for bin_data in bins:
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
                "top_temp_c": top_temp,
                "top_probability": top_probability,
                "range_label": bin_data.get("label"),
                "bin_kind": bin_data.get("kind"),
                "bin_value_c": bin_data.get("value"),
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
            "top_temp_c": top_temp,
            "top_probability": top_probability,
            "distribution": distribution,
            "distribution_components": model.get("distribution_components"),
            "source_values": source_values,
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

        self.write_replay_input(snapshot_id, captured_at, model, model_client, model_version)

        return {
            "written": True,
            "snapshot_id": snapshot_id,
            "bands": len(long_rows),
            "path": str(self.long_path),
            "wide_path": str(self.wide_path),
            "jsonl_path": str(self.jsonl_path),
            "features_path": str(self.features_long_path),
            "components_path": str(self.components_long_path),
            "next_due_at": self.next_due_at(captured_at),
        }

    def is_due(self, now):
        last = self.last_snapshot_time()
        return last is None or now - last >= self.interval

    def last_snapshot_time(self):
        if not self.long_path.exists():
            return None
        last_time = None
        with self.long_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                value = row.get("captured_at_local")
                if value:
                    try:
                        last_time = datetime.fromisoformat(value)
                    except ValueError:
                        continue
        return last_time

    def next_due_at(self, from_time=None):
        base = from_time or self.last_snapshot_time()
        if base is None:
            return None
        return (base + self.interval).isoformat()

    def source_values(self, sources, model_client):
        history = model_client.source_data(sources, "wu_history")
        current = model_client.source_data(sources, "wu_current")
        eccc = model_client.source_data(sources, "eccc_swob")
        weather_forecast = model_client.source_data(sources, "weather_forecast")
        open_meteo = model_client.source_data(sources, "open_meteo")
        eccc_city = model_client.source_data(sources, "eccc_citypage")
        return {
            "wu_history_high_c": history.get("max_c"),
            "wu_current_c": current.get("temp_c"),
            "wu_max_since_7am_c": current.get("max_since_7am_c"),
            "eccc_swob_max_c": eccc.get("same_day_max_c"),
            "weather_forecast_max_c": model_client.max_row_temp(
                weather_forecast.get("rows")
            ),
            "open_meteo_max_c": model_client.max_row_temp(open_meteo.get("rows")),
            "eccc_forecast_high_c": eccc_city.get("forecast_high_c"),
        }

    def component_rows(self, bundle, bins, snapshot_id, captured_at, model_version):
        bundle = bundle or {}
        components = bundle.get("components") or {}
        if not components or not bins:
            return []
        base = {
            "snapshot_id": snapshot_id,
            "captured_at_utc": captured_at.astimezone(timezone.utc).isoformat(),
            "captured_at_local": captured_at.isoformat(),
            "event_slug": self.event_slug,
            "model_version": model_version,
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
        items = {
            int(float(bucket)): float(probability)
            for bucket, probability in distribution.items()
            if probability is not None
        }
        if kind == "lte":
            return sum(prob for temp, prob in items.items() if temp <= value)
        if kind == "gte":
            return sum(prob for temp, prob in items.items() if temp >= value)
        return items.get(value, 0.0)

    def wide_columns(self, long_rows):
        columns = [
            "snapshot_id",
            "captured_at_utc",
            "captured_at_local",
            "event_slug",
            "event_updated_at",
            "model_version",
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
        if kind == "lte":
            return f"lte_{value}c"
        if kind == "gte":
            return f"gte_{value}c"
        return f"eq_{value}c"

    def append_csv(self, path, columns, rows):
        write_header = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def append_jsonl(self, path, payload):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def write_replay_input(self, snapshot_id, captured_at, model, model_client, model_version):
        """Persist the full model inputs for this snapshot so it can be replayed.

        The merged ``sources`` dict is exactly what ``estimate_distribution`` consumes
        (it is pure given sources + the build ``now``), and it is already
        JSON-serializable. ``recorded_distribution`` is kept alongside as a fidelity
        canary: replaying with the same code version must reproduce it.
        """
        sources = model.get("sources")
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


def capture_snapshot(force=False, market_id=DEFAULT_MARKET_ID):
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
    )


SNAPSHOT_DATA_ROOT = Path("data") / "snapshots"
PAUSE_FLAG_PATH = SNAPSHOT_DATA_ROOT / "loop_pause.flag"
LOOP_STATUS_PATH = SNAPSHOT_DATA_ROOT / "loop_status.json"
DIAGNOSTICS_PATH = SNAPSHOT_DATA_ROOT / "diagnostics.jsonl"


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


def loop_health(status, now, interval_minutes=10.0):
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
    if status.get("paused"):
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


def run_loop(force=False, interval_minutes=10.0):
    """Crash-proof managed snapshot loop: a capture failure is logged and the
    loop continues, so collection never silently dies on a transient error. A
    heartbeat + diagnostics record is written every iteration."""
    status = {
        "pid": os.getpid(),
        "started_at": datetime.now(TORONTO_TZ).isoformat(),
        "interval_minutes": interval_minutes,
        "iterations": 0,
        "consecutive_errors": 0,
        "last_error": None,
        "last_snapshot_id": None,
        "last_snapshot_written_at": None,
        "paused": False,
    }
    while True:
        now = datetime.now(TORONTO_TZ)
        status["iterations"] += 1
        status["last_heartbeat"] = now.isoformat()
        status["paused"] = PAUSE_FLAG_PATH.exists()
        if status["paused"]:
            write_loop_status(status)
            append_diagnostic({"time": now.isoformat(), "status": "paused"})
            print(json.dumps({"status": "paused", "time": now.isoformat()}), flush=True)
        else:
            # Capture every registered market each tick; one market's failure is
            # isolated so it never kills the loop or the other markets.
            market_results = {}
            for spec in all_specs():
                try:
                    market_results[spec.id] = capture_snapshot(force=force, market_id=spec.id)
                except Exception as exc:  # noqa: BLE001 - keep the loop alive
                    market_results[spec.id] = {"error": f"{type(exc).__name__}: {exc}"}
            errors = {mid: r["error"] for mid, r in market_results.items() if r.get("error")}
            if errors:
                status["consecutive_errors"] += 1
                status["last_error"] = "; ".join(f"{mid}: {err}" for mid, err in errors.items())
            else:
                status["consecutive_errors"] = 0
                status["last_error"] = None
            written = {mid: r.get("snapshot_id") for mid, r in market_results.items() if r.get("written")}
            if written:
                status["last_snapshot_id"] = next(iter(written.values()))
                status["last_snapshot_written_at"] = now.isoformat()
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
        time.sleep(max(1.0, interval_minutes * 60))


def main():
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
    args = parser.parse_args()

    if args.status:
        health = loop_health(read_loop_status(), datetime.now(TORONTO_TZ), args.interval_minutes)
        health["collection"] = current_collection_health(
            interval_minutes=args.interval_minutes,
            tolerance=args.status_tolerance,
        )
        print(json.dumps(health, indent=2, sort_keys=True, default=str))
        return
    if not args.loop:
        print(json.dumps(capture_snapshot(force=args.force), indent=2, sort_keys=True))
        return

    run_loop(force=args.force, interval_minutes=args.interval_minutes)


if __name__ == "__main__":
    main()
