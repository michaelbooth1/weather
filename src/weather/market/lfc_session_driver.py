"""Owner-run LFC attended-session driver (`python -m weather.market.lfc_cli session-run`).

One window, one command: the driver performs every step the session runbook makes the owner paste by hand
(docs/research/live-fill-calibration-session0-runbook-2026-10-09.md sections 3-8, as revised for counted sessions
by docs/research/live-fill-calibration-session1-runbook-2026-10-16.md). It is an ORCHESTRATOR ONLY:

- every campaign step runs the PINNED CLI as a child process (`python -m weather.market.lfc_cli <mode>` with
  cwd = the pinned worktree and PYTHONPATH = pin;pin\\src, runbook section 2), so `code_identity`, `clean_preflight`,
  `start_gates`, `start_refusals`, `confirmation`, the fee rule, the L ledger and every other refusal in lfc_cli,
  lfc_pilot and re1_owner_checks run unchanged; nothing is reimplemented or bypassed;
- `preflight`, `live` and `session0-attest` inherit the owner's console stdin, so their `owner_terminal_required`
  checks stay real and the `go <6 hex>` / `attest session0 <6 hex>` phrases are typed by the owner into the pinned
  CLI's own prompt. The driver never writes to a child's stdin and has no flag or variable that confirms anything;
- nothing is written into the pinned worktree (clean_preflight refuses a dirty tree); the evidence pack goes to the
  campaign root that lfc_cli already writes (`pilot_root()`), under `driver-<UTC stamp>/`.

Ported runbook helpers (section 2 of the session-0 runbook): Test-HostFree, Get-OpenOrderCount, Test-ReaderQuietAt,
Wait-ReaderQuiet, Save-OwnerSnapshot, Get-LatestT40Row and Compare-T40ToStart. Session-0 finding (record
2026-10-16, "the reader cap under closely spaced reads"; docs/operations/wallet-reader.md): every reader-touching
step waits for the reader-quiet window first, and one TimeoutError / timeout / refused is answered by
Wait-ReaderQuiet and ONE retry before the step FAILs. `preflight` and `live` are never retried.

The driver stops on the first FAIL or refusal and still writes pack.json and summary.txt with the reason.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

from weather.market import lfc_constants as LFC
from weather.market.lfc_ledger import BASELINE_SCHEMA  # the field Compare-T40ToStart checks

PACK_SCHEMA = 'lfc_session_driver_pack_v0.1'
EOF = object()

# Runbook section 3.2: what the pinned interpreter must report (pin-relative paths are checked separately).
EXPECTED_PYTHON_VERSION = '3.11.9'
EXPECTED_SDK_VERSION = '0.6.0'
# Runbook section 3.3.
EXPECTED_ASSIGNMENT_LINE = 'status=ASSIGNED host_match=True principal_match=True not_capture=True'
# Session-0 runs the driver may perform: only those with no owner action between `go` and the end (runbook
# section 6). 0b (foreign order), 0c (kill), 0d/0f/0g (drop measurement) stay manual.
DRIVER_SESSION0_RUNS = ('0a', '0e')
# neg_risk values each session kind may sign (clarification D, D8, signed 2026-10-10): session 0 is screened to
# plain binary markets (neg_risk false on both tokens); "Session 1 is the first neg-risk signing", so a counted
# session may sign either exchange path under the unchanged PR section 6 limits. Missing, None or non-bool refuses.
NEG_RISK_ALLOWED = {True: frozenset({False}), False: frozenset({True, False})}
# Pin review e27909a76..6bc6f2bec, SF-1: OwnerVenue.balances refuses collateral_allowance only when the MAXIMUM over
# all spenders is short, so a wallet approved for the standard exchange alone passes and the first neg-risk post is
# rejected (a counted session and its date spent). The driver therefore reads the per-spender allowances the PASS
# preflight already journaled (`preflight_read` step=balances, collateral_evidence.allowances; no new venue read) and
# requires every spender of the band's exchange path to cover the band cap (lfc_pilot.venue_ceiling: 0.98 x size).
# Production addresses from polymarket-client 0.6.0 `polymarket.environments.PRODUCTION` (a test pins them).
SPENDERS = {'standard_exchange': '0xE111180000d2663C0091e4f400237545B87B996B',
            'neg_risk_exchange': '0xe2222d279d744050d28e00520010520000310F59',
            'neg_risk_adapter': '0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296'}
SPENDERS_FOR = {False: ('standard_exchange',), True: ('neg_risk_exchange', 'neg_risk_adapter')}
BAND_CAP_FRACTION = Decimal('.98')
# Owner Ctrl+C during `live`: the console delivers it to the live child as well, whose own cleanup cancels our
# orders and reconciles (runbook section 9 step 1). The driver waits this long for that cleanup, then kills the tree.
LIVE_INTERRUPT_GRACE_SECONDS = 90
# After a kill the child's pipe must reach EOF within this many seconds, or the driver says LIVE STILL RUNNING.
KILL_EOF_SECONDS = 10
# A driver exception escaped mid-grace (_wait_out_grace): the wait is also bounded without the injected clock, by a
# monotonic cap of LIVE_INTERRUPT_GRACE_SECONDS + KILL_EOF_SECONDS and by this many consecutive swallowed exceptions;
# either one kills the tree and ends the wait (a clock that raises or is frozen cannot hold live's job open).
GRACE_EXCEPTION_LIMIT = 20
_FAR = datetime.max.replace(tzinfo=timezone.utc)
SECTION9_ACTION = ('If orders may rest: run `lfc_cli cancel-ours`, then `reconcile`, `verify`, `wallet-verify` and '
                   'Get-OpenOrderCount (runbook section 9). The driver never cancels.')

# The runbook section 8 "send to master" list, adapted to a counted session (and kept for 0a/0e session-0 runs).
# Every key is always present in pack.json and named in summary.txt (None when the step did not run).
MASTER_FIELDS = (
    'stopped_reason', 'stop_step', 'stop_code', 'pin_commit', 'session_kind', 'runs_planned', 't24',
    'latest_legal_live_start_utc', 'host_free_lines', 'reader_quiet_lines', 'snapshot_hash_lines', 't40_start_line',
    'compare_lines', 'preflight', 'selection_screen', 'runs', 'verify_lines', 'wallet_verify_line', 'attestation',
    'refusal_codes', 'action', 'live_still_running')
RUN_FIELDS = ('run', 'folder', 'session_id', 'reason', 'cleanup_ok', 'panic', 'result_line', 'toast_delivered',
              'helper_open_orders_after', 'submit_expirations', 'session_selection_neg_risk',
              'session_selection_fee_class', 'neg_risk_signing_suspect', 'exit_code', 'refusal')
# Pin review SF-2: a first post rejected on a neg-risk band is reported as a signing-contract suspect, never retried.
SIGNING_SUSPECT_REASONS = ('submit_acknowledgment', 'exception')


class DriverStop(Exception):
    """The driver's single stop path: step name, reason code, and whether it is a FAIL, a REFUSAL or a planned end."""

    def __init__(self, step, code, *, kind='FAIL'):
        super().__init__(code)
        self.step, self.code, self.kind = step, code, kind


# ----- injected boundaries -----------------------------------------------------------------------------------------
class Clock:
    def now(self):
        return datetime.now(timezone.utc)

    def sleep(self, seconds):
        import time
        time.sleep(seconds)


class Console:
    def say(self, text):
        try:
            print(text, flush=True)
        except UnicodeEncodeError:
            print(str(text).encode('ascii', 'replace').decode('ascii'), flush=True)

    def isatty(self):
        return sys.stdin.isatty()


