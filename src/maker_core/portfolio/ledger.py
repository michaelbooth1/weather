"""Pure deterministic FIFO campaign accounting over neutral account snapshots."""
from copy import deepcopy
from decimal import Decimal

from maker_core.contracts.portfolio import amount, instant, validate_campaigns, validate_snapshot
from maker_core.evidence.journal import digest, plain

ZERO = Decimal(0)


def attribute(row, config):
    for rule in config.get("lot_overrides", []):
        if row.get("transaction_hash") == rule["transaction_hash"]:
            return rule["campaign"]
    for rule in config.get("rules", []):
        if ("condition_id" in rule and row.get("condition_id") == rule["condition_id"]
                or "event_slug_prefix" in rule and str(row.get("event_slug", "")).startswith(rule["event_slug_prefix"])):
            return rule["campaign"]
    return "owner-discretionary"


def build_book(snapshots, config):
    """Rebuild from recorded trades; never backfill an acquisition or a cash flow.

    Sales consume account FIFO and keep the acquisition's campaign attribution.
    A known settlement realizes remaining basis without crediting unredeemed cash.
    """
    config = validate_campaigns(config)
    snapshots = sorted((deepcopy(validate_snapshot(s)) for s in snapshots),
                       key=lambda s: (instant(s["as_of_utc"]), digest(s)))
    if not snapshots:
        raise ValueError("snapshots_required")
    if len({s["account_id"] for s in snapshots}) != 1:
        raise ValueError("mixed_accounts_refused")
    latest = snapshots[-1]
    now = instant(latest["as_of_utc"])
    reasons, events, books = set(), {}, {}
    tolerance = amount(config.get("reconciliation_tolerance_pusd", "0.000001"))
    for campaign in config["campaigns"]:
        capital = sum((amount(c["amount_pusd"]) for c in campaign["contributions"]
                       if instant(c["at_utc"]) <= now), ZERO)
        books[campaign["id"]] = dict(contributed_capital_pusd=capital, cash_pusd=capital,
            realized_pnl_pusd=ZERO, unrealized_pnl_pusd=ZERO, unredeemed_terminal_value_pusd=ZERO,
            marked_open_value_pusd=ZERO, fees_paid_pusd=ZERO, open_lots=[], reasons=set(),
            bleed_limit_pusd=campaign.get("bleed_limit_pusd"), start=instant(campaign["start_utc"]))
    for snapshot in snapshots:
        for row in snapshot["trades"]:
            previous = events.get(row["event_id"])
            if previous is not None and previous != row:
                reasons.add("conflicting_trade_record")
                books[attribute(previous, config)]["reasons"].add("conflicting_trade_record")
                books[attribute(row, config)]["reasons"].add("conflicting_trade_record")
            else:
                events[row["event_id"]] = row
    if len({digest(s) for s in snapshots if instant(s["as_of_utc"]) == now}) > 1:
        reasons.add("conflicting_latest_snapshot")
    history_start = latest.get("history_start_utc")
    if (not latest["history_complete"] or history_start is None
            or instant(history_start) > min(b["start"] for b in books.values())):
        for book in books.values():
            book["reasons"].add("trade_history_incomplete")
    if not latest["positions_complete"]:
        reasons.add("positions_read_incomplete")
    lots, identities, time_groups = {}, {}, {}
    for row in events.values():
        key = (row["asset_id"], instant(row["at_utc"]))
        time_groups[key] = time_groups.get(key, 0) + 1
    for row in sorted(events.values(), key=lambda r: (instant(r["at_utc"]), r["event_id"])):
        asset, owner = row["asset_id"], attribute(row, config)
        condition = row["condition_id"]
        if asset in identities and identities[asset] != condition:
            reasons.add("asset_identity_conflict")
            books[owner]["reasons"].add("asset_identity_conflict")
            continue
        identities[asset] = condition
        queue = lots.setdefault(asset, [])
        if time_groups[(asset, instant(row["at_utc"]))] > 1:
            # An arbitrary event-id tie break is reproducible, but is not proof
            # of FIFO order. Do not publish complete accounting from that guess.
            for name in {owner, *(lot["campaign"] for lot in queue)}:
                books[name]["reasons"].add("ambiguous_trade_order")
        size, price = amount(row["size"]), amount(row["price"])
        fee = amount(row["fee_pusd"]) if row.get("fee_pusd") is not None else ZERO
        if row["side"] == "BUY":
            book = books[owner]
            if instant(row["at_utc"]) < book["start"]:
                book["reasons"].add("acquisition_before_campaign_start")
            if row.get("fee_pusd") is None:
                book["reasons"].add("fee_unknown")
            book["cash_pusd"] -= size * price + fee
            book["fees_paid_pusd"] += fee
            queue.append(dict(asset_id=asset, condition_id=condition, campaign=owner,
                              acquisition_event_id=row["event_id"], transaction_hash=row["transaction_hash"],
                              acquired_at_utc=row["at_utc"], size=size, entry_price=price,
                              remaining_entry_fee=fee))
        else:
            available = sum((lot["size"] for lot in queue), ZERO)
            if available < size:
                reasons.add("close_without_acquisition")
                for name in {owner, *(lot["campaign"] for lot in queue)}:
                    books[name]["reasons"].add("close_without_acquisition")
                continue
            remaining = size
            for lot in queue:
                if remaining <= 0 or lot["size"] == 0:
                    continue
                used = min(remaining, lot["size"])
                book = books[lot["campaign"]]
                exit_fee = fee * used / size
                entry_fee = lot["remaining_entry_fee"] * used / lot["size"]
                book["cash_pusd"] += used * price - exit_fee
                book["fees_paid_pusd"] += exit_fee
                book["realized_pnl_pusd"] += used * (price - lot["entry_price"]) - entry_fee - exit_fee
                if row.get("fee_pusd") is None:
                    book["reasons"].add("fee_unknown")
                lot["size"] -= used
                lot["remaining_entry_fee"] -= entry_fee
                remaining -= used
    positions = {p["asset_id"]: p for p in latest["positions"]}
    wallet_value, unknown_value = ZERO, False
    for asset in sorted(set(lots) | set(positions)):
        queue = [lot for lot in lots.get(asset, []) if lot["size"] > 0]
        position = positions.get(asset)
        held = sum((lot["size"] for lot in queue), ZERO)
        observed = amount(position["size"]) if position else ZERO
        affected = {lot["campaign"] for lot in queue}
        if not affected and position and observed > 0:
            # Attribution is deterministic, but an unmatched holding is not an invented lot.
            affected.add(attribute(position, config))
        if abs(held - observed) > tolerance:
            reasons.add("position_quantity_mismatch")
            for name in affected:
                books[name]["reasons"].add("unknown_lot_or_quantity")
        if position and identities.get(asset, position["condition_id"]) != position["condition_id"]:
            reasons.add("asset_identity_conflict")
            for name in affected:
                books[name]["reasons"].add("asset_identity_conflict")
        value, kind = None, "unknown"
        if position:
            kind = position["classification"]
            if kind == "resolved" and position.get("terminal_price") is not None:
                terminal = amount(position["terminal_price"])
                if terminal in (0, 1):
                    value = terminal
            elif kind == "live" and position.get("bid") is not None and position.get("ask") is not None:
                bid, ask = amount(position["bid"]), amount(position["ask"])
                if bid <= ask:
                    value = (bid + ask) / 2
            if observed > 0:
                if value is None:
                    unknown_value = True
                else:
                    wallet_value += observed * value
        for name in affected:
            if value is None and (held > 0 or observed > 0):
                books[name]["reasons"].add("terminal_price_unknown" if kind == "resolved" else "mark_or_position_unknown")
        for lot in queue:
            book = books[lot["campaign"]]
            lot_value = lot["size"] * value if value is not None else None
            item = {k: v for k, v in lot.items() if k != "remaining_entry_fee"}
            item.update(classification=kind, mark_value_pusd=lot_value,
                        cost_basis_pusd=lot["size"] * lot["entry_price"] + lot["remaining_entry_fee"])
            book["open_lots"].append(item)
            if value is not None:
                pnl = lot_value - item["cost_basis_pusd"]
                if kind == "resolved":
                    book["unredeemed_terminal_value_pusd"] += lot_value
                    book["realized_pnl_pusd"] += pnl
                else:
                    book["marked_open_value_pusd"] += lot_value
                    book["unrealized_pnl_pusd"] += pnl
    cash = amount(latest["cash_pusd"]) if latest.get("cash_pusd") is not None else None
    reserve = amount(config["unattributed_cash_pusd"])
    attributed_cash = sum((b["cash_pusd"] for b in books.values()), reserve)
    value_only_errors = {"terminal_price_unknown", "mark_or_position_unknown"}
    cash_known = all(not (b["reasons"] - value_only_errors) for b in books.values())
    cash_delta = cash - attributed_cash if cash is not None and cash_known else None
    if cash is None:
        reasons.add("cash_read_missing")
    elif cash_delta is not None and abs(cash_delta) > tolerance:
        reasons.add("cash_reconciliation_mismatch")
    wallet_equity = cash + wallet_value if cash is not None and not unknown_value else None
    campaign_equity = ZERO
    for name, book in books.items():
        book.pop("start")
        book["reasons"] = sorted(book["reasons"])
        equity = book["cash_pusd"] + book["marked_open_value_pusd"] + book["unredeemed_terminal_value_pusd"]
        campaign_equity += equity
        pnl = equity - book["contributed_capital_pusd"]
        limit = book["bleed_limit_pusd"]
        incomplete = bool(book["reasons"])
        book["equity_pusd"] = None if incomplete else equity
        book["pnl_pusd"] = None if incomplete else pnl
        book["bleed_limit_reached"] = None if incomplete and limit is not None else bool(limit is not None and pnl < -amount(limit))
        book["status"] = "INCOMPLETE" if incomplete else "BLEED_LIMIT" if book["bleed_limit_reached"] else "OBSERVED"
        if incomplete:
            reasons.add("campaign_incomplete:" + name)
            if set(book["reasons"]) - value_only_errors:
                book["cash_pusd"] = None
            for key in ("realized_pnl_pusd", "unrealized_pnl_pusd", "unredeemed_terminal_value_pusd",
                        "marked_open_value_pusd", "fees_paid_pusd"):
                book[key] = None
    equity_known = all(b["equity_pusd"] is not None for b in books.values())
    equity_delta = wallet_equity - (campaign_equity + reserve) if wallet_equity is not None and equity_known else None
    if equity_delta is not None and abs(equity_delta) > tolerance:
        reasons.add("equity_reconciliation_mismatch")
    if unknown_value:
        reasons.add("wallet_position_value_unknown")
    return plain(dict(as_of_utc=latest["as_of_utc"], account_id=latest["account_id"],
        status="INCOMPLETE" if reasons else "OBSERVED", reasons=sorted(reasons), campaigns=books,
        cash_pusd=cash, marked_or_terminal_positions_pusd=None if unknown_value else wallet_value,
        equity_pusd=wallet_equity, unattributed_cash_pusd=reserve,
        reconciliation=dict(tolerance_pusd=tolerance, cash_difference_pusd=cash_delta,
                            equity_difference_pusd=equity_delta),
        mark_basis="live_two_sided_mid_resolved_terminal_0_or_1", enforcement="report_only",
        config_sha256=digest(config), snapshots_sha256=sorted({digest(s) for s in snapshots})))
