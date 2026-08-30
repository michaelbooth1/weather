[CmdletBinding()]
param(
    [switch]$Json,
    [string]$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
)

# Lightweight, execution-host-only status for a portable International live
# session.  It deliberately does not inspect capture workers, the execution
# tape, scheduled integrations, credentials, or any exchange endpoint.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = [IO.Path]::GetFullPath($RepoRoot)
if (-not [IO.Path]::IsPathRooted($RepoRoot) -or
    -not (Test-Path -LiteralPath $repo -PathType Container)) {
    throw "execution host repository root must be an existing absolute directory"
}
$repositoryLocalMedia = $false
$repositoryReparseFree = $true
try {
    $repoDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($repo))
    $repositoryLocalMedia = $repoDrive.DriveType -in @(
        [IO.DriveType]::Fixed,
        [IO.DriveType]::Removable
    )
    $cursor = [IO.Path]::GetPathRoot($repo)
    $relative = $repo.Substring($cursor.Length)
    foreach ($component in $relative.Split(
            [char[]]@(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            ),
            [StringSplitOptions]::RemoveEmptyEntries
        )) {
        $cursor = Join-Path $cursor $component
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $repositoryReparseFree = $false
            break
        }
    }
}
catch {
    $repositoryLocalMedia = $false
    $repositoryReparseFree = $false
}

function Get-InternationalLiveExecutionHostId {
    $machineGuid = [string](Get-ItemPropertyValue `
        -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography" `
        -Name "MachineGuid" `
        -ErrorAction Stop)
    $machineGuid = $machineGuid.Trim().ToLowerInvariant()
    if (-not $machineGuid) {
        throw "execution host identity is unavailable"
    }
    $material = "international_live_execution_host_v2`0$machineGuid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return -join (
            $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($material)) |
                ForEach-Object { $_.ToString("x2") }
        )
    }
    finally { $hasher.Dispose() }
}

function Get-InternationalLiveExecutionPrincipalId {
    $sid = [string]([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
    $sid = $sid.Trim().ToLowerInvariant()
    if (-not $sid) {
        throw "execution principal identity is unavailable"
    }
    $material = "international_live_execution_principal_v1`0$sid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return -join (
            $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($material)) |
                ForEach-Object { $_.ToString("x2") }
        )
    }
    finally { $hasher.Dispose() }
}

function Get-InternationalLiveExecutionHostAssignment {
    $path = Join-Path $repo "config\international_live_execution_host.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "execution-host assignment is absent"
    }
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if ($item.Length -le 0 -or $item.Length -gt 16384 -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "execution-host assignment is not a bounded regular file"
    }
    $assignment = [IO.File]::ReadAllText($item.FullName) | ConvertFrom-Json
    $expectedNames = @(
        "active_portable_execution_host_id",
        "active_portable_execution_principal_id",
        "assignment_status",
        "dedicated_capture_execution_host_id",
        "reassignment_requires_new_production_tip",
        "schema_version"
    ) | Sort-Object
    $observedNames = @($assignment.PSObject.Properties.Name | Sort-Object)
    if (
        $observedNames.Count -ne $expectedNames.Count -or
        @(Compare-Object $expectedNames $observedNames).Count -ne 0 -or
        [string]$assignment.schema_version -cne
            "international_live_execution_host_assignment_v0.1" -or
        [string]$assignment.dedicated_capture_execution_host_id -cnotmatch
            '\A[0-9a-f]{64}\z' -or
        $assignment.reassignment_requires_new_production_tip -ne $true -or
        [string]$assignment.assignment_status -cnotin @("UNASSIGNED", "ASSIGNED")
    ) {
        throw "execution-host assignment contract is invalid"
    }
    if ([string]$assignment.assignment_status -ceq "UNASSIGNED") {
        if ($null -ne $assignment.active_portable_execution_host_id -or
            $null -ne $assignment.active_portable_execution_principal_id) {
            throw "unassigned execution-host registry contains an active identity"
        }
    }
    elseif (
        [string]$assignment.active_portable_execution_host_id -cnotmatch
            '\A[0-9a-f]{64}\z' -or
        [string]$assignment.active_portable_execution_principal_id -cnotmatch
            '\A[0-9a-f]{64}\z' -or
        [string]$assignment.active_portable_execution_host_id -ceq
            [string]$assignment.dedicated_capture_execution_host_id
    ) {
        throw "assigned portable execution-host identity is invalid"
    }
    return $assignment
}

