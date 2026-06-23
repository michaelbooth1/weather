"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_strategy_evaluation import *  # noqa: F403
from weather.market.taker_bot_two_sided import no_side_input_row, two_sided_enabled

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def existing_budget_spent(rows):
    total = 0.0
    for row in rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        total += maybe_float(row.get("total_spent_usdc")) or 0.0
    return round(total, 6)


def existing_position_notional_by_token(rows):
    totals = defaultdict(float)
    for row in rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        token = row.get("clob_token_id") or ""
        if not token:
            continue
        totals[token] += maybe_float(row.get("fill_notional_usdc")) or 0.0
    return totals


def existing_notional_by(rows, key_func):
    totals = defaultdict(float)
    for row in rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        totals[key_func(row)] += maybe_float(row.get("fill_notional_usdc")) or 0.0
    return totals


def existing_low_price_tail_notional(rows):
    return round(sum(
        maybe_float(row.get("fill_notional_usdc")) or 0.0
        for row in rows or []
        if str(row.get("order_status") or "").upper() == "FILLED"
        and bool_value(row.get("low_price_tail"), False)
    ), 6)


def existing_market_centered_warm_tail_notional(rows):
    return round(sum(
        maybe_float(row.get("fill_notional_usdc")) or 0.0
        for row in rows or []
        if str(row.get("order_status") or "").upper() == "FILLED"
        and bool_value(row.get("market_centered_warm_tail"), False)
    ), 6)


def existing_opinion_fill_counts(rows):
    counts = Counter()
    for row in rows or []:
        if str(row.get("order_status") or "").upper() == "FILLED":
            counts[independent_opinion_key(row)] += 1
    return counts


def existing_same_snapshot_cluster_counts(rows):
    counts = Counter()
    for row in rows or []:
        if str(row.get("order_status") or "").upper() == "FILLED":
            counts[same_snapshot_adjacent_cluster_key(row)] += 1
    return counts


def remaining_cap(cap_value, used_value):
    cap = maybe_float(cap_value)
    if cap is None or cap <= 0:
        return None
    return max(0.0, cap - float(used_value or 0.0))


def taker_fee_config(config):
    model = str(config.get("taker_fee_model") or "paper_no_fee").strip() or "paper_no_fee"
    rate = max(0.0, float(config.get("taker_fee_rate") or 0.0))
    return {
        "fee_model_version": model,
        "fee_model_name": model,
        "fee_market_category": config.get("taker_fee_market_category") or "weather",
        "fee_rate": rate,
        "fee_effective_date": config.get("taker_fee_effective_date") or "",
        "fee_provenance_url": config.get("taker_fee_provenance_url") or "",
        "pnl_fee_basis": "after_fee" if rate > 0 and model != "paper_no_fee" else "paper_no_fee",
    }


def taker_fee_per_share(price, config):
    price = clamp_probability(price)
    if price is None:
        return 0.0
    fee = taker_fee_config(config)
    rate = float(fee.get("fee_rate") or 0.0)
    model = fee.get("fee_model_name") or ""
    if rate <= 0:
        return 0.0
    if model == "polymarket_symmetric_price_v1":
        return rate * price * (1.0 - price)
    if model == "flat_notional_v1":
        return rate * price
    return 0.0


def executable_depth_state(row, config):
    best_ask = clamp_probability(first_present(row, "best_ask", "clob_best_ask", "gamma_best_ask"))
    top_size = maybe_float(first_present(row, "ask_size_at_best", "clob_ask_size_at_best")) or 0.0
    depth_1pct = maybe_float(first_present(
        row,
        "ask_depth_1pct",
        "clob_depth_1pct_total",
        "clob_ask_depth_1pct",
    ))
    if depth_1pct is None:
        depth_1pct = top_size
    haircut = max(0.0, min(1.0, float(config.get("executable_depth_haircut") or 1.0)))
    executable_depth = max(0.0, max(top_size, depth_1pct) * haircut)
    return {
        "executable_depth_model_version": config.get("executable_depth_model") or "top_of_book_only_v1",
        "executable_depth_mode": "top_of_book_plus_1pct_depth" if depth_1pct > top_size else "top_of_book",
        "top_of_book_size": compact_float(top_size),
        "executable_depth_size": compact_float(executable_depth),
        "executable_depth_1pct_size": compact_float(depth_1pct),
        "frictionless_fill_price": compact_float(best_ask),
    }


