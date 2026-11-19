"""Local observation intervals for the independent account-read components."""
from datetime import datetime, timedelta

from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign_state import StateRefused
from weather.market.mm_account_reads import order_terminal


ACCOUNT_READ_COMPONENTS = ('open_orders', 'trades', 'positions', 'balances', 'geography')
TERMINAL_STATUSES = {'CANCELED', 'MATCHED', 'EXPIRED'}
PENDING_STATUSES = {'LIVE', 'DELAYED', 'UNMATCHED'}
BACKFILL_ARTIFACT = 'private-terminal-backfill'


class TerminalBackfillRefused(StateRefused):
    """A named missing order exhausted readback or contradicted its binding."""


def terminal_order_facts(ledger, order_id, row, *, legacy=False):
    """Recognize the exact order; return False only for a pending observation."""
    leg = ledger.legs[ledger.by_order[order_id]]
    if (not isinstance(row, dict) or
            {str(row[key]) for key in ('id', 'order_id', 'orderID') if row.get(key) is not None} != {order_id} or
            (not legacy and row.get('id') is None and row.get('order_id') is None)):
        raise TerminalBackfillRefused('terminal_order_backfill_identity')
    for key, expected in (('asset_id', leg['token_id']), ('token_id', leg['token_id']),
                          ('market', leg['condition_id']), ('condition_id', leg['condition_id']),
                          ('side', 'BUY')):
        if row.get(key) is not None and str(row[key]).lower() != str(expected).lower():
            raise TerminalBackfillRefused('terminal_order_backfill_identity')
    if row.get('price') is not None:
        try:
            price_matches = quantity(row['price']) == quantity(leg['price'])
        except (TypeError, ValueError, ArithmeticError):
            price_matches = False
        if not price_matches:
            raise TerminalBackfillRefused('terminal_order_backfill_price')
    if legacy and not order_terminal(row, order_id=order_id, size=leg['size']):
        return False
    if not legacy:
        statuses = set()
        for key in ('status', 'official_order_status'):
            if row.get(key) not in (None, ''):
                status = str(row[key]).upper()
                statuses.add('CANCELED' if status == 'CANCELLED' else status)
        if len(statuses) > 1 or statuses - TERMINAL_STATUSES - PENDING_STATUSES:
            raise TerminalBackfillRefused('terminal_order_backfill_status')
        terminal = bool(statuses & TERMINAL_STATUSES)
        try:
            size = quantity(leg['size'])
            if quantity(row.get('original_size', size)) != size:
                raise ValueError('size_changed')
            if ('size_matched' in row and quantity(row['size_matched']) > size or
                    terminal and 'size_matched' not in row):
                raise ValueError('matched_out_of_range')
        except (TypeError, ValueError, ArithmeticError):
            raise TerminalBackfillRefused('terminal_order_backfill_quantity') from None
        if leg['status'] == 'terminal' and statuses & PENDING_STATUSES:
            raise TerminalBackfillRefused('terminal_order_backfill_status')
        if not terminal:
            return False
    if leg['status'] == 'terminal' and quantity(row['size_matched']) != quantity(leg['size_matched']):
        raise TerminalBackfillRefused('terminal_order_backfill_quantity')
    return True


def _instant(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() != timedelta(0):
        raise ValueError('timestamp_not_utc')
    return result


def terminal_result_time(ledger, attempt):
    """The immutable attempt result ledger event is the named GET frontier."""
    try:
        row, = ledger.event_rows('autostart_result', field='attempt_id', value=attempt)
        return _instant(row['recorded_at_utc'])
    except (KeyError, TypeError, ValueError):
        raise TerminalBackfillRefused('terminal_order_backfill_result_anchor') from None


def stage_postcheck_terminals(ledger, order_ids, read, *, now, result_at, reconcile=False):
    """Check the whole packet before yielding any acknowledged terminal writes.

    Retained L5 receipts used the booked leg's band end and the old row parser.
    New captures and their retained receipts bind to the attempt result event.
    """
    try:
        observations = read.get('terminal_orders', {})
        required = set(order_ids)
        pending = {leg['order_id'] for leg in ledger.unresolved_legs()} if reconcile else set()
        ids = required | (pending & observations.keys())
        if not ids:
            return {}
        begin, end = (_instant(read[key]) for key in ('started_at_utc', 'ended_at_utc'))
        if not begin <= end <= now:
            raise ValueError('read_interval')
        writes = {}
        for oid in sorted(ids):
            observed = observations[oid]
            start, finish = (_instant(observed[key]) for key in ('started_at_utc', 'ended_at_utc'))
            leg = ledger.legs[ledger.by_order[oid]]
            frontier = result_at
            if frontier is None:  # A previously sealed L5 receipt.
                frontier = _instant(ledger.sessions[leg['session_id']]['end']['recorded_at_utc'])
            if not begin <= start <= finish <= end or start < frontier:
                raise ValueError('order_interval')
            if oid in pending and (now - start).total_seconds() > 120:
                raise ValueError('terminal_read_stale')
            row = observed['row']
            if oid in required:
                if (not reconcile and leg['status'] != 'terminal' or
                        not terminal_order_facts(ledger, oid, row, legacy=result_at is None)):
                    raise ValueError('order_not_terminal')
            if oid in pending and order_terminal(row, order_id=oid, size=leg['size']):
                writes[oid] = row
        return writes
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        raise TerminalBackfillRefused('terminal_order_backfill_binding') from None


def validate_terminal_backfill(ledger, order_ids, read, *, now, result_at=None):
    """Bind retained terminal GETs to their original account read and booked fills."""
    stage_postcheck_terminals(ledger, order_ids, read, now=now, result_at=result_at)


def account_read_age(read, now):
    """Conservative age of the oldest component, never the report write time."""
    try:
        begin, end = (_instant(read[key]) for key in ('started_at_utc', 'ended_at_utc'))
        times = read['component_times']
        if not isinstance(times, dict) or set(times) != set(ACCOUNT_READ_COMPONENTS) or not begin <= end <= now:
            raise ValueError('observation_envelope')
        starts = []
        for name in ACCOUNT_READ_COMPONENTS:
            row = times[name]
            if not isinstance(row, dict) or set(row) != {'started_at_utc', 'ended_at_utc'}:
                raise ValueError('component_interval')
            start, finish = (_instant(row[key]) for key in ('started_at_utc', 'ended_at_utc'))
            if not begin <= start <= finish <= end:
                raise ValueError('component_outside_envelope')
            starts.append(start)
        return (now - min(starts)).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise StateRefused('account_read_binding') from None
