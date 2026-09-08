"""Immutable one-night authority and bounded evidence for retained-file recovery."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from zoneinfo import ZoneInfo

from weather.operations import storage_recovery_inventory as metadata
from weather.schema_registry import schema_version

MIB, GIB = 1024**2, 1024**3
MAX_PLAN_BYTES = 256 * MIB // 1024
MAX_LEDGER_BYTES = 24 * MIB
MAX_GROUPS = 90
MAX_NEW_FILES = 16384
MAX_ATTEMPTS = 768
MAX_RECOVERIES = 48
MAX_INPUT_BYTES = 256 * GIB
MAX_EVIDENCE_BYTES = 256 * MIB
ENV = "WEATHER_STORAGE_RECOVERY_NIGHT_"
SEGMENTS = (("early", time(0, 30), time(4, 42)), ("late", time(6, 45), time(8, 55)))
SAFE_TERMINALS = frozenset({"TARGET_MET", "WINDOW_COMPLETE", "CANDIDATES_EXHAUSTED",
                           "RESOURCE_LIMITED", "BUDGET_COMPLETE"})
MEMORY_REASONS = frozenset({"commit_not_below_70_percent", "physical_memory_below_4_gib"})


def utc(value):
    if not isinstance(value, str):
        raise ValueError("UTC timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("explicit UTC timestamp required")
    return parsed


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + " fields do not match the exact contract")


def digest(value, length=64):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value):
        raise ValueError("exact lower-case digest required")
    return value


def canonical_absolute(value):
    if (not isinstance(value, str) or any(c in value for c in ('"', "\r", "\n", "\x00"))
            or not Path(value).is_absolute() or Path(value) != Path(os.path.abspath(value))):
        raise ValueError("absolute normalized path required")
    return Path(value)


def segment_times(night, name):
    match = next((row for row in SEGMENTS if row[0] == name), None)
    if match is None:
        raise ValueError("unknown night segment")
    zone = ZoneInfo("America/Toronto")
    return tuple(datetime.combine(night, t, zone).astimezone(timezone.utc) for t in match[1:])


def validate_plan(plan, *, production_root, source_root, source_git_sha, now):
    exact_keys(plan, {
        "schema_version", "plan_id", "night_date", "approved_by", "approved_at_utc",
        "expires_at_utc", "production_repo_root", "execution_host_id", "source_root",
        "source_git_sha", "baseline_receipt", "baseline_receipt_sha256",
        "baseline_ledger", "baseline_ledger_sha256", "groups", "target_new_reclaimed_bytes",
        "target_free_disk_bytes", "max_new_files", "max_wrapper_attempts",
        "max_resource_recoveries", "max_logical_input_bytes", "receipt_budget_bytes",
        "allow_resource_recovery",
    }, "night plan")
    if plan["schema_version"] != schema_version("storage_recovery_night_plan"):
        raise ValueError("unsupported night plan")
    night = date.fromisoformat(plan["night_date"])
    if (not re.fullmatch("capacity-" + night.strftime("%Y%m%d") + "-[a-z0-9]{1,12}", plan["plan_id"])
            or not isinstance(plan["approved_by"], str) or not 1 <= len(plan["approved_by"].strip()) <= 128
            or plan["allow_resource_recovery"] is not True):
        raise ValueError("explicit bounded one-night recovery approval required")
    if (canonical_absolute(plan["production_repo_root"]) != production_root
            or canonical_absolute(plan["source_root"]) != source_root
            or plan["source_git_sha"] != digest(source_git_sha, 40)):
        raise ValueError("night source or production binding mismatch")
    digest(plan["execution_host_id"])
    approved, expires = utc(plan["approved_at_utc"]), utc(plan["expires_at_utc"])
    start, _ = segment_times(night, "early")
    expiry = datetime.combine(night, time(9), ZoneInfo("America/Toronto")).astimezone(timezone.utc)
    if (not approved <= now < expires or expires != expiry or approved >= start
            or expires - approved > timedelta(hours=72)):
        raise ValueError("night approval is expired, future-dated or outside its fixed expiry")
    for key, ceiling in (("max_new_files", MAX_NEW_FILES), ("max_wrapper_attempts", MAX_ATTEMPTS),
                         ("max_resource_recoveries", MAX_RECOVERIES),
                         ("max_logical_input_bytes", MAX_INPUT_BYTES),
                         ("receipt_budget_bytes", MAX_EVIDENCE_BYTES)):
        if type(plan[key]) is not int or not 1 <= plan[key] <= ceiling:
            raise ValueError("invalid night bound: " + key)
    for key in ("target_new_reclaimed_bytes", "target_free_disk_bytes"):
        if type(plan[key]) is not int or not 0 < plan[key] <= 1024 * GIB:
            raise ValueError("invalid capacity target")
    for key in ("baseline_receipt", "baseline_ledger"):
        path = canonical_absolute(plan[key])
        if path.parent != production_root / "scratch/handoffs":
            raise ValueError("baseline must be an exact retained handoff file")
        digest(plan[key + "_sha256"])
    groups = plan["groups"]
    if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError("one to ninety exact cold-date groups required")
    seen_names, seen_folders = set(), set()
    for group in groups:
        exact_keys(group, {"name", "folders"}, "folder group")
        target = date.fromisoformat(group["name"])
        if group["name"] in seen_names:
            raise ValueError("duplicate group")
        seen_names.add(group["name"])
        for folder, observed_date in metadata.validate_folders(group["folders"], as_of=night):
            if (not folder.startswith("snapshots/") or observed_date != target
                    or folder.casefold() in seen_folders):
                raise ValueError("night groups require unique cold snapshot event folders")
            seen_folders.add(folder.casefold())
    return plan


def night_root(plan):
    return Path(plan["production_repo_root"]) / "scratch/storage_recovery_nights" / plan["plan_id"]


def read_json(path, maximum, expected_hash=None):
    path = Path(path)
    metadata.validate_root(path.parent)
    before = metadata.checked_stat(path, directory=False)
    if before.st_size > maximum:
        raise ValueError("evidence exceeds its read bound")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum or metadata.identity(metadata.checked_stat(path, directory=False)) != metadata.identity(before):
        raise ValueError("evidence changed or exceeded its bound")
    observed_hash = hashlib.sha256(raw).hexdigest()
    if expected_hash is not None and observed_hash != digest(expected_hash):
        raise ValueError("evidence SHA-256 mismatch")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("evidence must be an object")
    return value, observed_hash


def write_json(path, value, maximum=2 * MIB):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > maximum:
        raise ValueError("evidence exceeds its write bound")
    metadata.validate_root(Path(path).parent)
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def memory_refusal(error):
    prefix = "capture admission refused: "
    if not isinstance(error, str) or not error.startswith(prefix):
        return False
    reasons = error[len(prefix):].split(",")
    return bool(reasons) and set(reasons) <= MEMORY_REASONS and all(reasons)


def native_integer(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch("[0-9]{1,24}", value):
        return int(value)
    raise ValueError("exact nonnegative native integer required")


def ledger_identity(row):
    native = row["native_identity"]
    return tuple(native_integer(native[key]) for key in
                 ("volume_serial", "file_index", "creation_filetime"))


def validate_ledger(rows):
    if not isinstance(rows, list) or len(rows) > MAX_NEW_FILES + 20000:
        raise ValueError("ledger cardinality exceeds its bound")
    paths, identities, total = set(), set(), 0
    for row in rows:
        path = row.get("path")
        if (not isinstance(path, str) or len(PurePosixPath(path).parts) != 3
                or not path.startswith("snapshots/") or PurePosixPath(path).as_posix() != path
                or any(p.startswith(".") for p in PurePosixPath(path).parts)):
            raise ValueError("invalid retained-file ledger path")
        digest(row.get("sha256"))
        saved = row.get("allocation_saving_bytes")
        if (type(saved) is not int or saved <= 0
                or native_integer(row["allocation_before_bytes"]) - native_integer(row["allocation_after_bytes"]) != saved):
            raise ValueError("ledger allocation delta mismatch")
        identity = ledger_identity(row)
        if path.casefold() in paths or identity in identities:
            raise ValueError("duplicate retained path or native identity in ledger")
        paths.add(path.casefold())
        identities.add(identity)
        total += saved
    return total


def read_baseline(plan):
    receipt, _ = read_json(plan["baseline_receipt"], 2 * MIB, plan["baseline_receipt_sha256"])
    ledger, _ = read_json(plan["baseline_ledger"], MAX_LEDGER_BYTES, plan["baseline_ledger_sha256"])
    rows = ledger.get("files")
    total = validate_ledger(rows)
    if (ledger.get("production_repo_root") != plan["production_repo_root"]
            or receipt.get("production_repo_root") != plan["production_repo_root"]
            or ledger.get("verified_new_reclaimed_bytes") != total
            or receipt.get("verified_new_reclaimed_bytes") != total
            or ledger.get("verified_file_count") != len(rows)
            or receipt.get("verified_file_count") != len(rows)
            or receipt.get("verified_file_ledger_sha256") != plan["baseline_ledger_sha256"]
            or any(receipt.get(k) != 0 for k in ("unmatched_preimages", "unverified_compressed_files",
                                               "active_recovery_processes", "source_files_deleted"))
            or ledger.get("deleted_files") != 0 or ledger.get("cleanup_eligible") is not False):
        raise ValueError("baseline is incomplete or inconsistent")
    return rows, total
