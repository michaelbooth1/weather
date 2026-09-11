"""Immutable phase journal: a started mutation is never dispatched twice."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import math
import time

from weather.operations import production_cold_archive_stage as archive
from weather.schema_registry import schema_version
from weather.operations import cold_archive_catalog as catalog

PHASES = ("stage", "copy", "encrypt", "upload", "download", "restore",
          "publish", "recovery", "workstation_cleanup", "reclaim", "backup")
QUALIFICATION_BATCHES = 3


class CampaignPaused(RuntimeError):
    """A durable stopping point; retained claims distinguish uncertain actions."""



def utc(value):
    if not isinstance(value, str):
        raise ValueError("explicit UTC timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs an explicit timezone")
    return parsed.astimezone(timezone.utc)


def active_window(config, now):
    matches = [row for row in config["windows"] if utc(row["start"]) <= now < utc(row["end"])]
    if len(matches) != 1:
        raise CampaignPaused("outside the explicitly bound campaign execution windows")
    return matches[0]

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def record(path, value):
    envelope = {"schema_version": schema_version("cold_archive_campaign_record"), "document": value}
    return catalog._write_record(path, envelope)[1]


def read_record(path):
    value, digest = archive._load(path)
    archive._check_seal(value, "receipt_hash")
    if value.get("schema_version") != schema_version("cold_archive_campaign_record"):
        raise ValueError("campaign journal schema differs")
    return value["document"], digest


def remaining_chunks(plan, completed_files):
    """Use existing approved chunks; isolate every partially completed chunk."""
    archive._check_seal(plan, "plan_hash")
    known = set(completed_files)
    all_rows = archive._rows([row for chunk in plan["chunks"] for row in chunk["files"]])
    if not known <= {row["path"] for row in all_rows}:
        raise ValueError("completed sources are outside the approved plan")
    ready, isolated = [], []
    for chunk in plan["chunks"]:
        overlap = [row for row in chunk["files"] if row["path"] in known]
        if overlap:
            isolated.append({
                "chunk_id": chunk["chunk_id"], "completed_files": len(overlap),
                "remaining_allocated_bytes": sum(
                    row["allocated_bytes"] for row in chunk["files"] if row["path"] not in known)})
        else:
            ready.append(chunk)
    return ready, isolated


class BatchJournal:
    def __init__(self, root, binding):
        self.root, self.binding = Path(root), dict(binding)
        if not self.root.exists():
            self.root.mkdir()
            record(self.root / "binding.json", self.binding)
        elif read_record(self.root / "binding.json")[0] != self.binding:
            raise ValueError("batch journal binding changed")

    def run(self, adapter, *, stop_requested=lambda: False):
        completed = {}
        for index, phase in enumerate(PHASES):
            prefix = self.root / f"{index:02d}-{phase}"
            claim_path = prefix.with_suffix(".claim.json")
            done_path = prefix.with_suffix(".done.json")
            if done_path.exists():
                done, _ = read_record(done_path)
                adapter.verify(phase, done["evidence"])
                completed[phase] = done
                continue
            if stop_requested():
                raise CampaignPaused("stop requested at a completed phase boundary")
            if claim_path.exists():
                claim, _ = read_record(claim_path)
                evidence = adapter.recover(phase, claim, completed)
                if evidence is None:
                    raise CampaignPaused("started phase needs reconciliation: " + phase)
                started = claim["started_monotonic"]
            else:
                # Admission waits are outside a started mutation and its phase timer.
                adapter.admit(phase, completed)
                claim = {**self.binding, "phase": phase, "started_at_utc": utc_now(),
                         "started_monotonic": time.monotonic()}
                record(claim_path, claim)
                started = claim["started_monotonic"]
                evidence = adapter.execute(phase, claim, completed)
            adapter.verify(phase, evidence)
            # Runtime is measured by the phase's own retained receipt on recovery.
            elapsed = evidence.get("elapsed_seconds", max(0, time.monotonic() - started))
            done = {**self.binding, "phase": phase, "status": "PASS", "evidence": evidence,
                    "elapsed_seconds": elapsed, "completed_at_utc": utc_now()}
            record(done_path, done)
            completed[phase] = done
        return completed


def qualification(completed_batches):
    """Three measured large batches must fit each phase with 20 percent margin."""
    if len(completed_batches) < QUALIFICATION_BATCHES:
        return False
    for batch in completed_batches[:QUALIFICATION_BATCHES]:
        if batch["logical_bytes"] < 900 * archive.MIB:
            raise CampaignPaused("qualification requires a real large chunk")
        for phase in PHASES:
            evidence = batch["phases"][phase]["evidence"]
            if evidence.get("deadline_seconds") is not None and (
                    evidence["elapsed_seconds"] > 0.8 * evidence["deadline_seconds"]):
                raise CampaignPaused("phase lacks measured 20 percent margin: " + phase)
    return True


def remaining_estimate(completed_batches, remaining_bytes):
    """Conservative active-work estimate from the last three real batches."""
    if type(remaining_bytes) is not int or remaining_bytes < 0:
        raise ValueError("remaining source bytes must be a nonnegative integer")
    if not qualification(completed_batches):
        return None
    ratios = []
    for batch in completed_batches[-QUALIFICATION_BATCHES:]:
        allocated = batch["reclaimed_allocated_bytes"]
        elapsed = sum(row["elapsed_seconds"] for row in batch["phases"].values())
        if type(allocated) is not int or allocated <= 0 or not math.isfinite(elapsed) or elapsed <= 0:
            raise CampaignPaused("measured batch throughput is invalid")
        ratios.append(elapsed / allocated)
    seconds_per_byte = max(ratios)
    return {
        "remaining_source_bytes": remaining_bytes,
        "active_seconds_estimate": math.ceil(remaining_bytes * seconds_per_byte * 1.2),
        "measured_source_bytes_per_second": 1 / seconds_per_byte,
        "measured_batches": QUALIFICATION_BATCHES,
        "excludes_resource_and_schedule_waits": True,
    }
