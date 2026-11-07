# Read-only qualification boundary. Dot-source and call Assert-WeatherPregateReceipt.
# A process exit code alone never qualifies a head; this performs no deployment.
function Assert-WeatherPregateReceipt {
    param(
        [Parameter(Mandatory=$true)][object]$Receipt,
        [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedHead,
        [Parameter(Mandatory=$true)][int]$ProcessExitCode,
        [Parameter(Mandatory=$true)][DateTimeOffset]$NotBefore
    )
    if ($ProcessExitCode -ne 0 -or $Receipt.schema -cne 'weather.workstation_pregate_receipt.v1' -or
        $Receipt.head -cne $ExpectedHead -or $Receipt.verdict -cne 'PASS' -or
        @($Receipt.failure_reasons).Count -ne 0 -or $Receipt.driver_exit_code -ne 0 -or
        $Receipt.worktree_removed -isnot [bool] -or $Receipt.worktree_removed -ne $true -or
        $Receipt.basetemp_removed -isnot [bool] -or $Receipt.basetemp_removed -ne $true) {
        throw 'pregate qualification refused: status, identity or cleanup'
    }
    $started = [DateTimeOffset]::Parse($Receipt.started_at)
    $finished = [DateTimeOffset]::Parse($Receipt.finished_at)
    if ($started -lt $NotBefore -or $finished -lt $started -or $finished -gt [DateTimeOffset]::UtcNow) {
        throw 'pregate qualification refused: stale or invalid observation time'
    }
    $plan = @($Receipt.chunk_plan)
    $chunks = @($Receipt.chunks)
    $junit = @($Receipt.junit_files)
    if ($plan.Count -lt 1 -or $chunks.Count -ne $plan.Count -or $junit.Count -ne $plan.Count -or
        @($Receipt.junit_paths).Count -ne $plan.Count -or $Receipt.inventory_files -lt 1 -or
        @($Receipt.skipped_host_checks).Count -ne 5) {
        throw 'pregate qualification refused: incomplete chunk evidence'
    }
    $log = [IO.Path]::GetFullPath([string]$Receipt.log_path)
    $root = [IO.Path]::GetDirectoryName($log) + [IO.Path]::DirectorySeparatorChar
    if ((Get-FileHash -LiteralPath $log -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Receipt.log_sha256) {
        throw 'pregate qualification refused: log hash'
    }
    $messages = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($line in [IO.File]::ReadLines($log)) {
        if ($line.Length -gt 21) { [void]$messages.Add($line.Substring(21)) }
    }
    $allPassed = @($messages | Where-Object {
        $_ -cmatch ('^VERDICT: ALL CHUNKS PASSED \(' + $plan.Count + '/' + $plan.Count + '\)')
    }).Count -eq 1
    if (-not $allPassed -or -not $messages.Contains(
        ('planned chunks={0} files={1} max_files={2}' -f $plan.Count,$Receipt.inventory_files,$Receipt.max_files_per_chunk))) {
        throw 'pregate qualification refused: missing full-suite verdict'
    }
    $files = 0
    for ($i=0; $i -lt $plan.Count; $i++) {
        $ordinal = $i+1
        $count = @($plan[$i]).Count
        $files += $count
        $chunk = $chunks[$i]
        $path = [IO.Path]::GetFullPath([string]$junit[$i].path)
        if ($count -lt 1 -or $count -gt 25 -or $chunk.ordinal -ne $ordinal -or
            $chunk.files -ne $count -or $chunk.logged_files -ne $count -or $chunk.exit_code -ne 0 -or
            $path -cne [IO.Path]::GetFullPath([string]$Receipt.junit_paths[$i]) -or
            -not $path.StartsWith($root,[StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetExtension($path) -cne '.xml' -or
            -not $messages.Contains(('chunk {0}/{1} starting files={2} junit={3}' -f $ordinal,$plan.Count,$count,$path)) -or
            -not $messages.Contains(('chunk {0}/{1} exit=0' -f $ordinal,$plan.Count))) {
            throw 'pregate qualification refused: chunk scope'
        }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $junit[$i].sha256) {
            throw 'pregate qualification refused: JUnit hash'
        }
        $settings = [Xml.XmlReaderSettings]::new()
        $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $reader = [Xml.XmlReader]::Create($path,$settings)
        $suites = 0
        try {
            while ($reader.Read()) {
                if ($reader.NodeType -eq [Xml.XmlNodeType]::Element -and $reader.Name -ceq 'testsuite') {
                    $suites++
                    if ([int]$reader.GetAttribute('failures') -ne 0 -or [int]$reader.GetAttribute('errors') -ne 0 -or
                        [int]$reader.GetAttribute('tests') -lt 1) { throw 'pregate qualification refused: failed or empty JUnit' }
                }
            }
        } finally { $reader.Dispose() }
        if ($suites -lt 1) { throw 'pregate qualification refused: missing JUnit suite' }
    }
    if ($files -ne $Receipt.inventory_files) { throw 'pregate qualification refused: inventory coverage' }
    return $true
}
