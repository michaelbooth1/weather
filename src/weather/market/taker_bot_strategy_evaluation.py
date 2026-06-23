"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_tape_io import *  # noqa: F403
from weather.market.snapshot_cadence_quality import snapshot_cadence_quality

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


def band_key_text(row):
    kind, value, value_hi = band_key(row)
    if value is None:
        return ""
    if kind == "eq" and value_hi not in (None, value):
        return f"{kind}:{value}-{value_hi}"
    return f"{kind}:{value}"


def warm_distance_from_modal(row, modal):
    if not modal:
        return None
    kind, value, value_hi = band_key(row)
    modal_hi = maybe_float(modal.get("market_modal_band_hi"))
    if value is None or modal_hi is None:
        return None
    if kind == "lte":
        return 0.0
    if kind == "gte":
        return round(max(0.0, float(value) - modal_hi), 6)
    return round(max(0.0, float(value) - modal_hi), 6)


def market_modal_contexts(input_rows):
    contexts = {}
    for row in input_rows or []:
        key = (
            row.get("market_id") or "",
            row.get("event_slug") or "",
            row.get("snapshot_id") or "",
        )
        probability = maybe_float(first_present(row, "market_mid", "market_yes", "clob_midpoint"))
        if probability is None:
            continue
        kind, value, value_hi = band_key(row)
        if value is None:
            continue
        current = contexts.get(key)
        if current is None or probability > float(current.get("market_modal_probability") or -1.0):
            contexts[key] = {
                "market_modal_band_key": band_key_text(row),
                "market_modal_probability": compact_float(probability),
                "market_modal_band_kind": kind,
                "market_modal_band_value": value,
                "market_modal_band_hi": value if value_hi is None else value_hi,
            }
    return contexts


def modal_context_for_row(row, modal_contexts, config=None):
    key = (
        row.get("market_id") or "",
        row.get("event_slug") or "",
        row.get("snapshot_id") or "",
    )
    modal = (modal_contexts or {}).get(key) or {}
    distance = warm_distance_from_modal(row, modal)
    min_distance = float((config or {}).get("market_centered_warm_tail_min_distance") or 1.0)
    return {
        "market_modal_band_key": modal.get("market_modal_band_key") or "",
        "market_modal_probability": modal.get("market_modal_probability"),
        "market_modal_band_distance": compact_float(distance),
        "market_centered_warm_tail": bool(
            distance is not None
            and distance >= min_distance
        ),
    }


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


def same_snapshot_adjacent_cluster_key(row):
    return f"{row.get('snapshot_id') or 'missing'}:{adjacent_bin_cluster_key(row)}"


def reliability_context_key(row):
    local, _zone_name = market_local_time(row)
    hour = maybe_float(row.get("capture_hour_local"))
    if hour is None and local is not None:
        hour = local.hour
    kind, value, value_hi = band_key(row)
    source_state = str(row.get("source_freshness_state") or "unknown").strip().lower() or "unknown"
    trust_state = "trusted_current_high" if bool_value(row.get("current_high_trusted"), True) else "untrusted_current_high"
    cadence_state = str(row.get("snapshot_cadence_quality_state") or "clean").strip().lower() or "clean"
    model_variant = row.get("model_version") or row.get("policy_version") or "unknown_model"
    return "|".join([
        row.get("market_id") or "unknown_market",
        str(model_variant),
        f"hour:{int(hour) if hour is not None else 'missing'}",
        f"band:{kind}:{value}:{value_hi}",
        f"source:{source_state}",
        f"cadence:{cadence_state}",
        trust_state,
    ])


def reliability_confidence(row, config):
    confidence = 1.0
    reasons = []
    source_state = str(row.get("source_freshness_state") or "").strip().lower()
    if source_state and source_state not in {"all_fresh", "fresh"}:
        confidence *= 0.80
        reasons.append(f"source_state:{source_state}")
    cadence = snapshot_cadence_quality(row, config=config)
    cadence_multiplier = maybe_float(cadence.get("snapshot_cadence_confidence_multiplier")) or 1.0
    if cadence.get("snapshot_cadence_quality_state") not in {"clean", "triggered", "disabled"} or cadence_multiplier < 1.0:
        confidence *= cadence_multiplier
        reasons.append(f"cadence_quality:{cadence.get('snapshot_cadence_quality_state')}")
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


