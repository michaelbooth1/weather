"""Gross SDK-confirmed personal cash movements between F2 wallet anchors."""
from decimal import Decimal, DecimalException, ROUND_HALF_UP

from weather.market.lfc_accounting import quantity
from weather.market.mm_stage2_hold import digest, utc


def terms(item):
    return {key: value for key, value in item.items() if key != 'source_sha256'}


def movements(ledger, rows, *, start, end, bound=None):
    from weather.market.lfc_capital import CapitalRefused, SCALE, native
    maker, ours = ledger.rows[0]['maker_address'].lower(), ledger.our_order_ids()
    bound = {} if bound is None else bound
    result = {}
    for row in rows:
        if str(row.get('status', '')).upper() == 'FAILED':
            continue
        parts = []
        if str(row.get('trader_side', '')).upper() == 'TAKER' and row.get('taker_order_id') not in ours:
            parts.append((row.get('taker_order_id'), row, 'size'))
        for part in row.get('maker_orders') or ():
            if part.get('order_id') not in ours:
                if str(part.get('maker_address', '')).lower() != maker:
                    continue
                parts.append((part.get('order_id'), part, 'matched_amount'))
        if not parts:
            continue
        try:
            timestamp = utc(row['matched_at']).timestamp()
            if timestamp < start:
                continue
            if timestamp > end or str(row.get('status', '')).upper() != 'CONFIRMED':
                raise ValueError('not confirmed in snapshot')
            trade_id = row['id']
            if not isinstance(trade_id, str) or not trade_id:
                raise ValueError('trade id')
            for order_id, part, size_key in parts:
                key = trade_id + '/' + str(order_id)
                side = str(part['side']).upper()
                price, size = quantity(part['price']), quantity(part[size_key])
                if not isinstance(order_id, str) or not order_id or side not in {'BUY', 'SELL'} or not 0 < price <= 1 or not size:
                    raise ValueError('trade terms')
                if key in bound:
                    fee_native = bound[key].get('fee_native', 0)
                else:
                    try:
                        fee_rate = part['fee_rate_bps']
                        if fee_rate is None and size_key == 'matched_amount':
                            fee_rate = 0
                        fee = size * quantity(fee_rate) / 10_000 * price * (1 - price)
                        fee_native = native(fee.quantize(Decimal('0.00001'), rounding=ROUND_HALF_UP))
                    except (KeyError, TypeError, ValueError, DecimalException):
                        raise CapitalRefused('f2_personal_trade_fee_unproven') from None
                amount = price * size
                cash = native(amount, ceil=True) if side == 'BUY' else int(amount * SCALE)
                item = {'id': key, 'order_id': order_id,
                        'timestamp': timestamp, 'side': side,
                        'cash_native': cash,
                        'fee_native': fee_native,
                        'source_sha256': digest(row)}
                if item['id'] in result and terms(result[item['id']]) != terms(item):
                    raise ValueError('changed duplicate')
                result[item['id']] = item
        except (KeyError, TypeError, ValueError, AttributeError, DecimalException) as exc:
            if isinstance(exc, CapitalRefused):
                raise
            raise CapitalRefused('f2_personal_trade_unproven') from None
    return result


def sources(book, read, snapshot_at):
    if book.inventory_anchor is None:
        return []
    first = book.inventory_anchors[0]
    start = utc(first.get('snapshot_at_utc', first['at_utc'])).timestamp()
    found = movements(book.ledger, read['trades'], start=start, end=utc(snapshot_at).timestamp(),
                      bound=book.personal_trades)
    for key, old in book.personal_trades.items():
        if key not in found or terms(found[key]) != terms(old):
            from weather.market.lfc_capital import CapitalRefused
            raise CapitalRefused('f2_personal_trade_changed')
    selected = {row['source_sha256'] for key, row in found.items() if key not in book.personal_trades}
    unique = {digest(row): row for row in read['trades'] if digest(row) in selected}
    return [unique[key] for key in sorted(unique)]


def capture(book, anchor, sequence):
    """Return signed personal cash already explained by these durable sources."""
    if 'personal_trade_sources' not in anchor:
        return 0  # Retained pre-B081 anchors keep their historical interpretation.
    if book.inventory_anchor is None or not book.inventory_anchors:
        if anchor['personal_trade_sources']:
            from weather.market.lfc_capital import CapitalRefused
            raise CapitalRefused('f2_personal_trade_binding')
        return 0
    first = book.inventory_anchors[0]
    found = movements(book.ledger, anchor['personal_trade_sources'],
        start=utc(first.get('snapshot_at_utc', first['at_utc'])).timestamp(),
        end=utc(anchor['snapshot_at_utc']).timestamp(), bound=book.personal_trades)
    net = 0
    for key, item in sorted(found.items(), key=lambda pair: (pair[1]['timestamp'], pair[0])):
        if key in book.personal_trades:
            from weather.market.lfc_capital import CapitalRefused
            raise CapitalRefused('f2_personal_trade_repeated')
        book.personal_trades[key] = item
        cash = item['cash_native']
        debit = item['fee_native'] + (cash if item['side'] == 'BUY' else 0)
        if debit:
            book.pool_movements.append({'kind': 'withdraw', 'amount': debit,
                'timestamp': item['timestamp'], 'sequence': sequence, 'charge_excess': False})
            book.pools_dirty = True
            net -= debit
        if item['side'] == 'SELL':
            book.credit('external', cash, {'id': 'personal-' + key, 'timestamp': item['timestamp']}, sequence=sequence)
            net += cash
    return net
