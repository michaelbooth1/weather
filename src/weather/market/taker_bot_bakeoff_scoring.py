"""Replay input and scoring helpers for taker strategy bakeoff."""

from weather.market import exchange_economics
from weather.market.taker_bot_reporting import *  # noqa: F403
from weather.schema_registry import schema_version

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

CURRENT_REPLAY_PROFITABILITY_SCHEMA_VERSION = schema_version("taker_current_replay_profitability_verification")
COMPOSITE_PROFITABILITY_SCHEMA_VERSION = schema_version("taker_profitability_artifact_verification_composite")


def _replay_profitability_check(code, status, detail, **extra):
    row = {"code": code, "status": status, "detail": detail}
    row.update(extra)
    return row


def _current_replay_profitability_verification(scored_rows, pnl_payload, config, exchange_economics_gate=None):
    """Verify that the bakeoff replay itself used current fee/depth economics."""
    config = config or {}
    pnl_payload = pnl_payload or {}
    summary = pnl_payload.get("summary") or {}
    strategy_rows = list(pnl_payload.get("by_strategy") or [])
    comparison = pnl_payload.get("strategy_comparison") or {}
    benchmark = comparison.get("market_benchmark_summary") or {}
    filled_rows = [
        row for row in scored_rows or []
        if str(row.get("order_status") or "").upper() == "FILLED"
    ]
    filled_strategy_rows = [
        row for row in strategy_rows
        if int(row.get("filled_order_count") or 0) > 0
    ]
    fee_model = str(config.get("taker_fee_model") or "").strip()
    fee_rate = maybe_float(config.get("taker_fee_rate")) or 0.0
    depth_model = str(config.get("executable_depth_model") or "").strip()
    checks = []
    if fee_model == "paper_no_fee" or fee_rate <= 0:
        checks.append(_replay_profitability_check(
            "current_replay_fee_model_not_enabled",
            "FAIL",
            "Current replay did not enable a positive taker fee model.",
            taker_fee_model=fee_model,
            taker_fee_rate=compact_float(fee_rate),
        ))
    if not depth_model:
        checks.append(_replay_profitability_check(
            "current_replay_executable_depth_model_missing",
            "FAIL",
            "Current replay did not name an executable-depth model.",
        ))
    exchange_economics_gate = exchange_economics_gate or {}
    if exchange_economics_gate.get("status") == "BLOCK" or exchange_economics_gate.get("ok") is False:
        checks.append(_replay_profitability_check(
            "current_replay_exchange_economics_not_current",
            "FAIL",
            exchange_economics_gate.get("reason") or "Current replay did not have a current exchange-economics snapshot.",
            evidence_basis=exchange_economics.STALE_EVIDENCE_BASIS,
            exchange_economics_snapshot_id=exchange_economics_gate.get("snapshot_id"),
            exchange_economics_hash=exchange_economics_gate.get("snapshot_hash"),
        ))
    if not scored_rows:
        checks.append(_replay_profitability_check(
            "current_replay_rows_missing",
            "FAIL",
            "Current replay produced no scored order rows.",
        ))
    if filled_rows:
        if not bool_value(summary.get("after_fee_pnl_scored"), False):
            checks.append(_replay_profitability_check(
                "current_replay_after_fee_pnl_not_scored",
                "FAIL",
                "Current replay summary does not mark filled orders as after-fee scored.",
            ))
        if not bool_value(summary.get("after_slippage_pnl_scored"), False):
            checks.append(_replay_profitability_check(
                "current_replay_after_slippage_pnl_not_scored",
                "FAIL",
                "Current replay summary does not mark filled orders as after-slippage scored.",
            ))
        stale_strategy_rows = [
            row.get("strategy_id") or "unknown"
            for row in filled_strategy_rows
            if not (
                bool_value(row.get("after_fee_pnl_scored"), False)
                and bool_value(row.get("after_slippage_pnl_scored"), False)
                and row.get("live_profitability_evidence_basis") == "executable_after_fee_after_slippage"
            )
        ]
        if stale_strategy_rows:
            checks.append(_replay_profitability_check(
                "current_replay_strategy_profitability_not_scored",
                "FAIL",
                "At least one filled strategy row lacks current after-fee/after-slippage scoring.",
                strategy_ids=stale_strategy_rows[:10],
            ))
    else:
        checks.append(_replay_profitability_check(
            "current_replay_realized_profitability_skipped_no_fills",
            "SKIP",
            "Current fee/depth replay produced no filled orders; realized PnL fields are not required.",
        ))
    for field in (
        "market_smarter_slice_count",
        "no_trade_recommendation_count",
        "avoided_loss_usdc",
        "missed_gain_usdc",
    ):
        if field not in benchmark:
            checks.append(_replay_profitability_check(
                f"current_replay_market_benchmark_{field}_missing",
                "FAIL",
                f"Current replay market benchmark field {field!r} is absent.",
                field=field,
            ))
    failed = [row for row in checks if row.get("status") == "FAIL"]
    return {
        "schema_version": CURRENT_REPLAY_PROFITABILITY_SCHEMA_VERSION,
        "status": "BLOCK" if failed else "PASS",
        "evidence_basis": "current_fee_depth_replay",
        "filled_order_count": int(summary.get("filled_order_count") or len(filled_rows)),
        "strategy_count": len(strategy_rows),
        "taker_fee_model": fee_model,
        "taker_fee_rate": compact_float(fee_rate),
        "executable_depth_model": depth_model,
        "exchange_economics_gate_status": exchange_economics_gate.get("status"),
        **exchange_economics.exchange_economics_artifact_fields(exchange_economics_gate),
        "check_count": len(checks),
        "failed_check_count": len(failed),
        "checks": checks,
    }


