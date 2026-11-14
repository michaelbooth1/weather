"""Guards: A080 inventory, crash recovery, 302-cash owner setup and funding."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import json
from urllib.parse import urlparse, parse_qs
import pytest

from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_f2_capital import MAKER, filled
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_f2_pinb import example_policy
from weather.market.lfc_ledger import Ledger, LedgerUnavailable, fetch_account_positions
from weather.market.lfc_recording_io import write_new


@pytest.mark.parametrize('extra', ['0.000001', '0.0001', '5'])
def test_late_own_fill_and_foreign_same_token_surplus_are_not_absorbed(tmp_path, extra):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(days=1)
    read = observation(ledger, clock, positions={'denver': str(Decimal(20)+Decimal(extra))}, cash='290')
    before = ledger.path.read_bytes()
    if Decimal(extra) >= Decimal('.0001'):
        with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
            synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
        assert ledger.path.read_bytes() == before
    else:
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
        assert ledger.L() == Decimal('10')  # Exact cost survives endpoint precision.
        before = ledger.path.read_bytes()
    # Even a stale positions endpoint cannot hide a newly visible campaign trade.
    read['positions'][0]['size'] = '20'
    read['trades'][0]['maker_orders'][0]['matched_amount'] = str(Decimal(20)+Decimal(extra))
    path = tmp_path/'campaign.json'; write_new(path, example_policy())
    runtime = object.__new__(Runtime)
    runtime.clock, runtime.policy_path, runtime.preparing_f2 = clock, path, True
    runtime.state = SimpleNamespace(ledger=ledger, maker=MAKER, root=tmp_path/'state')
    result = runtime.core_proof(ledger, read)
    assert result['money_contradiction'] and not result['money_accounting_complete']
    assert ledger.path.read_bytes() == before


def test_unknown_submit_cannot_cross_an_anchor_before_late_fill(tmp_path):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    ledger.record('session_start', session_id='unknown')
    ledger.intent(session_id='unknown', intent_key='unknown', token_id='late', condition_id='late-condition',
        size='20', price='.4', fee_rate_bps='0')
    ledger.record('session_end', session_id='unknown')
    read = observation(ledger, clock, positions={'denver': '20'}, cash='290')
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='f2_anchor_unknown_submit'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('observed,accepted', [('7', True), ('6.999999', True), ('7.000001', True),
                                            ('6.9999', False), ('7.0001', False)])
def test_cancelled_partial_fill_keeps_exact_basis_with_venue_precision(tmp_path, observed, accepted):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(hours=1)
    ledger.record('session_start', session_id='partial')
    ledger.intent(session_id='partial', intent_key='partial', token_id='partial-token', condition_id='partial-condition',
        size='20', price='.4', fee_rate_bps='0')
    ledger.ack('partial', 'partial-order')
    ledger.terminal('partial-order', {'id': 'partial-order', 'status': 'CANCELED', 'size_matched': '7'}, source='fixture')
    ledger.record('session_end', session_id='partial')
    clock.value += timedelta(hours=1)
    read = observation(ledger, clock, positions={'denver': '20', 'partial-token': observed}, cash='287.2')
    if accepted:
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
        book = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
        assert book.inventory_anchor['positions']['partial-token'] == observed
        assert book.lots['partial']['remaining_quantity'] == Decimal('7')
        assert book.lots['partial']['remaining_basis'] == 2_800_000
    else:
        before = ledger.path.read_bytes()
        with pytest.raises(CapitalRefused, match='capital_inventory_unreconciled'):
            synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
        assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('crash', ['before_append', 'after_append', 'torn_append'])
def test_anchor_crash_never_recredits_personal_cash(tmp_path, monkeypatch, crash):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(days=1)
    read = observation(ledger, clock, positions={'denver': '20', 'personal': '99'}, cash='490')
    original, before = ledger.record, ledger.path.read_bytes()
    def interrupt(event, **fields):
        if event != 'f2_session_anchor':
            return original(event, **fields)
        if crash != 'before_append':
            original(event, **fields)
            if crash == 'torn_append':
                data = ledger.path.read_bytes()
                ledger.path.write_bytes(data[:-5])
        raise OSError('synthetic interruption')
    monkeypatch.setattr(ledger, 'record', interrupt)
    with pytest.raises(OSError, match='synthetic interruption'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')
    if crash == 'torn_append':
        with pytest.raises(LedgerUnavailable):
            Ledger.open(ledger.path, clock=clock.now)
        return
    if crash == 'before_append':
        assert ledger.path.read_bytes() == before
    reopened = Ledger.open(ledger.path, clock=clock.now)
    retry = observation(reopened, clock, positions={'denver': '20', 'personal': '99'}, cash='490')
    synchronize(reopened, CapitalBook(reopened).inventory_anchor, retry, anchor_mode='session')
    book = CapitalBook(Ledger.open(reopened.path, clock=clock.now))
    assert book.external == 200_000_000 and book.expected_cash() == 490_000_000
    assert book.figures()['funding_native'] == 300_000_000 and book.figures()['headroom_native'] == 290_000_000
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='290.000001', available_cash='490')


def test_150_open_and_150_redeemable_positions_fit_the_existing_page_budget(tmp_path):
    calls, counts = [], {}
    class Reply:
        status = 200
        def __init__(self, status):
            base = 1 if status == 'OPEN' else 151
            self.raw = json.dumps({'data': [{'proxy_wallet': MAKER, 'token_id': str(i),
                'condition_id': 'condition-'+str(i), 'current_size': '20', 'status': status}
                for i in range(base, base+150)], 'pagination': {'next_cursor': None, 'has_more': False}}).encode()
        def read(self, size): return self.raw[:size]
        def close(self): pass
    def opener(request, **kwargs):
        query = parse_qs(urlparse(request.full_url).query)
        calls.append(query)
        assert query['limit'] == ['1000']
        return Reply(query['status'][0])
    rows = fetch_account_positions(MAKER, opener=opener, status_counts=counts)
    assert len(rows) == 300 and len(calls) == 2 and counts == {'OPEN': 150, 'REDEEMABLE_LOST': 150}


def test_recovery_then_funding_at_302_keeps_exact_300_sleeve(tmp_path, monkeypatch):
    from tests.market.test_lfc_history_setup import test_failed_f0_recovery_explicit_policy_then_enroll_then_seal
    from tests.market.test_lfc_campaign import Mutexes
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_capital import ASSET
    calls = []
    original = Runtime.confirm_funding
    def capture(runtime):
        result = original(runtime)
        calls.append(runtime)
        return result
    monkeypatch.setattr(Runtime, 'confirm_funding', capture)
    # Execute the same complete synthetic CLI history recovery/enrollment/seal
    # path, then a further protected funding check with the requested 302 cash.
    test_failed_f0_recovery_explicit_policy_then_enroll_then_seal(tmp_path, monkeypatch, True)
    runtime = calls[-1]
    def observed():
        read = runtime.account_read_once()
        read['balances'] = {'available_collateral': '302', 'assets': {ASSET: '302'},
            'collateral_evidence': {'balance': '302000000'}}
        return read
    monkeypatch.setattr(runtime, 'read_account', observed)
    with account_lease(MAKER, backend=Mutexes()):
        result = original(runtime)
    assert result['funding_native'] == 300_000_000 and result['capital_bridge_complete'] is True
    book = CapitalBook(runtime.state.ledger)
    assert book.expected_cash() == 302_000_000 and book.external == 22_500_000
    assert book.figures()['funding_native'] == 300_000_000 and book.figures()['retained_gains_available_native'] == 0
