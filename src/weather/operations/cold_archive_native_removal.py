"""Exclusive native NTFS pins for a catalog-verified exact-file removal.

This module owns no selection or deletion authority. Orchestrators must verify
the complete immutable evidence chain and journal intent before remove().
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os

from weather.operations.production_cold_archive_stage import _ArchiveSource, MIB
from weather.operations.ntfs_file_compression import _FileInformation, REPARSE_POINT


class ExactNtfsRemoval(_ArchiveSource):
    """Hash and mark one ordinary NTFS file for deletion through the same handle.

    An exclusive file handle refuses existing readers/writers. Ancestor pins
    prevent directory substitution. There is no path-based unlink fallback.
    """

    def _bind(self):
        super()._bind()
        signatures = {
            "ReadFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL),
            "SetFilePointerEx": ([wintypes.HANDLE, ctypes.c_int64,
                                   ctypes.POINTER(ctypes.c_int64), wintypes.DWORD], wintypes.BOOL),
            "SetFileInformationByHandle": ([wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes, function.restype = arguments, result

    def _close_file(self):
        handle = getattr(self, "_removal_handle", None)
        if handle is not None:
            self._check(self._kernel.CloseHandle(handle))
            self._removal_handle = None

    def _open(self, path, *, directory=False):
        if directory:
            return super()._open(path, directory=True)
        handle = self._kernel.CreateFileW(
            str(path), 0x80000000 | 0x00010000, 0, None, 3,
            0x00200000 | 0x08000000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self._removal_handle = handle
        self._stack.callback(self._close_file)
        info = _FileInformation()
        self._check(self._kernel.GetFileInformationByHandle(handle, ctypes.byref(info)))
        if info.attributes & (REPARSE_POINT | 0x10):
            raise ValueError("removal target is a directory or reparse point")
        final = ctypes.create_unicode_buffer(32768)
        length = self._check(self._kernel.GetFinalPathNameByHandleW(handle, final, len(final), 0))
        if length >= len(final) or os.path.normcase(final.value.removeprefix("\\\\?\\")) != os.path.normcase(str(path)):
            raise ValueError("removal handle names a different path")
        return handle

    def digest(self, *, guard):
        """Read through the exclusive deletion handle, with bounded throttling."""
        before = self.metadata()
        position = ctypes.c_int64()
        self._check(self._kernel.SetFilePointerEx(self.handle, 0, ctypes.byref(position), 0))
        buffer, digest, count = ctypes.create_string_buffer(MIB), hashlib.sha256(), 0
        while True:
            guard.admit()
            returned = wintypes.DWORD()
            self._check(self._kernel.ReadFile(self.handle, buffer, MIB, ctypes.byref(returned), None))
            if not returned.value:
                break
            count += returned.value
            if count > before["size_bytes"]:
                raise ValueError("removal target grew during verification")
            digest.update(buffer.raw[:returned.value])
            guard.account(returned.value)
        if count != before["size_bytes"] or self.metadata() != before:
            raise ValueError("removal target changed during verification")
        return digest.hexdigest()

    def remove(self):
        """Mark the verified handle; close it while its ancestors remain pinned."""
        self.metadata()  # Recheck ordinary file, single link, no pending delete.
        disposition = ctypes.c_ubyte(1)  # FILE_DISPOSITION_INFO.DeleteFile.
        self._check(self._kernel.SetFileInformationByHandle(
            self.handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)))
        self._close_file()
        if self.path.exists() or self.path.is_symlink():
            raise ValueError("removal completion could not be proved")
