# One-off guarded launcher for the read-only storage-audit size walk (lane L47).
# One-off exception to workstation_heavy admission, master ruling 2026-11-02, read-only metadata walk.
#
# It mirrors workload_admission.ps1's exclusive caller without waiting: it takes the exclusive barrier
# (Global\WeatherProjectHeavyWorkloadV1.Exclusive) and every slot mutex (slot 1 = Global\WeatherProjectHeavyWorkloadV1,
# slots 2..8 = "<that>.Slot<k>") with WaitOne(0). It refuses (exit 3, nothing started) if any is held or if a
# -Queue ticket is waiting. While it holds them, slot admission answers "exclusive_pending", so queued jobs wait.
# It verifies the walker sha256, starts the walker at BelowNormal priority, enforces a timebox (on expiry it kills
# only the walker process it started and marks the run PARTIAL), and releases every mutex in finally.
# Output and receipt go only under C:\t\storage-audit\out.
#
# ROW-28 COPY (lane L59): run_walk_guarded_v1.ps1 (sha256 0A87F905527500D43FDBA039131E09930A5E1557DEB3E087FB30159AF4809A87)
# plus items 1-5 and the OutRoot change of master's ruling 2026-11-03, option 2 (a one-off for row 28, L47 precedent).
# The "walker" is the row-28 runner; -Stage selects its stage (order (b): an explicit CLI flag).
# 1 JOB: the walker starts inside a repo kill-on-close Job (scripts\ops\windows_kill_on_close_job.ps1, sha-pinned):
#   LimitFlags = KILL_ON_JOB_CLOSE only, no BREAKAWAY_OK / SILENT_BREAKAWAY_OK (lines 186-187); CREATE_SUSPENDED (250, 268),
#   AssignProcessToJobObject before resume (280), ResumeThread (292); TerminateAndWait (641) ends the whole tree.
#   Start/drain/teardown pattern as scripts\ops\maker_replay_exam_step.ps1 213-237.
# 2 MEMORY floor at start: available physical >= 6 GB and commit <= 90%, workstation_heavy.ps1 defaults (lines 27-28),
#   read by workload_admission.ps1 Get-WeatherWorkstationMemoryReading (2885) and compared as at 3033 / 3037.
# 3 DISK floor at start: C: free >= 45 GiB. Every refusal exits 3 before any child starts.
# 4 TIMEBOX ceiling raised to 21600 s, the largest per-stage timebox pre-stated in RUN_LOG.md.
# 5 PEAK RAM: PeakJobMemoryUsed from JOBOBJECT_EXTENDED_LIMIT_INFORMATION (QueryInformationJobObject class 9) in the receipt.
# Output and receipt go only under C:\t\L59\row28\run.
#
# v2 (lane L59, 2026-11-03): run_row28_guarded_v1.ps1 (sha256 34235d44ba637ad8dc0ddae3bb37eaab4034be5fae6a641d6cb644bf41b9415e)
# plus the v1 review's launcher minors, and nothing else:
# L1 MutexNames must equal the 9 default names exactly; an override is accepted only if every name starts "TEST-ONLY".
# L2 every Dispose has its own try/catch, and the mutexes are released in their own finally.
# L3 a failed Job-memory read is recorded as job_memory_error, so receipt.json is always written.
# L4 the receipt records CapturedOutput Stdout/StderrTruncated and Stdout/StderrBytesSeen.
#
# v3 (lane L59, 3 Nov 2026): run_row28_guarded_v2.ps1 (sha256 8bfea24893b9a45e61b50661d9afe4668d545f92372eb7edd8f849d14b5ac3f0)
# plus the v2 delta review's LN1 and master's sealed-window ruling 2 (CLARIFICATION_2.md), and nothing else:
# LN1 on the success path the Job is TerminateAndWait(30000)-ed BEFORE output.Complete(2000), as on the timebox path.
# G1 after the child ends, walker.stdout and walker.stderr are scanned for ISO dates (YYYY-MM-DD, digit-bounded) on or
#    after 2026-01-01, with no allowlist (only the prereg folder-name token is masked). A hit HALTs a pre-score stage
#    (status HALT, exit 6); for look and score it is a FLAG for master (N1: no HALT once a score exists).
#    Only counts are recorded, never the matched text.
# G2 every receipt time is ISO 8601 basic format (yyyyMMddTHHmmss.fffffff+zz:zz); the receipt text is scanned the same
#    way before it is written, and a receipt with a hit is replaced by a minimal one that carries only counts.
#
# v4 (lane L59, 3 Nov 2026): run_row28_guarded_v3.ps1 (sha256 fb0397829c1fcbc19f124f8bbe76d8824ca406b34bfb1923cea97f11e6856a3c)
# plus the v3 delta review's F3 (h), F4, F6 and F7 as accepted by master (CLARIFICATION_3.md), and nothing else:
# F3h the log guard (G1) masks, besides the folder-name token, only the exact token centre=<label> whose label is in
#     the arm centre set, the same rule as the runner's GuardedStream (LOG_CENTRE_TOKEN). The set is carried below and
#     must hash (sha256 of the ordinally sorted labels joined by LF) to GUARD_CENTRE_SET_SHA256 of runner v4, else the
#     launcher refuses before any child starts. The receipt guard (G2) has no centre exception.
# F4  the minimal receipt that replaces a guarded receipt records receipt_guard_hits (runner v4 refuses a previous
#     stage whose receipt is not COMPLETE and guard-clean).
# F6  in look and score a withheld receipt keeps the stage status and adds output_guard_flag (a FLAG, not a HALT).
# F7  the receipt's exception string is reverted to the v2 text (C2 section 5). That text holds a 2026 date, so G2
#     masks exactly that one string (and nothing else) before it counts.
#
# v5 (lane L59, 3 Nov 2026): run_row28_guarded_v4.ps1 (sha256 3f356f38676ac680281b71c3981fd3f6d557a86246e4fc48584d6b4d79aad4ca)
# plus one change, and nothing else:
# G4  the minimal receipt that replaces a guarded receipt also carries job_memory (peak_job_memory_bytes), so every
#     stage's receipt records its PeakJobMemoryUsed. job_memory is itself guarded before it is copied.
#
# v6 (lane L59, 3 Nov 2026): run_row28_guarded_v5.ps1 (sha256 0b0d0f977ecba384a8ae4257a7d7f49af2fb92ca7d23f43916696ac9890ade5d)
# plus one change, and nothing else:
# K1  the receipt writes output_guard.from in basic format ("20260101"), as runner v6 does in walk.json. v5 wrote
#     $GuardFrom itself, which matches the guard pattern, so G2 counted 1 hit in every receipt (controls attempt 1).
#     $GuardFrom stays "2026-01-01": it is the ordinal comparison bound of the guard count and must stay ISO.
param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$RootsPath = "C:\t\storage-audit\roots_v1.json",
    [string]$WalkerPath = "C:\t\storage-audit\size_walk_v1.py",
    [string]$ExpectSha = "0becbe33e46e95dd1a4546a0bb983efcf80a825403bde4b09f9469535a5b39e8",
    [string]$PythonPath = "C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe",
    [ValidateRange(0, 21600)][int]$TimeboxSeconds = 2700,
    [string]$QueueRoot = "C:\ProgramData\WeatherProject\heavy_workload_queue_v1",
    # Tests pass TEST-ONLY names here; the default is the real set.
    [string[]]$MutexNames = @(
        "Global\WeatherProjectHeavyWorkloadV1.Exclusive",
        "Global\WeatherProjectHeavyWorkloadV1",
        "Global\WeatherProjectHeavyWorkloadV1.Slot2",
        "Global\WeatherProjectHeavyWorkloadV1.Slot3",
        "Global\WeatherProjectHeavyWorkloadV1.Slot4",
        "Global\WeatherProjectHeavyWorkloadV1.Slot5",
        "Global\WeatherProjectHeavyWorkloadV1.Slot6",
        "Global\WeatherProjectHeavyWorkloadV1.Slot7",
        "Global\WeatherProjectHeavyWorkloadV1.Slot8"
    ),
    [Parameter(Mandatory = $true)][ValidateSet("controls", "build", "integrity", "labels", "look", "score")][string]$Stage
)
$ErrorActionPreference = "Stop"
$OutRoot = "C:\t\L59\row28\run"
# Items 1 and 2: repo helpers, dot-sourced only after their sha256 matches.
$OpsDir = "C:\wt\L59row28\scripts\ops"
$JobHelperPath = Join-Path $OpsDir "windows_kill_on_close_job.ps1"
$JobHelperSha = "05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669"
$AdmissionPath = Join-Path $OpsDir "workload_admission.ps1"
$AdmissionSha = "48786bcb1946ad9b02934da53d5887d8ab49f69a72750c36809bc6d7f160b441"
$MinAvailableMemoryGB = 6
$MaxCommitPercent = 90
$MinFreeDiskBytes = [long](45 * 1GB)

