"""Guards: T113 bounded completion hooks preserve arms, prices and evidence."""
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_pair_completion import AT, lot, state
from weather.market import lfc_pair_runtime as runtime
from weather.market.mm_stage2_hold import HoldEnd


def band(value=None):
    events = []
    value = state(lot(1, 0, 20, '.24')) if value is None else value
    return SimpleNamespace(campaign_policy=SimpleNamespace(raw={'post_fill_mode': 'complete_pairs'}),
        pair_state=value, pair_last_quote=None, pair_latest_trades=None, pair_state_sha=None,
        pair_completion_orders=set(), pair_seen_fills=set(), pair_since=AT, pair_elapsed=D(0),
        normal_trade_legs=(0,), TRADE_LEGS=(1,), LEG_PRICE_RANGE=(D('.17'), D('.80')),
        tokens=('yes', 'no'), prices=[D('.22'), D('.76')], OFFSET=D('.015'),
        start=AT, end=AT+timedelta(hours=1), clock=SimpleNamespace(now=lambda: AT+timedelta(seconds=100)),
        inventory_proven=False, condition='condition',
        journal=SimpleNamespace(record=lambda event, **row: events.append((event, row))), events=events)


def test_replacement_is_capped_before_ordinary_submit_and_overheld_side_refuses():
    b = band()
    assert runtime.submit_price(b, 1, D('.76')) == D('.74')
    assert b.prices[1] == D('.74') and b.pair_last_quote.uncapped_price == D('.76')
    with pytest.raises(HoldEnd) as caught:
        runtime.submit_price(b, 0, D('.22'))
    assert caught.value.reason == 'completion_overheld_side'


def test_fresh_cap_screen_cannot_authorize_stale_higher_price_or_wrong_size():
    b = band()
    runtime.submit_price(b, 1, D('.76'))
    runtime.authorize(b, 1, D('.74'), D(20))
    for leg, price, size in [(0, D('.22'), D(20)), (1, D('.74'), D(19)), (1, D('.75'), D(20))]:
        with pytest.raises(HoldEnd):
            runtime.authorize(b, leg, price, size)


def test_invalid_capped_price_waits_without_consuming_an_order_attempt():
    b = band(state(lot(1, 0, 20, '.82')))
    with pytest.raises(HoldEnd) as caught:
        runtime.submit_price(b, 1, D('.18'))
    assert caught.value.reason == runtime.WAIT
    assert b.events[-1][1]['completion_refusal'] == 'completion_leg_price_bounds'


def test_binding_cap_does_not_requote_itself_each_minute():
    b = band()
    b.prices[1] = D('.74')
    snapshot = {'quote_inputs': {'reward_min_size': '20'},
                'rules': {'no': {'tick_size': '.01', 'min_order_size': '5'}}}
    observation = runtime.observe(b, snapshot, {'adjusted_mid': '.20', 'requote_legs': [1]})
    assert observation['requote_legs'] == []
    assert b.events[-1][1]['uncapped_completion_price'] == '0.78'
    observation = runtime.observe(b, snapshot, {'adjusted_mid': '.27', 'requote_legs': []})
    assert observation['requote_legs'] == [1]


def test_over_completion_changes_effective_leg_without_resetting_the_original_arm_or_clock():
    b = band()
    new = state(lot(1, 0, 5, '.24'), lot(2, 1, 20, '.70'))
    runtime.accept_inventory(b, new, [])
    assert b.TRADE_LEGS == (0,) and b.normal_trade_legs == (0,)
    assert b.pair_since == AT
    assert b.events[-1][1]['over_completions'] == 1


def test_flat_restores_cheap_arm_and_closes_only_the_completion_interval():
    b = band()
    flat = state(lot(1, 0, 20, '.24'), lot(2, 1, 20, '.74'))
    runtime.accept_inventory(b, flat, [])
    assert b.TRADE_LEGS == b.normal_trade_legs == (0,)
    assert b.pair_since is None and b.pair_elapsed == 100
    assert runtime.terminal_extra(b)['pair_completion']['completion_seconds'] == '100.0'


def test_completion_order_and_fill_evidence_are_attributed_once():
    b = band()
    runtime.submit_price(b, 1, D('.76'))
    runtime.posted(b, 'completion-order')
    record = {'trade_id': 't2', 'own_order_id': 'completion-order', 'condition_id': 'condition',
              'money_counted': True, 'status': 'MINED', 'provenance': [{'source': 'rest'}]}
    new = state(lot(1, 0, 20, '.24'), lot(2, 1, 5, '.74'))
    runtime.accept_inventory(b, new, [record])
    runtime.accept_inventory(b, new, [record | {'status': 'CONFIRMED'}])
    assert len([e for e, _ in b.events if e == 'pair_completion_fill']) == 1
    assert b.events[1][0] == 'pair_completion_order'
    assert runtime.terminal_extra(b)['pair_completion']['u'] == '15'


def test_provenance_refresh_does_not_append_again_after_terminal_journal_closes():
    b = band()
    record = {'trade_id': 't', 'own_order_id': 'o', 'condition_id': 'condition',
              'money_counted': True, 'provenance': [{'source': 'rest', 'at': 'old'}]}
    runtime.accept_inventory(b, b.pair_state, [record])
    count = len(b.events)
    runtime.accept_inventory(b, b.pair_state, [record | {'provenance': [{'source': 'rest', 'at': 'new'}]}])
    assert len(b.events) == count


def test_elapsed_completion_is_bounded_by_fixed_end():
    b = band()
    b.clock = SimpleNamespace(now=lambda: b.end+timedelta(minutes=5))
    assert runtime.elapsed(b) == 3600


def test_missing_recovered_inventory_cannot_quote_as_flat():
    b = band()
    b.pair_state = None
    with pytest.raises(HoldEnd) as caught:
        runtime.submit_price(b, 0, D('.22'))
    assert caught.value.reason == 'completion_inventory_unproven'
