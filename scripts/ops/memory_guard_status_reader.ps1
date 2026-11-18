# Shared reader for data\logs\memory_commit_guard_status.json. Dot-source it.
#
# memory_commit_guard.ps1 writes that file every minute with Windows PowerShell 5.1
# `Out-File -Encoding utf8` (a UTF-8 BOM) to a temp file and then replaces the live
# file by rename. A reader that opens it without FileShare.Delete can block or lose
# that replacement, and a reader that decodes it without stripping U+FEFF hands
# ConvertFrom-Json a leading BOM. Both broke load gates (Swarm P audit 2026-10-07).
# This reader opens with FileShare ReadWrite|Delete, strips the BOM explicitly and
# retries briefly across a rename. status.ps1 carries a byte-identical inline copy
# (it is a single hash-pinned file); a test keeps the two copies identical.
# Returns row, last_write_time (LOCAL, kept for compatibility), last_write_time_utc
# (ISO-8601 round-trip string ending in Z) and attempts. Freshness gates must use
# Get-WeatherMemoryGuardStatusAgeMinutes (UTC on both sides), never the local time.
# Pure host tooling; imports nothing from a capture loop -> roll-free.

function Read-WeatherMemoryGuardStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 20)][int]$Attempts = 6,
        [ValidateRange(1, 1000)][int]$RetryMilliseconds = 25
    )
    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
            $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
            try {
                $lastWrite = [IO.File]::GetLastWriteTime($Path)
                $lastWriteUtc = [IO.File]::GetLastWriteTimeUtc($Path).ToString('o', [Globalization.CultureInfo]::InvariantCulture)
                $reader = New-Object IO.StreamReader($stream, (New-Object Text.UTF8Encoding($false)), $false)
                try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
            }
            finally { $stream.Dispose() }
            $text = $text.TrimStart([char]0xFEFF)
            if ([string]::IsNullOrWhiteSpace($text)) { throw "memory guard status is empty" }
            $row = $text | ConvertFrom-Json -ErrorAction Stop
            return [pscustomobject]@{ row = $row; last_write_time = $lastWrite
                last_write_time_utc = $lastWriteUtc; attempts = $attempt }
        }
        catch {
            $lastError = $_
            if ($attempt -lt $Attempts) { Start-Sleep -Milliseconds $RetryMilliseconds }
        }
    }
    throw $lastError
}

# Freshness age of a Read-WeatherMemoryGuardStatus result, in minutes, UTC on both sides
# (GetLastWriteTimeUtc vs [DateTime]::UtcNow). A local LastWriteTime fails OPEN in the
# fall-back hour (a file written before the repeated 01:00 reads up to ~60 min young) and
# closed in the spring-forward hour. Fails closed: returns +Infinity (stale, callers refuse)
# when last_write_time_utc is missing or unparseable (an older reader), when either side
# is not UTC Kind, or when the write time is more than one minute in the future.
# -UtcNow exists only so tests can pin the clock; it defaults to the real UTC clock.
function Get-WeatherMemoryGuardStatusAgeMinutes {
    param(
        [Parameter(Mandatory = $true)][AllowNull()]$Read,
        [Nullable[DateTime]]$UtcNow = $null
    )
    $stale = [double]::PositiveInfinity
    # PowerShell unwraps Nullable[DateTime]; use the variable itself, never .Value.
    $now = if ($null -ne $UtcNow) { $UtcNow } else { [DateTime]::UtcNow }
    if (-not ($now -is [datetime]) -or $now.Kind -ne [DateTimeKind]::Utc) { return $stale }
    if ($null -eq $Read -or -not ($Read.PSObject.Properties.Name -contains 'last_write_time_utc')) { return $stale }
    $raw = $Read.last_write_time_utc
    $written = [DateTime]::MinValue
    if ($raw -is [datetime]) {
        $written = $raw
    }
    elseif (-not ($raw -is [string]) -or -not [DateTime]::TryParseExact(
            $raw, 'o', [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind, [ref]$written)) {
        return $stale
    }
    if ($written.Kind -ne [DateTimeKind]::Utc) { return $stale }
    $age = ($now - $written).TotalMinutes
    if ($age -lt -1) { return $stale }
    return [double]$age
}
