<#
.SYNOPSIS
    Read-only disk-space report of git worktrees and agent scratch folders, with a cleanup verdict per item.

.DESCRIPTION
    Lists (a) every git worktree of the repository and (b) every folder directly under the agent scratch
    roots, and gives each one a verdict:

      SAFE    pushed (or not a worktree), clean, idle >= IdleHours, no process inside, not locked,
              fully inspected with no reparse point and no nested repository.
      IN USE  a process has its current directory, executable or command line under it, the worktree
              is locked, or something under it was written within IdleHours.
      CHECK   anything unknown or needing an owner's eye: unpushed or dirty work, ignored files that
              are not caches, a nested repository or worktree, a reparse point, a truncated walk, a
              prunable or main worktree, or a process table that could not be fully read.

    It never deletes, moves, locks or writes anything except the optional -JsonPath file, and it does
    not fetch: "pushed" means reachable from the remote-tracking refs as of the last fetch.

    Light by construction, so it may run on either host at any hour (host load policy): it lowers its
    own priority, never walks the main working tree, never descends into a worktree's data\ folder,
    never follows a reparse point, caps every walk at -MaxEntriesPerItem entries and the whole run at
    -MaxTotalSeconds, and runs no Python, pytest or Get-ChildItem -Recurse. An item whose walk is cut
    short is reported CHECK, never SAFE.

    Open-handle enumeration needs elevation, so it is not attempted ("handles": "not-checked").
    Processes are matched by current directory (read from each process's own memory, unelevated),
    executable path and command line. workstation_space_clean.ps1 re-checks every item before
    removing it, and Windows refuses to delete a file another process holds open.

.PARAMETER RepoRoot
    The repository whose worktrees are listed. Defaults to the checkout holding this script.
.PARAMETER ScratchRoots
    Folders whose immediate child folders are reported. Defaults to the agent scratch roots named in
    docs/operations/WORKSTATION_SESSION_PREAMBLE.md plus the Claude Code scratchpad root.
.PARAMETER IncludeWorktreeData
    Also walk each worktree's data\ folder (same caps). Off by default, and never on the capture
    host, where a worktree's data\ can be large; without it worktree sizes exclude data\.
.PARAMETER OnlyPaths
    Evaluate only these item paths (used by the clean script for its fresh re-check).
.PARAMETER UnreadableProcessPolicy
    'check' (default): an unreadable interactive-session shell, git, Python or agent process makes
    every item CHECK. Unreadable session-0 processes (services, S4U tasks) are listed, not blocking.
    'ignore': report the unreadable processes but do not let them affect verdicts (fixture tests).
.EXAMPLE
    .\scripts\ops\workstation_space_report.ps1 -JsonPath C:\wt\space-report.json
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string[]]$ScratchRoots = @(),
    [double]$IdleHours = 24,
    [long]$MaxEntriesPerItem = 200000,
    [int]$MaxTotalSeconds = 600,
    [string]$JsonPath = "",
    [string[]]$OnlyPaths = @(),
    [ValidateSet('check', 'ignore')][string]$UnreadableProcessPolicy = 'check',
    [switch]$IncludeWorktreeData,
    [switch]$PassThru
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if (-not $RepoRoot) { $RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }
if (@($ScratchRoots).Count -eq 0) {
    $ScratchRoots = @('C:\wt', 'C:\pt', 'C:\swarm', 'C:\tmp', 'C:\bt',
        (Join-Path ([System.IO.Path]::GetTempPath()) 'claude'))
}
try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch { }

$BenignIgnoredNames = @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.hypothesis',
    'htmlcov', 'node_modules', 'venv', '.venv')
$BenignIgnoredLeafPatterns = @('*.egg-info', '*.pyc', '*.pyo', '.coverage')
$RelevantProcessNames = @('python.exe', 'pythonw.exe', 'git.exe', 'powershell.exe', 'pwsh.exe', 'cmd.exe',
    'bash.exe', 'sh.exe', 'node.exe', 'claude.exe', 'codex.exe', 'chatgpt.exe', 'code.exe', 'pytest.exe')

