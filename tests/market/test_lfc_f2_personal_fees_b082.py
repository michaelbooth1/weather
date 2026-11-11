"""Guards: B082 documented personal fees, conservative residuals and durable binding."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import pytest

from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_personal_cash_b081 import gained_wallet, owner_trade
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger


@pytest.mark.parametrize('role', ['TAKER', 'MAKER'])
def test_next_pre_go_accepts_personal_fee_market_fill(tmp_path, monkeypatch, role):
    from tests.market import test_lfc_f2_wallet_runtime_b080 as normal
    original = normal.observation
    seen = []
    def with_personal_fee(ledger, clock, **values):
        row = original(ledger, clock, **values)
        if 'evening-nfl' in values['positions']:
            trade = owner_trade(clock, 'BUY', role=role)
            trade['fee_rate_bps'] = '100'
            if role == 'MAKER':
                trade['maker_orders'][0]['fee_rate_bps'] = None
            row['trades'].append(trade)
            seen.append((ledger, clock))
        return row
    monkeypatch.setattr(normal, 'observation', with_personal_fee)
    # Exercise the actual coordinator, Runtime.pre_go and fresh anchor before
    # the inert session stub. Its original STARTED/no-incident assertions hold.
    normal.test_first_tick_reanchors_personal_wallet_before_session_stub(tmp_path, monkeypatch, False)
    ledger, clock = seen[-1]
    book = CapitalBook(ledger)
    assert book.figures()['funding_native'] == 300_000_000
    assert next(iter(book.personal_trades.values()))['fee_native'] == (49_920 if role == 'TAKER' else 0)
    reopened = Ledger.open(ledger.path, clock=clock.now)
    assert CapitalBook(reopened).figures() == book.figures()
    assert CapitalBook(reopened).personal_trades == book.personal_trades


@pytest.mark.parametrize('side,cash,remaining_gain,credit', [
    ('BUY', '280.35', 0, False), ('BUY', '280.36', 0, True),
    ('SELL', '301.15', 10_350_000, False), ('SELL', '301.16', 10_350_080, True)])
def test_fee_residuals_consume_gains_or_become_owner_cash(tmp_path, side, cash, remaining_gain, credit):
    ledger, clock, _ = gained_wallet(tmp_path)
    before = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    read = observation(ledger, clock, positions={'denver': '20', 'owner-new-nfl': '20'}, cash=cash)
    trade = owner_trade(clock, side)
    trade['fee_rate_bps'] = '100'  # Computed 0.04992; actual fee 0.05 or 0.04.
    read['trades'].append(trade)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session',
                         loss_basis='net_of_retained_gains')
    book = CapitalBook(ledger)
    figures = book.figures(loss_basis='net_of_retained_gains')
    assert result['cash_bridge_complete']
    assert figures['retained_gains_available_native'] == remaining_gain
    assert figures['headroom_native'] <= before['headroom_native']
    assert figures['funding_native'] == before['funding_native'] == 300_000_000
    if credit:
        assert book.wallet_quarantines[-1]['amount'] == 9_920
    else:
        assert any(move['kind'] == 'withdraw' and move['amount'] == 80 for move in book.pool_movements)
    assert next(iter(book.personal_trades.values()))['fee_native'] == 49_920
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains') == figures
    synchronize(ledger, book.inventory_anchor, read, anchor_mode='session', loss_basis='net_of_retained_gains')
    assert CapitalBook(ledger).figures(loss_basis='net_of_retained_gains') == figures


@pytest.mark.parametrize('field,value,missing,code', [
    ('fee_rate_bps', None, False, 'f2_personal_trade_fee_unproven'),
    ('fee_rate_bps', '', False, 'f2_personal_trade_fee_unproven'),
    ('fee_rate_bps', 'NaN', False, 'f2_personal_trade_fee_unproven'),
    ('fee_rate_bps', '-1', False, 'f2_personal_trade_fee_unproven'),
    ('fee_rate_bps', True, False, 'f2_personal_trade_fee_unproven'),
    ('fee_rate_bps', None, True, 'f2_personal_trade_fee_unproven'),
    ('size', 'bad', False, 'f2_personal_trade_unproven'),
    ('size', None, True, 'f2_personal_trade_unproven'),
    ('price', 'NaN', False, 'f2_personal_trade_unproven'),
    ('price', None, True, 'f2_personal_trade_unproven')])
def test_unreadable_personal_fields_defer_before_anchor(tmp_path, field, value, missing, code):
    ledger, clock, read = gained_wallet(tmp_path)
    trade = owner_trade(clock, 'BUY')
    if missing:
        trade.pop(field)
    else:
        trade[field] = value
    read['trades'].append(trade)
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match=code):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert ledger.path.read_bytes() == before


def test_missing_maker_fee_is_unreadable_while_explicit_null_is_zero(tmp_path):
    ledger, clock, read = gained_wallet(tmp_path)
    trade = owner_trade(clock, 'BUY', role='MAKER')
    trade['maker_orders'][0].pop('fee_rate_bps')
    read['trades'].append(trade)
    with pytest.raises(CapitalRefused, match='f2_personal_trade_fee_unproven'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')


@pytest.mark.parametrize('rate,fee_native', [('0.2', 10), ('0.1', 0)])
def test_fee_rounds_half_up_per_fill_to_five_decimals(tmp_path, rate, fee_native):
    ledger, clock, read = gained_wallet(tmp_path)
    trade = owner_trade(clock, 'BUY')
    trade.update(fee_rate_bps=rate, size='1', price='.5')
    read['trades'].append(trade)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    book = CapitalBook(ledger)
    assert next(iter(book.personal_trades.values()))['fee_native'] == fee_native


@pytest.mark.parametrize('rate,fee_native', [('500', 553_500), ('1000', 1_107_000)])
def test_documented_75_share_fill_numbers(tmp_path, rate, fee_native):
    ledger, clock, _ = gained_wallet(tmp_path)
    cash = Decimal('290.8') - Decimal('13.5') - Decimal(fee_native) / 1_000_000
    read = observation(ledger, clock, positions={'denver': '20', 'owner-new-nfl': '75'}, cash=str(cash))
    trade = owner_trade(clock, 'BUY')
    trade.update(size='75', price='.18', fee_rate_bps=rate)
    read['trades'].append(trade)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert result['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert next(iter(book.personal_trades.values()))['fee_native'] == fee_native
    assert book.expected_cash() == int(cash * 1_000_000)
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).personal_trades == book.personal_trades


@pytest.mark.parametrize('bad,missing', [(None, False), ('invalid', False), ('NaN', False), (None, True)])
def test_bound_fill_never_rechecks_later_fee_fields(tmp_path, bad, missing):
    ledger, clock, read = gained_wallet(tmp_path)
    trade = owner_trade(clock, 'BUY')
    trade['fee_rate_bps'] = '100'
    read['trades'].append(trade)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    book = CapitalBook(ledger)
    figures, recorded = book.figures(loss_basis='net_of_retained_gains'), deepcopy(book.personal_trades)
    clock.value += timedelta(seconds=1)
    after = observation(ledger, clock, positions={'denver': '20', 'owner-new-nfl': '20'}, cash='290.8')
    after['trades'] = deepcopy(read['trades'])
    if missing:
        after['trades'][-1].pop('fee_rate_bps')
    else:
        after['trades'][-1]['fee_rate_bps'] = bad
    synchronize(ledger, book.inventory_anchor, after, anchor_mode='session')
    replay = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
    assert replay.personal_trades == recorded
    assert replay.figures(loss_basis='net_of_retained_gains') == figures
