"""Guards: T076 real reply structures through Pin B fills, repost and evidence.

Only in-memory SDK boundaries and synthetic account values are installed.
"""
from decimal import Decimal
import json

import pytest

from tests.market.real_reply_shapes import close_claim, offline, pinb_fixture, shape
from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_controller import MAKER
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_recording_io import strict_json


def rows(path):
    return [strict_json(line) for line in path.read_bytes().splitlines()]


@pytest.mark.parametrize('phase', ['fill', 'cleanup'])
@pytest.mark.parametrize('trade_status', ['MINED', 'MATCHED', 'CONFIRMED'])
def test_three_second_sdk_decode_lag_completes_fill_repost_and_retained_closure(
        tmp_path, monkeypatch, phase, trade_status, request):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read, trace, began = pinb_fixture(
            tmp_path, monkeypatch, lag=3, lag_phase=phase, trade_status=trade_status)
        assert controller.policy.raw['schema_version'] == 'lfc_campaign_policy_v0.4'
        result = controller.run()
        first = controller.bands[0]
        assert began and any(item[2] == 'undecodable' for item in trace['mapped_reads'])
        assert first.submits >= 4 and not first._evidence_faults, result
        assert result['cleanup_ok'] and result['unknown_submit'] is False, result
        assert controller.results[first.session_id]['reason'] == 'fixed_end'
        assert any(event['trade_id'] for event in trace['events'])
        outcome, local, proof = close_claim(controller, account, status, ledger, clock, runtime)
        assert outcome['state'] == 'COMPLETE' and local['complete'], local
        # Retried GET failures remain honest journal facts; complete later
        # reads heal them without deleting the original evidence.
        assert all(gap.startswith('read_fill_order') or gap.startswith('read_order_')
                   for gap in local['money_read_gaps']), local
        assert not ledger.unresolved_legs() and not account.open_orders()
        assert CapitalBook(ledger).figures()['charged_native'] <= 300_000_000
        band_rows = rows(first.journal.path)
        fill = next(row for row in band_rows if row['event'] == 'fill' and row.get('user_event'))
        assert set(shape('fill_journal_user_event')) <= set(fill['user_event'])
        assert any(row['event'] == 'repost_ready' for row in band_rows)
        request.node.user_properties.append(('outcome', json.dumps({
            'phase': phase, 'trade_status': trade_status, 'reason': result['reason'],
            'submits': first.submits, 'cleanup_ok': result['cleanup_ok'],
            'faults': sorted(first._evidence_faults), 'money_read_gaps': local['money_read_gaps'],
            'postcheck_money_complete': proof['money_accounting_complete'],
            'pending': runtime.state.pending(), 'incidents': runtime.state.incidents(),
            'capital': CapitalBook(runtime.state.ledger).figures()})))


@pytest.mark.parametrize('miss', [False, True])
def test_no_fill_and_single_heartbeat_miss_preserve_full_evidence_and_capital(tmp_path, monkeypatch, miss):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read, trace, began = pinb_fixture(
            tmp_path, monkeypatch, fills=False, heartbeat_miss=miss)
        result = controller.run()
        assert result['cleanup_ok'] and not result['evidence_faults'], result
        outcome, local, proof = close_claim(controller, account, status, ledger, clock, runtime)
        assert outcome['state'] == 'COMPLETE' and not local['money_read_gaps']
        assert local['explained_gaps'] == (['heartbeat_unavailable'] if miss else [])
        root = rows(controller.journal.path)
        assert any(row['event'] == 'heartbeat_v1_acknowledgment' for row in root)
        assert len(trace['heartbeats']) > 100 and len(trace['balances']) > 0
        figures = CapitalBook(ledger).figures()
        assert figures['resting_reserve_native'] == figures['unrecovered_inventory_cost_native'] == 0
        assert figures['headroom_native'] == 300_000_000