def current_high_trust_gate_state(row, config):
    state = {
        "current_high_trust_gate_status": "clear",
        "current_high_trust_gate_action": "allow",
        "current_high_trust_gate_reason": "",
        "current_high_trust_gate_aggressive": False,
        "current_high_trust_gate_size_multiplier": 1.0,
    }
    if not config.get("current_high_trust_gate_enabled", True):
        state.update({
            "current_high_trust_gate_status": "disabled",
            "current_high_trust_gate_reason": "current-high trust gate disabled",
        })
        return state
    trust_present = row.get("current_high_trust_state_present")
    if trust_present in (None, ""):
        trust_present = "current_high_trusted" in row and row.get("current_high_trusted") not in (None, "")
    if config.get("current_high_trust_missing_blocks", True) and not bool_value(trust_present, False):
        state.update({
            "current_high_trust_gate_status": "blocked",
            "current_high_trust_gate_action": "deny_missing_trust_state",
            "current_high_trust_gate_reason": "missing_current_high_trust_state",
            "current_high_trust_gate_aggressive": True,
        })
        return state
    if bool_value(row.get("current_high_trusted"), True):
        state["current_high_trust_gate_reason"] = "current-high state trusted"
        return state

    local, _zone_name = market_local_time(row)
    hour = maybe_float(row.get("capture_hour_local"))
    if hour is None and local is not None:
        hour = local.hour
    start_hour = maybe_float(config.get("current_high_trust_gate_start_hour_local"))
    if start_hour is None:
        start_hour = 0.0
    late_window = hour is None or hour >= start_hour
    edge = maybe_float(row.get("edge"))
    best_ask = maybe_float(first_present(row, "best_ask", "clob_best_ask"))
    distance = current_high_band_distance(row)
    aggressive = any([
        low_price_tail_flag(row, config),
        edge is not None and edge >= float(config.get("current_high_trust_gate_aggressive_min_edge") or 0.08),
        best_ask is not None and best_ask <= float(config.get("current_high_trust_gate_aggressive_max_price") or 0.20),
        distance is not None and distance <= float(config.get("current_high_trust_gate_lockin_distance") or 1.0),
    ])
    reason_bits = [
        "untrusted_current_high",
        f"hour:{int(hour) if hour is not None else 'missing'}",
        f"current_max_state:{row.get('current_max_state') or 'unknown'}",
    ]
    if row.get("current_high_guard_reason"):
        reason_bits.append(f"guard:{row.get('current_high_guard_reason')}")
    state["current_high_trust_gate_aggressive"] = bool(aggressive)
    state["current_high_trust_gate_reason"] = ";".join(reason_bits)
    gate_action = str(config.get("current_high_trust_gate_action") or "deny_aggressive")
    strategy_status = str(row.get("strategy_status") or "").strip().lower()
    diagnostic_only = strategy_status in {"shadow", "diagnostic"} and gate_action != "deny_aggressive"
    if aggressive and not diagnostic_only:
        state["current_high_trust_gate_status"] = "blocked"
        state["current_high_trust_gate_action"] = "deny_aggressive"
        return state
    if not late_window:
        state["current_high_trust_gate_status"] = "observe"
        state["current_high_trust_gate_action"] = "allow_pre_late_window"
        return state
    state["current_high_trust_gate_status"] = "capped"
    state["current_high_trust_gate_action"] = "cap_size"
    state["current_high_trust_gate_size_multiplier"] = max(
        0.0,
        min(1.0, float(config.get("current_high_trust_gate_size_multiplier") or 0.25)),
    )
    return state


