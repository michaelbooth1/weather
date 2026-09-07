"""Native, handle-bound NTFS compression; no traversal, deletion or renaming."""

from __future__ import annotations

from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import time


MIB = 1024**2
MAX_FILE_BYTES = 64 * MIB
REPARSE_POINT = 0x400
COMPRESSED = 0x800
FILETIME_EPOCH = 116444736000000000


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", wintypes.FILETIME),
        ("accessed", wintypes.FILETIME),
        ("written", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


class _StandardInformation(ctypes.Structure):
    _fields_ = [
        ("allocation", ctypes.c_int64),
        ("eof", ctypes.c_int64),
        ("links", wintypes.DWORD),
        ("delete_pending", ctypes.c_ubyte),
        ("directory", ctypes.c_ubyte),
    ]


def _ticks(value):
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


class LockedNtfsFile:
    """Pin every ancestor against replacement; deny file writers and deletion.

    The compression operation uses the same handle as identity and hash checks.
    A busy writer, non-NTFS volume, link, alternate stream, or unsupported file
    attribute fails closed. Callers supply admission and durable journaling.
    """

    def __init__(self, path: Path, *, writable: bool):
        if os.name != "nt":
            raise OSError("NTFS compression requires native Windows")
        self.path = Path(path)
        if (not self.path.is_absolute() or not self.path.drive
                or len(self.path.drive) != 2 or ":" in str(self.path)[2:]
                or any(part in {".", ".."} for part in self.path.parts)):
            raise ValueError("a local absolute path without streams or traversal is required")
        self.writable = writable
        self._stack = ExitStack()
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._bind()

    def _bind(self):
        k = self._kernel
        signatures = {
            "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                             wintypes.HANDLE], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "GetFileInformationByHandle": ([wintypes.HANDLE, ctypes.POINTER(_FileInformation)], wintypes.BOOL),
            "GetFileInformationByHandleEx": ([wintypes.HANDLE, ctypes.c_int,
                                               ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "GetFinalPathNameByHandleW": ([wintypes.HANDLE, wintypes.LPWSTR,
                                           wintypes.DWORD, wintypes.DWORD], wintypes.DWORD),
            "GetVolumeInformationByHandleW": ([wintypes.HANDLE, wintypes.LPWSTR,
                                                wintypes.DWORD, ctypes.c_void_p,
                                                ctypes.c_void_p, ctypes.c_void_p,
                                                wintypes.LPWSTR, wintypes.DWORD], wintypes.BOOL),
            "DeviceIoControl": ([wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL),
            "FlushFileBuffers": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(k, name)
            function.argtypes, function.restype = arguments, result

    def _check(self, result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def _open(self, path, *, directory=False):
        # FILE_READ_ATTRIBUTES alone does not participate in Windows sharing
        # checks. GENERIC_READ includes FILE_LIST_DIRECTORY, so denying DELETE
        # actually prevents an empty evidence directory from being renamed.
        access = 0x80000000 | (0x40000000 if self.writable and not directory else 0)
        # Directory handles permit reads/writes but never deletion/rename.
        share = 3 if directory else 1
        flags = 0x00200000 | (0x02000000 if directory else 0x08000000)
        handle = self._kernel.CreateFileW(str(path), access, share, None, 3, flags, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self._stack.callback(self._kernel.CloseHandle, handle)
        info = _FileInformation()
        self._check(self._kernel.GetFileInformationByHandle(handle, ctypes.byref(info)))
        if info.attributes & REPARSE_POINT or bool(info.attributes & 0x10) != directory:
            raise ValueError("reparse point or unexpected file type")
        final = ctypes.create_unicode_buffer(32768)
        length = self._check(self._kernel.GetFinalPathNameByHandleW(handle, final, len(final), 0))
        if length >= len(final) or os.path.normcase(final.value.removeprefix("\\\\?\\")) != os.path.normcase(str(path)):
            raise ValueError("opened path does not match the requested path")
        return handle

    def __enter__(self):
        try:
            for parent in reversed(self.path.parents):
                self._open(parent, directory=True)
            self.handle = self._open(self.path)
            filesystem = ctypes.create_unicode_buffer(32)
            self._check(self._kernel.GetVolumeInformationByHandleW(
                self.handle, None, 0, None, None, None, filesystem, len(filesystem)))
            if filesystem.value != "NTFS":
                raise ValueError("only local NTFS is supported")
            self.metadata()
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(self, *args):
        self._stack.close()

    def metadata(self):
        info, standard = _FileInformation(), _StandardInformation()
        self._check(self._kernel.GetFileInformationByHandle(self.handle, ctypes.byref(info)))
        self._check(self._kernel.GetFileInformationByHandleEx(
            self.handle, 1, ctypes.byref(standard), ctypes.sizeof(standard)))
        size = (int(info.size_high) << 32) | int(info.size_low)
        # Archive, normal, compressed; reject sparse, offline, encrypted, etc.
        if info.attributes & ~(0x20 | 0x80 | COMPRESSED):
            raise ValueError("unsupported candidate file attributes")
        if (info.links != 1 or standard.links != 1 or standard.delete_pending
                or standard.directory or not 0 < size <= MAX_FILE_BYTES):
            raise ValueError("candidate must be one ordinary nonempty file of at most 64 MiB")
        compression = ctypes.c_ushort()
        returned = wintypes.DWORD()
        self._check(self._kernel.DeviceIoControl(
            self.handle, 0x9003C, None, 0, ctypes.byref(compression), 2,
            ctypes.byref(returned), None))
        if compression.value not in {0, 2}:
            raise ValueError("unsupported compression format")
        return {"size_bytes": size,
                "allocation_bytes": int(standard.allocation),
                "volume_serial": int(info.volume),
                "file_index": (int(info.index_high) << 32) | int(info.index_low),
                "mtime_ns": (_ticks(info.written) - FILETIME_EPOCH) * 100,
                "creation_filetime": _ticks(info.created),
                "attributes": int(info.attributes),
                "compression_format": compression.value}

    def digest(self, *, guard, bytes_per_second=8 * MIB):
        """Stream through an independent reader while the original handle pins bytes."""
        expected = self.metadata()["size_bytes"]
        digest = hashlib.sha256()
        count = 0
        start = time.monotonic()
        with self.path.open("rb", buffering=0) as stream:
            while True:
                guard()
                block = stream.read(MIB)
                if not block:
                    break
                count += len(block)
                if count > expected:
                    raise ValueError("file grew during protected read")
                digest.update(block)
                if bytes_per_second:
                    time.sleep(max(0, count / bytes_per_second - (time.monotonic() - start)))
        if count != expected:
            raise ValueError("file length changed during protected read")
        return digest.hexdigest()

    def compress(self):
        if not self.writable:
            raise ValueError("read-only candidate handle")
        algorithm, returned = ctypes.c_ushort(2), wintypes.DWORD()
        self._check(self._kernel.DeviceIoControl(
            self.handle, 0x9C040, ctypes.byref(algorithm), 2,
            None, 0, ctypes.byref(returned), None))
        self._check(self._kernel.FlushFileBuffers(self.handle))


class PinnedNtfsDirectory(LockedNtfsFile):
    """Keep an evidence directory and every ancestor in place through mutation."""

    def __init__(self, path):
        super().__init__(path, writable=False)

    def __enter__(self):
        try:
            for parent in reversed((self.path, *self.path.parents)):
                self.handle = self._open(parent, directory=True)
            return self
        except BaseException:
            self._stack.close()
            raise
