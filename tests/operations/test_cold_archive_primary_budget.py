"""Conditional reserve needs a complete conservative primary-allocation proof."""
from contextlib import ExitStack, nullcontext
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_primary_budget as budget
from weather.schema_registry import schema_version


def put(path, value, *, sealed=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = locations.canonical(locations.sealed(value) if sealed else value) + b"\n"
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def row(number, allocation=40, family="clob_tokens.jsonl"):
    return {"path": f"snapshots/highest-temperature-in-atlanta-on-july-{number}-2026/{family}",
            "size_bytes": 40, "mtime_ns": number, "device": 1, "file_id": number,
            "allocated_bytes": allocation}


def proposal(root, rows, kind):
    return {"schema_version": schema_version("archive_target_owner_review_proposal"),
            "source_root": str(root), "selection_kind": kind, "files": rows,
            "file_count": len(rows), "logical_bytes": sum(r["size_bytes"] for r in rows),
            "allocated_bytes": sum(r["allocated_bytes"] for r in rows)}


def add_receipt(case, name, source, kind, previous):
    member = {**source, "sha256": "d" * 64}
    entry = {"schema_version": schema_version("cold_archive_catalog_entry"), "status": "UPLOADED",
             "archive_id": name, "source_root": str(case.root),
             "plan_sha256": "e" * 64, "files": [member]}
    entry_spec = put(case.root / "cold_archive/catalog/archives" / name / "upload.json", entry, sealed=True)
    receipt = {"schema_version": schema_version("cold_archive_reclaim_receipt"), "status": "PASS",
               "attempt_id": name + "r1", "archive_id": name, "selection_kind": kind,
               "owner_approval_sha256": case.owner_spec["sha256"], "target_bytes": 100,
               "entry_sha256": entry_spec["sha256"], "plan_sha256": "e" * 64,
               "files": [copy.deepcopy(member)], "deleted_files": 1,
               "reclaimed_allocated_bytes": source["allocated_bytes"],
               "previous_reclaimed_allocated_bytes": previous}
    receipt_spec = put(case.campaign / (name + "r1") / "receipt.json", receipt, sealed=True)
    case.receipts.append((receipt_spec, receipt, entry_spec, entry))
    case.state.update(sequence=len(case.receipts), deleted_files=len(case.receipts),
                      reclaimed_allocated_bytes=previous + source["allocated_bytes"],
                      attempt_id=name + "r1", last_receipt_path=receipt_spec["path"],
                      last_receipt_sha256=receipt_spec["sha256"])


@pytest.fixture
def capacity_case(tmp_path, monkeypatch, request):
    if not request.node.name.startswith("test_native"):
        monkeypatch.setattr(budget.bridge, "_file_pin", lambda path: nullcontext(path))
        monkeypatch.setattr(budget.archive, "_directory_pin", lambda path: nullcontext(path))
    root = tmp_path / "data"
    root.mkdir()
    primary = proposal(root, [row(1), row(2), row(3)], "primary")
    reserve = proposal(root, [row(1, 20, "snapshot_explanations_long.csv"),
                              row(2, 20, "snapshot_explanations_long.csv")], "standby")
    primary_spec = put(tmp_path / "handoff/primary.json", primary)
    reserve_spec = put(tmp_path / "handoff/reserve.json", reserve)
    owner = {"schema_version": schema_version("archive_target_owner_approval"),
             "approved_by": "fixture owner", "owner_instruction": "approved primary and conditional reserve",
             "primary": {"proposal": "primary.json", "sha256": primary_spec["sha256"]},
             "conditional_reserve": {"proposal": "reserve.json", "sha256": reserve_spec["sha256"],
                                     "use_only_if_qualified_primary_reclaim_is_below_bytes": 100}}
    owner_spec = put(tmp_path / "handoff/owner.json", owner)
    campaign = root / "cold_archive/catalog/reclaims" / owner_spec["sha256"]
    campaign.mkdir(parents=True)
    audit_path = root / "backtest/model_market_disagreement_audit.jsonl"
    audit_path.parent.mkdir()
    audit_path.write_text("", encoding="utf-8")
    queue_path = root / "backtest/model_market_disagreement_review_queue.json"
    put(queue_path, {"source_audit_log_path": str(audit_path), "rows": []})
    state = {"status": "READY", "owner_approval_sha256": owner_spec["sha256"], "target_bytes": 100}
    case = SimpleNamespace(root=root, primary=primary, reserve=reserve, primary_spec=primary_spec,
                           reserve_spec=reserve_spec, owner=owner, owner_spec=owner_spec,
                           campaign=campaign, state=state, receipts=[], audit=audit_path, queue=queue_path)
    add_receipt(case, "first", row(1, 10), "primary", 0)
    return case


def run(case):
    class Guard:
        def admit(self): return True
        def account(self, count): pass
    with ExitStack() as stack:
        return budget.primary_capacity(
            request={"owner_approval": case.owner_spec, "proposal": case.reserve_spec},
            approval=case.owner, approval_sha256=case.owner_spec["sha256"], state=case.state,
            campaign=case.campaign, source_root=case.root, stack=stack, guard=Guard())


def replace_receipt(case, index=0):
    spec, receipt, entry_spec, entry = case.receipts[index]
    entry_spec.update(put(Path(entry_spec["path"]), entry, sealed=True))
    receipt["entry_sha256"] = entry_spec["sha256"]
    spec.update(put(Path(spec["path"]), receipt, sealed=True))
    if case.state["last_receipt_path"] == spec["path"]:
        case.state["last_receipt_sha256"] = spec["sha256"]


def test_unattempted_primary_is_counted_at_full_approved_allocation(capacity_case):
    result = run(capacity_case)
    assert result["qualified_primary_allocated_bytes_upper_bound"] == 90
    assert result["primary_reclaimed_allocated_bytes"] == 10
    assert result["unreclaimed_primary_allocated_bytes_upper_bound"] == 80
    assert result["unreclaimed_primary_file_count"] == 2
    assert result["source_payload_bytes_read"] == 0


def test_later_reserve_reclaim_does_not_inflate_primary_capacity(capacity_case):
    case = capacity_case
    add_receipt(case, "reserve", case.reserve["files"][0], "conditional_reserve", 10)
    result = run(case)
    assert result["qualified_primary_allocated_bytes_upper_bound"] == 90
    assert result["campaign_sequence"] == 2 and case.state["reclaimed_allocated_bytes"] == 30


def test_primary_that_can_still_reach_target_refuses(capacity_case):
    case = capacity_case
    _, receipt, _, entry = case.receipts[0]
    receipt["files"][0]["allocated_bytes"] = entry["files"][0]["allocated_bytes"] = 20
    receipt["reclaimed_allocated_bytes"] = case.state["reclaimed_allocated_bytes"] = 20
    replace_receipt(case)
    with pytest.raises(RuntimeError, match="ceiling can still reach"):
        run(case)


def test_current_queue_protection_excludes_only_its_remaining_primary_event(capacity_case):
    case = capacity_case
    event = case.primary["files"][2]["path"].split("/")[1]
    case.audit.write_text(json.dumps({"audit_key": "q1", "event_slug": event}) + "\n", encoding="utf-8")
    put(case.queue, {"source_audit_log_path": str(case.audit),
                     "rows": [{"case_count": 1, "sample_audit_keys": ["q1"]}]})
    result = run(case)
    assert result["qualified_primary_allocated_bytes_upper_bound"] == 50
    assert result["queue_protected_primary_file_count"] == 1
    assert result["queue_protected_primary_approved_allocated_bytes"] == 40
    assert len(result["queue_evidence"]) == 2


@pytest.mark.parametrize("fault", [
    "pointer_count", "pointer_total", "pointer_last_hash", "receipt_total", "history_gap",
    "wrong_owner", "native_identity", "allocation_increase", "member_hash", "wrong_kind",
    "changed_proposal", "missing_receipt", "wrong_campaign", "queue_missing_key", "queue_count",
    "unaccounted_archive_member",
])
def test_incomplete_or_inconsistent_primary_accounting_refuses(capacity_case, fault):
    case = capacity_case
    spec, receipt, entry_spec, entry = case.receipts[0]
    if fault == "pointer_count": case.state["sequence"] += 1
    elif fault == "pointer_total": case.state["reclaimed_allocated_bytes"] += 1
    elif fault == "pointer_last_hash": case.state["last_receipt_sha256"] = "a" * 64
    elif fault == "receipt_total":
        receipt["reclaimed_allocated_bytes"] += 1
        replace_receipt(case)
    elif fault == "history_gap":
        receipt["previous_reclaimed_allocated_bytes"] = 1
        replace_receipt(case)
    elif fault == "wrong_owner":
        receipt["owner_approval_sha256"] = "a" * 64
        replace_receipt(case)
    elif fault in {"native_identity", "allocation_increase"}:
        key, value = ("file_id", 999) if fault == "native_identity" else ("allocated_bytes", 41)
        receipt["files"][0][key] = entry["files"][0][key] = value
        if key == "allocated_bytes":
            receipt["reclaimed_allocated_bytes"] = case.state["reclaimed_allocated_bytes"] = value
        replace_receipt(case)
    elif fault == "member_hash":
        receipt["files"][0]["sha256"] = "a" * 64
        replace_receipt(case)
    elif fault == "unaccounted_archive_member":
        entry["files"].append({**row(2), "sha256": "d" * 64})
        replace_receipt(case)
    elif fault == "wrong_kind":
        receipt["selection_kind"] = "conditional_reserve"
        replace_receipt(case)
    elif fault == "changed_proposal": Path(case.primary_spec["path"]).write_text("{}", encoding="utf-8")
    elif fault == "missing_receipt": Path(spec["path"]).unlink()
    elif fault == "wrong_campaign": case.campaign = case.campaign.parent
    else:
        put(case.queue, {"source_audit_log_path": str(case.audit), "rows": [
            {"case_count": 2 if fault == "queue_count" else 1, "sample_audit_keys": ["missing"]}]})
    with pytest.raises((RuntimeError, ValueError, OSError, KeyError)):
        run(case)


def test_same_original_cannot_be_counted_in_two_receipts(capacity_case):
    case = capacity_case
    add_receipt(case, "duplicate", row(1, 10), "primary", 10)
    with pytest.raises(RuntimeError, match="source identity"):
        run(case)

@pytest.mark.skipif(os.name != "nt", reason="native Windows metadata pins")
def test_native_primary_budget_pins_complete_metadata_dependencies(capacity_case):
    result = run(capacity_case)
    assert result["qualified_primary_allocated_bytes_upper_bound"] == 90
    assert result["metadata_bytes_read"] > 0 and result["source_payload_bytes_read"] == 0
