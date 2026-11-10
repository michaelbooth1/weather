"""Cash-reference quarantine across F2 wallet snapshots and late native proof."""
from weather.market.mm_stage2_hold import utc


def capture(book, anchor, sequence):
    """Capture existing incoming quarantine before allocating any new surplus."""
    difference = anchor['cash_native'] - book.expected_cash()
    included = dict((book.cash_reference or {}).get('included_incoming', {}))
    extra = max(0, difference)
    for key, quarantine in book.incoming_quarantines.items():
        if book.activity_sequences[key] <= book.bridge['sequence'] or book.cash_before_bridge(book.activities[key]):
            continue
        take = min(extra, max(0, quarantine['amount'] - included.get(key, 0)))
        included[key] = included.get(key, 0) + take
        extra -= take
    movement = {'id': 'wallet-anchor-' + str(sequence), 'timestamp': int(utc(anchor['at_utc']).timestamp())}
    if extra:
        grant = book.credit('external', extra, movement, sequence=sequence)
        book.wallet_quarantines.append(grant)
    if difference < 0:
        book.pool_movements.append({'kind': 'withdraw', 'amount': -difference,
            'timestamp': movement['timestamp'], 'sequence': sequence, 'charge_excess': False})
        book.pools_dirty = True
    book.refresh_pools()
    book.cash_reference = {'cash_native': anchor['cash_native'],
        'purchased_native_at_bridge': sum(lot['basis'] for lot in book.lots.values()),
        'cash_in_at_bridge': book.cash_in, 'cash_out_at_bridge': book.cash_out,
        'included_incoming': included, 'at_utc': anchor['at_utc'], 'sequence': sequence}


def captured_credit(book, activity, amount, *, label=False):
    """A proved credit replaces captured quarantine, once, before growing cash."""
    reference = book.cash_reference
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
    if label:
        reference['included_incoming'][key] = reference['included_incoming'].get(key, 0) + included
    else:
        reference['cash_in_at_bridge'] += included
