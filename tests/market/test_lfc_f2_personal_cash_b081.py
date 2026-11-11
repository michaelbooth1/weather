"""Guards: B081 gross personal debits cannot preserve spent refill gains."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_capital import MAKER, filled
from tests.market.test_lfc_redemption_native import paired
from weather.market.lfc_capital import CapitalBook, CapitalRefused, record_activity
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_f2_pinb import example_policy
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import write_new
from weather.market.mm_stage2_hold import digest


@pytest.fixture
def account_guard():
    from tests.market.test_lfc_campaign import Mutexes
    from weather.market.lfc_campaign_guard import account_lease
    with account_lease(MAKER, backend=Mutexes()):
        yield


def gained_wallet(tmp_path):
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    source, proof, tokens = paired(auto=True)
    for index, token in enumerate(tokens):
        filled(ledger, f'pair-{index}', token=token, condition=source['condition_id'], price='.48')
    read = observation(ledger, clock, positions={'denver': '20', 'owner-old-nfl': '20',
                                              **{token: '20' for token in tokens}}, cash='270.8')
    synchronize(ledger, baseline, read, anchor_mode='enrollment', loss_basis='net_of_retained_gains')
    clock.value += timedelta(minutes=1)
    source['timestamp'] = int(clock.now().timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    record_activity(ledger, source, native_evidence=proof)
    clock.value += timedelta(hours=1)
    read = observation(ledger, clock, positions={'denver': '20', 'owner-new-nfl': '20'}, cash='290.8')
    return ledger, clock, read


def owner_trade(clock, side, *, role='TAKER', status='CONFIRMED', seconds=1):
    from polymarket.models.clob.account import ClobTrade
    # Real installed SDK parsing and normalized dump, including maker-side legs.
    row = {'id': 'owner-' + side, 'market': '0x' + 'c' * 64, 'asset_id': '90',
           'owner': 'owner', 'maker_address': MAKER, 'taker_order_id': 'taker-' + side,
           'side': side, 'trader_side': role, 'price': '.52', 'size': '20', 'outcome': 'Yes',
           'status': status, 'fee_rate_bps': '0', 'bucket_index': 0,
           'transaction_hash': '0x' + '1' * 64, 'match_time': int(clock.now().timestamp()) - seconds,
           'last_update': int(clock.now().timestamp()), 'maker_orders': []}
    if role == 'MAKER':
        row['maker_orders'] = [{'order_id': 'maker-' + side, 'asset_id': '90', 'maker_address': MAKER,
            'owner': 'owner', 'side': side, 'price': '.52', 'matched_amount': '20', 'outcome': 'Yes', 'fee_rate_bps': '0'}]
    return ClobTrade.model_validate(row).model_dump(mode='json', by_alias=False)


@pytest.mark.parametrize('role', ['MAKER', 'TAKER'])
@pytest.mark.parametrize('sale_first', [False, True])
def test_gross_personal_round_trip_consumes_gain_and_replay_cannot_restore_it(tmp_path, role, sale_first):
    ledger, clock, read = gained_wallet(tmp_path)
    buy = owner_trade(clock, 'BUY', role=role, seconds=1 if sale_first else 2)
    sale = owner_trade(clock, 'SELL', role=role, seconds=2 if sale_first else 1)
    read['trades'].extend([buy, sale, deepcopy(buy)])  # Equal duplicate is one execution.
    path = tmp_path / 'campaign.json'
    write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.clock, runtime.policy_path, runtime.preparing_f2 = clock, path, True
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER, root=tmp_path / 'state')
    assert runtime.core_proof(ledger, read, loss_basis='net_of_retained_gains')['money_accounting_complete']
    book = CapitalBook(ledger)
    figures = book.figures(loss_basis='net_of_retained_gains')
    assert figures['retained_gains_available_native'] == 0
    assert figures['headroom_native'] == 280_400_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='290', available_cash='290.8', loss_basis='net_of_retained_gains')
    for index in range(27):
        clock.value += timedelta(days=1)
        filled(ledger, 'later-' + str(index), token='later-' + str(index), condition='later-' + str(index))
    book = CapitalBook(ledger)
    assert book.figures(loss_basis='net_of_retained_gains')['unrecovered_inventory_cost_native'] == 280_000_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='19.6', available_cash='20.8', loss_basis='net_of_retained_gains')
    reopened = Ledger.open(ledger.path, clock=clock.now)
    assert CapitalBook(reopened).figures(loss_basis='net_of_retained_gains') == book.figures(loss_basis='net_of_retained_gains')
    assert len(CapitalBook(reopened).personal_trades) == 2


@pytest.mark.parametrize('fault,code', [('status', 'f2_personal_trade_unproven'),
    ('timestamp', 'f2_personal_trade_unproven'), ('price', 'f2_personal_trade_unproven'),
    ('fee', 'f2_personal_trade_fee_unproven'), ('duplicate', 'f2_personal_trade_unproven')])
def test_unproven_personal_flow_refuses_before_an_anchor(tmp_path, fault, code):
    ledger, clock, read = gained_wallet(tmp_path)
    buy = owner_trade(clock, 'BUY')
    read['trades'].append(buy)
    if fault == 'status':
        buy['status'] = 'MATCHED'
    elif fault == 'timestamp':
        buy['matched_at'] = 'unreadable'
    elif fault == 'price':
        buy['price'] = 'NaN'
    elif fault == 'fee':
        buy['fee_rate_bps'] = '100'
    else:
        read['trades'].append({**buy, 'price': '.51'})
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match=code):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert ledger.path.read_bytes() == before


def test_optional_maker_fee_cannot_hide_a_nonzero_trade_fee(tmp_path):
    ledger, clock, read = gained_wallet(tmp_path)
    buy = owner_trade(clock, 'BUY', role='MAKER')
    buy['fee_rate_bps'] = '100'
    buy['maker_orders'][0]['fee_rate_bps'] = None
    read['trades'].append(buy)
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='f2_personal_trade_fee_unproven'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert ledger.path.read_bytes() == before


def test_repeated_snapshot_and_changed_or_missing_personal_trade_cannot_recredit(tmp_path):
    ledger, clock, read = gained_wallet(tmp_path)
    read['trades'].extend([owner_trade(clock, 'BUY', seconds=2), owner_trade(clock, 'SELL')])
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    book = CapitalBook(ledger)
    before = book.figures(loss_basis='net_of_retained_gains')
    synchronize(ledger, book.inventory_anchor, read, anchor_mode='session')
    assert CapitalBook(ledger).figures(loss_basis='net_of_retained_gains') == before
    read['capital_activity'] = observation(ledger, clock,
        positions={'denver': '20', 'owner-new-nfl': '20'}, cash='290.8')['capital_activity']
    read['trades'][-1]['price'] = '.51'
    with pytest.raises(CapitalRefused, match='f2_personal_trade_changed'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    read['trades'].pop()
    with pytest.raises(CapitalRefused, match='f2_personal_trade_changed'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')


@pytest.mark.parametrize('reason', ['f2_personal_trade_unproven', 'f2_personal_trade_fee_unproven',
                                  'f2_personal_trade_changed', 'f2_anchor_snapshot_pending'])
def test_personal_flow_deferral_stays_named_and_cannot_claim(tmp_path, reason, account_guard):
    import json
    from tests.market.test_lfc_campaign import Clock, state_at, StubRuntime, bind_launch, policy_row
    from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
    from weather.market.lfc_campaign_policy import parse_policy
    clock = Clock()
    state = state_at(tmp_path, clock)
    runtime = StubRuntime(state, clock)
    def unproven(*args):
        raise TransientPrecheck(reason)
    runtime.pre_go = unproven
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    policy = bind_launch(coordinator, parse_policy(policy_row()))
    coordinator.tick(lambda: policy)
    rows = [json.loads(path.read_text()) for path in (tmp_path / 'control').glob('*.json')]
    assert {row['reason'] for row in rows} == {reason}
    assert any(row['phase'] == 'MISSED' for row in rows)
    assert not state.claims() and not state.incidents() and runtime.go_count == 0
