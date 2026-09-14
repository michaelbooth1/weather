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
    public sealed class BoundedJobSnapshot
    {
        public Int32[] ProcessIds;
        public UInt64 PeakCommitBytes;
        public UInt64 SampledPrivateBytes;
        public UInt64 SampledWorkingSetBytes;
        public UInt64 CommitLimitBytes;
        public bool NativeLimitExceeded;
        public Int64 UserTime100ns;
        public Int64 KernelTime100ns;
        public UInt32 ActiveProcesses;
        public UInt32 TotalProcesses;
    }

    public sealed class CapturedJobProcess : IDisposable
    {
        public readonly Process Process;
        private readonly System.IO.FileStream pipe;
        private readonly System.IO.FileStream output;
        private readonly Thread reader;
        private readonly Int64 maximum;
        private Int64 bytes;
        private volatile bool exceeded;
        private volatile bool finished;
        private volatile string error;
        public Int64 OutputBytes { get { return Interlocked.Read(ref bytes); } }
        public bool OutputExceeded { get { return exceeded; } }
        public bool CaptureComplete { get { return finished; } }
        public string CaptureError { get { return error; } }

        internal CapturedJobProcess(Process process, Microsoft.Win32.SafeHandles.SafeFileHandle read, string transcript, Int64 maximumOutput)
        {
            Process = process;
            maximum = maximumOutput;
            try
            {
                pipe = new System.IO.FileStream(read, System.IO.FileAccess.Read, 65536, false);
                output = new System.IO.FileStream(transcript, System.IO.FileMode.CreateNew,
                    System.IO.FileAccess.Write, System.IO.FileShare.Read);
                reader = new Thread(ReadOutput);
                reader.IsBackground = true;
                reader.Start();
            }
            catch
            {
                if (output != null) output.Dispose();
                if (pipe != null) pipe.Dispose();
                else read.Dispose();
                throw;
            }
        }

        private void ReadOutput()
        {
            try
            {
                byte[] buffer = new byte[65536];
                Int32 count;
                while ((count = pipe.Read(buffer, 0, buffer.Length)) != 0)
                {
                    Int64 previous = Interlocked.Read(ref bytes);
                    Int32 retain = (Int32)Math.Max(0, Math.Min((Int64)count, maximum - previous));
                    if (retain > 0) output.Write(buffer, 0, retain);
                    Interlocked.Add(ref bytes, count);
                    if (previous + count > maximum) exceeded = true;
                }
                output.Flush(true);
            }
            catch (Exception exception) { error = exception.GetType().FullName; }
            finally
            {
                try { output.Dispose(); } catch (Exception exception) { error = exception.GetType().FullName; }
                try { pipe.Dispose(); } catch (Exception exception) { error = exception.GetType().FullName; }
                finished = true;
            }
        }

        public bool WaitForCapture(Int32 milliseconds)
        {
            if (milliseconds < 0 || milliseconds > 120000) throw new ArgumentOutOfRangeException("milliseconds");
            return reader.Join(milliseconds) && finished;
        }

        public void Dispose()
        {
            // Caller first terminates the Job and proves zero children. Closing
            // the pipe on an uncertain path cannot create a successful capture.
            if (!finished) { error = "capture disposed before complete teardown"; pipe.Dispose(); }
            reader.Join(1000);
            Process.Dispose();
        }
    }


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

        private IntPtr completionPort = IntPtr.Zero;
        private bool nativeLimitExceeded;

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_ASSOCIATE_COMPLETION_PORT
        {
            public IntPtr CompletionKey;
            public IntPtr CompletionPort;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateIoCompletionPort(IntPtr file, IntPtr existing, UIntPtr key, UInt32 threads);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetQueuedCompletionStatus(IntPtr port, out UInt32 message, out UIntPtr key,
            out IntPtr overlapped, UInt32 milliseconds);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern UInt32 WaitForSingleObject(IntPtr value, UInt32 milliseconds);

        public static KillOnCloseJob CreateBounded(UInt64 maximumCommitBytes, UInt32 maximumProcesses)
        {
            if (IntPtr.Size != 8 || maximumCommitBytes < 16UL * 1024 * 1024 || maximumCommitBytes > 64UL * 1024 * 1024 * 1024 ||
                maximumProcesses < 1 || maximumProcesses > 128)
                throw new ArgumentOutOfRangeException("bounded Job limits");
            KillOnCloseJob job = Create();
            try
            {
                job.completionPort = CreateIoCompletionPort(new IntPtr(-1), IntPtr.Zero, UIntPtr.Zero, 1);
                if (job.completionPort == IntPtr.Zero)
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateIoCompletionPort failed");
                JOBOBJECT_ASSOCIATE_COMPLETION_PORT port = new JOBOBJECT_ASSOCIATE_COMPLETION_PORT();
                port.CompletionKey = new IntPtr(1);
                port.CompletionPort = job.completionPort;
                job.SetJobInformation(7, port);
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | 0x200 | 0x8 | 0x20;
                limits.BasicLimitInformation.ActiveProcessLimit = maximumProcesses;
                limits.BasicLimitInformation.PriorityClass = 0x4000; // BELOW_NORMAL_PRIORITY_CLASS
                limits.JobMemoryLimit = new UIntPtr(maximumCommitBytes);
                job.SetJobInformation(JobObjectExtendedLimitInformation, limits);
                return job;
            }
            catch { job.Dispose(); throw; }
        }

        private bool includesController;

        // This non-killing enclosing Job accounts for the trusted controller,
        // output reader, monitor and every descendant together. A nested
        // kill-on-close Job separately owns candidate teardown. Closing this
        // handle does not remove the enclosing limits from the running process.
        public static KillOnCloseJob EncloseCurrentProcess(UInt64 maximumCommitBytes, UInt32 maximumProcesses)
        {
            KillOnCloseJob envelope = CreateBounded(maximumCommitBytes, maximumProcesses);
            try
            {
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = envelope.ReadJobInformation<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>(9);
                limits.BasicLimitInformation.LimitFlags &= ~JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                envelope.SetJobInformation(9, limits);
                using (Process current = Process.GetCurrentProcess())
                {
                    if (!AssignProcessToJobObject(envelope.handle, current.Handle))
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Controller memory-envelope assignment failed");
                }
                envelope.includesController = true;
                return envelope;
            }
            catch { envelope.Dispose(); throw; }
        }

        public void SetEnvelopeCommitLimit(UInt64 maximumCommitBytes)
        {
            if (!includesController || handle == IntPtr.Zero)
                throw new InvalidOperationException("An active controller envelope is required");
            if (maximumCommitBytes < 16UL * 1024 * 1024 || maximumCommitBytes > 64UL * 1024 * 1024 * 1024)
                throw new ArgumentOutOfRangeException("maximumCommitBytes");
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = ReadJobInformation<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>(9);
            limits.JobMemoryLimit = new UIntPtr(maximumCommitBytes);
            SetJobInformation(9, limits);
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PROCESS_MEMORY_COUNTERS_EX
        {
            public UInt32 cb;
            public UInt32 PageFaultCount;
            public UIntPtr PeakWorkingSetSize, WorkingSetSize, QuotaPeakPagedPoolUsage, QuotaPagedPoolUsage;
            public UIntPtr QuotaPeakNonPagedPoolUsage, QuotaNonPagedPoolUsage, PagefileUsage, PeakPagefileUsage, PrivateUsage;
        }

        [DllImport("psapi.dll", SetLastError = true)]
        private static extern bool GetProcessMemoryInfo(IntPtr process, ref PROCESS_MEMORY_COUNTERS_EX information, UInt32 size);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);

        private void SampleProcessMemory(BoundedJobSnapshot snapshot)
        {
            foreach (Int32 pid in snapshot.ProcessIds)
            {
                try
                {
                    using (Process process = Process.GetProcessById(pid))
                    {
                        bool owned;
                        if (!IsProcessInJob(process.Handle, handle, out owned))
                            throw new Win32Exception(Marshal.GetLastWin32Error(), "Job process membership telemetry failed");
                        if (!owned) throw new InvalidOperationException("Job process identity changed during sampling");
                        PROCESS_MEMORY_COUNTERS_EX memory = new PROCESS_MEMORY_COUNTERS_EX();
                        memory.cb = (UInt32)Marshal.SizeOf(memory);
                        if (!GetProcessMemoryInfo(process.Handle, ref memory, memory.cb))
                        {
                            if (process.HasExited) continue;
                            throw new Win32Exception(Marshal.GetLastWin32Error(), "Job process memory telemetry unavailable");
                        }
                        checked
                        {
                            snapshot.SampledPrivateBytes += memory.PrivateUsage.ToUInt64();
                            snapshot.SampledWorkingSetBytes += memory.WorkingSetSize.ToUInt64();
                        }
                    }
                }
                catch (ArgumentException)
                {
                    // A process can exit between Job enumeration and opening its
                    // handle. Only a second native inventory can excuse that race.
                    if (Array.IndexOf(ProcessIds(), pid) >= 0) throw;
                }
                catch (InvalidOperationException)
                {
                    if (Array.IndexOf(ProcessIds(), pid) >= 0) throw;
                }
            }
        }


        private void SetJobInformation(Int32 kind, object value)
        {
            Int32 size = Marshal.SizeOf(value);
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.StructureToPtr(value, buffer, false);
                if (!SetInformationJobObject(handle, kind, buffer, (UInt32)size))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "SetInformationJobObject failed");
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        private T ReadJobInformation<T>(Int32 kind) where T : struct
        {
            Int32 size = Marshal.SizeOf(typeof(T));
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                UInt32 returned;
                if (!QueryInformationJobObject(handle, kind, buffer, (UInt32)size, out returned))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject failed");
                return (T)Marshal.PtrToStructure(buffer, typeof(T));
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        public Int32[] ProcessIds()
        {
            if (handle == IntPtr.Zero) throw new ObjectDisposedException("KillOnCloseJob");
            const Int32 maximum = 128;
            Int32 size = 8 + maximum * IntPtr.Size;
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                UInt32 returned;
                if (!QueryInformationJobObject(handle, 3, buffer, (UInt32)size, out returned))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Job process inventory unavailable");
                Int32 assigned = Marshal.ReadInt32(buffer, 0);
                Int32 count = Marshal.ReadInt32(buffer, 4);
                if (assigned < 0 || count < 0 || count > maximum || assigned != count)
                    throw new InvalidOperationException("Job process inventory truncated");
                Int32[] result = new Int32[count];
                for (Int32 i = 0; i < count; i++)
                    result[i] = checked((Int32)Marshal.ReadIntPtr(buffer, 8 + i * IntPtr.Size).ToInt64());
                return result;
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        public BoundedJobSnapshot Snapshot()
        {
            if (handle == IntPtr.Zero) throw new ObjectDisposedException("KillOnCloseJob");
            if (completionPort != IntPtr.Zero)
            {
                bool drained = false;
                for (Int32 i = 0; i < 1024; i++)
                {
                    UInt32 message;
                    UIntPtr key;
                    IntPtr overlapped;
                    if (!GetQueuedCompletionStatus(completionPort, out message, out key, out overlapped, 0))
                    {
                        if (Marshal.GetLastWin32Error() != 258)
                            throw new Win32Exception(Marshal.GetLastWin32Error(), "Job completion telemetry lost");
                        drained = true;
                        break;
                    }
                    if (key.ToUInt64() != 1) throw new InvalidOperationException("Unexpected completion identity");
                    if (message == 3 || message == 9 || message == 10) nativeLimitExceeded = true;
                }
                if (!drained) throw new InvalidOperationException("Job telemetry exceeded bound");
            }
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = ReadJobInformation<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>(9);
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting = ReadJobInformation<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>(1);
            BoundedJobSnapshot snapshot = new BoundedJobSnapshot {
                ProcessIds = ProcessIds(), PeakCommitBytes = limits.PeakJobMemoryUsed.ToUInt64(),
                CommitLimitBytes = limits.JobMemoryLimit.ToUInt64(), NativeLimitExceeded = nativeLimitExceeded,
                UserTime100ns = accounting.TotalUserTime, KernelTime100ns = accounting.TotalKernelTime,
                ActiveProcesses = accounting.ActiveProcesses, TotalProcesses = accounting.TotalProcesses
            };
            // Native peak accounting retains refused allocation attempts on
            // supported Windows. Keep the raw counter; never clip it to the
            // cap or describe it as measured resident consumption. Completion
            // messages are supplementary and absence is not a no-breach proof.
            if (snapshot.CommitLimitBytes > 0 && snapshot.PeakCommitBytes > snapshot.CommitLimitBytes)
                nativeLimitExceeded = true;
            snapshot.NativeLimitExceeded = nativeLimitExceeded;
            SampleProcessMemory(snapshot);
            return snapshot;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SECURITY_ATTRIBUTES
        {
            public Int32 Length;
            public IntPtr SecurityDescriptor;
            [MarshalAs(UnmanagedType.Bool)] public bool InheritHandle;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct STARTUPINFOEX
        {
            public STARTUPINFO StartupInfo;
            public IntPtr AttributeList;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CreatePipe(out IntPtr read, out IntPtr write, ref SECURITY_ATTRIBUTES attributes, UInt32 size);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(IntPtr target, UInt32 mask, UInt32 flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateFile(string name, UInt32 access, UInt32 share, ref SECURITY_ATTRIBUTES attributes,
            UInt32 disposition, UInt32 flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool InitializeProcThreadAttributeList(IntPtr list, Int32 count, UInt32 flags, ref UIntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool UpdateProcThreadAttribute(IntPtr list, UInt32 flags, UIntPtr attribute,
            IntPtr value, UIntPtr size, IntPtr previous, IntPtr returned);
        [DllImport("kernel32.dll")]
        private static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CreateProcessCaptured(string application, StringBuilder command, IntPtr processAttributes,
            IntPtr threadAttributes, bool inheritHandles, UInt32 flags, IntPtr environment, string directory,
            ref STARTUPINFOEX startup, out PROCESS_INFORMATION information);

        public CapturedJobProcess StartAssignedCaptured(string executable, string arguments, string directory,
            string transcript, Int64 maximumOutputBytes)
        {
            if (handle == IntPtr.Zero) throw new ObjectDisposedException("KillOnCloseJob");
            if (!System.IO.Path.IsPathRooted(executable) || !System.IO.Path.IsPathRooted(directory) ||
                !System.IO.Path.IsPathRooted(transcript) || maximumOutputBytes < 1 || maximumOutputBytes > 128L * 1024 * 1024)
                throw new ArgumentException("Absolute reviewed paths and bounded output required");
            SECURITY_ATTRIBUTES attributes = new SECURITY_ATTRIBUTES();
            attributes.Length = Marshal.SizeOf(attributes);
            attributes.InheritHandle = true;
            IntPtr read = IntPtr.Zero, write = IntPtr.Zero, input = IntPtr.Zero, list = IntPtr.Zero, inherited = IntPtr.Zero;
            bool listInitialized = false, created = false;
            PROCESS_INFORMATION info = new PROCESS_INFORMATION();
            Process process = null;
            CapturedJobProcess captured = null;
            Microsoft.Win32.SafeHandles.SafeFileHandle captureRead = null;
            try
            {
                if (!CreatePipe(out read, out write, ref attributes, 65536) || !SetHandleInformation(read, 1, 0))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Bounded output pipe unavailable");
                input = CreateFile("NUL", 0x80000000, 3, ref attributes, 3, 0, IntPtr.Zero);
                if (input == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error(), "NUL stdin unavailable");
                UIntPtr size = UIntPtr.Zero;
                InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
                if (size.ToUInt64() == 0 || size.ToUInt64() > 1024 * 1024)
                    throw new InvalidOperationException("Invalid native attribute-list size");
                list = Marshal.AllocHGlobal(checked((Int32)size.ToUInt64()));
                if (!InitializeProcThreadAttributeList(list, 1, 0, ref size))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Native handle-list initialization failed");
                listInitialized = true;
                inherited = Marshal.AllocHGlobal(2 * IntPtr.Size);
                Marshal.WriteIntPtr(inherited, 0, input);
                Marshal.WriteIntPtr(inherited, IntPtr.Size, write);
                if (!UpdateProcThreadAttribute(list, 0, new UIntPtr(0x20002), inherited,
                    new UIntPtr((UInt32)(2 * IntPtr.Size)), IntPtr.Zero, IntPtr.Zero))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Explicit inherited-handle list failed");
                STARTUPINFOEX startup = new STARTUPINFOEX();
                startup.StartupInfo.cb = Marshal.SizeOf(startup);
                startup.StartupInfo.dwFlags = 0x100;
                startup.StartupInfo.hStdInput = input;
                startup.StartupInfo.hStdOutput = write;
                startup.StartupInfo.hStdError = write;
                startup.AttributeList = list;
                StringBuilder command = new StringBuilder("\"" + executable + "\"" + (String.IsNullOrWhiteSpace(arguments) ? "" : " " + arguments));
                created = CreateProcessCaptured(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                    CREATE_SUSPENDED | CREATE_NO_WINDOW | 0x80000, IntPtr.Zero, directory, ref startup, out info);
                if (!created) throw new Win32Exception(Marshal.GetLastWin32Error(), "Captured CreateProcess failed");
                if (!AssignProcessToJobObject(handle, info.hProcess))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Captured child assignment failed before resume");
                process = Process.GetProcessById((Int32)info.dwProcessId);
                IntPtr waitable = process.Handle;
                captureRead = new Microsoft.Win32.SafeHandles.SafeFileHandle(read, true);
                read = IntPtr.Zero;
                captured = new CapturedJobProcess(process, captureRead, transcript, maximumOutputBytes);
                captureRead = null; // the capture stream owns this SafeFileHandle
                if (ResumeThread(info.hThread) == UInt32.MaxValue)
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Captured child resume failed");
                return captured;
            }
            catch
            {
                if (created)
                {
                    TerminateProcess(info.hProcess, 1);
                    if (WaitForSingleObject(info.hProcess, 5000) != 0)
                        throw new InvalidOperationException("Failed captured child teardown is unproved; PID=" + info.dwProcessId);
                }
                if (captured != null) captured.Dispose();
                else if (process != null) process.Dispose();
                throw;
            }
            finally
            {
                if (created) { CloseHandle(info.hThread); CloseHandle(info.hProcess); }
                if (captureRead != null) captureRead.Dispose();
                if (read != IntPtr.Zero) CloseHandle(read);
                if (write != IntPtr.Zero) CloseHandle(write);
                if (input != IntPtr.Zero && input != new IntPtr(-1)) CloseHandle(input);
                if (listInitialized) DeleteProcThreadAttributeList(list);
                if (list != IntPtr.Zero) Marshal.FreeHGlobal(list);
                if (inherited != IntPtr.Zero) Marshal.FreeHGlobal(inherited);
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
                if (WaitForSingleObject(processInfo.hProcess, 5000) != 0)
                    throw new InvalidOperationException("Failed suspended child teardown is unproved; PID=" + processInfo.dwProcessId);
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
            if (includesController) throw new InvalidOperationException("Terminate only the nested candidate Job, never the controller envelope");
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
            if (completionPort != IntPtr.Zero) { CloseHandle(completionPort); completionPort = IntPtr.Zero; }
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
