"""Swarm P host audit 2026-10-07 (G1, G3/G4, G5, BOM): watchdog classification,
severity carry-through and escalation, volatile-number dedupe, deployed-vs-master
drift and the memory-guard status reader. Fixtures only; never the live host.

Guards: Swarm P host audit 2026-10-07 items G1, G3/G4, G5 and BOM; HOST_LOAD_POLICY watchdog
classification and OPERATIONS_DESIGN pinned watchdog deployment.
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
READER = OPS / "memory_guard_status_reader.ps1"
pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell contract"),
    pytest.mark.spawns,
]

STATUS_FIXTURE = (
    "param([string]$RepoRoot, [switch]$Json, [string]$ExpectedSelfSha256)\n"
    "$flags = @((Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'flags.json') | ConvertFrom-Json) |"
    " ForEach-Object { [string]$_ })\n"
    "@{verdict='ATTENTION'; flags=$flags; warns=@(); streak=@{days=2;target=14;today='fixture'};"
    " host_stability=@{unclean_boots_7d=3}} | ConvertTo-Json -Depth 4\n"
)


def _setup(tmp_path: Path) -> Path:
    watchdog = tmp_path / "scripts" / "ops" / "health_watchdog.ps1"
    watchdog.parent.mkdir(parents=True, exist_ok=True)
    watchdog.write_bytes(WATCHDOG.read_bytes())
    (watchdog.parent / "status.ps1").write_text(STATUS_FIXTURE, encoding="utf-8")
    return watchdog


def run_watchdog(tmp_path: Path, flags: list[str], as_of: str) -> dict:
    watchdog = _setup(tmp_path)
    (watchdog.parent / "flags.json").write_text(json.dumps(flags), encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(watchdog), "-AsOf", as_of],
        cwd=tmp_path, capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode in (0, 2), result.stderr
    return json.loads(
        (tmp_path / "data" / "alerts" / "host_health_latest.json").read_text(encoding="utf-8-sig")
    )


def log_rows(tmp_path: Path) -> list[dict]:
    path = tmp_path / "data" / "alerts" / "host_health_alerts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def by_flag(latest: dict, prefix: str) -> dict:
    matches = [a for a in latest["alerts"] if a["flag"].startswith(prefix)]
    assert len(matches) == 1, latest["alerts"]
    return matches[0]


def ps(script: Path, functions: list[str], body: str, tmp_path: Path, **env: str):
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
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(runner)],
        capture_output=True, text=True, timeout=90, env={**os.environ, **env},
    )


# ---------------------------------------------------------------- G1
SHUTDOWN_IN_WINDOW = (
    "UNEXPECTED SHUTDOWN: host booted 2026-10-06 13:20 after an unclean shutdown "
    "(outage 2026-10-06 13:02 -> 2026-10-06 13:20); 3 unclean boot(s) in 7d - verify today's capture grade"
)
SHUTDOWN_OFF_WINDOW = (
    "UNEXPECTED SHUTDOWN: host booted 2026-10-06 23:35 after an unclean shutdown "
    "(outage 2026-10-06 23:20 -> 2026-10-06 23:35); 3 unclean boot(s) in 7d - verify today's capture grade"
)
SHUTDOWN_SPANNING_NOON = (
    "UNEXPECTED SHUTDOWN: host booted 2026-10-06 12:05 after an unclean shutdown "
    "(outage 2026-10-06 11:40 -> 2026-10-06 12:05); 1 unclean boot(s) in 7d - verify today's capture grade"
)


@pytest.mark.parametrize(
    "flag, expected",
    [(SHUTDOWN_IN_WINDOW, "CRITICAL"), (SHUTDOWN_OFF_WINDOW, "HIGH"), (SHUTDOWN_SPANNING_NOON, "CRITICAL")],
)
def test_unexpected_shutdown_is_high_and_critical_when_it_overlaps_graded_window(tmp_path, flag, expected):
    latest = run_watchdog(tmp_path, [flag], "2026-10-07T03:00:00")
    alert = by_flag(latest, "UNEXPECTED SHUTDOWN")
    assert alert["class"] == "host_stability"
    assert alert["severity"] == expected
    assert latest["host_stability"]["unclean_boots_7d"] == 3


@pytest.mark.parametrize("as_of, expected", [("2026-10-07T03:00:00", "HIGH"), ("2026-10-07T13:00:00", "CRITICAL")])
def test_clock_unsynchronized_is_capture_integrity(tmp_path, as_of, expected):
    latest = run_watchdog(tmp_path, ["system clock is not synchronized (source Local CMOS Clock)"], as_of)
    alert = by_flag(latest, "system clock")
    assert alert["class"] == "capture_integrity"
    assert alert["severity"] == expected
    assert "timestamps" in alert["act"]


def test_status_unclean_boot_state_counts_recent_boots_and_formats_outage(tmp_path):
    result = ps(STATUS, ["Get-WeatherUncleanBootState"], r"""
