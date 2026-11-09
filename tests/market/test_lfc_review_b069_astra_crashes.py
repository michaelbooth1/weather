"""Guards: B067 classification and durable closure/anchor crash boundaries.

All state is generated under tmp_path; no account, reader or venue capability.
"""
from pathlib import Path
import os
import json
import uuid
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, NOW
from tests.market.test_lfc_review_b067_integrity import prepared
from weather.market import lfc_campaign_closures as closures
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_ledger import Ledger, LedgerUnavailable


def reopen(runtime):
    state=runtime.state
    return AccountState(state.root.parent,Ledger.open(state.ledger.path,clock=runtime.clock.now))


@pytest.mark.parametrize('point',['closure_partial','closure_fsync','rename_after','anchor_before',
                                  'anchor_fsync','anchor_partial'])
def test_crashes_never_erase_originals_or_allow_unverified_completion(tmp_path,monkeypatch,point):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,policy,claim,proof=prepared(tmp_path,monkeypatch)
        state=runtime.state; path=state.root/'closed'/(claim['attempt_id']+'.json')
        ledger_path=state.ledger.path; before=ledger_path.read_bytes()
        ordinary_open=Path.open; ordinary_fsync=os.fsync; ordinary_rename=os.rename
        target_fd=[None]; hit=[]; stage=[]
        ordinary_record = state.ledger.record
        def record(event, **fields):
            stage[:] = [event]
            return ordinary_record(event, **fields)
        class FaultWriter:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def __getattr__(self,name):return getattr(self.stream,name)
            def write(self,raw):
                hit.append(point)
                self.stream.write(raw[:len(raw)//2]);self.stream.flush();ordinary_fsync(self.stream.fileno())
                if point=='anchor_partial':raise OSError('synthetic_torn_append')
                return len(raw)//2
        def opened(p,mode='r',*args,**kwargs):
            selected=(p==ledger_path and mode=='ab' and stage == ['autostart_close']) if point.startswith('anchor_') else ('.attempt-' in p.name and mode=='xb')
            if selected and point=='anchor_before':
                hit.append(point);raise OSError('synthetic_before_append')
            stream=ordinary_open(p,mode,*args,**kwargs)
            if selected:
                target_fd[0]=stream.fileno()
                if point in {'closure_partial','anchor_partial'}:return FaultWriter(stream)
            return stream
        def fsync(fd):
            ordinary_fsync(fd)
            if point.endswith('_fsync') and fd==target_fd[0]:
                hit.append(point);raise OSError('synthetic_after_fsync')
        def rename(a,b):
            ordinary_rename(a,b)
            if b==path:
                hit.append(point);raise OSError('synthetic_after_rename')
        with monkeypatch.context() as crash:
            crash.setattr(state.ledger, 'record', record)
            crash.setattr(Path,'open',opened);crash.setattr(os,'fsync',fsync)
            if point=='rename_after':crash.setattr(os,'rename',rename)
            with pytest.raises((OSError,LedgerUnavailable)):
                state.close(claim,proof,NOW)
        assert hit
        if point=='anchor_partial':
            original=path.read_bytes()
            with pytest.raises(LedgerUnavailable):reopen(runtime)
            assert path.read_bytes()==original and ledger_path.read_bytes()!=before
        elif point in {'closure_partial','closure_fsync'}:
            assert not path.exists() and ledger_path.read_bytes()==before
            fresh=reopen(runtime);fresh.verify()
            assert fresh.pending()==[claim] and not fresh.ledger.autostart_incidents
        else:
            original=path.read_bytes()
            for _ in range(2):
                fresh=reopen(runtime);fresh.verify();runtime.state=fresh
                assert len(fresh.ledger.event_rows('autostart_close'))==1
                assert path.read_bytes()==original and not fresh.ledger.autostart_incidents


def test_retryable_anchor_append_failure_does_not_invent_evidence_loss(tmp_path,monkeypatch):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,policy,claim,proof=prepared(tmp_path,monkeypatch)
        state=runtime.state
        with monkeypatch.context() as first_crash:
            first_crash.setattr(closures,'anchor',lambda *a:(_ for _ in ()).throw(OSError('crash_before_anchor')))
            with pytest.raises(OSError):state.close(claim,proof,NOW)
        path=state.root/'closed'/(claim['attempt_id']+'.json');original=path.read_bytes()
        state=reopen(runtime);runtime.state=state
        ordinary_open=Path.open;attempts=[];before=state.ledger.path.read_bytes()
        def once(p,mode='r',*args,**kwargs):
            if p==state.ledger.path and mode=='ab' and not attempts:
                attempts.append(True)
                assert p.read_bytes()==before
                raise OSError('synthetic_transient_append_open_failure')
            return ordinary_open(p,mode,*args,**kwargs)
        monkeypatch.setattr(Path,'open',once)
        with pytest.raises((StateRefused,LedgerUnavailable)):state.verify()
        state=reopen(runtime);state.verify()
        assert len(state.ledger.event_rows('autostart_close'))==1 and path.read_bytes()==original
        from weather.market.lfc_campaign import CampaignCoordinator
        runtime.state=state
        runtime.pre_go=lambda *a:pytest.fail('No admission during unresolved storage failure')
        coordinator=CampaignCoordinator(state=state,runtime=runtime,clock=runtime.clock,control_root=runtime.control_root)
        observed={'next_tick':coordinator.tick(lambda:policy),
            'closure_unchanged':path.read_bytes()==original,'anchor_count':len(state.ledger.event_rows('autostart_close')),
            'incident_count':len(state.ledger.autostart_incidents),'unacknowledged':len(state.ledger.unacknowledged_intents())}
        output=tmp_path/('r6-false-loss-'+uuid.uuid4().hex)
        output.mkdir()
        (output/'closed.json').write_bytes(original)
        (output/'ledger.jsonl').write_bytes(state.ledger.path.read_bytes())
        (output/'observed.json').write_text(json.dumps(observed,sort_keys=True))
        for incident in state.ledger.autostart_incidents:
            name=incident['attempt_id']+'.json'
            (output/name).write_bytes((state.root/'incidents'/name).read_bytes())
        assert not state.ledger.autostart_incidents and observed['next_tick']!='INCIDENT',observed
