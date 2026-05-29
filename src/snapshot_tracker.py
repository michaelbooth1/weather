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
from market_config import config_for_date, config_from_event
from toronto_model import TORONTO_TZ


SNAPSHOT_INTERVAL = timedelta(minutes=10)
DEFAULT_MARKET_CONFIG = config_for_date()
DEFAULT_SNAPSHOT_ROOT = Path("data") / "snapshots" / DEFAULT_MARKET_CONFIG.event_slug
MODEL_VERSION = "v0.4.9 HGBC feature-based ML model"


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
            "source_values": source_values,
            "bands": long_rows,
        })

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

        return {
            "written": True,
            "snapshot_id": snapshot_id,
            "bands": len(long_rows),
            "path": str(self.long_path),
            "wide_path": str(self.wide_path),
            "jsonl_path": str(self.jsonl_path),
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
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

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


def capture_snapshot(force=False):
    from polymarket_client import PolymarketClient
    from toronto_model import TorontoHighTempModel

    market_client = PolymarketClient()
    event = market_client.get_toronto_weather_event()
    event_config = config_from_event(event, fallback_date=market_client.config.target_date)
    model_client = TorontoHighTempModel(target_date=event_config.target_date)
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
    args = parser.parse_args()
    if not args.loop:
        print(json.dumps(capture_snapshot(force=args.force), indent=2, sort_keys=True))
        return

    while True:
        pause_flag = Path("data") / "snapshots" / "loop_pause.flag"
        if pause_flag.exists():
            print(json.dumps({"status": "paused", "reason": "pause flag file exists", "time": datetime.now().isoformat()}), flush=True)
        else:
            result = capture_snapshot(force=args.force)
            print(json.dumps(result, sort_keys=True), flush=True)
        time.sleep(max(1.0, args.interval_minutes * 60))


if __name__ == "__main__":
    main()
