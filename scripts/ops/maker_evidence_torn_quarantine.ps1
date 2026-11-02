<#
.SYNOPSIS
Quarantine torn maker-evidence journals left by a hard power loss (Stage 1: operator tool).

.DESCRIPTION
EvidenceStore._recover refuses to start when a journal in the unsealed segment ends in a
NUL-filled or partial last line, so WeatherMakerEvidenceCapture returns 1 at every trigger.
This script automates the manual runbook "Torn journal after power loss" in
docs/operations/passive-maker-evidence-capture.md. Report-only unless -Apply.

Safety contract (design approved 2026-11-02, L54):
- Classifies only while holding byte 0 of <Root>\.writer.lock (FileStream.Lock(0,1), the same
  Win32 LockFile region the recorder's msvcrt.locking takes before EvidenceStore exists). The
  lock is held for the whole pass, so no writer can start or be alive meanwhile. A running
  recorder process for the same root is an additional (advisory) refusal.
- Exactly one unsealed segment (<day>\<HH>-<12 hex> without manifest.json/.json.gz) or nothing.
- Candidates: non-empty *.jsonl directly in that segment whose last byte is not 0x0A. At most
  MaxFiles (hard cap 10); above it nothing moves. A NUL byte inside any other journal of the
  segment means the store cannot recover by moving tails: UNRESOLVED, no action.
- Same-volume rename only (never copy+delete), SHA-256 before and after, an intent file before
  the first move and an immutable receipt after the last. A rerun reconciles from the intent.
- Never truncates, rewrites or deletes; never touches sealed segments, manifests, .gz, .tmp,
  status.json or the lock file contents. No Scheduler call: start the task yourself afterwards.

Exit codes: 0 NOOP / REPORT / QUARANTINED / RECONCILED; 2 refused; 4 failed mid-apply (intent
kept; rerun reconciles); 5 UNRESOLVED (needs a human, no action taken).
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Root = "",
    [string]$QuarantineRoot = "",
    [string]$LogPath = "",
    [string]$TaskName = "",
    [ValidateRange(1, 10)][int]$MaxFiles = 10,
    [string]$RepoRoot = ""
)
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$coreDefault = $false
if (-not $Root) {
    $Root = Join-Path $RepoRoot "data\maker_evidence"
    $coreDefault = $true
    if (-not $QuarantineRoot) { $QuarantineRoot = Join-Path $RepoRoot "data\maker_evidence_quarantine" }
    if (-not $PSBoundParameters.ContainsKey("TaskName")) { $TaskName = "WeatherMakerEvidenceCapture" }
}
if (-not $LogPath) { $LogPath = Join-Path $RepoRoot "data\alerts\maker_evidence_torn_quarantine.jsonl" }

$script:result = [ordered]@{
    schema = "maker_evidence_torn_quarantine_v1"; status = ""; applied = [bool]$Apply
    checked_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    script_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    root = $Root; quarantine_root = $QuarantineRoot; segment = $null; candidates = @(); reasons = @()
}

