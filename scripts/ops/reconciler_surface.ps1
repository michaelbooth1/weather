# Reconciler test surface (L5, owner decision 2026-10-06).
#
# tests/operations/test_production_baseline_reconciler_execution.py is the bounded
# suite's most expensive file (~19 min). It only needs to run when a tip touches
# what it exercises. This library derives that surface from the test file itself
# and decides, per tip, whether the suite includes it.
#
# Surface = the test file and its local test helpers
#         + every scripts/ops/*.ps1 the test file names (as a path literal or as
#           "scripts" / "ops" / "<name>.ps1" segments)
#         + the transitive closure of scripts/ops/*.ps1 those scripts name
#           (dot-sourcing, Join-Path, child invocations)
#         + a floor that is always present: quiet_window_merge.ps1,
#           production_baseline_scheduler_rpc.ps1, workload_admission.ps1 and the
#           integration-attempt scripts (*integration_attempt*.ps1).
# Any floor file missing, or an empty derivation, throws: the caller must then
# include the reconciler. The predicate can never silently go empty.

Set-StrictMode -Version Latest

$script:WeatherReconcilerTestFile = "tests/operations/test_production_baseline_reconciler_execution.py"
$script:WeatherReconcilerFloor = @(
    "scripts/ops/quiet_window_merge.ps1",
    "scripts/ops/production_baseline_scheduler_rpc.ps1",
    "scripts/ops/workload_admission.ps1"
)

function Get-WeatherReconcilerTestFile { return $script:WeatherReconcilerTestFile }

function Get-WeatherPs1References {
    param([Parameter(Mandatory = $true)][string]$Text)
    $names = New-Object System.Collections.Generic.HashSet[string]
    # Path literals (either slash) and "scripts" / "ops" / "x.ps1" segment chains.
    $patterns = @(
        'scripts[\\/]+ops[\\/]+(?<n>[A-Za-z0-9_.-]+\.ps1)',
        '"scripts"\s*/\s*"ops"\s*/\s*"(?<n>[A-Za-z0-9_.-]+\.ps1)"',
        '["''](?<n>[A-Za-z0-9_.-]+\.ps1)["'']'
    )
    foreach ($pattern in $patterns) {
        foreach ($match in [regex]::Matches($Text, $pattern)) { [void]$names.Add($match.Groups["n"].Value) }
    }
    return @($names)
}

function Get-WeatherReconcilerSurface {
    param([Parameter(Mandatory = $true)][string]$Root)
    $ops = Join-Path $Root "scripts\ops"
    $testPath = Join-Path $Root ($script:WeatherReconcilerTestFile.Replace("/", "\"))
    if (-not (Test-Path -LiteralPath $testPath -PathType Leaf)) {
        throw "reconciler surface: test file is missing: $($script:WeatherReconcilerTestFile)"
    }
    $surface = New-Object System.Collections.Generic.HashSet[string]
    [void]$surface.Add($script:WeatherReconcilerTestFile)
    # Local test helpers the file imports (from tests.x import ...).
    $testText = [IO.File]::ReadAllText($testPath)
    foreach ($match in [regex]::Matches($testText, '(?m)^\s*from\s+(?<m>tests(?:\.[A-Za-z0-9_]+)+)\s+import')) {
        $relative = ($match.Groups["m"].Value -replace '\.', '/') + ".py"
        if (Test-Path -LiteralPath (Join-Path $Root $relative.Replace("/", "\")) -PathType Leaf) {
            [void]$surface.Add($relative)
        }
    }
    $pending = New-Object System.Collections.Generic.Queue[string]
    foreach ($name in (Get-WeatherPs1References -Text $testText)) { $pending.Enqueue($name) }
    foreach ($floor in $script:WeatherReconcilerFloor) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $floor.Replace("/", "\")) -PathType Leaf)) {
            throw "reconciler surface: floor file is missing: $floor"
        }
        $pending.Enqueue(($floor -split "/")[-1])
    }
    $attemptScripts = @(Get-ChildItem -LiteralPath $ops -Filter "*integration_attempt*.ps1" -File)
    if ($attemptScripts.Count -eq 0) { throw "reconciler surface: no integration-attempt scripts found" }
    foreach ($item in $attemptScripts) { $pending.Enqueue($item.Name) }
    $seen = New-Object System.Collections.Generic.HashSet[string]
    while ($pending.Count -gt 0) {
        $name = $pending.Dequeue()
        if (-not $seen.Add($name)) { continue }
        $path = Join-Path $ops $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }  # fixture-only names
        [void]$surface.Add("scripts/ops/$name")
        $text = [IO.File]::ReadAllText($path)
        foreach ($next in (Get-WeatherPs1References -Text $text)) { $pending.Enqueue($next) }
        # Python modules the script launches (-m weather.x.y) are on the surface too.
        foreach ($match in [regex]::Matches($text, '(?<![A-Za-z0-9_.])(?<m>weather(?:\.[A-Za-z0-9_]+)+)')) {
            $module = "src/" + ($match.Groups["m"].Value -replace '\.', '/') + ".py"
            if (Test-Path -LiteralPath (Join-Path $Root $module.Replace("/", "\")) -PathType Leaf) {
                [void]$surface.Add($module)
            }
        }
    }
    $result = @($surface | Sort-Object)
    if ($result.Count -lt ($script:WeatherReconcilerFloor.Count + 1)) {
        throw "reconciler surface: derivation is implausibly small ($($result.Count) paths)"
    }
    return $result
}

function Get-WeatherReconcilerDecision {
    # Returns [pscustomobject]@{ Include; Reason; Touched; SurfaceCount }.
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$ChangedPaths,
        [switch]$Force
    )
    if ($Force) {
        return [pscustomobject]@{ Include = $true; Reason = "forced (-IncludeReconciler)"; Touched = @(); SurfaceCount = $null }
    }
    $surface = Get-WeatherReconcilerSurface -Root $Root
    $changed = @($ChangedPaths | ForEach-Object { ([string]$_).Replace("\", "/") } | Where-Object { $_ })
    $touched = @($changed | Where-Object { $surface -contains $_ })
    if ($touched.Count -gt 0) {
        return [pscustomobject]@{ Include = $true; Reason = "surface touched"; Touched = $touched; SurfaceCount = $surface.Count }
    }
    return [pscustomobject]@{ Include = $false; Reason = "no surface path changed"; Touched = @(); SurfaceCount = $surface.Count }
}