def replay_input_key_payload(row):
    kind, value, value_hi = band_key(row)
    return {
        "target_date": row.get("target_date") or "",
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "snapshot_id": row.get("snapshot_id") or "",
        "captured_at_utc": row.get("captured_at_utc") or "",
        "range_label": row.get("range_label") or "",
        "bin_kind": kind or "",
        "bin_value": value,
        "bin_value_hi": value_hi,
        "clob_token_id": row.get("clob_token_id") or row.get("clob_yes_token_id") or "",
        "fair_probability": compact_float(row.get("fair_probability")),
        "best_ask": compact_float(first_present(row, "best_ask", "clob_best_ask")),
    }


def replay_input_key(row):
    return stable_hash(replay_input_key_payload(row), length=24)


def replay_input_rows_from_orders(order_rows):
    by_key = {}
    for row in order_rows or []:
        key = replay_input_key(row)
        if key not in by_key:
            by_key[key] = dict(row)
    return list(by_key.values())


def replay_tick_sort_key(row):
    timestamp = parse_time(first_present(row, "captured_at_utc", "generated_at_utc"))
    return (
        timestamp.isoformat() if timestamp else "",
        row.get("snapshot_id") or "",
        row.get("market_id") or "",
        row.get("event_slug") or "",
    )


def replay_input_ticks(replay_inputs):
    ticks = []
    current_key = None
    current_rows = []
    for row in sorted(replay_inputs or [], key=replay_tick_sort_key):
        key = (
            row.get("captured_at_utc") or row.get("generated_at_utc") or "",
            row.get("snapshot_id") or "",
        )
        if current_key is not None and key != current_key:
            ticks.append(current_rows)
            current_rows = []
        current_key = key
        current_rows.append(row)
    if current_rows:
        ticks.append(current_rows)
    return ticks