function Write-Log {
    if (-not $Apply) { return }
    try {
        $dir = Split-Path -Parent $LogPath
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $line = ($script:result | ConvertTo-Json -Compress -Depth 6) + "`n"
        $bytes = [Text.Encoding]::UTF8.GetBytes($line)
        $stream = New-Object IO.FileStream($LogPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    }
    catch { $script:result.reasons += ("log write failed: " + $_.Exception.Message) }
}

function Finish([string]$Status, [int]$Code, [string]$Reason = "") {
    $script:result.status = $Status
    if ($Reason) { $script:result.reasons += $Reason }
    Write-Log
    $script:result | ConvertTo-Json -Depth 6
    if ($null -ne $script:lockStream) {
        try { $script:lockStream.Unlock(0, 1) } catch { }
        $script:lockStream.Dispose()
        $script:lockStream = $null
    }
    exit $Code
}

function Open-Shared([string]$Path) {
    return New-Object IO.FileStream($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
}

function Get-Sha256([string]$Path) {
    $stream = Open-Shared $Path
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace "-", "").ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}

function Get-TailClass([string]$Path) {
    # Returns $null when the file ends in 0x0A (or is empty), else the torn-tail class.
    $stream = Open-Shared $Path
    try {
        $length = $stream.Length
        if ($length -eq 0) { return $null }
        $window = [int][Math]::Min($length, 1048576)
        $buffer = New-Object byte[] $window
        [void]$stream.Seek($length - $window, [IO.SeekOrigin]::Begin)
        $read = 0
        while ($read -lt $window) {
            $n = $stream.Read($buffer, $read, $window - $read)
            if ($n -le 0) { throw "short read on $Path" }
            $read += $n
        }
        if ($buffer[$window - 1] -eq 10) { return $null }
        $nul = 0
        for ($i = $window - 1; $i -ge 0 -and $buffer[$i] -eq 0; $i--) { $nul++ }
        if ($nul -gt 0) { return [ordered]@{ tail = "nul_tail"; nul_tail_bytes = $nul; nul_tail_scan_capped = ($nul -eq $window) } }
        return [ordered]@{ tail = "no_final_newline"; nul_tail_bytes = 0; nul_tail_scan_capped = $false }
    }
    finally { $stream.Dispose() }
}

function Test-ContainsNul([string]$Path) {
    $stream = Open-Shared $Path
    try {
        $buffer = New-Object byte[] 1048576
        while (($n = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ([Array]::IndexOf($buffer, [byte]0, 0, $n) -ge 0) { return $true }
        }
        return $false
    }
    finally { $stream.Dispose() }
}

function Test-ReparseChain([string]$Path) {
    # True when the path or any existing ancestor is a reparse point (junction/symlink).
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $true }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

function Write-AtomicNew([string]$Path, $Value) {
    # Never overwrites: tmp + flush-to-disk + rename onto a name that must not exist.
    if (Test-Path -LiteralPath $Path) { throw "refusing to overwrite $Path" }
    $tmp = $Path + ".tmp"
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 8) + "`n")
    $stream = New-Object IO.FileStream($tmp, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    [IO.File]::Move($tmp, $Path)
}

# ---- inputs ----
if (-not $QuarantineRoot) { Finish "REFUSED_NO_QUARANTINE_ROOT" 2 "an explicit -Root requires an explicit -QuarantineRoot" }
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')
$QuarantineRoot = [IO.Path]::GetFullPath($QuarantineRoot).TrimEnd('\')
$script:result.root = $Root; $script:result.quarantine_root = $QuarantineRoot
if ($QuarantineRoot.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $Root.StartsWith($QuarantineRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $Root -ieq $QuarantineRoot) {
    Finish "REFUSED_QUARANTINE_OVERLAPS_ROOT" 2 "quarantine root must be outside the store root and vice versa"
}
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { Finish "NOOP_NO_ROOT" 0 }
if ([IO.Path]::GetPathRoot($Root) -ine [IO.Path]::GetPathRoot($QuarantineRoot)) {
    Finish "REFUSED_CROSS_VOLUME" 2 "quarantine root is on another volume; rename-only design"
}
if ((Test-ReparseChain $Root) -or (Test-ReparseChain $QuarantineRoot)) {
    Finish "REFUSED_REPARSE_POINT" 2 "a reparse point in the root or quarantine path could hide a cross-volume move"
}

# ---- advisory process check (the lock below is authoritative) ----
try {
    $writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
        $line = [string]$_.CommandLine
        if ($line -notmatch 'weather\.market\.maker_evidence_capture' -or $line -match '--dry-run') { return $false }
        if ($line -match '--root\s+"([^"]+)"' -or $line -match '--root\s+(\S+)') {
            return ([IO.Path]::GetFullPath($Matches[1]).TrimEnd('\') -ieq $Root)
        }
        return $true   # implicit root: cannot prove it is a different store
    })
}
catch { Finish "REFUSED_PROCESS_CHECK_FAILED" 2 $_.Exception.Message }
if ($writers.Count -gt 0) {
    Finish "REFUSED_WRITER_ALIVE" 2 ("recorder process running: pid " + (($writers | ForEach-Object { $_.ProcessId }) -join ","))
}

# ---- writer lock (authoritative) ----
$lockPath = Join-Path $Root ".writer.lock"
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) { Finish "NOOP_NO_LOCK_FILE" 0 "the recorder never ran on this root" }
$script:lockStream = $null
try {
    $script:lockStream = New-Object IO.FileStream($lockPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite,
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    $script:lockStream.Lock(0, 1)
}
catch {
    if ($null -ne $script:lockStream) { $script:lockStream.Dispose(); $script:lockStream = $null }
    Finish "REFUSED_WRITER_ALIVE" 2 ("writer lock is held: " + $_.Exception.Message)
}

# ---- unsealed segments (same folder rule as EvidenceStore._recover: <any>\<HH>-<12 hex>) ----
$unsealed = @()
foreach ($parent in @(Get-ChildItem -LiteralPath $Root -Directory -Force)) {
    foreach ($folder in @(Get-ChildItem -LiteralPath $parent.FullName -Directory -Force)) {
        if ($folder.Name -cnotmatch '^\d{2}-[0-9a-f]{12}$') { continue }
        if ((Test-Path -LiteralPath (Join-Path $folder.FullName "manifest.json")) -or
            (Test-Path -LiteralPath (Join-Path $folder.FullName "manifest.json.gz"))) { continue }
        $unsealed += $folder
    }
}
if ($unsealed.Count -eq 0) { Finish "NOOP_NO_UNSEALED_SEGMENT" 0 }
if ($unsealed.Count -gt 1) {
    $script:result.segment = @($unsealed | ForEach-Object { $_.FullName })
    Finish "REFUSED_MULTIPLE_UNSEALED" 2 "more than one unsealed segment; the store never leaves two"
}
$segment = $unsealed[0]
$day = $segment.Parent.Name
$script:result.segment = $segment.FullName
if ($day -cnotmatch '^\d{4}-\d{2}-\d{2}$') { Finish "REFUSED_UNEXPECTED_LAYOUT" 2 "unsealed segment parent is not a UTC day folder" }
if ($segment.Attributes -band [IO.FileAttributes]::ReparsePoint) { Finish "REFUSED_REPARSE_POINT" 2 "segment folder is a reparse point" }
$destination = Join-Path (Join-Path $QuarantineRoot $day) $segment.Name
$intentPath = Join-Path $destination "QUARANTINE_INTENT.json"
$receiptPath = Join-Path $destination "QUARANTINE_RECEIPT.json"

# ---- classify ----
$candidates = @()
$interior = @()
foreach ($file in @(Get-ChildItem -LiteralPath $segment.FullName -File -Force)) {
    if (-not $file.Name.EndsWith(".jsonl", [StringComparison]::Ordinal)) { continue }
    if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { Finish "REFUSED_REPARSE_POINT" 2 ("journal is a reparse point: " + $file.Name) }
    $tail = Get-TailClass $file.FullName
    if ($null -ne $tail) {
        $candidates += [ordered]@{ name = $file.Name; size = $file.Length; tail = $tail.tail
            nul_tail_bytes = $tail.nul_tail_bytes; nul_tail_scan_capped = $tail.nul_tail_scan_capped }
    }
    elseif ($file.Length -gt 0 -and (Test-ContainsNul $file.FullName)) { $interior += $file.Name }
}
$script:result.candidates = @($candidates | ForEach-Object { [pscustomobject]$_ })
if ($interior.Count -gt 0) {
    $script:result.interior_nul_journals = $interior
    Finish "UNRESOLVED" 5 "a newline-terminated journal contains NUL bytes; moving tails cannot let the store recover"
}

$intent = $null
if (Test-Path -LiteralPath $receiptPath) {
    if ($candidates.Count -eq 0) { Finish "NOOP_ALREADY_QUARANTINED" 0 }
    Finish "REFUSED_RECEIPT_EXISTS" 2 "a receipt exists for this segment but torn journals remain"
}
if (Test-Path -LiteralPath $intentPath) {
    try { $intent = Get-Content -LiteralPath $intentPath -Raw | ConvertFrom-Json }
    catch { Finish "REFUSED_INTENT_UNREADABLE" 2 $_.Exception.Message }
}

if ($null -eq $intent -and $candidates.Count -eq 0) {
    if ($TaskName) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($info -and [int64]$info.LastTaskResult -eq 1) {
            $script:result.task_last_result = 1
            Finish "UNRESOLVED" 5 "task last result is 1 but no torn tail exists in the unsealed segment"
        }
    }
    Finish "NOOP_NO_TORN_TAIL" 0
}
if ($candidates.Count -gt $MaxFiles) { Finish "REFUSED_CAP" 2 ("{0} torn journals exceed the cap of {1}" -f $candidates.Count, $MaxFiles) }

# ---- plan (fresh or from intent) ----
if ($null -ne $intent) {
    if ([string]$intent.segment -ne $segment.FullName) { Finish "REFUSED_RECONCILE_MISMATCH" 2 "intent names another segment" }
    $plan = @($intent.files | ForEach-Object { [ordered]@{ name = [string]$_.name; size = [int64]$_.size
        sha256_before = [string]$_.sha256_before; tail = [string]$_.tail } })
    $planned = @($plan | ForEach-Object { $_.name })
    foreach ($candidate in $candidates) {
        if ($planned -notcontains $candidate.name) { Finish "REFUSED_RECONCILE_MISMATCH" 2 ("torn journal not in intent: " + $candidate.name) }
    }
    $mode = "reconcile"
}
else {
    $plan = @()
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $destination $candidate.name)) {
            Finish "REFUSED_DESTINATION_EXISTS" 2 ("quarantine already holds " + $candidate.name)
        }
        $plan += [ordered]@{ name = $candidate.name; size = $candidate.size
            sha256_before = (Get-Sha256 (Join-Path $segment.FullName $candidate.name)); tail = $candidate.tail }
    }
    $mode = "fresh"
}
# Verify every plan entry is in exactly one place with the planned hash before any mutation.
$pending = @()
foreach ($entry in $plan) {
    $src = Join-Path $segment.FullName $entry.name
    $dst = Join-Path $destination $entry.name
    $atSrc = Test-Path -LiteralPath $src; $atDst = Test-Path -LiteralPath $dst
    if ($atSrc -and $atDst) { Finish "REFUSED_RECONCILE_MISMATCH" 2 ("present at source and destination: " + $entry.name) }
    if (-not $atSrc -and -not $atDst) { Finish "REFUSED_RECONCILE_MISMATCH" 2 ("missing from source and destination: " + $entry.name) }
    $path = $src; if ($atDst) { $path = $dst }
    if ((Get-Sha256 $path) -ne $entry.sha256_before) { Finish "REFUSED_RECONCILE_MISMATCH" 2 ("hash differs from plan: " + $entry.name) }
    if ($atSrc) { $pending += $entry }
}
$script:result.mode = $mode
$script:result.plan = @($plan | ForEach-Object { [pscustomobject]$_ })
if (-not $Apply) { Finish "REPORT" 0 "report only; rerun with -Apply to quarantine" }

