# Bounded native execution primitives for the adopted qualification parent.
# Dot-sourcing grants no host, Scheduler or acceptance authority. The caller
# must first verify its frozen policy/closure, acquire admission and establish
# the offline environment. No command is selected from downloaded evidence.
Set-StrictMode -Version 2.0

if (-not ('Weather.Operations.QualificationSystemResources' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Weather.Operations
{
    public sealed class QualificationSystemResources
    {
        public UInt64 CommittedBytes, CommitLimitBytes, PhysicalAvailableBytes;

        [StructLayout(LayoutKind.Sequential)]
        private struct PERFORMANCE_INFORMATION
        {
            public UInt32 cb;
            public UIntPtr CommitTotal, CommitLimit, CommitPeak, PhysicalTotal, PhysicalAvailable;
            public UIntPtr SystemCache, KernelTotal, KernelPaged, KernelNonpaged, PageSize;
            public UInt32 HandleCount, ProcessCount, ThreadCount;
        }

        [DllImport("psapi.dll", SetLastError = true)]
        private static extern bool GetPerformanceInfo(ref PERFORMANCE_INFORMATION information, UInt32 size);

        public static QualificationSystemResources Read()
        {
            PERFORMANCE_INFORMATION information = new PERFORMANCE_INFORMATION();
            information.cb = (UInt32)Marshal.SizeOf(information);
            if (!GetPerformanceInfo(ref information, information.cb))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "System memory telemetry unavailable");
            UInt64 page = information.PageSize.ToUInt64();
            if (page == 0 || information.CommitLimit.ToUInt64() == 0)
                throw new InvalidOperationException("Invalid native system memory counters");
            checked
            {
                return new QualificationSystemResources {
                    CommittedBytes = page * information.CommitTotal.ToUInt64(),
                    CommitLimitBytes = page * information.CommitLimit.ToUInt64(),
                    PhysicalAvailableBytes = page * information.PhysicalAvailable.ToUInt64()
                };
            }
        }
    }
}
'@
}

function Assert-WeatherQualificationDisk {
    param(
        [Parameter(Mandatory = $true)][string[]]$VolumePaths,
        [Parameter(Mandatory = $true)][UInt64]$MinimumFreeBytes,
        [UInt64]$ReservedScratchBytes = 0
    )
    if ($VolumePaths.Count -lt 1 -or $VolumePaths.Count -gt 16) { throw 'Explicit bounded volume inventory required' }
    $minimum = [UInt64]::MaxValue
    foreach ($path in $VolumePaths) {
        if (-not [IO.Path]::IsPathRooted($path) -or $path.StartsWith('\\')) { throw 'Local absolute volume paths required' }
        $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path)))
        if (-not $drive.IsReady) { throw 'Qualification volume is unavailable' }
        $available = [UInt64]$drive.AvailableFreeSpace
        if ($available -lt $MinimumFreeBytes -or ($available - $MinimumFreeBytes) -lt $ReservedScratchBytes) {
            throw 'Qualification disk reservation or free-space floor refused'
        }
        $minimum = [Math]::Min($minimum, $available)
    }
    return $minimum
}

function Assert-WeatherQualificationCapture {
    param(
        [Parameter(Mandatory = $true)][string]$ProductionRoot,
        [Parameter(Mandatory = $true)][object[]]$Bindings
    )
    $specs = @(
        @{ Name = 'loop_status.json'; Lock = '.loop_status.json.writer.lock'; MaxAge = 720 },
        @{ Name = 'clob_loop_status.json'; Lock = '.clob_loop_status.json.writer.lock'; MaxAge = 180 },
        @{ Name = 'observation_trigger_status.json'; Lock = '.observation_trigger_status.json.writer.lock'; MaxAge = 180 }
    )
    if ($Bindings.Count -ne 3) { throw 'Exact three-worker capture bindings required' }
    for ($index = 0; $index -lt 3; $index++) {
        $binding = $Bindings[$index]
        $spec = $specs[$index]
        if ([string]$binding.name -cne $spec.Name -or [int]$binding.pid -le 0) { throw 'Wrong capture binding order/identity' }
        $process = Get-Process -Id ([int]$binding.pid) -ErrorAction Stop
        try {
            if ($process.StartTime.ToUniversalTime().Ticks -ne [Int64]$binding.creation_utc_ticks) {
                throw 'Capture process creation identity changed'
            }
        } finally { $process.Dispose() }
        $records = @()
        foreach ($name in @($spec.Name, $spec.Lock)) {
            $path = Join-Path (Join-Path $ProductionRoot 'data/snapshots') $name
            $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
            try {
                if ($stream.Length -le 0 -or $stream.Length -gt 65536) { throw 'Capture heartbeat outside metadata bound' }
                $bytes = New-Object byte[] ([int]$stream.Length)
                $offset = 0
                while ($offset -lt $bytes.Length) {
                    $count = $stream.Read($bytes, $offset, $bytes.Length - $offset)
                    if ($count -le 0) { throw 'Incomplete capture heartbeat' }
                    $offset += $count
                }
                if ($stream.ReadByte() -ne -1) { throw 'Capture heartbeat changed during bounded read' }
                $records += ([Text.UTF8Encoding]::new($false, $true).GetString($bytes) | ConvertFrom-Json)
            } finally { $stream.Dispose() }
        }
        if ([int]$records[0].pid -ne [int]$binding.pid -or [int]$records[1].pid -ne [int]$binding.pid) {
            throw 'Capture status/lock identity drift'
        }
        $age = ([DateTime]::UtcNow - ([DateTimeOffset]::Parse([string]$records[0].last_heartbeat)).UtcDateTime).TotalSeconds
        if ($age -lt 0 -or $age -gt $spec.MaxAge) { throw 'Capture heartbeat is stale or future-dated' }
    }
}

