"""Run one verified experiment in a filesystem- and resource-isolated sandbox.

The child protocol is deliberately small.  A successful experiment writes only
the manifest-declared artifacts below ``candidate_output_root`` and prints a
final line of the form::

    EXPERIMENT_OBSERVATION_JSON={"independent_sample_count": ..., "metrics": ...}

The executor, rather than the child, evaluates the manifest decision rule and
writes the canonical self-hashed terminal result.  Child output is promoted
from the scratch sandbox into the candidate tree only after every declared
hash/schema check passes.  Nothing in this module schedules experiments or
touches capture workers, active pointers, or serving releases.

The filesystem guard is a fail-closed Python audit policy for the repository's
allowlisted, trusted experiment modules.  It is not an operating-system sandbox
for hostile native code: subprocess and ``ctypes`` entry points are denied, but
preinstalled native extensions remain part of the trusted-module boundary.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import stat
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from weather.experiment_contract import (
    TERMINAL_DISPOSITIONS,
    ExperimentContractError,
    build_experiment_result,
    verify_automatic_experiment_queue,
)
from weather.io import write_json_atomic
from weather.operations.capture_resource_gate import build_capture_resource_gate
from weather.operations.daily_refresh_resources import host_commit_percent
from weather.operations.long_job_guard import run_isolated_subprocess
from weather.paths import REPO_ROOT, data_path


DEFAULT_QUEUE_PATH = data_path("backtest", "daily_learning.json")
OBSERVATION_PREFIX = "EXPERIMENT_OBSERVATION_JSON="
QUIET_TIMEZONE = ZoneInfo("America/Toronto")
QUIET_START_MINUTE = 60
QUIET_END_MINUTE = 8 * 60 + 30
MAX_MEMORY_MB = 8 * 1024
MAX_TIMEOUT_SECONDS = (QUIET_END_MINUTE - QUIET_START_MINUTE) * 60
MAX_HOST_COMMIT_PERCENT = 70.0
CAPTURE_MEMORY_RESERVE_BYTES = 4 * 1024**3
MIN_FREE_DISK_BYTES = 50 * 1024**3
MAX_QUEUE_BYTES = 16 * 1024 * 1024
MAX_EXECUTOR_COPY_BYTES = 512 * 1024 * 1024
MAX_PARENT_JSON_BYTES = 128 * 1024 * 1024
MAX_FINGERPRINT_FILES = 100_000
MAX_PARENT_TREE_ENTRIES = 100_000
MAX_PARENT_TREE_DEPTH = 64
MAX_PARENT_TREE_SECONDS = 60.0
OUTPUT_TAIL_CHARS = 256 * 1024
MAX_CHILD_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_TREE_ENTRIES = 10_000
MAX_OUTPUT_TREE_DEPTH = 24
MAX_OUTPUT_TREE_SECONDS = 15.0
ALLOWED_MODULE_PREFIXES = (
    "weather.backtesting.",
    "weather.calibration.",
    "weather.model.",
    "weather.reporting.",
)
class ExperimentExecutionError(RuntimeError):
    """A verified experiment could not be executed without weakening safety."""


def utc_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _reject_nested_nonfinite_json(value: Any, *, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite JSON number at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_nested_nonfinite_json(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nested_nonfinite_json(item, path=f"{path}[{index}]")


def _strict_json(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ExperimentExecutionError(
                    f"JSON contains duplicate key {key!r}: {path}"
                )
            result[key] = value
        return result

    try:
        size_bytes = path.stat().st_size
        if size_bytes > MAX_QUEUE_BYTES:
            raise ExperimentExecutionError(
                f"JSON input exceeds the {MAX_QUEUE_BYTES}-byte executor ceiling: {path}"
            )
        payload = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {value}")
            ),
        )
        _reject_nested_nonfinite_json(payload)
    except ExperimentExecutionError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExperimentExecutionError(
            f"cannot read experiment queue JSON {path}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ExperimentExecutionError(f"experiment queue JSON must be an object: {path}")
    return payload


def _queue_payload(document: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = document.get("experiment_queue")
    if isinstance(nested, Mapping):
        return nested
    return document


def _select_verified_item(
    queue_path: str | Path,
    queue_id: str,
    *,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(queue_path)
    if path.is_symlink() or not path.is_file():
        raise ExperimentExecutionError(
            f"experiment queue must be a regular non-symlink file: {path}"
        )
    document = _strict_json(path)
    try:
        queue = verify_automatic_experiment_queue(
            _queue_payload(document),
            repo_root=repo_root,
        )
    except (ExperimentContractError, OSError, TypeError, ValueError) as exc:
        raise ExperimentExecutionError(
            "experiment queue verification failed; regenerate the materialized queue "
            f"before execution: {type(exc).__name__}: {exc}"
        ) from exc
    matches = [
        item
        for item in queue.get("items") or []
        if str(item.get("queue_id") or "") == str(queue_id)
    ]
    if len(matches) != 1:
        raise ExperimentExecutionError(
            f"queue_id {queue_id!r} must identify exactly one verified queue item"
        )
    item = matches[0]
    if item.get("eligible") is not True or item.get("status") != "queued":
        raise ExperimentExecutionError(
            f"queue_id {queue_id!r} is not an eligible queued experiment"
        )
    manifest = item.get("experiment_manifest")
    if not isinstance(manifest, dict):
        raise ExperimentExecutionError("eligible queue item is missing its verified manifest")
    return queue, manifest


def _queue_entry_is_current(
    queue_path: str | Path,
    queue_id: str,
    manifest_sha256: str,
    *,
    repo_root: Path,
) -> bool:
    path = Path(queue_path)
    if path.is_symlink() or not path.is_file():
        raise ExperimentExecutionError(
            f"experiment queue must remain a regular non-symlink file: {path}"
        )
    document = _strict_json(path)
    try:
        queue = verify_automatic_experiment_queue(
            _queue_payload(document),
            repo_root=repo_root,
        )
    except (ExperimentContractError, OSError, TypeError, ValueError) as exc:
        raise ExperimentExecutionError(
            f"experiment queue re-verification failed before commit: {type(exc).__name__}: {exc}"
        ) from exc
    matches = [
        item
        for item in queue.get("items") or []
        if str(item.get("queue_id") or "") == str(queue_id)
    ]
    if len(matches) != 1:
        return False
    item = matches[0]
    return bool(
        item.get("eligible") is True
        and item.get("status") == "queued"
        and item.get("manifest_sha256") == manifest_sha256
    )


def _relative_repo_path(repo_root: Path, value: str, field: str) -> Path:
    normalized = str(value).replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ExperimentExecutionError(f"{field} is not a safe repository-relative path")
    lexical = repo_root.joinpath(*relative.parts)
    try:
        resolved_parent = lexical.parent.resolve(strict=True)
        resolved_parent.relative_to(repo_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExperimentExecutionError(f"{field} resolves outside repo_root") from exc
    current = repo_root.resolve(strict=True)
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ExperimentExecutionError(f"{field} contains a symlink component")
    return lexical


def _reject_symlink_components(path: Path, root: Path, field: str) -> None:
    try:
        root_resolved = root.resolve(strict=True)
        relative = path.absolute().relative_to(root_resolved)
        path.resolve(strict=False).relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExperimentExecutionError(f"{field} resolves outside repo_root") from exc
    current = root_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ExperimentExecutionError(f"{field} contains a symlink component")


def _within_quiet_window(now: datetime) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(QUIET_TIMEZONE)
    minute = local.hour * 60 + local.minute
    return QUIET_START_MINUTE <= minute < QUIET_END_MINUTE


def _quiet_window_remaining_seconds(now: datetime) -> int:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(QUIET_TIMEZONE)
    end = local.replace(hour=8, minute=30, second=0, microsecond=0)
    return max(0, int((end - local).total_seconds()))


def _host_admission(
    repo_root: Path,
    budget: Mapping[str, Any],
    *,
    now: datetime,
    admission_builder: Callable[..., Mapping[str, Any]],
    commit_percent_fn: Callable[[], float | None],
) -> dict[str, Any]:
    commit_percent = commit_percent_fn()
    if commit_percent is None or not math.isfinite(float(commit_percent)):
        raise ExperimentExecutionError(
            "host commit percentage is unavailable; defer the experiment"
        )
    if float(commit_percent) >= MAX_HOST_COMMIT_PERCENT:
        raise ExperimentExecutionError(
            f"host commit_percent={float(commit_percent):.3f} is not below "
            f"{MAX_HOST_COMMIT_PERCENT:.1f}; defer the experiment"
        )
    required_memory = CAPTURE_MEMORY_RESERVE_BYTES + int(budget["memory_mb"]) * 1024**2
    required_disk = MIN_FREE_DISK_BYTES + int(
        math.ceil(float(budget["io_write_mb"]) * 1024**2)
    )
    try:
        admission = dict(
            admission_builder(
                workload="isolated_experiment_executor",
                snapshots_root=repo_root / "data" / "snapshots",
                disk_path=repo_root,
                capture_mode="live",
                active_window=False,
                min_free_memory_bytes=required_memory,
                min_free_disk_bytes=required_disk,
                now=now,
            )
        )
    except Exception as exc:  # noqa: BLE001 - inability to prove admission blocks
        raise ExperimentExecutionError(
            f"capture-resource admission could not be evaluated: {type(exc).__name__}: {exc}"
        ) from exc
    if admission.get("admitted") is not True or admission.get("decision") != "ADMIT":
        codes = [str(row.get("code") or "") for row in admission.get("blockers") or []]
        raise ExperimentExecutionError(
            "capture-resource admission deferred the experiment"
            + (f": {', '.join(code for code in codes if code)}" if codes else "")
        )
    return {
        "commit_percent": float(commit_percent),
        "maximum_commit_percent": MAX_HOST_COMMIT_PERCENT,
        "required_free_memory_bytes": required_memory,
        "required_free_disk_bytes": required_disk,
        "capture_resource_gate": admission,
    }


def _validated_budget(manifest: Mapping[str, Any]) -> dict[str, Any]:
    budget = dict(manifest.get("resource_budget") or {})
    timeout_seconds = int(budget["timeout_seconds"])
    memory_mb = int(budget["memory_mb"])
    cpu_value = float(budget["cpu_cores"])
    cpu_cores = int(cpu_value)
    host_cpus = max(1, int(os.cpu_count() or 1))
    if not math.isclose(cpu_value, cpu_cores) or cpu_cores <= 0:
        raise ExperimentExecutionError(
            "resource_budget.cpu_cores must be a positive whole-core budget for "
            "the Windows Job Object executor"
        )
    if timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise ExperimentExecutionError(
            f"resource_budget.timeout_seconds={timeout_seconds} exceeds the quiet-window "
            f"ceiling of {MAX_TIMEOUT_SECONDS}"
        )
    if memory_mb > MAX_MEMORY_MB:
        raise ExperimentExecutionError(
            f"resource_budget.memory_mb={memory_mb} exceeds the host ceiling of "
            f"{MAX_MEMORY_MB} MiB"
        )
    if cpu_cores > host_cpus:
        raise ExperimentExecutionError(
            f"resource_budget.cpu_cores={cpu_cores} exceeds host logical CPUs={host_cpus}"
        )
    return {
        **budget,
        "timeout_seconds": timeout_seconds,
        "memory_mb": memory_mb,
        "cpu_cores": cpu_cores,
        "io_read_mb": float(budget["io_read_mb"]),
        "io_write_mb": float(budget["io_write_mb"]),
        "executor_host_ceiling": {
            "memory_mb": MAX_MEMORY_MB,
            "timeout_seconds": MAX_TIMEOUT_SECONDS,
            "logical_cpus": host_cpus,
        },
    }


def _validated_module(manifest: Mapping[str, Any]) -> str:
    argv = list(manifest.get("argv") or [])
    module = str(argv[2]) if len(argv) >= 3 and argv[1] == "-m" else ""
    if not any(module.startswith(prefix) for prefix in ALLOWED_MODULE_PREFIXES):
        raise ExperimentExecutionError(
            "experiment module is outside the offline research allowlist; use a "
            "weather.reporting, weather.calibration, weather.backtesting, or "
            "weather.model module"
        )
    return module


def _tree_deadline(max_seconds: float, operation: str) -> float:
    seconds = float(max_seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ExperimentExecutionError(
            f"{operation} requires a positive finite time ceiling"
        )
    return time.monotonic() + seconds


def _check_tree_deadline(deadline: float, operation: str) -> None:
    if time.monotonic() > deadline:
        raise ExperimentExecutionError(f"{operation} exceeded its declared time ceiling")


def _sha256_file_bounded(
    path: Path,
    *,
    max_bytes: int,
    deadline: float,
    operation: str,
) -> tuple[str, int]:
    """Hash one stable regular file without reading beyond the parent budget."""

    _check_tree_deadline(deadline, operation)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExperimentExecutionError(
            f"{operation} cannot open regular file: {path}: {exc}"
        ) from exc
    digest = hashlib.sha256()
    total = 0
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ExperimentExecutionError(f"{operation} encountered a non-regular file: {path}")
        if before.st_size > int(max_bytes):
            raise ExperimentExecutionError(
                f"{operation} exceeds the remaining {int(max_bytes)}-byte ceiling: {path}"
            )
        while True:
            _check_tree_deadline(deadline, operation)
            chunk = os.read(descriptor, min(1024 * 1024, int(max_bytes) - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > int(max_bytes):
                raise ExperimentExecutionError(
                    f"{operation} exceeds the remaining {int(max_bytes)}-byte ceiling: {path}"
                )
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or total != after.st_size
        ):
            raise ExperimentExecutionError(f"{operation} source changed while it was read: {path}")
    finally:
        os.close(descriptor)
    return digest.hexdigest(), total


def _tree_fingerprint(paths: list[Path], *, repo_root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    fingerprinted: set[str] = set()
    total_bytes = 0
    entry_count = 0
    root = repo_root.resolve(strict=True)
    deadline = _tree_deadline(MAX_PARENT_TREE_SECONDS, "protected tree fingerprint")

    def fingerprint_file(candidate: Path) -> None:
        nonlocal total_bytes
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(root).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ExperimentExecutionError(
                f"protected serving file escaped repo_root: {candidate}"
            ) from exc
        if relative in fingerprinted:
            return
        fingerprinted.add(relative)
        if len(fingerprinted) > MAX_FINGERPRINT_FILES:
            raise ExperimentExecutionError(
                f"protected tree exceeds {MAX_FINGERPRINT_FILES} files"
            )
        sha256, size_bytes = _sha256_file_bounded(
            candidate,
            max_bytes=MAX_EXECUTOR_COPY_BYTES - total_bytes,
            deadline=deadline,
            operation="protected tree fingerprint",
        )
        total_bytes += size_bytes
        rows.append(
            {"path": relative, "size_bytes": size_bytes, "sha256": sha256}
        )

    for declared in paths:
        _check_tree_deadline(deadline, "protected tree fingerprint")
        path = Path(declared)
        try:
            label = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ExperimentExecutionError(
                f"protected serving path escaped repo_root: {path}"
            ) from exc
        if label in seen:
            continue
        seen.add(label)
        try:
            root_stat = path.lstat()
        except FileNotFoundError:
            rows.append({"path": label, "type": "missing"})
            continue
        except OSError as exc:
            raise ExperimentExecutionError(
                f"protected serving path cannot be inspected: {path}: {exc}"
            ) from exc
        entry_count += 1
        if entry_count > MAX_PARENT_TREE_ENTRIES:
            raise ExperimentExecutionError(
                f"protected tree exceeds {MAX_PARENT_TREE_ENTRIES} filesystem entries"
            )
        if stat.S_ISLNK(root_stat.st_mode):
            raise ExperimentExecutionError(
                f"protected serving path must not be a symlink: {path}"
            )
        if stat.S_ISREG(root_stat.st_mode):
            fingerprint_file(path)
            continue
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ExperimentExecutionError(
                f"protected serving path must be a regular file or directory: {path}"
            )
        pending: list[tuple[Path, int]] = [(path, 0)]
        while pending:
            directory, depth = pending.pop()
            _check_tree_deadline(deadline, "protected tree fingerprint")
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        _check_tree_deadline(deadline, "protected tree fingerprint")
                        entry_count += 1
                        if entry_count > MAX_PARENT_TREE_ENTRIES:
                            raise ExperimentExecutionError(
                                "protected tree exceeds "
                                f"{MAX_PARENT_TREE_ENTRIES} filesystem entries"
                            )
                        candidate = Path(entry.path)
                        if entry.is_symlink():
                            raise ExperimentExecutionError(
                                f"protected serving tree contains a symlink: {candidate}"
                            )
                        if entry.is_dir(follow_symlinks=False):
                            child_depth = depth + 1
                            if child_depth > MAX_PARENT_TREE_DEPTH:
                                raise ExperimentExecutionError(
                                    "protected tree exceeds maximum directory depth "
                                    f"{MAX_PARENT_TREE_DEPTH}"
                                )
                            pending.append((candidate, child_depth))
                        elif entry.is_file(follow_symlinks=False):
                            fingerprint_file(candidate)
                        else:
                            raise ExperimentExecutionError(
                                f"protected tree contains a non-regular entry: {candidate}"
                            )
            except ExperimentExecutionError:
                raise
            except OSError as exc:
                raise ExperimentExecutionError(
                    f"protected tree cannot be enumerated safely: {directory}: {exc}"
                ) from exc
    rows.sort(key=lambda row: (str(row.get("path") or ""), str(row.get("type") or "")))
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "file_count": sum(1 for row in rows if row.get("sha256")),
        "total_bytes": total_bytes,
        "rows": rows,
    }


def _protected_serving_paths(repo_root: Path, release_id: str) -> list[Path]:
    releases = repo_root / "artifacts" / "releases"
    pointer = releases / "current_release.json"
    paths = [pointer, releases / release_id]
    if pointer.is_file():
        try:
            pointer_payload = _strict_json(pointer)
        except ExperimentExecutionError:
            pointer_payload = {}
        active_id = str(pointer_payload.get("active_release_id") or "")
        if active_id and active_id not in {".", ".."} and "/" not in active_id and "\\" not in active_id:
            paths.append(releases / active_id)
    return paths


def _copy_file(
    source: Path,
    target: Path,
    *,
    max_bytes: int,
    deadline: float | None = None,
) -> int:
    operation = "isolated input copy"
    copy_deadline = deadline or _tree_deadline(MAX_PARENT_TREE_SECONDS, operation)
    _check_tree_deadline(copy_deadline, operation)
    try:
        source_stat = source.lstat()
    except OSError as exc:
        raise ExperimentExecutionError(
            f"isolated input cannot be inspected: {source}: {exc}"
        ) from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ExperimentExecutionError(f"isolated input must be a regular file: {source}")
    if source_stat.st_size > int(max_bytes):
        raise ExperimentExecutionError(
            f"isolated input exceeds the remaining {int(max_bytes)}-byte staging "
            f"ceiling before copy: {source}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    source_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    target_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
    )
    source_descriptor: int | None = None
    target_descriptor: int | None = None
    target_created = False
    total_bytes = 0
    try:
        source_descriptor = os.open(source, source_flags)
        opened_stat = os.fstat(source_descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ExperimentExecutionError(f"isolated input must remain a regular file: {source}")
        target_descriptor = os.open(target, target_flags, 0o600)
        target_created = True
        while True:
            _check_tree_deadline(copy_deadline, operation)
            chunk = os.read(
                source_descriptor,
                min(1024 * 1024, int(max_bytes) - total_bytes + 1),
            )
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > int(max_bytes):
                raise ExperimentExecutionError(
                    f"isolated input exceeds the remaining {int(max_bytes)}-byte staging "
                    f"ceiling while copying: {source}"
                )
            view = memoryview(chunk)
            while view:
                _check_tree_deadline(copy_deadline, operation)
                written = os.write(target_descriptor, view)
                if written <= 0:
                    raise OSError("short write while staging isolated input")
                view = view[written:]
        after = os.fstat(source_descriptor)
        if (
            opened_stat.st_size != after.st_size
            or opened_stat.st_mtime_ns != after.st_mtime_ns
            or total_bytes != after.st_size
        ):
            raise ExperimentExecutionError(
                f"isolated input changed while it was copied: {source}"
            )
    except BaseException:
        if target_descriptor is not None:
            os.close(target_descriptor)
            target_descriptor = None
        if target_created:
            try:
                target.unlink()
            except OSError:
                pass
        raise
    finally:
        if target_descriptor is not None:
            os.close(target_descriptor)
        if source_descriptor is not None:
            os.close(source_descriptor)
    return total_bytes


def _copy_tree(
    source: Path,
    target: Path,
    *,
    max_bytes: int = MAX_EXECUTOR_COPY_BYTES,
    max_entries: int = MAX_PARENT_TREE_ENTRIES,
    max_depth: int = MAX_PARENT_TREE_DEPTH,
    max_seconds: float = MAX_PARENT_TREE_SECONDS,
    deadline: float | None = None,
) -> int:
    try:
        source_stat = source.lstat()
    except OSError as exc:
        raise ExperimentExecutionError(
            f"isolated source cannot be inspected: {source}: {exc}"
        ) from exc
    if not stat.S_ISDIR(source_stat.st_mode):
        raise ExperimentExecutionError(f"isolated source must be a regular directory: {source}")
    if int(max_bytes) < 0 or int(max_entries) <= 0 or int(max_depth) < 0:
        raise ExperimentExecutionError(
            f"isolated source has an invalid staging budget: {source}"
        )
    copy_deadline = deadline or _tree_deadline(
        max_seconds,
        "isolated source tree copy",
    )
    total_bytes = 0
    entry_count = 0
    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise ExperimentExecutionError(
            f"isolated target directory cannot be created: {target}: {exc}"
        ) from exc
    pending: list[tuple[Path, Path, int]] = [(source, target, 0)]
    while pending:
        source_directory, target_directory, depth = pending.pop()
        _check_tree_deadline(copy_deadline, "isolated source tree copy")
        try:
            with os.scandir(source_directory) as entries:
                for entry in entries:
                    _check_tree_deadline(copy_deadline, "isolated source tree copy")
                    entry_count += 1
                    if entry_count > int(max_entries):
                        raise ExperimentExecutionError(
                            "isolated source tree exceeds the "
                            f"{int(max_entries)}-entry staging ceiling: {source}"
                        )
                    source_path = Path(entry.path)
                    target_path = target_directory / entry.name
                    if entry.is_symlink():
                        raise ExperimentExecutionError(
                            f"isolated source tree contains a symlink: {source_path}"
                        )
                    if entry.is_dir(follow_symlinks=False):
                        child_depth = depth + 1
                        if child_depth > int(max_depth):
                            raise ExperimentExecutionError(
                                "isolated source tree exceeds the maximum directory depth "
                                f"{int(max_depth)}: {source}"
                            )
                        target_path.mkdir()
                        pending.append((source_path, target_path, child_depth))
                    elif entry.is_file(follow_symlinks=False):
                        total_bytes += _copy_file(
                            source_path,
                            target_path,
                            max_bytes=int(max_bytes) - total_bytes,
                            deadline=copy_deadline,
                        )
                    else:
                        raise ExperimentExecutionError(
                            f"isolated source tree contains a non-regular entry: {source_path}"
                        )
        except ExperimentExecutionError:
            raise
        except OSError as exc:
            raise ExperimentExecutionError(
                f"isolated source tree cannot be copied safely: {source_directory}: {exc}"
            ) from exc
    return total_bytes


def _python_runtime_read_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in (
        Path(sys.prefix),
        Path(sys.exec_prefix),
        Path(getattr(sys, "base_prefix", sys.prefix)),
        Path(getattr(sys, "base_exec_prefix", sys.exec_prefix)),
        Path(sys.executable).parent,
    ):
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_dir():
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            roots.append(resolved)
    if not roots:
        raise ExperimentExecutionError(
            "cannot identify a readable Python runtime root for the isolated child"
        )
    return tuple(roots)


def _sitecustomize_text(
    workspace: Path,
    runtime_read_roots: tuple[Path, ...],
    candidate_output_root: Path,
) -> str:
    workspace_text = str(workspace.resolve())
    source_text = str((workspace / "src").resolve())
    runtime_root_text = tuple(str(path) for path in runtime_read_roots)
    writable_root_text = tuple(
        str(path.resolve())
        for path in (
            candidate_output_root,
            workspace / "tmp",
            workspace / "home",
            workspace / "appdata",
        )
    )
    return f'''"""Generated experiment sandbox guard; not repository source."""
import os
import pathlib
import sys

_ROOT = pathlib.Path({workspace_text!r}).resolve()
_SRC = {source_text!r}
_RUNTIME_ROOTS = tuple(pathlib.Path(value).resolve() for value in {runtime_root_text!r})
_WRITABLE_ROOTS = tuple(pathlib.Path(value).resolve() for value in {writable_root_text!r})
_READ_EXACT = {{os.path.normcase(os.path.abspath(os.devnull))}}
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_WRITE_FLAGS = (
    getattr(os, "O_WRONLY", 0)
    | getattr(os, "O_RDWR", 0)
    | getattr(os, "O_APPEND", 0)
    | getattr(os, "O_CREAT", 0)
    | getattr(os, "O_TRUNC", 0)
)
_MAX_MUTATIONS = {MAX_OUTPUT_TREE_ENTRIES!r}
_MUTATION_COUNT = 0

def _record_mutation(event):
    global _MUTATION_COUNT
    _MUTATION_COUNT += 1
    if _MUTATION_COUNT > _MAX_MUTATIONS:
        raise PermissionError(
            f"experiment sandbox exceeded {{_MAX_MUTATIONS}} filesystem mutations: {{event}}"
        )

def _writable(value):
    if isinstance(value, int):
        return True
    try:
        if isinstance(value, bytes):
            value = os.fsdecode(value)
        path = pathlib.Path(value)
        if not path.is_absolute():
            path = pathlib.Path.cwd() / path
        resolved = path.resolve(strict=False)
        for root in _WRITABLE_ROOTS:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
    except (OSError, TypeError, ValueError):
        pass
    return False

def _readable(value):
    if isinstance(value, int):
        return True
    if value is None:
        value = pathlib.Path.cwd()
    try:
        if isinstance(value, bytes):
            value = os.fsdecode(value)
        path = pathlib.Path(value)
        if not path.is_absolute():
            path = pathlib.Path.cwd() / path
        resolved = path.resolve(strict=False)
        if os.path.normcase(str(resolved)) in _READ_EXACT:
            return True
        for root in (_ROOT, *_RUNTIME_ROOTS):
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
    except (OSError, TypeError, ValueError):
        pass
    return False

def _require_writable(value, event):
    if not _writable(value):
        raise PermissionError(
            f"experiment sandbox denied {{event}} outside writable roots "
            f"{{_WRITABLE_ROOTS}}: {{value}}"
        )

def _require_readable(value, event):
    if not _readable(value):
        raise PermissionError(
            f"experiment sandbox denied undeclared read {{event}} outside the workspace "
            f"and Python runtime roots: {{value}}"
        )

def _audit(event, args):
    if event == "open" and args:
        path = args[0]
        mode = args[1] if len(args) > 1 else "r"
        flags = args[2] if len(args) > 2 else 0
        writing = (
            isinstance(mode, str) and any(marker in mode for marker in "wax+")
        ) or (isinstance(flags, int) and bool(flags & _WRITE_FLAGS))
        if writing:
            _record_mutation(event)
            _require_writable(path, event)
        else:
            _require_readable(path, event)
    elif event in {{
        "os.listdir", "os.scandir", "os.walk", "os.fwalk", "os.readlink",
        "os.getxattr", "os.listxattr", "glob.glob", "glob.glob/2",
        "pathlib.Path.glob", "pathlib.Path.rglob"
    }}:
        _require_readable(args[0] if args else None, event)
    elif event in {{
        "os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
        "os.lchown", "os.truncate", "os.utime", "os.mknod",
        "os.setxattr", "os.removexattr"
    }} and args:
        _record_mutation(event)
        _require_writable(args[0], event)
    elif event in {{"os.rename", "os.link", "os.symlink"}}:
        _record_mutation(event)
        if args:
            _require_writable(args[0], event)
        if len(args) > 1:
            _require_writable(args[1], event)
    elif event == "os.chdir" and args:
        _require_readable(args[0], event)
    elif event in {{
        "os.system", "os.kill", "os.killpg", "os.fork", "os.forkpty",
        "os.posix_spawn", "os.posix_spawnp", "os.exec", "os.spawn",
        "os.startfile", "os.startfile/2"
    }} or event.startswith(("ctypes.", "winreg.")):
        raise PermissionError(f"experiment sandbox denied child process event: {{event}}")
    elif event == "subprocess.Popen":
        # A same-interpreter child can pass -S/-I and bypass this generated
        # sitecustomize entirely.  Experiments are therefore single-process;
        # parallelism must use bounded threads inside the Job Object.
        raise PermissionError("experiment sandbox denies all child processes")
    elif event in {{
        "socket.bind", "socket.connect", "socket.connect_ex", "socket.getaddrinfo",
        "socket.sendmsg", "socket.sendto"
    }}:
        raise PermissionError(f"experiment sandbox denied network event: {{event}}")

sys.addaudithook(_audit)
'''


def _prepare_workspace(
    repo_root: Path,
    manifest: Mapping[str, Any],
    run_root: Path,
    *,
    bound_release_fingerprint: Mapping[str, Any],
    max_copy_bytes: int,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    workspace = run_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=False)
    runtime_read_roots = _python_runtime_read_roots()
    staging_deadline = _tree_deadline(
        MAX_PARENT_TREE_SECONDS,
        "isolated workspace staging",
    )
    copied_bytes = 0
    source_weather = repo_root / "src" / "weather"
    copied_bytes += _copy_tree(
        source_weather,
        workspace / "src" / "weather",
        max_bytes=max_copy_bytes,
        deadline=staging_deadline,
    )

    release_id = str((manifest.get("release") or {}).get("release_id") or "")
    release_source = repo_root / "artifacts" / "releases" / release_id
    copied_bytes += _copy_tree(
        release_source,
        workspace / "artifacts" / "releases" / release_id,
        max_bytes=max_copy_bytes - copied_bytes,
        deadline=staging_deadline,
    )
    sandbox_protected = _tree_fingerprint(
        [workspace / "artifacts" / "releases" / release_id],
        repo_root=workspace,
    )
    if sandbox_protected["sha256"] != bound_release_fingerprint.get("sha256"):
        raise ExperimentExecutionError(
            "sandbox release copy does not match the verified manifest-bound release tree"
        )

    copied_inputs: set[str] = set()
    input_proof: list[dict[str, Any]] = []
    input_entry_budget = 0
    for row in [manifest["corpus"], *(manifest.get("inputs") or [])]:
        _check_tree_deadline(staging_deadline, "isolated workspace staging")
        relative = str(row["path"]).replace("\\", "/")
        if relative in copied_inputs:
            continue
        copied_inputs.add(relative)
        relative_parts = PurePosixPath(relative).parts
        if len(relative_parts) > MAX_PARENT_TREE_DEPTH:
            raise ExperimentExecutionError(
                "manifest-bound input exceeds maximum staging depth "
                f"{MAX_PARENT_TREE_DEPTH}: {relative}"
            )
        input_entry_budget += len(relative_parts)
        if input_entry_budget > MAX_PARENT_TREE_ENTRIES:
            raise ExperimentExecutionError(
                "manifest-bound inputs exceed the "
                f"{MAX_PARENT_TREE_ENTRIES}-entry staging ceiling"
            )
        source = repo_root.joinpath(*relative_parts)
        target = workspace.joinpath(*relative_parts)
        before_sha256, source_bytes = _sha256_file_bounded(
            source,
            max_bytes=max_copy_bytes - copied_bytes,
            deadline=staging_deadline,
            operation="manifest-bound input verification",
        )
        if before_sha256 != str(row["sha256"]):
            raise ExperimentExecutionError(
                f"manifest-bound input changed before staging: {relative}"
            )
        copied_bytes += _copy_file(
            source,
            target,
            max_bytes=max_copy_bytes - copied_bytes,
            deadline=staging_deadline,
        )
        copied_sha256, copied_size = _sha256_file_bounded(
            target,
            max_bytes=source_bytes,
            deadline=staging_deadline,
            operation="staged input verification",
        )
        after_sha256, after_size = _sha256_file_bounded(
            source,
            max_bytes=source_bytes,
            deadline=staging_deadline,
            operation="manifest-bound input re-verification",
        )
        if (
            copied_sha256 != before_sha256
            or after_sha256 != before_sha256
            or copied_size != source_bytes
            or after_size != source_bytes
        ):
            raise ExperimentExecutionError(
                f"manifest-bound input changed while staging: {relative}"
            )
        _verify_embedded_schema(target, str(row["schema_version"]))
        input_proof.append(
            {
                "path": relative,
                "sha256": copied_sha256,
                "schema_version": row["schema_version"],
                "bytes": copied_size,
            }
        )

    stage_root = workspace.joinpath(
        *PurePosixPath(str(manifest["candidate_output_root"])).parts
    )
    stage_root.mkdir(parents=True, exist_ok=False)
    (workspace / "tmp").mkdir()
    (workspace / "home").mkdir()
    (workspace / "appdata").mkdir()
    (workspace / "sitecustomize.py").write_text(
        _sitecustomize_text(workspace, runtime_read_roots, stage_root),
        encoding="utf-8",
    )
    return workspace, sandbox_protected, {
        "maximum_copy_bytes": max_copy_bytes,
        "copied_bytes": copied_bytes,
        "mutable_config_copied": False,
        "active_release_pointer_copied": False,
        "read_policy": {
            "workspace_root": str(workspace.resolve()),
            "python_runtime_roots": [str(path) for path in runtime_read_roots],
            "other_external_reads": "denied_by_python_audit_hook",
        },
        "write_policy": {
            "writable_roots": [
                str(path.resolve())
                for path in (
                    stage_root,
                    workspace / "tmp",
                    workspace / "home",
                    workspace / "appdata",
                )
            ],
            "copied_source_release_and_inputs": "read_only_by_python_audit_hook",
            "other_workspace_mutations": "denied_by_python_audit_hook",
        },
        "inputs": input_proof,
    }


def _affinity_callback(cpu_cores: int) -> tuple[Callable[[Mapping[str, Any]], None], dict[str, Any]]:
    proof: dict[str, Any] = {
        "requested_cores": int(cpu_cores),
        "status": "PENDING",
        "platform": "windows" if os.name == "nt" else "posix",
    }

    def apply(started: Mapping[str, Any]) -> None:
        pid = int(started["pid"])
        if os.name == "nt":
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            PROCESS_SET_INFORMATION = 0x0200
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetProcessAffinityMask.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_size_t),
            )
            kernel32.GetProcessAffinityMask.restype = wintypes.BOOL
            kernel32.SetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
            kernel32.SetProcessAffinityMask.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION,
                False,
                pid,
            )
            if not handle:
                raise OSError(ctypes.get_last_error(), "OpenProcess for CPU affinity failed")
            try:
                process_mask = ctypes.c_size_t()
                system_mask = ctypes.c_size_t()
                if not kernel32.GetProcessAffinityMask(
                    handle,
                    ctypes.byref(process_mask),
                    ctypes.byref(system_mask),
                ):
                    raise OSError(
                        ctypes.get_last_error(),
                        "GetProcessAffinityMask failed",
                    )
                available = [
                    bit
                    for bit in range(ctypes.sizeof(ctypes.c_size_t) * 8)
                    if int(process_mask.value) & (1 << bit)
                ]
                if len(available) < cpu_cores:
                    raise OSError(
                        f"only {len(available)} affinity CPUs are available; "
                        f"requested {cpu_cores}"
                    )
                selected = available[:cpu_cores]
                mask = sum(1 << bit for bit in selected)
                if not kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(mask)):
                    raise OSError(
                        ctypes.get_last_error(),
                        "SetProcessAffinityMask failed",
                    )
            finally:
                kernel32.CloseHandle(handle)
        elif hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity"):
            available = sorted(os.sched_getaffinity(pid))
            if len(available) < cpu_cores:
                raise OSError(
                    f"only {len(available)} affinity CPUs are available; requested {cpu_cores}"
                )
            selected = available[:cpu_cores]
            os.sched_setaffinity(pid, selected)
            mask = selected
        else:
            raise OSError("process affinity is unavailable on this platform")
        proof.update(
            {
                "status": "PASS",
                "pid": pid,
                "selected": mask,
                "applied_before_user_code": bool(
                    started.get("started_before_user_code")
                ),
            }
        )

    return apply, proof


def _child_environment(workspace: Path, cpu_cores: int) -> dict[str, str]:
    runtime_roots = _python_runtime_read_roots()
    path_rows = [Path(sys.executable).resolve(strict=True).parent, *runtime_roots]
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    if system_root:
        path_rows.append(Path(system_root) / "System32")
    path_parts: list[str] = []
    seen_paths: set[str] = set()
    for path in path_rows:
        key = os.path.normcase(str(path))
        if key not in seen_paths:
            seen_paths.add(key)
            path_parts.append(str(path))
    thread_count = str(cpu_cores)
    env = {
        "PATH": os.pathsep.join(path_parts),
        "PYTHONPATH": os.pathsep.join((str(workspace), str(workspace / "src"))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "HOME": str(workspace / "home"),
        "USERPROFILE": str(workspace / "home"),
        "APPDATA": str(workspace / "appdata"),
        "LOCALAPPDATA": str(workspace / "appdata"),
        "TMP": str(workspace / "tmp"),
        "TEMP": str(workspace / "tmp"),
        "TMPDIR": str(workspace / "tmp"),
        "OMP_NUM_THREADS": thread_count,
        "OPENBLAS_NUM_THREADS": thread_count,
        "MKL_NUM_THREADS": thread_count,
        "NUMEXPR_NUM_THREADS": thread_count,
        "LOKY_MAX_CPU_COUNT": thread_count,
        "WEATHER_EXPERIMENT_ISOLATED": "1",
    }
    # CreateProcess on Windows requires SystemRoot in a custom environment.
    # These are the only host values inherited; credentials, provider config,
    # user paths, and mutable WEATHER_* settings are intentionally absent.
    for key in ("SYSTEMROOT", "WINDIR"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _parse_observation(stdout: str) -> dict[str, Any]:
    for line in reversed(str(stdout or "").splitlines()):
        if not line.startswith(OBSERVATION_PREFIX):
            continue
        raw = line[len(OBSERVATION_PREFIX) :]
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ExperimentExecutionError(
                f"child observation is invalid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ExperimentExecutionError("child observation must be a JSON object")
        if "independent_sample_count" not in payload or "metrics" not in payload:
            raise ExperimentExecutionError(
                "child observation requires independent_sample_count and metrics"
            )
        return payload
    raise ExperimentExecutionError(
        f"child stdout is missing the final {OBSERVATION_PREFIX} record"
    )


def _verify_embedded_schema(
    path: Path,
    expected: str,
    *,
    max_bytes: int = MAX_PARENT_JSON_BYTES,
) -> None:
    if path.stat().st_size > int(max_bytes):
        raise ExperimentExecutionError(
            f"declared artifact exceeds the {int(max_bytes)}-byte parent verification ceiling: {path}"
        )
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = _strict_json(path)
        if payload.get("schema_version") != expected:
            raise ExperimentExecutionError(
                f"declared artifact schema mismatch: {path}"
            )
    elif suffix in {".jsonl", ".ndjson"}:
        row_count = 0
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    row_count += 1
                    if not isinstance(row, dict) or row.get("schema_version") != expected:
                        raise ExperimentExecutionError(
                            f"declared artifact JSONL schema mismatch: {path}"
                        )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExperimentExecutionError(
                f"declared artifact is not valid JSONL: {path}: {exc}"
            ) from exc
        if row_count == 0:
            raise ExperimentExecutionError(f"declared JSONL artifact is empty: {path}")


def _validate_staged_outputs(
    workspace: Path,
    manifest: Mapping[str, Any],
    budget: Mapping[str, Any],
) -> Path:
    deadline = _tree_deadline(
        MAX_OUTPUT_TREE_SECONDS,
        "candidate output verification",
    )
    stage_root = workspace.joinpath(
        *PurePosixPath(str(manifest["candidate_output_root"])).parts
    )
    expected = {
        str(row["path"]).replace("\\", "/"): row
        for row in manifest.get("expected_artifacts") or []
    }
    expected_directories: set[str] = set()
    for relative in expected:
        artifact_path = workspace.joinpath(*PurePosixPath(relative).parts)
        try:
            under_stage = artifact_path.relative_to(stage_root)
        except ValueError as exc:
            raise ExperimentExecutionError(
                f"declared artifact escapes candidate_output_root: {relative}"
            ) from exc
        parent = under_stage.parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent

    actual: set[str] = set()
    pending: list[tuple[Path, int]] = [(stage_root, 0)]
    entry_count = 0
    while pending:
        _check_tree_deadline(deadline, "candidate output verification")
        directory, depth = pending.pop()
        if depth > MAX_OUTPUT_TREE_DEPTH:
            raise ExperimentExecutionError(
                f"candidate output exceeds maximum directory depth {MAX_OUTPUT_TREE_DEPTH}"
            )
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    _check_tree_deadline(deadline, "candidate output verification")
                    entry_count += 1
                    if entry_count > MAX_OUTPUT_TREE_ENTRIES:
                        raise ExperimentExecutionError(
                            "candidate output exceeds "
                            f"{MAX_OUTPUT_TREE_ENTRIES} filesystem entries"
                        )
                    path = Path(entry.path)
                    if entry.is_symlink():
                        raise ExperimentExecutionError(
                            f"candidate output contains a symlink: {path}"
                        )
                    relative_stage = path.relative_to(stage_root).as_posix()
                    if entry.is_dir(follow_symlinks=False):
                        if relative_stage not in expected_directories:
                            raise ExperimentExecutionError(
                                "candidate output contains an unexpected directory: "
                                f"{path}"
                            )
                        pending.append((path, depth + 1))
                    elif entry.is_file(follow_symlinks=False):
                        actual.add(path.relative_to(workspace).as_posix())
                    else:
                        raise ExperimentExecutionError(
                            f"candidate output contains a non-regular entry: {path}"
                        )
        except ExperimentExecutionError:
            raise
        except OSError as exc:
            raise ExperimentExecutionError(
                f"candidate output cannot be enumerated safely: {directory}: {exc}"
            ) from exc
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise ExperimentExecutionError(
            f"candidate artifact inventory mismatch; missing={missing}; extra={extra}"
        )
    output_ceiling = min(
        MAX_PARENT_JSON_BYTES,
        int(float(budget["io_write_mb"]) * 1024**2),
    )
    total_output_bytes = 0
    for relative in expected:
        _check_tree_deadline(deadline, "candidate output verification")
        total_output_bytes += workspace.joinpath(
            *PurePosixPath(relative).parts
        ).stat().st_size
    if total_output_bytes > output_ceiling:
        raise ExperimentExecutionError(
            f"candidate artifacts total {total_output_bytes} bytes, exceeding the "
            f"{output_ceiling}-byte parent verification ceiling"
        )
    per_json_ceiling = min(
        output_ceiling,
        max(1, int(float(budget["memory_mb"]) * 1024**2 * 0.25)),
    )
    for relative, row in expected.items():
        _check_tree_deadline(deadline, "candidate output verification")
        path = workspace.joinpath(*PurePosixPath(relative).parts)
        actual_sha256, actual_size = _sha256_file_bounded(
            path,
            max_bytes=output_ceiling,
            deadline=deadline,
            operation="candidate output verification",
        )
        if actual_size > per_json_ceiling:
            raise ExperimentExecutionError(
                "declared artifact exceeds the "
                f"{per_json_ceiling}-byte verification ceiling: {path}"
            )
        if actual_sha256 != row["sha256"]:
            raise ExperimentExecutionError(
                f"candidate artifact hash mismatch for role={row['role']}: {relative}"
            )
        _verify_embedded_schema(
            path,
            str(row["schema_version"]),
            max_bytes=per_json_ceiling,
        )
    return stage_root


def _commit_candidate_tree(
    stage_root: Path,
    destination: Path,
) -> None:
    if stage_root.is_symlink() or not stage_root.is_dir():
        raise ExperimentExecutionError(
            f"verified candidate staging root must remain a regular directory: {stage_root}"
        )
    if destination.is_symlink() or not destination.is_dir():
        raise ExperimentExecutionError(
            f"candidate_output_root must remain a regular directory: {destination}"
        )
    if any(destination.iterdir()):
        raise ExperimentExecutionError(
            "candidate_output_root changed after verification; refusing to replace it"
        )
    destination.rmdir()
    try:
        stage_root.replace(destination)
    except BaseException:
        destination.mkdir(parents=True, exist_ok=True)
        raise


def _quarantine_candidate_stage(stage_root: Path, run_root: Path) -> Path | None:
    """Detach untrusted/stale output in constant filesystem operations."""

    if stage_root.is_symlink():
        stage_root.unlink()
        stage_root.mkdir(parents=True, exist_ok=False)
        return None
    if not stage_root.exists():
        stage_root.mkdir(parents=True, exist_ok=False)
        return None
    quarantine = run_root / f"discarded-candidate-output-{uuid.uuid4().hex}"
    stage_root.replace(quarantine)
    stage_root.mkdir(parents=True, exist_ok=False)
    return quarantine


def _remove_tree_bounded(
    root: Path,
    *,
    max_entries: int = (2 * MAX_PARENT_TREE_ENTRIES) + MAX_OUTPUT_TREE_ENTRIES + 1_000,
    max_depth: int = MAX_PARENT_TREE_DEPTH + MAX_OUTPUT_TREE_DEPTH + 16,
    max_seconds: float = MAX_PARENT_TREE_SECONDS,
) -> None:
    """Best-effort scratch cleanup without an unbounded recursive traversal."""

    deadline = _tree_deadline(max_seconds, "executor scratch cleanup")
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        root.unlink()
        return
    entry_count = 0
    pending: list[tuple[Path, int, bool]] = [(root, 0, False)]
    while pending:
        _check_tree_deadline(deadline, "executor scratch cleanup")
        path, depth, visited = pending.pop()
        if visited:
            path.rmdir()
            continue
        pending.append((path, depth, True))
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    _check_tree_deadline(deadline, "executor scratch cleanup")
                    entry_count += 1
                    if entry_count > int(max_entries):
                        raise ExperimentExecutionError(
                            "executor scratch cleanup exceeds the "
                            f"{int(max_entries)}-entry ceiling"
                        )
                    child = Path(entry.path)
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        child.unlink()
                        continue
                    child_depth = depth + 1
                    if child_depth > int(max_depth):
                        raise ExperimentExecutionError(
                            "executor scratch cleanup exceeds maximum directory depth "
                            f"{int(max_depth)}"
                        )
                    pending.append((child, child_depth, False))
        except ExperimentExecutionError:
            raise
        except OSError as exc:
            raise ExperimentExecutionError(
                f"executor scratch cleanup cannot enumerate {path}: {exc}"
            ) from exc


def _usage_from_run(run: Mapping[str, Any], budget: Mapping[str, Any]) -> dict[str, float]:
    duration = max(0.0, float(run.get("duration_seconds") or 0.0))
    peaks = run.get("resource_peaks") or {}
    io = run.get("resource_io") or {}
    peak_bytes = max(
        int(peaks.get("private_memory_peak_bytes") or 0),
        int(peaks.get("working_set_peak_bytes") or 0),
    )
    return {
        "duration_seconds": duration,
        # The affinity ceiling makes wall time x cores a conservative upper
        # bound.  It cannot understate child-tree CPU consumption.
        "cpu_seconds": duration * float(budget["cpu_cores"]),
        "peak_memory_mb": peak_bytes / (1024 * 1024),
        "io_read_mb": int(io.get("read_bytes") or 0) / (1024 * 1024),
        "io_write_mb": int(io.get("write_bytes") or 0) / (1024 * 1024),
    }


def _usage_over_budget(usage: Mapping[str, float], budget: Mapping[str, Any]) -> str | None:
    limits = {
        "duration_seconds": float(budget["timeout_seconds"]),
        "cpu_seconds": float(budget["timeout_seconds"]) * float(budget["cpu_cores"]),
        "peak_memory_mb": float(budget["memory_mb"]),
        "io_read_mb": float(budget["io_read_mb"]),
        "io_write_mb": float(budget["io_write_mb"]),
    }
    for field, limit in limits.items():
        if float(usage[field]) > limit:
            return f"{field}={usage[field]:.6f} exceeds declared limit={limit:.6f}"
    return None


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    raise ExperimentExecutionError(f"unsupported decision operator: {operator}")


def _measured_disposition(
    manifest: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> str:
    metrics = observation.get("metrics") or {}
    primary = metrics.get("primary") or {}
    protected_rows = metrics.get("protected") or []
    try:
        primary_value = float(primary["value"])
        protected = {str(row["name"]): float(row["value"]) for row in protected_rows}
        sample_count = int(observation["independent_sample_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentExecutionError(
            f"child observation metrics are incomplete: {exc}"
        ) from exc
    if not math.isfinite(primary_value) or any(
        not math.isfinite(value) for value in protected.values()
    ):
        raise ExperimentExecutionError("child observation metrics must be finite")
    if primary.get("name") != manifest["primary_metric"]["name"]:
        raise ExperimentExecutionError(
            "child primary metric name does not match the manifest"
        )
    if sample_count != float(observation["independent_sample_count"]):
        raise ExperimentExecutionError(
            "child independent_sample_count must be an integer"
        )
    if not isinstance(protected_rows, list) or len(protected) != len(protected_rows):
        raise ExperimentExecutionError(
            "child protected metrics must be a unique-name JSON array"
        )
    if sample_count < int(manifest["minimum_independent_sample"]["count"]):
        return "inconclusive"
    protected_specs = {
        str(row["name"]): row for row in manifest.get("protected_metrics") or []
    }
    if set(protected) != set(protected_specs):
        raise ExperimentExecutionError(
            "child protected metric inventory does not match the manifest"
        )
    if not all(
        _compare(protected[name], str(spec["operator"]), float(spec["threshold"]))
        for name, spec in protected_specs.items()
    ):
        return "regressed"
    decision = manifest["decision_rule"]
    return (
        "resolved"
        if _compare(primary_value, str(decision["operator"]), float(decision["threshold"]))
        else "rejected"
    )


def _one_line(value: Any, *, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit] or "unspecified failure"


def _default_result_path(repo_root: Path, manifest: Mapping[str, Any]) -> Path:
    output_root = repo_root.joinpath(
        *PurePosixPath(str(manifest["candidate_output_root"])).parts
    )
    return output_root / "experiment_result.json"


def _acquire_claim(experiments_root: Path, manifest: Mapping[str, Any]) -> Path:
    claim_root = experiments_root / ".executor_claims"
    if claim_root.is_symlink():
        raise ExperimentExecutionError(
            f"experiment claim directory must not be a symlink: {claim_root}"
        )
    claim_root.mkdir(parents=True, exist_ok=True)
    try:
        claim_root.resolve(strict=True).relative_to(experiments_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExperimentExecutionError(
            f"experiment claim directory escapes the candidate tree: {claim_root}"
        ) from exc
    claim_path = claim_root / f"{manifest['manifest_sha256']}.lock"
    try:
        descriptor = os.open(
            claim_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise ExperimentExecutionError(
            "this experiment is already claimed or has an interrupted claim; "
            f"inspect before manually removing {claim_path}"
        ) from exc
    try:
        os.write(
            descriptor,
            json.dumps(
                {
                    "pid": os.getpid(),
                    "queue_id": manifest["queue_id"],
                    "manifest_sha256": manifest["manifest_sha256"],
                    "claimed_at_utc": utc_iso(),
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
    except BaseException:
        os.close(descriptor)
        descriptor = None
        try:
            claim_path.unlink()
        except OSError:
            pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return claim_path


def _execute_one_impl(
    queue_path: str | Path,
    queue_id: str,
    *,
    repo_root: str | Path = REPO_ROOT,
    result_out: str | Path | None = None,
    now: datetime | None = None,
    runner: Callable[..., Mapping[str, Any]] = run_isolated_subprocess,
    admission_builder: Callable[..., Mapping[str, Any]] = build_capture_resource_gate,
    commit_percent_fn: Callable[[], float | None] = host_commit_percent,
    _claim_observer: Callable[[Path], None],
) -> tuple[dict[str, Any], Path]:
    """Execute exactly one eligible queue entry and persist its terminal result."""

    root = Path(repo_root).resolve(strict=True)
    executor_started_monotonic = time.monotonic()
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ExperimentExecutionError("now must be timezone-aware")
    if not _within_quiet_window(current):
        local = current.astimezone(QUIET_TIMEZONE)
        raise ExperimentExecutionError(
            "isolated experiments run only in the 01:00-08:30 America/Toronto "
            f"quiet window; current local time is {local.isoformat()}"
        )
    selected_queue, manifest = _select_verified_item(
        queue_path,
        queue_id,
        repo_root=root,
    )
    _validated_module(manifest)
    budget = _validated_budget(manifest)
    remaining_seconds = _quiet_window_remaining_seconds(current)
    if int(budget["timeout_seconds"]) > remaining_seconds:
        raise ExperimentExecutionError(
            f"resource_budget.timeout_seconds={budget['timeout_seconds']} exceeds "
            f"the remaining quiet window ({remaining_seconds} seconds)"
        )
    admission = _host_admission(
        root,
        budget,
        now=current,
        admission_builder=admission_builder,
        commit_percent_fn=commit_percent_fn,
    )

    candidate_root = _relative_repo_path(
        root,
        str(manifest["candidate_output_root"]),
        "candidate_output_root",
    )
    experiments_root = root / "artifacts" / "candidates" / str(manifest["candidate_id"]) / "experiments"
    try:
        candidate_root.resolve(strict=True).relative_to(experiments_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExperimentExecutionError(
            "candidate_output_root is outside the exact candidate experiments directory"
        ) from exc
    output_path = Path(result_out) if result_out else _default_result_path(root, manifest)
    if not output_path.is_absolute():
        output_path = root / output_path
    try:
        output_path.resolve(strict=False).relative_to(candidate_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExperimentExecutionError(
            "result_out must remain inside candidate_output_root so artifacts and "
            "their terminal result commit atomically"
        ) from exc
    expected_output_paths = {
        root.joinpath(*PurePosixPath(str(row["path"])).parts).resolve(strict=False)
        for row in manifest.get("expected_artifacts") or []
    }
    if output_path.resolve(strict=False) in expected_output_paths:
        raise ExperimentExecutionError(
            "result_out collides with a manifest-declared experiment artifact"
        )
    if output_path.exists() or output_path.is_symlink():
        raise ExperimentExecutionError(
            f"terminal experiment result already exists and will not be overwritten: {output_path}"
        )
    _reject_symlink_components(output_path, root, "result_out")
    if candidate_root.is_symlink() or not candidate_root.is_dir():
        raise ExperimentExecutionError(
            f"candidate_output_root must be a regular directory: {candidate_root}"
        )
    if any(candidate_root.iterdir()):
        raise ExperimentExecutionError(
            "candidate_output_root must be empty before the experiment is claimed; "
            "inspect or move existing material before retrying"
        )
    release_id = str(manifest["release"]["release_id"])
    protected_paths = _protected_serving_paths(root, release_id)
    serving_before = _tree_fingerprint(protected_paths, repo_root=root)
    bound_release_before = _tree_fingerprint(
        [root / "artifacts" / "releases" / release_id],
        repo_root=root,
    )
    run_root = (
        experiments_root
        / ".executor_runs"
        / f"{manifest['manifest_sha256'][:16]}-{uuid.uuid4().hex}"
    )
    _reject_symlink_components(run_root, root, "executor scratch directory")
    run_root.mkdir(parents=True, exist_ok=False)
    try:
        claim_path = _acquire_claim(experiments_root, manifest)
    except BaseException:
        # Fingerprinting and scratch establishment are pre-claim admission.
        # If another executor wins the exclusive claim, do not leave our
        # otherwise-empty unique scratch directory behind.
        try:
            run_root.rmdir()
        except OSError:
            pass
        raise
    _claim_observer(claim_path)
    started_at = utc_iso(current)
    workspace = run_root / "workspace"
    stage_root = workspace.joinpath(
        *PurePosixPath(str(manifest["candidate_output_root"])).parts
    )
    run: Mapping[str, Any] = {}
    affinity_proof: dict[str, Any] = {}
    sandbox_before: dict[str, Any] = {}
    sandbox_after: dict[str, Any] = {}
    staging_proof: dict[str, Any] = {}
    observation: dict[str, Any] | None = None
    measured_disposition: str | None = None
    failure: dict[str, Any] | None = None
    artifacts: list[Mapping[str, Any]] = []
    returncode = 125
    try:
        workspace, sandbox_before, staging_proof = _prepare_workspace(
            root,
            manifest,
            run_root,
            bound_release_fingerprint=bound_release_before,
            max_copy_bytes=min(
                MAX_EXECUTOR_COPY_BYTES,
                max(1, int(float(budget["io_read_mb"]) * 1024**2)),
            ),
        )
        if _tree_fingerprint(
            [root / "artifacts" / "releases" / release_id],
            repo_root=root,
        )["sha256"] != bound_release_before["sha256"]:
            raise ExperimentExecutionError(
                "manifest-bound release changed while the sandbox was staged"
            )
        callback, affinity_proof = _affinity_callback(int(budget["cpu_cores"]))
        argv = list(manifest["argv"])
        command = [sys.executable, *argv[1:]]
        remaining_at_child_start = max(
            0,
            remaining_seconds
            - int(time.monotonic() - executor_started_monotonic),
        )
        if int(budget["timeout_seconds"]) > remaining_at_child_start:
            raise ExperimentExecutionError(
                "staging consumed too much of the quiet window for the declared timeout"
            )
        run = runner(
            command,
            timeout_seconds=int(budget["timeout_seconds"]),
            working_set_max_bytes=int(budget["memory_mb"]) * 1024 * 1024,
            private_memory_max_bytes=int(budget["memory_mb"]) * 1024 * 1024,
            cwd=str(workspace),
            env=_child_environment(workspace, int(budget["cpu_cores"])),
            output_tail_chars=OUTPUT_TAIL_CHARS,
            output_max_bytes=min(
                MAX_CHILD_OUTPUT_BYTES,
                max(1, int(float(budget["io_write_mb"]) * 1024**2)),
            ),
            io_read_max_bytes=max(
                1,
                int(float(budget["io_read_mb"]) * 1024**2),
            ),
            io_write_max_bytes=max(
                1,
                int(float(budget["io_write_mb"]) * 1024**2),
            ),
            on_started=callback,
        )
        raw_returncode = run.get("returncode")
        returncode = (
            int(raw_returncode)
            if isinstance(raw_returncode, int) and not isinstance(raw_returncode, bool)
            else 125
        )
        sandbox_after = _tree_fingerprint(
            [workspace / "artifacts" / "releases" / release_id],
            repo_root=workspace,
        )
        serving_after = _tree_fingerprint(protected_paths, repo_root=root)
        usage = _usage_from_run(run, budget)
        if serving_after["sha256"] != serving_before["sha256"]:
            failure = {
                "code": "serving_artifact_mutation_detected",
                "detail": "protected serving bytes changed during isolated execution",
                "child_succeeded": returncode == 0,
            }
        elif sandbox_after["sha256"] != sandbox_before["sha256"]:
            failure = {
                "code": "sandbox_release_mutation_detected",
                "detail": "child attempted to mutate its read-only release copy",
                "child_succeeded": returncode == 0,
            }
        elif run.get("runner_error"):
            failure = {
                "code": "containment_runner_error",
                "detail": _one_line(run.get("runner_error")),
                "child_succeeded": returncode == 0,
            }
        elif affinity_proof.get("status") != "PASS":
            failure = {
                "code": "cpu_affinity_unverified",
                "detail": "declared CPU affinity was not applied to the contained child",
                "child_succeeded": returncode == 0,
            }
        elif run.get("resource_limit_exceeded"):
            failure = {
                "code": "resource_budget_exceeded",
                "detail": _one_line(run.get("resource_limit_exceeded")),
                "child_succeeded": returncode == 0,
            }
        elif run.get("timed_out"):
            failure = {
                "code": "timeout_budget_exceeded",
                "detail": f"child exceeded timeout_seconds={budget['timeout_seconds']}",
                "child_succeeded": returncode == 0,
            }
        elif returncode != 0:
            failure = {
                "code": "child_nonzero_exit",
                "detail": _one_line(run.get("stderr") or f"returncode={returncode}"),
                "child_succeeded": returncode == 0,
            }
        else:
            over_budget = _usage_over_budget(usage, budget)
            if over_budget:
                failure = {
                    "code": "resource_budget_exceeded",
                    "detail": over_budget,
                    "child_succeeded": True,
                }
            else:
                try:
                    observation = _parse_observation(str(run.get("stdout") or ""))
                    stage_root = _validate_staged_outputs(workspace, manifest, budget)
                    measured_disposition = _measured_disposition(
                        manifest,
                        observation,
                    )
                    build_experiment_result(
                        {
                            "result_id": "precommit-validation",
                            "queue_id": manifest["queue_id"],
                            "manifest_sha256": manifest["manifest_sha256"],
                            "started_at_utc": started_at,
                            "finished_at_utc": utc_iso(
                                current
                                + timedelta(seconds=float(usage["duration_seconds"]))
                            ),
                            "returncode": returncode,
                            "disposition": measured_disposition,
                            "disposition_reason": "precommit contract validation",
                            "independent_sample_count": int(
                                observation["independent_sample_count"]
                            ),
                            "metrics": observation["metrics"],
                            "artifacts": list(manifest["expected_artifacts"]),
                            "resource_usage": usage,
                        },
                        manifest=manifest,
                    )
                except (ExperimentContractError, ExperimentExecutionError) as exc:
                    failure = {
                        "code": "untrusted_child_output",
                        "detail": _one_line(exc),
                        "child_succeeded": True,
                    }
                else:
                    artifacts = list(manifest["expected_artifacts"])
    except Exception as exc:  # noqa: BLE001 - persist an honest terminal failure
        if failure is None:
            failure = {
                "code": "executor_failure",
                "detail": _one_line(f"{type(exc).__name__}: {exc}"),
                "child_succeeded": returncode == 0,
            }

    usage = _usage_from_run(run, budget)
    try:
        serving_final = _tree_fingerprint(protected_paths, repo_root=root)
    except Exception as exc:  # noqa: BLE001 - terminalize post-child integrity failures
        detail = _one_line(
            f"final protected serving fingerprint failed: {type(exc).__name__}: {exc}"
        )
        serving_final = {
            "status": "BLOCK",
            "error": detail,
        }
        failure = {
            "code": "serving_fingerprint_failed",
            "detail": detail,
            "child_succeeded": returncode == 0,
        }
    else:
        if serving_final["sha256"] != serving_before["sha256"]:
            failure = {
                "code": "serving_artifact_mutation_detected",
                "detail": "protected serving bytes changed before the atomic terminal commit",
                "child_succeeded": returncode == 0,
            }
    superseded = False
    try:
        queue_entry_current = _queue_entry_is_current(
            queue_path,
            queue_id,
            str(manifest["manifest_sha256"]),
            repo_root=root,
        )
        superseded = not queue_entry_current and failure is None
    except ExperimentExecutionError as exc:
        failure = {
            "code": "queue_reverification_failed",
            "detail": _one_line(exc),
            "child_succeeded": returncode == 0,
        }
    finished_at = utc_iso(
        current + timedelta(seconds=float(usage["duration_seconds"]))
    )
    queue_final_reverified = False
    if failure is None and not superseded:
        try:
            superseded = not _queue_entry_is_current(
                queue_path,
                queue_id,
                str(manifest["manifest_sha256"]),
                repo_root=root,
            )
            queue_final_reverified = True
        except ExperimentExecutionError as exc:
            failure = {
                "code": "queue_final_reverification_failed",
                "detail": _one_line(exc),
                "child_succeeded": returncode == 0,
            }
    result_returncode: int | None = returncode
    if superseded:
        disposition = "superseded"
        metrics = {}
        sample_count = 0
        artifacts = []
        failure = None
        result_returncode = None
    elif failure is not None:
        disposition = "inconclusive"
        metrics: Mapping[str, Any] = {}
        sample_count = 0
        artifacts = []
    else:
        if observation is None:
            raise ExperimentExecutionError(
                "executor reached an impossible success state without trusted output"
            )
        if measured_disposition is None:
            raise ExperimentExecutionError(
                "executor reached an impossible success state without a measured disposition"
            )
        disposition = measured_disposition
        metrics = observation["metrics"]
        sample_count = int(observation["independent_sample_count"])
    if disposition not in TERMINAL_DISPOSITIONS:
        raise ExperimentExecutionError(f"executor produced unknown disposition: {disposition}")

    quarantine_path: Path | None = None
    if disposition == "superseded" or failure is not None:
        quarantine_path = _quarantine_candidate_stage(stage_root, run_root)

    result_payload: dict[str, Any] = {
        "result_id": f"{manifest['queue_id']}:{uuid.uuid4().hex}",
        "queue_id": manifest["queue_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "returncode": result_returncode,
        "disposition": disposition,
        "disposition_reason": (
            _one_line((failure or {}).get("detail"))
            if failure
            else "queue entry changed before commit; child output was discarded"
            if superseded
            else "predeclared primary, protected, sample, artifact, and resource rules evaluated"
        ),
        "independent_sample_count": sample_count,
        "metrics": metrics,
        "artifacts": artifacts,
        "resource_usage": usage,
        "execution": {
            "executor": "weather.operations.experiment_executor",
            "queue_path": str(Path(queue_path)),
            "selected_queue_sha256": selected_queue.get("queue_sha256"),
            "queue_final_reverified_immediately_before_terminal_build": (
                queue_final_reverified
            ),
            "declared_argv": list(manifest["argv"]),
            "actual_python": sys.executable,
            "resource_budget": budget,
            "host_admission": admission,
            "remaining_quiet_window_seconds_at_start": remaining_seconds,
            "staging_proof": staging_proof,
            "cpu_seconds_basis": "wall_time_x_enforced_process_affinity_upper_bound",
            "cpu_affinity": affinity_proof,
            "containment": run.get("containment") or {},
            "termination": run.get("termination") or {},
            "resource_limit_exceeded": run.get("resource_limit_exceeded"),
            "bounded_child_output": {
                "tail_bytes_per_stream": OUTPUT_TAIL_CHARS,
                "maximum_total_bytes": min(
                    MAX_CHILD_OUTPUT_BYTES,
                    max(1, int(float(budget["io_write_mb"]) * 1024**2)),
                ),
            },
            "live_io_limits": {
                "read_max_bytes": max(
                    1,
                    int(float(budget["io_read_mb"]) * 1024**2),
                ),
                "write_max_bytes": max(
                    1,
                    int(float(budget["io_write_mb"]) * 1024**2),
                ),
                "enforcement": "contained_process_tree_sampled_during_execution",
            },
            "stdout_tail": str(run.get("stdout") or ""),
            "stderr_tail": str(run.get("stderr") or ""),
            "serving_fingerprint_before": serving_before,
            "serving_fingerprint_after": serving_final,
            "sandbox_release_fingerprint_before": sandbox_before,
            "sandbox_release_fingerprint_after": sandbox_after,
            "candidate_output_committed": True,
            "terminal_commit": "result_and_declared_artifacts_in_one_directory_rename",
            "claim_path": str(claim_path),
            "discarded_output_quarantine": (
                str(quarantine_path) if quarantine_path is not None else None
            ),
            "workspace_cleanup": (
                "quarantined_for_deliberate_bounded_cleanup"
                if quarantine_path is not None
                else "bounded_best_effort_after_atomic_terminal_commit"
            ),
        },
    }
    if failure is not None:
        result_payload["failure"] = failure
    try:
        result = build_experiment_result(result_payload, manifest=manifest)
    except ExperimentContractError as exc:
        raise ExperimentExecutionError(
            f"terminal result failed its self-hashed contract: {exc}"
        ) from exc
    staged_result = stage_root / output_path.relative_to(candidate_root)
    write_json_atomic(staged_result, result, trailing_newline=True)
    _commit_candidate_tree(stage_root, candidate_root)
    if quarantine_path is None:
        try:
            _remove_tree_bounded(run_root)
        except (OSError, ExperimentExecutionError):
            pass
    return result, output_path


def execute_one(
    queue_path: str | Path,
    queue_id: str,
    *,
    repo_root: str | Path = REPO_ROOT,
    result_out: str | Path | None = None,
    now: datetime | None = None,
    runner: Callable[..., Mapping[str, Any]] = run_isolated_subprocess,
    admission_builder: Callable[..., Mapping[str, Any]] = build_capture_resource_gate,
    commit_percent_fn: Callable[[], float | None] = host_commit_percent,
) -> tuple[dict[str, Any], Path]:
    """Execute one eligible queue entry and release every acquired claim on exit.

    Scratch and quarantine trees remain untouched when terminal persistence is
    interrupted so an operator can audit them; only the exclusive claim is
    released by this outer lifecycle guard.
    """

    acquired_claims: list[Path] = []
    try:
        return _execute_one_impl(
            queue_path,
            queue_id,
            repo_root=repo_root,
            result_out=result_out,
            now=now,
            runner=runner,
            admission_builder=admission_builder,
            commit_percent_fn=commit_percent_fn,
            _claim_observer=acquired_claims.append,
        )
    finally:
        for claim_path in reversed(acquired_claims):
            try:
                claim_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # The claim file itself is diagnostic evidence when Windows or
                # an external actor prevents its safe removal.
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run exactly one verified executable experiment manifest entry in an "
            "isolated candidate sandbox."
        )
    )
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE_PATH))
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--result-out", default="")
    args = parser.parse_args(argv)
    try:
        result, path = execute_one(
            args.queue,
            args.queue_id,
            repo_root=args.repo_root,
            result_out=args.result_out or None,
        )
    except ExperimentExecutionError as exc:
        print(
            json.dumps(
                {"status": "BLOCK", "error": f"{type(exc).__name__}: {exc}"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "queue_id": result["queue_id"],
                "disposition": result["disposition"],
                "result_sha256": result["result_sha256"],
                "result_path": str(path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
