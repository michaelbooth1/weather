"""Crash-persistent live workload marker, with explicit owner/reboot recovery.

The legacy poison location is intentional: older admission helpers reject this
new schema instead of automatically recovering it as an offline/Stage-0 lease.
Only this owner's reviewed recovery can clear it after a proved reboot.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import os
import sys

from weather.market.lfc_campaign_guard import AdmissionUncertain, HOLD_PATH, LEGACY_MUTEX, WindowsMutexes, account_key, CAMPAIGN_WORK_LOCK
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new


WORKLOAD_SCHEMA = 'lfc_campaign_workload_v0.1'


def current_boot_id():
    if os.name != 'nt':
        raise AdmissionUncertain('windows_boot_identity_required')
    import winreg
    path = r'SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        value, kind = winreg.QueryValueEx(key, 'BootId')
    if kind != winreg.REG_DWORD or type(value) is not int or not 0 <= value <= 2147483647:
        raise AdmissionUncertain('windows_boot_identity_unreadable')
    return value


class WorkloadMarker:
    def __init__(self, *, poison_root, state_id, maker, boot_id=None, policy_metadata=None):
        self.path = Path(poison_root) / 'heavy_workload_v1.poison'
        self.state_id, self.maker = state_id, maker
        self.boot_id = current_boot_id() if boot_id is None else boot_id
        self.sha256 = None
        self.policy_metadata = {} if policy_metadata is None else dict(policy_metadata)

    def acquire(self, *, hold_sha256, hold_owner):
        from weather.operations.process_lock_identity import current_process_identity
        write_new(self.path, {'schema_version': WORKLOAD_SCHEMA, 'state': 'ACTIVE', 'state_id': self.state_id,
                             **self.policy_metadata,
                             'account_key': account_key(self.maker), 'owner_pid': os.getpid(),
                             'hold_sha256': hold_sha256, 'hold_owner': hold_owner,
                             'owner_process_identity': current_process_identity(),
                             'boot_id': self.boot_id, 'at_utc': datetime.now(timezone.utc).isoformat()})
        self.sha256 = file_sha(self.path)

    def release(self, *, contained):
        if not contained or self.sha256 is None or file_sha(self.path) != self.sha256:
            raise AdmissionUncertain('campaign_workload_marker_retained')
        self.path.unlink()


def proved_owner_gone(row, now_boot):
    if type(row.get('boot_id')) is not int:
        return False
    if row['boot_id'] != now_boot:
        return True
    identity = row.get('owner_process_identity') or {}
    pid = row.get('owner_pid', row.get('pid'))
    if type(pid) is not int or pid <= 0 or identity.get('pid') != pid or not identity.get('creation_time_token'):
        return False
    from weather.operations.process_lock_identity import lock_owner_status
    return lock_owner_status({'pid': pid, 'owner_process_identity': identity}).get('stale') is True


def retained_read_allowed(path, *, maker, state_id):
    """GET recording may inspect a proved-dead own attempt, never clear it."""
    row = strict_json(read_bytes(path, 65536))
    return (row.get('schema_version') == WORKLOAD_SCHEMA and row.get('state_id') == state_id and
            row.get('account_key') == account_key(maker) and proved_owner_gone(row, current_boot_id()))


def owner_release_workload_after_reboot(*, path, expected_sha, state_id, maker, boot_id=None, backend=None,
                             namespace=LEGACY_MUTEX, owner_terminal=None, confirmation=None, hold_path=CAMPAIGN_WORK_LOCK):
    """Never called by automatic admission or money reconciliation."""
    terminal = sys.stdin.isatty() if owner_terminal is None else owner_terminal
    if terminal is not True:
        raise AdmissionUncertain('owner_terminal_required')
    row = strict_json(read_bytes(path, 65536))
    now_boot = current_boot_id() if boot_id is None else boot_id
    if (file_sha(path) != expected_sha or row.get('schema_version') != WORKLOAD_SCHEMA or
            row.get('state_id') != state_id or row.get('account_key') != account_key(maker) or
            not proved_owner_gone(row, now_boot)):
        raise AdmissionUncertain('owner_reboot_continuity_required')
    phrase = 'clear workload ' + expected_sha[:12]
    if confirmation is None:
        print('After reboot and continuity review only. Type: ' + phrase)
        confirmation = input().strip()
    if confirmation != phrase:
        raise AdmissionUncertain('owner_confirmation_refused')
    backend = WindowsMutexes(owner_recovery=True) if backend is None else backend
    # Acquire every real compatibility slot. This explicit owner recovery knows
    # only its one hash-bound marker; it never clears any other slot's poison.
    with ExitStack() as stack:
        for suffix in ['.Exclusive', ''] + [f'.Slot{i}' for i in range(2, 9)]:
            handle = backend.acquire(namespace + suffix)
            stack.callback(backend.release, handle)
        if file_sha(path) != expected_sha:
            raise AdmissionUncertain('owner_marker_changed')
        hold = Path(hold_path)
        if hold.exists() and (file_sha(hold) != row.get('hold_sha256') or
                              strict_json(read_bytes(hold, 65536)).get('owner') != row.get('hold_owner')):
            raise AdmissionUncertain('different_hold_owner')
        Path(path).unlink()
        if hold.exists():
            hold.unlink()
    # The monetary incident/claimed date remains. Clearing a workload marker
    # does not authorize live admission or close an ambiguous placement.


def owner_release_hold_only(*, path, expected_sha, boot_id=None, backend=None, owner_terminal=None, confirmation=None):
    terminal = sys.stdin.isatty() if owner_terminal is None else owner_terminal
    if terminal is not True:
        raise AdmissionUncertain('owner_terminal_required')
    path = Path(path)
    row = strict_json(read_bytes(path, 65536))
    now_boot = current_boot_id() if boot_id is None else boot_id
    if (file_sha(path) != expected_sha or row.get('schema_version') != 'lfc_campaign_hold_v0.1' or
            not proved_owner_gone(row, now_boot)):
        raise AdmissionUncertain('hold_owner_not_proved_gone')
    phrase = 'clear hold ' + expected_sha[:12]
    if confirmation is None:
        print('After proved owner exit only. Type: ' + phrase)
        confirmation = input().strip()
    if confirmation != phrase:
        raise AdmissionUncertain('owner_confirmation_refused')
    backend = WindowsMutexes(owner_recovery=True) if backend is None else backend
    with ExitStack() as stack:
        for suffix in ['.Exclusive', ''] + [f'.Slot{i}' for i in range(2, 9)]:
            handle = backend.acquire(LEGACY_MUTEX + suffix)
            stack.callback(backend.release, handle)
        if file_sha(path) != expected_sha:
            raise AdmissionUncertain('different_hold_owner')
        path.unlink()
