<#
.SYNOPSIS
Boot-task entry point of WeatherMakerEvidenceTornQuarantine (torn-journal quarantine Stage 2).

.DESCRIPTION
Runs maker_evidence_torn_quarantine.ps1 -Apply on the core root in a child Windows PowerShell and
passes its exit code through, with one exception: REFUSED_WRITER_ALIVE (exit 2: a running recorder
or a held .writer.lock) becomes 0. After a normal boot the recorder is up within one PT5M trigger,
so every later run of the 15-minute poll is that refusal; it means "nothing to recover", and as a
non-zero LastTaskResult it would be a status.ps1 failure until the next boot. Every other refusal
(cap, multiple unsealed segments, volume, reparse), UNRESOLVED (5), mid-apply failure (4) and
internal error (6) keeps its code. Takes no parameters; the Stage 1 script derives the repository
root from its own path. Never touches the Scheduler, the recorder or any file itself.

Exit codes: the Stage 1 code, except REFUSED_WRITER_ALIVE -> 0; 6 when the child cannot be run or
returns no code.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$exitCode = 6
try {
    $stage1 = Join-Path $PSScriptRoot 'maker_evidence_torn_quarantine.ps1'
    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $lines = @(& $powerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $stage1 -Apply)
    $childCode = $LASTEXITCODE
    $lines
    if ($null -ne $childCode) {
        $exitCode = [int]$childCode
        $status = ''
        try { $status = [string](($lines -join "`n") | ConvertFrom-Json).status } catch { $status = '' }
        if ($exitCode -eq 2 -and $status -ceq 'REFUSED_WRITER_ALIVE') { $exitCode = 0 }
    }
}
catch {
    Write-Output ('maker_evidence_torn_quarantine_boot: ' + $_.Exception.Message)
    $exitCode = 6
}
finally {
    $Host.SetShouldExit($exitCode)
    exit $exitCode
}
