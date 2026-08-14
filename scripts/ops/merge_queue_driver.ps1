# Drive an explicitly approved merge queue whose entries are bound to immutable commits.
# Missing queues are a no-op; malformed or moved entries fail the entire run before a merge.
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$QueueFile,
    [Parameter(Mandatory = $true)][string]$LogFile
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$mergeScript = Join-Path $RepoRoot "scripts\ops\quiet_window_merge.ps1"
$logParent = Split-Path -Parent ([IO.Path]::GetFullPath($LogFile))
if (-not (Test-Path -LiteralPath $logParent)) {
    New-Item -ItemType Directory -Path $logParent -Force | Out-Null
}
function Note([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Output $line
}

Note "=== exact-tip merge queue starting ==="
if (-not (Test-Path -LiteralPath $QueueFile -PathType Leaf)) {
    Note "queue absent; no work"
    exit 0
}
$payload = Get-Content -LiteralPath $QueueFile -Raw | ConvertFrom-Json
$entries = @($payload.entries)
if ([string]$payload.schema_version -ne "weather_exact_tip_merge_queue_v1") {
    throw "unsupported merge queue schema"
}

# Validate every entry before allowing the first merge. A later malformed row must not leave
# the queue half-applied, and a movable ref is never substituted for its reviewed object.
foreach ($entry in $entries) {
    $branch = [string]$entry.branch
    $expectedTip = ([string]$entry.expected_tip).ToLowerInvariant()
    if (-not [bool]$entry.approved) { throw "queue entry is not explicitly approved: $branch" }
    if ($branch -notmatch '^(origin/)?codex/[A-Za-z0-9._/-]+$') {
        throw "invalid branch ref in queue: $branch"
    }
    if ($expectedTip -notmatch '^[0-9a-f]{40}$') {
        throw "expected_tip must be a full SHA for $branch"
    }
    $commitRef = "{0}^{{commit}}" -f $branch
    $resolvedRaw = @(& git -C $RepoRoot rev-parse --verify $commitRef)
    $resolveExit = $LASTEXITCODE
    $resolved = if ($resolvedRaw.Count -gt 0) { ([string]$resolvedRaw[-1]).Trim().ToLowerInvariant() } else { "" }
    if ($resolveExit -ne 0 -or $resolved -ne $expectedTip) {
        throw "exact-tip preflight failed for ${branch}: resolved=$resolved expected=$expectedTip"
    }
}

foreach ($entry in $entries) {
    $branch = [string]$entry.branch
    $expectedTip = ([string]$entry.expected_tip).ToLowerInvariant()
    & git -C $RepoRoot merge-base --is-ancestor $expectedTip master
    if ($LASTEXITCODE -eq 0) {
        Note "already merged: $branch at $expectedTip"
        continue
    }
    Note "merging reviewed entry: $branch at $expectedTip"
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $mergeScript -Branch $branch -ExpectedTip $expectedTip
    if ($LASTEXITCODE -ne 0) {
        throw "guarded merge failed for $branch with exit $LASTEXITCODE; later entries were not attempted"
    }
}
Note "=== exact-tip merge queue finished ==="
