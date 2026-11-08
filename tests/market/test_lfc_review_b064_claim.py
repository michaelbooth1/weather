"""Guards: B064 no wrapper or byte-only ABA edit cannot consume a date."""
from datetime import timedelta
import hashlib
import json

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at, StubRuntime
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_launch import require_launch
from weather.market.lfc_campaign_policy import load_policy
from weather.market.lfc_f2_breadth import example_policy


@pytest.mark.parametrize('race', ['missing_envelope', 'byte_only_aba'])
def test_tick_start_snapshot_is_bound_before_claim_even_after_byte_only_aba(tmp_path, race):
    row = example_policy(); row['enabled'] = True
    path = tmp_path / 'policy.json'; path.write_text(json.dumps(row))
    original = path.read_bytes()
    policy_a = load_policy(path)
    entry = next(e for e in policy_a.entries if e.local_date == '2026-11-11')
    packet = {'deadline_utc': (entry.session_end(entry.end) + timedelta(minutes=30)).isoformat(),
              'policy_bytes_sha256': hashlib.sha256(original).hexdigest()}
    if race == 'byte_only_aba':
        path.write_bytes(original + b'\n')
        tick_start = load_policy(path)
        path.write_bytes(original)
        assert tick_start.sha256 == policy_a.sha256 and tick_start.source_sha256 != policy_a.source_sha256
    else:
        tick_start, packet = policy_a, None
    clock = Clock(); clock.value = entry.start
    class RuntimeLike(StubRuntime):
        def run_session(self, claim, entry, policy, prepared):
            require_launch(packet, policy, entry)
            return super().run_session(claim, entry, policy, prepared)
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path / 'account', clock)
        runtime = RuntimeLike(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock,
            control_root=tmp_path / 'control', wrapper_launch=packet)
        assert coordinator.start(entry, tick_start, lambda: load_policy(path)) == 'DEFERRED'
        assert runtime.go_count == 0 and not state.ledger.autostart_claims
        assert not state.incidents() and not state.consumed_dates()
