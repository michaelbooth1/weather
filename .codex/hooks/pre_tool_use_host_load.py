"""Block agent shell commands that violate the exact capture-host load policy."""

from __future__ import annotations

from datetime import datetime, time
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


HEAVY_START = time(0, 30)
HEAVY_END = time(9, 0)
EXECUTION_HOST_DOMAIN = "international_live_execution_host_v2\0"
ASSIGNMENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "international_live_execution_host.json"
)
_REPARSE_POINT = 0x400
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_MAX_ASSIGNMENT_BYTES = 16_384

_PYTEST = re.compile(
    r"(?i)(?:^|\s)-m\s+pytest\b|(?:^|[\s;&|])pytest(?:\.exe)?\b"
)
_COMPILEALL = re.compile(r"(?i)(?:^|\s)-m\s+compileall\b")
_DIRECT_HEAVY_WEATHER = re.compile(
    r"(?i)(?:^|\s)-m\s+weather\.[^\s]*(?:retrain|training|replay|backtest|daily_refresh|score_all)"
)
_TEST_FILE = re.compile(r"(?i)(?:^|\s)(?:[^\s\"']*[\\/])?test_[^\s\"']*\.py(?=\s|$)")


def _derive_execution_host_id(machine_guid: str) -> str:
    canonical = machine_guid.strip().lower()
    if not canonical:
        raise ValueError("empty Windows installation identity")
    return hashlib.sha256(
        f"{EXECUTION_HOST_DOMAIN}{canonical}".encode("utf-8")
    ).hexdigest()


def _read_machine_guid() -> str:
    import winreg

    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        access,
    ) as key:
        value, value_type = winreg.QueryValueEx(key, "MachineGuid")
    if value_type != winreg.REG_SZ or not isinstance(value, str):
        raise ValueError("Windows installation identity is not a string")
    return value


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("capture-host assignment contains a duplicate key")
        result[key] = value
    return result


