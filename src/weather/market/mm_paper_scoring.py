"""Tape ingestion and accounting helpers for MM paper scoring."""

from __future__ import annotations

import bisect
import csv
import gc
import hashlib
import json
import math
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.backtesting.settlement_ledger import ledger_label_for_slug, resolve_outcome
from weather.io import (
    iter_csv_rows as io_iter_csv_rows,
    normalize_csv_row,
    read_csv_rows as io_read_csv_rows,
)
from weather.market.mm_policy import bool_value, early_hour_guardrail_state, maybe_float, parse_time
from weather.market.mm_paper_constants import (
    DEFAULT_CONFIG,
    DEFAULT_JSON_OUT,
    DEFAULT_RUNS_ROOT,
    MARKOUT_HORIZONS,
    SCHEMA_VERSION,
)
from weather.market.mm_paper_evidence import run_folder_eligibility


ACTIVE_DAY_EVIDENCE_MODE = "active_day_live_forward"


def utc_now():
    return datetime.now(timezone.utc)


def generated_at_iso(now=None):
    parsed = parse_time(now) if now is not None else None
    return (parsed or utc_now()).astimezone(timezone.utc).isoformat()


def read_csv_rows(path):
    return io_read_csv_rows(path, attach_diagnostics=True)


def iter_csv_rows(path):
    return io_iter_csv_rows(path, attach_diagnostics=True)


