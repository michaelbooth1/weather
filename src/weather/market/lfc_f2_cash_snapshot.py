"""Bind whole-second activity to a cash snapshot without inventing inclusion."""
import re

from weather.market.mm_stage2_hold import digest, utc

CASH_SOLVER_STATE_LIMIT = 4096


def solve(variables, target):
    """Prove uniqueness, pruning sums that cannot reach the requested target."""
    from weather.market.lfc_campaign import TransientPrecheck
    lower = sum(amount for _, amount in variables if amount < 0)
    upper = sum(amount for _, amount in variables if amount > 0)
    if target in {lower, upper}:
        # Nonzero variables make either extremum unique, for any batch size.
        return frozenset(key for key, amount in variables
                         if (amount < 0 if target == lower else amount > 0))
    if not lower < target < upper:
        raise TransientPrecheck('capital_cash_snapshot_pending')
    states = {0: (1, frozenset())}
    for key, amount in sorted(variables, key=lambda pair: (-abs(pair[1]), pair[0])):
        lower -= min(0, amount)
        upper -= max(0, amount)
        following = {}
        for total, (count, chosen) in states.items():
            for value, selected in ((total, chosen), (total + amount, chosen | {key})):
                if not value + lower <= target <= value + upper:
                    continue
                prior = following.get(value)
                following[value] = ((min(2, count + prior[0]), frozenset()) if prior else
                                    (count, selected))
        if len(following) > CASH_SOLVER_STATE_LIMIT:
            raise TransientPrecheck('capital_cash_snapshot_pending')
        states = following
    match = states.get(target)
    if match is None or match[0] != 1:
        raise TransientPrecheck('capital_cash_snapshot_pending')
    return match[1]


def personal_net(book, rows, snapshot_at):
    """Unbound, confirmed SDK executions and documented fees are fixed terms."""
    if not rows:
        return 0
    from weather.market.lfc_f2_personal_cash import movements
    first = book.inventory_anchors[0]
    found = movements(book.ledger, rows,
        start=utc(first.get('snapshot_at_utc', first['at_utc'])).timestamp(),
        end=utc(snapshot_at).timestamp(), bound=book.personal_trades)
    return sum((item['cash_native'] if item['side'] == 'SELL' else -item['cash_native']) - item['fee_native']
               for key, item in found.items() if key not in book.personal_trades)


def surplus_batch(book, item):
    """An arbitrary earlier fallback must not make its peers appear unique."""
    return any(value.get('surplus_only') and value['reference'] == reference(book) and
               item['id'] in value.get('surplus_only_ids', ())
               for value in book.cash_capture_bindings.values())


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


def assignment(book, sources, cash, *, fixed=0):
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
    chosen = solve(variables, cash - book.expected_cash() - fixed)
    return {key: key not in chosen for key, _ in variables}


def context(book, read, remaining, *, anchor_mode=None):
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
    extra = {}
    if item['cash_native'] is None and captured is None:
        captured = False  # An unproved label never establishes cash inclusion.
    elif captured is None:
        from weather.market.lfc_f2_personal_cash import sources as personal_sources
        from weather.market.lfc_campaign import TransientPrecheck
        times = read.get('component_times', {})
        snapshot_at = min((times.get(name, {}).get('started_at_utc', read['started_at_utc'])
                           for name in ('positions', 'balances')), key=utc)
        rows = personal_sources(book, read, snapshot_at)
        extra = {'personal_trade_sources': rows, 'personal_snapshot_at_utc': snapshot_at}
        try:
            if surplus_batch(book, item):
                raise TransientPrecheck('capital_cash_snapshot_pending')
            captured = assignment(book, sources, native(read['balances']['available_collateral']),
                                  fixed=personal_net(book, rows, snapshot_at))[item['id']]
        except TransientPrecheck:
            if anchor_mode != 'session':
                raise
            from weather.market.lfc_f2_inventory import require_closed
            require_closed(book.ledger, read)
            # Only a new, closed-session anchor may absorb an unexplained
            # residual. No ambiguous gain is credited; surplus stays owner cash.
            captured = book.incoming(item)
            extra['surplus_only'] = True
            extra['surplus_only_ids'] = sorted(entry['id'] for entry in decode(book, sources)
                                               if relation(book, entry) is None)
    return {'reference': reference(book), 'read_sha256': digest(read), 'balances': read['balances'],
            'sources': sources if relation(book, item) is None else sources[:1], 'captured': captured,
            'ledger_head_sha256': book.ledger.previous, **extra}


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
            fixed = personal_net(book, value.get('personal_trade_sources', []),
                                 value.get('personal_snapshot_at_utc', value['reference']['at_utc']))
            try:
                if surplus_batch(book, item):
                    raise TransientPrecheck('capital_cash_snapshot_pending')
                captured = assignment(book, value['sources'], cash, fixed=fixed)[item['id']]
            except TransientPrecheck:
                if value.get('surplus_only') is not True:
                    raise
                from weather.market.lfc_f2_inventory import require_closed
                require_closed(book.ledger, {'complete': True, 'errors': [], 'open_orders': []})
                if value.get('surplus_only_ids') != sorted(entry['id'] for entry in decode(book, value['sources'])
                                                          if relation(book, entry) is None):
                    raise ValueError('fallback identities')
                captured = book.incoming(item)
            else:
                if value.get('surplus_only'):
                    raise ValueError('unnecessary fallback')
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
