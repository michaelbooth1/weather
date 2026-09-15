"""The temporary reserve cannot widen selection, host, output, or time authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from weather.operations import production_cold_archive_stage_cli as stage

PLAN = "bc30c32fc0403fd3f836501cbbe454aa791e025a29ef796b5ee8737f09043027"
SELECTION = "ce4d38697e1d24e7ba66a53cb41f407f074bfdd58fcf7118b926d9cd2b31f214"
APPROVAL = "2eb7309a03b9b5383f1bd848a43b9a268f6ffd390c236b3a27361f58d445cef5"
NOW = datetime(2026, 9, 16, 5, tzinfo=timezone.utc)

@pytest.fixture
def reserve(monkeypatch, tmp_path):
    record = {
        "schema": "capacity_disk_exception_v1",
        "owner_approval": {"path": str(tmp_path / "approval.json"), "sha256": APPROVAL},
        "source_git_sha": "a" * 40, "execution_host_id": "b" * 64,
        "production_root": str(tmp_path), "plan_sha256": PLAN,
        "selection_sha256": SELECTION, "expires_at_utc": "2026-09-16T13:00:00Z",
        "hard_reserve_bytes": 25 * stage.GIB, "output_cap_bytes": 2 * stage.GIB,
        "capture_bytes_per_second": 1024**2,
    }
    owner = {"post_denial_approval": True, "archive_selection_sha256": SELECTION}
    def pinned(path, maximum, digest):
        if path.name == "approval.json":
            assert digest == APPROVAL
            return owner, b""
        assert digest == "c" * 64
        return record, b""
    monkeypatch.setattr(stage, "_read_pinned_json", pinned)
    monkeypatch.setattr(stage.shutil, "disk_usage", lambda _: SimpleNamespace(free=37*stage.GIB))
    for key, suffix in (("source_git_sha", "SOURCE_SHA"), ("execution_host_id", "EXECUTION_HOST_ID"),
                        ("production_root", "PRODUCTION_ROOT")):
        monkeypatch.setenv(stage.ENV_PREFIX + suffix, record[key])
    def evaluate(now=NOW, deadline=None, plan_digest=PLAN, selection=SELECTION):
        return stage.capacity_recovery_reserve(
            tmp_path / "exception.json", "c"*64, {"selection_sha256": selection},
            plan_digest, now, deadline or now+timedelta(seconds=295))
    return record, owner, evaluate

def test_exact_exception_reserves_capped_output_and_growth(reserve):
    _, _, evaluate = reserve
    assert evaluate() == 27*stage.GIB + 300*1024**2

def test_ordinary_floor_returns_once_full_reservation_fits(reserve, monkeypatch):
    _, _, evaluate = reserve
    monkeypatch.setattr(stage.shutil, "disk_usage", lambda _: SimpleNamespace(free=53*stage.GIB))
    assert evaluate() == stage.SOURCE_RESERVE_BYTES

@pytest.mark.parametrize("field,value", [
    ("source_git_sha", "d"*40), ("execution_host_id", "d"*64),
    ("production_root", "C:/wrong"), ("plan_sha256", "d"*64),
    ("selection_sha256", "d"*64), ("hard_reserve_bytes", 24*stage.GIB),
    ("output_cap_bytes", 3*stage.GIB), ("capture_bytes_per_second", 0),
    ("expires_at_utc", "2026-09-17T13:00:00Z"), ("schema", "unknown"),
])
def test_changed_binding_or_limit_fails_closed(reserve, field, value):
    record, _, evaluate = reserve
    record[field] = value
    with pytest.raises(ValueError):
        evaluate()

@pytest.mark.parametrize("now,seconds", [
    (datetime(2026,9,16,4,29,tzinfo=timezone.utc), 295),
    (datetime(2026,9,16,13,tzinfo=timezone.utc), 1),
    (datetime(2026,9,16,12,59,tzinfo=timezone.utc), 50),
    (NOW, 301),
])
def test_expired_or_overlong_child_refused(reserve, now, seconds):
    _, _, evaluate = reserve
    with pytest.raises(ValueError):
        evaluate(now, now+timedelta(seconds=seconds))

def test_post_denial_approval_is_required(reserve):
    _, authority, evaluate = reserve
    authority["post_denial_approval"] = False
    with pytest.raises(ValueError):
        evaluate()

def test_different_plan_cannot_borrow_exception(reserve):
    _, _, evaluate = reserve
    with pytest.raises(ValueError):
        evaluate(plan_digest="e"*64)
    with pytest.raises(ValueError):
        evaluate(selection="e"*64)

def test_changed_record_bytes_fail_digest_before_scope_check(tmp_path):
    path = tmp_path / "exception.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        stage.capacity_recovery_reserve(path, "0"*64, {}, PLAN, NOW, NOW+timedelta(seconds=295))