def executable_fill_cost(fill_size, best_ask, top_size, config):
    fill_size = max(0.0, float(fill_size or 0.0))
    best_ask = clamp_probability(best_ask) or 0.0
    top_size = max(0.0, float(top_size or 0.0))
    if fill_size <= 0 or best_ask <= 0:
        return {
            "executable_fill_price": None,
            "frictionless_notional_usdc": 0.0,
            "fill_notional_usdc": 0.0,
            "slippage_usdc": 0.0,
            "slippage_price_impact_bps": 0.0,
        }
    top_fill = min(fill_size, top_size)
    depth_fill = max(0.0, fill_size - top_fill)
    impact_bps = max(0.0, float(config.get("executable_depth_slippage_bps") or 0.0))
    depth_price = min(0.999, best_ask * (1.0 + impact_bps / 10000.0))
    notional = (top_fill * best_ask) + (depth_fill * depth_price)
    frictionless = fill_size * best_ask
    avg_price = notional / fill_size if fill_size > 0 else None
    slippage = max(0.0, notional - frictionless)
    realized_impact_bps = ((avg_price / best_ask) - 1.0) * 10000.0 if best_ask > 0 and avg_price is not None else 0.0
    return {
        "executable_fill_price": compact_float(avg_price),
        "frictionless_notional_usdc": compact_float(frictionless),
        "fill_notional_usdc": compact_float(notional),
        "slippage_usdc": compact_float(slippage),
        "slippage_price_impact_bps": compact_float(realized_impact_bps),
    }


def current_high_band_distance(row):
    current = maybe_float(first_present(row, "settlement_current_high", "raw_current_high_bucket", "raw_current_high"))
    kind, value, value_hi = band_key(row)
    if current is None or value is None:
        return None
    value_hi = value if value_hi is None else value_hi
    if kind == "lte":
        return 0.0 if current <= value else round(abs(current - value), 6)
    if kind == "gte":
        return 0.0 if current >= value else round(abs(value - current), 6)
    if value <= current <= value_hi:
        return 0.0
    return round(min(abs(current - value), abs(current - value_hi)), 6)


def sizing_notional_cap(row, config, remaining_budget, base_cap):
    rule = str(config.get("sizing_rule") or "flat_notional")
    base_cap = max(0.0, float(base_cap or 0.0))
    if base_cap <= 0:
        return 0.0, 0.0, "base_cap_zero"
    risk_edge = maybe_float(first_present(row, "risk_adjusted_edge", "edge"))
    confidence = maybe_float(row.get("reliability_confidence")) or 1.0
    price = maybe_float(first_present(row, "best_ask", "clob_best_ask"))
    adjusted_fair = maybe_float(first_present(row, "reliability_adjusted_fair_probability", "fair_probability"))
    if rule == "fractional_kelly":
        if price is None or adjusted_fair is None or price >= 1.0:
            return 0.0, 0.0, "fractional_kelly_missing_inputs"
        full_kelly = max(0.0, (adjusted_fair - price) / max(1e-9, 1.0 - price))
        multiplier = min(1.0, full_kelly * float(config.get("kelly_fraction") or 0.0) * confidence)
        return min(base_cap, float(remaining_budget) * multiplier), compact_float(multiplier), "fractional_kelly"
    if rule == "ev_tiered":
        if risk_edge is None or risk_edge <= 0:
            multiplier = 0.0
            reason = "ev_tier_no_positive_edge"
        elif risk_edge >= float(config.get("ev_tier_high_edge") or 0.0):
            multiplier = float(config.get("ev_tier_high_multiplier") or 1.0)
            reason = "ev_tier_high"
        elif risk_edge >= float(config.get("ev_tier_low_edge") or 0.0):
            multiplier = float(config.get("ev_tier_mid_multiplier") or 0.5)
            reason = "ev_tier_mid"
        else:
            multiplier = float(config.get("ev_tier_low_multiplier") or 0.25)
            reason = "ev_tier_low"
        multiplier = max(0.0, min(1.0, multiplier * confidence))
        return min(base_cap, base_cap * multiplier), compact_float(multiplier), reason
    if rule == "tail_lottery":
        if bool_value(row.get("low_price_tail"), False):
            cap = min(base_cap, float(config.get("tail_lottery_max_order_usdc") or base_cap))
            return cap, compact_float(cap / base_cap if base_cap else 0.0), "tail_lottery_cap"
        multiplier = min(1.0, 0.5 * confidence)
        return min(base_cap, base_cap * multiplier), compact_float(multiplier), "tail_lottery_non_tail"
    return base_cap, 1.0, "flat_notional"


