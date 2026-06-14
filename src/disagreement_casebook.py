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
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import brier, fmt_num, fmt_signed, markdown_table, trade_pnl  # noqa: E402
from market_config import date_from_event_slug  # noqa: E402
from market_registry import spec_for_slug  # noqa: E402
from model_presentation import DRIVER_WATERFALL_STAGES  # noqa: E402
from settlement_ledger import ledger_label_for_slug  # noqa: E402


SCHEMA_VERSION = "disagreement_casebook_v0.1"
DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_BACKTEST_ROOT = Path("data") / "backtest"
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
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
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
        "start_time_local": row.get("captured_at_local"),
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
    case["source_context"] = source_snapshot_context(row)
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
            "winning_band": settlement_label.get("winning_band"),
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
    case["peak_snapshot"] = peak
    case.pop("_last_dt", None)
    case["band_key"] = band_key_text(case["band_key"])
    return case


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
    folder_summaries = []
    for folder in discover_folders(snapshots_root, folders):
        cases, folder_summary = detect_cases_for_folder(folder, args, trust)
        folder_summaries.append(folder_summary)
        if not cases:
            continue
        replay_inputs = load_replay_inputs(folder)
        components = component_index(folder)
        settlement = load_settlement_label(folder)
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
        "cases": all_cases,
    }
    return payload


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
            case.get("range_label"),
            fmt_case_time(case),
            fmt_signed(case.get("edge"), 3),
            fmt_pct(case.get("model_probability")),
            fmt_pct(case.get("market_yes")),
            ", ".join(case.get("trigger_reasons") or []),
            case.get("model_result"),
            case.get("taxonomy"),
        ])
    return rows


def render_report(payload):
    summary = payload["summary"]
    cases = payload["cases"]
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
