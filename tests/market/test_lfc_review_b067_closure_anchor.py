"""Guards: B067 retained close loss must latch, including a cold real-F2 reopen."""
import json
import uuid
from pathlib import Path
from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_review_b065_idle import idle_fixture, reboot
from weather.market.lfc_campaign_guard import account_lease


def retain(label, original, path, state, observed):
    directory=Path(r'C:\t\codex\T004\out')/('r5-closure-evidence-'+label+'-'+uuid.uuid4().hex)
    directory.mkdir(exist_ok=False)
    (directory/'original-closed.json').write_bytes(original)
    if path.exists(): (directory/'rewritten-closed.json').write_bytes(path.read_bytes())
    (directory/'ledger.jsonl').write_bytes(state.ledger.path.read_bytes())
    (directory/'observed.json').write_text(json.dumps(observed,sort_keys=True,indent=2))


def test_deleted_retained_close_is_latched_not_automatically_rewritten(tmp_path,monkeypatch):
    with account_lease(MAKER,backend=Mutexes()):
        runtime,c,p,directory,calls=idle_fixture(tmp_path,monkeypatch)
        assert c.tick(lambda:p)=='IDLE' and c.tick(lambda:p)=='IDLE'
        claim=runtime.state.claims()[0]
        path=runtime.state.root/'closed'/(claim['attempt_id']+'.json')
        original=path.read_bytes()
        path.unlink()
        reboot(runtime,c)
        outcome=c.tick(lambda:p)
        # Diagnostic facts remain in the assertion output, including whether
        # the missing historical decision was regenerated from a fresh proof.
        observed={'outcome':outcome,'recreated':path.exists(),
                  'rewritten':path.exists() and path.read_bytes()!=original,
                  'incidents':len(runtime.state.ledger.autostart_incidents),
                  'claims':len(runtime.state.ledger.autostart_claims),
                  'full_validations':len(calls)}
        observed['next_tick']=c.tick(lambda:p)
        observed['incidents_after_next_tick']=len(runtime.state.ledger.autostart_incidents)
        retain('normal',original,path,runtime.state,observed)
        assert not observed['rewritten'] and observed['incidents']>0, json.dumps(observed,sort_keys=True)


def test_real_f2_result_closure_loss_cannot_silently_become_complete(tmp_path,monkeypatch):
    from tests.market.test_lfc_review_t044_recheck2_end_to_end import (
        test_actual_tick_preserves_pre_post_vs_post_through_result_and_closure as end_to_end)
    from weather.market.lfc_campaign import CampaignCoordinator
    captured=[]
    original=CampaignCoordinator.__init__
    def capture(self,**kwargs):
        original(self,**kwargs); captured.append(self)
    monkeypatch.setattr(CampaignCoordinator,'__init__',capture)
    # Actual F2 session/result/closure, two inert bands, no real venue.
    end_to_end(tmp_path,monkeypatch,'intent_before_append',1,'memory')
    c=captured[-1]; runtime=c.runtime
    with account_lease(MAKER,backend=Mutexes()):
        c.state=runtime.state
        claim=c.state.claims()[0]
        from weather.market.lfc_campaign_policy import parse_policy
        policy=parse_policy(c.state.read(c.state.root/'policies'/(claim['attempt_id']+'.json'))['policy'])
        runtime.clock.seconds+=7200
        assert c.tick(lambda:policy)=='IDLE'
        assert (c.state.root/'.idle-validation.json').exists()
        path=c.state.root/'closed'/(claim['attempt_id']+'.json')
        original_bytes=path.read_bytes(); path.unlink()
        # B067 detects/latches on runtime reopen itself. Keep the original
        # assertions below and continue the fixture to inspect the next ticks.
        from weather.market.lfc_campaign_state import StateRefused
        try:
            runtime.reload_ledger()
        except StateRefused as exc:
            if str(exc) != 'anchored_closure_evidence_fault':
                raise
        c.state=runtime.state
        first=c.tick(lambda:policy)
        second=c.tick(lambda:policy)
        observed={'first_tick':first,'second_tick':second,
            'closure_rewritten':path.exists() and path.read_bytes()!=original_bytes,
            'incidents':len(c.state.ledger.autostart_incidents),
            'basis':c.state.ledger.sleeve_loss_basis}
        retain('f2',original_bytes,path,c.state,observed)
        assert not observed['closure_rewritten'] and observed['incidents']>0,json.dumps(observed,sort_keys=True)
