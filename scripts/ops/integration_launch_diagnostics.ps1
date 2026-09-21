# Small create-once bootstrap journal. It records that this wrapper actually
# entered, before source/task/host validation can fail. It is diagnostic evidence
# only: a bootstrap event never grants suite, merge, or live authority.

function Write-WeatherLaunchDiagnostic {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Journal,
        [Parameter(Mandatory = $true)][string]$Event,
        [object]$Detail = $null
    )

    if ($Journal.Closed) { throw "Launch diagnostic journal is already closed." }
    $record = [ordered]@{
        format_version = 1
        at_utc = [datetime]::UtcNow.ToString("o")
        operation = $Journal.Operation
        event = $Event
        pid = $PID
        detail = $Detail
    }
    $line = ($record | ConvertTo-Json -Depth 6 -Compress) + "`n"
    $bytes = [Text.UTF8Encoding]::new($false, $true).GetBytes($line)
    if ($Journal.Stream.Length + $bytes.Length -gt 65536) {
        throw "Launch diagnostic journal exceeded its 64 KiB limit."
    }
    $Journal.Stream.Write($bytes, 0, $bytes.Length)
    $Journal.Stream.Flush($true)
}

function New-WeatherLaunchDiagnostics {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][object]$Binding
    )

    $resolved = [IO.Path]::GetFullPath($Path)
    $parent = Get-Item -LiteralPath (Split-Path -Parent $resolved) -Force -ErrorAction Stop
    if (-not $parent.PSIsContainer -or
        ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Launch diagnostic parent must be an existing regular directory."
    }
    $stream = [IO.File]::Open(
        $resolved, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    $journal = [pscustomobject]@{
        Path = $resolved
        Operation = $Operation
        Stream = $stream
        Closed = $false
    }
    try {
        Write-WeatherLaunchDiagnostic -Journal $journal -Event "WRAPPER_ENTERED" -Detail ([ordered]@{
            binding = $Binding
            script_path = [IO.Path]::GetFullPath($ScriptPath)
            script_sha256 = (Get-FileHash -LiteralPath $ScriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
            principal = [Security.Principal.WindowsIdentity]::GetCurrent().Name
            powershell_version = $PSVersionTable.PSVersion.ToString()
        })
        return $journal
    }
    catch {
        $stream.Dispose()
        $journal.Closed = $true
        throw
    }
}

function Close-WeatherLaunchDiagnostics {
    [CmdletBinding()]
    param(
        [AllowNull()][object]$Journal,
        [Parameter(Mandatory = $true)][ValidateSet("PASS", "FAIL")][string]$Status,
        [AllowNull()][object]$Failure = $null
    )

    if ($null -eq $Journal -or $Journal.Closed) { return }
    try {
        $detail = [ordered]@{ status = $Status; failure_type = $null; failure = $null }
        if ($null -ne $Failure) {
            $detail.failure_type = $Failure.Exception.GetType().FullName
            $message = [string]$Failure.Exception.Message
            $detail.failure = $message.Substring(0, [math]::Min(4096, $message.Length))
        }
        Write-WeatherLaunchDiagnostic -Journal $Journal -Event "WRAPPER_EXIT" -Detail $detail
    }
    finally {
        $Journal.Stream.Dispose()
        $Journal.Closed = $true
    }
}