$clockService = $null
$clockLastSync = $null
$clockSyncAgeHours = $null
$clockSource = $null
$clockSynchronized = $false
try { $clockService = Get-Service -Name W32Time -ErrorAction Stop }
catch { }
try {
    $syncEvent = Get-WinEvent -FilterHashtable @{
        LogName = "System"
        ProviderName = "Microsoft-Windows-Time-Service"
        Id = 35, 37
        StartTime = (Get-Date).AddDays(-7)
    } -MaxEvents 1 -ErrorAction Stop
    if ($syncEvent) { $clockLastSync = [datetime]$syncEvent.TimeCreated }
}
catch { }
if ($clockService -and $clockService.Status -eq "Running" -and $clockLastSync) {
    # Event IDs and TimeCreated are language-independent; parsing w32tm's
    # localized labels would reject otherwise healthy non-English Windows PCs.
    $clockSynchronized = $true
    $clockSource = "Windows Time-Service synchronization event"
}
if ($clockLastSync) {
    $clockSyncAgeHours = [math]::Round(
        ((Get-Date) - $clockLastSync).TotalHours,
        3
    )
}

$windowsUpdateRebootPending = Test-Path -LiteralPath (
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\" +
    "Auto Update\RebootRequired"
)
$componentServicingRebootPending = Test-Path -LiteralPath (
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\" +
    "RebootPending"
)
$pendingFileRename = $false
$pendingFileRenameStateKnown = $false
try {
    $sessionManager = Get-Item `
        -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" `
        -ErrorAction Stop
    if ($sessionManager.GetValueNames() -contains "PendingFileRenameOperations") {
        $pendingFileRenameValue = $sessionManager.GetValue(
            "PendingFileRenameOperations", $null,
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
        $pendingFileRename = @($pendingFileRenameValue).Count -gt 0
    }
    $pendingFileRenameStateKnown = $true
}
catch { $pendingFileRenameStateKnown = $false }
$rebootPending = (
    $windowsUpdateRebootPending -or
    $componentServicingRebootPending -or
    $pendingFileRename
)

$networkRedirectEnvironmentNames = @(
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "WEATHER_MARKET_REGISTRY"
)
$configuredNetworkRedirectEnvironment = @(@(
    foreach ($entry in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
        $name = ([string]$entry.Key).ToUpperInvariant()
        if ($name -in $networkRedirectEnvironmentNames -and
            -not [string]::IsNullOrWhiteSpace([string]$entry.Value)) {
            $name
        }
    }
) | Sort-Object -Unique)

$userProxyStateKnown = $false
$userProxyEnabled = $null
$userProxyAutomaticConfiguration = $null
$userProxyAutomaticDetection = $null
try {
    if (-not ("WeatherPortableWinHttp.NativeMethods" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace WeatherPortableWinHttp {
    [StructLayout(LayoutKind.Sequential)]
    public struct CurrentUserIeProxyConfig {
        [MarshalAs(UnmanagedType.Bool)] public bool AutoDetect;
        public IntPtr AutoConfigUrl;
        public IntPtr Proxy;
        public IntPtr ProxyBypass;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct ProxyInfo {
        public UInt32 AccessType;
        public IntPtr Proxy;
        public IntPtr ProxyBypass;
    }
    public static class NativeMethods {
        [DllImport("winhttp.dll", SetLastError = true)]
        public static extern bool WinHttpGetIEProxyConfigForCurrentUser(
            ref CurrentUserIeProxyConfig proxyConfig);
        [DllImport("winhttp.dll", SetLastError = true)]
        public static extern bool WinHttpGetDefaultProxyConfiguration(
            ref ProxyInfo proxyInfo);
        [DllImport("kernel32.dll")]
        public static extern IntPtr GlobalFree(IntPtr memory);
    }
}
"@
    }
    $ieProxy = [WeatherPortableWinHttp.CurrentUserIeProxyConfig]::new()
    if (-not [WeatherPortableWinHttp.NativeMethods]::WinHttpGetIEProxyConfigForCurrentUser(
            [ref]$ieProxy
        )) {
        throw "current-user WinHTTP proxy query failed"
    }
    try {
        $userProxyEnabled = (
            ($ieProxy.Proxy -ne [IntPtr]::Zero -and
                -not [string]::IsNullOrWhiteSpace(
                    [Runtime.InteropServices.Marshal]::PtrToStringUni($ieProxy.Proxy)
                )) -or
            ($ieProxy.ProxyBypass -ne [IntPtr]::Zero -and
                -not [string]::IsNullOrWhiteSpace(
                    [Runtime.InteropServices.Marshal]::PtrToStringUni(
                        $ieProxy.ProxyBypass
                    )
                ))
        )
        $userProxyAutomaticConfiguration = (
            $ieProxy.AutoConfigUrl -ne [IntPtr]::Zero -and
            -not [string]::IsNullOrWhiteSpace(
                [Runtime.InteropServices.Marshal]::PtrToStringUni(
                    $ieProxy.AutoConfigUrl
                )
            )
        )
        $userProxyAutomaticDetection = [bool]$ieProxy.AutoDetect
    }
    finally {
        foreach ($pointer in @(
                $ieProxy.AutoConfigUrl, $ieProxy.Proxy, $ieProxy.ProxyBypass
            )) {
            if ($pointer -ne [IntPtr]::Zero) {
                [void][WeatherPortableWinHttp.NativeMethods]::GlobalFree($pointer)
            }
        }
    }
    $userProxyStateKnown = $true
}
catch { $userProxyStateKnown = $false }

$winHttpProxyStateKnown = $false
$winHttpDirect = $false
try {
    if (-not ("WeatherPortableWinHttp.NativeMethods" -as [type])) {
        throw "WinHTTP proxy native methods are unavailable"
    }
    $proxyInfo = [WeatherPortableWinHttp.ProxyInfo]::new()
    if (-not [WeatherPortableWinHttp.NativeMethods]::WinHttpGetDefaultProxyConfiguration(
            [ref]$proxyInfo
        )) {
        throw "WinHTTP proxy query failed"
    }
    try {
        $winHttpDirect = (
            $proxyInfo.AccessType -eq 1 -and
            $proxyInfo.Proxy -eq [IntPtr]::Zero
        )
        $winHttpProxyStateKnown = $true
    }
    finally {
        if ($proxyInfo.Proxy -ne [IntPtr]::Zero) {
            [void][WeatherPortableWinHttp.NativeMethods]::GlobalFree(
                $proxyInfo.Proxy
            )
        }
        if ($proxyInfo.ProxyBypass -ne [IntPtr]::Zero) {
            [void][WeatherPortableWinHttp.NativeMethods]::GlobalFree(
                $proxyInfo.ProxyBypass
            )
        }
    }
}
catch {
    $winHttpProxyStateKnown = $false
    $winHttpDirect = $false
}

$flags = [Collections.Generic.List[string]]::new()
$executionHostId = Get-InternationalLiveExecutionHostId
$executionPrincipalId = Get-InternationalLiveExecutionPrincipalId
$assignment = $null
try { $assignment = Get-InternationalLiveExecutionHostAssignment }
catch { $flags.Add("execution-host assignment is unreadable or invalid") }
if ($assignment) {
    if ($executionHostId -ceq
        [string]$assignment.dedicated_capture_execution_host_id) {
        $flags.Add("dedicated capture host forbids the portable execution profile")
    }
    if ([string]$assignment.assignment_status -cne "ASSIGNED") {
        $flags.Add("no portable execution host is assigned in the production tip")
    }
    elseif (
        $executionHostId -cne
            [string]$assignment.active_portable_execution_host_id -or
        $executionPrincipalId -cne
            [string]$assignment.active_portable_execution_principal_id
    ) {
        $flags.Add("this host and Windows principal are not the active portable executor")
    }
}
if (-not $repositoryLocalMedia) {
    $flags.Add("execution host repository is not on fixed or removable local media")
}
if (-not $repositoryReparseFree) {
    $flags.Add("execution host repository contains a redirected path entry")
}
if (-not $clockSynchronized) {
    $flags.Add("execution host clock is not synchronized")
}
elseif ($null -eq $clockSyncAgeHours -or
    $clockSyncAgeHours -lt 0 -or $clockSyncAgeHours -gt 24) {
    $flags.Add("execution host clock has no successful sync within 24 hours")
}
if (-not $pendingFileRenameStateKnown) {
    $flags.Add("pending file rename state is unknown")
}
if ($rebootPending) {
    $flags.Add("execution host has a pending reboot")
}
if ($configuredNetworkRedirectEnvironment.Count -ne 0) {
    $flags.Add("execution host process has ambient live-configuration overrides")
}
if (-not $userProxyStateKnown) {
    $flags.Add("current-user Windows proxy state is unknown")
}
elseif ($userProxyEnabled -or $userProxyAutomaticConfiguration -or
    $userProxyAutomaticDetection) {
    $flags.Add("current-user Windows proxy or automatic discovery is active")
}
if (-not $winHttpProxyStateKnown) {
    $flags.Add("machine-wide WinHTTP proxy state is unknown")
}
elseif (-not $winHttpDirect) {
    $flags.Add("machine-wide WinHTTP proxy is active")
}

$payload = [ordered]@{
    schema_version = "international_live_execution_host_status_v0.3"
    status = $(if ($flags.Count -eq 0) { "PASS" } else { "BLOCKED" })
    checked_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    execution_host_id = $executionHostId
    execution_principal_id = $executionPrincipalId
    execution_host_assignment = $(if ($assignment) {
        [ordered]@{
            status = [string]$assignment.assignment_status
            dedicated_capture_execution_host_id =
                [string]$assignment.dedicated_capture_execution_host_id
            active_portable_execution_host_id =
                $assignment.active_portable_execution_host_id
            active_portable_execution_principal_id =
                $assignment.active_portable_execution_principal_id
            current_assignment_matches = (
                [string]$assignment.assignment_status -ceq "ASSIGNED" -and
                $executionHostId -ceq
                    [string]$assignment.active_portable_execution_host_id -and
                $executionPrincipalId -ceq
                    [string]$assignment.active_portable_execution_principal_id
            )
        }
    } else { $null })
    repository_root = $repo
    repository = [ordered]@{
        local_media = $repositoryLocalMedia
        reparse_free = $repositoryReparseFree
    }
    flags = @($flags)
    clock = [ordered]@{
        service = $(if ($clockService) { [string]$clockService.Status } else { $null })
        synchronized = $clockSynchronized
        source = $clockSource
        sync_age_hours = $clockSyncAgeHours
        last_sync = $(if ($clockLastSync) { $clockLastSync.ToString("o") } else { $null })
    }
    resilience = [ordered]@{
        reboot_pending = $rebootPending
        pending_file_rename_state_known = $pendingFileRenameStateKnown
    }
    network = [ordered]@{
        ambient_redirect_environment_names = @(
            $configuredNetworkRedirectEnvironment
        )
        current_user_proxy_state_known = $userProxyStateKnown
        current_user_proxy_enabled = $userProxyEnabled
        current_user_automatic_configuration = $userProxyAutomaticConfiguration
        current_user_automatic_detection = $userProxyAutomaticDetection
        winhttp_proxy_state_known = $winHttpProxyStateKnown
        winhttp_direct = $winHttpDirect
    }
    public_candidate_substrate = [ordered]@{
        status = "NOT_EVALUATED"
        reason = "host status does not collect or validate market data"
    }
    credential_access = $false
    exchange_contact = $false
    scheduler_mutation = $false
    capture_mutation = $false
}
$exitCode = if ($flags.Count -eq 0) { 0 } else { 2 }
if ($Json) {
    $payload | ConvertTo-Json -Depth 5 -Compress
}
else {
    $state = if ($exitCode -eq 0) { "PASS" } else { "BLOCKED" }
    Write-Output ("International portable execution host: {0}" -f $state)
    foreach ($flag in $flags) { Write-Output ("  BLOCKER: {0}" -f $flag) }
}
exit $exitCode
