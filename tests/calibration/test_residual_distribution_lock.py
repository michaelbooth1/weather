from __future__ import annotations

import json

import pytest

from weather.calibration.residual_distribution_lock import (
    PreselectionLockError,
    append_preselection_lock,
    build_preselection_lock,
    find_matching_preselection_lock,
    read_preselection_lock_ledger,
    verify_preselection_lock,
)


def _lock(**overrides):
    values = {
        "candidate_id": "residual_distribution_v1-run-1",
        "corpus_sha256": "a" * 64,
        "corpus_manifest_sha256": "b" * 64,
        "locked_dates": [f"2026-06-{day:02d}" for day in range(1, 15)],
        "expected_market_ids": ["atlanta", "toronto"],
        "expected_cutoff_hours": [8, 12],
        "created_at_utc": "2026-05-01T00:00:00+00:00",
    }
    values.update(overrides)
    return build_preselection_lock(**values)


def test_lock_is_self_hashed_and_requires_fourteen_date_windows():
    lock = _lock()
    assert verify_preselection_lock(lock)["lock_sha256"] == lock["lock_sha256"]
    assert lock["minimum_outer_dates"] == 14
    assert lock["minimum_locked_dates"] == 14
    with pytest.raises(PreselectionLockError, match="at least 14"):
        _lock(minimum_locked_dates=7)


def test_lock_ledger_is_append_only_and_candidate_unique(tmp_path):
    ledger = tmp_path / "locks.jsonl"
    lock = _lock()
    append_preselection_lock(ledger, lock)
    before = ledger.read_bytes()
    assert read_preselection_lock_ledger(ledger) == [lock]
    with pytest.raises(PreselectionLockError, match="already registered"):
        append_preselection_lock(ledger, lock)
    assert ledger.read_bytes() == before


def test_tampered_or_post_evaluation_lock_is_rejected(tmp_path):
    lock = _lock()
    tampered = {**lock, "expected_market_ids": ["atlanta"]}
    with pytest.raises(PreselectionLockError, match="self-hash"):
        verify_preselection_lock(tampered)

    assert find_matching_preselection_lock(
        [lock],
        candidate_id=lock["candidate_id"],
        corpus_sha256=lock["corpus_sha256"],
        locked_dates=lock["locked_dates"],
        evaluation_generated_at_utc="2026-05-02T00:00:00+00:00",
    ) == lock
    with pytest.raises(PreselectionLockError, match="not recorded before"):
        find_matching_preselection_lock(
            [lock],
            candidate_id=lock["candidate_id"],
            corpus_sha256=lock["corpus_sha256"],
            locked_dates=lock["locked_dates"],
            evaluation_generated_at_utc="2026-04-30T00:00:00+00:00",
        )


def test_malformed_existing_ledger_blocks_append(tmp_path):
    ledger = tmp_path / "locks.jsonl"
    ledger.write_text(json.dumps({"schema_version": "wrong"}) + "\n", encoding="utf-8")
    with pytest.raises(PreselectionLockError, match="unsupported"):
        append_preselection_lock(ledger, _lock())
