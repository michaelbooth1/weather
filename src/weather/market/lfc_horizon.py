"""Current market-local event horizon; selection age never grants a T+0 order."""
from datetime import date
from zoneinfo import ZoneInfo

from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import utc


def local_event_dte(row, now):
    market = row['market_id']
    zone = row['market_timezone']
    if market not in REGISTRY or zone != REGISTRY[market].timezone:
        raise ValueError('market_local_horizon_identity')
    target = date.fromisoformat(row['target_date'])
    return (target - utc(now).astimezone(ZoneInfo(zone)).date()).days


def horizon_allowed(row, now, allowed=(1, 2)):
    return local_event_dte(row, now) in allowed