$RefusedTag = "L47-GUARDED-WALK-REFUSED: "
# G1/G2: the guard pattern, its start date, the masked token and the stamp format.
$GuardPattern = "(?<![0-9])(20[0-9]{2}-[01][0-9]-[0-3][0-9])(?![0-9])"
$GuardFrom = "2026-01-01"
$GuardMaskToken = "row28-yearround-history-" + "2026-11-02"
# F3h: the arm centre set and the exact log token (identical to runner v4's LOG_CENTRE_TOKEN).
$GuardCentreSetSha256 = "38a17ec2a04d764bac8ea43c8add0f89eb3fa542480eec73aaf0ab12febf6d83"
$GuardCentreLabels = [string[]]@(
    "2026-01-08",
    "2026-01-23",
    "2026-02-07",
    "2026-02-22",
    "2026-03-09",
    "2026-03-24",
    "2026-04-08",
    "2026-04-23",
    "2026-05-08",
    "2026-05-23",
    "2026-06-07",
    "2026-06-22",
    "2026-07-07",
    "2026-07-22",
    "2026-08-08",
    "2026-08-23",
    "2026-09-07",
    "2026-09-22",
    "2026-10-10",
    "2026-10-25",
    "2026-11-09",
    "2026-11-24",
    "2026-12-09",
    "2026-12-24"
)
$LogCentreToken = "(?<![A-Za-z0-9_])centre=(20[0-9]{2}-[01][0-9]-[0-3][0-9])(?![0-9A-Za-z_-])"
# F7: the v2 exception text, reverted; G2 masks exactly this string.
$ReceiptExceptionText = "one-off exception to workstation_heavy admission, master ruling 2026-11-02, read-only metadata walk"
$StampFormat = "yyyyMMdd'T'HHmmss.fffffffzzz"

