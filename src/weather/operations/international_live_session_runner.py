"""Compose, seal, and immediately launch one pre-reviewed fixed live session.

The command accepts only a content-bound session manifest and one fresh public
candidate.  It exposes no market, token, budget, wallet-cap, output, or timing
override arguments.  The generated launcher still requires its bounded human
confirmation before any authenticated boundary can run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from weather.market.mm_geographic_eligibility import (
    GeographicEligibilityError,
    validate_geographic_eligibility_receipt,
)
from weather.market.mm_live_lifecycle_probe import (
    verify_stage1_user_stream_journal,
)
from weather.market.market_registry import REGISTRY as MARKET_REGISTRY
from weather.operations import international_live_time_window as live_time_window
from weather.operations import international_live_wrapper_sealer as fixed_sealer
from weather.operations.live_path_security import (
    CAPTURE_COLOCATED_HOST_PROFILE,
    EXECUTION_HOST_PROFILES,
    PORTABLE_EXECUTION_HOST_PROFILE,
    assert_no_ambient_market_registry_override,
    canonical_windows_powershell,
    launcher_host_attestations_are_valid,
    SESSION_BOOTSTRAP_PATHS,
    current_execution_host_id,
    resolve_production_python_runtime_binding,
    validate_contained_regular_file,
    validate_nonreparse_directory,
    validate_private_attempt_root,
    validate_production_python_runtime_binding,
    validate_regular_nonreparse_file,
)
from weather.schema_registry import schema_version


SESSION_SCHEMA_VERSION = schema_version("international_live_fixed_session_manifest")
COMPOSITION_SCHEMA_VERSION = "international_live_session_composition_v0.2"
RUN_SCHEMA_VERSION = schema_version("international_live_session_run")
CAPTURE_COLOCATED_SESSION_SECONDS = 120
PORTABLE_EXECUTION_SESSION_SECONDS = 240
MAX_SESSION_SECONDS = PORTABLE_EXECUTION_SESSION_SECONDS
MIN_LAUNCH_REMAINING_SECONDS_BY_PROFILE = {
    CAPTURE_COLOCATED_HOST_PROFILE: 90,
    PORTABLE_EXECUTION_HOST_PROFILE: 180,
}
MAX_MIN_LAUNCH_REMAINING_SECONDS = max(
    MIN_LAUNCH_REMAINING_SECONDS_BY_PROFILE.values()
)
SESSION_SECONDS_BY_PROFILE = {
    CAPTURE_COLOCATED_HOST_PROFILE: CAPTURE_COLOCATED_SESSION_SECONDS,
    PORTABLE_EXECUTION_HOST_PROFILE: PORTABLE_EXECUTION_SESSION_SECONDS,
}
LAUNCHER_CLEANUP_MARGIN_SECONDS = 30
MAX_LAUNCHER_RUNTIME_SECONDS = MAX_SESSION_SECONDS
COOPERATIVE_CLEANUP_GRACE_SECONDS = (
    live_time_window.LIVE_WINDOW_CLEANUP_RESERVE_SECONDS
)
PLAN_PREPARATION_REVALIDATION_MARGIN_SECONDS = 40
DERIVED_STAGE_PLAN_TTL_SECONDS = (
    PORTABLE_EXECUTION_SESSION_SECONDS
    + COOPERATIVE_CLEANUP_GRACE_SECONDS
    + PLAN_PREPARATION_REVALIDATION_MARGIN_SECONDS
)


class SessionCompositionError(RuntimeError):
    """Raised when a fixed session cannot be safely composed or launched."""


class LauncherControlError(SessionCompositionError):
    def __init__(self, message, *, cooperative, forced, exit_code):
        self.cooperative = bool(cooperative)
        self.forced = bool(forced)
        self.exit_code = exit_code
        super().__init__(message)


LauncherRunner = Callable[[Path], subprocess.CompletedProcess[str]]


def _verify_launch_git_state(
    production: Mapping[str, Any],
    *,
    execution_host_profile: str,
    git_runner: fixed_sealer.GitRunner,
) -> dict[str, Any]:
    try:
        return fixed_sealer._verify_git_state(
            production,
            execution_host_profile=execution_host_profile,
            git_runner=git_runner,
        )
    except fixed_sealer.SealError as exc:
        raise SessionCompositionError(
            "live remote production equality failed at launch boundary"
        ) from exc


def _default_overlay_file_provider(
    production_root: Path, source_hashes: Mapping[str, str]
) -> Mapping[str, str]:
    from weather.market.live_sdk_overlay import (
        validated_live_sdk_overlay_file_hashes,
    )

    return validated_live_sdk_overlay_file_hashes(
        production_root / fixed_sealer.SDK_OVERLAY_MANIFEST_PATH,
        source_hashes[fixed_sealer.SDK_OVERLAY_MANIFEST_PATH],
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _read_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionCompositionError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise SessionCompositionError(f"{label} is not an object")
    return payload, raw


def _reserve_new(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SessionCompositionError(
            f"terminal evidence namespace is already spent: {path}"
        ) from exc


def _commit_reserved(descriptor: int, payload: bytes) -> None:
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _exact(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SessionCompositionError(f"{label} does not have exact keys")
    return value


def _record(value: Any, label: str) -> dict[str, str]:
    row = _exact(value, {"path", "sha256"}, label)
    try:
        path = validate_regular_nonreparse_file(str(row["path"]))
    except Exception as exc:
        raise SessionCompositionError(f"{label} is redirected or absent") from exc
    digest = str(row["sha256"] or "").lower()
    if (
        fixed_sealer.SHA256_RE.fullmatch(digest) is None
        or not path.is_file()
        or _sha256_file(path) != digest
    ):
        raise SessionCompositionError(f"{label} is absent or hash-mismatched")
    return {"path": str(path), "sha256": digest}


def _default_launcher_runner(
    path: Path,
    *,
    timeout_seconds: float = MAX_LAUNCHER_RUNTIME_SECONDS,
    absolute_deadline: datetime | None = None,
    minimum_start_remaining_seconds: float = 0,
    protected_files: Mapping[Path, str] | None = None,
    cleanup_grace_seconds: float = COOPERATIVE_CLEANUP_GRACE_SECONDS,
) -> subprocess.CompletedProcess[str]:
    if os.name != "nt":
        raise SessionCompositionError("fixed live launcher containment is Windows-only")
    timeout = float(timeout_seconds)
    if not 0 < timeout <= MAX_LAUNCHER_RUNTIME_SECONDS:
        raise SessionCompositionError("launcher timeout is outside the fixed bound")
    if absolute_deadline is not None and (
        absolute_deadline.tzinfo is None or absolute_deadline.utcoffset() is None
    ):
        raise SessionCompositionError("launcher absolute deadline is not timezone-aware")
    minimum_start_remaining = float(minimum_start_remaining_seconds)
    if not 0 <= minimum_start_remaining <= MAX_MIN_LAUNCH_REMAINING_SECONDS:
        raise SessionCompositionError("launcher start reserve is outside the fixed bound")
    cleanup_grace = float(cleanup_grace_seconds)
    if not 0 < cleanup_grace <= COOPERATIVE_CLEANUP_GRACE_SECONDS:
        raise SessionCompositionError("cleanup grace is outside the fixed bound")
    import ctypes
    from ctypes import wintypes

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    CREATE_SUSPENDED = 0x00000004
    CREATE_NEW_PROCESS_GROUP = 0x00000200

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class BasicAccounting(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    ntdll.NtResumeProcess.restype = ctypes.c_long
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise SessionCompositionError("CreateJobObject failed")
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    process = None
    assigned = False
    protected_handles = []

    def active_job_processes() -> int:
        accounting = BasicAccounting()
        returned = wintypes.DWORD()
        if not kernel32.QueryInformationJobObject(
            job,
            1,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned),
        ):
            raise SessionCompositionError("launcher Job accounting query failed")
        return int(accounting.ActiveProcesses)
    try:
        protected_files = dict(protected_files or {})
        for protected in protected_files:
            validate_regular_nonreparse_file(protected)
            handle = kernel32.CreateFileW(
                str(Path(protected).resolve()),
                0x80000000,
                0x00000001,
                None,
                3,
                0x00200000,
                None,
            )
            if handle in (None, 0, wintypes.HANDLE(-1).value):
                raise SessionCompositionError(
                    "sealed artifact could not be locked against write/delete"
                )
            protected_handles.append(handle)
        for protected, expected_hash in protected_files.items():
            validate_regular_nonreparse_file(protected)
            if _sha256_file(protected) != expected_hash:
                raise SessionCompositionError(
                    "sealed artifact changed after its deny-write handle was acquired"
                )
        if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise SessionCompositionError("KILL_ON_JOB_CLOSE configuration failed")
        if absolute_deadline is not None:
            remaining_before_start = (
                absolute_deadline - datetime.now().astimezone()
            ).total_seconds()
            if remaining_before_start < minimum_start_remaining:
                raise SessionCompositionError(
                    "sealed deadline reserve expired before child creation"
                )
            timeout = min(timeout, remaining_before_start)
        powershell = canonical_windows_powershell()
        command = [
            str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(path),
        ]
        process = subprocess.Popen(
            command,
            creationflags=CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP,
        )
        if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            raise SessionCompositionError("launcher assignment to kill-on-close Job failed")
        assigned = True
        if ntdll.NtResumeProcess(int(process._handle)) != 0:
            raise SessionCompositionError("suspended launcher could not be resumed")
        if absolute_deadline is not None:
            timeout = min(
                timeout,
                max(
                    0.001,
                    (
                        absolute_deadline - datetime.now().astimezone()
                    ).total_seconds(),
                ),
            )
        try:
            exit_code = process.wait(timeout=timeout)
        except (KeyboardInterrupt, subprocess.TimeoutExpired) as exc:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                cleanup_deadline = time.monotonic() + cleanup_grace
                while time.monotonic() < cleanup_deadline:
                    cleanup_exit = process.poll()
                    if cleanup_exit is not None and active_job_processes() == 0:
                        cooperative = True
                        forced = False
                        break
                    time.sleep(0.05)
                else:
                    cleanup_exit = process.poll()
                    cooperative = False
                    forced = True
            except (OSError, SessionCompositionError):
                cleanup_exit = None
                cooperative = False
                forced = True
            raise LauncherControlError(
                "sealed launcher was interrupted or exceeded its fixed runtime",
                cooperative=cooperative,
                forced=forced,
                exit_code=cleanup_exit,
            ) from exc
        quiesce_deadline = time.monotonic() + 2.0
        while active_job_processes() != 0 and time.monotonic() < quiesce_deadline:
            time.sleep(0.05)
        if active_job_processes() != 0:
            raise LauncherControlError(
                "launcher root exited before its contained child tree",
                cooperative=False,
                forced=True,
                exit_code=exit_code,
            )
        return subprocess.CompletedProcess(command, exit_code, "", "")
    finally:
        kernel32.CloseHandle(job)
        if process is not None and process.poll() is None:
            if not assigned:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            if process.poll() is None:
                raise SessionCompositionError("launcher child-tree termination was not proved")
        for handle in reversed(protected_handles):
            kernel32.CloseHandle(handle)


def _child_execution_facts(
    stage: str,
    attempt_root: Path,
    seal_result: Mapping[str, Any],
    *,
    expected_scope: Mapping[str, Any],
    expected_production: Mapping[str, Any],
    expected_interpreter_binding: Mapping[str, str],
    expected_lineage: Mapping[str, Mapping[str, str]],
    expected_candidate_sha256: str,
    expected_candidate: Mapping[str, Any],
    exit_code: int | None,
) -> dict[str, Any]:
    path = attempt_root / fixed_sealer.OUTPUT_LAYOUTS[stage][
        "wrapper_execution_receipt"
    ]
    unknown = {
        "validation": "UNKNOWN",
        "path": str(path),
        "sha256": None,
        "status": "UNKNOWN",
        "phase": "UNKNOWN",
        "live_mutation_attempted": "UNKNOWN",
        "order_submit_attempted": "UNKNOWN",
        "authenticated_exchange_write_attempted": "UNKNOWN",
        "authenticated_user_stream_subscription_sent": "UNKNOWN",
        "bootstrap_phase": "UNKNOWN",
        "bootstrap_recovery_phase": "UNKNOWN",
        "exchange_mutation_attempt_counts": "UNKNOWN",
        "credential_topology": "UNKNOWN",
        "credential_values_read_in_memory": "UNKNOWN",
    }
    if not path.is_file():
        return unknown
    try:
        validate_contained_regular_file(attempt_root, path)
        payload, raw = _read_object(path, "wrapper execution receipt")
        wrapper = payload.get("wrapper") or {}
        expected_mode = (
            None
            if stage == "stage0"
            else ("cancel_all" if stage == "stage1_cancel_all" else "dead_man")
        )
        seal_record = seal_result.get("seal_receipt") or {}
        seal_path = Path(str(seal_record.get("path") or ""))
        validate_contained_regular_file(attempt_root, seal_path)
        if (
            not seal_path.is_file()
            or _sha256_file(seal_path) != seal_record.get("sha256")
        ):
            raise SessionCompositionError("seal receipt changed before consumption")
        seal, _seal_raw = _read_object(seal_path, "seal receipt")
        seal_scope = seal.get("scope") or {}
        seal_production = seal.get("production") or {}
        try:
            seal_interpreter_binding = validate_production_python_runtime_binding(
                seal_production,
                production_root=expected_production["root"],
            )
        except Exception as exc:
            raise SessionCompositionError(
                "seal receipt interpreter binding is invalid"
            ) from exc
        seal_inputs = {
            row.get("role"): row
            for row in (seal.get("inputs") or [])
            if isinstance(row, dict) and row.get("role")
        }
        for role in ("session_manifest", "session_manifest_sidecar", "seal_spec"):
            record = expected_lineage[role]
            lineage_path = Path(record["path"])
            if (
                not lineage_path.is_file()
                or _sha256_file(lineage_path) != record["sha256"]
            ):
                raise SessionCompositionError(f"{role} changed before child consumption")
        if not all(
            (
                seal.get("schema_version")
                == fixed_sealer.RECEIPT_SCHEMA_VERSION,
                seal.get("status") == "PASS",
                seal.get("stage") == stage,
                seal.get("wrapper") == seal_result["wrapper"],
                seal.get("launcher") == seal_result["launcher"],
                seal.get("seal_spec") == expected_lineage["seal_spec"],
                seal_production.get("commit") == expected_production["commit"],
                seal_production.get("tree") == expected_production["tree"],
                seal_interpreter_binding == dict(expected_interpreter_binding),
                seal_scope.get("target_date") == expected_scope["target_date"],
                str(seal_scope.get("condition_id") or "").lower()
                == str(expected_scope["condition_id"]).lower(),
                str(seal_scope.get("token_id") or "")
                == str(expected_scope["token_id"]),
                float(seal_scope.get("requested_budget_pusd"))
                == float(expected_scope["requested_budget_pusd"]),
                seal_scope.get("execution_host_profile")
                == expected_scope["execution_host_profile"],
                seal_scope.get("execution_host_id")
                == expected_scope["execution_host_id"],
                seal_scope.get("market_id") == expected_scope["market_id"],
                seal_scope.get("market_timezone")
                == expected_scope["market_timezone"],
                seal_scope.get("cancellation_mode")
                == (expected_mode or "not_applicable"),
            )
        ):
            raise SessionCompositionError("seal receipt lineage or scope changed")
        if not all(
            (
                payload.get("schema_version") == fixed_sealer.EXECUTION_SCHEMA_VERSION,
                payload.get("stage") == stage,
                payload.get("status") in {"PASS", "FAIL"},
                payload.get("production_tip") == expected_production["commit"],
                payload.get("target_date") == expected_scope["target_date"],
                str(payload.get("condition_id") or "").lower()
                == str(expected_scope["condition_id"]).lower(),
                str(payload.get("token_id") or "")
                == str(expected_scope["token_id"]),
                float(payload.get("requested_budget_pusd"))
                == float(expected_scope["requested_budget_pusd"]),
                payload.get("execution_host_profile")
                == expected_scope["execution_host_profile"],
                payload.get("execution_host_id")
                == expected_scope["execution_host_id"],
                (
                    expected_mode is None
                    or payload.get("cancellation_mode") == expected_mode
                ),
                wrapper.get("path") == seal_result["wrapper"]["path"],
                wrapper.get("sha256") == seal_result["wrapper"]["sha256"],
            )
        ):
            raise SessionCompositionError("wrapper execution receipt identity changed")
        artifacts = payload.get("artifacts") or {}
        output_layout = fixed_sealer.OUTPUT_LAYOUTS[stage]
        required_roles = (
            {
                "doctor_receipt_out",
                "geography_precredential_receipt_out",
                "geography_premutation_receipt_out",
                "bootstrap_out",
                "command_receipt_out",
                "user_stream_journal_out",
            }
            if stage == "stage0"
            else {
                "doctor_receipt_out",
                "geography_precredential_receipt_out",
                "geography_presubmit_receipt_out",
                "result_out",
                "command_receipt_out",
                "user_stream_journal_out",
                "lifecycle_journal_out",
            }
        )
        if payload["status"] == "PASS" and set(artifacts) != required_roles:
            raise SessionCompositionError("PASS execution receipt has incomplete artifacts")
        if not set(artifacts).issubset(required_roles):
            raise SessionCompositionError("execution receipt has an unknown artifact role")
        for role, artifact in artifacts.items():
            artifact_path = Path(str(artifact.get("path") or ""))
            validate_contained_regular_file(attempt_root, artifact_path)
            expected_path = (
                attempt_root / output_layout[role.removesuffix("_out")]
            ).resolve()
            if (
                artifact_path.resolve() != expected_path
                or not artifact_path.is_file()
                or _sha256_file(artifact_path) != artifact.get("sha256")
            ):
                raise SessionCompositionError("wrapper execution artifact changed")
            if role.startswith("geography_"):
                try:
                    geographic_payload = _read_object(
                        artifact_path,
                        "geographic eligibility receipt",
                    )[0]
                    validate_geographic_eligibility_receipt(
                        geographic_payload,
                        require_fresh=False,
                    )
                except GeographicEligibilityError as exc:
                    raise SessionCompositionError(
                        "wrapper geographic eligibility artifact is invalid"
                    ) from exc
        mutation = payload.get("live_mutation_attempted", "UNKNOWN")
        order_submit = payload.get("order_submit_attempted", "UNKNOWN")
        authenticated_write = payload.get(
            "authenticated_exchange_write_attempted", "UNKNOWN"
        )
        credential = payload.get("credential_values_read_in_memory", "UNKNOWN")
        if any(
            value not in {True, False, "UNKNOWN"}
            for value in (mutation, order_submit, authenticated_write, credential)
        ):
            raise SessionCompositionError("wrapper execution facts are malformed")
        if payload["status"] == "PASS":
            attestations = payload.get("host_attestations")
            expected_flag_hashes = sorted(
                row["sha256"] for row in seal_scope.get("reviewed_status_flags") or []
            )
            if not all(
                (
                    exit_code == 0,
                    payload.get("phase") == "complete",
                    payload.get("exception_type") is None,
                    credential is True,
                    mutation is True,
                    authenticated_write is True,
                    order_submit is (stage != "stage0"),
                    len(
                        str(
                            payload.get("confirmation_scope_display_sha256")
                            or ""
                        )
                    )
                    == 64,
                    launcher_host_attestations_are_valid(
                        attestations,
                        expected_execution_host_profile=expected_scope[
                            "execution_host_profile"
                        ],
                        expected_execution_host_id=expected_scope[
                            "execution_host_id"
                        ],
                        expected_status_flag_sha256=expected_flag_hashes,
                    ),
                )
            ):
                raise SessionCompositionError("PASS execution facts are not terminal")
            command_path = (
                attempt_root / output_layout["command_receipt"]
            ).resolve()
            validate_contained_regular_file(attempt_root, command_path)
            command = _read_object(command_path, "command receipt")[0]
            command_paths = command.get("paths") or {}
            topology = command.get("credential_topology") or {}
            reference_record = seal_inputs.get("credential_reference_manifest") or {}
            reference_manifest = _read_object(
                Path(str(reference_record.get("path") or "")),
                "credential reference manifest",
            )[0]
            expected_command_paths = (
                {
                    "bootstrap": str(
                        (attempt_root / output_layout["bootstrap"]).resolve()
                    ),
                    "receipt": str(command_path),
                    "user_stream_journal": str(
                        (attempt_root / output_layout["user_stream_journal"]).resolve()
                    ),
                    "geography_premutation_receipt": str(
                        (
                            attempt_root
                            / output_layout["geography_premutation_receipt"]
                        ).resolve()
                    ),
                }
                if stage == "stage0"
                else {
                    "result": str(
                        (attempt_root / output_layout["result"]).resolve()
                    ),
                    "receipt": str(command_path),
                    "user_stream_journal": str(
                        (attempt_root / output_layout["user_stream_journal"]).resolve()
                    ),
                    "lifecycle_journal": str(
                        (attempt_root / output_layout["lifecycle_journal"]).resolve()
                    ),
                }
            )
            stage0_mutation_geography_bound = True
            if stage == "stage0":
                bootstrap_payload = _read_object(
                    attempt_root / output_layout["bootstrap"],
                    "Stage 0 bootstrap",
                )[0]
                mutation_artifact = artifacts.get(
                    "geography_premutation_receipt_out", {}
                )
                mutation_receipt = _read_object(
                    Path(str(mutation_artifact.get("path") or "")),
                    "Stage 0 pre-mutation geography receipt",
                )[0]
                bootstrap_geography = bootstrap_payload.get(
                    "mutation_geographic_eligibility", {}
                )
                stage0_mutation_geography_bound = all(
                    (
                        bootstrap_payload.get("schema_version")
                        == "mm_platform_bootstrap_v0.6",
                        bootstrap_geography.get("status") == "PASS",
                        bootstrap_geography.get("eligible") is True,
                        bootstrap_geography.get("receipt_payload_sha256")
                        == mutation_receipt.get("receipt_payload_sha256"),
                    )
                )
            if not all(
                (
                    command.get("schema_version")
                    == "mm_live_pilot_command_receipt_v0.2",
                    command.get("status") == "PASS",
                    command.get("command")
                    == ("stage0" if stage == "stage0" else "stage1"),
                    command.get("target_date") == expected_scope["target_date"],
                    str(command.get("condition_id") or "").lower()
                    == str(expected_scope["condition_id"]).lower(),
                    str(command.get("token_id") or "")
                    == str(expected_scope["token_id"]),
                    float(command.get("requested_budget_pusd"))
                    == float(expected_scope["requested_budget_pusd"]),
                    (command.get("cleanup") or {}).get("ok") is True,
                    command.get("credential_values_read_in_memory") is True,
                    command.get("exception_type") is None,
                    command_paths == expected_command_paths,
                    (
                        command.get("exchange_mutation_attempted") is True
                        if stage == "stage0"
                        else command.get("exchange_mutation_attempted") is True
                        and command.get("cancellation_mode") == expected_mode
                    ),
                    command.get("authenticated_exchange_write_attempted") is True,
                    command.get("order_submit_attempted") is (stage != "stage0"),
                    (
                        command.get("authenticated_user_stream_subscription_sent")
                        is True
                        and command.get("bootstrap_phase") == "complete"
                        and command.get("exchange_mutation_attempt_counts")
                        == {"cancel_all": 1, "heartbeat": 2}
                        if stage == "stage0"
                        else True
                    ),
                    (
                        payload.get("authenticated_user_stream_subscription_sent")
                        is command.get(
                            "authenticated_user_stream_subscription_sent"
                        )
                        and payload.get("bootstrap_phase")
                        == command.get("bootstrap_phase")
                        and payload.get("bootstrap_recovery_phase")
                        == command.get("bootstrap_recovery_phase")
                        and payload.get("exchange_mutation_attempt_counts")
                        == command.get("exchange_mutation_attempt_counts")
                        if stage == "stage0"
                        else True
                    ),
                    stage0_mutation_geography_bound,
                    (
                        (command.get("mutation_geographic_eligibility") or {}).get(
                            "path"
                        )
                        == artifacts.get(
                            "geography_premutation_receipt_out", {}
                        ).get("path")
                        and (
                            command.get("mutation_geographic_eligibility") or {}
                        ).get("sha256")
                        == artifacts.get(
                            "geography_premutation_receipt_out", {}
                        ).get("sha256")
                        if stage == "stage0"
                        else True
                    ),
                    topology.get("manifest_wallet_address")
                    == str(reference_manifest.get("wallet_address") or "").lower(),
                    all(
                        topology.get(name) is True
                        for name in (
                            "derived_signer_matches_manifest",
                            "api_owner_matches_manifest",
                            "order_signer_matches_manifest",
                            "funder_matches_identity",
                        )
                    ),
                )
            ):
                raise SessionCompositionError("PASS command receipt is incomplete")
            if stage != "stage0":
                result_path = (
                    attempt_root / output_layout["result"]
                ).resolve()
                validate_contained_regular_file(attempt_root, result_path)
                result = _read_object(result_path, "Stage 1 result")[0]
                stream_path = (
                    attempt_root / output_layout["user_stream_journal"]
                ).resolve()
                final_stream_evidence = verify_stage1_user_stream_journal(
                    stream_path,
                    result,
                )
                result_intent = result.get("intent") or {}
                try:
                    result_notional = Decimal(str(result.get("order_notional_usdc")))
                    cancellation_elapsed = float(
                        result.get("cancellation_elapsed_seconds")
                    )
                    candidate_intent = expected_candidate["intent"]
                    candidate_price = Decimal(str(candidate_intent["price"]))
                    candidate_size = Decimal(str(candidate_intent["size"]))
                    candidate_notional = Decimal(
                        str(candidate_intent["notional_pusd"])
                    )
                    candidate_tick = Decimal(str(expected_candidate["tick_size"]))
                    candidate_minimum = Decimal(
                        str(expected_candidate["order_min_size"])
                    )
                    result_price = Decimal(str(result_intent.get("price")))
                    result_size = Decimal(str(result_intent.get("size")))
                    collateral_balance = Decimal(
                        str(result.get("submit_collateral_balance_usdc"))
                    )
                    collateral_allowance = Decimal(
                        str(result.get("submit_collateral_allowance_usdc"))
                    )
                    candidate_fee_rate = Decimal(
                        str(expected_candidate["fee_rate"])
                    )
                    result_candidate_fee_rate = Decimal(
                        str(result.get("candidate_fee_rate"))
                    )
                    result_current_fee_rate_bps = Decimal(
                        str(result.get("current_fee_rate_bps"))
                    )
                except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
                    raise SessionCompositionError(
                        "Stage 1 result numeric evidence is invalid"
                    ) from exc
                if not all(
                    (
                        result.get("schema_version")
                        == "mm_live_lifecycle_probe_v0.3",
                        result.get("status") == "PASS",
                        result.get("platform") == "polymarket_global",
                        result.get("settlement_unit") == "pUSD",
                        result.get("cancellation_mode") == expected_mode,
                        str(result.get("condition_id") or "").lower()
                        == str(expected_scope["condition_id"]).lower(),
                        str(result.get("token_id") or "")
                        == str(expected_scope["token_id"]),
                        result.get("candidate_plan_sha256")
                        == expected_candidate_sha256,
                        result.get("candidate_semantic_plan_sha256")
                        == expected_candidate["semantic_plan_sha256"],
                        result.get("bootstrap_schema_version")
                        == "mm_platform_bootstrap_v0.6",
                        result.get("bootstrap_sha256")
                        == (seal_inputs.get("bootstrap") or {}).get("sha256"),
                        result.get("heartbeat_acknowledged") is True,
                        result.get("submit_boundary_heartbeat_acknowledged") is True,
                        result.get("submit_boundary_market_rules_verified") is True,
                        result.get(
                            "submit_boundary_geography_before_heartbeat_verified"
                        )
                        is True,
                        result.get(
                            "post_sign_order_placement_boundary_verified"
                        )
                        is True,
                        result_candidate_fee_rate == candidate_fee_rate,
                        result_current_fee_rate_bps
                        == candidate_fee_rate * Decimal("10000"),
                        result.get("candidate_neg_risk")
                        is expected_candidate["neg_risk"],
                        result.get("current_neg_risk")
                        is expected_candidate["neg_risk"],
                        result.get("starting_zero_open_orders_verified") is True,
                        result.get("starting_zero_positions_verified") is True,
                        result_intent.get("side") == "BUY",
                        str(result_intent.get("token_id") or "")
                        == str(expected_scope["token_id"]),
                        result_price == candidate_price == candidate_tick,
                        result_size == candidate_size == candidate_minimum,
                        result_notional
                        == candidate_notional
                        == candidate_price * candidate_size,
                        Decimal("0") < result_notional <= Decimal("10"),
                        bool(str(result.get("order_id") or "")),
                        result.get("placement_status") == "live",
                        result.get("open_order_observed") is True,
                        result.get("authoritative_user_event_observed") is True,
                        result.get("cancellation_observed") is True,
                        result.get("zero_open_orders_verified") is True,
                        result.get("zero_positions_verified") is True,
                        result.get("no_trade_lifecycle_event_observed") is True,
                        result.get("terminal_rest_order_verified") is True,
                        result.get("terminal_rest_zero_matched_verified") is True,
                        result.get("account_trades_rest_verified") is True,
                        result.get("scoped_account_trade_count") == 0,
                        result.get("post_cancel_quiescence_seconds") == 2.0,
                        result.get("collateral_no_fill_reconciliation_verified")
                        is True,
                        len(
                            str(
                                result.get("submit_collateral_snapshot_sha256")
                                or ""
                            )
                        )
                        == 64,
                        result.get("submit_collateral_snapshot_sha256")
                        == result.get("post_cancel_collateral_snapshot_sha256"),
                        Decimal("10") <= collateral_balance <= Decimal("100"),
                        collateral_allowance >= Decimal("10"),
                        result.get("terminal_user_event_observed") is True,
                        result.get("secret_values_redacted") is True,
                        Path(str(result.get("journal_path") or "")).resolve()
                        == (
                            attempt_root / output_layout["lifecycle_journal"]
                        ).resolve(),
                        result.get("journal_sha256")
                        == artifacts["lifecycle_journal_out"]["sha256"],
                        Path(
                            str(result.get("user_stream_journal_path") or "")
                        ).resolve()
                        == stream_path,
                        result.get("user_stream_journal_sha256")
                        == artifacts["user_stream_journal_out"]["sha256"],
                        result.get(
                            "cleanup_final_user_stream_journal_sha256"
                        )
                        == artifacts["user_stream_journal_out"]["sha256"],
                        final_stream_evidence.get("sha256")
                        == result.get("user_stream_journal_sha256"),
                        final_stream_evidence.get(
                            "terminal_stream_stopped_verified"
                        )
                        is True,
                        type(result.get("user_stream_journal_row_count")) is int,
                        result.get("user_stream_journal_row_count")
                        == final_stream_evidence.get("row_count"),
                        type(result.get("user_stream_scoped_order_event_count"))
                        is int,
                        result.get("user_stream_scoped_order_event_count")
                        == final_stream_evidence.get("scoped_order_event_count"),
                        (
                            result.get("cancel_response_present") is True
                            if expected_mode == "cancel_all"
                            else (
                                result.get("cancel_response_present") is False
                                and 10 <= cancellation_elapsed <= 15
                            )
                        ),
                    )
                ):
                    raise SessionCompositionError("Stage 1 result lineage changed")
        return {
            "validation": "PASS",
            "path": str(path),
            "sha256": _sha256_bytes(raw),
            "status": payload["status"],
            "phase": str(payload.get("phase") or "UNKNOWN"),
            "live_mutation_attempted": mutation,
            "order_submit_attempted": order_submit,
            "authenticated_exchange_write_attempted": authenticated_write,
            "authenticated_user_stream_subscription_sent": (
                payload.get("authenticated_user_stream_subscription_sent", "UNKNOWN")
            ),
            "bootstrap_phase": payload.get("bootstrap_phase", "UNKNOWN"),
            "bootstrap_recovery_phase": payload.get(
                "bootstrap_recovery_phase", "UNKNOWN"
            ),
            "exchange_mutation_attempt_counts": payload.get(
                "exchange_mutation_attempt_counts", "UNKNOWN"
            ),
            "credential_topology": topology if payload["status"] == "PASS" else "UNKNOWN",
            "credential_values_read_in_memory": credential,
        }
    except BaseException as exc:
        return {
            **unknown,
            "validation": "FAIL",
            "exception_type": type(exc).__name__,
        }


def _derived_lineage_inputs(stage: str, attempt_root: Path) -> dict[str, dict[str, str]]:
    if stage == "stage0":
        return {}
    relative_paths = {
        "bootstrap": "stage0/bootstrap.json",
        "stage0_receipt": "stage0/command-receipt.json",
        "stage0_seal_receipt": "seal/stage0-seal-receipt.json",
        "stage0_run_receipt": "session/stage0-run-receipt.json",
        "stage0_run_receipt_sidecar": "session/stage0-run-receipt.json.sha256",
        "stage0_wrapper_execution_receipt": "stage0/wrapper-execution-receipt.json",
    }
    if stage == "stage1_dead_man":
        relative_paths.update(
            {
                "cancel_all_seal_receipt": "seal/stage1-cancel-all-seal-receipt.json",
                "cancel_all_run_receipt": "session/stage1_cancel_all-run-receipt.json",
                "cancel_all_run_receipt_sidecar": (
                    "session/stage1_cancel_all-run-receipt.json.sha256"
                ),
                "cancel_all_wrapper_execution_receipt": (
                    "stage1-cancel-all/wrapper-execution-receipt.json"
                ),
                "cancel_all_command_receipt": "stage1-cancel-all/command-receipt.json",
                "cancel_all_result": "stage1-cancel-all/result.json",
                "cancel_all_lifecycle_journal": "stage1-cancel-all/lifecycle.jsonl",
            }
        )
    records = {}
    for role, relative in relative_paths.items():
        raw_path = attempt_root / relative
        if not raw_path.is_file():
            raise SessionCompositionError(f"required prior lineage is absent: {role}")
        path = validate_contained_regular_file(attempt_root, raw_path)
        records[role] = {"path": str(path), "sha256": _sha256_file(path)}
    return records


def compose_and_run_live_session(
    session_manifest_path: str | Path,
    fresh_candidate_path: str | Path,
    *,
    expected_session_manifest_sha256: str,
    now: datetime | None = None,
    seal_function=fixed_sealer.seal_fixed_scope,
    launcher_runner: LauncherRunner = _default_launcher_runner,
    before_launch: Callable[[], None] | None = None,
    launch_git_runner: fixed_sealer.GitRunner | None = None,
    attempt_root_validator=None,
    clock: Callable[[], datetime] | None = None,
    overlay_file_provider=None,
) -> dict[str, Any]:
    """Seal and launch one immutable session while its candidate remains current."""

    assert_no_ambient_market_registry_override()
    current = now or (clock() if clock is not None else datetime.now().astimezone())
    if current.tzinfo is None:
        raise SessionCompositionError("session clock must be timezone-aware")
    try:
        manifest_path = validate_regular_nonreparse_file(session_manifest_path)
    except Exception as exc:
        raise SessionCompositionError("session manifest is redirected or absent") from exc
    manifest, manifest_raw = _read_object(manifest_path, "session manifest")
    manifest_raw_sha256 = _sha256_bytes(manifest_raw)
    if manifest_raw_sha256 != str(expected_session_manifest_sha256).lower():
        raise SessionCompositionError("independently reviewed session manifest hash changed")
    sidecar_path = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    validate_regular_nonreparse_file(sidecar_path)
    try:
        sidecar_text = sidecar_path.read_text(encoding="ascii")
    except OSError as exc:
        raise SessionCompositionError("reviewed session-manifest sidecar is absent") from exc
    if sidecar_text != f"{manifest_raw_sha256}  {manifest_path.name}\n":
        raise SessionCompositionError("reviewed session-manifest sidecar does not match")
    stage = str(manifest.get("stage"))
    if stage not in fixed_sealer.STAGES:
        raise SessionCompositionError("session stage is unsupported")
    expected_manifest_keys = {
        "schema_version",
        "manifest_sha256",
        "stage",
        "production",
        "scope",
        "inputs",
        "reviewed_status_flags",
        "template_sha256",
        "source_sha256",
        "production_python_sha256",
        "session_bootstrap_sha256",
    }
    _exact(
        manifest,
        expected_manifest_keys,
        "session manifest",
    )
    if (
        manifest["schema_version"] != SESSION_SCHEMA_VERSION
        or manifest["manifest_sha256"] != _canonical_payload_sha256(manifest)
    ):
        raise SessionCompositionError("session manifest semantic hash changed")
    scope = _exact(
        manifest["scope"],
        {
            "target_date",
            "condition_id",
            "token_id",
            "requested_budget_pusd",
            "attempt_root",
            "lease_workload",
            "execution_host_profile",
            "execution_host_id",
            "market_id",
            "market_timezone",
            "max_session_seconds",
        },
        "session scope",
    )
    execution_host_profile = str(scope["execution_host_profile"] or "")
    execution_host_id = str(scope["execution_host_id"] or "").lower()
    market = MARKET_REGISTRY.get(str(scope["market_id"] or ""))
    expected_session_seconds = SESSION_SECONDS_BY_PROFILE.get(
        execution_host_profile
    )
    minimum_launch_remaining_seconds = (
        MIN_LAUNCH_REMAINING_SECONDS_BY_PROFILE.get(execution_host_profile)
    )
    if (
        execution_host_profile not in EXECUTION_HOST_PROFILES
        or fixed_sealer.SHA256_RE.fullmatch(execution_host_id) is None
        or execution_host_id != current_execution_host_id()
        or market is None
        or scope["market_timezone"] != market.timezone
        or (
            execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE
            and manifest["reviewed_status_flags"] != []
        )
        or float(scope["requested_budget_pusd"])
        != float(fixed_sealer.FIRST_TEST_REQUESTED_BUDGET_PUSD)
        or expected_session_seconds is None
        or minimum_launch_remaining_seconds is None
        or int(scope["max_session_seconds"]) != expected_session_seconds
    ):
        raise SessionCompositionError(
            "session host, budget, or duration differs from the fixed contract"
        )
    production_root = validate_nonreparse_directory(
        str(manifest["production"]["root"])
    )
    production_python = validate_regular_nonreparse_file(
        str(manifest["production"]["python"])
    )
    production_python_sha256 = str(manifest["production_python_sha256"] or "").lower()
    if (
        fixed_sealer.SHA256_RE.fullmatch(production_python_sha256) is None
        or _sha256_file(production_python) != production_python_sha256
    ):
        raise SessionCompositionError("reviewed production interpreter changed")
    try:
        expected_interpreter_binding = resolve_production_python_runtime_binding(
            production_root,
            interpreter_redirector=production_python,
        )
    except Exception as exc:
        raise SessionCompositionError(
            "reviewed production interpreter chain is invalid"
        ) from exc
    if (
        expected_interpreter_binding["interpreter_redirector_sha256"]
        != production_python_sha256
    ):
        raise SessionCompositionError("reviewed production interpreter changed")
    bootstrap_hashes = _exact(
        manifest["session_bootstrap_sha256"],
        set(SESSION_BOOTSTRAP_PATHS),
        "session bootstrap hashes",
    )
    for relative, expected_hash in bootstrap_hashes.items():
        path = validate_regular_nonreparse_file(production_root / relative)
        if (
            fixed_sealer.SHA256_RE.fullmatch(str(expected_hash).lower()) is None
            or _sha256_file(path) != str(expected_hash).lower()
        ):
            raise SessionCompositionError("session bootstrap source changed")
    raw_attempt_root = Path(str(scope["attempt_root"]))
    try:
        attempt_root = validate_nonreparse_directory(raw_attempt_root)
    except Exception as exc:
        raise SessionCompositionError("attempt root is redirected or absent") from exc
    if not manifest_path.is_relative_to(attempt_root):
        raise SessionCompositionError("session manifest is outside its existing attempt root")
    try:
        validator = attempt_root_validator or validate_private_attempt_root
        attempt_root_security = dict(validator(attempt_root))
    except Exception as exc:
        raise SessionCompositionError("attempt root failed private ACL/reparse checks") from exc
    if attempt_root_security.get("status") != "PASS":
        raise SessionCompositionError("attempt root security validation did not pass")
    expected_manifest_path = attempt_root / "inputs" / f"{stage}-session-manifest.json"
    if manifest_path != expected_manifest_path.resolve():
        raise SessionCompositionError("session manifest path is not canonical")

    expected_static_roles = {
        "identity", "credential_import_receipt",
        "credential_reference_manifest", "event_metadata",
    }
    static_inputs = _exact(
        manifest["inputs"],
        expected_static_roles,
        "session inputs",
    )
    input_records = {
        role: _record(value, f"session inputs.{role}")
        for role, value in static_inputs.items()
    }
    expected_identity = (
        attempt_root / fixed_sealer.INPUT_LAYOUTS[stage]["identity"]
    ).resolve()
    if Path(input_records["identity"]["path"]) != expected_identity:
        raise SessionCompositionError("session identity path is not canonical")
    stage_specific_roles = ("event_metadata",)
    for role in stage_specific_roles:
        expected_path = (
            attempt_root / fixed_sealer.INPUT_LAYOUTS[stage][role]
        ).resolve()
        if Path(input_records[role]["path"]) != expected_path:
            raise SessionCompositionError(
                f"session {role.replace('_', ' ')} path is not canonical"
            )
    input_records.update(_derived_lineage_inputs(stage, attempt_root))

    try:
        candidate_source = validate_regular_nonreparse_file(fresh_candidate_path)
    except Exception as exc:
        raise SessionCompositionError("fresh candidate is redirected or absent") from exc
    candidate_role = "scope_plan" if stage == "stage0" else "candidate_plan"
    candidate_destination = (
        attempt_root / fixed_sealer.INPUT_LAYOUTS[stage][candidate_role]
    ).resolve()
    if candidate_source == candidate_destination or candidate_destination.exists():
        raise SessionCompositionError("candidate destination must be new and distinct")
    candidate_raw = candidate_source.read_bytes()
    candidate_hash = _sha256_bytes(candidate_raw)
    candidate_payload, _unused = _read_object(candidate_source, "fresh candidate")
    try:
        gate_loader = (
            fixed_sealer.load_stage0_scope_gate
            if stage == "stage0"
            else fixed_sealer.load_stage1_lifecycle_plan_gate
        )
        candidate_gate = gate_loader(
            candidate_source,
            str(scope["target_date"]),
            expected_condition_id=str(scope["condition_id"]).lower(),
            expected_token_id=str(scope["token_id"]),
            now=current,
        )
    except RuntimeError as exc:
        raise SessionCompositionError(
            "fresh candidate failed the canonical constrained gate"
        ) from exc
    try:
        fixed_sealer.validate_bound_stage0_event_metadata(
            Path(input_records["event_metadata"]["path"]),
            candidate_gate["event_metadata"],
            target_date=str(scope["target_date"]),
            current_gamma=candidate_gate["current_gamma"],
            now=current,
        )
    except RuntimeError as exc:
        raise SessionCompositionError(
            "fresh candidate event metadata differs from the reviewed manifest"
        ) from exc
    candidate_selected = candidate_payload.get("selected") or {}
    if (
        candidate_selected.get("location_id") != scope["market_id"]
        or candidate_gate.get("market_id") != scope["market_id"]
    ):
        raise SessionCompositionError(
            "fresh candidate market differs from the reviewed session scope"
        )
    expected_candidate = {
        "neg_risk": candidate_gate["neg_risk"],
        "semantic_plan_sha256": candidate_gate["semantic_plan_sha256"],
    }
    if stage != "stage0":
        expected_candidate.update(
            {
                "intent": dict(candidate_gate["stage1_intent"]),
                "tick_size": candidate_gate["tick_size"],
                "order_min_size": candidate_gate["order_min_size"],
                "fee_rate": candidate_gate["fee_rate"],
            }
        )
    try:
        created = datetime.fromisoformat(
            str(candidate_payload["created_at_utc"]).replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            str(candidate_payload["expires_at_utc"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise SessionCompositionError("fresh candidate has no valid lifetime") from exc
    if created.tzinfo is None or expires.tzinfo is None:
        raise SessionCompositionError(
            "fresh candidate lifetime is not timezone-aware"
        )
    if expires - created != timedelta(seconds=DERIVED_STAGE_PLAN_TTL_SECONDS):
        raise SessionCompositionError(
            "fresh candidate lifetime differs from the derived "
            f"{DERIVED_STAGE_PLAN_TTL_SECONDS}-second portable envelope"
        )
    candidate_remaining_at_composition = (
        expires.astimezone(current.tzinfo) - current
    ).total_seconds()
    if (
        execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE
        and (
            current - created.astimezone(current.tzinfo)
        ).total_seconds() > PLAN_PREPARATION_REVALIDATION_MARGIN_SECONDS
    ):
        raise SessionCompositionError(
            "fresh candidate has consumed the portable plan's fixed 40-second "
            "preparation and revalidation margin"
        )
    stop = current + timedelta(seconds=int(scope["max_session_seconds"]))
    contained_end = stop + timedelta(seconds=COOPERATIVE_CLEANUP_GRACE_SECONDS)
    if contained_end > expires.astimezone(current.tzinfo):
        raise SessionCompositionError(
            "fresh candidate does not leave the full profile-fixed session "
            "and cleanup envelope"
        )
    target_date = str(scope["target_date"])
    calendar_timezone = (
        live_time_window.LIVE_WINDOW_TIMEZONE
        if execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        else ZoneInfo(str(scope["market_timezone"]))
    )
    if (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and any(
            value.astimezone(calendar_timezone).date().isoformat()
            != target_date
            for value in (current, stop, contained_end)
        )
    ):
        raise SessionCompositionError(
            "candidate-derived execution timestamps do not share the target date"
        )
    if (
        execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE
        and not live_time_window.portable_execution_window_is_supported(
            current,
            stop,
            target_date=target_date,
            market_timezone=calendar_timezone,
        )
    ):
        raise SessionCompositionError(
            "portable execution requires a current-day or next-day market target"
        )
    if (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and not live_time_window.execution_window_is_supported(
            current,
            stop,
            target_date=str(scope["target_date"]),
        )
    ):
        raise SessionCompositionError(
            "candidate-derived execution and cleanup window is outside the "
            "supported 00:30-09:00 America/Toronto live window"
        )
    if (stop - current).total_seconds() < expected_session_seconds:
        raise SessionCompositionError(
            "fresh candidate does not leave the full profile-fixed session envelope"
        )
    candidate_destination.parent.mkdir(parents=True, exist_ok=True)
    fixed_sealer._write_new(candidate_destination, candidate_raw)
    if _sha256_file(candidate_source) != candidate_hash:
        raise SessionCompositionError("fresh candidate changed while being copied")
    input_records[candidate_role] = {
        "path": str(candidate_destination),
        "sha256": candidate_hash,
    }

    prepared = current.isoformat()
    seal_spec = {
        "schema_version": fixed_sealer.SPEC_SCHEMA_VERSION,
        "stage": stage,
        "prepared_at_local": prepared,
        "production": manifest["production"],
        "scope": {
            "target_date": scope["target_date"],
            "condition_id": scope["condition_id"],
            "token_id": scope["token_id"],
            "requested_budget_pusd": scope["requested_budget_pusd"],
            "run_not_before_local": current.isoformat(),
            "run_not_after_local": stop.isoformat(),
            "attempt_root": str(attempt_root),
            "lease_workload": scope["lease_workload"],
            "execution_host_profile": execution_host_profile,
            "execution_host_id": execution_host_id,
            "market_id": scope["market_id"],
            "market_timezone": scope["market_timezone"],
        },
        "inputs": input_records,
        "reviewed_status_flags": manifest["reviewed_status_flags"],
        "template_sha256": manifest["template_sha256"],
        "source_sha256": manifest["source_sha256"],
    }
    spec_path = attempt_root / "inputs" / f"{stage}-seal-spec.json"
    fixed_sealer._write_new(spec_path, fixed_sealer._canonical_json(seal_spec))
    seal_result = seal_function(spec_path, now=current)

    composition_path = attempt_root / "session" / f"{stage}-composition-receipt.json"
    composition = {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "status": "PASS",
        "stage": stage,
        "prepared_at_local": prepared,
        "session_manifest": {
            "path": str(manifest_path),
            "sha256": manifest_raw_sha256,
            "semantic_sha256": manifest["manifest_sha256"],
            "sidecar_path": str(sidecar_path),
            "sidecar_sha256": _sha256_file(sidecar_path),
        },
        "candidate": {"source_sha256": candidate_hash, "sealed_path": str(candidate_destination)},
        "candidate_remaining_seconds_at_composition": candidate_remaining_at_composition,
        "seal_result": seal_result,
        "attempt_root_security": attempt_root_security,
        "run_not_after_local": stop.isoformat(),
        "live_mutation_attempted": False,
        "order_submit_attempted": False,
        "authenticated_exchange_write_attempted": False,
        "credential_value_read": False,
    }
    composition_raw = fixed_sealer._canonical_json(composition)
    fixed_sealer._write_new(composition_path, composition_raw)
    fixed_sealer._write_new(
        composition_path.with_suffix(composition_path.suffix + ".sha256"),
        f"{_sha256_bytes(composition_raw)}  {composition_path.name}\n".encode("ascii"),
    )
    composition_sidecar = composition_path.with_suffix(
        composition_path.suffix + ".sha256"
    )
    run_receipt_path = attempt_root / "session" / f"{stage}-run-receipt.json"
    run_receipt_sidecar = run_receipt_path.with_suffix(
        run_receipt_path.suffix + ".sha256"
    )
    if run_receipt_path.exists() or run_receipt_sidecar.exists():
        raise SessionCompositionError("terminal run-receipt namespace is not new")
    run_intent_path = attempt_root / "session" / f"{stage}-run-intent.json"
    run_intent = {
        "schema_version": "international_live_session_run_intent_v0.1",
        "status": "ARMED",
        "stage": stage,
        "created_at_local": datetime.now().astimezone().isoformat(),
        "session_manifest": composition["session_manifest"],
        "composition_receipt": {
            "path": str(composition_path),
            "sha256": _sha256_bytes(composition_raw),
        },
        "seal_receipt": seal_result["seal_receipt"],
        "launcher": seal_result["launcher"],
        "wrapper": seal_result["wrapper"],
        "candidate_sha256": candidate_hash,
        "run_not_after_local": stop.isoformat(),
        "terminal_receipt_path": str(run_receipt_path),
        "live_mutation_attempted": False,
        "order_submit_attempted": False,
        "authenticated_exchange_write_attempted": False,
        "credential_values_read_in_memory": False,
    }
    run_intent_raw = fixed_sealer._canonical_json(run_intent)
    fixed_sealer._write_new(run_intent_path, run_intent_raw)
    run_intent_sidecar = run_intent_path.with_suffix(run_intent_path.suffix + ".sha256")
    fixed_sealer._write_new(
        run_intent_sidecar,
        f"{_sha256_bytes(run_intent_raw)}  {run_intent_path.name}\n".encode(
            "ascii"
        ),
    )

    if before_launch is not None:
        before_launch()
    launch_now = (
        clock()
        if clock is not None
        else (datetime.now().astimezone() if now is None else current)
    )
    if (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and launch_now.astimezone(calendar_timezone)
        .date()
        .isoformat()
        != str(scope["target_date"])
    ):
        raise SessionCompositionError("launch boundary no longer matches the target date")
    if (
        execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE
        and not live_time_window.portable_execution_window_is_supported(
            launch_now,
            stop,
            target_date=str(scope["target_date"]),
            market_timezone=calendar_timezone,
        )
    ):
        raise SessionCompositionError(
            "launch boundary is not current-day or next-day target eligible"
        )
    if (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and not live_time_window.execution_window_is_supported(
            launch_now,
            stop,
            target_date=str(scope["target_date"]),
        )
    ):
        raise SessionCompositionError(
            "execution and cleanup boundary is outside the supported "
            "00:30-09:00 America/Toronto live window"
        )
    if _sha256_file(candidate_destination) != candidate_hash:
        raise SessionCompositionError("sealed candidate changed before launch")
    launch_validator = (
        fixed_sealer._validate_stage0_scope
        if stage == "stage0"
        else fixed_sealer._validate_candidate
    )
    launch_candidate = launch_validator(
        candidate_destination,
        target_date=str(scope["target_date"]),
        condition_id=str(scope["condition_id"]).lower(),
        token_id=str(scope["token_id"]),
        execution_host_profile=execution_host_profile,
        now=launch_now,
        run_stop=stop,
    )
    launch_expiry = datetime.fromisoformat(launch_candidate["expires_at_utc"])
    candidate_remaining_seconds = (
        launch_expiry.astimezone(launch_now.tzinfo) - launch_now
    ).total_seconds()
    effective_deadline_remaining_seconds = (
        min(launch_expiry.astimezone(stop.tzinfo), stop) - launch_now
    ).total_seconds()
    if effective_deadline_remaining_seconds < minimum_launch_remaining_seconds:
        raise SessionCompositionError(
            "fresh candidate no longer leaves the fixed pre-submit launch reserve"
        )
    launcher = Path(seal_result["launcher"]["path"]).resolve()
    if _sha256_file(launcher) != seal_result["launcher"]["sha256"]:
        raise SessionCompositionError("sealed launcher changed before launch")
    protected_expected = {
        launcher: seal_result["launcher"]["sha256"],
        Path(seal_result["wrapper"]["path"]): seal_result["wrapper"]["sha256"],
        candidate_destination: candidate_hash,
        spec_path: _sha256_file(spec_path),
        manifest_path: manifest_raw_sha256,
        sidecar_path: _sha256_file(sidecar_path),
        Path(seal_result["seal_receipt"]["path"]): seal_result["seal_receipt"][
            "sha256"
        ],
        Path(seal_result["seal_receipt_sidecar"]): _sha256_file(
            Path(seal_result["seal_receipt_sidecar"])
        ),
        composition_path: _sha256_bytes(composition_raw),
        composition_sidecar: _sha256_file(composition_sidecar),
        run_intent_path: _sha256_bytes(run_intent_raw),
        run_intent_sidecar: _sha256_file(run_intent_sidecar),
    }
    for record in input_records.values():
        protected_expected[Path(record["path"]).resolve()] = record["sha256"]
    for relative, expected_hash in manifest["source_sha256"].items():
        protected_expected[(production_root / relative).resolve()] = expected_hash
    protected_expected[production_python] = production_python_sha256
    protected_expected[
        Path(expected_interpreter_binding["pyvenv_config"])
    ] = expected_interpreter_binding["pyvenv_config_sha256"]
    protected_expected[
        Path(expected_interpreter_binding["runtime_process_image"])
    ] = expected_interpreter_binding["runtime_process_image_sha256"]
    for relative, expected_hash in bootstrap_hashes.items():
        protected_expected[(production_root / relative).resolve()] = str(
            expected_hash
        ).lower()
    overlay_files = (overlay_file_provider or _default_overlay_file_provider)(
        production_root,
        manifest["source_sha256"],
    )
    for path, expected_hash in overlay_files.items():
        protected_expected[Path(path)] = expected_hash
    for protected, expected_hash in protected_expected.items():
        try:
            protected.relative_to(attempt_root)
        except ValueError:
            validate_regular_nonreparse_file(protected)
        else:
            validate_contained_regular_file(attempt_root, protected)
        if _sha256_file(protected) != expected_hash:
            raise SessionCompositionError("sealed launch artifact changed at boundary")
    attempt_parents = {
        path.parent
        for path in protected_expected
        if path.is_relative_to(attempt_root)
    }
    for protected_parent in attempt_parents:
        if (attempt_root_validator or validate_private_attempt_root)(
            protected_parent
        ).get("status") != "PASS":
            raise SessionCompositionError("sealed artifact directory ACL is not private")
    boundary_git_runner = launch_git_runner
    if boundary_git_runner is None and seal_function is fixed_sealer.seal_fixed_scope:
        boundary_git_runner = fixed_sealer._default_git_runner
    if boundary_git_runner is not None:
        _verify_launch_git_state(
            manifest["production"],
            execution_host_profile=execution_host_profile,
            git_runner=boundary_git_runner,
        )
    launcher_timeout_seconds = min(
        MAX_LAUNCHER_RUNTIME_SECONDS,
        effective_deadline_remaining_seconds,
    )
    run_receipt_descriptor = _reserve_new(run_receipt_path)
    try:
        run_sidecar_descriptor = _reserve_new(run_receipt_sidecar)
    except BaseException:
        os.close(run_receipt_descriptor)
        raise
    process = None
    launch_exception: BaseException | None = None
    try:
        if launcher_runner is _default_launcher_runner:
            process = launcher_runner(
                launcher,
                timeout_seconds=launcher_timeout_seconds,
                absolute_deadline=stop,
                minimum_start_remaining_seconds=minimum_launch_remaining_seconds,
                protected_files=protected_expected,
            )
        else:
            process = launcher_runner(launcher)
    except BaseException as exc:
        launch_exception = exc
    exit_code = int(process.returncode) if process is not None else (
        launch_exception.exit_code
        if isinstance(launch_exception, LauncherControlError)
        else None
    )
    child = _child_execution_facts(
        stage,
        attempt_root,
        seal_result,
        expected_scope=scope,
        expected_production=manifest["production"],
        expected_interpreter_binding=expected_interpreter_binding,
        expected_lineage={
            "session_manifest": {
                "path": str(manifest_path),
                "sha256": manifest_raw_sha256,
            },
            "session_manifest_sidecar": {
                "path": str(sidecar_path),
                "sha256": _sha256_file(sidecar_path),
            },
            "seal_spec": {
                "path": str(spec_path.resolve()),
                "sha256": _sha256_file(spec_path),
            },
        },
        expected_candidate_sha256=candidate_hash,
        expected_candidate=expected_candidate,
        exit_code=exit_code,
    )
    if launch_exception is not None:
        terminal_status = "INTERRUPTED"
    elif child["validation"] != "PASS":
        terminal_status = "UNKNOWN"
    elif exit_code == 0 and child["status"] == "PASS":
        terminal_status = "PASS"
    else:
        terminal_status = "FAIL"
    run_receipt = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": terminal_status,
        "stage": stage,
        "execution_host_profile": execution_host_profile,
        "execution_host_id": execution_host_id,
        "finished_at_local": datetime.now().astimezone().isoformat(),
        "launcher": seal_result["launcher"],
        "wrapper": seal_result["wrapper"],
        "seal_receipt": seal_result["seal_receipt"],
        "session_manifest": composition["session_manifest"],
        "composition_receipt": run_intent["composition_receipt"],
        "run_intent": {
            "path": str(run_intent_path),
            "sha256": _sha256_bytes(run_intent_raw),
        },
        "candidate_sha256": candidate_hash,
        "candidate_remaining_seconds_before_launch": candidate_remaining_seconds,
        "effective_deadline_remaining_seconds_before_launch": (
            effective_deadline_remaining_seconds
        ),
        "launcher_timeout_seconds": launcher_timeout_seconds,
        "launcher_absolute_deadline": stop.isoformat(),
        "cooperative_cleanup_grace_seconds": COOPERATIVE_CLEANUP_GRACE_SECONDS,
        "exit_code": exit_code,
        "launcher_exception_type": (
            type(launch_exception).__name__ if launch_exception is not None else None
        ),
        "launcher_teardown": {
            "cooperative_cleanup_signal_sent": isinstance(
                launch_exception, LauncherControlError
            ),
            "cooperative_exit_observed": (
                launch_exception.cooperative
                if isinstance(launch_exception, LauncherControlError)
                else False
            ),
            "forced_job_teardown": (
                launch_exception.forced
                if isinstance(launch_exception, LauncherControlError)
                else False
            ),
        },
        "child_execution": child,
        "live_mutation_attempted": child["live_mutation_attempted"],
        "order_submit_attempted": child["order_submit_attempted"],
        "authenticated_exchange_write_attempted": child[
            "authenticated_exchange_write_attempted"
        ],
        "credential_topology": child["credential_topology"],
        "credential_values_read_in_memory": child[
            "credential_values_read_in_memory"
        ],
    }
    run_receipt_raw = fixed_sealer._canonical_json(run_receipt)
    _commit_reserved(run_receipt_descriptor, run_receipt_raw)
    _commit_reserved(
        run_sidecar_descriptor,
        f"{_sha256_bytes(run_receipt_raw)}  {run_receipt_path.name}\n".encode(
            "ascii"
        ),
    )
    if launch_exception is not None:
        raise launch_exception
    if terminal_status != "PASS":
        raise SessionCompositionError(
            "sealed session did not produce a validated PASS execution receipt"
        )
    return run_receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-manifest", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--expected-session-manifest-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = compose_and_run_live_session(
            args.session_manifest,
            args.candidate,
            expected_session_manifest_sha256=args.expected_session_manifest_sha256,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCK",
                    "exception_type": type(exc).__name__,
                    "live_mutation_attempted": "UNKNOWN",
                    "credential_values_read_in_memory": "UNKNOWN",
                    "terminal_receipt_may_exist": True,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
