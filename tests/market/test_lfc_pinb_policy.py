"""Guards: B072 schema-scoped duration, dates, hard stop and local T+1."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from weather.market.lfc_campaign_policy import parse_policy, PolicyRefused, ZONE
from weather.market.lfc_f2_breadth import example_policy, captured_market_ids
from weather.market.lfc_horizon import local_event_dte
from weather.market.market_registry import REGISTRY


def test_pinb_admits_35100_seconds_and_late_go_keeps_1845_end():
    policy = parse_policy(pinb_row())
    entry = next(e for e in policy.entries if e.local_date == '2026-11-16')
    now = datetime(2026, 11, 16, 9, tzinfo=ZONE).astimezone(timezone.utc)
    assert entry.seconds == 35100 and entry.permits(now)
    assert entry.session_end(now).astimezone(ZONE).isoformat() == '2026-11-16T18:45:00-05:00'
    late = now + timedelta(minutes=14)
    assert entry.permits(late) and entry.session_end(late) == entry.session_end(now)
    assert entry.session_end(late).strftime('%H:%M') == '23:45'


def test_pinb_has_no_transition_gap_and_exactly_thirty_confirmation_dates():
    policy = parse_policy(pinb_row())
    dates = {e.local_date for e in policy.entries}
    assert {'2026-11-16', '2026-11-22', '2026-11-23', '2026-12-22'} <= dates
    assert len([d for d in dates if '2026-11-23' <= d <= '2026-12-22']) == 30
    assert '2026-12-23' not in dates
    assert policy.raw['success_looks'] == ['2026-12-28T18:00:00-05:00']


@pytest.mark.parametrize('day', ['2026-11-11', '2026-11-16', '2026-11-23', '2026-12-22'])
def test_all_twelve_builtins_remain_t1_through_1845_toronto(day):
    start = datetime.fromisoformat(day+'T09:00:00').replace(tzinfo=ZONE).astimezone(timezone.utc)
    end = datetime.fromisoformat(day+'T18:45:00').replace(tzinfo=ZONE).astimezone(timezone.utc)
    markets = captured_market_ids()
    assert len(markets) == 12
    for market in markets:
        zone = REGISTRY[market].timezone
        row = {'market_id': market, 'market_timezone': zone,
               'target_date': (start.astimezone(ZoneInfo(zone)).date()+timedelta(days=1)).isoformat()}
        for minute in range(0, 586):
            now = start+timedelta(minutes=minute)
            assert now <= end and local_event_dte(row, now) == 1, (market, now)


@pytest.mark.parametrize('value', [35101, True, 299])
def test_pinb_refuses_unsupported_duration(value):
    row = pinb_row(); row['max_session_seconds'] = value
    with pytest.raises(PolicyRefused): parse_policy(row)


def test_pina_schema_still_refuses_an_extended_duration():
    row = example_policy(); row['max_session_seconds'] = 35100
    with pytest.raises(PolicyRefused, match='unsupported_max_session_seconds'): parse_policy(row)


@pytest.mark.parametrize('key,value', [
    ('max_submits_per_band', 41), ('max_submits_per_band', True), ('max_requotes_per_band', 17),
    ('learning_leg_arms', []), ('learning_leg_arms', ['cheap', 'cheap']),
    ('learning_leg_arms', ['unsupported']), ('confirmation_leg_arm', 'unsupported'),
    ('trading_end_toronto', '18:46:00'), ('tokens', ['CHEAP']),
    ('learning_dates', ['2026-11-09', '2026-11-23']), ('transition_no_entry_date', '2026-11-16'),
    ('confirmation_dates', ['2026-11-24', '2026-12-22']), ('nominal_confirmation_dates', 29),
    ('freeze_deadline_toronto', '2026-11-16T18:00:00-05:00')])
def test_pinb_refuses_unsupported_new_field_values(key, value):
    row = pinb_row(); row[key] = value
    with pytest.raises(PolicyRefused): parse_policy(row)