class _Job:
    """A Windows job object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (ctypes only). Closing or terminating it ends
    every process in the child tree, including the venv launcher's interpreter child (runbook section 6, 0c)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k32 = k32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)

        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount',
                'WriteTransferCount', 'OtherTransferCount')]

        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', Io), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('job_create_failed')
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise OSError('job_limit_failed')

    def assign_and_resume(self, pid):
        """Assign the CREATE_SUSPENDED child, then resume it, so no grandchild can start outside the job."""
        process = self.k32.OpenProcess(0x0100 | 0x0001 | 0x0800, False, pid)  # SET_QUOTA|TERMINATE|SUSPEND_RESUME
        if not process:
            raise OSError('job_open_process_failed')
        try:
            assigned = bool(self.k32.AssignProcessToJobObject(self.handle, process))
            ntdll = self.ctypes.WinDLL('ntdll')
            ntdll.NtResumeProcess.argtypes = (self.wintypes.HANDLE,)
            if ntdll.NtResumeProcess(process) != 0:
                raise OSError('resume_failed')
            return assigned
        finally:
            self.k32.CloseHandle(process)

    def terminate(self):
        return bool(self.handle) and bool(self.k32.TerminateJobObject(self.handle, 1))

    def close(self):
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


class ChildProcess:
    """One child: lines from a reader thread (so Ctrl+C and deadlines stay responsive), a job-object tree kill with
    a `taskkill /F /T` fallback when no job could be created or assigned."""

    def __init__(self, argv, *, cwd, env, interactive):
        self.job, self.kill_method = None, 'taskkill'
        flags = 0x4 if os.name == 'nt' else 0  # CREATE_SUSPENDED until the job holds it
        self.popen = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=None if interactive else subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8',
                                      errors='replace', creationflags=flags)
        if os.name == 'nt':
            try:
                self.job = _Job()
                if self.job.assign_and_resume(self.popen.pid):
                    self.kill_method = 'job'
                else:
                    self.job.close()
                    self.job = None
            except Exception:
                if self.job is not None:
                    self.job.close()
                    self.job = None
                self._resume_fallback()
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _resume_fallback(self):
        """Job creation failed: resume the suspended child; if even that fails, terminate it (nothing ran)."""
        try:
            import ctypes
            k32, ntdll = ctypes.WinDLL('kernel32'), ctypes.WinDLL('ntdll')
            k32.OpenProcess.restype = ctypes.c_void_p
            handle = k32.OpenProcess(0x0800, False, self.popen.pid)
            ok = bool(handle) and ntdll.NtResumeProcess(ctypes.c_void_p(handle)) == 0
            if handle:
                k32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:
            ok = False
        if not ok:
            self.popen.kill()
            raise RuntimeError('child_start_failed')

    def _pump(self):
        for line in self.popen.stdout:
            self.lines.put(line.rstrip('\r\n'))
        self.lines.put(EOF)

    def poll_line(self, timeout):
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait(self):
        return self.popen.wait()

    def kill_tree(self):
        if self.job is not None and self.job.terminate():
            return 'job'
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.popen.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
        return 'taskkill'

    def close(self):
        if self.job is not None:
            self.job.close()  # kill-on-close: nothing of this child's tree outlives the step


class Runner:
    """Starts children in the pinned worktree with the runbook section 2 environment."""

    def __init__(self, *, pin):
        self.pin = Path(pin)
        env = dict(os.environ)
        env['PYTHONPATH'] = f'{self.pin};{self.pin / "src"}'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        self.env = env

    def start(self, argv, *, interactive=False):
        return ChildProcess(argv, cwd=self.pin, env=self.env, interactive=interactive)


# ----- pure helpers (unit-tested) ----------------------------------------------------------------------------------
def utc_text(value, millis=False):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3 if millis else -7] + 'Z'


def reader_quiet_at(at, last_call):
    """Runbook section 2 Test-ReaderQuietAt: >= 60 s after a 5-minute boundary (the capture host's journal burst),
    <= 270 s into it, and >= 60 s after this window's last reader call."""
    phase = (at.minute % 5) * 60 + at.second
    since = 99999 if last_call is None else min((at - last_call).total_seconds(), 99999)
    return {'ok': 60 <= phase <= 270 and since >= 60, 'phase_s': phase, 'since_last_read_s': int(since)}


def parse_dicts(lines):
    """The dicts lfc_cli prints (SecretGuard.print is print(dict)); unparseable lines are skipped."""
    found = []
    for line in lines:
        text = line.strip()
        if text.startswith('{') and text.endswith('}'):
            try:
                value = ast.literal_eval(text)
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                try:
                    value = json.loads(text)
                except ValueError:
                    continue
            if isinstance(value, dict):
                found.append(value)
    return found


def last_status(lines):
    rows = [d for d in parse_dicts(lines) if 'status' in d]
    return rows[-1] if rows else None


def is_transient_cli(row):
    """A reader/venue read that timed out or was refused (session-0 record): wait for the quiet window, retry once."""
    if not isinstance(row, dict) or row.get('status') != 'REFUSED':
        return False
    kind = str(row.get('exception_type') or '')
    return 'Timeout' in kind or row.get('code') in ('timeout', 'refused')


def refusal_code(row, default):
    if not isinstance(row, dict):
        return default
    if row.get('refusals'):
        return ','.join(str(r) for r in row['refusals'])
    return str(row.get('code') or row.get('exception_type') or row.get('message') or default)


def judge_open_order_count(code, lines, *, expected=0):
    """Runbook section 2 Get-OpenOrderCount output: a number, or `ERR <reason>`."""
    text = [line.strip() for line in lines if line.strip()]
    last = text[-1] if text else ''
    if re.fullmatch(r'\d+', last):
        count = int(last)
        return ('PASS', count) if count == expected else ('FAIL', f'open_orders_{count}_expected_{expected}')
    if last in ('ERR timeout', 'ERR refused') or any('TimeoutError' in line for line in text):
        return 'TRANSIENT', 'reader_' + (last.split()[-1] if last.startswith('ERR') else 'timeout')
    if last.startswith('ERR'):
        return 'FAIL', 'reader_' + last.split()[-1]
    return 'FAIL', 'reader_output_unreadable'


def judge_cli(code, lines, *, step):
    row = last_status(lines)
    if is_transient_cli(row):
        return 'TRANSIENT', refusal_code(row, step + '_timeout')
    if code == 0 and row is not None and row.get('status') in ('PASS', 'ATTESTED'):
        return 'PASS', row
    return 'FAIL', refusal_code(row, f'{step}_exit_{code}') if row is not None and row.get('status') == 'REFUSED' \
        else f"{step}_{(row or {}).get('status') or 'exit_' + str(code)}"


def judge_wallet_verify(code, lines):
    row = last_status(lines)
    if is_transient_cli(row):
        return 'TRANSIENT', refusal_code(row, 'wallet_verify_timeout')
    if row is None:
        return 'FAIL', f'wallet_verify_exit_{code}'
    if code == 0 and row.get('status') == 'PASS':
        return 'PASS', row
    if any(row.get(k) == 'ERR' for k in ('open_orders', 'venue_L', 'positions_reader_status', 'l_difference')):
        return 'TRANSIENT', 'wallet_verify_reader_err'  # the session-0 post-0g case: venue L read as ERR
    return 'FAIL', 'wallet_verify_' + ('s0_1_fail' if row.get('s0_1') != 'PASS' else 's0_6_fail'
                                       if row.get('s0_6') != 'PASS' else str(row.get('status')))


def judge_snapshot(code, lines):
    text = '\n'.join(lines).strip()
    try:
        value = json.loads(text)
    except ValueError:
        return ('TRANSIENT', 'snapshot_timeout') if 'TimeoutError' in text else ('FAIL', 'snapshot_unreadable')
    if isinstance(value, dict) and value.get('error'):
        reason = str(value.get('reason'))
        return ('TRANSIENT' if reason in ('timeout', 'refused') else 'FAIL'), 'snapshot_' + reason
    return ('PASS', text) if code == 0 else ('FAIL', f'snapshot_exit_{code}')


def judge_host_free(lines):
    """Runbook section 3.4 success: holder null/empty, poison False, queued 0, MUTEX FREE (or WAS ABANDONED, cleared)."""
    values = {}
    for line in lines:
        if '=' in line and line.split('=', 1)[0] in ('holder', 'poison', 'queued'):
            key, value = line.split('=', 1)
            values[key] = value.strip()
        elif line.startswith('MUTEX'):
            values['mutex'] = line.strip()
    ok = (values.get('holder') in ('', 'null', '{}') and values.get('poison') == 'False' and
          values.get('queued') == '0' and values.get('mutex') in ('MUTEX FREE', 'MUTEX WAS ABANDONED (now cleared)'))
    return ok, values


def ledger_rows(root):
    path = Path(root) / 'ledger.jsonl'
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dec(value):
    return Decimal(str(value))


def compare_t40_to_start(root, start_file, start_sha):
    """Runbook section 2 Compare-T40ToStart (R-D1 (a), D5), ported field for field: the latest ledger t40 against
    the session-start t40 on schema, maker_address, open_order_ids, positions outside the ledger's own leg_intent
    tokens, and available_collateral while no leg of ours matched. Returns (ok, the PASS/STOP line); counts only."""
    try:
        rows = ledger_rows(root)
        t40s = [r for r in rows if r.get('event') == 'baseline' and r.get('label') == 't40']
        last = t40s[-1]
        why = []
        if not any(r.get('file') == start_file and r.get('sha256') == start_sha for r in t40s):
            why.append('start_not_a_ledger_t40')
        if _sha256_file(Path(root) / start_file) != start_sha:
            why.append('start_sha_mismatch')
        if _sha256_file(Path(root) / last['file']) != last['sha256']:
            why.append('latest_sha_mismatch')
        s = json.loads((Path(root) / start_file).read_bytes())
        latest = json.loads((Path(root) / last['file']).read_bytes())
        if s.get('schema_version') != BASELINE_SCHEMA or latest.get('schema_version') != BASELINE_SCHEMA:
            why.append('baseline_schema')
        if s.get('maker_address') != latest.get('maker_address'):
            why.append('account_differs')
        if list(s.get('open_order_ids') or []) or list(latest.get('open_order_ids') or []):
            why.append('open_orders_in_baseline')
        ours = [str(r.get('token_id')) for r in rows if r.get('event') == 'leg_intent']
        fills = sum(1 for r in rows if r.get('event') == 'leg_terminal' and _dec(r.get('size_matched')) != 0)
        sm = {k: _dec(v) for k, v in (s.get('positions') or {}).items()}
        lm = {k: _dec(v) for k, v in (latest.get('positions') or {}).items()}
        assets = sorted(a for a in set(sm) | set(lm) if a not in ours)
        changed = sum(1 for a in assets if sm.get(a) != lm.get(a))
        if changed:
            why.append(f'positions_changed_outside_pilot_tokens={changed}')
        if fills == 0 and _dec(s.get('available_collateral')) != _dec(latest.get('available_collateral')):
            why.append('collateral_changed_without_pilot_fill')
    except (OSError, ValueError, KeyError, IndexError, TypeError, InvalidOperation):
        return False, f'STOP compare_unreadable start={start_file}'
    if why:
        return False, f"STOP {' '.join(why)} start={start_file} latest={last['file']}"
    return True, (f"PASS start={start_file} latest={last['file']} assets_compared={len(assets)} "
                  f"pilot_tokens_excluded={len(ours)} pilot_fills={fills}")


def latest_baseline_row(root, label):
    """Runbook section 4 Get-LatestT40Row (any label): the last ledger baseline row of that label, or None."""
    rows = [r for r in ledger_rows(root) if r.get('event') == 'baseline' and r.get('label') == label]
    return rows[-1] if rows else None


def parse_utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('naive')
    return parsed.astimezone(timezone.utc)


def latest_legal_live_start(now, seconds):
    """start + run length must end by 23:50Z of the start's UTC date (PR section 4; lfc_pilot.start_refusals,
    past_hard_stop_2350z). The pin's gate decides; this only tells the owner the last minute that can pass it."""
    stop = datetime.combine(now.astimezone(timezone.utc).date(), LFC.HARD_STOP_UTC, tzinfo=timezone.utc)
    return stop - timedelta(seconds=seconds)


def t24_window(at_utc):
    """lfc_ledger.compare_baselines: a counted start needs the t24 20-30 h old."""
    at = parse_utc(at_utc)
    return at + timedelta(hours=20), at + timedelta(hours=30)


def neg_risk_screen(selection, condition, *, session0):
    """Clarification D, D8: the printed condition's row in the latest PASS preflight selection.json; every token's
    snapshot.rules.<token>.neg_risk must be a bool allowed for this session kind (NEG_RISK_ALLOWED) and equal on
    both tokens. Returns (ok, code, {token: value}, fee_class)."""
    rows = [r for r in (selection or {}).get('rows') or [] if isinstance(r, dict) and r.get('condition_id') == condition]
    if len(rows) != 1:
        return False, 'neg_risk_row_missing', {}, None
    row = rows[0]
    fee = row.get('fee') if isinstance(row.get('fee'), dict) else {}
    tokens = row.get('token_ids') if isinstance(row.get('token_ids'), list) else []
    try:
        rules = row['snapshot']['rules']
        values = {str(t): rules[str(t)].get('neg_risk') if isinstance(rules.get(str(t)), dict) else None
                  for t in tokens}
    except (KeyError, TypeError, AttributeError):
        return False, 'neg_risk_unreadable', {}, fee.get('fee_class')
    if len(tokens) != 2 or len(values) != 2:
        return False, 'neg_risk_tokens_not_two', values, fee.get('fee_class')
    if any(type(v) is not bool for v in values.values()):
        return False, 'neg_risk_missing_or_not_bool', values, fee.get('fee_class')
    if len(set(values.values())) != 1:
        return False, 'neg_risk_differs_between_tokens', values, fee.get('fee_class')
    if next(iter(values.values())) not in NEG_RISK_ALLOWED[bool(session0)]:
        return False, 'neg_risk_' + str(next(iter(values.values()))).lower() + '_not_allowed', values, \
            fee.get('fee_class')
    return True, None, values, fee.get('fee_class')


def preflight_allowances(journal_bytes):
    """The per-spender collateral allowances of the last `balances` read a preflight journaled (atomic units, keys
    lower-cased). Raises ValueError when no such read is present."""
    found = None
    for line in journal_bytes.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        response = row.get('response') if row.get('event') == 'preflight_read' and row.get('step') == 'balances' \
            else row.get('balances') if row.get('event') == 'selection_wallet' else None
        allowances = ((response or {}).get('collateral_evidence') or {}).get('allowances') \
            if isinstance(response, dict) else None
        if isinstance(allowances, dict) and allowances:
            found = {str(k).lower(): v for k, v in allowances.items()}
    if found is None:
        raise ValueError('no_allowance_evidence')
    return found


def allowance_screen(allowances, size, neg_risk):
    """SF-1: every spender of the band's exchange path (SPENDERS_FOR) must allow at least the band cap,
    0.98 x size pUSD. Returns (ok, code, {spender name: atomic amount or None}) for all three named spenders."""
    shown = {name: (allowances or {}).get(address.lower()) for name, address in SPENDERS.items()}
    try:
        need = BAND_CAP_FRACTION * _dec(size) * 1_000_000
    except (InvalidOperation, TypeError):
        return False, 'allowance_size_unreadable', shown
    for name in SPENDERS_FOR[bool(neg_risk)]:
        try:
            amount = _dec(shown[name])
        except (InvalidOperation, TypeError):
            return False, f'allowance_{name}_missing', shown
        if amount < need:
            return False, f'allowance_{name}_below_band_cap', shown
    return True, None, shown


def latest_preflight(root):
    """The receipt clean_preflight would read: the lexically last preflight-* folder (a newer FAIL hides a PASS)."""
    paths = sorted(Path(root).glob('preflight-*'))
    return paths[-1] if paths else None


def result_fields(line):
    return dict(re.findall(r'(\w+)=(\S+)', line[len('LFC-RESULT '):])) if line.startswith('LFC-RESULT ') else {}


# ----- the driver --------------------------------------------------------------------------------------------------
TEST_HOST_FREE_PS = r"""
. .\scripts\ops\workload_admission.ps1
"holder=" + (Get-WeatherHeavyWorkloadHolderSummary -RepoRoot (Get-Location).Path | ConvertTo-Json -Compress)
"poison=" + (Test-Path 'C:\ProgramData\WeatherProject\heavy_workload_v1.poison')
"queued=" + @(Get-ChildItem 'C:\ProgramData\WeatherProject\heavy_workload_queue_v1' -Filter 'ticket-*.json' -ErrorAction SilentlyContinue).Count
$m = [Threading.Mutex]::new($false, 'Global\WeatherProjectHeavyWorkloadV1')
try { if ($m.WaitOne(0)) { $m.ReleaseMutex(); 'MUTEX FREE' } else { 'MUTEX BUSY' } }
catch [Threading.AbandonedMutexException] { $m.ReleaseMutex(); 'MUTEX WAS ABANDONED (now cleared)' }
finally { $m.Dispose() }
"""
HOST_ASSIGNMENT_PS = r"""
. .\scripts\ops\workload_admission.ps1
$a = Get-Content .\config\international_live_execution_host.json -Raw | ConvertFrom-Json
$h = Get-WeatherExecutionHostId; $p = Get-WeatherExecutionPrincipalId
"status=$($a.assignment_status) host_match=$($h -eq $a.active_portable_execution_host_id) principal_match=$($p -eq $a.active_portable_execution_principal_id) not_capture=$($h -ne $a.dedicated_capture_execution_host_id)"
"""
OPEN_ORDER_COUNT_PY = ("import weather.market.wallet_reader_client as c\ntry:\n print(c.open_order_count(fresh=True))\n"
                       "except c.ReaderError as e:\n print('ERR', getattr(e, 'reason', 'refused'))")
INTERPRETER_PY = ("import sys, weather.market.lfc_cli, weather.market.re1_evidence, weather.market.re1_owner_checks, "
                  "weather.market.re1_rehearsal, weather.market.re1_transport, weather.market.wallet_reader_client\n"
                  "print('econ_loaded=' + str('weather.market.exchange_economics' in sys.modules))\n"
                  "import weather, weather.paths, importlib.metadata as m\n"
                  "print('version=' + sys.version.split()[0]); print('weather=' + weather.__file__)\n"
                  "print('lfc_cli=' + weather.market.lfc_cli.__file__); print('repo_root=' + str(weather.paths.REPO_ROOT))\n"
                  "print('sdk=' + m.version('polymarket-client'))\n"
                  "from polymarket.environments import PRODUCTION\n"
                  "for n in ('standard_exchange', 'neg_risk_exchange', 'neg_risk_adapter'):\n"
                  " print('spender_' + n + '=' + getattr(PRODUCTION._config, n))")


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(str(a).replace('/', os.sep))) == \
        os.path.normcase(os.path.normpath(str(b).replace('/', os.sep)))


