"""Guards: independently timed B082 endpoints, ledger interruption and malformed fees."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import ast
import pytest

from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.test_lfc_f2_overlap_b082 import wallet, feed
from tests.market.test_lfc_f2_cash_mirror_b082 import profitable_wallet, cash_activity, observed, single_redemption
from tests.market.test_lfc_f2_personal_cash_b081 import gained_wallet, owner_trade
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_f2_breadth import PROTOCOL
from weather.market.lfc_f2_inventory import activity_start
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.mm_stage2_hold import digest




@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('partial', [False, True])
def test_late_personal_proof_before_position_index_does_not_freeze_stale_quantity(tmp_path, reopen, partial):
    ledger, baseline, clock, source, proof, tokens, campaign = wallet(tmp_path, campaign=False)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    proof.update(rows=[source], rows_sha256=digest([source]))
    # All 20 shares were redeemed. A positions endpoint may initially report
    # either all 20 stale shares or an intermediate 10; native receipt is final.
    stale_positions = {campaign: '20', **{token: '20' for token in tokens}}
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions=stale_positions, cash='310'), anchor_mode='session')
    attempt = 'a' * 32
    ledger.record('session_start', session_id='active', protocol=PROTOCOL, autostart_attempt_id=attempt)
    clock.value += timedelta(seconds=90)
    lagging = {campaign: '20', **{token: ('10' if partial else '20') for token in tokens}}
    first = feed(ledger, clock, source, proof, lagging, '310')
    first['terminal_orders'] = {}
    try:
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, first, live_proof={'attempt_id': attempt})
    except CapitalRefused as exc:
        # A temporary mismatch while the position endpoint catches up is safe.
        assert str(exc) == 'capital_inventory_unreconciled'
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    outcomes = []
    for wait in (2, 901):
        clock.value += timedelta(seconds=wait)
        read = feed(ledger, clock, source, proof, {campaign: '20'}, '310')
        read['terminal_orders'] = {}
        try:
            result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read,
                                 live_proof={'attempt_id': attempt})
            outcomes.append('clean' if not result['inventory']['changed'] else 'changed')
        except CapitalRefused as exc:
            outcomes.append(str(exc))
    assert outcomes == ['clean', 'clean'], outcomes
    book = CapitalBook(ledger)
    assert book.profit == 0 and book.external == 20_000_000
    assert book.figures()['funding_native'] == 300_000_000


@pytest.mark.parametrize('point', ['before_group', 'after_group', 'before_activity', 'after_activity',
                                  'before_anchor', 'after_anchor', 'torn_activity', 'torn_anchor'])
def test_late_cash_crash_replay_does_not_double_debit(tmp_path, monkeypatch, point):
    ledger, clock = profitable_wallet(tmp_path)
    source, proof = cash_activity(clock, 'WITHDRAWAL', '50')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'103': '20'}, cash='323'), anchor_mode='session')
    old_start = activity_start(ledger, clock.now().isoformat())
    clock.value += timedelta(seconds=90)
    read = observed(ledger, clock, source, proof, '323')
    target = ('capital_native_group' if point.endswith('group') else
              'capital_activity' if point.endswith('activity') else 'f2_session_anchor')
    original = ledger.record
    def interrupted(event, **values):
        if event != target:
            return original(event, **values)
        if not point.startswith('before'):
            original(event, **values)
            if point.startswith('torn'):
                ledger.path.write_bytes(ledger.path.read_bytes()[:-5])
        raise OSError('synthetic crash at ' + point)
    monkeypatch.setattr(ledger, 'record', interrupted)
    with pytest.raises(OSError, match='synthetic crash'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    if point.startswith('torn'):
        with pytest.raises(LedgerUnavailable):
            Ledger.open(ledger.path, clock=clock.now)
        return
    ledger = Ledger.open(ledger.path, clock=clock.now)
    if point != 'after_anchor':
        assert activity_start(ledger, clock.now().isoformat()) == old_start
    else:
        covered = int(clock.now().timestamp())
        assert CapitalBook(ledger).inventory_anchor['activity_covered_through'] == covered
        from weather.market.mm_stage2_hold import utc
        genesis = int(utc(ledger.rows[0]['recorded_at_utc']).timestamp())
        assert activity_start(ledger, clock.now().isoformat()) == max(genesis, covered - 1800)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert result['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.expected_cash() == 323_000_000
    assert book.figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == 33_000_000
    assert book.figures()['funding_native'] == 300_000_000
    assert len([row for row in ledger.rows if row['event'] == 'capital_activity' and
                row.get('source', {}).get('transaction_hash') == source['transaction_hash']]) == 1
    before = book.figures()
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == before


@pytest.mark.parametrize('bad', ['missing', 'null'])
def test_unbound_malformed_fee_stays_named_refusal_until_corrected(tmp_path, bad):
    ledger, clock, _ = gained_wallet(tmp_path)
    trade = owner_trade(clock, 'BUY')
    if bad == 'missing':
        trade.pop('fee_rate_bps')
    else:
        trade['fee_rate_bps'] = None
    before = ledger.path.read_bytes()
    for days in (0, 1, 2):
        clock.value += timedelta(days=days)
        read = observation(ledger, clock, positions={'denver': '20', 'owner-old-nfl': '20',
                                                   'owner-new-nfl': '20'}, cash='280.1504')
        read['trades'].append(trade)
        with pytest.raises(CapitalRefused, match='f2_personal_trade_fee_unproven'):
            synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
        assert ledger.path.read_bytes() == before
        ledger = Ledger.open(ledger.path, clock=clock.now)
    trade['fee_rate_bps'] = '500'
    read['trades'][-1] = trade
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    assert len(CapitalBook(ledger).personal_trades) == 1


@pytest.mark.parametrize('lag,found', [(1799, True), (1800, True), (1801, False)])
def test_overlap_boundary_is_inclusive_but_finite(tmp_path, lag, found):
    ledger, baseline, clock, source, proof, tokens, campaign = wallet(tmp_path)
    source['timestamp'] = int(clock.now().timestamp()) - lag
    proof.update(rows=[source], rows_sha256=digest([source]))
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={token: '20' for token in tokens}, cash='310'),
        anchor_mode='session')
    clock.value += timedelta(seconds=90)
    read = feed(ledger, clock, source, proof, {}, '310')
    assert bool(read['capital_activity']['rows']) is found
    if found:
        assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)['cash_bridge_complete']
    else:
        with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
            synchronize(ledger, CapitalBook(ledger).inventory_anchor, read)


@pytest.mark.parametrize('point', ['before_activity', 'after_activity', 'before_anchor', 'after_anchor'])
def test_late_campaign_redemption_crash_is_exactly_once(tmp_path, monkeypatch, point):
    ledger, baseline, clock, source, proof, tokens, campaign = wallet(tmp_path)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    proof.update(rows=[source], rows_sha256=digest([source]))
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={token: '20' for token in tokens}, cash='310'),
        anchor_mode='session')
    clock.value += timedelta(seconds=90)
    read = feed(ledger, clock, source, proof, {}, '310')
    event_name = 'capital_activity' if point.endswith('activity') else 'f2_session_anchor'
    original = ledger.record
    def interrupted(event, **fields):
        if event != event_name:
            return original(event, **fields)
        if point.startswith('after'):
            original(event, **fields)
        raise OSError('synthetic redemption crash')
    monkeypatch.setattr(ledger, 'record', interrupted)
    with pytest.raises(OSError, match='synthetic redemption crash'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    ledger = Ledger.open(ledger.path, clock=clock.now)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    book = CapitalBook(ledger)
    figures = book.figures(loss_basis='net_of_retained_gains')
    assert book.expected_cash() == 310_000_000
    assert figures['funding_native'] == 300_000_000
    assert figures['retained_gains_available_native'] == 10_000_000
    assert book.returned_principal == 10_000_000 and book.external == 0
    assert len(book.allocations) == 1
    before = ledger.path.read_bytes()
    clock.value += timedelta(seconds=90)
    fresh = feed(ledger, clock, source, proof, {}, '310')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, fresh)
    assert ledger.path.read_bytes() == before
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures(loss_basis='net_of_retained_gains') == figures


@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('tight', [False, True])
def test_redemption_after_cash_snapshot_in_same_second_is_not_already_captured(tmp_path, reopen, tight):
    ledger, baseline, clock, source, proof, tokens, campaign = wallet(tmp_path)
    retained_positions = {}
    if tight:
        from tests.market.test_lfc_f2_capital import filled
        # 28 additional 10-pUSD filled singles, at most 30 filled pUSD per
        # condition, leave I=290 before redemption and I=280 afterwards.
        # Then a real-sized 19.60 band (I+R=299.60) must remain admissible.
        for index in range(28):
            token = 'carry-' + str(index % 10)
            CapitalBook(ledger).gate(reserve='10', available_cash=str(290-index*10))
            filled(ledger, 'carry-fill-'+str(index), token=token, condition=token)
            retained_positions[token] = str(int(retained_positions.get(token, '0')) + 20)
    second = clock.now()
    clock.value = second + timedelta(microseconds=250_000)
    # Native cash is observed BEFORE the redemption, within the same UTC second.
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={**retained_positions, **{token: '20' for token in tokens}},
                    cash='10' if tight else '290'),
        anchor_mode='session')
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    # The API provides only a whole-second timestamp for an event at T+.750s.
    source['timestamp'] = int(second.timestamp())
    proof.update(rows=[source], rows_sha256=digest([source]))
    clock.value = second + timedelta(seconds=2)
    cash = '30' if tight else '310'
    after = feed(ledger, clock, source, proof, retained_positions, cash)
    result = synchronize(ledger, CapitalBook(ledger).inventory_anchor, after)
    book = CapitalBook(ledger)
    refusal = None
    try:
        book.gate(reserve='19.6' if tight else '300', available_cash=cash, loss_basis='net_of_retained_gains')
    except CapitalRefused as exc:
        refusal = str(exc)
    assert (book.expected_cash(), refusal, result['cash_bridge_complete']) == (int(cash)*1_000_000, None, True), {
        'expected_cash': book.expected_cash(), 'reserve_refusal': refusal,
        'figures': book.figures(loss_basis='net_of_retained_gains')}
    assert book.figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == 10_000_000
    assert book.figures()['funding_native'] == 300_000_000 and book.external == 0


@pytest.mark.parametrize('target', ['capital_activity', 'f2_session_anchor'])
def test_fsync_failure_after_full_write_reopens_exactly_once(tmp_path, monkeypatch, target):
    from weather.market import lfc_ledger
    ledger, clock = profitable_wallet(tmp_path)
    source, proof = cash_activity(clock, 'WITHDRAWAL', '50')
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, clock, positions={'103': '20'}, cash='323'), anchor_mode='session')
    clock.value += timedelta(seconds=90)
    read = observed(ledger, clock, source, proof, '323')
    record, fsync = ledger.record, lfc_ledger.os.fsync
    fault = {'armed': False, 'fired': False}
    def failing_fsync(fd):
        if fault['armed'] and not fault['fired']:
            fault['fired'] = True
            raise OSError('synthetic fsync failure after flush')
        return fsync(fd)
    def wrapped(event, **fields):
        fault['armed'] = event == target
        try:
            return record(event, **fields)
        finally:
            fault['armed'] = False
    monkeypatch.setattr(lfc_ledger.os, 'fsync', failing_fsync)
    monkeypatch.setattr(ledger, 'record', wrapped)
    with pytest.raises(LedgerUnavailable, match='ledger_write_failed'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert fault['fired']
    ledger = Ledger.open(ledger.path, clock=clock.now)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.expected_cash() == 323_000_000
    assert book.figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == 33_000_000
    assert len([row for row in ledger.rows if row['event'] == 'capital_activity' and
                row.get('source', {}).get('transaction_hash') == source['transaction_hash']]) == 1


@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('fee', [False, True])
def test_t2_personal_buy_and_late_redemption_keep_only_unspent_gains(tmp_path, reopen, fee):
    ledger, clock = profitable_wallet(tmp_path)
    buy = owner_trade(clock, 'BUY', seconds=40)
    buy.update(token_id='104', size='20', price='.5', fee_rate_bps='500' if fee else '0')
    source, proof = single_redemption('104', '20', '20', '0x'+'e'*64, '0x'+'3'*64)
    source['timestamp'] = int(clock.now().timestamp()) - 20
    proof.update(rows=[source], rows_sha256=digest([source]))
    # 373 cash, personal buy 10 plus fee, then personal redemption +20.
    cash = '382.75' if fee else '383'
    gain = 72_750_000 if fee else 73_000_000
    stale = observation(ledger, clock, positions={'103': '20', '104': '20'}, cash=cash)
    stale['trades'].append(buy)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, stale, anchor_mode='session')
    assert CapitalBook(ledger).figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == gain
    if reopen:
        ledger = Ledger.open(ledger.path, clock=clock.now)
    clock.value += timedelta(seconds=90)
    after = observed(ledger, clock, source, proof, cash)
    after['trades'].append(buy)
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, after)['cash_bridge_complete']
    book = CapitalBook(ledger)
    assert book.figures(loss_basis='net_of_retained_gains')['retained_gains_available_native'] == gain
    assert book.external == 20_000_000
    assert book.figures()['funding_native'] == 300_000_000
    before = ledger.path.read_bytes()
    synchronize(ledger, book.inventory_anchor, after)
    assert ledger.path.read_bytes() == before
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == book.figures()
