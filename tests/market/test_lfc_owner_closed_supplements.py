"""Guards: T119r6 owner-accepted gaps never recur as supplement faults; N1 stays strict."""
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_campaign_recovery import owner_runtime
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_owner_close import owner_close
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_f2_economics import publish_supplements
from weather.market.lfc_recording_io import file_sha


@pytest.mark.parametrize('second_close', [False, True])
def test_owner_accepted_gaps_survive_repeated_supplements_and_cold_reopen(
        tmp_path, monkeypatch, second_close):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, first, directory = owner_runtime(tmp_path, monkeypatch)
        original = directory / 'journal.jsonl'
        original.write_text('synthetic retained fragment')
        assert owner_close(runtime, first) == 0
        state = runtime.state
        closed = state.root / 'closed' / (claim['attempt_id'] + '.json')
        closed_bytes = closed.read_bytes()
        if second_close:
            # Exact old publisher behavior: strict proof retries an acknowledged
            # gap and creates another occurrence for this same source attempt.
            with pytest.raises(StateRefused):
                state.retained_result(claim)
            second, = state.incidents()
            incident = second['attempt_id']
            sha = file_sha(state.root / 'incidents' / (incident + '.json'))
            monkeypatch.setattr('builtins.input', lambda: 'close ' + sha[:12])
            assert owner_close(runtime, incident) == 0
        receipts = {p.name: p.read_bytes() for p in (state.root/'owner-closures').glob('*.json')}
        count = len(state.ledger.autostart_incidents)
        for _ in range(3):
            publish_supplements(runtime)
            runtime.reload_ledger()
            runtime.state.require_retained_evidence()
            assert runtime.state.incidents() == []
            assert len(runtime.state.ledger.autostart_incidents) == count
        assert closed.read_bytes() == closed_bytes
        assert runtime.state.read(closed)['proof']['research_evidence_complete'] is False
        assert {p.name: p.read_bytes() for p in (state.root/'owner-closures').glob('*.json')} == receipts
        assert not list((state.root/'economics').glob('*.json'))
        assert not (state.root/'results'/(claim['attempt_id']+'.json')).exists()


@pytest.mark.parametrize('corruption', ['new_artifact_change', 'closure_change'])
def test_supplement_skip_revalidates_owner_decision_and_original_hashes(
        tmp_path, monkeypatch, corruption):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, first, directory = owner_runtime(tmp_path, monkeypatch)
        original = directory/'journal.jsonl'
        original.write_text('synthetic retained fragment')
        assert owner_close(runtime, first) == 0
        publish_supplements(runtime)
        runtime.reload_ledger()
        if corruption == 'new_artifact_change':
            original.write_text('genuinely changed after owner acceptance')
        else:
            receipt = runtime.state.root/'owner-closures'/(first+'.json')
            receipt.write_bytes(receipt.read_bytes()+b' ')
        with pytest.raises(StateRefused):
            publish_supplements(runtime)
        if corruption == 'new_artifact_change':
            assert len(runtime.state.ledger.autostart_incidents) == 2
            assert runtime.state.incidents()[0]['attempt_id'] != first
        assert not list((runtime.state.root/'economics').glob('*.json'))
