"""Guards: B090-K canonical trade/order identity, lifecycle provenance and unchanged money status rules."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_own_trades import OwnTradeProjection
from weather.market.lfc_ledger import traded_shares
from weather.market.lfc_recording_io import strict_json


def trade(status='CONFIRMED', tid='trade-1', size='5'):
    return {'id': tid, 'status': status, 'market': 'condition', 'price': '.7', 'size': '999',
        'maker_orders': [{'order_id': 'own', 'asset_id': 'yes', 'matched_amount': size, 'price': '.3', 'side': 'BUY'},
                         {'order_id': 'foreign', 'asset_id': 'no', 'matched_amount': '994', 'price': '.7'}]}


def stream(status='MATCHED'):
    return {'trade_id': 'trade-1', 'official_event_type': 'trade', 'official_trade_status': status,
        'order_id': 'own', 'clob_token_id': 'yes', 'condition_id': 'condition',
        'fill_size': '5', 'fill_price': '.30', 'side': 'BUY'}


def test_stream_and_rest_one_own_record_with_explicit_final_state_and_provenance():
    projection = OwnTradeProjection()
    projection.ingest([stream()], {'own'}, source='stream', observed_at_utc='first')
    provisional = projection.rows()[0]
    assert provisional['state'] == 'provisional' and not provisional['final'] and provisional['money_counted']
    projection.ingest([trade(), trade()], {'own'}, source='rest', observed_at_utc='second')
    assert len(projection.rows()) == 1 and projection.traded_shares() == {'own': '5'}
    row = projection.rows()[0]
    assert row['final'] and row['state'] == 'confirmed' and row['price'] in ('.3', '0.3')
    assert {p['source'] for p in row['provenance']} == {'stream', 'rest'}
    projection.ingest([stream()], {'own'}, source='stream', observed_at_utc='late-replay')
    assert projection.rows()[0]['status'] == 'CONFIRMED'
    for _ in range(100):
        projection.ingest([trade()], {'own'}, source='rest', observed_at_utc='repeated')
    assert len(projection.rows()[0]['provenance']) == 2


@pytest.mark.parametrize('status', ['MATCHED', 'MINED', 'RETRYING', 'CONFIRMED', 'UNKNOWN', ''])
def test_existing_nonfailed_statuses_still_count_for_money(status):
    assert traded_shares([trade(status)], {'own'}) == {'own': '5'}
    assert traded_shares([trade('FAILED')], {'own'}) == {}


def test_final_failed_supersedes_provisional_without_changing_failed_rule():
    projection = OwnTradeProjection()
    projection.ingest([stream()], {'own'}, source='stream')
    projection.ingest([trade('FAILED')], {'own'}, source='rest')
    assert projection.traded_shares() == {}
    assert projection.rows()[0]['state'] == 'failed' and projection.rows()[0]['final']


def test_failed_accounting_row_is_ignored_before_parsing_its_amounts():
    failed = trade('FAILED', size='unsettled-invalid-amount')
    assert traded_shares([failed, trade()], {'own'}) == {'own': '5'}


@pytest.mark.parametrize('post_fill_mode', ['continue', 'complete_pairs'])
def test_lifecycle_or_rest_replay_does_not_restart_post_fill_recording(post_fill_mode):
    from weather.market.lfc_f2_controller import F2Band
    triggers, updates = [], []
    band = SimpleNamespace(known={'own'}, own_trades=OwnTradeProjection(),
        campaign_policy=SimpleNamespace(raw={'post_fill_mode': post_fill_mode}),
        ledger=SimpleNamespace(by_order={'own': 'key'}, legs={'key': {}}),
        clock=SimpleNamespace(now=lambda: SimpleNamespace(isoformat=lambda: 'collection-time')),
        record_post_books=triggers.append,
        journal=SimpleNamespace(record=lambda event, **fields: updates.append(fields)))
    F2Band.project_trades(band, [stream()], source='stream')
    F2Band.project_trades(band, [trade()], source='rest')
    F2Band.project_trades(band, [stream()], source='stream')
    assert triggers == ['fill'] and len(updates) >= 2
    assert band.own_trades.rows()[0]['state'] == 'confirmed'


def test_trade_identity_includes_own_order_and_two_trades_on_one_order():
    first = trade()
    first['maker_orders'].append({'order_id': 'other-own', 'matched_amount': '2', 'price': '.31'})
    projection = OwnTradeProjection()
    projection.ingest([first, trade(tid='trade-2'), first], {'own', 'other-own'}, source='rest')
    assert len(projection.rows()) == 3
    assert projection.traded_shares() == {'other-own': '2', 'own': '10'}


@pytest.mark.parametrize('field,value', [('matched_amount', '6'), ('price', '.4'), ('asset_id', 'foreign-token')])
def test_conflicting_same_identity_refuses(field, value):
    projection = OwnTradeProjection()
    projection.ingest([trade()], {'own'}, source='rest')
    other = deepcopy(trade()); other['maker_orders'][0][field] = value
    with pytest.raises(ValueError, match='own_trade_conflict'):
        projection.ingest([other], {'own'}, source='rest')


def test_final_conflict_and_record_budget_refuse():
    projection = OwnTradeProjection(limit=1)
    projection.ingest([trade()], {'own'}, source='rest')
    with pytest.raises(ValueError, match='own_trade_final_conflict'):
        projection.ingest([trade('FAILED')], {'own'}, source='rest')
    with pytest.raises(ValueError, match='own_trade_record_budget'):
        projection.ingest([trade(tid='trade-2')], {'own'}, source='rest')


def test_legacy_missing_trade_id_is_named_and_not_claimed_as_venue_identity():
    row = trade(); del row['id']
    projection = OwnTradeProjection()
    projection.ingest([row, row], {'own'}, source='rest')
    assert len(projection.rows()) == 1 and projection.traded_shares() == {'own': '5'}
    assert projection.rows()[0]['identity_basis'] == 'legacy_content_sha256'


def test_controller_final_projection_and_fill_rows_share_the_accounting_source(tmp_path):
    controller, account, _, ledger, clock, runtime, read = fixture(tmp_path, seconds=300)
    result = controller.run()
    assert result['cleanup_ok'], result
    first = controller.bands[0]
    projection = first.own_trades.rows()
    assert projection and all(row['state'] == 'confirmed' for row in projection)
    assert first.own_trades.traded_shares() == traded_shares(read()['trades'], first.known)
    rows = [strict_json(line) for line in first.journal.path.read_bytes().splitlines()]
    fills = [row for row in rows if row['event'] == 'fill']
    assert fills and all(row['rows'] for row in fills)
    assert all('trade_id' in record and 'own_order_id' in record for row in fills for record in row['rows'])
    prediction = strict_json((first.directory / 'prediction.json').read_bytes())
    assert prediction['own_trade_projection'] == projection
