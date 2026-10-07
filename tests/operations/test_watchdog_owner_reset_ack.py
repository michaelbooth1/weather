"""Owner reset acknowledgement for the G1 UNEXPECTED SHUTDOWN flag (owner 2026-10-07).

Windows cannot tell the owner's manual reset from a crash, so an owner marker written by
``scripts/ops/owner_reset_note.ps1`` only annotates the flag. It never suppresses it, never
changes its class or severity, and never changes the watchdog dedup fingerprint. A malformed
ledger fails closed. Fixtures only; never the live host.

Guards: owner 2026-10-07 owner-reset acknowledgement (annotate, never suppress) on PR #255 G1;
docs/ops/streak-soak.md#owner-reset-acknowledgement.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
WATCHDOG = OPS / "health_watchdog.ps1"
STATUS = OPS / "status.ps1"
NOTE = OPS / "owner_reset_note.ps1"
pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell contract"),
    pytest.mark.spawns,
]

STATUS_FIXTURE = (
    "param([string]$RepoRoot, [switch]$Json, [string]$ExpectedSelfSha256)\n"
    "$flags = @((Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'flags.json') | ConvertFrom-Json) |"
    " ForEach-Object { [string]$_ })\n"
    "@{verdict='ATTENTION'; flags=$flags; warns=@(); streak=@{days=2;target=14;today='fixture'};"
    " host_stability=@{unclean_boots_7d=1}} | ConvertTo-Json -Depth 4\n"
)

PLAIN_IN_WINDOW = (
    "UNEXPECTED SHUTDOWN: host booted 2026-10-06 13:20 after an unclean shutdown "
    "(outage 2026-10-06 13:02 -> 2026-10-06 13:20); 1 unclean boot(s) in 7d - verify today's capture grade; "
    "an outage inside 12:00-18:00 ends the streak"
)
PLAIN_OFF_WINDOW = (
    "UNEXPECTED SHUTDOWN: host booted 2026-10-06 23:35 after an unclean shutdown "
    "(outage 2026-10-06 23:20 -> 2026-10-06 23:35); 1 unclean boot(s) in 7d - verify today's capture grade; "
    "an outage inside 12:00-18:00 ends the streak"
)
# A note may carry digits, parentheses and even outage-like text; none of it may move severity.
SPOOF_NOTE = "manual reset (outage 2026-10-06 13:00 -> 2026-10-06 13:10) 3 unclean boot(s) in 7d"


def annotated(flag: str, at: str, note: str) -> str:
    return f"{flag} - owner reset acknowledged {at} ({note})"


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", *args],
        capture_output=True, text=True, check=False, timeout=90, **kwargs,
    )


def ps(script: Path, functions: list[str], body: str, tmp_path: Path) -> subprocess.CompletedProcess:
    runner = tmp_path / "runner.ps1"
    names = ",".join("'" + name + "'" for name in functions)
    runner.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$tokens=$null; $errors=$null\n"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$tokens,[ref]$errors)\n"
        "if($errors.Count){throw ($errors | Out-String)}\n"
        f"$names=@({names})\n"
        "$found=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in $names},$true))\n"
        "if($found.Count -ne $names.Count){throw 'missing function'}\n"
        "$found | ForEach-Object {Invoke-Expression $_.Extent.Text}\n"
        f"$root='{tmp_path}'\n" + body,
        encoding="utf-8-sig",
    )
    return run(["-File", str(runner)])


def run_watchdog(tmp_path: Path, flags: list[str], as_of: str) -> dict:
    watchdog = tmp_path / "scripts" / "ops" / "health_watchdog.ps1"
    watchdog.parent.mkdir(parents=True, exist_ok=True)
    watchdog.write_bytes(WATCHDOG.read_bytes())
    (watchdog.parent / "status.ps1").write_text(STATUS_FIXTURE, encoding="utf-8")
    (watchdog.parent / "flags.json").write_text(json.dumps(flags), encoding="utf-8")
    result = run(["-File", str(watchdog), "-AsOf", as_of], cwd=tmp_path)
    assert result.returncode in (0, 2), result.stderr
    return json.loads((tmp_path / "data" / "alerts" / "host_health_latest.json").read_text(encoding="utf-8-sig"))


def watchdog_state(tmp_path: Path) -> dict:
    return json.loads(
        (tmp_path / "data" / "alerts" / "host_health_watchdog_state.json").read_text(encoding="utf-8-sig")
    )


def log_reasons(tmp_path: Path) -> list[str]:
    path = tmp_path / "data" / "alerts" / "host_health_alerts.jsonl"
    return [json.loads(line)["log_reason"] for line in path.read_text(encoding="utf-8").splitlines() if line]


def ledger(tmp_path: Path) -> Path:
    return tmp_path / "data" / "alerts" / "owner_resets" / "owner_resets_2026-10.jsonl"


def write_note(tmp_path: Path, at: str, note: str) -> subprocess.CompletedProcess:
    return run(["-File", str(NOTE), "-RepoRoot", str(tmp_path), "-At", at, "-Note", note])


def boot_state(tmp_path: Path, with_ledger: bool = True) -> dict:
    directory = "(Join-Path $root 'data\\alerts\\owner_resets')" if with_ledger else "''"
    result = ps(STATUS, ["Read-WeatherOwnerResetMarkers", "Get-WeatherUncleanBootState"], f"""
