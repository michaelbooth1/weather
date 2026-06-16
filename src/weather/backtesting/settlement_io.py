"""Settlement labels, daily summaries, and native market-band outcomes."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

from weather.paths import data_path

import pandas as pd

from weather.backtesting.settlement_ledger import (
    ledger_label_for_slug,
    settlement_from_sources as ledger_settlement_from_sources,
)
from weather.market.market_registry import spec_for_slug
from weather.scoring.metrics import missing, safe_float
from weather.sources.daily_summary import native_bucket


DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_DAILY_SUMMARY = data_path() / "wunderground" / "cyyz" / "daily" / "daily_summary.csv"
COMPLETE_DAY_MIN_ROWS = 18


def round_half_up(value):
    if value is None:
        return None
    try:
        return int(math.floor(float(value) + 0.5))
    except (TypeError, ValueError):
        return None


def band_value_hi(range_label, value, explicit=None):
    """Upper value of a band from its label ('76-77F' -> 77); single bands -> value."""
    explicit_value = safe_float(explicit)
    if explicit_value is not None:
        return int(explicit_value) if abs(explicit_value - round(explicit_value)) < 1e-9 else explicit_value
    numbers = re.findall(r"\d+", str(range_label or ""))
    return int(numbers[-1]) if len(numbers) >= 2 else value


def row_band_value_hi(row):
    explicit = row.get("bin_value_hi_c")
    if missing(explicit) or explicit == "":
        explicit = row.get("bin_value_hi")
    return band_value_hi(row.get("range_label"), row.get("bin_value_c"), explicit=explicit)


def resolve_outcome(kind, value, settlement_bucket, value_hi=None):
    """Resolve whether a native-unit market band settled YES (1) or NO (0)."""
    if settlement_bucket is None or kind is None or value is None:
        return None
    value = int(value)
    settlement_bucket = int(settlement_bucket)
    value_hi = int(value_hi) if value_hi is not None else value
    if kind == "lte":
        return 1 if settlement_bucket <= value else 0
    if kind == "gte":
        return 1 if settlement_bucket >= value else 0
    return 1 if value <= settlement_bucket <= value_hi else 0


def load_daily_summary(path):
    """date -> (native settlement bucket, row_count) from WU daily summary."""
    index = {}
    if not Path(path).exists():
        return index
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            d = row.get("local_date")
            bucket = native_bucket(row)
            if not d or bucket is None:
                continue
            try:
                index[d] = (int(bucket), int(row.get("row_count") or 0))
            except (TypeError, ValueError):
                continue
    return index


def settlement_for_tape(df, target_date, daily_index, overrides):
    """Return (bucket, source, note) for a settlement-scored snapshot tape."""
    event_slug = None
    if "event_slug" in df:
        values = df["event_slug"].dropna().astype(str)
        event_slug = next((value for value in values if value), None)
    iso = target_date.isoformat() if target_date else None
    if event_slug and iso not in (overrides or {}) and event_slug not in (overrides or {}):
        spec = spec_for_slug(event_slug)
        market_key = f"{spec.id}:{iso}" if spec and iso else None
        if not market_key or market_key not in (overrides or {}):
            label = ledger_label_for_slug(event_slug)
            if label and label.get("settlement_bucket") is not None:
                source = label.get("settlement_source") or "unknown"
                status = label.get("reconciliation_status") or "unknown"
                note = label.get("note") or ""
                if status and status != "not_requested":
                    note = f"{note}; polymarket_reconciliation={status}" if note else f"polymarket_reconciliation={status}"
                return int(label["settlement_bucket"]), f"settlement_ledger:{source}", note

    ledger_result = ledger_settlement_from_sources(
        df,
        target_date,
        daily_index,
        overrides=overrides,
        spec=spec_for_slug(event_slug),
        event_slug=event_slug,
    )
    if ledger_result["bucket"] is not None or ledger_result["source"] == "none":
        return ledger_result["bucket"], ledger_result["source"], ledger_result["note"]

    snapshot_high = None
    if "wu_history_high_c" in df:
        snapshot_high = round_half_up(pd.to_numeric(df["wu_history_high_c"], errors="coerce").max())
    summary = daily_index.get(iso)

    note_bits = []
    if summary is not None and snapshot_high is not None and summary[0] != snapshot_high:
        note_bits.append(
            f"daily_summary={summary[0]} (rows={summary[1]}) disagrees with snapshot high={snapshot_high}"
        )

    if iso in overrides:
        return overrides[iso], "override", "; ".join(note_bits) or "manual override"
    if summary is not None and summary[1] >= COMPLETE_DAY_MIN_ROWS:
        return summary[0], "daily_summary", "; ".join(note_bits)
    if snapshot_high is not None:
        reason = "snapshot wu_history_high (daily summary missing/incomplete)"
        return snapshot_high, "snapshot_high", "; ".join(note_bits) or reason
    if summary is not None:
        return summary[0], "daily_summary(sparse)", "; ".join(note_bits)
    return None, "none", "no settlement available"


def load_market_day_label(folder):
    slug = Path(folder).name
    label = ledger_label_for_slug(slug)
    if label and ledger_label_matches_folder(label, folder):
        return label
    path = Path(folder) / "settlement.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def ledger_label_matches_folder(label, folder):
    tape_path = label.get("snapshot_tape_path")
    if not tape_path:
        return True
    try:
        return Path(tape_path).resolve() == (Path(folder) / "snapshots_long.csv").resolve()
    except OSError:
        return False

