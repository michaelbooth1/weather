"""Deterministic one-night recovery authority and interruption state-machine tests."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from weather.operations import cold_snapshot_compression as compression
from weather.operations import storage_recovery_batch_plan as planner
from weather.operations import storage_recovery_night as subject
from weather.operations import storage_recovery_night_contract as contract
from weather.operations import storage_recovery_night_evidence as evidence
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 9, 5, tzinfo=timezone.utc)
FOLDER = "snapshots/highest-temperature-in-toronto-on-july-1-2026"
SOURCE, HOST = "a" * 40, "b" * 64
MEMORY_ERROR = "capture admission refused: commit_not_below_70_percent"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    return contract.write_json(path, value, contract.MAX_LEDGER_BYTES)


def fixture_plan(root):
    handoff = root / "scratch/handoffs"
    ledger = handoff / "baseline-files.json"
    ledger_sha = save(ledger, {"files": [], "production_repo_root": str(root),
        "verified_new_reclaimed_bytes": 0, "verified_file_count": 0, "deleted_files": 0, "cleanup_eligible": False})
    receipt = handoff / "baseline.json"
    receipt_sha = save(receipt, {"production_repo_root": str(root),
        "verified_new_reclaimed_bytes": 0, "verified_file_count": 0, "verified_file_ledger_sha256": ledger_sha,
        "unmatched_preimages": 0, "unverified_compressed_files": 0, "active_recovery_processes": 0, "source_files_deleted": 0})
    return {"schema_version": schema_version("storage_recovery_night_plan"),
        "plan_id": "capacity-20260909-test", "night_date": "2026-09-09", "approved_by": "fixture owner",
        "approved_at_utc": (NOW - timedelta(days=1)).isoformat(), "expires_at_utc": "2026-09-09T13:00:00+00:00",
        "production_repo_root": str(root), "source_root": str(root), "source_git_sha": SOURCE,
        "execution_host_id": HOST, "baseline_receipt": str(receipt), "baseline_receipt_sha256": receipt_sha,
        "baseline_ledger": str(ledger), "baseline_ledger_sha256": ledger_sha,
        "groups": [{"name": "2026-07-01", "folders": [FOLDER]}],
        "target_new_reclaimed_bytes": contract.GIB, "target_free_disk_bytes": 1,
        "max_new_files": 100, "max_wrapper_attempts": 100, "max_resource_recoveries": 10,
        "max_logical_input_bytes": contract.GIB, "receipt_budget_bytes": 64 * contract.MIB,
        "allow_resource_recovery": True}


def validate(plan, root, now=NOW):
    return contract.validate_plan(plan, production_root=root, source_root=root, source_git_sha=SOURCE, now=now)


def test_plan_is_fixed_to_one_night_with_separate_tiering_gap(tmp_path):
    plan = fixture_plan(tmp_path)
    assert validate(plan, tmp_path) == plan
    assert contract.segment_times(datetime(2026, 9, 9).date(), "early") == (
        datetime(2026, 9, 9, 4, 30, tzinfo=timezone.utc), datetime(2026, 9, 9, 8, 42, tzinfo=timezone.utc))
    assert contract.segment_times(datetime(2026, 9, 9).date(), "late")[0].hour == 10


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(allow_resource_recovery=False),
    lambda p: p.update(max_new_files=True),
    lambda p: p.update(max_wrapper_attempts=contract.MAX_ATTEMPTS + 1),
    lambda p: p.update(source_git_sha="d" * 40),
    lambda p: p.update(expires_at_utc="2026-09-10T13:00:00Z"),
    lambda p: p.update(approved_at_utc="2026-09-09T04:31:00Z"),
    lambda p: p.update(extra_permission="delete"),
    lambda p: p["groups"].append(deepcopy(p["groups"][0])),
    lambda p: p["groups"][0].update(name="2026-07-02"),
    lambda p: p["groups"][0].update(folders=["snapshots/highest-temperature-in-toronto-on-september-1-2026"]),
])
def test_invalid_approval_and_scope_fail_closed(tmp_path, mutate):
    plan = fixture_plan(tmp_path)
    mutate(plan)
    with pytest.raises(ValueError):
        validate(plan, tmp_path)


def test_baseline_requires_complete_reconciliation_and_unchanged_hashes(tmp_path):
    plan = fixture_plan(tmp_path)
    assert contract.read_baseline(plan) == ([], 0)
    Path(plan["baseline_receipt"]).write_text("{}")
    with pytest.raises(ValueError, match="SHA-256"):
        contract.read_baseline(plan)


@pytest.mark.parametrize("error,accepted", [
    (MEMORY_ERROR, True),
    ("capture admission refused: physical_memory_below_4_gib,commit_not_below_70_percent", True),
    ("capture admission refused: capture_unhealthy:snapshot", False),
    (MEMORY_ERROR + ",capture_loop_evidence_missing", False),
    ("compression deadline or request expiry reached", False),
    ("capture admission refused: ", False),
    (None, False),
])
def test_only_explicit_memory_failures_can_recover(error, accepted):
    assert contract.memory_refusal(error) is accepted


class Simulation:
    """Real request planning/evidence parsing over in-memory file metadata."""
    def __init__(self, root, fault=None):
        self.root, self.fault, self.calls = root, fault, []
        self.failed = False
        self.before = {}
        self.current = {}
        for i in range(2):
            path = FOLDER + f"/{i}.jsonl"
            native = {"size_bytes": 2 * contract.MIB, "allocation_bytes": 2 * contract.MIB,
                      "mtime_ns": int((NOW - timedelta(days=45)).timestamp()) * 10**9,
                      "volume_serial": 3, "file_index": i + 1, "creation_filetime": 100 + i,
                      "attributes": 32, "compression_format": 0}
            self.before[path] = native
            self.current[path] = dict(native)
        (root / "data" / FOLDER).mkdir(parents=True)

    def candidate(self, path):
        row = self.current[path]
        return {"path": path, "size_bytes": row["size_bytes"], "allocated_bytes": row["allocation_bytes"],
                "mtime_ns": str(row["mtime_ns"]), "device": str(row["volume_serial"]),
                "file_id": str(row["file_index"]), "attributes": row["attributes"]}

    def __call__(self, plan, *, segment, index, kind, request, output_dir, plan_sha256, deadline):
        self.calls.append(kind)
        request_sha = hashlib.sha256(json.dumps(request).encode()).hexdigest()
        family = "storage_recovery_inventory" if kind == "inventory" else "cold_snapshot_compression"
        attempt = self.root / "scratch" / family / f"fixture-{segment}-{index}-{kind}"
        common = {"source_git_sha": SOURCE, "execution_host_id": HOST, "request_sha256": request_sha,
                  "deleted_files": 0, "cleanup_eligible": False, "owner_approved_exception": ""}
        wrapper = {**common, "status": "PASS", "teardown_proved": True, "hard_stop": False, "reclaimed_bytes": 0}
        journals, rows = {}, []
        result = {**common, "status": "PASS", "reclaimed_bytes": 0}
        if kind == "inventory":
            data = {**common, "schema_version": schema_version("storage_recovery_inventory"), "status": "PASS",
                    "data_root": str(self.root / "data"), "traversal_scope": "immediate_files",
                    "folders": [{"path": FOLDER, "status": "COMPLETE", "traversal_scope": "immediate_files"}],
                    "files": [self.candidate(path) for path in self.current]}
            result.update(schema_version=schema_version("storage_recovery_inventory_receipt"),
                          inventory_sha256=save(attempt / "inventory.json", data))
        else:
            wrapper["apply"] = kind == "apply"
            result.update(schema_version=schema_version("cold_snapshot_compression_receipt"),
                          apply=kind == "apply", inventory_wrapper_sha256=request["inventory_wrapper_sha256"])
            for i, candidate in enumerate(request["files"]):
                path = candidate["path"]
                before = dict(self.before[path])
                if kind == "dry":
                    rows.append({"path": path, "before": before, "status": "PLANNED", "reclaimed_bytes": 0})
                    continue
                after = {**before, "allocation_bytes": contract.MIB, "attributes": 0x820, "compression_format": 2}
                row = {"path": path, "before": before, "after": after, "sha256": "c" * 64,
                       "action": "COMPRESS_AND_RETAIN", "status": "VERIFIED", "reclaimed_bytes": contract.MIB}
                if kind == "verify":
                    wrapper.update(verify_retained=True, source_files_changed=0, verified_reclaimed_bytes=contract.MIB)
                    result.update(schema_version=schema_version("cold_snapshot_verification_receipt"),
                        verify_retained=True, source_files_changed=0, verified_reclaimed_bytes=contract.MIB,
                        preimage_sha256=request["preimage_sha256"],
                        predecessor_wrapper_sha256=request["predecessor_wrapper_sha256"])
                    row.update(action="VERIFY_RETAINED", status="VERIFIED_RETAINED",
                               reclaimed_bytes=0, verified_reclaimed_bytes=contract.MIB, source_files_changed=0)
                    rows.append(row)
                    continue
                journals[f"{i:03d}-before.json"] = {
                    **result, "path": path, "before": before, "sha256": "c" * 64, "action": "COMPRESS_AND_RETAIN"}
                self.current[path] = after
                if self.fault and path.endswith("/1.jsonl") and not self.failed:
                    self.failed = True
                    wrapper["status"] = "FAILED"
                    if self.fault == "hard_stop":
                        wrapper["hard_stop"] = True
                    result.update(status="FAILED_RETAIN_AND_INSPECT",
                                  error=MEMORY_ERROR if self.fault in {"memory", "completed_memory"} else "hash mismatch")
                    if self.fault != "completed_memory":
                        break
                journals[f"{i:03d}-after.json"] = {**result, **row}
                rows.append(row)
            result.update(results=rows, reclaimed_bytes=sum(row["reclaimed_bytes"] for row in rows))
            wrapper["reclaimed_bytes"] = result["reclaimed_bytes"]
        result_sha = save(attempt / "result.json", result)
        wrapper["child_result_sha256"] = result_sha
        wrapper_sha = save(attempt / "wrapper-result.json", wrapper)
        hashes = {name: save(attempt / name, row) for name, row in journals.items()}
        return {"busy": False, "wrapper": wrapper, "wrapper_sha": wrapper_sha,
                "result": result, "result_sha": result_sha, "refusal": None, "journals": journals,
                "journal_hashes": hashes, "request": request, "request_sha": request_sha,
                "attempt": attempt, "output_bytes": 8192}


def runner_fixture(root, monkeypatch, fault=None, segment="early"):
    monkeypatch.setattr(subject, "process_memory_bytes", lambda: {"private_bytes": 64 * contract.MIB})
    monkeypatch.setattr(compression, "PinnedNtfsDirectory", lambda path: nullcontext())
    monkeypatch.setattr(planner, "PinnedNtfsDirectory", lambda path: nullcontext())
    plan = fixture_plan(root)
    simulation = Simulation(root, fault)
    path = root / "scratch/handoffs/night.json"
    sha = save(path, plan)
    output = contract.night_root(plan) / segment
    (output / "requests").mkdir(parents=True)
    (output / "steps").mkdir()
    runner = subject.NightRunner(plan, plan_path=path, plan_sha=sha, segment=segment, output=output,
        now=lambda: NOW, sleep=lambda seconds: None, dispatch=simulation,
        admission=lambda: {"status": "PASS", "reasons": [], "host_commit_percent": 60,
                           "available_memory_bytes": 6 * contract.GIB})
    return runner, simulation


@pytest.mark.parametrize("fault", [None, "memory", "completed_memory"])
def test_success_and_memory_recovery_count_each_identity_once(tmp_path, monkeypatch, fault):
    runner, simulation = runner_fixture(tmp_path, monkeypatch, fault)
    assert runner.run() == 0
    result = json.loads((runner.output / "result.json").read_text())
    assert result["status"] == "CANDIDATES_EXHAUSTED"
    assert result["night_verified_reclaimed_bytes"] == 2 * contract.MIB
    assert result["verified_file_count"] == 2
    assert result["pending"] is None and result["reconcile_rows"] == []
    assert result["target_met"] is False and result["deleted_files"] == 0
    assert ("verify" in simulation.calls) is (fault == "memory")
    if fault:
        assert result["recoveries"] == 1


@pytest.mark.parametrize("fault", ["hash", "hard_stop"])
def test_unknown_or_uncontained_failure_stops_without_retry(tmp_path, monkeypatch, fault):
    runner, simulation = runner_fixture(tmp_path, monkeypatch, fault)
    assert runner.run() == 1
    result = json.loads((runner.output / "result.json").read_text())
    assert result["status"] == "BLOCKED" and result["unverified_files"] is None
    assert result["verified_file_count"] == 1 and result["recoveries"] == 0
    assert simulation.calls[-1] == "apply"


def test_memory_wait_ends_without_dispatch_at_the_segment_reserve(tmp_path, monkeypatch):
    runner, simulation = runner_fixture(tmp_path, monkeypatch)
    now = [runner.deadline - timedelta(seconds=230)]
    runner.now = lambda: now[0]
    runner.sleep = lambda seconds: now.__setitem__(0, now[0] + timedelta(seconds=seconds))
    runner.admission = lambda: {"status": "BLOCK", "reasons": ["commit_not_below_70_percent"],
        "host_commit_percent": 71, "available_memory_bytes": 6 * contract.GIB}
    assert runner.run() == 0
    assert not simulation.calls
    assert json.loads((runner.output / "result.json").read_text())["status"] == "RESOURCE_LIMITED"


def test_duplicate_ledger_identity_is_never_credited(tmp_path, monkeypatch):
    runner, _ = runner_fixture(tmp_path, monkeypatch)
    assert runner.run() == 0
    with pytest.raises(ValueError, match="duplicate"):
        contract.validate_ledger(runner.rows + [deepcopy(runner.rows[0])])


def test_late_refuses_an_existing_early_directory_without_terminal_proof(tmp_path, monkeypatch):
    runner, simulation = runner_fixture(tmp_path, monkeypatch, segment="late")
    (contract.night_root(runner.plan) / "early").mkdir()
    assert runner.run() == 1
    assert not simulation.calls


def test_late_reads_only_a_hash_bound_safe_early_ledger(tmp_path, monkeypatch):
    runner, simulation = runner_fixture(tmp_path, monkeypatch)
    assert runner.run() == 0
    result_path = runner.output / "result.json"
    save(runner.output / "wrapper-result.json", {"status": "PASS", "teardown_proved": True, "hard_stop": False,
        "plan_sha256": runner.plan_sha, "source_git_sha": SOURCE, "execution_host_id": HOST, "segment": "early",
        "deleted_files": 0, "cleanup_eligible": False, "child_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()})
    late_output = contract.night_root(runner.plan) / "late"
    (late_output / "requests").mkdir(parents=True)
    (late_output / "steps").mkdir()
    late = subject.NightRunner(runner.plan, plan_path=runner.plan_path, plan_sha=runner.plan_sha,
        segment="late", output=late_output, now=lambda: NOW, sleep=lambda seconds: None, dispatch=simulation)
    late.resume()
    assert len(late.rows) == 2 and late.group_index == 1
    (runner.output / "verified-files.json").write_text("{}")
    with pytest.raises(ValueError, match="SHA-256"):
        late.resume()
