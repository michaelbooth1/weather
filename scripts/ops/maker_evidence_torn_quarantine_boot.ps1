<#
.SYNOPSIS
Boot-task entry point of WeatherMakerEvidenceTornQuarantine (torn-journal quarantine Stage 2).

.DESCRIPTION
Runs maker_evidence_torn_quarantine.ps1 -Apply on the core root in a child Windows PowerShell and
passes its exit code through, with one exception: exit 2 with status REFUSED_WRITER_ALIVE becomes 0
only when the same JSON proves torn_tail_found is false (Stage 1's read-only scan of the unsealed
segments older than the last cold boot completed and found no torn tail). After a normal boot the recorder
is up within one PT5M trigger, so every later run of the 15-minute poll is that clean refusal, and
as a non-zero LastTaskResult it would be a status.ps1 failure until the next boot.
A live writer over a torn pre-boot segment is REFUSED_WRITER_ALIVE_TORN (exit 3) and stays 3. A
writer-alive refusal whose scan did not complete (torn_tail_found null or missing) stays 2. Every
other refusal, UNRESOLVED (5), mid-apply failure (4) and internal error (6) keeps its code; so does
any output that does not parse. Takes no parameters; the Stage 1 script derives the repository root
from its own path. Never touches the Scheduler, the recorder or any file itself.

Exit codes: the Stage 1 code, except a proven-clean REFUSED_WRITER_ALIVE -> 0; 6 when the child
cannot be run or returns no code.
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
        $parsed = $null
        # Parse from the first line that starts with '{', so a stray WARNING line cannot break it.
        # No parse leaves the child's code standing.
        $start = -1
        for ($i = 0; $i -lt $lines.Count; $i++) { if ([string]$lines[$i] -like '{*') { $start = $i; break } }
        if ($start -ge 0) {
            try { $parsed = ($lines[$start..($lines.Count - 1)] -join "`n") | ConvertFrom-Json }
            catch { $parsed = $null }
        }
        if ($exitCode -eq 2 -and $null -ne $parsed -and [string]$parsed.status -ceq 'REFUSED_WRITER_ALIVE' -and
            $parsed.torn_tail_found -is [bool] -and $parsed.torn_tail_found -eq $false) { $exitCode = 0 }
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
