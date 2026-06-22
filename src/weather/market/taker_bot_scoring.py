"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_sizing import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

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


def settlement_for_folder(folder, event_slug, ledger_root=None):
    local = read_json(Path(folder) / "settlement.json", None)
    if local:
        return local
    try:
        return ledger_label_for_slug(event_slug, ledger_root=ledger_root)
    except TypeError:
        return ledger_label_for_slug(event_slug)


def settlement_outcome_for_order(row, settlement):
    if not settlement:
        return None
    bucket = maybe_float(settlement.get("settlement_bucket"))
    kind, value, value_hi = band_key(row)
    if bucket is None or value is None:
        return None
    try:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi=value_hi) else 0.0
    except TypeError:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi) else 0.0


def load_settlement_labels(labels_csv=DEFAULT_LABELS_CSV):
    """Load finalized market-day labels keyed by event slug and market/date."""
    labels = {
        "by_event_slug": {},
        "by_market_date": {},
    }
    for row in read_csv_rows(labels_csv, attach_diagnostics=True):
        event_slug = row.get("event_slug") or ""
        market_id = row.get("market_id") or ""
        target_date = row.get("target_date") or ""
        if event_slug:
            labels["by_event_slug"][event_slug] = row
        if market_id and target_date:
            labels["by_market_date"][(market_id, target_date)] = row
    return labels


def settlement_label_for_order(row, labels):
    event_slug = row.get("event_slug") or ""
    if event_slug and event_slug in labels.get("by_event_slug", {}):
        return labels["by_event_slug"][event_slug]
    key = (row.get("market_id") or "", row.get("target_date") or "")
    return labels.get("by_market_date", {}).get(key)


def executable_pnl_components(row, payout):
    fill_size = maybe_float(row.get("fill_size")) or 0.0
    fill_notional = maybe_float(row.get("fill_notional_usdc"))
    fee = maybe_float(row.get("fee_usdc")) or 0.0
    if fill_notional is None:
        fill_notional = max(0.0, (maybe_float(row.get("total_spent_usdc")) or 0.0) - fee)
    frictionless = maybe_float(row.get("frictionless_notional_usdc"))
    if frictionless is None:
        frictionless_price = maybe_float(first_present(row, "frictionless_fill_price", "best_ask", "fill_price"))
        frictionless = fill_size * frictionless_price if frictionless_price is not None else fill_notional
    slippage = maybe_float(row.get("slippage_usdc"))
    if slippage is None:
        slippage = max(0.0, fill_notional - frictionless)
    gross = float(payout) - frictionless
    net = gross - fee - slippage
    basis = row.get("pnl_fee_basis") or ("after_fee" if fee > 0 else "paper_no_fee")
    return {
        "gross_pnl_usdc": compact_float(gross),
        "fee_pnl_usdc": compact_float(-fee),
        "slippage_pnl_usdc": compact_float(-slippage),
        "slippage_usdc": compact_float(slippage),
        "executable_net_pnl_usdc": compact_float(net),
        "net_pnl_usdc": compact_float(net),
        "pnl_fee_basis": basis,
        "after_fee_pnl_scored": basis in {"after_fee", "fees_included", "net_after_fee"},
        "after_slippage_pnl_scored": row.get("executable_depth_model_version") not in (None, ""),
    }


def score_orders_against_labels(order_rows, labels):
    """Score filled taker orders against finalized labels without touching raw tape."""
    scored = []
    matched = 0
    unmatched = 0
    for row in order_rows or []:
        out = dict(row)
        if str(row.get("order_status") or "").upper() != "FILLED":
            scored.append(out)
            continue
        label = settlement_label_for_order(row, labels)
        outcome = settlement_outcome_for_order(row, label)
        out["settlement_outcome"] = compact_float(outcome)
        if outcome is None:
            unmatched += 1
            out.update({
                "settlement_status": "unsettled",
                "settlement_payout_usdc": None,
                "settlement_pnl_usdc": None,
                "mark_pnl_usdc": None,
                "pnl_source": "unscored",
                "net_pnl_usdc": None,
            })
            scored.append(out)
            continue
        matched += 1
        fill_size = maybe_float(row.get("fill_size")) or 0.0
        payout = float(outcome) * fill_size
        components = executable_pnl_components(row, payout)
        out.update({
            "settlement_status": "settled",
            "settlement_payout_usdc": compact_float(payout),
            "settlement_pnl_usdc": components["net_pnl_usdc"],
            "mark_pnl_usdc": None,
            "pnl_source": "settlement_finalized",
            **components,
        })
        scored.append(out)
    return scored, {
        "matched_filled_orders": matched,
        "unmatched_filled_orders": unmatched,
        "label_count": len(labels.get("by_event_slug", {})),
    }


