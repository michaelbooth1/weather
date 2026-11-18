"""F2 proof continuity through typed terminal-read gaps, using inert venues only."""
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_controller import MAKER, setup
from tests.market.test_lfc_f2_evidence import runtime_at_controller
from tests.market.test_lfc_f2_repost import campaign_stream
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_reads import TerminalBackfillRefused
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha


@pytest.mark.parametrize('case', ['recovered', 'unreadable', 'wrong_order', 'wrong_quantity'])
def test_postcheck_needs_an_exact_get_for_missing_private_terminal_order(tmp_path, monkeypatch, case):
    with account_lease(MAKER, backend=Mutexes()):
        controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
        raw = account.raws[0]
        original_read = raw.order
        missing = []

        def order(oid):
            if clock.seconds >= 300 and (not missing or oid == missing[0]):
                if not missing:
                    missing.append(oid)
                raise TimeoutError('synthetic in-band read gap')
            return original_read(oid)

        raw.order = order
        if case == 'wrong_quantity':
            original_verify = controller.verify

            def verify():
                # Independent terminal proof already booked the order. Its
                # missing journal observation still needs an exact later GET.
                ledger.terminal(missing[0], original_read(missing[0]), source='fixture_reconcile')
                return original_verify()

            controller.verify = verify
        controller.run()
        runtime = runtime_at_controller(controller, account, status, ledger, clock, monkeypatch)
        result = runtime.session_result(account.claim, status, status.finish(success=False), 1)
        assert result['local_money_proof']['complete']
        assert result['local_money_proof']['missing_terminal_orders'] == missing
        runtime.save_result(account.claim, result)
        saved = runtime.saved_result(account.claim)
        assert runtime.state.incidents() == []
        original_hash = file_sha(controller.bands[0].journal.path)
        outcome_hash = file_sha(runtime.state.root / 'results' / (controller.attempt_id + '.json'))
        read = runtime.read_account
        calls = []

        def get(oid):
            calls.append(clock.seconds)
            if case == 'unreadable' or (case == 'recovered' and len(calls) < 3):
                raise TimeoutError('synthetic postcheck transport gap')
            row = original_read(oid)
            if case == 'wrong_order':
                return dict(row, id='unrelated-order')
            if case == 'wrong_quantity':
                return dict(row, size_matched='11')
            return row

        def account_get(*, terminal_order_ids):
            assert terminal_order_ids == missing
            begin = clock.now()
            observations = runtime.read_missing_terminal_orders(SimpleNamespace(order=get), terminal_order_ids)
            packet = read()
            packet['started_at_utc'] = begin.isoformat()
            packet['terminal_orders'] = observations
            return packet

        monkeypatch.setattr(runtime, 'read_account', account_get)
        if case == 'recovered':
            proof = runtime.postcheck(account.claim, saved)
            assert [n - calls[0] for n in calls] == [0, 1, 3]
            assert proof['cleanup_proven'] and proof['money_accounting_complete']
            assert proof['research_evidence_complete'] is False
            invalid = dict(proof)
            invalid.pop('account_read')
            with pytest.raises(StateRefused, match='closeout_terminal_backfill_digest'):
                runtime.state.close(account.claim, invalid, clock.now())
            runtime.state.close(account.claim, proof, clock.now())
            state = AccountState(runtime.state.root.parent, Ledger.open(ledger.path, clock=clock.now))
            state.require_retained_evidence()
            assert state.pending() == [] and state.incidents() == []
        else:
            with pytest.raises(TerminalBackfillRefused):
                runtime.postcheck(account.claim, saved)
            assert len(calls) == (3 if case == 'unreadable' else 1)
            fault, = runtime.state.incidents()
            assert fault['artifact'] == 'private-terminal-backfill'
            assert not (runtime.state.root / 'closed' / (controller.attempt_id + '.json')).exists()
        assert file_sha(controller.bands[0].journal.path) == original_hash
        assert file_sha(runtime.state.root / 'results' / (controller.attempt_id + '.json')) == outcome_hash


def test_owner_auto_redeem_finishes_via_account_proof_and_foreign_notice_still_refuses(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    raw = account.raws[0]
    raw.fixture_directory = tmp_path
    raw.maker = MAKER
    notice = {'event_type': 'auto_redeem', 'proxy_wallet': MAKER,
              'txn_hash': '0x' + '1' * 64, 'condition_id': '0x' + '2' * 64}
    stream = campaign_stream(raw)
    with pytest.raises(RuntimeError, match='unknown_account_event'):
        stream._normalize_event(dict(notice, proxy_wallet='0x' + 'f' * 40))
    with pytest.raises(RuntimeError, match='unknown_account_event'):
        stream._normalize_event(dict(notice, order_id='unexpected-order'))
    marker = stream._normalize_event(notice)
    assert marker[0]['event_type'] == 'account_redemption_notice'
    assert set(marker[0]) == {'event_type', 'raw_event_sha256'}
    raw.events = lambda: marker if clock.seconds >= 12 else []
    result = controller.run()
    assert result['reason'] == 'account_redemption_notice'
    assert result['cleanup_ok'] and result['inventory_proven']
    assert ledger.unresolved_legs() == []
    from weather.market.lfc_campaign_proof import local_money_proof
    local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                              attempt_id=controller.attempt_id, outcome=status.finish(success=True),
                              terminal_backfill=True)
    assert local['complete'] and not local.get('missing_terminal_orders')
