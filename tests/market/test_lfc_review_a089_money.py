"""Guards: progressive SDK visibility cannot spend or quarantine cash twice."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_personal_cash_b081 import gained_wallet, owner_trade
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger


FIELDS = ('retained_gains_available_native', 'segregated_external_cash_native',
          'headroom_native', 'paid_or_reserved_campaign_costs_native')


def append_snapshot(ledger, clock, cash, rows):
    read = observation(ledger, clock, positions={'denver': '20'}, cash=cash)
    read['trades'].extend(deepcopy(rows))
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read,
                         anchor_mode='session', loss_basis='net_of_retained_gains')
    assert result['cash_bridge_complete']
    return result


@pytest.mark.parametrize('first', ['BUY', 'SELL'])
@pytest.mark.parametrize('reopen', [False, True])
def test_opposing_partial_visibility_has_one_gross_charge(tmp_path, first, reopen):
    results = []
    for mode in ('together', 'staggered'):
        directory = tmp_path / mode
        directory.mkdir()
        ledger, clock, _ = gained_wallet(directory)
        rows = [owner_trade(clock, side, seconds=2) for side in (first, 'SELL' if first == 'BUY' else 'BUY')]
        for row in rows:
            row.update(price='.5', size='2')
        append_snapshot(ledger, clock, '290.8', rows if mode == 'together' else [])
        if mode == 'staggered':
            for count in (1, 2):
                clock.value += timedelta(seconds=10)
                if reopen:
                    ledger = Ledger.open(ledger.path, clock=clock.now)
                append_snapshot(ledger, clock, '290.8', rows[:count])
        book = CapitalBook(ledger)
        before = ledger.path.read_bytes()
        final = book.figures(loss_basis='net_of_retained_gains')
        cold = CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains')
        assert final == cold and ledger.path.read_bytes() == before
        results.append({key: final[key] for key in FIELDS})
    (tmp_path / 'observation.json').write_text(json.dumps({'together': results[0], 'staggered': results[1]}))
    assert results[1] == results[0], results


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_four_late_partials_share_one_capture_across_reopens(tmp_path, side):
    ledger, clock, _ = gained_wallet(tmp_path)
    original = owner_trade(clock, side, seconds=2)
    original.update(price='.5', size='2')
    cash = '289.8' if side == 'BUY' else '291.8'
    append_snapshot(ledger, clock, cash, [])
    expected = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
    parts = []
    for index in range(4):
        part = {**deepcopy(original), 'id': original['id'] + '-part-' + str(index), 'size': '.5'}
        parts.append(part)
        clock.value += timedelta(seconds=10)
        ledger = Ledger.open(ledger.path, clock=clock.now)
        append_snapshot(ledger, clock, cash, parts)
        actual = CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')
        assert {key: actual[key] for key in FIELDS} == {key: expected[key] for key in FIELDS}
    assert len(CapitalBook(ledger).personal_trades) == 4
