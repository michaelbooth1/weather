"""Cash-reference quarantine across F2 wallet snapshots and late native proof."""
from weather.market.mm_stage2_hold import utc


def owner_debit(book, amount, *, timestamp, sequence, explained=False):
    movement = {'kind': 'withdraw', 'amount': amount, 'timestamp': timestamp,
                'sequence': sequence, 'charge_excess': False, 'explained_native': amount if explained else 0}
    book.pool_movements.append(movement)
    book.wallet_debit_quarantines.append(movement)
    book.pools_dirty = True


def capture(book, anchor, sequence):
    """Capture existing incoming quarantine before allocating any new surplus."""
    from weather.market.lfc_f2_personal_cash import capture as capture_personal
    personal_net = capture_personal(book, anchor, sequence)
    difference = anchor['cash_native'] - book.expected_cash() - personal_net
    included = dict((book.cash_reference or {}).get('included_incoming', {}))
    for key, quarantine in book.incoming_quarantines.items():
        if book.activity_sequences[key] <= book.bridge['sequence'] or book.cash_before_bridge(book.activities[key]):
            continue
        take = max(0, quarantine['amount'] - included.get(key, 0))
        included[key] = included.get(key, 0) + take
        difference -= take
    movement = {'id': 'wallet-anchor-' + str(sequence), 'timestamp': int(utc(anchor['at_utc']).timestamp())}
    if difference > 0:
        grant = book.credit('external', difference, movement, sequence=sequence)
        book.wallet_quarantines.append(grant)
    if difference < 0:
        owner_debit(book, -difference, timestamp=movement['timestamp'], sequence=sequence)
    book.refresh_pools()
    book.cash_reference = {'cash_native': anchor['cash_native'],
        'purchased_native_at_bridge': sum(lot['basis'] for lot in book.lots.values()),
        'cash_in_at_bridge': book.cash_in, 'cash_out_at_bridge': book.cash_out,
        'included_incoming': included, 'at_utc': anchor['at_utc'],
        'snapshot_at_utc': anchor.get('cash_snapshot_at_utc', anchor.get('snapshot_at_utc', anchor['at_utc'])),
        'sequence': sequence}


def captured_credit(book, activity, amount, *, label=False):
    """A proved credit replaces captured quarantine, once, before growing cash."""
    reference = book.cash_reference
    binding = book.cash_capture_bindings.get(activity['id'])
    if binding is None and reference is not None and reference.get('initial_snapshot'):
        return  # This reference was absent for retained pre-B083 activity rows.
    if binding is not None and not binding['captured']:
        return
    if reference is None or activity['timestamp'] > utc(reference['at_utc']).timestamp():
        return
    if amount < 0:
        reference['cash_in_at_bridge'] += amount
        return
    key = activity['id']
    keys = [key]
    if activity['type'] == 'REDEEM':
        tx = book.activity_transactions[key]
        keys = [other for other in reference['included_incoming'] if
                book.activity_transactions.get(other) == tx and book.activities[other]['type'] == 'REDEEM']
    captured = 0 if label else sum(reference['included_incoming'].pop(other, 0) for other in keys)
    included = min(amount, captured)
    if captured > included:
        # A smaller/zero native payout leaves the balance snapshot's excess
        # unattributed. Preserve that owner cash when replacing the old label.
        grant = book.credit('external', captured - included, {
            'id': 'wallet-remainder-' + key, 'timestamp': int(utc(reference['at_utc']).timestamp())},
            sequence=reference['sequence'])
        book.wallet_quarantines.append(grant)
    for grant in book.wallet_quarantines:
        if included == amount:
            break
        if grant['timestamp'] < activity['timestamp'] or grant['sequence'] > reference['sequence']:
            continue
        take = min(amount - included, grant['amount'])
        grant['amount'] -= take
        included += take
        book.pools_dirty = True
    already_captured = (binding['captured'] if binding is not None else
        activity['timestamp'] <= utc(reference.get('snapshot_at_utc', reference['at_utc'])).timestamp())
    accounted = amount if already_captured else included
    if label:
        reference['included_incoming'][key] = reference['included_incoming'].get(key, 0) + accounted
    else:
        reference['cash_in_at_bridge'] += accounted
    if included < accounted:
        owner_debit(book, accounted - included, timestamp=int(utc(reference['at_utc']).timestamp()),
                    sequence=reference['sequence'])


def captured_debit(book, activity, amount):
    """Preserve the anchor's debit timing and absorb a late cash counter once."""
    reference = book.cash_reference
    binding = book.cash_capture_bindings.get(activity['id'])
    if binding is None and reference is not None and reference.get('initial_snapshot'):
        return
    if binding is not None and not binding['captured']:
        return
    if (reference is None or amount <= 0 or
            activity['timestamp'] > utc(reference.get('snapshot_at_utc', reference['at_utc'])).timestamp()):
        return
    moves = [move for move in book.pool_movements if move['kind'] == 'withdraw' and
             move.get('activity_id') == activity['id']]
    session_cost = 0
    if any(move.get('charge_excess') for move in moves):
        previous_cost = book.withdrawal_costs
        book.refresh_pools()
        session_cost = max(0, book.withdrawal_costs - previous_cost)
    for move in moves:
        move['amount'] = 0
    book.pools_dirty = True
    book.refresh_pools()
    book.costs += session_cost
    reference['cash_out_at_bridge'] += amount
    remaining = amount
    for marker in book.wallet_debit_quarantines:
        if marker['sequence'] > reference['sequence'] or marker['timestamp'] < activity['timestamp']:
            continue
        take = min(remaining, marker['amount'] - marker.get('explained_native', 0))
        marker['explained_native'] = marker.get('explained_native', 0) + take
        remaining -= take
        if not remaining:
            break
    if remaining:
        timestamp, sequence = int(utc(reference['at_utc']).timestamp()), reference['sequence']
        owner_debit(book, remaining, timestamp=timestamp, sequence=sequence, explained=True)
        grant = book.credit('external', remaining, {'id': 'masked-credit-' + activity['id'], 'timestamp': timestamp},
                            sequence=sequence)
        book.wallet_quarantines.append(grant)
