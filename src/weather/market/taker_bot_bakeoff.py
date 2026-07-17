"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from datetime import datetime, timezone
from pathlib import Path

from weather.market import exchange_economics
from weather.market.taker_bot_bakeoff_scoring import (
    COMPOSITE_PROFITABILITY_SCHEMA_VERSION,
    CURRENT_REPLAY_PROFITABILITY_SCHEMA_VERSION,
    TAKER_MODEL_VARIANT_SPECS,
    _current_replay_profitability_verification,
    _replay_profitability_check,
    _variant_probability,
    expand_input_rows_for_model_variants,
    replay_input_key,
    replay_input_key_payload,
    replay_input_rows_from_orders,
    replay_input_ticks,
    replay_tick_sort_key,
    taker_model_variant_ids,
    taker_model_variant_specs,
)
from weather.market.taker_bot_aggregation import (
    DeferredTakerPayload,
    TakerRunAggregation,
)
from weather.market.taker_bot_artifact_projection import (
    DEFAULT_PROJECTION_MAX_BYTES,
    load_bakeoff_ledger_projection,
    read_pretty_json_top_level_schema_version,
    write_bakeoff_ledger_projection,
)
from weather.market.taker_profitability_artifact_verification import verify_taker_profitability_artifacts
from weather.market.taker_bot_reporting import *  # noqa: F403
from weather.io import (
    iter_csv_rows,
    read_pretty_json_top_level_values,
    write_text_atomic,
)
from weather.operations.bot_run_liveness import DEFAULT_MIN_FREE_BYTES, disk_capacity_preflight

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

CHAMPION_CHALLENGER_LEDGER_SCHEMA_VERSION = "taker_champion_challenger_ledger_v0.1"
DEFAULT_CHAMPION_MIN_COMPLETE_LABEL_DAYS = 3
DEFAULT_CHAMPION_MIN_SETTLED_ORDERS = 5
TAKER_COMPLETE_QUALITY_GRADES = {"complete", "manual_override"}
TAKER_DAILY_SETTLEMENT_SOURCES = {"daily_summary", "override"}
TAKER_BLOCKING_RECONCILIATION_STATUSES = {"mismatch", "not_closed", "unavailable", "fetch_error"}


def _read_bakeoff_source_summary(path):
    path = Path(path)
    try:
        if path.stat().st_size <= DEFAULT_PROJECTION_MAX_BYTES:
            return read_json(path, {}) or {}
    except OSError:
        return {}
    return read_pretty_json_top_level_values(
        path,
        ("run_id", "target_date", "summary"),
    )

def counterfactual_strategy_arg(config=None, strategies=None):
    if strategies not in (None, ""):
        return strategies
    configured = (config or {}).get("counterfactual_strategies")
    return configured or DEFAULT_BAKEOFF_STRATEGIES


def counterfactual_match_key(row):
    kind, value, value_hi = band_key(row)
    return (
        row.get("target_date") or "",
        row.get("market_id") or "",
        row.get("event_slug") or "",
        row.get("snapshot_id") or "",
        row.get("captured_at_utc") or "",
        row.get("range_label") or "",
        kind or "",
        str(value if value is not None else ""),
        str(value_hi if value_hi is not None else ""),
        row.get("clob_token_id") or row.get("clob_yes_token_id") or "",
        order_side(row),
    )


def real_action_index(rows):
    by_key = {}
    for row in rows or []:
        key = counterfactual_match_key(row)
        existing = by_key.get(key)
        if existing is None or str(row.get("order_status") or "").upper() == "FILLED":
            by_key[key] = row
    return by_key


def annotate_counterfactual_rows(rows, *, real_rows=None, strategy_set=None):
    real_by_key = real_action_index(real_rows or [])
    strategy_set = strategy_set or ""
    out = []
    for row in rows or []:
        item = dict(row)
        real = real_by_key.get(counterfactual_match_key(item)) or {}
        item.update({
            "counterfactual_schema_version": COUNTERFACTUAL_TAPE_SCHEMA_VERSION,
            "counterfactual_id": stable_hash({
                "intent_key": item.get("intent_key"),
                "strategy_id": strategy_id_for_row(item),
                "side": order_side(item),
                "run_id": item.get("run_id"),
            }, length=24),
            "counterfactual_source": "live_shared_snapshot_inputs",
            "counterfactual_strategy_set": strategy_set,
            "counterfactual_action": item.get("action") or "NO_TRADE",
            "counterfactual_order_status": item.get("order_status") or "SKIPPED",
            "counterfactual_reason_code": item.get("reason_code") or "",
            "counterfactual_reason_detail": item.get("reason_detail") or "",
            "counterfactual_requested_notional_usdc": item.get("requested_notional_usdc"),
            "counterfactual_fill_size": item.get("fill_size"),
            "counterfactual_total_spent_usdc": item.get("total_spent_usdc"),
            "counterfactual_pnl_source": item.get("pnl_source") or "",
            "real_action": real.get("action") or "NOT_SELECTED",
            "real_order_status": real.get("order_status") or "NOT_SELECTED",
            "real_reason_code": real.get("reason_code") or "",
            "real_strategy_id": real.get("strategy_id") or "",
            "real_order_id": real.get("order_id") or "",
            "real_fill_size": real.get("fill_size"),
            "real_total_spent_usdc": real.get("total_spent_usdc"),
            "real_pnl_source": real.get("pnl_source") or "",
        })
        out.append(item)
    return out


def build_counterfactual_taker_rows(
    input_rows,
    existing_counterfactual_rows,
    real_rows,
    *,
    budget_usdc,
    run_id,
    target_date,
    now,
    config,
    strategies=None,
    experiment_id=None,
    strategy_registry=None,
    intent_exists=None,
):
    strategy_arg = counterfactual_strategy_arg(config, strategies=strategies)
    specs = selected_strategy_specs(strategy_arg, base_config=config, registry=strategy_registry)
    variant_input_rows, variant_manifest = expand_input_rows_for_model_variants(input_rows, config=config)
    rows = []
    ledger = []
    for strategy in specs:
        prior_rows = [
            row for row in existing_counterfactual_rows or []
            if strategy_id_for_row(row) == strategy["strategy_id"]
        ]
        strategy_rows, strategy_ledger = apply_taker_budget(
            variant_input_rows,
            prior_rows,
            strategy.get("budget_usdc") or budget_usdc,
            run_id,
            target_date,
            now,
            strategy["config"],
            strategy=strategy,
            experiment_id=experiment_id,
            intent_exists=intent_exists,
        )
        rows.extend(strategy_rows)
        ledger.extend(strategy_ledger)
    return {
        "strategy_arg": strategy_arg,
        "strategy_specs": specs,
        "model_variant_manifest": variant_manifest,
        "rows": annotate_counterfactual_rows(
            rows,
            real_rows=real_rows,
            strategy_set=",".join(item["strategy_id"] for item in specs),
        ),
        "ledger": ledger,
    }