function Get-Row28GuardCount([string]$text) {
    $n = 0
    foreach ($m in [regex]::Matches($text.Replace($GuardMaskToken, ""), $GuardPattern)) {
        if ([string]::CompareOrdinal($m.Groups[1].Value, $GuardFrom) -ge 0) { $n++ }
    }
    $n
}

function Get-Row28CentreSetSha {
    $sorted = [string[]]@($GuardCentreLabels)
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    $bytes = [Text.Encoding]::UTF8.GetBytes(($sorted -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) }
    finally { $sha.Dispose() }
}

function Get-Row28LogGuardCount([string]$text) {
    # F3h: the folder-name token, then exact centre=<arm label> tokens, are masked; everything else counts.
    $t = $text.Replace($GuardMaskToken, "")
    $evaluator = [Text.RegularExpressions.MatchEvaluator] {
        param($m)
        if ($GuardCentreLabels -ccontains $m.Groups[1].Value) { "centre=[label]" } else { $m.Value }
    }
    $t = [regex]::Replace($t, $LogCentreToken, $evaluator)
    Get-Row28GuardCount $t
}

function Get-Row28LogGuard([string]$dir) {
    $files = [ordered]@{}
    $total = 0
    foreach ($name in @("walker.stdout", "walker.stderr")) {
        $path = Join-Path $dir $name
        $n = 0
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $fs = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
            try {
                $ms = [IO.MemoryStream]::new()
                $fs.CopyTo($ms)
                $bytes = $ms.ToArray()
            }
            finally { $fs.Dispose() }
            # Latin-1 maps every byte to one char, so the ASCII digits and dashes of a date survive any encoding.
            $n = Get-Row28LogGuardCount ([Text.Encoding]::GetEncoding(28591).GetString($bytes))
        }
        $files[$name] = $n
        $total += $n
    }
    [ordered]@{ pattern = $GuardPattern; from = $GuardFrom.Replace("-", ""); files = $files; hits_total = $total }
}
function Refuse([string]$why) { throw ($RefusedTag + $why) }

