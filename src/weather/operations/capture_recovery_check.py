"""Fail-closed health proof for the three streak-critical capture workers.

Unlike process-command-line inspection, this works for S4U-owned workers whose command
lines are hidden from an interactive session.  A worker is healthy only when its status,
single-writer lock, live PID, fresh heartbeat, and loaded-source identity all agree.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from weather.paths import REPO_ROOT
from weather.runtime_identity import current_identity_for, identities_match


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    status_file: str
    lock_file: str
    max_age_seconds: float


WORKERS = (
    WorkerSpec("snapshot_tracker", "loop_status.json", ".loop_status.json.writer.lock", 300.0),
    WorkerSpec(
        "market_microstructure",
        "clob_loop_status.json",
        ".clob_loop_status.json.writer.lock",
        180.0,
    ),
    WorkerSpec(
        "observation_trigger",
        "observation_trigger_status.json",
        ".observation_trigger_status.json.writer.lock",
        180.0,
    ),
)


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root is not an object")
    return payload


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("heartbeat has no timezone")
    return parsed.astimezone(timezone.utc)


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def check_capture_recovery(
    repo_root: Path,
    *,
    now: datetime | None = None,
    process_alive: Callable[[int], bool] = process_is_alive,
    current_identity: Callable[..., Mapping[str, Any]] = current_identity_for,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    snapshots = root / "data" / "snapshots"
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []

    for spec in WORKERS:
        reasons: list[str] = []
        status_path = snapshots / spec.status_file
        lock_path = snapshots / spec.lock_file
        status: Mapping[str, Any] = {}
        lock: Mapping[str, Any] = {}
        try:
            status = _read_json(status_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"status_unreadable:{type(exc).__name__}")
        try:
            lock = _read_json(lock_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"lock_unreadable:{type(exc).__name__}")

        try:
            pid = int(status.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        try:
            lock_pid = int(lock.get("pid") or 0)
        except (TypeError, ValueError):
            lock_pid = 0
        if pid <= 0:
            reasons.append("invalid_status_pid")
        if lock_pid != pid:
            reasons.append("writer_lock_pid_mismatch")
        if not process_alive(pid):
            reasons.append("pid_not_alive")

        heartbeat: datetime | None = None
        age_seconds: float | None = None
        try:
            heartbeat = _parse_datetime(status.get("last_heartbeat"))
            age_seconds = (checked_at - heartbeat).total_seconds()
            if age_seconds < 0:
                reasons.append("heartbeat_in_future")
            elif age_seconds > spec.max_age_seconds:
                reasons.append("heartbeat_stale")
        except (TypeError, ValueError):
            reasons.append("heartbeat_invalid")

        recorded_identity = status.get("runtime_identity")
        identity_match = False
        current_source_fingerprint = None
        if not isinstance(recorded_identity, dict) or not recorded_identity:
            reasons.append("runtime_identity_missing")
        else:
            try:
                recomputed = current_identity(recorded_identity, repo_root=root)
                current_source_fingerprint = recomputed.get("source_fingerprint")
                identity_match = identities_match(recorded_identity, recomputed)
            except (OSError, TypeError, ValueError):
                identity_match = False
            if not identity_match:
                reasons.append("runtime_identity_stale")

        rows.append(
            {
                "name": spec.name,
                "ok": not reasons,
                "pid": pid,
                "lock_pid": lock_pid,
                "last_heartbeat": heartbeat.isoformat() if heartbeat else None,
                "heartbeat_age_seconds": age_seconds,
                "max_age_seconds": spec.max_age_seconds,
                "recorded_source_fingerprint": (
                    recorded_identity.get("source_fingerprint")
                    if isinstance(recorded_identity, dict)
                    else None
                ),
                "current_source_fingerprint": current_source_fingerprint,
                "runtime_identity_matches_current": identity_match,
                "reasons": reasons,
            }
        )

    return {
        "schema_version": "capture_recovery_check_v1",
        "checked_at": checked_at.isoformat(),
        "repo_root": str(root),
        "ok": len(rows) == len(WORKERS) and all(row["ok"] for row in rows),
        "workers": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = check_capture_recovery(args.repo_root)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for row in result["workers"]:
            detail = "healthy" if row["ok"] else ",".join(row["reasons"])
            print(f"{row['name']}: {detail}")
        print("PASS" if result["ok"] else "BLOCK")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
