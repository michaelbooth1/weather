# Shared immutable path, source and time binding for one approved recovery night.
Set-StrictMode -Version 2

function Assert-WeatherNightDirectory {
    param([string]$Path)
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path -match '["\r\n]' -or
        [IO.Path]::GetFullPath($Path).TrimEnd('\') -cne $Path.TrimEnd('\')) {
        throw 'absolute normalized paths required'
    }
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'night evidence/source ancestors must be ordinary directories'
            }
        }
        $current = Split-Path -Parent $current
    }
}

function Assert-WeatherNightSource {
    param([string]$SourceRoot, [string]$ExpectedSourceTip)
    Assert-WeatherNightDirectory $SourceRoot
    $tip = [string](git -C $SourceRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0 -or $tip.Trim() -cne $ExpectedSourceTip) { throw 'night source tip mismatch' }
    $dirty = @(git -C $SourceRoot status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'night source must be clean' }
}

function Read-WeatherNightPlan {
    param([string]$ProductionRepoRoot, [string]$SourceRoot, [string]$ExpectedSourceTip,
          [string]$PlanPath, [string]$PlanSha256)
    Assert-WeatherNightDirectory $ProductionRepoRoot
    Assert-WeatherNightDirectory (Split-Path -Parent $PlanPath)
    $info = Get-Item -LiteralPath $PlanPath -Force
    if ($info.PSIsContainer -or $info.Length -gt 262144 -or
        ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'invalid night plan file' }
    if ((Get-FileHash -LiteralPath $PlanPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $PlanSha256) {
        throw 'night plan SHA-256 mismatch'
    }
    $plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $SourceRoot
    $hostIdentity = Get-WeatherExecutionHostId
    if ($hostIdentity -cne [string]$assignment.dedicated_capture_execution_host_id -or
        $plan.execution_host_id -cne $hostIdentity -or $plan.source_git_sha -cne $ExpectedSourceTip -or
        $plan.production_repo_root -cne $ProductionRepoRoot -or $plan.source_root -cne $SourceRoot) {
        throw 'night plan host/source/root binding mismatch'
    }
    $night = [DateTime]::ParseExact($plan.night_date, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    if ($plan.plan_id -cnotmatch ('^capacity-' + $night.ToString('yyyyMMdd') + '-[a-z0-9]{1,12}$')) {
        throw 'invalid one-night plan identifier'
    }
    $zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
    $expiry = [TimeZoneInfo]::ConvertTimeToUtc($night.AddHours(9), $zone)
    $approved = [DateTimeOffset]::Parse($plan.approved_at_utc).UtcDateTime
    if ([DateTimeOffset]::Parse($plan.expires_at_utc).UtcDateTime -ne $expiry -or
        $approved -gt [DateTime]::UtcNow -or [DateTime]::UtcNow -ge $expiry -or
        ($expiry - $approved).TotalHours -gt 72 -or $plan.allow_resource_recovery -ne $true) {
        throw 'night plan approval invalid or expired'
    }
    return $plan
}

function Get-WeatherNightTimes {
    param($Plan, [ValidateSet('early','late')][string]$Segment)
    $night = [DateTime]::ParseExact($Plan.night_date, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    $zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
    $startMinute, $endMinute = 30, 282
    if ($Segment -eq 'late') { $startMinute, $endMinute = 405, 535 }
    return @{
        Start = [TimeZoneInfo]::ConvertTimeToUtc($night.AddMinutes($startMinute), $zone)
        End = [TimeZoneInfo]::ConvertTimeToUtc($night.AddMinutes($endMinute), $zone)
    }
}

function Write-WeatherNightJson {
    param([string]$Path, $Value)
    Assert-WeatherNightDirectory (Split-Path -Parent $Path)
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 30) + [Environment]::NewLine)
    if ($bytes.Length -gt 2097152) { throw 'night receipt too large' }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
}
