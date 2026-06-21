"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_tape_io import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def preflight_summary_for_market(
    spec,
    target_date,
    folder,
    snapshot_rows,
    source_rows,
    book_rows,
    clob_feature_rows,
    current_high_assessment=None,
):
    latest_capture = parse_time(snapshot_rows[0].get("captured_at_utc")) if snapshot_rows else None
    token_rows = read_csv_rows(Path(folder) / "clob_tokens.csv", attach_diagnostics=True)
    token_discovery = clob_token_discovery_health(token_rows)
    status = "PASS"
    reasons = []
    gates = []

    def add_gate(name, ok, severity, detail):
        gates.append({"name": name, "ok": bool(ok), "severity": severity, "detail": detail})
        return bool(ok)

    if not snapshot_rows:
        status = "BLOCK"
        reasons.append("missing current snapshot/model rows")
    add_gate("snapshot_model_rows", bool(snapshot_rows), "missing", "missing current snapshot/model rows")
    if not token_discovery.get("ok"):
        status = "BLOCK"
        reasons.append(token_discovery.get("reason"))
    add_gate("clob_discovery", token_discovery.get("ok"), "missing", token_discovery.get("reason"))
    if not book_rows:
        status = "BLOCK"
        reasons.append("missing current CLOB book rows")
    add_gate("clob_books", bool(book_rows), "missing", "missing current CLOB book rows")
    if not clob_feature_rows:
        status = "BLOCK"
        reasons.append("missing band-level CLOB feature rows")
    add_gate("clob_features", bool(clob_feature_rows), "missing", "missing band-level CLOB feature rows")
    if source_rows and not source_status_is_current(source_rows):
        status = "STALE" if status == "PASS" else status
        reasons.append("no fresh source-status row for latest snapshot")
        add_gate("source_status_fresh", False, "stale", "no fresh source-status row for latest snapshot")
    elif not source_rows:
        status = "STALE" if status == "PASS" else status
        reasons.append("missing current source-status rows")
        add_gate("source_status_rows", False, "stale", "missing current source-status rows")
    else:
        add_gate("source_status_fresh", True, "stale", "source status fresh")
    return {
        "market_id": spec.id,
        "city": spec.city_label,
        "target_date": ensure_date(target_date).isoformat(),
        "event_slug": config_for_date(target_date, spec.id).event_slug,
        "folder": str(folder),
        "status": status,
        "reasons": reasons or ["ok"],
        "gates": gates,
        "first_failing_gate": first_failed_gate({"gates": gates}),
        "snapshot_rows": len(snapshot_rows),
        "latest_snapshot_id": snapshot_rows[0].get("snapshot_id") if snapshot_rows else None,
        "latest_capture_utc": latest_capture.isoformat() if latest_capture else None,
        "source_status_rows": len(source_rows),
        "source_status_fresh": source_status_is_current(source_rows),
        "clob_token_discovery": token_discovery,
        "book_rows": len(book_rows),
        "clob_feature_rows": len(clob_feature_rows),
        "current_high_assessment": current_high_assessment or {},
    }


def label_numbers(row):
    import re

    return [int(value) for value in re.findall(r"-?\d+", str(row.get("range_label") or ""))]


def band_key(row):
    kind = str(row.get("bin_kind") or row.get("winning_band_kind") or "").strip().lower()
    value = row.get("bin_value")
    if value in (None, ""):
        value = row.get("bin_value_c") or row.get("winning_band_value")
    value_hi = row.get("bin_value_hi") or row.get("winning_band_value_hi")
    value = int(float(value)) if maybe_float(value) is not None else None
    value_hi = int(float(value_hi)) if maybe_float(value_hi) is not None else None
    nums = label_numbers(row)
    if value is None and nums:
        value = nums[0]
    if value_hi is None and nums:
        value_hi = nums[-1]
    if value_hi is None:
        value_hi = value
    if not kind:
        text = str(row.get("range_label") or "").lower()
        if "above" in text or "higher" in text:
            kind = "gte"
        elif "below" in text or "under" in text:
            kind = "lte"
        else:
            kind = "eq"
    return kind, value, value_hi


def low_price_tail_flag(row, config):
    best_ask = maybe_float(first_present(row, "best_ask", "clob_best_ask"))
    threshold = float(config.get("tail_price_threshold") or 0.0)
    return bool(threshold > 0 and best_ask is not None and best_ask <= threshold)


