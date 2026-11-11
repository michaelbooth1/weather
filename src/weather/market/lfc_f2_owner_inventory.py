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
        parts = item.get('native_redemption', {}).get('positions', ())
        proved = sum((quantity(part['quantity']) for part in parts if part['token_id'] == token), quantity(0))
        if proved and anchor is not None:
            # A receipt is final, but the first positions endpoint can still
            # show all or part of the burned quantity. Retain only the proven
            # remaining burn; it can never grant another cash/principal credit.
            remaining = min(after, max(quantity(0), proved - max(quantity(0), before - after)))
            book.owner_inventory_allowances.setdefault((item['id'], token), remaining)
    return tokens


def apply_catchup(book, row):
    from weather.market.lfc_capital import CapitalRefused
    from weather.market.lfc_f2_inventory import campaign_tokens, expected_inventory
    activity = book.activities.get(row.get('activity_id'))
    anchor = book.inventory_anchor
    token = row.get('token_id')
    if (activity is None or 'native_redemption' not in activity or anchor is None or
            token in campaign_tokens(book.ledger, row['sequence']) or
            row.get('anchor_sha256') != digest(anchor) or
            row.get('native_redemption_sha256') != digest(activity['native_redemption']) or
            not re.fullmatch('[0-9a-f]{64}', row.get('read_sha256', ''))):
        raise CapitalRefused('capital_owner_inventory_binding')
    before, after, observed = (quantity(row[key]) for key in ('before', 'after', 'observed'))
    allowance = book.owner_inventory_allowances.get((activity['id'], token), quantity(0))
    expected = expected_inventory(book.ledger, anchor, book, cut=row['sequence'])
    if (before != quantity(expected.get(token, 0)) or not observed <= after < before or
            before - after > allowance or after != max(observed, before - allowance)):
        raise CapitalRefused('capital_owner_inventory_binding')
    book.owner_inventory_allowances[(activity['id'], token)] -= before - after
    book.owner_inventory_adjustments.append({'activity_id': activity['id'], 'sequence': row['sequence'],
        'token_id': token, 'delta': str(after - before), 'read_sha256': row['read_sha256']})


def reconcile(ledger, read):
    """Only a proved personal burn may explain later endpoint catch-up."""
    from weather.market.lfc_capital import CapitalBook
    from weather.market.lfc_f2_inventory import campaign_tokens, expected_inventory
    from weather.market.lfc_ledger import normalize_positions
    book = CapitalBook(ledger)
    if book.inventory_anchor is None:
        return
    current, protected = normalize_positions(read['positions']), campaign_tokens(ledger)
    for (key, token), allowance in list(book.owner_inventory_allowances.items()):
        if not allowance or token in protected:
            continue
        expected = expected_inventory(ledger, book.inventory_anchor, book)
        before, observed = quantity(expected.get(token, 0)), quantity(current.get(token, 0))
        if observed >= before:
            continue
        ledger.record('capital_owner_inventory', activity_id=key, token_id=token,
            before=str(before), after=str(max(observed, before - allowance)), observed=str(observed),
            anchor_sha256=digest(book.inventory_anchor), read_sha256=digest(read),
            native_redemption_sha256=digest(book.activities[key]['native_redemption']))
        book = CapitalBook(ledger)
