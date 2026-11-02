"""Torn maker-evidence journal quarantine (Stage 1 operator tool).

Guards: 2026-11-02 power-loss incident (maker-evidence recorder down 03:36-09:38 on NUL-tailed
reward journals) and the approved L54 auto-recovery design: classify only under the writer lock,
one unsealed segment, only non-empty *.jsonl without a final newline, hard cap 10, byte-exact
same-volume rename with intent and receipt, idempotent reconcile, never truncate or rewrite.
Runbook: docs/operations/passive-maker-evidence-capture.md "Torn journal after power loss".

Every case runs the real script with ``powershell.exe -File`` against a synthetic store under
pytest's tmp_path; the real data root is never named (explicit -Root/-QuarantineRoot/-LogPath).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from weather.market.maker_evidence_store import EvidenceStore, WriterLock, encoded

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "maker_evidence_torn_quarantine.ps1"
DAY, SEGMENT = "2026-11-02", "08-b7021b84b0cf"

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt" or shutil.which("powershell.exe") is None,
                       reason="Windows PowerShell 5.1 and msvcrt locking required"),
]


def journal(records=3):
    raw, offset = b"", 0
    for index in range(records):
        line = encoded({"kind": "reward", "n": index, "offset": offset}) + b"\n"
        raw += line
        offset += len(line)
    return raw


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


def run(base, root, *extra, quarantine=None):
    quarantine = quarantine or base / "maker_evidence_quarantine"
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
               str(SCRIPT), "-Root", str(root), "-QuarantineRoot", str(quarantine),
               "-LogPath", str(base / "alerts" / "torn.jsonl"), *extra]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, cwd=base)
    payload = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
    assert payload is not None, (result.returncode, result.stdout, result.stderr)
    return result.returncode, payload


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(base):
    return {str(p.relative_to(base)): (sha(p) if p.is_file() else "dir") for p in sorted(base.rglob("*"))}


TORN_NUL = journal() + b"\x00" * 4096
TORN_PARTIAL = journal() + b'{"kind":"reward","n":3,"off'


# 1 -----------------------------------------------------------------------------------------
def test_five_nul_tails_move_byte_exact_and_the_real_store_then_recovers(tmp_path):
    files = {f"reward-{i:024x}.jsonl": journal(2 + i) + b"\x00" * (512 * (i + 1)) + b"\x00" * i
             for i in range(5)}
    good = {f"book-{i}.jsonl": journal(4 + i) for i in range(3)}
    root, folder = make_store(tmp_path, {**files, **good})
    before = {name: sha(folder / name) for name in files}
    with pytest.raises((UnicodeDecodeError, ValueError)):
        EvidenceStore(root)

    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (0, "QUARANTINED")
    destination = tmp_path / "maker_evidence_quarantine" / DAY / SEGMENT
    assert sorted(p.name for p in destination.glob("*.jsonl")) == sorted(files)
    assert {name: sha(destination / name) for name in files} == before
    assert sorted(p.name for p in folder.glob("*.jsonl")) == sorted(good)
    receipt = json.loads((destination / "QUARANTINE_RECEIPT.json").read_text(encoding="utf-8-sig"))
    assert {row["name"]: (row["sha256_before"], row["sha256_after"], row["tail"]) for row in receipt["files"]} == {
        name: (before[name], before[name], "nul_tail") for name in files}
    assert receipt["writer_lock_held"] is True
    assert (destination / "QUARANTINE_INTENT.json").is_file()
    log = (tmp_path / "alerts" / "torn.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["status"] == "QUARANTINED"

    clock = lambda: datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
    store = EvidenceStore(root, clock=clock)
    store.seal()
    manifest = json.loads((folder / "manifest.json").read_bytes())
    assert sorted(manifest["files"]) == sorted(good)


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
    EvidenceStore(root, clock=lambda: datetime(2026, 11, 2, 14, tzinfo=timezone.utc)).seal()
    assert "reward-empty.jsonl" in json.loads((folder / "manifest.json").read_bytes())["files"]


# 4 -----------------------------------------------------------------------------------------
def test_interior_nul_with_final_newline_is_unresolved_and_nothing_moves(tmp_path):
    interior = journal(2) + b"\x00" * 64 + b"\n" + journal(1)
    root, folder = make_store(tmp_path, {"reward-a.jsonl": interior, "reward-b.jsonl": TORN_NUL})
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
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL}, sealed=True)
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
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    snapshot = tree(tmp_path / "maker_evidence")
    child = hold_msvcrt_lock(root)
    try:
        for extra in ((), ("-Apply",)):
            code, payload = run(tmp_path, root, *extra)
            assert (code, payload["status"]) == (2, "REFUSED_WRITER_ALIVE")
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
        assert status[0] == 2 and status[1]["status"] == "REFUSED_WRITER_ALIVE"
    finally:
        child.stdin.close()
        child.wait(timeout=30)


# 9 -----------------------------------------------------------------------------------------
def test_store_cannot_take_the_writer_lock_while_the_tool_style_lock_is_held(tmp_path):
    root, _ = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    hold = ("$s = New-Object IO.FileStream($env:LOCK_PATH, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite,"
            " ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)); $s.Lock(0, 1);"
            " [Console]::Out.WriteLine('LOCKED'); [Console]::Out.Flush(); [void][Console]::In.ReadLine(); $s.Dispose()")
    child = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", hold],
                             env={**os.environ, "LOCK_PATH": str(root / ".writer.lock")},
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(RuntimeError, match="already has a writer"):
            with WriterLock(root):
                pass
    finally:
        child.stdin.write("\n")
        child.stdin.close()
        child.wait(timeout=30)
    with WriterLock(root):
        pass


# 10 + 12 ----------------------------------------------------------------------------------
def test_interrupted_apply_reconciles_to_one_receipt_and_is_idempotent(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL, "reward-b.jsonl": TORN_PARTIAL})
    before = {name: sha(folder / name) for name in ("reward-a.jsonl", "reward-b.jsonl")}
    destination = tmp_path / "maker_evidence_quarantine" / DAY / SEGMENT
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
    receipt = json.loads((destination / "QUARANTINE_RECEIPT.json").read_text(encoding="utf-8-sig"))
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


def test_intent_that_disagrees_with_disk_refuses(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    destination = tmp_path / "maker_evidence_quarantine" / DAY / SEGMENT
    destination.mkdir(parents=True)
    (destination / "QUARANTINE_INTENT.json").write_text(json.dumps({
        "segment": str(folder), "files": [{"name": "reward-a.jsonl", "size": 1, "sha256_before": "0" * 64,
                                           "tail": "nul_tail"}]}), encoding="utf-8")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (2, "REFUSED_RECONCILE_MISMATCH")
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_NUL


# 11 ----------------------------------------------------------------------------------------
def test_existing_destination_with_other_bytes_refuses_and_source_is_untouched(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL})
    destination = tmp_path / "maker_evidence_quarantine" / DAY / SEGMENT
    destination.mkdir(parents=True)
    (destination / "reward-a.jsonl").write_bytes(b"other\n")
    code, payload = run(tmp_path, root, "-Apply")
    assert (code, payload["status"]) == (2, "REFUSED_DESTINATION_EXISTS")
    assert (folder / "reward-a.jsonl").read_bytes() == TORN_NUL
    assert (destination / "reward-a.jsonl").read_bytes() == b"other\n"


# 13 ----------------------------------------------------------------------------------------
def test_report_only_writes_nothing(tmp_path):
    root, folder = make_store(tmp_path, {"reward-a.jsonl": TORN_NUL, "book-1.jsonl": journal()})
    snapshot = tree(tmp_path)
    code, payload = run(tmp_path, root)
    assert (code, payload["status"], payload["applied"]) == (0, "REPORT", False)
    assert [entry["name"] for entry in payload["plan"]] == ["reward-a.jsonl"]
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
    allowed = {"Split-Path", "Join-Path", "Get-FileHash", "Test-Path", "New-Item", "ConvertTo-Json", "Finish",
               "Get-CimInstance", "Where-Object", "ForEach-Object", "Get-Item", "Get-ChildItem", "Get-Content",
               "ConvertFrom-Json", "Get-ScheduledTaskInfo", "Get-Date", "New-Object", "Out-Null", "Write-Log", "Open-Shared",
               "Get-Sha256", "Get-TailClass", "Test-ContainsNul", "Test-ReparseChain", "Write-AtomicNew"}
    assert set(payload["commands"]) <= allowed, set(payload["commands"]) - allowed
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("SetLength", "Truncate", "WriteAllBytes", "Remove-Item", "Copy-Item", "Move-Item",
                      "Delete(", "Start-ScheduledTask", "Register-ScheduledTask", "Set-Content", "Out-File",
                      "-m weather", "import "):
        assert forbidden not in text, forbidden
    assert text.count("[IO.File]::Move(") == 2  # journal rename and tmp->final for new JSON files only
