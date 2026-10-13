<#
.SYNOPSIS
    Removes only the items a workstation space report marked SAFE and that are still SAFE now.

.DESCRIPTION
    Input is the JSON written by workstation_space_report.ps1 -JsonPath: the list the owner reviews
    and approves (delete entries to keep them; set "recursive": true on a folder to approve removing
    its contents). For every SAFE item this script runs a fresh re-check through the report script,
    with the report's own roots, and refuses the item unless it is still SAFE, still the same kind,
    still the same commit (worktrees) and still a direct child of a recorded scratch root (folders).
    Every other item is refused with its reason.

    Without -Apply nothing is removed: the receipt lists what would be removed and what is refused.
    With -Apply:
      worktree  git worktree remove <path>, never --force: git itself refuses dirty or locked trees.
                The branch is kept.
      folder    non-recursive by default (removes an empty folder only). With "recursive": true in
                the report, a fully inspected tree is removed bottom-up; any reparse point refuses
                the whole item and a junction is never entered.

    Always writes a JSON receipt (-ReceiptPath, default beside the report). Exit 0 when nothing
    failed (refusals are normal), 1 when an attempted removal failed, 2 when the report is unusable.

.EXAMPLE
    .\scripts\ops\workstation_space_clean.ps1 -FromReport C:\wt\space-report.json
    .\scripts\ops\workstation_space_clean.ps1 -FromReport C:\wt\space-report.json -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$FromReport,
    [switch]$Apply,
    [string]$ReceiptPath = ""
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$reportScript = Join-Path $PSScriptRoot 'workstation_space_report.ps1'
$startUtc = [datetime]::UtcNow
if (-not $ReceiptPath) {
    $ReceiptPath = [System.IO.Path]::ChangeExtension($FromReport, $null).TrimEnd('.') +
        '.clean-' + (Get-Date).ToString('yyyyMMdd-HHmmss') + '.json'
}

