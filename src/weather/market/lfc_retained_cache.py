"""Process-local retention cache; file identity changes always invalidate proof.

This cache never stores account reads, money gates or ledger write-integrity checks.
"""
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import os

from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json
from weather.operations.live_path_security import validate_regular_nonreparse_file


@lru_cache(maxsize=1)
def native_api():
    import ctypes
    from ctypes import wintypes
    class BasicInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in
                    ('created', 'accessed', 'written', 'changed')] + [('attributes', wintypes.DWORD)]
    class UsnHeader(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('major', wintypes.WORD), ('minor', wintypes.WORD),
                    ('file_id', ctypes.c_ulonglong), ('parent_id', ctypes.c_ulonglong), ('usn', ctypes.c_longlong)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    return kernel, BasicInfo, UsnHeader


def change_stamp(path, observed):
    """Read the file's NTFS USN; timestamps alone may coalesce fast edits.

    This never enables or modifies the volume journal. Unsupported/unavailable
    per-file USN disables caching, retaining full content validation.
    """
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    kernel, BasicInfo, UsnHeader = native_api()
    handle = kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = BasicInfo()
        if not kernel.GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x400:
            raise ValueError('retained_evidence_reparse')
        output, returned = ctypes.create_string_buffer(4096), wintypes.DWORD()
        # CTL_CODE(FILE_DEVICE_FILE_SYSTEM,58,METHOD_NEITHER,FILE_ANY_ACCESS).
        # Omitted input requests USN_RECORD_V2, per the Microsoft SDK contract.
        if not kernel.DeviceIoControl(handle, 0x900EB, None, 0, output, len(output), ctypes.byref(returned), None):
            return None
        if returned.value < 60:
            return None
        record = UsnHeader.from_buffer_copy(output.raw[:ctypes.sizeof(UsnHeader)])
        if (record.major != 2 or record.minor != 0 or not 60 <= record.length <= returned.value or
                record.file_id != observed.st_ino or record.usn <= 0):
            return None
        return info.changed, record.usn
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class RetainedCache:
    def __init__(self):
        self.values, self.proofs = OrderedDict(), OrderedDict()
        self.bytes = 0

    def signature(self, path):
        path = validate_regular_nonreparse_file(Path(path).absolute())
        observed = path.stat()
        return (str(path), observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns,
                observed.st_ctime_ns, getattr(observed, 'st_file_attributes', 0), change_stamp(path, observed))

    def get(self, kind, path, load):
        signature = self.signature(path)
        key = (kind, str(Path(path).absolute()))
        old = self.values.get(key)
        if signature[-1] is not None and old is not None and old[0] == signature:
            self.values.move_to_end(key)
            return deepcopy(old[1])
        value, weight = load()
        if signature != self.signature(path):
            raise ValueError('retained_evidence_changed_during_read')
        if signature[-1] is None:
            return value
        if weight > 16 * 1024**2:
            # An exhaustive late-campaign receipt may be large. Never double
            # its memory merely to evict the copy immediately afterward.
            if old is not None:
                self.bytes -= old[2]
                del self.values[key]
            return value
        if old is not None:
            self.bytes -= old[2]
        self.values[key] = (signature, deepcopy(value), weight)
        self.bytes += weight
        self.values.move_to_end(key)
        while self.bytes > 16 * 1024**2 or len(self.values) > 16384:
            _, removed = self.values.popitem(last=False)
            self.bytes -= removed[2]
        return value

    def sha(self, path):
        return self.get('sha', path, lambda: (file_sha(path), 256))

    def json(self, path):
        def load():
            from weather.market.lfc_recording_io import STATE_JSON_LIMIT
            raw = read_bytes(path, STATE_JSON_LIMIT)
            return strict_json(raw), max(256, len(raw) * 5)
        return self.get('json', path, load)

    def memo(self, key, load, *, cacheable=True):
        if not cacheable:
            return load()
        if key not in self.proofs:
            self.proofs[key] = deepcopy(load())
        self.proofs.move_to_end(key)
        while len(self.proofs) > 64:
            self.proofs.popitem(last=False)
        return deepcopy(self.proofs[key])
