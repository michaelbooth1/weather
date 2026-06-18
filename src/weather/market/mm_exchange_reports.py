"""Report and reconciliation summaries for the MM exchange adapter."""

from __future__ import annotations

from collections import Counter

from weather.market.mm_policy import bool_value, maybe_float


SCHEMA_VERSION = "mm_exchange_adapter_v0.1"


def build_reconciliation_report(payload):
    lines = [
        "# MM Exchange Adapter Reconciliation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Gate Summary",
        "",
        f"- Item-45 gates ok: `{str((payload.get('item45_gates') or {}).get('ok')).lower()}`",
        f"- Trading verbs enabled: `{str(payload.get('trading_verbs_enabled')).lower()}`",
        f"- Credential values redacted: `{str((payload.get('credential_diagnostics') or {}).get('values_redacted')).lower()}`",
        "",
        "## Adapter Request Plan",
        "",
        f"- Supported actions: `{', '.join(((payload.get('adapter_request_diagnostics') or {}).get('capability_matrix') or {}).get('supported_actions') or [])}`",
        f"- Ready plans: `{(payload.get('adapter_request_diagnostics') or {}).get('ready_plan_count')}`",
        f"- Blocked plans: `{(payload.get('adapter_request_diagnostics') or {}).get('blocked_plan_count')}`",
        "",
        "## Reconciliation",
        "",
        f"- Local live orders: `{payload.get('local_live_order_count')}`",
        f"- Exchange open orders: `{payload.get('exchange_open_order_count')}`",
        f"- Matched orders: `{payload.get('matched_order_count')}`",
        f"- Missing exchange orders: `{payload.get('missing_exchange_order_count')}`",
        f"- Extra exchange orders: `{payload.get('extra_exchange_order_count')}`",
        f"- User stream lifecycle events: `{payload.get('user_stream_event_count')}`",
        "",
        "## MM-2 Probe Status",
        "",
    ]
    for name, row in (payload.get("mm2_probe_status") or {}).items():
        lines.append(f"- `{name}`: `{row.get('status')}` - {row.get('detail')}")
    return "\n".join(lines) + "\n"


def _probe_observed(probe_evidence, name):
    value = (probe_evidence or {}).get(name)
    if isinstance(value, dict):
        return bool_value(value.get("passed") or value.get("observed") or value.get("ok"), False)
    return bool_value(value, False)


def _probe_detail(probe_evidence, name, fallback):
    value = (probe_evidence or {}).get(name)
    if isinstance(value, dict):
        return value.get("detail") or value.get("evidence") or fallback
    return fallback


def mm2_probe_status(payload, probe_evidence=None):
    probe_evidence = probe_evidence or {}
    events = payload.get("user_stream_lifecycle_events") or []
    event_types = Counter(row.get("transition") for row in events)
    cancel_observed = bool(event_types.get("canceled")) or _probe_observed(
        probe_evidence,
        "cancel_all_verification",
    )
    return {
        "heartbeat_dead_man": {
            "status": "observed" if _probe_observed(probe_evidence, "heartbeat_dead_man") else "pending_real_probe",
            "detail": _probe_detail(
                probe_evidence,
                "heartbeat_dead_man",
                "requires a real heartbeat-lapse drill with a far-from-mid order",
            ),
        },
        "min_size_tick_post_only": {
            "status": "observed" if _probe_observed(probe_evidence, "min_size_tick_post_only") else "pending_real_probe",
            "detail": _probe_detail(
                probe_evidence,
                "min_size_tick_post_only",
                "requires real preview/rejection or client-side validation evidence",
            ),
        },
        "tiny_two_sided_quote": {
            "status": "observed" if payload.get("matched_order_count", 0) >= 2 else "pending",
            "detail": "requires two matched local/exchange order records for one band",
        },
        "cancel_all_verification": {
            "status": "observed" if cancel_observed else "pending",
            "detail": _probe_detail(
                probe_evidence,
                "cancel_all_verification",
                "requires cancel-all command plus zero open-order confirmation",
            ),
        },
        "user_stream_lifecycle": {
            "status": "observed" if event_types else "pending",
            "detail": f"user stream lifecycle transitions: {dict(sorted(event_types.items()))}",
        },
        "balance_reserve_reconciliation": {
            "status": "observed" if payload.get("balances") else "pending",
            "detail": "requires account balance snapshot from read-only adapter",
        },
        "reward_rebate_reconciliation": {
            "status": "observed" if payload.get("rewards") else "pending_next_cycle",
            "detail": "requires next payout-cycle reward/rebate snapshot",
        },
    }


def numeric_sum(rows, key):
    total = 0.0
    for row in rows or []:
        value = maybe_float(row.get(key))
        if value is not None:
            total += value
    return round(total, 6)