# L1: the real admission set, exactly as the parameter default above.
$DefaultMutexNames = @(
    "Global\WeatherProjectHeavyWorkloadV1.Exclusive",
    "Global\WeatherProjectHeavyWorkloadV1",
    "Global\WeatherProjectHeavyWorkloadV1.Slot2",
    "Global\WeatherProjectHeavyWorkloadV1.Slot3",
    "Global\WeatherProjectHeavyWorkloadV1.Slot4",
    "Global\WeatherProjectHeavyWorkloadV1.Slot5",
    "Global\WeatherProjectHeavyWorkloadV1.Slot6",
    "Global\WeatherProjectHeavyWorkloadV1.Slot7",
    "Global\WeatherProjectHeavyWorkloadV1.Slot8"
)

function Get-Row28OutputCounts($output) {
    [ordered]@{
        stdout_truncated = [bool]$output.StdoutTruncated; stderr_truncated = [bool]$output.StderrTruncated
        stdout_bytes_seen = [long]$output.StdoutBytesSeen; stderr_bytes_seen = [long]$output.StderrBytesSeen
    }
}

function Get-Sha([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Get-QueueTickets([string]$root) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return @() }
    @(Get-ChildItem -LiteralPath $root -File -Force -Filter "ticket-*.json" -ErrorAction SilentlyContinue)
}

