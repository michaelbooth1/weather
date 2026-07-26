# Prove the off-host mirror can actually be RESTORED FROM, not merely that robocopy exited 0.
#
#   .\scripts\ops\verify_mirror_restore.ps1 [-Sample 8]
#
# Why this exists: \\DESKTOP-RFCD2GH\weather-mirror is the only copy of data\ that is not on
# this disk, and the tape backup that used to include a restore drill has been disabled since
# 2026-06-30. Since then nothing has verified that the mirror is readable, complete, or
# correct -- WeatherDataMirror reports robocopy's exit code, which says a copy ran, not that
# what landed is restorable. Given this host loses power roughly every three weeks (see
# boot_recovery.ps1), an unverified single off-host copy is the real durability exposure.
#
# The check pulls named critical files plus a random recent sample BACK from the mirror into
# a scratch directory and compares SHA256 against local. Files written after the mirror ran
# are expected to differ and are reported as "newer locally", not as failures -- capture is
# always writing, so treating live churn as corruption would make this cry wolf nightly.
#
# Reads the sync credential the same way the mirror script does and never prints it.
[CmdletBinding()]
param([int]$Sample = 8)

$ErrorActionPreference = "Continue"
$repo = "C:\Users\micha\Desktop\github\weather"
$dataRoot = Join-Path $repo "data"
$share = '\\DESKTOP-RFCD2GH\weather-mirror'
$mirrorData = "$share\data"
$credF = 'C:\Users\micha\.weathersync.cred'
$statusPath = Join-Path $repo "data\alerts\mirror_restore_verify.json"
$scratch = Join-Path $env:TEMP ("mirror-restore-" + (Get-Date -Format "yyyyMMddHHmmss"))

# Files whose loss would actually hurt: the streak authority, the promotion artifact, the
# capture heartbeat. Verified by name every run rather than left to the random sample.
$critical = @(
    "settlements\toronto\ledger.jsonl",
    "backtest\market_day_labels.csv",
    "snapshots\loop_status.json"
)

# List[psobject], NOT List[object]: on this host `@($list)` throws "Argument types do not
# match" for a generic List[object] (any element type), which silently killed the status
# write while the checks themselves all passed. List[psobject] and List[string] enumerate
# normally.
$results = New-Object System.Collections.Generic.List[psobject]
$netOk = $false
$mirrorRun = $null
$mirrorRunIso = $null
try {
    $mirrorRunIso = [string](Get-Content "C:\Users\micha\ops\mirror_status.json" -Raw | ConvertFrom-Json).last_run
    $mirrorRun = [datetime]$mirrorRunIso
}
catch {}

function Add-Result($rel, $state, $detail) {
    $results.Add([PSCustomObject]@{ file = $rel; state = $state; detail = $detail })
}

# Never run while the mirror itself is copying. This is scheduled 12 minutes after the mirror
# typically finishes, but run length varies with churn -- and if it overran, the
# `net use /delete` below would tear the share out from under an in-progress robocopy.
# Skipping a day of verification is free; breaking the only off-host copy is not. Exit
# WITHOUT rewriting the status file, so a skip leaves the last real result standing and
# ages out through status.ps1's staleness check rather than looking like a failure.
$mirrorLock = "C:\Users\micha\ops\mirror.lock"
if (Test-Path $mirrorLock) {
    $lockAgeH = ((Get-Date) - (Get-Item $mirrorLock).LastWriteTime).TotalHours
    if ($lockAgeH -lt 12) {
        Write-Output ("skipped: mirror still running (lock {0:N1}h old); not touching its share" -f $lockAgeH)
        exit 0
    }
}

