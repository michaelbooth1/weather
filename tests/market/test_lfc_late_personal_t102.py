"""Guards: T102 reclassifies a captured personal SDK execution exactly once.

The four A081 witness cases and their assertions are retained verbatim.
"""
from datetime import timedelta
import pytest
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_personal_cash_b081 import gained_wallet, owner_trade
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
@pytest.mark.parametrize('reopen', [False, True])
def test_late_sdk_trade_reclassifies_prior_cash_snapshot_once(tmp_path, side, reopen):
    ledger, clock, read = gained_wallet(tmp_path)
    source = owner_trade(clock, side)
    positions = {'denver': '20'}
    if side == 'BUY':
        positions.update({'owner-old-nfl': '20', 'owner-new-nfl': '20'})
    cash = '280.4' if side == 'BUY' else '301.2'
    first = observation(ledger, clock, positions=positions, cash=cash)
    # The trade endpoint is one read behind the positions/balance endpoints.
    # Its entire notional is already included in the first accepted cash anchor.
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, first, anchor_mode='session', loss_basis='net_of_retained_gains')
    before = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    reserve = '280.4' if side == 'BUY' else '290'
    CapitalBook(ledger).gate(reserve=reserve, available_cash=cash, loss_basis='net_of_retained_gains')
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    clock.value += timedelta(seconds=10)
    second = observation(ledger, clock, positions=positions, cash=cash)
    second['trades'].append(source)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, second, anchor_mode='session', loss_basis='net_of_retained_gains')
    assert result['cash_bridge_complete']
    after = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    refusal = None
    try:
        CapitalBook(ledger).gate(reserve=reserve, available_cash=cash, loss_basis='net_of_retained_gains')
    except CapitalRefused as exc:
        refusal = str(exc)
    assert refusal is None, {'refusal': refusal, 'before_G': before['retained_gains_available_native'],
        'after_G': after['retained_gains_available_native'], 'before_external': before['segregated_external_cash_native'],
        'after_external': after['segregated_external_cash_native'], 'cash': cash}
    assert after['retained_gains_available_native'] == before['retained_gains_available_native'], (before, after)
    assert after['segregated_external_cash_native'] == before['segregated_external_cash_native'], (before, after)
    assert after['headroom_native'] == before['headroom_native']


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_two_late_partial_fills_share_only_the_original_finite_capture(tmp_path, side):
    from copy import deepcopy
    ledger, clock, _ = gained_wallet(tmp_path)
    original = owner_trade(clock, side)
    cash = '280.4' if side == 'BUY' else '301.2'
    positions = {'denver': '20'}
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions=positions, cash=cash), anchor_mode='session')
    before = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    fragments = []
    for index in range(2):
        row = deepcopy(original)
        row['id'] += '-part-' + str(index)
        row['size'] = '10'
        fragments.append(row)
    clock.value += timedelta(seconds=10)
    read = observation(ledger, clock, positions=positions, cash=cash)
    read['trades'] += fragments
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert len(book.personal_trades) == 2
    for field in ('headroom_native', 'retained_gains_available_native', 'segregated_external_cash_native'):
        assert book.figures(loss_basis='net_of_retained_gains')[field] == before[field]
    raw = ledger.path.read_bytes()
    assert synchronize(ledger, book.inventory_anchor, read)['cash_bridge_complete']
    assert ledger.path.read_bytes() == raw
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


def test_later_purchase_cannot_reuse_an_earlier_anonymous_debit(tmp_path):
    ledger, clock, _ = gained_wallet(tmp_path)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20'}, cash='285.8'), anchor_mode='session')
    before = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    clock.value += timedelta(seconds=10)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='285.8')
    read['trades'].append(owner_trade(clock, 'BUY'))
    # An equal new owner deposit masks this later buy's net balance change.
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    after = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    assert after['retained_gains_available_native'] == 0 < before['retained_gains_available_native']
    assert after['headroom_native'] <= before['headroom_native']


def test_same_second_round_trip_cannot_reuse_two_earlier_anonymous_adjustments(tmp_path):
    ledger, clock, _ = gained_wallet(tmp_path)
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20'}, cash='289.8'), anchor_mode='session')
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20'}, cash='290.8'), anchor_mode='session')
    before = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    clock.value += timedelta(microseconds=250000)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='290.8')
    for side in ('BUY', 'SELL'):
        row = owner_trade(clock, side, seconds=0)
        row.update(size='2', price='.5')
        read['trades'].append(row)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    after = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    assert after['retained_gains_available_native'] == before['retained_gains_available_native'] - 1_000_000
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains') == after


def test_pre_snapshot_round_trip_cannot_explain_separate_later_cash_adjustments(tmp_path):
    ledger, clock, _ = gained_wallet(tmp_path)
    trades = []
    for side in ('BUY', 'SELL'):
        row = owner_trade(clock, side, seconds=2)
        row.update(size='2', price='.5')
        trades.append(row)
    # Both SDK executions already precede the FIRST balance. Their net is zero.
    # The two later adjustments therefore cannot be their buy and sale cash.
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20'}, cash='289.8'), anchor_mode='session')
    clock.value += timedelta(seconds=10)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20'}, cash='290.8'), anchor_mode='session')
    before = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    clock.value += timedelta(seconds=10)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='290.8')
    read['trades'] += trades
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    after = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    assert after['retained_gains_available_native'] == before['retained_gains_available_native'] - 1_000_000
    assert after['headroom_native'] == before['headroom_native'] - 1_000_000
    pools = ('segregated_external_cash_native', 'segregated_profit_native', 'segregated_incentives_native')
    assert sum(after[field] for field in pools) == sum(before[field] for field in pools)
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains') == after


def test_late_buy_then_sale_reclassify_their_own_distinct_balance_windows(tmp_path):
    ledger, clock, _ = gained_wallet(tmp_path)
    buy = owner_trade(clock, 'BUY')
    buy.update(size='2', price='.5')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20', '90': '2'}, cash='289.8'), anchor_mode='session')
    clock.value += timedelta(seconds=10)
    sale = owner_trade(clock, 'SELL')
    sale.update(size='2', price='.5')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'denver': '20'}, cash='290.8'), anchor_mode='session')
    before = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    clock.value += timedelta(seconds=10)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='290.8')
    read['trades'] += [buy, sale]
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    after = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    for field in ('headroom_native', 'retained_gains_available_native', 'segregated_external_cash_native'):
        assert after[field] == before[field]
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains') == CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
