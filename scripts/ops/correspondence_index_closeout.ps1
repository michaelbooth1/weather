# Closeout regeneration of the correspondence index (option D).
#
#   .\scripts\ops\correspondence_index_closeout.ps1 [-Land] [-RepoRoot <path>]
#
# Branches never commit docs/roadmap/correspondence-index*.md; the morning
# closeout regenerates it once after the night's landings. This script does that
# in one idempotent command:
#
#   1. fetch origin/master and check it out detached in a temporary worktree;
#   2. run the generator from that worktree's own source;
#   3. if nothing changed, report "unchanged" and exit 0;
#   4. refuse unless the diff touches only the generated index files, and
#      unless the strict --check then passes;
#   5. commit on docs/correspondence-index-closeout-<origin/master 12> and push
#      that branch (pushing a branch never rolls capture). A rerun on the same
#      origin/master reuses the pushed branch when it already carries this tree.
#   6. with -Land, hand the branch to docs_light_path.ps1 (roll-free, Markdown
#      under docs/ only) and return its exit code.
#
# The temporary worktree is always removed. Exit codes: 0 unchanged, prepared or
# landed; 1 refused or failed; otherwise docs_light_path.ps1's code.
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [string]$WorktreeRoot = "",
    [switch]$Land
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path.TrimEnd('\')
if (-not $PythonPath) { $PythonPath = Join-Path $RepoRoot "venv\Scripts\python.exe" }
if (-not $WorktreeRoot) { $WorktreeRoot = Join-Path $env:SystemDrive "lpf-s\idx-closeout" }
$generatedPattern = '^docs/roadmap/correspondence-index(\.md|/[^/]+\.md)$'

function Note([string]$m) { Write-Host ("[index-closeout] {0}" -f $m) }

function Invoke-Git([string]$dir, [string[]]$arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& git -C $dir @arguments 2>&1 | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw ("git {0} failed (exit {1}): {2}" -f ($arguments -join ' '), $code, ($out -join ' | ')) }
    return @($out | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Invoke-Generator([string]$dir, [string[]]$arguments) {
    $previous = $env:PYTHONPATH
    $env:PYTHONPATH = "$dir;$dir\src"
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& $PythonPath -m weather.reporting.roadmap.correspondence_index --repo-root $dir @arguments 2>&1 |
            ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = "Stop"
        $env:PYTHONPATH = $previous
    }
    $out | ForEach-Object { Note $_ }
    return $code
}

Invoke-Git $RepoRoot @("fetch", "--quiet", "origin", "master") | Out-Null
$base = ([string]@(Invoke-Git $RepoRoot @("rev-parse", "--verify", "origin/master^{commit}"))[0]).ToLowerInvariant()
$branch = "docs/correspondence-index-closeout-{0}" -f $base.Substring(0, 12)
$worktree = Join-Path $WorktreeRoot ("{0}-{1}" -f $base.Substring(0, 12), [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $WorktreeRoot -Force | Out-Null
Invoke-Git $RepoRoot @("worktree", "add", "--quiet", "--detach", $worktree, $base) | Out-Null
$exit = 1
try {
    if ((Invoke-Generator $worktree @()) -ne 0) { throw "generator failed" }
    $changed = @(Invoke-Git $worktree @("status", "--porcelain", "--untracked-files=all") |
        ForEach-Object { ($_ -replace '^\S+\s+', '') -replace '\\', '/' })
    if ($changed.Count -eq 0) {
        Note "unchanged: origin/master $base already carries the regenerated index"
        $exit = 0
        return
    }
    $foreign = @($changed | Where-Object { $_ -cnotmatch $generatedPattern })
    if ($foreign.Count -gt 0) { throw ("refused: regeneration touched non-index paths: {0}" -f ($foreign -join ', ')) }
    if ((Invoke-Generator $worktree @("--check")) -ne 0) { throw "refused: strict --check fails after regeneration" }

    Invoke-Git $worktree @("add", "--all", "--", "docs/roadmap/correspondence-index.md", "docs/roadmap/correspondence-index") | Out-Null
    Invoke-Git $worktree @("-c", "core.hooksPath=", "commit", "--quiet", "-m",
        "docs(roadmap): regenerate the correspondence index after landings (closeout)") | Out-Null
    $tip = ([string]@(Invoke-Git $worktree @("rev-parse", "HEAD"))[0]).ToLowerInvariant()
    $tree = [string]@(Invoke-Git $worktree @("rev-parse", "HEAD^{tree}"))[0]

    $remote = @(Invoke-Git $RepoRoot @("ls-remote", "origin", "refs/heads/$branch"))
    if ($remote.Count -eq 1) {
        $remoteTip = ((([string]$remote[0]) -split '\s+')[0]).ToLowerInvariant()
        Invoke-Git $RepoRoot @("fetch", "--quiet", "origin", $branch) | Out-Null
        $remoteTree = [string]@(Invoke-Git $RepoRoot @("rev-parse", "$remoteTip^{tree}"))[0]
        if ($remoteTree -ne $tree) { throw "refused: origin/$branch exists with a different tree; inspect it" }
        $tip = $remoteTip
        Note "reusing origin/$branch at $tip (same tree)"
    }
    else {
        Invoke-Git $worktree @("push", "--quiet", "origin", "HEAD:refs/heads/$branch") | Out-Null
        Note "pushed origin/$branch at $tip"
    }
    Write-Output ("CLOSEOUT_BRANCH=origin/{0}" -f $branch)
    Write-Output ("CLOSEOUT_TIP={0}" -f $tip)
    if (-not $Land) {
        Note ("land with: .\scripts\ops\docs_light_path.ps1 -Branch origin/{0} -ExpectedTip {1}" -f $branch, $tip)
        $exit = 0
        return
    }
    Invoke-Git $RepoRoot @("fetch", "--quiet", "origin", $branch) | Out-Null
    & (Join-Path $RepoRoot "scripts\ops\docs_light_path.ps1") -Branch "origin/$branch" -ExpectedTip $tip -RepoRoot $RepoRoot
    $exit = $LASTEXITCODE
}
catch {
    Note $_.Exception.Message
    $exit = 1
}
finally {
    try { Invoke-Git $RepoRoot @("worktree", "remove", "--force", $worktree) | Out-Null }
    catch { Note ("worktree cleanup failed: {0}" -f $_.Exception.Message) }
    exit $exit
}
