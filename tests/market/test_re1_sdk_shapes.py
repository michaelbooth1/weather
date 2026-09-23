"""Construct SDK 0.6.0 reply models, then use the real plain-value adapter."""
from types import SimpleNamespace
import json

import pytest

pytest.importorskip('polymarket')

from tests.market.stage2_fakes import CONDITION, TOKENS, MAKER
from tests.market.test_re1_attended import setup
from tests.market.test_mm_stage2_rewards import sdk_fixture
from weather.market.mm_official_adapter import _plain_sdk_value, _value, OfficialPolymarketGlobalAdapter
from weather.market.mm_stage2_hold import _cancel_ack_ids, _exact_open_orders
from weather.market.re1_transport import OwnerVenue, bounded_rows


def sdk_order(status='LIVE'):
    from polymarket.models.clob.account import OpenOrder
    return OpenOrder.model_validate(dict(id='order-1', market=CONDITION, asset_id=TOKENS[0],
        owner='fixture', maker_address=MAKER, side='BUY', price='.33', original_size='20',
        size_matched='0', outcome='Yes', order_type='GTD', status=status, created_at=1800000000,
        expiration='1800021600', associate_trades=[]))


def test_sdk_accepted_and_raw_post_models_pass_controller(tmp_path):
    from polymarket.models.clob.order_response import RawOrderResponse, normalize_order_response
    for raw_reply in (False, True):
        session, venue, _ = setup(tmp_path / str(raw_reply))
        original = venue.submit
        def submit(request, **kwargs):
            response = original(request, **kwargs)
            model = RawOrderResponse.model_validate(dict(errorMsg='', makingAmount='6.6',
                takingAmount='20', orderID=response['order_id'], status='live', success=True, tradeIDs=[]))
            return _plain_sdk_value(model if raw_reply else normalize_order_response(model))
        venue.submit = submit
        result = session.run(rehearsal_seconds=1)
        assert result['post_count'] == 2 and result['reason'] == 'fixed_end' and result['cleanup_ok']
    assert _value({'success': True}, 'ok', 'success') is True
    assert _value({'orderID': 'wire'}, 'order_id', 'orderID') == 'wire'


def test_sdk_cancel_models_and_open_order_model_normalization():
    from polymarket.models.clob.cancel import CancelOrdersResponse
    cancelled = CancelOrdersResponse(canceled=('order-1',), not_canceled={})
    client = SimpleNamespace(cancel_order=lambda **kw: cancelled, cancel_all=lambda: cancelled,
                             get_order=lambda **kw: sdk_order(), list_open_orders=lambda: [])
    adapter = OfficialPolymarketGlobalAdapter(client, maker_address=MAKER, condition_id=CONDITION, sdk_version='0.6.0')
    assert _cancel_ack_ids(adapter.cancel_order('order-1')) == {'order-1'}
    assert _cancel_ack_ids(_plain_sdk_value(client.cancel_all())) == {'order-1'}
    order = adapter.get_order('order-1')
    _exact_open_orders([order], {'order-1': (TOKENS[0], __import__('decimal').Decimal('.33'), 20)}, maker=MAKER, condition=CONDITION)
    assert order['token_id'] == TOKENS[0] and order['status'] == 'LIVE' and order['size_matched'] == '0'
    assert bounded_rows([SimpleNamespace(items=(sdk_order(),), next_cursor=None)]) == [order]


def test_sdk_trade_model_retains_fill_facts():
    from polymarket.models.clob.account import ClobTrade, MakerOrder
    maker_order = MakerOrder.model_validate(dict(order_id='order-1', asset_id=TOKENS[0], maker_address=MAKER,
        owner='fixture', side='BUY', price='.33', matched_amount='.1', outcome='Yes', fee_rate_bps='0'))
    trade = ClobTrade.model_validate(dict(id='trade-1', market=CONDITION, asset_id=TOKENS[0], owner='fixture',
        maker_address=MAKER, taker_order_id='taker-1', side='SELL', trader_side='MAKER', price='.33', size='.1',
        outcome='Yes', status='TRADE_STATUS_MATCHED', fee_rate_bps='0', bucket_index=0, transaction_hash='',
        maker_orders=(maker_order,), match_time=1800000000, last_update=1800000000))
    rows = bounded_rows([SimpleNamespace(items=(trade,), next_cursor=None)])
    assert rows[0]['status'] == 'MATCHED'
    assert rows[0]['maker_orders'][0]['matched_amount'] == '0.1'


def test_sdk_credential_owner_is_redacted_without_losing_order_binding():
    from weather.market.re1_attended import SecretGuard
    private_owner = 'synthetic-private-api-key'
    row = _plain_sdk_value(sdk_order().model_copy(update={'owner': private_owner}))
    guard = SecretGuard([private_owner])
    cleaned = guard.clean(row)
    assert 'owner' not in cleaned and cleaned['id'] == 'order-1'
    _exact_open_orders([cleaned], {'order-1': (TOKENS[0], __import__('decimal').Decimal('.33'), 20)}, maker=MAKER, condition=CONDITION)
    with pytest.raises(RuntimeError, match='secret_output_refused'):
        guard.clean({'unexpected_field': private_owner})