$boots=@([pscustomobject]@{{boot=[datetime]'2026-10-06T13:20:00'; last_alive=[datetime]'2026-10-06T13:02:00'}})
Get-WeatherUncleanBootState -Boots $boots -Now ([datetime]'2026-10-07T03:00:00') -OwnerResetDirectory {directory} |
  ConvertTo-Json -Depth 4 -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ---------------------------------------------------------------- owner command
def test_owner_command_appends_a_dated_marker_and_never_rewrites(tmp_path):
    first = write_note(tmp_path, "2026-10-06 12:50", "manual reset, screen frozen")
    second = write_note(tmp_path, "2026-10-06T14:00:30", "second reset")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    raw = ledger(tmp_path).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    assert [(r["schema"], r["at"], r["note"]) for r in rows] == [
        ("owner_reset_note_v1", "2026-10-06T12:50:00", "manual reset, screen frozen"),
        ("owner_reset_note_v1", "2026-10-06T14:00:30", "second reset"),
    ]
    assert all(r["recorded_at"] for r in rows)


@pytest.mark.parametrize(
    "at, note",
    [("2099-01-01 00:00", "future"), ("06/10/2026 12:50", "ambiguous culture date"),
     ("2026-10-06 12:50", "tab\tcontrol"), ("2026-10-06 12:50", "x" * 201)],
)
def test_owner_command_rejects_bad_input_and_writes_nothing(tmp_path, at, note):
    result = write_note(tmp_path, at, note)
    assert result.returncode != 0
    assert not ledger(tmp_path).exists()


# ---------------------------------------------------------------- status.ps1
def test_matched_marker_annotates_the_flag_and_fills_owner_reset_ack(tmp_path):
    plain = boot_state(tmp_path, with_ledger=False)
    assert plain["flag"] == PLAIN_IN_WINDOW
    # 12:50 is 12 minutes before the outage start (13:02): inside the 15-minute tolerance.
    assert write_note(tmp_path, "2026-10-06 12:50", "manual reset (owner)").returncode == 0
    state = boot_state(tmp_path)
    assert state["flag"] == annotated(PLAIN_IN_WINDOW, "2026-10-06 12:50", "manual reset (owner)")
    ack = state["owner_reset_ack"]
    assert ack["at"].startswith("2026-10-06T12:50:00")
    assert ack["note"] == "manual reset (owner)"
    assert ack["ledger"] == "owner_resets_2026-10.jsonl"
    assert ack["tolerance_minutes"] == 15
    assert state["owner_reset_note"] is None
    for field in ("unclean_boots_7d", "unclean_boots_90d", "outage_start", "outage_end", "last_unclean_boot"):
        assert state[field] == plain[field]


@pytest.mark.parametrize("at", ["2026-10-06 12:40", "2026-10-06 13:30", "2026-09-30 13:10"])
def test_unmatched_marker_leaves_the_flag_unchanged(tmp_path, at):
    # 12:40 is 22 minutes before the outage; 13:30 is after the boot; 09-30 is another month.
    plain = boot_state(tmp_path, with_ledger=False)
    assert write_note(tmp_path, at, "a different reset").returncode == 0
    state = boot_state(tmp_path)
    assert state == plain


