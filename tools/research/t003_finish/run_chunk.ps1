# Invoke only after master GO for this exact commit and script pin.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ReviewedCommit,
    [ValidateSet('scan','compare','aggregate')][string]$Mode='scan',
    [ValidateRange(0,719)][int]$Start=0,
    [ValidateRange(1,30)][int]$Count=30,
    [switch]$CheckOnly
)
$ErrorActionPreference='Stop'
$exitCode=1
try {
    $repo='C:\wt\codex-t003-finish-20261110'
    $scriptPath='C:\t\codex\T085\out\scan.py'
    $sha=(Get-FileHash -Algorithm SHA256 -LiteralPath $scriptPath).Hash.ToLowerInvariant()
    & git -C $repo merge-base --is-ancestor $ReviewedCommit HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Reviewed commit is not ancestral to HEAD' }
    $committed=(& git -C $repo show "${ReviewedCommit}:scripts/ops/workload_admission.ps1") -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Reviewed admission helper unavailable' }
    $pattern="path\s*=\s*'"+[regex]::Escape($scriptPath)+"'\s*\r?\n\s*sha256\s*=\s*'"+$sha+"'"
    if ($committed -cnotmatch $pattern) { throw 'Exact reviewed script pin missing' }
    & git -C $repo diff --quiet $ReviewedCommit -- scripts/ops/workload_admission.ps1 tools/research/t003_finish
    if ($LASTEXITCODE -ne 0) { throw 'Runner or admission differs from reviewed commit' }
    $sourcePath=Join-Path $repo 'tools\research\t003_finish\scan.py'
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant() -cne $sha) {
        throw 'Task script differs from committed source'
    }
    if ($CheckOnly) {
        Write-Output "PASS reviewed pin $sha; no book payload read or lease acquired"
        $exitCode=0
    }
    else {
        $nowUtc=[DateTimeOffset]::UtcNow
        $morningEnd=[DateTimeOffset]::Parse('2026-11-10T13:23:00Z')
        $eveningStart=[DateTimeOffset]::Parse('2026-11-11T00:00:00Z')
        $eveningEnd=[DateTimeOffset]::Parse('2026-11-11T04:58:00Z')
        if ($nowUtc -ge $morningEnd -and ($nowUtc -lt $eveningStart -or $nowUtc -ge $eveningEnd)) {
            throw 'Outside reviewed morning/evening execution reserves'
        }
        # Immediate check before EVERY wrapper invocation; never create HOLD.
        if (Test-Path -LiteralPath 'C:\t\codex\HOLD_HEAVY') {
            Write-Output 'HOLD_HEAVY: no heavy invoked'; $exitCode=76
        }
        else {
            $scanArgs=@('-I',$scriptPath,$Mode,'--start',[string]$Start,'--count',[string]$Count,
                '--max-seconds','1000','--reviewed-commit',$ReviewedCommit)
            $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -Compress -InputObject $scanArgs)))
            & C:\wt\codex-t003-finish-20261110\scripts\ops\workstation_heavy.ps1 -Kind research_script `
                -PythonPath C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe `
                -ArgumentsBase64 $encoded -RepoRoot $repo -Queue -QueueTimeoutSeconds 60
            $exitCode=$LASTEXITCODE
        }
    }
}
catch { $Host.UI.WriteErrorLine(($_ | Out-String).TrimEnd()) }
finally { $Host.SetShouldExit($exitCode); exit $exitCode }