try {
    $pw = (Get-Content $credF -Raw).Trim()
    net use $share $pw /user:DESKTOP-RFCD2GH\weathersync | Out-Null
    $netOk = ($LASTEXITCODE -eq 0)
    $pw = $null
    if (-not $netOk) { throw "could not mount $share" }

    New-Item -ItemType Directory -Force -Path $scratch | Out-Null

    # Sample the newest files that PREDATE the mirror run. Sampling the newest files overall
    # is nearly worthless here: capture rewrites the hot ones constantly, so almost every
    # comparison comes back "newer locally" and proves nothing (the first run of this script
    # verified exactly one file out of 19). A file last written before the mirror ran must be
    # byte-identical off-host, so every such comparison is a real test.
    # Shallow listings only -- never a recursive walk of data\, which has starved capture.
    $picks = @($critical)
    $sampleDirs = @("settlements\toronto", "alerts", "backtest")
    foreach ($d in $sampleDirs) {
        $full = Join-Path $dataRoot $d
        if (-not (Test-Path $full)) { continue }
        Get-ChildItem $full -File -EA SilentlyContinue |
        Where-Object { -not $mirrorRun -or $_.LastWriteTime -lt $mirrorRun } |
        Sort-Object LastWriteTime -Descending | Select-Object -First $Sample |
        ForEach-Object { $picks += (Join-Path $d $_.Name) }
    }
    $picks = @($picks | Select-Object -Unique)

    foreach ($rel in $picks) {
        $local = Join-Path $dataRoot $rel
        $remote = Join-Path $mirrorData $rel
        if (-not (Test-Path $local)) { Add-Result $rel "skipped" "not present locally"; continue }
        if (-not (Test-Path $remote)) {
            # A file created after the last mirror run has simply not been copied yet; that
            # is the schedule working, not a durability hole. Only an older file that is
            # absent off-host means we would actually lose something.
            $lw = (Get-Item -LiteralPath $local).LastWriteTime
            if ($mirrorRun -and $lw -gt $mirrorRun) {
                Add-Result $rel "not_yet_mirrored" ("created {0:yyyy-MM-dd HH:mm}, after the last mirror run" -f $lw)
            }
            else {
                Add-Result $rel "MISSING_IN_MIRROR" "no copy off-host despite predating the last mirror run"
            }
            continue
        }

        $restored = Join-Path $scratch ($rel -replace '[\\/]', '_')
        Copy-Item -LiteralPath $remote -Destination $restored -Force -EA SilentlyContinue
        if (-not (Test-Path $restored)) { Add-Result $rel "UNREADABLE" "copy back from mirror failed"; continue }

        $hLocal = (Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash
        $hRest = (Get-FileHash -LiteralPath $restored -Algorithm SHA256).Hash
        if ($hLocal -eq $hRest) { Add-Result $rel "ok" "hash match" ; continue }

        # Differs. Only a problem if the local file has NOT changed since the mirror ran.
        $lw = (Get-Item -LiteralPath $local).LastWriteTime
        if ($mirrorRun -and $lw -gt $mirrorRun) {
            Add-Result $rel "newer_locally" ("local modified {0:yyyy-MM-dd HH:mm} after mirror run" -f $lw)
        }
        else {
            Add-Result $rel "MISMATCH" ("differs though local unchanged since mirror run (local {0:yyyy-MM-dd HH:mm})" -f $lw)
        }
    }
}
catch {
    Add-Result "(mount)" "ERROR" $_.Exception.Message
}
finally {
    if ($netOk) { net use $share /delete /y | Out-Null }
    Remove-Item $scratch -Recurse -Force -EA SilentlyContinue
}

$bad = @($results | Where-Object { $_.state -cmatch '^[A-Z_]+$' -and $_.state -ne 'ok' })
$verified = @($results | Where-Object { $_.state -eq 'ok' }).Count
$ok = ($bad.Count -eq 0 -and $verified -gt 0)

[ordered]@{
    ts = (Get-Date).ToString("o"); ok = $ok
    mirror_last_run = $mirrorRunIso
    checked = $results.Count; verified_identical = $verified; problems = $bad.Count
    results = @($results)
} | ConvertTo-Json -Depth 4 | Set-Content -Path $statusPath -Encoding utf8

$results | ForEach-Object { "{0,-20} {1}" -f $_.state, $_.file }
""
"checked=$($results.Count)  identical=$verified  problems=$($bad.Count)  ok=$ok"
if (-not $ok) { exit 2 }
exit 0