def _read_stable_assignment(path: Path) -> bytes:
    assignment_path = Path(os.path.abspath(os.fspath(path)))
    cursor = Path(assignment_path.anchor)
    for part in assignment_path.parts[1:]:
        cursor /= part
        entry = cursor.lstat()
        if cursor.is_symlink() or bool(
            getattr(entry, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise ValueError("capture-host assignment path is redirected")

    descriptor = os.open(
        assignment_path,
        os.O_RDONLY | getattr(os, "O_BINARY", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size <= 0
            or opened.st_size > _MAX_ASSIGNMENT_BYTES
        ):
            raise ValueError("capture-host assignment is not a bounded regular file")
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
        after_path = assignment_path.stat()
        if (
            len(raw) != opened.st_size
            or not os.path.samestat(opened, after_handle)
            or not os.path.samestat(opened, after_path)
            or after_handle.st_size != opened.st_size
            or after_handle.st_mtime_ns != opened.st_mtime_ns
        ):
            raise ValueError("capture-host assignment changed while it was read")
        return raw
    finally:
        os.close(descriptor)


def _read_dedicated_capture_host_id(path: Path) -> str:
    raw = _read_stable_assignment(path)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("capture-host assignment must not contain a BOM")
    assignment = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_pairs,
    )
    expected = {
        "active_portable_execution_host_id",
        "active_portable_execution_principal_id",
        "assignment_status",
        "dedicated_capture_execution_host_id",
        "reassignment_requires_new_production_tip",
        "schema_version",
    }
    if not isinstance(assignment, dict) or set(assignment) != expected:
        raise ValueError("capture-host assignment does not have the exact keys")
    dedicated_id = assignment["dedicated_capture_execution_host_id"]
    active_host_id = assignment["active_portable_execution_host_id"]
    active_principal_id = assignment["active_portable_execution_principal_id"]
    status_value = assignment["assignment_status"]
    if (
        assignment["schema_version"]
        != "international_live_execution_host_assignment_v0.1"
        or not isinstance(dedicated_id, str)
        or _HEX64.fullmatch(dedicated_id) is None
        or assignment["reassignment_requires_new_production_tip"] is not True
        or status_value not in {"UNASSIGNED", "ASSIGNED"}
    ):
        raise ValueError("capture-host assignment contract is invalid")
    if status_value == "UNASSIGNED":
        if active_host_id is not None or active_principal_id is not None:
            raise ValueError("unassigned capture-host assignment has active identities")
    elif (
        not isinstance(active_host_id, str)
        or _HEX64.fullmatch(active_host_id) is None
        or not isinstance(active_principal_id, str)
        or _HEX64.fullmatch(active_principal_id) is None
        or active_host_id == dedicated_id
    ):
        raise ValueError("assigned portable execution-host identity is invalid")
    return dedicated_id


def _capture_host_policy_state(
    *,
    assignment_path: Path = ASSIGNMENT_PATH,
    machine_guid: str | None = None,
    windows: bool | None = None,
) -> bool | None:
    """Return exact capture-host match, non-match, or indeterminate proof."""

    is_windows = os.name == "nt" if windows is None else windows
    if not is_windows:
        return False
    try:
        observed_id = _derive_execution_host_id(
            _read_machine_guid() if machine_guid is None else machine_guid
        )
        dedicated_id = _read_dedicated_capture_host_id(assignment_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return observed_id == dedicated_id


def _inside_heavy_window(now: datetime) -> bool:
    local = now.astimezone()
    return HEAVY_START <= local.time().replace(tzinfo=None) < HEAVY_END


def _forbidden_recursive_scan(command: str) -> bool:
    normalized = command.replace("/", "\\")
    data_root = re.search(r"(?i)(?:^|[\s\"'])(?:\.\\)?data(?:\\|[\s\"'])", normalized)
    get_child = re.search(r"(?i)\bGet-ChildItem\b", command)
    recurse = re.search(r"(?i)(?:^|\s)-(?:Recurse|r)(?:\s|$)", command)
    broad_rg = re.search(r"(?i)(?:^|[\s;&|])rg(?:\.exe)?(?:\s|$)", command)
    return bool((get_child and recurse) or (data_root and broad_rg))


def _unbounded_pytest(command: str) -> bool:
    if not _PYTEST.search(command):
        return False
    return not _TEST_FILE.search(command)


def _recognized_host_load_command(command: str) -> bool:
    return bool(
        _forbidden_recursive_scan(command)
        or _PYTEST.search(command)
        or _COMPILEALL.search(command)
        or _DIRECT_HEAVY_WEATHER.search(command)
    )


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def evaluate(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    constrained_capture_host: bool | None = None,
) -> dict[str, Any] | None:
    """Return a Codex hook denial, or ``None`` when the call may proceed."""

    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    active = (
        _capture_host_policy_state()
        if constrained_capture_host is None
        else constrained_capture_host
    )
    if active is None:
        if _recognized_host_load_command(command):
            return _deny(
                "Cannot prove this Windows installation differs from the tracked "
                "dedicated capture host; recognized heavy work is blocked fail-closed."
            )
        return None
    if not active:
        return None

    if _forbidden_recursive_scan(command):
        return _deny(
            "Recursive Get-ChildItem and broad scans of data/ are forbidden on the capture host; use rg or target a known file/bounded subtree."
        )
    if _unbounded_pytest(command):
        return _deny(
            "An unbounded pytest run is forbidden on the 16 GB capture host; use the repository-owned bounded 25-file suite wrapper."
        )

    instant = now or datetime.now().astimezone()
    if not _inside_heavy_window(instant) and (
        _PYTEST.search(command)
        or _COMPILEALL.search(command)
        or _DIRECT_HEAVY_WEATHER.search(command)
    ):
        return _deny(
            "Agent-started pytest, compileall, replay, backtest, or training work is allowed only 00:30-09:00 America/Toronto on this capture host."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    result = evaluate(payload)
    if result is not None:
        json.dump(result, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
