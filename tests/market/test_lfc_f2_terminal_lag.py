"""Synthetic closed-order lag through the real F2 cleanup and retained proof.

Guards: T073 terminal-read lag must retire safely without a private-evidence incident.
All order/account reads use in-memory fixtures; no client or credential is opened.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_recording_io import strict_json


def closed_order_lag(account, clock, *, seconds, live=False):
    """Final GET starts lagging at the fill cleanup's first cancel ACK.

    The preceding fill observation succeeds, as in the reported real session.
    Both just-closed identities share the lag, exposing per-order budget resets.
    """
    raw = account.raws[0]
    cancel, order = raw.cancel, raw.order
    began, observations = [], []

    def cancel_ack(oid):
        result = cancel(oid)
        if account.fill_times and not began:
            began.append(clock.seconds)
            account.fills_enabled = False
        return result

    def read_order(oid):
        row = order(oid)
        if began and clock.seconds - began[0] < seconds:
            observations.append((clock.seconds, oid))
            if live:
                return dict(row, status='LIVE')
            raise TimeoutError('order_read_undecodable')
        return row

    raw.cancel, raw.order = cancel_ack, read_order
    return began, observations


@pytest.mark.parametrize('live', [False, True], ids=['undecodable', 'readable-LIVE'])
def test_three_second_closed_order_lag_fills_reposts_and_closes_without_fault(tmp_path, monkeypatch, live):
    with account_lease('0x' + 'a' * 40, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, enrolled=True)
        began, observations = closed_order_lag(account, clock, seconds=3, live=live)
        result = controller.run()
        band = controller.bands[0]
        assert began and observations and band.submits == 4, controller.results
        assert result['cleanup_ok'] and not band._evidence_faults, result
        assert controller.results[band.session_id]['reason'] == 'fixed_end'
        outcome = status.finish(success=True)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and local['money_read_gaps'] == [], local
        runtime.save_result(account.claim, {'session_id': controller.session_id,
            'private_evidence_directory': controller.directory.name, 'outcome': outcome,
            'local_money_proof': local, 'evidence_complete': True})
        runtime.lease = SimpleNamespace(check=lambda: None)
        runtime.control_root = tmp_path / 'control'
        monkeypatch.setattr(runtime, 'read_account', read)
        proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
        assert proof['money_accounting_complete'] and proof['cleanup_proven']
        runtime.state.close(account.claim, proof, clock.now())
        assert runtime.state.pending() == [] and runtime.state.incidents() == []


@pytest.mark.parametrize('live', [False, True], ids=['undecodable', 'readable-LIVE'])
def test_lag_past_shared_budget_retires_keeps_reserve_then_postcheck_heals(tmp_path, monkeypatch, live):
    with account_lease('0x' + 'a' * 40, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, enrolled=True)
        began, observations = closed_order_lag(account, clock, seconds=600, live=live)
        result = controller.run()
        band = controller.bands[0]
        assert controller.results[band.session_id]['reason'] == 'repost_terminal_unreadable', controller.results
        assert band.submits == 2 and band._evidence_faults == {'terminal_order_unavailable'}
        rows = [strict_json(line) for line in band.journal.path.read_bytes().splitlines()]
        terminal = next(row for row in rows if row['event'] == 'terminal')
        from weather.market.mm_stage2_hold import utc
        assert (utc(terminal['recorded_at_utc']) - clock.base).total_seconds() == began[0] + 10
        assert all(t - began[0] < 10 or t >= 300 for t, _ in observations)
        assert not any(row['event'] == 'terminal_order' for row in rows)
        assert not result['cleanup_ok'] and not result['unknown_submit']
        outcome = status.finish(success=False)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and 'terminal_order_unavailable' in local['money_read_gaps'], local
        assert not local['explained_gaps']
        runtime.save_result(account.claim, {'session_id': controller.session_id,
            'private_evidence_directory': controller.directory.name, 'outcome': outcome,
            'local_money_proof': local, 'evidence_complete': False, 'inventory_proven': False})
        runtime.state.retained_result(account.claim)
        assert runtime.state.incidents() == []
        reserved = CapitalBook(ledger).figures()['resting_reserve_native']
        assert reserved == sum(int(Decimal(leg['price']) * Decimal(leg['size']) * 1_000_000)
                               for leg in ledger.unresolved_legs()) > 0
        runtime.lease = SimpleNamespace(check=lambda: None)
        runtime.control_root = tmp_path / 'control'
        clock.sleep(601)
        monkeypatch.setattr(runtime, 'read_account', read)
        proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
        assert proof['money_accounting_complete'] and proof['cleanup_proven'], proof
        assert not proof['raw_evidence_flags']['inventory_proven']
        assert CapitalBook(runtime.state.ledger).figures()['resting_reserve_native'] == 0
        runtime.state.close(account.claim, proof, clock.now())
        assert runtime.state.pending() == [] and runtime.state.incidents() == []


def test_sdk_terminal_strings_and_rejected_shapes():
    from polymarket import UnexpectedResponseError
    from polymarket.models.clob.account import OpenOrder
    from tests.market.test_re1_sdk_shapes import sdk_order
    from weather.market.mm_account_reads import order_terminal
    from weather.market.mm_official_adapter import plain_sdk_value
    row = plain_sdk_value(sdk_order())
    for status in ('CANCELED', 'CANCELLED', 'MATCHED', 'EXPIRED'):
        assert order_terminal(plain_sdk_value(sdk_order(status)), order_id=row['id'], size='20')
    for status in ('LIVE', 'DELAYED', 'UNMATCHED', 'SOMETHING_NEW'):
        assert not order_terminal(plain_sdk_value(sdk_order(status)), order_id=row['id'], size='20')
    raw = sdk_order().model_dump(mode='json', by_alias=True)
    # model_dump uses the model's names for validation-only aliases.
    raw.update(asset_id=raw['token_id'], expiration=raw['expires_at'])
    assert OpenOrder.parse_response(raw).id == row['id']
    for damaged in (None, [], {'id': row['id'], 'status': 'MATCHED'},
                    {'data': raw}, dict(raw, price=1), dict(raw, size_matched=0),
                    dict(raw, price='not-a-decimal'), dict(raw, created_at='bad-date')):
        with pytest.raises(UnexpectedResponseError):
            OpenOrder.parse_response(damaged)
