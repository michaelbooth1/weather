"""Guards: B065 cheap idle ticks detect evidence loss and never admit from a cache."""
from datetime import timedelta
import os
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, NOW, policy_row, bind_launch
from tests.market.test_lfc_campaign_runtime import runtime_at
from tests.market.test_lfc_campaign_recurrence import configure_runtime, next_policy
from tests.market.lfc_campaign_fixtures import private_result
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_ledger import Ledger


def idle_fixture(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path); configure_runtime(runtime,monkeypatch)
    runtime.notify_control = lambda row: None
    policy = parse_policy(policy_row())
    claim = runtime.state.claim(policy.entries[0],policy,NOW)
    directory,result = private_result(runtime,claim,faults=())
    runtime.save_result(claim,result)
    runtime.state.close(claim,runtime.postcheck(claim,runtime.saved_result(claim)),NOW)
    policy = next_policy(runtime,12)
    runtime.clock.value -= timedelta(hours=2)
    coordinator = CampaignCoordinator(state=runtime.state,runtime=runtime,clock=runtime.clock,
        control_root=runtime.control_root)
    policy = bind_launch(coordinator,policy)
    calls = []
    original = AccountState.require_retained_evidence
    def retained(state):
        calls.append(state.ledger.previous)
        return original(state)
    monkeypatch.setattr(AccountState,'require_retained_evidence',retained)
    return runtime,coordinator,policy,directory,calls


def reboot(runtime, coordinator):
    runtime.state = AccountState(runtime.state.root.parent,
        Ledger.open(runtime.state.ledger.path,clock=runtime.clock.now,maker_address=MAKER))
    coordinator.state = runtime.state


def test_healthy_idle_ticks_reuse_only_metadata_after_cold_restart(tmp_path,monkeypatch):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,directory,calls = idle_fixture(tmp_path,monkeypatch)
        before = runtime.state.ledger.previous
        assert c.tick(lambda:p)=='IDLE' and len(calls)==1
        assert (runtime.state.root/'.idle-validation.json').exists()
        reboot(runtime,c)
        assert c.tick(lambda:p)=='IDLE' and len(calls)==1
        assert runtime.state.ledger.previous==before and len(runtime.state.claims())==1


@pytest.mark.parametrize('kind',['deleted','same_length_rewritten'])
def test_idle_evidence_change_reenters_full_validation_and_latches_before_claim(tmp_path,monkeypatch,kind):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,directory,calls = idle_fixture(tmp_path,monkeypatch)
        assert c.tick(lambda:p)=='IDLE'
        path=directory/'journal.jsonl'; raw=path.read_bytes(); stamp=path.stat()
        if kind=='deleted': path.unlink()
        else:
            path.write_bytes(b'['+raw[1:]); os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        reboot(runtime,c)
        assert c.tick(lambda:p)=='INCIDENT' and len(calls)==2
        assert len(runtime.state.incidents())==1 and len(runtime.state.claims())==1
        path.write_bytes(raw)
        assert c.tick(lambda:p)=='INCIDENT'  # Restoration never clears N1.


def test_lookback_keeps_full_validation_despite_matching_idle_cache(tmp_path,monkeypatch):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,_,calls = idle_fixture(tmp_path,monkeypatch)
        assert c.tick(lambda:p)=='IDLE'
        runtime.clock.value=p.entries[0].start-timedelta(minutes=2)
        assert c.tick(lambda:p)=='IDLE' and len(calls)==2


def test_due_followup_never_uses_idle_cache_and_callback_still_runs(tmp_path,monkeypatch):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,_,calls=idle_fixture(tmp_path,monkeypatch)
        due=[False]; callbacks=[]
        c.record_followups=lambda *a,**kw:callbacks.append(kw)
        runtime.followup_due=lambda policy:due[0]
        assert c.tick(lambda:p)=='IDLE'
        due[0]=True
        assert c.tick(lambda:p)=='IDLE' and len(calls)==2 and len(callbacks)==2


def test_native_stamp_unavailable_keeps_full_reads(tmp_path,monkeypatch):
    from weather.market import lfc_retained_cache
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,_,calls=idle_fixture(tmp_path,monkeypatch)
        monkeypatch.setattr(lfc_retained_cache,'change_stamp',lambda *a:None)
        assert c.tick(lambda:p)=='IDLE'
        assert c.tick(lambda:p)=='IDLE' and len(calls)==2
        assert not (runtime.state.root/'.idle-validation.json').exists()


def test_change_after_full_validation_does_not_seed_a_clean_cache(tmp_path,monkeypatch):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,directory,calls=idle_fixture(tmp_path,monkeypatch)
        retained=runtime.state.require_retained_evidence
        def raced():
            retained()
            with (directory/'journal.jsonl').open('ab') as stream: stream.write(b'changed-after-read')
        monkeypatch.setattr(runtime.state,'require_retained_evidence',raced)
        assert c.tick(lambda:p)=='IDLE'
        assert not (runtime.state.root/'.idle-validation.json').exists()
        monkeypatch.setattr(runtime.state,'require_retained_evidence',retained)
        assert c.tick(lambda:p)=='INCIDENT'


def test_corrupt_derived_cache_runs_full_verification_without_waiving_evidence(tmp_path,monkeypatch):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,_,calls=idle_fixture(tmp_path,monkeypatch)
        assert c.tick(lambda:p)=='IDLE'
        (runtime.state.root/'.idle-validation.json').write_text('not JSON')
        assert c.tick(lambda:p)=='IDLE' and len(calls)==2
        assert not runtime.state.incidents()
