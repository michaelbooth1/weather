# Native identity observations for the adopted S4U qualification entrypoint.
# Reading the current token does not authenticate downloaded evidence or grant
# invocation authority. The guarded parent supplies the reviewed host/principal.
Set-StrictMode -Version Latest

function Initialize-WeatherQualificationLogonReader {
    if ('Weather.Operations.QualificationLogonReader' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;

namespace Weather.Operations
{
    public sealed class QualificationLogonIdentity
    {
        public String Sid, AuthenticationId;
        public UInt32 LogonType, TokenType, Session;
        public Boolean Elevated;
    }

    public static class QualificationLogonReader
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct LUID { public UInt32 LowPart; public Int32 HighPart; }
        [StructLayout(LayoutKind.Sequential)]
        private struct TOKEN_STATISTICS
        {
            public LUID TokenId, AuthenticationId;
            public Int64 ExpirationTime;
            public UInt32 TokenType, ImpersonationLevel, DynamicCharged, DynamicAvailable, GroupCount, PrivilegeCount;
            public LUID ModifiedId;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct LSA_UNICODE_STRING { public UInt16 Length, MaximumLength; public IntPtr Buffer; }
        // The documented prefix ends at Sid. No account names, authentication
        // package strings or credential material are dereferenced or retained.
        [StructLayout(LayoutKind.Sequential)]
        private struct LOGON_PREFIX
        {
            public UInt32 Size;
            public LUID LogonId;
            public LSA_UNICODE_STRING UserName, LogonDomain, AuthenticationPackage;
            public UInt32 LogonType, Session;
            public IntPtr Sid;
        }
        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern Boolean GetTokenInformation(IntPtr token, Int32 informationClass, IntPtr information,
                                                          UInt32 length, out UInt32 returnedLength);
        [DllImport("secur32.dll")]
        private static extern UInt32 LsaGetLogonSessionData(ref LUID logonId, out IntPtr data);
        [DllImport("secur32.dll")]
        private static extern UInt32 LsaFreeReturnBuffer(IntPtr buffer);
        [DllImport("shell32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern IntPtr CommandLineToArgvW(String command, out Int32 count);
        [DllImport("kernel32.dll")]
        private static extern IntPtr LocalFree(IntPtr memory);

        public static String[] Arguments(String command)
        {
            Int32 count;
            IntPtr pointer = CommandLineToArgvW(command, out count);
            if (pointer == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            try {
                if (count < 1 || count > 64) throw new InvalidOperationException("Unbounded qualification command line");
                String[] arguments = new String[count];
                for (Int32 index = 0; index < count; index++)
                    arguments[index] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(pointer, index * IntPtr.Size));
                return arguments;
            } finally { LocalFree(pointer); }
        }

        public static QualificationLogonIdentity Read()
        {
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent()) {
                Int32 size = Marshal.SizeOf(typeof(TOKEN_STATISTICS));
                IntPtr buffer = Marshal.AllocHGlobal(size);
                IntPtr session = IntPtr.Zero;
                try {
                    UInt32 returned;
                    if (!GetTokenInformation(identity.Token, 10, buffer, (UInt32)size, out returned) || returned != size)
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Native token statistics unavailable");
                    TOKEN_STATISTICS statistics = (TOKEN_STATISTICS)Marshal.PtrToStructure(buffer, typeof(TOKEN_STATISTICS));
                    if (!GetTokenInformation(identity.Token, 20, buffer, (UInt32)size, out returned) || returned != 4)
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Native token elevation unavailable");
                    Boolean elevated = Marshal.ReadInt32(buffer) != 0;
                    UInt32 status = LsaGetLogonSessionData(ref statistics.AuthenticationId, out session);
                    if (status != 0 || session == IntPtr.Zero)
                        throw new InvalidOperationException("Native logon session unavailable");
                    LOGON_PREFIX data = (LOGON_PREFIX)Marshal.PtrToStructure(session, typeof(LOGON_PREFIX));
                    if (data.Size < Marshal.SizeOf(typeof(LOGON_PREFIX)) || data.Sid == IntPtr.Zero ||
                        data.LogonId.LowPart != statistics.AuthenticationId.LowPart || data.LogonId.HighPart != statistics.AuthenticationId.HighPart)
                        throw new InvalidOperationException("Native logon session identity mismatch");
                    String sid = new SecurityIdentifier(data.Sid).Value;
                    if (identity.User == null || sid != identity.User.Value)
                        throw new InvalidOperationException("Token and logon principal differ");
                    return new QualificationLogonIdentity {
                        Sid = sid,
                        AuthenticationId = ((UInt32)statistics.AuthenticationId.HighPart).ToString("x8") + statistics.AuthenticationId.LowPart.ToString("x8"),
                        LogonType = data.LogonType, TokenType = statistics.TokenType, Session = data.Session, Elevated = elevated
                    };
                } finally {
                    if (session != IntPtr.Zero) LsaFreeReturnBuffer(session);
                    Marshal.FreeHGlobal(buffer);
                }
            }
        }
    }
}
'@
}

function Get-WeatherQualificationCurrentLogon {
    Initialize-WeatherQualificationLogonReader
    $identity = [Weather.Operations.QualificationLogonReader]::Read()
    $process = [Diagnostics.Process]::GetCurrentProcess()
    try {
        return [pscustomobject]@{
            pid = $PID; creation_utc_ticks = $process.StartTime.ToUniversalTime().Ticks
            image = $process.MainModule.FileName; sid = $identity.Sid
            authentication_id = $identity.AuthenticationId; logon_type = [int]$identity.LogonType
            token_type = [int]$identity.TokenType; session = [int]$identity.Session; elevated = $identity.Elevated
        }
    } finally { $process.Dispose() }
}

function Assert-WeatherQualificationS4UInvocation {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet('host', 'merge')][string]$Role,
        [Parameter(Mandatory = $true)][string]$ExpectedHostId,
        [Parameter(Mandatory = $true)][string]$ExpectedPrincipalId
    )
    if ($ExpectedHostId -cnotmatch '\A[0-9a-f]{64}\z' -or $ExpectedPrincipalId -cnotmatch '\A[0-9a-f]{64}\z' -or
        (Get-WeatherExecutionHostId) -cne $ExpectedHostId -or
        (Get-WeatherExecutionPrincipalId) -cne $ExpectedPrincipalId) { throw 'S4U invocation is on the wrong host or principal' }
    $identity = Get-WeatherQualificationCurrentLogon
    # SECURITY_LOGON_TYPE.Batch=4 plus the exact registered S4U action/instance
    # distinguishes this lane from an interactive or service invocation.
    if ($identity.logon_type -ne 4 -or $identity.token_type -ne 1 -or $identity.elevated) {
        throw 'Qualification requires an unelevated primary batch-logon token'
    }
    $binding = Assert-WeatherIntegrationAttemptTaskBinding -AttemptContract $AttemptContract -Role $Role -IncludeTaskInfo
    if ([string]$binding.Task.State -cne 'Running') { throw 'Qualification task is not running' }
    $expected = Get-WeatherIntegrationExpectedTaskBinding -AttemptContract $AttemptContract -Role $Role -UserId ([string]$binding.Task.Principal.UserId)
    $principalSid = ([Security.Principal.NTAccount]::new([string]$binding.Task.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value
    if ($principalSid -cne $identity.sid -or -not (Test-WeatherIntegrationPathEqual -Left $identity.image -Right $expected.executable)) {
        throw 'Actual qualification token or executable differs from the task'
    }
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    $argv = [Weather.Operations.QualificationLogonReader]::Arguments([string]$current.CommandLine)
    $actualArguments = ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens @($argv | Select-Object -Skip 1)
    if ($actualArguments -cne [string]$expected.arguments) { throw 'Actual qualification command differs from the exact task action' }
    $ancestors = @([pscustomobject]@{ pid = $PID; creation_utc_ticks = $identity.creation_utc_ticks })
    for ($depth = 0; $depth -lt 2; $depth++) {
        $parentId = [int]$current.ParentProcessId
        if ($parentId -le 0 -or $parentId -in @($ancestors.pid)) { throw 'Qualification process ancestry is ambiguous' }
        $parent = Get-Process -Id $parentId -ErrorAction Stop
        try { $created = $parent.StartTime.ToUniversalTime().Ticks } finally { $parent.Dispose() }
        if ($created -gt $ancestors[-1].creation_utc_ticks) { throw 'Qualification parent PID was reused' }
        $ancestors += [pscustomobject]@{ pid = $parentId; creation_utc_ticks = $created }
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction Stop
    }
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    $task = $scheduler.GetFolder('\').GetTask([string]$binding.Task.TaskName)
    $instances = @($task.GetInstances(1))
    if ($instances.Count -ne 1 -or [int]$instances[0].State -ne 4 -or
        [int]$instances[0].EnginePID -notin @($ancestors.pid) -or
        [string]$instances[0].InstanceGuid -notmatch '^\{?[0-9a-fA-F-]{36}\}?$') {
        throw 'Qualification process is not the one native running task instance'
    }
    $runAt = $binding.Info.LastRunTime.ToUniversalTime()
    if ([Math]::Abs(([DateTime]::new($identity.creation_utc_ticks, [DateTimeKind]::Utc) - $runAt).TotalSeconds) -gt 120) {
        throw 'Qualification instance is not correlated with the native task run'
    }
    return [pscustomobject]@{
        schema = 'qualification_s4u_invocation_v2'; role = $Role
        host_id = $ExpectedHostId; principal_id = $ExpectedPrincipalId; token = $identity; ancestry = $ancestors
        task_name = [string]$binding.Task.TaskName; instance_guid = [string]$instances[0].InstanceGuid
        engine_pid = [int]$instances[0].EnginePID; registration_receipt_sha256 = $binding.RegistrationReceiptSha256
        registration_intent_sha256 = $binding.RegistrationIntentSha256
    }
}