def counterfactual_learning_summary(rows, pnl_payload=None):
    row_count = 0
    would_buy_count = 0
    settled_would_buy_count = 0
    real_filled_match_count = 0
    strategy_ids = set()
    reason_counts = Counter()
    for row in rows or []:
        row_count += 1
        strategy_ids.add(strategy_id_for_row(row))
        reason_counts[row.get("reason_code") or "unknown"] += 1
        if str(row.get("real_order_status") or "").upper() == "FILLED":
            real_filled_match_count += 1
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        would_buy_count += 1
        if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES:
            settled_would_buy_count += 1
    by_strategy = (pnl_payload or {}).get("by_strategy") or []
    best = max(by_strategy, key=lambda row: maybe_float(row.get("net_pnl_usdc")) or 0.0, default={})
    return {
        "row_count": row_count,
        "would_buy_count": would_buy_count,
        "settled_would_buy_count": settled_would_buy_count,
        "real_filled_match_count": real_filled_match_count,
        "zero_real_fill_learning": bool(
            real_filled_match_count == 0 and settled_would_buy_count > 0
        ),
        "strategy_count": len(strategy_ids),
        "best_counterfactual_strategy_id": best.get("strategy_id"),
        "best_counterfactual_net_pnl_usdc": best.get("net_pnl_usdc"),
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def counterfactual_strategy_lift_rows(pnl_payload, active_strategy_id=None):
    strategies = (pnl_payload or {}).get("by_strategy") or []
    by_id = {row.get("strategy_id"): row for row in strategies if row.get("strategy_id")}
    active = by_id.get(active_strategy_id) or (strategies[0] if strategies else {})
    active_net = maybe_float(active.get("net_pnl_usdc")) or 0.0
    rows = []
    for row in strategies:
        net = maybe_float(row.get("net_pnl_usdc")) or 0.0
        rows.append({
            "strategy_id": row.get("strategy_id"),
            "strategy_family": row.get("strategy_family"),
            "active_policy_strategy_id": (active or {}).get("strategy_id") or active_strategy_id,
            "would_buy_count": row.get("filled_order_count"),
            "settled_would_buy_count": row.get("settled_order_count"),
            "net_pnl_usdc": compact_float(net),
            "delta_vs_active_policy_net_pnl_usdc": compact_float(net - active_net),
            "delta_vs_no_trade_net_pnl_usdc": compact_float(net),
            "market_top_net_pnl_usdc": row.get("market_benchmark_market_top_net_pnl_usdc"),
            "delta_vs_market_top_net_pnl_usdc": compact_float(
                net - (maybe_float(row.get("market_benchmark_market_top_net_pnl_usdc")) or 0.0)
            ),
            "market_benchmark_status": row.get("market_benchmark_status"),
            "quality_candidate_countable": row.get("quality_candidate_countable"),
            "settlement_promotion_gate_status": row.get("settlement_promotion_gate_status"),
            "settlement_promotion_failed_gates": row.get("settlement_promotion_failed_gates") or [],
        })
    return rows


def _counterfactual_slice_row(dimension, value, rows):
    rows = list(rows or [])
    would_buy = [row for row in rows if str(row.get("order_status") or "").upper() == "FILLED"]
    settled = [row for row in would_buy if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES]
    return {
        "dimension": dimension,
        "value": value if value not in (None, "") else "unknown",
        "row_count": len(rows),
        "would_buy_count": len(would_buy),
        "settled_would_buy_count": len(settled),
        "win_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 1.0),
        "loss_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 0.0),
        "spent_usdc": sum_field(would_buy, "total_spent_usdc"),
        "net_pnl_usdc": sum_field([row for row in would_buy if row.get("net_pnl_usdc") not in (None, "")], "net_pnl_usdc"),
    }


def _capture_hour_bucket(row):
    hour = maybe_float(row.get("capture_hour_local"))
    if hour is not None:
        return f"{int(hour):02d}"
    parsed = parse_time(row.get("captured_at_utc") or row.get("generated_at_utc"))
    return f"{parsed.hour:02d}Z" if parsed else "unknown"


def _current_high_bucket(row):
    gate = row.get("current_high_trust_gate_status") or "unknown"
    distance = maybe_float(row.get("current_high_band_distance"))
    if distance is None:
        return gate
    if distance <= 0:
        bucket = "at_current_high"
    elif distance <= 1:
        bucket = "adjacent_current_high"
    else:
        bucket = "away_from_current_high"
    return f"{gate}:{bucket}"


def counterfactual_slice_summaries(rows):
    dimensions = {
        "by_market": lambda row: row.get("market_id") or "unknown",
        "by_hour": _capture_hour_bucket,
        "by_tail": lambda row: row.get("tail_risk_bucket") or ("low_price_tail" if bool_value(row.get("low_price_tail"), False) else "regular"),
        "by_current_high": _current_high_bucket,
        "by_source_state": lambda row: row.get("source_freshness_state") or "unknown",
    }
    groups = {name: defaultdict(lambda: {
        "row_count": 0,
        "would_buy_count": 0,
        "settled_would_buy_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "spent_usdc": 0.0,
        "net_pnl_usdc": 0.0,
    }) for name in dimensions}
    for row in rows or []:
        filled = str(row.get("order_status") or "").upper() == "FILLED"
        settled = filled and row.get("pnl_source") in SETTLEMENT_PNL_SOURCES
        outcome = maybe_float(row.get("settlement_outcome")) if settled else None
        spent = maybe_float(row.get("total_spent_usdc")) or 0.0
        net = maybe_float(row.get("net_pnl_usdc"))
        for name, key_func in dimensions.items():
            bucket = groups[name][key_func(row)]
            bucket["row_count"] += 1
            if not filled:
                continue
            bucket["would_buy_count"] += 1
            bucket["spent_usdc"] += spent
            if net is not None:
                bucket["net_pnl_usdc"] += net
            if settled:
                bucket["settled_would_buy_count"] += 1
                bucket["win_count"] += int(outcome == 1.0)
                bucket["loss_count"] += int(outcome == 0.0)
    return {
        name: [
            {
                "dimension": name,
                "value": key if key not in (None, "") else "unknown",
                **{field: value for field, value in bucket.items() if field not in {"spent_usdc", "net_pnl_usdc"}},
                "spent_usdc": round(bucket["spent_usdc"], 6),
                "net_pnl_usdc": round(bucket["net_pnl_usdc"], 6),
            }
            for key, bucket in sorted(name_groups.items(), key=lambda item: str(item[0]))
        ]
        for name, name_groups in groups.items()
    }


def _no_side_campaign_status(no_rows, real_book_rows, real_eligible_rows, would_buy, real_eligible_would_buy, settled_real_eligible):
    if not no_rows:
        return "BLOCK_NO_SIDE_ROWS"
    if not real_book_rows:
        return "BLOCK_NO_REAL_NO_BOOK_ROWS"
    if not real_eligible_rows:
        return "BLOCK_REAL_NO_BOOK_DEPTH"
    if not would_buy:
        return "WATCH_NO_SIDE_NO_WOULD_BUY"
    if not real_eligible_would_buy:
        return "BLOCK_SYNTHETIC_OR_STALE_NO_BOOK"
    if not settled_real_eligible:
        return "COLLECTING_UNSETTLED_NO_SIDE"
    return "COLLECTING_SETTLED_NO_SIDE"


def _no_side_campaign_core(rows):
    rows = list(rows or [])
    no_rows = [row for row in rows if order_side(row) == NO_SIDE]
    would_buy = [row for row in no_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    settled = [row for row in would_buy if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES]
    real_book_rows = [row for row in no_rows if row.get("no_book_source") == "no_token_book"]
    synthetic_rows = [row for row in no_rows if str(row.get("no_book_source") or "").startswith("synthetic")]
    stale_rows = [
        row for row in real_book_rows
        if not bool_value(row.get("no_book_fresh"), False)
    ]
    real_eligible_rows = [
        row for row in real_book_rows
        if bool_value(row.get("real_no_book_depth_eligible"), False)
    ]
    missing_depth_rows = [
        row for row in real_book_rows
        if bool_value(row.get("no_book_fresh"), False)
        and not bool_value(row.get("real_no_book_depth_eligible"), False)
    ]
    real_eligible_would_buy = [
        row for row in would_buy
        if row.get("no_book_source") == "no_token_book"
        and bool_value(row.get("real_no_book_depth_eligible"), False)
    ]
    synthetic_would_buy = [
        row for row in would_buy
        if str(row.get("no_book_source") or "").startswith("synthetic")
    ]
    stale_would_buy = [
        row for row in would_buy
        if row.get("no_book_source") == "no_token_book"
        and not bool_value(row.get("no_book_fresh"), False)
    ]
    settled_real_eligible = [
        row for row in real_eligible_would_buy
        if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES
    ]
    return {
        "no_rows": no_rows,
        "would_buy": would_buy,
        "settled": settled,
        "real_book_rows": real_book_rows,
        "synthetic_rows": synthetic_rows,
        "stale_rows": stale_rows,
        "missing_depth_rows": missing_depth_rows,
        "real_eligible_rows": real_eligible_rows,
        "real_eligible_would_buy": real_eligible_would_buy,
        "synthetic_would_buy": synthetic_would_buy,
        "stale_would_buy": stale_would_buy,
        "settled_real_eligible": settled_real_eligible,
    }


def _no_side_campaign_slice_row(dimension, value, rows):
    core = _no_side_campaign_core(rows)
    would_buy = core["would_buy"]
    settled = core["settled"]
    real_eligible_would_buy = core["real_eligible_would_buy"]
    settled_real_eligible = core["settled_real_eligible"]
    return {
        "dimension": dimension,
        "value": value if value not in (None, "") else "unknown",
        "no_side_row_count": len(core["no_rows"]),
        "real_no_book_row_count": len(core["real_book_rows"]),
        "real_no_book_depth_eligible_row_count": len(core["real_eligible_rows"]),
        "synthetic_no_book_row_count": len(core["synthetic_rows"]),
        "stale_no_book_row_count": len(core["stale_rows"]),
        "no_side_would_buy_count": len(would_buy),
        "countable_no_side_would_buy_count": len(real_eligible_would_buy),
        "settled_no_side_would_buy_count": len(settled),
        "settled_countable_no_side_would_buy_count": len(settled_real_eligible),
        "win_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 1.0),
        "loss_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 0.0),
        "spent_usdc": sum_field(would_buy, "total_spent_usdc"),
        "net_pnl_usdc": sum_field([row for row in would_buy if row.get("net_pnl_usdc") not in (None, "")], "net_pnl_usdc"),
        "countable_net_pnl_usdc": sum_field([
            row for row in real_eligible_would_buy
            if row.get("net_pnl_usdc") not in (None, "")
        ], "net_pnl_usdc"),
        "delta_vs_no_trade_net_pnl_usdc": sum_field([
            row for row in real_eligible_would_buy
            if row.get("net_pnl_usdc") not in (None, "")
        ], "net_pnl_usdc"),
    }


def _new_no_side_stats():
    return {
        "no_side_row_count": 0,
        "real_no_book_row_count": 0,
        "real_no_book_depth_eligible_row_count": 0,
        "synthetic_no_book_row_count": 0,
        "stale_no_book_row_count": 0,
        "missing_depth_no_book_row_count": 0,
        "no_side_would_buy_count": 0,
        "countable_no_side_would_buy_count": 0,
        "synthetic_no_book_would_buy_count": 0,
        "stale_no_book_would_buy_count": 0,
        "settled_no_side_would_buy_count": 0,
        "settled_countable_no_side_would_buy_count": 0,
        "no_side_win_count": 0,
        "no_side_loss_count": 0,
        "no_side_spent_usdc": 0.0,
        "no_side_net_pnl_usdc": 0.0,
        "countable_no_side_net_pnl_usdc": 0.0,
        "reason_counts": Counter(),
        "strategy_family": "unknown",
    }


def _update_no_side_stats(stats, row):
    stats["no_side_row_count"] += 1
    if stats["strategy_family"] == "unknown":
        stats["strategy_family"] = row.get("strategy_family") or "unknown"
    stats["reason_counts"][row.get("reason_code") or "unknown"] += 1
    source = str(row.get("no_book_source") or "")
    real_book = source == "no_token_book"
    synthetic = source.startswith("synthetic")
    fresh = bool_value(row.get("no_book_fresh"), False)
    real_eligible = real_book and bool_value(
        row.get("real_no_book_depth_eligible"),
        False,
    )
    if real_book:
        stats["real_no_book_row_count"] += 1
        stats["stale_no_book_row_count"] += int(not fresh)
        stats["missing_depth_no_book_row_count"] += int(fresh and not real_eligible)
    if real_eligible:
        stats["real_no_book_depth_eligible_row_count"] += 1
    if synthetic:
        stats["synthetic_no_book_row_count"] += 1
    if str(row.get("order_status") or "").upper() != "FILLED":
        return
    stats["no_side_would_buy_count"] += 1
    stats["no_side_spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
    net = maybe_float(row.get("net_pnl_usdc"))
    if net is not None:
        stats["no_side_net_pnl_usdc"] += net
    if real_eligible:
        stats["countable_no_side_would_buy_count"] += 1
        if net is not None:
            stats["countable_no_side_net_pnl_usdc"] += net
    if synthetic:
        stats["synthetic_no_book_would_buy_count"] += 1
    if real_book and not fresh:
        stats["stale_no_book_would_buy_count"] += 1
    settled = row.get("pnl_source") in SETTLEMENT_PNL_SOURCES
    if settled:
        stats["settled_no_side_would_buy_count"] += 1
        outcome = maybe_float(row.get("settlement_outcome"))
        stats["no_side_win_count"] += int(outcome == 1.0)
        stats["no_side_loss_count"] += int(outcome == 0.0)
        if real_eligible:
            stats["settled_countable_no_side_would_buy_count"] += 1


def _no_side_slice_from_stats(dimension, value, stats):
    return {
        "dimension": dimension,
        "value": value if value not in (None, "") else "unknown",
        "no_side_row_count": stats["no_side_row_count"],
        "real_no_book_row_count": stats["real_no_book_row_count"],
        "real_no_book_depth_eligible_row_count": stats[
            "real_no_book_depth_eligible_row_count"
        ],
        "synthetic_no_book_row_count": stats["synthetic_no_book_row_count"],
        "stale_no_book_row_count": stats["stale_no_book_row_count"],
        "no_side_would_buy_count": stats["no_side_would_buy_count"],
        "countable_no_side_would_buy_count": stats[
            "countable_no_side_would_buy_count"
        ],
        "settled_no_side_would_buy_count": stats[
            "settled_no_side_would_buy_count"
        ],
        "settled_countable_no_side_would_buy_count": stats[
            "settled_countable_no_side_would_buy_count"
        ],
        "win_count": stats["no_side_win_count"],
        "loss_count": stats["no_side_loss_count"],
        "spent_usdc": round(stats["no_side_spent_usdc"], 6),
        "net_pnl_usdc": round(stats["no_side_net_pnl_usdc"], 6),
        "countable_net_pnl_usdc": round(
            stats["countable_no_side_net_pnl_usdc"],
            6,
        ),
        "delta_vs_no_trade_net_pnl_usdc": round(
            stats["countable_no_side_net_pnl_usdc"],
            6,
        ),
    }


def no_side_campaign_summary(rows, pnl_payload=None, *, include_slices=True):
    overall = _new_no_side_stats()
    strategy_groups = defaultdict(_new_no_side_stats)
    market_groups = defaultdict(_new_no_side_stats)
    hour_groups = defaultdict(_new_no_side_stats)
    for row in rows or []:
        if order_side(row) != NO_SIDE:
            continue
        _update_no_side_stats(overall, row)
        _update_no_side_stats(strategy_groups[strategy_id_for_row(row)], row)
        if include_slices:
            _update_no_side_stats(market_groups[row.get("market_id") or "unknown"], row)
            _update_no_side_stats(hour_groups[_capture_hour_bucket(row)], row)
    by_strategy_payload = {
        row.get("strategy_id"): row
        for row in (pnl_payload or {}).get("by_strategy") or []
        if row.get("strategy_id")
    }
    present = lambda count: (None,) if count else ()
    out = {
        "status": _no_side_campaign_status(
            present(overall["no_side_row_count"]),
            present(overall["real_no_book_row_count"]),
            present(overall["real_no_book_depth_eligible_row_count"]),
            present(overall["no_side_would_buy_count"]),
            present(overall["countable_no_side_would_buy_count"]),
            present(overall["settled_countable_no_side_would_buy_count"]),
        ),
        "candidate_basis": "NO-side rows generated by two_sided/fade arm",
        "countable_evidence_basis": "real no-token book depth only",
        "synthetic_only_countable": False,
        **{
            key: value
            for key, value in overall.items()
            if key not in {
                "reason_counts",
                "strategy_family",
                "no_side_spent_usdc",
                "no_side_net_pnl_usdc",
                "countable_no_side_net_pnl_usdc",
            }
        },
        "no_side_spent_usdc": round(overall["no_side_spent_usdc"], 6),
        "no_side_net_pnl_usdc": round(overall["no_side_net_pnl_usdc"], 6),
        "countable_no_side_net_pnl_usdc": round(
            overall["countable_no_side_net_pnl_usdc"],
            6,
        ),
        "delta_vs_no_trade_net_pnl_usdc": round(
            overall["countable_no_side_net_pnl_usdc"],
            6,
        ),
        "reason_counts": dict(sorted(overall["reason_counts"].items())),
    }
    out["by_strategy"] = []
    for strategy_id, stats in sorted(strategy_groups.items()):
        strategy_row = _no_side_slice_from_stats("by_strategy", strategy_id, stats)
        pnl_row = by_strategy_payload.get(strategy_id) or {}
        market_top = maybe_float(pnl_row.get("market_benchmark_market_top_net_pnl_usdc"))
        strategy_net = maybe_float(pnl_row.get("net_pnl_usdc"))
        strategy_row.update({
            "strategy_id": strategy_id,
            "strategy_family": stats["strategy_family"],
            "strategy_market_top_net_pnl_usdc": compact_float(market_top),
            "strategy_delta_vs_market_top_net_pnl_usdc": compact_float(
                strategy_net - market_top
                if strategy_net is not None and market_top is not None else None
            ),
            "settlement_promotion_gate_status": pnl_row.get("settlement_promotion_gate_status") or "",
            "settlement_promotion_failed_gates": pnl_row.get("settlement_promotion_failed_gates") or [],
        })
        out["by_strategy"].append(strategy_row)
    if include_slices:
        for name, groups in (("by_market", market_groups), ("by_hour", hour_groups)):
            out[name] = [
                _no_side_slice_from_stats(name, key, stats)
                for key, stats in sorted(groups.items(), key=lambda item: str(item[0]))
            ]
    return out


def model_variant_id_for_row(row):
    return str(row.get("model_variant_id") or row.get("variant_id") or row.get("model_version") or "served_current")


def model_variant_strategy_bakeoff(rows, *, alpha=0.05, min_settled_would_buy=5):
    groups = defaultdict(lambda: {
        "model_variant_family": "unknown",
        "model_variant_role": "shadow",
        "strategy_family": "unknown",
        "row_count": 0,
        "would_buy_count": 0,
        "settled_would_buy_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "spent_usdc": 0.0,
        "net_pnl_usdc": 0.0,
        "after_fee_count": 0,
        "after_slippage_count": 0,
    })
    for row in rows or []:
        bucket = groups[(model_variant_id_for_row(row), strategy_id_for_row(row))]
        if bucket["row_count"] == 0:
            bucket["model_variant_family"] = row.get("model_variant_family") or "unknown"
            bucket["model_variant_role"] = row.get("model_variant_role") or "shadow"
            bucket["strategy_family"] = row.get("strategy_family") or "unknown"
        bucket["row_count"] += 1
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        bucket["would_buy_count"] += 1
        bucket["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        net = maybe_float(row.get("net_pnl_usdc"))
        if net is not None:
            bucket["net_pnl_usdc"] += net
        bucket["after_fee_count"] += int(
            bool_value(row.get("after_fee_pnl_scored"), False)
            or row.get("pnl_fee_basis") in {"after_fee", "fees_included", "net_after_fee"}
        )
        bucket["after_slippage_count"] += int(
            bool_value(row.get("after_slippage_pnl_scored"), False)
            or row.get("executable_depth_model_version") not in (None, "")
        )
        if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES:
            bucket["settled_would_buy_count"] += 1
            outcome = maybe_float(row.get("settlement_outcome"))
            bucket["win_count"] += int(outcome == 1.0)
            bucket["loss_count"] += int(outcome == 0.0)
    pair_rows = []
    served_by_strategy = {}
    for (variant_id, strategy_id), bucket in sorted(groups.items()):
        net = round(bucket["net_pnl_usdc"], 6)
        spent = round(bucket["spent_usdc"], 6)
        row = {
            "model_variant_id": variant_id,
            "model_variant_family": bucket["model_variant_family"],
            "model_variant_role": bucket["model_variant_role"],
            "strategy_id": strategy_id,
            "strategy_family": bucket["strategy_family"],
            "row_count": bucket["row_count"],
            "would_buy_count": bucket["would_buy_count"],
            "settled_would_buy_count": bucket["settled_would_buy_count"],
            "win_count": bucket["win_count"],
            "loss_count": bucket["loss_count"],
            "spent_usdc": spent,
            "net_pnl_usdc": net,
            "roi": compact_float(net / spent if spent > 0 else None),
            "after_fee_count": bucket["after_fee_count"],
            "after_slippage_count": bucket["after_slippage_count"],
        }
        if variant_id == "served_current":
            served_by_strategy[strategy_id] = row
        pair_rows.append(row)
    comparison_count = sum(1 for row in pair_rows if row.get("model_variant_id") != "served_current")
    adjusted_alpha = compact_float(float(alpha) / comparison_count if comparison_count else float(alpha), digits=8)
    for row in pair_rows:
        baseline = served_by_strategy.get(row.get("strategy_id")) or {}
        row["served_current_net_pnl_usdc"] = baseline.get("net_pnl_usdc")
        row["delta_vs_served_current_net_pnl_usdc"] = compact_float(
            (maybe_float(row.get("net_pnl_usdc")) or 0.0)
            - (maybe_float(baseline.get("net_pnl_usdc")) or 0.0)
        )
        failed = []
        if row.get("model_variant_id") != "served_current":
            if int(row.get("settled_would_buy_count") or 0) < int(min_settled_would_buy):
                failed.append("min_settled_would_buy")
            if (maybe_float(row.get("delta_vs_served_current_net_pnl_usdc")) or 0.0) <= 0:
                failed.append("positive_delta_vs_served_current")
        row["variant_selection_status"] = "PASS" if row.get("model_variant_id") != "served_current" and not failed else (
            "CONTROL" if row.get("model_variant_id") == "served_current" else "BLOCK"
        )
        row["variant_selection_failed_gates"] = failed
        row["multiple_testing_adjusted_alpha"] = adjusted_alpha
    pass_rows = [row for row in pair_rows if row.get("variant_selection_status") == "PASS"]
    return {
        "schema_version": "taker_model_variant_shadow_bakeoff_v0.1",
        "alpha": float(alpha),
        "multiple_testing_method": "bonferroni_pre_registered_basket",
        "comparison_count": comparison_count,
        "adjusted_alpha": adjusted_alpha,
        "min_settled_would_buy": int(min_settled_would_buy),
        "status": "PASS" if pass_rows else "BLOCK",
        "recommended_model_variant_id": (max(
            pass_rows,
            key=lambda row: maybe_float(row.get("delta_vs_served_current_net_pnl_usdc")) or 0.0,
            default={},
        )).get("model_variant_id"),
        "pair_count": len(pair_rows),
        "pairs": pair_rows,
    }


def _cluster_stats(values, alpha=0.05):
    values = [float(value or 0.0) for value in values]
    n = len(values)
    total = sum(values)
    mean = total / n if n else 0.0
    if n <= 1:
        stdev = 0.0
        lower = mean if n else None
        upper = mean if n else None
    else:
        stdev = math.sqrt(sum((value - mean) ** 2 for value in values) / (n - 1))
        z = 2.576 if float(alpha) <= 0.01 else 1.96
        half_width = z * stdev / math.sqrt(n)
        lower = mean - half_width
        upper = mean + half_width
    return {
        "n": n,
        "total": compact_float(total),
        "mean": compact_float(mean),
        "stdev": compact_float(stdev),
        "mean_lower": compact_float(lower),
        "mean_upper": compact_float(upper),
        "total_lower": compact_float(lower * n if lower is not None else None),
        "total_upper": compact_float(upper * n if upper is not None else None),
    }


def clustered_taker_promotion_statistics(
    rows,
    *,
    alpha=0.05,
    min_independent_target_days=3,
    min_independent_markets=2,
):
    groups = defaultdict(lambda: {
        "would_buy_count": 0,
        "settled_would_buy_count": 0,
        "unresolved_would_buy_count": 0,
        "after_fee_count": 0,
        "after_slippage_count": 0,
        "clusters": defaultdict(lambda: {
            "settled_would_buy_count": 0,
            "spent_usdc": 0.0,
            "net_pnl_usdc": 0.0,
        }),
    })
    for row in rows or []:
        bucket = groups[(model_variant_id_for_row(row), strategy_id_for_row(row))]
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        bucket["would_buy_count"] += 1
        bucket["after_fee_count"] += int(
            bool_value(row.get("after_fee_pnl_scored"), False)
            or row.get("pnl_fee_basis") in {"after_fee", "fees_included", "net_after_fee"}
        )
        bucket["after_slippage_count"] += int(
            bool_value(row.get("after_slippage_pnl_scored"), False)
            or row.get("executable_depth_model_version") not in (None, "")
        )
        if row.get("pnl_source") not in SETTLEMENT_PNL_SOURCES:
            bucket["unresolved_would_buy_count"] += 1
            continue
        bucket["settled_would_buy_count"] += 1
        cluster = bucket["clusters"][(
            row.get("target_date") or "",
            row.get("market_id") or "",
        )]
        cluster["settled_would_buy_count"] += 1
        cluster["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        net = maybe_float(row.get("net_pnl_usdc"))
        if net is not None:
            cluster["net_pnl_usdc"] += net
    comparison_count = sum(1 for key in groups if key[0] != "served_current") or max(1, len(groups))
    adjusted_alpha = float(alpha) / comparison_count if comparison_count else float(alpha)
    result_rows = []
    for (variant_id, strategy_id), bucket in sorted(groups.items()):
        cluster_rows = []
        for (target_date, market_id), cluster in sorted(bucket["clusters"].items()):
            spent = round(cluster["spent_usdc"], 6)
            net = round(cluster["net_pnl_usdc"], 6)
            cluster_rows.append({
                "target_date": target_date,
                "market_id": market_id,
                "settled_would_buy_count": cluster["settled_would_buy_count"],
                "spent_usdc": spent,
                "net_pnl_usdc": net,
                "roi": compact_float(net / spent if spent > 0 else None),
            })
        target_days = {row.get("target_date") for row in cluster_rows if row.get("target_date")}
        markets = {row.get("market_id") for row in cluster_rows if row.get("market_id")}
        net_stats = _cluster_stats([row["net_pnl_usdc"] for row in cluster_rows], alpha=adjusted_alpha)
        spent_total = sum(row["spent_usdc"] for row in cluster_rows)
        net_total = sum(row["net_pnl_usdc"] for row in cluster_rows)
        after_fee_count = bucket["after_fee_count"]
        after_slippage_count = bucket["after_slippage_count"]
        failed = []
        if len(target_days) < int(min_independent_target_days):
            failed.append("min_independent_target_days")
        if len(markets) < int(min_independent_markets):
            failed.append("min_independent_markets")
        if bucket["unresolved_would_buy_count"]:
            failed.append("complete_settlement_required")
        if bucket["would_buy_count"] and after_fee_count < bucket["would_buy_count"]:
            failed.append("after_fee_pnl_scored")
        if bucket["would_buy_count"] and after_slippage_count < bucket["would_buy_count"]:
            failed.append("after_slippage_pnl_scored")
        if (maybe_float(net_stats.get("mean_lower")) or 0.0) <= 0:
            failed.append("positive_cluster_mean_pnl_lower_bound")
        result_rows.append({
            "model_variant_id": variant_id,
            "strategy_id": strategy_id,
            "status": "PASS" if not failed else "BLOCK",
            "failed_gates": failed,
            "cluster_key": "target_date,market_id",
            "cluster_count": len(cluster_rows),
            "independent_target_day_count": len(target_days),
            "independent_market_count": len(markets),
            "would_buy_count": bucket["would_buy_count"],
            "settled_would_buy_count": bucket["settled_would_buy_count"],
            "unresolved_would_buy_count": bucket["unresolved_would_buy_count"],
            "spent_usdc": compact_float(spent_total),
            "net_pnl_usdc": compact_float(net_total),
            "roi": compact_float(net_total / spent_total if spent_total > 0 else None),
            "cluster_net_pnl": net_stats,
            "after_fee_pnl_scored": bool(
                bucket["would_buy_count"]
                and after_fee_count == bucket["would_buy_count"]
            ),
            "after_slippage_pnl_scored": bool(
                bucket["would_buy_count"]
                and after_slippage_count == bucket["would_buy_count"]
            ),
            "clusters": cluster_rows,
        })
    pass_rows = [row for row in result_rows if row.get("status") == "PASS"]
    return {
        "schema_version": "taker_clustered_promotion_gate_v0.1",
        "status": "PASS" if pass_rows else "BLOCK",
        "cluster_key": "target_date,market_id",
        "alpha": float(alpha),
        "multiple_testing_method": "bonferroni_pre_registered_strategy_model_pairs",
        "comparison_count": comparison_count,
        "adjusted_alpha": compact_float(adjusted_alpha, digits=8),
        "min_independent_target_days": int(min_independent_target_days),
        "min_independent_markets": int(min_independent_markets),
        "pass_pair_count": len(pass_rows),
        "pair_count": len(result_rows),
        "pairs": result_rows,
    }


def strategy_filled_rows(order_rows, strategy_id):
    return [
        row for row in order_rows or []
        if strategy_id_for_row(row) == strategy_id and str(row.get("order_status") or "").upper() == "FILLED"
    ]


def cumulative_drawdown_usdc(rows):
    ordered = sorted(
        rows or [],
        key=lambda row: (
            row.get("generated_at_utc") or "",
            row.get("captured_at_utc") or "",
            row.get("order_id") or "",
        ),
    )
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for row in ordered:
        pnl = maybe_float(row.get("net_pnl_usdc"))
        if pnl is None:
            continue
        cumulative += pnl
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return round(drawdown, 6)


def source_mark_index(source_rows):
    source_marks = {}
    for row in source_rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        mark = maybe_float(row.get("mark_pnl_usdc"))
        if mark is None and row.get("pnl_source") == "mark_to_market":
            mark = maybe_float(row.get("net_pnl_usdc"))
        if mark is not None:
            source_marks[replay_input_key(row)] = mark
    return source_marks


def source_mark_sign_flip_count(
    source_rows,
    scored_rows,
    strategy_id,
    *,
    source_marks=None,
    filled_rows=None,
):
    source_marks = (
        source_mark_index(source_rows)
        if source_marks is None
        else source_marks
    )
    count = 0
    for row in (
        strategy_filled_rows(scored_rows, strategy_id)
        if filled_rows is None
        else filled_rows
    ):
        mark = source_marks.get(replay_input_key(row))
        settled = maybe_float(first_present(row, "settlement_pnl_usdc", "net_pnl_usdc"))
        if mark is not None and settled is not None and mark * settled < 0:
            count += 1
    return count


def strategy_concentration_summary(rows, strategy_id, *, filled_rows=None):
    filled = (
        strategy_filled_rows(rows, strategy_id)
        if filled_rows is None
        else filled_rows
    )
    by_market = defaultdict(float)
    by_token = defaultdict(float)
    by_cluster = defaultdict(float)
    by_opinion = Counter()
    total = 0.0
    low_tail = 0.0
    for row in filled:
        spent = maybe_float(row.get("total_spent_usdc")) or 0.0
        total += spent
        by_market[row.get("market_id") or "unknown"] += spent
        by_token[row.get("clob_token_id") or row.get("order_id") or "unknown"] += spent
        by_cluster[row.get("adjacent_bin_cluster_key") or adjacent_bin_cluster_key(row)] += spent
        by_opinion[independent_opinion_key(row)] += 1
        if bool_value(row.get("low_price_tail"), False):
            low_tail += spent
    top_market_id, top_market_spent = max(by_market.items(), key=lambda item: item[1], default=("", 0.0))
    top_token_id, top_token_spent = max(by_token.items(), key=lambda item: item[1], default=("", 0.0))
    top_cluster_key, top_cluster_spent = max(by_cluster.items(), key=lambda item: item[1], default=("", 0.0))
    repeated_opinion_count = sum(max(0, count - 1) for count in by_opinion.values())
    return {
        "spent_usdc": round(total, 6),
        "top_market_id": top_market_id,
        "top_market_spent_usdc": round(top_market_spent, 6),
        "top_market_spend_share": compact_float(top_market_spent / total if total > 0 else 0.0),
        "top_token_id": top_token_id,
        "top_token_spent_usdc": round(top_token_spent, 6),
        "top_token_spend_share": compact_float(top_token_spent / total if total > 0 else 0.0),
        "top_adjacent_cluster_key": top_cluster_key,
        "top_adjacent_cluster_spent_usdc": round(top_cluster_spent, 6),
        "top_adjacent_cluster_spend_share": compact_float(top_cluster_spent / total if total > 0 else 0.0),
        "low_price_tail_spent_usdc": round(low_tail, 6),
        "low_price_tail_spend_share": compact_float(low_tail / total if total > 0 else 0.0),
        "repeated_opinion_count": repeated_opinion_count,
    }


def taker_settlement_label_complete(row):
    grade = str(row.get("quality_grade") or "").strip().lower()
    if grade in TAKER_COMPLETE_QUALITY_GRADES:
        return True
    source = str(row.get("settlement_source") or "").strip().lower()
    if source not in TAKER_DAILY_SETTLEMENT_SOURCES:
        return False
    if row.get("settlement_bucket") in (None, ""):
        return False
    reconciliation = str(row.get("reconciliation_status") or "").strip().lower()
    return reconciliation not in TAKER_BLOCKING_RECONCILIATION_STATUSES


def label_summary_for_target(labels_csv, target_date):
    target = ensure_date(target_date).isoformat()
    label_rows = 0
    settlement_complete_rows = 0
    quality_counts = Counter()
    for row in iter_csv_rows(labels_csv, attach_diagnostics=True):
        if row.get("target_date") != target:
            continue
        label_rows += 1
        quality_counts[row.get("quality_grade") or "unknown"] += 1
        settlement_complete_rows += int(taker_settlement_label_complete(row))
    return {
        "target_date": target,
        "label_rows": label_rows,
        "complete_rows": settlement_complete_rows,
        "settlement_complete_rows": settlement_complete_rows,
        "snapshot_quality_complete_rows": quality_counts.get("complete", 0),
        "partial_rows": quality_counts.get("partial", 0),
        "quality_counts": dict(sorted(quality_counts.items())),
    }


def strategy_gate_for_bakeoff(
    strategy_row,
    scored_rows,
    source_rows,
    min_settled_orders=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS,
    min_settled_markets=DEFAULT_PROMOTION_MIN_SETTLED_MARKETS,
    min_settlement_expected_pnl_usdc=DEFAULT_PROMOTION_MIN_SETTLED_EXPECTED_PNL_USDC,
    max_drawdown_usdc=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC,
    max_top_market_spend_share=1.0,
    max_repeated_opinion_count=0,
    max_tail_fill_fraction=DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION,
    require_real_no_book_for_two_sided=True,
    source_marks=None,
    strategy_fills=None,
):
    strategy_id = strategy_row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
    filled = (
        strategy_filled_rows(scored_rows, strategy_id)
        if strategy_fills is None
        else strategy_fills
    )
    settled = int(strategy_row.get("settled_order_count") or 0)
    settled_markets = int(strategy_row.get("settled_market_count") or 0)
    unsettled = int(strategy_row.get("unsettled_order_count") or 0)
    unscored = int(strategy_row.get("unscored_order_count") or 0)
    clob_failures = int(strategy_row.get("clob_continuity_fail_count") or 0)
    mark_outliers = int(strategy_row.get("mark_sanity_outlier_count") or 0)
    spent = maybe_float(strategy_row.get("spent_usdc")) or 0.0
    net = maybe_float(strategy_row.get("net_pnl_usdc")) or 0.0
    roi = net / spent if spent > 0 else None
    after_fee_scored = bool_value(strategy_row.get("after_fee_pnl_scored"), False)
    after_slippage_scored = bool_value(strategy_row.get("after_slippage_pnl_scored"), False)
    drawdown = cumulative_drawdown_usdc(filled)
    sign_flips = source_mark_sign_flip_count(
        source_rows,
        scored_rows,
        strategy_id,
        source_marks=source_marks,
        filled_rows=filled,
    )
    concentration = strategy_concentration_summary(
        scored_rows,
        strategy_id,
        filled_rows=filled,
    )
    top_market_share = maybe_float(concentration.get("top_market_spend_share")) or 0.0
    repeated_opinions = int(concentration.get("repeated_opinion_count") or 0)
    settlement_expected = maybe_float(strategy_row.get("settlement_scored_expected_pnl_usdc")) or 0.0
    tail_fraction = maybe_float(strategy_row.get("low_price_tail_fill_fraction")) or 0.0
    no_side_status = strategy_row.get("no_side_live_scale_book_status") or "PASS"
    two_sided_book_ok = (
        not bool_value(require_real_no_book_for_two_sided, True)
        or strategy_row.get("strategy_family") != "two_sided"
        or no_side_status == "PASS"
    )
    gates = [
        {
            "name": "min_settled_sample",
            "ok": settled >= int(min_settled_orders),
            "value": settled,
            "threshold": int(min_settled_orders),
        },
        {
            "name": "min_settled_markets",
            "ok": settled_markets >= int(min_settled_markets),
            "value": settled_markets,
            "threshold": int(min_settled_markets),
        },
        {
            "name": "min_settlement_scored_expected_pnl",
            "ok": settlement_expected >= float(min_settlement_expected_pnl_usdc),
            "value": compact_float(settlement_expected),
            "threshold": compact_float(min_settlement_expected_pnl_usdc),
        },
        {
            "name": "after_fee_pnl_scored",
            "ok": after_fee_scored,
            "value": after_fee_scored,
            "threshold": True,
        },
        {
            "name": "after_slippage_pnl_scored",
            "ok": after_slippage_scored,
            "value": after_slippage_scored,
            "threshold": True,
        },
        {
            "name": "real_no_book_depth_for_two_sided",
            "ok": two_sided_book_ok,
            "value": no_side_status,
            "threshold": "PASS",
        },
        {
            "name": "non_negative_settled_roi",
            "ok": settled >= int(min_settled_orders) and roi is not None and roi >= 0 and net >= 0,
            "value": compact_float(roi),
            "threshold": 0.0,
        },
        {
            "name": "max_drawdown",
            "ok": drawdown <= float(max_drawdown_usdc),
            "value": compact_float(drawdown),
            "threshold": float(max_drawdown_usdc),
        },
        {
            "name": "no_unresolved_orders",
            "ok": unsettled == 0 and unscored == 0,
            "value": unsettled + unscored,
            "threshold": 0,
        },
        {
            "name": "no_resolved_stale_mark_sign_flips",
            "ok": sign_flips == 0,
            "value": sign_flips,
            "threshold": 0,
        },
        {
            "name": "no_clob_continuity_failures",
            "ok": clob_failures == 0,
            "value": clob_failures,
            "threshold": 0,
        },
        {
            "name": "no_mark_sanity_outliers",
            "ok": mark_outliers == 0,
            "value": mark_outliers,
            "threshold": 0,
        },
        {
            "name": "max_market_concentration",
            "ok": top_market_share <= float(max_top_market_spend_share),
            "value": compact_float(top_market_share),
            "threshold": float(max_top_market_spend_share),
        },
        {
            "name": "max_repeated_opinion_concentration",
            "ok": repeated_opinions <= int(max_repeated_opinion_count),
            "value": repeated_opinions,
            "threshold": int(max_repeated_opinion_count),
        },
        {
            "name": "max_tail_fill_fraction",
            "ok": tail_fraction <= float(max_tail_fill_fraction),
            "value": compact_float(tail_fraction),
            "threshold": compact_float(max_tail_fill_fraction),
        },
    ]
    failed = [row["name"] for row in gates if not row["ok"]]
    return {
        "strategy_id": strategy_id,
        "strategy_family": strategy_row.get("strategy_family") or "unknown",
        "status": "PASS" if not failed else "BLOCK",
        "failed_gates": failed,
        "filled_order_count": int(strategy_row.get("filled_order_count") or 0),
        "settled_order_count": settled,
        "settled_market_count": settled_markets,
        "unsettled_order_count": unsettled,
        "unscored_order_count": unscored,
        "after_fee_pnl_scored": after_fee_scored,
        "after_slippage_pnl_scored": after_slippage_scored,
        "pnl_fee_basis": strategy_row.get("pnl_fee_basis") or "",
        "after_fee_pnl_basis": strategy_row.get("after_fee_pnl_basis") or strategy_row.get("pnl_fee_basis") or "",
        "live_profitability_evidence_basis": strategy_row.get("live_profitability_evidence_basis") or "",
        "no_side_fill_count": int(strategy_row.get("no_side_fill_count") or 0),
        "no_side_real_book_fill_count": int(strategy_row.get("no_side_real_book_fill_count") or 0),
        "no_side_synthetic_book_fill_count": int(strategy_row.get("no_side_synthetic_book_fill_count") or 0),
        "no_side_stale_book_fill_count": int(strategy_row.get("no_side_stale_book_fill_count") or 0),
        "no_side_missing_depth_fill_count": int(strategy_row.get("no_side_missing_depth_fill_count") or 0),
        "no_side_live_scale_book_status": no_side_status,
        "spent_usdc": compact_float(spent),
        "net_pnl_usdc": compact_float(net),
        "settlement_scored_expected_pnl_usdc": compact_float(settlement_expected),
        "roi": compact_float(roi),
        "low_price_tail_fill_fraction": compact_float(tail_fraction),
        "max_drawdown_usdc": compact_float(drawdown),
        "stale_mark_sign_flip_count": sign_flips,
        "clob_continuity_fail_count": clob_failures,
        "mark_sanity_outlier_count": mark_outliers,
        "concentration": concentration,
        "gates": gates,
    }


def paired_strategy_comparisons(strategy_rows, promotion_gates, control_strategy_id=DEFAULT_CONTROL_STRATEGY_ID):
    by_strategy = {row.get("strategy_id"): row for row in strategy_rows or []}
    by_gate = {row.get("strategy_id"): row for row in promotion_gates or []}
    control = by_strategy.get(control_strategy_id) or {}
    control_spent = maybe_float(control.get("spent_usdc")) or 0.0
    control_net = maybe_float(control.get("net_pnl_usdc")) or 0.0
    control_roi = control_net / control_spent if control_spent > 0 else None
    comparisons = []
    for row in strategy_rows or []:
        strategy_id = row.get("strategy_id")
        if strategy_id == control_strategy_id:
            continue
        spent = maybe_float(row.get("spent_usdc")) or 0.0
        net = maybe_float(row.get("net_pnl_usdc")) or 0.0
        roi = net / spent if spent > 0 else None
        comparisons.append({
            "control_strategy_id": control_strategy_id,
            "candidate_strategy_id": strategy_id,
            "candidate_strategy_family": row.get("strategy_family") or "unknown",
            "control_status": (by_gate.get(control_strategy_id) or {}).get("status"),
            "candidate_status": (by_gate.get(strategy_id) or {}).get("status"),
            "control_net_pnl_usdc": compact_float(control_net),
            "candidate_net_pnl_usdc": compact_float(net),
            "delta_net_pnl_usdc": compact_float(net - control_net),
            "control_roi": compact_float(control_roi),
            "candidate_roi": compact_float(roi),
            "delta_roi": compact_float(roi - control_roi) if roi is not None and control_roi is not None else None,
            "control_filled_order_count": int(control.get("filled_order_count") or 0),
            "candidate_filled_order_count": int(row.get("filled_order_count") or 0),
            "control_spent_usdc": compact_float(control_spent),
            "candidate_spent_usdc": compact_float(spent),
        })
    return comparisons


def render_bakeoff_report(payload):
    summary = payload.get("summary") or {}
    pnl = payload.get("pnl") or {}
    strategies = pnl.get("by_strategy") or []
    gates = payload.get("promotion_gates") or []
    comparisons = payload.get("paired_comparisons") or []
    blockers = payload.get("blockers") or []
    gate_by_strategy = {row.get("strategy_id"): row for row in gates}
    lines = [
        "# Settlement-Scored Taker Strategy Bakeoff",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Source run: `{payload.get('source_run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Input orders: `{payload.get('input_orders_path')}`",
        f"Labels: `{payload.get('labels_csv')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Strategy count", summary.get("strategy_count")],
            ["Replay input rows", summary.get("replay_input_rows")],
            ["Replay ticks", summary.get("replay_tick_count")],
            ["Scored order rows", summary.get("scored_order_rows")],
            ["Label rows for date", (payload.get("label_summary") or {}).get("label_rows")],
            ["Exchange economics", summary.get("exchange_economics_gate_status") or "-"],
            ["Exchange snapshot", summary.get("exchange_economics_snapshot_id") or "-"],
            [
                "Profitability artifact verification",
                (payload.get("profitability_artifact_verification") or {}).get("status") or "-",
            ],
            ["Blockers", len(blockers)],
        ],
    ))
    if blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(markdown_table(
            ["Code", "Detail"],
            [[row.get("code"), row.get("detail")] for row in blockers],
        ))
    lines.extend(["", "## Strategy Results", ""])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Family",
            "Filled",
            "Settled",
            "Unresolved",
            "Expected P&L",
            "Risk-Adj Exp P&L",
            "Net P&L",
            "ROI",
            "Drawdown",
            "Tail Spent",
            "Tail Fraction",
            "Top Market Share",
            "Gate",
        ],
        [
            [
                row.get("strategy_id"),
                row.get("strategy_family"),
                row.get("filled_order_count"),
                row.get("settled_order_count"),
                row.get("unsettled_order_count"),
                fmt_num(row.get("expected_pnl_usdc"), 4),
                fmt_num(row.get("risk_adjusted_expected_pnl_usdc"), 4),
                fmt_num(row.get("net_pnl_usdc"), 4),
                fmt_num((gate_by_strategy.get(row.get("strategy_id")) or {}).get("roi"), 4),
                fmt_num((gate_by_strategy.get(row.get("strategy_id")) or {}).get("max_drawdown_usdc"), 4),
                fmt_num(row.get("low_price_tail_spent_usdc"), 2),
                fmt_num(row.get("low_price_tail_fill_fraction"), 4),
                fmt_num(
                    ((gate_by_strategy.get(row.get("strategy_id")) or {}).get("concentration") or {}).get(
                        "top_market_spend_share"
                    ),
                    4,
                ),
                (gate_by_strategy.get(row.get("strategy_id")) or {}).get("status"),
            ]
            for row in strategies
        ],
    ))
    if comparisons:
        lines.extend(["", "## Paired Against Control", ""])
        lines.extend(markdown_table(
            ["Candidate", "Status", "Delta Net P&L", "Delta ROI", "Candidate Spent", "Control Spent"],
            [
                [
                    row.get("candidate_strategy_id"),
                    row.get("candidate_status"),
                    fmt_num(row.get("delta_net_pnl_usdc"), 4),
                    fmt_num(row.get("delta_roi"), 4),
                    fmt_num(row.get("candidate_spent_usdc"), 2),
                    fmt_num(row.get("control_spent_usdc"), 2),
                ]
                for row in comparisons
            ],
        ))
    lines.extend(["", "## Promotion Gates", ""])
    gate_rows = []
    for row in gates:
        gate_rows.append([
            row.get("strategy_id"),
            row.get("status"),
            ", ".join(row.get("failed_gates") or []) or "-",
            row.get("settled_order_count"),
            row.get("settled_market_count"),
            fmt_num(row.get("net_pnl_usdc"), 4),
            fmt_num(row.get("settlement_scored_expected_pnl_usdc"), 4),
            fmt_num(row.get("roi"), 4),
            fmt_num(row.get("low_price_tail_fill_fraction"), 4),
            fmt_num(row.get("max_drawdown_usdc"), 4),
            row.get("stale_mark_sign_flip_count"),
            row.get("clob_continuity_fail_count"),
            row.get("mark_sanity_outlier_count"),
        ])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Status",
            "Failed Gates",
            "Settled",
            "Markets",
            "Net P&L",
            "Expected P&L",
            "ROI",
            "Tail Fraction",
            "Drawdown",
            "Sign Flips",
            "CLOB Fails",
            "Mark Outliers",
        ],
        gate_rows,
    ))
    lines.append("")
    return "\n".join(lines)


