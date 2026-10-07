# C3 rehearsal launcher and cleanup, v3.1. Starts ONE child directly inside a fresh
# kill-on-close Job owned by this script, waits with a bound, then closes the Job.
# Closing the last Job handle is the ONLY termination this script performs. It never
# looks a process up by name, image, command line or start time, and it never ends a
# process by PID. The snapshots and console lists below are read-only evidence.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Tokens,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][ValidateRange(5, 600)][int]$TimeoutSeconds,
    [string]$WatchMarkersUnder = '',
    [ValidateRange(-1, 64)][int]$ExpectStarted = -1      # v3.1 Q6: -1 records only; otherwise a difference is verify=FAIL
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$C3RunVersion = 'c3-run-v3.1-F3'
$scratch = Split-Path -Parent $PSCommandPath
$ledger = Join-Path $scratch 'launch-ledger.txt'
if ($Label -notmatch '^[A-Za-z0-9._-]+$') { throw "Label must match [A-Za-z0-9._-]+: $Label" }
if (-not [IO.Path]::IsPathRooted($Exe) -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Exe must be an existing absolute path: $Exe" }

# The C# source. __NS__ is replaced by a namespace derived from the SHA-256 of this text, so an
# edited source always compiles a NEW type: Add-Type can never silently reuse stale code (N3).
$csSource = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace __NS__
{
    public static class Info { public const string Version = "c3-run-v3.1-F3"; }

    // Read-only host facts: the console's attached PIDs (M3) and the true OS version (N1).
    public static class Native
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint GetConsoleProcessList([Out] uint[] list, uint count);
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct OSVERSIONINFOW
        {
            public uint Size, Major, Minor, Build, Platform;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Csd;
        }
        [DllImport("ntdll.dll")]
        static extern int RtlGetVersion(ref OSVERSIONINFOW info);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint WaitForSingleObject(IntPtr handle, uint ms);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);

        // F3: conhost keeps a console-list entry for a process group that was sent Ctrl+Break from this console
        // while it lived on ANOTHER console (the 6b CREATE_NO_WINDOW stub). The entry outlives the process. True
        // ONLY when the PID provably has no live process: no such PID (ERROR_INVALID_PARAMETER), or its process
        // object is signalled (exited). Any other failure (access denied, ...) is false: treated as live, fail closed.
        public static bool IsGone(uint pid)
        {
            IntPtr h = OpenProcess(0x00100000 | 0x00001000, false, pid);   // SYNCHRONIZE | QUERY_LIMITED_INFORMATION
            if (h == IntPtr.Zero) return Marshal.GetLastWin32Error() == 87;
            try { return WaitForSingleObject(h, 0) == 0; } finally { CloseHandle(h); }
        }

        public static uint[] ConsoleProcesses()
        {
            uint[] list = new uint[256];
            uint n = GetConsoleProcessList(list, (uint)list.Length);
            if (n == 0) throw new Win32Exception(Marshal.GetLastWin32Error(), "GetConsoleProcessList failed (no console?)");
            if (n > list.Length) throw new InvalidOperationException("more than 256 processes share this console");
            Array.Resize(ref list, (int)n);
            return list;
        }

        public static Version OsVersion()
        {
            OSVERSIONINFOW v = new OSVERSIONINFOW();
            v.Size = (uint)Marshal.SizeOf(typeof(OSVERSIONINFOW));
            if (RtlGetVersion(ref v) != 0) throw new InvalidOperationException("RtlGetVersion failed");
            return new Version((int)v.Major, (int)v.Minor, (int)v.Build);
        }
    }

    public sealed class OwnJob
    {
        const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        const int JobObjectBasicAccountingInformation = 1;
        const int JobObjectBasicProcessIdList = 3;
        const int JobObjectExtendedLimitInformation = 9;
        const uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
        static readonly IntPtr PROC_THREAD_ATTRIBUTE_JOB_LIST = new IntPtr(0x0002000D);
        const uint WAIT_TIMEOUT = 0x00000102;

        [StructLayout(LayoutKind.Sequential)]
        struct BASIC_LIMIT
        {
            public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize; public uint ActiveProcessLimit;
            public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct IO_COUNTERS { public ulong R, W, O, RT, WT, OT; }
        [StructLayout(LayoutKind.Sequential)]
        struct EXTENDED_LIMIT
        {
            public BASIC_LIMIT Basic; public IO_COUNTERS Io; public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit; public UIntPtr PeakProcessMemoryUsed; public UIntPtr PeakJobMemoryUsed;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct STARTUPINFO
        {
            public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
            public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
            public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct STARTUPINFOEX { public STARTUPINFO StartupInfo; public IntPtr lpAttributeList; }
        [StructLayout(LayoutKind.Sequential)]
        struct PROCESS_INFORMATION { public IntPtr hProcess; public IntPtr hThread; public int dwProcessId; public int dwThreadId; }

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern IntPtr CreateJobObjectW(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref EXTENDED_LIMIT info, uint size);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool QueryInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint size, IntPtr returned);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returnSize);
        [DllImport("kernel32.dll")]
        static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern bool CreateProcessW(string application, StringBuilder commandLine, IntPtr processAttributes, IntPtr threadAttributes,
            bool inheritHandles, uint creationFlags, IntPtr environment, string currentDirectory,
            ref STARTUPINFOEX startupInfo, out PROCESS_INFORMATION processInformation);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);

        IntPtr job;
        IntPtr child = IntPtr.Zero;
        public int ChildPid { get; private set; }

        OwnJob(IntPtr handle) { job = handle; }

        // 1. Create the Job: unnamed, non-inheritable handle, kill-on-close.
        public static OwnJob Create()
        {
            IntPtr handle = CreateJobObjectW(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");
            EXTENDED_LIMIT limits = new EXTENDED_LIMIT();
            limits.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if (!SetInformationJobObject(handle, JobObjectExtendedLimitInformation, ref limits, (uint)Marshal.SizeOf(typeof(EXTENDED_LIMIT))))
            {
                int error = Marshal.GetLastWin32Error();
                CloseHandle(handle);   // empty Job: closing it ends nothing
                throw new Win32Exception(error, "KILL_ON_JOB_CLOSE configuration failed");
            }
            return new OwnJob(handle);
        }

        // 2. The child is CREATED inside the Job (PROC_THREAD_ATTRIBUTE_JOB_LIST, Windows 10+).
        //    If the Job cannot take it, CreateProcess fails and no process exists.
        //    Same console, same process group, so a console Ctrl+C reaches it.
        public int Launch(string executable, string commandLine, string workingDirectory)
        {
            if (job == IntPtr.Zero) throw new ObjectDisposedException("OwnJob");
            if (child != IntPtr.Zero) throw new InvalidOperationException("one child per Job");
            IntPtr size = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            IntPtr list = Marshal.AllocHGlobal(size);
            IntPtr jobs = Marshal.AllocHGlobal(IntPtr.Size);
            bool initialized = false;
            try
            {
                if (!InitializeProcThreadAttributeList(list, 1, 0, ref size))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "InitializeProcThreadAttributeList failed");
                initialized = true;
                Marshal.WriteIntPtr(jobs, job);
                if (!UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST, jobs, new IntPtr(IntPtr.Size), IntPtr.Zero, IntPtr.Zero))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "UpdateProcThreadAttribute(JOB_LIST) failed");
                STARTUPINFOEX startup = new STARTUPINFOEX();
                startup.StartupInfo.cb = Marshal.SizeOf(typeof(STARTUPINFOEX));
                startup.lpAttributeList = list;
                PROCESS_INFORMATION info;
                if (!CreateProcessW(executable, new StringBuilder(commandLine), IntPtr.Zero, IntPtr.Zero, false,
                        EXTENDED_STARTUPINFO_PRESENT, IntPtr.Zero, workingDirectory, ref startup, out info))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcess into the Job failed");
                CloseHandle(info.hThread);
                child = info.hProcess;
                ChildPid = info.dwProcessId;
                return info.dwProcessId;
            }
            finally
            {
                if (initialized) DeleteProcThreadAttributeList(list);
                Marshal.FreeHGlobal(list);
                Marshal.FreeHGlobal(jobs);
            }
        }

        public bool WaitChild(int milliseconds)
        {
            uint result = WaitForSingleObject(child, (uint)milliseconds);
            if (result == 0) return true;
            if (result == WAIT_TIMEOUT) return false;
            throw new Win32Exception(Marshal.GetLastWin32Error(), "WaitForSingleObject failed");
        }

        public int ChildExitCode()
        {
            uint code;
            if (!GetExitCodeProcess(child, out code)) throw new Win32Exception(Marshal.GetLastWin32Error(), "GetExitCodeProcess failed");
            return unchecked((int)code);
        }

        // JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: { TotalProcesses @36, ActiveProcesses @40 }.
        // TotalProcesses counts every process ever associated with the Job (nested Jobs included).
        public int[] Accounting()
        {
            const int size = 48;   // sizeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION); the call requires the exact size
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                if (!QueryInformationJobObject(job, JobObjectBasicAccountingInformation, buffer, size, IntPtr.Zero))
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Win32Exception(error, "Job accounting query failed (Win32 error " + error + ")");
                }
                return new int[] { Marshal.ReadInt32(buffer, 36), Marshal.ReadInt32(buffer, 40) };
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        // v3.1: JOBOBJECT_EXTENDED_LIMIT_INFORMATION.PeakJobMemoryUsed, the peak committed (private) bytes of
        // all members together (nested Jobs included). Read-only; for the resource profile.
        public long PeakJobPrivateBytes()
        {
            int size = Marshal.SizeOf(typeof(EXTENDED_LIMIT));
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                if (!QueryInformationJobObject(job, JobObjectExtendedLimitInformation, buffer, (uint)size, IntPtr.Zero))
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Win32Exception(error, "Job extended-limit query failed (Win32 error " + error + ")");
                }
                EXTENDED_LIMIT info = (EXTENDED_LIMIT)Marshal.PtrToStructure(buffer, typeof(EXTENDED_LIMIT));
                return (long)info.PeakJobMemoryUsed.ToUInt64();
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        // Member PIDs, read from the Job itself (JOBOBJECT_BASIC_PROCESS_ID_LIST).
        public int[] ProcessIds()
        {
            const int capacity = 4096;
            int bytes = 8 + capacity * IntPtr.Size;
            IntPtr buffer = Marshal.AllocHGlobal(bytes);
            try
            {
                if (!QueryInformationJobObject(job, JobObjectBasicProcessIdList, buffer, (uint)bytes, IntPtr.Zero))
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Win32Exception(error, "Job PID list query failed (Win32 error " + error + ")");
                }
                int count = Marshal.ReadInt32(buffer, 4);
                int[] ids = new int[count];
                for (int i = 0; i < count; i++) ids[i] = (int)Marshal.ReadIntPtr(buffer, 8 + i * IntPtr.Size).ToInt64();
                return ids;
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        // 3. Close the Job to terminate: closing the last handle of a KILL_ON_JOB_CLOSE Job
        //    makes Windows end every process still in it (and in Jobs nested in it).
        public void CloseToTerminate()
        {
            if (child != IntPtr.Zero) { CloseHandle(child); child = IntPtr.Zero; }   // a process handle; closing it ends nothing
            if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
        }
    }

    // B1 (v3): a NATIVE console control handler. SetConsoleCtrlHandler calls a process's handlers
    // newest-first until one returns TRUE (C3-handler-order-proof.md). Install() removes and re-adds
    // the routine on EVERY call, so it is always the newest handler, ahead of PowerShell's own
    // ConsoleHost break handler. It swallows CTRL_C_EVENT in THIS process only; Ctrl+Break and
    // close/logoff events fall through. It is not SetConsoleCtrlHandler(NULL, TRUE), so nothing is
    // inherited: children still receive the console event.
    public static class CtrlCGuard
    {
        public delegate bool HandlerRoutine(uint ctrlType);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetConsoleCtrlHandler(HandlerRoutine routine, bool add);
        static readonly HandlerRoutine Routine = new HandlerRoutine(OnCtrl);   // static: never collected
        static volatile bool fired;
        static int count;
        public static bool Fired { get { return fired; } }
        public static int Count { get { return System.Threading.Interlocked.CompareExchange(ref count, 0, 0); } }
        static bool OnCtrl(uint ctrlType)
        {
            if (ctrlType == 0) { fired = true; System.Threading.Interlocked.Increment(ref count); return true; }
            return false;
        }
        public static void Install()
        {
            SetConsoleCtrlHandler(Routine, false);   // drop any earlier registration (FALSE if none; ignored)
            fired = false;
            System.Threading.Interlocked.Exchange(ref count, 0);
            if (!SetConsoleCtrlHandler(Routine, true))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "SetConsoleCtrlHandler(add) failed");
        }
        public static bool Uninstall()                   // v3.1 N3: the result is recorded (guardRemoved)
        {
            return SetConsoleCtrlHandler(Routine, false);
        }
    }
}
'@

