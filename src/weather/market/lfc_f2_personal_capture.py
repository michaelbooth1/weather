"""Reclassify late SDK executions against finite, already-captured owner cash.

Only anonymous adjustments from an earlier balance snapshot are eligible. A
replacement retains that adjustment's original time and ledger sequence; it
cannot restore gains already consumed or be spent by a later native proof.
"""
from weather.market.mm_stage2_hold import utc


def plan(book, found):
    reference = book.cash_reference or {}
    assigned, totals = {}, {}
    for key, item in found.items():
        if key in book.personal_trades:
            continue
        assigned[key] = None
        for anchor in book.inventory_anchors:
            if anchor['ledger_cut'] > reference.get('sequence', -1):
                continue
            instant = utc(anchor.get('cash_snapshot_at_utc', anchor['snapshot_at_utc'])).timestamp()
            if item['timestamp'] <= instant:
                # A later balance cannot capture a movement for the first time
                # if an earlier balance could already contain it. An overlap
                # stays gross; timestamps alone do not prove inclusion.
                if item['timestamp'] + 1 <= instant:
                    at = assigned[key] = anchor['ledger_cut']
                    totals[at] = totals.get(at, 0) + (
                        item['cash_native'] if item['side'] == 'SELL' else -item['cash_native']) - item['fee_native']
                break
    budgets = {(at, debit): max(0, -amount if debit else amount)
               for at, amount in totals.items() for debit in (True, False)}
    debits = {id(move): max(0, move['amount'] - move.get('explained_native', 0))
              for move in book.wallet_debit_quarantines}
    credits = {id(move): move['amount'] for move in book.wallet_quarantines}
    result, net = [], 0
    for key, item in sorted(found.items(), key=lambda pair: (pair[1]['timestamp'], pair[0])):
        if key in book.personal_trades:
            continue
        parts = []
        for debit, amount, markers, remaining in (
                (True, item['fee_native'] + (item['cash_native'] if item['side'] == 'BUY' else 0),
                 book.wallet_debit_quarantines, debits),
                (False, item['cash_native'] if item['side'] == 'SELL' else 0, book.wallet_quarantines, credits)):
            matched = []
            at = assigned[key]
            budget = budgets.get((at, debit), 0)
            for marker in markers:
                if not amount or not budget:
                    break
                if marker['sequence'] != at:
                    continue
                take = min(amount, budget, remaining[id(marker)])
                if take:
                    remaining[id(marker)] -= take
                    amount -= take
                    budget -= take
                    matched.append((marker, take))
            budgets[at, debit] = budget
            parts.append((debit, matched, amount))
            net += -amount if debit else amount
        result.append((key, item, parts))
    return result, net


def capture(book, found, sequence):
    planned, net = plan(book, found)
    for key, item, parts in planned:
        book.personal_trades[key] = item
        for debit, matched, remaining in parts:
            transfers = []
            for marker, amount in matched:
                marker['amount'] -= amount
                transfers.append((amount, marker['timestamp'], marker['sequence']))
            if remaining:
                transfers.append((remaining, item['timestamp'], sequence))
            for amount, timestamp, at in transfers:
                if debit:
                    book.pool_movements.append({'kind': 'withdraw', 'amount': amount, 'timestamp': timestamp,
                        'sequence': at, 'charge_excess': False, 'activity_id': 'personal-' + key})
                else:
                    book.credit('external', amount, {'id': 'personal-' + key, 'timestamp': timestamp}, sequence=at)
            if transfers:
                book.pools_dirty = True
    return net
