"""Power-management helpers for long-running local workers."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, field
from typing import Callable


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040

ExecutionStateFn = Callable[[int], int]


def _load_set_thread_execution_state() -> ExecutionStateFn | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_thread_execution_state = kernel32.SetThreadExecutionState
    set_thread_execution_state.argtypes = [ctypes.c_uint]
    set_thread_execution_state.restype = ctypes.c_uint
    return set_thread_execution_state


def _last_windows_error() -> int | None:
    try:
        return int(ctypes.get_last_error())
    except Exception:
        return None


@dataclass
class SystemSleepInhibitor:
    """Keep Windows from entering idle sleep while a worker is running.

    The Windows execution-state request is process/thread local. It prevents
    idle system sleep while active, but it does not override explicit user sleep
    or power-button/lid behavior. Non-Windows platforms return a harmless no-op
    status so call sites can use the helper unconditionally.
    """

    reason: str
    enabled: bool = True
    away_mode: bool = False
    set_thread_execution_state: ExecutionStateFn | None = None
    platform_name: str = field(default_factory=lambda: os.name)
    active: bool = False
    status: dict[str, object] = field(default_factory=dict)

    def _state_fn(self) -> ExecutionStateFn | None:
        return self.set_thread_execution_state or _load_set_thread_execution_state()

    def start(self) -> dict[str, object]:
        if not self.enabled or os.environ.get("WEATHER_DISABLE_STAY_AWAKE") == "1":
            self.status = {
                "status": "disabled",
                "active": False,
                "reason": self.reason,
            }
            return self.status
        if self.platform_name != "nt" and self.set_thread_execution_state is None:
            self.status = {
                "status": "not_supported",
                "active": False,
                "reason": self.reason,
            }
            return self.status
        set_state = self._state_fn()
        if set_state is None:
            self.status = {
                "status": "not_supported",
                "active": False,
                "reason": self.reason,
            }
            return self.status

        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        if self.away_mode:
            flags |= ES_AWAYMODE_REQUIRED
        previous_state = int(set_state(flags) or 0)
        self.active = previous_state != 0
        self.status = {
            "status": "active" if self.active else "failed",
            "active": self.active,
            "reason": self.reason,
            "flags": flags,
            "away_mode": bool(self.away_mode),
            "previous_state": previous_state,
        }
        if not self.active:
            self.status["error_code"] = _last_windows_error()
        return self.status

    def stop(self) -> dict[str, object]:
        if not self.active:
            return {
                "status": "inactive",
                "active": False,
                "reason": self.reason,
            }
        set_state = self._state_fn()
        result = int(set_state(ES_CONTINUOUS) or 0) if set_state is not None else 0
        self.active = False
        return {
            "status": "released" if result != 0 else "release_failed",
            "active": False,
            "reason": self.reason,
            "flags": ES_CONTINUOUS,
            "previous_state": result,
        }

    def __enter__(self) -> "SystemSleepInhibitor":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()


def keep_system_awake(reason: str, *, away_mode: bool = False, enabled: bool = True) -> SystemSleepInhibitor:
    return SystemSleepInhibitor(reason=reason, away_mode=away_mode, enabled=enabled)