$now=[datetime]'2026-10-07T03:00:00'
$boots=@(
  [pscustomobject]@{boot=[datetime]'2026-10-06T23:35:00'; last_alive=[datetime]'2026-10-06T23:20:00'},
  [pscustomobject]@{boot=[datetime]'2026-10-03T14:00:00'; last_alive=$null},
  [pscustomobject]@{boot=[datetime]'2026-08-20T09:00:00'; last_alive=$null}
)
Get-WeatherUncleanBootState -Boots $boots -Now $now | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["unclean_boots_7d"] == 2
    assert state["unclean_boots_90d"] == 3
    assert state["flag"].startswith("UNEXPECTED SHUTDOWN: host booted 2026-10-06 23:35")
    assert "(outage 2026-10-06 23:20 -> 2026-10-06 23:35)" in state["flag"]
    assert "2 unclean boot(s) in 7d" in state["flag"]


# ---------------------------------------------------------------- G3
def test_sweep_severity_is_carried_and_standing_learning_criticals_are_demoted(tmp_path):
    latest = run_watchdog(tmp_path, [
        "STALENESS_SWEEP CRITICAL [closure/fixture]: data\\x.json is 1.5d old | only source |",
        "STALENESS_SWEEP CRITICAL [closure/old]: data\\y.json is 4.0d old | only source |",
        "STALENESS_SWEEP CRITICAL [learning/daily_learning]: data\\backtest\\daily_learning.json is 54.3d old | cannot learn |",
        "STALENESS_SWEEP CRITICAL [learning/market_beating_scoreboard]: data\\backtest\\market_beating_objective_scoreboard.json is 54.3d old | scorecard |",
    ], "2026-10-07T03:00:00")
    fresh = by_flag(latest, "STALENESS_SWEEP CRITICAL [closure/fixture]")
    old = by_flag(latest, "STALENESS_SWEEP CRITICAL [closure/old]")
    assert (fresh["class"], fresh["severity"]) == ("staleness_sweep", "HIGH")
    assert old["severity"] == "CRITICAL"
    for check in ("learning/daily_learning", "learning/market_beating_scoreboard"):
        alert = by_flag(latest, f"STALENESS_SWEEP CRITICAL [{check}]")
        assert alert["severity"] == "MEDIUM"
        assert alert["demoted"]
    assert latest["top_severity"] == "CRITICAL"


def test_scheduled_job_escalates_on_consecutive_failures_and_age(tmp_path):
    first = run_watchdog(tmp_path, [
        "WeatherFixtureJob 0x1 unexpected (last run 10/05/2026 06:50:00)",
        "WeatherOtherJob 0x1 unexpected (last run 10/05/2026 05:00:00)",
    ], "2026-10-07T03:00:00")
    assert {a["severity"] for a in first["alerts"]} == {"MEDIUM"}
    second = run_watchdog(tmp_path, [
        "WeatherFixtureJob 0x1 unexpected (last run 10/06/2026 06:50:00)",
        "WeatherOtherJob 0x1 unexpected (last run 10/05/2026 05:00:00)",
    ], "2026-10-07T03:15:00")
    repeated = by_flag(second, "WeatherFixtureJob")
    assert repeated["severity"] == "HIGH"
    assert repeated["consecutive_failures"] == 2
    assert by_flag(second, "WeatherOtherJob")["severity"] == "MEDIUM"
    later = run_watchdog(tmp_path, [
        "WeatherOtherJob 0x1 unexpected (last run 10/05/2026 05:00:00)",
    ], "2026-10-08T04:00:00")
    aged = by_flag(later, "WeatherOtherJob")
    assert aged["severity"] == "HIGH"
    assert aged["condition_age_hours"] >= 24


