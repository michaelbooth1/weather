"""Rate and deadline regression checks without large synthetic payloads."""
import time
import pytest
from weather.operations import production_cold_archive_stage as capture
from weather.operations import production_cold_archive_transfer_core as transfer
from weather.operations import workstation_cold_archive_io as workstation
from weather.operations import workstation_cold_archive_transfer as network
from weather.operations import workstation_cold_archive_cleanup as cleanup


def test_capture_still_rejects_workstation_rate():
    with pytest.raises(capture.ArchiveStageError, match="host profile"):
        capture._Guard(lambda: True, time.monotonic() + 30, 64 * capture.MIB)


def test_workstation_rate_accounts_all_bytes_and_checks_admission(monkeypatch):
    clock = [1.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    calls = []
    guard = workstation.ReadGuard(lambda: calls.append(True) or True, 20)
    guard.account(128 * capture.MIB)
    guard.admit()
    assert clock[0] == pytest.approx(3)
    assert len(calls) == 2
    with pytest.raises(capture.ArchiveStageError, match="admission"):
        workstation.ReadGuard(lambda: False, 20)


def test_largest_cleanup_and_network_phases_have_twenty_percent_margin():
    size = transfer.MAX_CIPHERTEXT_BYTES
    cleanup_seconds = 6 * size / workstation.READ_BYTES_PER_SECOND
    assert cleanup_seconds < cleanup.DEADLINE_SECONDS * 0.8
    budget = transfer.required_transfer_seconds(
        size, phase="upload_only", hash_rate_bytes_per_second=workstation.READ_BYTES_PER_SECOND,
        network_rate_bytes_per_second=workstation.NETWORK_BUDGET_BYTES_PER_SECOND)
    assert budget + 45 < network.DEADLINE_SECONDS * 0.8
    # The cloud cap remains 8 MiB/s; budgeting uses the slower measured baseline.
    assert budget > transfer.required_transfer_seconds(size, phase="upload_only")