def tail_risk_bucket(row, config):
    if low_price_tail_flag(row, config):
        return "low_price_tail"
    distance = current_high_band_distance(row)
    if distance is not None and distance <= 1:
        return "current_high_or_adjacent"
    return "regular"


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


def adjacent_bin_cluster_key(row):
    kind, value, value_hi = band_key(row)
    market_id = row.get("market_id") or "unknown"
    event_slug = row.get("event_slug") or "unknown"
    if value is None:
        return f"{market_id}:{event_slug}:missing"
    if kind in {"lte", "gte"}:
        return f"{market_id}:{event_slug}:{kind}:{value}"
    cluster_floor = int(value) - (int(value) % 3)
    return f"{market_id}:{event_slug}:eq:{cluster_floor}-{cluster_floor + 2}"


def reliability_context_key(row):
    local, _zone_name = market_local_time(row)
    hour = maybe_float(row.get("capture_hour_local"))
    if hour is None and local is not None:
        hour = local.hour
    kind, value, value_hi = band_key(row)
    source_state = str(row.get("source_freshness_state") or "unknown").strip().lower() or "unknown"
    trust_state = "trusted_current_high" if bool_value(row.get("current_high_trusted"), True) else "untrusted_current_high"
    model_variant = row.get("model_version") or row.get("policy_version") or "unknown_model"
    return "|".join([
        row.get("market_id") or "unknown_market",
        str(model_variant),
        f"hour:{int(hour) if hour is not None else 'missing'}",
        f"band:{kind}:{value}:{value_hi}",
        f"source:{source_state}",
        trust_state,
    ])


def reliability_confidence(row, config):
    confidence = 1.0
    reasons = []
    source_state = str(row.get("source_freshness_state") or "").strip().lower()
    if source_state and source_state not in {"all_fresh", "fresh"}:
        confidence *= 0.80
        reasons.append(f"source_state:{source_state}")
    if not bool_value(row.get("current_high_trusted"), True):
        confidence *= 0.70
        reasons.append("untrusted_current_high")
    model_age = maybe_float(row.get("model_age_seconds"))
    if model_age is not None and model_age > 300:
        confidence *= 0.85
        reasons.append("model_age_gt_300s")
    book_age = maybe_float(row.get("book_age_seconds"))
    if book_age is not None and book_age > 60:
        confidence *= 0.90
        reasons.append("book_age_gt_60s")
    if low_price_tail_flag(row, config):
        confidence *= 0.85
        reasons.append("low_price_tail")
    floor = float(config.get("calibration_confidence_floor", 0.15) or 0.15)
    confidence = max(floor, min(1.0, confidence))
    return confidence, reasons or ["full_confidence"]


def clob_continuity_state(row, config):
    best_bid = maybe_float(first_present(row, "best_bid", "clob_best_bid", "gamma_best_bid"))
    best_ask = maybe_float(first_present(row, "best_ask", "clob_best_ask", "gamma_best_ask"))
    book_age = maybe_float(row.get("book_age_seconds"))
    if best_ask is None:
        return "missing", "missing best ask"
    if best_bid is not None and best_bid > best_ask:
        return "broken", "best bid is above best ask"
    if book_age is None:
        return "missing", "missing book age"
    if book_age > float(config.get("max_book_age_seconds") or DEFAULT_CONFIG["max_book_age_seconds"]):
        return "stale", "book age exceeds strategy continuity window"
    return "pass", "book is continuous enough for sizing"


def mark_sanity_state(row, config):
    mark = maybe_float(first_present(row, "mark_pnl_usdc", "net_pnl_usdc"))
    spent = maybe_float(first_present(row, "total_spent_usdc", "fill_notional_usdc"))
    if mark is None or spent in (None, 0):
        return "not_available", "no mark P&L available"
    ratio = abs(mark) / max(1e-9, abs(spent))
    max_ratio = float(config.get("max_mark_sanity_ratio") or DEFAULT_CONFIG["max_mark_sanity_ratio"])
    if ratio > max_ratio:
        return "outlier", f"mark P&L/spend ratio {ratio:.3f} exceeds {max_ratio:.3f}"
    return "pass", "mark P&L is within sanity ratio"