def strategy_event_fields(run_id, now, strategy=None, experiment_id=None):
    strategy = strategy or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at_utc": now.isoformat(),
        "experiment_id": experiment_id or DEFAULT_EXPERIMENT_ID,
        "strategy_id": strategy.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_family": strategy.get("strategy_family") or "raw_edge",
        "assignment_rule": strategy.get("assignment_rule") or "shared_inputs_full_shadow",
        "control_strategy_id": strategy.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_config_hash": strategy.get("strategy_config_hash") or "",
    }


def independent_opinion_key(row):
    return (
        row.get("market_id") or "",
        row.get("event_slug") or "",
        row.get("range_label") or "",
        row.get("bin_kind") or "",
        str(row.get("bin_value") or ""),
        str(row.get("bin_value_hi") or ""),
    )


def apply_taker_budget(
    input_rows,
    existing_rows,
    budget_usdc,
    run_id,
    target_date,
    now,
    config,
    strategy=None,
    experiment_id=None,
):
    strategy = strategy or selected_strategy_specs(None, base_config=config)[0]
    experiment_id = experiment_id or DEFAULT_EXPERIMENT_ID
    budget = float(budget_usdc)
    config_hash = policy_hash(config)
    existing_keys = {row.get("intent_key") for row in existing_rows or [] if row.get("intent_key")}
    seen_keys = set(existing_keys)
    modal_contexts = market_modal_contexts(input_rows)
    # Two-sided taker (item 253): a gated arm (two_sided_enabled) also evaluates
    # the NO side of each band as a synthesized candidate, so an over-priced band
    # the model dislikes can be faded. YES-only arms leave evaluated_rows == input_rows.
    evaluated_rows = list(input_rows)
    if two_sided_enabled(config):
        for input_row in list(input_rows):
            no_row = no_side_input_row(input_row, config)
            if no_row is not None:
                evaluated_rows.append(no_row)
    rows = []
    candidates = []
    for input_row in evaluated_rows:
        row = base_order_row(
            input_row,
            run_id,
            target_date,
            now,
            config,
            config_hash,
            strategy=strategy,
            experiment_id=experiment_id,
        )
        row.update(taker_fee_config(config))
        row.update(executable_depth_state({**input_row, **row}, config))
        edge = maybe_float(row.get("edge"))
        best_ask = maybe_float(row.get("best_ask"))
        if edge is not None and best_ask is not None:
            row["expected_profit_after_friction_per_share"] = compact_float(
                edge - taker_fee_per_share(best_ask, config)
            )
        if row["intent_key"] in seen_keys:
            continue
        seen_keys.add(row["intent_key"])
        row.update(early_hour_guardrail_state({**input_row, **row}, config))
        row.update(enrich_taker_risk_fields({**input_row, **row}, config))
        row.update(modal_context_for_row({**input_row, **row}, modal_contexts, config=config))
        row.update(weak_slot_gate_state({**input_row, **row}, config))
        row.update(warm_tail_guard_state({**input_row, **row}, config))
        row.update(bad_tail_no_go_state({**input_row, **row}, config))
        reason, detail = candidate_skip_reason({**input_row, **row}, config)
        if reason:
            row.update({"reason_code": reason, "reason_detail": detail})
            rows.append(row)
        else:
            candidates.append(row)

    candidates.sort(
        key=lambda row: (
            -(maybe_float(row.get("edge")) or 0.0),
            row.get("market_id") or "",
            row.get("range_label") or "",
        )
    )
    spent = existing_budget_spent(existing_rows)
    positions = existing_position_notional_by_token(existing_rows)
    market_positions = existing_notional_by(existing_rows, lambda item: item.get("market_id") or "unknown")
    cluster_positions = existing_notional_by(
        existing_rows,
        lambda item: item.get("adjacent_bin_cluster_key") or adjacent_bin_cluster_key(item),
    )
    tail_notional = existing_low_price_tail_notional(existing_rows)
    warm_tail_notional = existing_market_centered_warm_tail_notional(existing_rows)
    opinion_counts = existing_opinion_fill_counts(existing_rows)
    same_snapshot_counts = existing_same_snapshot_cluster_counts(existing_rows)
    filled_count = sum(1 for row in existing_rows or [] if str(row.get("order_status") or "").upper() == "FILLED")
    ledger = [{
        **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
        "event": "daily_budget_start",
        "budget_usdc": budget,
        "spent_usdc": spent,
        "remaining_usdc": round(max(0.0, budget - spent), 6),
    }]
    for row in candidates:
        caps = early_hour_effective_caps(row, config)
        token = row.get("clob_token_id") or ""
        price = maybe_float(row.get("best_ask")) or 0.0
        ask_size = maybe_float(row.get("ask_size_at_best")) or 0.0
        executable_depth_size = maybe_float(row.get("executable_depth_size")) or ask_size
        remaining_budget = max(0.0, budget - spent)
        position_before = positions[token]
        position_remaining = max(0.0, float(caps["max_position_per_token_usdc"]) - position_before)
        market_key = row.get("market_id") or "unknown"
        cluster_key = row.get("adjacent_bin_cluster_key") or adjacent_bin_cluster_key(row)
        same_snapshot_key = same_snapshot_adjacent_cluster_key(row)
        opinion_key = independent_opinion_key(row)
        market_before = market_positions[market_key]
        cluster_before = cluster_positions[cluster_key]
        repeated_before = opinion_counts[opinion_key]
        same_snapshot_before = same_snapshot_counts[same_snapshot_key]
        row["budget_usdc"] = round(budget, 6)
        row["budget_spent_before_usdc"] = round(spent, 6)
        row["position_notional_before_usdc"] = round(position_before, 6)
        row["market_notional_before_usdc"] = round(market_before, 6)
        row["adjacent_cluster_notional_before_usdc"] = round(cluster_before, 6)
        row["low_price_tail_notional_before_usdc"] = round(tail_notional, 6)
        row["market_centered_warm_tail_notional_before_usdc"] = round(warm_tail_notional, 6)
        row["repeated_opinion_fill_count_before"] = int(repeated_before)
        row["same_snapshot_adjacent_cluster_fill_count_before"] = int(same_snapshot_before)

        if filled_count >= int(caps["max_daily_positions"]):
            row.update({
                "reason_code": (
                    "NO_TRADE_EARLY_HOUR_DAILY_POSITION_LIMIT"
                    if row.get("early_hour_guardrail_status") == "active"
                    else "NO_TRADE_DAILY_POSITION_LIMIT"
                ),
                "reason_detail": "max early-hour filled positions reached"
                if row.get("early_hour_guardrail_status") == "active"
                else "max daily filled positions reached",
            })
            rows.append(row)
            continue
        max_repeated = int(float(config.get("max_repeated_opinion_fills") or 0))
        if max_repeated > 0 and repeated_before >= max_repeated:
            row.update({
                "reason_code": "NO_TRADE_REPEATED_OPINION_CAP",
                "reason_detail": "strategy repeated-opinion fill cap reached",
            })
            rows.append(row)
            continue
        max_same_snapshot = int(float(config.get("max_same_snapshot_adjacent_cluster_fills") or 0))
        if max_same_snapshot > 0 and same_snapshot_before >= max_same_snapshot:
            row.update({
                "reason_code": "NO_TRADE_SAME_SNAPSHOT_ADJACENT_CLUSTER_CAP",
                "reason_detail": "strategy same-snapshot adjacent warm-tail cluster fill cap reached",
            })
            rows.append(row)
            continue
        market_remaining = remaining_cap(config.get("max_market_notional_usdc"), market_before)
        if market_remaining is not None:
            if market_remaining <= 1e-9:
                row.update({
                    "reason_code": "NO_TRADE_MARKET_EXPOSURE_CAP",
                    "reason_detail": "strategy market-level exposure cap reached",
                })
                rows.append(row)
                continue
            position_remaining = min(position_remaining, market_remaining)
        cluster_remaining = remaining_cap(config.get("max_adjacent_cluster_notional_usdc"), cluster_before)
        if cluster_remaining is not None:
            if cluster_remaining <= 1e-9:
                row.update({
                    "reason_code": "NO_TRADE_ADJACENT_CLUSTER_EXPOSURE_CAP",
                    "reason_detail": "strategy adjacent-bin cluster exposure cap reached",
                })
                rows.append(row)
                continue
            position_remaining = min(position_remaining, cluster_remaining)
        tail_remaining = remaining_cap(config.get("max_low_price_tail_notional_usdc"), tail_notional)
        if bool_value(row.get("low_price_tail"), False) and tail_remaining is not None:
            if tail_remaining <= 1e-9:
                row.update({
                    "reason_code": "NO_TRADE_LOW_PRICE_TAIL_EXPOSURE_CAP",
                    "reason_detail": "strategy low-price tail exposure cap reached",
                })
                rows.append(row)
                continue
            position_remaining = min(position_remaining, tail_remaining)
        warm_tail_remaining = remaining_cap(
            config.get("market_centered_warm_tail_max_notional_usdc"),
            warm_tail_notional,
        )
        if (
            config.get("market_centered_warm_tail_guard_enabled", True)
            and bool_value(row.get("market_centered_warm_tail"), False)
            and warm_tail_remaining is not None
        ):
            if warm_tail_remaining <= 1e-9:
                row.update({
                    "reason_code": "NO_TRADE_MARKET_CENTERED_WARM_TAIL_CAP",
                    "reason_detail": "strategy market-centered warm-tail exposure cap reached",
                })
                rows.append(row)
                continue
            position_remaining = min(position_remaining, warm_tail_remaining)
        if position_remaining <= 1e-9:
            row.update({
                "reason_code": (
                    "NO_TRADE_EARLY_HOUR_POSITION_CAP"
                    if row.get("early_hour_guardrail_status") == "active"
                    else "NO_TRADE_POSITION_CAP"
                ),
                "reason_detail": "per-token early-hour position cap reached"
                if row.get("early_hour_guardrail_status") == "active"
                else "per-token daily position cap reached",
            })
            rows.append(row)
            continue
        base_order_notional = min(float(caps["max_order_usdc"]), position_remaining)
        max_order_notional, sizing_multiplier, sizing_reason = sizing_notional_cap(
            row,
            config,
            remaining_budget,
            base_order_notional,
        )
        trust_gate_multiplier = maybe_float(row.get("current_high_trust_gate_size_multiplier")) or 1.0
        if row.get("current_high_trust_gate_status") == "capped" and trust_gate_multiplier < 1.0:
            max_order_notional *= max(0.0, trust_gate_multiplier)
            sizing_multiplier = compact_float((maybe_float(sizing_multiplier) or 1.0) * trust_gate_multiplier)
            sizing_reason = f"{sizing_reason}+current_high_trust_cap"
        row["sizing_multiplier"] = sizing_multiplier
        row["sizing_limit_reason"] = sizing_reason
        if max_order_notional <= 1e-9:
            row.update({
                "reason_code": "NO_TRADE_SIZING_RULE_ZERO",
                "reason_detail": "strategy sizing rule returned no spend",
                "budget_remaining_usdc": round(remaining_budget, 6),
                "position_notional_after_usdc": round(position_before, 6),
            })
            rows.append(row)
            continue
        fee_per_share = taker_fee_per_share(price, config)
        max_size_by_order = max_order_notional / price if price > 0 else 0.0
        max_size_by_budget = remaining_budget / (price + fee_per_share) if price > 0 else 0.0
        fill_size = min(executable_depth_size, max_size_by_order, max_size_by_budget)
        min_order_size = maybe_float(first_present(row, "min_order_size", "minimum_order_size")) or 0.0
        if fill_size <= 1e-9 or (min_order_size > 0 and fill_size < min_order_size):
            row.update({
                "reason_code": "NO_TRADE_BUDGET_EXHAUSTED",
                "reason_detail": "remaining daily budget cannot fund the minimum taker buy",
                "budget_remaining_usdc": round(remaining_budget, 6),
                "position_notional_after_usdc": round(position_before, 6),
            })
            rows.append(row)
            ledger.append({
                **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
                "event": "budget_exhausted",
                "market_id": row.get("market_id"),
                "event_slug": row.get("event_slug"),
                "clob_token_id": token,
                "remaining_usdc": round(remaining_budget, 6),
            })
            continue
        fill_cost = executable_fill_cost(fill_size, price, ask_size, config)
        notional = maybe_float(fill_cost.get("fill_notional_usdc")) or 0.0
        avg_price = maybe_float(fill_cost.get("executable_fill_price")) or price
        fee = fill_size * taker_fee_per_share(avg_price, config)
        total = notional + fee
        if total > remaining_budget > 0:
            fill_size = fill_size * (remaining_budget / total)
            fill_cost = executable_fill_cost(fill_size, price, ask_size, config)
            notional = maybe_float(fill_cost.get("fill_notional_usdc")) or 0.0
            avg_price = maybe_float(fill_cost.get("executable_fill_price")) or price
            fee = fill_size * taker_fee_per_share(avg_price, config)
            total = notional + fee
        spent_after = spent + total
        position_after = position_before + notional
        slippage = maybe_float(fill_cost.get("slippage_usdc")) or 0.0
        row.update({
            "action": "BUY",
            "order_status": "FILLED",
            "reason_code": "BUY_EDGE",
            "reason_detail": "best ask is cheap versus fair value",
            "requested_notional_usdc": round(max_order_notional, 6),
            "fill_price": round(avg_price, 6),
            "fill_size": round(fill_size, 6),
            "fill_notional_usdc": round(notional, 6),
            "fee_usdc": round(fee, 6),
            "fee_pnl_usdc": round(-fee, 6),
            "frictionless_fill_price": round(price, 6),
            "frictionless_notional_usdc": round(maybe_float(fill_cost.get("frictionless_notional_usdc")) or 0.0, 6),
            "executable_fill_price": round(avg_price, 6),
            "slippage_price_impact_bps": round(maybe_float(fill_cost.get("slippage_price_impact_bps")) or 0.0, 6),
            "slippage_usdc": round(slippage, 6),
            "slippage_pnl_usdc": round(-slippage, 6),
            "total_spent_usdc": round(total, 6),
            "budget_spent_after_usdc": round(spent_after, 6),
            "budget_remaining_usdc": round(max(0.0, budget - spent_after), 6),
            "position_notional_after_usdc": round(position_after, 6),
        })
        rows.append(row)
        spent = spent_after
        positions[token] = position_after
        market_positions[market_key] += notional
        cluster_positions[cluster_key] += notional
        if bool_value(row.get("low_price_tail"), False):
            tail_notional += notional
        if bool_value(row.get("market_centered_warm_tail"), False):
            warm_tail_notional += notional
        opinion_counts[opinion_key] += 1
        same_snapshot_counts[same_snapshot_key] += 1
        filled_count += 1
        ledger.append({
            **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
            "event": "taker_buy_filled",
            "market_id": row.get("market_id"),
            "event_slug": row.get("event_slug"),
            "range_label": row.get("range_label"),
            "clob_token_id": token,
            "fill_price": round(avg_price, 6),
            "fill_size": round(fill_size, 6),
            "fee_usdc": round(fee, 6),
            "slippage_usdc": round(slippage, 6),
            "spent_usdc": round(spent_after, 6),
            "remaining_usdc": round(max(0.0, budget - spent_after), 6),
        })

    for row in rows:
        row.setdefault("budget_usdc", round(budget, 6))
        row.setdefault("budget_spent_before_usdc", round(spent, 6))
        row.setdefault("budget_spent_after_usdc", round(spent, 6))
        row.setdefault("budget_remaining_usdc", round(max(0.0, budget - spent), 6))
        row.setdefault("position_notional_before_usdc", 0.0)
        row.setdefault("position_notional_after_usdc", row.get("position_notional_before_usdc", 0.0))
    ledger.append({
        **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
        "event": "daily_budget_end",
        "budget_usdc": budget,
        "spent_usdc": round(spent, 6),
        "remaining_usdc": round(max(0.0, budget - spent), 6),
    })
    return rows, ledger

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
