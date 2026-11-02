"""Torn maker-evidence journal quarantine (Stage 1 operator tool).

Guards: 2026-11-02 power-loss incident (maker-evidence recorder down 03:36-09:38 on NUL-tailed
reward journals) and the approved L54 auto-recovery design: classify only under the writer lock,
one unsealed segment, only non-empty *.jsonl without a final newline, hard cap 10, byte-exact
same-volume rename with intent and receipt, idempotent reconcile (also after the store sealed),
every NOOP checked against the recorder task's last result, never truncate or rewrite.
Runbook: docs/operations/passive-maker-evidence-capture.md (torn-journal quarantine tool).

Every case runs the real script against a synthetic store under pytest's tmp_path; the real data
root is never named (explicit -Root/-QuarantineRoot/-LogPath). Runs go through a wrapper that
invokes the script in-session (``& script @args``) and, only when a case sets the matching
environment variable, replaces Get-ScheduledTaskInfo, Get-CimInstance or Get-FileHash with a
global stub (the stub pattern of test_docs_light_path_script.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import string
import subprocess
import sys

import pytest

from weather.market.maker_evidence_store import SCHEMA as EVIDENCE_SCHEMA, EvidenceStore, WriterLock, encoded

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "maker_evidence_torn_quarantine.ps1"
DAY, SEGMENT = "2026-11-02", "08-b7021b84b0cf"
CLOCK = lambda: datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)  # noqa: E731

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt" or shutil.which("powershell.exe") is None,
                       reason="Windows PowerShell 5.1 and msvcrt locking required"),
]

WRAPPER = r"""
if ($env:FAKE_TASK_MODE) {
    function global:Get-ScheduledTaskInfo { [CmdletBinding()] param([string]$TaskName)
        if ($env:FAKE_TASK_MODE -eq 'missing') { return }
        if ($env:FAKE_TASK_PROBE_SCRIPT) {
            $out = & $env:FAKE_PYTHON $env:FAKE_TASK_PROBE_SCRIPT $env:FAKE_LOCK_ROOT 2>&1 | Out-String
            [IO.File]::WriteAllText($env:FAKE_TASK_PROBE_OUT, $out)
        }
        $result = $env:FAKE_TASK_RESULT
        if ($env:FAKE_TASK_MODE -eq 'garbage') { $result = 'not-a-number' }
        [pscustomobject]@{ TaskName = $TaskName; LastTaskResult = $result
            LastRunTime = (Get-Date).AddSeconds([int]$env:FAKE_TASK_RUN_OFFSET) } }
}
if ($env:FAKE_PROCESS_CMDLINE) {
    function global:Get-CimInstance { [CmdletBinding()] param([Parameter(Position = 0)][string]$ClassName, [string]$Filter)
        if ($env:FAKE_PROCESS_CMDLINE -eq 'throw') { throw 'process query stub failure' }
        [pscustomobject]@{ ProcessId = 4242; CommandLine = $env:FAKE_PROCESS_CMDLINE } }
}
if ($env:FAKE_HASH_BAD_PREFIX -or $env:FAKE_HASH_NULL_PREFIX) {
    # Get-FileHash is a function of this module in 5.1; an autoload after the stub would replace it.
    Import-Module Microsoft.PowerShell.Utility
    function global:Get-FileHash { [CmdletBinding()] param([string]$LiteralPath, [string]$Algorithm = 'SHA256')
        if ($env:FAKE_HASH_NULL_PREFIX -and
            $LiteralPath.StartsWith($env:FAKE_HASH_NULL_PREFIX, [StringComparison]::OrdinalIgnoreCase)) { return $null }
        if ($env:FAKE_HASH_BAD_PREFIX -and
            $LiteralPath.StartsWith($env:FAKE_HASH_BAD_PREFIX, [StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{ Hash = ('0' * 64) } }
        $stream = [IO.File]::OpenRead($LiteralPath); $sha = [Security.Cryptography.SHA256]::Create()
        try { [pscustomobject]@{ Hash = ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '') } }
        finally { $sha.Dispose(); $stream.Dispose() } }
}
& $env:FAKE_SCRIPT @args
$code = $LASTEXITCODE
if ($env:FAKE_RELOCK) {
    $s = New-Object IO.FileStream($env:FAKE_RELOCK, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite,
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try { $s.Lock(0, 1); $s.Unlock(0, 1); [IO.File]::WriteAllText($env:FAKE_RELOCK + '.probe', 'RELOCK_OK') }
    catch { [IO.File]::WriteAllText($env:FAKE_RELOCK + '.probe', 'RELOCK_FAILED') }
    finally { $s.Dispose() }
}
exit $code
"""


def journal(records=3, newline=b"\n"):
    raw, offset = b"", 0
    for index in range(records):
        line = encoded({"kind": "reward", "n": index, "offset": offset}) + newline
        raw += line
        offset += len(line)
    return raw


TORN_NUL = journal() + b"\x00" * 4096
TORN_PARTIAL = journal() + b'{"kind":"reward","n":3,"off'


def make_store(base, files, *, day=DAY, segment=SEGMENT, sealed=False):
    root = base / "maker_evidence"
    folder = root / day / segment
    folder.mkdir(parents=True)
    (root / ".writer.lock").write_bytes(b"0")
    for name, data in files.items():
        (folder / name).write_bytes(data)
    if sealed:
        (folder / "manifest.json").write_bytes(b"{}\n")
    return root, folder


def quarantine_dir(base):
    return base / "maker_evidence_quarantine" / DAY / SEGMENT


def run(base, root, *extra, quarantine=None, env=None):
    quarantine = quarantine or base / "maker_evidence_quarantine"
    wrapper = base / "wrapper_l54.ps1"
    if not wrapper.exists():
        wrapper.write_text(WRAPPER, encoding="utf-8")
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
               str(wrapper), "-Root", str(root), "-QuarantineRoot", str(quarantine),
               "-LogPath", str(base / "alerts" / "torn.jsonl"), *extra]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("FAKE_")}
    environment.update({"FAKE_SCRIPT": str(SCRIPT), **(env or {})})
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, cwd=base, env=environment)
    payload = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
    assert payload is not None, (result.returncode, result.stdout, result.stderr)
    return result.returncode, payload


def task_env(result, offset_seconds=-3600, mode="value"):
    return {"FAKE_TASK_MODE": mode, "FAKE_TASK_RESULT": str(result), "FAKE_TASK_RUN_OFFSET": str(offset_seconds)}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(base):
    return {str(p.relative_to(base)): (sha(p) if p.is_file() else "dir") for p in sorted(base.rglob("*"))}


def log_rows(base):
    return [json.loads(line) for line in (base / "alerts" / "torn.jsonl").read_text(encoding="utf-8").splitlines()]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# 1 -----------------------------------------------------------------------------------------
def test_five_nul_tails_move_byte_exact_and_the_real_store_then_recovers(tmp_path):
    files = {f"reward-{i:024x}.jsonl": journal(2 + i) + b"\x00" * (512 * (i + 1) + i) for i in range(5)}
    good = {f"book-{i}.jsonl": journal(4 + i) for i in range(3)}
    root, folder = make_store(tmp_path, {**files, **good})
    before = {name: sha(folder / name) for name in files}
    with pytest.raises((UnicodeDecodeError, ValueError)):
        EvidenceStore(root)

    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "QUARANTINED")
    destination = quarantine_dir(tmp_path)
    assert sorted(p.name for p in destination.glob("*.jsonl")) == sorted(files)
    assert {name: sha(destination / name) for name in files} == before
    assert sorted(p.name for p in folder.glob("*.jsonl")) == sorted(good)
    receipt = read_json(destination / "QUARANTINE_RECEIPT.json")
    assert {row["name"]: (row["sha256_before"], row["sha256_after"], row["tail"]) for row in receipt["files"]} == {
        name: (before[name], before[name], "nul_tail") for name in files}
    assert receipt["writer_lock_held"] is True and receipt["sealed_before_receipt"] is False
    intent = read_json(destination / "QUARANTINE_INTENT.json")
    assert (intent["root"], intent["segment"], intent["destination"]) == (str(root), str(folder), str(destination))
    assert log_rows(tmp_path)[-1]["status"] == "QUARANTINED"
    assert payload["task_check"] is None  # only NOOP exits consult the task

    store = EvidenceStore(root, clock=CLOCK)
    store.seal()
    assert sorted(read_json(folder / "manifest.json")["files"]) == sorted(good)


# 2 -----------------------------------------------------------------------------------------
def test_partial_last_line_without_nul_is_moved(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_PARTIAL, "book-1.jsonl": journal()})
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "QUARANTINED")
    assert [c["tail"] for c in payload["candidates"]] == ["no_final_newline"]
    assert not (folder / "reward-a.jsonl").exists() and (folder / "book-1.jsonl").exists()


# 3 -----------------------------------------------------------------------------------------
def test_empty_journal_is_not_torn_and_stays(tmp_path):
    root, folder = make_store(tmp_path, {"reward-empty.jsonl": b"", "book-1.jsonl": journal()})
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "NOOP_NO_TORN_TAIL")
    assert (folder / "reward-empty.jsonl").exists()
    EvidenceStore(root, clock=CLOCK).seal()
    assert "reward-empty.jsonl" in read_json(folder / "manifest.json")["files"]


def test_crlf_journal_ends_in_newline_and_is_not_torn(tmp_path):
    root, folder = make_store(tmp_path, {"reward-crlf.jsonl": journal(3, newline=b"\r\n")})
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "NOOP_NO_TORN_TAIL")
    assert (folder / "reward-crlf.jsonl").exists()


def test_all_nul_files_are_torn_and_report_whether_the_tail_scan_was_capped(tmp_path):
    root, _ = make_store(tmp_path, {"reward-small.jsonl": b"\x00" * 4096,
                                    "reward-large.jsonl": b"\x00" * (1024 * 1024 + 512)})
    code, payload = run(tmp_path, root)
    assert (code, payload["status"]) == (0, "REPORT")
    rows = {c["name"]: c for c in payload["candidates"]}
    assert (rows["reward-small.jsonl"]["nul_tail_bytes"], rows["reward-small.jsonl"]["nul_tail_scan_capped"]) == (4096, False)
    assert (rows["reward-large.jsonl"]["nul_tail_bytes"], rows["reward-large.jsonl"]["nul_tail_scan_capped"]) == (1048576, True)


def test_dot_files_are_skipped_and_extension_matches_case_insensitively(tmp_path):
    root, folder = make_store(tmp_path, {".hidden.jsonl": TORN_NUL, "REWARD-UPPER.JSONL": TORN_NUL,
                                         "reward-a.jsonl.gz": TORN_NUL})
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "QUARANTINED")
    assert [c["name"] for c in payload["candidates"]] == ["REWARD-UPPER.JSONL"]
    assert (folder / ".hidden.jsonl").exists() and (folder / "reward-a.jsonl.gz").exists()


# 4 -----------------------------------------------------------------------------------------
def test_interior_nul_with_final_newline_is_unresolved_and_nothing_moves(tmp_path):
    interior = journal(2) + b"\x00" * 64 + b"\n" + journal(1)
    root, _ = make_store(tmp_path, {"reward-a.jsonl": interior, "reward-b.jsonl": TORN_NUL})
    snapshot = tree(tmp_path / "maker_evidence")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (5, "UNRESOLVED")
    assert payload["interior_nul_journals"] == ["reward-a.jsonl"]
    assert tree(tmp_path / "maker_evidence") == snapshot
    assert not (tmp_path / "maker_evidence_quarantine").exists()


# 5 -----------------------------------------------------------------------------------------
def test_eleven_torn_journals_exceed_the_cap_and_nothing_moves(tmp_path):
    root, _ = make_store(tmp_path, {f"reward-{i:02d}.jsonl": TORN_NUL for i in range(11)})
    snapshot = tree(tmp_path / "maker_evidence")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (2, "REFUSED_CAP")
    assert tree(tmp_path / "maker_evidence") == snapshot


def test_ten_torn_journals_are_at_the_cap_and_move(tmp_path):
    root, _ = make_store(tmp_path, {f"reward-{i:02d}.jsonl": TORN_NUL for i in range(10)})
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "QUARANTINED")
    assert len(payload["plan"]) == 10


# 6 -----------------------------------------------------------------------------------------
def test_two_unsealed_segments_refuse(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    (root / DAY / "09-0123456789ab").mkdir()
    snapshot = tree(tmp_path / "maker_evidence")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (2, "REFUSED_MULTIPLE_UNSEALED")
    assert tree(tmp_path / "maker_evidence") == snapshot


# 7 -----------------------------------------------------------------------------------------
def test_torn_file_in_a_sealed_segment_is_never_touched(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL}, sealed=True)
    snapshot = tree(tmp_path / "maker_evidence")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "NOOP_NO_UNSEALED_SEGMENT")
    assert tree(tmp_path / "maker_evidence") == snapshot


# 8 + live-writer requirement --------------------------------------------------------------
def hold_msvcrt_lock(root):
    code = ("import msvcrt,sys,time;h=open(sys.argv[1],'a+b');h.seek(0);"
            "msvcrt.locking(h.fileno(),msvcrt.LK_NBLCK,1);print('LOCKED',flush=True);sys.stdin.read()")
    child = subprocess.Popen([sys.executable, "-c", code, str(root / ".writer.lock")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "LOCKED"
    return child


def test_live_python_msvcrt_lock_holder_makes_the_tool_refuse(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    snapshot = tree(tmp_path / "maker_evidence")
    child = hold_msvcrt_lock(root)
    try:
        for extra in ((), ("-Apply",)):
            code, payload = run(tmp_path, root, *extra)
            assert (code, payload["status"]) == (3, "REFUSED_WRITER_ALIVE_TORN")
            assert payload["candidates"] == []
    finally:
        child.stdin.close()
        child.wait(timeout=30)
    assert tree(tmp_path / "maker_evidence") == snapshot
    code, payload = run(tmp_path, root)
    assert (code, payload["status"]) == (0, "REPORT")


def test_real_writer_lock_holder_makes_the_tool_refuse(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    code = ("import sys;from weather.market.maker_evidence_store import WriterLock;"
            "w=WriterLock(sys.argv[1]).__enter__();print('LOCKED',flush=True);sys.stdin.read()")
    child = subprocess.Popen([sys.executable, "-c", code, str(root)], cwd=ROOT,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        status = run(tmp_path, root, "-Apply")
        assert status[0] == 3 and status[1]["status"] == "REFUSED_WRITER_ALIVE_TORN"
    finally:
        child.stdin.close()
        child.wait(timeout=30)


def test_recorder_process_for_this_root_is_an_advisory_refusal(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    line = f'pythonw.exe -m weather.market.maker_evidence_capture --root "{root}" --extra-conditions "x.json"'
    code, payload = run(tmp_path, root, "-Apply", env={"FAKE_PROCESS_CMDLINE": line})
    assert (code, payload["status"]) == (3, "REFUSED_WRITER_ALIVE_TORN")
    assert "pid 4242" in payload["reasons"][-1]
    other = f'pythonw.exe -m weather.market.maker_evidence_capture --root "{tmp_path / "other"}"'
    code, payload = run(tmp_path, root, env={"FAKE_PROCESS_CMDLINE": other})
    assert (code, payload["status"]) == (0, "REPORT")
    code, payload = run(tmp_path, root, "-Apply", env={"FAKE_PROCESS_CMDLINE": "throw"})
    assert (code, payload["status"]) == (2, "REFUSED_PROCESS_CHECK_FAILED")


# Writer alive: read-only mirror of EvidenceStore._recover before the refusal (Stage 2 false-silence
# fix, master 2026-11-02 and 11-03). The boot task may call a writer-alive refusal benign only with
# torn_tail_found false; only the live writer's own segment may show a partial line, and only while
# it moves.
OLDER = "05-0123456789ab"


def alive(root):
    return {"FAKE_PROCESS_CMDLINE": f'pythonw.exe -m weather.market.maker_evidence_capture --root "{root}"'}


def stamps(base):
    return {str(p.relative_to(base)): p.stat().st_mtime_ns for p in sorted(base.rglob("*"))}


def add_segment(root, files, *, day=DAY, segment=OLDER, manifest=None):
    folder = root / day / segment
    folder.mkdir(parents=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    if manifest is not None:
        (folder / "manifest.json").write_bytes(manifest)
    return folder


def good_manifest():
    return encoded({"schema_version": EVIDENCE_SCHEMA, "files": {}, "stream_response_bytes": 0,
                    "stream_capped": False}) + b"\n"


def test_writer_alive_over_a_torn_segment_is_refused_torn_without_any_write(tmp_path):
    # Crash loop: the only (newest) segment's tail does not move during the settle wait.
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL, "book-1.jsonl": journal()})
    snapshot, times = tree(tmp_path / "maker_evidence"), stamps(tmp_path / "maker_evidence")
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"]) == (3, "REFUSED_WRITER_ALIVE_TORN")
    assert payload["torn_tail_found"] is True and payload["torn_tail_scan"] == "complete"
    assert payload["torn_journals"] == [str(folder / "reward-a.jsonl")]
    assert payload["unsealed_segments"] == [str(folder)] and payload["live_segment"] == str(folder)
    assert payload["candidates"] == []
    assert tree(tmp_path / "maker_evidence") == snapshot and stamps(tmp_path / "maker_evidence") == times
    assert not (tmp_path / "maker_evidence_quarantine").exists()
    assert log_rows(tmp_path)[-1]["status"] == "REFUSED_WRITER_ALIVE_TORN"


def test_writer_alive_over_an_older_torn_segment_beside_a_clean_live_one_is_torn(tmp_path):
    # Post-boot, not the newest: scanned like any other segment, no settle exemption.
    root, live = make_store(tmp_path, {"book-1.jsonl": journal()})
    older = add_segment(root, {"reward-a.jsonl": TORN_PARTIAL})
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"], payload["torn_tail_found"]) == (3, "REFUSED_WRITER_ALIVE_TORN", True)
    assert payload["torn_journals"] == [str(older / "reward-a.jsonl")]
    assert payload["live_segment"] == str(live)
    assert (older / "reward-a.jsonl").read_bytes() == TORN_PARTIAL


def test_held_writer_lock_over_a_torn_segment_is_refused_torn(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_PARTIAL})
    code = ("import sys;from weather.market.maker_evidence_store import WriterLock;"
            "w=WriterLock(sys.argv[1]).__enter__();print('LOCKED',flush=True);sys.stdin.read()")
    child = subprocess.Popen([sys.executable, "-c", code, str(root)], cwd=ROOT,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        status, payload = run(tmp_path, root, "-Apply")
        assert (status, payload["status"], payload["torn_tail_found"]) == (3, "REFUSED_WRITER_ALIVE_TORN", True)
        assert "writer lock is held" in payload["reasons"][0]
    finally:
        child.stdin.close()
        child.wait(timeout=30)
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_PARTIAL


def test_a_lock_open_failure_that_is_not_a_lock_violation_is_its_own_refusal(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    lock = root / ".writer.lock"
    os.chmod(lock, 0o444)  # read-only attribute: ReadWrite open is access denied, not a sharing violation
    try:
        code, payload = run(tmp_path, root, "-Apply")
    finally:
        os.chmod(lock, 0o666)
    assert (code, payload["status"]) == (2, "REFUSED_LOCK_UNAVAILABLE")
    assert "torn_tail_found" not in payload


def test_writer_alive_with_a_clean_store_proves_no_torn_tail(tmp_path):
    root, folder = make_store(tmp_path, {"book-1.jsonl": journal(), "reward-empty.jsonl": b""})
    sealed = add_segment(root, {"book-1.jsonl": journal()}, manifest=good_manifest())
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"]) == (2, "REFUSED_WRITER_ALIVE")
    assert payload["torn_tail_found"] is False and payload["torn_tail_scan"] == "complete"
    assert payload["unsealed_segments"] == [str(folder)] and payload["unsealed_segment_count"] == 1
    assert str(sealed) not in payload["unsealed_segments"]


def test_the_live_writers_moving_tail_is_in_flight_not_torn(tmp_path):
    # A writer thread appends records in two halves with a pause: the tail is partial most of the
    # time but always moves across the settle wait.
    import threading
    import time
    root, folder = make_store(tmp_path, {"reward-a.jsonl": journal()})
    path = folder / "reward-a.jsonl"
    stop = threading.Event()

    def writer():
        offset, index = path.stat().st_size, 100
        while not stop.is_set():
            line = encoded({"kind": "reward", "n": index, "offset": offset}) + b"\n"
            half = len(line) // 2
            with open(path, "ab") as handle:
                handle.write(line[:half])
            time.sleep(0.7)
            with open(path, "ab") as handle:
                handle.write(line[half:])
            time.sleep(0.02)
            offset, index = offset + len(line), index + 1

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    finally:
        stop.set()
        thread.join(timeout=10)
    assert (code, payload["status"], payload["torn_tail_found"]) == (2, "REFUSED_WRITER_ALIVE", False)
    assert payload["live_segment"] == str(folder)
    assert payload.get("torn_journals") is None


def test_writer_alive_scan_that_cannot_read_a_journal_is_unknown(tmp_path):
    import ctypes
    from ctypes import wintypes
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = kernel32.CreateFileW(str(folder / "reward-a.jsonl"), 0x80000000, 0, None, 3, 0x80, None)
    assert handle not in (None, wintypes.HANDLE(-1).value)
    try:
        code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    finally:
        kernel32.CloseHandle(handle)
    assert (code, payload["status"]) == (2, "REFUSED_WRITER_ALIVE")
    assert payload["torn_tail_found"] is None and payload["torn_tail_scan"].startswith("unknown: ")


def test_writer_alive_scan_reads_a_journal_the_writer_holds_open_for_append(tmp_path):
    # The scan opens shared: a recorder-style append handle does not block it and no byte changes.
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_PARTIAL})
    with open(folder / "reward-a.jsonl", "ab"):
        code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"], payload["torn_tail_found"]) == (3, "REFUSED_WRITER_ALIVE_TORN", True)
    assert payload["torn_tail_scan"] == "complete"
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_PARTIAL


def _line(row):
    return encoded(row) + b"\n"


UNVERIFIABLE = {
    "interior_nul": journal(2) + b"\x00" * 16 + b"\n" + journal(1),
    "offset_mismatch": journal(2) + _line({"kind": "reward", "n": 9, "offset": 7}),
    "float_offset": _line({"kind": "reward", "offset": 0.0}),
    "invalid_json": journal(1) + b'{"kind": reward}\n',
    "not_an_object": b"[1]\n",
    "bad_utf8": b'{"kind":"\xff","offset":0}\n',
    "duplicate_offset": b'{"offset":0,"offset":0}\n',
    "nan": b'{"offset":0,"x":NaN}\n',
    "stream_without_response_bytes": _line({"kind": "stream", "offset": 0}),
    "oversized": b'{"offset":0,"x":"' + b"a" * (16 * 1024 ** 2) + b'"}\n',
}


@pytest.mark.parametrize("case", sorted(UNVERIFIABLE))
def test_writer_alive_over_a_record_recovery_would_refuse_is_unknown_not_clean(tmp_path, case):
    body = UNVERIFIABLE[case]
    root, folder = make_store(tmp_path, {"reward-a.jsonl": body})
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"], payload["torn_tail_found"]) == (2, "REFUSED_WRITER_ALIVE", None)
    assert payload["torn_tail_scan"].startswith("unknown: " + str(folder / "reward-a.jsonl"))
    assert (folder / "reward-a.jsonl").read_bytes() == body


@pytest.mark.parametrize("manifest", [b"{}\n", b"not json\n",
                                      encoded({"schema_version": "maker_evidence_v1", "stream_response_bytes": 0,
                                               "stream_capped": False}) + b"\n"])
def test_writer_alive_over_a_sealed_manifest_recovery_would_refuse_is_unknown(tmp_path, manifest):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    add_segment(root, {"book-1.jsonl": journal()}, manifest=manifest)
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"], payload["torn_tail_found"]) == (2, "REFUSED_WRITER_ALIVE", None)
    assert "manifest.json" in payload["torn_tail_scan"]


def test_a_sealed_gzip_manifest_is_verified(tmp_path):
    import gzip
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    folder = add_segment(root, {})
    (folder / "manifest.json.gz").write_bytes(gzip.compress(good_manifest()))
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["torn_tail_found"]) == (2, False)


def test_writer_alive_torn_tail_stays_torn_when_another_journal_is_unreadable(tmp_path):
    import ctypes
    from ctypes import wintypes
    root, folder = make_store(tmp_path, {"book-1.jsonl": journal(), "reward-a.jsonl": TORN_NUL})
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = kernel32.CreateFileW(str(folder / "book-1.jsonl"), 0x80000000, 0, None, 3, 0x80, None)
    assert handle not in (None, wintypes.HANDLE(-1).value)
    try:
        code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    finally:
        kernel32.CloseHandle(handle)
    assert (code, payload["status"], payload["torn_tail_found"]) == (3, "REFUSED_WRITER_ALIVE_TORN", True)
    assert payload["torn_tail_scan"].startswith("partial: ")
    assert payload["torn_journals"] == [str(folder / "reward-a.jsonl")]
    assert payload["torn_tail_scan_problem_count"] == 1


def test_writer_alive_scan_stops_at_64_unsealed_segments_and_is_unknown(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    for index in range(64):
        add_segment(root, {"book-1.jsonl": journal()}, day="2026-11-01", segment=f"03-{index:012x}")
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"], payload["torn_tail_found"]) == (2, "REFUSED_WRITER_ALIVE", None)
    assert "only the first 64 scanned" in payload["torn_tail_scan"]
    assert payload["unsealed_segment_count"] == 64 and len(payload["unsealed_segments"]) == 20


def test_writer_alive_output_lists_are_capped_at_20_with_counts(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    for index in range(25):
        add_segment(root, {"reward-a.jsonl": TORN_PARTIAL}, day="2026-11-01", segment=f"03-{index:012x}")
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert (code, payload["status"]) == (3, "REFUSED_WRITER_ALIVE_TORN")
    assert payload["torn_journal_count"] == 25 and len(payload["torn_journals"]) == 20
    assert payload["unsealed_segment_count"] == 26 and len(payload["unsealed_segments"]) == 20


def test_writer_alive_scan_reports_a_junctioned_segment_as_a_problem(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    target = tmp_path / "elsewhere"
    target.mkdir()
    (root / "2026-11-01").mkdir()
    link = root / "2026-11-01" / OLDER
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    assert made.returncode == 0, made.stdout + made.stderr
    try:
        code, payload = run(tmp_path, root, "-Apply", env=alive(root))
        assert (code, payload["status"], payload["torn_tail_found"]) == (2, "REFUSED_WRITER_ALIVE", None)
        assert payload["torn_tail_scan"] == "unknown: folder is a reparse point: " + str(link)
        # A torn tail elsewhere still wins over the problem.
        add_segment(root, {"reward-a.jsonl": TORN_PARTIAL}, day="2026-11-01", segment="02-0123456789ab")
        code, payload = run(tmp_path, root, "-Apply", env=alive(root))
        assert (code, payload["torn_tail_found"]) == (3, True)
        assert payload["torn_tail_scan"].startswith("partial: folder is a reparse point")
    finally:
        os.rmdir(link)


def test_the_store_scan_constants_match_the_store():
    from weather.market import maker_evidence_store as store
    text = SCRIPT.read_text(encoding="utf-8")
    assert f'public const string Schema = "{store.SCHEMA}";' in text
    assert f"public const long MaxRawBytes = {store.MAX_RAW_BYTES};" in text
    assert "public const int MaxLineBytes = 16 * 1024 * 1024;" in text and store.MAX_LINE_BYTES == 16 * 1024 ** 2
    assert "public const int MaxPaths = 20000;" in text


@pytest.mark.parametrize(("files", "expected_stage1", "expected_boot"), [
    ({"book-1.jsonl": journal()}, 2, 0),
    ({"reward-a.jsonl": TORN_PARTIAL}, 3, 3),
    ({"reward-a.jsonl": UNVERIFIABLE["offset_mismatch"]}, 2, 2),
])
def test_real_stage1_writer_alive_output_drives_the_boot_wrapper(tmp_path, files, expected_stage1, expected_boot):
    # Behavioural: what Stage 1 really emits for alive+clean / alive+torn / alive+unknown, fed to the
    # boot wrapper, gives 0 / non-zero / non-zero.
    root, _ = make_store(tmp_path, files)
    code, payload = run(tmp_path, root, "-Apply", env=alive(root))
    assert code == expected_stage1
    ops = tmp_path / "repo" / "scripts" / "ops"
    ops.mkdir(parents=True)
    shutil.copyfile(SCRIPT.parent / "maker_evidence_torn_quarantine_boot.ps1",
                    ops / "maker_evidence_torn_quarantine_boot.ps1")
    (ops / SCRIPT.name).write_text("param([switch]$Apply)\n$env:FAKE_STAGE1_OUTPUT\nexit ([int]$env:FAKE_STAGE1_CODE)\n",
                                   encoding="utf-8")
    env = {**os.environ, "FAKE_STAGE1_OUTPUT": json.dumps(payload, indent=1), "FAKE_STAGE1_CODE": str(code)}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(ops / "maker_evidence_torn_quarantine_boot.ps1")],
                            capture_output=True, text=True, env=env, timeout=120, check=False)
    assert result.returncode == expected_boot, result.stdout + result.stderr


# 9 -----------------------------------------------------------------------------------------
def test_the_store_cannot_take_the_writer_lock_while_the_script_holds_it(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    probe = tmp_path / "lock_probe_l54.py"
    probe.write_text(
        "import sys\n"
        f"sys.path[:0] = [{str(ROOT)!r}]\n"
        "from weather.market.maker_evidence_store import WriterLock\n"
        "try:\n"
        "    with WriterLock(sys.argv[1]):\n"
        "        print('ACQUIRED')\n"
        "except RuntimeError as exc:\n"
        "    print('REFUSED', exc)\n", encoding="utf-8")
    out = tmp_path / "probe_out.txt"
    env = {**task_env(0), "FAKE_TASK_PROBE_SCRIPT": str(probe), "FAKE_TASK_PROBE_OUT": str(out),
           "FAKE_PYTHON": sys.executable, "FAKE_LOCK_ROOT": str(root)}
    code, payload = run(tmp_path, root, "-TaskName", "WeatherMakerEvidenceCapture", env=env)
    assert (code, payload["status"]) == (0, "NOOP_NO_TORN_TAIL")
    assert out.read_text(encoding="utf-8").strip() == "REFUSED maker evidence already has a writer"
    with WriterLock(root):
        pass


# 10 + 12 ----------------------------------------------------------------------------------
def test_interrupted_apply_reconciles_to_one_receipt_and_is_idempotent(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL, "reward-b.jsonl": TORN_PARTIAL})
    before = {name: sha(folder / name) for name in ("reward-a.jsonl", "reward-b.jsonl")}
    destination = quarantine_dir(tmp_path)
    blocker = open(folder / "reward-b.jsonl", "rb")  # CRT share mode omits FILE_SHARE_DELETE
    try:
        code, payload = run(tmp_path, root, "-Apply")
    finally:
        blocker.close()
    assert (code, payload["status"]) == (4, "FAILED_MOVE")
    assert (destination / "reward-a.jsonl").exists() and (folder / "reward-b.jsonl").exists()
    assert (destination / "QUARANTINE_INTENT.json").exists()
    assert not (destination / "QUARANTINE_RECEIPT.json").exists()
    assert sha(folder / "reward-b.jsonl") == before["reward-b.jsonl"]

    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"], payload["mode"]) == (0, "RECONCILED", "reconcile")
    receipt = read_json(destination / "QUARANTINE_RECEIPT.json")
    assert {row["name"]: row["sha256_after"] for row in receipt["files"]} == before
    receipt_bytes = (destination / "QUARANTINE_RECEIPT.json").read_bytes()

    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "NOOP_ALREADY_QUARANTINED")
    assert (destination / "QUARANTINE_RECEIPT.json").read_bytes() == receipt_bytes
    assert sorted(p.name for p in destination.glob("*.jsonl")) == sorted(before)


def test_move_blocked_by_a_reader_fails_cleanly_and_retries(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    original = (folder / "reward-a.jsonl").read_bytes()
    blocker = open(folder / "reward-a.jsonl", "rb")
    try:
        code, payload = run(tmp_path, root, "-Apply")
    finally:
        blocker.close()
    assert (code, payload["status"]) == (4, "FAILED_MOVE")
    assert (folder / "reward-a.jsonl").read_bytes() == original
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "RECONCILED")


# Receipt failure: all files already at the destination, and the store sealing before a rerun ----
def fail_receipt_once(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL, "book-1.jsonl": journal()})
    before = sha(folder / "reward-a.jsonl")
    destination = quarantine_dir(tmp_path)
    (destination / "QUARANTINE_RECEIPT.json.tmp").mkdir(parents=True)  # makes the receipt write fail
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (4, "FAILED_RECEIPT")
    assert (destination / "reward-a.jsonl").exists() and not (folder / "reward-a.jsonl").exists()
    assert (destination / "QUARANTINE_INTENT.json").exists()
    assert not (destination / "QUARANTINE_RECEIPT.json").exists()
    return root, folder, destination, before


def test_failed_receipt_then_rerun_reconciles_with_every_file_already_at_the_destination(tmp_path):
    root, _, destination, before = fail_receipt_once(tmp_path)
    (destination / "QUARANTINE_RECEIPT.json.tmp").rmdir()
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"], payload["mode"]) == (0, "RECONCILED", "reconcile")
    assert read_json(destination / "QUARANTINE_RECEIPT.json")["files"][0]["sha256_after"] == before


def test_store_sealing_before_the_receipt_rerun_reconciles_after_seal(tmp_path):
    root, folder, destination, before = fail_receipt_once(tmp_path)
    EvidenceStore(root, clock=CLOCK).seal()  # the PT5M trigger recovers the rest and seals
    assert (folder / "manifest.json").exists()
    (destination / "QUARANTINE_RECEIPT.json.tmp").rmdir()
    code, payload = run(tmp_path, root)
    assert (code, payload["status"]) == (0, "REPORT_AFTER_SEAL")
    assert not (destination / "QUARANTINE_RECEIPT.json").exists()
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "RECONCILED_AFTER_SEAL")
    receipt = read_json(destination / "QUARANTINE_RECEIPT.json")
    assert (receipt["mode"], receipt["sealed_before_receipt"]) == ("after_seal", True)
    assert receipt["files"][0]["sha256_after"] == before
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "NOOP_NO_UNSEALED_SEGMENT")


# Hash mismatch across the move (stubbed post-move hash) ------------------------------------
def test_hash_mismatch_after_move_fails_and_a_rerun_is_unresolved(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    env = {"FAKE_HASH_BAD_PREFIX": str(tmp_path / "maker_evidence_quarantine")}
    code, payload = run(tmp_path, root, "-Apply", env=env)
    assert (code, payload["status"]) == (4, "FAILED_HASH_MISMATCH")
    assert not (quarantine_dir(tmp_path) / "QUARANTINE_RECEIPT.json").exists()
    code, payload = run(tmp_path, root, "-Apply", env=env)
    assert (code, payload["status"]) == (5, "UNRESOLVED")
    assert (quarantine_dir(tmp_path) / "reward-a.jsonl").read_bytes() == TORN_NUL


def test_null_hash_after_move_is_failed_hash_read_and_a_rerun_reconciles(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    destination = quarantine_dir(tmp_path)
    code, payload = run(tmp_path, root, "-Apply", env={"FAKE_HASH_NULL_PREFIX": str(destination)})
    assert (code, payload["status"]) == (4, "FAILED_HASH_READ")
    assert payload["reasons"][-1].endswith("intent kept, rerun reconciles")
    assert (destination / "QUARANTINE_INTENT.json").exists()
    assert not (destination / "QUARANTINE_RECEIPT.json").exists()
    assert (destination / "reward-a.jsonl").read_bytes() == TORN_NUL
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "RECONCILED")


def test_null_hash_while_planning_is_failed_hash_read_and_nothing_moves(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    code, payload = run(tmp_path, root, "-Apply", env={"FAKE_HASH_NULL_PREFIX": str(folder)})
    assert (code, payload["status"]) == (4, "FAILED_HASH_READ")
    assert payload["reasons"][-1].endswith("nothing moved; no intent")
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_NUL
    assert not (tmp_path / "maker_evidence_quarantine").exists()


# Intent validation -------------------------------------------------------------------------
def write_intent(base, store_root, folder, files, **override):
    destination = quarantine_dir(base)
    destination.mkdir(parents=True, exist_ok=True)
    intent = {"root": str(store_root), "segment": str(folder), "destination": str(destination), "files": files,
              **override}
    (destination / "QUARANTINE_INTENT.json").write_text(json.dumps(intent), encoding="utf-8")


def entry(name, digest):
    return {"name": name, "size": 1, "sha256_before": digest, "tail": "nul_tail"}


def test_intent_whose_hash_disagrees_with_the_source_is_unresolved(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    write_intent(tmp_path, root, folder, [entry("reward-a.jsonl", "0" * 64)])
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (5, "UNRESOLVED")
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_NUL


@pytest.mark.parametrize("override, files", [
    ({"segment": "C:\\elsewhere\\2026-11-02\\08-000000000000"}, None),
    ({"root": "C:\\elsewhere"}, None),
    ({"destination": "C:\\elsewhere\\q"}, None),
    ({}, [entry("..\\reward-a.jsonl", "a" * 64)]),
    ({}, [entry("sub\\reward-a.jsonl", "a" * 64)]),
    ({}, [entry("C:reward-a.jsonl", "a" * 64)]),
    ({}, [entry("reward-a.txt", "a" * 64)]),
    ({}, [entry("reward-a.jsonl", "not-a-hash")]),
    ({}, [{**entry("reward-a.jsonl", "a" * 64), "size": -1}]),
    ({}, [{**entry("reward-a.jsonl", "a" * 64), "size": "12"}]),
    ({}, [{**entry("reward-a.jsonl", "a" * 64), "size": 1.5}]),
    ({}, [{**entry("reward-a.jsonl", "a" * 64), "tail": "bogus"}]),
], ids=["other-segment", "other-root", "other-destination", "dotdot", "separator", "drive", "extension", "hash",
        "negative-size", "string-size", "fractional-size", "tail"])
def test_malformed_or_foreign_intent_refuses(tmp_path, override, files):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    write_intent(tmp_path, root, folder, files or [entry("reward-a.jsonl", sha(folder / "reward-a.jsonl"))], **override)
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (2, "REFUSED_INTENT_INVALID")
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_NUL


def test_intent_without_receipt_whose_source_segment_is_gone_is_unresolved(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()}, sealed=True)
    gone = quarantine_dir(tmp_path).parent / "07-0123456789ab"
    gone.mkdir(parents=True)
    (gone / "QUARANTINE_INTENT.json").write_text(json.dumps({"root": str(root), "files": []}), encoding="utf-8")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (5, "UNRESOLVED")
    assert "source segment is gone" in payload["reasons"][-1]


# 11 + receipt guards ----------------------------------------------------------------------
def test_existing_destination_with_other_bytes_refuses_and_source_is_untouched(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    destination = quarantine_dir(tmp_path)
    destination.mkdir(parents=True)
    (destination / "reward-a.jsonl").write_bytes(b"other\n")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (2, "REFUSED_DESTINATION_EXISTS")
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_NUL
    assert (destination / "reward-a.jsonl").read_bytes() == b"other\n"


def test_receipt_time_without_offset_is_read_as_utc(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    destination = quarantine_dir(tmp_path)
    destination.mkdir(parents=True)
    # Offset-free receipt 30 s before the fake task run. Only a UTC read makes the run newer; on a host
    # behind UTC a local read would push the receipt hours later and wrongly report "predates".
    from datetime import timedelta
    receipt = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S")
    (destination / "QUARANTINE_RECEIPT.json").write_text(json.dumps({"completed_at_utc": receipt}), encoding="utf-8")
    code, payload = run(tmp_path, root, "-TaskName", "T", env=task_env(1, offset_seconds=60))
    assert (code, payload["status"], payload["noop_status"]) == (5, "TORN_SIGNATURE_UNRESOLVED", "NOOP_ALREADY_QUARANTINED")


def test_receipt_exists_but_torn_journals_remain_refuses(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    destination = quarantine_dir(tmp_path)
    destination.mkdir(parents=True)
    (destination / "QUARANTINE_RECEIPT.json").write_text(json.dumps({"completed_at_utc": "2026-11-02T10:00:00+00:00"}),
                                                         encoding="utf-8")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (2, "REFUSED_RECEIPT_EXISTS")
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_NUL


# Task-result check on every NOOP (review MAJOR) -------------------------------------------
def test_torn_manifest_noop_with_failing_task_is_torn_signature_unresolved(tmp_path):
    root, folder = make_store(tmp_path, {"book-1.jsonl": journal()}, sealed=True)
    (folder / "manifest.json").write_bytes(b"\x00" * 512)
    code, payload = run(tmp_path, root, "-Apply", "-TaskName", "WeatherMakerEvidenceCapture", env=task_env(1))
    assert (code, payload["status"], payload["noop_status"]) == (5, "TORN_SIGNATURE_UNRESOLVED", "NOOP_NO_UNSEALED_SEGMENT")
    assert payload["task_last_result"] == 1
    code, payload = run(tmp_path, root, "-TaskName", "WeatherMakerEvidenceCapture", env=task_env(0))
    assert (code, payload["status"], payload["task_check"]) == (0, "NOOP_NO_UNSEALED_SEGMENT", "last result 0")


def test_no_torn_tail_with_failing_task_is_torn_signature_unresolved(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    code, payload = run(tmp_path, root, "-TaskName", "WeatherMakerEvidenceCapture", env=task_env(1))
    assert (code, payload["status"], payload["noop_status"]) == (5, "TORN_SIGNATURE_UNRESOLVED", "NOOP_NO_TORN_TAIL")


def test_already_quarantined_is_unresolved_only_when_the_task_failed_after_the_receipt(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    assert run(tmp_path, root, "-Apply")[1]["status"] == "QUARANTINED"
    # The task's failure predates the receipt: the operator has not started it yet.
    code, payload = run(tmp_path, root, "-TaskName", "T", env=task_env(1, offset_seconds=-3600))
    assert (code, payload["status"]) == (0, "NOOP_ALREADY_QUARANTINED")
    assert payload["task_check"].startswith("last result 1 predates")
    # The task ran after the quarantine and still failed: non-NUL corruption remains.
    code, payload = run(tmp_path, root, "-TaskName", "T", env=task_env(1, offset_seconds=60))
    assert (code, payload["status"], payload["noop_status"]) == (5, "TORN_SIGNATURE_UNRESOLVED", "NOOP_ALREADY_QUARANTINED")


def test_family_root_skips_the_task_check_unless_a_task_name_is_given(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    code, payload = run(tmp_path, root, env=task_env(1))
    assert (code, payload["status"], payload["task_check"]) == (0, "NOOP_NO_TORN_TAIL", "skipped: no -TaskName")
    code, payload = run(tmp_path, root, "-TaskName", "WeatherMakerEvidenceLowestTemperature", env=task_env(1))
    assert (code, payload["status"]) == (5, "TORN_SIGNATURE_UNRESOLVED")
    code, payload = run(tmp_path, root, "-TaskName", "Missing", env=task_env(1, mode="missing"))
    assert (code, payload["status"], payload["task_check"]) == (0, "NOOP_NO_TORN_TAIL", "task not found")


# Internal error contract (review minor 1) -------------------------------------------------
def test_unexpected_error_releases_the_lock_logs_and_exits_six_in_session(tmp_path):
    root, _ = make_store(tmp_path, {"book-1.jsonl": journal()})
    env = {**task_env(0, mode="garbage"), "FAKE_RELOCK": str(root / ".writer.lock")}
    code, payload = run(tmp_path, root, "-Apply", "-TaskName", "T", env=env)
    assert (code, payload["status"]) == (6, "INTERNAL_ERROR")
    assert log_rows(tmp_path)[-1]["status"] == "INTERNAL_ERROR"
    assert (root / ".writer.lock.probe").read_text() == "RELOCK_OK"


# 13 ----------------------------------------------------------------------------------------
def test_report_only_writes_nothing(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL, "book-1.jsonl": journal()})
    (tmp_path / "wrapper_l54.ps1").write_text(WRAPPER, encoding="utf-8")
    snapshot = tree(tmp_path)
    code, payload = run(tmp_path, root)
    assert (code, payload["status"], payload["applied"]) == (0, "REPORT", False)
    assert [e["name"] for e in payload["plan"]] == ["reward-a.jsonl"]
    assert payload["plan"][0]["sha256_before"] == sha(folder / "reward-a.jsonl")
    assert tree(tmp_path) == snapshot


# Input guards ------------------------------------------------------------------------------
def test_explicit_root_requires_an_explicit_quarantine_root(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(SCRIPT), "-Root", str(root), "-LogPath", str(tmp_path / "l.jsonl")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 2 and json.loads(result.stdout)["status"] == "REFUSED_NO_QUARANTINE_ROOT"


def test_quarantine_inside_the_store_root_refuses(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    code, payload = run(tmp_path, root, "-Apply", quarantine=root / "quarantine")
    assert (code, payload["status"]) == (2, "REFUSED_QUARANTINE_OVERLAPS_ROOT")


def test_quarantine_on_another_volume_refuses(tmp_path):
    """Exercises the path-root refusal only (a free drive letter); a same-root serial mismatch needs a mount."""
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    free = next(letter for letter in reversed(string.ascii_uppercase[3:]) if not os.path.exists(f"{letter}:\\"))
    code, payload = run(tmp_path, root, "-Apply", quarantine=Path(f"{free}:\\maker_evidence_quarantine"))
    assert (code, payload["status"]) == (2, "REFUSED_CROSS_VOLUME")
    assert (root / DAY / SEGMENT / "reward-a.jsonl").read_bytes() == TORN_NUL


def test_junctioned_day_folder_refuses(tmp_path):
    root = tmp_path / "maker_evidence"
    root.mkdir()
    (root / ".writer.lock").write_bytes(b"0")
    target = tmp_path / "elsewhere" / DAY
    (target / SEGMENT).mkdir(parents=True)
    (target / SEGMENT / "reward-a.jsonl").write_bytes(TORN_NUL)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / DAY), str(target)], capture_output=True, text=True)
    assert made.returncode == 0, made.stderr
    try:
        code, payload = run(tmp_path, root, "-Apply")
        assert (code, payload["status"]) == (2, "REFUSED_REPARSE_POINT")
        assert (target / SEGMENT / "reward-a.jsonl").read_bytes() == TORN_NUL
    finally:
        os.rmdir(root / DAY)


def test_missing_lock_file_is_a_noop(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    (root / ".writer.lock").unlink()
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "NOOP_NO_LOCK_FILE")


# 14 ----------------------------------------------------------------------------------------
def test_script_is_roll_free_and_has_no_rewrite_delete_or_scheduler_mutation():
    source = r"""
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:TARGET, [ref]$tokens, [ref]$errors)
$names = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) |
    ForEach-Object { $_.GetCommandName() } | Where-Object { $_ } | Sort-Object -Unique)