def _run_taker_strategy_bakeoff_impl(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    strategies=DEFAULT_BAKEOFF_STRATEGIES,
    budget_usdc=None,
    out_json=None,
    out_report=None,
    now=None,
    experiment_id=None,
    config=None,
    min_settled_orders=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS,
    max_drawdown_usdc=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    stream_tapes=True,
    aggregation=None,
):
    now = utc_now(now)
    run_folder = Path(run_folder)
    labels_csv = Path(labels_csv)
    input_orders_path = run_folder / "orders_long.csv"
    if aggregation is not None:
        aggregation.ingest_order_tape(input_orders_path)
        source_rows = aggregation.order_rows
        replay_inputs = aggregation.replay_inputs
        first_source_row = source_rows.first() or {}
    else:
        source_rows = read_order_rows(input_orders_path)
        replay_inputs = replay_input_rows_from_orders(source_rows)
        first_source_row = source_rows[0] if source_rows else {}
    run_config = read_json(run_folder / "run_config.json", {}) or {}
    source_summary = _read_bakeoff_source_summary(run_folder / "run_summary.json")
    target = ensure_date(
        run_config.get("target_date")
        or source_summary.get("target_date")
        or first_source_row.get("target_date")
        or run_folder.parent.name
    )
    source_run_id = (
        run_config.get("run_id")
        or source_summary.get("run_id")
        or first_source_row.get("run_id")
        or run_folder.name
    )
    base_config = {
        **DEFAULT_CONFIG,
        **(run_config.get("policy_config") or {}),
        **(config or {}),
    }
    base_config = enrich_config_with_performance_gates(base_config, target)
    exchange_gate_required = (
        bool(exchange_economics_required)
        if exchange_economics_required is not None
        else (
            (
                Path(run_folder).is_relative_to(DEFAULT_RUNS_ROOT)
                if hasattr(Path(run_folder), "is_relative_to")
                else str(Path(run_folder)).startswith(str(DEFAULT_RUNS_ROOT))
            )
            or exchange_economics_snapshot_path is not None
        )
    )
    exchange_gate = exchange_economics.load_exchange_economics_gate(
        exchange_economics_snapshot_path or exchange_economics.DEFAULT_SNAPSHOT,
        target,
        platform=exchange_economics_platform,
        now=now,
        required=exchange_gate_required,
    )
    exchange_fields = exchange_economics.exchange_economics_artifact_fields(exchange_gate)
    budget = float(
        budget_usdc
        if budget_usdc is not None
        else run_config.get("budget_usdc")
        or ((source_summary.get("summary") or {}).get("budget_usdc"))
        or 100.0
    )
    strategy_specs = selected_strategy_specs(strategies, base_config=base_config)
    strategy_ids = [row["strategy_id"] for row in strategy_specs]
    experiment_id = experiment_id or default_experiment_id(target, strategy_ids)
    bakeoff_run_id = f"{source_run_id}-bakeoff"
    labels = load_settlement_labels(labels_csv)
    if aggregation is not None:
        replay_tick_count = sum(1 for _rows in replay_inputs.iter_ticks())
        scored_rows = aggregation.scored_rows
        budget_ledger = aggregation.budget_ledger
        generated_order_row_count = 0
        matched_filled_orders = 0
        unmatched_filled_orders = 0
        for strategy_order, strategy in enumerate(strategy_specs):
            strategy_existing_fills = []
            for tick_order, tick_rows in enumerate(replay_inputs.iter_ticks()):
                rows, ledger = apply_taker_budget(
                    tick_rows,
                    strategy_existing_fills,
                    strategy.get("budget_usdc") or budget,
                    bakeoff_run_id,
                    target,
                    now,
                    strategy["config"],
                    strategy=strategy,
                    experiment_id=experiment_id,
                )
                strategy_existing_fills.extend(
                    row for row in rows
                    if str(row.get("order_status") or "").upper() == "FILLED"
                )
                for row in rows:
                    row.update({
                        "exchange_economics_snapshot_id": exchange_fields.get("exchange_economics_snapshot_id"),
                        "exchange_economics_hash": exchange_fields.get("exchange_economics_hash"),
                        "exchange_economics_evidence_basis": exchange_fields.get("exchange_economics_evidence_basis"),
                    })
                scored_tick, tick_score_summary = score_orders_against_labels(rows, labels)
                scored_rows.extend(
                    scored_tick,
                    strategy_order=strategy_order,
                    tick_order=tick_order,
                )
                budget_ledger.extend(
                    ledger,
                    strategy_order=strategy_order,
                    tick_order=tick_order,
                )
                generated_order_row_count += len(rows)
                matched_filled_orders += int(
                    tick_score_summary.get("matched_filled_orders") or 0
                )
                unmatched_filled_orders += int(
                    tick_score_summary.get("unmatched_filled_orders") or 0
                )
            del strategy_existing_fills
        aggregation.commit()
        score_summary = {
            "matched_filled_orders": matched_filled_orders,
            "unmatched_filled_orders": unmatched_filled_orders,
            "label_count": len(labels.get("by_event_slug", {})),
        }
    else:
        replay_ticks = replay_input_ticks(replay_inputs)
        replay_tick_count = len(replay_ticks)
        generated_rows = []
        budget_ledger = []
        for strategy in strategy_specs:
            strategy_existing_fills = []
            for tick_rows in replay_ticks:
                rows, ledger = apply_taker_budget(
                    tick_rows,
                    strategy_existing_fills,
                    strategy.get("budget_usdc") or budget,
                    bakeoff_run_id,
                    target,
                    now,
                    strategy["config"],
                    strategy=strategy,
                    experiment_id=experiment_id,
                )
                strategy_existing_fills.extend(
                    row for row in rows
                    if str(row.get("order_status") or "").upper() == "FILLED"
                )
                generated_rows.extend(rows)
                budget_ledger.extend(ledger)
        for row in generated_rows:
            row.update({
                "exchange_economics_snapshot_id": exchange_fields.get("exchange_economics_snapshot_id"),
                "exchange_economics_hash": exchange_fields.get("exchange_economics_hash"),
                "exchange_economics_evidence_basis": exchange_fields.get("exchange_economics_evidence_basis"),
            })
        scored_rows, score_summary = score_orders_against_labels(generated_rows, labels)
        generated_order_row_count = len(generated_rows)
    total_budget_usdc = sum(float(item.get("budget_usdc") or budget) for item in strategy_specs)
    pnl_payload = build_pnl_payload(
        scored_rows,
        total_budget_usdc,
        bakeoff_run_id,
        target,
        now=now,
        policy_config=base_config,
    )
    pnl_payload["exchange_economics_gate"] = exchange_gate
    pnl_payload.update(exchange_fields)
    pnl_payload.setdefault("summary", {}).update({
        "exchange_economics_gate_status": exchange_gate.get("status"),
        "promotion_evidence_basis": (
            "settlement_scored" if exchange_gate.get("ok") else exchange_economics.STALE_EVIDENCE_BASIS
        ),
        **exchange_fields,
    })
    for row in pnl_payload.get("by_strategy") or []:
        row.update({
            "exchange_economics_gate_status": exchange_gate.get("status"),
            **exchange_fields,
        })
    label_summary = label_summary_for_target(labels_csv, target)
    source_marks = source_mark_index(source_rows)
    filled_by_strategy = defaultdict(list)
    for scored_row in scored_rows:
        if str(scored_row.get("order_status") or "").upper() == "FILLED":
            filled_by_strategy[strategy_id_for_row(scored_row)].append(scored_row)
    promotion_gates = [
        strategy_gate_for_bakeoff(
            row,
            scored_rows,
            source_rows,
            min_settled_orders=min_settled_orders,
            min_settled_markets=base_config.get(
                "promotion_min_settled_markets",
                DEFAULT_PROMOTION_MIN_SETTLED_MARKETS,
            ),
            min_settlement_expected_pnl_usdc=base_config.get(
                "promotion_min_settled_expected_pnl_usdc",
                DEFAULT_PROMOTION_MIN_SETTLED_EXPECTED_PNL_USDC,
            ),
            max_drawdown_usdc=max_drawdown_usdc,
            max_top_market_spend_share=base_config.get("canary_max_top_market_spend_share", 1.0),
            max_repeated_opinion_count=base_config.get("canary_max_repeated_opinion_count", 0),
            max_tail_fill_fraction=base_config.get(
                "promotion_max_tail_fill_fraction",
                DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION,
            ),
            require_real_no_book_for_two_sided=base_config.get(
                "two_sided_real_no_book_required_for_promotion",
                True,
            ),
            source_marks=source_marks,
            strategy_fills=filled_by_strategy.get(strategy_id_for_row(row), []),
        )
        for row in pnl_payload.get("by_strategy") or []
    ]
    paired = paired_strategy_comparisons(
        pnl_payload.get("by_strategy") or [],
        promotion_gates,
        control_strategy_id=DEFAULT_CONTROL_STRATEGY_ID,
    )
    blockers = []
    if not source_rows:
        blockers.append({
            "code": "missing_orders_tape",
            "detail": f"No orders_long.csv rows found at {input_orders_path}",
        })
    if label_summary["label_rows"] == 0:
        blockers.append({
            "code": "missing_target_date_labels",
            "detail": f"No settlement labels for {target.isoformat()} in {labels_csv}",
        })
    elif label_summary["complete_rows"] < label_summary["label_rows"]:
        blockers.append({
            "code": "partial_target_date_labels",
            "detail": (
                f"{label_summary['label_rows'] - label_summary['complete_rows']} of "
                f"{label_summary['label_rows']} settlement labels for {target.isoformat()} "
                "are not taker-complete settlement labels; do not promote from this bakeoff alone"
            ),
        })
    if score_summary.get("unmatched_filled_orders"):
        blockers.append({
            "code": "unmatched_filled_orders",
            "detail": (
                f"{score_summary['unmatched_filled_orders']} filled replay orders had no settlement label"
            ),
        })
    if not exchange_gate.get("ok"):
        blockers.append({
            "code": "paper_stale_exchange_economics",
            "detail": exchange_gate.get("reason") or "Exchange economics snapshot is stale, missing, or mismatched.",
            "exchange_economics_snapshot_id": exchange_fields.get("exchange_economics_snapshot_id"),
        })
        for gate in promotion_gates:
            failed_gates = list(gate.get("failed_gates") or [])
            if "paper_stale_exchange_economics" not in failed_gates:
                failed_gates.append("paper_stale_exchange_economics")
            gate["failed_gates"] = failed_gates
            gate["status"] = "BLOCK"
    source_profitability_verification = verify_taker_profitability_artifacts(
        run_folder,
        exchange_economics_gate=exchange_gate,
    )
    replay_profitability_verification = _current_replay_profitability_verification(
        scored_rows,
        pnl_payload,
        base_config,
        exchange_economics_gate=exchange_gate,
    )
    if source_profitability_verification.get("status") == "PASS":
        profitability_verification = {
            **source_profitability_verification,
            "evidence_basis": "source_current_artifacts",
            "source_status": source_profitability_verification.get("status"),
            "current_replay_status": replay_profitability_verification.get("status"),
        }
    elif replay_profitability_verification.get("status") == "PASS":
        profitability_verification = {
            **replay_profitability_verification,
            "source_status": source_profitability_verification.get("status"),
            "source_failed_check_count": source_profitability_verification.get("failed_check_count"),
            "source_run_folder": str(run_folder),
        }
    else:
        source_failures = [
            {
                **row,
                "scope": "source_artifact",
            }
            for row in source_profitability_verification.get("checks") or []
            if row.get("status") == "FAIL"
        ]
        replay_failures = [
            {
                **row,
                "scope": "current_replay",
            }
            for row in replay_profitability_verification.get("checks") or []
            if row.get("status") == "FAIL"
        ]
        profitability_verification = {
            "schema_version": COMPOSITE_PROFITABILITY_SCHEMA_VERSION,
            "status": "BLOCK",
            "evidence_basis": "no_current_profitability_evidence",
            "source_status": source_profitability_verification.get("status"),
            "current_replay_status": replay_profitability_verification.get("status"),
            "failed_check_count": len(source_failures) + len(replay_failures),
            "check_count": (
                int(source_profitability_verification.get("check_count") or 0)
                + int(replay_profitability_verification.get("check_count") or 0)
            ),
            "checks": source_failures + replay_failures,
            "source_run_folder": str(run_folder),
        }
    if profitability_verification.get("status") == "BLOCK":
        failed_codes = [
            row.get("code")
            for row in profitability_verification.get("checks") or []
            if row.get("status") == "FAIL" and row.get("code")
        ]
        blockers.append({
            "code": "profitability_artifact_verification_failed",
            "detail": (
                "Source taker run lacks current fee/slippage/executable-depth/"
                "benchmark/no-trade profitability fields"
            ),
            "failed_check_count": profitability_verification.get("failed_check_count"),
            "failed_checks": failed_codes[:10],
        })
        for gate in promotion_gates:
            failed_gates = list(gate.get("failed_gates") or [])
            if "profitability_artifact_verification" not in failed_gates:
                failed_gates.append("profitability_artifact_verification")
            gate["failed_gates"] = failed_gates
            gate["status"] = "BLOCK"
    out_json = Path(out_json) if out_json else run_folder / "strategy_bakeoff.json"
    out_report = Path(out_report) if out_report else run_folder / "strategy_bakeoff.md"
    disk_preflight = disk_capacity_preflight(
        out_json.parent,
        min_free_bytes=min_free_bytes,
        usage_fn=disk_usage_fn,
    )
    if not disk_preflight.get("ok"):
        raise RuntimeError(
            "insufficient free disk for taker strategy bakeoff: "
            f"free={disk_preflight.get('free_bytes')} required={disk_preflight.get('required_free_bytes')}"
        )
    payload = {
        "schema_version": STRATEGY_BAKEOFF_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": bakeoff_run_id,
        "source_run_id": source_run_id,
        "target_date": target.isoformat(),
        "input_run_folder": str(run_folder),
        "input_orders_path": str(input_orders_path),
        "labels_csv": str(labels_csv),
        "output_json_path": str(out_json),
        "output_report_path": str(out_report),
        "experiment_id": experiment_id,
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_ids": strategy_ids,
        "budget_per_strategy_usdc": compact_float(budget),
        "budget_scope": "per_strategy",
        "exchange_economics_gate": exchange_gate,
        **exchange_fields,
        "strategy_registry": strategy_registry_payload(),
        "strategies": [
            {
                key: value
                for key, value in item.items()
                if key not in {"config"}
            }
            for item in strategy_specs
        ],
        "label_summary": label_summary,
        "score_summary": score_summary,
        "summary": {
            "strategy_count": len(strategy_specs),
            "source_order_rows": len(source_rows),
            "replay_input_rows": len(replay_inputs),
            "replay_tick_count": replay_tick_count,
            "generated_order_rows": generated_order_row_count,
            "scored_order_rows": len(scored_rows),
            "exchange_economics_gate_status": exchange_gate.get("status"),
            **exchange_fields,
            "promotion_pass_count": sum(1 for row in promotion_gates if row.get("status") == "PASS"),
            "promotion_block_count": sum(1 for row in promotion_gates if row.get("status") != "PASS"),
        },
        "pnl": pnl_payload,
        "profitability_artifact_verification": profitability_verification,
        "source_profitability_artifact_verification": source_profitability_verification,
        "current_replay_profitability_verification": replay_profitability_verification,
        "promotion_gates": promotion_gates,
        "paired_comparisons": paired,
        "budget_ledger": budget_ledger,
        "disk_capacity_preflight": disk_preflight,
        "blockers": blockers,
    }
    write_text_atomic(out_report, render_bakeoff_report(payload))
    write_json(out_json, payload)
    write_bakeoff_ledger_projection(out_json, payload)
    return payload


