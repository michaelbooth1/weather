# Windows Job Object helper for scheduled wrappers that own delegated children.
#
# A Job with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE makes child-tree ownership an
# operating-system invariant: if Task Scheduler terminates the PowerShell
# wrapper, Windows closes the wrapper's Job handle and terminates every process
# assigned to the Job. The handle is intentionally non-inheritable, so a child
# cannot keep its own containment Job alive after the wrapper exits.
# Normal evidence-producing callers use TerminateAndWaitForEmpty to prove the
# Job's active-process count reached zero before consuming redirected output.

Set-StrictMode -Version 2.0

if (-not ("Weather.Operations.KillOnCloseJobV3" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace Weather.Operations
{
    public sealed class RedirectedAssignedProcessV3 : IDisposable
    {
        private const UInt32 FILE_BEGIN = 0;
        private Process process;
        private IntPtr stdoutHandle;
        private IntPtr stderrHandle;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetFileSizeEx(IntPtr file, out Int64 fileSize);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetFilePointerEx(
            IntPtr file,
            Int64 distance,
            out Int64 newFilePointer,
            UInt32 moveMethod
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool ReadFile(
            IntPtr file,
            [Out] byte[] buffer,
            UInt32 bytesToRead,
            out UInt32 bytesRead,
            IntPtr overlapped
        );

        internal RedirectedAssignedProcessV3(
            Process ownedProcess,
            IntPtr ownedStdoutHandle,
            IntPtr ownedStderrHandle
        )
        {
            process = ownedProcess;
            stdoutHandle = ownedStdoutHandle;
            stderrHandle = ownedStderrHandle;
        }

        private Process CurrentProcess
        {
            get
            {
                if (process == null)
                {
                    throw new ObjectDisposedException("RedirectedAssignedProcessV3");
                }
                return process;
            }
        }

        public bool HasExited { get { return CurrentProcess.HasExited; } }
        public Int32 ExitCode { get { return CurrentProcess.ExitCode; } }
        public Int32 Id { get { return CurrentProcess.Id; } }
        public bool WaitForExit(Int32 milliseconds) { return CurrentProcess.WaitForExit(milliseconds); }
        public void WaitForExit() { CurrentProcess.WaitForExit(); }
        public void Refresh() { CurrentProcess.Refresh(); }

        private static Int64 RetainedLength(IntPtr file)
        {
            Int64 length;
            if (!GetFileSizeEx(file, out length))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "GetFileSizeEx failed");
            }
            return length;
        }

        public Int64 GetStandardOutputLength() { return RetainedLength(stdoutHandle); }
        public Int64 GetStandardErrorLength() { return RetainedLength(stderrHandle); }

        private byte[] ReadRetainedOutput(IntPtr file, Int32 maxBytes, string streamName)
        {
            if (maxBytes < 0)
            {
                throw new ArgumentOutOfRangeException("maxBytes");
            }
            if (!CurrentProcess.HasExited)
            {
                throw new InvalidOperationException(
                    streamName + " cannot be read before the assigned process exits"
                );
            }
            Int64 length = RetainedLength(file);
            if (length < 0 || length > maxBytes || length > Int32.MaxValue)
            {
                throw new InvalidOperationException(
                    streamName + " exceeds its retained output bound"
                );
            }
            Int64 newPointer;
            if (!SetFilePointerEx(file, 0, out newPointer, FILE_BEGIN) || newPointer != 0)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "SetFilePointerEx failed");
            }
            byte[] result = new byte[(Int32)length];
            Int32 offset = 0;
            while (offset < result.Length)
            {
                Int32 width = Math.Min(65536, result.Length - offset);
                byte[] chunk = new byte[width];
                UInt32 bytesRead;
                if (!ReadFile(file, chunk, (UInt32)width, out bytesRead, IntPtr.Zero))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "ReadFile failed");
                }
                if (bytesRead == 0)
                {
                    throw new InvalidOperationException(
                        streamName + " ended before its retained length"
                    );
                }
                Buffer.BlockCopy(chunk, 0, result, offset, (Int32)bytesRead);
                offset += (Int32)bytesRead;
            }
            return result;
        }

        public byte[] ReadStandardOutputBytes(Int32 maxBytes)
        {
            return ReadRetainedOutput(stdoutHandle, maxBytes, "stdout");
        }

        public byte[] ReadStandardErrorBytes(Int32 maxBytes)
        {
            return ReadRetainedOutput(stderrHandle, maxBytes, "stderr");
        }

        public void Dispose()
        {
            Exception processDisposeError = null;
            if (process != null)
            {
                try
                {
                    process.Dispose();
                }
                catch (Exception error)
                {
                    processDisposeError = error;
                }
                finally
                {
                    process = null;
                }
            }
            Int32 closeError = 0;
            if (stderrHandle != IntPtr.Zero)
            {
                if (CloseHandle(stderrHandle))
                {
                    stderrHandle = IntPtr.Zero;
                }
                else
                {
                    closeError = Marshal.GetLastWin32Error();
                }
            }
            if (stdoutHandle != IntPtr.Zero)
            {
                if (CloseHandle(stdoutHandle))
                {
                    stdoutHandle = IntPtr.Zero;
                }
                else if (closeError == 0)
                {
                    closeError = Marshal.GetLastWin32Error();
                }
            }
            if (closeError != 0)
            {
                throw new Win32Exception(closeError, "CloseHandle(retained output) failed");
            }
            GC.SuppressFinalize(this);
            if (processDisposeError != null)
            {
                throw new InvalidOperationException(
                    "Dispose(retained assigned process) failed after output handles closed",
                    processDisposeError
                );
            }
        }

        ~RedirectedAssignedProcessV3()
        {
            try
            {
                if (process != null)
                {
                    process.Dispose();
                    process = null;
                }
            }
            catch { }
            if (stderrHandle != IntPtr.Zero)
            {
                CloseHandle(stderrHandle);
                stderrHandle = IntPtr.Zero;
            }
            if (stdoutHandle != IntPtr.Zero)
            {
                CloseHandle(stdoutHandle);
                stdoutHandle = IntPtr.Zero;
            }
        }
    }

    public sealed class KillOnCloseJobV3 : IDisposable
    {
        private const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        private const Int32 JobObjectBasicAccountingInformation = 1;
        private const Int32 JobObjectExtendedLimitInformation = 9;
        private const UInt32 CREATE_SUSPENDED = 0x00000004;
        private const UInt32 CREATE_NO_WINDOW = 0x08000000;
        private const UInt32 EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
        private const UInt32 STARTF_USESTDHANDLES = 0x00000100;
        private const UInt32 GENERIC_READ = 0x80000000;
        private const UInt32 GENERIC_WRITE = 0x40000000;
        private const UInt32 FILE_SHARE_READ = 0x00000001;
        private const UInt32 FILE_SHARE_WRITE = 0x00000002;
        private const UInt32 CREATE_NEW = 1;
        private const UInt32 OPEN_EXISTING = 3;
        private const UInt32 FILE_ATTRIBUTE_NORMAL = 0x00000080;
        private const Int32 PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002;
        private static readonly IntPtr INVALID_HANDLE_VALUE = new IntPtr(-1);
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
        private static extern bool QueryInformationJobObject(
            IntPtr job,
            Int32 informationClass,
            out JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information,
            UInt32 informationLength,
            IntPtr returnLength
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, UInt32 exitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(
            IntPtr job,
            IntPtr process
        );

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

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct STARTUPINFOEX
        {
            public STARTUPINFO StartupInfo;
            public IntPtr lpAttributeList;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SECURITY_ATTRIBUTES
        {
            public Int32 nLength;
            public IntPtr lpSecurityDescriptor;
            [MarshalAs(UnmanagedType.Bool)]
            public bool bInheritHandle;
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

        [DllImport(
            "kernel32.dll",
            EntryPoint = "CreateProcessW",
            CharSet = CharSet.Unicode,
            SetLastError = true
        )]
        private static extern bool CreateProcessWithExtendedStartupInfo(
            string applicationName,
            StringBuilder commandLine,
            IntPtr processAttributes,
            IntPtr threadAttributes,
            bool inheritHandles,
            UInt32 creationFlags,
            IntPtr environment,
            string currentDirectory,
            ref STARTUPINFOEX startupInfo,
            out PROCESS_INFORMATION processInformation
        );

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateFile(
            string fileName,
            UInt32 desiredAccess,
            UInt32 shareMode,
            ref SECURITY_ATTRIBUTES securityAttributes,
            UInt32 creationDisposition,
            UInt32 flagsAndAttributes,
            IntPtr templateFile
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool InitializeProcThreadAttributeList(
            IntPtr attributeList,
            Int32 attributeCount,
            UInt32 flags,
            ref UIntPtr size
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool UpdateProcThreadAttribute(
            IntPtr attributeList,
            UInt32 flags,
            IntPtr attribute,
            IntPtr value,
            IntPtr size,
            IntPtr previousValue,
            IntPtr returnSize
        );

        [DllImport("kernel32.dll")]
        private static extern void DeleteProcThreadAttributeList(IntPtr attributeList);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern UInt32 ResumeThread(IntPtr thread);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateProcess(IntPtr process, UInt32 exitCode);

        private KillOnCloseJobV3(IntPtr jobHandle)
        {
            handle = jobHandle;
        }

        public static KillOnCloseJobV3 Create()
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
                return new KillOnCloseJobV3(job);
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

        public Process StartAssigned(
            string executable,
            string arguments,
            string workingDirectory
        )
        {
            if (String.IsNullOrWhiteSpace(executable))
            {
                throw new ArgumentException("executable is required", "executable");
            }
            if (handle == IntPtr.Zero)
            {
                throw new ObjectDisposedException("KillOnCloseJobV3");
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
                false,
                CREATE_SUSPENDED | CREATE_NO_WINDOW,
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

        public RedirectedAssignedProcessV3 StartAssignedRedirected(
            string executable,
            string arguments,
            string workingDirectory,
            string standardOutputPath,
            string standardErrorPath
        )
        {
            if (String.IsNullOrWhiteSpace(executable))
            {
                throw new ArgumentException("executable is required", "executable");
            }
            if (handle == IntPtr.Zero)
            {
                throw new ObjectDisposedException("KillOnCloseJobV3");
            }
            string stdoutPath = System.IO.Path.GetFullPath(standardOutputPath);
            string stderrPath = System.IO.Path.GetFullPath(standardErrorPath);
            if (String.Equals(stdoutPath, stderrPath, StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException("stdout and stderr paths must differ");
            }
            if (!System.IO.Directory.Exists(System.IO.Path.GetDirectoryName(stdoutPath)) ||
                !System.IO.Directory.Exists(System.IO.Path.GetDirectoryName(stderrPath)))
            {
                throw new ArgumentException("redirected output parents must already exist");
            }

            SECURITY_ATTRIBUTES security = new SECURITY_ATTRIBUTES();
            security.nLength = Marshal.SizeOf(security);
            security.lpSecurityDescriptor = IntPtr.Zero;
            security.bInheritHandle = true;
            IntPtr stdinHandle = INVALID_HANDLE_VALUE;
            IntPtr stdoutHandle = INVALID_HANDLE_VALUE;
            IntPtr stderrHandle = INVALID_HANDLE_VALUE;
            IntPtr attributeList = IntPtr.Zero;
            IntPtr handleList = IntPtr.Zero;
            bool attributeListInitialized = false;
            PROCESS_INFORMATION processInfo = new PROCESS_INFORMATION();
            bool processCreated = false;
            try
            {
                stdinHandle = CreateFile(
                    "NUL",
                    GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    ref security,
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL,
                    IntPtr.Zero
                );
                if (stdinHandle == INVALID_HANDLE_VALUE)
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateFile(NUL) failed");
                }
                stdoutHandle = CreateFile(
                    stdoutPath,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ,
                    ref security,
                    CREATE_NEW,
                    FILE_ATTRIBUTE_NORMAL,
                    IntPtr.Zero
                );
                if (stdoutHandle == INVALID_HANDLE_VALUE)
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateFile(stdout CREATE_NEW) failed");
                }
                stderrHandle = CreateFile(
                    stderrPath,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ,
                    ref security,
                    CREATE_NEW,
                    FILE_ATTRIBUTE_NORMAL,
                    IntPtr.Zero
                );
                if (stderrHandle == INVALID_HANDLE_VALUE)
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateFile(stderr CREATE_NEW) failed");
                }

                UIntPtr attributeBytes = UIntPtr.Zero;
                InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref attributeBytes);
                if (attributeBytes == UIntPtr.Zero)
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "InitializeProcThreadAttributeList size query failed"
                    );
                }
                attributeList = Marshal.AllocHGlobal(
                    new IntPtr(checked((Int64)attributeBytes.ToUInt64()))
                );
                if (!InitializeProcThreadAttributeList(attributeList, 1, 0, ref attributeBytes))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "InitializeProcThreadAttributeList failed"
                    );
                }
                attributeListInitialized = true;
                handleList = Marshal.AllocHGlobal(IntPtr.Size * 3);
                Marshal.WriteIntPtr(handleList, 0, stdinHandle);
                Marshal.WriteIntPtr(handleList, IntPtr.Size, stdoutHandle);
                Marshal.WriteIntPtr(handleList, IntPtr.Size * 2, stderrHandle);
                if (!UpdateProcThreadAttribute(
                    attributeList,
                    0,
                    new IntPtr(PROC_THREAD_ATTRIBUTE_HANDLE_LIST),
                    handleList,
                    new IntPtr(IntPtr.Size * 3),
                    IntPtr.Zero,
                    IntPtr.Zero
                ))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "UpdateProcThreadAttribute(HANDLE_LIST) failed"
                    );
                }

                STARTUPINFOEX startup = new STARTUPINFOEX();
                startup.StartupInfo.cb = Marshal.SizeOf(startup);
                startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
                startup.StartupInfo.hStdInput = stdinHandle;
                startup.StartupInfo.hStdOutput = stdoutHandle;
                startup.StartupInfo.hStdError = stderrHandle;
                startup.lpAttributeList = attributeList;
                StringBuilder commandLine = new StringBuilder(
                    "\"" + executable + "\"" +
                    (String.IsNullOrWhiteSpace(arguments) ? "" : " " + arguments)
                );
                processCreated = CreateProcessWithExtendedStartupInfo(
                    executable,
                    commandLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    true,
                    CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
                    IntPtr.Zero,
                    workingDirectory,
                    ref startup,
                    out processInfo
                );
                if (!processCreated)
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "CreateProcess(CREATE_SUSPENDED, redirected) failed"
                    );
                }

                Process managedProcess = null;
                try
                {
                    if (!AssignProcessToJobObject(handle, processInfo.hProcess))
                    {
                        throw new Win32Exception(
                            Marshal.GetLastWin32Error(),
                            "AssignProcessToJobObject before redirected resume failed"
                        );
                    }
                    managedProcess = Process.GetProcessById((Int32)processInfo.dwProcessId);
                    IntPtr managedHandle = managedProcess.Handle;
                    if (ResumeThread(processInfo.hThread) == UInt32.MaxValue)
                    {
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread failed");
                    }
                    RedirectedAssignedProcessV3 redirected = new RedirectedAssignedProcessV3(
                        managedProcess,
                        stdoutHandle,
                        stderrHandle
                    );
                    stdoutHandle = INVALID_HANDLE_VALUE;
                    stderrHandle = INVALID_HANDLE_VALUE;
                    return redirected;
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
            }
            finally
            {
                if (processCreated)
                {
                    CloseHandle(processInfo.hThread);
                    CloseHandle(processInfo.hProcess);
                }
                if (attributeListInitialized)
                {
                    DeleteProcThreadAttributeList(attributeList);
                }
                if (attributeList != IntPtr.Zero)
                {
                    Marshal.FreeHGlobal(attributeList);
                }
                if (handleList != IntPtr.Zero)
                {
                    Marshal.FreeHGlobal(handleList);
                }
                if (stderrHandle != INVALID_HANDLE_VALUE)
                {
                    CloseHandle(stderrHandle);
                }
                if (stdoutHandle != INVALID_HANDLE_VALUE)
                {
                    CloseHandle(stdoutHandle);
                }
                if (stdinHandle != INVALID_HANDLE_VALUE)
                {
                    CloseHandle(stdinHandle);
                }
            }
        }

        // Terminate the entire assigned process tree, prove through the Job's
        // accounting state that no assigned process remains, and only then
        // close the non-inheritable Job handle. A timeout or API failure leaves
        // the handle owned so Dispose/finalization still supplies last-resort
        // KILL_ON_JOB_CLOSE teardown, but it never claims a drained tree.
        public void TerminateAndWaitForEmpty(Int32 timeoutMilliseconds)
        {
            if (timeoutMilliseconds < 0)
            {
                throw new ArgumentOutOfRangeException("timeoutMilliseconds");
            }
            if (handle == IntPtr.Zero)
            {
                throw new ObjectDisposedException("KillOnCloseJobV3");
            }
            if (!TerminateJobObject(handle, 1))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "TerminateJobObject failed"
                );
            }

            Stopwatch stopwatch = Stopwatch.StartNew();
            UInt32 activeProcesses = UInt32.MaxValue;
            while (true)
            {
                JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting;
                if (!QueryInformationJobObject(
                    handle,
                    JobObjectBasicAccountingInformation,
                    out accounting,
                    (UInt32)Marshal.SizeOf(typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)),
                    IntPtr.Zero
                ))
                {
                    throw new Win32Exception(
                        Marshal.GetLastWin32Error(),
                        "QueryInformationJobObject(active process count) failed"
                    );
                }
                activeProcesses = accounting.ActiveProcesses;
                if (activeProcesses == 0)
                {
                    break;
                }
                if (stopwatch.ElapsedMilliseconds >= timeoutMilliseconds)
                {
                    throw new TimeoutException(
                        "Kill-on-close Job did not drain within " +
                        timeoutMilliseconds + " ms; active_processes=" + activeProcesses
                    );
                }
                Thread.Sleep(25);
            }

            if (!CloseHandle(handle))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "CloseHandle(drained kill-on-close Job) failed"
                );
            }
            handle = IntPtr.Zero;
            GC.SuppressFinalize(this);
        }

        public void Dispose()
        {
            if (handle == IntPtr.Zero)
            {
                return;
            }
            if (!CloseHandle(handle))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "CloseHandle(kill-on-close Job) failed"
                );
            }
            handle = IntPtr.Zero;
            GC.SuppressFinalize(this);
        }

        ~KillOnCloseJobV3()
        {
            if (handle != IntPtr.Zero)
            {
                CloseHandle(handle);
                handle = IntPtr.Zero;
            }
        }
    }
}
'@
}

function New-WeatherKillOnCloseJob {
    [CmdletBinding()]
    param()

    return [Weather.Operations.KillOnCloseJobV3]::Create()
}

function Start-WeatherProcessInJob {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [Weather.Operations.KillOnCloseJobV3]$Job,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$ArgumentString,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    return $Job.StartAssigned($FilePath, $ArgumentString, $WorkingDirectory)
}

function Start-WeatherProcessInJobWithRedirectedOutput {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [Weather.Operations.KillOnCloseJobV3]$Job,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$ArgumentString,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$StandardOutputPath,
        [Parameter(Mandatory = $true)]
        [string]$StandardErrorPath
    )

    return $Job.StartAssignedRedirected(
        $FilePath,
        $ArgumentString,
        $WorkingDirectory,
        $StandardOutputPath,
        $StandardErrorPath
    )
}