@{ errors = @($errors | ForEach-Object { $_.Message }); commands = $names } | ConvertTo-Json -Compress
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", source],
                            env={**os.environ, "TARGET": str(SCRIPT)}, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    helpers = {"Get-ShaChecked", "Release-Lock", "Write-Log", "Emit-And-Exit", "Test-TaskSignature", "Finish", "Get-Sha256",
               "Open-Shared", "Get-TailClass", "Test-ContainsNul", "Test-Reparse", "Test-ReparseChain",
               "Get-VolumeIdentity", "Write-AtomicNew", "Read-JsonFile", "Test-JournalName", "Get-IntentProblem",
               "Get-StoreScanType", "Get-Capped", "Finish-WriterAlive"}
    cmdlets = {"Split-Path", "Join-Path", "Get-FileHash", "Test-Path", "New-Item", "ConvertTo-Json", "Out-Null",
               "Get-CimInstance", "Where-Object", "ForEach-Object", "Get-Item", "Get-ChildItem", "Get-Content",
               "ConvertFrom-Json", "Get-ScheduledTaskInfo", "Get-Date", "New-Object", "Add-Type"}
    assert set(payload["commands"]) <= helpers | cmdlets, set(payload["commands"]) - helpers - cmdlets
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("SetLength", "Truncate", "WriteAllBytes", "Remove-Item", "Copy-Item", "Move-Item",
                      "Delete(", "Start-ScheduledTask", "Register-ScheduledTask", "Set-Content", "Out-File",
                      "-m weather", "import "):
        assert forbidden not in text, forbidden
    assert text.count("[IO.File]::Move(") == 2  # journal rename and tmp->final for new JSON files only