def enrich_taker_risk_fields(row, config):
    out = dict(row)
    fair = clamp_probability(out.get("fair_probability"))
    best_ask = clamp_probability(first_present(out, "best_ask", "clob_best_ask"))
    edge = maybe_float(out.get("edge"))
    if edge is None and fair is not None and best_ask is not None:
        edge = fair - best_ask
    confidence, reasons = reliability_confidence(out, config)
    adjusted = None
    risk_edge = None
    if fair is not None and best_ask is not None and edge is not None:
        adjusted = clamp_probability(best_ask + (edge * confidence))
        risk_edge = adjusted - best_ask if adjusted is not None else None
    continuity_status, continuity_reason = clob_continuity_state(out, config)
    mark_status, mark_reason = mark_sanity_state(out, config)
    out.update({
        "reliability_context_key": reliability_context_key(out),
        "reliability_confidence": compact_float(confidence),
        "reliability_adjusted_fair_probability": compact_float(adjusted),
        "reliability_adjustment": compact_float((adjusted - fair) if adjusted is not None and fair is not None else None),
        "reliability_reason": ",".join(reasons),
        "risk_adjusted_edge": compact_float(risk_edge),
        "risk_adjusted_expected_profit_per_share": compact_float(risk_edge),
        "sizing_rule": config.get("sizing_rule") or "flat_notional",
        "sizing_multiplier": 1.0,
        "sizing_limit_reason": "base",
        "low_price_tail": low_price_tail_flag(out, config),
        "tail_risk_bucket": tail_risk_bucket(out, config),
        "current_high_band_distance": compact_float(current_high_band_distance(out)),
        "adjacent_bin_cluster_key": adjacent_bin_cluster_key(out),
        "clob_continuity_status": continuity_status,
        "clob_continuity_reason": continuity_reason,
        "mark_sanity_status": mark_status,
        "mark_sanity_reason": mark_reason,
    })
    return out