def run_taker_strategy_bakeoff(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    strategies=DEFAULT_BAKEOFF_STRATEGIES,
    budget_usdc=None,
    out_json=None,
    out_report=None,
    now=None,
    experiment_id=None,
    config=None,
    min_settled_orders=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS,
    max_drawdown_usdc=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    stream_tapes=True,
    materialize_output_rows=True,
):
    """Run one bakeoff while owning and deterministically releasing scratch."""

    aggregation = TakerRunAggregation() if stream_tapes else None
    try:
        payload = _run_taker_strategy_bakeoff_impl(
            run_folder,
            labels_csv=labels_csv,
            strategies=strategies,
            budget_usdc=budget_usdc,
            out_json=out_json,
            out_report=out_report,
            now=now,
            experiment_id=experiment_id,
            config=config,
            min_settled_orders=min_settled_orders,
            max_drawdown_usdc=max_drawdown_usdc,
            min_free_bytes=min_free_bytes,
            disk_usage_fn=disk_usage_fn,
            exchange_economics_snapshot_path=exchange_economics_snapshot_path,
            exchange_economics_platform=exchange_economics_platform,
            exchange_economics_required=exchange_economics_required,
            stream_tapes=stream_tapes,
            aggregation=aggregation,
        )
        if aggregation is None:
            return payload
        if materialize_output_rows:
            return aggregation.materialize(payload)
        return DeferredTakerPayload(payload, aggregation)
    except BaseException:
        if aggregation is not None:
            aggregation.close()
        raise
    finally:
        if aggregation is not None and materialize_output_rows:
            aggregation.close()


