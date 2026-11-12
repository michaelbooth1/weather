"""Guards: T109 reveal order, finite snapshot residuals, native proof and current fees."""
from copy import deepcopy
from datetime import timedelta
from itertools import permutations

import pytest

from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_personal_cash_b081 import gained_wallet, owner_trade
from tests.market.test_lfc_f2_cash_mirror_b082 import cash_activity
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger


FIELDS = ('retained_gains_available_native', 'segregated_external_cash_native',
          'headroom_native', 'paid_or_reserved_campaign_costs_native')


def snapshot(ledger, clock, cash, trades):
    read = observation(ledger, clock, positions={'denver': '20'}, cash=cash)
    read['trades'].extend(deepcopy(trades))
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read,
                         anchor_mode='session', loss_basis='net_of_retained_gains')
    assert result['cash_bridge_complete'] and result['funding_native'] == 300_000_000


@pytest.mark.parametrize('order', list(permutations(range(3))))
@pytest.mark.parametrize('reopen', [False, True])
def test_three_fee_bearing_partial_reveals_equal_the_fully_visible_read(tmp_path, order, reopen):
    figures = []
    for gradual in (False, True):
        root = tmp_path / str(gradual)
        root.mkdir()
        ledger, clock, _ = gained_wallet(root)
        trades = []
        for index, (side, size) in enumerate((('BUY', '2'), ('SELL', '1'), ('BUY', '.5'))):
            trade = owner_trade(clock, side, seconds=2)
            trade.update(id=trade['id'] + str(index), price='.5', size=size, fee_rate_bps='500')
            trades.append(trade)
        # Gross outflow 1.29375, sale credit .5; net cash change -.79375.
        cash = '290.00625'
        snapshot(ledger, clock, cash, [] if gradual else trades)
        if gradual:
            visible = []
            for index in order:
                clock.value += timedelta(seconds=7)
                if reopen:
                    ledger = Ledger.open(ledger.path, clock=clock.now)
                visible.append(trades[index])
                snapshot(ledger, clock, cash, visible)
        book = CapitalBook(ledger)
        raw = ledger.path.read_bytes()
        actual = book.figures(loss_basis='net_of_retained_gains')
        assert actual == CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains')
        assert ledger.path.read_bytes() == raw and len(book.personal_trades) == 3
        assert actual['retained_gains_available_native'] == 9_106_250
        assert actual['segregated_external_cash_native'] == 500_000
        figures.append({key: actual[key] for key in FIELDS})
    assert figures[0] == figures[1]


@pytest.mark.parametrize('first', ['BUY', 'SELL'])
@pytest.mark.parametrize('reopen', [False, True])
def test_new_sdk_proof_cannot_reuse_native_explained_withdrawal(tmp_path, first, reopen):
    results = []
    for gradual in (False, True):
        root = tmp_path / str(gradual)
        root.mkdir()
        ledger, clock, _ = gained_wallet(root)
        trades = [owner_trade(clock, side, seconds=2) for side in (first, 'SELL' if first == 'BUY' else 'BUY')]
        for row in trades:
            row.update(size='2', price='.5')
        snapshot(ledger, clock, '289.8', [] if gradual else trades)
        source, proof = cash_activity(clock, 'WITHDRAWAL', '1', timestamp=int(clock.now().timestamp()) - 3)
        record_activity(ledger, source, native_evidence=proof)
        if gradual:
            for count in (1, 2):
                clock.value += timedelta(seconds=10)
                if reopen:
                    ledger = Ledger.open(ledger.path, clock=clock.now)
                snapshot(ledger, clock, '289.8', trades[:count])
        book = CapitalBook(ledger)
        figures = book.figures(loss_basis='net_of_retained_gains')
        # Preserve native capture timing/pool rules while charging both real
        # gross outflows. The native-explained residual is never reused.
        assert figures['retained_gains_available_native'] == 8_400_000
        assert sum(row.get('explained_native', 0) for row in book.wallet_debit_quarantines) == 1_000_000
        assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains') == figures
        results.append({key: figures[key] for key in FIELDS})
    assert results[0] == results[1]