def base_order_row(input_row, run_id, target_date, now, config, config_hash, strategy=None, experiment_id=None):
    strategy = strategy or {}
    experiment_id = experiment_id or DEFAULT_EXPERIMENT_ID
    kind, value, value_hi = snapshot_band_key(input_row)
    token = input_row.get("clob_token_id") or input_row.get("clob_yes_token_id") or ""
    fair = clamp_probability(input_row.get("fair_probability"))
    best_bid = clamp_probability(first_present(input_row, "clob_best_bid", "best_bid", "gamma_best_bid"))
    best_ask = clamp_probability(first_present(input_row, "clob_best_ask", "best_ask", "gamma_best_ask"))
    mid = market_mid(input_row)
    edge = fair - best_ask if fair is not None and best_ask is not None else None
    ask_size = maybe_float(first_present(input_row, "ask_size_at_best", "clob_ask_size_at_best", "ask_depth_1pct"))
    if ask_size is None:
        ask_size = 0.0
    generated = now.isoformat()
    intent_payload = {
        "experiment_id": experiment_id,
        "strategy_id": strategy.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "market_id": input_row.get("market_id") or "",
        "event_slug": input_row.get("event_slug") or "",
        "snapshot_id": input_row.get("snapshot_id") or "",
        "captured_at_utc": input_row.get("captured_at_utc") or "",
        "clob_token_id": token,
        "range_label": input_row.get("range_label") or "",
        "fair_probability": compact_float(fair),
        "best_ask": compact_float(best_ask),
    }
    intent = order_key(intent_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": config_hash,
        "experiment_id": experiment_id,
        "strategy_id": strategy.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_family": strategy.get("strategy_family") or "raw_edge",
        "assignment_rule": strategy.get("assignment_rule") or "shared_inputs_full_shadow",
        "control_strategy_id": strategy.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_config_hash": strategy.get("strategy_config_hash") or config_hash,
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "generated_at_utc": generated,
        "intent_key": intent,
        "order_id": f"taker_{intent}",
        "market_id": input_row.get("market_id") or "",
        "event_slug": input_row.get("event_slug") or "",
        "snapshot_id": input_row.get("snapshot_id") or "",
        "captured_at_utc": input_row.get("captured_at_utc") or "",
        "range_label": input_row.get("range_label") or "",
        "bin_kind": input_row.get("bin_kind") or kind or "",
        "bin_value": input_row.get("bin_value") or input_row.get("bin_value_c") or value or "",
        "bin_value_hi": input_row.get("bin_value_hi") or value_hi or "",
        "condition_id": input_row.get("condition_id") or "",
        "clob_token_id": token,
        "side": "YES_BUY",
        "action": "NO_TRADE",
        "order_status": "SKIPPED",
        "reason_code": "",
        "reason_detail": "",
        "fair_probability": compact_float(fair),
        "best_bid": compact_float(best_bid),
        "best_ask": compact_float(best_ask),
        "market_mid": compact_float(mid),
        "edge": compact_float(edge),
        "expected_profit_per_share": compact_float(edge),
        "reliability_context_key": "",
        "reliability_confidence": None,
        "reliability_adjusted_fair_probability": None,
        "reliability_adjustment": None,
        "reliability_reason": "",
        "risk_adjusted_edge": None,
        "risk_adjusted_expected_profit_per_share": None,
        "sizing_rule": config.get("sizing_rule") or "flat_notional",
        "sizing_multiplier": 1.0,
        "sizing_limit_reason": "base",
        "low_price_tail": False,
        "tail_risk_bucket": "",
        "current_high_band_distance": None,
        "adjacent_bin_cluster_key": "",
        "market_notional_before_usdc": 0.0,
        "adjacent_cluster_notional_before_usdc": 0.0,
        "low_price_tail_notional_before_usdc": 0.0,
        "repeated_opinion_fill_count_before": 0,
        "clob_continuity_status": "",
        "clob_continuity_reason": "",
        "mark_sanity_status": "",
        "mark_sanity_reason": "",
        "ask_size_at_best": compact_float(ask_size),
        "min_order_size": compact_float(first_present(input_row, "min_order_size", "minimum_order_size")),
        "requested_notional_usdc": 0.0,
        "fill_price": None,
        "fill_size": 0.0,
        "fill_notional_usdc": 0.0,
        "fee_usdc": 0.0,
        "total_spent_usdc": 0.0,
        "book_age_seconds": compact_float(book_age_seconds(input_row, now)),
        "model_age_seconds": compact_float(model_age_seconds(input_row, now)),
        "raw_current_high": compact_float(input_row.get("raw_current_high")),
        "raw_current_high_bucket": compact_float(input_row.get("raw_current_high_bucket")),
        "settlement_current_high": compact_float(input_row.get("settlement_current_high")),
        "high_source": input_row.get("high_source") or "",
        "revision_state": input_row.get("revision_state") or "",
        "settlement_bin_key": input_row.get("settlement_bin_key") or "",
        "raw_current_high_bin_key": input_row.get("raw_current_high_bin_key") or "",
        "probability_on_raw_current_high": compact_float(input_row.get("probability_on_raw_current_high")),
        "probability_on_settlement_current_high": compact_float(
            input_row.get("probability_on_settlement_current_high")
        ),
        "current_max_state": input_row.get("current_max_state") or "",
        "current_max_disposition": input_row.get("current_max_disposition") or "",
        "current_max_gap_to_wu_history": compact_float(input_row.get("current_max_gap_to_wu_history")),
        "current_max_gap_to_current_temp": compact_float(input_row.get("current_max_gap_to_current_temp")),
        "current_high_trusted": bool_value(input_row.get("current_high_trusted"), True),
        "current_high_guard_reason": input_row.get("current_high_guard_reason") or "",
        "source_fresh": bool_value(input_row.get("source_fresh"), False),
        "source_freshness_state": input_row.get("source_freshness_state") or "",
        "capture_hour_local": None,
        "capture_timezone": "",
        "early_hour_guardrail_status": "inactive",
        "early_hour_guardrail_reason": "",
        "early_hour_guardrail_min_edge": None,
        "early_hour_guardrail_max_order_usdc": None,
        "early_hour_guardrail_max_position_per_token_usdc": None,
        "early_hour_guardrail_max_daily_positions": None,
    }


