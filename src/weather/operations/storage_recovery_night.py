"""Run one approved overnight segment through existing retained-file wrappers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time

from weather.operations import cold_snapshot_compression as compression
from weather.operations import storage_recovery_batch_plan as planner
from weather.operations import storage_recovery_inventory as metadata
from weather.operations import storage_recovery_night_contract as contract
from weather.operations import storage_recovery_night_evidence as evidence
from weather.operations import storage_recovery_night_steps as steps
from weather.operations.replay_cache_compression_admission import (
    observe_capture_admission, set_current_process_below_normal, process_memory_bytes,
)
from weather.paths import repo_path
from weather.schema_registry import schema_version


class SegmentStop(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(status)


class GroupSkipped(Exception):
    pass


class NightRunner:
    def __init__(self, plan, *, plan_path, plan_sha, segment, output,
                 now=lambda: datetime.now(timezone.utc), sleep=time.sleep,
                 admission=None, dispatch=steps.invoke):
        self.plan, self.plan_path, self.plan_sha = plan, Path(plan_path), plan_sha
        self.root, self.source = Path(plan["production_repo_root"]), Path(plan["source_root"])
        self.segment, self.output = segment, Path(output)
        self.now, self.sleep, self.dispatch = now, sleep, dispatch
        self.admission = admission or (lambda: observe_capture_admission(self.root, compression.check_resources))
        self.deadline = contract.segment_times(datetime.fromisoformat(plan["night_date"]).date(), segment)[1]
        self.baseline, self.baseline_bytes = contract.read_baseline(plan)
        self.rows, self.pending, self.reconcile_rows = [], None, []
        self.group_index = self.attempts = self.recoveries = self.input_bytes = self.output_bytes = 0
        self.completed_groups, self.events = [], []
        self.status_sequence, self.current_phase = 0, "PREPARING"
        self.last_admission = None

    def resume(self):
        if self.segment == "early":
            return
        previous = contract.night_root(self.plan) / "early"
        if not previous.exists():
            self.events.append({"event": "EARLY_NEVER_CREATED", "reclaim_credit": 0})
            return
        wrapper, _ = contract.read_json(previous / "wrapper-result.json", 2 * contract.MIB)
        if (wrapper.get("status") != "PASS" or wrapper.get("teardown_proved") is not True
                or wrapper.get("hard_stop") is not False or wrapper.get("plan_sha256") != self.plan_sha
                or wrapper.get("source_git_sha") != self.plan["source_git_sha"]
                or wrapper.get("execution_host_id") != self.plan["execution_host_id"]
                or wrapper.get("segment") != "early" or wrapper.get("deleted_files") != 0
                or wrapper.get("cleanup_eligible") is not False):
            raise ValueError("early segment lacks a complete matching teardown; no automatic restart")
        result, _ = contract.read_json(previous / "result.json", 2 * contract.MIB,
                                       contract.digest(wrapper.get("child_result_sha256")))
        if (result.get("status") not in contract.SAFE_TERMINALS or result.get("segment") != "early"
                or result.get("plan_sha256") != self.plan_sha or result.get("source_git_sha") != self.plan["source_git_sha"]
                or result.get("execution_host_id") != self.plan["execution_host_id"]
                or result.get("deleted_files") != 0 or result.get("cleanup_eligible") is not False):
            raise ValueError("early segment is not a safe continuation")
        ledger, _ = contract.read_json(previous / "verified-files.json", contract.MAX_LEDGER_BYTES,
                                       result["verified_ledger_sha256"])
        if (ledger.get("schema_version") != schema_version("storage_recovery_night_ledger")
                or ledger.get("plan_sha256") != self.plan_sha):
            raise ValueError("early ledger plan or schema mismatch")
        self.rows = ledger["files"]
        if contract.validate_ledger(self.rows) != result["night_verified_reclaimed_bytes"]:
            raise ValueError("early segment ledger differs from its receipt")
        steps.append_rows(self.baseline, self.rows)
        for field in ("group_index", "attempts", "recoveries", "input_bytes", "output_bytes"):
            value = result[field]
            if type(value) is not int or value < 0:
                raise ValueError("invalid predecessor counter")
            setattr(self, field, value)
        self.pending, self.reconcile_rows = result["pending"], result["reconcile_rows"]
        self.completed_groups = result["completed_groups"]
        if (not 0 <= self.group_index <= len(self.plan["groups"])
                or self.completed_groups != [g["name"] for g in self.plan["groups"][:self.group_index]]):
            raise ValueError("predecessor cursor skips an uncompleted group")
        self._bounds()

    def _bounds(self, kind=None, request=None):
        if (self.attempts >= self.plan["max_wrapper_attempts"]
                or self.recoveries >= self.plan["max_resource_recoveries"]
                or len(self.rows) >= self.plan["max_new_files"]
                or self.input_bytes >= self.plan["max_logical_input_bytes"]
                or self.output_bytes + 32 * contract.MIB > self.plan["receipt_budget_bytes"]):
            raise SegmentStop("BUDGET_COMPLETE")
        if kind == "apply":
            if (self.input_bytes + sum(f["size_bytes"] for f in request["files"]) > self.plan["max_logical_input_bytes"]
                    or len(self.rows) + len(request["files"]) > self.plan["max_new_files"]):
                raise SegmentStop("BUDGET_COMPLETE")

    def progress(self, phase):
        if os.name == "nt":
            memory = process_memory_bytes()
            if memory is None or max(memory.values()) > 256 * contract.MIB:
                raise ValueError("actual night controller memory exceeded 256 MiB or is unavailable")
        self.current_phase = phase
        self.status_sequence += 1
        value = {"schema_version": schema_version("storage_recovery_night_receipt"),
                 "plan_sha256": self.plan_sha, "segment": self.segment, "phase": phase,
                 "checked_at_utc": self.now().isoformat(), "group_index": self.group_index,
                 "attempts": self.attempts, "recoveries": self.recoveries,
                 "night_verified_reclaimed_bytes": sum(r["allocation_saving_bytes"] for r in self.rows),
                 "free_disk_bytes": shutil.disk_usage(self.root).free,
                 "pending_verification": self.pending is not None,
                 "uncredited_completed_files": len(self.reconcile_rows), "deleted_files": 0}
        temporary = self.output / f"progress-{self.status_sequence:06d}.tmp"
        contract.write_json(temporary, value)
        target = self.output / "progress.json"
        if target.exists():
            metadata.checked_stat(target, directory=False)
        os.replace(temporary, target)

    def wait_ready(self, required_seconds):
        stable = 0
        waited_for_resources = False
        while True:
            if (self.deadline - self.now()).total_seconds() < required_seconds:
                raise SegmentStop("RESOURCE_LIMITED" if waited_for_resources else "WINDOW_COMPLETE")
            observed = self.admission()
            self.last_admission = observed
            reasons = set(observed.get("reasons", []))
            if reasons - contract.MEMORY_REASONS:
                raise ValueError("capture or non-memory admission failure: " + ",".join(sorted(reasons)))
            ready = (observed.get("status") == "PASS" and observed["host_commit_percent"] < 66
                     and observed["available_memory_bytes"] >= int(4.5 * contract.GIB))
            waited_for_resources = waited_for_resources or not ready
            stable = stable + 1 if ready else 0
            if stable >= 3:
                return
            if not ready or stable == 1:
                self.progress("WAITING_FOR_STABLE_HEADROOM")
            self.sleep(5)

    def recover(self, reason, attempt=None):
        self.recoveries += 1
        contract.write_json(self.output / "steps" / f"recovery-{self.recoveries:03d}.json",
                            {"reason": reason, "attempt": str(attempt) if attempt else None,
                             "at_utc": self.now().isoformat(), "plan_sha256": self.plan_sha,
                             "pending_verification": self.pending is not None})
        self.progress("RESOURCE_PAUSE")
        self._bounds()
        self.sleep(15)

    def execute(self, kind, request):
        self._bounds(kind, request)
        # Apply leaves time for a fresh inventory and read-only reconciliation.
        self.wait_ready(630 if kind == "apply" else steps.KINDS[kind][2] + 45)
        _, observed_plan_sha = contract.read_json(self.plan_path, contract.MAX_PLAN_BYTES, self.plan_sha)
        if observed_plan_sha != self.plan_sha:
            raise ValueError("night plan changed")
        self.attempts += 1
        if kind == "apply":
            self.input_bytes += sum(f["size_bytes"] for f in request["files"])
        self.progress(kind.upper())
        outcome = self.dispatch(self.plan, segment=self.segment, index=self.attempts, kind=kind,
                                request=request, output_dir=self.output,
                                plan_sha256=self.plan_sha, deadline=self.deadline)
        self.output_bytes += outcome["output_bytes"]
        return outcome

    def context(self, wrapper_path, wrapper_sha):
        return {"schema_version": schema_version("cold_snapshot_compression_request"),
                "production_repo_root": str(self.root), "execution_host_id": self.plan["execution_host_id"],
                "operation": "compress_and_retain", "approved_by": self.plan["approved_by"],
                "approved_at_utc": self.now().isoformat(), "expires_at_utc": self.plan["expires_at_utc"],
                "inventory_wrapper_receipt": str(wrapper_path), "inventory_wrapper_sha256": wrapper_sha}

    def inventory(self, group):
        existing, absent = [], []
        metadata.validate_root(self.root / "data/snapshots")
        for relative in group["folders"]:
            try:
                metadata.checked_stat(self.root / "data" / relative, directory=True)
                existing.append(relative)
            except FileNotFoundError:
                absent.append(relative)
        if absent:
            self.events.append({"event": "MISSING_FOLDERS", "group": group["name"], "folders": absent,
                                "capacity_credit": 0})
        if not existing:
            if self.pending or self.reconcile_rows:
                raise ValueError("a group needing reconciliation disappeared")
            raise GroupSkipped("all named folders absent")
        while True:
            request = {"schema_version": schema_version("storage_recovery_inventory_request"),
                       "production_repo_root": str(self.root), "execution_host_id": self.plan["execution_host_id"],
                       "operation": "metadata_only", "approved_by": self.plan["approved_by"],
                       "approved_at_utc": self.now().isoformat(), "expires_at_utc": self.plan["expires_at_utc"],
                       "folders": existing, "traversal_scope": "immediate_files"}
            outcome = self.execute("inventory", request)
            if outcome["busy"]:
                self.recover("shared lease busy before dispatch")
                continue
            if outcome["wrapper"]["status"] != "PASS":
                if contract.memory_refusal(steps.failure_error(outcome)):
                    self.recover(steps.failure_error(outcome), outcome["attempt"])
                    continue
                result = outcome.get("result") or {}
                if result.get("status") == "PARTIAL" and not self.pending and not self.reconcile_rows:
                    raise GroupSkipped("partial inventory supplies no compression authority")
                raise ValueError("inventory failed outside approved resource recovery")
            context = self.context(outcome["attempt"] / "wrapper-result.json", outcome["wrapper_sha"])
            manifest = compression.read_inventory(context, [], production_root=self.root,
                                                   source_git_sha=self.plan["source_git_sha"])
            credited = [r for r in self.baseline + self.rows if "/".join(r["path"].split("/")[:2]) in group["folders"]]
            evidence.reconcile_inventory(credited + self.reconcile_rows, manifest)
            if self.reconcile_rows:
                self.add_rows(self.reconcile_rows)
                self.reconcile_rows = []
            return context, manifest

    def add_rows(self, rows):
        steps.append_rows(self.baseline + self.rows, rows)
        self.rows.extend(rows)
        if len(self.rows) > self.plan["max_new_files"]:
            raise ValueError("verified file bound exceeded")

    def saved_rows(self, outcome, completed):
        return [evidence.ledger_row(
            row, original_attempt=outcome["attempt"].name,
            before_hash=outcome["journal_hashes"][f"{i:03d}-before.json"],
            after_hash=outcome["journal_hashes"][f"{i:03d}-after.json"])
            for i, row in enumerate(completed)]

    def apply(self, request):
        if self.pending or self.reconcile_rows:
            raise ValueError("unreconciled evidence blocks all new compression")
        outcome = self.execute("apply", request)
        if outcome["busy"]:
            self.recover("shared lease busy before dispatch")
            return False, None
        completed, pending = evidence.inspect_apply(
            request, outcome["wrapper"], outcome["result"], outcome["journals"],
            request_sha=outcome["request_sha"], plan=self.plan)
        added = self.saved_rows(outcome, completed)
        if outcome["wrapper"]["status"] == "PASS":
            self.add_rows(added)
            return True, outcome
        error = steps.failure_error(outcome)
        if not contract.memory_refusal(error):
            raise ValueError("compression failed outside the memory-only recovery policy")
        self.reconcile_rows = added
        if pending:
            ordinal = pending["ordinal"]
            self.pending = {**pending, "original_attempt": outcome["attempt"].name,
                            "preimage_receipt": str(outcome["attempt"] / f"{ordinal:03d}-before.json"),
                            "preimage_sha256": outcome["journal_hashes"][f"{ordinal:03d}-before.json"],
                            "predecessor_wrapper_sha256": outcome["wrapper_sha"]}
        self.recover(error, outcome["attempt"])
        return False, None

    def verify_pending(self, context, manifest):
        if self.pending is None:
            return
        pending = self.pending
        rows = [r for r in manifest["files"] if r["path"] == pending["path"]]
        if len(rows) != 1:
            raise ValueError("pending retained file is absent from fresh inventory")
        request = {**context, "schema_version": schema_version("cold_snapshot_verification_request"),
                   "operation": "verify_retained", "files": rows,
                   **{k: pending[k] for k in ("preimage_receipt", "preimage_sha256", "predecessor_wrapper_sha256")}}
        while True:
            outcome = self.execute("verify", request)
            if outcome["busy"]:
                self.recover("shared lease busy before verification")
                continue
            if outcome["wrapper"]["status"] != "PASS":
                if not contract.memory_refusal(steps.failure_error(outcome)):
                    raise ValueError("retained verification failed outside the memory-only policy")
                self.recover(steps.failure_error(outcome), outcome["attempt"])
                continue
            row = evidence.inspect_verification(request, outcome["wrapper"], outcome["result"],
                                                pending["preimage"], request_sha=outcome["request_sha"],
                                                plan=self.plan)
            if row["verified_reclaimed_bytes"] > 0:
                self.add_rows([evidence.ledger_row(
                    row, original_attempt=pending["original_attempt"],
                    before_hash=pending["preimage_sha256"], after_hash=outcome["result_sha"],
                    verification_attempt=outcome["attempt"].name)])
            self.pending = None
            return

    def process_group(self, group):
        while True:
            context, manifest = self.inventory(group)
            self.verify_pending(context, manifest)
            try:
                pilot_plan = planner.prepare(manifest, context, production_root=self.root,
                                             now=self.now(), mode="pilot")
            except ValueError as exc:
                if str(exc) != "no eligible candidates at the requested cursor":
                    raise
                return
            pilot_request = pilot_plan["requests"][0]
            dry = self.execute("dry", pilot_request)
            if dry["busy"]:
                self.recover("shared lease busy before dry run")
                continue
            if dry["wrapper"]["status"] != "PASS":
                if not contract.memory_refusal(steps.failure_error(dry)):
                    raise ValueError("pilot dry run failed outside the memory-only policy")
                self.recover(steps.failure_error(dry), dry["attempt"])
                continue
            if ((dry.get("result") or {}).get("status") != "PASS"
                    or dry["wrapper"].get("reclaimed_bytes") != 0
                    or dry["result"].get("reclaimed_bytes") != 0
                    or len(dry["result"].get("results", [])) != 1):
                raise ValueError("dry-run proof does not cover the exact pilot")
            dry_row = dry["result"]["results"][0]
            if (dry_row.get("path") != pilot_request["files"][0]["path"]
                    or dry_row.get("status") != "PLANNED" or dry_row.get("reclaimed_bytes") != 0):
                raise ValueError("dry-run row differs from its pilot")
            evidence.expected_native(pilot_request["files"][0], dry_row["before"])
            passed, pilot = self.apply(pilot_request)
            if not passed:
                continue
            pilot_paths = planner.pilot_files(
                pilot["attempt"] / "wrapper-result.json", pilot["wrapper_sha"],
                production_root=self.root, source_git_sha=self.plan["source_git_sha"], context=context)
            cursor, interrupted = 0, False
            while True:
                if self.target_met():
                    return
                try:
                    expansion = planner.prepare(manifest, context, production_root=self.root, now=self.now(),
                                                mode="expand", start_index=cursor, pilot_paths=pilot_paths)
                except ValueError as exc:
                    if str(exc) != "no eligible candidates at the requested cursor":
                        raise
                    break
                for request in expansion["requests"]:
                    passed, _ = self.apply(request)
                    if not passed:
                        interrupted = True
                        break
                    if self.target_met():
                        return
                if interrupted or not expansion["has_more"]:
                    break
                cursor = expansion["next_index"]
            # Fresh inventory independently reconciles this group's allocation
            # and removes every already-compressed file before any new pilot.
            if interrupted:
                continue

    def target_met(self):
        saved = self.baseline_bytes + sum(r["allocation_saving_bytes"] for r in self.rows)
        return (not self.pending and not self.reconcile_rows
                and saved >= self.plan["target_new_reclaimed_bytes"]
                and shutil.disk_usage(self.root).free >= self.plan["target_free_disk_bytes"])

    def run(self):
        status, error = "CANDIDATES_EXHAUSTED", None
        try:
            self.resume()
            while self.group_index < len(self.plan["groups"]):
                if self.target_met():
                    status = "TARGET_MET"
                    break
                group = self.plan["groups"][self.group_index]
                try:
                    self.process_group(group)
                except GroupSkipped as exc:
                    self.events.append({"event": "GROUP_SKIPPED", "group": group["name"], "reason": str(exc),
                                        "capacity_credit": 0})
                if self.target_met():
                    status = "TARGET_MET"
                    break
                self.completed_groups.append(group["name"])
                self.group_index += 1
        except SegmentStop as exc:
            status = exc.status
        except Exception as exc:
            status, error = "BLOCKED", f"{type(exc).__name__}: {exc}"
        ledger = {"schema_version": schema_version("storage_recovery_night_ledger"),
                  "plan_sha256": self.plan_sha, "files": self.rows}
        ledger_sha = contract.write_json(self.output / "verified-files.json", ledger, contract.MAX_LEDGER_BYTES)
        saved = contract.validate_ledger(self.rows)
        result = {
            "schema_version": schema_version("storage_recovery_night_receipt"),
            "status": status, "error": error, "segment": self.segment, "plan_sha256": self.plan_sha,
            "source_git_sha": self.plan["source_git_sha"], "execution_host_id": self.plan["execution_host_id"],
            "completed_at_utc": self.now().isoformat(), "group_index": self.group_index,
            "completed_groups": self.completed_groups, "attempts": self.attempts, "recoveries": self.recoveries,
            "input_bytes": self.input_bytes, "output_bytes": self.output_bytes, "events": self.events,
            "verified_file_count": len(self.rows), "night_verified_reclaimed_bytes": saved,
            "baseline_verified_reclaimed_bytes": self.baseline_bytes,
            "cumulative_verified_reclaimed_bytes": saved + self.baseline_bytes,
            "verified_ledger_sha256": ledger_sha, "pending": self.pending, "reconcile_rows": self.reconcile_rows,
            "unverified_files": None if status == "BLOCKED" else int(self.pending is not None),
            "free_disk_bytes": shutil.disk_usage(self.root).free, "target_met": self.target_met(),
            "final_admission": self.last_admission, "deleted_files": 0, "cleanup_eligible": False,
        }
        contract.write_json(self.output / "result.json", result)
        self.progress(status)
        print(json.dumps({k: result[k] for k in ("status", "night_verified_reclaimed_bytes", "free_disk_bytes", "target_met")}))
        return 1 if status == "BLOCKED" else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("production-repo-root", "plan", "plan-sha256", "source-git-sha", "output-root"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--segment", choices=("early", "late"), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        root, source, output = metadata.validate_root(Path(args.production_repo_root)), repo_path(), Path(args.output_root)
        plan, _ = contract.read_json(args.plan, contract.MAX_PLAN_BYTES, args.plan_sha256)
        now = datetime.now(timezone.utc)
        contract.validate_plan(plan, production_root=root, source_root=source, source_git_sha=args.source_git_sha, now=now)
        steps.runtime_owner(source, plan["execution_host_id"])
        steps.source_clean(source, plan["source_git_sha"])
        if output.parent != contract.night_root(plan) or output.name not in {"early", "late", "preflight"}:
            raise ValueError("night output differs from its exact plan")
        metadata.validate_root(output)
        set_current_process_below_normal()
        wrapper_deadline = contract.utc(os.environ[contract.ENV + "DEADLINE_UTC"])
        if args.preflight_only:
            if output.name != "preflight" or os.environ.get(contract.ENV + "PREFLIGHT") != "1":
                raise ValueError("preflight is not bound to the wrapper's read-only mode")
            rows, total = contract.read_baseline(plan)
            result = {"schema_version": schema_version("storage_recovery_night_receipt"), "status": "PREFLIGHT_PASS",
                      "plan_sha256": args.plan_sha256, "source_git_sha": args.source_git_sha,
                      "execution_host_id": plan["execution_host_id"], "verified_baseline_files": len(rows),
                      "verified_baseline_reclaimed_bytes": total, "groups": len(plan["groups"]),
                      "source_payload_bytes_read": 0, "source_files_changed": 0, "deleted_files": 0,
                      "cleanup_eligible": False}
            contract.write_json(output / "result.json", result)
            return 0
        start, end = contract.segment_times(datetime.fromisoformat(plan["night_date"]).date(), args.segment)
        if (output.name != args.segment or not start <= now <= start + contract.timedelta(seconds=75)
                or wrapper_deadline != end or os.environ.get(contract.ENV + "PREFLIGHT") != "0"):
            raise ValueError("night segment is outside its exact dispatch window")
        for directory in ("requests", "steps"):
            (output / directory).mkdir()
        return NightRunner(plan, plan_path=args.plan, plan_sha=args.plan_sha256,
                           segment=args.segment, output=output).run()
    except Exception as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
