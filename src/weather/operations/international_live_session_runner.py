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
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from weather.operations import international_live_wrapper_sealer as fixed_sealer


SESSION_SCHEMA_VERSION = "international_live_fixed_session_manifest_v0.1"
COMPOSITION_SCHEMA_VERSION = "international_live_session_composition_v0.1"
RUN_SCHEMA_VERSION = "international_live_session_run_v0.1"
MAX_SESSION_SECONDS = 90
MIN_LAUNCH_REMAINING_SECONDS = 30


class SessionCompositionError(RuntimeError):
    """Raised when a fixed session cannot be safely composed or launched."""


LauncherRunner = Callable[[Path], subprocess.CompletedProcess[str]]


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


def _exact(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SessionCompositionError(f"{label} does not have exact keys")
    return value


def _record(value: Any, label: str) -> dict[str, str]:
    row = _exact(value, {"path", "sha256"}, label)
    path = Path(str(row["path"])).resolve()
    digest = str(row["sha256"] or "").lower()
    if (
        fixed_sealer.SHA256_RE.fullmatch(digest) is None
        or not path.is_file()
        or _sha256_file(path) != digest
    ):
        raise SessionCompositionError(f"{label} is absent or hash-mismatched")
    return {"path": str(path), "sha256": digest}


def _default_launcher_runner(path: Path) -> subprocess.CompletedProcess[str]:
    if os.name != "nt":
        raise SessionCompositionError("fixed live launcher containment is Windows-only")
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
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    ntdll.NtResumeProcess.restype = ctypes.c_long
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise SessionCompositionError("CreateJobObject failed")
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    process = None
    try:
        if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise SessionCompositionError("KILL_ON_JOB_CLOSE configuration failed")
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(path),
        ]
        process = subprocess.Popen(
            command,
            creationflags=CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP,
        )
        if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
            raise SessionCompositionError("launcher assignment to kill-on-close Job failed")
        if ntdll.NtResumeProcess(int(process._handle)) != 0:
            raise SessionCompositionError("suspended launcher could not be resumed")
        return subprocess.CompletedProcess(command, process.wait(), "", "")
    finally:
        kernel32.CloseHandle(job)
        if process is not None and process.poll() is None:
            process.wait(timeout=10)


def _child_execution_facts(
    stage: str,
    attempt_root: Path,
    seal_result: Mapping[str, Any],
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
        "credential_values_read_in_memory": "UNKNOWN",
    }
    if not path.is_file():
        return unknown
    try:
        payload, raw = _read_object(path, "wrapper execution receipt")
        wrapper = payload.get("wrapper") or {}
        if not all(
            (
                payload.get("schema_version")
                == "international_live_fixed_scope_execution_v0.2",
                payload.get("stage") == stage,
                payload.get("status") in {"PASS", "FAIL"},
                wrapper.get("path") == seal_result["wrapper"]["path"],
                wrapper.get("sha256") == seal_result["wrapper"]["sha256"],
            )
        ):
            raise SessionCompositionError("wrapper execution receipt identity changed")
        for artifact in (payload.get("artifacts") or {}).values():
            artifact_path = Path(str(artifact.get("path") or ""))
            if (
                not artifact_path.is_file()
                or _sha256_file(artifact_path) != artifact.get("sha256")
            ):
                raise SessionCompositionError("wrapper execution artifact changed")
        mutation = payload.get("live_mutation_attempted", "UNKNOWN")
        credential = payload.get("credential_values_read_in_memory", "UNKNOWN")
        if mutation not in {True, False, "UNKNOWN"} or credential not in {
            True, False, "UNKNOWN"
        }:
            raise SessionCompositionError("wrapper execution facts are malformed")
        return {
            "validation": "PASS",
            "path": str(path),
            "sha256": _sha256_bytes(raw),
            "status": payload["status"],
            "phase": str(payload.get("phase") or "UNKNOWN"),
            "live_mutation_attempted": mutation,
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
        "stage0_wrapper_execution_receipt": "stage0/wrapper-execution-receipt.json",
    }
    records = {}
    for role, relative in relative_paths.items():
        path = (attempt_root / relative).resolve()
        if not path.is_file():
            raise SessionCompositionError(f"required prior lineage is absent: {role}")
        records[role] = {"path": str(path), "sha256": _sha256_file(path)}
    return records