def _bakeoff_mtime_utc(path):
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def bakeoff_needs_refresh(run_folder, labels_csv=DEFAULT_LABELS_CSV, out_json=None):
    run_folder = Path(run_folder)
    out_json = Path(out_json) if out_json else run_folder / "strategy_bakeoff.json"
    if not out_json.exists():
        return True
    projection = load_bakeoff_ledger_projection(
        out_json,
        expected_bakeoff_schema_version=STRATEGY_BAKEOFF_SCHEMA_VERSION,
    )
    if projection is None:
        try:
            legacy_size = out_json.stat().st_size
        except OSError:
            return True
        # Small pre-projection artifacts remain compatible. Large historical
        # artifacts must be rebuilt once so all watchdog consumers stay
        # bounded instead of decoding the canonical JSON into Python objects.
        if legacy_size > DEFAULT_PROJECTION_MAX_BYTES:
            return True
        if (
            read_pretty_json_top_level_schema_version(out_json)
            != STRATEGY_BAKEOFF_SCHEMA_VERSION
        ):
            return True
    bakeoff_mtime = _bakeoff_mtime_utc(out_json)
    cutoff = max(
        (
            value for value in (
                _bakeoff_mtime_utc(run_folder / "orders_long.csv"),
                _bakeoff_mtime_utc(labels_csv),
            )
            if value is not None
        ),
        default=None,
    )
    return bool(bakeoff_mtime is None or (cutoff is not None and bakeoff_mtime < cutoff))


