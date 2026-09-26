"""Additive neutral portfolio contracts. Decimal amounts are JSON strings.

Wire schema and accounting scope: docs/operations/portfolio-ledger.md.
No file, credential, domain, venue or network access occurs here.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

SNAPSHOT_SCHEMA = "portfolio_snapshot_v0.1"
CAMPAIGNS_SCHEMA = "portfolio_campaigns_v0.1"
LEDGER_SCHEMA = "portfolio_ledger_v0.1"


def amount(value):
    try:
        if isinstance(value, bool) or value is None:
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("invalid_portfolio_amount") from None


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid_portfolio_time") from None


def identity(value):
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_portfolio_identity")
    return value


def decimal_text(value):
    return format(amount(value), "f")


def validate_campaigns(config):
    if not isinstance(config, dict) or config.get("schema_version") != CAMPAIGNS_SCHEMA:
        raise ValueError("invalid_campaign_config")
    campaigns = config.get("campaigns")
    if not isinstance(campaigns, list) or not campaigns:
        raise ValueError("campaigns_required")
    ids, contribution_ids = set(), set()
    for campaign in campaigns:
        name = identity(campaign["id"])
        if name in ids:
            raise ValueError("duplicate_campaign")
        ids.add(name)
        start = instant(campaign["start_utc"])
        for contribution in campaign["contributions"]:
            cid = identity(contribution["id"])
            if cid in contribution_ids or instant(contribution["at_utc"]) < start:
                raise ValueError("invalid_capital_record")
            contribution_ids.add(cid)
            amount(contribution["amount_pusd"])  # Negative means a recorded withdrawal.
        limit = campaign.get("bleed_limit_pusd")
        if limit is not None and (amount(limit) < 0 or name == "owner-discretionary"):
            raise ValueError("invalid_bleed_limit")
    if "owner-discretionary" not in ids:
        raise ValueError("owner_discretionary_required")
    if config.get("default_campaign", "owner-discretionary") != "owner-discretionary":
        raise ValueError("default_must_be_owner_discretionary")
    seen = set()
    for rule in config.get("lot_overrides", []):
        tx = identity(rule["transaction_hash"])
        if tx in seen or rule["campaign"] not in ids:
            raise ValueError("invalid_lot_override")
        seen.add(tx)
    for rule in config.get("rules", []):
        selectors = set(rule) & {"condition_id", "event_slug_prefix"}
        if len(selectors) != 1 or rule["campaign"] not in ids:
            raise ValueError("invalid_campaign_rule")
        identity(rule[next(iter(selectors))])
    amount(config["unattributed_cash_pusd"])
    tolerance = amount(config.get("reconciliation_tolerance_pusd", "0.000001"))
    if not 0 <= tolerance <= Decimal("0.01"):
        raise ValueError("invalid_reconciliation_tolerance")
    return config


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
        raise ValueError("invalid_snapshot_schema")
    now = instant(snapshot["as_of_utc"])
    identity(snapshot["account_id"])
    for key in ("positions_complete", "history_complete"):
        if not isinstance(snapshot.get(key), bool):
            raise ValueError("snapshot_completeness_required")
    if snapshot.get("cash_pusd") is not None and amount(snapshot["cash_pusd"]) < 0:
        raise ValueError("negative_account_cash")
    if snapshot.get("history_start_utc") is not None:
        if instant(snapshot["history_start_utc"]) > now:
            raise ValueError("future_history_start")
    seen = set()
    for row in snapshot["positions"]:
        asset = identity(row["asset_id"])
        identity(row["condition_id"])
        if asset in seen or amount(row["size"]) < 0 or not 0 <= amount(row["avg_price"]) <= 1:
            raise ValueError("invalid_position")
        seen.add(asset)
        if row["classification"] not in {"live", "resolved", "unknown"}:
            raise ValueError("invalid_classification")
        for key in ("bid", "ask", "terminal_price"):
            if row.get(key) is not None and not 0 <= amount(row[key]) <= 1:
                raise ValueError("invalid_position_price")
    for row in snapshot["trades"]:
        for key in ("event_id", "transaction_hash", "asset_id", "condition_id"):
            identity(row[key])
        if instant(row["at_utc"]) > now or row["side"] not in {"BUY", "SELL", "REDEEM"}:
            raise ValueError("invalid_trade")
        if amount(row["size"]) <= 0 or not 0 <= amount(row["price"]) <= 1:
            raise ValueError("invalid_trade_amount")
        if row["side"] == "REDEEM" and amount(row["price"]) not in (0, 1):
            raise ValueError("invalid_redemption_price")
        if row.get("fee_pusd") is not None and amount(row["fee_pusd"]) < 0:
            raise ValueError("invalid_trade_fee")
    return snapshot
