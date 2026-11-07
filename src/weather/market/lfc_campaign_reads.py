"""Local observation intervals for the independent account-read components."""
from datetime import datetime, timedelta

from weather.market.lfc_campaign_state import StateRefused


ACCOUNT_READ_COMPONENTS = ('open_orders', 'trades', 'positions', 'balances', 'geography')


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
