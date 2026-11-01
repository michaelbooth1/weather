# R20 forward receipts beacon, workstation side (master ruling 2026-11-01, section 2). The action of the WS task
# registered by register_ws_forward_receipts_beacon.ps1 (every 30 minutes at :10/:40 and at logon); also safe to
# run by hand. Research/shadow only: it reads three local receipt ledgers and writes a small projection of them,
# plus a heartbeat, onto the capture host's xfer share, where WeatherForwardArrivalCheck reads them.
#
# Reads, and only through [IO.File]::Open(path, Open, Read, ReadWrite,Delete) so the B and L6_G writers can keep
# appending while it reads (never Copy-Item, File.Copy or robocopy; no ledger is ever opened for write):
#   -Mg2Ledger        C:\t\mg2\forward\input_receipts.jsonl   -> mg2_input_receipts.jsonl
#   -L6gBundleLedger  C:\t\l6g\forward\bundle_receipts.jsonl  -> l6g_bundle_receipts.jsonl
#   -L6gInputLedger   C:\t\l6g\forward\input_receipts.jsonl   -> l6g_input_receipts.jsonl
# Only complete lines (up to the last LF at open) are used. Each row is projected to its schema, date, status, sha
# and time fields (schema, target_date, date, status, manifest_sha256, recorded_at, emitted_utc, vectors_sha256);
# checks, paths, per-market counts and every other field stay on the workstation. A line that does not parse is
# written as {"unparseable":true,"line":<n>}.
#
# Writes: <target>\in\forward-receipts\<name>.tmp, then renamed over <name> (File.Replace, or File.Move for a new
# file), for the three projections and finally heartbeat.json (generated_utc, ws_boot_utc, user, computer, the
# beacon's own sha256, the name and IP probe results, which root was written, and per-ledger row counts). <target>
# is -ShareRoot when its in\ folder is reachable, else -FallbackShareRoot. Both are parameters: the registrar passes
# the host-name form (R20 section 1) and the IP form. A local run log goes to -LogRoot\runs.jsonl.
# Exit 0 when every file was written, 1 otherwise (nothing reachable, a missing ledger, a failed rename).
# Never handles a credential: the share is reached with the logged-on user's stored credential (Interactive task).
[CmdletBinding()]
param(
    [string]$ShareRoot = '',
    [string]$FallbackShareRoot = '',
    [string]$Mg2Ledger = 'C:\t\mg2\forward\input_receipts.jsonl',
    [string]$L6gBundleLedger = 'C:\t\l6g\forward\bundle_receipts.jsonl',
    [string]$L6gInputLedger = 'C:\t\l6g\forward\input_receipts.jsonl',
    [string]$LogRoot = 'C:\t\forward-receipts-beacon',
    # Define the functions and stop (tests dot-source the script this way).
    [switch]$DefineFunctionsOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$script:ProjectedFields = @('schema', 'target_date', 'date', 'status', 'manifest_sha256', 'recorded_at',
    'emitted_utc', 'vectors_sha256')
$script:ReceiptsSubdir = 'in\forward-receipts'

function Open-WeatherLedgerForRead {
    # The only way this beacon opens a ledger: read access, and the writer keeps write and delete sharing.
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
}

function Read-WeatherLedgerCompleteLines {
    # Complete lines from an open ledger stream: bytes [0, length at entry), cut after the last LF.
    param([Parameter(Mandatory = $true)][IO.Stream]$Stream)
    $length = [int64]$Stream.Length
    $buffer = New-Object byte[] $length
    $read = 0
    while ($read -lt $length) {
        $n = $Stream.Read($buffer, $read, [int]($length - $read))
        if ($n -le 0) { break }
        $read += $n
    }
    $end = $read
    while ($end -gt 0 -and $buffer[$end - 1] -ne 10) { $end-- }
    $text = (New-Object Text.UTF8Encoding($false)).GetString($buffer, 0, $end)
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
    return [pscustomobject]@{ bytes_read = $read; complete_bytes = $end
        lines = @($text -split "`n" | ForEach-Object { $_.TrimEnd("`r") } | Where-Object { $_.Trim() }) }
}

function ConvertTo-WeatherReceiptProjection {
    param([string[]]$Lines)
    $out = New-Object System.Collections.Generic.List[string]
    $n = 0
    foreach ($line in @($Lines)) {
        $n++
        $row = $null
        try { $row = $line | ConvertFrom-Json } catch { $row = $null }
        if ($null -eq $row -or $row -isnot [Management.Automation.PSCustomObject]) {
            $out.Add(([ordered]@{ unparseable = $true; line = $n } | ConvertTo-Json -Compress))
            continue
        }
        $projected = [ordered]@{}
        foreach ($name in $script:ProjectedFields) {
            $property = $row.PSObject.Properties[$name]
            if ($null -eq $property -or $null -eq $property.Value) { continue }
            $value = $property.Value
            if ($value -is [datetime]) { $value = $value.ToString('o', [Globalization.CultureInfo]::InvariantCulture) }
            if ($value -is [Management.Automation.PSCustomObject] -or $value -is [array]) { continue }
            $projected[$name] = [string]$value
        }
        $out.Add(($projected | ConvertTo-Json -Compress))
    }
    return ,$out.ToArray()
}

function Write-WeatherFileByRename {
    # <dest>.tmp, then renamed over <dest>. The tmp file is removed when the rename fails.
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][byte[]]$Bytes)
    $tmp = "$Path.tmp"
    [IO.File]::WriteAllBytes($tmp, $Bytes)
    try {
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($tmp, $Path, $null) }
        else { [IO.File]::Move($tmp, $Path) }
    }
    catch {
        try { [IO.File]::Delete($tmp) } catch { }
        throw
    }
}

