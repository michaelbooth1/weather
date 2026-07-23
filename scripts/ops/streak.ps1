# One-word streak check:  .\scripts\ops\streak.ps1   (add -Json or -Monitor)
# The single most important operational status: contiguous complete-grade Toronto
# days toward the 14-day code-soak lock, plus whether TODAY is on track.
[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$Monitor
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$script = Join-Path $repo "scripts\ops\streak_status.py"
$passthru = @()
if ($Json) { $passthru += "--json" }
if ($Monitor) { $passthru += "--monitor" }
& $py $script @passthru
exit $LASTEXITCODE
