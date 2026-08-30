# Windows Job Object helper for scheduled wrappers that own delegated children.
#
# A Job with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE makes child-tree ownership an
# operating-system invariant: if Task Scheduler terminates the PowerShell
# wrapper, Windows closes the wrapper's Job handle and terminates every process
# assigned to the Job. The handle is intentionally non-inheritable, so a child
# cannot keep its own containment Job alive after the wrapper exits.

Set-StrictMode -Version 2.0

if (-not ("Weather.Operations.KillOnCloseJob" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace Weather.Operations
{
    public sealed class KillOnCloseJob : IDisposable
    {
        private const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        private const Int32 JobObjectExtendedLimitInformation = 9;
        private const UInt32 CREATE_SUSPENDED = 0x00000004;
        private const UInt32 CREATE_NO_WINDOW = 0x08000000;
        private const Int32 JobObjectBasicAccountingInformation = 1;
        private IntPtr handle;

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

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(
            IntPtr jobAttributes,
            string name
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(
            IntPtr job,
            Int32 informationClass,
            IntPtr information,
            UInt32 informationLength
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(
            IntPtr job,
            IntPtr process
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool QueryInformationJobObject(
            IntPtr job,
            Int32 informationClass,
            IntPtr information,
            UInt32 informationLength,
            out UInt32 returnLength
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, UInt32 exitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

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

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CreateProcess(
            string applicationName,
            StringBuilder commandLine,
            IntPtr processAttributes,
            IntPtr threadAttributes,
            bool inheritHandles,
            UInt32 creationFlags,
            IntPtr environment,
            string currentDirectory,
            ref STARTUPINFO startupInfo,
            out PROCESS_INFORMATION processInformation
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern UInt32 ResumeThread(IntPtr thread);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateProcess(IntPtr process, UInt32 exitCode);

        private KillOnCloseJob(IntPtr jobHandle)
        {
            handle = jobHandle;
        }

        public static KillOnCloseJob Create()
        {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");
            }

            IntPtr information = IntPtr.Zero;
            try
            {
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits =
                    new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                limits.BasicLimitInformation.LimitFlags =
                    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                Int32 size = Marshal.SizeOf(limits);
                information = Marshal.AllocHGlobal(size);
                Marshal.StructureToPtr(limits, information, false);
                if (!SetInformationJobObject(
                    job,
                    JobObjectExtendedLimitInformation,
                    information,
                    (UInt32)size
                ))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "SetInformationJobObject(KILL_ON_JOB_CLOSE) failed"
                    );
                }
                return new KillOnCloseJob(job);
            }
            catch
            {
                CloseHandle(job);
                throw;
            }
            finally
            {
                if (information != IntPtr.Zero)
                {
                    Marshal.FreeHGlobal(information);
                }
            }
        }

        private Process StartAssignedInternal(
            string executable,
            string arguments,
            string workingDirectory,
            bool interactive
        )
        {
            if (String.IsNullOrWhiteSpace(executable))
            {
                throw new ArgumentException("executable is required", "executable");
            }
            if (handle == IntPtr.Zero)
            {
                throw new ObjectDisposedException("KillOnCloseJob");
            }

            STARTUPINFO startup = new STARTUPINFO();
            startup.cb = Marshal.SizeOf(startup);
            PROCESS_INFORMATION processInfo;
            StringBuilder commandLine = new StringBuilder(
                "\"" + executable + "\"" +
                (String.IsNullOrWhiteSpace(arguments) ? "" : " " + arguments)
            );
            bool created = CreateProcess(
                executable,
                commandLine,
                IntPtr.Zero,
                IntPtr.Zero,
                // Console attachment does not require inheriting every ambient
                // inheritable handle held by the launcher process.
                false,
                CREATE_SUSPENDED | (interactive ? 0 : CREATE_NO_WINDOW),
                IntPtr.Zero,
                workingDirectory,
                ref startup,
                out processInfo
            );
            if (!created)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcess(CREATE_SUSPENDED) failed");
            }

            Process managedProcess = null;
            try
            {
                if (!AssignProcessToJobObject(handle, processInfo.hProcess))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "AssignProcessToJobObject before resume failed"
                    );
                }
                managedProcess = Process.GetProcessById((Int32)processInfo.dwProcessId);
                // Force .NET to open its own waitable process handle before the
                // native CreateProcess handle is closed in finally. This also
                // makes very short-lived child processes safe to WaitForExit.
                IntPtr managedHandle = managedProcess.Handle;
                if (ResumeThread(processInfo.hThread) == UInt32.MaxValue)
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread failed");
                }
                return managedProcess;
            }
            catch
            {
                TerminateProcess(processInfo.hProcess, 1);
                if (managedProcess != null)
                {
                    managedProcess.Dispose();
                }
                throw;
            }
            finally
            {
                CloseHandle(processInfo.hThread);
                CloseHandle(processInfo.hProcess);
            }
        }

        public Process StartAssigned(
            string executable,
            string arguments,
            string workingDirectory
        )
        {
            return StartAssignedInternal(
                executable,
                arguments,
                workingDirectory,
                false
            );
        }

        public Process StartAssignedInteractive(
            string executable,
            string arguments,
            string workingDirectory
        )
        {
            return StartAssignedInternal(
                executable,
                arguments,
                workingDirectory,
                true
            );
        }

        private UInt32 ActiveProcessCount()
        {
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting =
                new JOBOBJECT_BASIC_ACCOUNTING_INFORMATION();
            Int32 size = Marshal.SizeOf(accounting);
            IntPtr information = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.StructureToPtr(accounting, information, false);
                UInt32 returned;
                if (!QueryInformationJobObject(
                    handle,
                    JobObjectBasicAccountingInformation,
                    information,
                    (UInt32)size,
                    out returned
                ))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "QueryInformationJobObject(accounting) failed"
                    );
                }
                accounting = (JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)
                    Marshal.PtrToStructure(
                        information,
                        typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)
                    );
                return accounting.ActiveProcesses;
            }
            finally
            {
                Marshal.FreeHGlobal(information);
            }
        }

        public void TerminateAndWait(Int32 timeoutMilliseconds)
        {
            if (handle == IntPtr.Zero)
            {
                throw new ObjectDisposedException("KillOnCloseJob");
            }
            if (timeoutMilliseconds < 0)
            {
                throw new ArgumentOutOfRangeException("timeoutMilliseconds");
            }
            if (!TerminateJobObject(handle, 1))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "TerminateJobObject failed"
                );
            }
            Stopwatch deadline = Stopwatch.StartNew();
            while (ActiveProcessCount() != 0)
            {
                if (deadline.ElapsedMilliseconds >= timeoutMilliseconds)
                {
                    throw new TimeoutException(
                        "Windows Job child tree did not reach zero active processes"
                    );
                }
                Thread.Sleep(10);
            }
        }

        public void Dispose()
        {
            if (handle == IntPtr.Zero)
            {
                return;
            }
            CloseHandle(handle);
            handle = IntPtr.Zero;
            GC.SuppressFinalize(this);
        }

        ~KillOnCloseJob()
        {
            Dispose();
        }
    }
}
'@
}

