"""Offline CLOB book recon and reward-competition analytics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.io import normalize_csv_row, read_csv_rows as io_read_csv_rows
from weather.paths import data_path

from weather.market.market_config import date_from_event_slug
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("clob_book_recon")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "clob_book_recon.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "clob_book_recon.md"
DEFAULT_SLICES_OUT = DEFAULT_BACKTEST_ROOT / "clob_book_recon_slices.csv"

DEFAULT_CONFIG = {
    "reward_distance_threshold": 0.045,
    "quote_size": 5.0,
    "executable_sizes": [10, 100],
    "toxicity_horizons_seconds": [30, 300],
    "near_settlement_minutes": 60,
    "min_recon_rows_for_policy": 3,
    "max_quote_size_usdc": 25.0,
}

SLICE_COLUMNS = [
    "schema_version",
    "market_id",
    "event_slug",
    "target_date",
    "hour_utc",
    "range_label",
    "side",
    "book_rows",
    "first_capture_utc",
    "last_capture_utc",
    "mean_spread",
    "mean_midpoint",
    "mean_top_size",
    "mean_reward_qualifying_size",
    "mean_depth_all",
    "mean_executable_price",
    "executable_coverage",
    "mean_refresh_cadence_seconds",
    "mean_top_lifetime_seconds",
    "mean_spread_turnover",
    "mean_depth_turnover",
    "near_settlement_depth_collapse",
    "passive_trade_count",
    "mean_passive_markout_30s",
    "mean_passive_markout_300s",
    "min_order_size_values",
    "tick_size_values",
    "recommended_permission",
    "permission_reason",
]


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def generated_at_iso(now=None):
    parsed = parse_time(now)
    return (parsed or datetime.now(timezone.utc)).isoformat()


def finite_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def compact_float(value, digits=6):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def mean(values):
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def median(values):
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return statistics.median(clean) if clean else None


def percentile(values, pct):
    clean = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * float(pct)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return clean[lo]
    return clean[lo] * (hi - pos) + clean[hi] * (pos - lo)


def read_csv_rows(path):
    return io_read_csv_rows(path, attach_diagnostics=True)


def write_csv(path, fieldnames, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(normalize_csv_row(row) for row in rows)
    return str(path)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def discover_snapshot_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        folder for folder in root.glob("*")
        if folder.is_dir() and (folder / "order_books_summary.csv").exists()
    )


def hour_bucket(value):
    parsed = parse_time(value)
    return f"{parsed.hour:02d}:00Z" if parsed else "unknown"


def target_date_for_row(row):
    parsed = date_from_event_slug(row.get("event_slug") or "")
    if parsed:
        return parsed.isoformat()
    captured = parse_time(row.get("captured_at_utc") or row.get("book_time_utc"))
    return captured.date().isoformat() if captured else ""


def side_fields(row, side, config):
    threshold = float(config["reward_distance_threshold"])
    if side == "YES_BID":
        best = finite_float(row.get("best_bid"))
        top_size = finite_float(row.get("bid_size_at_best"), 0.0) or 0.0
        depth_all = finite_float(row.get("bid_depth_all"), 0.0) or 0.0
        depth_qual = finite_float(row.get("bid_depth_5pct" if threshold > 0.011 else "bid_depth_1pct"), 0.0) or 0.0
        executable_price = executable_price_for_side(row, "sell", config)
    else:
        best = finite_float(row.get("best_ask"))
        top_size = finite_float(row.get("ask_size_at_best"), 0.0) or 0.0
        depth_all = finite_float(row.get("ask_depth_all"), 0.0) or 0.0
        depth_qual = finite_float(row.get("ask_depth_5pct" if threshold > 0.011 else "ask_depth_1pct"), 0.0) or 0.0
        executable_price = executable_price_for_side(row, "buy", config)
    return {
        "best": best,
        "top_size": top_size,
        "depth_all": depth_all,
        "reward_qualifying_size": depth_qual,
        "executable_price": executable_price,
    }


def executable_price_for_side(row, direction, config):
    sizes = [float(value) for value in config.get("executable_sizes") or []]
    if not sizes:
        sizes = [float(config.get("quote_size") or 5.0)]
    size = min(sizes)
    label = str(int(size))
    price = finite_float(row.get(f"{direction}_vwap_{label}"))
    fillable = finite_float(row.get(f"{direction}_fillable_{label}"), 0.0) or 0.0
    if price is not None and fillable >= size:
        return price
    fallback = finite_float(row.get("best_ask" if direction == "buy" else "best_bid"))
    return fallback if fillable > 0 else None


def group_key(row, side):
    return (
        row.get("market_id") or "",
        row.get("event_slug") or "",
        target_date_for_row(row),
        hour_bucket(row.get("captured_at_utc") or row.get("book_time_utc")),
        row.get("range_label") or "",
        side,
    )


def load_book_rows(folders):
    rows = []
    for folder in folders:
        for row in read_csv_rows(Path(folder) / "order_books_summary.csv"):
            if str(row.get("outcome") or "").lower() not in {"yes", ""}:
                continue
            row["_folder"] = str(folder)
            row["_captured_at"] = parse_time(row.get("captured_at_utc") or row.get("book_time_utc"))
            if row["_captured_at"] is None:
                continue
            rows.append(row)
    rows.sort(key=lambda row: (row.get("market_id") or "", row.get("event_slug") or "", row.get("clob_token_id") or "", row["_captured_at"]))
    return rows


def _nearest_before(rows, timestamp):
    candidates = [row for row in rows if row.get("_captured_at") and row["_captured_at"] <= timestamp]
    return candidates[-1] if candidates else None


def _first_after(rows, timestamp):
    for row in rows:
        if row.get("_captured_at") and row["_captured_at"] >= timestamp:
            return row
    return None


def load_trade_like_rows(folders):
    rows = []
    for folder in folders:
        folder = Path(folder)
        for filename in ("market_ws_events.csv", "trades_long.csv", "market_trades.csv"):
            for row in read_csv_rows(folder / filename):
                ts = parse_time(
                    row.get("received_at_utc")
                    or row.get("trade_time_utc")
                    or row.get("timestamp_utc")
                    or row.get("captured_at_utc")
                )
                token = row.get("asset_id") or row.get("clob_token_id") or row.get("token_id")
                price = finite_float(row.get("price") or row.get("trade_price") or row.get("last_trade_price"))
                if ts is None or not token or price is None:
                    continue
                rows.append({
                    "_folder": str(folder),
                    "time": ts,
                    "event_slug": row.get("event_slug") or folder.name,
                    "market_id": row.get("market_id") or "",
                    "clob_token_id": str(token),
                    "price": price,
                    "side": str(row.get("side") or row.get("taker_side") or "").upper(),
                    "source": filename,
                })
    rows.sort(key=lambda row: (row["clob_token_id"], row["time"]))
    return rows


def passive_side_for_trade(trade, book):
    side = trade.get("side")
    if side in {"SELL", "ASK"}:
        return "YES_BID"
    if side in {"BUY", "BID"}:
        return "YES_ASK"
    if book:
        bid = finite_float(book.get("best_bid"))
        ask = finite_float(book.get("best_ask"))
        if bid is not None and trade["price"] <= bid:
            return "YES_BID"
        if ask is not None and trade["price"] >= ask:
            return "YES_ASK"
    return ""


def trade_markout_rows(book_rows, trade_rows, horizons):
    by_token = defaultdict(list)
    for row in book_rows:
        by_token[str(row.get("clob_token_id") or "")].append(row)
    for rows in by_token.values():
        rows.sort(key=lambda row: row["_captured_at"])
    out = []
    for trade in trade_rows:
        books = by_token.get(str(trade.get("clob_token_id") or "")) or []
        prior = _nearest_before(books, trade["time"])
        passive_side = passive_side_for_trade(trade, prior)
        if not prior or not passive_side:
            continue
        item = {
            "market_id": prior.get("market_id") or trade.get("market_id") or "",
            "event_slug": prior.get("event_slug") or trade.get("event_slug") or "",
            "target_date": target_date_for_row(prior),
            "hour_utc": hour_bucket(trade["time"]),
            "range_label": prior.get("range_label") or "",
            "side": passive_side,
            "trade_time_utc": trade["time"].isoformat(),
            "trade_price": trade["price"],
        }
        direction = 1.0 if passive_side == "YES_BID" else -1.0
        for horizon in horizons:
            future = _first_after(books, trade["time"] + timedelta(seconds=float(horizon)))
            future_mid = finite_float((future or {}).get("midpoint"))
            item[f"markout_{int(horizon)}s"] = (
                direction * (future_mid - trade["price"])
                if future_mid is not None
                else None
            )
        out.append(item)
    return out


def aggregate_slices(book_rows, trade_markouts, config):
    grouped = defaultdict(list)
    for row in book_rows:
        for side in ("YES_BID", "YES_ASK"):
            grouped[group_key(row, side)].append(row)
    markouts = defaultdict(list)
    for row in trade_markouts:
        key = (
            row.get("market_id") or "",
            row.get("event_slug") or "",
            row.get("target_date") or "",
            row.get("hour_utc") or "unknown",
            row.get("range_label") or "",
            row.get("side") or "",
        )
        markouts[key].append(row)
    rows = []
    for key, books in grouped.items():
        books.sort(key=lambda row: row["_captured_at"])
        market_id, event_slug, target_date, hour_utc, range_label, side = key
        fields = [side_fields(row, side, config) for row in books]
        times = [row["_captured_at"] for row in books]
        refresh = [
            (times[index] - times[index - 1]).total_seconds()
            for index in range(1, len(times))
        ]
        top_lifetimes = []
        current_best = None
        current_start = None
        for row, values in zip(books, fields):
            best = values["best"]
            if best != current_best:
                if current_start is not None:
                    top_lifetimes.append((row["_captured_at"] - current_start).total_seconds())
                current_best = best
                current_start = row["_captured_at"]
        if current_start is not None and len(books) > 1:
            top_lifetimes.append((books[-1]["_captured_at"] - current_start).total_seconds())
        spreads = [finite_float(row.get("spread")) for row in books]
        depths = [values["depth_all"] for values in fields]
        spread_turnover = [abs(spreads[index] - spreads[index - 1]) for index in range(1, len(spreads)) if spreads[index] is not None and spreads[index - 1] is not None]
        depth_turnover = [abs(depths[index] - depths[index - 1]) for index in range(1, len(depths)) if depths[index] is not None and depths[index - 1] is not None]
        last_capture = max(times)
        near_cutoff = last_capture - timedelta(minutes=float(config["near_settlement_minutes"]))
        near_depth = [values["depth_all"] for row, values in zip(books, fields) if row["_captured_at"] >= near_cutoff]
        earlier_depth = [values["depth_all"] for row, values in zip(books, fields) if row["_captured_at"] < near_cutoff]
        earlier = mean(earlier_depth)
        near = mean(near_depth)
        collapse = None
        if earlier and earlier > 0 and near is not None:
            collapse = max(0.0, (earlier - near) / earlier)
        toxicity = markouts.get(key) or []
        row = {
            "schema_version": SCHEMA_VERSION,
            "market_id": market_id,
            "event_slug": event_slug,
            "target_date": target_date,
            "hour_utc": hour_utc,
            "range_label": range_label,
            "side": side,
            "book_rows": len(books),
            "first_capture_utc": min(times).isoformat(),
            "last_capture_utc": last_capture.isoformat(),
            "mean_spread": compact_float(mean(spreads)),
            "mean_midpoint": compact_float(mean(finite_float(row.get("midpoint")) for row in books)),
            "mean_top_size": compact_float(mean(values["top_size"] for values in fields)),
            "mean_reward_qualifying_size": compact_float(mean(values["reward_qualifying_size"] for values in fields)),
            "mean_depth_all": compact_float(mean(values["depth_all"] for values in fields)),
            "mean_executable_price": compact_float(mean(values["executable_price"] for values in fields)),
            "executable_coverage": compact_float(sum(1 for values in fields if values["executable_price"] is not None) / max(1, len(fields))),
            "mean_refresh_cadence_seconds": compact_float(mean(refresh)),
            "mean_top_lifetime_seconds": compact_float(mean(top_lifetimes)),
            "mean_spread_turnover": compact_float(mean(spread_turnover)),
            "mean_depth_turnover": compact_float(mean(depth_turnover)),
            "near_settlement_depth_collapse": compact_float(collapse),
            "passive_trade_count": len(toxicity),
            "mean_passive_markout_30s": compact_float(mean(row.get("markout_30s") for row in toxicity)),
            "mean_passive_markout_300s": compact_float(mean(row.get("markout_300s") for row in toxicity)),
            "min_order_size_values": ",".join(sorted({str(row.get("min_order_size")) for row in books if row.get("min_order_size") not in (None, "")})),
            "tick_size_values": ",".join(sorted({str(row.get("tick_size")) for row in books if row.get("tick_size") not in (None, "")})),
        }
        permission, reason = permission_from_slice(row)
        row["recommended_permission"] = permission
        row["permission_reason"] = reason
        rows.append(row)
    rows.sort(key=lambda row: (row["market_id"], row["target_date"], row["hour_utc"], row["range_label"], row["side"]))
    return rows


def permission_from_slice(row):
    executable = finite_float(row.get("executable_coverage"), 0.0) or 0.0
    depth = finite_float(row.get("mean_reward_qualifying_size"), 0.0) or 0.0
    markout = finite_float(row.get("mean_passive_markout_300s"))
    if executable < 0.5:
        return "no_quote", "executable_depth_missing"
    if depth <= 0:
        return "harvest_only", "reward_competition_unmeasured"
    if markout is not None and markout < -0.005:
        return "harvest_only", "passive_flow_toxic"
    return "harvest_only", "measured_harvest_window"


def summarize_payload(slice_rows, book_rows, trade_markouts, config):
    reward_depths = [finite_float(row.get("mean_reward_qualifying_size")) for row in slice_rows]
    spreads = [finite_float(row.get("mean_spread")) for row in slice_rows]
    refresh = [finite_float(row.get("mean_refresh_cadence_seconds")) for row in slice_rows]
    toxicity = [finite_float(row.get("mean_passive_markout_300s")) for row in slice_rows]
    permission_counts = Counter(row.get("recommended_permission") for row in slice_rows)
    quote_size = percentile(reward_depths, 0.2)
    if quote_size is None:
        quote_size = float(config["quote_size"])
    quote_size = min(float(config["quote_size"]), max(0.0, quote_size), float(config["max_quote_size_usdc"]))
    half_spread = median(spreads)
    if half_spread is not None:
        half_spread = max(0.001, min(0.05, half_spread / 2.0))
    suggestions = {
        "quote_size": compact_float(quote_size),
        "harvest_half_spread": compact_float(half_spread),
        "min_depth_1pct_total": compact_float(max(1.0, percentile(reward_depths, 0.1) or 1.0)),
        "reward_competitor_q": compact_float(max(0.0, median(reward_depths) or 0.0)),
    }
    return {
        "book_rows": len(book_rows),
        "slice_rows": len(slice_rows),
        "passive_trade_markout_rows": len(trade_markouts),
        "market_count": len({row.get("market_id") for row in slice_rows if row.get("market_id")}),
        "event_count": len({row.get("event_slug") for row in slice_rows if row.get("event_slug")}),
        "mean_reward_qualifying_size": compact_float(mean(reward_depths)),
        "median_reward_qualifying_size": compact_float(median(reward_depths)),
        "mean_spread": compact_float(mean(spreads)),
        "mean_refresh_cadence_seconds": compact_float(mean(refresh)),
        "mean_passive_markout_300s": compact_float(mean(toxicity)),
        "permission_counts": dict(sorted(permission_counts.items())),
        "policy_parameter_suggestions": suggestions,
        "config_hash": hashlib.sha1(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:12],
    }


def build_recon_payload(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    folders=None,
    config=None,
    now=None,
):
    config = {**DEFAULT_CONFIG, **(config or {})}
    folders = [Path(item) for item in (folders or discover_snapshot_folders(snapshots_root))]
    book_rows = load_book_rows(folders)
    trade_rows = load_trade_like_rows(folders)
    horizons = config.get("toxicity_horizons_seconds") or [30, 300]
    trade_markouts = trade_markout_rows(book_rows, trade_rows, horizons)
    slice_rows = aggregate_slices(book_rows, trade_markouts, config)
    summary = summarize_payload(slice_rows, book_rows, trade_markouts, config)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_iso(now),
        "snapshots_root": str(snapshots_root),
        "folders": [str(folder) for folder in folders],
        "config": config,
        "summary": summary,
        "policy_parameter_suggestions": summary["policy_parameter_suggestions"],
        "slices": slice_rows,
        "passive_trade_markouts": trade_markouts[:500],
    }


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines


def render_recon_report(payload):
    summary = payload.get("summary") or {}
    suggestions = payload.get("policy_parameter_suggestions") or {}
    lines = [
        "# CLOB Book Recon Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Book rows", summary.get("book_rows")],
            ["Slice rows", summary.get("slice_rows")],
            ["Passive trade markouts", summary.get("passive_trade_markout_rows")],
            ["Mean reward qualifying size", summary.get("mean_reward_qualifying_size")],
            ["Mean spread", summary.get("mean_spread")],
            ["Mean 300s passive markout", summary.get("mean_passive_markout_300s")],
        ],
    ))
    lines.extend(["", "## Policy Parameter Suggestions", ""])
    lines.extend(markdown_table(
        ["Parameter", "Value"],
        [[key, value] for key, value in sorted(suggestions.items())],
    ))
    lines.extend(["", "## Top Slices", ""])
    slice_rows = sorted(
        payload.get("slices") or [],
        key=lambda row: (
            -(finite_float(row.get("mean_reward_qualifying_size"), 0.0) or 0.0),
            row.get("market_id") or "",
            row.get("hour_utc") or "",
        ),
    )[:40]
    lines.extend(markdown_table(
        ["Market", "Hour", "Band", "Side", "Reward size", "Executable", "300s markout", "Permission"],
        [
            [
                row.get("market_id"),
                row.get("hour_utc"),
                row.get("range_label"),
                row.get("side"),
                row.get("mean_reward_qualifying_size"),
                row.get("executable_coverage"),
                row.get("mean_passive_markout_300s"),
                row.get("recommended_permission"),
            ]
            for row in slice_rows
        ],
    ))
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT, slices_out=DEFAULT_SLICES_OUT):
    outputs = {
        "json": write_json(json_out, payload),
        "report": str(report_out),
        "slices_csv": write_csv(slices_out, SLICE_COLUMNS, payload.get("slices") or []),
    }
    Path(report_out).parent.mkdir(parents=True, exist_ok=True)
    Path(report_out).write_text(render_recon_report(payload), encoding="utf-8")
    payload["outputs"] = outputs
    write_json(json_out, payload)
    return payload


def load_recon_payload(path=DEFAULT_JSON_OUT):
    path = Path(path)
    payload = read_json(path, {}) or {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "path": str(path),
        "exists": path.exists(),
        "schema_version": payload.get("schema_version"),
        "summary": payload.get("summary") or {},
        "policy_parameter_suggestions": payload.get("policy_parameter_suggestions") or {},
        "slices": payload.get("slices") or [],
    }


def policy_overrides_from_recon(path=DEFAULT_JSON_OUT, enabled=False):
    """Read bounded research suggestions only after an explicit opt-in.

    This historical report is not a current, market-scoped policy proposal.
    Its optional use must never be mistaken for qualified automatic adoption.
    """
    if not enabled:
        return {}, {"enabled": False, "exists": False, "reason": "disabled"}
    payload = load_recon_payload(path)
    diagnostics = {
        "enabled": True,
        "exists": payload.get("exists", False),
        "path": payload.get("path"),
        "schema_version": payload.get("schema_version"),
        "applied_keys": [],
        "research_only": True,
        "current_scope_verified": False,
    }
    if not payload.get("exists") or payload.get("schema_version") != SCHEMA_VERSION:
        return {}, {**diagnostics, "reason": "missing or unsupported research report"}
    suggestions = payload.get("policy_parameter_suggestions") or {}
    if not isinstance(suggestions, dict):
        return {}, {**diagnostics, "reason": "invalid research suggestions"}
    allowed = {"quote_size", "harvest_half_spread", "min_depth_1pct_total"}
    overrides = {}
    for key, value in suggestions.items():
        if key not in allowed:
            continue
        number = finite_float(value)
        if (isinstance(value, bool) or number is None or number < 0
                or (key != "min_depth_1pct_total" and number == 0)
                or (key == "harvest_half_spread" and number >= 0.5)):
            return {}, {**diagnostics, "reason": "invalid research parameter bounds"}
        overrides[key] = number
    return overrides, {
        **diagnostics,
        "applied_keys": sorted(overrides),
        "summary": payload.get("summary") or {},
        "reason": "explicit research opt-in; current market scope and expiry are unverified",
    }


def parse_config_overrides(items):
    config = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --config override {item!r}; expected key=value")
        key, value = item.split("=", 1)
        if key not in DEFAULT_CONFIG:
            raise SystemExit(f"Unknown recon config key {key!r}")
        default = DEFAULT_CONFIG[key]
        if isinstance(default, list):
            config[key] = [float(part.strip()) for part in value.split(",") if part.strip()]
        elif isinstance(default, (int, float)):
            config[key] = float(value)
        else:
            config[key] = value
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build CLOB book recon and reward-competition analytics.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--folder", action="append", default=[], help="Specific snapshot folder to include.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--slices-out", default=str(DEFAULT_SLICES_OUT))
    parser.add_argument("--now", default=None)
    parser.add_argument("--config", action="append", default=[])
    args = parser.parse_args(argv)

    payload = build_recon_payload(
        snapshots_root=args.snapshots_root,
        folders=args.folder or None,
        config=parse_config_overrides(args.config),
        now=args.now,
    )
    payload = write_outputs(payload, json_out=args.json_out, report_out=args.report_out, slices_out=args.slices_out)
    print(
        "CLOB recon: "
        f"{payload['summary']['book_rows']} book rows, "
        f"{payload['summary']['slice_rows']} slices -> {payload['outputs']['json']}"
    )
    return payload


if __name__ == "__main__":
    main()