def write_csv(path, fieldnames, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(normalize_csv_row(row) for row in rows)
    return str(path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            _write_json_value(handle, payload, level=0)
            handle.write("\n")
        temp_path.replace(path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return str(path)


def _json_key_text(key):
    if isinstance(key, str):
        return key
    if key is None:
        return "null"
    if key is True:
        return "true"
    if key is False:
        return "false"
    if isinstance(key, (int, float)):
        return str(key)
    raise TypeError(f"keys must be str, int, float, bool or None, not {type(key).__name__}")


def _write_json_value(handle, value, *, level):
    """Write JSON incrementally, including disk-backed detail-row arrays."""

    indent = "  " * level
    child_indent = "  " * (level + 1)
    if isinstance(value, dict):
        if not value:
            handle.write("{}")
            return
        handle.write("{\n")
        keys = sorted(value)
        for index, key in enumerate(keys):
            if index:
                handle.write(",\n")
            handle.write(child_indent)
            handle.write(json.dumps(_json_key_text(key)))
            handle.write(": ")
            _write_json_value(handle, value[key], level=level + 1)
        handle.write(f"\n{indent}}}")
        return
    is_spilled_array = bool(
        getattr(value, "is_spilled_rows", False)
        or getattr(value, "is_spilled_queue_rows", False)
    )
    if isinstance(value, (list, tuple)) or is_spilled_array:
        iterator = iter(value)
        try:
            first = next(iterator)
        except StopIteration:
            handle.write("[]")
            return
        handle.write("[\n")
        handle.write(child_indent)
        _write_json_value(handle, first, level=level + 1)
        for item in iterator:
            handle.write(",\n")
            handle.write(child_indent)
            _write_json_value(handle, item, level=level + 1)
        handle.write(f"\n{indent}]")
        return
    encoder = json.JSONEncoder(default=str)
    for chunk in encoder.iterencode(value):
        handle.write(chunk)


def iter_jsonl(path):
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def read_jsonl(path):
    return list(iter_jsonl(path) or [])


def finite_float(value, default=None):
    number = maybe_float(value)
    return default if number is None else number


def clamp01(value):
    number = maybe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def iso_or_blank(value):
    parsed = parse_time(value)
    return parsed.isoformat() if parsed else ""


def compact_float(value, digits=6):
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def label_numbers(label):
    import re

    return [int(value) for value in re.findall(r"-?\d+", str(label or ""))]


def band_key(row):
    kind = str(row.get("bin_kind") or row.get("winning_band_kind") or "").strip().lower()
    value = row.get("bin_value")
    if value in (None, ""):
        value = row.get("bin_value_c") or row.get("winning_band_value")
    value_hi = row.get("bin_value_hi") or row.get("winning_band_value_hi")
    value = int(float(value)) if maybe_float(value) is not None else None
    value_hi = int(float(value_hi)) if maybe_float(value_hi) is not None else None
    nums = label_numbers(row.get("range_label") or row.get("winning_band"))
    if value is None and nums:
        value = nums[0]
    if value_hi is None and nums:
        value_hi = nums[-1]
    if value_hi is None:
        value_hi = value
    if not kind:
        text = str(row.get("range_label") or row.get("winning_band") or "").lower()
        if "above" in text or "higher" in text:
            kind = "gte"
        elif "below" in text or "under" in text:
            kind = "lte"
        else:
            kind = "eq"
    return kind, value, value_hi


def band_key_text(row):
    kind, value, value_hi = band_key(row)
    if value is None:
        return ""
    if kind == "eq" and value_hi not in (None, value):
        return f"{kind}:{value}-{value_hi}"
    return f"{kind}:{value}"


def band_distance_bucket(row):
    value = finite_float(row.get("bin_value"))
    if value is None:
        nums = label_numbers(row.get("range_label"))
        value = float(nums[0]) if nums else None
    market_mid = finite_float(row.get("market_mid"))
    fair = finite_float(row.get("fair_probability"))
    if market_mid is not None and fair is not None:
        distance = abs(fair - market_mid)
        if distance < 0.01:
            return "edge_lt_1c"
        if distance < 0.03:
            return "edge_1c_3c"
        if distance < 0.08:
            return "edge_3c_8c"
        return "edge_ge_8c"
    if value is None:
        return "unknown"
    return band_key_text(row) or "unknown"


def book_imbalance_bucket(value):
    number = finite_float(value)
    if number is None:
        return "unknown"
    if number <= -0.25:
        return "ask_heavy"
    if number >= 0.25:
        return "bid_heavy"
    return "balanced"


def hour_bucket(value):
    parsed = parse_time(value)
    return f"{parsed.hour:02d}:00Z" if parsed else "unknown"


def discover_run_folders(runs_root=DEFAULT_RUNS_ROOT, run_folders=None):
    if run_folders:
        return [Path(item) for item in run_folders]
    root = Path(runs_root)
    if not root.exists():
        return []
    return sorted(
        [folder for folder in root.glob("*/*") if folder.is_dir() and (folder / "quote_intents_long.csv").exists()],
        key=lambda path: str(path),
    )


def _path_mtime_iso(path):
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _run_folder_freshness_row(folder):
    folder = Path(folder)
    summary_path = folder / "run_summary.json"
    summary = read_json(summary_path, {}) or {}
    run_config = read_json(folder / "run_config.json", {}) or {}
    live_gate = summary.get("live_forward_gate") or {}
    evidence_mode = summary.get("evidence_mode") or live_gate.get("evidence_mode")
    target_date = summary.get("target_date") or run_config.get("target_date") or folder.parent.name
    run_id = summary.get("run_id") or run_config.get("run_id") or folder.name
    completed = summary_path.exists() and (folder / "quote_intents_long.csv").exists()
    return {
        "run_folder": str(folder),
        "run_id": run_id,
        "target_date": target_date,
        "mode": summary.get("mode") or run_config.get("mode"),
        "evidence_mode": evidence_mode,
        "completed": completed,
        "active_day": evidence_mode == ACTIVE_DAY_EVIDENCE_MODE,
        "counts_toward_live_forward_gate": bool_value(
            summary.get("counts_toward_live_forward_gate")
            if summary.get("counts_toward_live_forward_gate") is not None
            else live_gate.get("counts_toward_live_forward_gate"),
            False,
        ),
        "generated_at_utc": summary.get("generated_at_utc") or summary.get("started_at_utc") or "",
        "run_summary_mtime_utc": _path_mtime_iso(summary_path),
    }


def _run_freshness_sort_key(row):
    return (
        str(row.get("target_date") or ""),
        str(row.get("generated_at_utc") or ""),
        str(row.get("run_summary_mtime_utc") or ""),
        str(row.get("run_id") or ""),
        str(row.get("run_folder") or ""),
    )


def maker_paper_score_freshness(candidate_run_folders, covered_run_folders=None, *, report_generated_at_utc=None):
    covered = {str(Path(folder)) for folder in covered_run_folders or []}
    rows = [_run_folder_freshness_row(folder) for folder in candidate_run_folders or []]
    active_completed = [
        row for row in rows
        if row.get("active_day") and row.get("completed")
    ]
    covered_active = [
        row for row in active_completed
        if row.get("run_folder") in covered
    ]
    latest_completed = max(active_completed, key=_run_freshness_sort_key, default={})
    latest_covered = max(covered_active, key=_run_freshness_sort_key, default={})
    if not latest_completed:
        status = "NO_ACTIVE_DAY"
        reason = "no completed active-day maker run found"
    elif latest_covered.get("run_folder") == latest_completed.get("run_folder"):
        status = "PASS"
        reason = "standard maker paper score covers the latest completed active day"
    else:
        status = "STALE"
        reason = "standard maker paper score does not cover the latest completed active day"
    return {
        "status": status,
        "reason": reason,
        "report_generated_at_utc": report_generated_at_utc,
        "latest_completed_active_day": latest_completed.get("target_date"),
        "latest_completed_active_run_id": latest_completed.get("run_id"),
        "latest_completed_active_run_folder": latest_completed.get("run_folder"),
        "latest_covered_active_day": latest_covered.get("target_date"),
        "latest_covered_active_run_id": latest_covered.get("run_id"),
        "latest_covered_active_run_folder": latest_covered.get("run_folder"),
        "completed_active_run_count": len(active_completed),
        "covered_active_run_count": len(covered_active),
        "live_forward_day_count": len({row.get("target_date") for row in covered_active if row.get("target_date")}),
        "blocks_maker_evidence_countability": status == "STALE",
        "covered_run_folders": sorted(covered),
    }


def maker_paper_score_freshness_from_report(runs_root=DEFAULT_RUNS_ROOT, report_json=DEFAULT_JSON_OUT):
    candidate_run_folders = discover_run_folders(runs_root)
    payload = read_json(report_json, {}) or {}
    summary = payload.get("summary") or {}
    freshness = summary.get("paper_score_freshness") or {}
    covered = freshness.get("covered_run_folders")
    if covered is None:
        covered = list((payload.get("run_configs") or {}).keys())
    result = maker_paper_score_freshness(
        candidate_run_folders,
        covered,
        report_generated_at_utc=payload.get("generated_at_utc"),
    )
    result["report_json"] = str(Path(report_json))
    result["report_exists"] = Path(report_json).exists()
    if not result["report_exists"] and result.get("status") == "PASS":
        result["status"] = "STALE"
        result["reason"] = "standard maker paper score JSON is missing"
        result["blocks_maker_evidence_countability"] = True
    return result


def quote_id(row, index):
    digest = hashlib.sha1(
        "|".join([
            str(row.get("run_id") or ""),
            str(row.get("event_slug") or ""),
            str(row.get("clob_token_id") or ""),
            str(row.get("range_label") or ""),
            str(row.get("generated_at_utc") or ""),
            str(index),
        ]).encode("utf-8")
    ).hexdigest()[:12]
    return f"quote_{digest}"


def load_quote_rows(run_folders, eligibility_by_folder=None, quote_filename="quote_intents_long.csv"):
    rows = []
    run_configs = {}
    eligibility_by_folder = eligibility_by_folder or {}
    for folder in run_folders:
        folder = Path(folder)
        run_config = read_json(folder / "run_config.json", {}) or {}
        run_configs[str(folder)] = run_config
        eligibility = eligibility_by_folder.get(str(folder)) or run_folder_eligibility(folder)
        for index, row in enumerate(iter_csv_rows(folder / quote_filename)):
            row = dict(row)
            row["_run_folder"] = str(folder)
            row["_quote_row_index"] = index
            row["_quote_id"] = quote_id(row, index)
            row["_run_config"] = run_config
            row["_run_schema_version"] = eligibility.get("schema_version")
            row["_run_live_forward_gate_counts"] = eligibility.get("live_forward_gate_counts", True)
            rows.append(row)
    return rows, run_configs


def load_model_variant_quote_rows(run_folders, eligibility_by_folder=None):
    return load_quote_rows(
        run_folders,
        eligibility_by_folder=eligibility_by_folder,
        quote_filename="model_variant_quote_intents_long.csv",
    )


def quote_permission(row):
    return bool_value(row.get("quote_permission"), False)


def quote_legs(quote_rows, config):
    legs = []
    for row in quote_rows:
        if not quote_permission(row):
            continue
        quote_time = parse_time(row.get("generated_at_utc") or row.get("captured_at_utc"))
        if quote_time is None:
            continue
        market_mid = clamp01(row.get("market_mid") or row.get("market_yes"))
        fair_probability = clamp01(row.get("fair_probability") or row.get("model_probability") or row.get("candidate_p"))
        edge = finite_float(row.get("edge"))
        if edge is None and fair_probability is not None and market_mid is not None:
            edge = fair_probability - market_mid
        guardrail = early_hour_guardrail_state(row, config=config, now=quote_time)
        common = {
            "quote_row": row,
            "quote_id": row["_quote_id"],
            "run_id": row.get("run_id") or (row.get("_run_config") or {}).get("run_id") or "",
            "run_folder": row.get("_run_folder") or "",
            "run_mode": row.get("run_mode") or (row.get("_run_config") or {}).get("mode") or "",
            "policy_hash": row.get("policy_hash") or (row.get("_run_config") or {}).get("policy_hash") or "",
            "model_variant_id": row.get("model_variant_id") or "served_current",
            "model_variant_family": row.get("model_variant_family") or "served_current",
            "model_variant_role": row.get("model_variant_role") or "served",
            "model_variant_basket_id": row.get("model_variant_basket_id") or "",
            "model_variant_probability_source": row.get("model_variant_probability_source") or "",
            "model_variant_counterfactual": bool_value(row.get("model_variant_counterfactual"), False),
            "served_model_version": row.get("served_model_version") or row.get("model_version") or "",
            "event_slug": row.get("event_slug") or "",
            "market_id": row.get("market_id") or "",
            "target_date": row.get("target_date") or (row.get("_run_config") or {}).get("target_date") or "",
            "range_label": row.get("range_label") or "",
            "generated_at_utc": row.get("generated_at_utc") or row.get("captured_at_utc") or "",
            "reason_code": row.get("reason_code") or "",
            "known_edge_permission": row.get("known_edge_permission") or "",
            "promotion_state": row.get("promotion_state") or "",
            "bin_kind": row.get("bin_kind") or "",
            "bin_value": row.get("bin_value") or row.get("bin_value_c") or "",
            "bin_value_hi": row.get("bin_value_hi") or "",
            "clob_token_id": row.get("clob_token_id") or row.get("asset_id") or "",
            "quote_time": quote_time,
            "market_mid": market_mid,
            "book_spread": finite_float(row.get("book_spread")),
            "best_bid": finite_float(row.get("best_bid_price") or row.get("book_best_bid") or row.get("best_bid")),
            "best_ask": finite_float(row.get("best_ask_price") or row.get("book_best_ask") or row.get("best_ask")),
            "tick_size": finite_float(row.get("tick_size")),
            "min_order_size": finite_float(row.get("min_order_size")),
            "fair_probability": fair_probability,
            "edge": edge,
            "capture_hour_utc": guardrail.get("capture_hour_utc"),
            "capture_hour_local": guardrail.get("capture_hour_local"),
            "capture_timezone": guardrail.get("capture_timezone"),
            "hourly_trust_band": guardrail.get("hourly_trust_band"),
            "hourly_trust_multiplier": guardrail.get("hourly_trust_multiplier"),
            "early_hour_guardrail_status": row.get("early_hour_guardrail_status") or guardrail.get("early_hour_guardrail_status"),
            "early_hour_guardrail_reason": row.get("early_hour_guardrail_reason") or guardrail.get("early_hour_guardrail_reason"),
            "early_hour_guardrail_min_edge": finite_float(row.get("early_hour_guardrail_min_edge"), guardrail.get("early_hour_guardrail_min_edge")),
            "early_hour_guardrail_size_multiplier": finite_float(
                row.get("early_hour_guardrail_size_multiplier"),
                guardrail.get("early_hour_guardrail_size_multiplier"),
            ),
            "early_hour_guardrail_quote_widen_buffer": finite_float(
                row.get("early_hour_guardrail_quote_widen_buffer"),
                guardrail.get("early_hour_guardrail_quote_widen_buffer"),
            ),
            "early_hour_guardrail_override_allowed": bool_value(
                row.get("early_hour_guardrail_override_allowed"),
                bool(guardrail.get("early_hour_guardrail_override_allowed")),
            ),
            "early_hour_guardrail_market_weight": finite_float(
                row.get("early_hour_guardrail_market_weight"),
                guardrail.get("early_hour_guardrail_market_weight"),
            ),
            "market_aware_overlay_probability": finite_float(
                row.get("market_aware_overlay_probability"),
                guardrail.get("market_aware_overlay_probability"),
            ),
            "market_aware_overlay_edge": finite_float(
                row.get("market_aware_overlay_edge"),
                guardrail.get("market_aware_overlay_edge"),
            ),
            "market_aware_overlay_used_for_risk_only": bool_value(
                row.get("market_aware_overlay_used_for_risk_only"),
                bool(guardrail.get("market_aware_overlay_used_for_risk_only")),
            ),
            "regime": row.get("regime") or "",
            "source_fresh": bool_value(row.get("source_fresh"), False),
            "source_freshness_state": row.get("source_freshness_state") or "",
            "book_imbalance_bucket": book_imbalance_bucket(row.get("book_imbalance_1pct")),
            "band_distance_bucket": band_distance_bucket(row),
            "event_gate_status": row.get("event_gate_status") or "",
            "event_gate_action": row.get("event_gate_action") or "",
            "event_gate_reason_code": row.get("event_gate_reason_code") or "",
            "event_gate_event_class": row.get("event_gate_event_class") or "",
            "event_gate_event_id": row.get("event_gate_event_id") or "",
            "event_gate_next_event_at_utc": row.get("event_gate_next_event_at_utc") or "",
            "event_gate_exception_id": row.get("event_gate_exception_id") or "",
            "quote_age_seconds": None,
            "reward_estimate_usdc": 0.0,
            "reward_q_min": 0.0,
            "reward_normalized_share": 0.0,
        }
        captured = parse_time(row.get("captured_at_utc"))
        if captured is not None:
            common["quote_age_seconds"] = max(0.0, (quote_time - captured).total_seconds())
        bid = clamp01(row.get("bid_price"))
        bid_size = finite_float(row.get("bid_size"), 0.0) or 0.0
        ask = clamp01(row.get("ask_price"))
        ask_size = finite_float(row.get("ask_size"), 0.0) or 0.0
        if bid is not None and bid_size > 0:
            leg = dict(common)
            leg.update({
                "leg_id": f"{common['quote_id']}:YES_BID",
                "side": "YES_BID",
                "direction": 1.0,
                "quote_price": bid,
                "quote_size": bid_size,
            })
            legs.append(leg)
        if ask is not None and ask_size > 0:
            leg = dict(common)
            leg.update({
                "leg_id": f"{common['quote_id']}:YES_ASK",
                "side": "YES_ASK",
                "direction": -1.0,
                "quote_price": ask,
                "quote_size": ask_size,
            })
            legs.append(leg)
    attach_expiry(legs, config)
    attach_reward_estimates(legs, config)
    for leg in legs:
        leg.pop("quote_row", None)
    return legs


def attach_expiry(legs, config):
    ttl = float(config["quote_ttl_seconds"])
    grouped = defaultdict(list)
    for leg in legs:
        grouped[(leg["run_id"], leg["event_slug"], leg["clob_token_id"], leg["side"])].append(leg)
    for group in grouped.values():
        group.sort(key=lambda leg: leg["quote_time"])
        for index, leg in enumerate(group):
            ttl_expiry = leg["quote_time"] + timedelta(seconds=ttl)
            next_time = group[index + 1]["quote_time"] if index + 1 < len(group) else None
            if next_time and next_time > leg["quote_time"]:
                leg["quote_expires_at"] = min(ttl_expiry, next_time)
            else:
                leg["quote_expires_at"] = ttl_expiry


def reward_leg_score(price, size, mid, min_order_size, threshold):
    if price is None or mid is None or size <= 0 or size < min_order_size:
        return 0.0
    distance = abs(float(price) - float(mid))
    if distance > threshold:
        return 0.0
    return float(size) * max(0.0, 1.0 - distance / max(threshold, 1e-9))


def attach_reward_estimates(legs, config):
    by_quote = defaultdict(list)
    for leg in legs:
        by_quote[leg["quote_id"]].append(leg)
    for quote_legs_ in by_quote.values():
        row = quote_legs_[0]["quote_row"]
        mid = quote_legs_[0].get("market_mid")
        min_order = finite_float(row.get("min_order_size"), 0.0) or 0.0
        threshold = float(config["reward_distance_threshold"])
        campaign_pool = float(config["reward_campaign_pool_usdc"])
        competitor_q = max(0.0, float(config["reward_competitor_q"]))
        scores = {}
        for leg in quote_legs_:
            scores[leg["side"]] = reward_leg_score(
                leg["quote_price"],
                leg["quote_size"],
                mid,
                min_order,
                threshold,
            )
        q_one = scores.get("YES_BID", 0.0)
        q_two = scores.get("YES_ASK", 0.0)
        c = max(1.0, float(config["reward_c"]))
        q_min = max(min(q_one, q_two), max(q_one / c, q_two / c))
        qualifying_size = max(0.0, q_min)
        normalized_share = q_min / (q_min + competitor_q) if q_min > 0 else 0.0
        estimate = campaign_pool * normalized_share
        if estimate < float(config["reward_min_payout_usdc"]):
            estimate = 0.0
        total_size = sum(leg["quote_size"] for leg in quote_legs_) or 1.0
        for leg in quote_legs_:
            leg["reward_estimate_usdc"] = estimate * (leg["quote_size"] / total_size)
            leg["reward_q_min"] = q_min
            leg["reward_qualifying_size"] = qualifying_size
            leg["reward_normalized_share"] = normalized_share
            leg["reward_formula"] = "q_min=max(min(q_one,q_two),max(q_one/c,q_two/c)); normalized=q_min/(q_min+competition_q)"


def load_trade_rows(folder):
    folder = Path(folder)
    rows = []
    missing_size_count = 0

    def add_trade(raw, source, index):
        nonlocal missing_size_count
        trade = raw.get("trade") if isinstance(raw.get("trade"), dict) else {}
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        ts = parse_time(
            raw.get("trade_time_utc")
            or raw.get("timestamp_utc")
            or raw.get("received_at_utc")
            or raw.get("captured_at_utc")
            or raw.get("time")
            or trade.get("trade_time_utc")
            or trade.get("timestamp")
            or payload.get("timestamp_utc")
        )
        token = (
            raw.get("clob_token_id")
            or raw.get("asset_id")
            or raw.get("token_id")
            or raw.get("assetId")
            or trade.get("asset_id")
            or trade.get("token_id")
            or payload.get("asset_id")
        )
        price = clamp01(
            raw.get("price")
            or raw.get("trade_price")
            or raw.get("last_trade_price")
            or trade.get("price")
            or payload.get("price")
        )
        size = finite_float(
            raw.get("size")
            or raw.get("trade_size")
            or raw.get("shares")
            or raw.get("amount")
            or raw.get("matched_amount")
            or raw.get("maker_amount")
            or raw.get("matched_size")
            or raw.get("size_matched")
            or raw.get("quantity")
            or trade.get("size")
            or trade.get("trade_size")
            or trade.get("shares")
            or trade.get("amount")
            or payload.get("size")
            or payload.get("trade_size")
        )
        if ts is None or not token or price is None:
            return
        if size is None or size <= 0:
            missing_size_count += 1
            size = None
        rows.append({
            "trade_id": f"{source}:{index}",
            "time": ts,
            "clob_token_id": str(token),
            "price": float(price),
            "size": float(size) if size is not None else None,
            "side": raw.get("side") or raw.get("taker_side") or "",
            "source": source,
        })

    for filename in ("trades_long.csv", "market_trades.csv", "market_ws_events.csv"):
        for index, row in enumerate(iter_csv_rows(folder / filename)):
            add_trade(row, filename, index)

    jsonl_index = 0
    for raw in iter_jsonl(folder / "market_ws.jsonl") or []:
        candidates = [raw]
        payload = raw.get("payload") if isinstance(raw, dict) else None
        if isinstance(payload, dict):
            candidates.append(payload)
            for key in ("price_changes", "trades", "fills"):
                values = payload.get(key)
                if isinstance(values, list):
                    candidates.extend(item for item in values if isinstance(item, dict))
        for key in ("price_changes", "trades", "fills"):
            values = raw.get(key) if isinstance(raw, dict) else None
            if isinstance(values, list):
                candidates.extend(item for item in values if isinstance(item, dict))
        for candidate in candidates:
            if "received_at_utc" not in candidate and isinstance(raw, dict):
                candidate = {**candidate, "received_at_utc": raw.get("received_at_utc")}
            add_trade(candidate, "market_ws.jsonl", jsonl_index)
            jsonl_index += 1

    rows.sort(key=lambda row: (row["time"], row["trade_id"]))
    return rows, {"trade_rows": len(rows), "missing_size_trade_rows": missing_size_count}


def strict_trade_through(side, trade_price, quote_price):
    if side == "YES_BID":
        return trade_price < quote_price
    if side == "YES_ASK":
        return trade_price > quote_price
    return False


def load_book_rows(folder):
    rows = []
    for row in iter_csv_rows(Path(folder) / "order_books_summary.csv"):
        token = row.get("clob_token_id") or row.get("asset_id") or ""
        ts = parse_time(row.get("captured_at_utc") or row.get("book_time_utc") or row.get("captured_at_local"))
        if not token or ts is None:
            continue
        best_bid = clamp01(row.get("best_bid"))
        best_ask = clamp01(row.get("best_ask"))
        midpoint = clamp01(row.get("midpoint"))
        if midpoint is None and best_bid is not None and best_ask is not None and best_ask >= best_bid:
            midpoint = (best_bid + best_ask) / 2.0
        rows.append({
            "time": ts,
            "event_slug": row.get("event_slug") or Path(folder).name,
            "market_id": row.get("market_id") or "",
            "range_label": row.get("range_label") or "",
            "bin_kind": row.get("bin_kind") or "",
            "bin_value": row.get("bin_value") or "",
            "bin_value_hi": row.get("bin_value_hi") or "",
            "clob_token_id": str(token),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "midpoint": midpoint,
            "last_trade_price": clamp01(row.get("last_trade_price") or row.get("gamma_last_trade_price")),
            "bid_size_at_best": finite_float(row.get("bid_size_at_best"), 0.0) or 0.0,
            "ask_size_at_best": finite_float(row.get("ask_size_at_best"), 0.0) or 0.0,
            "bid_depth_1pct": finite_float(row.get("bid_depth_1pct"), 0.0) or 0.0,
            "ask_depth_1pct": finite_float(row.get("ask_depth_1pct"), 0.0) or 0.0,
            "tick_size": finite_float(row.get("tick_size"), 0.001) or 0.001,
        })
    rows.sort(key=lambda row: (row["clob_token_id"], row["time"]))
    return rows


class TimeIndexedRows(list):
    __slots__ = ("times",)

    def rebuild_time_index(self):
        self.times = [row["time"] for row in self]
        return self


def _time_index_for_rows(rows):
    times = getattr(rows, "times", None)
    if times is None or len(times) != len(rows):
        times = [row["time"] for row in rows]
    return times


def group_by_token(rows):
    grouped = defaultdict(TimeIndexedRows)
    for row in rows:
        grouped[row["clob_token_id"]].append(row)
    for values in grouped.values():
        values.sort(key=lambda row: row["time"])
        values.rebuild_time_index()
    return grouped


def nearest_row_before(rows, timestamp):
    if not rows or timestamp is None:
        return None
    times = _time_index_for_rows(rows)
    pos = bisect.bisect_right(times, timestamp)
    return rows[pos - 1] if pos > 0 else None


def rows_between(rows, start, end):
    if not rows:
        return []
    times = _time_index_for_rows(rows)
    lo = bisect.bisect_right(times, start)
    hi = bisect.bisect_right(times, end)
    return rows[lo:hi]


def queue_ahead_for_leg(leg, book_row):
    if not book_row:
        return None, "missing_initial_book"
    tick = max(1e-9, float(book_row.get("tick_size") or 0.001))
    price = leg["quote_price"]
    if leg["side"] == "YES_BID":
        best = book_row.get("best_bid")
        if best is None:
            return None, "missing_best_bid"
        if price > best + tick / 2.0:
            return 0.0, "improves_best_bid"
        if abs(price - best) <= tick / 2.0:
            return float(book_row.get("bid_size_at_best") or 0.0), "joins_best_bid"
        return float(book_row.get("bid_depth_1pct") or book_row.get("bid_size_at_best") or 0.0), "behind_best_bid"
    best = book_row.get("best_ask")
    if best is None:
        return None, "missing_best_ask"
    if price < best - tick / 2.0:
        return 0.0, "improves_best_ask"
    if abs(price - best) <= tick / 2.0:
        return float(book_row.get("ask_size_at_best") or 0.0), "joins_best_ask"
    return float(book_row.get("ask_depth_1pct") or book_row.get("ask_size_at_best") or 0.0), "behind_best_ask"


def queue_simulate_leg(leg, book_by_token, trades_by_token):
    books = book_by_token.get(leg["clob_token_id"]) or []
    start_row = nearest_row_before(books, leg["quote_time"])
    ahead, position = queue_ahead_for_leg(leg, start_row)
    if ahead is None:
        return {
            "leg_id": leg["leg_id"],
            "status": "missing_book",
            "estimated_fill_size": 0.0,
            "initial_queue_ahead": None,
            "depleted_ahead": 0.0,
            "reason": position,
        }
    candidates = rows_between(books, leg["quote_time"], leg["quote_expires_at"])
    max_depletion = 0.0
    touched = False
    through = False
    for row in candidates:
        if leg["side"] == "YES_BID":
            best = row.get("best_bid")
            current_size = float(row.get("bid_size_at_best") or 0.0)
            if best is not None and abs(best - leg["quote_price"]) <= float(row.get("tick_size") or 0.001) / 2.0:
                touched = True
                max_depletion = max(max_depletion, max(0.0, ahead - current_size))
            if best is not None and best < leg["quote_price"]:
                through = True
                max_depletion = max(max_depletion, ahead + leg["quote_size"])
        else:
            best = row.get("best_ask")
            current_size = float(row.get("ask_size_at_best") or 0.0)
            if best is not None and abs(best - leg["quote_price"]) <= float(row.get("tick_size") or 0.001) / 2.0:
                touched = True
                max_depletion = max(max_depletion, max(0.0, ahead - current_size))
            if best is not None and best > leg["quote_price"]:
                through = True
                max_depletion = max(max_depletion, ahead + leg["quote_size"])
    missing_size_through = any(
        strict_trade_through(leg["side"], trade["price"], leg["quote_price"]) and trade.get("size") is None
        for trade in rows_between(trades_by_token.get(leg["clob_token_id"]) or [], leg["quote_time"], leg["quote_expires_at"])
    )
    if through:
        status = "estimated_full_fill"
        estimated = leg["quote_size"]
        reason = "book_moved_through_quote_price"
    elif max_depletion > 0:
        status = "estimated_partial_or_ahead_cancellation"
        ratio = min(1.0, max_depletion / max(ahead, leg["quote_size"], 1e-9))
        estimated = leg["quote_size"] * ratio
        reason = "best_queue_size_declined"
    elif missing_size_through:
        status = "missed_missing_trade_size"
        estimated = 0.0
        reason = "strict_trade_through_seen_without_size"
    elif touched:
        status = "missed_queue_ahead"
        estimated = 0.0
        reason = "quote_price_touched_without_queue_depletion"
    else:
        status = "no_touch"
        estimated = 0.0
        reason = "book_never_reached_quote_price"
    return {
        "leg_id": leg["leg_id"],
        "status": status,
        "estimated_fill_size": compact_float(estimated) or 0.0,
        "initial_queue_ahead": compact_float(ahead),
        "depleted_ahead": compact_float(max_depletion) or 0.0,
        "reason": f"{position}; {reason}",
    }


def load_mark_rows(folder):
    folder = Path(folder)
    marks = []

    def add_mark(raw, source, token_key="clob_token_id", time_keys=("point_time_utc", "captured_at_utc", "received_at_utc")):
        token = raw.get(token_key) or raw.get("asset_id") or raw.get("token_id") or raw.get("assetId")
        ts = None
        for key in time_keys:
            ts = parse_time(raw.get(key))
            if ts is not None:
                break
        price = clamp01(raw.get("midpoint") or raw.get("price") or raw.get("last_trade_price") or raw.get("gamma_last_trade_price"))
        if price is None:
            bid = clamp01(raw.get("best_bid"))
            ask = clamp01(raw.get("best_ask"))
            if bid is not None and ask is not None and ask >= bid:
                price = (bid + ask) / 2.0
        if token and ts is not None and price is not None:
            marks.append({
                "time": ts,
                "clob_token_id": str(token),
                "price": float(price),
                "source": source,
            })

    for row in iter_csv_rows(folder / "price_history.csv"):
        add_mark(row, "price_history.csv", time_keys=("point_time_utc", "timestamp_utc", "captured_at_utc"))
    for row in iter_csv_rows(folder / "order_books_summary.csv"):
        add_mark(row, "order_books_summary.csv", time_keys=("captured_at_utc", "book_time_utc", "captured_at_local"))
    for row in iter_csv_rows(folder / "market_ws_events.csv"):
        add_mark(row, "market_ws_events.csv", time_keys=("received_at_utc", "timestamp_utc", "captured_at_utc"))
    marks.sort(key=lambda row: (row["clob_token_id"], row["time"]))
    return marks


def mark_at(mark_by_token, token, target_time):
    rows = mark_by_token.get(str(token)) or []
    if not rows:
        return None
    times = _time_index_for_rows(rows)
    pos = bisect.bisect_left(times, target_time)
    if pos < len(rows):
        return rows[pos]
    return None


def settlement_for_folder(folder, event_slug, ledger_root=None):
    folder = Path(folder)
    local = read_json(folder / "settlement.json", None)
    if local:
        return local
    try:
        return ledger_label_for_slug(event_slug, ledger_root=ledger_root)
    except TypeError:
        return ledger_label_for_slug(event_slug)


def settlement_outcome_for_leg(leg, settlement):
    if not settlement:
        return None
    bucket = finite_float(settlement.get("settlement_bucket"))
    kind, value, value_hi = band_key(leg)
    if bucket is None or value is None:
        return None
    try:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi=value_hi) else 0.0
    except TypeError:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi) else 0.0


def iter_casebook_cases(path):
    path = Path(path)
    if not path.exists():
        return
    seeking_cases = True
    seeking_array = False
    depth = 0
    in_string = False
    escape = False
    object_chars = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if seeking_cases:
                if '"cases"' not in line:
                    continue
                seeking_cases = False
                if "[" in line:
                    line = line.split("[", 1)[1]
                else:
                    seeking_array = True
                    continue
            if seeking_array:
                if "[" not in line:
                    continue
                seeking_array = False
                line = line.split("[", 1)[1]
            for char in line:
                if depth == 0:
                    if char == "{":
                        object_chars = ["{"]
                        depth = 1
                        in_string = False
                        escape = False
                    elif char == "]":
                        return
                    continue
                object_chars.append(char)
                if in_string:
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            yield json.loads("".join(object_chars))
                        except json.JSONDecodeError:
                            pass
                        object_chars = []


def load_casebook_index(path, event_slugs=None):
    wanted_events = {str(event) for event in event_slugs or [] if event}
    restrict_events = bool(wanted_events)
    index = defaultdict(list)
    for case in iter_casebook_cases(path) or []:
        event_slug = case.get("event_slug") or ""
        if restrict_events and event_slug not in wanted_events:
            continue
        market_id = case.get("market_id") or ""
        label = case.get("range_label") or ""
        key = (event_slug, market_id, label)
        start = parse_time(case.get("start_time_utc") or case.get("start_time_local"))
        end = parse_time(case.get("end_time_utc") or case.get("end_time_local"))
        index[key].append({
            "case_id": case.get("case_id") or "",
            "taxonomy": case.get("taxonomy") or "",
            "start": start,
            "end": end,
        })
    return index


def casebook_for_fill(leg, fill_time, casebook_index):
    keys = [
        (leg.get("event_slug") or "", leg.get("market_id") or "", leg.get("range_label") or ""),
        (leg.get("event_slug") or "", "", leg.get("range_label") or ""),
    ]
    for key in keys:
        for case in casebook_index.get(key) or []:
            start = case.get("start")
            end = case.get("end")
            if start and end and start <= fill_time <= end:
                return case
            if start is None and end is None:
                return case
    for case in casebook_index.get(keys[0]) or []:
        return case
    return {"case_id": "", "taxonomy": ""}


def fee_equivalent(size, price, fee_rate):
    return max(0.0, float(size)) * max(0.0, float(fee_rate)) * max(0.0, float(price)) * max(0.0, 1.0 - float(price))


def compute_fill_financials(leg, fill, mark_by_token, settlement, config):
    fill_time = fill["fill_time"]
    price = fill["fill_price"]
    size = fill["fill_size"]
    direction = leg["direction"]
    mid = leg.get("market_mid")
    if mid is None:
        mid = price
    markouts = {}
    for label, seconds in MARKOUT_HORIZONS:
        mark = mark_at(mark_by_token, leg["clob_token_id"], fill_time + timedelta(seconds=seconds))
        future = mark.get("price") if mark else None
        markouts[label] = (direction * (future - price)) if future is not None else None
    mark_30m = markouts.get("30m")
    adverse_30m = None
    mark_30m_row = mark_at(mark_by_token, leg["clob_token_id"], fill_time + timedelta(seconds=1800))
    if mark_30m_row and mid is not None:
        adverse_30m = direction * (mark_30m_row["price"] - mid) * size
    outcome = settlement_outcome_for_leg(leg, settlement)
    settlement_markout = direction * (outcome - price) if outcome is not None else None
    settlement_pnl = settlement_markout * size if settlement_markout is not None else None
    if leg["side"] == "YES_BID":
        spread_capture = (mid - price) * size
    else:
        spread_capture = (price - mid) * size
    maker_fee_equiv = fee_equivalent(size, price, config["maker_fee_rate"])
    maker_rebate = maker_fee_equiv * float(config["maker_rebate_pool_share"])
    flatten_fee = fee_equivalent(size, price, config["flattening_fee_rate"])
    reward = float(leg.get("reward_estimate_usdc") or 0.0) * (size / max(leg["quote_size"], 1e-9))
    if settlement_pnl is not None:
        net = settlement_pnl + maker_rebate + reward - flatten_fee
    elif mark_30m is not None:
        net = mark_30m * size + maker_rebate + reward - flatten_fee
    else:
        net = maker_rebate + reward - flatten_fee
    return {
        "markouts": markouts,
        "settlement_outcome": outcome,
        "settlement_markout": settlement_markout,
        "settlement_pnl": settlement_pnl,
        "spread_capture": spread_capture,
        "adverse_30m": adverse_30m,
        "maker_fee_equiv": maker_fee_equiv,
        "maker_rebate": maker_rebate,
        "reward": reward,
        "flatten_fee": flatten_fee,
        "net": net,
    }


def conservative_fill_row(
    leg,
    trade,
    fill_size,
    cumulative_leg_fill_size,
    bundle,
    casebook_index,
    queue,
    config,
):
    """Build one conservative fill row without retaining its source leg."""

    fill = {
        "fill_time": trade["time"],
        "fill_price": leg["quote_price"],
        "fill_size": fill_size,
        "through_trade_price": trade["price"],
        "through_trade_size": trade["size"],
        "trade_source": trade["source"],
    }
    financials = compute_fill_financials(
        leg,
        fill,
        bundle.get("marks_by_token") or {},
        bundle.get("settlement"),
        config,
    )
    case = casebook_for_fill(leg, trade["time"], casebook_index)
    fill_id = (
        "fill_"
        + hashlib.sha1(
            (
                leg["leg_id"]
                + trade["trade_id"]
                + str(cumulative_leg_fill_size)
            ).encode("utf-8")
        ).hexdigest()[:12]
    )
    row = {
        "paper_schema_version": SCHEMA_VERSION,
        "run_id": leg["run_id"],
        "run_folder": leg["run_folder"],
        "run_mode": leg["run_mode"],
        "policy_hash": leg["policy_hash"],
        "model_variant_id": leg.get("model_variant_id") or "served_current",
        "model_variant_family": leg.get("model_variant_family") or "served_current",
        "model_variant_role": leg.get("model_variant_role") or "served",
        "model_variant_basket_id": leg.get("model_variant_basket_id") or "",
        "model_variant_probability_source": leg.get("model_variant_probability_source") or "",
        "model_variant_counterfactual": bool(leg.get("model_variant_counterfactual")),
        "served_model_version": leg.get("served_model_version") or "",
        "quote_id": leg["quote_id"],
        "leg_id": leg["leg_id"],
        "fill_id": fill_id,
        "fill_time_utc": trade["time"].isoformat(),
        "event_slug": leg["event_slug"],
        "market_id": leg["market_id"],
        "target_date": leg["target_date"],
        "range_label": leg["range_label"],
        "bin_kind": leg["bin_kind"],
        "bin_value": leg["bin_value"],
        "bin_value_hi": leg["bin_value_hi"],
        "clob_token_id": leg["clob_token_id"],
        "side": leg["side"],
        "quote_time_utc": leg["quote_time"].isoformat(),
        "quote_expires_at_utc": leg["quote_expires_at"].isoformat(),
        "quote_age_seconds": compact_float(leg.get("quote_age_seconds")),
        "quote_price": compact_float(leg["quote_price"]),
        "quote_size": compact_float(leg["quote_size"]),
        "fill_price": compact_float(fill["fill_price"]),
        "fill_size": compact_float(fill_size),
        "through_trade_price": compact_float(trade["price"]),
        "through_trade_size": compact_float(trade.get("size")),
        "trade_source": trade["source"],
        "conservative_fill_rule": "strict_trade_through_price_and_recorded_size",
        "queue_status": queue.get("status"),
        "queue_fill_size": compact_float(queue.get("estimated_fill_size")),
        "queue_initial_ahead": compact_float(queue.get("initial_queue_ahead")),
        "queue_depleted_ahead": compact_float(queue.get("depleted_ahead")),
        "queue_reason": queue.get("reason"),
        "market_mid": compact_float(leg.get("market_mid")),
        "fair_probability": compact_float(leg.get("fair_probability")),
        "edge": compact_float(leg.get("edge")),
        "capture_hour_utc": leg.get("capture_hour_utc"),
        "capture_hour_local": leg.get("capture_hour_local"),
        "capture_timezone": leg.get("capture_timezone") or "",
        "hourly_trust_band": leg.get("hourly_trust_band") or "",
        "hourly_trust_multiplier": compact_float(leg.get("hourly_trust_multiplier")),
        "early_hour_guardrail_status": leg.get("early_hour_guardrail_status") or "",
        "early_hour_guardrail_reason": leg.get("early_hour_guardrail_reason") or "",
        "early_hour_guardrail_min_edge": compact_float(leg.get("early_hour_guardrail_min_edge")),
        "early_hour_guardrail_size_multiplier": compact_float(
            leg.get("early_hour_guardrail_size_multiplier")
        ),
        "early_hour_guardrail_quote_widen_buffer": compact_float(
            leg.get("early_hour_guardrail_quote_widen_buffer")
        ),
        "early_hour_guardrail_override_allowed": bool(
            leg.get("early_hour_guardrail_override_allowed")
        ),
        "early_hour_guardrail_market_weight": compact_float(
            leg.get("early_hour_guardrail_market_weight")
        ),
        "market_aware_overlay_probability": compact_float(
            leg.get("market_aware_overlay_probability")
        ),
        "market_aware_overlay_edge": compact_float(leg.get("market_aware_overlay_edge")),
        "market_aware_overlay_used_for_risk_only": bool(
            leg.get("market_aware_overlay_used_for_risk_only")
        ),
        "spread_capture_usdc": compact_float(financials["spread_capture"]),
        "adverse_selection_30m_usdc": compact_float(financials["adverse_30m"]),
        "settlement_pnl_usdc": compact_float(financials["settlement_pnl"]),
        "maker_fee_equivalent_usdc": compact_float(financials["maker_fee_equiv"]),
        "maker_rebate_estimate_usdc": compact_float(financials["maker_rebate"]),
        "liquidity_reward_estimate_usdc": compact_float(financials["reward"]),
        "flattening_fee_estimate_usdc": compact_float(financials["flatten_fee"]),
        "net_pnl_after_fees_incentives_usdc": compact_float(financials["net"]),
        "settlement_markout_per_share": compact_float(financials["settlement_markout"]),
        "settlement_outcome": compact_float(financials["settlement_outcome"]),
        "regime": leg["regime"],
        "source_fresh": leg["source_fresh"],
        "source_freshness_state": leg.get("source_freshness_state") or "",
        "event_gate_status": leg.get("event_gate_status") or "",
        "event_gate_action": leg.get("event_gate_action") or "",
        "event_gate_reason_code": leg.get("event_gate_reason_code") or "",
        "event_gate_event_class": leg.get("event_gate_event_class") or "",
        "event_gate_event_id": leg.get("event_gate_event_id") or "",
        "event_gate_exception_id": leg.get("event_gate_exception_id") or "",
        "book_imbalance_bucket": leg["book_imbalance_bucket"],
        "band_distance_bucket": leg["band_distance_bucket"],
        "casebook_taxonomy": case.get("taxonomy") or "",
        "casebook_case_id": case.get("case_id") or "",
    }
    for horizon, _seconds in MARKOUT_HORIZONS:
        row[f"markout_{horizon}_per_share"] = compact_float(
            financials["markouts"].get(horizon)
        )
    return row


def _simulate_spilled_conservative_fills(
    legs,
    snapshots_root,
    casebook_index,
    config,
    ledger_root=None,
):
    """Preserve corpus-wide fill ordering while keeping legs and outputs on disk."""

    tape_index = legs.new_tape_index("tapes")
    diagnostics = defaultdict(
        lambda: {
            "trade_rows": 0,
            "missing_size_trade_rows": 0,
            "book_rows": 0,
            "mark_rows": 0,
            "settlement_available": False,
        }
    )
    for event_slug in legs.event_slugs():
        folder = Path(snapshots_root) / event_slug
        trades, trade_diag = load_trade_rows(folder)
        books = load_book_rows(folder)
        marks = load_mark_rows(folder)
        settlement = settlement_for_folder(
            folder,
            event_slug,
            ledger_root=ledger_root,
        )
        tape_index.add_event(event_slug, trades, books, marks, settlement)
        diagnostics[event_slug].update(trade_diag)
        diagnostics[event_slug]["book_rows"] = len(books)
        diagnostics[event_slug]["mark_rows"] = len(marks)
        diagnostics[event_slug]["settlement_available"] = bool(settlement)
        del trades, books, marks, settlement
        gc.collect()

    queue_rows = legs.new_queue_store("queues")
    for source_order, leg in legs.iter_with_sequence():
        books, trades = tape_index.queue_rows(leg)
        token_id = leg["clob_token_id"]
        queue_rows.upsert(
            queue_simulate_leg(
                leg,
                {token_id: books},
                {token_id: trades},
            ),
            source_order=source_order,
            context=leg,
        )

    fill_rows = legs.new_row_store("fills", iteration_order="sorted")
    for leg in legs.iter_sorted():
        trade_rows = tape_index.trade_rows(leg)
        remaining_leg = float(leg["quote_size"])
        for trade in trade_rows:
            if remaining_leg <= 1e-9:
                break
            if not strict_trade_through(leg["side"], trade["price"], leg["quote_price"]):
                continue
            if trade.get("size") is None:
                continue
            remaining_trade = tape_index.remaining(trade["trade_id"])
            if remaining_trade <= 1e-9:
                continue
            fill_size = min(remaining_leg, remaining_trade)
            if fill_size <= 1e-9:
                continue
            tape_index.set_remaining(trade["trade_id"], remaining_trade - fill_size)
            remaining_leg -= fill_size
            cumulative_fill_size = tape_index.add_leg_fill(leg["leg_id"], fill_size)
            mark_targets = [
                trade["time"] + timedelta(seconds=seconds)
                for _label, seconds in MARKOUT_HORIZONS
            ]
            marks = tape_index.mark_rows(
                leg["event_slug"],
                leg["clob_token_id"],
                mark_targets,
            )
            bundle = {
                "marks_by_token": {leg["clob_token_id"]: marks},
                "settlement": tape_index.settlement(leg["event_slug"]),
            }
            row = conservative_fill_row(
                leg,
                trade,
                fill_size,
                cumulative_fill_size,
                bundle,
                casebook_index,
                queue_rows.get(leg["leg_id"]),
                config,
            )
            fill_rows.append(
                row,
                sort_time=leg["quote_time"],
                sort_id=leg["leg_id"],
            )
    legs.connection.commit()
    return fill_rows, queue_rows, dict(diagnostics), {}


def simulate_conservative_fills(legs, snapshots_root, casebook_index, config, ledger_root=None):
    if getattr(legs, "is_spilled_rows", False):
        return _simulate_spilled_conservative_fills(
            legs,
            snapshots_root,
            casebook_index,
            config,
            ledger_root=ledger_root,
        )
    folders = {}
    diagnostics = defaultdict(lambda: {
        "trade_rows": 0,
        "missing_size_trade_rows": 0,
        "book_rows": 0,
        "mark_rows": 0,
        "settlement_available": False,
    })
    for leg in legs:
        event_slug = leg["event_slug"]
        if event_slug not in folders:
            folder = Path(snapshots_root) / event_slug
            trades, trade_diag = load_trade_rows(folder)
            books = load_book_rows(folder)
            marks = load_mark_rows(folder)
            settlement = settlement_for_folder(folder, event_slug, ledger_root=ledger_root)
            folders[event_slug] = {
                "folder": folder,
                "trades": trades,
                "trades_by_token": group_by_token(trades),
                "books": books,
                "books_by_token": group_by_token(books),
                "marks": marks,
                "marks_by_token": group_by_token(marks),
                "settlement": settlement,
            }
            diagnostics[event_slug].update(trade_diag)
            diagnostics[event_slug]["book_rows"] = len(books)
            diagnostics[event_slug]["mark_rows"] = len(marks)
            diagnostics[event_slug]["settlement_available"] = bool(settlement)

    queue_by_leg = {}
    for leg in legs:
        bundle = folders.get(leg["event_slug"]) or {}
        queue_by_leg[leg["leg_id"]] = queue_simulate_leg(
            leg,
            bundle.get("books_by_token") or {},
            bundle.get("trades_by_token") or {},
        )

    trade_remaining = {}
    for bundle in folders.values():
        for trade in bundle["trades"]:
            if trade.get("size") is not None:
                trade_remaining[trade["trade_id"]] = float(trade["size"])

    fill_rows = []
    leg_fill_sizes = Counter()
    legs_sorted = sorted(legs, key=lambda leg: (leg["quote_time"], leg["leg_id"]))
    for leg in legs_sorted:
        bundle = folders.get(leg["event_slug"]) or {}
        trade_rows = rows_between(
            (bundle.get("trades_by_token") or {}).get(leg["clob_token_id"]) or [],
            leg["quote_time"],
            leg["quote_expires_at"],
        )
        remaining_leg = float(leg["quote_size"])
        for trade in trade_rows:
            if remaining_leg <= 1e-9:
                break
            if not strict_trade_through(leg["side"], trade["price"], leg["quote_price"]):
                continue
            if trade.get("size") is None:
                continue
            remaining_trade = trade_remaining.get(trade["trade_id"], 0.0)
            if remaining_trade <= 1e-9:
                continue
            fill_size = min(remaining_leg, remaining_trade)
            if fill_size <= 1e-9:
                continue
            trade_remaining[trade["trade_id"]] = remaining_trade - fill_size
            remaining_leg -= fill_size
            leg_fill_sizes[leg["leg_id"]] += fill_size
            queue = queue_by_leg.get(leg["leg_id"], {})
            fill_rows.append(
                conservative_fill_row(
                    leg,
                    trade,
                    fill_size,
                    leg_fill_sizes[leg["leg_id"]],
                    bundle,
                    casebook_index,
                    queue,
                    config,
                )
            )
    queue_rows = list(queue_by_leg.values())
    return fill_rows, queue_rows, dict(diagnostics), leg_fill_sizes


def mean(values):
    values = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not values:
        return None
    return sum(values) / len(values)


def ci_bounds(values, z=1.96):
    values = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not values:
        return None, None
    avg = sum(values) / len(values)
    if len(values) < 2:
        return avg, avg
    stderr = statistics.stdev(values) / math.sqrt(len(values))
    return avg - z * stderr, avg + z * stderr


def sum_field(rows, key):
    return sum(finite_float(row.get(key), 0.0) or 0.0 for row in rows)


def summarize_pnl(fill_rows):
    return {
        "spread_capture_usdc": compact_float(sum_field(fill_rows, "spread_capture_usdc")),
        "adverse_selection_30m_usdc": compact_float(sum_field(fill_rows, "adverse_selection_30m_usdc")),
        "settlement_pnl_usdc": compact_float(sum_field(fill_rows, "settlement_pnl_usdc")),
        "maker_fee_equivalent_usdc": compact_float(sum_field(fill_rows, "maker_fee_equivalent_usdc")),
        "maker_rebate_estimate_usdc": compact_float(sum_field(fill_rows, "maker_rebate_estimate_usdc")),
        "liquidity_reward_estimate_usdc": compact_float(sum_field(fill_rows, "liquidity_reward_estimate_usdc")),
        "flattening_fee_estimate_usdc": compact_float(sum_field(fill_rows, "flattening_fee_estimate_usdc")),
        "net_pnl_after_fees_incentives_usdc": compact_float(sum_field(fill_rows, "net_pnl_after_fees_incentives_usdc")),
    }


__all__ = [name for name in globals() if not name.startswith("__")]
