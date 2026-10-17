# Job Object with memory and priority limits for the nightly replay export (U6 fix round, P-v2 NB2).
#
# The venv python.exe is a redirector that starts the real interpreter as its child, so limits on the
# started process alone miss the exporter. This Job applies to every member:
#   - JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (as windows_kill_on_close_job.ps1);
#   - JOB_OBJECT_LIMIT_JOB_MEMORY and JOB_OBJECT_LIMIT_PROCESS_MEMORY (committed bytes);
#   - JOB_OBJECT_LIMIT_PRIORITY_CLASS (every member runs at the given class, e.g. BelowNormal).
# A completion port receives JOB_OBJECT_MSG_JOB_MEMORY_LIMIT / _PROCESS_MEMORY_LIMIT; a watcher thread then
# terminates the whole Job at once and records which process hit the limit. The shared helper is untouched.

Set-StrictMode -Version 2.0

if (-not ("Weather.Operations.ReplayExportLimitedJob" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace Weather.Operations
{
    public sealed class ReplayExportLimitedJob : IDisposable
    {
        public const UInt32 MemoryLimitExitCode = 0xE0E0E0E0;
        private const UInt32 JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020;
        private const UInt32 JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100;
        private const UInt32 JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200;
        private const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        private const Int32 JobObjectBasicAccountingInformation = 1;
        private const Int32 JobObjectBasicProcessIdList = 3;
        private const Int32 JobObjectAssociateCompletionPortInformation = 7;
        private const Int32 JobObjectExtendedLimitInformation = 9;
        private const UInt32 JOB_OBJECT_MSG_NEW_PROCESS = 6;
        private const UInt32 JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT = 9;
        private const UInt32 JOB_OBJECT_MSG_JOB_MEMORY_LIMIT = 10;
        private const UInt32 CREATE_SUSPENDED = 0x00000004;
        private const UInt32 CREATE_NO_WINDOW = 0x08000000;

        private IntPtr handle;
        private IntPtr port;
        private Thread watcher;
        private volatile bool memoryLimitHit;
        private volatile UInt32 memoryLimitProcessId;
        private volatile UInt32 memoryLimitMessage;
        private readonly System.Collections.Generic.List<UInt32> members = new System.Collections.Generic.List<UInt32>();

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

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_ASSOCIATE_COMPLETION_PORT
        {
            public IntPtr CompletionKey;
            public IntPtr CompletionPort;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct STARTUPINFO
        {
            public Int32 cb;
            public string lpReserved;
            public string lpDesktop;
            public string lpTitle;
            public UInt32 dwX;
            public UInt32 dwY;
            public UInt32 dwXSize;
            public UInt32 dwYSize;
            public UInt32 dwXCountChars;
            public UInt32 dwYCountChars;
            public UInt32 dwFillAttribute;
            public UInt32 dwFlags;
            public UInt16 wShowWindow;
            public UInt16 cbReserved2;
            public IntPtr lpReserved2;
            public IntPtr hStdInput;
            public IntPtr hStdOutput;
            public IntPtr hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PROCESS_INFORMATION
        {
            public IntPtr hProcess;
            public IntPtr hThread;
            public UInt32 dwProcessId;
            public UInt32 dwThreadId;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MEMORYSTATUSEX
        {
            public UInt32 dwLength;
            public UInt32 dwMemoryLoad;
            public UInt64 ullTotalPhys;
            public UInt64 ullAvailPhys;
            public UInt64 ullTotalPageFile;
            public UInt64 ullAvailPageFile;
            public UInt64 ullTotalVirtual;
            public UInt64 ullAvailVirtual;
            public UInt64 ullAvailExtendedVirtual;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr job, Int32 informationClass, IntPtr information,
            UInt32 length);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool QueryInformationJobObject(IntPtr job, Int32 informationClass, IntPtr information,
            UInt32 length, out UInt32 returned);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, UInt32 exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateIoCompletionPort(IntPtr file, IntPtr existing, UIntPtr key, UInt32 threads);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetQueuedCompletionStatus(IntPtr port, out UInt32 bytes, out UIntPtr key,
            out IntPtr overlapped, UInt32 milliseconds);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CreateProcess(string application, StringBuilder commandLine, IntPtr processAttributes,
            IntPtr threadAttributes, bool inheritHandles, UInt32 flags, IntPtr environment, string directory,
            ref STARTUPINFO startup, out PROCESS_INFORMATION information);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern UInt32 ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateProcess(IntPtr process, UInt32 exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX status);

        private ReplayExportLimitedJob(IntPtr job, IntPtr completion)
        {
            handle = job;
            port = completion;
            watcher = new Thread(Watch);
            watcher.IsBackground = true;
            watcher.Start();
        }

        public static UInt64 AvailablePhysicalMiB()
        {
            MEMORYSTATUSEX status = new MEMORYSTATUSEX();
            status.dwLength = (UInt32)Marshal.SizeOf(status);
            if (!GlobalMemoryStatusEx(ref status))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "GlobalMemoryStatusEx failed");
            }
            return status.ullAvailPhys / (1024UL * 1024UL);
        }

        public static ReplayExportLimitedJob Create(UInt64 jobMemoryLimitBytes, UInt64 processMemoryLimitBytes,
            UInt32 priorityClass)
        {
            if (jobMemoryLimitBytes == 0 || processMemoryLimitBytes == 0 || processMemoryLimitBytes > jobMemoryLimitBytes)
            {
                throw new ArgumentException("0 < process memory limit <= job memory limit required");
            }
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");
            }
            IntPtr completion = IntPtr.Zero;
            IntPtr buffer = IntPtr.Zero;
            try
            {
                completion = CreateIoCompletionPort(new IntPtr(-1), IntPtr.Zero, UIntPtr.Zero, 1);
                if (completion == IntPtr.Zero)
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateIoCompletionPort failed");
                }
                JOBOBJECT_ASSOCIATE_COMPLETION_PORT association = new JOBOBJECT_ASSOCIATE_COMPLETION_PORT();
                association.CompletionKey = job;
                association.CompletionPort = completion;
                Int32 size = Marshal.SizeOf(association);
                buffer = Marshal.AllocHGlobal(size);
                Marshal.StructureToPtr(association, buffer, false);
                if (!SetInformationJobObject(job, JobObjectAssociateCompletionPortInformation, buffer, (UInt32)size))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Job completion port association failed");
                }
                Marshal.FreeHGlobal(buffer);
                buffer = IntPtr.Zero;

                JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
                    JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_PRIORITY_CLASS;
                limits.BasicLimitInformation.PriorityClass = priorityClass;
                limits.JobMemoryLimit = new UIntPtr(jobMemoryLimitBytes);
                limits.ProcessMemoryLimit = new UIntPtr(processMemoryLimitBytes);
                size = Marshal.SizeOf(limits);
                buffer = Marshal.AllocHGlobal(size);
                Marshal.StructureToPtr(limits, buffer, false);
                if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, buffer, (UInt32)size))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "SetInformationJobObject(limits) failed");
                }
                return new ReplayExportLimitedJob(job, completion);
            }
            catch
            {
                if (completion != IntPtr.Zero) { CloseHandle(completion); }
                CloseHandle(job);
                throw;
            }
            finally
            {
                if (buffer != IntPtr.Zero) { Marshal.FreeHGlobal(buffer); }
            }
        }

        private void Watch()
        {
            while (true)
            {
                UInt32 message;
                UIntPtr key;
                IntPtr overlapped;
                IntPtr current = port;
                if (current == IntPtr.Zero) { return; }
                if (!GetQueuedCompletionStatus(current, out message, out key, out overlapped, 250))
                {
                    if (overlapped == IntPtr.Zero && port != IntPtr.Zero) { continue; }  // timeout
                    return;  // port closed
                }
                if (message == JOB_OBJECT_MSG_NEW_PROCESS)
                {
                    lock (members) { members.Add((UInt32)overlapped.ToInt64()); }
                }
                if (message == JOB_OBJECT_MSG_JOB_MEMORY_LIMIT || message == JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT)
                {
                    memoryLimitProcessId = (UInt32)overlapped.ToInt64();
                    memoryLimitMessage = message;
                    memoryLimitHit = true;
                    IntPtr job = handle;
                    if (job != IntPtr.Zero) { TerminateJobObject(job, MemoryLimitExitCode); }
                }
            }
        }

        public bool MemoryLimitHit { get { return memoryLimitHit; } }
        public UInt32 MemoryLimitProcessId { get { return memoryLimitProcessId; } }
        // Every process ever assigned to the Job (JOB_OBJECT_MSG_NEW_PROCESS), including members that already exited.
        public UInt32[] MemberProcessIds() { lock (members) { return members.ToArray(); } }
        public string MemoryLimitKind
        {
            get
            {
                return !memoryLimitHit ? "" :
                    (memoryLimitMessage == JOB_OBJECT_MSG_JOB_MEMORY_LIMIT ? "JOB_MEMORY_LIMIT" : "PROCESS_MEMORY_LIMIT");
            }
        }

        private JOBOBJECT_EXTENDED_LIMIT_INFORMATION Extended()
        {
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            Int32 size = Marshal.SizeOf(info);
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                UInt32 returned;
                if (!QueryInformationJobObject(handle, JobObjectExtendedLimitInformation, buffer, (UInt32)size, out returned))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject(limits) failed");
                }
                return (JOBOBJECT_EXTENDED_LIMIT_INFORMATION)Marshal.PtrToStructure(buffer,
                    typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public UInt64 PeakJobMemoryUsed { get { return Extended().PeakJobMemoryUsed.ToUInt64(); } }
        public UInt64 PeakProcessMemoryUsed { get { return Extended().PeakProcessMemoryUsed.ToUInt64(); } }
        public UInt64 JobMemoryLimit { get { return Extended().JobMemoryLimit.ToUInt64(); } }
        public UInt64 ProcessMemoryLimit { get { return Extended().ProcessMemoryLimit.ToUInt64(); } }
        public UInt32 PriorityClass { get { return Extended().BasicLimitInformation.PriorityClass; } }

        public Int32 ActiveProcessCount()
        {
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info = new JOBOBJECT_BASIC_ACCOUNTING_INFORMATION();
            Int32 size = Marshal.SizeOf(info);
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                UInt32 returned;
                if (!QueryInformationJobObject(handle, JobObjectBasicAccountingInformation, buffer, (UInt32)size,
                    out returned))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject(accounting) failed");
                }
                info = (JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)Marshal.PtrToStructure(buffer,
                    typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION));
                return (Int32)info.ActiveProcesses;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public Int32[] ProcessIds()
        {
            const Int32 capacity = 256;
            Int32 size = 8 + capacity * IntPtr.Size;
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                UInt32 returned;
                if (!QueryInformationJobObject(handle, JobObjectBasicProcessIdList, buffer, (UInt32)size, out returned))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject(process ids) failed");
                }
                Int32 count = Marshal.ReadInt32(buffer, 4);
                List<Int32> ids = new List<Int32>();
                for (Int32 i = 0; i < count && i < capacity; i++)
                {
                    ids.Add((Int32)Marshal.ReadIntPtr(buffer, 8 + i * IntPtr.Size).ToInt64());
                }
                return ids.ToArray();
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public Process StartAssigned(string executable, string arguments, string workingDirectory)
        {
            if (String.IsNullOrWhiteSpace(executable)) { throw new ArgumentException("executable is required"); }
            if (handle == IntPtr.Zero) { throw new ObjectDisposedException("ReplayExportLimitedJob"); }
            STARTUPINFO startup = new STARTUPINFO();
            startup.cb = Marshal.SizeOf(startup);
            PROCESS_INFORMATION info;
            StringBuilder commandLine = new StringBuilder("\"" + executable + "\"" +
                (String.IsNullOrWhiteSpace(arguments) ? "" : " " + arguments));
            if (!CreateProcess(executable, commandLine, IntPtr.Zero, IntPtr.Zero, false,
                CREATE_SUSPENDED | CREATE_NO_WINDOW, IntPtr.Zero, workingDirectory, ref startup, out info))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcess(CREATE_SUSPENDED) failed");
            }
            Process managed = null;
            try
            {
                if (!AssignProcessToJobObject(handle, info.hProcess))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "AssignProcessToJobObject before resume failed");
                }
                managed = Process.GetProcessById((Int32)info.dwProcessId);
                IntPtr managedHandle = managed.Handle;
                if (ResumeThread(info.hThread) == UInt32.MaxValue)
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread failed");
                }
                return managed;
            }
            catch
            {
                TerminateProcess(info.hProcess, 1);
                if (managed != null) { managed.Dispose(); }
                throw;
            }
            finally
            {
                CloseHandle(info.hThread);
                CloseHandle(info.hProcess);
            }
        }

        public void TerminateAndWait(Int32 timeoutMilliseconds)
        {
            if (handle == IntPtr.Zero) { throw new ObjectDisposedException("ReplayExportLimitedJob"); }
            if (timeoutMilliseconds < 0) { throw new ArgumentOutOfRangeException("timeoutMilliseconds"); }
            if (!TerminateJobObject(handle, 1))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "TerminateJobObject failed");
            }
            Stopwatch deadline = Stopwatch.StartNew();
            while (ActiveProcessCount() != 0)
            {
                if (deadline.ElapsedMilliseconds >= timeoutMilliseconds)
                {
                    throw new TimeoutException("Windows Job child tree did not reach zero active processes");
                }
                Thread.Sleep(10);
            }
        }

        public void Dispose()
        {
            IntPtr completion = port;
            port = IntPtr.Zero;
            if (completion != IntPtr.Zero) { CloseHandle(completion); }
            if (watcher != null) { watcher.Join(2000); watcher = null; }
            if (handle != IntPtr.Zero)
            {
                CloseHandle(handle);
                handle = IntPtr.Zero;
            }
            GC.SuppressFinalize(this);
        }
    }
}
'@
}

function New-ReplayExportLimitedJob {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][UInt64]$JobMemoryLimitBytes,
        [Parameter(Mandatory = $true)][UInt64]$ProcessMemoryLimitBytes,
        [Diagnostics.ProcessPriorityClass]$PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
    )
    return [Weather.Operations.ReplayExportLimitedJob]::Create($JobMemoryLimitBytes, $ProcessMemoryLimitBytes,
        [UInt32][int]$PriorityClass)
}
