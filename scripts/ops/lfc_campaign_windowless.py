"""Owner-registered GUI entry point; no console, credentials or order logic.

Agents never invoke this on a campaign. The parent remains alive until the
contained PowerShell wrapper exits; Scheduler IgnoreNew therefore spans the
whole attempt. The wrapper owns the Python child's kill-on-close Job.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime, timezone


STATUS_ROOT = Path(r'C:\t\pilot\status\control')
IMPORT_OVERRIDES = ('PYTHONPATH', 'PYTHONHOME', 'WEATHER_MARKET_REGISTRY')


def append_refusal(path, raw):
    with path.open('ab') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def move_refusal(source, target):
    # Production is Windows: rename is atomic and refuses an existing name.
    # Other hosts cannot safely emulate that with a check-then-replace race.
    if os.name != 'nt':
        raise OSError('atomic_move_requires_windows')
    os.rename(source, target)


def refusal_row(reason):
    """One atomic UTC-named record; names/codes only, no private values."""
    now = datetime.now(timezone.utc)
    row = {'schema_version': 'lfc_launcher_refusal_v0.1', 'state': 'REFUSED', 'phase': 'REFUSED',
        'at_utc': now.isoformat(),
        'observed_at_utc': now.isoformat(), 'reason': reason, 'exit_code': 1,
        'variable_names': sorted(name for name in IMPORT_OVERRIDES if name in os.environ)}
    raw = (json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    name = (now.strftime('%Y%m%dT%H%M%S%fZ') + '-launcher-refusals-' +
            now.date().isoformat() + '-' + uuid.uuid4().hex + '.jsonl')
    path = STATUS_ROOT / name
    # A filename-sorted watch sees only complete one-line records. Stage in
    # the parent directory, then publish create-only; never replace evidence.
    temporary = STATUS_ROOT.parent / ('.' + name + '.tmp')
    created = False
    try:
        try:
            STATUS_ROOT.mkdir(parents=True, exist_ok=True)
            with temporary.open('xb') as stream:
                created = True
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except OSError:
                move_refusal(temporary, path)
        except OSError:
            # Only a fully flushed stage can reach link/rename. A failed write
            # stays outside the watched folder and falls directly to this log.
            STATUS_ROOT.parent.mkdir(parents=True, exist_ok=True)
            append_refusal(STATUS_ROOT.parent / 'launcher-refusals-fallback.jsonl', raw)
    finally:
        if created:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # The complete refusal is retained; cleanup cannot erase it.



class ChildJob:
    """Assign a suspended wrapper before it can spawn; close kills its tree."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.kernel = k = c.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.argtypes, k.CreateJobObjectW.restype = (c.c_void_p, w.LPCWSTR), w.HANDLE
        k.SetInformationJobObject.argtypes = (w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
        k.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
        k.TerminateJobObject.argtypes = (w.HANDLE, w.UINT)
        k.CloseHandle.argtypes = (w.HANDLE,)
        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                ('min_working', c.c_size_t), ('max_working', c.c_size_t), ('active_limit', w.DWORD),
                ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Limits(c.Structure):
            _fields_ = [('basic', Basic), ('io', c.c_ulonglong * 6),
                ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle: raise OSError('windowless_job_create')
        limits = Limits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; handle is not inheritable.
        if not k.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            k.CloseHandle(self.handle)
            raise OSError('windowless_job_limits')

    def resume(self, child):
        c, w, k = self.c, self.w, self.kernel
        k.OpenProcess.argtypes, k.OpenProcess.restype = (w.DWORD, w.BOOL, w.DWORD), w.HANDLE
        handle = k.OpenProcess(0x0100 | 0x0001 | 0x0800, False, child.pid)
        if not handle: raise OSError('windowless_child_handle')
        try:
            if not k.AssignProcessToJobObject(self.handle, handle): raise OSError('windowless_child_assignment')
            native = c.WinDLL('ntdll')
            native.NtResumeProcess.argtypes = (w.HANDLE,)
            if native.NtResumeProcess(handle) != 0: raise OSError('windowless_child_resume')
        finally:
            k.CloseHandle(handle)

    def close(self):
        try:
            self.kernel.TerminateJobObject(self.handle, 1)
        finally:
            self.kernel.CloseHandle(self.handle)


def file_sha(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(65536), b''):
            sha.update(block)
    return sha.hexdigest()


def run(release_path, expected_sha):
    if os.name != 'nt' or any(name in os.environ for name in IMPORT_OVERRIDES):
        raise ValueError('campaign_windowless_environment')
    release_path = Path(release_path).resolve(strict=True)
    if release_path.stat().st_size > 65536 or file_sha(release_path) != expected_sha:
        raise ValueError('campaign_release_hash')
    row = json.loads(release_path.read_bytes())
    root = Path(__file__).resolve().parents[2]
    binding = row['windowless']
    if (row.get('schema_version') != 'lfc_campaign_release_v0.1' or
            row.get('task_name') != 'WeatherLFCCampaign' or Path(row['root']).resolve() != root or
            Path(binding['python']).resolve() != Path(sys.executable).resolve() or
            file_sha(sys.executable) != binding['sha256'] or
            file_sha(__file__) != binding['launcher_sha256']):
        raise ValueError('campaign_windowless_binding')
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # No pipes or inherited console handles: PS and its contained child share
    # the owner's session, with no visible window. The tick writes its own safe
    # rotating log and status. Never expose raw stderr or credential paths here.
    with open(os.devnull, 'r+b') as sink:
        job, child = ChildJob(), None
        try:
            child = subprocess.Popen([str(shell), '-NoProfile', '-NonInteractive', '-File',
                str(root / 'scripts/ops/lfc_campaign_task.ps1'), '-ReleasePath', str(release_path),
                '-ReleaseSha256', expected_sha], cwd=root, stdin=sink, stdout=sink, stderr=sink,
                creationflags=subprocess.CREATE_NO_WINDOW | 0x4, close_fds=True)
            job.resume(child)
            return child.wait()
        finally:
            job.close()
            if child is not None:
                if child.poll() is None: child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', required=True)
    parser.add_argument('--release-sha256', required=True)
    args = parser.parse_args()
    try:
        return run(args.release, args.release_sha256)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        allowed = {'campaign_windowless_environment', 'campaign_release_hash', 'campaign_windowless_binding'}
        reason = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else 'campaign_windowless_refused'
        try:
            refusal_row(reason)
        except OSError:
            pass  # An unwritable volume still returns nonzero; never leak its exception/path.
        return 1


if __name__ == '__main__':
    sys.exit(main())
