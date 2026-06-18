"""Native Windows process inspection without shelling out to PowerShell."""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes


MAX_PATH = 260
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010


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

    NtQueryInformationProcess = ntdll.NtQueryInformationProcess
    NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    NtQueryInformationProcess.restype = wintypes.LONG


def _open_process(pid: int):
    handle = OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
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


def snapshot_processes() -> dict[int, dict]:
    if os.name != "nt":
        return {}
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
            }
        )
    finally:
        CloseHandle(handle)
    return result


def python_process_rows() -> list[dict]:
    if os.name != "nt":
        return []
    table = snapshot_processes()
    rows = []
    for pid, info in table.items():
        if "python" not in str(info.get("name") or "").lower():
            continue
        detail = describe_process(pid, table)
        rows.append(
            {
                "pid": pid,
                "name": detail.get("name"),
                "command_line": detail.get("command_line") or "",
            }
        )
    return rows
