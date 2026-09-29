# One read-only manual order journal run (WeatherManualOrderJournal, every 5 minutes).
#
#   .\scripts\ops\manual_order_journal.ps1 -ExpectedSelfSha256 <sha> -ExpectedModulesSha256 <sha> [-StateRoot <checkout>]
#
# -RepoRoot is the code checkout (pinned modules, working directory). -StateRoot (default: RepoRoot)
# supplies venv\Scripts\python.exe, config\local\wallet_reader_client.json and data\manual_order_journal,
# so a detached reviewed worktree can journal into the production checkout's data before a merge.
#
# Appends one hash-chained record under data\manual_order_journal via
# `python -m weather.market.order_journal record`. Light and lease-free: a few LAN reader
# GETs plus at most 40 public CLOB GETs, no capture imports, no workload lease (the host load
# policy's heavy-work rules do not apply). Reads the existing wallet_reader_client.json; no venue
# credentials, orders, cancels or signing. Refuses to run if this script or the journal modules
# differ from the reviewed pins. Runbook: docs/operations/manual-order-journal.md.
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$StateRoot = "",
    [string]$ExpectedSelfSha256 = "",
    [string]$ExpectedModulesSha256 = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$repo = [IO.Path]::GetFullPath($RepoRoot)
$state = if ([string]::IsNullOrWhiteSpace($StateRoot)) { $repo } else { [IO.Path]::GetFullPath($StateRoot) }
$ModuleFiles = @(
    'src/weather/market/order_journal.py',
    'src/weather/market/order_journal_io.py',
    'src/weather/market/order_journal_sources.py',
    'src/weather/market/order_journal_report.py',
    'src/weather/market/wallet_reader_client.py'
)

function Get-ModulesSha256([string]$Root) {
    $lines = foreach ($name in $ModuleFiles) {
        $path = Join-Path $Root ($name -replace '/', '\')
        '{0}:{1}' -f $name, (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) } finally { $sha.Dispose() }
}

$outDir = Join-Path $state "data\manual_order_journal"
if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
$log = Join-Path $outDir "runner.log"
function Write-RunLog([string]$Status, [int]$Code, [string]$Detail) {
    $line = [ordered]@{ at_utc = (Get-Date).ToUniversalTime().ToString('o'); status = $Status; exit_code = $Code; detail = $Detail }
    Add-Content -LiteralPath $log -Value ($line | ConvertTo-Json -Compress) -Encoding UTF8
}

if ($ExpectedSelfSha256 -notmatch '^[0-9A-Fa-f]{64}$' -or $ExpectedModulesSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
    Write-RunLog 'refused' 3 'reviewed self and module SHA256 pins are required'
    exit 3
}
if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash -ine $ExpectedSelfSha256) {
    Write-RunLog 'refused' 3 'runner differs from its reviewed pin'
    exit 3
}
if ((Get-ModulesSha256 $repo) -ine $ExpectedModulesSha256) {
    Write-RunLog 'refused' 3 'journal modules differ from their reviewed pin; re-register after review'
    exit 3
}
$python = Join-Path $state "venv\Scripts\python.exe"
$readerConfig = Join-Path $state "config\local\wallet_reader_client.json"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-RunLog 'refused' 3 'project interpreter missing'
    exit 3
}
# Native stderr lines arrive as ErrorRecords under Windows PowerShell 5.1; keep them non-terminating
# and log their text (the client emits fixed reason codes only, never tokens).
$ErrorActionPreference = "Continue"
# The pins cover $repo\src only. The state venv may carry an editable .pth to another checkout's src,
# so the child runs with -P -B and PYTHONPATH=$repo\src (child scope), and a probe must resolve the
# journal module under $repo\src before anything is recorded.
$pinnedSrc = [IO.Path]::GetFullPath((Join-Path $repo "src")).TrimEnd('') + ''
$savedPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pinnedSrc.TrimEnd('')
Push-Location $repo
try {
    $probe = @(& $python -P -B -c "import weather.market.order_journal as m; print(m.__file__)" 2>&1 |
        ForEach-Object { "$_" })
    $probeCode = $LASTEXITCODE
    $resolved = if ($probe.Count) { $probe[-1].Trim() } else { "" }
    $resolvedFull = try { [IO.Path]::GetFullPath($resolved) } catch { "" }
    if ($probeCode -ne 0 -or -not $resolvedFull -or
            -not $resolvedFull.StartsWith($pinnedSrc, [StringComparison]::OrdinalIgnoreCase)) {
        Write-RunLog 'refused' 3 ("journal module does not resolve under the pinned checkout {0}: {1}" -f $pinnedSrc, (($probe -join ' ').Trim()))
        exit 3
    }
    $output = & $python -P -B -m weather.market.order_journal record --out $outDir --reader-config $readerConfig 2>&1
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    $env:PYTHONPATH = $savedPythonPath
}
$detail = ((@($output) | ForEach-Object { "$_" }) -join ' ').Trim()
if ($detail.Length -gt 2000) { $detail = $detail.Substring($detail.Length - 2000) }
Write-RunLog ($(if ($code -eq 0) { 'recorded' } else { 'failed' })) $code $detail
exit $code
