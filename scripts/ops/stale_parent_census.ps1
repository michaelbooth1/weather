# Stale-parent census for long-running capture and recorder workers (READ-ONLY).
#
# Run by hand only; never schedule it (scheduling is a separate owner decision).
# For every process whose command line matches a worker pattern it reports pid,
# name, a command-line summary, ParentProcessId, and whether that parent is live.
# A parent counts as LIVE only if a process with that pid exists AND it was
# created no later than the child. A missing pid is DEAD; an existing pid created
# after the child is REUSED (the stale number now names an unrelated process).
# Either way the worker is exposed to a stale-PPID tree kill. Background and the
# option analysis: docs/research/recorder-live-parent-design-2026-11-01/design.md
# (section 4.2 lists this census as the roll-free read-only step).
#
# The script only enumerates Win32_Process once. It terminates nothing, changes no
# scheduled task, and writes nothing except the optional -OutFile.
#
# Usage (repository root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\stale_parent_census.ps1
#   ... -OutFile C:\t\census.json
#   ... -WorkerPatternsJson '{"my_worker":{"match":"my_module\\s+run"}}'
#
# On the capture host, S4U-owned command lines may be hidden from an interactive
# query; `summary.python_rows_without_command_line` counts those so an empty match
# is read as UNKNOWN, not as "no workers".
[CmdletBinding()]
param(
    # Label -> regex, or label -> @{ Match = regex; Exclude = regex }. Replaces the defaults.
    [hashtable]$WorkerPatterns,
    # Same mapping as JSON (usable through -File, which cannot pass a hashtable).
    [string]$WorkerPatternsJson,
    # Image names considered at all. cmd.exe is included for the recorder wrappers.
    [string[]]$ImageNames = @("python.exe", "pythonw.exe", "cmd.exe"),
    [int]$CommandLineSummaryChars = 240,
    [int]$MaxAncestry = 32,
    [string]$OutFile
)
$ErrorActionPreference = "Stop"

# Derived from scripts/ops registrars, the loop command builders in src/weather and
# the design doc's section 1. Host loops are matched on module PLUS subcommand so the
# short-lived `ensure` / `thin_ensure` interpreters and per-cycle hot-capture children
# are not counted as the worker.
$defaultPatterns = [ordered]@{
    clob_book_loop            = @{ Match = 'weather\.market\.market_microstructure\s+loop\b'; Exclude = 'hot_capture|--expected-runtime-fingerprint|result\.json' }
    snapshot_loop             = @{ Match = 'weather\.collection\.snapshot_tracker\s+--loop\b'; Exclude = 'hot_capture|--expected-runtime-fingerprint|result\.json' }
    observation_trigger_loop  = @{ Match = 'weather\.operations\.observation_trigger\s+loop\b'; Exclude = 'hot_capture|--expected-runtime-fingerprint|result\.json' }
    execution_tape_supervisor = @{ Match = 'weather\.operations\.execution_tape_supervisor\s+run\b'; Exclude = '' }
    maker_shadow              = @{ Match = 'weather\.market\.maker_shadow\s+run\b'; Exclude = '' }
    maker_evidence            = @{ Match = 'weather\.market\.maker_evidence_capture\b'; Exclude = '--family|--dry-run' }
    maker_evidence_family     = @{ Match = 'weather\.market\.maker_evidence_capture\b.*--family'; Exclude = '--dry-run' }
    ws_forward_recorder       = @{ Match = '[\w-]+_forward_recorder\.py'; Exclude = '' }
}