def first_numeric(mapping, *keys):
    mapping = mapping or {}
    for key in keys:
        value = maybe_float(mapping.get(key))
        if value is not None:
            return value
    return None


def actual_reward_rebate_usdc(rewards):
    rewards = rewards or {}
    total = first_numeric(rewards, "total_usdc", "total_reward_usdc", "total_rewards_usdc")
    if total is not None:
        return total
    values = [
        first_numeric(rewards, "maker_rebate_usdc", "maker_rebate"),
        first_numeric(rewards, "reward_rebate_usdc", "rebate_usdc"),
        first_numeric(rewards, "liquidity_reward_usdc", "liquidity_rewards_usdc", "reward_usdc"),
    ]
    values = [value for value in values if value is not None]
    return round(sum(values), 6) if values else None


def balance_amount_usdc(balances, *extra_keys):
    return first_numeric(
        balances,
        *extra_keys,
        "cash",
        "available_cash",
        "available_usdc",
        "usdc",
        "USDC",
        "pUSD",
        "pusd",
        "collateral",
        "balance",
        "total_usdc",
    )


def build_financial_reconciliation(reconciliation, quote_rows, fill_rows):
    balances = reconciliation.get("balances") or {}
    rewards = reconciliation.get("rewards") or {}
    fees = reconciliation.get("fees") or {}
    redemption = reconciliation.get("redemption_status") or {}
    expected_rebate = numeric_sum(quote_rows, "expected_rebate_value")
    expected_reward_score = numeric_sum(quote_rows, "expected_reward_score")
    actual_reward = actual_reward_rebate_usdc(rewards)
    actual_fees = first_numeric(
        fees,
        "paid_usdc",
        "fees_paid_usdc",
        "fee_usdc",
        "maker_fee_usdc",
        "taker_fee_usdc",
        "total_usdc",
    )
    redemption_usdc = first_numeric(
        redemption,
        "redemption_usdc",
        "settlement_redemption_usdc",
        "redeemed_usdc",
        "claimable_usdc",
        "payout_usdc",
    )
    settlement_pnl = first_numeric(
        redemption,
        "settlement_pnl_usdc",
        "realized_pnl_usdc",
        "pnl_usdc",
        "net_pnl_usdc",
    )
    starting_balance = balance_amount_usdc(
        balances,
        "starting_balance_usdc",
        "starting_cash_usdc",
        "cash_before",
        "initial_cash_usdc",
    )
    ending_balance = balance_amount_usdc(
        balances,
        "ending_balance_usdc",
        "ending_cash_usdc",
        "cash_after",
        "final_cash_usdc",
    )
    if starting_balance is not None and ending_balance is not None:
        balance_delta = round(ending_balance - starting_balance, 6)
    else:
        balance_delta = None
    actual_total_pnl = None
    if settlement_pnl is not None:
        actual_total_pnl = settlement_pnl
        if actual_reward is not None:
            actual_total_pnl += actual_reward
        if actual_fees is not None:
            actual_total_pnl -= actual_fees
        actual_total_pnl = round(actual_total_pnl, 6)
    missing = []
    if starting_balance is None or ending_balance is None:
        missing.append("balance_delta")
    if actual_reward is None:
        missing.append("actual_reward_rebate")
    if actual_fees is None:
        missing.append("actual_fees")
    if redemption_usdc is None:
        missing.append("redemption_status")
    if settlement_pnl is None:
        missing.append("settlement_pnl")
    return {
        "expected_rebate_value_usdc": expected_rebate,
        "expected_reward_score": expected_reward_score,
        "actual_reward_rebate_usdc": actual_reward,
        "reward_rebate_delta_usdc": None if actual_reward is None else round(actual_reward - expected_rebate, 6),
        "actual_fees_usdc": actual_fees,
        "redemption_usdc": redemption_usdc,
        "settlement_pnl_usdc": settlement_pnl,
        "starting_balance_usdc": starting_balance,
        "ending_balance_usdc": ending_balance,
        "balance_delta_usdc": balance_delta,
        "actual_total_pnl_after_fees_incentives_usdc": actual_total_pnl,
        "fill_notional_usdc": round(
            sum(
                (maybe_float(row.get("fill_price")) or 0.0)
                * (maybe_float(row.get("fill_size")) or 0.0)
                for row in fill_rows or []
            ),
            6,
        ),
        "missing_evidence": missing,
        "complete": not missing,
    }


