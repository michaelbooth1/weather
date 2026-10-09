# One-line, read-only readout of the forward maker shadow runner for the owner's check-in.
# Reads only file names, seal JSONs, the embargo windows in src\maker_core\shadow\admission.py,
# the tail (at most 1 MiB) of the newest open tape and,
# when -ParityStartUtc is given, the agreement status of score reports. It writes nothing,
# takes no lease, starts no Python and touches no 88a, panel or settlement data, so it is
# safe at any hour. Contract: docs/operations/maker-shadow-runner.md.
param(
    [string]$RepoRoot = "",
    [string]$ParityStartUtc = ""   # yyyy-MM-dd of the engine freeze; empty = parity clock not started
)
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = "Stop"
$root = Join-Path $RepoRoot "data\maker_shadow"
$tapes = Join-Path $root "tapes"
$todayUtc = [DateTime]::UtcNow.ToString("yyyy-MM-dd")

# Embargo text derived from the window constant in the code this script ships with (never hard-coded).
$codeRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$admission = Join-Path $codeRoot "src\maker_core\shadow\admission.py"
$embargo = "embargo windows unreadable"
if (Test-Path -LiteralPath $admission -PathType Leaf) {
    $windows = @([regex]::Matches((Get-Content -LiteralPath $admission -Raw),
        '\(\s*"(\d{4}-\d{2}-\d{2})",\s*"(\d{4}-\d{2}-\d{2})",\s*(FULL|OUTCOME),'))
    if ($windows.Count) {
        $through = ($windows | ForEach-Object { $_.Groups[2].Value } | Sort-Object)[-1]
        $closed = ($windows | Where-Object { $_.Groups[3].Value -eq "FULL" } |
            ForEach-Object { "{0}..{1}" -f $_.Groups[1].Value, $_.Groups[2].Value }) -join ", "
        $embargo = "88a scoring embargoed through $through UTC; parity outcome-blind, never $closed"
    }
}

$alive = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { [string]$_.CommandLine -match '-m\s+weather\.market\.maker_shadow\s+run' }).Count

$seals = @()
$open = @()
if (Test-Path -LiteralPath $tapes -PathType Container) {
    $seals = @(Get-ChildItem -LiteralPath $tapes -Filter "*.seal.json" -File)
    $sealedNames = @{}
    foreach ($s in $seals) { $sealedNames[$s.Name -replace '\.seal\.json$', '.tape.jsonl'] = $true }
    $open = @(Get-ChildItem -LiteralPath $tapes -Filter "*.tape.jsonl" -File |
        Where-Object { -not $sealedNames.ContainsKey($_.Name) } | Sort-Object LastWriteTimeUtc)
}
$days = @($seals | ForEach-Object { $_.Name.Substring(0, 10) } | Sort-Object -Unique)
$since = if ($days.Count) { $days[0] } else { "none" }

$rowsToday = 0
$bytesToday = 0
foreach ($s in ($seals | Where-Object { $_.Name.StartsWith($todayUtc) })) {
    $seal = Get-Content -LiteralPath $s.FullName -Raw | ConvertFrom-Json
    $rowsToday += [int]$seal.records
    $bytesToday += [long]$seal.bytes
}

# The newest open tape is the live run; older open tapes are crashed runs the scorer never reads.
$last = "none"
$lastAge = "n/a"
$lastState = ""
$code = ""
if ($open.Count) {
    $live = $open[-1]
    $stream = [IO.File]::Open($live.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $take = [Math]::Min($stream.Length, 1MB)
        [void]$stream.Seek(-$take, [IO.SeekOrigin]::End)
        $buffer = New-Object byte[] $take
        $read = 0
        while ($read -lt $take) {
            $n = $stream.Read($buffer, $read, $take - $read)
            if ($n -le 0) { break }
            $read += $n
        }
    }
    finally { $stream.Dispose() }
    # The opening record (first line) carries the code identity the run computed once at start.
    $head = [IO.File]::Open($live.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $headBuffer = New-Object byte[] ([Math]::Min($head.Length, 64KB))
        $headRead = $head.Read($headBuffer, 0, $headBuffer.Length)
    }
    finally { $head.Dispose() }
    $firstLine = [Text.Encoding]::UTF8.GetString($headBuffer, 0, $headRead).Split("`n")[0]
    $code = "; code not recorded"
    try {
        $scope = ($firstLine | ConvertFrom-Json).scope
        if ($scope.PSObject.Properties.Name -contains "git_commit") {
            if ($scope.git_commit) {
                $code = "; code {0}{1}" -f ([string]$scope.git_commit).Substring(0, 12),
                    $(if ($scope.git_dirty -eq $false) { "" } elseif ($scope.git_dirty) { " DIRTY" } else { " dirty-unknown" })
            }
            else { $code = "; code unbound ({0})" -f [string]$scope.git_error }
        }
    }
    catch { $code = "; code unreadable" }
    $lines = @([Text.Encoding]::UTF8.GetString($buffer, 0, $read).Split("`n") | Where-Object { $_.Trim() })
    if ($lines.Count) {
        $row = $lines[-1] | ConvertFrom-Json
        if ($live.Name.StartsWith($todayUtc)) {
            $rowsToday += [int]$row.sequence + 1
            $bytesToday += $live.Length
        }
        $at = [DateTime]::Parse([string]$row.recorded_at_utc).ToUniversalTime()
        $last = $at.ToString("yyyy-MM-ddTHH:mmZ")
        $lastAge = "{0:N0}s ago" -f ([DateTime]::UtcNow - $at).TotalSeconds
        if ($row.event -eq "minute") {
            $unevaluated = @($row.conditions | Where-Object { $_.PSObject.Properties.Name -contains "unevaluated" }).Count
            $lastState = ", last minute: {0} bands, {1} unevaluated, {2} print gaps, guard {3}" -f `
                @($row.conditions).Count, $unevaluated, @($row.paper.print_gaps).Count, [string]$row.guard.action
        }
        else { $lastState = ", last record: $($row.event)" }
    }
}
$crashed = [Math]::Max(0, $open.Count - [int]($alive -gt 0))

if ($ParityStartUtc) {
    $passDays = @()
    $scores = Join-Path $root "scores"
    if (Test-Path -LiteralPath $scores -PathType Container) {
        foreach ($f in (Get-ChildItem -LiteralPath $scores -Filter "*.json" -File)) {
            $day = $f.Name.Substring(0, 10)
            if ($day -lt $ParityStartUtc) { continue }
            $report = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json
            if ([string]$report.agreement.status -eq "PASS") { $passDays += $day }
        }
    }
    $parity = "parity-days PASS since $ParityStartUtc`: $(@($passDays | Sort-Object -Unique).Count)"
}
else { $parity = "parity clock not started (starts at the W1/W2/F3 engine freeze)" }
$flags = @()
if (Test-Path -LiteralPath (Join-Path $root "STOP")) { $flags += "STOP file present" }
if (Test-Path -LiteralPath (Join-Path $root "PAUSE")) { $flags += "PAUSE file present" }
$flagText = if ($flags.Count) { " [" + ($flags -join "; ") + "]" } else { "" }

"shadow: process {0}; sealed days {1} since {2}; last tick {3} ({4}){5}{11}; rows today {6} ({7:N0} MB); crashed/unsealed tapes {8}; {9}; {12}{10}" -f `
    $(if ($alive) { "running" } else { "NOT running" }), $days.Count, $since, $last, $lastAge, $lastState,
    $rowsToday, ($bytesToday / 1MB), $crashed, $parity, $flagText, $code, $embargo