function New-WeatherKillOnCloseJob {
    [CmdletBinding()]
    param()

    return [Weather.Operations.KillOnCloseJob]::Create()
}

function Start-WeatherProcessInJob {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [Weather.Operations.KillOnCloseJob]$Job,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$ArgumentString,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    return $Job.StartAssigned($FilePath, $ArgumentString, $WorkingDirectory)
}

function Start-WeatherInteractiveProcessInJob {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [Weather.Operations.KillOnCloseJob]$Job,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$ArgumentString,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    return $Job.StartAssignedInteractive(
        $FilePath,
        $ArgumentString,
        $WorkingDirectory
    )
}

function ConvertTo-WeatherWindowsArgumentString {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string[]]$Tokens)

    $encoded = foreach ($token in $Tokens) {
        $value = [string]$token
        if ($value -notmatch '[\s"]' -and $value.Length -gt 0) {
            $value
            continue
        }
        $builder = [Text.StringBuilder]::new()
        [void]$builder.Append('"')
        $slashes = 0
        foreach ($character in $value.ToCharArray()) {
            if ($character -eq '\') {
                $slashes++
                continue
            }
            if ($character -eq '"') {
                [void]$builder.Append(('\' * (($slashes * 2) + 1)))
                [void]$builder.Append('"')
                $slashes = 0
                continue
            }
            if ($slashes -gt 0) {
                [void]$builder.Append(('\' * $slashes))
                $slashes = 0
            }
            [void]$builder.Append($character)
        }
        if ($slashes -gt 0) {
            [void]$builder.Append(('\' * ($slashes * 2)))
        }
        [void]$builder.Append('"')
        $builder.ToString()
    }
    return ($encoded -join ' ')
}
