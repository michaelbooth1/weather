"""Guards: B065 indexed replay equals full scans through recovery and reopen."""
import random
import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at, policy_row
from tests.market.test_lfc_campaign_recovery import owner_runtime
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_campaign_recovery import recover_empty, attempt_intents
from weather.market.lfc_campaign_owner_close import owner_close
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha


def scanned(self, event, *, field=None, value=None):
    return tuple(r for r in self.rows if r['event']==event and (field is None or r.get(field)==value))


def scanned_intents(self, attempt):
    sessions = {sid for sid, s in self.sessions.items() if s['start'].get('autostart_attempt_id')==attempt}
    return tuple(r for r in self.rows if r['event']=='leg_intent' and r['session_id'] in sessions)


def equivalent(state, monkeypatch):
    ledger = state.ledger
    for event in {r['event'] for r in ledger.rows}:
        assert ledger.event_rows(event)==scanned(ledger,event)
        for field in ('attempt_id','source_attempt_id'):
            for value in {r.get(field) for r in ledger.rows if r['event']==event}:
                assert ledger.event_rows(event,field=field,value=value)==scanned(ledger,event,field=field,value=value)
    attempts = {s['start'].get('autostart_attempt_id') for s in ledger.sessions.values()}
    for attempt in attempts:
        assert tuple(attempt_intents(ledger,attempt))==scanned_intents(ledger,attempt)
    indexed = (state.verify(), state.claims(), state.pending(), state.incidents())
    original_anchor = AccountState.result_anchor
    with monkeypatch.context() as old:
        old.setattr(Ledger,'event_rows',scanned)
        old.setattr(Ledger,'attempt_intent_rows',scanned_intents)
        old.setattr(AccountState,'result_anchor',lambda self, attempt, **kw: original_anchor(self,attempt))
        assert (state.verify(),state.claims(),state.pending(),state.incidents())==indexed


@pytest.mark.parametrize('seed', range(6))
def test_randomized_empty_claim_incidents_close_and_replay_match_scans(tmp_path, monkeypatch, seed):
    rng = random.Random(seed); clock = Clock()
    with account_lease(MAKER,backend=Mutexes()):
        state = state_at(tmp_path,clock)
        policy = parse_policy(policy_row()); claim = state.claim(policy.entries[0],policy,clock.now())
        for n in range(rng.randrange(1,7)):
            sid = 'empty-'+str(n)
            state.ledger.record('session_start',session_id=sid,counted=False,autostart_attempt_id=claim['attempt_id'])
            if rng.choice([True,False]): state.ledger.record('session_end',session_id=sid,unknown_submit=False)
        if rng.choice([True,False]): state.latch(claim['attempt_id'],'claimed_attempt_interrupted',clock.now())
        equivalent(state,monkeypatch)
        assert recover_empty(state,clock.now())
        equivalent(state,monkeypatch)
        state = AccountState(state.root.parent,Ledger.open(state.ledger.path,clock=clock.now))
        equivalent(state,monkeypatch)


@pytest.mark.parametrize('seed', range(4))
def test_randomized_owner_closure_occurrences_and_reopen_match_scans(tmp_path, monkeypatch, seed):
    rng = random.Random(seed)
    with account_lease(MAKER,backend=Mutexes()):
        runtime, claim, incident, _ = owner_runtime(tmp_path,monkeypatch)
        for n in range(rng.randrange(1,4)):
            equivalent(runtime.state,monkeypatch)
            path = runtime.state.root/'incidents'/(incident+'.json')
            monkeypatch.setattr('builtins.input',lambda:'close '+file_sha(path)[:12])
            assert owner_close(runtime,incident)==0
            equivalent(runtime.state,monkeypatch)
            runtime.reload_ledger()
            equivalent(runtime.state,monkeypatch)
            if n+1 < 3 and rng.choice([True,False]):
                incident = runtime.state.latch(claim['attempt_id'],'session_failed',runtime.clock.now())
            else: break


@pytest.mark.parametrize('value', [None, [], {'legacy':'extra'}])
def test_index_preserves_missing_and_unhashable_optional_field_semantics(tmp_path,value):
    clock=Clock()
    ledger=Ledger.create(tmp_path/'ledger.jsonl',clock=clock.now,maker_address=MAKER)
    ledger.record('baseline',label='fixture',attempt_id=value)
    for candidate in (ledger,Ledger.open(ledger.path,clock=clock.now)):
        assert candidate.event_rows('baseline',field='attempt_id',value=value)==scanned(
            candidate,'baseline',field='attempt_id',value=value)
        assert candidate.event_rows('baseline',field='source_attempt_id',value=None)==scanned(
            candidate,'baseline',field='source_attempt_id',value=None)


@pytest.mark.parametrize('metadata_only',[False,True])
def test_uncached_result_read_still_binds_the_bytes_after_prior_hash_check(tmp_path,monkeypatch,metadata_only):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from tests.market.lfc_campaign_fixtures import private_result
    from weather.market.lfc_campaign_state import StateRefused
    with account_lease(MAKER,backend=Mutexes()):
        runtime=runtime_at(tmp_path)
        policy=parse_policy(policy_row())
        claim=runtime.state.claim(policy.entries[0],policy,runtime.clock.now())
        _,result=private_result(runtime,claim,faults=())
        runtime.save_result(claim,result)
        state=AccountState(runtime.state.root.parent,runtime.state.ledger)
        path=state.root/'results'/(claim['attempt_id']+'.json')
        actual=state.file_sha; changed=[]
        def raced(file):
            sha=actual(file)
            if file==path and not changed:
                changed.append(True)
                with path.open('ab') as stream:stream.write(b' ')
            return sha
        monkeypatch.setattr(state,'file_sha',raced)
        with pytest.raises(StateRefused,match='private_result_evidence_fault'):
            state.result_anchor(claim['attempt_id'],metadata_only=metadata_only)
