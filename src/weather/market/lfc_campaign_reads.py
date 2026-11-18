"""Local observation intervals for the independent account-read components."""
from datetime import datetime, timedelta

from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign_state import StateRefused
from weather.market.mm_account_reads import order_terminal


ACCOUNT_READ_COMPONENTS = ('open_orders', 'trades', 'positions', 'balances', 'geography')


class TerminalBackfillRefused(StateRefused):
    """A named missing order exhausted readback or contradicted its binding."""


def terminal_order_facts(ledger, order_id, row):
    """Recognize the exact order; distinguish pending from contradictory facts."""
    leg = ledger.legs[ledger.by_order[order_id]]
    if (not isinstance(row, dict) or
            {str(row[key]) for key in ('id', 'order_id', 'orderID') if row.get(key) is not None} != {order_id}):
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
    if not order_terminal(row, order_id=order_id, size=leg['size']):
        return False
    if leg['status'] == 'terminal' and quantity(row['size_matched']) != quantity(leg['size_matched']):
        raise TerminalBackfillRefused('terminal_order_backfill_quantity')
    return True


def validate_terminal_backfill(ledger, order_ids, read, *, now):
    """Bind every requested GET to the account read and already booked fills."""
    from weather.market.mm_stage2_hold import utc
    try:
        observations = read['terminal_orders']
        begin, end = (datetime.fromisoformat(read[key]) for key in ('started_at_utc', 'ended_at_utc'))
        if (begin.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0) or
                not begin <= end <= now):
            raise ValueError('read_interval')
        for oid in order_ids:
            observed = observations[oid]
            start, finish = (datetime.fromisoformat(observed[key])
                             for key in ('started_at_utc', 'ended_at_utc'))
            leg = ledger.legs[ledger.by_order[oid]]
            session_end = ledger.sessions[leg['session_id']]['end']['recorded_at_utc']
            if (start.utcoffset() != timedelta(0) or finish.utcoffset() != timedelta(0) or
                    not begin <= start <= finish <= end or start < utc(session_end) or
                    leg['status'] != 'terminal' or not terminal_order_facts(ledger, oid, observed['row'])):
                raise ValueError('order_interval_or_terminal')
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        raise TerminalBackfillRefused('terminal_order_backfill_binding') from None


def account_read_age(read, now):
    """Conservative age of the oldest component, never the report write time."""
    def instant(value):
        if not isinstance(value, str):
            raise ValueError('timestamp_type')
        result = datetime.fromisoformat(value)
        if result.utcoffset() != timedelta(0):
            raise ValueError('timestamp_not_utc')
        return result

    try:
        begin, end = (instant(read[key]) for key in ('started_at_utc', 'ended_at_utc'))
        times = read['component_times']
        if not isinstance(times, dict) or set(times) != set(ACCOUNT_READ_COMPONENTS) or not begin <= end <= now:
            raise ValueError('observation_envelope')
        starts = []
        for name in ACCOUNT_READ_COMPONENTS:
            row = times[name]
            if not isinstance(row, dict) or set(row) != {'started_at_utc', 'ended_at_utc'}:
                raise ValueError('component_interval')
            start, finish = (instant(row[key]) for key in ('started_at_utc', 'ended_at_utc'))
            if not begin <= start <= finish <= end:
                raise ValueError('component_outside_envelope')
            starts.append(start)
        return (now - min(starts)).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise StateRefused('account_read_binding') from None