@pytest.mark.parametrize(
    "bad_line",
    ["{not json", '"just a string"', '{"schema":"owner_reset_note_v1","at":"2026-10-06 12:55","note":"x","recorded_at":"r"}',
     '{"schema":"owner_reset_note_v2","at":"2026-10-06T12:55:00","note":"x","recorded_at":"r"}',
     '{"schema":"owner_reset_note_v1","at":"2026-10-06T12:55:00","recorded_at":"r"}'],
)
def test_malformed_marker_fails_closed_with_a_note(tmp_path, bad_line):
    plain = boot_state(tmp_path, with_ledger=False)
    # A valid matching marker is present too: one bad record still means no annotation.
    assert write_note(tmp_path, "2026-10-06 13:05", "manual reset").returncode == 0
    with ledger(tmp_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(bad_line + "\n")
    state = boot_state(tmp_path)
    assert state["flag"] == plain["flag"]
    assert state["owner_reset_ack"] is None
    assert state["owner_reset_note"].startswith("owner reset ledger unreadable (owner_resets_2026-10.jsonl line 2")
    assert "not annotated" in state["owner_reset_note"]


# ---------------------------------------------------------------- watchdog
@pytest.mark.parametrize("plain, expected", [(PLAIN_IN_WINDOW, "CRITICAL"), (PLAIN_OFF_WINDOW, "HIGH")])
def test_watchdog_keeps_class_and_severity_for_an_acknowledged_reset(tmp_path, plain, expected):
    flag = annotated(plain, "2026-10-06 13:00", SPOOF_NOTE)
    latest = run_watchdog(tmp_path, [flag], "2026-10-07T03:00:00")
    (alert,) = latest["alerts"]
    assert alert["class"] == "host_stability"
    assert alert["severity"] == expected
    assert alert["flag"] == flag
    assert alert["unclean_boots_7d"] == 1
    assert alert["owner_reset_ack"] == {"at": "2026-10-06 13:00", "note": SPOOF_NOTE}


def test_watchdog_unannotated_shutdown_has_no_owner_reset_ack(tmp_path):
    latest = run_watchdog(tmp_path, [PLAIN_IN_WINDOW], "2026-10-07T03:00:00")
    (alert,) = latest["alerts"]
    assert alert["severity"] == "CRITICAL"
    assert alert["owner_reset_ack"] is None


def test_acknowledging_a_reset_does_not_change_the_fingerprint(tmp_path):
    run_watchdog(tmp_path, [PLAIN_OFF_WINDOW], "2026-10-07T03:00:00")
    before = watchdog_state(tmp_path)
    run_watchdog(tmp_path, [annotated(PLAIN_OFF_WINDOW, "2026-10-06 23:15", SPOOF_NOTE)], "2026-10-07T03:15:00")
    after = watchdog_state(tmp_path)
    assert after["fingerprint"] == before["fingerprint"]
    assert after["tracking"] == before["tracking"]
    assert log_reasons(tmp_path) == ["state_change"]


def ps_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def test_dedup_key_strips_only_the_owner_reset_annotation(tmp_path):
    result = ps(WATCHDOG, ["Get-WeatherDiskDepthBucket", "Get-WeatherFlagDedupKey"], f"""
@(
 (Get-WeatherFlagDedupKey {ps_literal(PLAIN_OFF_WINDOW)}),
 (Get-WeatherFlagDedupKey {ps_literal(annotated(PLAIN_OFF_WINDOW, "2026-10-06 23:15", SPOOF_NOTE))}),
 (Get-WeatherFlagDedupKey 'LOW DISK: 23 GB free - owner reset acknowledged 2026-10-06 23:15 (x)')
) | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    plain, acknowledged, other = json.loads(result.stdout)
    assert acknowledged == plain
    assert "owner reset acknowledged" not in plain
    # Only an UNEXPECTED SHUTDOWN row can carry the annotation; nothing else is stripped.
    assert "owner reset acknowledged" in other