@pytest.mark.parametrize('status', ['CANCELED', 'CANCELLED', 'EXPIRED', 'MATCHED', 'DELAYED', 'UNMATCHED', 'unknown'])
def test_nonresting_sdk_status_ends_and_cancels(tmp_path, status):
    session, venue, clock = setup(tmp_path)
    original = venue.order
    def order(oid):
        row = original(oid)
        if clock.seconds >= 20 and not session.closed:
            model = sdk_order(status).model_copy(update={'id': oid})
            row.update(_plain_sdk_value(model))
            if status == 'MATCHED': row['size_matched'] = '.1'
        return row
    venue.order = order
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == ('fill' if status == 'MATCHED' else 'order_no_longer_resting')
    assert result['cleanup_ok'] and not venue.open_orders()


def test_sdk_scoring_parser_has_no_model_and_empty_list_is_rejected():
    from polymarket.errors import UserInputError
    client, http, calls = sdk_fixture()
    try:
        with pytest.raises(UserInputError): client.get_orders_scoring(order_ids=[])
        assert calls == []
        assert _plain_sdk_value(client.get_orders_scoring(order_ids=['order-1'])) == {'order-1': True}
    finally:
        http.close()


def test_response_hook_never_raises_non_json_or_secret_guard_failure():
    import httpx
    records = []
    http = httpx.Client(base_url='https://clob.polymarket.com',
                         transport=httpx.MockTransport(lambda req: httpx.Response(502, content=b'upstream unavailable')))
    venue = object.__new__(OwnerVenue)
    venue.client = SimpleNamespace(_ctx=SimpleNamespace(secure_clob=SimpleNamespace(_client=http)))
    venue.set_journal(SimpleNamespace(record=lambda event, **fields: records.append((event, fields))))
    try:
        assert http.get('/data/order/one').status_code == 502
        row = records[-1][1]
        assert row['response'] is None and row['length'] == 20 and len(row['sha256']) == 64
        def failed(*args, **kwargs): raise RuntimeError('secret_output_refused')
        venue.set_journal(SimpleNamespace(record=failed))
        # Invoke only the response hook; request journaling is allowed to fail
        # before transmission. No response hook may hide an accepted order.
        response = httpx.Response(200, json={'secret': 'synthetic'}, request=httpx.Request('POST', 'https://clob.polymarket.com/order'))
        http.event_hooks['response'][-1](response)
        assert venue.journal_failed
    finally:
        http.close()


def sdk_earnings_models():
    from polymarket.models.clob.rewards import UserEarning, TotalUserEarning, UserRewardsEarning
    from weather.market.re1_transport import ASSETS
    from weather.market.mm_exchange_reports import INCENTIVE_CASH_ASSET
    rows = [UserEarning.model_validate(dict(date='2026-09-01T00:00:00Z', maker_address=MAKER,
        condition_id=CONDITION, asset_address=asset, asset_rate='1',
        earnings='1.250000' if asset.lower() == INCENTIVE_CASH_ASSET['asset_address'] else '0')) for asset in ASSETS]
    totals = [TotalUserEarning.model_validate(r.model_dump(exclude={'condition_id'})) for r in rows]
    config = UserRewardsEarning.model_validate(dict(condition_id=CONDITION, maker_address=MAKER,
        earning_percentage=1.0, earnings=[r.model_dump(include={'asset_address', 'asset_rate', 'earnings'}) for r in rows],
        event_slug='test', image='', market_competitiveness=0, market_slug='test', question='fixture',
        rewards_config=[dict(asset_address=r.asset_address, start_date='2026-09-01T00:00:00Z',
            end_date='2026-09-02T00:00:00Z', rate_per_day='40', total_rewards='40') for r in rows],
        rewards_max_spread=3, rewards_min_size='20', tokens=[]))
    return rows, totals, config


def test_earnings_reply_models_reach_real_reconciler_vocabulary():
    from weather.market.re1_payout_evidence import normalize_earnings
    from weather.market.mm_stage2_hold import utc
    from tests.market.test_mm_paid_incentive_reconciliation import evidence_fixture
    rows, totals, config = sdk_earnings_models()
    plain = _plain_sdk_value(rows)
    scope = dict(evidence_fixture()['scope'], maker_address=MAKER, condition_id=CONDITION)
    normalized, complete = normalize_earnings([(r, 'a' * 64) for r in plain],
        [(r, 'b' * 64) for r in _plain_sdk_value(totals)], scope, utc('2026-09-04T01:00:00Z'))
    assert complete and {r['status'] for r in normalized} == {'ACCRUED', 'COMPLETED_ZERO'}
    assert sorted(r['amount'] for r in normalized) == ['0', '1.250000']
    assert _plain_sdk_value(config)['earnings'][0]['asset_rate'] == '1'
    opened, _ = normalize_earnings([(r, 'a' * 64) for r in plain], [], scope, utc('2026-09-01T12:00:00Z'))
    assert {r['status'] for r in opened} == {'ESTIMATED'}


def test_sdk_reward_activity_has_no_earned_period_or_condition():
    from polymarket.models.data.activity import RewardActivity
    row = RewardActivity.model_validate(dict(proxyWallet=MAKER, timestamp=1788350400,
        transactionHash='0x' + '1' * 64, type='REWARD', amount='1.25'))
    plain = _plain_sdk_value(row)
    assert plain['wallet'] == MAKER and plain['amount'] == '1.25'
    assert not {'date', 'accrual_id', 'condition_id', 'asset_address', 'log_index'} & plain.keys()
