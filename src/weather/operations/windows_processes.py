"""Native Windows process inspection without shelling out to PowerShell."""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from typing import Callable


MAX_PATH = 260
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
ERROR_NO_MORE_FILES = 18


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)


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

    TerminateProcess = kernel32.TerminateProcess
    TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    TerminateProcess.restype = wintypes.BOOL

    WaitForSingleObject = kernel32.WaitForSingleObject
    WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    WaitForSingleObject.restype = wintypes.DWORD

    GetProcessTimes = kernel32.GetProcessTimes
    GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    GetProcessTimes.restype = wintypes.BOOL

    NtQueryInformationProcess = ntdll.NtQueryInformationProcess
    NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    NtQueryInformationProcess.restype = wintypes.LONG


def _open_process(pid: int, *, access: int | None = None):
    handle = OpenProcess(
        access
        if access is not None
        else PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
        False,
        int(pid),
    )
    return handle or None


def _read_memory(handle, address: int, size: int) -> bytes | None:
    if not address or size <= 0:
        return None
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok = ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(read))
    if not ok or read.value == 0:
        return None
    return buffer.raw[: read.value]


def _read_ptr(handle, address: int, ptr_size: int) -> int | None:
    raw = _read_memory(handle, address, ptr_size)
    if not raw or len(raw) < ptr_size:
        return None
    fmt = "<Q" if ptr_size == 8 else "<I"
    return struct.unpack(fmt, raw[:ptr_size])[0]


def _read_ushort(handle, address: int) -> int | None:
    raw = _read_memory(handle, address, 2)
    if not raw or len(raw) < 2:
        return None
    return struct.unpack("<H", raw[:2])[0]


def _read_unicode_at(handle, string_struct: int, ptr_size: int) -> str | None:
    length = _read_ushort(handle, string_struct)
    if not length:
        return None
    buffer_offset = 8 if ptr_size == 8 else 4
    buffer_ptr = _read_ptr(handle, string_struct + buffer_offset, ptr_size)
    if not buffer_ptr:
        return None
    raw = _read_memory(handle, buffer_ptr, min(length, 32768))
    if not raw:
        return None
    return raw.decode("utf-16-le", errors="replace").rstrip("\x00")


def _process_basic_info(handle):
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


def _wow64_peb(handle) -> int | None:
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


def _remote_command_line(handle) -> str | None:
    peb32 = _wow64_peb(handle)
    if peb32:
        params = _read_ptr(handle, peb32 + 0x10, 4)
        if params:
            cmd = _read_unicode_at(handle, params + 0x40, 4)
            if cmd:
                return cmd

    info = _process_basic_info(handle)
    if not info or not info.PebBaseAddress:
        return None
    params = _read_ptr(handle, int(info.PebBaseAddress) + 0x20, 8)
    if not params:
        return None
    return _read_unicode_at(handle, params + 0x70, 8)


def _image_path(handle) -> str | None:
    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return None
    return buffer.value


def _creation_time_token(handle) -> str | None:
    """Return the immutable Win32 creation FILETIME for one process handle."""

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
    ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    return f"win32-filetime:{ticks}"


def snapshot_processes() -> dict[int, dict] | None:
    if os.name != "nt":
        return None
    snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return None
    table: dict[int, dict] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ctypes.set_last_error(0)
        ok = Process32FirstW(snapshot, ctypes.byref(entry))
        if not ok:
            return {} if ctypes.get_last_error() == ERROR_NO_MORE_FILES else None
        while ok:
            pid = int(entry.th32ProcessID)
            table[pid] = {
                "pid": pid,
                "parent_pid": int(entry.th32ParentProcessID),
                "name": entry.szExeFile,
            }
            ctypes.set_last_error(0)
            ok = Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != ERROR_NO_MORE_FILES:
            return None
    finally:
        CloseHandle(snapshot)
    return table


def describe_process(pid: int, table: dict[int, dict] | None = None) -> dict:
    if os.name != "nt":
        return {"pid": int(pid)}
    result = dict((table or {}).get(int(pid)) or {"pid": int(pid)})
    handle = _open_process(int(pid))
    if not handle:
        return result
    try:
        result.update(
            {
                "image_path": _image_path(handle),
                "command_line": _remote_command_line(handle),
                "creation_time_token": _creation_time_token(handle),
            }
        )
    finally:
        CloseHandle(handle)
    return result


def terminate_verified_process(
    pid: int,
    *,
    expected_creation_time_token: str,
    command_line_check: Callable[[str | None], bool],
    exit_code: int = 15,
    wait_timeout_ms: int = 2000,
) -> dict:
    """Terminate only the instance verified through the same open handle."""

    if os.name != "nt":
        return {"pid": int(pid), "stopped": False, "reason": "not_windows"}
    access = (
        PROCESS_TERMINATE
        | PROCESS_QUERY_LIMITED_INFORMATION
        | PROCESS_QUERY_INFORMATION
        | PROCESS_VM_READ
        | SYNCHRONIZE
    )
    handle = _open_process(int(pid), access=access)
    if not handle:
        return {"pid": int(pid), "stopped": False, "reason": "process_handle_unavailable"}
    try:
        creation_token = _creation_time_token(handle)
        if not creation_token:
            return {"pid": int(pid), "stopped": False, "reason": "process_creation_token_unavailable"}
        if creation_token != str(expected_creation_time_token):
            return {"pid": int(pid), "stopped": False, "reason": "process_instance_changed_before_termination"}
        command_line = _remote_command_line(handle)
        if not command_line or not command_line_check(command_line):
            return {"pid": int(pid), "stopped": False, "reason": "process_command_changed_before_termination"}
        if not TerminateProcess(handle, int(exit_code)):
            return {
                "pid": int(pid),
                "stopped": False,
                "reason": f"TerminateProcess failed with Win32 error {ctypes.get_last_error()}",
            }
        wait_result = int(WaitForSingleObject(handle, max(0, int(wait_timeout_ms))))
        exited = wait_result == WAIT_OBJECT_0
        return {
            "pid": int(pid),
            "stopped": exited,
            "termination_requested": True,
            "termination_scope": "verified_process_handle",
            "creation_time_token": creation_token,
            "exited": exited,
            "reason": "verified_process_exited" if exited else "verified_process_exit_not_observed",
            "wait_result": wait_result,
        }
    finally:
        CloseHandle(handle)


def python_process_rows() -> list[dict]:
    if os.name != "nt":
        return []
    table = snapshot_processes()
    if table is None:
        return []
    rows = []
    for pid, info in table.items():
        if "python" not in str(info.get("name") or "").lower():
            continue
        detail = describe_process(pid, table)
        rows.append(
            {
                "pid": pid,
                "parent_pid": detail.get("parent_pid"),
                "name": detail.get("name"),
                "image_path": detail.get("image_path"),
                "command_line": detail.get("command_line") or "",
                "creation_time_token": detail.get("creation_time_token"),
            }
        )
    return rows
