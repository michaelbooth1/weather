"""Read selected-run trading and accounting reports for the operator UI."""

from __future__ import annotations

import math
from pathlib import Path

from weather.market.mm_exchange_reports import INCENTIVE_CASH_ASSET
from weather.reporting.market.operator_evidence import freshness, read_artifact, scalar_fields
from weather.schema_registry import schema_version


ORDER_FIELDS = ("exchange_order_id", "order_id", "market_id", "clob_token_id", "side",
                "price", "exchange_remaining_size", "remaining_size", "exchange_status", "status")
FILL_FIELDS = ("generated_at_utc", "market_id", "side", "fill_price", "fill_size",
               "liquidity_role", "official_trade_status", "exchange_order_id", "trade_id")
POSITION_FIELDS = ("market_id", "condition_id", "clob_token_id", "asset", "outcome",
                   "size", "current_value", "currentValue", "cash_pnl", "cashPnl")


def _object(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _rows(values, fields):
    return [scalar_fields(value, fields)
            for value in (values if isinstance(values, list) else [])[-100:] if isinstance(value, dict)]


def _bound_artifact(path, run):
    artifact = read_artifact(path, root=path.parent)
    payload = artifact.get("payload") or {}
    if artifact["available"] and (
        not run.get("run_id") or not run.get("target_date")
        or payload.get("run_id") != run.get("run_id")
        or payload.get("target_date") != run.get("target_date")
    ):
        artifact.update(available=False, error="Report belongs to a different run or target date.")
        artifact.pop("payload", None)
    return artifact


def collect_trading_snapshot(run_artifact, *, now=None):
    run = _object(run_artifact.get("payload"))
    path = run_artifact.get("path")
    if not run_artifact.get("available") or not path or not run.get("run_id"):
        return {"available": False, "detail": "No maker run has been observed.", "orders": [], "fills": [], "positions": []}
    folder = Path(path).parent
    reconciliation = _bound_artifact(folder / "exchange_reconciliation.json", run)
    report = _bound_artifact(folder / "mm2_pilot_report.json", run)
    exchange = _object(reconciliation.get("payload"))
    pilot = _object(report.get("payload"))
    if exchange and exchange.get("schema_version") != schema_version("mm_exchange_adapter"):
        reconciliation.update(available=False, error="Unsupported exchange reconciliation schema.")
        exchange = {}
    paid_schema = schema_version("mm_paid_incentive_pilot_report")
    if pilot and pilot.get("schema_version") not in {schema_version("mm_exchange_adapter"), paid_schema}:
        report.update(available=False, error="Unsupported accounting report schema.")
        pilot = {}
    if exchange and pilot and exchange.get("generated_at_utc") != pilot.get("generated_at_utc"):
        report.update(available=False, error="Accounting and exchange observations have different timestamps.")
        pilot = {}
    financial = _object(pilot.get("financial_reconciliation"))
    paid = _object(financial.get("paid_incentive_reconciliation"))
    paid_asset_valid = (pilot.get("cash_asset") == INCENTIVE_CASH_ASSET
                        and financial.get("cash_asset") == INCENTIVE_CASH_ASSET)
    if pilot.get("schema_version") == paid_schema and not paid_asset_valid:
        report.update(available=False, error="Accounting cash asset is not the supported pUSD asset.")
        pilot, financial, paid = {}, {}, {}
    paid_verified = (pilot.get("schema_version") == paid_schema
                     and paid.get("schema_version") == schema_version("mm_paid_incentive_reconciliation")
                     and paid.get("complete") is True
                     and financial.get("paid_cash_basis_verified") is True)
    accounting_complete = (pilot.get("financial_reconciliation_complete") is True
                           and financial.get("complete") is True
                           and financial.get("financial_identity_inputs_verified") is True
                           and not financial.get("missing_evidence"))
    if pilot.get("schema_version") == paid_schema and not paid_verified:
        accounting_complete = False
    amounts = {
        "Trading P&L before fees": _number(financial.get("settlement_pnl_usdc")),
        "Actual fees": _number(financial.get("actual_fees_usdc")),
        "Paid maker rebates": _number(financial.get("actual_maker_rebate_usdc")) if paid_verified else None,
        "Paid liquidity rewards": _number(financial.get("actual_liquidity_reward_usdc")) if paid_verified else None,
        "Estimated fill rebates": _number(financial.get("expected_live_fill_rebate_usdc")),
        "Net reconciled P&L": _number(financial.get("actual_total_pnl_after_fees_incentives_usdc")) if accounting_complete else None,
    }
    orders = _rows(exchange.get("matched_orders"), ORDER_FIELDS)
    orders.extend(_rows(exchange.get("extra_exchange_orders"), ORDER_FIELDS))
    events = exchange.get("user_stream_lifecycle_events")
    events = events if isinstance(events, list) else []
    fills = _rows([row for row in events if isinstance(row, dict) and row.get("transition") == "filled"], FILL_FIELDS)
    lifecycle = _object(run.get("order_lifecycle"))
    return {
        "available": True, "run_id": run.get("run_id"), "target_date": run.get("target_date"),
        "mode": run.get("mode"), "orders": orders[:100], "fills": fills,
        "positions": _rows(exchange.get("positions"), POSITION_FIELDS),
        "open_orders": _number(exchange.get("exchange_open_order_count")),
        "reserved": _number(lifecycle.get("current_reserved_usdc")),
        "reconciliation": freshness(reconciliation, now=now, max_age_seconds=60),
        "accounting": freshness(report, now=now, max_age_seconds=600),
        "accounting_complete": accounting_complete, "paid_verified": paid_verified,
        "amounts": amounts, "missing_evidence": financial.get("missing_evidence") or [],
        "recorded_status": exchange.get("status"),
        "order_mismatches": {
            "Missing at exchange": _number(exchange.get("missing_exchange_order_count")),
            "Unexpected at exchange": _number(exchange.get("extra_exchange_order_count")),
        },
    }
