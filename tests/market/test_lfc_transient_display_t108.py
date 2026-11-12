"""Guards: T108 dispatch cannot replace a post-claim INCIDENT with DEFERRED."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, StubRuntime, policy_row, state_at
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_control import latest_control, watch_status


@pytest.mark.parametrize('stage', ['preclaim', 'claimed_ack', 'claimed_unknown'])
def test_transient_display_preserves_the_actual_claim_boundary(tmp_path, monkeypatch, capsys, stage):
    from weather.market import lfc_campaign_cli as cli, lfc_campaign_runtime as adapter, lfc_campaign_visibility
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        runtime = StubRuntime(state, clock)
        raw = json.dumps(policy_row()).encode()
        policy = replace(parse_policy(policy_row()), source_sha256=hashlib.sha256(raw).hexdigest())
        entry = policy.entries[0]
        def pre_go(*args):
            if stage == 'preclaim':
                # End this window after the transport failure so a later retry
                # cannot obscure the pre-claim DEFERRED observation.
                clock.value = entry.end
                raise TransientPrecheck('capital_cash_snapshot_pending')
            return {'fixture': True}
        runtime.pre_go = pre_go
        def failed_after_placement(claim, *args):
            ledger = state.ledger
            ledger.record('session_start', session_id='placed', autostart_attempt_id=claim['attempt_id'])
            ledger.intent(session_id='placed', intent_key='placed:1', token_id='t', condition_id='c',
                          size='20', price='.5', fee_rate_bps='0')
            if stage == 'claimed_ack':
                ledger.ack('placed:1', 'ours')
            clock.sleep(1)
            raise TransientPrecheck('capital_cash_snapshot_pending')
        runtime.run_session = failed_after_placement
        control = tmp_path / 'control'
        class DispatchTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.now() + timedelta(seconds=1)
        monkeypatch.setattr(cli, 'CONTROL_ROOT', control)
        monkeypatch.setattr(cli, 'datetime', DispatchTime)
        monkeypatch.setattr(cli, 'load_release', lambda *args: {'maker_address': MAKER, 'campaign_path': 'synthetic'})
        monkeypatch.setattr(cli, 'validate_release', lambda *args: None)
        monkeypatch.setattr(cli, 'bound_state', lambda *args, **kwargs: (state.ledger.path.parent, state))
        monkeypatch.setattr(cli, 'account_lease', lambda *args: nullcontext())
        monkeypatch.setattr(cli, 'load_policy', lambda *args: policy)
        monkeypatch.setattr(adapter, 'CampaignClock', lambda: clock)
        monkeypatch.setattr(adapter, 'Runtime', lambda **kwargs: runtime)
        monkeypatch.setattr(lfc_campaign_visibility, 'notify_control', lambda *args: None)
        code = cli.dispatch(['tick', '--release', 'synthetic', '--release-sha256', 'a' * 64,
            '--wrapper-deadline-utc', (entry.session_end(entry.end) + timedelta(minutes=30)).isoformat(),
            '--wrapper-policy-sha256', policy.source_sha256])
        row = latest_control(control)
        if stage == 'preclaim':
            assert not state.ledger.autostart_claims
            assert code == 0 and row['phase'] in {'MISSED', 'DEFERRED'}
            phases = {json.loads(path.read_text())['phase'] for path in control.glob('*.json')}
            assert 'DEFERRED' in phases and 'INCIDENT' not in phases
        else:
            assert code == 1
            assert len(state.ledger.autostart_claims) == 1
            assert row['phase'] == 'INCIDENT' and row['incident'] is True and row['postchecks_pending'] is True
            public, exit_code = watch_status(row, now=DispatchTime.now())
            assert exit_code == 1 and public['watch_state'] == 'attention' and public['phase'] == 'INCIDENT'
            assert json.loads(capsys.readouterr().out)['state'] == 'INCIDENT'
            assert bool(state.incidents()) is (stage == 'claimed_unknown')
