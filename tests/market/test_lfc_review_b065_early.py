"""Guards: B065 absent launch authority performs no pre-go reads or writes."""
import json

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at, StubRuntime
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import load_policy
from weather.market.lfc_f2_breadth import example_policy


@pytest.mark.parametrize('envelope',['missing','mismatched'])
def test_missing_envelope_defers_before_account_reads_baselines_or_workload_markers(tmp_path,monkeypatch,envelope):
    row = example_policy(); row['enabled'] = True
    path = tmp_path / 'policy.json'; path.write_text(json.dumps(row))
    policy = load_policy(path)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    clock = Clock(); clock.value = entry.start
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path / 'account', clock); before = state.ledger.path.read_bytes()
        runtime = StubRuntime(state, clock)
        runtime.admission = lambda: pytest.fail('missing envelope created a workload marker')
        runtime.pre_go = lambda *a: pytest.fail('missing envelope read account or wrote T-40 baseline')
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        if envelope=='mismatched':
            from datetime import timedelta
            coordinator.wrapper_launch={'deadline_utc':(entry.session_end(entry.end)+timedelta(minutes=30)).isoformat(),
                'policy_bytes_sha256':'0'*64}
        from weather.market import lfc_pilot
        from weather.market.lfc_campaign_visibility import notify_control
        actual=lfc_pilot.notify_owner; notices=[]
        def inert_notice(root,summary,**kwargs):
            notice=actual(root,summary,windows=False,printer=lambda *a,**kw:None,**kwargs)
            notices.append(notice);return notice
        monkeypatch.setattr(lfc_pilot,'notify_owner',inert_notice)
        runtime.control_root=tmp_path/'control'
        runtime.notify_control=lambda row:notify_control(runtime,row)
        assert coordinator.start(entry, policy, lambda: load_policy(path)) == 'DEFERRED'
        assert before == state.ledger.path.read_bytes() and not state.ledger.autostart_claims
        assert not state.incidents() and runtime.go_count == 0
        status=json.loads(sorted((tmp_path/'control').glob('*.json'))[-1].read_text())
        assert status['account_read'] is False and status['incident'] is None
        assert status['orders_open_unproven'] is None and status['attention_required'] is True
        assert len(notices)==1 and 'account not read' in notices[0]['result_line']
