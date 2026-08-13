"""Report and reconciliation summaries for the MM exchange adapter."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import math
import re
from urllib.parse import parse_qs, urlsplit

from weather.market.mm_policy import bool_value, maybe_float


SCHEMA_VERSION = "mm_exchange_adapter_v0.2"
EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
CONDITION_ID_RE = re.compile(r"^0x[0-9a-f]{64}$")
TX_HASH_RE = re.compile(r"^0x[0-9a-f]{64}$")
FEE_PRECISION_USDC = Decimal("0.00001")
CONFIRMED_TRADE_HASH_FIELDS = (
    "trade_id",
    "transaction_hash",
    "lifecycle_key",
    "exchange_order_id",
    "maker_address",
    "condition_id",
    "clob_token_id",
    "liquidity_role",
    "side",
    "fill_price",
    "fill_size",
    "fee_rate_bps",
    "official_trade_status",
)


def _exact_query_url(value, *, scheme, host, path, expected_query):
    try:
        parsed = urlsplit(str(value or ""))
        query = parse_qs(parsed.query, keep_blank_values=True)
    except (TypeError, ValueError):
        return False
    normalized_query = {
        key: [str(item).lower() for item in values]
        for key, values in query.items()
    }
    normalized_expected = {
        key: [str(item).lower() for item in values]
        for key, values in expected_query.items()
    }
    return all((
        parsed.scheme.lower() == scheme,
        parsed.netloc.lower() == host,
        parsed.path == path,
        not parsed.fragment,
        normalized_query == normalized_expected,
    ))


def confirmed_trade_set_sha256(fill_rows):
    """Hash the exact confirmed-trade identity and fee-calculation inputs."""

    normalized = [
        {key: row.get(key) for key in CONFIRMED_TRADE_HASH_FIELDS}
        for row in fill_rows or []
        if isinstance(row, dict)
    ]
    encoded_rows = [
        json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
        for row in normalized
    ]
    encoded = ("[" + ",".join(sorted(encoded_rows)) + "]").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _calculated_trade_fees(fill_rows, maker_address, condition_id):
    total = Decimal("0")
    blockers = []
    seen_fill_keys = set()
    for row in fill_rows or []:
        if not isinstance(row, dict):
            blockers.append("actual_fee_fill_row_invalid")
            continue
        trade_id = str(row.get("trade_id") or "").strip()
        transaction_hash = str(row.get("transaction_hash") or "").strip()
        role = str(row.get("liquidity_role") or "").strip().upper()
        row_maker = str(row.get("maker_address") or "").strip().lower()
        row_condition = str(row.get("condition_id") or "").strip().lower()
        token_id = str(row.get("clob_token_id") or "").strip()
        status = str(row.get("official_trade_status") or "").strip().upper()
        fill_key = (
            trade_id,
            str(row.get("exchange_order_id") or row.get("lifecycle_key") or "").strip(),
            token_id,
        )
        try:
            price = Decimal(str(row.get("fill_price")))
            size = Decimal(str(row.get("fill_size")))
            fee_rate_bps = Decimal(str(row.get("fee_rate_bps")))
        except (InvalidOperation, TypeError, ValueError):
            blockers.append("actual_fee_fill_numeric_invalid")
            continue
        if (
            not trade_id
            or fill_key in seen_fill_keys
            or not TX_HASH_RE.fullmatch(transaction_hash.lower())
            or status != "CONFIRMED"
            or role not in {"MAKER", "TAKER"}
            or row_maker != maker_address
            or row_condition != condition_id
            or not token_id
        ):
            blockers.append("actual_fee_confirmed_trade_scope_invalid")
            continue
        seen_fill_keys.add(fill_key)
        if not all((
            price.is_finite(),
            size.is_finite(),
            fee_rate_bps.is_finite(),
            Decimal("0") < price < Decimal("1"),
            size > 0,
            Decimal("0") <= fee_rate_bps <= Decimal("10000"),
        )):
            blockers.append("actual_fee_fill_numeric_invalid")
            continue
        if role == "TAKER":
            rate = fee_rate_bps / Decimal("10000")
            fee = size * rate * price * (Decimal("1") - price)
            total += fee.quantize(FEE_PRECISION_USDC, rounding=ROUND_HALF_UP)
    return total, blockers


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
        "## Live Readiness Notes",
        "",
        *[
            f"- `{row.get('code')}`: `{row.get('severity')}` - {row.get('detail')}"
            for row in (payload.get("adapter_request_diagnostics") or {}).get("live_readiness_notes") or []
        ],
        "" if (payload.get("adapter_request_diagnostics") or {}).get("live_readiness_notes") else "- No platform-specific notes recorded.",
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


def _open_order_count_after_cancel(value):
    if not isinstance(value, dict):
        return None
    for key in ("open_order_count_after", "open_orders_count_after", "post_cancel_open_order_count"):
        if key in value:
            count = maybe_float(value.get(key))
            return None if count is None else int(count)
    for key in ("open_orders_after_cancel_all", "open_orders_after"):
        rows = value.get(key)
        if isinstance(rows, list):
            return len(rows)
    return None


def _cancel_all_probe_status(probe_evidence):
    value = (probe_evidence or {}).get("cancel_all_verification")
    fallback = "requires cancel-all command plus zero open-order confirmation"
    if not isinstance(value, dict):
        return {
            "status": "pending",
            "detail": fallback,
        }
    open_count = _open_order_count_after_cancel(value)
    zero_confirmed = bool_value(value.get("zero_open_orders_confirmed"), False) or open_count == 0
    request_observed = (
        bool_value(value.get("cancel_all_sent") or value.get("cancel_all_requested"), False)
        or value.get("cancel_all_response") not in (None, "", {})
        or value.get("canceled_order_ids") is not None
    )
    if _probe_observed(probe_evidence, "cancel_all_verification") and zero_confirmed and request_observed:
        return {
            "status": "observed",
            "detail": _probe_detail(probe_evidence, "cancel_all_verification", "cancel-all verified with zero open orders"),
        }
    if _probe_observed(probe_evidence, "cancel_all_verification") and not zero_confirmed:
        return {
            "status": "pending_zero_open_order_confirmation",
            "detail": "cancel-all evidence is present but does not prove zero open orders afterward",
        }
    return {
        "status": "pending",
        "detail": _probe_detail(probe_evidence, "cancel_all_verification", fallback),
    }


def mm2_probe_status(payload, probe_evidence=None):
    probe_evidence = probe_evidence or {}
    events = payload.get("user_stream_lifecycle_events") or []
    event_types = Counter(row.get("transition") for row in events)
    cancel_all = _cancel_all_probe_status(probe_evidence)
    rebate_reconciliation = maker_rebate_reconciliation(payload.get("rewards") or {})
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
            "status": cancel_all["status"],
            "detail": cancel_all["detail"],
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
            "status": "observed" if rebate_reconciliation.get("complete") else "pending_next_cycle",
            "detail": (
                "exact next-cycle per-condition maker rebate reconciled"
                if rebate_reconciliation.get("complete")
                else "requires completed next-cycle /rebates/current evidence for the exact maker, date, and condition"
            ),
        },
    }


def numeric_sum(rows, key):
    total = 0.0
    for row in rows or []:
        value = maybe_float(row.get(key))
        if value is not None and math.isfinite(value):
            total += value
    return round(total, 6)


def first_numeric(mapping, *keys):
    mapping = mapping or {}
    for key in keys:
        value = maybe_float(mapping.get(key))
        if value is not None and math.isfinite(value):
            return value
    return None


def maker_rebate_reconciliation(rewards):
    """Validate exact next-cycle maker rebate evidence for the pilot market."""

    evidence = (rewards or {}).get("maker_rebate_evidence")
    if not isinstance(evidence, dict):
        return {
            "complete": False,
            "actual_maker_rebate_usdc": None,
            "blockers": ["maker_rebate_evidence_missing"],
        }
    query_date = str(evidence.get("query_date") or "")
    maker_address = str(evidence.get("maker_address") or "").lower()
    condition_id = str(evidence.get("condition_id") or "").lower()
    queried_at = None
    try:
        queried_at = datetime.fromisoformat(
            str(evidence.get("queried_at_utc") or "").replace("Z", "+00:00")
        )
        if queried_at.tzinfo is None:
            queried_at = None
        else:
            queried_at = queried_at.astimezone(timezone.utc)
    except ValueError:
        queried_at = None
    blockers = []
    if evidence.get("status") != "OBSERVED":
        blockers.append("maker_rebate_endpoint_not_observed")
    if evidence.get("query_scope") != "exact_maker_date":
        blockers.append("maker_rebate_query_scope_not_exact")
    if evidence.get("http_status") != 200:
        blockers.append("maker_rebate_http_status_invalid")
    if len(str(evidence.get("response_sha256") or "")) != 64:
        blockers.append("maker_rebate_response_hash_missing")
    request_url = str(evidence.get("request_url") or "")
    if not _exact_query_url(
        request_url,
        scheme="https",
        host="clob.polymarket.com",
        path="/rebates/current",
        expected_query={
            "date": [query_date],
            "maker_address": [maker_address],
        },
    ):
        blockers.append("maker_rebate_request_url_invalid")
    if not evidence.get("payout_cycle_complete"):
        blockers.append("maker_rebate_payout_cycle_incomplete")
    parsed_date = None
    try:
        parsed_date = date.fromisoformat(query_date)
        query_date_valid = parsed_date.isoformat() == query_date
    except ValueError:
        query_date_valid = False
    if (
        queried_at is None
        or not query_date_valid
        or parsed_date is None
        or queried_at.date() <= parsed_date
    ):
        blockers.append("maker_rebate_query_not_after_payout_day")
    if (
        not query_date_valid
        or not EVM_ADDRESS_RE.fullmatch(maker_address)
        or not CONDITION_ID_RE.fullmatch(condition_id)
    ):
        blockers.append("maker_rebate_scope_incomplete")
    rows = evidence.get("rows")
    if not isinstance(rows, list):
        blockers.append("maker_rebate_rows_invalid")
        rows = []
    selected_values = []
    ignored_condition_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            blockers.append("maker_rebate_row_invalid")
            continue
        if (
            str(row.get("date") or "") != query_date
            or str(row.get("maker_address") or "").lower() != maker_address
        ):
            blockers.append("maker_rebate_row_scope_mismatch")
            continue
        row_condition = str(row.get("condition_id") or "").lower()
        asset_address = str(row.get("asset_address") or "").lower()
        amount = maybe_float(row.get("rebated_fees_usdc"))
        if (
            amount is None
            or not math.isfinite(amount)
            or amount < 0
            or not CONDITION_ID_RE.fullmatch(row_condition)
            or not EVM_ADDRESS_RE.fullmatch(asset_address)
        ):
            blockers.append("maker_rebate_row_amount_invalid")
            continue
        if row_condition == condition_id:
            selected_values.append(amount)
        else:
            ignored_condition_rows += 1
    blockers = sorted(set(blockers))
    return {
        "complete": not blockers,
        "query_date": query_date or None,
        "maker_address": maker_address or None,
        "condition_id": condition_id or None,
        "payout_cycle_complete": bool(evidence.get("payout_cycle_complete")),
        "selected_row_count": len(selected_values),
        "ignored_other_condition_row_count": ignored_condition_rows,
        "actual_maker_rebate_usdc": (
            round(sum(selected_values), 6) if not blockers else None
        ),
        "blockers": blockers,
    }


def actual_reward_rebate_usdc(rewards):
    """Compatibility facade returning only fully reconciled maker rebates."""

    return maker_rebate_reconciliation(rewards).get("actual_maker_rebate_usdc")


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


def position_reconciliation(reconciliation):
    """Require an observed exact-wallet/condition position query, including empty."""

    evidence = reconciliation.get("position_evidence")
    positions = reconciliation.get("positions")
    blockers = []
    if not isinstance(evidence, dict):
        evidence = {}
        blockers.append("position_evidence_missing")
    maker_address = str(evidence.get("maker_address") or "").lower()
    condition_id = str(evidence.get("condition_id") or "").lower()
    evidence_rows = evidence.get("rows")
    if evidence.get("status") != "OBSERVED":
        blockers.append("position_endpoint_not_observed")
    if evidence.get("query_scope") != "exact_maker_condition":
        blockers.append("position_scope_not_exact")
    if evidence.get("http_status") != 200:
        blockers.append("position_http_status_invalid")
    if len(str(evidence.get("response_sha256") or "")) != 64:
        blockers.append("position_response_hash_missing")
    position_url = str(evidence.get("request_url") or "")
    if not _exact_query_url(
        position_url,
        scheme="https",
        host="data-api.polymarket.com",
        path="/positions",
        expected_query={
            "user": [maker_address],
            "market": [condition_id],
            "sizeThreshold": ["0"],
            "limit": ["500"],
            "offset": ["0"],
        },
    ):
        blockers.append("position_request_url_invalid")
    if (
        not EVM_ADDRESS_RE.fullmatch(maker_address)
        or not CONDITION_ID_RE.fullmatch(condition_id)
    ):
        blockers.append("position_scope_invalid")
    if not isinstance(positions, list) or not isinstance(evidence_rows, list):
        blockers.append("position_rows_invalid")
        positions = []
        evidence_rows = []
    elif positions != evidence_rows:
        blockers.append("position_rows_do_not_match_reconciliation")

    def position_is_zero(row):
        if not isinstance(row, dict):
            return False
        amount = first_numeric(row, "size", "quantity", "balance", "amount")
        return amount is not None and abs(amount) <= 0.00000001

    blockers = sorted(set(blockers))
    return {
        "complete": not blockers,
        "maker_address": maker_address or None,
        "condition_id": condition_id or None,
        "row_count": len(positions),
        "ending_positions_zero": not blockers and all(
            position_is_zero(row) for row in positions
        ),
        "blockers": blockers,
    }


def actual_fee_reconciliation(fees, fill_rows):
    """Accept only observed all-trade fee evidence, never a configured fee rate."""

    evidence = (fees or {}).get("actual_fee_evidence")
    blockers = []
    if not isinstance(evidence, dict):
        evidence = {}
        blockers.append("actual_fee_evidence_missing")
    maker_address = str(evidence.get("maker_address") or "").lower()
    condition_id = str(evidence.get("condition_id") or "").lower()
    paid_usdc = maybe_float(evidence.get("paid_usdc"))
    observed_fill_count = maybe_float(evidence.get("observed_fill_count"))
    if evidence.get("status") != "OBSERVED":
        blockers.append("actual_fee_evidence_not_observed")
    if evidence.get("coverage") != "all_pilot_trades_and_exits":
        blockers.append("actual_fee_coverage_incomplete")
    if evidence.get("includes_taker_and_flattening_fees") is not True:
        blockers.append("actual_fee_basis_incomplete")
    if evidence.get("calculation_basis") != "confirmed_trade_events":
        blockers.append("actual_fee_calculation_basis_invalid")
    if evidence.get("fee_formula") != "shares_x_rate_x_price_x_one_minus_price":
        blockers.append("actual_fee_formula_invalid")
    if evidence.get("maker_fees_zero") is not True:
        blockers.append("actual_fee_maker_rule_invalid")
    if evidence.get("precision_decimal_places") != 5:
        blockers.append("actual_fee_precision_invalid")
    reported_trade_hash = str(evidence.get("confirmed_trade_set_sha256") or "")
    calculated_trade_hash = confirmed_trade_set_sha256(fill_rows)
    if len(reported_trade_hash) != 64:
        blockers.append("actual_fee_trade_evidence_hash_missing")
    elif reported_trade_hash != calculated_trade_hash:
        blockers.append("actual_fee_trade_evidence_hash_mismatch")
    if (
        not EVM_ADDRESS_RE.fullmatch(maker_address)
        or not CONDITION_ID_RE.fullmatch(condition_id)
    ):
        blockers.append("actual_fee_scope_invalid")
    if paid_usdc is None or not math.isfinite(paid_usdc) or paid_usdc < 0:
        blockers.append("actual_fee_amount_invalid")
    calculated_fees, calculation_blockers = _calculated_trade_fees(
        fill_rows,
        maker_address,
        condition_id,
    )
    blockers.extend(calculation_blockers)
    if paid_usdc is not None and math.isfinite(paid_usdc):
        reported_fee = Decimal(str(paid_usdc)).quantize(
            FEE_PRECISION_USDC,
            rounding=ROUND_HALF_UP,
        )
        if reported_fee != calculated_fees:
            blockers.append("actual_fee_amount_mismatch")
    if (
        observed_fill_count is None
        or not math.isfinite(observed_fill_count)
        or not observed_fill_count.is_integer()
        or int(observed_fill_count) != len(fill_rows or [])
    ):
        blockers.append("actual_fee_fill_count_mismatch")
    blockers = sorted(set(blockers))
    return {
        "complete": not blockers,
        "maker_address": maker_address or None,
        "condition_id": condition_id or None,
        "observed_fill_count": (
            None if observed_fill_count is None else int(observed_fill_count)
        ),
        "actual_fees_usdc": None if blockers else round(paid_usdc, 6),
        "calculated_fees_usdc": float(calculated_fees),
        "confirmed_trade_set_sha256": calculated_trade_hash,
        "blockers": blockers,
    }


def build_financial_reconciliation(reconciliation, quote_rows, fill_rows):
    balances = reconciliation.get("balances") or {}
    rewards = reconciliation.get("rewards") or {}
    fees = reconciliation.get("fees") or {}
    redemption = reconciliation.get("redemption_status") or {}
    expected_rebate_values = []
    for row in fill_rows or []:
        value = first_numeric(
            row,
            "maker_rebate_estimate_usdc",
            "expected_rebate_value",
        )
        if value is not None:
            expected_rebate_values.append(value)
    expected_rebate = (
        round(sum(expected_rebate_values), 6) if expected_rebate_values else None
    )
    expected_reward_score = numeric_sum(quote_rows, "expected_reward_score")
    rebate_reconciliation = maker_rebate_reconciliation(rewards)
    actual_reward = rebate_reconciliation.get("actual_maker_rebate_usdc")
    fee_reconciliation = actual_fee_reconciliation(fees, fill_rows)
    actual_fees = fee_reconciliation.get("actual_fees_usdc")
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
    starting_balance = first_numeric(
        balances,
        "starting_balance_usdc",
        "starting_cash_usdc",
        "cash_before",
        "initial_cash_usdc",
    )
    ending_balance = first_numeric(
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
    identity = (
        reconciliation.get("financial_identity")
        or redemption.get("financial_identity")
        or {}
    )
    external_cash_flows = first_numeric(identity, "external_cash_flows_usdc")
    positions_reconciled = position_reconciliation(reconciliation)
    observed_positions_zero = positions_reconciled.get("ending_positions_zero") is True
    financial_scope_consistent = (
        rebate_reconciliation.get("maker_address")
        == fee_reconciliation.get("maker_address")
        == positions_reconciled.get("maker_address")
        and rebate_reconciliation.get("condition_id")
        == fee_reconciliation.get("condition_id")
        == positions_reconciled.get("condition_id")
        and rebate_reconciliation.get("maker_address") is not None
        and rebate_reconciliation.get("condition_id") is not None
    )
    identity_inputs_verified = all((
        identity.get("ending_positions_zero") is True,
        observed_positions_zero,
        identity.get("settlement_pnl_excludes_fees_and_incentives") is True,
        external_cash_flows is not None,
        starting_balance is not None,
        ending_balance is not None,
        settlement_pnl is not None,
        actual_reward is not None,
        actual_fees is not None,
        financial_scope_consistent,
    ))
    actual_total_pnl = None
    identity_delta = None
    if identity_inputs_verified:
        actual_total_pnl = settlement_pnl
        actual_total_pnl += actual_reward
        actual_total_pnl -= actual_fees
        actual_total_pnl = round(actual_total_pnl, 6)
        expected_balance_delta = round(actual_total_pnl + external_cash_flows, 6)
        identity_delta = round(balance_delta - expected_balance_delta, 6)
        if abs(identity_delta) > 0.00001:
            actual_total_pnl = None
    missing = []
    if starting_balance is None or ending_balance is None:
        missing.append("balance_delta")
    if not rebate_reconciliation.get("complete"):
        missing.append("actual_maker_rebate_reconciliation")
    if actual_fees is None:
        missing.append("actual_fees")
    if not positions_reconciled.get("complete"):
        missing.append("position_reconciliation")
    elif not observed_positions_zero:
        missing.append("ending_positions_nonzero")
    if not financial_scope_consistent:
        missing.append("financial_scope_mismatch")
    if redemption_usdc is None:
        missing.append("redemption_status")
    if settlement_pnl is None:
        missing.append("settlement_pnl")
    if expected_rebate is None and fill_rows:
        missing.append("live_fill_rebate_estimate")
    if not identity_inputs_verified:
        missing.append("financial_identity_inputs")
    elif actual_total_pnl is None:
        missing.append("financial_identity_mismatch")
    return {
        "expected_live_fill_rebate_usdc": expected_rebate,
        "expected_reward_score": expected_reward_score,
        "actual_maker_rebate_usdc": actual_reward,
        "maker_rebate_delta_usdc": (
            None
            if actual_reward is None or expected_rebate is None
            else round(actual_reward - expected_rebate, 6)
        ),
        "maker_rebate_reconciliation": rebate_reconciliation,
        "actual_fees_usdc": actual_fees,
        "actual_fee_reconciliation": fee_reconciliation,
        "redemption_usdc": redemption_usdc,
        "settlement_pnl_usdc": settlement_pnl,
        "starting_balance_usdc": starting_balance,
        "ending_balance_usdc": ending_balance,
        "balance_delta_usdc": balance_delta,
        "external_cash_flows_usdc": external_cash_flows,
        "ending_positions_zero_observed": observed_positions_zero,
        "position_reconciliation": positions_reconciled,
        "financial_scope_consistent": financial_scope_consistent,
        "financial_identity_inputs_verified": identity_inputs_verified,
        "financial_identity_delta_usdc": identity_delta,
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
    actual_reward = financial.get("actual_maker_rebate_usdc")
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
        "actual_maker_rebate_usdc": actual_reward,
        "live_fill_maker_rebate_delta_usdc": financial.get("maker_rebate_delta_usdc"),
        "markout_30m_count": len(markout_values),
        "markout_30m_mean": None if not markout_values else round(sum(markout_values) / len(markout_values), 6),
        "probe_status": probe_status,
        "paper_counterfactual_available": bool(paper_quote_rows),
        "maker_rebate_reconciled": bool(
            (financial.get("maker_rebate_reconciliation") or {}).get("complete")
        ),
        "financial_reconciliation": financial,
        "financial_reconciliation_complete": financial.get("complete"),
        "markout_reconciled": bool(markout_values),
    }
    missing = []
    if not fills:
        missing.append("live_fills")
    elif any(str(row.get("liquidity_role") or "").upper() != "MAKER" for row in fills):
        missing.append("maker_liquidity_role")
    if fills and any(
        not row.get("exchange_order_id")
        or not row.get("trade_id")
        or not row.get("transaction_hash")
        or str(row.get("official_trade_status") or "").upper() != "CONFIRMED"
        for row in fills
    ):
        missing.append("confirmed_fill_identity")
    if not paper_quote_rows:
        missing.append("paper_counterfactual_quotes")
    if actual_reward is None:
        missing.append("actual_maker_rebate")
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
        f"- Actual maker rebate: `{payload.get('actual_maker_rebate_usdc')}`",
        f"- Live-fill maker-rebate delta: `{payload.get('live_fill_maker_rebate_delta_usdc')}`",
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