$hasher = [Security.Cryptography.SHA256]::Create()
try { $srcHash = -join ($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($csSource)) | ForEach-Object { $_.ToString('x2') }) }
finally { $hasher.Dispose() }
$ns = 'C3R_' + $srcHash.Substring(0, 16)
if (-not ("$ns.OwnJob" -as [type])) { Add-Type -TypeDefinition $csSource.Replace('__NS__', $ns) }   # csc.exe runs once per console per source (N2)
$OwnJobType = "$ns.OwnJob" -as [type]
$GuardType = "$ns.CtrlCGuard" -as [type]
$NativeType = "$ns.Native" -as [type]
if ((("$ns.Info" -as [type])::Version) -ne $C3RunVersion) { throw "loaded C3 type is not $C3RunVersion" }

function ConvertTo-C3Token([string]$value) {
    if ($value.Length -gt 0 -and $value -notmatch '[\s"]') { return $value }
    $sb = [Text.StringBuilder]::new(); [void]$sb.Append('"'); $slashes = 0
    foreach ($ch in $value.ToCharArray()) {
        if ($ch -eq '\') { $slashes++; continue }
        if ($ch -eq '"') { [void]$sb.Append('\' * ($slashes * 2 + 1)); [void]$sb.Append('"'); $slashes = 0; continue }
        if ($slashes) { [void]$sb.Append('\' * $slashes); $slashes = 0 }
        [void]$sb.Append($ch)
    }
    [void]$sb.Append('\' * ($slashes * 2)); [void]$sb.Append('"')
    return $sb.ToString()
}

# Read-only snapshot "pid|creationUtc" -> {Pid, Parent, Name, Created}. Evidence only; never passed to any stop call.
function Get-C3Snapshot {
    $map = @{}
    foreach ($p in @(Get-CimInstance -ClassName Win32_Process -Property ProcessId, ParentProcessId, CreationDate, Name -OperationTimeoutSec 30)) {
        $created = if ($p.CreationDate) { $p.CreationDate.ToUniversalTime() } else { [DateTime]::MinValue }
        $map['{0}|{1}' -f $p.ProcessId, $created.ToString('o')] = [pscustomobject]@{
            Pid = [int]$p.ProcessId; Parent = [int]$p.ParentProcessId; Name = ([string]$p.Name) -replace '\s', '_'; Created = $created }
    }
    return $map
}

$f = [ordered]@{
    label = $Label; version = $C3RunVersion; rc = 70; timedOut = $false; interrupted = $true; ctrlC = $false; ctrlCCount = 0
    console = '[]'; started = -1; endedBeforeClose = -1; activeAtClose = -1; endedAtClose = -1; memberMismatch = -1
    seen = 0; unseen = -1; lateMembers = 0; jobPids = '[]'; stillAlive = -1; escaped = -1; consoleForeign = -1
    startedPin = 'unpinned'; expectStarted = $ExpectStarted; pidReuse = 0; peakActive = -1; peakJobPrivateMB = -1
    guardRemoved = 'n/a'; vanishedOutsideJob = -1; verify = 'FAIL'; reason = ''; escapedList = '[]'; outsideJob = '[]'
    consoleStale = '[]'                                     # F3: record-only, console entries with no live process
}
$job = $null; $closed = $false; $guardInstalled = $false; $exitCode = 70
$seen = New-Object 'System.Collections.Generic.HashSet[int]'
$jobPids = @(); $members = @(); $foreign = @(); $pre = $null; $post = $null; $listConsistent = $false
$seenAtRead = 0; $peakActive = 0
$launchUtc = [DateTime]::UtcNow.AddSeconds(-2)

try {
    $GuardType::Install(); $guardInstalled = $true          # registered on EVERY call (B1)
    try {
        $os = $NativeType::OsVersion()
        if ($os.Major -lt 10) { $f.reason = 'windows-below-10'; throw "Windows 10 or later is required (PROC_THREAD_ATTRIBUTE_JOB_LIST); this is $os" }
        $attached = @($NativeType::ConsoleProcesses())
        $f.console = '[' + ($attached -join ';') + ']'
        $stale = @($attached | Where-Object { [int]$_ -ne $PID -and $NativeType::IsGone([uint32]$_) })   # F3
        $f.consoleStale = '[' + ($stale -join ';') + ']'
        $attached = @($attached | Where-Object { $stale -notcontains $_ })
        if ($attached.Count -ne 1 -or [int]$attached[0] -ne $PID) {   # M3: refuse unless this console is ours alone (live PIDs)
            $f.reason = 'console-shared'
            throw "REFUSED: this console is shared with PIDs [$($attached -join ',')]; open a fresh console (P4, step 1)"
        }
        $job = $OwnJobType::Create()
        $commandLine = (@($Exe) + $Tokens | ForEach-Object { ConvertTo-C3Token $_ }) -join ' '
        $launchUtc = [DateTime]::UtcNow.AddSeconds(-2)
        $childPid = $job.Launch($Exe, $commandLine, $WorkingDirectory)
        [void]$seen.Add($childPid)
        Write-Host "C3RUN ${Label}: child pid $childPid started inside this script's own kill-on-close Job"
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        $announced = $false
        while (-not $job.WaitChild(250)) {
            foreach ($p in $job.ProcessIds()) { [void]$seen.Add($p) }      # M2: union of every member seen
            $acc = $job.Accounting(); if ($acc[1] -gt $peakActive) { $peakActive = $acc[1] }   # v3.1: peak concurrent members
            if ($WatchMarkersUnder -and -not $announced) {
                $found = @(Get-ChildItem -LiteralPath $WatchMarkersUnder -Filter 'markers.txt' -Recurse -File -ErrorAction SilentlyContinue)
                if ($found.Count -eq 1 -and (Select-String -LiteralPath $found[0].FullName -Pattern '^START ' -Quiet)) {
                    $sentinel = Join-Path $found[0].DirectoryName 'sentinel.txt'
                    if ((Test-Path -LiteralPath $sentinel) -and (Select-String -LiteralPath $sentinel -Pattern '^READY ' -Quiet)) {
                        Write-Host "C3RUN ${Label}: START and sentinel READY seen in $($found[0].DirectoryName) - press Ctrl+C ONCE now, then wait."
                        $announced = $true
                    }
                }
            }
            if ([DateTime]::UtcNow -gt $deadline) { $f.timedOut = $true; break }
        }
        $f.rc = if ($f.timedOut) { 124 } else { $job.ChildExitCode() }
        $f.interrupted = $false
    }
    catch {
        Write-Host "C3RUN ${Label}: launch or wait error: $_"
        if (-not $f.reason) { $f.reason = 'launch-or-wait-error' }
        $f.rc = if ($f.reason -eq 'console-shared') { 64 } else { 71 }
        if ($_.Exception -isnot [System.Management.Automation.PipelineStoppedException]) { $f.interrupted = $false }
    }
    finally {
        if ($null -ne $job) {
            try {
                # v3.1 M1: the (slow, WMI) snapshot is taken FIRST, so every Job read below is newer than it.
                try { $pre = Get-C3Snapshot } catch { Write-Host "C3RUN ${Label}: snapshot failed: $_"; $pre = $null }
                try {
                    for ($i = 0; $i -lt 5; $i++) {                          # a consistent read: accounting, list, accounting
                        $a1 = $job.Accounting(); $ids = @($job.ProcessIds()); $a2 = $job.Accounting()
                        $listConsistent = ($a1[0] -eq $a2[0]) -and ($a1[1] -eq $a2[1]) -and ($ids.Count -eq $a2[1])
                        if ($listConsistent) { break }
                        Start-Sleep -Milliseconds 50
                    }
                    if (-not $listConsistent) { $f.reason += ';job-list-inconsistent'; throw 'job list never consistent' }   # v3.1 N2: FAIL, not HARD STOP
                    $jobPids = $ids; foreach ($p in $ids) { [void]$seen.Add($p) }
                    $seenAtRead = $seen.Count
                    $f.started = $a2[0]; $f.activeAtClose = $a2[1]; $f.endedBeforeClose = $a2[0] - $a2[1]
                    if ($a2[1] -gt $peakActive) { $peakActive = $a2[1] }
                } catch { Write-Host "C3RUN ${Label}: Job query failed: $_"; $f.reason += ';job-query-failed'; $f.started = -1 }
                try { $f.peakJobPrivateMB = [Math]::Round($job.PeakJobPrivateBytes() / 1MB, 1) } catch { Write-Host "C3RUN ${Label}: peak memory query failed: $_" }
                try { $consoleNow = @($NativeType::ConsoleProcesses()) } catch { Write-Host "C3RUN ${Label}: console list failed: $_"; $consoleNow = $null }
                try { $lateIds = @($job.ProcessIds()) } catch { $lateIds = @() }
                $members = @($jobPids) + @($lateIds | Where-Object { $jobPids -notcontains $_ })   # membership is permanent
                $f.lateMembers = $members.Count - @($jobPids).Count
                foreach ($p in $lateIds) { [void]$seen.Add($p) }
                # v3.1-R1: assign INSIDE the branch. `$x = if (..) { @() }` unrolls an empty array to $null, which
                # made every clean run look like "console list failed" (observed in the v3.1 self-test).
                $foreign = $null
                if ($null -ne $consoleNow) {
                    # F3: an entry with no live process cannot receive a keystroke; record it (consoleStale), never count it.
                    $staleNow = @($consoleNow | Where-Object { [int]$_ -ne $PID -and $members -notcontains [int]$_ -and $NativeType::IsGone([uint32]$_) })
                    if ($staleNow.Count -gt 0) { $f.consoleStale = '[' + ((@($f.consoleStale.Trim('[]') -split ';' | Where-Object { $_ }) + @($staleNow | ForEach-Object { "close:$_" })) -join ';') + ']' }
                    $foreign = @($consoleNow | Where-Object { [int]$_ -ne $PID -and $members -notcontains [int]$_ -and $staleNow -notcontains $_ })
                }
            }
            finally {
                $job.CloseToTerminate(); $closed = $true        # M1: always; the ONLY termination in this script
            }
        }
        if ($f.interrupted) { Write-Host "C3RUN ${Label} wrapper interrupted (Job closed by finally)" }
    }

    # Verification. Everything here is read-only evidence.
    if ($f.reason -eq 'console-shared' -or $f.reason -eq 'windows-below-10') {
        $f.verify = 'REFUSED'
    }
    elseif ($null -eq $job -or -not $closed) { $f.reason += ';no-job' }
    elseif ($null -eq $pre -or $null -eq $foreign -or $f.started -lt 0) {
        $f.reason += ';evidence-missing'
        if ($null -eq $pre) { $f.reason += ':snapshot' }; if ($null -eq $foreign) { $f.reason += ':console' }; if ($f.started -lt 0) { $f.reason += ':job' }
    }
    else {
        $jobKeys = @($pre.Keys | Where-Object { $members -contains $pre[$_].Pid })
        $readKeys = @($pre.Keys | Where-Object { $jobPids -contains $pre[$_].Pid })
        $until = [DateTime]::UtcNow.AddSeconds(10)
        do {
            $post = Get-C3Snapshot
            $alive = @($jobKeys | Where-Object { $post.ContainsKey($_) })
            if ($alive.Count -eq 0) { break }
            Start-Sleep -Milliseconds 100
        } while ([DateTime]::UtcNow -lt $until)
        $f.stillAlive = $alive.Count
        # Started versus ended, for this Job's own members (master-agent: a mismatch is a HARD STOP).
        $f.endedAtClose = @($jobPids).Count - @($readKeys | Where-Object { $post.ContainsKey($_) }).Count
        $ended = $f.endedBeforeClose + $f.endedAtClose
        $f.memberMismatch = [Math]::Abs($f.started - $ended) + [Math]::Abs($jobPids.Count - $f.activeAtClose)
        if ($seenAtRead -gt $f.started) { $f.memberMismatch += $seenAtRead - $f.started }   # late PIDs excluded (v3.1 M1)
        if ($f.started -lt 1) { $f.memberMismatch += 1 }                  # the child itself is always a member
        $f.seen = $seen.Count; $f.unseen = [Math]::Max(0, $f.started - $seenAtRead); $f.peakActive = $peakActive
        if ($ExpectStarted -ge 0) { $f.startedPin = if ($f.started -eq $ExpectStarted) { 'OK' } else { 'DIFF' } }   # v3.1 Q6
        # Escaped: a process this run caused (created after launch; a seen member itself, or a descendant of one)
        # that is NOT a Job member. Fixpoint over the parent chain in the before and after snapshots.
        $all = @{}; foreach ($k in $pre.Keys) { $all[$k] = $pre[$k] }; foreach ($k in $post.Keys) { $all[$k] = $post[$k] }
        $roots = New-Object 'System.Collections.Generic.HashSet[int]'; foreach ($p in $seen) { [void]$roots.Add($p) }
        $escapedKeys = New-Object 'System.Collections.Generic.HashSet[string]'
        # v3.1 M1: parent-IDENTITY rule. A process can never leave a Job, so a non-member whose PID is in $seen is a
        # reused PID (recorded as pidReuse, never counted as escaped). A candidate counts only if its live parent entry
        # (same PID, created no later than the candidate) is a member or an already-escaped process.
        do {
            $grew = $false
            foreach ($k in @($all.Keys)) {
                $e = $all[$k]
                if ($escapedKeys.Contains($k) -or $e.Pid -eq $PID -or $members -contains $e.Pid -or $e.Created -lt $launchUtc) { continue }
                $parentKey = @($all.Keys | Where-Object { $all[$_].Pid -eq $e.Parent -and $all[$_].Created -le $e.Created } |
                              Sort-Object { $all[$_].Created } | Select-Object -Last 1)
                $byMember = if ($parentKey.Count -eq 1) {
                    ($members -contains $all[$parentKey[0]].Pid) -or $escapedKeys.Contains($parentKey[0])   # identity-checked parent
                } else {
                    $roots.Contains($e.Parent)                                                              # parent gone: fail closed
                }
                if ($byMember) { [void]$escapedKeys.Add($k); [void]$roots.Add($e.Pid); $grew = $true }
            }
        } while ($grew)
        $f.pidReuse = @($all.Keys | Where-Object { $seen.Contains($all[$_].Pid) -and $members -notcontains $all[$_].Pid -and -not $escapedKeys.Contains($_) }).Count
        $f.escaped = $escapedKeys.Count
        $f.escapedList = '[' + (($escapedKeys | ForEach-Object { '{0}|{1}|ppid{2}' -f $_, $all[$_].Name, $all[$_].Parent }) -join ';') + ']'
        $f.consoleForeign = $foreign.Count
        # Host-wide: processes OUTSIDE the Job that ended during the close window. RECORD ONLY, never a stop (M2).
        $outside = @($pre.Keys | Where-Object { -not $post.ContainsKey($_) -and $jobKeys -notcontains $_ -and -not $escapedKeys.Contains($_) })
        $f.vanishedOutsideJob = $outside.Count
        $f.outsideJob = '[' + (($outside | ForEach-Object { '{0}|{1}|ppid{2}' -f $_, $pre[$_].Name, $pre[$_].Parent }) -join ';') + ']'
        if ($f.escaped -gt 0 -or $f.memberMismatch -ne 0 -or $f.consoleForeign -gt 0) { $f.verify = 'HARDSTOP' }
        elseif ($f.startedPin -eq 'DIFF') { $f.verify = 'FAIL'; $f.reason += ';started-differs-from-pin' }   # ABORT, not HARD STOP
        elseif ($f.stillAlive -eq 0) { $f.verify = 'OK' }
    }
}
catch {
    Write-Host "C3RUN ${Label}: verification error: $_"
    $f.reason += ';verification-error'
    if ($f.verify -eq 'OK') { $f.verify = 'FAIL' }
}
finally {
    # M1: the ledger line is written unconditionally.
    try { $f.ctrlC = $GuardType::Fired; $f.ctrlCCount = $GuardType::Count } catch { }
    if ($guardInstalled) { try { $f.guardRemoved = $GuardType::Uninstall(); $guardInstalled = $false } catch { $f.guardRemoved = 'error' } }
    $f.jobPids = '[' + ($jobPids -join ';') + ']'
    if (-not $f.reason) { $f.reason = 'none' }
    $f.reason = $f.reason.TrimStart(';') -replace '\s', '_'
    $line = ([DateTime]::UtcNow.ToString('o')) + ' ' + (($f.GetEnumerator() | ForEach-Object { '{0}={1}' -f $_.Key, $_.Value }) -join ' ')
    try { Add-Content -LiteralPath $ledger -Value $line -Encoding UTF8 }
    catch { Write-Host "C3RUN ${Label}: LEDGER WRITE FAILED: $_ (treat as verify FAIL)"; $f.verify = 'FAIL' }
    Write-Host ("C3RUN {0} exit={1} started={2} startedPin={3} ended={4} memberMismatch={5} escaped={6} consoleForeign={7} stillAlive={8} ctrlC={9}/{10} peakActive={11} peakJobPrivateMB={12} pidReuse={13}(record-only) vanishedOutsideJob={14}(record-only) consoleStale={16}(record-only) verify {15}" -f `
        $Label, $(if ($f.timedOut) { 'TIMEOUT' } else { $f.rc }), $f.started, $f.startedPin, ($f.endedBeforeClose + $f.endedAtClose), $f.memberMismatch,
        $f.escaped, $f.consoleForeign, $f.stillAlive, $f.ctrlC, $f.ctrlCCount, $f.peakActive, $f.peakJobPrivateMB, $f.pidReuse, $f.vanishedOutsideJob, $f.verify, $f.consoleStale)
    if ($f.verify -eq 'HARDSTOP') { Write-Host "C3RUN ${Label}: HARD STOP. The rehearsal caused a process outside its Job, or its Job's members do not add up. Stop the rehearsal; record FAIL." }
    elseif ($f.verify -ne 'OK') { Write-Host "C3RUN ${Label}: verify $($f.verify) ($($f.reason)). This script issued no stop call. Abort the step." }
    $exitCode = if ($f.verify -eq 'OK') { [int]$f.rc } elseif ($f.verify -eq 'REFUSED') { 64 } else { 125 }
    if ($guardInstalled) { [void]$GuardType::Uninstall() }
}
exit $exitCode
