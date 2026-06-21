"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_strategy_registry import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(path)


def tape_integrity_summary(path, expected_rows, row_kind):
    actual_rows = len(read_csv_rows(path))
    expected_rows = int(expected_rows or 0)
    status = "PASS" if actual_rows == expected_rows else "WARN"
    return {
        "status": status,
        "path": str(path),
        "row_kind": row_kind,
        "expected_rows": expected_rows,
        "actual_rows": actual_rows,
        "detail": (
            f"{row_kind} tape row count matches summary"
            if status == "PASS"
            else f"{row_kind} tape has {actual_rows} rows but summary expected {expected_rows}"
        ),
    }


def read_order_rows(path):
    return [
        normalize_order_strategy_fields(row)
        for row in read_csv_rows(path, attach_diagnostics=True)
    ]


def order_key(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def latest_book_index(rows):
    by_token = {}
    by_band = {}
    for row in rows or []:
        kind, value, value_hi = snapshot_band_key(row)
        snapshot_id = row.get("snapshot_id") or ""
        token = row.get("clob_token_id") or row.get("clob_yes_token_id") or ""
        band_key = (snapshot_id, kind, value, value_hi)
        by_band[band_key] = row
        if token:
            by_token[(snapshot_id, kind, value, value_hi, str(token))] = row
    return by_token, by_band


def _book_for_snapshot(snapshot_row, by_token, by_band):
    kind, value, value_hi = snapshot_band_key(snapshot_row)
    token = snapshot_row.get("clob_token_id") or snapshot_row.get("clob_yes_token_id") or ""
    snapshot_id = snapshot_row.get("snapshot_id") or ""
    return (
        by_token.get((snapshot_id, kind, value, value_hi, str(token)))
        or by_token.get(("", kind, value, value_hi, str(token)))
        or by_band.get((snapshot_id, kind, value, value_hi))
        or by_band.get(("", kind, value, value_hi))
        or {}
    )


def age_seconds(timestamp, now):
    parsed = parse_time(timestamp)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def market_mid(row):
    mid = clamp_probability(first_present(row, "market_mid", "clob_midpoint", "midpoint"))
    if mid is not None:
        return mid
    bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid", "gamma_best_bid"))
    ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask", "gamma_best_ask"))
    if bid is not None and ask is not None and ask >= bid:
        return (bid + ask) / 2.0
    return clamp_probability(row.get("market_yes"))


def model_age_seconds(row, now):
    value = maybe_float(row.get("model_age_seconds"))
    if value is not None:
        return max(0.0, value)
    return age_seconds(row.get("captured_at_utc"), now)


def book_age_seconds(row, now):
    value = maybe_float(first_present(row, "book_age_seconds", "clob_book_age_seconds"))
    if value is not None:
        return max(0.0, value)
    return age_seconds(first_present(row, "clob_book_captured_at_utc", "book_time_utc", "captured_at_utc"), now)


def boolish_active(value):
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"active", "open", "1", "true", "yes"}:
        return True
    if text in {"closed", "inactive", "0", "false", "no"}:
        return False
    return True


def csv_tokens(value):
    return {
        item.strip().lower()
        for item in str(value or "").replace(";", ",").split(",")
        if item.strip()
    }


def market_local_time(row):
    timestamp = parse_time(first_present(row, "captured_at_utc", "generated_at_utc"))
    if timestamp is None:
        return None, ""
    try:
        spec = spec_for_id(row.get("market_id") or "")
        zone = spec.tz
    except Exception:  # noqa: BLE001 - an unknown market should not crash policy diagnostics
        zone = timezone.utc
    local = timestamp.astimezone(zone)
    return local, getattr(zone, "key", str(zone))


