"""Synthetic market-local midnight pulls through the real fixture controller.

Guards: B021/T032: stale selection never permits a disallowed local event day;
placements/requotes and resting orders respect Toronto/Denver local midnight.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from tests.market.stage2_fakes import CONDITION, TOKENS
from tests.market.test_lfc_pilot import Clock, OTHER, events, setup, snapshot
from weather.market import lfc_constants as C
from weather.market.lfc_horizon import local_event_dte
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import HoldEnd, digest
from weather.market.mm_stage2_selection import select_table, validate_selection


def horizon_table(clock, market, dte=1, allowed=None):
    zone = REGISTRY[market].timezone
    target = clock.now().astimezone(ZoneInfo(zone)).date() + timedelta(days=dte)
    slug = event_slug_for_date(target, market)
    value = snapshot(clock)
    value['fee_evidence']['event_slug'] = slug
    row = {'market_id': market, 'market_timezone': zone, 'target_date': target.isoformat(),
           'condition_id': CONDITION, 'token_ids': list(TOKENS), 'snapshot': value,
           'event_slug': slug, 'event_condition_ids': [CONDITION, OTHER]}
    return select_table([row], now=clock.now(), available_collateral='500', treatment=C.TREATMENT,
                        ledger={'L': '0', 'L_resting': '0'}, held_conditions=[], local_event_dte=allowed)


@pytest.mark.parametrize('market,hour', [('toronto', 3), ('denver', 5)])
def test_local_midnight_cancels_event_and_stops_quoting_mid_session(tmp_path, market, hour):
    base = datetime(2026, 10, 21, hour, 59, 58, tzinfo=timezone.utc)
    table = horizon_table(Clock(base), market)
    session, venue, clock, ledger = setup(tmp_path, base=base, table=table)
    result = session.run(rehearsal_seconds=10)
    assert result['reason'] == 'market_local_horizon' and result['cleanup_ok']
    assert result['post_count'] == 2 and set(venue.cancelled) == set(session.known)
    assert venue.open_orders() == [] and ledger.L() == 0
    retired = events(session, 'lfc_horizon_retired')
    assert retired[0]['current_local_event_dte'] == 0
    assert retired[0]['allowed_local_event_dte'] == [1, 2]
    assert clock.seconds < 10


@pytest.mark.parametrize('market,hour', [('toronto', 3), ('denver', 5)])
def test_stale_selection_crossing_midnight_cannot_place_or_requote(tmp_path, market, hour):
    base = datetime(2026, 10, 21, hour, 59, 58, tzinfo=timezone.utc)
    table = horizon_table(Clock(base), market)
    session, venue, clock, ledger = setup(tmp_path, base=base, table=table)
    clock.seconds = 3
    # The selection is only three seconds old; frozen creation-time validation
    # alone would still accept it. The actual placement gate must refuse.
    with pytest.raises(HoldEnd, match='market_local_horizon'):
        session.authorize_post(0, session.prices[0], session.size, {})
    assert not ledger.legs and not venue.memory.orders


@pytest.mark.parametrize('market,hour', [('toronto', 3), ('denver', 5)])
def test_allowed_tplus2_to_tplus1_transition_continues(tmp_path, market, hour):
    base = datetime(2026, 10, 21, hour, 59, 58, tzinfo=timezone.utc)
    table = horizon_table(Clock(base), market, dte=2)
    session, _, _, _ = setup(tmp_path, base=base, table=table)
    result = session.run(rehearsal_seconds=4)
    assert result['reason'] == 'fixed_end' and result['cleanup_ok']
    assert not events(session, 'lfc_horizon_retired')


def test_same_utc_time_has_distinct_market_local_horizons():
    now = datetime(2026, 10, 21, 5, tzinfo=timezone.utc)
    toronto = {'market_id': 'toronto', 'market_timezone': REGISTRY['toronto'].timezone, 'target_date': '2026-10-21'}
    denver = {'market_id': 'denver', 'market_timezone': REGISTRY['denver'].timezone, 'target_date': '2026-10-21'}
    assert local_event_dte(toronto, now) == 0 and local_event_dte(denver, now) == 1


def test_restricted_horizon_selection_reproduces_and_default_shape_is_unchanged():
    clock = Clock()
    default = horizon_table(clock, 'denver', dte=2)
    assert default['selected_condition_id'] == CONDITION and 'local_event_dte' not in default
    refused = horizon_table(clock, 'denver', dte=2, allowed=[1])
    assert refused['selected_condition_id'] is None
    selected = horizon_table(clock, 'denver', dte=1, allowed=[1])
    assert selected['local_event_dte'] == [1]
    assert validate_selection(selected, expected_sha256=digest(selected), condition_id=CONDITION,
                              token_ids=TOKENS, now=clock.now(), allow_sized=True)['condition_id'] == CONDITION


def test_cancel_race_fill_does_not_erase_horizon_retirement_reason(tmp_path):
    base = datetime(2026, 10, 21, 3, 59, 58, tzinfo=timezone.utc)
    session, venue, _, _ = setup(tmp_path, base=base, table=horizon_table(Clock(base), 'toronto'))
    original = venue.cancel
    raced = []
    def cancel(oid):
        if not raced:
            venue.memory.orders[oid]['size_matched'] = '1'
            raced.append(oid)
        return original(oid)
    venue.cancel = cancel
    result = session.run(rehearsal_seconds=10)
    assert result['reason'] == 'fill' and result['horizon_retirement']['reason'] == 'market_local_horizon'
