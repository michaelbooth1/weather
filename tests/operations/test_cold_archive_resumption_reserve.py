"""The September 14 archive reserve cannot escape its approved inputs or window."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from weather.operations import production_cold_archive_stage_cli as subject


@pytest.fixture
def pinned_plan(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    selection = "1" * 64
    path.write_text(json.dumps({"selection_sha256": selection}), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, "RESUMPTION_PLAN_SHA256", {digest: selection})
    return path, digest


@pytest.mark.parametrize("checked,expected", [
    ("2026-09-13T04:30:00+00:00", 50),
    ("2026-09-14T04:29:59+00:00", 50),
    ("2026-09-14T04:30:00+00:00", 20),
    ("2026-09-14T07:00:00+00:00", 20),
    ("2026-09-14T08:36:45+00:00", 20),
    ("2026-09-14T08:42:00+00:00", 50),
    ("2026-09-15T04:30:00+00:00", 50),
])
def test_reserve_is_limited_to_approved_date_and_hours(pinned_plan, checked, expected):
    now = datetime.fromisoformat(checked)
    _, reserve = subject.load_plan_with_reserve(
        *pinned_plan, now=now, deadline=now + timedelta(seconds=300))
    assert reserve == expected * subject.GIB


@pytest.mark.parametrize("deadline", [None, "2026-09-14T07:00:00+00:00",
                                       "2026-09-14T08:41:45.000001+00:00",
                                       "2026-09-14T08:42:00+00:00"])
def test_reserve_requires_independent_teardown_deadline(pinned_plan, deadline):
    now = datetime(2026, 9, 14, 7, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(deadline) if deadline else None
    with pytest.raises(ValueError, match="preserves teardown"):
        subject.load_plan_with_reserve(*pinned_plan, now=now, deadline=parsed)


def test_last_safe_deadline_still_preserves_fifteen_seconds(pinned_plan):
    now = subject.RESUMPTION_END - timedelta(seconds=16)
    assert subject.load_plan_with_reserve(
        *pinned_plan, now=now, deadline=subject.RESUMPTION_END - timedelta(seconds=15)
    )[1] == 20 * subject.GIB


def test_claimed_plan_digest_cannot_substitute_changed_bytes(pinned_plan):
    path, digest = pinned_plan
    now = subject.RESUMPTION_START
    kwargs = dict(now=now, deadline=now + timedelta(seconds=300))
    path.write_text(json.dumps({"selection_sha256": "2" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        subject.load_plan_with_reserve(path, digest, **kwargs)
    changed = hashlib.sha256(path.read_bytes()).hexdigest()
    assert subject.load_plan_with_reserve(path, changed, **kwargs)[1] == 50 * subject.GIB


def test_exact_plan_still_requires_its_exact_selection(pinned_plan, monkeypatch):
    path, digest = pinned_plan
    monkeypatch.setattr(subject, "RESUMPTION_PLAN_SHA256", {digest: "2" * 64})
    now = subject.RESUMPTION_START
    assert subject.load_plan_with_reserve(
        path, digest, now=now, deadline=now + timedelta(seconds=300)
    )[1] == 50 * subject.GIB


def test_renewal_does_not_revive_expired_daytime_authority(pinned_plan):
    now = subject.RESUMPTION_START
    with pytest.raises(ValueError, match="daytime archive authority"):
        subject.load_plan_with_reserve(
            *pinned_plan, now=now, deadline=now + timedelta(seconds=300),
            owner_approved_exception=subject.ARCHIVE_DAYTIME_EXCEPTION)


def test_renewal_preserves_evidence_and_output_space(pinned_plan):
    now = subject.RESUMPTION_START
    reserve = subject.load_plan_with_reserve(
        *pinned_plan, now=now, deadline=now + timedelta(seconds=300))[1]
    assert subject.staging_reserve({"logical_bytes": subject.GIB}, reserve) == (
        20 * subject.GIB + subject.EVIDENCE_RESERVE_BYTES)
    # The archive writer independently reserves its complete worst-case output.
    assert subject.SOURCE_RESERVE_BYTES == 50 * subject.GIB