# ---------------------------------------------------------------- G4
def test_rows_differing_only_in_volatile_numbers_dedupe(tmp_path):
    run_watchdog(tmp_path, [
        "LOW DISK: 23.4 GB free",
        "STALENESS_SWEEP CRITICAL [learning/daily_learning]: data\\backtest\\daily_learning.json is 54.3d old | cannot learn |",
        "WeatherFixtureJob 0x1 unexpected (last run 10/05/2026 06:50:00)",
    ], "2026-10-07T03:00:00")
    second = run_watchdog(tmp_path, [
        "LOW DISK: 22.9 GB free",
        "STALENESS_SWEEP CRITICAL [learning/daily_learning]: data\\backtest\\daily_learning.json is 55.1d old | cannot learn |",
        "WeatherFixtureJob 0x1 unexpected (last run 10/05/2026 06:50:00)",
    ], "2026-10-07T03:15:00")
    rows = log_rows(tmp_path)
    assert [row["log_reason"] for row in rows] == ["state_change"]
    assert by_flag(second, "LOW DISK")["flag"] == "LOW DISK: 22.9 GB free"
    run_watchdog(tmp_path, ["LOW DISK: 22.1 GB free"], "2026-10-07T03:30:00")
    assert [row["log_reason"] for row in log_rows(tmp_path)] == ["state_change", "state_change"]


