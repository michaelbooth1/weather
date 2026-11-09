"""Guards: retry/reopen, short/torn writes and the append-to-fsync crash gap."""
import os
from pathlib import Path
import pytest
from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_review_b069_retry import interrupted, coordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_campaign_control import latest_control, watch_status
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.lfc_campaign_persistence import ClosureRetryPending


@pytest.fixture(autouse=True)
def guarded():
    with account_lease(MAKER, backend=Mutexes()): yield


def reboot(runtime):
    runtime.state = AccountState(runtime.state.root.parent,
        Ledger.open(runtime.state.ledger.path, clock=runtime.clock.now))


def test_repeated_failed_appends_across_reboots_never_admit(tmp_path, monkeypatch):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ledger_path = runtime.state.ledger.path
    before = ledger_path.read_bytes()
    ordinary = Path.open
    def fail(p, mode='r', *a, **kw):
        if p == ledger_path and mode == 'ab': raise OSError('temporary_storage_outage')
        return ordinary(p, mode, *a, **kw)
    with monkeypatch.context() as failure:
        failure.setattr(Path, 'open', fail)
        for _ in range(3):
            reboot(runtime); runtime.clock.sleep(1)
            assert coordinator(runtime).tick(lambda: pytest.fail('new admission during retry')) == 'RETRY_PENDING'
            row = latest_control(runtime.control_root)
            assert row['phase'] == 'RETRY_PENDING' and row['incident'] is False
            assert watch_status(row, now=runtime.clock.now())[1] == 1
            assert ledger_path.read_bytes() == before and path.read_bytes() == original
            assert len(runtime.state.ledger.autostart_claims) == 1
    for _ in range(2):
        reboot(runtime); runtime.clock.sleep(1)
        assert coordinator(runtime).tick(lambda: policy) == 'IDLE'
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
        assert not runtime.state.ledger.autostart_incidents and path.read_bytes() == original


@pytest.mark.parametrize('sync_first', [False, True])
@pytest.mark.parametrize('after_crash', ['intact', 'delete', 'rollback_undurable_append'])
def test_append_fsync_gap_reopens_without_duplicate_or_hidden_anchored_loss(tmp_path, monkeypatch, sync_first, after_crash):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ledger_path = runtime.state.ledger.path
    before = ledger_path.read_bytes()
    ordinary_open, ordinary_sync = Path.open, os.fsync
    target, hits = [], []
    def opened(p, mode='r', *a, **kw):
        handle = ordinary_open(p, mode, *a, **kw)
        if p == ledger_path and mode == 'ab': target[:] = [handle.fileno()]
        return handle
    def sync(fd):
        if target == [fd] and not hits:
            if sync_first: ordinary_sync(fd)
            hits.append(True); raise OSError('simulated_fsync_crash')
        return ordinary_sync(fd)
    with monkeypatch.context() as failure:
        failure.setattr(Path, 'open', opened); failure.setattr(os, 'fsync', sync)
        assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
    assert hits and len(runtime.state.ledger.event_rows('autostart_close')) == 1
    if after_crash == 'delete': path.unlink()
    if after_crash == 'rollback_undurable_append':
        # Model loss of a whole trailing append on reboot; synthetic bytes only.
        ledger_path.write_bytes(before)
    reboot(runtime); runtime.clock.sleep(1)
    assert coordinator(runtime).tick(lambda: policy) == ('INCIDENT' if after_crash == 'delete' else 'IDLE')
    if after_crash == 'delete':
        assert not path.exists() and len(runtime.state.ledger.autostart_incidents) == 1
    else:
        assert path.read_bytes() == original and not runtime.state.ledger.autostart_incidents
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1


@pytest.mark.parametrize('raise_after_partial', [False, True])
def test_partial_anchor_cannot_be_replayed_or_used_for_a_new_claim(tmp_path, monkeypatch, raise_after_partial):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ledger_path = runtime.state.ledger.path
    ordinary = Path.open
    class Partial:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *a): self.stream.close()
        def write(self, raw):
            n = self.stream.write(raw[:len(raw)//2])
            self.stream.flush(); os.fsync(self.stream.fileno())
            if raise_after_partial: raise OSError('torn_append')
            return n
        def flush(self): return self.stream.flush()
        def fileno(self): return self.stream.fileno()
    def opened(p, mode='r', *a, **kw):
        handle = ordinary(p, mode, *a, **kw)
        return Partial(handle) if p == ledger_path and mode == 'ab' else handle
    with monkeypatch.context() as failure:
        failure.setattr(Path, 'open', opened)
        try: runtime.state.verify()
        except LedgerUnavailable as exc: assert not isinstance(exc, ClosureRetryPending)
    torn = ledger_path.read_bytes()
    with pytest.raises(LedgerUnavailable): reboot(runtime)
    assert ledger_path.read_bytes() == torn and path.read_bytes() == original
    assert len(runtime.state.ledger.autostart_claims) == 1