function Write-Receipt($Receipt) {
    $dir = Split-Path -Parent $ReceiptPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText($ReceiptPath, ($Receipt | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
}

function Test-Prop($Object, [string]$Name) { return $null -ne $Object.PSObject.Properties[$Name] }

$receipt = [ordered]@{
    schema = 'workstation_space_clean_receipt_v1'
    mode = $(if ($Apply) { 'apply' } else { 'list' })
    report_path = $FromReport
    report_sha256 = $null
    started_utc = $startUtc.ToString('o')
    finished_utc = $null
    removed = @(); would_remove = @(); refused = @(); failed = @()
    error = $null
}

try {
    $raw = [System.IO.File]::ReadAllText($FromReport)
    $receipt.report_sha256 = (Get-FileHash -LiteralPath $FromReport -Algorithm SHA256).Hash.ToLowerInvariant()
    $report = $raw | ConvertFrom-Json
    if (-not (Test-Prop $report 'schema') -or $report.schema -ne 'workstation_space_report_v1') { throw 'not a workstation_space_report_v1 file' }
    foreach ($field in @('repo_root', 'scratch_roots', 'items', 'idle_hours', 'process_check')) {
        if (-not (Test-Prop $report $field)) { throw "report has no $field" }
    }
} catch {
    $receipt.error = "unusable report: $($_.Exception.Message)"
    $receipt.finished_utc = [datetime]::UtcNow.ToString('o')
    Write-Receipt $receipt
    Write-Output $receipt.error
    exit 2
}

$roots = @($report.scratch_roots | ForEach-Object { [string]$_ })
$idle = [math]::Max(24.0, [double]$report.idle_hours)
$policy = if ([string]$report.process_check.policy -eq 'ignore') { 'ignore' } else { 'check' }
$candidates = @()
$refused = New-Object System.Collections.Generic.List[object]
foreach ($item in @($report.items)) {
    if ([string]$item.verdict -eq 'SAFE') { $candidates += $item }
    else { $refused.Add([ordered]@{ path = [string]$item.path; kind = [string]$item.kind
        reason = ('report verdict {0}: {1}' -f $item.verdict, (@($item.reasons) -join ' | ')) }) }
}

$fresh = @{}
if ($candidates.Count -gt 0) {
    $recheck = & $reportScript -RepoRoot ([string]$report.repo_root) -ScratchRoots $roots -IdleHours $idle `
        -OnlyPaths @($candidates | ForEach-Object { [string]$_.path }) -UnreadableProcessPolicy $policy -PassThru
    foreach ($f in @($recheck.items)) { $fresh[([string]$f.path).ToLowerInvariant()] = $f }
}

$removed = New-Object System.Collections.Generic.List[object]
$would = New-Object System.Collections.Generic.List[object]
$failed = New-Object System.Collections.Generic.List[object]

foreach ($item in $candidates) {
    $path = [string]$item.path
    $kind = [string]$item.kind
    $now = $fresh[$path.ToLowerInvariant()]
    $why = $null
    if ($null -eq $now) { $why = 'fresh re-check: item no longer found' }
    elseif ([string]$now.kind -ne $kind) { $why = "fresh re-check: kind changed to $($now.kind)" }
    elseif ([string]$now.verdict -ne 'SAFE') { $why = ('fresh re-check verdict {0}: {1}' -f $now.verdict, (@($now.reasons) -join ' | ')) }
    elseif ($kind -eq 'worktree' -and [string]$now.head -ne [string]$item.head) { $why = 'fresh re-check: HEAD moved since the report' }
    elseif ($kind -eq 'folder') {
        $parent = Split-Path -Parent $path
        $inRoot = @($roots | Where-Object { $_.Equals($parent, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
        if (-not $inRoot) { $why = 'folder is not a direct child of a recorded scratch root' }
    } elseif ($kind -ne 'worktree') { $why = "kind $kind is never removed" }
    if ($why) { $refused.Add([ordered]@{ path = $path; kind = $kind; reason = $why }); continue }

    $recursive = (Test-Prop $item 'recursive') -and ($item.recursive -eq $true)
    if ($kind -eq 'folder' -and -not $recursive) {
        $hasChildren = @(Get-ChildItem -LiteralPath $path -Force -ErrorAction SilentlyContinue | Select-Object -First 1).Count -gt 0
        if ($hasChildren) {
            $refused.Add([ordered]@{ path = $path; kind = $kind
                reason = 'not empty and "recursive": true was not set for this item in the report' }); continue
        }
    }
    $entry = [ordered]@{ path = $path; kind = $kind; size_bytes = $now.size_bytes; recursive = $recursive
        head = $(if ($kind -eq 'worktree') { [string]$now.head } else { $null })
        branch = $(if ($kind -eq 'worktree') { [string]$now.branch } else { $null }) }
    if (-not $Apply) { $would.Add($entry); continue }

    try {
        if ($kind -eq 'worktree') {
            $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
            try { $out = & git -C ([string]$report.repo_root) worktree remove $path 2>&1; $code = $LASTEXITCODE }
            finally { $ErrorActionPreference = $old }
            if ($code -ne 0) { throw ('git worktree remove exit {0}: {1}' -f $code, (($out | ForEach-Object { [string]$_ }) -join ' ')) }
            if (Test-Path -LiteralPath $path) { throw 'git worktree remove succeeded but the folder remains' }
        } elseif ($recursive) {
            $entry.removed_entries = [SpaceReportNative]::RemoveTree($path)
        } else {
            [System.IO.Directory]::Delete($path, $false)
        }
        $removed.Add($entry)
    } catch {
        $failed.Add([ordered]@{ path = $path; kind = $kind; reason = $_.Exception.Message })
    }
}

$receipt.removed = $removed.ToArray()
$receipt.would_remove = $would.ToArray()
$receipt.refused = $refused.ToArray()
$receipt.failed = $failed.ToArray()
$receipt.finished_utc = [datetime]::UtcNow.ToString('o')
Write-Receipt $receipt

'{0}: removed {1}, would remove {2}, refused {3}, failed {4}' -f $receipt.mode, $removed.Count, $would.Count, $refused.Count, $failed.Count
foreach ($e in $would) { 'WOULD REMOVE  {0}  {1}' -f $e.kind, $e.path }
foreach ($e in $removed) { 'REMOVED       {0}  {1}' -f $e.kind, $e.path }
foreach ($e in $failed) { 'FAILED        {0}  {1}  {2}' -f $e.kind, $e.path, $e.reason }
"receipt: $ReceiptPath"
if ($failed.Count -gt 0) { exit 1 }
exit 0
