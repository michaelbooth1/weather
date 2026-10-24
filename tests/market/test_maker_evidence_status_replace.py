"""status.json replace retry: a reader holding the file delays the write but never kills the recorder.

Guards: 88a passive maker-evidence recorder liveness (S2+S9 dry-run PermissionError in atomic_json, 2026-10-15)
"""
import json
import sys
import threading

import pytest

from weather.market import maker_evidence_store as store_module
from weather.market.maker_evidence_store import (
    REPLACE_ATTEMPTS, REPLACE_BUDGET_SECONDS, EvidenceStore, atomic_json, replace_with_retry, write_status,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="open files block os.replace only on Windows")


def flaky_replace(monkeypatch, failures):
    calls = []
    real = store_module.os.replace

    def replace(source, target):
        calls.append(target)
        if len(calls) <= failures:
            raise PermissionError(13, "Access is denied")
        real(source, target)

    monkeypatch.setattr(store_module.os, "replace", replace)
    return calls


def test_retry_rides_out_transient_permission_errors_within_budget(tmp_path, monkeypatch):
    calls = flaky_replace(monkeypatch, failures=REPLACE_ATTEMPTS - 1)
    slept = []
    source, target = tmp_path / "a.tmp", tmp_path / "a.json"
    source.write_text("x")

    assert replace_with_retry(source, target, sleep=slept.append) == REPLACE_ATTEMPTS
    assert len(calls) == REPLACE_ATTEMPTS and target.read_text() == "x"
    assert len(slept) == REPLACE_ATTEMPTS - 1 and sum(slept) <= REPLACE_BUDGET_SECONDS


def test_retry_exhaustion_reraises_after_bounded_attempts(tmp_path, monkeypatch):
    calls = flaky_replace(monkeypatch, failures=10 ** 6)
    source = tmp_path / "a.tmp"
    source.write_text("x")

    with pytest.raises(PermissionError):
        replace_with_retry(source, tmp_path / "a.json", sleep=lambda _: None)
    assert len(calls) == REPLACE_ATTEMPTS


def test_other_errors_are_not_retried(tmp_path, monkeypatch):
    calls = []

    def replace(source, target):
        calls.append(target)
        raise FileNotFoundError(source)

    monkeypatch.setattr(store_module.os, "replace", replace)
    with pytest.raises(FileNotFoundError):
        replace_with_retry(tmp_path / "missing.tmp", tmp_path / "a.json", sleep=lambda _: None)
    assert len(calls) == 1


def test_manifest_seal_still_raises_when_replace_is_exhausted(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path / "root")
    store.event("probe", {"n": 1})
    flaky_replace(monkeypatch, failures=10 ** 6)
    monkeypatch.setattr(store_module.time, "sleep", lambda _: None)

    with pytest.raises(PermissionError):
        store.seal()


@windows_only
def test_held_reader_released_mid_retry_lets_status_write_land(tmp_path):
    path = tmp_path / "status.json"
    atomic_json(path, {"cycles": 0})
    reader = path.open("rb")
    release = threading.Timer(0.3, reader.close)
    release.start()
    try:
        atomic_json(path, {"cycles": 1})
    finally:
        release.cancel()
        reader.close()
    assert json.loads(path.read_text()) == {"cycles": 1}


@windows_only
def test_reader_held_past_budget_journals_warn_and_keeps_running(tmp_path):
    store = EvidenceStore(tmp_path / "root")
    path = tmp_path / "status.json"
    atomic_json(path, {"cycles": 0})
    state = {"cycles": 1}
    with path.open("rb"):
        assert write_status(store, path, state, budget_seconds=0.2) is False
    assert state["status_write_misses"] == 1
    assert json.loads(path.read_text()) == {"cycles": 0}
    # Reader gone: the next cycle's write lands and carries the miss count.
    assert write_status(store, path, state) is True
    assert json.loads(path.read_text())["status_write_misses"] == 1
    store.seal()
    journals = list((tmp_path / "root").rglob("*.jsonl")) + list((tmp_path / "root").rglob("*.jsonl.gz"))
    text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in journals if p.suffix == ".jsonl")
    assert "status_write_failed" in text and "WARN" in text
