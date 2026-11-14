"""Guards: B064 early ticks retain a complete, bounded admission opportunity.

All policy, state and file timings are synthetic; no operational files or APIs.
"""
from datetime import timedelta
import hashlib
import json
import statistics
import time
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at, StubRuntime, policy_row
from tests.market.test_lfc_review_t044_recheck1 import wrapper_deadline
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import load_policy, parse_policy
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_f2_policy import example_policy as two_band_policy


@pytest.mark.spawns
def test_slow_pre_entry_tick_crosses_begin_and_claims_once_per_tick(tmp_path, monkeypatch):
    row = example_policy(); row.update(enabled=True)
    entry = next(e for e in parse_policy(row).entries if e.local_date == '2026-11-11')
    began = entry.start - timedelta(minutes=5)
    deadline = wrapper_deadline(tmp_path, row, began)
    path = tmp_path / 'synthetic-policy.json'
    launch = {'deadline_utc': deadline.isoformat(), 'policy_bytes_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    clock = Clock(); clock.value = began
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path / 'account', clock)
        runtime = StubRuntime(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock,
            control_root=tmp_path / 'control', wrapper_launch=launch)
        original = state.verify; first = [True]
        def slow(*args, **kwargs):
            if first[0]: first[0] = False; clock.sleep(650)
            return original(*args, **kwargs)
        monkeypatch.setattr(state, 'verify', slow)
        assert coordinator.tick(lambda: load_policy(path)) == 'STARTED'
        assert runtime.go_count == 1 and len(state.ledger.autostart_claims) == 1
        assert not state.incidents()
        assert coordinator.tick(lambda: load_policy(path)) == 'STARTED'
        assert runtime.go_count == 2 and len(state.ledger.autostart_claims) == 2
        clock.sleep((entry.end - clock.now()).total_seconds() + 1)
        assert coordinator.tick(lambda: load_policy(path)) == 'IDLE'
        assert runtime.go_count == 2 and not state.pending() and not state.incidents()


@pytest.mark.spawns
@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('window_minutes', [10, 15, 30, 60])
def test_all_wrapper_schemas_cover_only_the_calculated_pre_entry_lookback(tmp_path, version, window_minutes):
    row = policy_row() if version == 1 else (two_band_policy() if version == 2 else example_policy())
    if version != 1:
        row['schema_version'] = 'lfc_campaign_policy_v0.' + str(version)
        row['start_window_toronto'] = ['09:00:00', f'{9 + window_minutes // 60:02d}:{window_minutes % 60:02d}:00']
    else:
        row['entries'][0].update(window_end_utc=(parse_policy(row).entries[0].start + timedelta(minutes=window_minutes)).isoformat().replace('+00:00', 'Z'))
    entry = next(e for e in parse_policy(row).entries if e.local_date == '2026-11-11')
    lookback = timedelta(minutes=max(5, 30 - window_minutes))
    earliest = entry.start - lookback
    expected = entry.session_end(entry.end) + timedelta(minutes=30)
    assert wrapper_deadline(tmp_path, row, earliest) == expected
    outside = earliest - timedelta(microseconds=1)
    assert wrapper_deadline(tmp_path, row, outside) == outside + timedelta(minutes=30)
    assert wrapper_deadline(tmp_path, row, entry.end) == entry.end + timedelta(minutes=30)


@pytest.mark.spawns
@pytest.mark.parametrize('version', [1, 2, 3])
def test_midnight_window_lookback_is_bound_to_the_upcoming_entry_date(tmp_path, version):
    row = policy_row() if version == 1 else (two_band_policy() if version == 2 else example_policy())
    if version == 1:
        row['entries'][0].update(window_start_utc='2026-11-11T05:00:00Z', window_end_utc='2026-11-11T05:15:00Z')
    else:
        row.update(start_window_toronto=['00:00:00', '00:15:00'], trading_end_toronto='06:00:00')
    entry = next(e for e in parse_policy(row).entries if e.local_date == '2026-11-11')
    began = entry.start - timedelta(minutes=5)
    assert wrapper_deadline(tmp_path, row, began) == entry.session_end(entry.end) + timedelta(minutes=30)


@pytest.mark.spawns
def test_legacy_midnight_fixed_end_uses_the_entry_date_not_the_launch_date(tmp_path):
    row = policy_row(); row['trading_end_toronto'] = '06:30:00'
    row['entries'][0].update(window_start_utc='2026-11-11T05:00:00Z', window_end_utc='2026-11-11T05:15:00Z')
    entry = parse_policy(row).entries[0]
    assert wrapper_deadline(tmp_path, row, entry.start-timedelta(minutes=5)) == entry.session_end(entry.end)+timedelta(minutes=30)


@pytest.mark.parametrize('history_days', [1, 40])
def test_healthy_near_entry_followup_cost_is_independent_of_retained_history(history_days):
    from weather.market.lfc_f2_followup import maintenance
    policy = parse_policy(example_policy())
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    class NoHistoryAccess:
        def __getattr__(self, name):
            raise AssertionError('near-entry maintenance inspected retained history')
    runtime = SimpleNamespace(clock=SimpleNamespace(now=lambda: entry.start-timedelta(minutes=5)),
        state=NoHistoryAccess(), synthetic_history_days=history_days)
    assert maintenance(runtime, policy) is None


def test_streamed_retained_hash_cost_sample(tmp_path, record_property):
    from weather.market.lfc_retained_cache import RetainedCache
    path = tmp_path / 'synthetic-retained-sample.bin'
    block = b'bounded synthetic evidence\n' * 2048
    expected = hashlib.sha256()
    with path.open('xb') as stream:
        for _ in range(160): stream.write(block); expected.update(block)
    times = []
    for _ in range(3):
        began = time.perf_counter()
        assert RetainedCache().sha(path) == expected.hexdigest()
        times.append(time.perf_counter() - began)
    record_property('retained_sample_bytes', path.stat().st_size)
    record_property('retained_hash_median_seconds', statistics.median(times))
    record_property('retained_hash_samples_seconds', json.dumps(times))


def test_state_snapshot_read_validate_cost_sample(tmp_path, record_property):
    from weather.market.lfc_retained_cache import RetainedCache
    from weather.market.mm_stage2_hold import digest
    path = tmp_path / 'synthetic-account-snapshot.json'
    row = {'id': 'fixture-only', 'asset_id': '123', 'size': '20', 'price': '.48',
           'timestamp': '2026-11-11T14:00:00+00:00', 'status': 'MATCHED', 'padding': 'x' * 128}
    # One repeated shape, streamed construction; parsing/digest work remains real.
    with path.open('x', encoding='utf-8') as stream:
        stream.write('{"trades":[')
        for n in range(4096):
            if n: stream.write(',')
            json.dump({**row, 'id': str(n)}, stream)
        stream.write(']}')
    times = []
    for _ in range(3):
        began = time.perf_counter()
        value = RetainedCache().json(path)
        assert len(value['trades']) == 4096 and len(digest(value)) == 64
        times.append(time.perf_counter() - began)
    record_property('snapshot_sample_bytes', path.stat().st_size)
    record_property('snapshot_read_validate_median_seconds', statistics.median(times))