if (-not ('SpaceReportNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;

public class SpaceWalkResult {
    public long Bytes; public long Files; public long Dirs; public long Denied;
    public DateTime MaxWriteUtc = DateTime.MinValue;
    public bool Truncated; public bool DeadlineHit;
    public long ReparseCount; public List<string> Reparse = new List<string>();
    public long GitMarkerCount; public List<string> GitMarkers = new List<string>();
    public List<string> Stopped = new List<string>(); public List<string> Skipped = new List<string>();
}

public static class SpaceReportNative {
    // Bounded, iterative walk. Never follows a reparse point (it is counted, not entered).
    public static SpaceWalkResult Walk(string root, string[] skipTopNames, string[] stopAt,
                                       long maxEntries, DateTime deadlineUtc, bool gitMarkerAtTop) {
        SpaceWalkResult r = new SpaceWalkResult();
        HashSet<string> stop = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string s in stopAt) stop.Add(s.TrimEnd('\\'));
        HashSet<string> skip = new HashSet<string>(skipTopNames, StringComparer.OrdinalIgnoreCase);
        DirectoryInfo rootInfo = new DirectoryInfo(root);
        r.MaxWriteUtc = rootInfo.LastWriteTimeUtc;
        Stack<KeyValuePair<DirectoryInfo, int>> stack = new Stack<KeyValuePair<DirectoryInfo, int>>();
        stack.Push(new KeyValuePair<DirectoryInfo, int>(rootInfo, 0));
        long entries = 0;
        while (stack.Count > 0) {
            KeyValuePair<DirectoryInfo, int> cur = stack.Pop();
            try {
                foreach (FileSystemInfo fi in cur.Key.EnumerateFileSystemInfos()) {
                    entries++;
                    if (entries > maxEntries) { r.Truncated = true; return r; }
                    if ((entries & 255) == 0 && DateTime.UtcNow > deadlineUtc) {
                        r.Truncated = true; r.DeadlineHit = true; return r;
                    }
                    DateTime lw = fi.LastWriteTimeUtc;
                    if (lw > r.MaxWriteUtc) r.MaxWriteUtc = lw;
                    if (fi.Name == ".git" && (cur.Value > 0 || gitMarkerAtTop)) {
                        r.GitMarkerCount++; if (r.GitMarkers.Count < 5) r.GitMarkers.Add(fi.FullName);
                    }
                    if ((fi.Attributes & FileAttributes.ReparsePoint) != 0) {
                        r.ReparseCount++; if (r.Reparse.Count < 5) r.Reparse.Add(fi.FullName);
                        continue;
                    }
                    if ((fi.Attributes & FileAttributes.Directory) != 0) {
                        if (cur.Value == 0 && skip.Contains(fi.Name)) { r.Skipped.Add(fi.FullName); continue; }
                        if (stop.Contains(fi.FullName.TrimEnd('\\'))) { r.Stopped.Add(fi.FullName); continue; }
                        r.Dirs++;
                        stack.Push(new KeyValuePair<DirectoryInfo, int>((DirectoryInfo)fi, cur.Value + 1));
                    } else {
                        r.Files++; r.Bytes += ((FileInfo)fi).Length;
                    }
                }
            } catch (UnauthorizedAccessException) { r.Denied++; }
              catch (IOException) { r.Denied++; }
        }
        return r;
    }

    // Removes a tree it has fully inspected. Refuses when any reparse point or unreadable folder
    // exists, and re-checks every entry while deleting so a junction is never entered.
    public static long RemoveTree(string root) {
        DirectoryInfo rootInfo = new DirectoryInfo(root);
        if ((rootInfo.Attributes & FileAttributes.ReparsePoint) != 0)
            throw new InvalidOperationException("the item itself is a reparse point");
        SpaceWalkResult pre = Walk(root, new string[0], new string[0], long.MaxValue, DateTime.MaxValue, true);
        if (pre.ReparseCount > 0) throw new InvalidOperationException("reparse point inside: " + pre.Reparse[0]);
        if (pre.Denied > 0) throw new InvalidOperationException("unreadable folder inside");
        long removed = 0;
        DeleteDir(rootInfo, ref removed);
        return removed;
    }

    static void DeleteDir(DirectoryInfo d, ref long removed) {
        foreach (FileSystemInfo fi in d.GetFileSystemInfos()) {
            if ((fi.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("reparse point appeared: " + fi.FullName);
            if ((fi.Attributes & FileAttributes.Directory) != 0) {
                DeleteDir((DirectoryInfo)fi, ref removed);
            } else {
                if ((fi.Attributes & FileAttributes.ReadOnly) != 0) fi.Attributes = FileAttributes.Normal;
                fi.Delete(); removed++;
            }
        }
        if ((d.Attributes & FileAttributes.ReadOnly) != 0) d.Attributes = FileAttributes.Directory;
        d.Delete(false); removed++;
    }

    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(int access, bool inherit, int pid);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll")] static extern bool IsWow64Process(IntPtr h, out bool wow);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, IntPtr size, out IntPtr read);
    [DllImport("ntdll.dll")] static extern int NtQueryInformationProcess(IntPtr h, int cls, ref Pbi info, int len, out int retLen);
    [StructLayout(LayoutKind.Sequential)]
    struct Pbi { public IntPtr R1; public IntPtr Peb; public IntPtr R2a; public IntPtr R2b; public IntPtr Pid; public IntPtr R3; }

    // A process's current directory (64-bit, same-user, unelevated), or null when it cannot be read.
    public static string GetCwd(int pid) {
        if (IntPtr.Size != 8) return null;
        IntPtr h = OpenProcess(0x0410, false, pid);
        if (h == IntPtr.Zero) return null;
        try {
            bool wow;
            if (IsWow64Process(h, out wow) && wow) return null;
            Pbi pbi = new Pbi(); int rl;
            if (NtQueryInformationProcess(h, 0, ref pbi, Marshal.SizeOf(pbi), out rl) != 0) return null;
            byte[] p = new byte[8]; IntPtr n;
            if (!ReadProcessMemory(h, pbi.Peb + 0x20, p, (IntPtr)8, out n)) return null;
            IntPtr pp = (IntPtr)BitConverter.ToInt64(p, 0);
            if (pp == IntPtr.Zero) return null;
            byte[] us = new byte[16];
            if (!ReadProcessMemory(h, pp + 0x38, us, (IntPtr)16, out n)) return null;
            int len = BitConverter.ToUInt16(us, 0);
            IntPtr buf = (IntPtr)BitConverter.ToInt64(us, 8);
            if (len == 0 || buf == IntPtr.Zero) return null;
            byte[] s = new byte[len];
            if (!ReadProcessMemory(h, buf, s, (IntPtr)len, out n)) return null;
            return System.Text.Encoding.Unicode.GetString(s);
        } finally { CloseHandle(h); }
    }
}
'@
}

function ConvertTo-NormalPath([string]$Path) {
    if (-not $Path) { return '' }
    $p = $Path.Replace('/', '\')
    try { $p = [System.IO.Path]::GetFullPath($p) } catch { }
    if ($p.Length -gt 3) { $p = $p.TrimEnd('\') }
    return $p
}

function Test-PathUnder([string]$Candidate, [string]$Root) {
    if (-not $Candidate) { return $false }
    $c = $Candidate.Replace('/', '\').TrimEnd('\')
    return $c.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or
        $c.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Invoke-Git([string[]]$Arguments) {
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $out = & git @Arguments 2>$null; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $old }
    return [pscustomobject]@{ Code = $code; Lines = @($out | ForEach-Object { [string]$_ }) }
}

function Get-ProcessTable {
    $rows = New-Object System.Collections.Generic.List[object]
    $unreadable = New-Object System.Collections.Generic.List[string]
    $serviceSession = New-Object System.Collections.Generic.List[string]
    foreach ($p in @(Get-CimInstance Win32_Process)) {
        $procId = [int]$p.ProcessId
        if ($procId -le 4) { continue }
        $cwd = $null
        try { $cwd = [SpaceReportNative]::GetCwd($procId) } catch { $cwd = $null }
        $name = [string]$p.Name
        if (-not $cwd -and $RelevantProcessNames -contains $name.ToLowerInvariant() -and
            $null -ne (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
            # Session 0 holds services and S4U scheduled tasks, whose paths are repository-owned and
            # fixed; agent sessions run interactively. An unreadable interactive process (for
            # example an elevated shell) is an unknown that blocks SAFE.
            if ([int]$p.SessionId -eq 0) { $serviceSession.Add(('{0} ({1})' -f $name, $procId)) }
            else { $unreadable.Add(('{0} ({1})' -f $name, $procId)) }
        }
        $rows.Add([pscustomobject]@{ Pid = $procId; Name = $name; Cwd = $cwd
            Exe = [string]$p.ExecutablePath; CommandLine = [string]$p.CommandLine })
    }
    return [pscustomobject]@{ Rows = $rows; Unreadable = $unreadable.ToArray(); ServiceSession = $serviceSession.ToArray() }
}

function Find-ProcessesUnder([string]$Path, $Table) {
    $hits = @()
    $pattern = '(?i)' + [regex]::Escape($Path) + '(?:\\|"|''|\s|$)'
    foreach ($row in $Table.Rows) {
        $via = @()
        if (Test-PathUnder $row.Cwd $Path) { $via += 'cwd' }
        if (Test-PathUnder $row.Exe $Path) { $via += 'exe' }
        if ($row.CommandLine -and ($row.CommandLine.Replace('/', '\') -match $pattern)) { $via += 'cmdline' }
        if ($via.Count -gt 0) { $hits += [pscustomobject]@{ pid = $row.Pid; name = $row.Name; via = ($via -join ',') } }
    }
    return @($hits)
}

function Get-WorktreeEntries([string]$Root) {
    $result = Invoke-Git @('-C', $Root, 'worktree', 'list', '--porcelain')
    if ($result.Code -ne 0) { throw "git worktree list failed for $Root" }
    $entries = @(); $cur = $null
    foreach ($line in $result.Lines + @('')) {
        if ($line -eq '') { if ($cur) { $entries += [pscustomobject]$cur; $cur = $null }; continue }
        if ($line.StartsWith('worktree ')) {
            $cur = [ordered]@{ path = (ConvertTo-NormalPath $line.Substring(9)); head = $null; branch = $null
                detached = $false; bare = $false; locked = $false; lock_reason = $null; prunable = $false }
        } elseif ($null -eq $cur) { continue }
        elseif ($line.StartsWith('HEAD ')) { $cur.head = $line.Substring(5) }
        elseif ($line.StartsWith('branch ')) { $cur.branch = $line.Substring(7) -replace '^refs/heads/', '' }
        elseif ($line -eq 'detached') { $cur.detached = $true }
        elseif ($line -eq 'bare') { $cur.bare = $true }
        elseif ($line -eq 'locked' -or $line.StartsWith('locked ')) {
            $cur.locked = $true; if ($line.Length -gt 7) { $cur.lock_reason = $line.Substring(7) } }
        elseif ($line -eq 'prunable' -or $line.StartsWith('prunable ')) { $cur.prunable = $true }
    }
    return @($entries)
}

function Test-BenignIgnored([string]$Entry) {
    $parts = @($Entry.Trim('"').TrimEnd('/').Split('/') | Where-Object { $_ })
    foreach ($part in $parts) { if ($BenignIgnoredNames -contains $part) { return $true } }
    if ($parts.Count -gt 0) {
        foreach ($pat in $BenignIgnoredLeafPatterns) { if ($parts[-1] -like $pat) { return $true } }
    }
    return $false
}

function Get-WorktreeGitDir([string]$Path) {
    $dotGit = Join-Path $Path '.git'
    if (Test-Path -LiteralPath $dotGit -PathType Container) { return $dotGit }
    if (Test-Path -LiteralPath $dotGit -PathType Leaf) {
        $line = [System.IO.File]::ReadAllText($dotGit).Trim()
        if ($line.StartsWith('gitdir:')) { return ConvertTo-NormalPath ($line.Substring(7).Trim()) }
    }
    return $null
}

function Get-IdleHours([datetime]$LastUtc) {
    if ($LastUtc -eq [datetime]::MinValue) { return $null }
    return [math]::Round(([datetime]::UtcNow - $LastUtc).TotalHours, 1)
}

function New-ItemRecord([string]$Kind, [string]$Path) {
    return [ordered]@{ kind = $Kind; path = $Path; verdict = $null; reasons = @(); size_bytes = $null
        size_complete = $false; entries = $null; last_write_utc = $null; idle_hours = $null
        processes = @(); handles = 'not-checked'; recursive = $false }
}

function Set-WalkFields($Record, $Walk) {
    $Record.size_bytes = $Walk.Bytes
    $Record.entries = $Walk.Files + $Walk.Dirs
    $Record.size_complete = (-not $Walk.Truncated) -and ($Walk.Denied -eq 0)
}

function Complete-Verdict($Record, [string[]]$InUse, [string[]]$Check) {
    $Record.reasons = @($InUse) + @($Check)
    if (@($InUse).Count -gt 0) { $Record.verdict = 'IN USE' }
    elseif (@($Check).Count -gt 0) { $Record.verdict = 'CHECK' }
    else { $Record.verdict = 'SAFE'; $Record.reasons = @('pushed or not a worktree; idle; no process; fully inspected') }
}

$startUtc = [datetime]::UtcNow
$deadlineUtc = $startUtc.AddSeconds($MaxTotalSeconds)
$RepoRoot = ConvertTo-NormalPath $RepoRoot
$rootsNormal = @($ScratchRoots | ForEach-Object { ConvertTo-NormalPath $_ })
$onlyNormal = @($OnlyPaths | Where-Object { $_ } | ForEach-Object { ConvertTo-NormalPath $_ })
function Test-Wanted([string]$Path) {
    if ($onlyNormal.Count -eq 0) { return $true }
    foreach ($o in $onlyNormal) { if ($o.Equals($Path, [StringComparison]::OrdinalIgnoreCase)) { return $true } }
    return $false
}

$worktreeSkip = if ($IncludeWorktreeData) { @() } else { @('data') }
$worktrees = @(Get-WorktreeEntries $RepoRoot)
$worktreePaths = @($worktrees | ForEach-Object { $_.path })
$mainPath = if ($worktrees.Count -gt 0) { $worktrees[0].path } else { $RepoRoot }
$remoteCommits = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$revList = Invoke-Git @('-C', $RepoRoot, 'rev-list', '--remotes=origin')
foreach ($sha in $revList.Lines) { if ($sha) { [void]$remoteCommits.Add($sha.Trim()) } }
$commonDir = (Invoke-Git @('-C', $RepoRoot, 'rev-parse', '--path-format=absolute', '--git-common-dir')).Lines | Select-Object -First 1
$fetchHead = if ($commonDir) { Join-Path (ConvertTo-NormalPath $commonDir) 'FETCH_HEAD' } else { $null }
$lastFetchUtc = $null
if ($fetchHead -and (Test-Path -LiteralPath $fetchHead)) {
    $lastFetchUtc = (Get-Item -LiteralPath $fetchHead).LastWriteTimeUtc.ToString('o')
}

$processes = Get-ProcessTable
$processStatus = if (@($processes.Unreadable).Count -eq 0) { 'complete' } else { 'partial' }
$globalCheck = @()
if ($processStatus -ne 'complete' -and $UnreadableProcessPolicy -eq 'check') {
    $globalCheck += ('process table partial: cannot read {0}' -f ((@($processes.Unreadable) | Select-Object -First 5) -join ', '))
}

$items = New-Object System.Collections.Generic.List[object]

foreach ($wt in $worktrees) {
    if (-not (Test-Wanted $wt.path)) { continue }
    $rec = New-ItemRecord 'worktree' $wt.path
    foreach ($k in @('head', 'branch', 'detached', 'locked', 'lock_reason', 'prunable')) { $rec[$k] = $wt.$k }
    $rec.pushed = ($null -ne $wt.head) -and $remoteCommits.Contains([string]$wt.head)
    $rec.dirty = $null; $rec.ignored_not_cache = @()
    $inUse = @(); $check = @() + $globalCheck
    if ($wt.path.Equals($mainPath, [StringComparison]::OrdinalIgnoreCase)) {
        $rec.kind = 'main-worktree'
        $check += 'main working tree: never removed (not walked)'
    }
    if ($wt.locked) { $inUse += ('locked' + $(if ($wt.lock_reason) { ': ' + $wt.lock_reason } else { '' })) }
    if ($wt.prunable -or -not (Test-Path -LiteralPath $wt.path)) {
        $check += 'prunable: folder is missing; git worktree prune is an owner decision'
        Complete-Verdict $rec $inUse $check; $items.Add([pscustomobject]$rec); continue
    }
    if ($wt.bare) { $check += 'bare repository entry' }
    if (-not $rec.pushed) { $check += 'HEAD is not reachable from any origin ref (unpushed)' }
    $hits = @(Find-ProcessesUnder $wt.path $processes)
    $rec.processes = $hits
    if ($hits.Count -gt 0) { $inUse += ('process inside: ' + (($hits | ForEach-Object { '{0} {1} ({2})' -f $_.name, $_.pid, $_.via }) -join '; ')) }
    $lastUtc = [datetime]::MinValue
    $gitDir = Get-WorktreeGitDir $wt.path
    if ($gitDir) {
        foreach ($rel in @('index', 'HEAD', 'logs\HEAD')) {
            $f = Join-Path $gitDir $rel
            if (Test-Path -LiteralPath $f) { $t = (Get-Item -LiteralPath $f).LastWriteTimeUtc; if ($t -gt $lastUtc) { $lastUtc = $t } }
        }
    }
    if ($rec.kind -eq 'worktree') {
        $status = Invoke-Git @('-c', 'core.quotepath=off', '--no-optional-locks', '-C', $wt.path, 'status', '--porcelain=v1', '--ignored')
        if ($status.Code -ne 0) { $check += 'git status failed' }
        else {
            $changes = @($status.Lines | Where-Object { $_ -and -not $_.StartsWith('!! ') })
            $rec.dirty = $changes.Count -gt 0
            if ($rec.dirty) { $check += ('uncommitted or untracked changes: {0}' -f $changes.Count) }
            $ignored = @($status.Lines | Where-Object { $_ -and $_.StartsWith('!! ') } | ForEach-Object { $_.Substring(3) } |
                Where-Object { -not (Test-BenignIgnored $_) })
            $rec.ignored_not_cache = @($ignored | Select-Object -First 10)
            if ($ignored.Count -gt 0) { $check += ('ignored files that are not caches: ' + (($ignored | Select-Object -First 5) -join ', ')) }
        }
        if ([datetime]::UtcNow -gt $deadlineUtc) {
            $check += 'not walked: run time budget spent'
        } else {
            $walk = [SpaceReportNative]::Walk($wt.path, [string[]]$worktreeSkip, [string[]]@($worktreePaths | Where-Object { $_ -ne $wt.path }),
                $MaxEntriesPerItem, $deadlineUtc, $false)
            Set-WalkFields $rec $walk
            $rec.size_excludes = @($walk.Skipped)
            if ($walk.MaxWriteUtc -gt $lastUtc) { $lastUtc = $walk.MaxWriteUtc }
            if ($walk.Truncated) { $check += 'walk truncated (entry cap or time budget): contents not fully inspected' }
            if ($walk.Denied -gt 0) { $check += ('unreadable folders inside: {0}' -f $walk.Denied) }
            if ($walk.ReparseCount -gt 0) { $check += ('reparse point inside (not followed): ' + ($walk.Reparse -join ', ')) }
            if ($walk.Stopped.Count -gt 0) { $check += ('contains other worktree(s): ' + ($walk.Stopped -join ', ')) }
            if ($walk.GitMarkerCount -gt 0) { $check += ('contains a nested repository: ' + ($walk.GitMarkers -join ', ')) }
        }
    }
    if ($lastUtc -ne [datetime]::MinValue) { $rec.last_write_utc = $lastUtc.ToString('o') }
    $rec.idle_hours = Get-IdleHours $lastUtc
    if ($null -eq $rec.idle_hours) { $check += 'last write time unknown' }
    elseif ($rec.idle_hours -lt $IdleHours) { $inUse += ('written {0} h ago (< {1} h)' -f $rec.idle_hours, $IdleHours) }
    Complete-Verdict $rec $inUse $check
    $items.Add([pscustomobject]$rec)
}

$rootSummaries = New-Object System.Collections.Generic.List[object]
foreach ($root in $rootsNormal) {
    $summary = [ordered]@{ path = $root; exists = (Test-Path -LiteralPath $root -PathType Container); folders = 0
        loose_files = 0; loose_bytes = 0 }
    if (-not $summary.exists) { $rootSummaries.Add([pscustomobject]$summary); continue }
    foreach ($child in @(Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue)) {
        if (-not $child.PSIsContainer) { $summary.loose_files++; $summary.loose_bytes += $child.Length; continue }
        $summary.folders++
        $path = ConvertTo-NormalPath $child.FullName
        if ($worktreePaths -contains $path) { continue }   # reported as a worktree above
        if (-not (Test-Wanted $path)) { continue }
        $rec = New-ItemRecord 'folder' $path
        $rec.root = $root
        $inUse = @(); $check = @() + $globalCheck
        $hits = @(Find-ProcessesUnder $path $processes)
        $rec.processes = $hits
        if ($hits.Count -gt 0) { $inUse += ('process inside: ' + (($hits | ForEach-Object { '{0} {1} ({2})' -f $_.name, $_.pid, $_.via }) -join '; ')) }
        $lastUtc = $child.LastWriteTimeUtc
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $rec.kind = 'reparse'
            $check += 'the folder is a reparse point (junction or link); its target is not inspected'
        } elseif ([datetime]::UtcNow -gt $deadlineUtc) {
            $check += 'not walked: run time budget spent'
        } else {
            $walk = [SpaceReportNative]::Walk($path, [string[]]@(), [string[]]$worktreePaths, $MaxEntriesPerItem, $deadlineUtc, $true)
            Set-WalkFields $rec $walk
            if ($walk.MaxWriteUtc -gt $lastUtc) { $lastUtc = $walk.MaxWriteUtc }
            if ($walk.Truncated) { $check += 'walk truncated (entry cap or time budget): contents not fully inspected' }
            if ($walk.Denied -gt 0) { $check += ('unreadable folders inside: {0}' -f $walk.Denied) }
            if ($walk.ReparseCount -gt 0) { $check += ('reparse point inside (not followed): ' + ($walk.Reparse -join ', ')) }
            if ($walk.Stopped.Count -gt 0) { $check += ('contains git worktree(s): ' + ($walk.Stopped -join ', ')) }
            if ($walk.GitMarkerCount -gt 0) { $check += ('contains a git repository: ' + ($walk.GitMarkers -join ', ')) }
        }
        $rec.last_write_utc = $lastUtc.ToString('o')
        $rec.idle_hours = Get-IdleHours $lastUtc
        if ($rec.idle_hours -lt $IdleHours) { $inUse += ('written {0} h ago (< {1} h)' -f $rec.idle_hours, $IdleHours) }
        Complete-Verdict $rec $inUse $check
        $items.Add([pscustomobject]$rec)
    }
    $rootSummaries.Add([pscustomobject]$summary)
}

$report = [pscustomobject][ordered]@{
    schema = 'workstation_space_report_v1'
    generated_utc = $startUtc.ToString('o')
    computer = $env:COMPUTERNAME
    repo_root = $RepoRoot
    scratch_roots = $rootsNormal
    idle_hours = $IdleHours
    max_entries_per_item = $MaxEntriesPerItem
    origin_refs_as_of_fetch_utc = $lastFetchUtc
    process_check = [ordered]@{ status = $processStatus; policy = $UnreadableProcessPolicy
        unreadable = @($processes.Unreadable); unreadable_session0 = @($processes.ServiceSession) }
    handle_check = 'not-checked: open-handle enumeration needs elevation; the clean script re-checks and Windows refuses to delete open files'
    elapsed_seconds = [math]::Round(([datetime]::UtcNow - $startUtc).TotalSeconds, 1)
    roots = $rootSummaries.ToArray()
    items = $items.ToArray()
    totals = [ordered]@{}
}
foreach ($v in @('SAFE', 'IN USE', 'CHECK')) {
    $sel = @($items | Where-Object { $_.verdict -eq $v })
    [long]$bytes = 0
    foreach ($s in $sel) { if ($null -ne $s.size_bytes) { $bytes += [long]$s.size_bytes } }
    $report.totals[$v] = [ordered]@{ count = $sel.Count; bytes = $bytes }
}

if ($JsonPath) {
    $dir = Split-Path -Parent $JsonPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText($JsonPath, ($report | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
}

if ($PassThru) { return $report }

$items | Sort-Object @{ Expression = { @('SAFE', 'CHECK', 'IN USE').IndexOf($_.verdict) } }, @{ Expression = { -1 * [double]$(if ($_.size_bytes) { $_.size_bytes } else { 0 }) } } |
    Format-Table -AutoSize -Wrap @(
        @{ Label = 'Verdict'; Expression = { $_.verdict } },
        @{ Label = 'Kind'; Expression = { $_.kind } },
        @{ Label = 'GiB'; Expression = { if ($null -ne $_.size_bytes) { '{0:N2}{1}' -f ($_.size_bytes / 1GB), $(if ($_.size_complete) { '' } else { '+' }) } else { '?' } } },
        @{ Label = 'IdleH'; Expression = { $_.idle_hours } },
        @{ Label = 'Path'; Expression = { $_.path } },
        @{ Label = 'Reason'; Expression = { ($_.reasons | Select-Object -First 2) -join ' | ' } }
    ) | Out-String -Width 220
foreach ($v in @('SAFE', 'IN USE', 'CHECK')) {
    '{0,-7} {1,4} items  {2,8:N2} GiB' -f $v, $report.totals[$v].count, ($report.totals[$v].bytes / 1GB)
}
'process check: {0} (policy {1}); open handles: not checked; origin refs as of {2}; {3} s' -f $processStatus, $UnreadableProcessPolicy, $lastFetchUtc, $report.elapsed_seconds
if ($JsonPath) { "JSON: $JsonPath" }