def test_lag_beyond_budget_keeps_reserve_and_heals_through_real_postcheck(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read, trace, began = pinb_fixture(
            tmp_path, monkeypatch, lag=700)
        result = controller.run(); first = controller.bands[0]
        assert first.submits == 2 and not result['cleanup_ok']
        assert controller.results[first.session_id]['reason'] == 'repost_terminal_unreadable'
        assert first._evidence_faults == {'terminal_order_unavailable'}
        assert CapitalBook(ledger).figures()['resting_reserve_native'] > 0
        assert not any(row['event'] == 'terminal_order' for row in rows(first.journal.path))
        clock.sleep(701)
        outcome, local, proof = close_claim(controller, account, status, ledger, clock, runtime)
        assert 'terminal_order_unavailable' in local['money_read_gaps']
        assert not runtime.state.ledger.unresolved_legs()


def test_partial_fill_in_real_canceled_order_row_reposts_after_requote_cancel(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read, trace, began = pinb_fixture(
            tmp_path, monkeypatch, fills=False)
        first = controller.bands[0]; raw = account.raws[0]
        observe, cancel = first.observe_snapshot, raw.cancel
        raced = []
        def snapshot(value):
            observation = observe(value)
            observation['requote_legs'] = [0] if first.posts == 2 and not raced and clock.seconds >= 60 else []
            return observation
        def canceled(oid):
            reply = cancel(oid)
            if not raced:
                raced.append(oid)
                raw.memory.orders[oid]['size_matched'] = '1'
                account.fill_times.append(clock.seconds)
            return reply
        first.observe_snapshot, raw.cancel = snapshot, canceled
        result = controller.run()
        assert raced and first.submits == 4 and result['cleanup_ok'], result
        assert not first._evidence_faults and not result['unknown_submit']
        retained = rows(first.journal.path)
        reads = [row['response'] for row in retained if row['event'] == 'cancel_order_read_response']
        assert reads and reads[0]['status'] == 'CANCELED' and reads[0]['size_matched'] == '1'
        assert set(shape('order_read_after_cancel_row')) <= set(reads[0])
        close_claim(controller, account, status, ledger, clock, runtime)


def test_extra_owner_cash_is_quarantined_and_does_not_expand_campaign_capital(tmp_path, monkeypatch):
    from weather.market.lfc_capital import ASSET, CapitalRefused
    from weather.market.lfc_capital_reads import synchronize
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read, trace, began = pinb_fixture(
            tmp_path, monkeypatch, fills=False)
        assert controller.run()['cleanup_ok']
        close_claim(controller, account, status, ledger, clock, runtime)
        active = runtime.state.ledger
        before = CapitalBook(active).figures()
        incoming = read()
        incoming['balances'] = {'available_collateral': '350', 'assets': {ASSET: '350'},
                                'collateral_evidence': {'balance': '350000000'}}
        observed = synchronize(active, runtime.original_baseline(active), incoming)
        assert observed['quarantined_unattributed_incoming_native'] == 50_000_000
        assert observed['cash_bridge_complete'] is False
        after = CapitalBook(active).figures()
        assert after['owner_contributions_native'] == before['owner_contributions_native'] == 300_000_000
        assert after['headroom_native'] == before['headroom_native'] == 300_000_000
        assert CapitalBook(active).gate(reserve='1', available_cash='350')['funding_native'] == 300_000_000
        with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
            CapitalBook(active).gate(reserve='300.000001', available_cash='350')


def test_missing_positions_sample_cannot_be_used_as_empty_account_proof(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_state import StateRefused
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read, trace, began = pinb_fixture(
            tmp_path, monkeypatch, fills=False)
        packet = read(); packet['positions'] = shape('positions_row')
        with pytest.raises(StateRefused, match='account_read_binding'):
            runtime.core_proof(ledger, packet)
        assert CapitalBook(ledger).figures()['headroom_native'] == 300_000_000
