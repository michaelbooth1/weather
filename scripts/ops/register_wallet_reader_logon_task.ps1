# Owner-run only, on the WORKSTATION: registers WeatherWalletReader, which starts the
# read-only wallet LAN reader at the owner's logon. See docs/operations/wallet-reader.md.
#
# S4U/Limited: no console window and no stored password. The task starts one minute after
# the owner logs on and runs until stopped (no execution time limit). Registration
# refuses an existing task instead of silently replacing it, and requires the matching
# firewall rule from register_wallet_reader_firewall.ps1. Run from an elevated session.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium', DefaultParameterSetName = 'Register')]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true, ParameterSetName = 'Register')][string]$Bind,
    [Parameter(Mandatory = $true, ParameterSetName = 'Register')][string]$AllowIp,
    [Parameter(ParameterSetName = 'Register')][ValidateRange(1, 65535)][int]$Port = 8765,
    [Parameter(Mandatory = $true, ParameterSetName = 'Register')][ValidateSet(2, 3)][int]$SignatureType,
    [Parameter(Mandatory = $true, ParameterSetName = 'Unregister')][switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$taskName = 'WeatherWalletReader'
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $WhatIfPreference -and
    -not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run from an elevated PowerShell session (S4U task registration needs administrator rights).'
}

if ($Unregister) {
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        throw 'No WeatherWalletReader task is registered.'
    }
    if ($PSCmdlet.ShouldProcess($taskName, 'Stop and remove the wallet-reader logon task')) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
        Write-Output "unregistered $taskName"
    }
    exit 0
}

foreach ($value in @($Bind, $AllowIp)) {
    $address = $null
    if (-not [Net.IPAddress]::TryParse($value, [ref]$address) -or
        $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        $address.ToString() -cne $value) {
        throw 'Bind and AllowIp must be literal RFC1918 IPv4 addresses.'
    }
    $bytes = $address.GetAddressBytes()
    if (-not ($bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
              ($bytes[0] -eq 192 -and $bytes[1] -eq 168))) {
        throw 'Bind and AllowIp must be RFC1918.'
    }
}
if (-not (Get-NetIPAddress -IPAddress $Bind -ErrorAction SilentlyContinue)) {
    throw 'Bind must be an IPv4 address assigned to this PC.'
}
$ruleName = "WeatherWalletReader-$AllowIp-$Port"
if (-not (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)) {
    throw 'Register the matching firewall rule first (register_wallet_reader_firewall.ps1).'
}

$repo = [IO.Path]::GetFullPath($RepoRoot)
$python = Join-Path $repo 'venv\Scripts\python.exe'
if ($repo -match '["\r\n]') { throw 'unsafe quoted task path' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $repo 'src\weather\market\wallet_reader.py') -PathType Leaf)) {
    throw 'RepoRoot must be a checkout of current master with its venv (for example the main checkout).'
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Task already exists; unregister it before replacing it.'
}

$arguments = "-m weather.market.wallet_reader serve --bind $Bind --allow $AllowIp --port $Port --signature-type $SignatureType"
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT1M'  # let the LAN address come up before binding
# S4U: no window and no stored password; the process outlives the logon session.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

if ($PSCmdlet.ShouldProcess($taskName, 'Register logon task for the read-only wallet reader')) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings `
        -Description 'Read-only wallet LAN reader (docs/operations/wallet-reader.md); starts at owner logon' `
        -ErrorAction Stop | Out-Null

    $t = Get-ScheduledTask -TaskName $taskName
    if (@($t.Actions).Count -ne 1 -or $t.Actions[0].Execute -ine $python -or
        $t.Actions[0].Arguments -cne $arguments -or $t.Actions[0].WorkingDirectory -ine $repo -or
        @($t.Triggers).Count -ne 1 -or
        [string]$t.Principal.LogonType -ne 'S4U' -or [string]$t.Principal.RunLevel -ne 'Limited' -or
        $t.Settings.ExecutionTimeLimit -ne 'PT0S') {
        throw 'registered wallet-reader task does not match the reviewed action, trigger, principal, and settings'
    }
    Write-Output ("registered {0}: logon={1} state={2}; start now with Start-ScheduledTask -TaskName {0}" -f $taskName, $t.Principal.LogonType, $t.State)
}