function ConvertTo-PatternTable {
    param($Source)
    $table = [ordered]@{}
    $entries = if ($Source -is [System.Collections.IDictionary]) {
        @($Source.Keys | ForEach-Object { [pscustomobject]@{ Name = [string]$_; Value = $Source[$_] } })
    }
    else {
        @($Source.PSObject.Properties | ForEach-Object { [pscustomobject]@{ Name = [string]$_.Name; Value = $_.Value } })
    }
    foreach ($entry in $entries) {
        $value = $entry.Value
        $match = ""; $exclude = ""
        if ($value -is [string]) { $match = $value }
        elseif ($value -is [System.Collections.IDictionary]) {
            foreach ($k in $value.Keys) {
                if ([string]$k -ieq "match") { $match = [string]$value[$k] }
                elseif ([string]$k -ieq "exclude") { $exclude = [string]$value[$k] }
            }
        }
        else {
            foreach ($p in $value.PSObject.Properties) {
                if ($p.Name -ieq "match") { $match = [string]$p.Value }
                elseif ($p.Name -ieq "exclude") { $exclude = [string]$p.Value }
            }
        }
        if ([string]::IsNullOrWhiteSpace($match)) { throw "Worker pattern '$($entry.Name)' has no match regex." }
        [void][regex]::new($match)
        if ($exclude) { [void][regex]::new($exclude) }
        $table[$entry.Name] = [pscustomobject]@{ Match = $match; Exclude = $exclude }
    }
    if ($table.Count -eq 0) { throw "No worker patterns." }
    return $table
}

if ($WorkerPatterns -and $WorkerPatternsJson) { throw "Pass -WorkerPatterns or -WorkerPatternsJson, not both." }
if ($OutFile) {
    $outParent = Split-Path -Parent ([IO.Path]::GetFullPath($OutFile))
    if (-not (Test-Path -LiteralPath $outParent -PathType Container)) {
        throw "OutFile directory does not exist (the census creates no directories): $outParent"
    }
}
$patternSource = if ($WorkerPatternsJson) { ConvertFrom-Json -InputObject $WorkerPatternsJson }
                 elseif ($WorkerPatterns) { $WorkerPatterns }
                 else { $defaultPatterns }
$patterns = ConvertTo-PatternTable $patternSource
$patternsUsed = if ($WorkerPatternsJson) { "json" } elseif ($WorkerPatterns) { "parameter" } else { "default" }

function Format-Utc {
    param($Value)
    if ($null -eq $Value) { return $null }
    try { return ([datetime]$Value).ToUniversalTime().ToString("o") } catch { return $null }
}

function Get-Summary {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return "" }
    $flat = ($Text -replace '\s+', ' ').Trim()
    if ($flat.Length -le $CommandLineSummaryChars) { return $flat }
    return $flat.Substring(0, $CommandLineSummaryChars) + "..."
}

$rows = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
$byPid = @{}
foreach ($row in $rows) { $byPid[[int64]$row.ProcessId] = $row }
$selfId = [int64]$PID

# Parent verdict for one child row: live | dead | reused | unknown | none.
function Get-ParentVerdict {
    param($Child)
    $ppid = [int64]$Child.ParentProcessId
    if ($ppid -le 0) { return [pscustomobject]@{ Status = "none"; Parent = $null } }
    $parent = $byPid[$ppid]
    if ($null -eq $parent) { return [pscustomobject]@{ Status = "dead"; Parent = $null } }
    if ($null -eq $Child.CreationDate -or $null -eq $parent.CreationDate) {
        return [pscustomobject]@{ Status = "unknown"; Parent = $parent }
    }
    if ([datetime]$parent.CreationDate -le [datetime]$Child.CreationDate) {
        return [pscustomobject]@{ Status = "live"; Parent = $parent }
    }
    return [pscustomobject]@{ Status = "reused"; Parent = $parent }
}

