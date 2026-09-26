"""Whitelist adapter for saved wallet-reader JSON; no SDK, secrets or IO.

An archive is {account_id, captured_at_utc, summary, trades}. Unknown completeness
and fees remain unknown. A neutral snapshot can also be supplied directly.
"""
from datetime import datetime, timezone

from maker_core.contracts.portfolio import SNAPSHOT_SCHEMA, instant, validate_snapshot


def timestamp(value):
    if isinstance(value, (int, float)) or isinstance(value, str) and value.isdigit():
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    return instant(value).isoformat()


def adapt_archive(value):
    if value.get("schema_version") == SNAPSHOT_SCHEMA:
        return validate_snapshot(value)
    summary = value.get("summary", value)
    trades = value.get("trades", {})
    if not isinstance(summary, dict) or not isinstance(trades, dict):
        raise ValueError("invalid_reader_archive")
    account = value.get("account_id", summary.get("account_id"))
    as_of = timestamp(value.get("captured_at_utc", summary.get("captured_at_utc")))
    positions, history = [], []
    complete = not summary.get("errors", {}).get("positions") and isinstance(summary.get("positions"), list)
    resolved = summary.get("resolved_positions", [])
    if summary.get("resolved_count", len(resolved)) != len(resolved):
        complete = False
    for row in [*summary.get("positions", []), *resolved, *summary.get("unclassified_positions", [])]:
        positions.append(dict(asset_id=row.get("token_id"), condition_id=row.get("condition_id"),
            event_slug=row.get("event_slug", ""), size=row.get("size"), avg_price=row.get("avg_price"),
            classification=row.get("classification", "unknown"), redeemable=row.get("redeemable") is True,
            terminal_price=row.get("terminal_price"), bid=row.get("bid"), ask=row.get("ask")))
    # Public account activity provides account-relative sides. Raw CLOB maker
    # fills require a separate maker-order allocation; never guess their side.
    source = trades.get("account_activity", trades.get("recent_activity", []))
    history_complete = trades.get("history_complete") is True and isinstance(source, list)
    for row in source if isinstance(source, list) else []:
        try:
            if str(row.get("proxyWallet", "")).lower() != str(account).lower():
                raise ValueError("foreign_activity")
            if row.get("type") not in {"TRADE", "REDEEM"}:
                raise ValueError("unsupported_activity")
            side = row.get("side") if row["type"] == "TRADE" else "REDEEM"
            tx = row.get("transactionHash")
            at = timestamp(row.get("timestamp"))
            # Transaction hash alone is not a unique fill id. Identical duplicate
            # rows deduplicate; distinct fills need the venue's explicit id.
            event_id = row.get("id") or ":".join(str(x) for x in
                (tx, row.get("asset"), side, at, row.get("size"), row.get("price")))
            event = dict(event_id=event_id, transaction_hash=tx, at_utc=at,
                asset_id=row.get("asset"), condition_id=row.get("conditionId"),
                event_slug=row.get("eventSlug", ""), side=side, size=row.get("size"),
                price=row.get("price"), fee_pusd=row.get("fee_pusd"))
            # Validate this row through the same neutral contract, without
            # allowing one malformed activity row to erase available positions.
            validate_snapshot(dict(schema_version=SNAPSHOT_SCHEMA, as_of_utc=as_of,
                account_id=account, cash_pusd=None, positions_complete=False,
                history_complete=False, positions=[], trades=[event]))
            history.append(event)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError):
            history_complete = False
    return validate_snapshot(dict(schema_version=SNAPSHOT_SCHEMA, account_id=account, as_of_utc=as_of,
        cash_pusd=summary.get("cash_pusd"), positions=positions, trades=history,
        positions_complete=complete, history_complete=history_complete,
        history_start_utc=trades.get("history_start_utc")))