function Get-WeatherSha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return (($sha.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) -join '') }
    finally { $sha.Dispose() }
}

function Get-WeatherShareProbe {
    # Host part of a UNC root, its DNS answer (when it is a name), and whether <root>\in is reachable.
    param([string]$Root)
    $probe = [ordered]@{ root = $Root; host = $null; addresses = @(); resolve_error = $null; reachable = $false }
    if ([string]::IsNullOrWhiteSpace($Root)) { return $probe }
    if ($Root -match '^\\\\([^\\]+)\\') {
        $probe.host = $Matches[1]
        $ip = $null
        if (-not [Net.IPAddress]::TryParse($probe.host, [ref]$ip)) {
            try { $probe.addresses = @([Net.Dns]::GetHostAddresses($probe.host) | ForEach-Object { $_.ToString() }) }
            catch { $probe.resolve_error = $_.Exception.Message }
        }
        else { $probe.addresses = @($probe.host) }
    }
    try { $probe.reachable = [bool](Test-Path -LiteralPath (Join-Path $Root 'in') -PathType Container) }
    catch { $probe.reachable = $false }
    return $probe
}

if ($DefineFunctionsOnly) { return }

$culture = [Globalization.CultureInfo]::InvariantCulture
$startedUtc = [DateTime]::UtcNow
$utf8 = New-Object Text.UTF8Encoding($false)
if (-not $ShareRoot) { throw 'pass -ShareRoot (the xfer share root, e.g. the host-name form)' }
$beaconSha = Get-WeatherSha256Hex -Bytes ([IO.File]::ReadAllBytes($PSCommandPath))
$problems = New-Object System.Collections.Generic.List[string]

$nameProbe = Get-WeatherShareProbe -Root $ShareRoot
$ipProbe = Get-WeatherShareProbe -Root $FallbackShareRoot
$via = $null
$targetDir = $null
if ($nameProbe.reachable) { $via = 'share_root'; $targetDir = Join-Path $ShareRoot $script:ReceiptsSubdir }
elseif ($ipProbe.reachable) { $via = 'fallback_share_root'; $targetDir = Join-Path $FallbackShareRoot $script:ReceiptsSubdir }
else { $problems.Add('no_share_reachable') }

$ledgers = [ordered]@{
    'mg2_input_receipts.jsonl' = $Mg2Ledger
    'l6g_bundle_receipts.jsonl' = $L6gBundleLedger
    'l6g_input_receipts.jsonl' = $L6gInputLedger
}
$ledgerState = [ordered]@{}
if ($targetDir) {
    try { [void][IO.Directory]::CreateDirectory($targetDir) }
    catch { $problems.Add('target_dir_unwritable'); $targetDir = $null }
}
foreach ($name in $ledgers.Keys) {
    $source = $ledgers[$name]
    $entry = [ordered]@{ source = $source; status = 'missing'; rows = 0; bytes_read = 0; sha256 = $null }
    if (-not [IO.File]::Exists($source)) {
        $problems.Add("ledger_missing:$name")
        $ledgerState[$name] = $entry
        continue
    }
    try {
        $stream = Open-WeatherLedgerForRead -Path $source
        try { $content = Read-WeatherLedgerCompleteLines -Stream $stream } finally { $stream.Dispose() }
        $projected = ConvertTo-WeatherReceiptProjection -Lines $content.lines
        $text = if ($projected.Count) { ($projected -join "`n") + "`n" } else { '' }
        $bytes = $utf8.GetBytes($text)
        $entry.rows = $projected.Count
        $entry.bytes_read = $content.bytes_read
        $entry.sha256 = Get-WeatherSha256Hex -Bytes $bytes
        $entry.status = 'read'
        if ($targetDir) {
            Write-WeatherFileByRename -Path (Join-Path $targetDir $name) -Bytes $bytes
            $entry.status = 'written'
        }
    }
    catch {
        $entry.status = 'error'
        $problems.Add("ledger_error:${name}:$($_.Exception.Message)")
    }
    $ledgerState[$name] = $entry
}

$bootUtc = $null
try {
    $boot = (Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
    $bootUtc = $boot.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', $culture)
}
catch { $bootUtc = $null }
$heartbeat = [ordered]@{
    schema = 'ws_forward_receipts_heartbeat/1'
    generated_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ', $culture)
    ws_boot_utc = $bootUtc
    user = "$env:USERDOMAIN\$env:USERNAME"
    computer = $env:COMPUTERNAME
    beacon_sha256 = $beaconSha
    written_via = $via
    name_probe = $nameProbe
    ip_probe = $ipProbe
    ledgers = $ledgerState
    problems = @($problems)
}
$heartbeatJson = $heartbeat | ConvertTo-Json -Compress -Depth 5
if ($targetDir) {
    try { Write-WeatherFileByRename -Path (Join-Path $targetDir 'heartbeat.json') -Bytes ($utf8.GetBytes($heartbeatJson + "`n")) }
    catch { $problems.Add("heartbeat_error:$($_.Exception.Message)") }
}
try {
    [void][IO.Directory]::CreateDirectory($LogRoot)
    $log = [ordered]@{ started_utc = $startedUtc.ToString('yyyy-MM-ddTHH:mm:ssZ', $culture)
        written_via = $via; target = $targetDir; problems = @($problems)
        rows = [ordered]@{} }
    foreach ($name in $ledgerState.Keys) { $log.rows[$name] = $ledgerState[$name].rows }
    Add-Content -LiteralPath (Join-Path $LogRoot 'runs.jsonl') -Value ($log | ConvertTo-Json -Compress -Depth 4) -Encoding UTF8
}
catch { }
Write-Output $heartbeatJson
if ($problems.Count) { exit 1 }
exit 0