@dataclass
class DriverConfig:
    pin: Path
    expect_commit: str
    root: Path
    snap_dir: Path
    python: str = sys.executable
    phase: str = 'session'  # 'session' or 't24'
    to_go_prompt: bool = False
    session0_runs: tuple = ()
    session0_flags: tuple = ()  # --event-slug ... --extra-conditions F --shadow-scope F, passed through unchanged
    attest: tuple | None = None  # (s0_2_seconds, helper_zero_utc), session 0 only


@dataclass
class _State:
    steps: list = field(default_factory=list)
    pack: dict = field(default_factory=dict)
    last_reader_call: datetime | None = None
    current: object = None
    current_is_live: bool = False
    interrupted: bool = False
    transcript_index: int = 0


class SessionDriver:
    def __init__(self, config, *, runner, clock=None, console=None, monotonic=None):
        self.config, self.runner = config, runner
        self.clock, self.console = clock or Clock(), console or Console()
        self.monotonic = monotonic or time.monotonic  # seconds; independent of the injected clock
        self.state = _State()
        self.session0 = bool(config.session0_runs)
        self.pack_dir = None

    # --- bookkeeping ---
    def say(self, text):
        self.console.say(text)

    def record(self, step, status, **fields):
        row = {'step': step, 'status': status, 'at_utc': utc_text(self.clock.now()), **fields}
        self.state.steps.append(row)
        self.say(f"DRIVER {status} {step}" + (f" {fields['code']}" if fields.get('code') else ''))
        return row

    def _transcript(self, name, lines):
        """Raw child output holds reader JSON (positions, balances, the address) and live's table with
        available_collateral: it stays owner-private beside the owner snapshots (Fable review fix 3). The pack folder
        holds only each transcript's sha256 (per step)."""
        self.state.transcript_index += 1
        raw = ('\n'.join(lines) + '\n').encode('utf-8')
        if self.pack_dir is not None:
            folder = self.config.snap_dir / 'driver-transcripts' / self.pack_dir.name
            path = folder / f'{self.state.transcript_index:02d}-{name}.txt'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def cli(self, mode, *extra):
        return [self.config.python, '-m', 'weather.market.lfc_cli', mode, *extra]

    # --- children ---
    def _run_child(self, name, argv, *, interactive=False, echo=True, live_hook=None):
        """Start a child and stream its lines. Ctrl+C anywhere in an iteration (poll, hook, console, clock) is one
        owner press: a non-live child is killed at once; `live` (which got the Ctrl+C from the console too) keeps
        LIVE_INTERRUPT_GRACE_SECONDS for its own cleanup, and a second press or the deadline kills its tree. The job
        is never closed while that grace is pending. After any kill every further line is dropped, and EOF must come
        within KILL_EOF_SECONDS or the driver says LIVE STILL RUNNING. A hook returns None (it echoed the line
        itself) or a list of messages: kill FIRST, then say them. Returns (exit code, lines, transcript sha256)."""
        proc = self.runner.start(argv, interactive=interactive)
        self.state.current, self.state.current_is_live = proc, live_hook is not None
        st = {'lines': [], 'deadline': None, 'killed_at': None, 'presses': 0, 'eof': False, 'stuck': False}
        live = live_hook is not None
        code = None
        try:
            while not st['eof'] and not st['stuck']:
                try:
                    self._iteration(proc, st, live_hook, echo)
                except KeyboardInterrupt:
                    self._press(proc, st, live)
            while st['eof']:
                try:
                    code = proc.wait()
                    break
                except KeyboardInterrupt:
                    self._press(proc, st, live)
        finally:
            try:
                if not (st['eof'] or st['killed_at'] is not None or st['deadline'] is None):
                    self._wait_out_grace(proc, st)  # a driver exception escaped mid-grace: let live finish first
                proc.close()  # kill-on-close; never while live's own cleanup grace is pending
            finally:
                self.state.current = None
        sha = self._transcript(name, st['lines'])
        if st['stuck']:
            raise DriverStop(name, 'live_still_running_after_kill' if live else 'child_still_running_after_kill',
                             kind='INTERRUPT' if self.state.interrupted else 'FAIL')
        if self.state.interrupted:
            raise DriverStop(name, 'owner_interrupt', kind='INTERRUPT')
        return code, st['lines'], sha

    def _iteration(self, proc, st, live_hook, echo):
        item = proc.poll_line(0.5)
        if item is EOF:
            st['eof'] = True
            return
        now = self.clock.now()
        if st['killed_at'] == _FAR:  # a Ctrl+C landed inside kill_tree: kill again, start the EOF watchdog now
            st['killed_at'] = now
            self.record('kill_tree', 'INFO', method=proc.kill_tree(), retried=True)
        if st['deadline'] is not None and st['killed_at'] is None and now >= st['deadline']:
            self._kill(proc, st)
        # any output after a kill counts as still running: a killed child that keeps printing never reaches EOF
        if st['killed_at'] is not None and now - st['killed_at'] >= timedelta(seconds=KILL_EOF_SECONDS):
            st['stuck'] = True
            self.state.pack['live_still_running'] = True
            self.say('LIVE STILL RUNNING \u2014 Ctrl+C now, type nothing')
            return
        if item is None:
            return
        st['lines'].append(item)
        if st['killed_at'] is not None:
            return  # after a kill nothing more reaches the console (a buffered `Type: go` line included)
        if live_hook is None:
            if echo:
                self.say(item)
            return
        messages = live_hook(item)
        if messages is not None:
            self._kill(proc, st)
            for message in messages:
                self.say(message)

    def _press(self, proc, st, live):
        """One owner Ctrl+C; a press while this one is handled counts as the next press."""
        st['presses'] += 1
        self.state.interrupted = True
        while True:
            try:
                if live and st['presses'] == 1 and st['killed_at'] is None:
                    if st['deadline'] is None:
                        st['deadline'] = _FAR  # grace pending before the clock is read
                        st['deadline'] = self.clock.now() + timedelta(seconds=LIVE_INTERRUPT_GRACE_SECONDS)
                    self.say('DRIVER owner Ctrl+C: live is running its own cleanup; Ctrl+C again kills its tree')
                elif st['killed_at'] is None:
                    self._kill(proc, st)
                return
            except KeyboardInterrupt:
                st['presses'] += 1

    def _wait_out_grace(self, proc, st):
        """An exception escaped while live's cleanup grace was pending: keep reading (nothing is shown) until EOF,
        and kill only when the remaining grace runs out or on another Ctrl+C. Bounded by the grace deadline and,
        without the injected clock, by the monotonic cap and GRACE_EXCEPTION_LIMIT consecutive swallowed exceptions."""
        cap = self.monotonic() + LIVE_INTERRUPT_GRACE_SECONDS + KILL_EOF_SECONDS
        failures = 0
        while not st['eof'] and st['killed_at'] is None:
            try:
                try:
                    item = proc.poll_line(0.5)
                    if item is EOF:
                        st['eof'] = True
                    elif item is not None:
                        st['lines'].append(item)
                finally:
                    # the monotonic cap first: a raising or frozen clock is never consulted once it has passed
                    if not st['eof'] and st['killed_at'] is None and (
                            self.monotonic() >= cap or self.clock.now() >= st['deadline']):
                        self._kill(proc, st)
                failures = 0
            except KeyboardInterrupt:
                st['presses'] += 1
                self._kill(proc, st)
            except Exception:  # keep waiting; the deadline, the monotonic cap and the storm limit bound this loop
                failures += 1
                if failures >= GRACE_EXCEPTION_LIMIT:
                    try:
                        self._kill(proc, st)  # marks killed_at before anything in it can raise
                    except Exception:
                        pass
                    return

    def _kill(self, proc, st):
        if st['killed_at'] is None:
            st['killed_at'] = _FAR  # killed, before anything below can raise
            method = proc.kill_tree()
            st['killed_at'] = self.clock.now()
            self.record('kill_tree', 'INFO', method=method)

    def kill(self, proc):
        method = proc.kill_tree()
        self.record('kill_tree', 'INFO', method=method)

    # --- runbook helpers ---
    def wait_reader_quiet(self, step, lead=0):
        """Runbook section 2 Wait-ReaderQuiet; the READER_QUIET line goes to the pack."""
        while True:
            at = self.clock.now() + timedelta(seconds=lead)
            r = reader_quiet_at(at, self.state.last_reader_call)
            if r['ok']:
                line = (f"READER_QUIET event_utc={utc_text(at)} phase_s={r['phase_s']} "
                        f"since_last_read_s={r['since_last_read_s']}")
                self.state.pack.setdefault('reader_quiet_lines', []).append(f'{step}: {line}')
                self.say(line)
                return line
            self.clock.sleep(0.5)

    def reader_step(self, name, argv, judge, *, echo=True):
        """Every reader-touching step: Wait-ReaderQuiet, run, and on a transient failure Wait-ReaderQuiet and retry
        ONCE (session-0 record 2026-10-16); a second failure, or any other failure, stops the driver."""
        for attempt in (1, 2):
            self.wait_reader_quiet(name)
            code, lines, sha = self._run_child(name, argv, echo=echo)
            self.state.last_reader_call = self.clock.now()
            verdict, value = judge(code, lines)
            if verdict == 'PASS':
                self.record(name, 'PASS', attempt=attempt, transcript_sha256=sha)
                return value, lines
            self.record(name, 'RETRY' if verdict == 'TRANSIENT' and attempt == 1 else 'FAIL', attempt=attempt,
                        code=value, transcript_sha256=sha)
            if verdict != 'TRANSIENT' or attempt == 2:
                raise DriverStop(name, value)
        raise AssertionError('unreachable')

    def open_order_count(self, name='open_order_count'):
        count, _ = self.reader_step(name, [self.config.python, '-c', OPEN_ORDER_COUNT_PY], judge_open_order_count)
        return count

    def test_host_free(self, before):
        """Runbook section 3.4: before every preflight and every live."""
        name = 'test_host_free_' + before
        code, lines, sha = self._run_child(name, ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                                  TEST_HOST_FREE_PS])
        ok, values = judge_host_free(lines)
        self.state.pack.setdefault('host_free_lines', []).append(
            f"{before}: holder={values.get('holder')} poison={values.get('poison')} queued={values.get('queued')} "
            f"{values.get('mutex')}")
        self.record(name, 'PASS' if ok else 'FAIL', code=None if ok else 'host_not_free', transcript_sha256=sha)
        if not ok:
            raise DriverStop(name, 'host_not_free')

    def save_owner_snapshot(self, label):
        """Runbook section 2 Save-OwnerSnapshot: raw reader output stays owner-private in the snapshot folder; only
        the sha256 lines go to the pack. One quiet wait for the three reads, retry-once per read."""
        self.config.snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.clock.now().strftime('%Y%m%dT%H%M%SZ')
        for resource in ('summary', 'open-orders', 'positions'):
            text, _ = self.reader_step(f'snapshot_{label}_{resource}',
                                       [self.config.python, '-m', 'weather.market.wallet_reader_client', resource],
                                       judge_snapshot, echo=False)
            path = self.config.snap_dir / f'{label}-{resource}-{stamp}.json'
            with open(path, 'xb') as handle:
                handle.write((text + '\n').encode('utf-8'))
            self.state.pack.setdefault('snapshot_hash_lines', []).append(f'{_sha256_file(path)}  {path.name}')

    def baseline(self, label):
        row, _ = self.reader_step(f'baseline_{label}', self.cli('baseline', '--label', label),
                                  lambda c, l: judge_cli(c, l, step='baseline'))
        return row

    def compare(self, when):
        ok, line = compare_t40_to_start(self.config.root, *self.t40_start)
        self.state.pack.setdefault('compare_lines', []).append(f'{when}: {line}')
        self.record('compare_t40_to_start_' + when, 'PASS' if ok else 'FAIL', code=None if ok else line)
        if not ok:
            raise DriverStop('compare_t40_to_start_' + when, line)

    def verify(self, when):
        row, _ = self.reader_step('verify_' + when, self.cli('verify'), lambda c, l: judge_cli(c, l, step='verify'))
        self.state.pack.setdefault('verify_lines', []).append(
            f"{when}: status={row.get('status')} our_open_orders={row.get('our_open_orders')} "
            f"foreign_open_orders={row.get('foreign_open_orders')} open_sessions={row.get('open_sessions')} "
            f"counted_sessions={row.get('counted_sessions')} session0_passed={row.get('session0_passed')} "
            f"stop_reason={row.get('stop_reason')} L={row.get('L')}")
        return row

    # --- steps ---
    def setup(self):
        """Runbook sections 3.1-3.3 on the pin: HEAD, a clean tree, the lock, the pinned imports, the assignment."""
        pin, git = str(self.config.pin), ['git', '-C', str(self.config.pin)]
        code, lines, _ = self._run_child('setup_head', git + ['rev-parse', 'HEAD'])
        head = lines[-1].strip() if lines else ''
        if code != 0 or head != self.config.expect_commit:
            raise DriverStop('setup_head', 'pin_head_not_expected_commit', kind='REFUSED')
        self.state.pack['pin_commit'] = head
        code, lines, _ = self._run_child('setup_status', git + ['status', '--porcelain', '--untracked-files=normal'])
        if code != 0 or any(line.strip() for line in lines):
            raise DriverStop('setup_status', 'pin_worktree_not_clean', kind='REFUSED')
        code, lines, _ = self._run_child('setup_lock', git + ['worktree', 'list', '--porcelain'])
        block, locked = False, False
        for line in lines:
            if line.startswith('worktree '):
                block = _same_path(line[len('worktree '):], pin)
            elif block and line.startswith('locked'):
                locked = True
        if code != 0 or not locked:
            raise DriverStop('setup_lock', 'pin_worktree_not_locked', kind='REFUSED')
        code, lines, _ = self._run_child('setup_interpreter', [self.config.python, '-c', INTERPRETER_PY])
        seen = dict(line.split('=', 1) for line in lines if '=' in line)
        expected = {'econ_loaded': 'False', 'version': EXPECTED_PYTHON_VERSION, 'sdk': EXPECTED_SDK_VERSION}
        paths = {'weather': self.config.pin / 'weather' / '__init__.py',
                 'lfc_cli': self.config.pin / 'src' / 'weather' / 'market' / 'lfc_cli.py', 'repo_root': self.config.pin}
        if code != 0 or any(seen.get(k) != v for k, v in expected.items()) or \
                any(not _same_path(seen.get(k, ''), v) for k, v in paths.items()):
            raise DriverStop('setup_interpreter', 'pin_interpreter_or_imports_unexpected', kind='REFUSED')
        if any(seen.get('spender_' + k) != v for k, v in SPENDERS.items()):
            raise DriverStop('setup_interpreter', 'pin_sdk_spenders_differ', kind='REFUSED')  # SF-1 addresses
        code, lines, _ = self._run_child('setup_assignment', ['powershell.exe', '-NoProfile', '-NonInteractive',
                                                              '-Command', HOST_ASSIGNMENT_PS])
        if code != 0 or EXPECTED_ASSIGNMENT_LINE not in [line.strip() for line in lines]:
            raise DriverStop('setup_assignment', 'wrong_workstation_or_principal', kind='REFUSED')
        self.record('setup', 'PASS')

    def timing(self, seconds):
        """Counted: the t24 must be 20-30 h old at the live start; the start must leave the run inside 23:50Z. These
        are early stops for the owner's benefit; the pin's start_gates/start_refusals stay the deciding gates."""
        now = self.clock.now()
        latest = latest_legal_live_start(now, seconds)
        if not self.session0:
            row = latest_baseline_row(self.config.root, 't24')
            if row is None:
                raise DriverStop('timing', 'baseline_missing_t24', kind='REFUSED')
            opens, closes = t24_window(row['at_utc'])
            self.state.pack['t24'] = {'file': row['file'], 'sha256': row['sha256'], 'at_utc': row['at_utc'],
                                      'valid_from_utc': utc_text(opens), 'valid_until_utc': utc_text(closes)}
            latest = min(latest, closes)
            if now < opens:
                raise DriverStop('timing', 'driver_t24_younger_than_20h_until_' + utc_text(opens), kind='REFUSED')
        self.state.pack['latest_legal_live_start_utc'] = utc_text(latest)
        self.say(f'DRIVER latest legal live start {utc_text(latest)} (the pin refuses past_hard_stop_2350z / '
                 'baseline_t24_age after it)')
        if now > latest:
            raise DriverStop('timing', 'driver_past_latest_legal_live_start', kind='REFUSED')

    def run_flags(self, run):
        return ('--session0', '--run', run, *self.config.session0_flags) if run else ()

    def preflight(self, run):
        self.test_host_free('preflight')
        name = 'preflight' + (f'_{run}' if run else '')
        code, lines, sha = self._run_child(name, self.cli('preflight', *self.run_flags(run)), interactive=True)
        row = last_status(lines)
        receipt = latest_preflight(self.config.root)
        self.state.pack['preflight'] = {'receipt_folder': receipt.name if receipt else None,
                                        'status': (row or {}).get('status'), 'exit_code': code}
        if code != 0 or (row or {}).get('status') != 'PASS':
            self.record(name, 'FAIL', code=refusal_code(row, 'preflight_failed'), transcript_sha256=sha)
            raise DriverStop(name, refusal_code(row, 'preflight_failed'))
        self.record(name, 'PASS', transcript_sha256=sha)

    def screen_selection(self, row):
        """D8 neg_risk screen and SF-1 allowance screen of the printed selection; returns (ok, code, SCREEN line).
        The line carries no selection sha256 and no go code."""
        condition = row['condition']
        receipt = latest_preflight(self.config.root)
        try:
            if json.loads((receipt / 'preflight.json').read_bytes()).get('status') != 'PASS':
                raise ValueError('latest preflight is not PASS')
            selection = json.loads((receipt / 'selection.json').read_bytes())
        except (OSError, ValueError, TypeError, AttributeError):
            selection = None
        ok, code, values, fee_class = neg_risk_screen(selection, condition, session0=self.session0)
        shown = None
        if ok:  # SF-1: the band's exchange path must be approved per spender, from the preflight's own read
            try:
                allowances = preflight_allowances((receipt / 'journal.jsonl').read_bytes())
            except (OSError, ValueError, TypeError):
                ok, code = False, 'allowance_evidence_unreadable'
            else:
                ok, code, shown = allowance_screen(allowances, row.get('size'), next(iter(values.values())))
        self.state.pack['selection_screen'] = {
            'condition': condition, 'event_slug': row.get('event_slug'), 'quote': row.get('quote'),
            'size': row.get('size'), 'minutes': row.get('minutes'), 'fee_class': fee_class,
            'neg_risk_preflight': values, 'neg_risk_allowed': sorted(NEG_RISK_ALLOWED[self.session0]),
            'allowances_atomic': shown, 'preflight_receipt_folder': receipt.name if receipt else None,
            'status': 'PASS' if ok else code}
        return ok, code, (f"SCREEN {'PASS' if ok else 'REFUSED ' + code} condition={condition} "
                          f"event_slug={row.get('event_slug')} fee_class={fee_class} neg_risk={values} "
                          f"allowed={sorted(NEG_RISK_ALLOWED[self.session0])} allowances_atomic={shown}")

    def live(self, run, seconds):
        """`live` with the owner's console as stdin. Its output is held from the selection line on until the
        neg_risk screen (D8) passes, so the owner cannot read `go <6 hex>` before it; a failed screen kills the tree
        at the prompt (runbook section 5: Ctrl+C at the prompt posts nothing). --to-go-prompt kills it there too."""
        self.timing(seconds)
        self.test_host_free('live')
        self.say(f"DRIVER latest legal live start {self.state.pack['latest_legal_live_start_utc']}; "
                 'type the go phrase only after the SCREEN PASS line')
        screen = {'state': 'pending', 'stop': None}

        def hook(line):
            """None = this hook echoed the line; a list = kill the live tree first, then say these messages."""
            if screen['state'] == 'passed':
                self.say(line)
                return None
            if screen['state'] != 'pending' or line.lstrip().startswith('Type:'):
                return None  # nothing after the selection line is shown until the screens passed
            rows = parse_dicts([line])
            if not (rows and 'condition' in rows[0] and 'selection_sha256' in rows[0]):
                self.say(line)
                return None
            screen['state'] = 'screening'
            ok, code, text = self.screen_selection(rows[0])
            if not ok:
                screen['state'], screen['stop'] = 'stopped', DriverStop('neg_risk_screen', code, kind='REFUSED')
                return [text]
            if self.config.to_go_prompt:
                screen['state'] = 'stopped'
                screen['stop'] = DriverStop('live_dry_run', 'dry_run_complete', kind='END')
                return [text, f"DRY RUN stopped at the go prompt: condition={rows[0].get('condition')} "
                              f"event_slug={rows[0].get('event_slug')} size={rows[0].get('size')} (nothing posted)"]
            screen['state'] = 'passed'
            self.say(text)
            if any(self.state.pack['selection_screen']['neg_risk_preflight'].values()):
                self.say('SCREEN neg-risk band: SDK 0.6.0 picks the exchange itself (pin review SF-2). If the first '
                         'post is rejected (submit_acknowledgment / exception), REPORT it as a signing-contract '
                         'suspect; do not retry.')
            self.say(line)
            return None

        name = 'live' + (f'_{run}' if run else '')
        code, lines, sha = self._run_child(name, self.cli('live', *self.run_flags(run)), interactive=True,
                                           live_hook=hook)
        result = next((line for line in reversed(lines) if line.startswith('LFC-RESULT ')), None)
        if screen['stop'] is not None:
            self.record(name, 'END' if screen['stop'].kind == 'END' else 'REFUSED', code=screen['stop'].code,
                        transcript_sha256=sha)
            if self.config.to_go_prompt:
                self.test_host_free('after_dry_run')  # clears the mutex the killed live left abandoned (3.4)
            raise screen['stop']
        if result is None:
            row = last_status(lines)
            code_text = refusal_code(row, f'live_exit_{code}')
            self.record(name, 'REFUSED', code=code_text, transcript_sha256=sha)
            raise DriverStop(name, code_text, kind='REFUSED')
        self.record(name, 'ENDED', exit_code=code, transcript_sha256=sha)
        return code, result

    def after_run(self, run, code, result):
        """Runbook section 5 "After every run": session_end.json, the journal's submit expirations (S0-7), the
        session's own selection.json neg_risk (D8), Get-OpenOrderCount 0 (fresh read), verify PASS."""
        fields = result_fields(result)
        session_id = fields.get('session_id')
        entry = {k: None for k in RUN_FIELDS}
        entry.update(run=run or 'counted', session_id=session_id, result_line=result, exit_code=code)
        self.state.pack.setdefault('runs', []).append(entry)
        starts = [r for r in ledger_rows(self.config.root) if r.get('event') == 'session_start' and
                  r.get('session_id') == session_id]
        if len(starts) != 1 or not starts[0].get('directory'):
            raise DriverStop('after_run', 'session_directory_unknown')
        directory = self.config.root / starts[0]['directory']
        entry['folder'] = starts[0]['directory']
        try:
            end = json.loads((directory / 'session_end.json').read_bytes())
        except (OSError, ValueError):
            raise DriverStop('after_run', 'session_end_unreadable') from None
        entry.update(reason=end.get('reason'), cleanup_ok=end.get('cleanup_ok'), panic=end.get('panic'),
                     toast_delivered=(end.get('notification') or {}).get('toast_delivered'))
        expirations = set()
        try:
            for line in (directory / 'journal.jsonl').read_bytes().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('event') == 'submit_request':
                    expirations.add(str((row.get('request') or {}).get('expiration')))
        except OSError:
            pass
        entry['submit_expirations'] = sorted(expirations)
        try:
            selection = json.loads((directory / 'selection.json').read_bytes())
            condition = selection.get('selected_condition_id')
            entry['session_selection_neg_risk'] = neg_risk_screen(selection, condition, session0=self.session0)[2]
            entry['session_selection_fee_class'] = next((r.get('fee', {}).get('fee_class') for r in selection.get(
                'rows') or [] if isinstance(r, dict) and r.get('condition_id') == condition and
                isinstance(r.get('fee'), dict)), None)
        except (OSError, ValueError, AttributeError):
            entry['session_selection_neg_risk'] = 'unreadable'
        neg = entry['session_selection_neg_risk']
        entry['neg_risk_signing_suspect'] = bool(isinstance(neg, dict) and any(v is True for v in neg.values()) and
                                                 end.get('reason') in SIGNING_SUSPECT_REASONS)
        if entry['neg_risk_signing_suspect']:
            self.say('AFTER-RUN neg-risk band ended ' + str(end.get('reason')) + ': SIGNING-CONTRACT SUSPECT (pin review '
                     'SF-2). Report it to master-agent; do not start another session for it.')
        self.say(f"AFTER-RUN neg_risk={entry['session_selection_neg_risk']} "
                 f"fee_class={entry.get('session_selection_fee_class')} reason={end.get('reason')} "
                 f"cleanup_ok={end.get('cleanup_ok')} panic={end.get('panic')}")
        self.record('session_end_' + (run or 'counted'), 'INFO', code=None)
        if end.get('cleanup_ok') is not True or end.get('panic'):
            entry['refusal'] = 'cleanup_not_ok_or_panic'
            raise DriverStop('after_run', 'cleanup_not_ok_or_panic')
        entry['helper_open_orders_after'] = self.open_order_count('open_order_count_after_' + (run or 'counted'))
        self.verify('after_' + (run or 'counted'))
        if self.session0 and end.get('reason') not in LFC.SESSION0_PASS_REASONS.get(run, ()):
            entry['refusal'] = 'wrong_end_reason'
            raise DriverStop('after_run', f"wrong_end_reason_{run}_{end.get('reason')}")
        if len(expirations) > 1:
            entry['refusal'] = 'submit_expirations_differ'
            raise DriverStop('after_run', 'submit_expirations_differ')

    def wallet_verify(self):
        row, _ = self.reader_step('wallet_verify', self.cli('wallet-verify'), judge_wallet_verify)
        changed = row.get('positions_changed_outside_pilot')
        self.state.pack['wallet_verify_line'] = (
            f"status={row.get('status')} s0_1={row.get('s0_1')} s0_6={row.get('s0_6')} "
            f"open_orders={row.get('open_orders')} ledger_L={row.get('ledger_L')} venue_L={row.get('venue_L')} "
            f"l_difference={row.get('l_difference')} positions_reader_status={row.get('positions_reader_status')} "
            f"positions_changed_outside_pilot={len(changed) if isinstance(changed, list) else changed}")

    def attest(self):
        """Session 0 only (runbook section 8): the owner reads the printed gap and types the attest phrase into the
        pinned CLI's own prompt; every refusal (runs missing, S above 20 or below the gap, wrong phrase) is the CLI's."""
        seconds, zero = self.config.attest
        code, lines, sha = self._run_child('session0_attest', self.cli(
            'session0-attest', '--s0-2-seconds', str(seconds), '--s0-2-helper-zero-utc', str(zero)), interactive=True)
        row = last_status(lines)
        if code != 0 or (row or {}).get('status') != 'ATTESTED':
            self.record('session0_attest', 'REFUSED', code=refusal_code(row, 'attest_failed'), transcript_sha256=sha)
            raise DriverStop('session0_attest', refusal_code(row, 'attest_failed'), kind='REFUSED')
        self.state.pack['attestation'] = {'sha256': row.get('sha256'), 'file': Path(str(row.get('file'))).name}
        self.record('session0_attest', 'PASS', transcript_sha256=sha)
        self.verify('after_attest')

    # --- plans ---
    def plan_t24(self):
        self.setup()
        self.open_order_count('open_order_count_t24')
        self.save_owner_snapshot('t24')
        row = self.baseline('t24')
        self.state.pack['t24'] = {'file': row.get('baseline'), 'sha256': row.get('sha256'),
                                  'open_orders': row.get('open_orders')}
        return 't24_complete'

    def plan_session(self):
        runs = list(self.config.session0_runs) or [None]
        self.state.pack['runs_planned'] = [r or 'counted' for r in runs]
        self.setup()
        first_seconds = LFC.SESSION0_RUNS[runs[0]] if runs[0] else LFC.SESSION_SECONDS
        self.timing(first_seconds)
        self.test_host_free('start')
        self.open_order_count('open_order_count_start')
        label = 't40'
        self.save_owner_snapshot(label)
        row = self.baseline('t40')
        self.t40_start = (row.get('baseline'), row.get('sha256'))
        self.state.pack['t40_start_line'] = f't40_start file={self.t40_start[0]} sha256={self.t40_start[1]}'
        self.say(self.state.pack['t40_start_line'])
        self.compare('start')
        for index, run in enumerate(runs):
            seconds = LFC.SESSION0_RUNS[run] if run else LFC.SESSION_SECONDS
            if index:
                self.test_host_free('cycle_' + run)
                self.open_order_count('open_order_count_before_' + run)
                self.baseline('t40')
                self.compare('before_' + run)
            self.preflight(run)
            code, result = self.live(run, seconds)
            self.after_run(run, code, result)
        self.verify('final')
        self.wallet_verify()
        self.baseline('t40')  # final t40 AFTER wallet-verify (runbook section 7)
        self.compare('final')
        self.save_owner_snapshot('after-session0' if self.session0 else 'after-session')
        if self.config.attest:
            self.attest()
        return 'session_complete'

    def run(self):
        """Run the plan, stop at the first FAIL/refusal, and always write pack.json and summary.txt."""
        started = self.clock.now()
        self.pack_dir = self.config.root / ('driver-' + started.strftime('%Y%m%dT%H%M%S%fZ'))
        self.pack_dir.mkdir(parents=True, exist_ok=False)
        pack = self.state.pack
        pack.update(schema_version=PACK_SCHEMA, phase=self.config.phase, to_go_prompt=self.config.to_go_prompt,
                    session_kind='session0' if self.session0 else 'counted', pin=str(self.config.pin),
                    started_at_utc=utc_text(started), pack_folder=self.pack_dir.name,
                    live_still_running=False)
        stop = None
        try:
            if not self.console.isatty():
                raise DriverStop('start', 'owner_terminal_required', kind='REFUSED')
            if self.config.phase == 't24' and self.session0:
                raise DriverStop('start', 'driver_t24_is_for_counted_sessions', kind='REFUSED')
            pack['stopped_reason'] = self.plan_t24() if self.config.phase == 't24' else self.plan_session()
        except DriverStop as exc:
            stop = exc
        except KeyboardInterrupt:
            if self.state.current is not None:
                self.kill(self.state.current)
            stop = DriverStop('driver', 'owner_interrupt', kind='INTERRUPT')
        except Exception as exc:  # never echo a message: it may carry a secret
            stop = DriverStop('driver', 'driver_exception_' + type(exc).__name__)
        if stop is not None:
            pack['stopped_reason'] = {'END': stop.code, 'INTERRUPT': 'owner_interrupt'}.get(stop.kind, stop.kind)
            pack['stop_step'], pack['stop_code'] = stop.step, stop.code
            if stop.kind not in ('END',):
                pack['action'] = SECTION9_ACTION if stop.step.startswith(('live', 'after_run', 'driver')) or \
                    stop.kind == 'INTERRUPT' else 'Fix the cause and rerun the driver; nothing was posted by this step.'
        return self.write_pack()

    def write_pack(self):
        pack = self.state.pack
        pack['ended_at_utc'] = utc_text(self.clock.now())
        pack['refusal_codes'] = [s['code'] for s in self.state.steps if s.get('code') and s['status'] != 'PASS']
        pack['steps'] = self.state.steps
        for key in MASTER_FIELDS:
            pack.setdefault(key, None)
        raw = json.dumps(pack, indent=1, sort_keys=True, default=str).encode('utf-8')
        (self.pack_dir / 'pack.json').write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        text = summary_text(pack, sha)
        (self.pack_dir / 'summary.txt').write_text(text, encoding='utf-8')
        self.say(text)
        return pack, sha