TAKER_MODEL_VARIANT_SPECS = {
    "served_current": {
        "model_variant_id": "served_current",
        "model_variant_family": "served",
        "model_variant_role": "control",
        "probability_fields": ("fair_probability", "model_probability", "candidate_p"),
    },
    "dynamic_source_state": {
        "model_variant_id": "dynamic_source_state",
        "model_variant_family": "dynamic_source_state",
        "model_variant_role": "shadow",
        "probability_fields": (
            "dynamic_source_probability",
            "dynamic_source_state_probability",
            "probability_dynamic_source_state",
        ),
    },
    "exact_winner_catchup": {
        "model_variant_id": "exact_winner_catchup",
        "model_variant_family": "exact_winner_catchup",
        "model_variant_role": "shadow",
        "probability_fields": (
            "exact_winner_probability",
            "exact_winner_catchup_probability",
            "probability_exact_winner",
        ),
    },
    "continuous_density": {
        "model_variant_id": "continuous_density",
        "model_variant_family": "continuous_density",
        "model_variant_role": "shadow",
        "probability_fields": (
            "continuous_density_probability",
            "density_probability",
            "probability_continuous_density",
        ),
    },
    "clob_overlay": {
        "model_variant_id": "clob_overlay",
        "model_variant_family": "market_microstructure_overlay",
        "model_variant_role": "shadow",
        "probability_fields": (
            "clob_overlay_probability",
            "market_overlay_probability",
            "microstructure_probability",
        ),
    },
}


def taker_model_variant_ids(config=None, variants=None):
    raw = variants if variants not in (None, "") else (config or {}).get("taker_model_variant_basket")
    raw = raw or DEFAULT_TAKER_MODEL_VARIANT_BASKET
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = str(raw).replace(";", ",").split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def taker_model_variant_specs(config=None, variants=None):
    specs = []
    for variant_id in taker_model_variant_ids(config, variants=variants):
        base = dict(TAKER_MODEL_VARIANT_SPECS.get(variant_id) or {})
        if not base:
            base = {
                "model_variant_id": variant_id,
                "model_variant_family": "custom",
                "model_variant_role": "shadow",
                "probability_fields": (f"{variant_id}_probability",),
            }
        specs.append(base)
    return specs


def _variant_probability(row, spec):
    for field in spec.get("probability_fields") or ():
        probability = clamp_probability(row.get(field))
        if probability is not None:
            return probability, field
    return None, ""


def expand_input_rows_for_model_variants(input_rows, *, config=None, variants=None):
    specs = taker_model_variant_specs(config, variants=variants)
    include_missing = bool_value((config or {}).get("taker_model_variant_include_missing"), False)
    basket_id = stable_hash([spec["model_variant_id"] for spec in specs], length=16)
    rows = []
    materialized = Counter()
    missing = Counter()
    for input_row in input_rows or []:
        served_version = input_row.get("model_version") or input_row.get("served_model_version") or ""
        for spec in specs:
            probability, source = _variant_probability(input_row, spec)
            if probability is None and not include_missing:
                missing[spec["model_variant_id"]] += 1
                continue
            out = dict(input_row)
            out["fair_probability"] = compact_float(probability)
            out["model_probability"] = compact_float(probability)
            out["model_variant_id"] = spec["model_variant_id"]
            out["model_variant_family"] = spec["model_variant_family"]
            out["model_variant_role"] = spec["model_variant_role"]
            out["model_variant_basket_id"] = basket_id
            out["model_variant_basket_size"] = len(specs)
            out["model_variant_probability"] = compact_float(probability)
            out["model_variant_probability_source"] = source or "missing_prediction"
            out["calibrated_model_probability"] = compact_float(probability)
            out["calibrated_fair_probability"] = compact_float(probability)
            out["calibrated_fair"] = compact_float(probability)
            out["taker_edge_permission_hit_rate"] = compact_float(probability)
            out["model_variant_prediction_generated_at_utc"] = (
                input_row.get("model_variant_prediction_generated_at_utc")
                or input_row.get("prediction_generated_at_utc")
                or input_row.get("captured_at_utc")
                or ""
            )
            out["served_model_version"] = served_version
            rows.append(out)
            materialized[spec["model_variant_id"]] += 1
    return rows, {
        "basket_id": basket_id,
        "requested_variant_ids": [spec["model_variant_id"] for spec in specs],
        "materialized_variant_ids": sorted([key for key, value in materialized.items() if value > 0]),
        "missing_variant_ids": sorted([key for key, value in missing.items() if value > 0 and materialized.get(key, 0) == 0]),
        "materialized_row_count": len(rows),
        "materialized_counts": dict(sorted(materialized.items())),
        "missing_counts": dict(sorted(missing.items())),
        "include_missing": include_missing,
    }


__all__ = [name for name in globals() if not name.startswith("__")]