def test_proven_nonzero_personal_fee_is_accepted_once_and_does_not_age_into_a_refusal(tmp_path):
    """Replace A081's obsolete permanent nonzero-fee refusal characterization."""
    ledger, baseline, clock, _ = fixture(tmp_path, personal=False, bridge=False)
    clock.value += timedelta(hours=2)
    old = owner_trade(clock, 'BUY', seconds=3600)
    old['fee_rate_bps'] = '500'
    first = observation(ledger, clock, positions={'denver': '20', 'personal-nfl': '20'}, cash='302')
    first['trades'].append(old)
    synchronize(ledger, baseline, first, anchor_mode='enrollment')
    clock.value += timedelta(minutes=10)
    next_read = observation(ledger, clock, positions={'denver': '20', 'personal-nfl': '20'}, cash='302')
    next_read['trades'].append(old)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, next_read, anchor_mode='session')['funding_native'] == 300_000_000
    new = owner_trade(clock, 'SELL', seconds=1)
    new['fee_rate_bps'] = '500'
    for days in (1, 2):
        clock.value += timedelta(days=days)
        read = observation(ledger, clock, positions={'denver': '20'}, cash='312.1504')
        bound = deepcopy(new)
        if days == 2:
            bound['fee_rate_bps'] = 'not-reread-after-binding'
        read['trades'].extend([old, bound])
        result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
        assert result['cash_bridge_complete'] and result['funding_native'] == 300_000_000
        book = CapitalBook(ledger)
        assert len(book.personal_trades) == 1
        flow = next(iter(book.personal_trades.values()))
        assert flow['cash_native'] == 10_400_000 and flow['fee_native'] == 249_600
        assert sum(move['amount'] for move in book.pool_movements if move.get('activity_id') == 'personal-' + flow['id'] and move['kind'] == 'withdraw') == 249_600
        assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()


@pytest.mark.parametrize('first', ['BUY', 'SELL'])
def test_later_proven_campaign_gain_is_independent_of_sdk_reveal_timing(tmp_path, first):
    from tests.market.test_lfc_f2_capital import filled
    from tests.market.test_lfc_f2_cash_mirror_b082 import single_redemption
    results = []
    for gradual in (False, True):
        root = tmp_path / str(gradual)
        root.mkdir()
        ledger, clock, _ = gained_wallet(root)
        trades = [owner_trade(clock, side, seconds=2) for side in (first, 'SELL' if first == 'BUY' else 'BUY')]
        for trade in trades:
            trade.update(size='2', price='.5')
        snapshot(ledger, clock, '290.8', [] if gradual else trades)
        condition = next(lot['condition_id'] for lot in CapitalBook(ledger).lots.values() if lot['token_id'] == '101')
        clock.value += timedelta(seconds=10)
        filled(ledger, 'later-winner', token='101', condition=condition)
        source, proof = single_redemption('101', '20', '20', condition, '0x' + '3' * 64)
        source['timestamp'] = int(clock.now().timestamp())
        from weather.market.mm_stage2_hold import digest
        proof.update(rows=[source], rows_sha256=digest([source]))
        record_activity(ledger, source, native_evidence=proof)
        if gradual:
            for count in (1, 2):
                clock.value += timedelta(seconds=10)
                ledger = Ledger.open(ledger.path, clock=clock.now)
                snapshot(ledger, clock, '300.8', trades[:count])
        else:
            clock.value += timedelta(seconds=20)
            snapshot(ledger, clock, '300.8', trades)
        actual = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
        assert actual['retained_gains_available_native'] == 19_400_000
        assert actual == CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains')
        results.append({key: actual[key] for key in FIELDS})
    assert results[0] == results[1]
