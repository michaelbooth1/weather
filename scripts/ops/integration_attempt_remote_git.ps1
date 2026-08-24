Set-StrictMode -Version Latest

function ConvertTo-WeatherIntegrationCanonicalOriginUrl {
    param([Parameter(Mandatory = $true)][string]$Url)

    $candidate = $Url.Trim()
    if ($candidate -cnotmatch
        '^https://github\.com/(?<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?<repository>[A-Za-z0-9._-]{1,100})\.git$') {
        throw (
            "Integration origin must use the canonical credential-free GitHub HTTPS " +
            "form https://github.com/<owner>/<repository>.git."
        )
    }
    return (
        "https://github.com/$([string]$Matches.owner)/" +
        "$([string]$Matches.repository).git"
    ).ToLowerInvariant()
}

function Get-WeatherIntegrationCanonicalOriginUrl {
    param([Parameter(Mandatory = $true)][string]$Root)

    $resolvedRoot = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "Integration repository root is missing: $resolvedRoot"
    }
    $git = Get-Command git.exe -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    $rows = @(& ([string]$git.Source) -C $resolvedRoot config --get-all remote.origin.url)
    if ($LASTEXITCODE -ne 0 -or $rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0])) {
        throw "Integration repository must define exactly one origin fetch URL."
    }
    $originUrl = ConvertTo-WeatherIntegrationCanonicalOriginUrl -Url ([string]$rows[0])

    # `git push origin` prefers remote.origin.pushurl over the fetch URL.  URL
    # insteadOf/pushInsteadOf rules can also redirect an apparently canonical
    # command after the manifest has frozen its repository identity.  Reject
    # every effective config scope; a string comparison of remote.origin.url
    # alone is not a transport-identity proof.
    $pushUrls = @(& ([string]$git.Source) -C $resolvedRoot config --get-all remote.origin.pushurl)
    $pushUrlExit = $LASTEXITCODE
    if ($pushUrlExit -notin @(0, 1)) {
        throw "Integration repository push-URL configuration could not be inspected."
    }
    if ($pushUrlExit -eq 0 -or $pushUrls.Count -gt 0) {
        throw "Integration repository must not define remote.origin.pushurl."
    }
    $rewrites = @(& ([string]$git.Source) -C $resolvedRoot config `
        --show-origin --show-scope --get-regexp `
        '^url\..*\.(insteadof|pushinsteadof)$')
    $rewriteExit = $LASTEXITCODE
    if ($rewriteExit -notin @(0, 1)) {
        throw "Integration repository URL-rewrite configuration could not be inspected."
    }
    if ($rewriteExit -eq 0 -or $rewrites.Count -gt 0) {
        throw (
            "Integration repository refuses url.*.insteadOf/pushInsteadOf rules " +
            "because they can redirect the frozen origin identity."
        )
    }
    return $originUrl
}

function Assert-WeatherIntegrationCanonicalOriginUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedUrl,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $expected = ConvertTo-WeatherIntegrationCanonicalOriginUrl -Url $ExpectedUrl
    if ($expected -cne $ExpectedUrl) {
        throw "$Phase expected origin URL is not stored in canonical form."
    }
    $actual = Get-WeatherIntegrationCanonicalOriginUrl -Root $Root
    if ($actual -cne $expected) {
        throw "$Phase origin URL changed after freeze. Expected $expected; got $actual"
    }
    return $actual
}

function ConvertTo-WeatherIntegrationProcessArgumentString {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Tokens
    )

    $encoded = foreach ($token in $Tokens) {
        $value = [string]$token
        if ($value.Contains('"')) {
            throw "Bounded child-process arguments may not contain a double quote."
        }
        if ($value -match '\s') {
            if ($value.EndsWith('\')) {
                throw "A quoted bounded child-process argument may not end in a backslash."
            }
            '"{0}"' -f $value
        }
        elseif ($value.Length -eq 0) { '""' }
        else { $value }
    }
    return ($encoded -join " ")
}

function Invoke-WeatherIntegrationBoundedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 900)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][string]$Label,
        [hashtable]$Environment = @{},
        [string[]]$RemoveEnvironmentVariables = @(),
        [int[]]$AllowedExitCodes = @(0)
    )

    $resolvedWorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
    if (-not (Test-Path -LiteralPath $resolvedWorkingDirectory -PathType Container)) {
        throw "$Label working directory is missing: $resolvedWorkingDirectory"
    }
    $resolvedExecutable = if (Test-Path -LiteralPath $Executable -PathType Leaf) {
        [IO.Path]::GetFullPath($Executable)
    }
    else {
        $command = Get-Command $Executable -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
        [string]$command.Source
    }

    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $resolvedExecutable
    $startInfo.Arguments = ConvertTo-WeatherIntegrationProcessArgumentString `
        -Tokens $Arguments
    $startInfo.WorkingDirectory = $resolvedWorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($name in $RemoveEnvironmentVariables) {
        [void]$startInfo.EnvironmentVariables.Remove([string]$name)
    }
    foreach ($name in $Environment.Keys) {
        $startInfo.EnvironmentVariables[[string]$name] = [string]$Environment[$name]
    }

    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    $stdoutTask = $null
    $stderrTask = $null
    try {
        if (-not $process.Start()) {
            throw "$Label could not start its bounded child process."
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $processId = [int]$process.Id
            $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
            $terminationFailures = New-Object System.Collections.Generic.List[string]
            if (Test-Path -LiteralPath $taskkill -PathType Leaf) {
                $killInfo = New-Object Diagnostics.ProcessStartInfo
                $killInfo.FileName = $taskkill
                $killInfo.Arguments = "/PID $processId /T /F"
                $killInfo.UseShellExecute = $false
                $killInfo.CreateNoWindow = $true
                $killInfo.RedirectStandardOutput = $true
                $killInfo.RedirectStandardError = $true
                $killer = $null
                try {
                    $killer = [Diagnostics.Process]::Start($killInfo)
                    if ($null -eq $killer) {
                        $terminationFailures.Add("taskkill did not return a process handle")
                    }
                    elseif (-not $killer.WaitForExit(10000)) {
                        $terminationFailures.Add("taskkill did not exit within 10 seconds")
                        try { $killer.Kill() } catch {
                            $terminationFailures.Add(
                                "timed-out taskkill could not be stopped: $($_.Exception.Message)"
                            )
                        }
                        if (-not $killer.WaitForExit(2000)) {
                            $terminationFailures.Add("timed-out taskkill remained alive")
                        }
                    }
                    elseif ([int]$killer.ExitCode -ne 0) {
                        $killDiagnostic = (@(
                            [string]$killer.StandardError.ReadToEnd(),
                            [string]$killer.StandardOutput.ReadToEnd()
                        ) | ForEach-Object { $_.Trim() } |
                            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                            Select-Object -First 1)
                        if ([string]::IsNullOrWhiteSpace([string]$killDiagnostic)) {
                            $killDiagnostic = "no taskkill diagnostic output"
                        }
                        if ($killDiagnostic.Length -gt 256) {
                            $killDiagnostic = $killDiagnostic.Substring(0, 256)
                        }
                        $terminationFailures.Add(
                            "taskkill exited $([int]$killer.ExitCode): $killDiagnostic"
                        )
                    }
                }
                catch {
                    $terminationFailures.Add(
                        "taskkill could not be executed: $($_.Exception.Message)"
                    )
                }
                finally {
                    if ($null -ne $killer) { $killer.Dispose() }
                }
            }
            else {
                $terminationFailures.Add("taskkill.exe is missing")
            }
            if (-not $process.HasExited) {
                try { $process.Kill() }
                catch {
                    $terminationFailures.Add(
                        "timed-out parent could not be killed: $($_.Exception.Message)"
                    )
                }
            }
            if (-not $process.WaitForExit(5000) -or -not $process.HasExited) {
                $terminationFailures.Add(
                    "timed-out parent did not prove exit within 5 seconds"
                )
            }
            if ($terminationFailures.Count -gt 0) {
                throw (
                    "$Label timed out after $TimeoutSeconds seconds; child-tree " +
                    "termination could not be proved: $($terminationFailures -join '; ')"
                )
            }
            throw (
                "$Label timed out after $TimeoutSeconds seconds; taskkill and parent-exit " +
                "checks proved its child process tree was terminated."
            )
        }
        # The parameterless wait is required to flush asynchronous redirected
        # output after the process handle becomes signaled.
        $process.WaitForExit()
        $stdout = [string]$stdoutTask.Result
        $stderr = [string]$stderrTask.Result
        $exitCode = [int]$process.ExitCode
        if ($AllowedExitCodes -notcontains $exitCode) {
            $diagnostic = (@($stderr, $stdout) |
                ForEach-Object { ([string]$_).Trim() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Select-Object -First 1)
            if ([string]::IsNullOrWhiteSpace([string]$diagnostic)) {
                $diagnostic = "no child diagnostic output"
            }
            if ($diagnostic.Length -gt 512) { $diagnostic = $diagnostic.Substring(0, 512) }
            throw "$Label failed with exit code ${exitCode}: $diagnostic"
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Stdout = $stdout
            Stderr = $stderr
            StdoutLines = @($stdout -split "`r?`n" | Where-Object { $_ -ne "" })
        }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-WeatherIntegrationBoundedRemoteGit {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$Arguments,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 90,
        [string]$Label = "remote Git operation"
    )

    if ([string]$Arguments[0] -notin @("ls-remote", "fetch", "push")) {
        throw "The bounded remote Git helper accepts only ls-remote, fetch, or push."
    }
    $git = Get-Command git.exe -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    return Invoke-WeatherIntegrationBoundedProcess `
        -Executable ([string]$git.Source) `
        -Arguments (@("-C", ([IO.Path]::GetFullPath($Root))) + $Arguments) `
        -WorkingDirectory ([IO.Path]::GetFullPath($Root)) `
        -TimeoutSeconds $TimeoutSeconds `
        -Label $Label `
        -Environment @{
            GIT_TERMINAL_PROMPT = "0"
            GCM_INTERACTIVE = "Never"
        }
}

function Invoke-WeatherIntegrationCanonicalLsRemote {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedUrl,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string[]]$RemoteRefs,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 90,
        [string]$Label = "canonical remote Git query"
    )

    $canonicalUrl = Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $Root -ExpectedUrl $ExpectedUrl -Phase $Label
    foreach ($remoteRef in $RemoteRefs) {
        if ([string]$remoteRef -cnotmatch '^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,192}$') {
            throw "$Label received an unsafe exact remote ref: $remoteRef"
        }
    }

    # Query the frozen URL outside every repository and without system/global
    # Git configuration. This makes the acknowledgement independent of
    # remote names, pushurl, include files, and URL rewrite rules while keeping
    # the ordinary in-repository checks above as a separate fail-closed gate.
    $queryRoot = Join-Path ([IO.Path]::GetTempPath()) (
        "weather-canonical-ls-remote-" + [Guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $queryRoot -ErrorAction Stop | Out-Null
    try {
        $git = Get-Command git.exe -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
        return Invoke-WeatherIntegrationBoundedProcess `
            -Executable ([string]$git.Source) `
            -Arguments (@("ls-remote", "--heads", $canonicalUrl) + $RemoteRefs) `
            -WorkingDirectory $queryRoot `
            -TimeoutSeconds $TimeoutSeconds `
            -Label $Label `
            -RemoveEnvironmentVariables @(
                "GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS"
            ) `
            -Environment @{
                GIT_TERMINAL_PROMPT = "0"
                GCM_INTERACTIVE = "Never"
                GIT_CONFIG_NOSYSTEM = "1"
                GIT_CONFIG_SYSTEM = "NUL"
                GIT_CONFIG_GLOBAL = "NUL"
                GIT_CONFIG_COUNT = "0"
            }
    }
    finally {
        if (Test-Path -LiteralPath $queryRoot -PathType Container) {
            Remove-Item -LiteralPath $queryRoot -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-WeatherIntegrationCanonicalRemoteTip {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExpectedUrl,
        [Parameter(Mandatory = $true)][string]$RemoteRef,
        [switch]$AllowMissing,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 90,
        [string]$Label = "canonical remote Git ref query"
    )

    $query = Invoke-WeatherIntegrationCanonicalLsRemote `
        -Root $Root -ExpectedUrl $ExpectedUrl -RemoteRefs @($RemoteRef) `
        -TimeoutSeconds $TimeoutSeconds -Label $Label
    $rows = @($query.StdoutLines)
    if ($rows.Count -eq 0 -and $AllowMissing.IsPresent) { return $null }
    if ($rows.Count -ne 1) {
        throw "$Label did not return exactly one remote ref."
    }
    $columns = @(([string]$rows[0]).Trim() -split "`t")
    if ($columns.Count -ne 2 -or
        [string]$columns[0] -cnotmatch '^[0-9a-f]{40}$' -or
        [string]$columns[1] -cne $RemoteRef) {
        throw "$Label returned malformed or substituted remote-ref evidence."
    }
    return ([string]$columns[0]).ToLowerInvariant()
}
