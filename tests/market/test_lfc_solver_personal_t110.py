"""Guards: T110 same-second solving uses the capture's current personal net."""
from datetime import timedelta

import pytest

from tests.market.test_lfc_f2_overlap_b082 import wallet, feed
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_personal_cash_b081 import owner_trade
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_f2_breadth import PROTOCOL
from weather.market.lfc_f2_cash_snapshot import personal_net
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


@pytest.mark.parametrize('side,captured,reference_cash,current_cash', [
    ('BUY', True, '290', '290'), ('SELL', False, '310', '330')])
@pytest.mark.parametrize('reopen', [False, True])
def test_late_personal_fill_and_same_second_redemption_use_one_cash_definition(
        tmp_path, side, captured, reference_cash, current_cash, reopen):
    ledger, _, clock, source, proof, tokens, _ = wallet(tmp_path)
    second = clock.now()
    trade = owner_trade(clock, side, seconds=2)
    trade.update(price='.5', size='40')
    owner = {'90': '40'} if side == 'BUY' else {}
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={**{token: '20' for token in tokens}, **owner},
                    cash=reference_cash), anchor_mode='session')
    source['timestamp'] = int(second.timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    ledger.record('session_start', session_id='active', protocol=PROTOCOL,
                  autostart_attempt_id='a' * 32)
    clock.value += timedelta(seconds=2)
    read = feed(ledger, clock, source, proof, owner, current_cash)
    read['trades'].append(trade)
    read['terminal_orders'] = {}
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read,
                         live_proof={'attempt_id': 'a' * 32})
    book = CapitalBook(ledger)
    assert result['cash_bridge_complete'] and result['inventory']['changed'] == []
    assert book.expected_cash() == int(current_cash) * 1_000_000
    assert next(iter(book.cash_capture_bindings.values()))['captured'] is captured
    assert all(not binding.get('surplus_only') for binding in book.cash_capture_bindings.values())
    assert personal_net(book, [trade], read['started_at_utc']) == 0
    assert not book.personal_trades  # Read-only solving does not pre-bind a trade.
    assert book.figures()['headroom_native'] <= 300_000_000
    raw = ledger.path.read_bytes()
    assert synchronize(ledger, book.inventory_anchor, read, live_proof={'attempt_id': 'a' * 32}) == result
    assert ledger.path.read_bytes() == raw
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
    ledger.record('session_end', session_id='active')
    clock.value += timedelta(seconds=1)
    fresh = feed(ledger, clock, source, proof, owner, current_cash)
    fresh['trades'].append(trade)
    assert synchronize(ledger, book.inventory_anchor, fresh, anchor_mode='session')['cash_bridge_complete']
    bound = CapitalBook(ledger)
    assert len(bound.personal_trades) == 1 and len(bound.activities) == 1
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == bound.figures()


@pytest.mark.parametrize('side,expected', [('BUY', -1_025_000), ('SELL', 975_000)])
def test_fresh_personal_fee_flow_stays_in_the_solver_fixed_term(tmp_path, side, expected):
    ledger, _, clock, _, _, tokens, _ = wallet(tmp_path)
    late = owner_trade(clock, 'BUY', seconds=2)
    late.update(id='late', taker_order_id='late-order', price='.5', size='40')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={token: '20' for token in tokens}, cash='270'),
        anchor_mode='session')
    clock.value += timedelta(seconds=2)
    fresh = owner_trade(clock, side, seconds=1)
    fresh.update(id='fresh', taker_order_id='fresh-order', price='.5', size='2', fee_rate_bps='500')
    book = CapitalBook(ledger)
    before = book.figures()
    raw = ledger.path.read_bytes()
    assert personal_net(book, [late, fresh], clock.now().isoformat()) == expected
    assert personal_net(book, [fresh], clock.now().isoformat()) == expected
    assert not book.personal_trades and book.figures() == before
    assert ledger.path.read_bytes() == raw
