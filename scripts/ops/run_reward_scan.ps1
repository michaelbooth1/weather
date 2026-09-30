# Owner-started, foreground, read-only reward-opportunity scan loop for the
# workstation (docs/operations/reward-scan.md). Each iteration runs one
# `weather.market.reward_scan scan`, which reads public CLOB reward terms and books
# and the wallet reader's pool percentages; it places, cancels and signs nothing.
# No Scheduler registration: Ctrl+C stops it. -WhatIf prints the command only.
#
#   .\scripts\ops\run_reward_scan.ps1 -WhatIf
#   .\scripts\ops\run_reward_scan.ps1 -Once
#   .\scripts\ops\run_reward_scan.ps1 -IntervalMinutes 15 -Condition 0x<64 hex>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Python = "",
    [string]$OutDir = "",
    [string[]]$Condition = @(),
    [ValidateRange(5, 240)][int]$IntervalMinutes = 15,
    [switch]$NoReader,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
if (-not $Python) { $Python = Join-Path $RepoRoot "venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $Python)) {
    throw "venv python not found at $Python -- pass -Python or create the venv."
}
foreach ($id in $Condition) {
    if ($id -notmatch '^0x[0-9a-fA-F]{64}$') { throw "condition id must be 0x plus 64 hex characters: $id" }
}

$arguments = @("-m", "weather.market.reward_scan", "scan")
if ($OutDir) { $arguments += @("--out", $OutDir) }
foreach ($id in $Condition) { $arguments += @("--condition", $id) }
if ($NoReader) { $arguments += "--no-reader" }
# One scan must finish inside the interval: stop opening GETs 2 minutes early.
$arguments += @("--deadline-seconds", [string](($IntervalMinutes * 60) - 120))

if (-not $PSCmdlet.ShouldProcess("$Python $($arguments -join ' ')", "run read-only reward scan every $IntervalMinutes minutes")) {
    return
}

Push-Location $RepoRoot
try {
    while ($true) {
        $started = Get-Date
        & $Python @arguments
        if ($LASTEXITCODE -ne 0) { Write-Warning "reward scan exited $LASTEXITCODE; continuing" }
        if ($Once) { break }
        $next = $started.AddMinutes($IntervalMinutes)
        $wait = [int][Math]::Max(0, ($next - (Get-Date)).TotalSeconds)
        Start-Sleep -Seconds $wait
    }
} finally {
    Pop-Location
}