def candidate_skip_reason(row, config):
    fair = maybe_float(row.get("fair_probability"))
    best_ask = maybe_float(row.get("best_ask"))
    ask_size = maybe_float(row.get("ask_size_at_best")) or 0.0
    edge = maybe_float(row.get("edge"))
    book_age = maybe_float(row.get("book_age_seconds"))
    model_age = maybe_float(row.get("model_age_seconds"))
    min_price = float(config["min_price"])
    max_price = float(config["max_price"])
    if config.get("require_active_market") and not boolish_active(first_present(row, "market_status", "active")):
        return "NO_TRADE_MARKET_INACTIVE", "market is not active"
    if config.get("require_source_fresh") and not bool_value(row.get("source_fresh"), False):
        return "NO_TRADE_SOURCE_STALE", "source freshness gate is false"
    if fair is None:
        return "NO_TRADE_MISSING_FAIR", "missing fair probability"
    if not row.get("clob_token_id"):
        return "NO_TRADE_MISSING_TOKEN", "missing CLOB token id"
    if best_ask is None:
        return "NO_TRADE_MISSING_ASK", "missing best ask"
    if best_ask < min_price or best_ask > max_price:
        return "NO_TRADE_PRICE_OUT_OF_RANGE", "best ask is outside allowed price bounds"
    if ask_size <= 0:
        return "NO_TRADE_NO_ASK_SIZE", "missing or zero ask size at best"
    min_ask_size = float(config.get("min_ask_size_at_best") or 0.0)
    if min_ask_size > 0 and ask_size < min_ask_size:
        return "NO_TRADE_INSUFFICIENT_ASK_DEPTH", "ask size at best is below strategy liquidity floor"
    if book_age is None or book_age > float(config["max_book_age_seconds"]):
        return "NO_TRADE_STALE_BOOK", "book age exceeds latency budget"
    if model_age is None or model_age > float(config["max_model_age_seconds"]):
        return "NO_TRADE_STALE_MODEL", "model age exceeds latency budget"
    min_capture_hour = maybe_float(config.get("min_capture_hour_local"))
    if min_capture_hour is not None and min_capture_hour >= 0:
        capture_hour = maybe_float(row.get("capture_hour_local"))
        if capture_hour is None:
            local, _zone_name = market_local_time(row)
            capture_hour = local.hour if local else None
        if capture_hour is None or capture_hour < min_capture_hour:
            return "NO_TRADE_TOO_EARLY_LOCAL_HOUR", "local capture hour is before strategy timing window"
    if config.get("require_current_high_trusted") and not bool_value(row.get("current_high_trusted"), False):
        return "NO_TRADE_CURRENT_HIGH_NOT_TRUSTED", "current-high state is not trusted enough for this strategy"
    if config.get("require_clob_continuity") and row.get("clob_continuity_status") != "pass":
        return "NO_TRADE_CLOB_CONTINUITY", row.get("clob_continuity_reason") or "CLOB continuity gate failed"
    max_current_high_distance = maybe_float(config.get("max_current_high_band_distance"))
    if max_current_high_distance is not None and max_current_high_distance < 9999.0:
        distance = current_high_band_distance(row)
        if distance is None or distance > max_current_high_distance:
            return (
                "NO_TRADE_CURRENT_HIGH_DISTANCE",
                "band is outside the strategy current-high distance window",
            )
    if row.get("early_hour_guardrail_status") == "blocked":
        reason = str(row.get("early_hour_guardrail_reason") or "")
        if reason.startswith("guarded_current_high"):
            return (
                "NO_TRADE_EARLY_HOUR_CURRENT_HIGH_GUARDED",
                "early-hour current high is not validated as same-day evidence",
            )
        if reason.startswith("source_state"):
            return "NO_TRADE_EARLY_HOUR_SOURCE_STATE", "early-hour source agreement is too weak"
        return "NO_TRADE_EARLY_HOUR_EDGE_TOO_SMALL", "edge does not clear early-hour minimum"
    if edge is None or edge < float(config["min_edge"]):
        return "NO_TRADE_EDGE_TOO_SMALL", "best ask is not cheap enough versus fair value"
    if config.get("risk_adjusted_entry_enabled"):
        risk_edge = maybe_float(row.get("risk_adjusted_edge"))
        min_risk_edge = float(config.get("min_risk_adjusted_edge") or 0.0)
        if risk_edge is None or risk_edge < min_risk_edge:
            return "NO_TRADE_RISK_ADJUSTED_EDGE_TOO_SMALL", "reliability-adjusted edge is too small"
    return None, None

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