def current_high_trust_config_warnings(config):
    config = config or {}
    start_hour = maybe_float(config.get("current_high_trust_gate_start_hour_local"))
    if start_hour is None or start_hour <= 0:
        return []
    return [{
        "code": "CURRENT_HIGH_TRUST_GATE_DELAYED_START",
        "severity": "WARN",
        "configured_start_hour_local": start_hour,
        "effective_aggressive_start_hour_local": 0.0,
        "detail": (
            "current_high_trust_gate_start_hour_local is greater than 0; "
            "aggressive untrusted-current-high taker rows still deny from local hour 0"
        ),
    }]


def strategy_risk_gate_allowlisted(row, config, *, family_key, id_key):
    strategy_id = str(row.get("strategy_id") or "").strip().lower()
    family = str(row.get("strategy_family") or "").strip().lower()
    allowed_families = csv_tokens(config.get(family_key))
    allowed_ids = csv_tokens(config.get(id_key))
    return (
        "*" in allowed_families
        or "*" in allowed_ids
        or (family and family in allowed_families)
        or (strategy_id and strategy_id in allowed_ids)
    )


def strategy_family_blocked(row, config, key):
    family = str(row.get("strategy_family") or "").strip().lower()
    blocked = csv_tokens(config.get(key) or "*")
    return "*" in blocked or (family and family in blocked)


def snapshot_cadence_state_present(row):
    cadence_keys = (
        "snapshot_cadence",
        "snapshot_cadence_quality_state",
        "snapshot_cadence_permission",
        "snapshot_cadence_gap_count",
        "snapshot_cadence_max_gap_seconds",
        "snapshot_cadence_last_model_age_seconds",
        "cadence",
        "cadence_quality_state",
        "cadence_permission",
    )
    return any((row or {}).get(key) not in (None, "") for key in cadence_keys)


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
    cadence = snapshot_cadence_quality(out, config=config)
    cadence_present = out.get("snapshot_cadence_state_present")
    if cadence_present in (None, ""):
        cadence_present = snapshot_cadence_state_present(out)
    cadence_missing_allowed = strategy_risk_gate_allowlisted(
        out,
        config,
        family_key="snapshot_cadence_missing_allow_strategy_families",
        id_key="snapshot_cadence_missing_allow_strategy_ids",
    )
    if (
        bool_value(config.get("snapshot_cadence_quality_enabled"), True)
        and bool_value(config.get("snapshot_cadence_missing_blocks"), True)
        and not bool_value(cadence_present, False)
        and not cadence_missing_allowed
    ):
        cadence.update({
            "snapshot_cadence": "missing",
            "snapshot_cadence_quality_state": "missing",
            "snapshot_cadence_permission": "deny",
            "snapshot_cadence_reason": "missing snapshot cadence quality state",
        })
    out.update(cadence)
    fair = clamp_probability(out.get("fair_probability"))
    best_ask = clamp_probability(first_present(out, "best_ask", "clob_best_ask"))
    edge = maybe_float(out.get("edge"))
    if edge is None and fair is not None and best_ask is not None:
        edge = fair - best_ask
    confidence, reasons = reliability_confidence(out, config)
    trust_gate = current_high_trust_gate_state(out, config)
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
        **trust_gate,
        "current_high_band_distance": compact_float(current_high_band_distance(out)),
        "adjacent_bin_cluster_key": adjacent_bin_cluster_key(out),
        "clob_continuity_status": continuity_status,
        "clob_continuity_reason": continuity_reason,
        "mark_sanity_status": mark_status,
        "mark_sanity_reason": mark_reason,
        "snapshot_cadence_state_present": bool_value(cadence_present, False),
    })
    return out


