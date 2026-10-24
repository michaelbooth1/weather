import json
from datetime import datetime, timedelta, timezone

from weather.market.wallet_reader_client import ClientError
from weather.reporting.market import cockpit_snapshot as cockpit
from weather.reporting.roadmap import worktrack


NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)


def _refusing_reader(command, **kwargs):
    raise ClientError("config")


def _record(key, **changes):
    record = worktrack.new_record(key, f"Mission {key}", "ops", "production", NOW - timedelta(days=6))
    record.update(changes)
    return record


def _write_work(root, *records):
    root.mkdir()
    for record in records:
        (root / f"{record['id']}.yaml").write_text(json.dumps(record), encoding="utf-8")
    return root


def _snapshot(tmp_path, **kwargs):
    defaults = dict(
        now=NOW,
        host_health_path=tmp_path / "alerts" / "host_health_latest.json",
        disk_trail_path=tmp_path / "alerts" / "disk_free_trail.jsonl",
        maker_evidence_root=tmp_path / "maker_evidence",
        work_root=tmp_path / "work",
        decision_log=tmp_path / "DECISION_LOG.md",
        wallet_reader=_refusing_reader,
        capture_families_config=tmp_path / "capture_families.json",
        capture_families_root=tmp_path / "maker_evidence_families",
    )
    defaults.update(kwargs)
    return cockpit.collect_cockpit_snapshot(**defaults)


def test_every_missing_source_is_unavailable_with_a_reason(tmp_path):
    snapshot = _snapshot(tmp_path)

    sections = [snapshot["money"], snapshot["work"], *snapshot["health"].values()]
    assert all(section["available"] is False and section["reason"] for section in sections)
    assert snapshot["money"]["reason"] == "wallet reader config"
    assert "host_health_latest.json" in snapshot["health"]["host"]["reason"]
    assert "disk_free_trail.jsonl" in snapshot["health"]["disk"]["reason"]
    assert "maker_evidence" in snapshot["health"]["maker_evidence"]["reason"]
    assert "capture_families.json" in snapshot["health"]["capture_families"]["reason"]
    assert "does not exist" in snapshot["work"]["reason"]
    # The exam calendar is constant and needs no source; closed counts are unknown, not zero.
    assert snapshot["exam"]["available"] is True
    assert {row["panel_days_closed"] for row in snapshot["exam"]["exams"]} == {None}


def test_incomplete_wallet_pnl_is_never_shown_as_a_number(tmp_path):
    calls = []

    def reader(command, **kwargs):
        calls.append((command, kwargs))
        if command == "rewards":
            return {"date": kwargs["day"], "total": [{"earnings": "5.25"}, {"earnings": 3}], "payment_verified": False}
        return {"status": "INCOMPLETE", "cash_pusd": "283.95", "campaign_pnl_pusd": "12.5",
                "incomplete_reasons": ["unredeemed_terminal_value_unknown"], "positions": [],
                "open_orders": [], "unredeemed_positions": [{}],
                "campaigns": {"status": "INCOMPLETE", "reasons": ["portfolio_input_unavailable"],
                              "books": {"policy-a": {"pnl_pusd": "9"}}},
                "errors": {}}

    money = _snapshot(tmp_path, wallet_reader=reader)["money"]

    assert money["available"] and money["cash_pusd"] == "283.95"
    assert money["pnl_pusd"] is None
    assert money["pnl_reason"] == "INCOMPLETE: unredeemed_terminal_value_unknown, portfolio_input_unavailable"
    assert money["rewards"] == {"available": True, "date": "2026-10-01", "total_pusd": "8.25", "payment_verified": False}
    assert calls == [("summary", {}), ("rewards", {"day": "2026-10-01"})]
    # Embargo: no per-campaign (policy) book reaches the cockpit.
    assert "campaigns" not in money and "policy-a" not in json.dumps(money)


def test_observed_wallet_pnl_is_shown(tmp_path):
    def reader(command, **kwargs):
        if command == "rewards":
            raise ClientError("timeout")
        return {"status": "OBSERVED", "cash_pusd": "300", "campaign_pnl_pusd": "-4.5", "positions": [{}],
                "open_orders": None, "incomplete_reasons": []}

    money = _snapshot(tmp_path, wallet_reader=reader)["money"]

    assert money["pnl_pusd"] == "-4.5" and money["pnl_reason"] is None
    assert money["open_order_count"] is None and money["position_count"] == 1
    assert money["rewards"] == {"available": False, "reason": "wallet reader timeout"}


def test_negative_disk_slope_projects_days_to_both_floors(tmp_path):
    trail = tmp_path / "alerts" / "disk_free_trail.jsonl"
    trail.parent.mkdir()
    rows = [(NOW - timedelta(hours=hours), free) for hours, free in ((50, 100.0), (26, 96.0), (24, 94.0), (1, 91.0))]
    lines = [json.dumps({"ts": ts.isoformat(), "free_gb": free}) for ts, free in rows]
    trail.write_text("﻿" + "\n".join(["not json", *lines]) + "\n", encoding="utf-8")

    disk = _snapshot(tmp_path)["health"]["disk"]

    # Reference: the newest sample at least 24 h before the latest (-1 h), i.e. -26 h at 96 GiB.
    assert disk["free_gib"] == 91.0
    assert disk["slope_gib_per_day"] == round((91.0 - 96.0) / 25 * 24, 2)
    assert disk["days_to"] == {"50": round(41 / 4.8, 1), "40": round(51 / 4.8, 1)}