def ensure_taker_strategy_bakeoff(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    *,
    strategies=DEFAULT_BAKEOFF_STRATEGIES,
    now=None,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    stream_tapes=True,
    materialize_output_rows=True,
    include_payload=True,
):
    run_folder = Path(run_folder)
    out_json = run_folder / "strategy_bakeoff.json"
    if not bakeoff_needs_refresh(run_folder, labels_csv=labels_csv, out_json=out_json):
        return {
            "action": "fresh",
            "strategy_bakeoff_path": str(out_json),
            "strategy_bakeoff_report_path": str(run_folder / "strategy_bakeoff.md"),
            "payload": (read_json(out_json, {}) or {}) if include_payload else None,
        }
    payload = run_taker_strategy_bakeoff(
        run_folder,
        labels_csv=labels_csv,
        strategies=strategies,
        out_json=out_json,
        out_report=run_folder / "strategy_bakeoff.md",
        now=now,
        min_free_bytes=min_free_bytes,
        disk_usage_fn=disk_usage_fn,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
        stream_tapes=stream_tapes,
        materialize_output_rows=materialize_output_rows,
    )
    if not include_payload:
        close_payload = getattr(payload, "close", None)
        if close_payload:
            close_payload()
        payload = None
    return {
        "action": "created",
        "strategy_bakeoff_path": str(out_json),
        "strategy_bakeoff_report_path": str(run_folder / "strategy_bakeoff.md"),
        "payload": payload,
    }


