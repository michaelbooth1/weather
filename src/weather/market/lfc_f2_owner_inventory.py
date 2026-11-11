"""Read-bound owner quantity decisions for late personal redemptions."""
import re

from weather.market.lfc_accounting import quantity
from weather.market.mm_stage2_hold import digest, utc


def opening_owner_cash(book, item):
    if not book.inventory_anchors:
        return 0
    from weather.market.lfc_f2_inventory import campaign_tokens
    first = book.inventory_anchors[0]
    if item['timestamp'] >= int(utc(first.get('snapshot_at_utc', first['at_utc'])).timestamp()):
        return 0
    protected = campaign_tokens(book.ledger)
    return sum(part['cash_native'] or 0 for part in item.get('native_redemption', {}).get('positions', ())
               if part['token_id'] not in protected)


def decision(book, read, item):
    if item['type'] != 'REDEEM':
        return None
    from weather.market.lfc_f2_inventory import campaign_tokens, expected_inventory
    from weather.market.lfc_ledger import normalize_positions
    anchor = book.inventory_anchor
    if anchor is not None and item['timestamp'] > utc(anchor.get('snapshot_at_utc', anchor['at_utc'])).timestamp():
        return None
    protected = campaign_tokens(book.ledger)
    parts = item.get('native_redemption', {}).get('positions', [item])
    tokens = {part['token_id'] for part in parts} - protected
    if not tokens:
        return None
    current = normalize_positions(read['positions'])
    expected = expected_inventory(book.ledger, anchor, book) if anchor is not None else {}
    # A native resolution first undoes provisional burns from the same tx.
    tx = item.get('native_redemption', {}).get('transaction_hash')
    undo = {item['id']} if item['id'] in book.activities else set()
    if tx is not None and tx not in book.redeemed_transactions:
        undo.update(key for key in book.activities if book.activity_transactions[key] == tx)
    for removal in book.removal_events:
        if removal['activity_id'] in undo:
            token = removal['token_id']
            expected[token] = str(quantity(expected.get(token, 0)) + quantity(removal['quantity']))
    if item.get('native_redemption') is None:
        tokens.update((set(current) | set(expected)) - protected)
    return {'read_sha256': digest(read), 'anchor_sha256': digest(anchor) if anchor else None,
            'before': {token: str(expected.get(token, 0)) for token in sorted(tokens)},
            'after': {token: str(current.get(token, 0)) for token in sorted(tokens)}}


def apply(book, context, item, sequence):
    if context is None:
        return set()
    from weather.market.lfc_capital import CapitalRefused
    from weather.market.lfc_f2_inventory import campaign_tokens, expected_inventory
    anchor = book.inventory_anchor
    protected = campaign_tokens(book.ledger, sequence)
    tokens = set(context['before'])
    if (tokens != set(context['after']) or tokens & protected or
            context.get('anchor_sha256') != (digest(anchor) if anchor else None) or
            not re.fullmatch('[0-9a-f]{64}', context.get('read_sha256', '')) or
            anchor and item['timestamp'] > utc(anchor.get('snapshot_at_utc', anchor['at_utc'])).timestamp()):
        raise CapitalRefused('capital_owner_inventory_binding')
    expected = expected_inventory(book.ledger, anchor, book, cut=sequence) if anchor else {}
    for token in tokens:
        before, after = quantity(context['before'][token]), quantity(context['after'][token])
        if before != quantity(expected.get(token, 0)):
            raise CapitalRefused('capital_owner_inventory_binding')
        if anchor is not None and after != before:
            book.owner_inventory_adjustments.append({'activity_id': item['id'], 'sequence': sequence,
                'token_id': token, 'delta': str(after - before), 'read_sha256': context['read_sha256']})
    return tokens
