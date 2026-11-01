# Forward input arrival check (R20 section 2, master ruling 2026-11-01): did yesterday's B and L6_G forward inputs
# reach the workstation, and is the workstation's receipts beacon alive?
#
# Runs on the capture host as WeatherForwardArrivalCheck (register_forward_input_arrival_check.ps1; S4U/Limited,
# 07:45, 11:45 and 18:05 local). Pure PowerShell and light: it opens a handful of small files, starts no child
# process, takes no lease and finishes in seconds. Read-only except for its own two outputs under data\alerts.
#
# For D = yesterday (America/Toronto) it checks, by slot (local time of the run):
#   always       the host's ready marker data\exports\mg2-inputs\<D>\manifest.json.sha256 exists, and the beacon's
#                heartbeat.json under -ReceiptsRoot is no older than -HeartbeatMaxAgeMinutes (90);
#   from 11:45   a B row (mg2_input_receipts.jsonl) for D with status verified and manifest_sha256 equal to the
#                marker, and (D >= -L6gFirstDate) an L6_G bundle row (l6g_bundle_receipts.jsonl) for D, verified;
#   from 18:05   (D >= -L6gFirstDate) an L6_G emit receipt (l6g_input_receipts.jsonl) for D, and B again.
# The beacon (tools\research\ws_forward_receipts_beacon.ps1) writes those files into -ReceiptsRoot, already
# projected to their date, status and sha fields. This script still parses only those fields of each line, with
# a key match that must be unique per line; any other field, and any line where a key repeats, is ignored.
#
# Output: one appended row per run in data\alerts\forward_arrival.jsonl and the atomic state file
# data\alerts\forward_arrival_state.json (status OK, ALERT or RETIRED), which status.ps1 classifies.
# Exit 0 = every check passed, or D is after -LastDate (retired: nothing is checked); exit 2 = at least one check
# failed (the alert; scheduled_tasks.json lists no expected non-zero code, so status.ps1 shows it); an exception
# exits 1. Every file is opened with ReadWrite,Delete sharing, so the beacon's rename over a receipt never fails
# because this check holds it open.
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    # Host-local folder behind \\<host>\xfer\in\forward-receipts, where the beacon writes.
    [string]$ReceiptsRoot = "",
    # Last target date checked; after it the task is silent (R20: accrual ends 2026-12-16).
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$LastDate = "2026-12-16",
    # First target date with an L6_G bundle and emit (the L6_G forward screen starts 2026-10-31).
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$L6gFirstDate = "2026-10-31",
    [ValidateRange(5, 1440)][int]$HeartbeatMaxAgeMinutes = 90,
    # Test seam: the local wall-clock instant of the run (yyyy-MM-ddTHH:mm:ss, America/Toronto). Default: now.
    [ValidatePattern('^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})?$')][string]$Now = ""
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an advanced script's param()
# defaults under `powershell -File`; derive the default here. An explicit -RepoRoot always wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$culture = [Globalization.CultureInfo]::InvariantCulture

function Read-WeatherSharedText {
    # The whole file as UTF-8 text through a ReadWrite,Delete-shared handle; $null when it does not exist.
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        $reader = New-Object IO.StreamReader($stream, (New-Object Text.UTF8Encoding($false)), $true)
        return $reader.ReadToEnd()
    }
    finally { $stream.Dispose() }
}

function Get-WeatherReceiptField {
    # The string value of one top-level-style key, only when the key occurs exactly once in the line.
    param([string]$Line, [Parameter(Mandatory = $true)][string]$Key)
    $found = [regex]::Matches($Line, '(?:^|[{,])\s*"' + [regex]::Escape($Key) + '"\s*:\s*"([^"\\]*)"')
    if ($found.Count -ne 1) { return $null }
    return $found[0].Groups[1].Value
}

function Get-WeatherReceiptRows {
    # Date, status and sha fields of each complete JSONL line; nothing else is read.
    param([string]$Text)
    $rows = @()
    if ($null -eq $Text) { return ,$rows }
    foreach ($line in ($Text -split "`n")) {
        $line = $line.TrimEnd("`r")
        if (-not $line.Trim()) { continue }
        $rows += [pscustomobject]@{
            target_date = Get-WeatherReceiptField -Line $line -Key 'target_date'
            date = Get-WeatherReceiptField -Line $line -Key 'date'
            status = Get-WeatherReceiptField -Line $line -Key 'status'
            manifest_sha256 = Get-WeatherReceiptField -Line $line -Key 'manifest_sha256'
        }
    }
    return ,$rows
}

function Write-WeatherAtomicText {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Text)
    $tmp = "$Path.tmp"
    [IO.File]::WriteAllText($tmp, $Text, (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $Path -PathType Leaf) { [IO.File]::Replace($tmp, $Path, $null) }
    else { [IO.File]::Move($tmp, $Path) }
}

if (-not [IO.Path]::IsPathRooted($RepoRoot) -or $RepoRoot -match '["\r\n]') { throw 'an absolute -RepoRoot is required' }
if (-not $ReceiptsRoot -or -not [IO.Path]::IsPathRooted($ReceiptsRoot) -or $ReceiptsRoot -match '["\r\n]') {
    throw 'an absolute -ReceiptsRoot is required (the host folder the beacon writes into)'
}
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$localNow = if ($Now) { [datetime]::ParseExact($Now, 'yyyy-MM-ddTHH:mm:ss', $culture) }
    else { [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone) }
$utcNow = if ($Now) { [TimeZoneInfo]::ConvertTimeToUtc([datetime]::SpecifyKind($localNow, 'Unspecified'), $zone) }
    else { [DateTime]::UtcNow }