def test_dedup_key_strips_volatile_numbers_but_keeps_identity(tmp_path):
    result = ps(WATCHDOG, ["Get-WeatherFlagDedupKey"], r"""
$pairs=@(
 @('HIGH COMMIT: 88.4% used (memory guard warning at 85%)','HIGH COMMIT: 91% used (memory guard warning at 85%)'),
 @('WeatherJob 0x1 unexpected (last run 10/05/2026 06:50:00)','WeatherJob 0x1 unexpected (last run 10/06/2026 6:50:00 AM)'),
 @('stale since 2026-10-06T23:35:00-04:00, 1,234 bytes','stale since 2026-10-07T01:00:00Z, 5,678 bytes'),
 @('health watchdog stale by 50 min','health watchdog stale by 75 min'),
 @('WeatherJob 0x1 unexpected','WeatherJob 0x2 unexpected'),
 @('Weather110nTask unexpectedly DISABLED','Weather111nTask unexpectedly DISABLED')
)
@($pairs | ForEach-Object { (Get-WeatherFlagDedupKey $_[0]) -ceq (Get-WeatherFlagDedupKey $_[1]) }) | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [True, True, True, True, False, False]


def test_low_disk_dedup_key_keeps_depth_bucket(tmp_path):
    # PR #255 Defender G4: 23 GB and 5 GB free used to share a key, so a worsening disk
    # never re-alerted. Each step down a bucket is a new condition; ticks within one dedupe.
    result = ps(WATCHDOG, ["Get-WeatherDiskDepthBucket", "Get-WeatherFlagDedupKey"], r"""
@(
 (Get-WeatherFlagDedupKey 'LOW DISK: 23 GB free'),
 (Get-WeatherFlagDedupKey 'LOW DISK: 5 GB free'),
 (Get-WeatherFlagDedupKey 'LOW DISK: 22 GB free'),
 (Get-WeatherFlagDedupKey 'LOW DISK: 4.2 GB free')
) | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    k23, k5, k22, k4 = json.loads(result.stdout)
    assert k23 == k22 == "LOW DISK: <25GiB free"
    assert k5 == "LOW DISK: <10GiB free"
    assert k4 == "LOW DISK: <5GiB free"
    assert len({k23, k5, k4}) == 3


def test_low_disk_depth_never_parses_a_comma_decimal_tail(tmp_path):
    # PR #255 fold Defender N6: "23,5 GB" must never bucket as 5 GiB. Without a clean
    # "<n> GB" figure the row keeps the plain '#' key, as before the bucket existed.
    result = ps(WATCHDOG, ["Get-WeatherDiskDepthBucket", "Get-WeatherFlagDedupKey"], r"""
@(
 (Get-WeatherFlagDedupKey 'LOW DISK: 23,5 GB free'),
 (Get-WeatherFlagDedupKey 'LOW DISK: 1.234,5 GB free'),
 (Get-WeatherFlagDedupKey 'LOW DISK: 23.5 GB free')
) | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    comma, grouped, dot = json.loads(result.stdout)
    assert comma == grouped == "LOW DISK: # GB free"
    assert dot == "LOW DISK: <25GiB free"


def test_settlement_hole_dedup_key_tracks_the_missing_date_set(tmp_path):
    # PR #255 Defender G4: a HIGH one-date hole moving to a new date used to keep its key.
    # A new missing date re-alerts; the same set in a different order still dedupes.
    hole = (
        "SETTLEMENT HOLE: {n} date(s) unsettled in the last 14 days [{dates}] - worst {worst}, "
        "up to 3 of 40 market(s) - each needs an EXPLICIT per-date backfill; the next chain run will not retry it"
    )
    flags = [
        hole.format(n=1, dates="2026-09-01", worst="2026-09-01"),
        hole.format(n=1, dates="2026-09-02", worst="2026-09-02"),
        hole.format(n=2, dates="2026-09-01, 2026-09-02", worst="2026-09-01"),
        hole.format(n=2, dates="2026-09-02, 2026-09-01", worst="2026-09-02"),
    ]
    literals = ",\n".join("'" + flag + "'" for flag in flags)
    result = ps(WATCHDOG, ["Get-WeatherFlagDedupKey"], f"""
$flags=@(
{literals}
)
@($flags | ForEach-Object {{ Get-WeatherFlagDedupKey $_ }}) | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    one, moved, pair, pair_reordered = json.loads(result.stdout)
    assert one.endswith("|dates=2026-09-01")
    assert moved.endswith("|dates=2026-09-02")
    assert one != moved
    assert pair.endswith("|dates=2026-09-01,2026-09-02")
    assert pair == pair_reordered


# ---------------------------------------------------------------- G5
def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("case", ["drift", "current", "pin_mismatch", "not_registered"])
def test_status_reports_deployed_watchdog_drift_against_master(tmp_path, case):
    repo = tmp_path / "production"
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "master")
    (ops / "health_watchdog.ps1").write_text("# watchdog v1\n", encoding="utf-8")
    (ops / "status.ps1").write_text("# status v1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "deployed")
    deployed_sha = _git(repo, "rev-parse", "HEAD")
    deploy = tmp_path / f"weather-watchdog-deployed-110n-{deployed_sha[:8]}"
    _git(repo, "worktree", "add", "-q", "--detach", str(deploy), deployed_sha)
    if case != "current":
        (ops / "health_watchdog.ps1").write_text("# watchdog v2\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "watchdog change")
        (repo / "unrelated.txt").write_text("x\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "unrelated")
    import hashlib
    wd_path = deploy / "scripts" / "ops" / "health_watchdog.ps1"
    st_path = deploy / "scripts" / "ops" / "status.ps1"
    wd_hash = hashlib.sha256(wd_path.read_bytes()).hexdigest()
    st_hash = hashlib.sha256(st_path.read_bytes()).hexdigest()
    if case == "pin_mismatch":
        st_hash = "0" * 64
    arguments = (
        f'-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{wd_path}" -RepoRoot "{repo}" '
        f'-ExpectedSelfSha256 {wd_hash} -StatusScriptPath "{st_path}" -ExpectedStatusScriptSha256 {st_hash}'
    )
    if case == "not_registered":
        arguments = ""
    result = ps(STATUS, ["Get-WeatherWatchdogDeploymentDrift"], r"""
Get-WeatherWatchdogDeploymentDrift -Arguments $env:FIXTURE_ARGS -Repo $env:FIXTURE_REPO | ConvertTo-Json -Depth 5 -Compress
""", tmp_path, FIXTURE_ARGS=arguments, FIXTURE_REPO=str(repo))
    assert result.returncode == 0, result.stderr
    drift = json.loads(result.stdout)
    if case == "not_registered":
        assert drift["status"] == "NOT_REGISTERED"
        return
    assert drift["deployed_commit"] == deployed_sha
    files = {f["name"]: f for f in drift["files"]}
    if case == "current":
        assert drift["status"] == "CURRENT"
        assert drift["commits_behind"] == 0
        assert all(f["matches_master"] for f in files.values())
        return
    assert drift["commits_behind"] == 2
    assert drift["commits_behind_touching"] == 1
    assert files["health_watchdog.ps1"]["matches_master"] is False
    assert files["status.ps1"]["matches_master"] is True
    if case == "pin_mismatch":
        assert drift["status"] == "PIN_MISMATCH"
        assert files["status.ps1"]["pin_ok"] is False
    else:
        assert drift["status"] == "DRIFT"
        assert all(f["pin_ok"] for f in files.values())
    assert "behind master" in drift["detail"]


# ---------------------------------------------------------------- BOM
def test_status_inline_reader_is_byte_identical_to_shared_helper():
    def function_text(path: Path) -> str:
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        start = text.index("function Read-WeatherMemoryGuardStatus")
        end = text.index("\n}\n", start) + 3
        return text[start:end]

    assert function_text(STATUS) == function_text(READER)
    for wrapper in ("closed_day_projection_twins_run.ps1", "guidance_extract_run.ps1", "wu_orphan_cleanup_run.ps1"):
        source = (OPS / wrapper).read_text(encoding="utf-8-sig")
        assert "memory_guard_status_reader.ps1" in source
        assert "Read-WeatherMemoryGuardStatus" in source
        assert "Get-Content -LiteralPath $memoryPath" not in source


@pytest.mark.parametrize("source", ["status", "helper"])
def test_memory_guard_reader_survives_bom_and_rename_replacement(tmp_path, source):
    script = STATUS if source == "status" else READER
    status_path = tmp_path / "memory_commit_guard_status.json"
    result = ps(script, ["Read-WeatherMemoryGuardStatus"], r"""
$path = Join-Path $root 'memory_commit_guard_status.json'
function Write-Guard([double]$pct) {
    $tmp = '{0}.{1}.tmp' -f $path, [guid]::NewGuid().ToString('N')
    # Windows PowerShell 5.1 Out-File utf8 writes a BOM, exactly like the guard.
    [ordered]@{checked_at=(Get-Date).ToString('o'); commit_percent=$pct; warn_percent=85; act_percent=92} |
        ConvertTo-Json | Out-File -LiteralPath $tmp -Encoding utf8
    Move-Item -LiteralPath $tmp -Destination $path -Force
}
Write-Guard 41.5
$bytes = [IO.File]::ReadAllBytes($path)
if ($bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) { throw 'fixture lacks BOM' }
# A reader holding the file open with the helper's share mode must not block replacement.
$share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
$held = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
try { Write-Guard 42.5 } finally { $held.Dispose() }
$writer = Start-Job -ScriptBlock {
    param($path)
    $deadline = (Get-Date).AddSeconds(4)
    $i = 0
    while ((Get-Date) -lt $deadline) {
        $tmp = '{0}.{1}.tmp' -f $path, [guid]::NewGuid().ToString('N')
        [ordered]@{checked_at=(Get-Date).ToString('o'); commit_percent=(40 + ($i % 10)); warn_percent=85; act_percent=92} |
            ConvertTo-Json | Out-File -LiteralPath $tmp -Encoding utf8
        Move-Item -LiteralPath $tmp -Destination $path -Force
        $i++
    }
    $i
} -ArgumentList $path
Start-Sleep -Milliseconds 500
$ok = 0; $failures = @()
for ($n = 0; $n -lt 150; $n++) {
    try {
        $read = Read-WeatherMemoryGuardStatus -Path $path
        if ($null -ne $read.row.commit_percent -and $read.last_write_time -is [datetime]) { $ok++ }
    } catch { $failures += $_.Exception.Message }
}
$writes = Receive-Job -Job $writer -Wait
Remove-Job -Job $writer
[ordered]@{ok=$ok; failures=$failures; writes=[int](@($writes)[-1])} | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["failures"] in ([], None), outcome
    assert outcome["ok"] == 150
    assert outcome["writes"] > 5
    assert status_path.exists()


def test_status_memory_guard_evidence_reads_bom_json(tmp_path):
    result = ps(STATUS, ["Read-WeatherMemoryGuardStatus", "Get-StatusMemoryGuardEvidence"], r"""
$path = Join-Path $root 'guard.json'
$json = '{"checked_at":"2026-10-07T03:00:00-04:00","commit_percent":41.5,"warn_percent":85,"act_percent":92}'
[IO.File]::WriteAllText($path, $json, [Text.UTF8Encoding]::new($true))
Get-StatusMemoryGuardEvidence -Path $path -Now ([datetimeoffset]'2026-10-07T03:01:00-04:00') | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["status"] == "OK", state
    assert state["commit_percent"] == 41.5
