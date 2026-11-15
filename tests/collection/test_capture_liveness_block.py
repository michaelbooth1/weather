"""Guards: T115 silent capture outage, BLOCK projection and tape-based liveness."""

import csv
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from weather.collection import collection_health as health
from weather.collection import snapshot_tracker as tracker
from weather.market.market_config import config_for_date
from weather.market.market_registry import spec_for_id


NOW = datetime(2026, 11, 15, 14, tzinfo=ZoneInfo("America/Toronto"))
REASON = "generated location_market_events metadata is 60 hours old"


def write_tape(root, day, times):
    folder = root / config_for_date(day, "toronto").event_slug
    folder.mkdir()
    with (folder / "snapshots_long.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["snapshot_id", "captured_at_local"])
        writer.writeheader()
        writer.writerows({"snapshot_id": str(i), "captured_at_local": ts.isoformat()}
                        for i, ts in enumerate(times))


@pytest.mark.parametrize("mode", ["no_tape", "old_day", "stale_today"])
def test_blocked_current_day_cannot_be_hidden_by_missing_or_old_tape(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(health, "all_specs", lambda: [spec_for_id("toronto")])
    if mode == "old_day":
        old = NOW - timedelta(days=2)
        write_tape(tmp_path, old.date(), [old.replace(hour=12), old.replace(hour=18)])
    elif mode == "stale_today":
        write_tape(tmp_path, NOW.date(), [NOW - timedelta(minutes=30)])
    result = {"blocked": True, "status": "BLOCK", "reason": REASON,
              "written": False, "event_slug": config_for_date(NOW.date(), "toronto").event_slug}
    (tmp_path / "loop_status.json").write_text(json.dumps({"last_market_results": {"toronto": result}}))
    liveness = health.fleet_collection_health(tmp_path, as_of=NOW)["capture_liveness"]
    assert liveness["status"] == "STALE"
    assert liveness["healthy_market_count"] == 0
    assert liveness["stale_market_count"] == liveness["blocked_market_count"] == 1
    assert REASON in liveness["reason"]


@pytest.mark.parametrize("detail", [{"error": "disk write failed"}, {"skipped_reason": "maintenance"}, {}])
def test_stale_unwritten_market_reports_reason(detail):
    liveness = health.fleet_capture_liveness([
        {"market_id": "toronto", "state": "AT_RISK", "latest_age_minutes": 23,
         "last_capture": {"written": False, **detail}}
    ])
    assert liveness["status"] == "STALE" and liveness["healthy_market_count"] == 0
    assert next(iter(detail.values()), "no recent snapshot written") in liveness["reason"]


def test_fresh_tape_is_live_and_missing_pre_window_market_is_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "all_specs", lambda: [spec_for_id("toronto")])
    write_tape(tmp_path, NOW.date(), [NOW - timedelta(minutes=10), NOW])
    assert health.fleet_collection_health(tmp_path, as_of=NOW)["capture_liveness"]["status"] == "OK"
    before_window = health.fleet_collection_health(tmp_path / "empty", as_of=NOW.replace(hour=10))
    assert before_window["capture_liveness"]["status"] == "OK"
    assert before_window["capture_liveness"]["pending_markets"] == ["toronto"]


def test_all_block_iteration_preserves_details_and_clean_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json")
    monkeypatch.setattr(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl")
    monkeypatch.setattr(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag")
    monkeypatch.setattr(tracker, "all_specs", lambda: [spec_for_id("toronto")])
    monkeypatch.setattr(tracker, "current_fleet_collection_health", lambda **kwargs: {"summary": {}, "markets": []})
    blocked = {"blocked": True, "status": "BLOCK", "reason": REASON, "skipped_reason": None}
    status = tracker.run_loop(max_iterations=1, capture_fn=lambda **kwargs: blocked,
                              now_fn=lambda: NOW, sleep_fn=lambda _: None)
    assert status["last_iteration_outcome"] == "error"
    assert status["consecutive_errors"] == 1 and REASON in status["last_error"]
    persisted = json.loads((tmp_path / "loop_status.json").read_text())
    for key in ("blocked", "status", "reason", "skipped_reason"):
        assert persisted["last_market_results"]["toronto"][key] == blocked[key]
        assert persisted["last_cadence_attribution"]["markets"]["toronto"][key] == blocked[key]
    diagnostic = json.loads((tmp_path / "diagnostics.jsonl").read_text().splitlines()[-1])
    assert diagnostic["markets"]["toronto"]["reason"] == REASON
    tracker.finalize_iteration_error_state(status, {"toronto": {"written": True, "snapshot_id": "new"}},
                                           expected_market_ids=["toronto"], completed_at=NOW)
    assert status["last_iteration_outcome"] == "clean" and status["consecutive_errors"] == 0


def test_unexplained_no_write_is_not_a_clean_iteration():
    status = {}
    tracker.finalize_iteration_error_state(status, {"toronto": {"written": False}},
                                           expected_market_ids=["toronto"], completed_at=NOW)
    assert status["last_iteration_outcome"] == "error"