def taker_bakeoff_artifact_paths(runs_root=DEFAULT_RUNS_ROOT, target_date=None):
    root = Path(runs_root)
    if target_date:
        candidates = sorted((root / ensure_date(target_date).isoformat()).glob("*/strategy_bakeoff.json"))
    else:
        candidates = sorted(root.glob("*/*/strategy_bakeoff.json"))
    return [path for path in candidates if path.exists()]


def _bakeoff_complete_label_day(payload):
    label_summary = payload.get("label_summary") or {}
    blocker_codes = {row.get("code") for row in payload.get("blockers") or []}
    return bool(
        int(label_summary.get("label_rows") or 0) > 0
        and int(label_summary.get("complete_rows") or 0) >= int(label_summary.get("label_rows") or 0)
        and not (blocker_codes & {
            "missing_target_date_labels",
            "partial_target_date_labels",
            "unmatched_filled_orders",
        })
    )


def _strategy_gate_map(payload):
    return {
        row.get("strategy_id"): row
        for row in payload.get("promotion_gates") or []
        if row.get("strategy_id")
    }


def _load_bakeoff_ledger_payload(path):
    """Load only the compact ledger projection for large bakeoff artifacts."""

    path = Path(path)
    projection = load_bakeoff_ledger_projection(
        path,
        expected_bakeoff_schema_version=STRATEGY_BAKEOFF_SCHEMA_VERSION,
    )
    if projection is not None:
        return projection
    try:
        if path.stat().st_size > DEFAULT_PROJECTION_MAX_BYTES:
            return {}
    except OSError:
        return {}
    return read_json(path, {}) or {}