def load_mark_rows(folder):
    folder = Path(folder)
    rows = []
    for row in read_csv_rows(folder / "price_history.csv", attach_diagnostics=True):
        token = row.get("clob_token_id") or row.get("asset_id") or row.get("token_id")
        ts = parse_time(row.get("point_time_utc") or row.get("captured_at_utc") or row.get("timestamp_utc"))
        price = clamp_probability(row.get("price") or row.get("midpoint") or row.get("last_trade_price"))
        if token and ts is not None and price is not None:
            rows.append({"time": ts, "clob_token_id": str(token), "price": price, "source": "price_history"})
    for row in read_csv_rows(folder / "order_books_summary.csv", attach_diagnostics=True):
        token = row.get("clob_token_id") or row.get("asset_id") or row.get("token_id")
        ts = parse_time(row.get("captured_at_utc") or row.get("book_time_utc"))
        price = clamp_probability(row.get("midpoint") or row.get("last_trade_price") or row.get("gamma_last_trade_price"))
        if token and ts is not None and price is not None:
            rows.append({"time": ts, "clob_token_id": str(token), "price": price, "source": "order_books_summary"})
    rows.sort(key=lambda item: (item["time"], item["source"]))
    return rows


def latest_mark(mark_rows, token, now):
    token_rows = [row for row in mark_rows if row.get("clob_token_id") == str(token)]
    if not token_rows:
        return None
    before = [row for row in token_rows if row["time"] <= now]
    return before[-1] if before else token_rows[-1]


def score_orders(order_rows, snapshots_root=DEFAULT_SNAPSHOTS_ROOT, ledger_root=None, now=None):
    now = utc_now(now)
    cache = {}
    scored = []
    for row in order_rows or []:
        out = dict(row)
        if str(row.get("order_status") or "").upper() != "FILLED":
            scored.append(out)
            continue
        event_slug = row.get("event_slug") or ""
        if event_slug not in cache:
            folder = Path(snapshots_root) / event_slug
            cache[event_slug] = {
                "folder": folder,
                "settlement": settlement_for_folder(folder, event_slug, ledger_root=ledger_root),
                "marks": load_mark_rows(folder),
            }
        item = cache[event_slug]
        fill_size = maybe_float(row.get("fill_size")) or 0.0
        outcome = settlement_outcome_for_order(row, item["settlement"])
        mark = latest_mark(item["marks"], row.get("clob_token_id"), now)
        out["settlement_outcome"] = compact_float(outcome)
        out["mark_price"] = compact_float(mark.get("price") if mark else None)
        if outcome is not None:
            payout = outcome * fill_size
            components = executable_pnl_components(row, payout)
            out.update({
                "settlement_status": "settled",
                "settlement_payout_usdc": compact_float(payout),
                "settlement_pnl_usdc": components["net_pnl_usdc"],
                "mark_pnl_usdc": None,
                "pnl_source": "settlement",
                **components,
            })
        elif mark:
            components = executable_pnl_components(row, float(mark["price"]) * fill_size)
            out.update({
                "settlement_status": "unsettled",
                "settlement_payout_usdc": None,
                "settlement_pnl_usdc": None,
                "mark_pnl_usdc": components["net_pnl_usdc"],
                "pnl_source": "mark_to_market",
                **components,
            })
        else:
            out.update({
                "settlement_status": "unsettled",
                "settlement_payout_usdc": None,
                "settlement_pnl_usdc": None,
                "mark_pnl_usdc": None,
                "pnl_source": "unscored",
                "net_pnl_usdc": None,
            })
        scored.append(out)
    return scored


def sum_field(rows, key):
    return round(sum(maybe_float(row.get(key)) or 0.0 for row in rows), 6)


def pnl_source_for_group(settled_count, marked_count, unscored_count):
    if settled_count > 0 and marked_count == 0 and unscored_count == 0:
        return "settlement"
    if settled_count > 0:
        return "mixed_settlement_and_unscored"
    if marked_count > 0:
        return "mark_to_market"
    return "unscored"


def independent_opinion_key(row):
    return (
        row.get("market_id") or "",
        row.get("event_slug") or "",
        row.get("range_label") or "",
        row.get("bin_kind") or "",
        str(row.get("bin_value") or ""),
        str(row.get("bin_value_hi") or ""),
    )


def _numeric_config(config, key, default):
    value = maybe_float((config or {}).get(key))
    return default if value is None else value


def _int_config(config, key, default):
    value = maybe_float((config or {}).get(key))
    return int(default if value is None else value)


def promotion_thresholds(policy_config=None):
    policy_config = policy_config or {}
    return {
        "min_settled_orders": _int_config(
            policy_config,
            "promotion_min_settled_orders",
            DEFAULT_PROMOTION_MIN_SETTLED_ORDERS,
        ),
        "min_settled_markets": _int_config(
            policy_config,
            "promotion_min_settled_markets",
            DEFAULT_PROMOTION_MIN_SETTLED_MARKETS,
        ),
        "min_settled_net_pnl_usdc": _numeric_config(
            policy_config,
            "promotion_min_settled_net_pnl_usdc",
            DEFAULT_PROMOTION_MIN_SETTLED_NET_PNL_USDC,
        ),
        "min_settled_expected_pnl_usdc": _numeric_config(
            policy_config,
            "promotion_min_settled_expected_pnl_usdc",
            DEFAULT_PROMOTION_MIN_SETTLED_EXPECTED_PNL_USDC,
        ),
        "max_tail_fill_fraction": _numeric_config(
            policy_config,
            "promotion_max_tail_fill_fraction",
            DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION,
        ),
    }


