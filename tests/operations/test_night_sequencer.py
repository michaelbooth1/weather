"""Pure tests of the night sequencer generator (plan -> units, findings, timetable, queue draft).

Guards: INTEGRATION_ATTEMPT_RUNBOOK windows (suite 00:30-09:00; merge 01:00-03:40, >= 30 min after the
suite), the night plan's hash binding (landing_night_plan_v0.1, R-2), stacked heads gated on their base
having landed, and the M6 rule that only the owner approves and signs a merge queue (drafts are unsigned,
approved=false).
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from weather.operations import night_sequencer as ns
from weather.operations.landing_preflight import plan_content_sha256

MASTER = "a" * 40
RS = "b" * 40
RF = "c" * 40
ALONE = "d" * 40


def _pregate(base: str = MASTER, verdict: str = "PASS") -> dict:
    return {"verdict": verdict, "receipt_sha256": "e" * 64, "base": base, "base_is_ancestor": True}


def _plan(**overrides) -> dict:
    plan = {
        "schema": "landing_night_plan_v0.1",
        "night": "2026-10-14",
        "label": "test night",
        "master_sha": MASTER,
        "schedule": {"overflow_drop_order": ["rf", "rs"], "rs_failure_fallback": "land rf-alone"},
        "fallback_heads": [{"head": "claude/integration-20261014-n9-rf-alone-r2", "sha": ALONE,
                            "stacked_on": f"built on master {MASTER}", "expected_roll_class": "ROLL-FREE",
                            "pregate": _pregate()}],
        "docs_light_path": [{"branch": "claude/docs-x-20261013", "sha": "f" * 40}],
        "slots": [
            # Listed out of execution order on purpose: exec decides.
            {"kind": "rf_guarded_merge", "head": "claude/integration-20261014-n9-rf-r2", "sha": RF, "exec": 2,
             "stacked_on": f"claude/integration-20261014-n9-rs-r2 {RS}", "expected_roll_class": "ROLL-FREE",
             "pregate": _pregate()},
            {"kind": "rs_guarded_merge", "head": "claude/integration-20261014-n9-rs-r2", "sha": RS, "exec": 1,
             "stacked_on": f"built directly on master {MASTER}", "expected_roll_class": "ROLL-SENSITIVE",
             "pregate": _pregate()},
        ],
    }
    plan.update(overrides)
    plan["plan_sha256"] = plan_content_sha256(plan)
    return plan


def _write(tmp_path: Path, plan: dict) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_units_follow_exec_order_and_stacked_heads_require_their_base():
    units, findings = ns.build_units(_plan())
    assert [u.label for u in units] == ["n9-rs-r2", "n9-rf-r2", "n9-rf-alone-r2"]
    assert [u.fallback for u in units] == [False, False, True]
    assert units[0].requires_landed == []  # stacked on master_sha itself
    assert units[1].requires_landed == [RS]
    assert units[2].requires_landed == []
    assert units[1].attempt_stem == "20261014-n9-rf-r2"
    assert findings == []


@pytest.mark.parametrize(
    "head, label",
    [
        ("claude/integration-20261014-n9-rs-r2", "n9-rs-r2"),
        ("origin/codex/integration-20261014-x", "x"),
        ("claude/dst-m2-cache-age-utc-20261011", "dst-m2-cache-age-utc-20261011"),
    ],
)
def test_unit_label_strips_only_the_integration_prefix(head, label):
    assert ns.unit_label(head) == label


def test_attempt_stem_fits_the_attempt_id_limit():
    stem = ns.attempt_stem(date(2026, 10, 14), "x" * 80)
    assert len(stem + "-a9") <= 48
    assert stem.startswith("20261014-")


def test_pregate_findings_block_on_missing_or_failed_pregate_and_note_a_base_drift():
    plan = _plan()
    plan["slots"][1]["pregate"] = _pregate(verdict="FAIL")
    plan["slots"][0].pop("pregate")
    plan["fallback_heads"][0]["pregate"] = _pregate(base="9" * 40)
    plan["plan_sha256"] = plan_content_sha256(plan)
    _, findings = ns.build_units(plan)
    by_unit = {(f.unit, f.severity) for f in findings}
    assert ("n9-rs-r2", "BLOCK") in by_unit
    assert ("n9-rf-r2", "BLOCK") in by_unit
    assert ("n9-rf-alone-r2", "NOTE") in by_unit
    assert ("n9-rf-alone-r2", "BLOCK") not in by_unit


def test_unknown_stacked_base_and_bad_roll_class_block():
    plan = _plan()
    plan["slots"][0]["stacked_on"] = "claude/elsewhere " + "9" * 40
    plan["slots"][1]["expected_roll_class"] = "maybe"
    _, findings = ns.build_units(plan)
    messages = [(f.unit, f.severity, f.message) for f in findings]
    assert any(u == "n9-rf-r2" and s == "BLOCK" and "neither master_sha" in m for u, s, m in messages)
    assert any(u == "n9-rs-r2" and s == "BLOCK" and "roll class" in m for u, s, m in messages)


def test_duplicate_labels_are_refused():
    plan = _plan()
    plan["fallback_heads"][0]["head"] = "claude/integration-20261014-n9-rs-r2"
    with pytest.raises(ValueError, match="share the label"):
        ns.build_units(plan)


def test_timetable_is_serial_and_respects_the_merge_window():
    units, _ = ns.build_units(_plan())
    rows = ns.estimate_timetable(units, date(2026, 10, 14), suite_minutes=52, land_minutes=8)
    assert [r["label"] for r in rows] == ["n9-rs-r2", "n9-rf-r2"]  # fallback is not scheduled
    first, second = rows
    assert first["suite_at"] == datetime(2026, 10, 14, 0, 35)  # the real first trigger, not 00:30
    assert first["merge_at"] == datetime(2026, 10, 14, 1, 5)  # max(suite + 30, 01:00)
    assert first["suite_end"] == datetime(2026, 10, 14, 1, 27)
    assert first["landed_at"] == datetime(2026, 10, 14, 1, 35)  # max(merge, suite end) + 8
    assert second["suite_at"] == datetime(2026, 10, 14, 1, 37)
    assert second["merge_at"] == datetime(2026, 10, 14, 2, 7)
    assert not first["overflow"] and not second["overflow"]
    assert first["path"] == second["path"] == "attempt"


def _one(unit, *, start: datetime, suite_minutes: int = 52, land_minutes: int = 8) -> dict:
    return ns.estimate_timetable([unit], date(2026, 10, 14), suite_minutes=suite_minutes,
                                 land_minutes=land_minutes, start=start)[0]


def test_attempt_overflows_when_its_suite_would_run_past_0340():
    rs = ns.build_units(_plan())[0][0]
    at_reserve = _one(rs, start=datetime(2026, 10, 14, 2, 48))  # 02:48 + 52 = 03:40 exactly
    past = _one(rs, start=datetime(2026, 10, 14, 2, 49))
    assert at_reserve["suite_end"] == datetime(2026, 10, 14, 3, 40) and not at_reserve["overflow"]
    # The merge trigger (03:19) is inside the reserve; the suite end alone makes it overflow.
    assert past["merge_at"] == datetime(2026, 10, 14, 3, 19)
    assert past["overflow"] and "suite end 03:41" in past["overflow_reason"]
    assert "merge trigger" not in past["overflow_reason"]


def test_attempt_merge_trigger_boundary_is_the_0340_reserve():
    rs = ns.build_units(_plan())[0][0]
    at_reserve = _one(rs, start=datetime(2026, 10, 14, 3, 10), suite_minutes=20)
    past = _one(rs, start=datetime(2026, 10, 14, 3, 11), suite_minutes=20)
    assert at_reserve["merge_at"] == datetime(2026, 10, 14, 3, 40) and not at_reserve["overflow"]
    assert past["overflow"] and "merge trigger 03:41" in past["overflow_reason"]


def _direct_plan() -> dict:
    plan = _plan()
    plan["slots"][0]["landing_path"] = "direct_rf"  # the roll-free slot (exec 2)
    plan["plan_sha256"] = plan_content_sha256(plan)
    return plan


def test_direct_rf_unit_is_not_bound_by_0340_only_by_0900():
    units, findings = ns.build_units(_direct_plan())
    assert findings == []
    rf = units[1]
    assert rf.path == "direct_rf" and units[0].path == "attempt"
    late = _one(rf, start=datetime(2026, 10, 14, 3, 50))
    assert not late["overflow"]
    assert late["merge_at"] == late["suite_end"] == datetime(2026, 10, 14, 4, 42)  # merge right after the suite
    assert late["landed_at"] == datetime(2026, 10, 14, 4, 50)
    at_close = _one(rf, start=datetime(2026, 10, 14, 8, 0))  # lands 09:00 exactly
    past = _one(rf, start=datetime(2026, 10, 14, 8, 1))
    assert at_close["landed_at"] == datetime(2026, 10, 14, 9, 0) and not at_close["overflow"]
    assert past["overflow"] and "09:00" in past["overflow_reason"]


def test_direct_rf_after_an_attempt_follows_it_serially():
    units, _ = ns.build_units(_direct_plan())
    rows = ns.estimate_timetable(units, date(2026, 10, 14), suite_minutes=52, land_minutes=8,
                                 start=datetime(2026, 10, 14, 2, 40))
    rs, rf = rows
    assert not rs["overflow"]  # 02:40 + 52 = 03:32
    assert rf["suite_at"] == datetime(2026, 10, 14, 3, 42)  # previous landing 03:40 + 2
    assert not rf["overflow"]  # a direct head past 03:40 is not an overflow


@pytest.mark.parametrize(
    "path, roll, needle",
    [
        ("direct_rf", "ROLL-SENSITIVE", "needs expected_roll_class ROLL-FREE"),
        ("direct_rf", "ROLL-FREE-IF-DORMANT", "needs expected_roll_class ROLL-FREE"),
        ("sideways", "ROLL-FREE", "is not one of attempt, direct_rf"),
    ],
)
def test_landing_path_findings_block(path, roll, needle):
    plan = _plan()
    plan["slots"][0]["landing_path"] = path
    plan["slots"][0]["expected_roll_class"] = roll
    _, findings = ns.build_units(plan)
    assert any(f.unit == "n9-rf-r2" and f.severity == "BLOCK" and needle in f.message for f in findings), findings


@pytest.mark.parametrize("value", ["a'b", "a$b", "a`b", 'a"b', "a;b"])
def test_emitted_literals_refuse_powershell_metacharacters(value):
    with pytest.raises(ValueError):
        ns.ps_literal(value)


def test_generate_writes_three_files_and_an_unsigned_queue_draft(tmp_path):
    plan = _plan()
    out = tmp_path / "out"
    summary = ns.generate(_write(tmp_path, plan), out, expect_sha256=plan["plan_sha256"])
    assert summary["blocking"] is False
    assert summary["units"] == ["n9-rs-r2", "n9-rf-r2", "n9-rf-alone-r2"]
    queue = json.loads((out / "queue-2026-10-14.draft.json").read_text(encoding="utf-8"))
    assert queue["schema_version"] == ns.QUEUE_SCHEMA
    assert queue["plan_sha256"] == plan["plan_sha256"] and queue["base_sha"] == MASTER
    assert [(e["order"], e["expected_tip"], e["roll_class"]) for e in queue["entries"]] == [
        (1, RS, "ROLL-SENSITIVE"), (2, RF, "ROLL-FREE")]
    assert all(e["approved"] is False and e["approval_ref"] == "" for e in queue["entries"])
    assert sorted(p.name for p in out.iterdir()) == [
        "queue-2026-10-14.draft.json", "sequencer-2026-10-14.ps1", "timetable-2026-10-14.md"]
    timetable = (out / "timetable-2026-10-14.md").read_text(encoding="utf-8")
    assert "-CheckOnly" in timetable and "Findings:" in timetable


def test_generate_carries_paths_and_estimates_into_the_outputs(tmp_path):
    out = tmp_path / "out"
    summary = ns.generate(_write(tmp_path, _direct_plan()), out, suite_minutes=47, land_minutes=6)
    assert summary["blocking"] is False
    script = (out / "sequencer-2026-10-14.ps1").read_bytes().decode("utf-8-sig")
    assert "[int]$SuiteMinutes = 47," in script and "[int]$LandMinutes = 6" in script
    assert "path = 'direct_rf'" in script and "path = 'attempt'" in script
    timetable = (out / "timetable-2026-10-14.md").read_text(encoding="utf-8")
    assert "| n9-rs-r2 | attempt | 00:35 | 01:22 | 01:05 | 01:28 | no |" in timetable
    assert "| n9-rf-r2 | direct_rf | 01:30 | 02:17 | 02:17 | 02:23 | no |" in timetable


def test_generate_notes_a_suite_end_overflow(tmp_path):
    out = tmp_path / "out"
    summary = ns.generate(_write(tmp_path, _plan()), out, suite_minutes=170)  # rs 00:35-03:25 fits; rf from 03:35
    notes = {f["unit"]: f["message"] for f in summary["findings"]}
    assert "n9-rs-r2" not in notes
    assert notes["n9-rf-r2"].startswith("estimated overflow: merge trigger 04:05 is past the 03:40 reserve; suite end 06:25")
    assert "YES: merge trigger 04:05" in (out / "timetable-2026-10-14.md").read_text(encoding="utf-8")
    summary = ns.generate(_write(tmp_path, _plan()), out, suite_minutes=190)  # rs 00:35 + 190 = 03:45
    notes = {f["unit"]: f["message"] for f in summary["findings"]}
    assert notes["n9-rs-r2"] == "estimated overflow: suite end 03:45 is past 03:40, where the consumer stops it"


def test_queue_draft_binds_a_named_preflight_receipt(tmp_path):
    out = tmp_path / "out"
    (out / "receipts").mkdir(parents=True)
    receipt = out / "receipts" / "pf-rs.json"
    receipt.write_bytes(b'{"verdict":"PASS"}')
    ns.generate(_write(tmp_path, _plan()), out, receipts=[f"n9-rs-r2={receipt}"])
    entry = json.loads((out / "queue-2026-10-14.draft.json").read_text(encoding="utf-8"))["entries"][0]
    assert entry["preflight_receipt"] == "receipts/pf-rs.json"
    assert entry["preflight_receipt_sha256"] == hashlib.sha256(b'{"verdict":"PASS"}').hexdigest()


def test_main_refuses_a_plan_hash_mismatch_and_exits_2_on_blocking_findings(tmp_path, capsys):
    plan = _plan()
    path = _write(tmp_path, plan)
    assert ns.main(["--plan", str(path), "--out-dir", str(tmp_path / "o1"), "--expect-plan-sha256", "0" * 64]) == ns.EXIT_REFUSED
    assert not (tmp_path / "o1").exists()
    tampered = copy.deepcopy(plan)
    tampered["slots"][0]["sha"] = "9" * 40  # embedded plan_sha256 no longer matches
    assert ns.main(["--plan", str(_write(tmp_path, tampered)), "--out-dir", str(tmp_path / "o2")]) == ns.EXIT_REFUSED
    blocked = _plan()
    blocked["slots"][0]["pregate"] = _pregate(verdict="FAIL")
    blocked["plan_sha256"] = plan_content_sha256(blocked)
    assert ns.main(["--plan", str(_write(tmp_path, blocked)), "--out-dir", str(tmp_path / "o3")]) == ns.EXIT_FINDINGS
    assert ns.main(["--plan", str(_write(tmp_path, plan)), "--out-dir", str(tmp_path / "o4")]) == ns.EXIT_OK
    capsys.readouterr()