def weak_slot_gate_state(row, config):
    state = {
        "weak_slot_gate_status": "inactive",
        "weak_slot_gate_reason": "",
        "weak_slot_gate_source": "",
    }
    if not config.get("weak_slot_guard_enabled", True):
        return state
    local, _zone_name = market_local_time(row)
    if local is None:
        return state
    slot = local.hour * 60 + ((local.minute // 10) * 10)
    configured_minutes = set(config.get("_weak_slot_minutes") or [])
    configured_hours = csv_number_set(config.get("weak_slot_guard_hours"))
    in_slot = slot in configured_minutes
    in_hour = local.hour in configured_hours
    if not in_slot and not in_hour:
        return state
    ten_status = str(config.get("_weak_slot_gate_status") or "CONFIG").upper()
    hourly_status = str(config.get("_hourly_gate_status") or "CONFIG").upper()
    block_statuses = csv_tokens(config.get("weak_slot_guard_block_statuses") or "BLOCK")
    blocked = (
        ten_status.lower() in block_statuses
        or hourly_status.lower() in block_statuses
        or not configured_minutes
    )
    state["weak_slot_gate_status"] = "blocked" if blocked else "active"
    source = config.get("_weak_slot_gate_source") or "config"
    state["weak_slot_gate_source"] = source
    reason_bits = [f"slot:{local.hour:02d}:{(local.minute // 10) * 10:02d}"]
    if in_slot:
        reason_bits.append(f"ten_minute_gate:{ten_status}")
    if in_hour and not in_slot:
        reason_bits.append("configured_weak_hour")
    if hourly_status not in {"", "CONFIG"}:
        reason_bits.append(f"hourly_gate:{hourly_status}")
    blocker = config.get("_weak_slot_gate_first_blocker") or config.get("_hourly_gate_first_blocker")
    if blocker:
        reason_bits.append(f"blocker:{blocker}")
    state["weak_slot_gate_reason"] = ";".join(reason_bits)
    return state


def warm_tail_guard_state(row, config):
    state = {
        "warm_tail_guard_status": "inactive",
        "warm_tail_guard_reason": "",
    }
    if not config.get("market_centered_warm_tail_guard_enabled", True):
        return state
    if not bool_value(row.get("market_centered_warm_tail"), False):
        return state
    state["warm_tail_guard_status"] = "active"
    family = str(row.get("strategy_family") or "").strip().lower()
    status = str(row.get("strategy_status") or "").strip().lower()
    allowed = strategy_risk_gate_allowlisted(
        row,
        config,
        family_key="market_centered_warm_tail_allow_strategy_families",
        id_key="market_centered_warm_tail_allow_strategy_ids",
    )
    allowed_statuses = {"candidate", "promoted", "active"}
    reasons = [
        f"distance:{row.get('market_modal_band_distance')}",
        f"market_modal:{row.get('market_modal_band_key') or 'missing'}",
    ]
    if not allowed and strategy_family_blocked(row, config, "market_centered_warm_tail_block_strategy_families"):
        state.update({
            "warm_tail_guard_status": "blocked",
            "warm_tail_guard_reason": ";".join([*reasons, f"strategy_family:{family or 'missing'}"]),
        })
        return state
    if status not in allowed_statuses:
        state.update({
            "warm_tail_guard_status": "blocked",
            "warm_tail_guard_reason": ";".join([*reasons, f"strategy_status:{status or 'missing'}"]),
        })
        return state
    if config.get("market_centered_warm_tail_require_clob_continuity", True) and row.get("clob_continuity_status") != "pass":
        state.update({
            "warm_tail_guard_status": "blocked",
            "warm_tail_guard_reason": ";".join([*reasons, "clob_continuity_not_pass"]),
        })
        return state
    if config.get("market_centered_warm_tail_require_risk_adjusted", True):
        risk_edge = maybe_float(row.get("risk_adjusted_edge"))
        threshold = float(config.get("market_centered_warm_tail_min_risk_adjusted_edge") or 0.0)
        if risk_edge is None or risk_edge < threshold:
            state.update({
                "warm_tail_guard_status": "blocked",
                "warm_tail_guard_reason": ";".join([*reasons, f"risk_edge_below:{threshold}"]),
            })
            return state
    state["warm_tail_guard_reason"] = ";".join(reasons)
    return state


def bad_tail_no_go_state(row, config):
    state = {
        "bad_tail_no_go_status": "inactive",
        "bad_tail_no_go_action": "allow",
        "bad_tail_no_go_slice_id": "",
        "bad_tail_no_go_reason": "",
    }
    if not bool_value(config.get("bad_tail_no_go_enabled"), True):
        state.update({
            "bad_tail_no_go_status": "disabled",
            "bad_tail_no_go_reason": "bad-tail no-go registry disabled",
        })
        return state
    if not strategy_family_blocked(row, config, "bad_tail_no_go_block_strategy_families"):
        return state

    slice_id = ""
    reasons = []
    best_ask = maybe_float(first_present(row, "best_ask", "clob_best_ask"))
    low_tail_max = maybe_float(config.get("bad_tail_no_go_low_price_tail_max_price"))
    if low_tail_max is None:
        low_tail_max = maybe_float(config.get("tail_price_threshold")) or 0.05
    if (
        bool_value(config.get("bad_tail_no_go_low_price_tail_enabled"), True)
        and bool_value(row.get("low_price_tail"), False)
        and best_ask is not None
        and best_ask <= low_tail_max
    ):
        slice_id = f"low_price_tail_price_le_{low_tail_max:.2f}"
        reasons.extend([
            "tail_type:low_price_tail",
            f"best_ask:{compact_float(best_ask)}",
            f"max_price:{compact_float(low_tail_max)}",
        ])
    elif (
        bool_value(config.get("bad_tail_no_go_warm_tail_enabled"), True)
        and bool_value(config.get("market_centered_warm_tail_guard_enabled"), True)
        and bool_value(row.get("market_centered_warm_tail"), False)
        and row.get("warm_tail_guard_status") == "blocked"
    ):
        slice_id = "market_centered_warm_tail"
        reasons.extend([
            "tail_type:market_centered_warm_tail",
            f"distance:{row.get('market_modal_band_distance')}",
            f"modal:{row.get('market_modal_band_key') or 'missing'}",
        ])

    if not slice_id:
        return state

    allowed_slices = csv_tokens(config.get("bad_tail_no_go_allow_slice_ids"))
    allowed = (
        slice_id.lower() in allowed_slices
        or strategy_risk_gate_allowlisted(
            row,
            config,
            family_key="bad_tail_no_go_allow_strategy_families",
            id_key="bad_tail_no_go_allow_strategy_ids",
        )
    )
    state.update({
        "bad_tail_no_go_status": "allowed" if allowed else "blocked",
        "bad_tail_no_go_action": "allow" if allowed else "no_trade",
        "bad_tail_no_go_slice_id": slice_id,
        "bad_tail_no_go_reason": ";".join([
            *reasons,
            "requires_settlement_positive_allowlist",
        ]),
    })
    return state


def base_order_row(input_row, run_id, target_date, now, config, config_hash, strategy=None, experiment_id=None):
    strategy = strategy or {}
    experiment_id = experiment_id or DEFAULT_EXPERIMENT_ID
    kind, value, value_hi = snapshot_band_key(input_row)
    token = input_row.get("clob_token_id") or input_row.get("clob_yes_token_id") or ""
    fair = clamp_probability(input_row.get("fair_probability"))
    best_bid = clamp_probability(first_present(input_row, "clob_best_bid", "best_bid", "gamma_best_bid"))
    best_ask = clamp_probability(first_present(input_row, "clob_best_ask", "best_ask", "gamma_best_ask"))
    no_best_bid = clamp_probability(first_present(input_row, "no_best_bid", "clob_no_best_bid"))
    no_best_ask = clamp_probability(first_present(input_row, "no_best_ask", "clob_no_best_ask"))
    no_ask_size = maybe_float(first_present(input_row, "no_ask_size_at_best", "clob_no_ask_size_at_best"))
    no_bid_size = maybe_float(first_present(input_row, "no_bid_size_at_best", "clob_no_bid_size_at_best"))
    no_book_age = maybe_float(first_present(input_row, "no_book_age_seconds", "clob_no_book_age_seconds"))
    if no_book_age is None:
        no_book_age = age_seconds(
            first_present(input_row, "no_book_captured_at_utc", "clob_no_book_captured_at_utc"),
            now,
        )
    no_book_source = input_row.get("no_book_source") or ""
    no_book_max_age = float(config.get("two_sided_real_no_book_max_age_seconds") or 120.0)
    no_book_min_depth = float(config.get("two_sided_real_no_book_min_ask_size") or 0.0)
    no_book_real = no_book_source == "no_token_book"
    no_book_fresh = bool(no_book_real and no_book_age is not None and no_book_age <= no_book_max_age)
    real_no_depth_eligible = bool(no_book_fresh and (no_ask_size or 0.0) > 0 and (no_ask_size or 0.0) >= no_book_min_depth)
    mid = market_mid(input_row)
    edge = fair - best_ask if fair is not None and best_ask is not None else None
    model_variant_id = (
        input_row.get("model_variant_id")
        or input_row.get("variant_id")
        or "served_current"
    )
    model_variant_family = (
        input_row.get("model_variant_family")
        or input_row.get("variant_family")
        or "served"
    )
    model_variant_probability = clamp_probability(
        input_row.get("model_variant_probability")
        or input_row.get("fair_probability")
        or input_row.get("model_probability")
    )
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
        "model_variant_id": model_variant_id,
        "range_label": input_row.get("range_label") or "",
        "fair_probability": compact_float(fair),
        "best_ask": compact_float(best_ask),
    }
    intent = order_key(intent_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": config_hash,
        "model_variant_id": model_variant_id,
        "model_variant_family": model_variant_family,
        "model_variant_role": input_row.get("model_variant_role") or ("control" if model_variant_id == "served_current" else "shadow"),
        "model_variant_basket_id": input_row.get("model_variant_basket_id") or "",
        "model_variant_basket_size": input_row.get("model_variant_basket_size"),
        "model_variant_probability": compact_float(model_variant_probability),
        "model_variant_probability_source": input_row.get("model_variant_probability_source") or "",
        "model_variant_prediction_generated_at_utc": (
            input_row.get("model_variant_prediction_generated_at_utc")
            or input_row.get("prediction_generated_at_utc")
            or input_row.get("captured_at_utc")
            or generated
        ),
        "served_model_version": input_row.get("served_model_version") or input_row.get("model_version") or "",
        "model_artifact_path": input_row.get("model_artifact_path") or input_row.get("artifact_path") or "",
        "model_artifact_hash": input_row.get("model_artifact_hash") or input_row.get("artifact_hash") or "",
        "model_feature_schema": input_row.get("model_feature_schema") or input_row.get("feature_schema") or "",
        "model_runtime_identity": input_row.get("model_runtime_identity") or input_row.get("runtime_identity") or "",
        "experiment_id": experiment_id,
        "strategy_id": strategy.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_family": strategy.get("strategy_family") or "raw_edge",
        "strategy_status": strategy.get("status") or "control",
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
        "clob_yes_token_id": input_row.get("clob_yes_token_id") or "",
        "clob_no_token_id": input_row.get("clob_no_token_id") or "",
        "clob_token_id": token,
        # Two-sided taker (item 253): NO-side candidates carry taker_side=NO_BUY;
        # default stays YES_BUY so YES-only behaviour is unchanged.
        "side": str(input_row.get("taker_side") or "YES_BUY").upper(),
        "action": "NO_TRADE",
        "order_status": "SKIPPED",
        "reason_code": "",
        "reason_detail": "",
        "fair_probability": compact_float(fair),
        "best_bid": compact_float(best_bid),
        "best_ask": compact_float(best_ask),
        "no_best_bid": compact_float(no_best_bid),
        "no_best_ask": compact_float(no_best_ask),
        "no_bid_size_at_best": compact_float(no_bid_size),
        "no_ask_size_at_best": compact_float(no_ask_size),
        "no_ask_depth_1pct": compact_float(first_present(input_row, "no_ask_depth_1pct", "clob_no_ask_depth_1pct")),
        "no_book_source": no_book_source,
        "no_book_captured_at_utc": input_row.get("no_book_captured_at_utc") or input_row.get("clob_no_book_captured_at_utc") or "",
        "no_book_age_seconds": compact_float(no_book_age),
        "no_book_fresh": no_book_fresh,
        "real_no_book_depth_eligible": real_no_depth_eligible,
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
        "market_modal_band_key": "",
        "market_modal_probability": None,
        "market_modal_band_distance": None,
        "market_centered_warm_tail": False,
        "warm_tail_guard_status": "inactive",
        "warm_tail_guard_reason": "",
        "bad_tail_no_go_status": "inactive",
        "bad_tail_no_go_action": "allow",
        "bad_tail_no_go_slice_id": "",
        "bad_tail_no_go_reason": "",
        "weak_slot_gate_status": "inactive",
        "weak_slot_gate_reason": "",
        "weak_slot_gate_source": "",
        "current_high_band_distance": None,
        "adjacent_bin_cluster_key": "",
        "market_notional_before_usdc": 0.0,
        "adjacent_cluster_notional_before_usdc": 0.0,
        "low_price_tail_notional_before_usdc": 0.0,
        "market_centered_warm_tail_notional_before_usdc": 0.0,
        "same_snapshot_adjacent_cluster_fill_count_before": 0,
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
        "current_high_trust_state_present": input_row.get("current_high_trusted") not in (None, ""),
        "current_high_trusted": bool_value(input_row.get("current_high_trusted"), True),
        "current_high_guard_reason": input_row.get("current_high_guard_reason") or "",
        "source_fresh": bool_value(input_row.get("source_fresh"), False),
        "source_freshness_state": input_row.get("source_freshness_state") or "",
        "snapshot_cadence_state_present": snapshot_cadence_state_present(input_row),
        "snapshot_cadence": input_row.get("snapshot_cadence") or "",
        "snapshot_cadence_quality_state": input_row.get("snapshot_cadence_quality_state") or "",
        "snapshot_cadence_gap_count": input_row.get("snapshot_cadence_gap_count") or "",
        "snapshot_cadence_max_gap_seconds": input_row.get("snapshot_cadence_max_gap_seconds") or "",
        "snapshot_cadence_last_model_age_seconds": input_row.get("snapshot_cadence_last_model_age_seconds") or "",
        "snapshot_cadence_confidence_multiplier": input_row.get("snapshot_cadence_confidence_multiplier") or "",
        "snapshot_cadence_permission": input_row.get("snapshot_cadence_permission") or "",
        "snapshot_cadence_reason": input_row.get("snapshot_cadence_reason") or "",
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
    if row.get("snapshot_cadence_permission") == "deny":
        return (
            "NO_TRADE_SNAPSHOT_CADENCE_DEGRADED",
            row.get("snapshot_cadence_reason") or "snapshot cadence quality gate denied taker permission",
        )
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
    weak_slot_allowlisted = strategy_risk_gate_allowlisted(
        row,
        config,
        family_key="weak_slot_guard_allow_strategy_families",
        id_key="weak_slot_guard_allow_strategy_ids",
    )
    if (
        row.get("weak_slot_gate_status") == "blocked"
        and not weak_slot_allowlisted
        and strategy_family_blocked(row, config, "weak_slot_guard_block_strategy_families")
    ):
        return (
            "NO_TRADE_WEAK_SLOT_KILL_SWITCH",
            row.get("weak_slot_gate_reason") or "strategy is blocked by weak-slot performance gate",
        )
    if row.get("warm_tail_guard_status") == "blocked":
        return (
            "NO_TRADE_MARKET_CENTERED_WARM_TAIL",
            row.get("warm_tail_guard_reason") or "market-centered warm-tail guard blocked this buy",
        )
    if row.get("bad_tail_no_go_status") == "blocked":
        return (
            "NO_TRADE_BAD_TAIL_NO_GO",
            row.get("bad_tail_no_go_reason") or "bad-tail no-go registry blocked this buy",
        )
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
    if row.get("current_high_trust_gate_status") == "blocked":
        return (
            "NO_TRADE_CURRENT_HIGH_TRUST_GATE",
            row.get("current_high_trust_gate_reason") or "untrusted current-high state blocks aggressive entry",
        )
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