$imageSet = @($ImageNames | ForEach-Object { $_.ToLowerInvariant() })
$pythonWithoutCommandLine = 0
$workers = New-Object System.Collections.Generic.List[object]
foreach ($row in $rows) {
    $name = [string]$row.Name
    if ($imageSet -notcontains $name.ToLowerInvariant()) { continue }
    if ([int64]$row.ProcessId -eq $selfId) { continue }
    $commandLine = [string]$row.CommandLine
    if ([string]::IsNullOrEmpty($commandLine)) {
        if ($name -like "python*") { $pythonWithoutCommandLine++ }
        continue
    }
    if ($commandLine -match 'stale_parent_census') { continue }
    $label = $null
    foreach ($key in $patterns.Keys) {
        $p = $patterns[$key]
        if ($commandLine -match $p.Match -and -not ($p.Exclude -and $commandLine -match $p.Exclude)) { $label = $key; break }
    }
    if ($null -eq $label) { continue }

    $verdict = Get-ParentVerdict $row
    $parentInfo = $null
    if ($null -ne $verdict.Parent) {
        $parentInfo = [ordered]@{
            name = [string]$verdict.Parent.Name
            created_utc = Format-Utc $verdict.Parent.CreationDate
            command_line_summary = Get-Summary ([string]$verdict.Parent.CommandLine)
        }
    }
    # Walk up through live links; the first non-live link is where the chain is exposed.
    $exposed = $null
    $cursor = $row
    $depth = 0
    while ($null -ne $cursor -and $depth -lt $MaxAncestry) {
        $link = Get-ParentVerdict $cursor
        if ($link.Status -ne "live") {
            if ($link.Status -ne "none") {
                $exposed = [ordered]@{
                    pid = [int64]$cursor.ProcessId
                    name = [string]$cursor.Name
                    parent_pid = [int64]$cursor.ParentProcessId
                    parent_status = $link.Status
                    depth = $depth
                }
            }
            break
        }
        if ([int64]$link.Parent.ProcessId -eq [int64]$cursor.ProcessId) { break }
        $cursor = $link.Parent
        $depth++
    }
    $workers.Add([pscustomobject][ordered]@{
        worker = $label
        pid = [int64]$row.ProcessId
        name = $name
        created_utc = Format-Utc $row.CreationDate
        command_line_summary = Get-Summary $commandLine
        parent_pid = [int64]$row.ParentProcessId
        parent_alive = ($verdict.Status -eq "live")
        parent_exists = ($null -ne $verdict.Parent)
        parent_status = $verdict.Status
        parent_created_before_child = if ($null -eq $verdict.Parent -or $verdict.Status -eq "unknown") { $null } else { $verdict.Status -eq "live" }
        parent = $parentInfo
        chain_exposed_link = $exposed
    })
}

$ordered = @($workers | Sort-Object worker, pid)
$byWorker = [ordered]@{}
foreach ($key in $patterns.Keys) {
    $mine = @($ordered | Where-Object { $_.worker -eq $key })
    $byWorker[$key] = [ordered]@{
        processes = $mine.Count
        parent_live = @($mine | Where-Object { $_.parent_status -eq "live" }).Count
        parent_dead = @($mine | Where-Object { $_.parent_status -eq "dead" }).Count
        parent_reused = @($mine | Where-Object { $_.parent_status -eq "reused" }).Count
        parent_unknown = @($mine | Where-Object { $_.parent_status -in @("unknown", "none") }).Count
        chain_exposed = @($mine | Where-Object { $null -ne $_.chain_exposed_link }).Count
    }
}
$stalePpids = @($ordered | Where-Object { $_.parent_status -in @("dead", "reused") } |
    Group-Object parent_pid | Sort-Object { [int64]$_.Name } | ForEach-Object {
        [ordered]@{ parent_pid = [int64]$_.Name; children = $_.Count; workers = @($_.Group | ForEach-Object { $_.worker } | Sort-Object -Unique) }
    })

$report = [ordered]@{
    schema = "weather.stale_parent_census.v1"
    generated_utc = (Get-Date).ToUniversalTime().ToString("o")
    computer = $env:COMPUTERNAME
    read_only = $true
    patterns_source = $patternsUsed
    patterns = $patterns
    summary = [ordered]@{
        processes_scanned = $rows.Count
        worker_processes = $ordered.Count
        parent_live = @($ordered | Where-Object { $_.parent_status -eq "live" }).Count
        parent_dead = @($ordered | Where-Object { $_.parent_status -eq "dead" }).Count
        parent_reused = @($ordered | Where-Object { $_.parent_status -eq "reused" }).Count
        parent_unknown = @($ordered | Where-Object { $_.parent_status -in @("unknown", "none") }).Count
        chain_exposed = @($ordered | Where-Object { $null -ne $_.chain_exposed_link }).Count
        python_rows_without_command_line = $pythonWithoutCommandLine
        stale_parent_pids = $stalePpids
        by_worker = $byWorker
    }
    workers = $ordered
}
$json = ConvertTo-Json -InputObject $report -Depth 8
if ($OutFile) {
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutFile), $json, (New-Object System.Text.UTF8Encoding($false)))
}
$json
exit 0
