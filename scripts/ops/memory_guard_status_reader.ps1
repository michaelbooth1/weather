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
                $reader = New-Object IO.StreamReader($stream, (New-Object Text.UTF8Encoding($false)), $false)
                try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
            }
            finally { $stream.Dispose() }
            $text = $text.TrimStart([char]0xFEFF)
            if ([string]::IsNullOrWhiteSpace($text)) { throw "memory guard status is empty" }
            $row = $text | ConvertFrom-Json -ErrorAction Stop
            return [pscustomobject]@{ row = $row; last_write_time = $lastWrite; attempts = $attempt }
        }
        catch {
            $lastError = $_
            if ($attempt -lt $Attempts) { Start-Sleep -Milliseconds $RetryMilliseconds }
        }
    }
    throw $lastError
}