function Invoke-WeatherQualificationProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][Weather.Operations.KillOnCloseJob]$Envelope,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Tokens,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Transcript,
        [Parameter(Mandatory = $true)][DateTimeOffset]$DeadlineUtc,
        [Parameter(Mandatory = $true)][ValidateRange(1, 1200)][int]$MaximumSeconds,
        [Parameter(Mandatory = $true)][ValidateRange(1, 120)][int]$TeardownSeconds,
        [Parameter(Mandatory = $true)][UInt64]$CommitBytes,
        [Parameter(Mandatory = $true)][UInt64]$WorkingSetBytes,
        [Parameter(Mandatory = $true)][ValidateRange(1, 134217728)][Int64]$MaximumOutputBytes,
        [Parameter(Mandatory = $true)][string[]]$VolumePaths,
        [Parameter(Mandatory = $true)][UInt64]$MinimumDiskBytes,
        [UInt64]$ReservedScratchBytes = 0,
        [ValidateSet('offhost', 'capture_s4u')][string]$ResourceMode = 'offhost',
        [string]$ProductionRoot,
        [object[]]$CaptureBindings = @()
    )
    # Native tests may exercise this mechanism off-host. The production entry
    # point must supply capture_s4u; this helper never produces acceptance PASS.
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $remaining = ($DeadlineUtc.UtcDateTime - [DateTime]::UtcNow).TotalMilliseconds
    $totalMilliseconds = [Math]::Min($remaining, ($MaximumSeconds + $TeardownSeconds) * 1000)
    $executionMilliseconds = $totalMilliseconds - ($TeardownSeconds * 1000)
    if ($executionMilliseconds -le 0 -or $CommitBytes -lt 16777216 -or $WorkingSetBytes -lt 16777216) {
        throw 'No reviewed execution and teardown envelope remains'
    }
    if ($ResourceMode -eq 'capture_s4u' -and ($MinimumDiskBytes -lt 53687091200 -or $CaptureBindings.Count -ne 3)) {
        throw 'Production resource contract is incomplete'
    }
    $start = $Envelope.Snapshot()
    if ($start.ProcessIds.Count -ne 1 -or $start.ProcessIds[0] -ne $PID -or $start.CommitLimitBytes -ne $CommitBytes) {
        throw 'Controller must own an otherwise empty exact native memory envelope'
    }
    $minimumDisk = Assert-WeatherQualificationDisk -VolumePaths $VolumePaths -MinimumFreeBytes $MinimumDiskBytes -ReservedScratchBytes $ReservedScratchBytes
    $system = [Weather.Operations.QualificationSystemResources]::Read()
    if ($ResourceMode -eq 'capture_s4u') {
        Assert-WeatherQualificationCapture -ProductionRoot $ProductionRoot -Bindings $CaptureBindings
        $reserve = [Math]::Max(0, [double]$CommitBytes - [double]$start.SampledPrivateBytes)
        if (100.0 * $system.CommittedBytes / $system.CommitLimitBytes -gt 64 -or
            100.0 * ($system.CommittedBytes + $reserve) / $system.CommitLimitBytes -gt 66 -or
            ($system.PhysicalAvailableBytes - $reserve) -lt 4294967296) {
            throw 'Projected capture-host memory reservation refused'
        }
    }
    $job = $null
    $child = $null
    $exitCode = $null
    $failure = $null
    $teardown = $false
    $peakPrivate = $start.SampledPrivateBytes
    $peakWorking = $start.SampledWorkingSetBytes
    $peakCommit = $start.PeakCommitBytes
    $peakSystem = [double](100.0 * $system.CommittedBytes / $system.CommitLimitBytes)
    $maxSampleGap = 0
    $samples = 0
    try {
        if ($clock.ElapsedMilliseconds -ge $executionMilliseconds -or [DateTime]::UtcNow -ge $DeadlineUtc.UtcDateTime.AddSeconds(-$TeardownSeconds)) {
            throw 'Admission exhausted execution deadline'
        }
        $job = [Weather.Operations.KillOnCloseJob]::CreateBounded($CommitBytes, 32)
        $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens $Tokens
        $child = $job.StartAssignedCaptured($Executable, $arguments, $WorkingDirectory, $Transcript, $MaximumOutputBytes)
        $previousSample = $clock.ElapsedMilliseconds
        $nextSlowSample = $previousSample
        while ($true) {
            $now = $clock.ElapsedMilliseconds
            $gap = $now - $previousSample
            $maxSampleGap = [Math]::Max($maxSampleGap, $gap)
            if ($gap -gt 1000) { throw 'Continuous resource monitor lost its one-second deadline' }
            $previousSample = $now
            if ($now -ge $executionMilliseconds -or [DateTime]::UtcNow -ge $DeadlineUtc.UtcDateTime.AddSeconds(-$TeardownSeconds)) {
                throw 'Candidate execution deadline exceeded'
            }
            $snapshot = $Envelope.Snapshot()
            $system = [Weather.Operations.QualificationSystemResources]::Read()
            $samples++
            $peakPrivate = [Math]::Max($peakPrivate, $snapshot.SampledPrivateBytes)
            $peakWorking = [Math]::Max($peakWorking, $snapshot.SampledWorkingSetBytes)
            $peakCommit = [Math]::Max($peakCommit, $snapshot.PeakCommitBytes)
            $percent = 100.0 * $system.CommittedBytes / $system.CommitLimitBytes
            $peakSystem = [Math]::Max($peakSystem, $percent)
            if ($snapshot.CommitLimitBytes -ne $CommitBytes -or $snapshot.NativeLimitExceeded -or
                $snapshot.SampledPrivateBytes -gt $CommitBytes -or $snapshot.SampledWorkingSetBytes -gt $WorkingSetBytes) {
                throw 'Aggregate process resource envelope exceeded'
            }
            if ($child.OutputExceeded -or $child.CaptureError) { throw 'Output cap or capture failure' }
            if ($ResourceMode -eq 'capture_s4u' -and ($percent -gt 66 -or $system.PhysicalAvailableBytes -lt 4294967296)) {
                throw 'Continuous capture-host memory guard refused'
            }
            if ($now -ge $nextSlowSample) {
                $disk = Assert-WeatherQualificationDisk -VolumePaths $VolumePaths -MinimumFreeBytes $MinimumDiskBytes
                $minimumDisk = [Math]::Min($minimumDisk, $disk)
                if ($ResourceMode -eq 'capture_s4u') { Assert-WeatherQualificationCapture -ProductionRoot $ProductionRoot -Bindings $CaptureBindings }
                $nextSlowSample = $now + 1000
            }
            if ($child.Process.HasExited) { $exitCode = $child.Process.ExitCode; break }
            Start-Sleep -Milliseconds 100
        }
        if ($exitCode -ne 0) { throw 'Candidate returned a nonzero native exit' }
    }
    catch { $failure = $_.Exception.Message }
    finally {
        if ($null -ne $job) {
            try {
                $remainingTeardown = [Math]::Min($totalMilliseconds - $clock.ElapsedMilliseconds, ($DeadlineUtc.UtcDateTime - [DateTime]::UtcNow).TotalMilliseconds)
                if ($remainingTeardown -le 0) { throw 'Absolute deadline left no provable teardown time' }
                $job.TerminateAndWait([int][Math]::Min(120000, $remainingTeardown))
                if ($job.Snapshot().ProcessIds.Count -ne 0 -or $Envelope.Snapshot().ProcessIds.Count -ne 1) {
                    throw 'Descendant teardown is incomplete'
                }
                $teardown = $true
                if ($child) {
                    $remainingCapture = [Math]::Min($totalMilliseconds - $clock.ElapsedMilliseconds, ($DeadlineUtc.UtcDateTime - [DateTime]::UtcNow).TotalMilliseconds)
                    if ($remainingCapture -le 0 -or -not $child.WaitForCapture([int][Math]::Min(120000, $remainingCapture))) { throw 'Output EOF/flush not proved before deadline' }
                    if ($child.OutputExceeded -or $child.CaptureError) { throw 'Output retained with non-authorizing capture failure' }
                }
            }
            catch { $failure = $_.Exception.Message }
            finally {
                if ($child) { $child.Dispose() }
                $job.Dispose()
            }
        }
    }
    # A controller retains its admission lease when this flag is false. Closing
    # a Job handle alone is deliberately not a claimed zero-child proof.
    return [PSCustomObject]@{
        completed = ($null -eq $failure -and $teardown -and $exitCode -eq 0)
        failure = $failure
        exit_code = $exitCode
        teardown_proved = $teardown
        elapsed_ms = [Int64]$clock.ElapsedMilliseconds
        peak_private_bytes = [UInt64]$peakPrivate
        peak_working_set_bytes = [UInt64]$peakWorking
        native_peak_commit_bytes = [UInt64]$peakCommit
        system_commit_basis_points = [Int64][Math]::Ceiling($peakSystem * 100)
        minimum_disk_bytes = [UInt64]$minimumDisk
        maximum_sample_gap_ms = [Int64]$maxSampleGap
        resource_samples = [Int64]$samples
    }
}
