"""Fleet-wide model-vs-market disagreement casebook.

The casebook turns live edge episodes into durable cases that can be revisited
after settlement.  It is intentionally built from append-only artifacts:
snapshot tapes, replay inputs, component tapes, CLOB book summaries, and the
settlement ledger/folder labels.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

from weather.scoring.metrics import brier
from weather.scoring.trading import trade_pnl
from weather.reporting.formatting import (
    fmt_num,
    fmt_signed,
    markdown_table,
)
from weather.backtesting.settlement_ledger import ledger_label_for_slug
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.model.model_presentation import DRIVER_WATERFALL_STAGES


SCHEMA_VERSION = "disagreement_casebook_v0.1"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "disagreement_casebook.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "disagreement_casebook_report.md"
DEFAULT_OPERATOR_OUT = DEFAULT_BACKTEST_ROOT / "disagreement_operator_report.md"

DEFAULT_EDGE_THRESHOLD = 0.10
DEFAULT_MARKET_COLLAPSE_PRICE = 0.02
DEFAULT_MARKET_COLLAPSE_DROP = 0.15
DEFAULT_MODEL_HIGH_PROB = 0.10
DEFAULT_MODEL_JUMP_THRESHOLD = 0.10
DEFAULT_SOURCE_SUPPORT_DELTA = 0.50
DEFAULT_CLOB_MIDPOINT_MOVE = 0.05
DEFAULT_MAX_EPISODE_GAP_MINUTES = 30.0
DEFAULT_MAX_CLOB_AGE_SECONDS = 180.0
DEFAULT_PNL_THRESHOLD = 0.05
LATE_DAY_WARM_SIDE_SCHEMA_VERSION = "late_day_warm_side_cases_v0.1"
LATE_DAY_WARM_SIDE_START_HOUR = 14
LATE_DAY_HEATING_WINDOW_END_HOUR = 18
SOURCE_UNAVAILABLE_STATUSES = {
    "failed",
    "stale_cache",
    "rate_limited",
    "rate_limited_cache",
}
FORECAST_SOURCE_NAMES = {
    "weather_forecast",
    "open_meteo",
    "open_meteo_multimodel",
    "open_meteo_global_models",
    "nws_hourly",
    "nws_grid",
    "nbm_probabilistic_tmax",
    "global_ensemble",
    "eccc_citypage",
    "eccc_gem",
}
OPEN_METEO_SOURCE_NAMES = {"open_meteo", "open_meteo_multimodel", "open_meteo_global_models"}

SNAPSHOT_FILENAME = "snapshots_long.csv"
COMPONENT_FILENAME = "components_long.csv"
REPLAY_INPUTS_FILENAME = "replay_inputs.jsonl"
BOOK_SUMMARY_FILENAME = "order_books_summary.csv"
SETTLEMENT_FILENAME = "settlement.json"

LIVE_OBS_COLUMNS = (
    "wu_history_high_c",
    "wu_current_c",
    "wu_max_since_7am_c",
    "eccc_swob_max_c",
)
FORECAST_COLUMNS = (
    "weather_forecast_max_c",
    "open_meteo_max_c",
    "nws_forecast_max_c",
    "global_ensemble_max_c",
    "eccc_forecast_high_c",
)
SOURCE_VALUE_COLUMNS = LIVE_OBS_COLUMNS + FORECAST_COLUMNS + (
    "forecast_source_count",
    "forecast_disagreement",
)
RUNNING_STAGE_ORDER = [key for key, _label in DRIVER_WATERFALL_STAGES]
RUNNING_STAGE_LABELS = dict(DRIVER_WATERFALL_STAGES)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def maybe_int(value):
    number = maybe_float(value)
    if number is None:
        return None
    return int(round(number))


def parse_time(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_utc_timestamp(value):
    parsed = parse_time(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).timestamp()


def minutes_between(a, b):
    if a is None or b is None:
        return None
    return abs((b - a).total_seconds()) / 60.0


def label_numbers(label):
    import re

    return [int(value) for value in re.findall(r"\d+", str(label or ""))]


def clean_label(label):
    if label is None:
        return None
    text = str(label)
    for unit in ("C", "F"):
        replacements = (
            f"\u00c3\u201a\u00c2\u00b0{unit}",
            f"\u00c2\u00b0{unit}",
            f"\u00ef\u00bf\u00bd{unit}",
            f"\ufffd{unit}",
            f"\u00b0{unit}",
        )
        for bad in replacements:
            text = text.replace(bad, f" {unit}")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def band_key(row):
    kind = (row.get("bin_kind") or row.get("kind") or "").lower()
    value = maybe_int(row.get("bin_value_c") or row.get("bin_value") or row.get("value"))
    value_hi = maybe_int(row.get("bin_value_hi") or row.get("value_hi"))
    nums = label_numbers(row.get("range_label"))
    if value is None and nums:
        value = nums[0]
    if value_hi is None:
        if kind == "eq" and len(nums) >= 2:
            value_hi = nums[-1]
        else:
            value_hi = value
    return kind, value, value_hi


def band_key_text(key):
    kind, value, value_hi = key
    if kind == "eq" and value_hi not in (None, value):
        return f"{kind}:{value}-{value_hi}"
    return f"{kind}:{value}"


def direction_for_edge(edge):
    if edge is None:
        return "unknown"
    if edge > 0:
        return "model_yes"
    if edge < 0:
        return "model_no"
    return "flat"


def edge_value(row):
    edge = maybe_float(row.get("edge"))
    if edge is not None:
        return edge
    model_p = maybe_float(row.get("model_probability"))
    market_p = maybe_float(row.get("market_yes"))
    if model_p is None or market_p is None:
        return None
    return model_p - market_p


def source_values(row):
    return {column: maybe_float(row.get(column)) for column in SOURCE_VALUE_COLUMNS if column in row}


def max_live_observation(row):
    values = [
        maybe_float(row.get(column))
        for column in LIVE_OBS_COLUMNS
        if maybe_float(row.get(column)) is not None
    ]
    return max(values) if values else None


def forecast_consensus(row):
    values = [
        maybe_float(row.get(column))
        for column in FORECAST_COLUMNS
        if maybe_float(row.get(column)) is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def band_outcome(row, settlement_bucket):
    if settlement_bucket is None:
        return None
    kind, value, value_hi = band_key(row)
    if value is None:
        return None
    if kind == "lte":
        return int(settlement_bucket <= value)
    if kind == "gte":
        return int(settlement_bucket >= value)
    if value_hi is None:
        value_hi = value
    return int(value <= settlement_bucket <= value_hi)


def stable_case_id(event_slug, market_id, key, direction, start_snapshot_id):
    digest = hashlib.sha1(
        "|".join([
            str(event_slug),
            str(market_id),
            band_key_text(key),
            str(direction),
            str(start_snapshot_id),
        ]).encode("utf-8")
    ).hexdigest()[:12]
    return f"case_{digest}"


def read_jsonl(path):
    rows = []
    path = Path(path)
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_snapshot_rows(folder):
    path = Path(folder) / SNAPSHOT_FILENAME
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row = dict(row)
            row["range_label"] = clean_label(row.get("range_label"))
            row["_folder"] = str(Path(folder))
            row["_captured_dt"] = parse_time(row.get("captured_at_local") or row.get("captured_at_utc"))
            row["_edge"] = edge_value(row)
            row["_band_key"] = band_key(row)
            rows.append(row)
    rows.sort(key=lambda item: (
        item.get("event_slug") or "",
        band_key_text(item.get("_band_key")),
        item.get("_captured_dt") or datetime.min.replace(tzinfo=timezone.utc),
    ))
    return rows


def load_replay_inputs(folder):
    index = {}
    for row in read_jsonl(Path(folder) / REPLAY_INPUTS_FILENAME):
        snapshot_id = row.get("snapshot_id")
        if snapshot_id:
            index[snapshot_id] = row
    return index


def load_settlement_label(folder):
    folder = Path(folder)
    path = folder / SETTLEMENT_FILENAME
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return ledger_label_for_slug(folder.name)


def load_trust_scores(backtest_root=DEFAULT_BACKTEST_ROOT):
    path = Path(backtest_root) / "location_trust.json"
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {
        (row.get("market") or row.get("market_id")): {
            "trust_score": row.get("trust_score"),
            "grade": row.get("grade"),
            "settled_days": row.get("settled_days"),
            "brier_skill_vs_market": row.get("brier_skill_vs_market"),
        }
        for row in rows
        if row.get("market") or row.get("market_id")
    }


def component_index(folder):
    path = Path(folder) / COMPONENT_FILENAME
    index = defaultdict(dict)
    if not path.exists():
        return index
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            snapshot_id = row.get("snapshot_id")
            key = band_key(row)
            component = row.get("component_name")
            if not snapshot_id or not component:
                continue
            index[(snapshot_id, key)][component] = maybe_float(row.get("component_probability"))
    return index


def driver_waterfall_for_components(components):
    if not components:
        return []
    rows = []
    previous = None
    for key in RUNNING_STAGE_ORDER:
        if key not in components or components[key] is None:
            continue
        probability = float(components[key])
        contribution = probability if previous is None else probability - previous
        rows.append({
            "component_name": key,
            "label": RUNNING_STAGE_LABELS.get(key, key),
            "probability": probability,
            "contribution": contribution,
        })
        previous = probability
    # Include standalone/non-running components as context after the waterfall.
    for key, probability in sorted(components.items()):
        if key in RUNNING_STAGE_ORDER or probability is None:
            continue
        rows.append({
            "component_name": key,
            "label": key,
            "probability": float(probability),
            "contribution": None,
        })
    return rows


def load_clob_context(folder, max_age_seconds=DEFAULT_MAX_CLOB_AGE_SECONDS):
    path = Path(folder) / BOOK_SUMMARY_FILENAME
    by_key = defaultdict(list)
    if not path.exists():
        return by_key
    previous_midpoint = {}
    def _read_rows(errors=None):
        with path.open("r", encoding="utf-8", errors=errors, newline="") as handle:
            return list(csv.DictReader(handle))
    try:
        rows = _read_rows(errors=None)
    except UnicodeDecodeError:
        rows = _read_rows(errors="replace")
    for row in rows:
        if str(row.get("outcome") or "").lower() != "yes":
            continue
        key = band_key(row)
        ts = to_utc_timestamp(row.get("captured_at_utc") or row.get("captured_at_local"))
        if ts is None:
            continue
        midpoint = maybe_float(row.get("midpoint"))
        prev = previous_midpoint.get(key)
        move = None
        if midpoint is not None and prev is not None:
            move = midpoint - prev
        if midpoint is not None:
            previous_midpoint[key] = midpoint
        by_key[key].append({
            "timestamp": ts,
            "captured_at_utc": row.get("captured_at_utc"),
            "captured_at_local": row.get("captured_at_local"),
            "range_label": clean_label(row.get("range_label")),
            "best_bid": maybe_float(row.get("best_bid")),
            "best_ask": maybe_float(row.get("best_ask")),
            "midpoint": midpoint,
            "spread": maybe_float(row.get("spread")),
            "bid_depth_1pct": maybe_float(row.get("bid_depth_1pct")),
            "ask_depth_1pct": maybe_float(row.get("ask_depth_1pct")),
            "bid_depth_5pct": maybe_float(row.get("bid_depth_5pct")),
            "ask_depth_5pct": maybe_float(row.get("ask_depth_5pct")),
            "imbalance_1pct": maybe_float(row.get("imbalance_1pct")),
            "imbalance_5pct": maybe_float(row.get("imbalance_5pct")),
            "last_trade_price": maybe_float(row.get("last_trade_price")),
            "midpoint_move": move,
            "midpoint_move_abs": abs(move) if move is not None else None,
            "age_seconds": None,
        })
    for rows in by_key.values():
        rows.sort(key=lambda item: item["timestamp"])
    return by_key


def nearest_clob_row(clob_by_key, key, snapshot_time, max_age_seconds=DEFAULT_MAX_CLOB_AGE_SECONDS):
    if snapshot_time is None:
        return None
    rows = clob_by_key.get(key) or []
    if not rows:
        return None
    ts = snapshot_time.astimezone(timezone.utc).timestamp()
    times = [item["timestamp"] for item in rows]
    pos = bisect.bisect_right(times, ts)
    candidates = []
    if pos > 0:
        candidates.append(rows[pos - 1])
    if pos < len(rows):
        candidates.append(rows[pos])
    if not candidates:
        return None
    best = min(candidates, key=lambda item: abs(item["timestamp"] - ts))
    age = abs(best["timestamp"] - ts)
    if age > max_age_seconds:
        return None
    out = dict(best)
    out["age_seconds"] = age
    out.pop("timestamp", None)
    return out


def support_changed(prev, row, threshold):
    prev_max = max_live_observation(prev) if prev else None
    current_max = max_live_observation(row)
    if prev_max is None or current_max is None:
        return False
    return abs(current_max - prev_max) >= threshold


def trigger_reasons(row, prev, clob, args):
    reasons = []
    edge = row.get("_edge")
    model_p = maybe_float(row.get("model_probability"))
    market_p = maybe_float(row.get("market_yes"))
    if edge is not None and abs(edge) >= args.edge_threshold:
        reasons.append("absolute_edge")

    if model_p is not None and market_p is not None and model_p >= args.model_high_prob:
        prev_market = maybe_float(prev.get("market_yes")) if prev else None
        dropped = (
            prev_market is not None
            and prev_market - market_p >= args.market_collapse_drop
        )
        if market_p <= args.market_collapse_price or dropped:
            reasons.append("market_price_collapse_model_high")

    if prev is not None:
        prev_model = maybe_float(prev.get("model_probability"))
        if model_p is not None and prev_model is not None:
            if abs(model_p - prev_model) >= args.model_jump_threshold and not support_changed(prev, row, args.source_support_delta):
                reasons.append("model_jump_without_source_support")

    if clob and (clob.get("midpoint_move_abs") or 0.0) >= args.clob_midpoint_move:
        reasons.append("large_clob_midpoint_move")

    return sorted(set(reasons))


def is_same_episode(current, row, direction, args):
    if current is None:
        return False
    if current["event_slug"] != row.get("event_slug"):
        return False
    if current["band_key"] != row.get("_band_key"):
        return False
    if current["direction"] != direction:
        return False
    gap = minutes_between(current.get("_last_dt"), row.get("_captured_dt"))
    return gap is not None and gap <= args.max_episode_gap_minutes


def open_episode(row, direction, reasons, clob, trust):
    spec = spec_for_slug(row.get("event_slug"))
    market_id = spec.id if spec else row.get("market_id") or "unknown"
    key = row.get("_band_key")
    case_id = stable_case_id(row.get("event_slug"), market_id, key, direction, row.get("snapshot_id"))
    return {
        "case_id": case_id,
        "event_slug": row.get("event_slug"),
        "market_id": market_id,
        "city": spec.city_label if spec else None,
        "unit": spec.display_unit if spec else None,
        "target_date": date_from_event_slug(row.get("event_slug")).isoformat() if row.get("event_slug") else None,
        "range_label": row.get("range_label"),
        "band_key": key,
        "band_key_text": band_key_text(key),
        "direction": direction,
        "start_time_utc": row.get("captured_at_utc"),
        "start_time_local": row.get("captured_at_local"),
        "end_time_utc": row.get("captured_at_utc"),
        "end_time_local": row.get("captured_at_local"),
        "start_snapshot_id": row.get("snapshot_id"),
        "end_snapshot_id": row.get("snapshot_id"),
        "snapshot_ids": [row.get("snapshot_id")],
        "trigger_reasons": sorted(set(reasons)),
        "trigger_counts": dict(Counter(reasons)),
        "snapshot_count": 1,
        "threshold_snapshot_count": 1 if "absolute_edge" in reasons else 0,
        "peak_abs_edge": abs(row.get("_edge") or 0.0),
        "peak_snapshot": row,
        "peak_clob": clob,
        "trust": trust.get(market_id) or {},
        "_last_dt": row.get("_captured_dt"),
    }


def update_episode(case, row, reasons, clob):
    case["end_time_local"] = row.get("captured_at_local")
    case["end_time_utc"] = row.get("captured_at_utc")
    case["end_snapshot_id"] = row.get("snapshot_id")
    case["snapshot_ids"].append(row.get("snapshot_id"))
    case["snapshot_count"] += 1
    case["threshold_snapshot_count"] += 1 if "absolute_edge" in reasons else 0
    counts = Counter(case.get("trigger_counts") or {})
    counts.update(reasons)
    case["trigger_counts"] = dict(counts)
    case["trigger_reasons"] = sorted(set(case["trigger_reasons"]) | set(reasons))
    abs_edge = abs(row.get("_edge") or 0.0)
    if abs_edge >= case.get("peak_abs_edge", 0.0):
        case["peak_abs_edge"] = abs_edge
        case["peak_snapshot"] = row
        case["peak_clob"] = clob
    case["_last_dt"] = row.get("_captured_dt")
    return case


def detect_cases_for_folder(folder, args, trust):
    rows = load_snapshot_rows(folder)
    if not rows:
        return [], {"folder": str(folder), "snapshot_rows": 0, "threshold_snapshot_count": 0}
    clob_by_key = load_clob_context(folder, args.max_clob_age_seconds) if args.include_clob else {}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("_band_key")].append(row)
    cases = []
    threshold_count = 0
    for key, band_rows in grouped.items():
        previous = None
        current = None
        for row in sorted(band_rows, key=lambda item: item.get("_captured_dt") or datetime.min.replace(tzinfo=timezone.utc)):
            clob = nearest_clob_row(clob_by_key, key, row.get("_captured_dt"), args.max_clob_age_seconds)
            reasons = trigger_reasons(row, previous, clob, args)
            if "absolute_edge" in reasons:
                threshold_count += 1
            if not reasons:
                previous = row
                continue
            direction = direction_for_edge(row.get("_edge"))
            if is_same_episode(current, row, direction, args):
                update_episode(current, row, reasons, clob)
            else:
                if current:
                    cases.append(current)
                current = open_episode(row, direction, reasons, clob, trust)
            previous = row
        if current:
            cases.append(current)
    return cases, {
        "folder": str(folder),
        "snapshot_rows": len(rows),
        "threshold_snapshot_count": threshold_count,
        "case_count": len(cases),
    }


def source_freshness_from_replay(replay_row):
    sources = (replay_row or {}).get("sources") or {}
    freshness = {}
    for name, item in sorted(sources.items()):
        if not isinstance(item, dict):
            continue
        freshness[name] = {
            "ok": item.get("ok"),
            "status": item.get("status"),
            "stale": item.get("stale"),
            "fetched_at": item.get("fetched_at"),
            "cache_age_minutes": item.get("cache_age_minutes"),
            "ttl_minutes": item.get("ttl_minutes"),
            "error": item.get("error"),
        }
    return freshness


def has_stale_or_failed_source(freshness):
    for item in (freshness or {}).values():
        if item.get("stale") or item.get("ok") is False or item.get("status") in {"stale_cache", "failed"}:
            return True
    return False


def source_snapshot_context(row):
    context = source_values(row)
    context["max_live_observation"] = max_live_observation(row)
    context["forecast_consensus"] = forecast_consensus(row)
    return context


def classify_taxonomy(case):
    if not case.get("settlement"):
        return "open_unsettled"
    if has_stale_or_failed_source(case.get("source_freshness")) and case.get("model_result") == "model_loss":
        return "stale_source"
    row = case.get("peak_snapshot") or {}
    settlement_bucket = maybe_float((case.get("settlement") or {}).get("settlement_bucket"))
    live_max = maybe_float((case.get("source_context") or {}).get("max_live_observation"))
    wu_history = maybe_float((case.get("source_context") or {}).get("wu_history_high_c"))
    forecast = maybe_float((case.get("source_context") or {}).get("forecast_consensus"))
    clob = case.get("clob_context") or {}

    if case.get("model_result") == "model_loss":
        if live_max is not None and wu_history is not None and live_max - wu_history >= 1.0:
            return "wu_lag_catchup_miss"
        if forecast is not None and settlement_bucket is not None and abs(forecast - settlement_bucket) >= 2.0:
            return "forecast_miss"
        if clob and (clob.get("spread") is None or (clob.get("spread") or 0.0) >= 0.05):
            return "book_liquidity_artifact"
        kind, value, value_hi = band_key(row)
        if kind == "eq" and settlement_bucket is not None and value is not None:
            hi = value_hi if value_hi is not None else value
            if min(abs(settlement_bucket - value), abs(settlement_bucket - hi)) <= 1.0:
                return "boundary_rounding_error"
        if case.get("market_brier") is not None and case.get("model_brier") is not None:
            return "market_lead"
        return "model_calibration_error"
    if clob and (clob.get("spread") is None or (clob.get("spread") or 0.0) >= 0.05):
        return "book_liquidity_artifact"
    return "market_overreaction"


def score_case(case, settlement_label, replay_inputs, components):
    row = case.get("peak_snapshot") or {}
    snapshot_id = row.get("snapshot_id")
    replay_row = replay_inputs.get(snapshot_id) if replay_inputs else None
    case["model_version"] = row.get("model_version")
    case["peak_time_local"] = row.get("captured_at_local")
    case["peak_snapshot_id"] = snapshot_id
    case["model_probability"] = maybe_float(row.get("model_probability"))
    case["market_yes"] = maybe_float(row.get("market_yes"))
    case["market_no"] = maybe_float(row.get("market_no"))
    case["edge"] = row.get("_edge")
    case["peak_edge"] = case["edge"]
    case["source_context"] = source_snapshot_context(row)
    case["source_values"] = dict(case["source_context"])
    case["source_freshness"] = source_freshness_from_replay(replay_row)
    case["model_identity"] = (replay_row or {}).get("model_identity") or {}
    component_map = components.get((snapshot_id, row.get("_band_key"))) if components else None
    case["driver_waterfall"] = driver_waterfall_for_components(component_map)
    case["clob_context"] = case.get("peak_clob") or {}

    if settlement_label:
        settlement_bucket = maybe_int(settlement_label.get("settlement_bucket"))
        outcome = band_outcome(row, settlement_bucket)
        case["settlement"] = {
            "settlement_bucket": settlement_bucket,
            "settlement_high": maybe_float(settlement_label.get("settlement_high")),
            "settlement_unit": settlement_label.get("settlement_unit"),
            "winning_band": clean_label(settlement_label.get("winning_band")),
            "quality_grade": settlement_label.get("quality_grade"),
            "settlement_source": settlement_label.get("settlement_source"),
            "reconciliation_status": settlement_label.get("reconciliation_status"),
        }
        case["outcome"] = outcome
        if outcome is not None and case["model_probability"] is not None and case["market_yes"] is not None:
            case["model_brier"] = brier(case["model_probability"], outcome)
            case["market_brier"] = brier(case["market_yes"], outcome)
            case["brier_delta_market_minus_model"] = case["market_brier"] - case["model_brier"]
            pnl = trade_pnl(
                case["model_probability"],
                case["market_yes"],
                case["market_no"],
                outcome,
                DEFAULT_PNL_THRESHOLD,
            )
            case["trade_pnl_at_5c"] = pnl
            if case["model_brier"] + 1e-12 < case["market_brier"]:
                case["model_result"] = "model_win"
            elif case["model_brier"] > case["market_brier"] + 1e-12:
                case["model_result"] = "model_loss"
            else:
                case["model_result"] = "tie"
    else:
        case["settlement"] = None
        case["outcome"] = None
        case["model_result"] = "open"

    case["taxonomy"] = classify_taxonomy(case)
    # Drop internal raw row helpers after all derived context is attached.
    peak = dict(case.get("peak_snapshot") or {})
    peak.pop("_captured_dt", None)
    peak["_band_key"] = band_key_text(peak.get("_band_key")) if peak.get("_band_key") else None
    peak["range_label"] = clean_label(peak.get("range_label"))
    case["peak_snapshot"] = peak
    case.pop("_last_dt", None)
    case["band_key"] = band_key_text(case["band_key"])
    return case


def stable_warm_side_case_id(event_slug, snapshot_id, top_band_key):
    digest = hashlib.sha1(
        "|".join([
            str(event_slug),
            str(snapshot_id),
            band_key_text(top_band_key),
            "late_day_warm_side",
        ]).encode("utf-8")
    ).hexdigest()[:12]
    return f"warm_{digest}"


def band_contains_value(row, value):
    if value is None:
        return False
    kind, low, high = band_key(row)
    if low is None:
        return False
    high = high if high is not None else low
    if kind == "lte":
        return value <= low
    if kind == "gte":
        return value >= low
    return low <= value <= high


def band_lower_value(row):
    kind, low, _high = band_key(row)
    if kind == "lte":
        return None
    return maybe_float(low)


def band_sort_value(row):
    kind, low, high = band_key(row)
    if low is None:
        return (float("inf"), float("inf"))
    high = high if high is not None else low
    if kind == "lte":
        return (float("-inf"), low)
    if kind == "gte":
        return (low, float("inf"))
    return (low, high)


def sorted_band_rows(rows):
    return sorted(rows or [], key=band_sort_value)


def find_band_for_value(rows, value):
    candidates = [row for row in rows or [] if band_contains_value(row, value)]
    if not candidates:
        return None
    return min(candidates, key=lambda row: (
        0 if band_key(row)[0] == "eq" else 1,
        (band_sort_value(row)[1] - band_sort_value(row)[0])
        if all(math.isfinite(item) for item in band_sort_value(row))
        else float("inf"),
        band_sort_value(row),
    ))


def top_model_band_row(rows):
    candidates = [
        row for row in rows or []
        if maybe_float(row.get("model_probability")) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (
        maybe_float(row.get("model_probability")) or 0.0,
        band_sort_value(row)[0] if math.isfinite(band_sort_value(row)[0]) else -1e9,
    ))


def market_top_band_row(rows):
    candidates = [
        row for row in rows or []
        if maybe_float(row.get("market_yes")) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (
        maybe_float(row.get("market_yes")) or 0.0,
        band_sort_value(row)[0] if math.isfinite(band_sort_value(row)[0]) else -1e9,
    ))


def warm_bin_distance(rows, current_high_row, top_row):
    if not current_high_row or not top_row:
        return None
    ordered = sorted_band_rows(rows)
    try:
        current_idx = ordered.index(current_high_row)
        top_idx = ordered.index(top_row)
    except ValueError:
        return None
    return max(0, top_idx - current_idx)


def warm_distance_bucket(distance):
    if distance is None:
        return "unknown"
    if distance <= 1:
        return "one_bin"
    if distance == 2:
        return "two_bins"
    return "three_plus_bins"


def heating_window_bucket(hours_remaining):
    if hours_remaining is None:
        return "unknown"
    if hours_remaining <= 0:
        return "closed"
    if hours_remaining <= 1:
        return "0-1h"
    if hours_remaining <= 2:
        return "1-2h"
    return "2h_plus"


def forecast_gap_bucket(gap):
    if gap is None:
        return "unknown"
    if gap >= 2.0:
        return "forecast_2plus_above_high"
    if gap >= 1.0:
        return "forecast_1_above_high"
    if gap >= 0.0:
        return "forecast_near_high"
    return "forecast_below_high"


def cooling_trend_bucket(current_minus_high):
    if current_minus_high is None:
        return "unknown"
    if current_minus_high >= -0.25:
        return "at_or_near_peak"
    if current_minus_high >= -1.0:
        return "slightly_off_peak"
    return "cooling_off_peak"


def unavailable_source_names(freshness):
    unavailable = []
    for name, item in sorted((freshness or {}).items()):
        status = str(item.get("status") or "").lower()
        if item.get("stale") or item.get("ok") is False or status in SOURCE_UNAVAILABLE_STATUSES:
            unavailable.append(name)
    return unavailable


def compact_source_freshness(freshness):
    return {
        name: {
            "ok": item.get("ok"),
            "status": item.get("status"),
            "stale": item.get("stale"),
            "cache_age_minutes": item.get("cache_age_minutes"),
            "ttl_minutes": item.get("ttl_minutes"),
        }
        for name, item in sorted((freshness or {}).items())
    }


def source_freshness_bucket(freshness):
    if not freshness:
        return "unknown"
    unavailable = set(unavailable_source_names(freshness))
    if not unavailable:
        return "all_fresh"
    if unavailable & OPEN_METEO_SOURCE_NAMES:
        return "open_meteo_unavailable"
    if unavailable & FORECAST_SOURCE_NAMES:
        return "forecast_source_unavailable"
    return "source_degraded"


def market_disagreement_bucket(top_row, market_row):
    if not market_row:
        return "market_missing"
    top_key = band_key(top_row)
    market_key = band_key(market_row)
    if top_key == market_key:
        return "aligned"
    top_low = band_lower_value(top_row)
    market_low = band_lower_value(market_row)
    if top_low is not None and market_low is not None and top_low > market_low:
        return "model_warmer_than_market"
    return "different_top_band"


def coastal_context_bucket(spec):
    if not spec:
        return "unknown"
    if spec.coastal:
        return "coastal"
    if "marine_context" in (spec.sources or ()):
        return "marine_context_tracked"
    return "inland"


def late_day_warm_side_case_for_snapshot(rows, settlement_label, replay_inputs, trust):
    if not rows:
        return None
    first = rows[0]
    captured = parse_time(first.get("captured_at_local") or first.get("captured_at_utc"))
    if captured is None:
        return None
    local_hour = captured.hour + captured.minute / 60.0 + captured.second / 3600.0
    if local_hour < LATE_DAY_WARM_SIDE_START_HOUR:
        return None
    top_row = top_model_band_row(rows)
    if not top_row:
        return None
    high_so_far = max_live_observation(top_row)
    top_low = band_lower_value(top_row)
    if high_so_far is None or top_low is None or top_low <= high_so_far:
        return None
    spec = spec_for_slug(top_row.get("event_slug"))
    market_id = spec.id if spec else top_row.get("market_id") or "unknown"
    market_row = market_top_band_row(rows)
    current_high_row = find_band_for_value(rows, high_so_far)
    distance = warm_bin_distance(rows, current_high_row, top_row)
    current_temp = maybe_float(top_row.get("wu_current_c"))
    current_minus_high = None if current_temp is None else current_temp - high_so_far
    forecast = forecast_consensus(top_row)
    forecast_gap = None if forecast is None else forecast - high_so_far
    snapshot_id = top_row.get("snapshot_id")
    replay_row = replay_inputs.get(snapshot_id) if replay_inputs else None
    freshness = source_freshness_from_replay(replay_row)
    unavailable = unavailable_source_names(freshness)
    heating_remaining = max(0.0, LATE_DAY_HEATING_WINDOW_END_HOUR - local_hour)
    top_key = band_key(top_row)
    market_key = band_key(market_row) if market_row else None
    current_key = band_key(current_high_row) if current_high_row else None
    market_disagreement = market_key != top_key if market_key else None
    case = {
        "case_id": stable_warm_side_case_id(top_row.get("event_slug"), snapshot_id, top_key),
        "event_slug": top_row.get("event_slug"),
        "market_id": market_id,
        "city": spec.city_label if spec else None,
        "unit": spec.display_unit if spec else None,
        "target_date": date_from_event_slug(top_row.get("event_slug")).isoformat() if top_row.get("event_slug") else None,
        "snapshot_id": snapshot_id,
        "captured_at_utc": top_row.get("captured_at_utc"),
        "captured_at_local": top_row.get("captured_at_local"),
        "local_hour": round(local_hour, 2),
        "heating_window_hours_remaining": round(heating_remaining, 2),
        "heating_window_bucket": heating_window_bucket(heating_remaining),
        "model_top_band": clean_label(top_row.get("range_label")),
        "model_top_band_key": band_key_text(top_key),
        "model_top_probability": maybe_float(top_row.get("model_probability")),
        "market_top_band": clean_label(market_row.get("range_label")) if market_row else None,
        "market_top_band_key": band_key_text(market_key) if market_key else None,
        "market_top_probability": maybe_float(market_row.get("market_yes")) if market_row else None,
        "market_disagreement": market_disagreement,
        "market_disagreement_bucket": market_disagreement_bucket(top_row, market_row),
        "current_high": high_so_far,
        "current_temp": current_temp,
        "current_minus_high": current_minus_high,
        "current_high_band": clean_label(current_high_row.get("range_label")) if current_high_row else None,
        "current_high_band_key": band_key_text(current_key) if current_key else None,
        "warm_gap_degrees": top_low - high_so_far,
        "warm_bin_distance": distance,
        "warm_distance_bucket": warm_distance_bucket(distance),
        "forecast_consensus": forecast,
        "forecast_high_gap": forecast_gap,
        "forecast_gap_bucket": forecast_gap_bucket(forecast_gap),
        "cooling_trend_bucket": cooling_trend_bucket(current_minus_high),
        "source_freshness_state": source_freshness_bucket(freshness),
        "unavailable_sources": unavailable,
        "source_freshness": compact_source_freshness(freshness),
        "coastal_context": coastal_context_bucket(spec),
        "coastal": bool(spec.coastal) if spec else None,
        "marine_context_source_present": bool(spec and "marine_context" in (spec.sources or ())),
        "marine_context_status": (freshness.get("marine_context") or {}).get("status") if freshness else None,
        "trust": trust.get(market_id) or {},
        "model_version": top_row.get("model_version"),
    }
    if settlement_label:
        settlement_bucket = maybe_int(settlement_label.get("settlement_bucket"))
        model_outcome = band_outcome(top_row, settlement_bucket)
        market_outcome = band_outcome(market_row, settlement_bucket) if market_row else None
        current_outcome = band_outcome(current_high_row, settlement_bucket) if current_high_row else None
        case["settlement"] = {
            "settlement_bucket": settlement_bucket,
            "settlement_high": maybe_float(settlement_label.get("settlement_high")),
            "settlement_unit": settlement_label.get("settlement_unit"),
            "winning_band": clean_label(settlement_label.get("winning_band")),
            "quality_grade": settlement_label.get("quality_grade"),
            "settlement_source": settlement_label.get("settlement_source"),
            "reconciliation_status": settlement_label.get("reconciliation_status"),
        }
        case["model_top_outcome"] = model_outcome
        case["market_top_outcome"] = market_outcome
        case["current_high_lockin_outcome"] = current_outcome
        case["model_vs_market_top_result"] = baseline_result(model_outcome, market_outcome)
        case["model_vs_current_high_result"] = baseline_result(model_outcome, current_outcome)
    else:
        case["settlement"] = None
        case["model_top_outcome"] = None
        case["market_top_outcome"] = None
        case["current_high_lockin_outcome"] = None
        case["model_vs_market_top_result"] = "open"
        case["model_vs_current_high_result"] = "open"
    return case


def baseline_result(model_outcome, baseline_outcome):
    if model_outcome is None or baseline_outcome is None:
        return "open"
    if model_outcome > baseline_outcome:
        return "model_win"
    if model_outcome < baseline_outcome:
        return "model_loss"
    return "tie"


def late_day_warm_side_cases_for_folder(folder, settlement_label, replay_inputs, trust):
    rows = load_snapshot_rows(folder)
    grouped = defaultdict(list)
    for row in rows:
        key = (row.get("event_slug"), row.get("snapshot_id"))
        grouped[key].append(row)
    cases = []
    for _key, snapshot_rows in sorted(
        grouped.items(),
        key=lambda item: item[1][0].get("_captured_dt") or datetime.min.replace(tzinfo=timezone.utc),
    ):
        case = late_day_warm_side_case_for_snapshot(snapshot_rows, settlement_label, replay_inputs, trust)
        if case:
            cases.append(case)
    return cases


def warm_case_ref(case):
    return {
        "case_id": case.get("case_id"),
        "market_id": case.get("market_id"),
        "event_slug": case.get("event_slug"),
        "snapshot_id": case.get("snapshot_id"),
        "captured_at_utc": case.get("captured_at_utc"),
        "model_top_band": case.get("model_top_band"),
        "current_high": case.get("current_high"),
        "market_top_band": case.get("market_top_band"),
        "source_freshness_state": case.get("source_freshness_state"),
    }


def late_day_warm_side_slice(cases, fields, max_refs=20):
    grouped = defaultdict(list)
    for case in cases:
        key = tuple(case.get(field) for field in fields)
        grouped[key].append(case)
    rows = []
    for key, items in grouped.items():
        settled = [item for item in items if item.get("settlement")]
        rows.append({
            "fields": list(fields),
            "key": {field: value for field, value in zip(fields, key)},
            "case_count": len(items),
            "settled_case_count": len(settled),
            "open_case_count": len(items) - len(settled),
            "model_top_hit_count": sum(1 for item in settled if item.get("model_top_outcome") == 1),
            "market_top_hit_count": sum(1 for item in settled if item.get("market_top_outcome") == 1),
            "current_high_lockin_hit_count": sum(
                1 for item in settled if item.get("current_high_lockin_outcome") == 1
            ),
            "model_vs_market_top": dict(Counter(item.get("model_vs_market_top_result") for item in settled)),
            "model_vs_current_high": dict(Counter(item.get("model_vs_current_high_result") for item in settled)),
            "case_refs": [warm_case_ref(item) for item in items[:max_refs]],
        })
    rows.sort(key=lambda item: (
        item.get("settled_case_count", 0),
        item.get("case_count", 0),
        str(item.get("key")),
    ), reverse=True)
    return rows


def summarize_late_day_warm_side_cases(cases):
    settled = [case for case in cases if case.get("settlement")]
    return {
        "case_count": len(cases),
        "settled_case_count": len(settled),
        "open_case_count": len(cases) - len(settled),
        "market_disagreement_count": sum(1 for case in cases if case.get("market_disagreement")),
        "model_top_hit_count": sum(1 for case in settled if case.get("model_top_outcome") == 1),
        "market_top_hit_count": sum(1 for case in settled if case.get("market_top_outcome") == 1),
        "current_high_lockin_hit_count": sum(
            1 for case in settled if case.get("current_high_lockin_outcome") == 1
        ),
        "source_freshness_counts": dict(Counter(case.get("source_freshness_state") for case in cases)),
        "coastal_context_counts": dict(Counter(case.get("coastal_context") for case in cases)),
        "warm_distance_counts": dict(Counter(case.get("warm_distance_bucket") for case in cases)),
        "heating_window_counts": dict(Counter(case.get("heating_window_bucket") for case in cases)),
    }


def build_late_day_warm_side_casebook(cases):
    cases = sorted(cases, key=lambda case: (
        case.get("target_date") or "",
        case.get("market_id") or "",
        case.get("captured_at_utc") or "",
    ), reverse=True)
    return {
        "schema_version": LATE_DAY_WARM_SIDE_SCHEMA_VERSION,
        "late_day_start_hour": LATE_DAY_WARM_SIDE_START_HOUR,
        "heating_window_end_hour": LATE_DAY_HEATING_WINDOW_END_HOUR,
        "summary": summarize_late_day_warm_side_cases(cases),
        "slices": {
            "by_heating_window": late_day_warm_side_slice(cases, ("heating_window_bucket",)),
            "by_forecast_gap": late_day_warm_side_slice(cases, ("forecast_gap_bucket",)),
            "by_cooling_trend": late_day_warm_side_slice(cases, ("cooling_trend_bucket",)),
            "by_coastal_context": late_day_warm_side_slice(cases, ("coastal_context",)),
            "by_source_freshness": late_day_warm_side_slice(cases, ("source_freshness_state",)),
            "by_market_disagreement": late_day_warm_side_slice(cases, ("market_disagreement_bucket",)),
            "by_warm_distance": late_day_warm_side_slice(cases, ("warm_distance_bucket",)),
            "source_coastal_interaction": late_day_warm_side_slice(
                cases,
                ("warm_distance_bucket", "source_freshness_state", "coastal_context"),
            ),
        },
        "cases": cases,
    }


def discover_folders(snapshots_root, explicit_folders=None):
    if explicit_folders:
        return [Path(item) for item in explicit_folders]
    root = Path(snapshots_root)
    if not root.exists():
        return []
    return sorted(
        [folder for folder in root.iterdir() if folder.is_dir() and (folder / SNAPSHOT_FILENAME).exists()],
        key=lambda path: path.name,
    )


def build_casebook(
    folders=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    args=None,
):
    args = args or argparse.Namespace(
        edge_threshold=DEFAULT_EDGE_THRESHOLD,
        market_collapse_price=DEFAULT_MARKET_COLLAPSE_PRICE,
        market_collapse_drop=DEFAULT_MARKET_COLLAPSE_DROP,
        model_high_prob=DEFAULT_MODEL_HIGH_PROB,
        model_jump_threshold=DEFAULT_MODEL_JUMP_THRESHOLD,
        source_support_delta=DEFAULT_SOURCE_SUPPORT_DELTA,
        clob_midpoint_move=DEFAULT_CLOB_MIDPOINT_MOVE,
        max_episode_gap_minutes=DEFAULT_MAX_EPISODE_GAP_MINUTES,
        max_clob_age_seconds=DEFAULT_MAX_CLOB_AGE_SECONDS,
        include_clob=True,
    )
    trust = load_trust_scores(backtest_root)
    all_cases = []
    warm_side_cases = []
    folder_summaries = []
    for folder in discover_folders(snapshots_root, folders):
        cases, folder_summary = detect_cases_for_folder(folder, args, trust)
        folder_summaries.append(folder_summary)
        replay_inputs = load_replay_inputs(folder)
        settlement = load_settlement_label(folder)
        warm_side_cases.extend(late_day_warm_side_cases_for_folder(folder, settlement, replay_inputs, trust))
        if cases:
            components = component_index(folder)
            for case in cases:
                all_cases.append(score_case(case, settlement, replay_inputs, components))
    all_cases.sort(key=lambda case: (
        case.get("target_date") or "",
        case.get("market_id") or "",
        case.get("peak_abs_edge") or 0.0,
    ), reverse=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "thresholds": {
            "edge_threshold": args.edge_threshold,
            "market_collapse_price": args.market_collapse_price,
            "market_collapse_drop": args.market_collapse_drop,
            "model_high_prob": args.model_high_prob,
            "model_jump_threshold": args.model_jump_threshold,
            "source_support_delta": args.source_support_delta,
            "clob_midpoint_move": args.clob_midpoint_move,
            "max_episode_gap_minutes": args.max_episode_gap_minutes,
            "max_clob_age_seconds": args.max_clob_age_seconds,
        },
        "folders": folder_summaries,
        "summary": summarize_cases(all_cases, folder_summaries),
        "feedback_slices": feedback_slices(all_cases),
        "late_day_warm_side_cases": build_late_day_warm_side_casebook(warm_side_cases),
        "cases": all_cases,
    }
    return payload


TAXONOMY_ROADMAP_ITEMS = {
    "stale_source": ["17", "31", "42"],
    "wu_lag_catchup_miss": ["23", "40", "42"],
    "forecast_miss": ["22", "27", "33", "35"],
    "book_liquidity_artifact": ["38"],
    "boundary_rounding_error": ["7", "21", "35"],
    "market_lead": ["21", "33", "38"],
    "model_calibration_error": ["21", "33", "35"],
    "market_overreaction": ["21", "38"],
}


def mean(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def snapshot_ref(case):
    return {
        "case_id": case.get("case_id"),
        "market_id": case.get("market_id"),
        "event_slug": case.get("event_slug"),
        "range_label": case.get("range_label"),
        "peak_snapshot_id": case.get("peak_snapshot_id"),
        "snapshot_ids": case.get("snapshot_ids") or [],
        "start_time_utc": case.get("start_time_utc"),
        "end_time_utc": case.get("end_time_utc"),
        "taxonomy": case.get("taxonomy"),
    }


def feedback_slices(cases, max_refs=50):
    settled = [case for case in cases if case.get("settlement")]
    grouped = defaultdict(list)
    for case in settled:
        grouped[case.get("taxonomy") or "unknown"].append(case)
    output = []
    for taxonomy, rows in grouped.items():
        wins = [case for case in rows if case.get("model_result") == "model_win"]
        losses = [case for case in rows if case.get("model_result") == "model_loss"]
        ties = [case for case in rows if case.get("model_result") == "tie"]
        if len(losses) >= max(len(wins), 1):
            slice_type = "model_losing_family"
        elif wins:
            slice_type = "known_edge_candidate"
        else:
            slice_type = "mixed_or_tie"
        refs = sorted(rows, key=lambda case: abs(case.get("edge") or 0.0), reverse=True)
        output.append({
            "taxonomy": taxonomy,
            "slice_type": slice_type,
            "case_count": len(rows),
            "model_win_count": len(wins),
            "model_loss_count": len(losses),
            "tie_count": len(ties),
            "mean_model_brier": mean(case.get("model_brier") for case in rows),
            "mean_market_brier": mean(case.get("market_brier") for case in rows),
            "mean_brier_delta_market_minus_model": mean(
                case.get("brier_delta_market_minus_model") for case in rows
            ),
            "trade_pnl_at_5c_sum": sum(
                case.get("trade_pnl_at_5c") or 0.0
                for case in rows
                if case.get("trade_pnl_at_5c") is not None
            ),
            "roadmap_items": TAXONOMY_ROADMAP_ITEMS.get(taxonomy, []),
            "case_ids": [case.get("case_id") for case in refs],
            "snapshot_refs": [snapshot_ref(case) for case in refs[:max_refs]],
            "promotion_gate": (
                "A proposed fix must improve this exact case/snapshot slice "
                "and then pass the broader pinned promotion corpus/gauntlet."
            ),
        })
    output.sort(key=lambda item: (
        item.get("model_loss_count", 0),
        item.get("case_count", 0),
        item.get("model_win_count", 0),
    ), reverse=True)
    return output


def summarize_cases(cases, folder_summaries):
    taxonomy = Counter(case.get("taxonomy") for case in cases)
    triggers = Counter()
    results = Counter()
    markets = Counter()
    settled = 0
    for case in cases:
        triggers.update(case.get("trigger_reasons") or [])
        results[case.get("model_result") or "unknown"] += 1
        markets[case.get("market_id") or "unknown"] += 1
        if case.get("settlement"):
            settled += 1
    threshold_snapshots = sum(item.get("threshold_snapshot_count", 0) for item in folder_summaries)
    covered = sum(case.get("threshold_snapshot_count", 0) for case in cases)
    return {
        "case_count": len(cases),
        "settled_case_count": settled,
        "open_case_count": len(cases) - settled,
        "model_win_count": results.get("model_win", 0),
        "model_loss_count": results.get("model_loss", 0),
        "tie_count": results.get("tie", 0),
        "taxonomy_counts": dict(taxonomy),
        "trigger_counts": dict(triggers),
        "market_counts": dict(markets),
        "folder_count": len(folder_summaries),
        "snapshot_rows_scanned": sum(item.get("snapshot_rows", 0) for item in folder_summaries),
        "threshold_snapshot_count": threshold_snapshots,
        "covered_threshold_snapshot_count": covered,
        "threshold_coverage_ok": threshold_snapshots == covered,
    }


def fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def fmt_case_time(case):
    start = case.get("start_time_local") or "-"
    end = case.get("end_time_local") or "-"
    if start == end:
        return start
    return f"{start} -> {end}"


def render_case_rows(cases, limit=30):
    rows = []
    for case in sorted(cases, key=lambda item: item.get("peak_abs_edge") or 0.0, reverse=True)[:limit]:
        rows.append([
            case.get("case_id"),
            case.get("market_id"),
            clean_label(case.get("range_label")),
            fmt_case_time(case),
            fmt_signed(case.get("edge"), 3),
            fmt_pct(case.get("model_probability")),
            fmt_pct(case.get("market_yes")),
            ", ".join(case.get("trigger_reasons") or []),
            case.get("model_result"),
            case.get("taxonomy"),
        ])
    return rows


def render_feedback_rows(slices, slice_type=None, limit=12):
    rows = []
    items = [item for item in slices if slice_type is None or item.get("slice_type") == slice_type]
    for item in items[:limit]:
        rows.append([
            item.get("taxonomy"),
            item.get("slice_type"),
            item.get("case_count"),
            item.get("model_loss_count"),
            item.get("model_win_count"),
            fmt_num(item.get("mean_model_brier"), 4),
            fmt_num(item.get("mean_market_brier"), 4),
            fmt_signed(item.get("mean_brier_delta_market_minus_model"), 4),
            fmt_signed(item.get("trade_pnl_at_5c_sum"), 2),
            ", ".join(item.get("roadmap_items") or []),
            ", ".join((item.get("case_ids") or [])[:5]),
        ])
    return rows


def render_warm_case_rows(cases, limit=30):
    rows = []
    for case in sorted(
        cases,
        key=lambda item: (
            item.get("settlement") is not None,
            item.get("captured_at_utc") or "",
            item.get("market_id") or "",
        ),
        reverse=True,
    )[:limit]:
        rows.append([
            case.get("case_id"),
            case.get("market_id"),
            case.get("captured_at_local"),
            case.get("current_high"),
            case.get("model_top_band"),
            fmt_pct(case.get("model_top_probability")),
            case.get("market_top_band"),
            fmt_pct(case.get("market_top_probability")),
            case.get("warm_distance_bucket"),
            case.get("source_freshness_state"),
            case.get("coastal_context"),
            case.get("model_vs_market_top_result"),
            case.get("model_vs_current_high_result"),
        ])
    return rows


def render_warm_slice_rows(slices, limit=12):
    rows = []
    for item in (slices or [])[:limit]:
        key = item.get("key") or {}
        rows.append([
            ", ".join(f"{name}={value}" for name, value in key.items()),
            item.get("case_count"),
            item.get("settled_case_count"),
            item.get("open_case_count"),
            item.get("model_top_hit_count"),
            item.get("market_top_hit_count"),
            item.get("current_high_lockin_hit_count"),
            dict(item.get("model_vs_market_top") or {}),
        ])
    return rows


def render_report(payload):
    summary = payload["summary"]
    cases = payload["cases"]
    slices = payload.get("feedback_slices") or []
    warm_side = payload.get("late_day_warm_side_cases") or {}
    warm_summary = warm_side.get("summary") or {}
    warm_slices = warm_side.get("slices") or {}
    warm_cases = warm_side.get("cases") or []
    settled_cases = [case for case in cases if case.get("settlement")]
    open_cases = [case for case in cases if not case.get("settlement")]
    lines = [
        "# Model-Market Disagreement Casebook",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "## Design",
        "",
        "This report scans append-only snapshot tapes and CLOB book summaries for "
        "large model-market disagreements, collapses contiguous triggered rows "
        "into stable cases, attaches source/book/model context at the peak, and "
        "revisits settled cases with ledger outcomes and a first-pass taxonomy.",
        "",
        "Triggers: absolute edge, market-price collapse while the model stays "
        "high, model jump without observed-source support, and large CLOB "
        "midpoint move. Cases are grouped by market, event, band, direction, and "
        "episode gap.",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Cases", summary.get("case_count")],
            ["Settled / open", f"{summary.get('settled_case_count')} / {summary.get('open_case_count')}"],
            ["Model wins / losses / ties", f"{summary.get('model_win_count')} / {summary.get('model_loss_count')} / {summary.get('tie_count')}"],
            ["Snapshot rows scanned", summary.get("snapshot_rows_scanned")],
            ["Threshold snapshot coverage", f"{summary.get('covered_threshold_snapshot_count')} / {summary.get('threshold_snapshot_count')}"],
            ["Threshold coverage OK", summary.get("threshold_coverage_ok")],
        ],
    ))
    lines.extend(["", "## Trigger Counts", ""])
    lines.extend(markdown_table(
        ["Trigger", "Cases"],
        [[key, value] for key, value in sorted(summary.get("trigger_counts", {}).items())],
    ))
    lines.extend(["", "## Taxonomy Counts", ""])
    lines.extend(markdown_table(
        ["Taxonomy", "Cases"],
        [[key, value] for key, value in sorted(summary.get("taxonomy_counts", {}).items())],
    ))
    lines.extend(["", "## Largest Cases", ""])
    lines.extend(markdown_table(
        ["Case", "Market", "Band", "Time", "Edge", "Model", "Market", "Triggers", "Result", "Taxonomy"],
        render_case_rows(cases, limit=40),
    ))
    lines.extend(["", "## Open Cases Needing Attention", ""])
    lines.extend(markdown_table(
        ["Case", "Market", "Band", "Time", "Edge", "Model", "Market", "Triggers", "Result", "Taxonomy"],
        render_case_rows(open_cases, limit=25),
    ))
    lines.extend(["", "## Settled Cases", ""])
    lines.extend(markdown_table(
        ["Case", "Market", "Band", "Time", "Edge", "Model", "Market", "Triggers", "Result", "Taxonomy"],
        render_case_rows(settled_cases, limit=40),
    ))
    lines.extend(["", "## Top Model-Losing Case Families", ""])
    losing = Counter(case.get("taxonomy") for case in settled_cases if case.get("model_result") == "model_loss")
    lines.extend(markdown_table(
        ["Family", "Losses"],
        [[key, value] for key, value in losing.most_common()],
    ))
    lines.extend([
        "",
        "## Feedback Slices",
        "",
        "These slices make recurring disagreement families actionable: a proposed "
        "fix should improve the exact case/snapshot refs in the JSON slice, then "
        "pass the broader pinned promotion corpus/gauntlet.",
        "",
        "### Model-Losing Replay Targets",
        "",
    ])
    lines.extend(markdown_table(
        [
            "Taxonomy",
            "Type",
            "Cases",
            "Losses",
            "Wins",
            "Model Brier",
            "Market Brier",
            "Market-Model",
            "P&L @5c",
            "Items",
            "Example Cases",
        ],
        render_feedback_rows(slices, slice_type="model_losing_family"),
    ))
    lines.extend(["", "### Known-Edge Candidates", ""])
    lines.extend(markdown_table(
        [
            "Taxonomy",
            "Type",
            "Cases",
            "Losses",
            "Wins",
            "Model Brier",
            "Market Brier",
            "Market-Model",
            "P&L @5c",
            "Items",
            "Example Cases",
        ],
        render_feedback_rows(slices, slice_type="known_edge_candidate"),
    ))
    lines.extend([
        "",
        "## Late-Day Warm-Side Cases",
        "",
        "This slice captures snapshots after 14:00 local time where the model's "
        "top band is still warmer than the live high-so-far, then compares the "
        "model top, market top, and current-high lock-in baselines once "
        "settlement is available.",
        "",
    ])
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Cases", warm_summary.get("case_count")],
            ["Settled / open", f"{warm_summary.get('settled_case_count')} / {warm_summary.get('open_case_count')}"],
            ["Market disagreements", warm_summary.get("market_disagreement_count")],
            ["Model / market / lock-in hits", (
                f"{warm_summary.get('model_top_hit_count')} / "
                f"{warm_summary.get('market_top_hit_count')} / "
                f"{warm_summary.get('current_high_lockin_hit_count')}"
            )],
        ],
    ))
    lines.extend(["", "### Warm-Side Source Health", ""])
    lines.extend(markdown_table(
        [
            "Slice",
            "Cases",
            "Settled",
            "Open",
            "Model Hits",
            "Market Hits",
            "Lock-In Hits",
            "Model vs Market",
        ],
        render_warm_slice_rows(warm_slices.get("by_source_freshness")),
    ))
    lines.extend(["", "### Warm-Side Coastal / Marine Interaction", ""])
    lines.extend(markdown_table(
        [
            "Slice",
            "Cases",
            "Settled",
            "Open",
            "Model Hits",
            "Market Hits",
            "Lock-In Hits",
            "Model vs Market",
        ],
        render_warm_slice_rows(warm_slices.get("source_coastal_interaction")),
    ))
    lines.extend(["", "### Warm-Side Snapshot Cases", ""])
    lines.extend(markdown_table(
        [
            "Case",
            "Market",
            "Time",
            "High",
            "Model Top",
            "Model",
            "Market Top",
            "Market",
            "Warm Dist.",
            "Source",
            "Coastal",
            "Model vs Market",
            "Model vs Lock-In",
        ],
        render_warm_case_rows(warm_cases, limit=40),
    ))
    lines.append("")
    return "\n".join(lines)


def render_operator_report(payload):
    open_cases = [case for case in payload["cases"] if not case.get("settlement")]
    lines = [
        "# Open Disagreement Cases",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "These cases crossed the live disagreement thresholds and do not yet have "
        "a settlement outcome attached.",
        "",
    ]
    lines.extend(markdown_table(
        ["Case", "Market", "Band", "Time", "Edge", "Model", "Market", "Triggers", "Result", "Taxonomy"],
        render_case_rows(open_cases, limit=50),
    ))
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT, operator_out=DEFAULT_OPERATOR_OUT):
    json_out = Path(json_out)
    report_out = Path(report_out)
    operator_out = Path(operator_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    operator_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    operator_out.write_text(render_operator_report(payload), encoding="utf-8")
    return json_out, report_out, operator_out


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Build the model-market disagreement casebook.")
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders. Defaults to every folder under --snapshots-root.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--operator-out", default=str(DEFAULT_OPERATOR_OUT))
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    parser.add_argument("--market-collapse-price", type=float, default=DEFAULT_MARKET_COLLAPSE_PRICE)
    parser.add_argument("--market-collapse-drop", type=float, default=DEFAULT_MARKET_COLLAPSE_DROP)
    parser.add_argument("--model-high-prob", type=float, default=DEFAULT_MODEL_HIGH_PROB)
    parser.add_argument("--model-jump-threshold", type=float, default=DEFAULT_MODEL_JUMP_THRESHOLD)
    parser.add_argument("--source-support-delta", type=float, default=DEFAULT_SOURCE_SUPPORT_DELTA)
    parser.add_argument("--clob-midpoint-move", type=float, default=DEFAULT_CLOB_MIDPOINT_MOVE)
    parser.add_argument("--max-episode-gap-minutes", type=float, default=DEFAULT_MAX_EPISODE_GAP_MINUTES)
    parser.add_argument("--max-clob-age-seconds", type=float, default=DEFAULT_MAX_CLOB_AGE_SECONDS)
    parser.add_argument("--no-clob", dest="include_clob", action="store_false")
    parser.set_defaults(include_clob=True)
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = build_casebook(
        folders=args.folders,
        snapshots_root=args.snapshots_root,
        backtest_root=args.backtest_root,
        args=args,
    )
    json_out, report_out, operator_out = write_outputs(payload, args.json_out, args.report_out, args.operator_out)
    print(f"Wrote {json_out}")
    print(f"Wrote {report_out}")
    print(f"Wrote {operator_out}")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
