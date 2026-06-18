from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
import traceback
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


if os.name != "nt":
    raise SystemExit("window_popup_monitor.py is Windows-only")


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

MAX_PATH = 260
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
WAIT_TIMEOUT = 0x00000102

CONSOLE_CLASSES = {
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
}
SUSPECT_EXE_NAMES = {
    "cmd.exe",
    "conhost.exe",
    "opencconsole.exe",
    "openconsole.exe",
    "powershell.exe",
    "powershell_ise.exe",
    "pwsh.exe",
    "wscript.exe",
    "cscript.exe",
    "wt.exe",
    "windowsterminal.exe",
}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
    ]


Process32FirstW = kernel32.Process32FirstW
Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
Process32FirstW.restype = wintypes.BOOL

Process32NextW = kernel32.Process32NextW
Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
Process32NextW.restype = wintypes.BOOL

CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
CreateToolhelp32Snapshot.restype = wintypes.HANDLE

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = wintypes.BOOL

QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
QueryFullProcessImageNameW.restype = wintypes.BOOL

GetProcessTimes = kernel32.GetProcessTimes
GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
]
GetProcessTimes.restype = wintypes.BOOL

WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
WaitForSingleObject.restype = wintypes.DWORD

NtQueryInformationProcess = ntdll.NtQueryInformationProcess
NtQueryInformationProcess.argtypes = [
    wintypes.HANDLE,
    wintypes.ULONG,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
NtQueryInformationProcess.restype = wintypes.LONG


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def filetime_to_iso(value: wintypes.FILETIME) -> str | None:
    ticks = (int(value.dwHighDateTime) << 32) + int(value.dwLowDateTime)
    if not ticks:
        return None
    timestamp = (ticks - 116444736000000000) / 10_000_000
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def write_jsonl(path: Path, payload: dict) -> None:
    payload = {"observed_at_utc": utc_now(), **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def open_process(pid: int):
    handle = OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
        False,
        int(pid),
    )
    return handle or None


def read_memory(handle, address: int, size: int) -> bytes | None:
    if not address or size <= 0:
        return None
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok = ReadProcessMemory(
        handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(read),
    )
    if not ok or read.value == 0:
        return None
    return buffer.raw[: read.value]


def read_ptr(handle, address: int, ptr_size: int) -> int | None:
    raw = read_memory(handle, address, ptr_size)
    if not raw or len(raw) < ptr_size:
        return None
    fmt = "<Q" if ptr_size == 8 else "<I"
    return struct.unpack(fmt, raw[:ptr_size])[0]


def read_ushort(handle, address: int) -> int | None:
    raw = read_memory(handle, address, 2)
    if not raw or len(raw) < 2:
        return None
    return struct.unpack("<H", raw[:2])[0]


def read_unicode_at(handle, string_struct: int, ptr_size: int) -> str | None:
    length = read_ushort(handle, string_struct)
    if not length:
        return None
    buffer_offset = 8 if ptr_size == 8 else 4
    buffer_ptr = read_ptr(handle, string_struct + buffer_offset, ptr_size)
    if not buffer_ptr:
        return None
    raw = read_memory(handle, buffer_ptr, min(length, 32768))
    if not raw:
        return None
    return raw.decode("utf-16-le", errors="replace").rstrip("\x00")


def process_basic_info(handle):
    info = PROCESS_BASIC_INFORMATION()
    return_len = wintypes.ULONG(0)
    status = NtQueryInformationProcess(
        handle,
        0,
        ctypes.byref(info),
        ctypes.sizeof(info),
        ctypes.byref(return_len),
    )
    if status != 0:
        return None
    return info


def wow64_peb(handle) -> int | None:
    peb32 = ctypes.c_void_p()
    return_len = wintypes.ULONG(0)
    status = NtQueryInformationProcess(
        handle,
        26,
        ctypes.byref(peb32),
        ctypes.sizeof(peb32),
        ctypes.byref(return_len),
    )
    if status != 0 or not peb32.value:
        return None
    return int(peb32.value)


def remote_command_line(handle) -> str | None:
    peb32 = wow64_peb(handle)
    if peb32:
        params = read_ptr(handle, peb32 + 0x10, 4)
        if params:
            cmd = read_unicode_at(handle, params + 0x40, 4)
            if cmd:
                return cmd

    info = process_basic_info(handle)
    if not info or not info.PebBaseAddress:
        return None
    params = read_ptr(handle, int(info.PebBaseAddress) + 0x20, 8)
    if not params:
        return None
    return read_unicode_at(handle, params + 0x70, 8)


def image_path(handle) -> str | None:
    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return None
    return buffer.value


def creation_time(handle) -> str | None:
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None
    return filetime_to_iso(created)


def is_process_running(pid: int) -> bool:
    handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        return WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        CloseHandle(handle)


def snapshot_processes() -> dict[int, dict]:
    snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return {}
    table: dict[int, dict] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            table[pid] = {
                "pid": pid,
                "parent_pid": int(entry.th32ParentProcessID),
                "name": entry.szExeFile,
            }
            ok = Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        CloseHandle(snapshot)
    return table


class ProcessDescriber:
    def __init__(self):
        self.cache: dict[int, dict] = {}

    def prune(self, live_pids: set[int]) -> None:
        for pid in list(self.cache):
            if pid not in live_pids:
                self.cache.pop(pid, None)

    def describe(self, pid: int, table: dict[int, dict] | None = None, enrich: bool = True) -> dict:
        pid = int(pid)
        base = dict((table or {}).get(pid) or {"pid": pid})
        cached = self.cache.get(pid, {})
        if cached and base.get("name") and cached.get("name") != base.get("name"):
            cached = {}
        result = {**cached, **base}
        if enrich and (not cached.get("enriched")):
            handle = open_process(pid)
            if handle:
                try:
                    result.update(
                        {
                            "image_path": image_path(handle),
                            "command_line": remote_command_line(handle),
                            "creation_time_utc": creation_time(handle),
                            "enriched": True,
                        }
                    )
                finally:
                    CloseHandle(handle)
            else:
                result.setdefault("enriched", False)
        self.cache[pid] = result
        return result

    def ancestry(self, pid: int, table: dict[int, dict], depth: int = 6) -> list[dict]:
        chain = []
        current = int(pid)
        visited = set()
        for _ in range(depth):
            if current in visited or current <= 0:
                break
            visited.add(current)
            info = self.describe(current, table, enrich=True)
            chain.append(info)
            current = int(info.get("parent_pid") or 0)
        return chain


def window_text(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def window_class(hwnd) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_pid(hwnd) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def visible_windows() -> list[dict]:
    windows = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = window_text(hwnd)
        klass = window_class(hwnd)
        pid = window_pid(hwnd)
        if title or klass in CONSOLE_CLASSES:
            windows.append({
                "hwnd": int(hwnd),
                "title": title,
                "class": klass,
                "pid": pid,
            })
        return True

    user32.EnumWindows(callback, 0)
    return windows


def foreground_window() -> dict | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    return {
        "hwnd": int(hwnd),
        "title": window_text(hwnd),
        "class": window_class(hwnd),
        "pid": window_pid(hwnd),
    }


def is_suspicious_process(info: dict) -> bool:
    name = str(info.get("name") or "").lower()
    image = str(info.get("image_path") or "").lower()
    command = str(info.get("command_line") or "").lower()
    if name in SUSPECT_EXE_NAMES:
        return True
    if image.endswith((".cmd", ".bat")):
        return True
    if "cmd.exe" in command or "powershell" in command or "pwsh" in command:
        return True
    return False


def is_console_like_window(window: dict, proc: dict | None = None) -> bool:
    klass = str(window.get("class") or "")
    if klass in CONSOLE_CLASSES:
        return True
    if proc and is_suspicious_process(proc):
        return True
    title = str(window.get("title") or "").lower()
    return "command prompt" in title or "windows powershell" in title


def write_status(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_monitor(args) -> int:
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status_path = Path(args.status)
    pid_path = Path(args.pid_file)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()) + "\n", encoding="utf-8")

    describer = ProcessDescriber()
    seen_pids: set[int] = set()
    seen_windows: set[tuple[int, int, str, str]] = set()
    last_foreground_hwnd: int | None = None
    started = time.time()
    last_status = 0.0
    last_process_poll = 0.0

    write_jsonl(log_path, {
        "event": "monitor_start",
        "pid": os.getpid(),
        "log": str(log_path),
        "status": str(status_path),
        "process_poll_seconds": args.process_poll_seconds,
        "window_poll_seconds": args.window_poll_seconds,
        "duration_seconds": args.duration_seconds,
    })

    table = snapshot_processes()
    for pid, info in table.items():
        seen_pids.add(pid)
        enriched = describer.describe(pid, table, enrich=is_suspicious_process(info))
        if is_suspicious_process(enriched):
            write_jsonl(log_path, {
                "event": "baseline_suspicious_process",
                "process": enriched,
                "ancestry": describer.ancestry(pid, table),
            })

    while True:
        now = time.time()
        if args.duration_seconds and now - started >= args.duration_seconds:
            break

        if now - last_process_poll >= args.process_poll_seconds:
            last_process_poll = now
            table = snapshot_processes()
            live_pids = set(table)
            seen_pids.intersection_update(live_pids)
            describer.prune(live_pids)
            for pid, _info in table.items():
                if pid in seen_pids:
                    continue
                seen_pids.add(pid)
                enriched = describer.describe(pid, table, enrich=True)
                event = "process_start_suspicious" if is_suspicious_process(enriched) else "process_start"
                write_jsonl(log_path, {
                    "event": event,
                    "process": enriched,
                    "ancestry": describer.ancestry(pid, table),
                })
        else:
            table = snapshot_processes()

        for window in visible_windows():
            proc = describer.describe(window["pid"], table, enrich=True)
            key = (
                int(window["hwnd"]),
                int(window["pid"]),
                str(window.get("class") or ""),
                str(window.get("title") or ""),
            )
            if key not in seen_windows:
                seen_windows.add(key)
                if is_console_like_window(window, proc):
                    write_jsonl(log_path, {
                        "event": "visible_console_window",
                        "window": window,
                        "process": proc,
                        "ancestry": describer.ancestry(window["pid"], table),
                    })

        fg = foreground_window()
        if fg and fg["hwnd"] != last_foreground_hwnd:
            last_foreground_hwnd = fg["hwnd"]
            proc = describer.describe(fg["pid"], table, enrich=True)
            if is_console_like_window(fg, proc):
                write_jsonl(log_path, {
                    "event": "foreground_console_window",
                    "window": fg,
                    "process": proc,
                    "ancestry": describer.ancestry(fg["pid"], table),
                })

        if now - last_status >= args.status_seconds:
            last_status = now
            write_status(status_path, {
                "active": True,
                "pid": os.getpid(),
                "started_at_utc": datetime.fromtimestamp(started, timezone.utc).isoformat(),
                "updated_at_utc": utc_now(),
                "log": str(log_path),
                "duration_seconds": round(now - started, 3),
                "known_processes": len(seen_pids),
                "known_windows": len(seen_windows),
            })
        time.sleep(args.window_poll_seconds)

    write_jsonl(log_path, {"event": "monitor_stop", "pid": os.getpid()})
    write_status(status_path, {
        "active": False,
        "pid": os.getpid(),
        "updated_at_utc": utc_now(),
        "log": str(log_path),
    })
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default=str(Path("data") / "ops" / "window_popup_monitor.jsonl"))
    parser.add_argument("--status", default=str(Path("data") / "ops" / "window_popup_monitor_status.json"))
    parser.add_argument("--pid-file", default=str(Path("data") / "ops" / "window_popup_monitor.pid"))
    parser.add_argument("--process-poll-seconds", type=float, default=0.25)
    parser.add_argument("--window-poll-seconds", type=float, default=0.05)
    parser.add_argument("--status-seconds", type=float, default=5.0)
    parser.add_argument("--duration-seconds", type=float, default=8 * 60 * 60)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return run_monitor(args)
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic daemon
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(log_path, {
            "event": "monitor_error",
            "pid": os.getpid(),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        status_path = Path(args.status)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        write_status(status_path, {
            "active": False,
            "pid": os.getpid(),
            "updated_at_utc": utc_now(),
            "log": str(log_path),
            "error": f"{type(exc).__name__}: {exc}",
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
