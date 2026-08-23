"""Block agent shell commands that violate the capture-host load policy."""

from __future__ import annotations

import ctypes
from datetime import datetime, time
import json
import os
import re
import sys
from typing import Any


HEAVY_START = time(0, 30)
HEAVY_END = time(9, 0)
CAPTURE_HOST_MAX_PHYSICAL_BYTES = 20 * 1024**3

_PYTEST = re.compile(
    r"(?i)(?:^|\s)-m\s+pytest\b|(?:^|[\s;&|])pytest(?:\.exe)?\b"
)
_COMPILEALL = re.compile(r"(?i)(?:^|\s)-m\s+compileall\b")
_DIRECT_HEAVY_WEATHER = re.compile(
    r"(?i)(?:^|\s)-m\s+weather\.[^\s]*(?:retrain|training|replay|backtest|daily_refresh|score_all)"
)
_TEST_FILE = re.compile(r"(?i)(?:^|\s)(?:[^\s\"']*[\\/])?test_[^\s\"']*\.py(?=\s|$)")


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    ]


def _is_constrained_capture_host() -> bool:
    override = os.environ.get("WEATHER_CODEX_HOST_LOAD_POLICY", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    if os.name != "nt":
        return False
    status = _MemoryStatusEx()
    status.length = ctypes.sizeof(status)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return False
    return bool(ok) and 0 < status.total_physical <= CAPTURE_HOST_MAX_PHYSICAL_BYTES


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
    active = _is_constrained_capture_host() if constrained_capture_host is None else constrained_capture_host
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
