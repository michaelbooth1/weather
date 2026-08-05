"""Durable handoff from the observation watcher to snapshot capture.

The observation watcher owns trigger detection, but it must not run the much
heavier model snapshot inline.  This file-backed spool lets the existing
snapshot supervisor claim that work under its normal worker and memory limits.
One JSON file is one immutable trigger request; directory renames are the state
transitions, so a process exit cannot silently erase queued work.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from weather.operations.supervisor import atomic_write_json
from weather.paths import data_path
from weather.schema_registry import schema_version


DEFAULT_TRIGGER_QUEUE_ROOT = data_path() / "snapshots" / "triggered_snapshot_queue"
PENDING_DIR = "pending"
INFLIGHT_DIR = "inflight"
COMPLETED_DIR = "completed"
ACKNOWLEDGED_DIR = "acknowledged"
ACK_TOMBSTONE_LIMIT = 4096
QUEUE_SCHEMA_VERSION = schema_version("observation_trigger")


def _utc_now():
    return datetime.now(timezone.utc)


def _queue_root(queue_root=None):
    return Path(queue_root or DEFAULT_TRIGGER_QUEUE_ROOT)


def _state_dir(queue_root, state):
    path = _queue_root(queue_root) / state
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_job(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _work_id(market_id, target_date, event_slug, trigger_context):
    current = (trigger_context or {}).get("current_observation") or {}
    identity = {
        "market_id": market_id,
        "target_date": target_date,
        "event_slug": event_slug,
        "current_captured_at_utc": current.get("captured_at_utc"),
        "triggers": (trigger_context or {}).get("triggers") or [],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _known_path(queue_root, work_id):
    root = _queue_root(queue_root)
    for state in (PENDING_DIR, INFLIGHT_DIR, COMPLETED_DIR, ACKNOWLEDGED_DIR):
        path = root / state / f"{work_id}.json"
        if path.exists():
            return state, path
    return None, None


def enqueue_triggered_snapshot(
    *,
    market_id,
    target_date,
    event_slug,
    trigger_context,
    queue_root=None,
    now=None,
):
    """Persist one trigger request before returning to the watcher loop."""

    root = _queue_root(queue_root)
    work_id = _work_id(market_id, target_date, event_slug, trigger_context)
    state, existing = _known_path(root, work_id)
    if existing is not None:
        return {
            "work_id": work_id,
            "state": state,
            "path": str(existing),
            "deduplicated": True,
        }
    queued_at = now or _utc_now()
    if queued_at.tzinfo is None:
        queued_at = queued_at.replace(tzinfo=timezone.utc)
    job = {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "record_type": "triggered_snapshot_work",
        "work_id": work_id,
        "market_id": market_id,
        "target_date": str(target_date) if target_date else None,
        "event_slug": event_slug,
        "queued_at_utc": queued_at.astimezone(timezone.utc).isoformat(),
        "attempt_count": 0,
        "trigger_context": trigger_context,
    }
    path = _state_dir(root, PENDING_DIR) / f"{work_id}.json"
    atomic_write_json(path, job, trailing_newline=True)
    return {
        "work_id": work_id,
        "state": PENDING_DIR,
        "path": str(path),
        "deduplicated": False,
    }


def recover_inflight_jobs(queue_root=None):
    """Return work orphaned by a prior snapshot-supervisor process to pending."""

    root = _queue_root(queue_root)
    inflight = _state_dir(root, INFLIGHT_DIR)
    pending = _state_dir(root, PENDING_DIR)
    completed = _state_dir(root, COMPLETED_DIR)
    acknowledged = _state_dir(root, ACKNOWLEDGED_DIR)
    recovered = []
    discarded_terminal = []
    for path in sorted(inflight.glob("*.json")):
        work_id = path.stem
        if (completed / path.name).exists() or (acknowledged / path.name).exists():
            path.unlink(missing_ok=True)
            discarded_terminal.append(work_id)
            continue
        destination = pending / path.name
        if destination.exists():
            path.unlink(missing_ok=True)
        else:
            os.replace(path, destination)
        recovered.append(work_id)
    return {
        "recovered_count": len(recovered),
        "recovered_work_ids": recovered,
        "terminal_duplicate_count": len(discarded_terminal),
    }


def claim_triggered_snapshot_jobs(queue_root=None, market_ids=None, limit=None):
    """Claim at most one oldest queued trigger per market for the next batch."""

    root = _queue_root(queue_root)
    pending = _state_dir(root, PENDING_DIR)
    inflight = _state_dir(root, INFLIGHT_DIR)
    allowed = set(market_ids or []) or None
    candidates = []
    for path in pending.glob("*.json"):
        job = _read_job(path)
        if not job or (allowed is not None and job.get("market_id") not in allowed):
            continue
        candidates.append((str(job.get("queued_at_utc") or ""), path.name, path, job))
    claimed = []
    claimed_markets = set()
    for _queued_at, _name, path, job in sorted(candidates):
        market_id = job.get("market_id")
        if market_id in claimed_markets:
            continue
        if limit is not None and len(claimed) >= int(limit):
            break
        destination = inflight / path.name
        try:
            os.replace(path, destination)
        except FileNotFoundError:
            continue
        job["queue_state"] = INFLIGHT_DIR
        job["queue_path"] = str(destination)
        claimed.append(job)
        claimed_markets.add(market_id)
    return claimed


def retry_triggered_snapshot_job(job, result, *, queue_root=None, now=None):
    """Persist retry evidence and put a retryable job back into the queue."""

    root = _queue_root(queue_root)
    work_id = job["work_id"]
    retried_at = now or _utc_now()
    if retried_at.tzinfo is None:
        retried_at = retried_at.replace(tzinfo=timezone.utc)
    payload = {
        key: value
        for key, value in job.items()
        if key not in {"queue_state", "queue_path"}
    }
    payload["attempt_count"] = int(payload.get("attempt_count") or 0) + 1
    payload["last_attempt_at_utc"] = retried_at.astimezone(timezone.utc).isoformat()
    payload["last_retryable_result"] = result
    pending_path = _state_dir(root, PENDING_DIR) / f"{work_id}.json"
    atomic_write_json(pending_path, payload, trailing_newline=True)
    (_state_dir(root, INFLIGHT_DIR) / f"{work_id}.json").unlink(missing_ok=True)
    return {"work_id": work_id, "state": PENDING_DIR, "path": str(pending_path)}


def complete_triggered_snapshot_job(job, result, execution=None, *, queue_root=None, now=None):
    """Write a terminal receipt before removing the in-flight request."""

    root = _queue_root(queue_root)
    work_id = job["work_id"]
    completed_at = now or _utc_now()
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    receipt = {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "record_type": "triggered_snapshot_receipt",
        "work_id": work_id,
        "market_id": job.get("market_id"),
        "target_date": job.get("target_date"),
        "event_slug": job.get("event_slug"),
        "queued_at_utc": job.get("queued_at_utc"),
        "completed_at_utc": completed_at.astimezone(timezone.utc).isoformat(),
        "attempt_count": int(job.get("attempt_count") or 0) + 1,
        "trigger_context": job.get("trigger_context") or {},
        "snapshot": result or {},
        "execution": execution or {},
    }
    completed_path = _state_dir(root, COMPLETED_DIR) / f"{work_id}.json"
    atomic_write_json(completed_path, receipt, trailing_newline=True)
    (_state_dir(root, INFLIGHT_DIR) / f"{work_id}.json").unlink(missing_ok=True)
    return receipt


def completed_triggered_snapshot_jobs(queue_root=None):
    root = _queue_root(queue_root)
    rows = []
    for path in sorted(_state_dir(root, COMPLETED_DIR).glob("*.json")):
        receipt = _read_job(path)
        if receipt:
            rows.append(receipt)
    return sorted(rows, key=lambda row: (str(row.get("completed_at_utc") or ""), row.get("work_id") or ""))


def has_pending_triggered_snapshot_jobs(queue_root=None):
    pending = _state_dir(_queue_root(queue_root), PENDING_DIR)
    return next(pending.glob("*.json"), None) is not None


def acknowledge_triggered_snapshot_job(work_id, queue_root=None):
    root = _queue_root(queue_root)
    source = _state_dir(root, COMPLETED_DIR) / f"{work_id}.json"
    destination = _state_dir(root, ACKNOWLEDGED_DIR) / f"{work_id}.json"
    if destination.exists():
        source.unlink(missing_ok=True)
        return destination
    try:
        receipt = _read_job(source)
        if receipt is None:
            raise FileNotFoundError(source)
        atomic_write_json(
            destination,
            {
                "schema_version": QUEUE_SCHEMA_VERSION,
                "record_type": "triggered_snapshot_ack",
                "work_id": work_id,
                "market_id": receipt.get("market_id"),
                "acknowledged_at_utc": _utc_now().isoformat(),
            },
            trailing_newline=True,
        )
        source.unlink(missing_ok=True)
    except FileNotFoundError:
        return None
    tombstones = sorted(
        _state_dir(root, ACKNOWLEDGED_DIR).glob("*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    for stale in tombstones[:-ACK_TOMBSTONE_LIMIT]:
        stale.unlink(missing_ok=True)
    return destination


def triggered_snapshot_queue_status(queue_root=None):
    root = _queue_root(queue_root)
    counts = {
        state: len(list(_state_dir(root, state).glob("*.json")))
        for state in (PENDING_DIR, INFLIGHT_DIR, COMPLETED_DIR, ACKNOWLEDGED_DIR)
    }
    return {
        "queue_root": str(root),
        "pending_count": counts[PENDING_DIR],
        "inflight_count": counts[INFLIGHT_DIR],
        "completed_unacknowledged_count": counts[COMPLETED_DIR],
        "acknowledged_count": counts[ACKNOWLEDGED_DIR],
    }
