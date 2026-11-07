"""Account and workstation exclusion for the owner-activated campaign lane.

All handles stay on one coordinator thread. Abandoned/poisoned ownership is
refused without recovery. No environment flag can attest ownership to a child.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import threading
import uuid

from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new
from weather.operations.live_path_security import validate_nonreparse_directory


class AdmissionBusy(RuntimeError):
    pass


class AdmissionUncertain(RuntimeError):
    pass


def workstation_headroom():
    """Admission-only observation, never kills apps or changes host thresholds."""
    if os.name != 'nt':
        raise AdmissionUncertain('windows_required')
    import ctypes
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in ('total_phys', 'avail_phys', 'total_page', 'avail_page',
                                                  'total_virtual', 'avail_virtual', 'extended')]
    row = Memory()
    row.length = ctypes.sizeof(row)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Memory)]
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(row)):
        raise AdmissionBusy('headroom_observation_unavailable')
    if row.avail_phys < 1024 * 1024 * 1024 or row.avail_page < 1024 * 1024 * 1024:
        raise AdmissionBusy('workstation_headroom')
    return {'available_physical_bytes': row.avail_phys, 'available_commit_bytes': row.avail_page}


_owned = threading.local()
LEGACY_MUTEX = r'Global\WeatherProjectHeavyWorkloadV1'
HOLD_PATH = Path(r'C:\t\codex\HOLD_HEAVY')


class OwnedHold:
    """Advisory owner-runtime marker, subordinate to the real OS exclusion.

    Agents never manufacture this live marker. Tests always supply a temp path.
    A pre-existing holder is honored, never deleted or taken over.
    """
    def __init__(self, path=HOLD_PATH, *, policy_metadata=None):
        self.path, self.identity, self.sha256 = Path(path), uuid.uuid4().hex, None
        self.policy_metadata = {} if policy_metadata is None else dict(policy_metadata)

    def acquire(self):
        try:
            write_new(self.path, {'schema_version': 'lfc_campaign_hold_v0.1', 'owner': self.identity,
                                  **self.policy_metadata,
                                  'pid': os.getpid()})
        except FileExistsError:
            raise AdmissionBusy('hold_already_owned') from None
        self.sha256 = file_sha(self.path)

    def release(self, *, contained):
        if not contained:
            raise AdmissionUncertain('hold_retained_teardown_unproved')
        if self.sha256 is None or file_sha(self.path) != self.sha256:
            raise AdmissionUncertain('hold_ownership_changed')
        if strict_json(read_bytes(self.path, 65536)).get('owner') != self.identity:
            raise AdmissionUncertain('hold_ownership_changed')
        self.path.unlink()


def account_key(maker):
    return hashlib.sha256(str(maker).lower().encode('ascii')).hexdigest()


def account_owned(maker):
    return account_key(maker) in getattr(_owned, 'accounts', set())


def require_account(maker):
    if not account_owned(maker):
        raise AdmissionUncertain('account_guard_required')


class WindowsMutexes:
    def __init__(self):
        if os.name != 'nt':
            raise AdmissionUncertain('windows_required')
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]

    def acquire(self, name):
        handle = self.api.CreateMutexW(None, False, name)
        if not handle:
            raise AdmissionUncertain('mutex_open_failed')
        result = self.api.WaitForSingleObject(handle, 0)
        if result == 0:
            return handle
        if result == 0x80:
            # Release our acquired abandoned handle; the caller records a sticky
            # incident. Never pretend abandonment proved the old tree is gone.
            self.api.ReleaseMutex(handle)
        self.api.CloseHandle(handle)
        if result == 0x102:
            raise AdmissionBusy('workload_busy')
        raise AdmissionUncertain('mutex_abandoned_or_failed')

    def release(self, handle):
        ok = self.api.ReleaseMutex(handle)
        self.api.CloseHandle(handle)
        if not ok:
            raise AdmissionUncertain('mutex_release_failed')


@contextmanager
def account_lease(maker, *, backend=None):
    backend = WindowsMutexes() if backend is None else backend
    if account_owned(maker):
        raise AdmissionUncertain('nested_account_lease')
    handle = backend.acquire(r'Global\WeatherLFCCampaignAccount.' + account_key(maker))
    previous = getattr(_owned, 'accounts', set())
    _owned.accounts = previous | {account_key(maker)}
    try:
        yield
    finally:
        _owned.accounts = previous
        backend.release(handle)


class ExclusiveWorkload:
    """Barrier + legacy + all seven newer slots, not just the default slot."""
    def __init__(self, maker, *, backend=None, namespace=LEGACY_MUTEX, poison_root=None):
        self.maker = maker
        self.backend = WindowsMutexes() if backend is None else backend
        self.namespace = namespace
        self.poison_root = Path(poison_root) if poison_root is not None else Path(
            os.environ.get('ProgramData', r'C:\ProgramData')) / 'WeatherProject'
        self.handles = []
        self.thread = None

    def check(self):
        require_account(self.maker)
        if self.thread != threading.get_ident() or len(self.handles) != 9:
            raise AdmissionUncertain('exclusive_lease_not_owned')

    def __enter__(self):
        require_account(self.maker)
        if self.handles:
            raise AdmissionUncertain('nested_workload_lease')
        try:
            for suffix in ['.Exclusive', ''] + [f'.Slot{i}' for i in range(2, 9)]:
                self.handles.append(self.backend.acquire(self.namespace + suffix))
            try:
                validate_nonreparse_directory(self.poison_root.absolute())
            except RuntimeError:
                raise AdmissionUncertain('workload_state_root_uncertain') from None
            poisons = ['heavy_workload_v1.poison'] + [f'heavy_workload_v1.slot{i}.poison' for i in range(2, 9)]
            for name in poisons:
                try:
                    (self.poison_root / name).lstat()
                except FileNotFoundError:
                    continue
                except OSError:
                    raise AdmissionUncertain('workload_state_unreadable') from None
                raise AdmissionUncertain('workload_poison')
            self.thread = threading.get_ident()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        failed = False
        while self.handles:
            try:
                self.backend.release(self.handles.pop())
            except BaseException:
                failed = True
        self.thread = None
        if failed:
            raise AdmissionUncertain('workload_release_uncertain')
