"""Reconcile each proved gross execution with its original cash snapshot once.

Progressive SDK visibility can reverse an earlier anonymous residual. Adjust
that same snapshot, never a later unrelated payment. Native-explained cash is
protected; any unmatched difference remains owner cash, never campaign gain.
"""
from weather.market.mm_stage2_hold import utc


def plan(book, found):
    reference = book.cash_reference or {}
    result, net = [], 0
    for key, item in found.items():
        if key in book.personal_trades:
            continue
        original = None
        for anchor in book.inventory_anchors:
            if anchor['ledger_cut'] > reference.get('sequence', -1):
                continue
            instant = utc(anchor.get('cash_snapshot_at_utc', anchor['snapshot_at_utc'])).timestamp()
            if item['timestamp'] <= instant:
                # A later balance cannot capture a movement for the first time
                # if an earlier balance could already contain it. An overlap
                # stays gross; timestamps alone do not prove inclusion.
                if item['timestamp'] + 1 <= instant:
                    original = anchor
                break
        if original is None:
            net += signed_cash(item)
        result.append((key, item, original))
    return result, net


def signed_cash(item):
    return (item['cash_native'] if item['side'] == 'SELL' else -item['cash_native']) - item['fee_native']


def adjust_snapshot(book, anchor, delta):
    """Replace only a finite unexplained residual at this proved snapshot.

    Every new historical gross flow changes the old anonymous residual by its
    opposite net. A later opposing fill can therefore cancel the provisional
    adjustment made when only the first fill was visible. It never replays
    either gross flow or consumes another snapshot's quarantine.
    """
    if not delta:
        return
    sequence = anchor['ledger_cut']
    markers = book.wallet_debit_quarantines if delta > 0 else book.wallet_quarantines
    remaining = abs(delta)
    for marker in markers:
        if marker['sequence'] != sequence:
            continue
        available = marker['amount'] - (marker.get('explained_native', 0) if delta > 0 else 0)
        take = min(remaining, max(0, available))
        marker['amount'] -= take
        remaining -= take
        if not remaining:
            break
    if remaining:
        timestamp = int(utc(anchor['at_utc']).timestamp())
        if delta > 0:
            grant = book.credit('external', remaining, {'id': 'wallet-anchor-' + str(sequence),
                                'timestamp': timestamp}, sequence=sequence)
            book.wallet_quarantines.append(grant)
        else:
            from weather.market.lfc_f2_wallet_cash import owner_debit
            owner_debit(book, remaining, timestamp=timestamp, sequence=sequence)
    if delta:
        book.pools_dirty = True


def capture(book, found, sequence):
    planned, net = plan(book, found)
    groups = {}
    for key, item, original in sorted(planned, key=lambda row: (row[1]['timestamp'], row[0])):
        book.personal_trades[key] = item
        debit = item['fee_native'] + (item['cash_native'] if item['side'] == 'BUY' else 0)
        if debit:
            book.pool_movements.append({'kind': 'withdraw', 'amount': debit, 'timestamp': item['timestamp'],
                'sequence': sequence, 'charge_excess': False, 'activity_id': 'personal-' + key})
        if item['side'] == 'SELL':
            book.credit('external', item['cash_native'], {'id': 'personal-' + key,
                        'timestamp': item['timestamp']}, sequence=sequence)
        if original is not None:
            at = original['ledger_cut']
            previous = groups.get(at, (original, 0))[1]
            groups[at] = original, previous - signed_cash(item)
        book.pools_dirty = True
    for at in sorted(groups):
        anchor, delta = groups[at]
        adjust_snapshot(book, anchor, delta)
    return net
