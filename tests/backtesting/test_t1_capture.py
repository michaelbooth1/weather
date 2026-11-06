"""Guards: charter captured-book fidelity, own-liquidity exclusion and execution-time lineage."""
from decimal import Decimal as D

import pytest

from tests.backtesting.t1_fixtures import BASE, at, book
from weather.backtesting.t1_capture import captured_book, captured_print, pin_snapshot


def test_pin_snapshot_terms_and_own_bid_complement_are_removed():
    b = book()
    snapshot = {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'], 'observed_at_utc': at(0),
                'rules': {token: {'tick_size': '.01', 'min_order_size': '5'} for token in ('yes1', 'no1')},
                'quote_inputs': {'yes_bids': b['YES']['bids'], 'yes_asks': b['YES']['asks'],
                                 'no_bids': b['NO']['bids'], 'no_asks': b['NO']['asks'],
                                 'reward_min_size': '5', 'reward_max_spread_cents': '3', 'reward_rate_per_day': '50'}}
    result, terms = pin_snapshot(snapshot, available_at=at(0), valid_until=at(30),
                                 own=[{'outcome': 'YES', 'price': '.49', 'remaining': '5'}])
    assert result['YES']['bids'][0]['size'] == 15
    assert result['NO']['asks'][0]['size'] == 15
    assert result['NO']['bids'][0]['size'] == 20
    assert terms['min_size'] == '5'
    assert len(terms['source_sha256']) == 64


def test_captured_book_refuses_missing_own_size():
    b = book()
    raw = {token: {'asset_id': token, 'market': 'c1', 'bids': b[outcome]['bids'], 'asks': b[outcome]['asks'],
                   'tick_size': '.01', 'min_order_size': '5'}
           for token, outcome in (('yes1', 'YES'), ('no1', 'NO'))}
    with pytest.raises(ValueError, match='own size missing'):
        captured_book(raw, condition_id='c1', token_ids=['yes1', 'no1'], captured_at=at(0), observed_at=at(0),
                      source_sha256='a' * 64, own=[{'outcome': 'YES', 'price': '.49', 'remaining': '21'}])


def test_execution_receipt_time_is_distinct_from_trade_time_and_id_required():
    row = {'event_type': 'last_trade_price', 'asset_id': 'yes1', 'side': 'SELL', 'price': '.49',
           'size': '10', 'timestamp': str(int(BASE.timestamp() * 1000)), 'execution_id': 'trade-1'}
    out = captured_print(row, captured_at=at(2), condition_id='c1', token_ids=['yes1', 'no1'], source_sha256='b' * 64)
    assert out['traded_at'] == at(0)
    assert out['at'] == at(2)
    assert D(out['price']) == D('.49')
    row.pop('execution_id')
    with pytest.raises(ValueError, match='execution ID'):
        captured_print(row, captured_at=at(2), condition_id='c1', token_ids=['yes1', 'no1'], source_sha256='b' * 64)


def test_pin_batch_start_is_age_bound_and_journal_time_is_availability():
    b = book()
    snapshot = {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'], 'observed_at_utc': at(0),
                'rules': {token: {'tick_size': '.01', 'min_order_size': '5'} for token in ('yes1', 'no1')},
                'quote_inputs': {'yes_bids': b['YES']['bids'], 'yes_asks': b['YES']['asks'],
                                 'no_bids': b['NO']['bids'], 'no_asks': b['NO']['asks'],
                                 'reward_min_size': '5', 'reward_max_spread_cents': '3', 'reward_rate_per_day': '50'}}
    captured, terms = pin_snapshot(snapshot, available_at=at(3), valid_until=at(30))
    assert captured['at'] == terms['at'] == at(3)
    assert captured['observed_at'] == at(0)
    assert captured['YES']['tick'] == '.01'