def summary_text(pack, sha):
    """The one block the owner pastes to master-agent: the section 8 fields, counts, codes and hashes only."""
    lines = [f"LFC session driver pack {pack.get('schema_version')} sha256={sha}",
             f"pack_folder={pack.get('pack_folder')} phase={pack.get('phase')} to_go_prompt={pack.get('to_go_prompt')} "
             f"started_at_utc={pack.get('started_at_utc')} ended_at_utc={pack.get('ended_at_utc')}"]
    for key in MASTER_FIELDS:
        value = pack.get(key)
        if key == 'runs' and isinstance(value, list):
            lines.append('runs:')
            for run in value:
                lines.append('  ' + ' '.join(f'{k}={run.get(k)}' for k in RUN_FIELDS))
        elif isinstance(value, list):
            lines.append(f'{key}:')
            lines.extend('  ' + str(v) for v in value)
        else:
            lines.append(f'{key}={json.dumps(value, sort_keys=True, default=str) if isinstance(value, dict) else value}')
    return '\n'.join(lines) + '\n'


def main(args):
    """lfc_cli session-run: build the config from the parsed flags and run the driver."""
    from weather.market.lfc_pilot import pilot_root
    from weather.paths import REPO_ROOT
    pin = Path(args.pin) if args.pin else Path(REPO_ROOT)
    flags = []
    for slug in args.event_slug or []:
        flags += ['--event-slug', slug]
    if args.extra_conditions:
        flags += ['--extra-conditions', str(args.extra_conditions)]
    if args.shadow_scope:
        flags += ['--shadow-scope', str(args.shadow_scope)]
    runs = tuple(args.session0_run or ())
    if (flags or args.s0_2_seconds or args.s0_2_helper_zero_utc) and not runs:
        raise ValueError('session0_flags_without_session0')  # counted sessions take no session-0 flags
    if runs and (len(set(runs)) != len(runs) or any(r not in DRIVER_SESSION0_RUNS for r in runs)):
        raise ValueError('driver_session0_runs_are_0a_0e_only')
    if bool(args.s0_2_seconds) != bool(args.s0_2_helper_zero_utc):
        raise ValueError('driver_attest_needs_both_s0_2_values')
    if not re.fullmatch(r'[0-9a-f]{40}', args.expect_commit or ''):
        raise ValueError('expect_commit_must_be_full_sha')
    if args.to_go_prompt and args.phase != 'session':
        raise ValueError('to_go_prompt_is_a_session_phase_option')
    root = pilot_root()
    config = DriverConfig(pin=pin, expect_commit=args.expect_commit, root=root,
                          snap_dir=root.parent / '.weather-lfc-20261009-owner-snapshots', phase=args.phase,
                          to_go_prompt=args.to_go_prompt, session0_runs=runs, session0_flags=tuple(flags),
                          attest=(args.s0_2_seconds, args.s0_2_helper_zero_utc) if args.s0_2_seconds else None)
    pack, _ = SessionDriver(config, runner=Runner(pin=pin)).run()
    return 0 if pack['stopped_reason'] in ('session_complete', 't24_complete', 'dry_run_complete') else 1