def build_pilot_report_payload(reconciliation, quote_rows, fill_rows, probe_status):
    fills = fill_rows or []
    financial = build_financial_reconciliation(reconciliation, quote_rows, fills)
    expected_rebate = numeric_sum(quote_rows, "expected_rebate_value")
    expected_reward_score = numeric_sum(quote_rows, "expected_reward_score")
    actual_reward = financial.get("actual_reward_rebate_usdc")
    markout_values = [
        maybe_float(row.get("markout_30m") or row.get("markout_30m_usdc"))
        for row in fills
    ]
    markout_values = [value for value in markout_values if value is not None]
    paper_quote_rows = [row for row in quote_rows if bool_value(row.get("quote_permission"), False)]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": reconciliation.get("generated_at_utc"),
        "run_id": reconciliation.get("run_id"),
        "target_date": reconciliation.get("target_date"),
        "status": reconciliation.get("status"),
        "live_fill_count": len(fills),
        "live_fill_size": numeric_sum(fills, "fill_size"),
        "live_notional_usdc": round(
            sum(
                (maybe_float(row.get("fill_price")) or 0.0)
                * (maybe_float(row.get("fill_size")) or 0.0)
                for row in fills
            ),
            6,
        ),
        "live_cancellation_count": sum(
            1 for row in reconciliation.get("user_stream_lifecycle_events") or [] if row.get("transition") == "canceled"
        ),
        "live_rejection_count": sum(
            1 for row in reconciliation.get("user_stream_lifecycle_events") or [] if row.get("transition") == "rejected"
        ),
        "paper_counterfactual_quote_count": len(paper_quote_rows),
        "paper_counterfactual_expected_rebate_value": expected_rebate,
        "paper_counterfactual_expected_reward_score": expected_reward_score,
        "actual_reward_rebate_usdc": actual_reward,
        "reward_rebate_delta_usdc": None if actual_reward is None else round(actual_reward - expected_rebate, 6),
        "markout_30m_count": len(markout_values),
        "markout_30m_mean": None if not markout_values else round(sum(markout_values) / len(markout_values), 6),
        "probe_status": probe_status,
        "paper_counterfactual_available": bool(paper_quote_rows),
        "reward_rebate_reconciled": actual_reward is not None,
        "financial_reconciliation": financial,
        "financial_reconciliation_complete": financial.get("complete"),
        "markout_reconciled": bool(markout_values),
    }
    missing = []
    if not fills:
        missing.append("live_fills")
    if not paper_quote_rows:
        missing.append("paper_counterfactual_quotes")
    if actual_reward is None:
        missing.append("actual_reward_rebate")
    if not markout_values:
        missing.append("markout_30m")
    missing.extend(f"financial:{item}" for item in financial.get("missing_evidence") or [])
    payload["missing_evidence"] = missing
    payload["evidence_complete"] = not missing
    return payload


def render_pilot_report(payload):
    lines = [
        "# MM-2 Pilot Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run: `{payload.get('run_id')}`",
        f"Status: `{payload.get('status')}`",
        f"Evidence complete: `{str(payload.get('evidence_complete')).lower()}`",
        "",
        "## Live Execution",
        "",
        f"- Fill count: `{payload.get('live_fill_count')}`",
        f"- Fill size: `{payload.get('live_fill_size')}`",
        f"- Fill notional: `{payload.get('live_notional_usdc')}`",
        f"- Cancellations: `{payload.get('live_cancellation_count')}`",
        f"- Rejections: `{payload.get('live_rejection_count')}`",
        "",
        "## Paper Counterfactual",
        "",
        f"- Quote rows: `{payload.get('paper_counterfactual_quote_count')}`",
        f"- Expected rebate value: `{payload.get('paper_counterfactual_expected_rebate_value')}`",
        f"- Expected reward score: `{payload.get('paper_counterfactual_expected_reward_score')}`",
        "",
        "## Reconciliation",
        "",
        f"- Actual reward/rebate: `{payload.get('actual_reward_rebate_usdc')}`",
        f"- Reward/rebate delta: `{payload.get('reward_rebate_delta_usdc')}`",
        f"- 30m markout mean: `{payload.get('markout_30m_mean')}`",
        f"- Missing evidence: `{', '.join(payload.get('missing_evidence') or []) or '-'}`",
        "",
        "## Financial Reconciliation",
        "",
        f"- Complete: `{str(payload.get('financial_reconciliation_complete')).lower()}`",
        f"- Actual fees: `{(payload.get('financial_reconciliation') or {}).get('actual_fees_usdc')}`",
        f"- Redemption: `{(payload.get('financial_reconciliation') or {}).get('redemption_usdc')}`",
        f"- Settlement P&L: `{(payload.get('financial_reconciliation') or {}).get('settlement_pnl_usdc')}`",
        f"- Balance delta: `{(payload.get('financial_reconciliation') or {}).get('balance_delta_usdc')}`",
        f"- Actual total P&L after fees/incentives: `{(payload.get('financial_reconciliation') or {}).get('actual_total_pnl_after_fees_incentives_usdc')}`",
    ]
    return "\n".join(lines) + "\n"
