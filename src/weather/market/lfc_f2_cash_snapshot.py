"""Bind whole-second activity to a cash snapshot without inventing inclusion."""
import re

from weather.market.mm_stage2_hold import digest, utc


def reference(book):
    row = book.cash_reference
    return None if row is None else {
        key: row[key] for key in ('sequence', 'cash_native', 'snapshot_at_utc', 'at_utc')}


def relation(book, item):
    ref = reference(book)
    if ref is None:
        return None
    instant = utc(ref['snapshot_at_utc']).timestamp()
    if item['timestamp'] + 1 <= instant:
        return True
    if item['timestamp'] > instant:
        return False
    return None  # The event's [second, second+1) overlaps the snapshot.


def delta(book, item, seen):
    cash = item['cash_native']
    old = book.activities.get(item['id'])
    if cash is None or old is not None and old['cash_native'] is not None:
        return 0
    if item['type'] == 'REDEEM' and item.get('native_redemption'):
        tx = item['native_redemption']['transaction_hash']
        if tx in seen or tx in book.redeemed_transactions:
            return 0
        seen.add(tx)
    return cash if book.incoming(item) else -cash


def decode(book, sources):
    from weather.market.lfc_capital import CapitalRefused, normalize_activity
    result, rows, identities = [], {}, set()
    for entry in sources:
        proof = book.native_groups.get(entry['native_group_sha256'])
        if proof is None:
            raise CapitalRefused('capital_cash_capture_binding')
        if entry['native_group_sha256'] not in rows:
            rows[entry['native_group_sha256']] = {digest(raw) for raw in proof['rows']}
        item = normalize_activity(entry['source'], proof)
        if (digest(entry['source']) not in rows[entry['native_group_sha256']] or item['id'] in identities or
                item['wallet'] != book.ledger.rows[0]['maker_address'].lower()):
            raise CapitalRefused('capital_cash_capture_binding')
        identities.add(item['id'])
        result.append(item)
    return result


def assignment(book, sources, cash):
    """Only a unique native-balance equation resolves an overlapping second."""
    from weather.market.lfc_campaign import TransientPrecheck
    items, seen, variables = decode(book, sources), set(), []
    for item in items:
        amount = delta(book, item, seen)
        if amount and relation(book, item) is None:
            variables.append((item['id'], amount))
    resolving = {item['id'] for item in items if item['cash_native'] is not None}
    if set(book.blocking_unknown()) - resolving or set(book.incoming_quarantines) - resolving:
        raise TransientPrecheck('capital_cash_snapshot_pending')
    # Sum -> (number of explanations, unique set of fresh cash movements).
    states = {0: (1, frozenset())}
    for key, amount in variables:
        following = dict(states)
        for total, (count, chosen) in states.items():
            target = total + amount
            prior = following.get(target)
            following[target] = ((min(2, count + prior[0]), frozenset()) if prior else
                                 (count, chosen | {key}))
        if len(following) > 4096:
            raise TransientPrecheck('capital_cash_snapshot_pending')
        states = following
    match = states.get(cash - book.expected_cash())
    if match is None or match[0] != 1:
        raise TransientPrecheck('capital_cash_snapshot_pending')
    return {key: key not in match[1] for key, _ in variables}


def context(book, read, remaining):
    """The binding travels atomically with its activity, including on retry."""
    from weather.market.lfc_capital import native
    if reference(book) is None:
        return None
    source, group = remaining[0]
    sources = [{'source': raw, 'native_group_sha256': sha} for raw, sha in remaining]
    item = decode(book, sources[:1])[0]
    if item['cash_native'] is not None and not delta(book, item, set()):
        return None
    captured = relation(book, item)
    if item['cash_native'] is None and captured is None:
        captured = False  # An unproved label never establishes cash inclusion.
    elif captured is None:
        captured = assignment(book, sources, native(read['balances']['available_collateral']))[item['id']]
    return {'reference': reference(book), 'read_sha256': digest(read), 'balances': read['balances'],
            'sources': sources if relation(book, item) is None else sources[:1], 'captured': captured,
            'ledger_head_sha256': book.ledger.previous}


def accept(book, row, item):
    from weather.market.lfc_capital import ASSET, CapitalRefused, native
    from weather.market.lfc_campaign import TransientPrecheck
    value = row.get('cash_capture')
    if value is None:
        return  # Retained pre-B083 rows preserve their original interpretation.
    try:
        balances = value['balances']
        cash = native(balances['available_collateral'])
        assets = {str(key).lower(): amount for key, amount in balances['assets'].items()}
        if (value['reference'] != reference(book) or
                value['ledger_head_sha256'] != row['previous_sha256'] or
                not re.fullmatch('[0-9a-f]{64}', value['read_sha256']) or
                native(assets[ASSET]) != cash or str(balances['collateral_evidence']['balance']) != str(cash) or
                decode(book, value['sources'][:1])[0] != item or type(value['captured']) is not bool):
            raise ValueError('binding')
        captured = relation(book, item)
        if item['cash_native'] is None and captured is None:
            captured = False
        elif captured is None:
            captured = assignment(book, value['sources'], cash)[item['id']]
        if captured != value['captured']:
            raise ValueError('inclusion')
    except (ValueError, KeyError, TypeError, TransientPrecheck):
        raise CapitalRefused('capital_cash_capture_binding') from None
    book.cash_capture_bindings[item['id']] = value


def initial_reference(book, anchor, sequence):
    """The enrollment balance has a component timestamp, too."""
    book.cash_reference = {'cash_native': anchor['cash_native'],
        'purchased_native_at_bridge': book.bridge['purchased_native_at_bridge'],
        'cash_in_at_bridge': book.bridge['cash_in_at_bridge'], 'cash_out_at_bridge': book.bridge['cash_out_at_bridge'],
        'included_incoming': {}, 'at_utc': anchor['at_utc'],
        'snapshot_at_utc': anchor.get('cash_snapshot_at_utc', anchor.get('snapshot_at_utc', anchor['at_utc'])),
        'sequence': sequence, 'initial_snapshot': True}
    book.wallet_quarantines.append(book.bridge_quarantine)
