from datetime import date, datetime, timedelta, timezone
import json

import pytest

from weather.reporting.roadmap import worktrack as wt


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


@pytest.fixture
def record():
    return wt.new_record("W-0001", "Verify the handback", "ops", "production", NOW)


def call(root, *args, now=NOW):
    return wt.main(["--root", str(root), "--decision-log", str(root / "decisions.md"), "--now", now.isoformat(), *args])


def test_cli_lifecycle_and_handoff(tmp_path, capsys):
    root = tmp_path / "work"
    assert call(root, "new", "--title", "A mission", "--workstream", "model") == 0
    assert call(root, "new", "--title", "Follow-up", "--workstream", "model") == 0
    assert call(root, "link", "W-0002", "depends_on", "W-0001") == 0
    assert call(root, "link", "W-0002", "depends_on", "W-0001") == 0
    assert call(root, "set", "W-0001", "branch=codex/mission", "tip=1234567", "status=handed-off") == 0
    assert call(root, "link", "W-0001", "handoff", "docs/roadmap/handoff.md") == 0
    assert call(root, "link", "W-0001", "handbacks", "docs/roadmap/report.md") == 0
    later = NOW + timedelta(days=1)
    assert call(root, "link", "W-0001", "handbacks", "docs/roadmap/report.md", now=later) == 0
    record = wt.load_records(root)["W-0001"]
    assert record["status"] == "handback-received"
    assert len(record["handbacks"]) == 1
    assert wt.instant(record["handbacks"][0]["received"]) == NOW
    assert wt.load_records(root)["W-0002"]["depends_on"] == ["W-0001"]
    assert call(root, "handoff-prompt", "W-0001", now=later) == 0
    assert "Execute W-0001 from origin/codex/mission" in capsys.readouterr().out
    assert call(root, "check", now=later) == 0


@pytest.mark.parametrize("mutation", [
    {"surprise": True}, {"status": "done"}, {"owner": "anyone"},
    {"roll": "safe"}, {"workstream": "other"}, {"depends_on": "W-0002"},
    {"id": "../outside"}, {"handbacks": [{"path": "x", "received": "bad", "verified": False}]},
    {"needs_owner": [{"question": "Q", "status": "pending", "since": "2026-09-27", "decision": None, "typo": 1}]},
    {"updated": "yesterday"}, {"updated": "2026-09-27T12:00:00"},
    {"status": "handback-received"}, {"landing_slot": {"date": "bad", "window": "night"}},
])
def test_strict_shape(record, mutation):
    record.update(mutation)
    with pytest.raises(wt.RegistryError):
        wt.validate(record)


def test_duplicate_yaml_keys_rejected():
    with pytest.raises(wt.RegistryError, match="duplicate"):
        wt.read_yaml('{"id": "W-0001", "id": "W-0002"}')


def test_filename_must_match_and_unknown_fields_fail_check(tmp_path, record):
    wt.write_record(tmp_path, record, create=True)
    source = tmp_path / "W-0001.yaml"
    original = source.read_text(encoding="utf-8")
    source.write_text(original + "typo: true\n", encoding="utf-8")
    assert call(tmp_path, "check") == 1
    source.write_text(original, encoding="utf-8")
    source.rename(tmp_path / "W-0002.yaml")
    assert call(tmp_path, "check") == 1


def test_dangling_cycle_and_failed_edit_preserves_bytes(tmp_path, record):
    wt.write_record(tmp_path, record, create=True)
    original = (tmp_path / "W-0001.yaml").read_bytes()
    assert call(tmp_path, "link", "W-0001", "depends_on", "W-9999") == 1
    assert (tmp_path / "W-0001.yaml").read_bytes() == original
    assert call(tmp_path, "set", "W-0001", "unknown=bad") == 1
    assert call(tmp_path, "set", "W-0001", "id=W-0002") == 1
    assert (tmp_path / "W-0001.yaml").read_bytes() == original
    assert call(tmp_path, "new", "--id", "W-0001", "--title", "Overwrite", "--workstream", "ops") == 1
    assert (tmp_path / "W-0001.yaml").read_bytes() == original
    record["depends_on"] = ["W-9999"]
    wt.write_record(tmp_path, record)
    assert call(tmp_path, "check") == 1
    other = wt.new_record("W-9999", "Cycle", "ops", "production", NOW)
    other["depends_on"] = ["W-0001"]
    wt.write_record(tmp_path, other, create=True)
    assert any("cycle" in error for error in wt.check(wt.load_records(tmp_path), set(), NOW))


def test_age_boundaries_and_notes_cannot_refresh_them(tmp_path, record):
    record["needs_owner"] = [dict(question="Approve", status="pending", since=NOW.isoformat(), decision=None)]
    record["status"] = "handback-received"
    record["handbacks"] = [dict(path="report.md", received=(NOW + timedelta(days=1)).isoformat(), verified=False)]
    wt.write_record(tmp_path, record, create=True)
    boundary = NOW + timedelta(days=3)
    assert call(tmp_path, "check", now=boundary) == 0
    assert call(tmp_path, "set", "W-0001", 'notes=["touched"]', now=boundary) == 0
    errors = wt.check(wt.load_records(tmp_path), set(), boundary + timedelta(seconds=1))
    assert sum("older than 3 days" in error for error in errors) == 1
    assert sum("more than 2 days" in error for error in errors) == 1
    record["handbacks"][0]["verified"] = True
    record["needs_owner"][0]["status"] = "declined"
    assert wt.check({record["id"]: record}, set(), boundary + timedelta(days=1)) == []