def compose_and_run_live_session(
    session_manifest_path: str | Path,
    fresh_candidate_path: str | Path,
    *,
    now: datetime | None = None,
    seal_function=fixed_sealer.seal_fixed_scope,
    launcher_runner: LauncherRunner = _default_launcher_runner,
    before_launch: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Seal and launch one immutable session while its candidate remains current."""

    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        raise SessionCompositionError("session clock must be timezone-aware")
    manifest_path = Path(session_manifest_path).resolve()
    manifest, manifest_raw = _read_object(manifest_path, "session manifest")
    manifest_raw_sha256 = _sha256_bytes(manifest_raw)
    sidecar_path = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    try:
        sidecar_text = sidecar_path.read_text(encoding="ascii")
    except OSError as exc:
        raise SessionCompositionError("reviewed session-manifest sidecar is absent") from exc
    if sidecar_text != f"{manifest_raw_sha256}  {manifest_path.name}\n":
        raise SessionCompositionError("reviewed session-manifest sidecar does not match")
    _exact(
        manifest,
        {
            "schema_version",
            "manifest_sha256",
            "stage",
            "production",
            "scope",
            "inputs",
            "reviewed_status_flags",
            "template_sha256",
            "source_sha256",
        },
        "session manifest",
    )
    if (
        manifest["schema_version"] != SESSION_SCHEMA_VERSION
        or manifest["manifest_sha256"] != _canonical_payload_sha256(manifest)
    ):
        raise SessionCompositionError("session manifest semantic hash changed")
    stage = str(manifest["stage"])
    if stage not in fixed_sealer.STAGES:
        raise SessionCompositionError("session stage is unsupported")
    scope = _exact(
        manifest["scope"],
        {
            "target_date",
            "condition_id",
            "token_id",
            "requested_budget_pusd",
            "attempt_root",
            "lease_workload",
            "max_session_seconds",
        },
        "session scope",
    )
    if (
        float(scope["requested_budget_pusd"])
        != float(fixed_sealer.FIRST_TEST_REQUESTED_BUDGET_PUSD)
        or int(scope["max_session_seconds"]) < MIN_LAUNCH_REMAINING_SECONDS
        or int(scope["max_session_seconds"]) > MAX_SESSION_SECONDS
    ):
        raise SessionCompositionError("session budget or duration exceeds the fixed contract")
    attempt_root = Path(str(scope["attempt_root"])).resolve()
    if not attempt_root.is_dir() or not manifest_path.is_relative_to(attempt_root):
        raise SessionCompositionError("session manifest is outside its existing attempt root")
    expected_manifest_path = attempt_root / "inputs" / f"{stage}-session-manifest.json"
    if manifest_path != expected_manifest_path.resolve():
        raise SessionCompositionError("session manifest path is not canonical")

    static_inputs = _exact(
        manifest["inputs"],
        {"identity", "credential_import_receipt", "credential_reference_manifest"},
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
    input_records.update(_derived_lineage_inputs(stage, attempt_root))

    candidate_source = Path(fresh_candidate_path).resolve()
    if not candidate_source.is_file():
        raise SessionCompositionError("fresh candidate is absent")
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
        expires = datetime.fromisoformat(
            str(candidate_payload["expires_at_utc"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise SessionCompositionError("fresh candidate has no valid expiry") from exc
    if expires.tzinfo is None:
        raise SessionCompositionError("fresh candidate expiry is not timezone-aware")
    stop = min(
        current + timedelta(seconds=int(scope["max_session_seconds"])),
        expires.astimezone(current.tzinfo),
    )
    if (stop - current).total_seconds() < MIN_LAUNCH_REMAINING_SECONDS:
        raise SessionCompositionError("fresh candidate leaves too little launch time")
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
            "run_not_before_local": (current - timedelta(seconds=1)).isoformat(),
            "run_not_after_local": stop.isoformat(),
            "attempt_root": str(attempt_root),
            "lease_workload": scope["lease_workload"],
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
        "seal_result": seal_result,
        "run_not_after_local": stop.isoformat(),
        "live_mutation_attempted": False,
        "credential_value_read": False,
    }
    composition_raw = fixed_sealer._canonical_json(composition)
    fixed_sealer._write_new(composition_path, composition_raw)
    fixed_sealer._write_new(
        composition_path.with_suffix(composition_path.suffix + ".sha256"),
        f"{_sha256_bytes(composition_raw)}  {composition_path.name}\n".encode("ascii"),
    )

    if before_launch is not None:
        before_launch()
    launch_now = datetime.now().astimezone() if now is None else current
    if _sha256_file(candidate_destination) != candidate_hash:
        raise SessionCompositionError("sealed candidate changed before launch")
    fixed_sealer._validate_candidate(
        candidate_destination,
        target_date=str(scope["target_date"]),
        condition_id=str(scope["condition_id"]).lower(),
        token_id=str(scope["token_id"]),
        now=launch_now,
        run_stop=stop,
    )
    launcher = Path(seal_result["launcher"]["path"]).resolve()
    if _sha256_file(launcher) != seal_result["launcher"]["sha256"]:
        raise SessionCompositionError("sealed launcher changed before launch")
    process = None
    launch_exception: BaseException | None = None
    try:
        process = launcher_runner(launcher)
    except BaseException as exc:
        launch_exception = exc
    child = _child_execution_facts(stage, attempt_root, seal_result)
    exit_code = int(process.returncode) if process is not None else None
    if launch_exception is not None:
        terminal_status = "INTERRUPTED"
    elif child["validation"] != "PASS":
        terminal_status = "UNKNOWN"
    elif exit_code == 0 and child["status"] == "PASS":
        terminal_status = "PASS"
    else:
        terminal_status = "FAIL"
    run_receipt_path = attempt_root / "session" / f"{stage}-run-receipt.json"
    run_receipt = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": terminal_status,
        "stage": stage,
        "finished_at_local": datetime.now().astimezone().isoformat(),
        "launcher": seal_result["launcher"],
        "candidate_sha256": candidate_hash,
        "exit_code": exit_code,
        "launcher_exception_type": (
            type(launch_exception).__name__ if launch_exception is not None else None
        ),
        "child_execution": child,
        "live_mutation_attempted": child["live_mutation_attempted"],
        "credential_values_read_in_memory": child[
            "credential_values_read_in_memory"
        ],
    }
    fixed_sealer._write_new(
        run_receipt_path,
        fixed_sealer._canonical_json(run_receipt),
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = compose_and_run_live_session(args.session_manifest, args.candidate)
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
