"""Pure reconciliation of supplied International incentive and wallet evidence.

Normalized inputs are not an API response or proof that a network query happened.
The caller owns capture and normalization; this module checks their scope and
matches explicit transfer references. See docs/operations/maker-incentive-payments.md.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

from weather.schema_registry import schema_version

PROGRAMS = ("maker_rebate", "liquidity_reward")
MICRO = Decimal("0.000001")
ZERO = Decimal(0)
ADDRESS = re.compile(r"0x[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
CONDITION = re.compile(r"0x[0-9a-f]{64}")
ASSET = re.compile(r"eip155:137/erc20:0x[0-9a-f]{40}")
MAX_ROWS = 1024


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _utc(value):
    _require(isinstance(value, str) and len(value) <= 40, "timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(parsed.tzinfo is not None, "timestamp_naive")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("timestamp_invalid") from exc


def _amount(value, *, payment=False):
    _require(type(value) in (str, int) and len(str(value)) <= 40, "amount_invalid")
    try:
        amount = Decimal(value)
        _require(amount.is_finite() and ZERO <= amount <= Decimal("1000000000"), "amount_invalid")
        _require(amount.as_tuple().exponent >= -12, "amount_precision_invalid")
        _require(not payment or amount == amount.quantize(MICRO), "payment_precision_invalid")
        return amount
    except InvalidOperation as exc:
        raise ValueError("amount_invalid") from exc


def _rows(payload, name):
    rows = payload.get(name)
    _require(isinstance(rows, list) and len(rows) <= MAX_ROWS, name + "_invalid")
    _require(all(isinstance(row, dict) for row in rows), name + "_invalid")
    identifiers = [row.get("id") for row in rows]
    _require(all(isinstance(key, str) and 0 < len(key) <= 160 for key in identifiers), name + "_id_invalid")
    _require(len(set(identifiers)) == len(identifiers), name + "_duplicate_id")
    for row in rows:
        _require(bool(HASH.fullmatch(str(row.get("source_sha256", "")))), name + "_source_hash_invalid")
    return rows


def _transfer(row):
    tx = row.get("transaction_hash")
    index = row.get("log_index")
    _require(isinstance(tx, str) and bool(CONDITION.fullmatch(tx)), "transfer_hash_invalid")
    _require(type(index) is int and 0 <= index < 1000000, "transfer_log_index_invalid")
    return tx, index


def _scope(payload):
    scope = payload.get("scope")
    _require(isinstance(scope, dict) and set(scope) == {"maker_address", "asset", "query_date", "condition_id"}, "scope_invalid")
    _require(bool(ADDRESS.fullmatch(str(scope["maker_address"]))), "account_invalid")
    _require(bool(ASSET.fullmatch(str(scope["asset"]))), "asset_invalid")
    _require(scope["condition_id"] is None or bool(CONDITION.fullmatch(str(scope["condition_id"]))), "condition_invalid")
    day = date.fromisoformat(scope["query_date"])
    _require(day.isoformat() == scope["query_date"], "query_date_invalid")
    start = datetime.combine(day, time(), timezone.utc)
    return scope, start


def _queries(payload, scope, start, blockers):
    queries = payload.get("queries")
    _require(isinstance(queries, dict) and set(queries) == set(PROGRAMS), "programme_queries_invalid")
    latest = start
    for program, query in queries.items():
        _require(isinstance(query, dict) and query.get("scope") == scope, "programme_query_scope_mismatch")
        for name in ("earnings_sha256", "distributions_sha256", "rules_sha256"):
            _require(bool(HASH.fullmatch(str(query.get(name, "")))), "programme_query_source_hash_invalid")
        due, observed = _utc(query.get("payout_due_at_utc")), _utc(query.get("queried_at_utc"))
        _require(due >= start + timedelta(days=1), "payout_deadline_precedes_period_end")
        latest = max(latest, observed)
        if not (query.get("status") == "OBSERVED" and query.get("earnings_complete") is True
                and query.get("distributions_complete") is True and query.get("payout_cycle_complete") is True
                and observed >= due):
            blockers.append(program + "_query_incomplete")
    wallet = payload.get("wallet_query")
    _require(isinstance(wallet, dict) and wallet.get("maker_address") == scope["maker_address"]
             and wallet.get("asset") == scope["asset"], "wallet_query_scope_mismatch")
    _require(bool(HASH.fullmatch(str(wallet.get("source_sha256", "")))), "wallet_query_source_hash_invalid")
    first, last = _utc(wallet.get("from_utc")), _utc(wallet.get("through_utc"))
    _require(first <= last, "wallet_query_interval_invalid")
    if not (wallet.get("status") == "OBSERVED" and wallet.get("complete") is True
            and first <= start and last >= latest):
        blockers.append("wallet_query_incomplete")
    return first, last


def _reconcile(payload):
    _require(isinstance(payload, dict) and payload.get("schema_version") == schema_version("mm_incentive_payment_evidence"), "payment_evidence_version_unsupported")
    _require(payload.get("platform") == "polymarket_global", "platform_not_international")
    scope, start = _scope(payload)
    blockers = []
    first, last = _queries(payload, scope, start, blockers)
    earnings, distributions, credits = (_rows(payload, name) for name in ("earnings", "distributions", "wallet_credits"))
    earned, natural_keys = {}, set()
    accrued = dict.fromkeys(PROGRAMS, ZERO)
    for row in earnings:
        program, condition = row.get("program"), row.get("condition_id")
        _require(program in PROGRAMS and row.get("maker_address") == scope["maker_address"]
                 and row.get("asset") == scope["asset"] and row.get("query_date") == scope["query_date"], "earning_scope_mismatch")
        _require(condition is None or bool(CONDITION.fullmatch(str(condition))), "earning_condition_invalid")
        _require(scope["condition_id"] is None or condition in (None, scope["condition_id"]), "earning_condition_mismatch")
        natural_key = program, condition
        _require(natural_key not in natural_keys, "earning_duplicate_scope")
        natural_keys.add(natural_key)
        amount = _amount(row.get("amount"))
        earned[row["id"]] = (program, condition, amount)
        if scope["condition_id"] is not None and condition is None:
            blockers.append("portfolio_earning_not_attributable_to_condition")
        else:
            accrued[program] += amount
    wallets = {}
    for row in credits:
        transfer = _transfer(row)
        _require(transfer not in wallets, "wallet_transfer_counted_twice")
        _require(row.get("maker_address") == scope["maker_address"] and row.get("asset") == scope["asset"], "wallet_credit_scope_mismatch")
        amount = _amount(row.get("amount"), payment=True)
        _require(amount > 0, "wallet_credit_not_positive")
        observed = _utc(row.get("confirmed_at_utc"))
        _require(first <= observed <= last, "wallet_credit_outside_query")
        wallets[transfer] = row, amount
    claimed = defaultdict(lambda: ZERO)
    transfers = defaultdict(list)
    distribution_keys = set()
    for row in distributions:
        earning = earned.get(row.get("earning_id"))
        _require(earning is not None, "distribution_earning_missing")
        program, condition, amount = earning
        _require(row.get("program") == program and row.get("condition_id") == condition
                 and row.get("query_date") == scope["query_date"] and row.get("maker_address") == scope["maker_address"]
                 and row.get("asset") == scope["asset"], "distribution_scope_mismatch")
        transfer = _transfer(row)
        distribution_key = row["earning_id"], transfer
        _require(distribution_key not in distribution_keys, "distribution_duplicate_transfer_allocation")
        distribution_keys.add(distribution_key)
        paid = _amount(row.get("amount"), payment=True)
        _require(paid > 0, "distribution_not_positive")
        claimed[row["earning_id"]] += paid
        _require(claimed[row["earning_id"]] <= amount.quantize(MICRO, rounding=ROUND_HALF_UP), "distribution_exceeds_accrual")
        transfers[transfer].append((row, paid))
    paid = dict.fromkeys(PROGRAMS, ZERO)
    matched, unresolved = [], []
    for transfer, allocations in transfers.items():
        programs = {row["program"] for row, _ in allocations}
        _require(len(programs) == 1, "wallet_credit_claimed_by_multiple_programmes")
        wallet = wallets.get(transfer)
        total = sum((amount for _, amount in allocations), ZERO)
        reason = ("wallet_credit_missing" if wallet is None else
                  "wallet_credit_not_confirmed" if wallet[0].get("status") != "CONFIRMED" else
                  "wallet_credit_amount_mismatch" if total != wallet[1] else None)
        if reason:
            blockers.append(reason)
            unresolved.extend(row["id"] for row, _ in allocations)
            continue
        for row, amount in allocations:
            if scope["condition_id"] is not None and row["condition_id"] is None:
                blockers.append("portfolio_payment_not_attributable_to_condition")
                unresolved.append(row["id"])
            else:
                paid[row["program"]] += amount
                matched.append(row["id"])
    unallocated = [row["id"] for key, (row, _) in wallets.items() if key not in transfers]
    if unallocated:
        blockers.append("wallet_credits_without_distribution_attribution")
    estimates = payload.get("estimates", {})
    _require(isinstance(estimates, dict) and set(estimates) <= set(PROGRAMS), "estimates_invalid")
    complete = not blockers
    programs = {}
    for program in PROGRAMS:
        programs[program] = {
            "estimated_amount": str(_amount(estimates[program])) if program in estimates else None,
            "accrued_amount": str(accrued[program]),
            "matched_paid_amount": format(paid[program], ".6f"),
            "paid_amount": format(paid[program], ".6f") if complete else None,
            "unpaid_accrual_amount": str(max(ZERO, accrued[program] - paid[program])),
            "rounding_residual_amount": str(max(ZERO, paid[program] - accrued[program])),
            "completed_zero": complete and paid[program] == 0,
        }
    return {
        "schema_version": schema_version("mm_incentive_payment_reconciliation"),
        "scope": dict(scope), "complete": complete, "programs": programs,
        "matched_distribution_ids": sorted(matched), "unresolved_distribution_ids": sorted(unresolved),
        "unallocated_wallet_credit_ids": sorted(unallocated), "blockers": sorted(set(blockers)),
        "source_evidence_independently_verified": False, "live_permission": False,
    }


def reconcile_incentive_payments(payload):
    """Match supplied records without I/O or granting any execution permission.

    Missing, partial and unsupported evidence cannot produce paid income. A
    complete empty query can establish zero; positive unpaid accrual stays
    separate from payments. Callers must retain and qualify the source records.
    """
    try:
        with localcontext(Context(prec=40, rounding=ROUND_HALF_UP)):
            return _reconcile(payload)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {
            "schema_version": schema_version("mm_incentive_payment_reconciliation"),
            "complete": False, "programs": {}, "blockers": [str(exc)],
            "source_evidence_independently_verified": False, "live_permission": False,
        }