def test_approval_requires_exact_row_not_prose_or_substring(tmp_path, record):
    log = tmp_path / "DECISION_LOG.md"
    log.write_text("Approved in conversation: 2026-09-26 | Allow this\n| Date | Decision | Scope |\n| --- | --- | --- |\n| 2026-09-26 | Allow this exact thing | ops |\n", encoding="utf-8")
    need = dict(question="Permission", status="approved", since="2026-09-26", decision=dict(date="2026-09-26", text="Allow this"))
    record["needs_owner"] = [need]
    rows = wt.decision_rows(log)
    assert "no matching DECISION_LOG row" in wt.check({record["id"]: record}, rows, NOW)[0]
    need["decision"]["text"] = "Allow this exact thing"
    assert wt.check({record["id"]: record}, rows, NOW) == []
    need["decision"]["date"] = "2026-09-25"
    assert wt.check({record["id"]: record}, rows, NOW)
    need["decision"] = None
    assert wt.check({record["id"]: record}, rows, NOW)


def test_readiness_blocks_dependency_owner_roll_and_handback(record):
    record.update(status="queued", branch="codex/test", tip="1234567", roll="free", landing_slot=dict(date="2026-09-27", window="docs"))
    records = {record["id"]: record}
    assert wt.blockers(record, records, set()) == []
    record["depends_on"] = ["W-0002"]
    assert wt.blockers(record, records, set()) == ["waiting for W-0002"]
    dep = wt.new_record("W-0002", "Dependency", "ops", "production", NOW)
    records[dep["id"]] = dep
    dep["status"] = "landed"
    assert wt.blockers(record, records, set()) == []
    record["roll"] = "unknown"
    record["handbacks"] = [dict(path="report", received=NOW.isoformat(), verified=False)]
    record["needs_owner"] = [dict(question="Go?", status="approved", since=NOW.isoformat(), decision=None)]
    assert len(wt.blockers(record, records, set())) == 3


def test_board_and_night_plan_are_deterministic_fixture_outputs(tmp_path, record):
    record.update(status="verified", roll="free", branch="codex/test", tip="1234567", landing_slot=dict(date="2026-09-27", window="docs"))
    record["title"] = "A | B\nC"
    wt.write_record(tmp_path, record, create=True)
    output = tmp_path / "board.md"
    assert call(tmp_path, "board", "--actor", "production", "--night", "2026-09-27", "--output", str(output)) == 0
    text = output.read_text(encoding="utf-8")
    assert "## By status" in text and "## Per workstream" in text
    assert "## Waiting on owner" in text and "## Ready to land tonight" in text
    assert "A \\| B<br>C" in text
    assert call(tmp_path, "night-plan", "--night", "2026-09-27") == 0
    assert "READY for production review" in wt.night_plan(wt.load_records(tmp_path), set(), date(2026, 9, 27))
    assert "W-0001" not in wt.night_plan(wt.load_records(tmp_path), set(), date(2026, 9, 28))
    record["needs_owner"] = [dict(question="Approval", status="approved", since="2026-09-26", decision=None)]
    wt.write_record(tmp_path, record)
    assert call(tmp_path, "night-plan", "--night", "2026-09-27") == 1
    assert call(tmp_path, "board", "--actor", "production", "--night", "2026-09-27", "--output", str(output)) == 1
    assert "Registry check failed" in output.read_text(encoding="utf-8")


def test_board_requires_production_declaration(tmp_path):
    with pytest.raises(SystemExit):
        call(tmp_path, "board", "--night", "2026-09-27")


def test_patch_file_and_missing_handoff(tmp_path, record):
    wt.write_record(tmp_path, record, create=True)
    patch = tmp_path / "patch.txt"
    patch.write_text(json.dumps(dict(landing_slot=dict(date="2026-09-27", window="docs"), notes=["evidence"])), encoding="utf-8")
    assert call(tmp_path, "set", "W-0001", "--file", str(patch)) == 0
    assert wt.load_records(tmp_path)["W-0001"]["notes"] == ["evidence"]
    assert call(tmp_path, "handoff-prompt", "W-0001") == 1
    assert call(tmp_path, "set", "W-9999", "status=closed") == 1


def test_missing_registry_fails_and_defaults_ignore_cwd(tmp_path, monkeypatch):
    assert call(tmp_path / "missing", "check") == 1
    expected = wt.DEFAULT_ROOT
    monkeypatch.chdir(tmp_path)
    assert wt.DEFAULT_ROOT == expected and expected.is_absolute()


def test_future_dates_fail_closed(record):
    assert "future" in wt.check({record["id"]: record}, set(), NOW - timedelta(seconds=1))[0]
