"""Freshness checks for compact daily rollup artifacts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "daily_rollup_freshness_v0.1"

REQUIRED_GRANULAR_ARTIFACTS = (
    ("hourly_model_performance", "hourly_model_performance.json"),
    ("ten_minute_model_performance", "ten_minute_model_performance.json"),
    ("promotion_refresh", "f_family_promotion_refresh.json"),
    ("active_variant_shadow", "active_variant_shadow.json"),
    ("progress_audit", "progress_audit.json"),
)

COMPACT_ROLLUP_ARTIFACTS = (
    ("daily_learning", "daily_learning.json"),
    ("daily_progress_latest", "daily_progress_latest.json"),
)

TIMESTAMP_FIELDS = (
    "generated_at_utc",
    "generated_at",
    "finished_at_utc",
    "updated_at_utc",
    "created_at_utc",
)


def _utc_iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def parse_timestamp(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _payload_timestamp(payload):
    if not isinstance(payload, dict):
        return None, None
    for field in TIMESTAMP_FIELDS:
        dt = parse_timestamp(payload.get(field))
        if dt is not None:
            return dt, field
    return None, None


def artifact_record(backtest_root, name, filename, *, generated_at_override=None):
    path = Path(backtest_root) / filename
    override_dt = parse_timestamp(generated_at_override)
    if override_dt is not None:
        return {
            "name": name,
            "path": str(path),
            "exists": True,
            "timestamp_utc": _utc_iso(override_dt),
            "timestamp_source": "generated_at_override",
            "mtime_utc": _utc_iso(
                datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            ) if path.exists() else None,
        }
    if not path.exists():
        return {
            "name": name,
            "path": str(path),
            "exists": False,
            "timestamp_utc": None,
            "timestamp_source": None,
            "mtime_utc": None,
        }
    payload = _read_json(path)
    dt, source = _payload_timestamp(payload)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if dt is None:
        dt = mtime
        source = "mtime"
    return {
        "name": name,
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
        "status": payload.get("status") if isinstance(payload, dict) else None,
        "timestamp_utc": _utc_iso(dt),
        "timestamp_source": source,
        "mtime_utc": _utc_iso(mtime),
    }


def _timestamp_from_record(record):
    return parse_timestamp(record.get("timestamp_utc"))


def resume_repair_command(backtest_root, snapshots_root, *, resume_from_step="daily_learning"):
    return (
        "python -m weather.operations.daily_refresh repair-stale-locks "
        f"--backtest-root {Path(backtest_root)} "
        f"--snapshots-root {Path(snapshots_root)} "
        f"--resume-from-step {resume_from_step} "
        "--run-after-repair"
    )


def build_rollup_freshness(
    backtest_root,
    *,
    snapshots_root=None,
    generated_at_overrides=None,
    required_artifacts=REQUIRED_GRANULAR_ARTIFACTS,
    rollup_artifacts=COMPACT_ROLLUP_ARTIFACTS,
    stale_after_seconds=0,
    repair_command=None,
):
    root = Path(backtest_root)
    generated_at_overrides = generated_at_overrides or {}
    required = [
        artifact_record(root, name, filename)
        for name, filename in required_artifacts
    ]
    present_required = [
        row for row in required
        if row.get("exists") and _timestamp_from_record(row) is not None
    ]
    latest_required = None
    if present_required:
        latest_required = max(present_required, key=lambda row: _timestamp_from_record(row))
    latest_required_dt = _timestamp_from_record(latest_required or {})

    rollups = []
    blockers = []
    for name, filename in rollup_artifacts:
        record = artifact_record(
            root,
            name,
            filename,
            generated_at_override=generated_at_overrides.get(name),
        )
        rollup_dt = _timestamp_from_record(record)
        if not present_required:
            record["freshness_status"] = "NOT_CHECKED"
            record["reason"] = "no_required_granular_artifacts_present"
        elif not record.get("exists") or rollup_dt is None:
            record["freshness_status"] = "MISSING"
            record["reason"] = "compact_rollup_missing"
        else:
            stale_cutoff = rollup_dt.timestamp() + float(max(0, stale_after_seconds))
            if latest_required_dt and latest_required_dt.timestamp() > stale_cutoff:
                record["freshness_status"] = "STALE"
                record["reason"] = "required_granular_artifact_newer"
            else:
                record["freshness_status"] = "PASS"
                record["reason"] = ""
        record["latest_required_artifact"] = latest_required.get("name") if latest_required else None
        record["latest_required_timestamp_utc"] = (
            latest_required.get("timestamp_utc") if latest_required else None
        )
        if record["freshness_status"] in {"MISSING", "STALE"}:
            blockers.append({
                "rollup": name,
                "status": record["freshness_status"],
                "reason": record["reason"],
                "rollup_timestamp_utc": record.get("timestamp_utc"),
                "latest_required_artifact": record.get("latest_required_artifact"),
                "latest_required_timestamp_utc": record.get("latest_required_timestamp_utc"),
                "path": record.get("path"),
            })
        rollups.append(record)

    if blockers:
        status = "BLOCK"
    elif not present_required:
        status = "NO_REQUIRED_ARTIFACTS"
    else:
        status = "PASS"

    if repair_command is None and snapshots_root is not None:
        repair_command = resume_repair_command(root, snapshots_root)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "required_artifact_count": len(required),
        "present_required_artifact_count": len(present_required),
        "latest_required_artifact": latest_required.get("name") if latest_required else None,
        "latest_required_timestamp_utc": latest_required.get("timestamp_utc") if latest_required else None,
        "required_artifacts": required,
        "rollups": rollups,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "repair_command": repair_command,
        "stale_after_seconds": int(max(0, stale_after_seconds)),
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
