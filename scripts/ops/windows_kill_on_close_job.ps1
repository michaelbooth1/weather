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
using System.IO;
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
            bool interactive,
            CapturedOutput output = null
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
            bool created;
            if (output == null)
            {
                created = CreateProcess(
                    executable, commandLine, IntPtr.Zero, IntPtr.Zero,
                    // Console attachment does not require inheriting every ambient
                    // inheritable handle held by the launcher process.
                    false, CREATE_SUSPENDED | (interactive ? 0 : CREATE_NO_WINDOW),
                    IntPtr.Zero, workingDirectory, ref startup, out processInfo
                );
            }
            else
            {
                STARTUPINFOEX extended = new STARTUPINFOEX();
                extended.StartupInfo = startup;
                extended.StartupInfo.cb = Marshal.SizeOf(extended);
                extended.StartupInfo.dwFlags = 0x00000100; // STARTF_USESTDHANDLES
                extended.StartupInfo.hStdInput = output.InputHandle;
                extended.StartupInfo.hStdOutput = output.OutputHandle;
                extended.StartupInfo.hStdError = output.ErrorHandle;
                extended.AttributeList = output.AttributeList;
                created = CreateProcessWithAttributes(
                    executable, commandLine, IntPtr.Zero, IntPtr.Zero,
                    // TRUE is required with HANDLE_LIST; only its three handles
                    // can be inherited. The Job and parent reader handles cannot.
                    true, CREATE_SUSPENDED | CREATE_NO_WINDOW | 0x00080000,
                    IntPtr.Zero, workingDirectory, ref extended, out processInfo
                );
            }
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


        [StructLayout(LayoutKind.Sequential)]
        private struct STARTUPINFOEX
        {
            public STARTUPINFO StartupInfo;
            public IntPtr AttributeList;
        }

        [DllImport("kernel32.dll", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CreateProcessWithAttributes(
            string applicationName, StringBuilder commandLine,
            IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles,
            UInt32 creationFlags, IntPtr environment, string currentDirectory,
            ref STARTUPINFOEX startupInfo, out PROCESS_INFORMATION processInformation
        );

        [StructLayout(LayoutKind.Sequential)]
        private struct SECURITY_ATTRIBUTES
        {
            public Int32 Length;
            public IntPtr SecurityDescriptor;
            [MarshalAs(UnmanagedType.Bool)] public bool InheritHandle;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CreatePipe(out IntPtr read, out IntPtr write,
            ref SECURITY_ATTRIBUTES attributes, UInt32 size);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(IntPtr handle, UInt32 mask, UInt32 flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateFile(string name, UInt32 access, UInt32 share,
            ref SECURITY_ATTRIBUTES attributes, UInt32 disposition, UInt32 flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool InitializeProcThreadAttributeList(
            IntPtr list, Int32 count, UInt32 flags, ref IntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool UpdateProcThreadAttribute(
            IntPtr list, UInt32 flags, IntPtr attribute, IntPtr value,
            IntPtr size, IntPtr previous, IntPtr returned);
        [DllImport("kernel32.dll")]
        private static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool PeekNamedPipe(IntPtr pipe, IntPtr buffer, UInt32 size,
            IntPtr read, out UInt32 available, IntPtr remaining);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool ReadFile(IntPtr file, byte[] buffer, UInt32 count,
            out UInt32 read, IntPtr overlapped);

        // Single-reader polling keeps teardown bounded: no background reader can
        // hold a stream/lease while blocked waiting for an inherited pipe to close.
        public sealed class CapturedOutput : IDisposable
        {
            private sealed class PipeOutput : IDisposable
            {
                internal IntPtr ReadHandle;
                internal IntPtr WriteHandle;
                internal FileStream File;
                internal readonly string Path;
                internal readonly Int32 Limit;
                internal Int64 Total;
                internal Int64 Retained;
                internal bool Eof;
                private readonly byte[] buffer = new byte[8192];

                internal PipeOutput(string path, Int32 limit)
                {
                    Path = path;
                    Limit = limit;
                    try
                    {
                        File = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
                        SECURITY_ATTRIBUTES attributes = new SECURITY_ATTRIBUTES();
                        attributes.Length = Marshal.SizeOf(attributes);
                        attributes.InheritHandle = true;
                        if (!CreatePipe(out ReadHandle, out WriteHandle, ref attributes, 0))
                            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreatePipe failed");
                        if (!SetHandleInformation(ReadHandle, 1, 0))
                            throw new Win32Exception(Marshal.GetLastWin32Error(), "Pipe reader inheritance removal failed");
                    }
                    catch { Dispose(); throw; }
                }

                internal void CloseWriter()
                {
                    if (WriteHandle != IntPtr.Zero) { CloseHandle(WriteHandle); WriteHandle = IntPtr.Zero; }
                }

                internal void Drain()
                {
                    // Bound each turn even when the child writes continuously.
                    for (Int32 budget = 65536; budget > 0 && !Eof; )
                    {
                        UInt32 available;
                        if (!PeekNamedPipe(ReadHandle, IntPtr.Zero, 0, IntPtr.Zero, out available, IntPtr.Zero))
                        {
                            Int32 error = Marshal.GetLastWin32Error();
                            if (error == 109) { Eof = true; return; } // ERROR_BROKEN_PIPE
                            throw new Win32Exception(error, "Output pipe peek failed");
                        }
                        if (available == 0) return;
                        UInt32 read;
                        UInt32 count = Math.Min(available, (UInt32)Math.Min(buffer.Length, budget));
                        if (!ReadFile(ReadHandle, buffer, count, out read, IntPtr.Zero))
                            throw new Win32Exception(Marshal.GetLastWin32Error(), "Output pipe read failed");
                        if (read == 0) { Eof = true; return; }
                        Total = checked(Total + read);
                        Int32 retain = (Int32)Math.Min((Int64)read, Limit - Retained);
                        if (retain > 0)
                        {
                            File.Write(buffer, 0, retain);
                            Retained += retain;
                            File.Flush();
                        }
                        budget -= (Int32)read;
                    }
                }

                public void Dispose()
                {
                    CloseWriter();
                    if (ReadHandle != IntPtr.Zero) { CloseHandle(ReadHandle); ReadHandle = IntPtr.Zero; }
                    if (File != null)
                    {
                        try { File.Flush(true); }
                        finally { File.Dispose(); File = null; }
                    }
                }
            }

            private PipeOutput stdout;
            private PipeOutput stderr;
            internal IntPtr InputHandle;
            internal IntPtr AttributeList;
            private IntPtr handleList;
            private bool attributesInitialized;
            private bool disposed;
            private bool used;
            public bool Completed { get; private set; }
            public string StdoutPath { get { return stdout.Path; } }
            public string StderrPath { get { return stderr.Path; } }
            public Int64 StdoutBytesSeen { get { return stdout.Total; } }
            public Int64 StderrBytesSeen { get { return stderr.Total; } }
            public Int64 StdoutBytesRetained { get { return stdout.Retained; } }
            public Int64 StderrBytesRetained { get { return stderr.Retained; } }
            public bool StdoutTruncated { get { return stdout.Total > stdout.Retained; } }
            public bool StderrTruncated { get { return stderr.Total > stderr.Retained; } }
            internal IntPtr OutputHandle { get { return stdout.WriteHandle; } }
            internal IntPtr ErrorHandle { get { return stderr.WriteHandle; } }

            private static string ValidatePath(string path)
            {
                if (String.IsNullOrWhiteSpace(path) || path.Length < 3 || !Char.IsLetter(path[0]) ||
                    path[1] != ':' || (path[2] != '\\' && path[2] != '/'))
                    throw new ArgumentException("Output path must be an absolute local drive path.");
                string full = System.IO.Path.GetFullPath(path);
                DirectoryInfo parent = new DirectoryInfo(System.IO.Path.GetDirectoryName(full));
                for (DirectoryInfo current = parent; current != null; current = current.Parent)
                    if (!current.Exists || (current.Attributes & FileAttributes.ReparsePoint) != 0)
                        throw new ArgumentException("Output parent must exist and may not traverse a reparse point.");
                return full;
            }

            public CapturedOutput(string stdoutPath, string stderrPath, Int32 maxBytesPerStream)
            {
                if (maxBytesPerStream < 1024 || maxBytesPerStream > 8388608)
                    throw new ArgumentOutOfRangeException("maxBytesPerStream");
                stdoutPath = ValidatePath(stdoutPath);
                stderrPath = ValidatePath(stderrPath);
                if (String.Equals(stdoutPath, stderrPath, StringComparison.OrdinalIgnoreCase))
                    throw new ArgumentException("Stdout and stderr require distinct paths.");
                try
                {
                    stdout = new PipeOutput(stdoutPath, maxBytesPerStream);
                    stderr = new PipeOutput(stderrPath, maxBytesPerStream);
                    SECURITY_ATTRIBUTES attributes = new SECURITY_ATTRIBUTES();
                    attributes.Length = Marshal.SizeOf(attributes);
                    attributes.InheritHandle = true;
                    InputHandle = CreateFile("NUL", 0x80000000, 3, ref attributes, 3, 0, IntPtr.Zero);
                    if (InputHandle == new IntPtr(-1))
                    {
                        InputHandle = IntPtr.Zero;
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Opening NUL stdin failed");
                    }
                    IntPtr size = IntPtr.Zero;
                    InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
                    if (size == IntPtr.Zero)
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Attribute-list sizing failed");
                    AttributeList = Marshal.AllocHGlobal(size);
                    if (!InitializeProcThreadAttributeList(AttributeList, 1, 0, ref size))
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Attribute-list initialization failed");
                    attributesInitialized = true;
                    handleList = Marshal.AllocHGlobal(IntPtr.Size * 3);
                    Marshal.WriteIntPtr(handleList, 0, InputHandle);
                    Marshal.WriteIntPtr(handleList, IntPtr.Size, OutputHandle);
                    Marshal.WriteIntPtr(handleList, IntPtr.Size * 2, ErrorHandle);
                    // PROC_THREAD_ATTRIBUTE_HANDLE_LIST, never ambient inheritance.
                    if (!UpdateProcThreadAttribute(AttributeList, 0, new IntPtr(0x20002),
                        handleList, new IntPtr(IntPtr.Size * 3), IntPtr.Zero, IntPtr.Zero))
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Restricted handle-list update failed");
                }
                catch { Dispose(); throw; }
            }

            internal void Claim()
            {
                if (disposed || used) throw new InvalidOperationException("Output capture can launch only one child.");
                used = true;
            }

            internal void CloseChildHandles()
            {
                if (stdout != null) stdout.CloseWriter();
                if (stderr != null) stderr.CloseWriter();
                if (InputHandle != IntPtr.Zero) { CloseHandle(InputHandle); InputHandle = IntPtr.Zero; }
                if (attributesInitialized) { DeleteProcThreadAttributeList(AttributeList); attributesInitialized = false; }
                if (AttributeList != IntPtr.Zero) { Marshal.FreeHGlobal(AttributeList); AttributeList = IntPtr.Zero; }
                if (handleList != IntPtr.Zero) { Marshal.FreeHGlobal(handleList); handleList = IntPtr.Zero; }
            }

            public void Drain()
            {
                if (disposed) throw new ObjectDisposedException("CapturedOutput");
                stdout.Drain();
                stderr.Drain();
            }

            // Call only after the containing Job proves zero active processes.
            public void Complete(Int32 timeoutMilliseconds)
            {
                if (timeoutMilliseconds < 0) throw new ArgumentOutOfRangeException("timeoutMilliseconds");
                Stopwatch wait = Stopwatch.StartNew();
                while (true)
                {
                    Drain();
                    if (stdout.Eof && stderr.Eof) break;
                    if (wait.ElapsedMilliseconds >= timeoutMilliseconds)
                        throw new TimeoutException("Output pipes did not reach EOF before the drain deadline.");
                    Thread.Sleep(1);
                }
                stdout.File.Flush(true);
                stderr.File.Flush(true);
                Completed = true;
            }

            public void Dispose()
            {
                if (disposed) return;
                disposed = true;
                CloseChildHandles();
                try { if (stdout != null) stdout.Dispose(); }
                finally { if (stderr != null) stderr.Dispose(); }
            }
        }

        public Process StartAssignedWithOutput(string executable, string arguments,
            string workingDirectory, CapturedOutput output)
        {
            if (output == null) throw new ArgumentNullException("output");
            output.Claim();
            try { return StartAssignedInternal(executable, arguments, workingDirectory, false, output); }
            finally { output.CloseChildHandles(); }
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
        [string]$WorkingDirectory,
        [Weather.Operations.KillOnCloseJob+CapturedOutput]$OutputCapture = $null
    )

    if ($null -ne $OutputCapture) {
        return $Job.StartAssignedWithOutput($FilePath, $ArgumentString, $WorkingDirectory, $OutputCapture)
    }
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