def build_champion_challenger_ledger(
    *,
    runs_root=DEFAULT_RUNS_ROOT,
    target_date=None,
    bakeoff_paths=None,
    champion_strategy_id=ACTIVE_DEFAULT_STRATEGY_ID,
    now=None,
    min_complete_label_days=DEFAULT_CHAMPION_MIN_COMPLETE_LABEL_DAYS,
    min_settled_orders=DEFAULT_CHAMPION_MIN_SETTLED_ORDERS,
):
    now = utc_now(now)
    paths = [Path(path) for path in (bakeoff_paths or taker_bakeoff_artifact_paths(runs_root, target_date=target_date))]
    rows_by_strategy = {}
    runs = []
    for path in paths:
        payload = _load_bakeoff_ledger_payload(path)
        if not payload:
            continue
        complete_day = _bakeoff_complete_label_day(payload)
        blocker_codes = [row.get("code") for row in payload.get("blockers") or [] if row.get("code")]
        gates = _strategy_gate_map(payload)
        runs.append({
            "path": str(path),
            "run_id": payload.get("run_id"),
            "source_run_id": payload.get("source_run_id"),
            "target_date": payload.get("target_date"),
            "complete_label_day": complete_day,
            "blocker_codes": blocker_codes,
        })
        for strategy in (payload.get("pnl") or {}).get("by_strategy") or []:
            strategy_id = strategy.get("strategy_id")
            if not strategy_id:
                continue
            gate = gates.get(strategy_id) or {}
            entry = rows_by_strategy.setdefault(strategy_id, {
                "strategy_id": strategy_id,
                "strategy_family": strategy.get("strategy_family") or "unknown",
                "role": "champion" if strategy_id == champion_strategy_id else "challenger",
                "bakeoff_day_count": 0,
                "complete_label_day_count": 0,
                "partial_quality_day_count": 0,
                "missing_label_day_count": 0,
                "gate_pass_day_count": 0,
                "settled_order_count": 0,
                "settled_market_count": 0,
                "unresolved_order_count": 0,
                "filled_order_count": 0,
                "spent_usdc": 0.0,
                "settlement_pnl_usdc": 0.0,
                "after_fee_pnl_usdc": 0.0,
                "net_pnl_usdc": 0.0,
                "max_drawdown_usdc": 0.0,
                "low_price_tail_fill_count": 0,
                "stale_mark_sign_flip_count": 0,
                "blocker_codes": set(),
                "target_dates": set(),
            })
            entry["bakeoff_day_count"] += 1
            pending_label_evidence = any(
                int(strategy.get(field) or gate.get(field) or 0) > 0
                for field in (
                    "filled_order_count",
                    "settled_order_count",
                    "unsettled_order_count",
                    "unscored_order_count",
                )
            )
            if complete_day:
                entry["complete_label_day_count"] += 1
            else:
                if "partial_target_date_labels" in blocker_codes:
                    entry["partial_quality_day_count"] += 1
                if "missing_target_date_labels" in blocker_codes and pending_label_evidence:
                    entry["missing_label_day_count"] += 1
            if gate.get("status") == "PASS":
                entry["gate_pass_day_count"] += 1
            entry["settled_order_count"] += int(strategy.get("settled_order_count") or gate.get("settled_order_count") or 0)
            entry["settled_market_count"] += int(gate.get("settled_market_count") or 0)
            unresolved = int(strategy.get("unsettled_order_count") or 0) + int(strategy.get("unscored_order_count") or 0)
            entry["unresolved_order_count"] += unresolved
            entry["filled_order_count"] += int(strategy.get("filled_order_count") or 0)
            entry["spent_usdc"] += maybe_float(strategy.get("spent_usdc")) or 0.0
            entry["settlement_pnl_usdc"] += maybe_float(strategy.get("settlement_pnl_usdc")) or 0.0
            entry["after_fee_pnl_usdc"] += maybe_float(strategy.get("net_pnl_usdc")) or 0.0
            entry["net_pnl_usdc"] += maybe_float(strategy.get("net_pnl_usdc")) or 0.0
            entry["max_drawdown_usdc"] = max(
                entry["max_drawdown_usdc"],
                maybe_float(gate.get("max_drawdown_usdc")) or 0.0,
            )
            entry["low_price_tail_fill_count"] += int(strategy.get("low_price_tail_fill_count") or 0)
            entry["stale_mark_sign_flip_count"] += int(gate.get("stale_mark_sign_flip_count") or 0)
            entry["blocker_codes"].update(
                code for code in blocker_codes
                if code != "missing_target_date_labels" or pending_label_evidence
            )
            if payload.get("target_date"):
                entry["target_dates"].add(payload.get("target_date"))
    champion = rows_by_strategy.get(champion_strategy_id) or {
        "strategy_id": champion_strategy_id,
        "net_pnl_usdc": 0.0,
        "after_fee_pnl_usdc": 0.0,
    }
    champion_net = maybe_float(champion.get("net_pnl_usdc")) or 0.0
    strategy_rows = []
    for entry in rows_by_strategy.values():
        failed_gates = []
        if entry["complete_label_day_count"] < int(min_complete_label_days):
            failed_gates.append("min_complete_label_days")
        if entry["partial_quality_day_count"] > 0:
            failed_gates.append("no_partial_quality_days")
        if entry["missing_label_day_count"] > 0:
            failed_gates.append("no_missing_label_days")
        if entry["settled_order_count"] < int(min_settled_orders):
            failed_gates.append("min_settled_orders")
        if entry["unresolved_order_count"] > 0:
            failed_gates.append("no_unresolved_orders")
        if entry["gate_pass_day_count"] < entry["complete_label_day_count"]:
            failed_gates.append("all_complete_days_pass_strategy_gate")
        if entry["strategy_id"] != champion_strategy_id and entry["net_pnl_usdc"] <= champion_net:
            failed_gates.append("beats_current_champion_after_fee_pnl")
        promotion_status = (
            "PASS"
            if entry["strategy_id"] != champion_strategy_id and not failed_gates
            else ("CHAMPION" if entry["strategy_id"] == champion_strategy_id else "BLOCK")
        )
        row = {
            "strategy_id": entry["strategy_id"],
            "strategy_family": entry["strategy_family"],
            "role": entry["role"],
            "promotion_status": promotion_status,
            "failed_gates": failed_gates,
            "bakeoff_day_count": entry["bakeoff_day_count"],
            "complete_label_day_count": entry["complete_label_day_count"],
            "partial_quality_day_count": entry["partial_quality_day_count"],
            "missing_label_day_count": entry["missing_label_day_count"],
            "gate_pass_day_count": entry["gate_pass_day_count"],
            "settled_order_count": entry["settled_order_count"],
            "settled_market_count": entry["settled_market_count"],
            "unresolved_order_count": entry["unresolved_order_count"],
            "filled_order_count": entry["filled_order_count"],
            "spent_usdc": compact_float(entry["spent_usdc"]),
            "settlement_pnl_usdc": compact_float(entry["settlement_pnl_usdc"]),
            "after_fee_pnl_usdc": compact_float(entry["after_fee_pnl_usdc"]),
            "net_pnl_usdc": compact_float(entry["net_pnl_usdc"]),
            "max_drawdown_usdc": compact_float(entry["max_drawdown_usdc"]),
            "low_price_tail_fill_count": entry["low_price_tail_fill_count"],
            "stale_mark_sign_flip_count": entry["stale_mark_sign_flip_count"],
            "blocker_codes": sorted(entry["blocker_codes"]),
            "target_dates": sorted(entry["target_dates"]),
        }
        strategy_rows.append(row)
    challengers = [row for row in strategy_rows if row.get("promotion_status") == "PASS"]
    recommended = max(
        challengers,
        key=lambda row: maybe_float(row.get("after_fee_pnl_usdc")) or 0.0,
        default=None,
    )
    strategy_rows = sorted(
        strategy_rows,
        key=lambda row: (row.get("role") != "champion", -(maybe_float(row.get("after_fee_pnl_usdc")) or 0.0)),
    )
    return {
        "schema_version": CHAMPION_CHALLENGER_LEDGER_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "runs_root": str(runs_root),
        "target_date": ensure_date(target_date).isoformat() if target_date else None,
        "champion_strategy_id": champion_strategy_id,
        "recommended_strategy_id": (recommended or {}).get("strategy_id") or champion_strategy_id,
        "promotion_decision": "PROMOTE_CHALLENGER" if recommended else "KEEP_CHAMPION",
        "min_complete_label_days": int(min_complete_label_days),
        "min_settled_orders": int(min_settled_orders),
        "summary": {
            "bakeoff_artifact_count": len(paths),
            "loaded_bakeoff_count": len(runs),
            "strategy_count": len(strategy_rows),
            "complete_label_day_count": sum(1 for row in runs if row.get("complete_label_day")),
            "promotion_pass_count": len(challengers),
            "blocked_challenger_count": sum(
                1 for row in strategy_rows
                if row.get("role") == "challenger" and row.get("promotion_status") == "BLOCK"
            ),
        },
        "runs": runs,
        "strategies": strategy_rows,
    }


def render_champion_challenger_ledger(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Taker Champion/Challenger Ledger",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Champion: `{payload.get('champion_strategy_id')}`",
        f"Decision: `{payload.get('promotion_decision')}`",
        f"Recommended: `{payload.get('recommended_strategy_id')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Bakeoff artifacts", summary.get("bakeoff_artifact_count")],
            ["Loaded bakeoffs", summary.get("loaded_bakeoff_count")],
            ["Strategies", summary.get("strategy_count")],
            ["Complete-label days", summary.get("complete_label_day_count")],
            ["Promotion pass", summary.get("promotion_pass_count")],
            ["Blocked challengers", summary.get("blocked_challenger_count")],
            ["Min complete-label days", payload.get("min_complete_label_days")],
            ["Min settled orders", payload.get("min_settled_orders")],
        ],
    ))
    lines.extend(["", "## Strategies", ""])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Role",
            "Status",
            "Failed Gates",
            "Complete Days",
            "Missing Days",
            "Settled",
            "Unresolved",
            "After-Fee P&L",
            "Drawdown",
        ],
        [
            [
                row.get("strategy_id"),
                row.get("role"),
                row.get("promotion_status"),
                ", ".join(row.get("failed_gates") or []) or "-",
                row.get("complete_label_day_count"),
                row.get("missing_label_day_count"),
                row.get("settled_order_count"),
                row.get("unresolved_order_count"),
                fmt_num(row.get("after_fee_pnl_usdc"), 4),
                fmt_num(row.get("max_drawdown_usdc"), 4),
            ]
            for row in payload.get("strategies") or []
        ],
    ))
    lines.append("")
    return "\n".join(lines)


def write_champion_challenger_ledger(
    *,
    out_json,
    out_report=None,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    **kwargs,
):
    out_json = Path(out_json)
    disk_preflight = disk_capacity_preflight(
        out_json.parent,
        min_free_bytes=min_free_bytes,
        usage_fn=disk_usage_fn,
    )
    if not disk_preflight.get("ok"):
        raise RuntimeError(
            "insufficient free disk for taker champion/challenger ledger: "
            f"free={disk_preflight.get('free_bytes')} required={disk_preflight.get('required_free_bytes')}"
        )
    payload = build_champion_challenger_ledger(**kwargs)
    payload["disk_capacity_preflight"] = disk_preflight
    write_json(out_json, payload)
    if out_report:
        out_report = Path(out_report)
        out_report.parent.mkdir(parents=True, exist_ok=True)
        out_report.write_text(render_champion_challenger_ledger(payload), encoding="utf-8")
        payload["output_report_path"] = str(out_report)
    payload["output_json_path"] = str(out_json)
    return payload

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
