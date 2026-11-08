"""Guards: RECHECK2 latest-go deadline envelope and non-destructive state bounds."""
from datetime import timedelta
import json
import hashlib

import pytest

from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import example_policy
from tests.market.test_lfc_review_t044_recheck1 import wrapper_deadline


@pytest.mark.parametrize('seconds,finish,fixed', [(300, '09:15:00', '15:00:00'),
    (3600, '11:00:00', '15:00:00'), (21600, '09:15:00', '15:00:00'),
    (21600, '11:00:00', '15:00:00')])
@pytest.mark.spawns
def test_latest_half_open_go_never_outlives_wrapper_minus_cleanup(tmp_path, seconds, finish, fixed):
    row = example_policy()
    row.update(enabled=True, start_window_toronto=['09:00:00', finish],
               trading_end_toronto=fixed, max_session_seconds=seconds)
    policy = parse_policy(row)
    for day in ('2026-11-11', '2026-12-22'):
        entry = next(e for e in policy.entries if e.local_date == day)
        latest = entry.end - timedelta(microseconds=1)
        assert entry.permits(latest) and not entry.permits(entry.end)
        for wrapper_start in (entry.start, latest):
            deadline = wrapper_deadline(tmp_path, row, wrapper_start)
            for go in (wrapper_start, latest):
                assert entry.session_end(go) <= deadline - timedelta(minutes=30)
            assert deadline <= entry.fixed_end + timedelta(minutes=30)


@pytest.mark.parametrize('change', [{'schema_version': 'unknown'}, {'max_session_seconds': 299},
    {'max_session_seconds': 21601}, {'start_window_toronto': ['bad', '09:15:00']},
    {'trading_end_toronto': '09:00:00'}])
@pytest.mark.spawns
def test_invalid_timing_fields_keep_short_refused_deadline(tmp_path, change):
    row = example_policy()
    entry = parse_policy(row).entries[0]
    assert wrapper_deadline(tmp_path, {**row, **change}, entry.start) == entry.start + timedelta(minutes=30)


@pytest.mark.spawns
def test_edit_between_wrapper_read_and_child_policy_load_cannot_shorten_live_budget(tmp_path):
    from weather.market.lfc_campaign_policy import load_policy
    row = example_policy()
    row.update(enabled=True, max_session_seconds=300)
    first = parse_policy(row)
    entry = next(e for e in first.entries if e.local_date == '2026-11-11')
    begin = entry.start
    deadline = wrapper_deadline(tmp_path, row, begin)
    wrapper_sha = hashlib.sha256((tmp_path/'synthetic-policy.json').read_bytes()).hexdigest()
    # The task receives only the release hash and policy pathname. The owner-
    # editable policy is loaded again by the child, after interpreter startup
    # and release/state validation. Both versions below are accepted policies.
    changed = {**row, 'max_session_seconds': 21600, 'revision': row['revision'] + 1,
               'policy_revision': row['policy_revision'] + 1}
    path = tmp_path / 'synthetic-policy.json'
    path.write_text(json.dumps(changed))
    child_policy = load_policy(path)
    assert child_policy.sha256 != first.sha256
    child_entry = next(e for e in child_policy.entries if e.local_date == entry.local_date)
    child_start = begin + timedelta(seconds=1)
    assert child_entry.permits(child_start)
    # The changed model still permits the mathematical end. The operational
    # child must refuse this unadmitted policy before it acquires a date/POST.
    from weather.market.lfc_campaign_launch import require_launch, LaunchDeferred
    with pytest.raises(LaunchDeferred, match='wrapper_policy_changed'):
        require_launch({'deadline_utc':deadline.isoformat(), 'policy_bytes_sha256':wrapper_sha}, child_policy, child_entry)


def test_oversized_state_refusal_preserves_all_preexisting_bytes(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market import lfc_campaign_state as module
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, Clock())
        state.save('followups/original.json', {'last_observation': 'keep'})
        path = state.root / 'followups/original.json'
        original = path.read_bytes()
        history = state.ledger.path.read_bytes()
        monkeypatch.setattr(module, 'STATE_JSON_LIMIT', 512)
        for name in ('followups/original.json', 'followups/new.json'):
            with pytest.raises(ValueError, match='recording_file_budget'):
                state.save(name, {'unaccepted_new_evidence': 'x' * 1024})
        assert path.read_bytes() == original and state.ledger.path.read_bytes() == history
        assert not (state.root / 'followups/new.json').exists()
        assert not list(path.parent.glob('.*.attempt-*'))


def test_large_evidence_remains_available_after_cache_eviction_and_detects_change(tmp_path):
    from weather.market.lfc_retained_cache import RetainedCache
    from weather.market.lfc_recording_io import write_new, STATE_JSON_LIMIT
    path = tmp_path / 'retained-large.json'
    write_new(path, {'needed_for_recovery': 'x' * 4_000_000, 'final_report_marker': 391}, max_bytes=STATE_JSON_LIMIT)
    cache = RetainedCache()
    first = cache.json(path)
    assert first['final_report_marker'] == 391 and len(first['needed_for_recovery']) == 4_000_000
    assert cache.bytes == 0
    # Eviction affects memory only, not files or the next complete read.
    assert cache.json(path) == first and path.exists()
    data = path.read_bytes()
    changed = data.replace(b'391', b'392', 1)
    assert len(changed) == len(data) and changed != data
    path.write_bytes(changed)
    assert cache.json(path)['final_report_marker'] == 392
