"""Public execution-host profiles and stable attended-host identity."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
from pathlib import Path

from weather.paths import REPO_ROOT

if os.name == "nt":  # pragma: no cover - exercised by Windows operations tests.
    import ctypes
    import winreg


CAPTURE_COLOCATED_HOST_PROFILE = "capture_colocated_v1"
PORTABLE_EXECUTION_HOST_PROFILE = "portable_execution_v1"
EXECUTION_HOST_PROFILES = frozenset(
    {CAPTURE_COLOCATED_HOST_PROFILE, PORTABLE_EXECUTION_HOST_PROFILE}
)
EXECUTION_HOST_ID_DOMAIN = "international_live_execution_host_v2"
EXECUTION_PRINCIPAL_ID_DOMAIN = "international_live_execution_principal_v1"
EXECUTION_HOST_ASSIGNMENT_SCHEMA_VERSION = (
    "international_live_execution_host_assignment_v0.1"
)
EXECUTION_HOST_ASSIGNMENT_RELATIVE_PATH = Path(
    "config/international_live_execution_host.json"
)
DEFAULT_EXECUTION_HOST_ASSIGNMENT_PATH = (
    REPO_ROOT / EXECUTION_HOST_ASSIGNMENT_RELATIVE_PATH
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ASSIGNMENT_BYTES = 16_384


class ExecutionHostAssignmentError(RuntimeError):
    """Raised when the single-active portable executor contract is not exact."""


def _machine_identity() -> str:
    if os.name == "nt":
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                value, value_type = winreg.QueryValueEx(key, "MachineGuid")
        except OSError as exc:
            raise RuntimeError("Windows machine identity is unavailable") from exc
        if value_type != winreg.REG_SZ:
            raise RuntimeError("Windows machine identity has an unexpected type")
        machine = str(value).strip().casefold()
    else:
        # Non-Windows support exists only so static/unit checks can import this
        # module. International live execution remains Windows-only.
        machine = platform.node().strip().casefold()
    if not machine:
        raise RuntimeError("execution host identity is unavailable")
    return machine


def current_execution_host_id() -> str:
    """Return a non-secret binding to this Windows installation."""

    material = "\0".join((EXECUTION_HOST_ID_DOMAIN, _machine_identity()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _principal_identity() -> str:
    if os.name != "nt":
        # Non-Windows support exists only for deterministic unit checks. Live
        # execution is Windows-only and never relies on this fallback.
        identity = str(os.getuid()) if hasattr(os, "getuid") else platform.node()
        if not identity:
            raise RuntimeError("execution principal identity is unavailable")
        return identity.casefold()

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    advapi32.GetTokenInformation.restype = ctypes.c_int
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int

    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise RuntimeError("Windows execution principal token is unavailable")
    try:
        required = ctypes.c_ulong(0)
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if required.value <= 0:
            raise RuntimeError("Windows execution principal identity is unavailable")
        token_info = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, 1, token_info, required, ctypes.byref(required)
        ):
            raise RuntimeError("Windows execution principal identity is unavailable")
        sid_pointer = ctypes.cast(token_info, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_string = ctypes.c_void_p()
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_string)):
            raise RuntimeError("Windows execution principal SID is unavailable")
        try:
            sid = ctypes.wstring_at(sid_string).strip().casefold()
        finally:
            kernel32.LocalFree(sid_string)
    finally:
        kernel32.CloseHandle(token)
    if not sid:
        raise RuntimeError("Windows execution principal identity is unavailable")
    return sid


def current_execution_principal_id() -> str:
    """Return a non-secret binding to the current Windows token SID."""

    material = "\0".join((EXECUTION_PRINCIPAL_ID_DOMAIN, _principal_identity()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def current_execution_session_id() -> int:
    """Read this process's Windows session; zero is the service session.

    A nonzero session is necessary for this attended lane, not proof of human
    presence or geographic eligibility. Those remain operator obligations.
    """

    if os.name != "nt":
        raise RuntimeError("attended execution requires a Windows desktop session")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ProcessIdToSessionId.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
    ]
    kernel32.ProcessIdToSessionId.restype = ctypes.c_int
    session_id = ctypes.c_uint32()
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
        raise RuntimeError("Windows execution session is unavailable")
    return session_id.value


def _reject_duplicate_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ExecutionHostAssignmentError(
                "execution-host assignment contains a duplicate key"
            )
        result[key] = value
    return result


def _read_stable_assignment(path: str | Path) -> bytes:
    assignment_path = Path(os.path.abspath(os.fspath(path)))
    cursor = Path(assignment_path.anchor)
    for part in assignment_path.parts[1:]:
        cursor /= part
        try:
            entry = cursor.lstat()
        except OSError as exc:
            raise ExecutionHostAssignmentError(
                "execution-host assignment path is unavailable"
            ) from exc
        if cursor.is_symlink() or bool(
            getattr(entry, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ExecutionHostAssignmentError(
                "execution-host assignment path contains a redirected entry"
            )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(assignment_path, flags)
    except OSError as exc:
        raise ExecutionHostAssignmentError(
            "execution-host assignment is not readable exact JSON"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size <= 0
            or opened.st_size > _MAX_ASSIGNMENT_BYTES
        ):
            raise ExecutionHostAssignmentError(
                "execution-host assignment is not a bounded regular file"
            )
        chunks: list[bytes] = []
        remaining = _MAX_ASSIGNMENT_BYTES + 1
        while remaining > 0:
            block = os.read(descriptor, min(8192, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        after_handle = os.fstat(descriptor)
        try:
            after_path = assignment_path.stat()
        except OSError as exc:
            raise ExecutionHostAssignmentError(
                "execution-host assignment changed while reading"
            ) from exc
        if (
            len(raw) != opened.st_size
            or not os.path.samestat(opened, after_handle)
            or not os.path.samestat(opened, after_path)
            or after_handle.st_size != opened.st_size
            or after_handle.st_mtime_ns != opened.st_mtime_ns
        ):
            raise ExecutionHostAssignmentError(
                "execution-host assignment changed while reading"
            )
        return raw
    finally:
        os.close(descriptor)


def load_execution_host_assignment(
    path: str | Path = DEFAULT_EXECUTION_HOST_ASSIGNMENT_PATH,
) -> dict:
    """Load the exact tracked single-active portable-executor assignment."""

    try:
        raw = _read_stable_assignment(path)
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ExecutionHostAssignmentError(
                "execution-host assignment must be UTF-8 without a BOM"
            )
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_pairs
        )
    except ExecutionHostAssignmentError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionHostAssignmentError(
            "execution-host assignment is not readable exact JSON"
        ) from exc
    expected = {
        "schema_version",
        "assignment_status",
        "dedicated_capture_execution_host_id",
        "active_portable_execution_host_id",
        "active_portable_execution_principal_id",
        "reassignment_requires_new_production_tip",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ExecutionHostAssignmentError(
            "execution-host assignment does not have the exact keys"
        )
    capture_id = payload["dedicated_capture_execution_host_id"]
    active_host_id = payload["active_portable_execution_host_id"]
    active_principal_id = payload["active_portable_execution_principal_id"]
    status = payload["assignment_status"]
    if (
        payload["schema_version"] != EXECUTION_HOST_ASSIGNMENT_SCHEMA_VERSION
        or _SHA256_RE.fullmatch(str(capture_id or "")) is None
        or payload["reassignment_requires_new_production_tip"] is not True
        or status not in {"UNASSIGNED", "ASSIGNED"}
    ):
        raise ExecutionHostAssignmentError(
            "execution-host assignment contract is invalid"
        )
    if status == "UNASSIGNED":
        if active_host_id is not None or active_principal_id is not None:
            raise ExecutionHostAssignmentError(
                "unassigned execution-host registry contains an active identity"
            )
    elif (
        _SHA256_RE.fullmatch(str(active_host_id or "")) is None
        or _SHA256_RE.fullmatch(str(active_principal_id or "")) is None
        or active_host_id == capture_id
    ):
        raise ExecutionHostAssignmentError(
            "assigned portable execution-host identity is invalid"
        )
    return payload


def require_current_portable_execution_assignment(
    path: str | Path = DEFAULT_EXECUTION_HOST_ASSIGNMENT_PATH,
    *,
    execution_host_id: str | None = None,
    execution_principal_id: str | None = None,
) -> dict:
    """Require this exact host/principal to be the sole tracked portable executor."""

    assignment = load_execution_host_assignment(path)
    host_id = execution_host_id or current_execution_host_id()
    principal_id = execution_principal_id or current_execution_principal_id()
    if host_id == assignment["dedicated_capture_execution_host_id"]:
        raise ExecutionHostAssignmentError(
            "the dedicated capture host cannot use the portable execution profile"
        )
    if (
        assignment["assignment_status"] != "ASSIGNED"
        or host_id != assignment["active_portable_execution_host_id"]
        or principal_id != assignment["active_portable_execution_principal_id"]
    ):
        raise ExecutionHostAssignmentError(
            "this host and Windows principal are not the active portable executor"
        )
    return assignment


def require_current_capture_execution_assignment(
    path: str | Path = DEFAULT_EXECUTION_HOST_ASSIGNMENT_PATH,
    *,
    execution_host_id: str | None = None,
) -> dict:
    """Require the dedicated capture installation and no active portable lane."""

    assignment = load_execution_host_assignment(path)
    host_id = execution_host_id or current_execution_host_id()
    if host_id != assignment["dedicated_capture_execution_host_id"]:
        raise ExecutionHostAssignmentError(
            "this Windows installation is not the dedicated capture host"
        )
    if assignment["assignment_status"] != "UNASSIGNED":
        raise ExecutionHostAssignmentError(
            "capture-colocated International live execution is disabled while a "
            "portable executor is assigned"
        )
    return assignment