def hour_in_window(hour, start, end):
    if hour is None:
        return False
    hour = int(hour)
    start = int(start)
    end = int(end)
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def early_hour_guardrail_state(row, config):
    local, zone_name = market_local_time(row)
    hour = local.hour if local else None
    enabled = bool(config.get("early_hour_guardrail_enabled", True))
    in_window = enabled and hour_in_window(hour, config.get("early_hour_start", 0), config.get("early_hour_end", 8))
    min_edge = max(
        float(config["min_edge"]) * float(config.get("early_hour_min_edge_multiplier", 1.0)),
        float(config.get("early_hour_min_edge", config["min_edge"])),
    )
    max_order = min(float(config["max_order_usdc"]), float(config.get("early_hour_max_order_usdc", config["max_order_usdc"])))
    max_position = min(
        float(config["max_position_per_token_usdc"]),
        float(config.get("early_hour_max_position_per_token_usdc", config["max_position_per_token_usdc"])),
    )
    max_positions = min(
        int(config["max_daily_positions"]),
        int(float(config.get("early_hour_max_daily_positions", config["max_daily_positions"]))),
    )
    state = {
        "capture_hour_local": hour,
        "capture_timezone": zone_name,
        "early_hour_guardrail_status": "inactive",
        "early_hour_guardrail_reason": "",
        "early_hour_guardrail_min_edge": round(min_edge, 6),
        "early_hour_guardrail_max_order_usdc": round(max_order, 6),
        "early_hour_guardrail_max_position_per_token_usdc": round(max_position, 6),
        "early_hour_guardrail_max_daily_positions": max_positions,
    }
    if not in_window:
        return state

    state["early_hour_guardrail_status"] = "active"
    edge = maybe_float(row.get("edge"))
    allowed_states = csv_tokens(config.get("early_hour_require_source_states"))
    source_state = str(row.get("source_freshness_state") or "").strip().lower()
    disposition = str(row.get("current_max_disposition") or "").strip().lower()
    current_state = str(row.get("current_max_state") or "").strip()
    if (
        config.get("early_hour_block_guarded_current_high", True)
        and disposition in {"null_before_reset", "support_only"}
    ):
        state.update({
            "early_hour_guardrail_status": "blocked",
            "early_hour_guardrail_reason": f"guarded_current_high:{current_state or disposition}",
        })
    elif allowed_states and source_state not in allowed_states:
        state.update({
            "early_hour_guardrail_status": "blocked",
            "early_hour_guardrail_reason": f"source_state:{source_state or 'missing'}",
        })
    elif edge is not None and edge < min_edge:
        state.update({
            "early_hour_guardrail_status": "blocked",
            "early_hour_guardrail_reason": "edge_below_early_hour_minimum",
        })
    return state


def early_hour_effective_caps(row, config):
    if row.get("early_hour_guardrail_status") == "active":
        return {
            "max_order_usdc": maybe_float(row.get("early_hour_guardrail_max_order_usdc")) or float(config["max_order_usdc"]),
            "max_position_per_token_usdc": (
                maybe_float(row.get("early_hour_guardrail_max_position_per_token_usdc"))
                or float(config["max_position_per_token_usdc"])
            ),
            "max_daily_positions": int(float(row.get("early_hour_guardrail_max_daily_positions") or config["max_daily_positions"])),
        }
    return {
        "max_order_usdc": float(config["max_order_usdc"]),
        "max_position_per_token_usdc": float(config["max_position_per_token_usdc"]),
        "max_daily_positions": int(config["max_daily_positions"]),
    }


def assemble_taker_inputs_for_market(
    market_id,
    folder,
    snapshot_rows,
    source_rows,
    clob_feature_rows,
    book_rows,
    current_high_assessment=None,
):
    clob_by_token, clob_by_band = clob_feature_index_from_rows(clob_feature_rows)
    book_by_token, book_by_band = latest_book_index(book_rows)
    source_fresh = source_status_is_current(source_rows)
    source_state = source_freshness_state_from_rows(source_rows)
    rows = []
    for snapshot_row in snapshot_rows:
        kind, value, value_hi = snapshot_band_key(snapshot_row)
        token = snapshot_row.get("clob_token_id") or snapshot_row.get("clob_yes_token_id") or ""
        snapshot_id = snapshot_row.get("snapshot_id")
        band_key = (snapshot_id, kind, value, value_hi)
        token_key = (snapshot_id, kind, value, value_hi, str(token))
        clob_row = clob_by_token.get(token_key) or clob_by_band.get(band_key) or {}
        book_row = _book_for_snapshot({**snapshot_row, **clob_row}, book_by_token, book_by_band)
        merged = dict(snapshot_row)
        merged.update({key: value for key, value in clob_row.items() if value not in (None, "")})
        merged.update({key: value for key, value in book_row.items() if value not in (None, "")})
        merged["market_id"] = market_id
        merged["folder"] = str(folder)
        merged["fair_probability"] = first_present(merged, "fair_probability", "model_probability", "candidate_p")
        merged["market_mid"] = market_mid(merged)
        merged["source_fresh"] = source_fresh
        merged["source_freshness_state"] = source_state
        merged.update(normalized_high_fields(current_high_assessment))
        if not merged.get("clob_token_id"):
            merged["clob_token_id"] = token
        if "bin_value" not in merged and merged.get("bin_value_c") not in (None, ""):
            merged["bin_value"] = merged.get("bin_value_c")
        rows.append(merged)
    return rows

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
