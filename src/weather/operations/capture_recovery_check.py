"""Fail-closed health proof for the three streak-critical capture workers.

The proof runs in the S4U recovery context so it can re-observe each worker's
OS command and creation token. A worker is healthy only when its status,
single-writer lock, exact process instance, fresh heartbeat, and loaded-source
identity all agree.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from weather.operations.supervisor import commands_match_exact, observe_process
from weather.paths import REPO_ROOT
from weather.runtime_identity import current_identity_for, identities_match
from weather.schema_registry import schema_version


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    status_file: str
    lock_file: str
    max_age_seconds: float
    command_markers: tuple[str, ...]


WORKERS = (
    # The normal snapshot loop can sleep for almost its full 10-minute cadence.
    # Keep recovery stricter than the 15-minute capture-gap objective while not
    # declaring a healthy, identity-current sleeping worker stale mid-cycle.
    WorkerSpec(
        "snapshot_tracker",
        "loop_status.json",
        ".loop_status.json.writer.lock",
        720.0,
        ("-m", "weather.collection.snapshot_tracker", "--loop"),
    ),
    WorkerSpec(
        "market_microstructure",
        "clob_loop_status.json",
        ".clob_loop_status.json.writer.lock",
        180.0,
        ("-m", "weather.market.market_microstructure", "loop"),
    ),
    WorkerSpec(
        "observation_trigger",
        "observation_trigger_status.json",
        ".observation_trigger_status.json.writer.lock",
        180.0,
        ("-m", "weather.operations.observation_trigger", "loop"),
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


def _contains_markers(values: object, markers: tuple[str, ...]) -> bool:
    if not isinstance(values, (list, tuple)):
        return False
    text = [str(value) for value in values]
    width = len(markers)
    return any(
        tuple(text[index : index + width]) == markers
        for index in range(len(text) - width + 1)
    )


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def check_capture_recovery(
    repo_root: Path,
    *,
    now: datetime | None = None,
    process_observer: Callable[[object], Mapping[str, Any]] = observe_process,
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
        status_managed = status.get("managed_process")
        lock_managed = lock.get("managed_process")
        expected_command: list[str] | None = None
        managed_identity_matches = False
        if not isinstance(status_managed, dict) or not status_managed.get(
            "verified_at_capture"
        ):
            reasons.append("managed_process_identity_missing")
        else:
            raw_expected = status_managed.get("expected_command")
            if isinstance(raw_expected, list) and _contains_markers(
                raw_expected, spec.command_markers
            ):
                expected_command = [str(value) for value in raw_expected]
            else:
                reasons.append("managed_process_expected_command_invalid")
        if not isinstance(lock_managed, dict) or not lock_managed.get(
            "verified_at_capture"
        ):
            reasons.append("writer_lock_process_identity_missing")
        elif isinstance(status_managed, dict):
            managed_identity_matches = bool(
                _integer(status_managed.get("pid")) == pid
                and _integer(lock_managed.get("pid")) == pid
                and status_managed.get("creation_time_token")
                == lock_managed.get("creation_time_token")
                and status_managed.get("expected_command")
                == lock_managed.get("expected_command")
            )
            if not managed_identity_matches:
                reasons.append("status_lock_process_identity_mismatch")

        try:
            observation = dict(process_observer(pid))
        except (OSError, TypeError, ValueError):
            observation = {"state": "unknown", "pid": pid, "inspectable": False}
        process_state = str(observation.get("state") or "unknown")
        process_inspectable = bool(observation.get("inspectable"))
        creation_token_matches = bool(
            isinstance(status_managed, dict)
            and status_managed.get("creation_time_token")
            and observation.get("creation_time_token")
            == status_managed.get("creation_time_token")
        )
        command_matches = bool(
            expected_command
            and commands_match_exact(observation.get("argv"), expected_command)
        )
        if process_state == "not_found":
            reasons.append("pid_not_alive")
        elif process_state != "running":
            reasons.append("process_identity_unknown")
        if process_state == "running" and not process_inspectable:
            reasons.append("process_identity_uninspectable")
        if (
            process_state == "running"
            and process_inspectable
            and not creation_token_matches
        ):
            reasons.append("process_creation_token_mismatch")
        if process_state == "running" and process_inspectable and not command_matches:
            reasons.append("process_command_mismatch")

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
                "process_state": process_state,
                "process_identity_inspectable": process_inspectable,
                "process_creation_token_matches": creation_token_matches,
                "process_command_matches": command_matches,
                "status_lock_process_identity_matches": managed_identity_matches,
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
        "schema_version": schema_version("capture_recovery_check"),
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