def test_disk_tail_read_and_non_falling_slope(tmp_path):
    trail = tmp_path / "trail.jsonl"
    lines = [json.dumps({"ts": (NOW - timedelta(hours=30 - n / 10)).isoformat(), "free_gb": 60.0 + n / 100})
             for n in range(300)]
    trail.write_text("\n".join(lines) + "\n", encoding="utf-8")

    disk = cockpit.read_disk_trail(trail, NOW, tail_bytes=4096)

    assert disk["slope_gib_per_day"] is None  # the tail alone does not span 24 h
    full = cockpit.read_disk_trail(trail, NOW)
    assert full["slope_gib_per_day"] > 0 and full["days_to"] == {"50": None, "40": None}


def test_waiting_on_owner_older_than_three_days_is_overdue(tmp_path):
    old = _record("W-0001", needs_owner=[{"question": "Approve 5f deletes", "status": "pending",
                                          "since": (NOW - timedelta(days=4)).isoformat(), "decision": None}])
    fresh = _record("W-0002", needs_owner=[{"question": "Pick a landing night", "status": "pending",
                                            "since": (NOW - timedelta(days=1)).isoformat(), "decision": None}])
    ready = _record("W-0003", status="queued", branch="codex/x", tip="abcdef1", roll="free")
    done = _record("W-0004", status="landed")
    root = _write_work(tmp_path / "work", old, fresh, ready, done)

    work = _snapshot(tmp_path, work_root=root)["work"]

    assert work["record_count"] == 4 and work["open_count"] == 3
    assert [(row["id"], row["overdue"]) for row in work["waiting_on_owner"]] == [("W-0001", True), ("W-0002", False)]
    assert work["overdue_owner_count"] == 1
    assert work["ready_to_land"] == ["W-0003"]
    assert any("older than 3 days" in issue for issue in work["check_issues"])
    assert work["by_status"] == {"proposed": 2, "queued": 1}


def test_host_health_with_bom_and_staleness(tmp_path):
    path = tmp_path / "host_health_latest.json"
    record = {"ts": (NOW - timedelta(minutes=90)).isoformat(), "verdict": "OK", "top_severity": "MEDIUM",
              "streak": "3/14", "today": "ok", "window": "graded",
              "alerts": [{"severity": "MEDIUM", "class": "disk", "flag": "x", "act": "y", "extra": 1}]}
    path.write_text("﻿" + json.dumps(record), encoding="utf-8")

    host = cockpit.read_host_health(path, NOW)

    assert host["available"] and host["stale"] and host["age_minutes"] == 90.0
    assert host["alerts"] == [{"severity": "MEDIUM", "class": "disk", "flag": "x", "act": "y"}]


def test_maker_evidence_counts_only_sealed_past_utc_dates(tmp_path):
    root = tmp_path / "maker_evidence"
    for day, sealed in (("2026-09-30", True), ("2026-10-01", False), ("2026-10-02", True)):
        segment = root / day / "00-0123456789ab"
        segment.mkdir(parents=True)
        (segment / ("manifest.json.gz" if sealed else "part.jsonl")).write_bytes(b"")
    (root / "2026-09-29").mkdir()  # empty day is not closed
    (root / "status.json").write_text(json.dumps({"state": "RUNNING", "updated_at_utc": NOW.isoformat(),
                                                  "source_sha256": {"a": "b"}}), encoding="utf-8")

    snapshot = _snapshot(tmp_path)
    maker = snapshot["health"]["maker_evidence"]

    assert maker["closed_dates"] == ["2026-09-30"]
    assert maker["unsealed_past_dates"] == ["2026-09-29", "2026-10-01"]
    assert maker["status"]["state"] == "RUNNING" and "source_sha256" not in maker["status"]
    first = snapshot["exam"]["exams"][0]
    assert first["phase"] == "panel day 3 of 14" and first["panel_days_closed"] == 1
    assert first["days_to_look"] == 13


def test_exam_phases_follow_the_signed_calendar():
    def phases(day):
        now = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        return [row["phase"] for row in cockpit.exam_state(now)["exams"]]

    assert phases("2026-09-26") == ["before calibration", "before panel"]
    assert phases("2026-09-28") == ["calibration", "before panel"]
    assert phases("2026-10-13") == ["panel day 14 of 14", "before panel"]
    assert phases("2026-10-14") == ["settlement", "before panel"]
    assert phases("2026-10-15") == ["look day", "before panel"]
    assert phases("2026-10-16") == ["look passed", "panel day 1 of 14"]
    assert phases("2026-10-30") == ["look passed", "awaiting look"]
    assert phases("2026-11-01") == ["look passed", "look passed"]
    assert "No policy P&L" in cockpit.exam_state(NOW)["embargo"]


def test_reward_total_refuses_unknown_shapes():
    assert cockpit.reward_total({"total": {"earnings": "1.5"}}) == "1.5"
    assert cockpit.reward_total({"total": [{"earnings": "x"}]}) is None
    assert cockpit.reward_total({"total": "7"}) is None
    assert cockpit.reward_total({}) is None


def test_capture_families_section_reads_each_configured_family_status(tmp_path):
    (tmp_path / "capture_families.json").write_text(json.dumps({"format_version": 1, "families": {
        "lowest_temperature": {"max_conditions": 600, "stop_below_free_gib": 70}}}), encoding="utf-8")
    folder = tmp_path / "maker_evidence_families" / "lowest_temperature"
    folder.mkdir(parents=True)
    (folder / "status.json").write_text(json.dumps({
        "state": "STOPPED_FAMILY_DISK_FLOOR", "free_bytes": 65 * 1024**3,
        "updated_at_utc": (NOW - timedelta(seconds=20)).isoformat()}), encoding="utf-8")

    families = _snapshot(tmp_path)["health"]["capture_families"]

    assert families["available"] is True
    [row] = families["families"]
    assert row["family"] == "lowest_temperature" and row["severity"] == "WARN" and row["disk_floor"] == "stopped"
    assert "not a capture failure" in row["reason"]
