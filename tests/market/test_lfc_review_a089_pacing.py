"""Guards: paced control proof must expire before the next real POST hook."""

import importlib.util

import json

from pathlib import Path

import subprocess

from datetime import timedelta

from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes

from tests.market.test_lfc_campaign_runtime import runtime_at

from weather.market.lfc_campaign_guard import account_lease

from weather.market.lfc_campaign_release import TaskReadbackUnavailable

from weather.market.mm_stage2_hold import HoldEnd

@pytest.fixture(autouse=True)
def owned_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield

def test_failed_probe_crossing_expiry_cannot_reach_post(tmp_path, monkeypatch):
    from tests.market.test_lfc_f2_controller import setup
    from tests.market.test_lfc_task_readback_b089 import wire_runtime
    from weather.market.lfc_pilot import PilotSession
    controller, account, status, ledger, clock = setup(tmp_path, k=1, enrolled=True)
    runtime, authority = wire_runtime(controller, account, status, ledger, clock, tmp_path)
    original_sleep = clock.sleep
    def elapsed_with_independent_heartbeat(seconds):
        # Model the production heartbeat thread while the main thread is in a
        # bounded read. Do not update main-loop progress or authority clocks.
        remaining = seconds
        while remaining > 0:
            step = min(1, remaining)
            original_sleep(step)
            remaining -= step
            loop = controller.bands[0].heartbeat_loop
            if loop is not None:
                loop.step()
    monkeypatch.setattr(clock, 'sleep', elapsed_with_independent_heartbeat)
    reads = []
    def read():
        reads.append(clock.monotonic())
        if len(reads) > 1:
            clock.sleep(5)
            raise TaskReadbackUnavailable('timeout')
        return True
    runtime._read_task_enabled = read
    original = PilotSession.before_post
    def delayed_last_check(band, request):
        if band.posts == 1:
            # Normal progress checkpoints continue through 105 s. The last
            # signing/setup interval is 14 s, within the unchanged gap guard.
            while clock.monotonic() < 105:
                clock.sleep(min(10, 105 - clock.monotonic()))
                band.control()
            clock.sleep(14)
        return original(band, request)
    monkeypatch.setattr(PilotSession, 'before_post', delayed_last_check)
    posted = []
    raw = account.raws[0]
    original_submit = raw.submit
    def capture_post(request, **kwargs):
        result = original_submit(request, **kwargs)
        posted.append({'at': clock.monotonic(), 'order_id': result['order_id']})
        return result
    monkeypatch.setattr(raw, 'submit', capture_post)
    result = controller.run()
    observation = {'reads': reads, 'posts': posted, 'result': result,
        'failure_since': runtime._task_failure_since, 'incidents': runtime.state.incidents()}
    (tmp_path / 'observation.json').write_text(json.dumps(observation, default=str))
    assert reads == [0, 60, 85, 119], observation
    assert not runtime.state.incidents(), observation
    assert result['reason'] == 'campaign_task_readback_unavailable', observation
    assert all(row['at'] < 120 for row in posted), observation

@pytest.mark.parametrize('slow', ['lease', 'verify'])
def test_setup_wait_cannot_resync_away_a_validation_stall(tmp_path, monkeypatch, slow):
    from tests.market.test_lfc_campaign import policy_row
    from tests.market.test_lfc_campaign_runtime import account_read
    from weather.market.lfc_campaign_policy import parse_policy
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    runtime = runtime_at(tmp_path)
    policy = parse_policy(policy_row())
    entry = policy.entries[0]
    claim = runtime.state.claim(entry, policy, runtime.clock.now())
    prepared = {'baseline': {}, 'account_read': account_read(runtime),
                'expires_utc': (runtime.clock.now() + timedelta(seconds=120)).isoformat()}
    runtime.lease = SimpleNamespace(check=lambda: None)
    authority = ScheduledAuthority(runtime, claim, entry, policy, prepared)
    calls = []
    def read():
        calls.append(runtime.clock.monotonic())
        if len(calls) == 1:
            raise TaskReadbackUnavailable('timeout')
        return True
    runtime._read_task_enabled = read
    owner = runtime.lease if slow == 'lease' else runtime.state
    name = 'check' if slow == 'lease' else 'verify'
    original = getattr(owner, name)
    delayed = []
    def validation(*args, **kwargs):
        if runtime._task_failures and not delayed:
            delayed.append(runtime.clock.monotonic())
            runtime.clock.sleep(16)  # Exceeds 15 s, stays below the 20 s watchdog.
        return original(*args, **kwargs)
    monkeypatch.setattr(owner, name, validation)
    fault = None
    try:
        authority.check(starting=True)
    except RuntimeError as exc:
        fault = str(exc)
    observation = {'slow': slow, 'reads': calls, 'delayed': delayed, 'raised': fault,
                   'incidents': runtime.state.incidents(), 'ended': runtime.clock.monotonic()}
    (tmp_path / 'observation.json').write_text(json.dumps(observation, default=str))
    assert fault == 'clock_or_resume_uncertain', observation
    assert runtime.state.incidents(), observation