# ---- apply ----
try {
    if (-not (Test-Path -LiteralPath $destination)) { New-Item -ItemType Directory -Path $destination -Force | Out-Null }
    if ($mode -eq "fresh") {
        Write-AtomicNew $intentPath ([ordered]@{ schema = "maker_evidence_torn_quarantine_intent_v1"
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o"); script_sha256 = $script:result.script_sha256
            root = $Root; segment = $segment.FullName; destination = $destination
            files = @($plan | ForEach-Object { [pscustomobject]$_ }) })
    }
}
catch { Finish "FAILED_INTENT" 4 $_.Exception.Message }
foreach ($entry in $pending) {
    $src = Join-Path $segment.FullName $entry.name
    $dst = Join-Path $destination $entry.name
    try { [IO.File]::Move($src, $dst) }
    catch { Finish "FAILED_MOVE" 4 ("move failed for {0}: {1}; intent kept, rerun reconciles" -f $entry.name, $_.Exception.Message) }
}
$files = @()
foreach ($entry in $plan) {
    $dst = Join-Path $destination $entry.name
    $after = Get-Sha256 $dst
    if ($after -ne $entry.sha256_before) { Finish "FAILED_HASH_MISMATCH" 4 ("hash changed across move: " + $entry.name) }
    $files += [pscustomobject][ordered]@{ name = $entry.name; size = $entry.size; tail = $entry.tail
        sha256_before = $entry.sha256_before; sha256_after = $after
        source = (Join-Path $segment.FullName $entry.name); destination = $dst }
}
try {
    Write-AtomicNew $receiptPath ([ordered]@{ schema = "maker_evidence_torn_quarantine_receipt_v1"
        completed_at_utc = (Get-Date).ToUniversalTime().ToString("o"); script_sha256 = $script:result.script_sha256
        host = $env:COMPUTERNAME; mode = $mode; writer_lock_held = $true; root = $Root; segment = $segment.FullName
        reason = "torn journal tail after unclean shutdown; moved byte-exact, never truncated or rewritten"
        files = $files })
}
catch { Finish "FAILED_RECEIPT" 4 $_.Exception.Message }
$script:result.receipt = $receiptPath
$status = "QUARANTINED"; if ($mode -eq "reconcile") { $status = "RECONCILED" }
Finish $status 0 "start the recorder task; the store seals the remaining journals"
