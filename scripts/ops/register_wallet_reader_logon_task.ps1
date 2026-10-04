# Owner-run only, on the WORKSTATION: registers WeatherWalletReader, which starts the
# read-only wallet LAN reader at the owner's logon. See docs/operations/wallet-reader.md.
#
# S4U/Limited: no console window and no stored password. The task starts one minute after
# the owner logs on and runs until stopped (no execution time limit). Registration
# refuses an existing task instead of silently replacing it, and requires the matching
# firewall rule from register_wallet_reader_firewall.ps1. Run from an elevated session.
#
# The reader runs from a dedicated linked worktree at a reviewed commit (-RepoRoot,
# -ExpectedCommit) with the main checkout's venv interpreter (-PythonPath, default: the
# common checkout's venv). The main checkout's data\ is the write-protected workstation
# mirror, so a reader started there cannot write its request journal and answers every
# read with 503. Registration refuses the main checkout, a dirty or different commit, a
# reader module that does not import from -RepoRoot\src, and an unwritable journal folder.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium', DefaultParameterSetName = 'Register')]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true, ParameterSetName = 'Register')][string]$ExpectedCommit,
    [Parameter(ParameterSetName = 'Register')][string]$PythonPath = '',
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

$repo = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')
if ($repo -match '["\r\n]') { throw 'unsafe quoted task path' }
if (-not (Test-Path -LiteralPath (Join-Path $repo 'src\weather\market\wallet_reader.py') -PathType Leaf)) {
    throw 'RepoRoot must be a checkout that contains src\weather\market\wallet_reader.py.'
}
function Invoke-Git([string[]]$GitArgs) {
    $out = & git -C $repo @GitArgs 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'RepoRoot must be a git checkout readable by git.' }
    @($out)
}
$top = [IO.Path]::GetFullPath(@(Invoke-Git @('rev-parse', '--show-toplevel'))[0]).TrimEnd('\')
$gitDir = [IO.Path]::GetFullPath(@(Invoke-Git @('rev-parse', '--path-format=absolute', '--git-dir'))[0]).TrimEnd('\')
$commonDir = [IO.Path]::GetFullPath(@(Invoke-Git @('rev-parse', '--path-format=absolute', '--git-common-dir'))[0]).TrimEnd('\')
if ($top -ine $repo) { throw 'RepoRoot must be the top level of its checkout.' }
if ($gitDir -ieq $commonDir) {
    throw 'RepoRoot must be a dedicated linked worktree, not the main checkout (its data\ is the write-protected mirror).'
}
if ($ExpectedCommit -notmatch '^[0-9a-f]{40}$') { throw 'ExpectedCommit must be a full lowercase commit SHA.' }
$head = @(Invoke-Git @('rev-parse', 'HEAD'))[0]
if ($head -cne $ExpectedCommit) { throw "RepoRoot HEAD $head is not the reviewed ExpectedCommit." }
if ((Invoke-Git @('status', '--porcelain', '--untracked-files=no')) -join '') {
    throw 'RepoRoot has uncommitted changes to tracked files.'
}
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path (Split-Path -Parent $commonDir) 'venv\Scripts\python.exe'
}
$python = [IO.Path]::GetFullPath($PythonPath)
if ($python -match '["\r\n]') { throw 'unsafe quoted task path' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'PythonPath (default: the main checkout venv interpreter) does not exist.'
}
# The task runs `-m` with RepoRoot as its working directory, so the reader must import from there.
Push-Location -LiteralPath $repo
try {
    $origin = & $python -c "import importlib.util as u; print(u.find_spec('weather.market.wallet_reader').origin)" 2>$null
    $probeExit = $LASTEXITCODE
} finally { Pop-Location }
$srcPrefix = $repo + '\src\'
if ($probeExit -ne 0 -or -not $origin -or
    -not ([IO.Path]::GetFullPath([string]@($origin)[-1])).StartsWith($srcPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The reader module does not import from RepoRoot\src with this interpreter.'
}
# The reader journals every upstream GET before sending it; an unwritable folder means 503 on every read.
$journal = Join-Path $repo 'data\wallet_reader'
function Test-WritableFolder([string]$Folder) {
    $probe = Join-Path $Folder ('.write-probe-' + [guid]::NewGuid().ToString('N'))
    try {
        [IO.File]::WriteAllBytes($probe, [byte[]]@())
        [IO.File]::Delete($probe)  # not Remove-Item: -WhatIf would leave the probe behind
        $true
    } catch { $false }
}
if ((Test-Path -LiteralPath $journal) -and -not (Test-Path -LiteralPath $journal -PathType Container)) {
    throw 'The journal path RepoRoot\data\wallet_reader exists but is not a folder.'
}
if (-not (Test-Path -LiteralPath $journal -PathType Container) -and -not $WhatIfPreference) {
    try { New-Item -ItemType Directory -Path $journal -ErrorAction Stop | Out-Null }
    catch { throw 'The journal folder RepoRoot\data\wallet_reader cannot be created (write-protected data?).' }
}
$probeFolder = $journal
while (-not (Test-Path -LiteralPath $probeFolder -PathType Container)) { $probeFolder = Split-Path -Parent $probeFolder }
if (-not (Test-WritableFolder $probeFolder)) {
    throw 'The journal folder RepoRoot\data\wallet_reader is not writable (write-protected data?).'
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

Write-Output ("plan {0}: python={1} workdir={2} commit={3} journal={4} args={5}" -f $taskName, $python, $repo, $ExpectedCommit, $journal, $arguments)
if ($PSCmdlet.ShouldProcess($taskName, 'Register logon task for the read-only wallet reader')) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings `
        -Description "Read-only wallet LAN reader (docs/operations/wallet-reader.md); starts at owner logon; commit $ExpectedCommit" `
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
