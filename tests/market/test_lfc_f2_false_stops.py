"""Synthetic ordinary-venue misses through F2 cleanup and retained proof.

Guards: T075 C-H1/C-H3; kills transient-heartbeat incident latching and strict
repeat-cancel ACK mutations while preserving stale and still-open money stops.
No SDK, venue, reader, live record or credential is used.
"""
from copy import deepcopy

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_controller import Account, MAKER, Raw, setup
from tests.market.test_lfc_f2_evidence import runtime_at_controller
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_recording_io import strict_json
from weather.market.mm_stage2_hold import cancel_ack_ids


def journal_rows(path):
    return [strict_json(line) for line in path.read_bytes().splitlines()]


def test_one_failed_root_heartbeat_closes_without_campaign_incident(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
        sends = []

        def heartbeat():
            sends.append(clock.seconds)
            if len(sends) == 3:
                raise TimeoutError('synthetic single heartbeat miss')
            return {'status': 'ok'}

        account.raws[0].heartbeat = heartbeat
        result = controller.run()
        assert result['reason'] == 'fixed_end' and result['cleanup_ok'], result
        rows = journal_rows(controller.journal.path)
        assert sum(row['event'] == 'heartbeat_unavailable' for row in rows) == 1
        assert sum(row['event'] == 'heartbeat_response' for row in rows) > 100
        outcome = status.finish(success=True)
        local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                 attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and local['money_read_gaps'] == [], local
        # This legacy fixture has no normalized venue earnings response. K8
        # names that ancillary gap without changing the money proof.
        assert local['explained_gaps'] == ['campaign_reward_estimate_unavailable', 'heartbeat_unavailable']
        runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
        runtime.save_result(account.claim, {'session_id': controller.session_id,
            'private_evidence_directory': controller.directory.name, 'outcome': outcome,
            'local_money_proof': local, 'evidence_complete': True, 'inventory_proven': True,
            'unknown_submit': False})
        runtime.state.retained_result(account.claim)
        proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
        assert proof['money_accounting_complete'] and proof['cleanup_proven'], proof
        runtime.state.close(account.claim, proof, clock.now())
        runtime.state.require_retained_evidence()
        assert runtime.state.pending() == [] and runtime.state.incidents() == []


@pytest.mark.parametrize('error,reason,stop_at', [
    (TimeoutError, 'heartbeat_stale', 10),
    (ValueError, 'heartbeat_failed', 4),
])
def test_heartbeat_stale_and_nontransient_failure_still_end_all_bands(tmp_path, error, reason, stop_at):
    controller, account, status, ledger, clock = setup(tmp_path)
    good = []

    def heartbeat():
        if clock.seconds >= 4:
            raise error('synthetic heartbeat outage')
        good.append(clock.seconds)
        return {'status': 'ok'}

    account.raws[0].heartbeat = heartbeat
    result = controller.run()
    assert good == [0, 2]
    assert result['reason'] == reason and result['cleanup_ok'], result
    assert account.cancel_all_calls == [stop_at]
    assert all(row['reason'] == reason for row in controller.results.values())
    assert not account.open_orders() and not ledger.unresolved_legs()
    if reason == 'heartbeat_stale':
        assert stop_at - good[-1] == 8


class LaggingAccount(Account):
    def __init__(self, clock):
        super().__init__(clock)
        self.lagging = {}
        self.stays_open = False
        self.not_canceled_reason = 'already cancelled'

    def open_orders(self):
        actual = {row['id']: row for row in super().open_orders()}
        return list({**actual, **deepcopy(self.lagging)}.values())


class RepeatCancelRaw(Raw):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cancel_counts = {}
        self.repeat_responses = []

    def cancel(self, oid):
        if self.index != 0:
            return super().cancel(oid)
        count = self.cancel_counts.get(oid, 0) + 1
        self.cancel_counts[oid] = count
        if count == 1:
            before = deepcopy(self.memory.orders[oid])
            if self.account.stays_open and before['status'] == 'LIVE':
                # A first ACK is insufficient: this order really stays LIVE.
                self.cancellations.append((self.account.clock.seconds, oid))
                response = {'canceled': [oid], 'not_canceled': {}}
            else:
                response = super().cancel(oid)
            self.account.lagging[oid] = dict(before, status='LIVE')
            return response
        self.cancellations.append((self.account.clock.seconds, oid))
        self.account.lagging.pop(oid, None)
        response = {'canceled': [], 'not_canceled': {oid: self.account.not_canceled_reason}}
        self.repeat_responses.append(response)
        return response


@pytest.mark.parametrize('reason', ['already cancelled', 'already matched'])
def test_lagging_repeat_cancel_closes_band_and_peer_continues(tmp_path, reason):
    controller, account, status, ledger, clock = setup(
        tmp_path, account_type=LaggingAccount, raw_type=RepeatCancelRaw)
    account.filled_band, account.fill_at = 0, 12
    account.not_canceled_reason = reason
    result = controller.run()
    first, peer = controller.bands
    assert account.raws[0].repeat_responses
    assert first.cancellation_ok and controller.results[first.session_id]['reason'] == 'fill'
    assert controller.results[peer.session_id]['reason'] == 'fixed_end'
    assert all(when >= 300 for when, _ in account.raws[1].cancellations)
    assert account.cancel_all_calls == [300] and result['cleanup_ok'], result
    retained = [row['response'] for row in journal_rows(first.journal.path)
                if row['event'] == 'cleanup_cancel_response' and row['response'].get('not_canceled')]
    assert retained == account.raws[0].repeat_responses
    outcome = status.finish(success=True)
    local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id=controller.attempt_id, outcome=outcome)
    assert local['complete'] and local['money_read_gaps'] == [], local
    assert not ledger.unresolved_legs() and not account.open_orders()


def test_repeat_not_canceled_with_order_still_open_stops_peers_as_money_fault(tmp_path):
    controller, account, status, ledger, clock = setup(
        tmp_path, account_type=LaggingAccount, raw_type=RepeatCancelRaw)
    account.filled_band, account.fill_at = 0, 12
    account.stays_open = True
    result = controller.run()
    first, peer = controller.bands
    assert account.raws[0].repeat_responses and not first.cancellation_ok
    reads = [row for row in journal_rows(first.journal.path) if row['event'] == 'cleanup_open_orders']
    assert len(reads) == 10 and all(row['rows'] for row in reads)
    assert result['reason'] == 'f2_band_money_or_core_fault' and not result['cleanup_ok'], result
    assert controller.results[peer.session_id]['reason'] == 'f2_band_money_or_core_fault'
    assert account.cancel_all_calls[0] < 300
    assert account.open_orders() and ledger.unresolved_legs()


def test_shared_cancel_ack_parser_still_rejects_not_canceled():
    with pytest.raises(RuntimeError, match='no complete acknowledgment list'):
        cancel_ack_ids({'canceled': [], 'not_canceled': {'known': 'already cancelled'}})