def tail_fill_detail(row):
    return {
        "strategy_id": strategy_id_for_row(row),
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "range_label": row.get("range_label") or "",
        "clob_token_id": row.get("clob_token_id") or "",
        "fair_probability": compact_float(first_present(row, "fair_probability", "model_probability")),
        "market_probability": compact_float(first_present(row, "best_ask", "clob_best_ask", "market_mid")),
        "fill_price": compact_float(row.get("fill_price")),
        "filled_shares": compact_float(row.get("fill_size")),
        "spent_usdc": compact_float(row.get("total_spent_usdc")),
        "pnl_source": row.get("pnl_source") or "",
        "settlement_status": row.get("settlement_status") or "",
        "settlement_outcome": compact_float(row.get("settlement_outcome")),
        "settlement_pnl_usdc": compact_float(row.get("settlement_pnl_usdc")),
        "mark_to_market_pnl_usdc": compact_float(row.get("mark_pnl_usdc")),
        "net_pnl_usdc": compact_float(row.get("net_pnl_usdc")),
    }


def tail_fill_quality_payload(rows, max_tail_fill_fraction=DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION):
    filled = [row for row in rows or [] if str(row.get("order_status") or "").upper() == "FILLED"]
    tail_rows = [row for row in filled if bool_value(row.get("low_price_tail"), False)]
    settled_tail = [row for row in tail_rows if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES]
    unsettled_tail = [row for row in tail_rows if row.get("pnl_source") not in SETTLEMENT_PNL_SOURCES]
    fill_count = len(filled)
    tail_count = len(tail_rows)
    fraction = tail_count / fill_count if fill_count else 0.0
    threshold = float(max_tail_fill_fraction)
    high_fraction = tail_count > 0 and fraction > threshold
    missing_settlement = tail_count > 0 and not settled_tail
    alerts = []
    if high_fraction:
        alerts.append({
            "code": "HIGH_TAIL_FILL_FRACTION",
            "detail": (
                f"{tail_count}/{fill_count} filled orders are low-price tail fills; "
                f"threshold={threshold:.4f}"
            ),
        })
    if missing_settlement:
        alerts.append({
            "code": "TAIL_FILLS_MISSING_SETTLEMENT",
            "detail": "low-price tail fills have no settlement-scored outcomes yet",
        })
    by_key = defaultdict(lambda: {
        "strategy_id": "",
        "market_id": "",
        "range_label": "",
        "fill_count": 0,
        "settled_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "spent_usdc": 0.0,
        "settlement_pnl_usdc": 0.0,
        "mark_to_market_pnl_usdc": 0.0,
        "net_pnl_usdc": 0.0,
    })
    for row in tail_rows:
        key = (strategy_id_for_row(row), row.get("market_id") or "", row.get("range_label") or "")
        bucket = by_key[key]
        bucket["strategy_id"], bucket["market_id"], bucket["range_label"] = key
        bucket["fill_count"] += 1
        bucket["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        bucket["settlement_pnl_usdc"] += maybe_float(row.get("settlement_pnl_usdc")) or 0.0
        bucket["mark_to_market_pnl_usdc"] += maybe_float(row.get("mark_pnl_usdc")) or 0.0
        bucket["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
        if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES:
            bucket["settled_count"] += 1
        outcome = maybe_float(row.get("settlement_outcome"))
        if outcome == 1.0:
            bucket["win_count"] += 1
        elif outcome == 0.0:
            bucket["loss_count"] += 1
    by_market_range = [
        {
            **value,
            "spent_usdc": round(value["spent_usdc"], 6),
            "settlement_pnl_usdc": round(value["settlement_pnl_usdc"], 6),
            "mark_to_market_pnl_usdc": round(value["mark_to_market_pnl_usdc"], 6),
            "net_pnl_usdc": round(value["net_pnl_usdc"], 6),
        }
        for _key, value in sorted(by_key.items())
    ]
    status = (
        "WARN_HIGH_TAIL_SHARE"
        if high_fraction else
        "PENDING_SETTLEMENT"
        if missing_settlement else
        "NO_TAIL_FILLS"
        if tail_count == 0 else
        "PASS"
    )
    return {
        "summary": {
            "status": status,
            "filled_order_count": fill_count,
            "low_price_tail_fill_count": tail_count,
            "low_price_tail_fill_fraction": compact_float(fraction),
            "max_tail_fill_fraction": compact_float(threshold),
            "settled_tail_fill_count": len(settled_tail),
            "unsettled_tail_fill_count": len(unsettled_tail),
            "tail_win_count": sum(1 for row in settled_tail if maybe_float(row.get("settlement_outcome")) == 1.0),
            "tail_loss_count": sum(1 for row in settled_tail if maybe_float(row.get("settlement_outcome")) == 0.0),
            "tail_spent_usdc": sum_field(tail_rows, "total_spent_usdc"),
            "tail_settlement_pnl_usdc": sum_field(settled_tail, "settlement_pnl_usdc"),
            "tail_mark_to_market_pnl_usdc": sum_field(unsettled_tail, "mark_pnl_usdc"),
            "alert_count": len(alerts),
            "alerts": alerts,
        },
        "by_market_range": by_market_range,
        "fills": [tail_fill_detail(row) for row in tail_rows],
    }


def settlement_promotion_gate(strategy_row, thresholds):
    settled_orders = int(strategy_row.get("settled_order_count") or 0)
    settled_markets = int(strategy_row.get("settled_market_count") or 0)
    unsettled_orders = int(strategy_row.get("unsettled_order_count") or 0)
    unscored_orders = int(strategy_row.get("unscored_order_count") or 0)
    settled_net = maybe_float(strategy_row.get("settlement_scored_net_pnl_usdc")) or 0.0
    settled_expected = maybe_float(strategy_row.get("settlement_scored_expected_pnl_usdc")) or 0.0
    after_fee_scored = bool_value(strategy_row.get("after_fee_pnl_scored"), False)
    after_slippage_scored = bool_value(strategy_row.get("after_slippage_pnl_scored"), False)
    tail_summary = strategy_row.get("tail_fill_quality_summary") or {}
    max_tail_fraction = maybe_float(thresholds.get("max_tail_fill_fraction")) or 0.0
    tail_fraction = maybe_float(tail_summary.get("low_price_tail_fill_fraction")) or 0.0
    gates = [
        {
            "name": "min_settled_orders",
            "ok": settled_orders >= int(thresholds.get("min_settled_orders") or 0),
            "value": settled_orders,
            "threshold": int(thresholds.get("min_settled_orders") or 0),
        },
        {
            "name": "min_settled_markets",
            "ok": settled_markets >= int(thresholds.get("min_settled_markets") or 0),
            "value": settled_markets,
            "threshold": int(thresholds.get("min_settled_markets") or 0),
        },
        {
            "name": "min_settlement_scored_net_pnl",
            "ok": settled_net >= float(thresholds.get("min_settled_net_pnl_usdc") or 0.0),
            "value": compact_float(settled_net),
            "threshold": compact_float(thresholds.get("min_settled_net_pnl_usdc")),
        },
        {
            "name": "min_settlement_scored_expected_pnl",
            "ok": settled_expected >= float(thresholds.get("min_settled_expected_pnl_usdc") or 0.0),
            "value": compact_float(settled_expected),
            "threshold": compact_float(thresholds.get("min_settled_expected_pnl_usdc")),
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
            "name": "no_unresolved_orders",
            "ok": unsettled_orders == 0 and unscored_orders == 0,
            "value": unsettled_orders + unscored_orders,
            "threshold": 0,
        },
        {
            "name": "max_tail_fill_fraction",
            "ok": tail_fraction <= max_tail_fraction,
            "value": compact_float(tail_fraction),
            "threshold": compact_float(max_tail_fraction),
        },
    ]
    failed = [row["name"] for row in gates if not row["ok"]]
    return {
        "basis": "settlement_scored_executable_after_fee",
        "status": "PASS" if not failed else "BLOCK",
        "failed_gates": failed,
        "gates": gates,
        **thresholds,
    }


def build_pnl_payload(order_rows, budget_usdc, run_id, target_date, now=None, policy_config=None):
    now = utc_now(now)
    thresholds = promotion_thresholds(policy_config)
    filled = [row for row in order_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    settled = [row for row in filled if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES]
    marked = [row for row in filled if row.get("pnl_source") == "mark_to_market"]
    unscored = [row for row in filled if row.get("pnl_source") == "unscored"]
    tail_quality = tail_fill_quality_payload(
        filled,
        max_tail_fill_fraction=thresholds["max_tail_fill_fraction"],
    )
    reason_counts = Counter(row.get("reason_code") or "unknown" for row in order_rows)
    by_market = defaultdict(lambda: {
        "filled_order_count": 0,
        "filled_shares": 0.0,
        "spent_usdc": 0.0,
        "net_pnl_usdc": 0.0,
    })
    by_strategy = defaultdict(lambda: {
        "experiment_id": "",
        "strategy_id": "",
        "strategy_family": "",
        "strategy_status": "",
        "assignment_rule": "",
        "control_strategy_id": "",
        "strategy_config_hash": "",
        "order_rows": 0,
        "filled_order_count": 0,
        "filled_shares": 0.0,
        "spent_usdc": 0.0,
        "gross_cost_usdc": 0.0,
        "frictionless_cost_usdc": 0.0,
        "fees_usdc": 0.0,
        "slippage_usdc": 0.0,
        "settlement_payout_usdc": 0.0,
        "gross_pnl_usdc": 0.0,
        "fee_pnl_usdc": 0.0,
        "slippage_pnl_usdc": 0.0,
        "executable_net_pnl_usdc": 0.0,
        "settlement_pnl_usdc": 0.0,
        "mark_to_market_pnl_usdc": 0.0,
        "expected_pnl_usdc": 0.0,
        "risk_adjusted_expected_pnl_usdc": 0.0,
        "net_pnl_usdc": 0.0,
        "settled_order_count": 0,
        "settled_markets": set(),
        "settlement_scored_expected_pnl_usdc": 0.0,
        "settlement_scored_risk_adjusted_expected_pnl_usdc": 0.0,
        "unsettled_order_count": 0,
        "unscored_order_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "low_price_tail_fill_count": 0,
        "low_price_tail_spent_usdc": 0.0,
        "low_price_tail_settled_count": 0,
        "low_price_tail_unsettled_count": 0,
        "low_price_tail_win_count": 0,
        "low_price_tail_loss_count": 0,
        "low_price_tail_settlement_pnl_usdc": 0.0,
        "low_price_tail_mark_to_market_pnl_usdc": 0.0,
        "low_price_tail_net_pnl_usdc": 0.0,
        "clob_continuity_fail_count": 0,
        "mark_sanity_outlier_count": 0,
        "stale_book_rows": 0,
        "source_stale_rows": 0,
        "after_fee_pnl_scored_count": 0,
        "after_slippage_pnl_scored_count": 0,
        "paper_no_fee_count": 0,
        "reason_counts": Counter(),
        "filled_opinions": set(),
    })
    positions = defaultdict(lambda: {
        "market_id": "",
        "event_slug": "",
        "range_label": "",
        "clob_token_id": "",
        "filled_shares": 0.0,
        "spent_usdc": 0.0,
        "net_pnl_usdc": 0.0,
        "pnl_source": "",
    })
    for row in order_rows:
        strategy_id = strategy_id_for_row(row)
        strat = by_strategy[strategy_id]
        strat["experiment_id"] = row.get("experiment_id") or DEFAULT_EXPERIMENT_ID
        strat["strategy_id"] = strategy_id
        strat["strategy_family"] = row.get("strategy_family") or "raw_edge"
        strat["strategy_status"] = row.get("strategy_status") or "control"
        strat["assignment_rule"] = row.get("assignment_rule") or "shared_inputs_full_shadow"
        strat["control_strategy_id"] = row.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
        strat["strategy_config_hash"] = row.get("strategy_config_hash") or row.get("policy_hash") or ""
        strat["order_rows"] += 1
        reason = row.get("reason_code") or "unknown"
        strat["reason_counts"][reason] += 1
        if reason in {"NO_TRADE_STALE_BOOK"}:
            strat["stale_book_rows"] += 1
        if reason in {"NO_TRADE_SOURCE_STALE", "NO_TRADE_EARLY_HOUR_SOURCE_STATE"}:
            strat["source_stale_rows"] += 1
    for row in filled:
        market_id = row.get("market_id") or "unknown"
        strategy_id = strategy_id_for_row(row)
        strat = by_strategy[strategy_id]
        by_market[market_id]["filled_order_count"] += 1
        by_market[market_id]["filled_shares"] += maybe_float(row.get("fill_size")) or 0.0
        by_market[market_id]["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        by_market[market_id]["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
        strat["filled_order_count"] += 1
        strat["filled_shares"] += maybe_float(row.get("fill_size")) or 0.0
        strat["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        strat["gross_cost_usdc"] += maybe_float(row.get("fill_notional_usdc")) or 0.0
        strat["frictionless_cost_usdc"] += maybe_float(row.get("frictionless_notional_usdc")) or maybe_float(row.get("fill_notional_usdc")) or 0.0
        strat["fees_usdc"] += maybe_float(row.get("fee_usdc")) or 0.0
        strat["slippage_usdc"] += maybe_float(row.get("slippage_usdc")) or 0.0
        strat["settlement_payout_usdc"] += maybe_float(row.get("settlement_payout_usdc")) or 0.0
        strat["gross_pnl_usdc"] += maybe_float(row.get("gross_pnl_usdc")) or 0.0
        strat["fee_pnl_usdc"] += maybe_float(row.get("fee_pnl_usdc")) or 0.0
        strat["slippage_pnl_usdc"] += maybe_float(row.get("slippage_pnl_usdc")) or 0.0
        strat["executable_net_pnl_usdc"] += maybe_float(row.get("executable_net_pnl_usdc")) or maybe_float(row.get("net_pnl_usdc")) or 0.0
        strat["settlement_pnl_usdc"] += maybe_float(row.get("settlement_pnl_usdc")) or 0.0
        strat["mark_to_market_pnl_usdc"] += maybe_float(row.get("mark_pnl_usdc")) or 0.0
        if bool_value(row.get("after_fee_pnl_scored"), False) or row.get("pnl_fee_basis") in {"after_fee", "fees_included", "net_after_fee"}:
            strat["after_fee_pnl_scored_count"] += 1
        if bool_value(row.get("after_slippage_pnl_scored"), False) or row.get("executable_depth_model_version"):
            strat["after_slippage_pnl_scored_count"] += 1
        if row.get("pnl_fee_basis") == "paper_no_fee":
            strat["paper_no_fee_count"] += 1
        edge = maybe_float(row.get("expected_profit_after_friction_per_share"))
        edge_after_friction = edge is not None
        if edge is None:
            edge = maybe_float(first_present(row, "expected_profit_per_share", "edge"))
        expected_contribution = None
        if edge is not None:
            expected_contribution = edge * (maybe_float(row.get("fill_size")) or 0.0)
            if not edge_after_friction:
                expected_contribution -= (
                    (maybe_float(row.get("fee_usdc")) or 0.0)
                    + (maybe_float(row.get("slippage_usdc")) or 0.0)
                )
            strat["expected_pnl_usdc"] += expected_contribution
        risk_edge = maybe_float(first_present(row, "risk_adjusted_expected_profit_per_share", "risk_adjusted_edge"))
        risk_contribution = None
        if risk_edge is not None:
            risk_contribution = (
                risk_edge * (maybe_float(row.get("fill_size")) or 0.0)
            ) - (
                (maybe_float(row.get("fee_usdc")) or 0.0)
                + (maybe_float(row.get("slippage_usdc")) or 0.0)
            )
            strat["risk_adjusted_expected_pnl_usdc"] += risk_contribution
        if bool_value(row.get("low_price_tail"), False):
            strat["low_price_tail_fill_count"] += 1
            strat["low_price_tail_spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
            strat["low_price_tail_net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
            if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES:
                strat["low_price_tail_settled_count"] += 1
                strat["low_price_tail_settlement_pnl_usdc"] += maybe_float(row.get("settlement_pnl_usdc")) or 0.0
            else:
                strat["low_price_tail_unsettled_count"] += 1
                strat["low_price_tail_mark_to_market_pnl_usdc"] += maybe_float(row.get("mark_pnl_usdc")) or 0.0
        if row.get("clob_continuity_status") not in {"", "pass"}:
            strat["clob_continuity_fail_count"] += 1
        if row.get("mark_sanity_status") == "outlier":
            strat["mark_sanity_outlier_count"] += 1
        strat["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
        if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES:
            strat["settled_order_count"] += 1
            strat["settled_markets"].add(market_id)
            if expected_contribution is not None:
                strat["settlement_scored_expected_pnl_usdc"] += expected_contribution
            if risk_contribution is not None:
                strat["settlement_scored_risk_adjusted_expected_pnl_usdc"] += risk_contribution
        elif row.get("pnl_source") == "mark_to_market":
            strat["unsettled_order_count"] += 1
        else:
            strat["unsettled_order_count"] += 1
            strat["unscored_order_count"] += 1
        if maybe_float(row.get("settlement_outcome")) == 1.0:
            strat["win_count"] += 1
            if bool_value(row.get("low_price_tail"), False):
                strat["low_price_tail_win_count"] += 1
        elif maybe_float(row.get("settlement_outcome")) == 0.0:
            strat["loss_count"] += 1
            if bool_value(row.get("low_price_tail"), False):
                strat["low_price_tail_loss_count"] += 1
        strat["filled_opinions"].add(independent_opinion_key(row))
        token = row.get("clob_token_id") or row.get("order_id") or ""
        pos = positions[token]
        pos.update({
            "market_id": market_id,
            "event_slug": row.get("event_slug") or "",
            "range_label": row.get("range_label") or "",
            "clob_token_id": token,
            "pnl_source": row.get("pnl_source") or "",
        })
        pos["filled_shares"] += maybe_float(row.get("fill_size")) or 0.0
        pos["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        pos["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
    spent = sum_field(filled, "total_spent_usdc")
    summary = {
        "budget_usdc": round(float(budget_usdc), 6),
        "budget_spent_usdc": spent,
        "budget_remaining_usdc": round(max(0.0, float(budget_usdc) - spent), 6),
        "order_rows": len(order_rows),
        "filled_order_count": len(filled),
        "filled_shares": sum_field(filled, "fill_size"),
        "settled_order_count": len(settled),
        "unsettled_order_count": len(marked) + len(unscored),
        "unscored_order_count": len(unscored),
        "gross_cost_usdc": sum_field(filled, "fill_notional_usdc"),
        "frictionless_cost_usdc": sum_field(filled, "frictionless_notional_usdc"),
        "fees_usdc": sum_field(filled, "fee_usdc"),
        "slippage_usdc": sum_field(filled, "slippage_usdc"),
        "gross_pnl_usdc": sum_field([row for row in filled if row.get("gross_pnl_usdc") not in (None, "")], "gross_pnl_usdc"),
        "fee_pnl_usdc": sum_field(filled, "fee_pnl_usdc"),
        "slippage_pnl_usdc": sum_field(filled, "slippage_pnl_usdc"),
        "executable_net_pnl_usdc": sum_field([row for row in filled if row.get("executable_net_pnl_usdc") not in (None, "")], "executable_net_pnl_usdc"),
        "after_fee_pnl_scored": all(
            row.get("pnl_fee_basis") in {"after_fee", "fees_included", "net_after_fee"}
            or bool_value(row.get("after_fee_pnl_scored"), False)
            for row in filled
        ) if filled else False,
        "after_slippage_pnl_scored": all(
            bool_value(row.get("after_slippage_pnl_scored"), False)
            or row.get("executable_depth_model_version") not in (None, "")
            for row in filled
        ) if filled else False,
        "live_profitability_evidence_basis": (
            "executable_after_fee_after_slippage"
            if filled and all(
                row.get("pnl_fee_basis") in {"after_fee", "fees_included", "net_after_fee"}
                or bool_value(row.get("after_fee_pnl_scored"), False)
                for row in filled
            ) else "paper_no_fee"
        ),
        "settlement_payout_usdc": sum_field(settled, "settlement_payout_usdc"),
        "settlement_pnl_usdc": sum_field(settled, "settlement_pnl_usdc"),
        "mark_to_market_pnl_usdc": sum_field(marked, "mark_pnl_usdc"),
        "net_pnl_usdc": sum_field([row for row in filled if row.get("net_pnl_usdc") not in (None, "")], "net_pnl_usdc"),
        "low_price_tail_fill_count": tail_quality["summary"]["low_price_tail_fill_count"],
        "low_price_tail_fill_fraction": tail_quality["summary"]["low_price_tail_fill_fraction"],
        "tail_fill_quality_status": tail_quality["summary"]["status"],
        "tail_fill_alert_count": tail_quality["summary"]["alert_count"],
        "win_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 1.0),
        "loss_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 0.0),
        "reason_counts": dict(sorted(reason_counts.items())),
    }
    strategy_rows = []
    for key, value in sorted(by_strategy.items()):
        strategy_fills = [row for row in filled if strategy_id_for_row(row) == key]
        strategy_tail_quality = tail_fill_quality_payload(
            strategy_fills,
            max_tail_fill_fraction=thresholds["max_tail_fill_fraction"],
        )
        row = {
            "experiment_id": value["experiment_id"],
            "strategy_id": key,
            "strategy_family": value["strategy_family"],
            "strategy_status": value["strategy_status"],
            "assignment_rule": value["assignment_rule"],
            "control_strategy_id": value["control_strategy_id"],
            "strategy_config_hash": value["strategy_config_hash"],
            "order_rows": value["order_rows"],
            "filled_order_count": value["filled_order_count"],
            "filled_shares": round(value["filled_shares"], 6),
            "spent_usdc": round(value["spent_usdc"], 6),
            "gross_cost_usdc": round(value["gross_cost_usdc"], 6),
            "frictionless_cost_usdc": round(value["frictionless_cost_usdc"], 6),
            "fees_usdc": round(value["fees_usdc"], 6),
            "slippage_usdc": round(value["slippage_usdc"], 6),
            "gross_pnl_usdc": round(value["gross_pnl_usdc"], 6),
            "fee_pnl_usdc": round(value["fee_pnl_usdc"], 6),
            "slippage_pnl_usdc": round(value["slippage_pnl_usdc"], 6),
            "executable_net_pnl_usdc": round(value["executable_net_pnl_usdc"], 6),
            "after_fee_pnl_scored": (
                value["filled_order_count"] > 0
                and value["after_fee_pnl_scored_count"] == value["filled_order_count"]
            ),
            "after_slippage_pnl_scored": (
                value["filled_order_count"] > 0
                and value["after_slippage_pnl_scored_count"] == value["filled_order_count"]
            ),
            "paper_no_fee_count": value["paper_no_fee_count"],
            "pnl_fee_basis": (
                "after_fee"
                if value["filled_order_count"] > 0
                and value["after_fee_pnl_scored_count"] == value["filled_order_count"]
                else "paper_no_fee"
            ),
            "after_fee_pnl_basis": (
                "after_fee"
                if value["filled_order_count"] > 0
                and value["after_fee_pnl_scored_count"] == value["filled_order_count"]
                else "paper_no_fee"
            ),
            "live_profitability_evidence_basis": (
                "executable_after_fee_after_slippage"
                if value["filled_order_count"] > 0
                and value["after_fee_pnl_scored_count"] == value["filled_order_count"]
                and value["after_slippage_pnl_scored_count"] == value["filled_order_count"]
                else "paper_no_fee"
            ),
            "settlement_payout_usdc": round(value["settlement_payout_usdc"], 6),
            "settlement_pnl_usdc": round(value["settlement_pnl_usdc"], 6),
            "mark_to_market_pnl_usdc": round(value["mark_to_market_pnl_usdc"], 6),
            "expected_pnl_usdc": round(value["expected_pnl_usdc"], 6),
            "risk_adjusted_expected_pnl_usdc": round(value["risk_adjusted_expected_pnl_usdc"], 6),
            "realized_minus_expected_pnl_usdc": round(
                value["net_pnl_usdc"] - value["expected_pnl_usdc"],
                6,
            ),
            "realized_minus_risk_adjusted_expected_pnl_usdc": round(
                value["net_pnl_usdc"] - value["risk_adjusted_expected_pnl_usdc"],
                6,
            ),
            "net_pnl_usdc": round(value["net_pnl_usdc"], 6),
            "settled_order_count": value["settled_order_count"],
            "settled_market_count": len(value["settled_markets"]),
            "settlement_scored_net_pnl_usdc": round(value["settlement_pnl_usdc"], 6),
            "settlement_scored_expected_pnl_usdc": round(value["settlement_scored_expected_pnl_usdc"], 6),
            "settlement_scored_risk_adjusted_expected_pnl_usdc": round(
                value["settlement_scored_risk_adjusted_expected_pnl_usdc"],
                6,
            ),
            "unsettled_order_count": value["unsettled_order_count"],
            "unscored_order_count": value["unscored_order_count"],
            "win_count": value["win_count"],
            "loss_count": value["loss_count"],
            "independent_opinion_count": len(value["filled_opinions"]),
            "low_price_tail_fill_count": value["low_price_tail_fill_count"],
            "low_price_tail_spent_usdc": round(value["low_price_tail_spent_usdc"], 6),
            "low_price_tail_fill_fraction": compact_float(
                value["low_price_tail_fill_count"] / value["filled_order_count"]
                if value["filled_order_count"] else 0.0
            ),
            "low_price_tail_settled_count": value["low_price_tail_settled_count"],
            "low_price_tail_unsettled_count": value["low_price_tail_unsettled_count"],
            "low_price_tail_win_count": value["low_price_tail_win_count"],
            "low_price_tail_loss_count": value["low_price_tail_loss_count"],
            "low_price_tail_settlement_pnl_usdc": round(value["low_price_tail_settlement_pnl_usdc"], 6),
            "low_price_tail_mark_to_market_pnl_usdc": round(value["low_price_tail_mark_to_market_pnl_usdc"], 6),
            "low_price_tail_net_pnl_usdc": round(value["low_price_tail_net_pnl_usdc"], 6),
            "tail_fill_quality_summary": strategy_tail_quality["summary"],
            "tail_fill_quality_by_market_range": strategy_tail_quality["by_market_range"],
            "clob_continuity_fail_count": value["clob_continuity_fail_count"],
            "mark_sanity_outlier_count": value["mark_sanity_outlier_count"],
            "stale_book_rows": value["stale_book_rows"],
            "source_stale_rows": value["source_stale_rows"],
            "pnl_source": pnl_source_for_group(
                value["settled_order_count"],
                value["unsettled_order_count"] - value["unscored_order_count"],
                value["unscored_order_count"],
            ),
            "reason_counts": dict(sorted(value["reason_counts"].items())),
        }
        gate = settlement_promotion_gate(row, thresholds)
        row["settlement_promotion_gate"] = gate
        row["settlement_promotion_gate_status"] = gate["status"]
        row["settlement_promotion_failed_gates"] = gate["failed_gates"]
        row["quality_candidate_countable"] = gate["status"] == "PASS"
        row["quality_candidate_evidence_basis"] = gate["basis"]
        strategy_rows.append(row)
    best_by_net = max(strategy_rows, key=lambda row: row["net_pnl_usdc"], default=None)
    countable_candidates = [row for row in strategy_rows if row["quality_candidate_countable"]]
    best_countable = max(countable_candidates, key=lambda row: row["net_pnl_usdc"], default=None)
    strategy_comparison = {
        "schema_version": STRATEGY_REPORT_SCHEMA_VERSION,
        "strategy_count": len(strategy_rows),
        "best_strategy_id": (best_by_net or {}).get("strategy_id"),
        "best_strategy_net_pnl_usdc": (best_by_net or {}).get("net_pnl_usdc"),
        "best_settlement_scored_strategy_id": (best_countable or {}).get("strategy_id"),
        "best_settlement_scored_net_pnl_usdc": (best_countable or {}).get("net_pnl_usdc"),
        "countable_strategy_quality_candidate": best_countable or {},
        "countable_strategy_quality_candidate_status": (
            "COUNTABLE_SETTLED" if best_countable else "MISSING_SETTLED_SAMPLE"
        ),
        "promotion_thresholds": thresholds,
        "promotion_evidence_basis": "settlement_scored_executable_after_fee",
        "mtm_promotion_allowed": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "summary": summary,
        "by_strategy": strategy_rows,
        "strategy_comparison": strategy_comparison,
        "tail_fill_quality": tail_quality,
        "by_market": [
            {
                "market_id": key,
                "filled_order_count": value["filled_order_count"],
                "filled_shares": round(value["filled_shares"], 6),
                "spent_usdc": round(value["spent_usdc"], 6),
                "net_pnl_usdc": round(value["net_pnl_usdc"], 6),
            }
            for key, value in sorted(by_market.items())
        ],
        "positions": [
            {
                **value,
                "filled_shares": round(value["filled_shares"], 6),
                "spent_usdc": round(value["spent_usdc"], 6),
                "net_pnl_usdc": round(value["net_pnl_usdc"], 6),
            }
            for _key, value in sorted(positions.items())
        ],
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