# Item 5: PeakJobMemoryUsed (JOBOBJECT_EXTENDED_LIMIT_INFORMATION, class 9) and the Job's process accounting (class 1).
# Struct layouts are copied from windows_kill_on_close_job.ps1 lines 32-79.
function Initialize-Row28JobMemoryReader {
    if ("Row28.JobMemoryV1" -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Row28
{
    public static class JobMemoryV1
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public Int64 PerProcessUserTimeLimit;
            public Int64 PerJobUserTimeLimit;
            public UInt32 LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public UInt32 ActiveProcessLimit;
            public UIntPtr Affinity;
            public UInt32 PriorityClass;
            public UInt32 SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public UInt64 ReadOperationCount;
            public UInt64 WriteOperationCount;
            public UInt64 OtherOperationCount;
            public UInt64 ReadTransferCount;
            public UInt64 WriteTransferCount;
            public UInt64 OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        {
            public Int64 TotalUserTime;
            public Int64 TotalKernelTime;
            public Int64 ThisPeriodTotalUserTime;
            public Int64 ThisPeriodTotalKernelTime;
            public UInt32 TotalPageFaultCount;
            public UInt32 TotalProcesses;
            public UInt32 ActiveProcesses;
            public UInt32 TotalTerminatedProcesses;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool QueryInformationJobObject(
            IntPtr job, Int32 informationClass, IntPtr information, UInt32 informationLength, out UInt32 returnLength);

        // { PeakJobMemoryUsed, PeakProcessMemoryUsed, LimitFlags, TotalProcesses, ActiveProcesses }
        public static UInt64[] Read(IntPtr job)
        {
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION ext = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION acc = new JOBOBJECT_BASIC_ACCOUNTING_INFORMATION();
            Int32 extSize = Marshal.SizeOf(ext);
            Int32 accSize = Marshal.SizeOf(acc);
            IntPtr extBuf = Marshal.AllocHGlobal(extSize);
            IntPtr accBuf = Marshal.AllocHGlobal(accSize);
            try
            {
                UInt32 returned;
                Marshal.StructureToPtr(ext, extBuf, false);
                if (!QueryInformationJobObject(job, 9, extBuf, (UInt32)extSize, out returned))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject(extended limits) failed");
                ext = (JOBOBJECT_EXTENDED_LIMIT_INFORMATION)Marshal.PtrToStructure(extBuf, typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
                Marshal.StructureToPtr(acc, accBuf, false);
                if (!QueryInformationJobObject(job, 1, accBuf, (UInt32)accSize, out returned))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject(accounting) failed");
                acc = (JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)Marshal.PtrToStructure(accBuf, typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION));
                return new UInt64[] {
                    ext.PeakJobMemoryUsed.ToUInt64(), ext.PeakProcessMemoryUsed.ToUInt64(),
                    ext.BasicLimitInformation.LimitFlags, acc.TotalProcesses, acc.ActiveProcesses
                };
            }
            finally
            {
                Marshal.FreeHGlobal(extBuf);
                Marshal.FreeHGlobal(accBuf);
            }
        }
    }
}
'@
}

function Get-Row28JobMemory($job) {
    # The helper keeps its Job handle private (windows_kill_on_close_job.ps1 line 30); read it, never change it.
    # L3: a failed read never stops the receipt; it is recorded as job_memory_error.
    try {
        $field = [Weather.Operations.KillOnCloseJob].GetField("handle", [Reflection.BindingFlags]"NonPublic, Instance")
        $values = [Row28.JobMemoryV1]::Read([IntPtr]$field.GetValue($job))
        [ordered]@{
            peak_job_memory_bytes = [long]$values[0]
            peak_process_memory_bytes = [long]$values[1]
            job_limit_flags = ("0x{0:X8}" -f [long]$values[2])
            job_total_processes = [long]$values[3]
            job_active_processes = [long]$values[4]
            read_at = (Get-Date).ToString($StampFormat)
        }
    }
    catch {
        [ordered]@{ job_memory_error = [string]$_.Exception.Message; read_at = (Get-Date).ToString($StampFormat) }
    }
}

$exitCode = 1
$child = $null
$job = $null
$output = $null
$held = [System.Collections.Generic.List[object]]::new()
try {
# --- checks that start nothing ---------------------------------------------------------------
$outFull = [IO.Path]::GetFullPath($OutDir)
if (-not $outFull.StartsWith($OutRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
    Refuse "OutDir must be below $OutRoot"
}
if (Test-Path -LiteralPath $outFull) { Refuse "OutDir already exists: $outFull" }
$isDefaultSet = (@($MutexNames).Count -eq $DefaultMutexNames.Count) -and
    ((@($MutexNames) -join "|") -ceq ($DefaultMutexNames -join "|"))
$isTestSet = (@($MutexNames).Count -gt 0) -and (@($MutexNames | Where-Object { -not $_.StartsWith("TEST-ONLY") }).Count -eq 0)
if (-not ($isDefaultSet -or $isTestSet)) { Refuse "MutexNames must be the 9 default names, or all TEST-ONLY names" }
foreach ($p in @($RootsPath, $WalkerPath, $PythonPath, $JobHelperPath, $AdmissionPath)) {
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { Refuse "missing file: $p" }
}
$walkerSha = Get-Sha $WalkerPath
if ($walkerSha -cne $ExpectSha) { Refuse "walker sha256 $walkerSha differs from expected $ExpectSha" }
if (@($GuardCentreLabels | Select-Object -Unique).Count -ne 24 -or (Get-Row28CentreSetSha) -cne $GuardCentreSetSha256) {
    Refuse "the launcher's arm centre set differs from GUARD_CENTRE_SET_SHA256 (F3h)"
}
if ((Get-Sha $JobHelperPath) -cne $JobHelperSha) { Refuse "job helper sha256 differs from $JobHelperSha" }
if ((Get-Sha $AdmissionPath) -cne $AdmissionSha) { Refuse "admission helper sha256 differs from $AdmissionSha" }
if (@(Get-QueueTickets $QueueRoot).Count -gt 0) { Refuse "a -Queue ticket is waiting in $QueueRoot" }
. $AdmissionPath
. $JobHelperPath
Initialize-Row28JobMemoryReader

# --- mutexes: all or nothing, non-blocking ----------------------------------------------------
    foreach ($name in $MutexNames) {
        $m = [Threading.Mutex]::new($false, $name)
        $owned = $false
        try { $owned = $m.WaitOne(0, $false) }
        catch [Threading.AbandonedMutexException] { $owned = $true }
        if (-not $owned) {
            $m.Dispose()
            Refuse "mutex held by another process: $name"
        }
        $held.Add($m)
    }
    if (@(Get-QueueTickets $QueueRoot).Count -gt 0) { Refuse "a -Queue ticket appeared while acquiring" }

    # --- items 2 and 3: floors at start (a refusal starts no child and creates no OutDir) ----------
    $memory = Get-WeatherWorkstationMemoryReading
    if ([long]$memory.AvailablePhysicalBytes -lt [long][Math]::Floor($MinAvailableMemoryGB * 1GB)) {
        Refuse ("available physical memory {0} bytes is below {1} GB" -f $memory.AvailablePhysicalBytes, $MinAvailableMemoryGB)
    }
    if ([double]$memory.CommitPercent -gt $MaxCommitPercent) {
        Refuse ("commit charge {0}% is above {1}%" -f $memory.CommitPercent, $MaxCommitPercent)
    }
    $freeDisk = [long]([IO.DriveInfo]::new("C").AvailableFreeSpace)
    if ($freeDisk -lt $MinFreeDiskBytes) { Refuse "C: free space $freeDisk bytes is below 45 GiB" }

    [void][IO.Directory]::CreateDirectory($outFull)
    $start = Get-Date
    $receipt = [ordered]@{
        schema = "storage_audit_guarded_walk_receipt/1"
        exception = $ReceiptExceptionText
        walker = $WalkerPath; walker_sha256 = $walkerSha
        launcher = $PSCommandPath; launcher_sha256 = (Get-Sha $PSCommandPath)
        roots = $RootsPath; roots_sha256 = (Get-Sha $RootsPath)
        python = $PythonPath; mutexes_held = @($MutexNames)
        timebox_seconds = $TimeboxSeconds; start = $start.ToString($StampFormat)
    }
    $receipt.stage = $Stage
    $receipt.job_helper_sha256 = $JobHelperSha
    $receipt.admission_helper_sha256 = $AdmissionSha
    $receipt.start_available_physical_bytes = [long]$memory.AvailablePhysicalBytes
    $receipt.start_commit_percent = [double]$memory.CommitPercent
    $receipt.start_free_disk_bytes = $freeDisk
    $outJson = Join-Path $outFull "walk.json"
    $outCsv = Join-Path $outFull "walk.csv"
    $argList = @("-I", "`"$WalkerPath`"", "--roots", "`"$RootsPath`"", "--out-json", "`"$outJson`"",
                 "--out-csv", "`"$outCsv`"", "--expect-sha", $ExpectSha, "--stage", $Stage)
    # Item 1: create suspended, assign to the kill-on-close Job, resume (helper lines 250-292); no breakaway.
    $job = New-WeatherKillOnCloseJob
    $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
        (Join-Path $outFull "walker.stdout"), (Join-Path $outFull "walker.stderr"), 8388608)
    $child = Start-WeatherProcessInJob -Job $job -FilePath $PythonPath -ArgumentString ($argList -join " ") `
        -WorkingDirectory $outFull -OutputCapture $output
    $null = $child.Handle  # cache the handle so ExitCode is readable after exit
    try { $child.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal } catch { }
    $receipt.walker_pid = $child.Id
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $finished = $true
    while (-not $child.HasExited) {
        if ($clock.Elapsed.TotalSeconds -ge $TimeboxSeconds) { $finished = $false; break }
        $output.Drain(); Start-Sleep -Milliseconds 100; $child.Refresh()
    }
    if (-not $finished) {
        $receipt.job_memory = Get-Row28JobMemory $job
        try { $job.TerminateAndWait(30000) } catch { }
        try { $output.Complete(2000) } catch { }
        $receipt.output_capture = Get-Row28OutputCounts $output
        $receipt.status = "PARTIAL"
        $receipt.reason = "timebox of $TimeboxSeconds s reached; the walker process (pid $($child.Id)) was killed"
        $exitCode = 4
    }
    else {
        $child.WaitForExit()
        $receipt.job_memory = Get-Row28JobMemory $job
        try { $job.TerminateAndWait(30000) } catch { }  # LN1: end the tree before draining the pipes
        try { $output.Complete(2000) } catch { }
        $receipt.output_capture = Get-Row28OutputCounts $output
        $receipt.walker_exit_code = $child.ExitCode
        if ($child.ExitCode -eq 0 -and (Test-Path -LiteralPath $outJson) -and (Test-Path -LiteralPath $outCsv)) {
            $receipt.status = "COMPLETE"
            $receipt.walk_json_sha256 = Get-Sha $outJson
            $receipt.walk_csv_sha256 = Get-Sha $outCsv
            $exitCode = 0
        }
        else {
            $receipt.status = "PARTIAL"
            $receipt.reason = "walker exited $($child.ExitCode) or wrote no output"
            $exitCode = 5
        }
    }
    # G1: the walker's logs, after the child tree has ended and the pipes are drained.
    $guard = Get-Row28LogGuard $outFull
    $receipt.output_guard = $guard
    $postScore = $Stage -in @("look", "score")
    if ($guard.hits_total -gt 0) {
        if ($postScore) {
            $receipt.output_guard_flag = "log guard hit(s) in a look/score stage: FLAG for master (N1)"
        }
        else {
            $receipt.status = "HALT"
            $receipt.reason = "output guard: $($guard.hits_total) dated string(s) in the walker logs"
            $exitCode = 6
        }
    }
    $receipt.end = (Get-Date).ToString($StampFormat)
    # G2: the receipt text is guarded before it is written.
    $receiptJson = $receipt | ConvertTo-Json -Depth 4
    $receiptHits = Get-Row28GuardCount ($receiptJson.Replace($ReceiptExceptionText, ""))
    if ($receiptHits -gt 0) {
        $minimal = [ordered]@{
            schema = $receipt.schema; stage = $Stage; status = "HALT"
            reason = "receipt withheld by the output guard ($receiptHits hit(s))"; output_guard = $guard
            receipt_guard_hits = $receiptHits
            job_memory = $(if ((Get-Row28GuardCount ([string]($receipt.job_memory | ConvertTo-Json -Depth 3))) -eq 0) {
                    $receipt.job_memory } else { "[withheld by output guard]" })
        }
        if ($postScore) {
            # F6: after a score exists this is a FLAG for master, not a HALT (N1).
            $minimal.status = $receipt.status
            $minimal.output_guard_flag = "receipt withheld by the output guard in a look/score stage: FLAG for master (N1)"
        }
        $receiptJson = $minimal | ConvertTo-Json -Depth 4
        if (-not $postScore) { $exitCode = 6 }
    }
    $receiptJson | Out-File -LiteralPath (Join-Path $outFull "receipt.json") -Encoding utf8
    Write-Output ("{0} exit {1} out {2}" -f $receipt.status, $exitCode, $outFull)
}
catch {
    $msg = [string]$_.Exception.Message
    if ($msg.StartsWith($RefusedTag)) {
        [Console]::Error.WriteLine("REFUSED: " + $msg.Substring($RefusedTag.Length))
        $exitCode = 3
    }
    else {
        [Console]::Error.WriteLine("ERROR: " + $msg)
        $exitCode = 2
    }
}
finally {
    # Never leave the walker running unguarded: end only the Job this launcher created (the walker and its tree).
    try {
        if ($null -ne $job) { try { $job.TerminateAndWait(30000) } catch { } }
        if ($null -ne $output) { try { $output.Complete(2000) } catch { } }
    }
    finally {
        try {
            if ($null -ne $output) { try { $output.Dispose() } catch { } }
            if ($null -ne $child) { try { $child.Dispose() } catch { } }
            if ($null -ne $job) { try { $job.Dispose() } catch { } }
        }
        finally {
            foreach ($m in $held) {
                try { $m.ReleaseMutex() } catch { }
                try { $m.Dispose() } catch { }
            }
        }
    }
}
exit $exitCode
