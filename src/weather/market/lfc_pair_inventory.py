"""Adapt T112's canonical own-trade projection to held campaign FIFO lots.

No balance, rounded position, public trade size, or new money rule supplies U.
Terminal own-order totals and evidenced held-lot quantities must agree exactly.
"""
from datetime import datetime, timezone
from decimal import Decimal

from weather.market.lfc_accounting import quantity
from weather.market.lfc_pair_completion import OwnLot, instant, inventory


def fill_time(value):
    if value is None or isinstance(value, bool):
        raise ValueError('completion_fill_time_unproven')
    try:
        if isinstance(value, (int, float, Decimal)) or isinstance(value, str) and value.replace('.', '', 1).isdigit():
            return datetime.fromtimestamp(float(quantity(value)), timezone.utc)
        return instant(value)
    except (ValueError, TypeError, OverflowError, OSError):
        raise ValueError('completion_fill_time_unproven') from None


def project_read(trades, legs, *, observed_at_utc):
    """The K6 class alone normalizes/deduplicates executions and their lifecycle.

    The unified SDK names the venue match clock matched_at. Pass that same
    retained value to the canonical time field without inventing a read clock.
    """
    from weather.market.lfc_own_trades import OwnTradeProjection
    projection = OwnTradeProjection()
    rows = [dict(row, exchange_match_time=row.get('exchange_match_time') or
                 row.get('matched_at') or row.get('match_time')) for row in trades]
    projection.ingest(rows, legs, source='rest', observed_at_utc=observed_at_utc)
    return projection.rows()


def held_inventory(records, legs, held_lots, *, campaign_id, condition_id, tokens):
    """Build U from exact canonical fills allocated to the campaign's own lots.

    `legs` maps our order IDs to ledger legs; `held_lots` maps intent keys to
    the canonical capital book's still-held lots. The caller has already proved
    this campaign/account binding and fresh complete inventory. The function
    does not grant or replace that proof.
    """
    if len(tokens) != 2 or len(set(tokens)) != 2:
        raise ValueError('completion_token_pair')
    selected = {oid: leg for oid, leg in legs.items() if leg['condition_id'] == condition_id}
    by_order, identities = {oid: [] for oid in selected}, set()
    for row in records:
        oid = row['own_order_id']
        if oid not in selected:
            continue
        leg = selected[oid]
        identity = row['trade_id'], oid
        if identity in identities:
            raise ValueError('completion_projection_not_canonical')
        identities.add(identity)
        if (row.get('identity_basis') != 'venue_trade_id' or type(row.get('money_counted')) is not bool or
                type(row.get('final')) is not bool or row.get('state') not in {'provisional', 'confirmed', 'failed'} or
                not row.get('provenance')):
            raise ValueError('completion_projection_unproven')
        if row['money_counted'] != (row['status'] != 'FAILED'):
            raise ValueError('completion_projection_lifecycle')
        if not row['money_counted']:
            continue
        if (row.get('condition_id') != condition_id or row.get('token_id') != leg['token_id'] or
                row.get('side') != 'BUY' or row.get('liquidity_role') != 'MAKER' or
                quantity(row['price']) != quantity(leg['price']) or row['token_id'] not in tokens):
            raise ValueError('completion_projection_binding')
        by_order[oid].append(OwnLot(row['trade_id'], oid, campaign_id, condition_id,
            tokens.index(row['token_id']), row['shares'], row['price'], fill_time(row.get('exchange_match_time'))))
    lots = []
    for oid, leg in selected.items():
        expected = quantity(leg['size_matched'])
        rows = sorted(by_order[oid], key=lambda row: row.at_utc)
        total = sum((row.shares for row in rows), Decimal(0))
        if total != expected or expected and leg['status'] != 'terminal':
            raise ValueError('completion_terminal_fill_coverage')
        if not expected:
            continue
        held = held_lots.get(leg['intent_key'])
        if held is None or held['token_id'] != leg['token_id'] or held['condition_id'] != condition_id:
            raise ValueError('completion_held_lot_binding')
        remaining = quantity(held['remaining_quantity'])
        if remaining > total:
            raise ValueError('completion_held_lot_quantity')
        # Capital-book removals allocate oldest own lots first. Within an
        # order, all maker allocations have its same proven limit price.
        removed = total-remaining
        for row in rows:
            take = min(removed, row.shares)
            removed -= take
            if take < row.shares:
                lots.append(OwnLot(row.trade_id, row.order_id, campaign_id, condition_id,
                                   row.leg, row.shares-take, row.price, row.at_utc))
    return inventory(lots, campaign_id=campaign_id, condition_id=condition_id)


def from_read(ledger, read, *, campaign_id, condition_id, tokens):
    """Consume a caller-proved account read and the existing capital projection."""
    from weather.market.lfc_capital import CapitalBook
    # This ledger lane records BUY intents only; legacy leg rows omit side.
    legs = {oid: dict(ledger.legs[key], intent_key=key, side='BUY') for oid, key in ledger.by_order.items()}
    records = project_read(read['trades'], legs, observed_at_utc=read['ended_at_utc'])
    return held_inventory(records, legs, CapitalBook(ledger).lots, campaign_id=campaign_id,
                          condition_id=condition_id, tokens=tuple(tokens)), records
