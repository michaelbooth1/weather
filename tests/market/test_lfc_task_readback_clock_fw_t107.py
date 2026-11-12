"""Guards: T107 pre-intent readback waiting must retain the 15-second stall guard."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, policy_row
from tests.market.test_lfc_campaign_runtime import runtime_at, account_read
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_release import TaskReadbackUnavailable
from weather.market.lfc_campaign_runtime import ScheduledAuthority


def test_pre_intent_retry_wait_cannot_resync_away_a_real_stall(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, runtime.clock.now())
        runtime.lease = SimpleNamespace(check=lambda: None)
        prepared = {'baseline': {}, 'account_read': account_read(runtime),
                    'expires_utc': (runtime.clock.now() + timedelta(seconds=120)).isoformat()}
        authority = ScheduledAuthority(runtime, claim, policy.entries[0], policy, prepared)
        calls = []
        def read():
            calls.append(1)
            if len(calls) == 1:
                raise TaskReadbackUnavailable('timeout')
            return True
        runtime._read_task_enabled = read
        sleep = runtime.clock.sleep
        runtime.clock.sleep = lambda seconds: sleep(20 if seconds == 1 else seconds)
        with pytest.raises(RuntimeError, match='clock_or_resume_uncertain'):
            authority.check(starting=True)
        assert len(calls) == 1
        assert runtime.state.incidents()
