"""Guards: B076 bounded final-read lag and unresolved-first repost proofs.

All clocks, account reads and cancellations are inert local fixtures.
"""
from decimal import Decimal
from types import SimpleNamespace

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_controller import MAKER, NOW, setup
from tests.market.test_lfc_f2_evidence import runtime_at_controller
from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.lfc_completion import complete_evidence, ledger_completion
from weather.market.lfc_f2_controller import F2Band


def delayed_final_reads(account, clock, seconds):
    reads = []
    for raw in account.raws:
        original = raw.order

        def read(oid, original=original):
            if clock.seconds >= 300:
                reads.append((clock.seconds, oid))
                if clock.seconds < 300 + seconds:
                    raise TimeoutError('synthetic terminal propagation')
            return original(oid)

        raw.order = read
    return reads


def test_fixed_end_short_read_lag_closes_complete_without_attention(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
        reads = delayed_final_reads(account, clock, 1.5)
        result = controller.run()
        assert result['reason'] == 'fixed_end' and complete_evidence(result), result
        assert clock.seconds == 302
        assert all(raw.cancellations[0][0] == 300 for raw in account.raws)
        assert all(raw.cancellations[0][0] <= reads[0][0] for raw in account.raws)
        outcome = status.finish(success=True)
        assert outcome['state'] == 'COMPLETE'
        local = local_money_proof(controller.directory, ledger=ledger,
            session_id=controller.session_id, attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and local['money_read_gaps'] == [], local
        runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
        runtime.save_result(account.claim, {'session_id': controller.session_id,
            'private_evidence_directory': controller.directory.name, 'outcome': outcome,
            'local_money_proof': local, 'evidence_complete': True, 'inventory_proven': True,
            'unknown_submit': False})
        proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
        assert proof['money_accounting_complete'] and proof['cleanup_proven'], proof
        runtime.state.close(account.claim, proof, clock.now())
        assert complete_evidence(ledger_completion(tmp_path, ledger))
        assert runtime.state.pending() == [] and runtime.state.incidents() == []


def test_fixed_end_read_lag_past_three_seconds_keeps_typed_gap(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    reads = delayed_final_reads(account, clock, 600)
    result = controller.run()
    assert not result['evidence_complete'] and not result['unknown_submit']
    assert result['evidence_faults'] == ['f2_account_cleanup_pending', 'terminal_order_unavailable']
    assert clock.seconds == 306  # One shared three-second budget per band.
    assert all(raw.cancellations[0][0] == 300 for raw in account.raws)
    assert all(raw.cancellations[0][0] <= reads[0][0] for raw in account.raws)
    assert ledger.unresolved_legs()
    local = local_money_proof(controller.directory, ledger=ledger,
        session_id=controller.session_id, attempt_id=controller.attempt_id,
        outcome=status.finish(success=False))
    assert local['complete'] and 'terminal_order_unavailable' in local['money_read_gaps'], local


def test_repost_proves_unresolved_before_thirty_slow_terminal_probes():
    band = object.__new__(F2Band)
    band.clock, band.size = Clock(NOW), Decimal(20)
    old = [f'old-{i}' for i in range(30)]
    band.known = {oid: (0, Decimal('.3')) for oid in [*old, 'unresolved']}
    band.ledger = SimpleNamespace(by_order={oid: oid for oid in band.known}, legs={
        oid: {'status': 'acknowledged' if oid == 'unresolved' else 'terminal'} for oid in band.known})
    band._terminal_order_deadline, band._terminal_read_seconds = None, 10
    band.progress = lambda: None
    band._retain = lambda *a, **k: None
    calls, proved = [], []

    def read(oid):
        calls.append((oid, band.clock.seconds))
        if oid == 'unresolved':
            if band.clock.seconds < 4:
                raise TimeoutError('synthetic unresolved propagation')
            proved.append(band.clock.seconds)
        else:
            band.clock.sleep(.4)
        return {'id': oid, 'status': 'CANCELED', 'size_matched': '0', 'original_size': '20'}

    band.venue = SimpleNamespace(order=read)
    # The shared Session enumerates historical orders in insertion order.
    for oid in band.known:
        assert band.terminal_order_read(oid, None)['id'] == oid
    assert calls[0] == ('unresolved', 0)
    assert proved == [4] and all(at >= 4 for oid, at in calls if oid in old)
    assert all(sum(oid == seen for seen, _ in calls) == 1 for oid in old)


def test_sample_scoring_fault_then_fill_reposts_without_cancelling_peers(tmp_path, monkeypatch):
    from tests.market.test_lfc_f2_repost import fixture

    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, enrolled=True)
        first, peer = controller.bands
        raw = account.raws[0]
        scoring, sampled = raw.scoring, []

        def unavailable():
            raise TimeoutError('synthetic ancillary sample')

        def scoring_with_one_gap(ids):
            if not sampled:
                sampled.append(clock.seconds)
                assert first.sample('scoring', unavailable) is None
            return scoring(ids)

        raw.scoring = scoring_with_one_gap
        result = controller.run()
        assert sampled and 'sample_scoring' in first._evidence_faults
        assert first.submits > 2, controller.results
        assert controller.results[peer.session_id]['reason'] == 'fixed_end', controller.results
        assert all(at >= peer.deadline for at, _ in account.raws[1].cancellations)
        assert all(row['failure_type'] is None for row in controller.results.values())
        outcome = status.finish(success=False)  # The ancillary gap remains honestly recorded.
        local = local_money_proof(controller.directory, ledger=ledger,
            session_id=controller.session_id, attempt_id=controller.attempt_id, outcome=outcome)
        assert local['complete'] and local['money_read_gaps'] == [], local
        assert local['explained_gaps'] == ['sample_scoring']
        runtime.save_result(account.claim, {'session_id': controller.session_id,
            'private_evidence_directory': controller.directory.name, 'outcome': outcome,
            'local_money_proof': local, 'evidence_complete': False, 'inventory_proven': True,
            'unknown_submit': False})
        runtime.lease = SimpleNamespace(check=lambda: None)
        runtime.control_root = tmp_path / 'control'
        monkeypatch.setattr(runtime, 'read_account', read)
        proof = runtime.postcheck(account.claim, runtime.saved_result(account.claim))
        assert proof['cleanup_proven'] and proof['money_accounting_complete'], proof
        runtime.state.close(account.claim, proof, clock.now())
        assert runtime.state.pending() == [] and runtime.state.incidents() == []