$day = $localNow.Date.AddDays(-1)
$D = $day.ToString('yyyy-MM-dd', $culture)
$minutes = $localNow.Hour * 60 + $localNow.Minute
$slot = if ($minutes -ge (18 * 60 + 5)) { '18:05' } elseif ($minutes -ge (11 * 60 + 45)) { '11:45' } else { '07:45' }
$alertDir = Join-Path $RepoRoot 'data\alerts'
$ledgerPath = Join-Path $alertDir 'forward_arrival.jsonl'
$statePath = Join-Path $alertDir 'forward_arrival_state.json'
$failures = New-Object System.Collections.Generic.List[string]
$checks = [ordered]@{}

if ($day -gt [datetime]::ParseExact($LastDate, 'yyyy-MM-dd', $culture)) {
    $status = 'RETIRED'
}
else {
    $l6gDue = $day -ge [datetime]::ParseExact($L6gFirstDate, 'yyyy-MM-dd', $culture)
    # 1. Host ready marker (the export's last write); its sha is the bundle identity B must verify.
    $markerPath = Join-Path $RepoRoot ("data\exports\mg2-inputs\{0}\manifest.json.sha256" -f $D)
    $markerText = Read-WeatherSharedText -Path $markerPath
    $marker = $null
    if ($null -ne $markerText -and $markerText -match '^\s*([0-9a-f]{64})\s*$') { $marker = $Matches[1] }
    $checks.host_marker = [bool]$marker
    if (-not $marker) {
        $failures.Add($(if ($null -eq $markerText) { "host_marker_missing:$D" } else { "host_marker_unreadable:$D" }))
    }
    # 2. Beacon heartbeat age.
    $heartbeatText = Read-WeatherSharedText -Path (Join-Path $ReceiptsRoot 'heartbeat.json')
    $generated = Get-WeatherReceiptField -Line $heartbeatText -Key 'generated_utc'
    $heartbeatAge = $null
    if ($generated) {
        $parsed = [DateTimeOffset]::MinValue
        if ([DateTimeOffset]::TryParse($generated, $culture, [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$parsed)) {
            $heartbeatAge = [math]::Round(($utcNow - $parsed.UtcDateTime).TotalMinutes, 1)
        }
    }
    $checks.heartbeat_age_minutes = $heartbeatAge
    if ($null -eq $heartbeatText) { $failures.Add('heartbeat_missing') }
    elseif ($null -eq $heartbeatAge) { $failures.Add('heartbeat_unreadable') }
    elseif ($heartbeatAge -gt $HeartbeatMaxAgeMinutes -or $heartbeatAge -lt -10) {
        $failures.Add("heartbeat_stale:$($heartbeatAge)min")
    }
    if ($slot -ne '07:45') {
        # 3. B verified for the marker's bundle.
        $b = @(Get-WeatherReceiptRows -Text (Read-WeatherSharedText -Path (Join-Path $ReceiptsRoot 'mg2_input_receipts.jsonl')) |
            Where-Object { $_.target_date -ceq $D })
        $bOk = @($b | Where-Object { $_.status -ceq 'verified' -and $marker -and $_.manifest_sha256 -ceq $marker }).Count -gt 0
        $checks.b_verified = $bOk
        if (-not $bOk) {
            $seen = @($b | ForEach-Object { [string]$_.status }) -join ','
            $failures.Add("b_not_verified:$D$(if ($seen) { " ($seen)" })")
        }
        # 4. L6_G bundle verified.
        if ($l6gDue) {
            $g = @(Get-WeatherReceiptRows -Text (Read-WeatherSharedText -Path (Join-Path $ReceiptsRoot 'l6g_bundle_receipts.jsonl')) |
                Where-Object { $_.target_date -ceq $D })
            $gOk = @($g | Where-Object { $_.status -ceq 'verified' }).Count -gt 0
            $checks.l6g_bundle_verified = $gOk
            if (-not $gOk) {
                $seen = @($g | ForEach-Object { [string]$_.status }) -join ','
                $failures.Add("l6g_bundle_not_verified:$D$(if ($seen) { " ($seen)" })")
            }
        }
    }
    if ($slot -eq '18:05' -and $l6gDue) {
        # 5. L6_G emitted (its receipt is written only after every control passed).
        $e = @(Get-WeatherReceiptRows -Text (Read-WeatherSharedText -Path (Join-Path $ReceiptsRoot 'l6g_input_receipts.jsonl')) |
            Where-Object { $_.date -ceq $D })
        $checks.l6g_emitted = ($e.Count -gt 0)
        if ($e.Count -eq 0) { $failures.Add("l6g_not_emitted:$D") }
    }
    $status = if ($failures.Count) { 'ALERT' } else { 'OK' }
}

$row = [ordered]@{
    schema = 'forward_arrival_check/1'
    status = $status
    target_date = $D
    slot = $slot
    checked_local = $localNow.ToString('yyyy-MM-ddTHH:mm:ss', $culture)
    checked_utc = $utcNow.ToString('yyyy-MM-ddTHH:mm:ssZ', $culture)
    last_date = $LastDate
    failures = @($failures)
    checks = $checks
}
$json = $row | ConvertTo-Json -Compress -Depth 4
[void][IO.Directory]::CreateDirectory($alertDir)
Add-Content -LiteralPath $ledgerPath -Value $json -Encoding UTF8
Write-WeatherAtomicText -Path $statePath -Text ($json + "`n")
Write-Output $json
if ($status -eq 'ALERT') { exit 2 }
exit 0
