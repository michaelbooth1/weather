# Workstation pre-gate driver: replays the capture host's bounded suite
# (bounded_worktree_test_suite.ps1, read from the same scripts\ops directory)
# statement by statement from its PowerShell AST, so the pytest chunk launch,
# Job containment, console attachment, environment scrubbing, per-chunk
# basetemp, JUnit handling and time-packed chunk plan are the host's own code,
# not a copy that can drift.
#
# Only host-only admission statements are replaced, each located structurally
# and required to occur exactly once (a drifted host suite fails closed here):
#   - the 00:30-09:00 start-window refusal          -> skipped
#   - the 09:00 hard stop                            -> no wall-clock stop
#                                                       (MaxRuntimeSeconds still applies)
#   - the capture-host heavy-workload lease          -> skipped (the caller holds
#                                                       the workstation queue lease)
#   - Assert-HostAdmission (capture workers, host    -> logging stub
#     commit ceiling)
# Every replacement is written into the suite log, which the receipt hashes.
# $PSScriptRoot/$PSCommandPath in replayed statements are rebound to the host
# suite's directory and path (Invoke-Expression has no script file); the driver
# sits in that directory, so the same helper files load.
#
# Launch this only through scripts\ops\workstation_pregate.ps1. It never merges,
# pushes, checks out, registers a task, or writes under data\ of any checkout.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$WorktreeRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedTip,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [Parameter(Mandatory = $true)][string]$GitExecutablePath,
    [Parameter(Mandatory = $true)][string]$ExpectedGitExecutableSha256,
    [Parameter(Mandatory = $true)][string]$ExpectedGitExecutableFileVersion
)

$ErrorActionPreference = "Stop"
$launchJournal = $null
trap {
    if (Get-Command Close-WeatherLaunchDiagnostics -ErrorAction SilentlyContinue) {
        Close-WeatherLaunchDiagnostics -Journal $launchJournal -Status "FAIL" -Failure $_
    }
    throw
}

$pregateHostScriptRoot = $PSScriptRoot
$pregateHostSuitePath = Join-Path $PSScriptRoot "bounded_worktree_test_suite.ps1"
$pregateParseTokens = $null
$pregateParseErrors = $null
$pregateHostAst = [Management.Automation.Language.Parser]::ParseFile(
    $pregateHostSuitePath, [ref]$pregateParseTokens, [ref]$pregateParseErrors
)
if ($pregateParseErrors.Count -ne 0) {
    throw "workstation pre-gate cannot parse the host bounded suite: $pregateHostSuitePath"
}

# Bind the host suite's own parameter block: the identity parameters from this
# driver, every other parameter from the host's declared default.
$pregateBound = @{
    RepoRoot = $RepoRoot
    WorktreeRoot = $WorktreeRoot
    ExpectedTip = $ExpectedTip
    BranchRef = $ExpectedTip
    LogPath = $LogPath
    GitExecutablePath = $GitExecutablePath
    ExpectedGitExecutableSha256 = $ExpectedGitExecutableSha256
    ExpectedGitExecutableFileVersion = $ExpectedGitExecutableFileVersion
}
foreach ($pregateParameter in @($pregateHostAst.ParamBlock.Parameters)) {
    $pregateName = $pregateParameter.Name.VariablePath.UserPath
    if ($pregateBound.ContainsKey($pregateName)) {
        $pregateValue = $pregateBound[$pregateName]
    }
    elseif ($pregateParameter.StaticType -eq [System.Management.Automation.SwitchParameter]) {
        $pregateValue = [switch]$false
    }
    elseif ($null -ne $pregateParameter.DefaultValue) {
        $pregateValue = Invoke-Expression $pregateParameter.DefaultValue.Extent.Text
    }
    else {
        throw "host bounded suite parameter has no pre-gate binding: $pregateName"
    }
    Set-Variable -Name $pregateName -Value $pregateValue -Scope Script
}
$MaxFilesPerChunk = [int]$MaxFilesPerChunk
$StartCommitPercent = [double]$StartCommitPercent
$AbortCommitPercent = [double]$AbortCommitPercent
$MaxRuntimeSeconds = [int]$MaxRuntimeSeconds

function Test-WorkstationPregateStatement {
    param(
        [Parameter(Mandatory = $true)][object]$Statement,
        [Parameter(Mandatory = $true)][string]$Rule
    )

    switch ($Rule) {
        "trap" {
            return $Statement -is [Management.Automation.Language.TrapStatementAst]
        }
        "window" {
            return $Statement -is [Management.Automation.Language.IfStatementAst] -and
                $Statement.Extent.Text.Contains("00:30-09:00 heavy-work window")
        }
        "hard_stop" {
            return $Statement -is [Management.Automation.Language.AssignmentStatementAst] -and
                $Statement.Left -is [Management.Automation.Language.VariableExpressionAst] -and
                $Statement.Left.VariablePath.UserPath -ceq "hardStop"
        }
        "lease" {
            return $Statement -is [Management.Automation.Language.AssignmentStatementAst] -and
                $Statement.Left -is [Management.Automation.Language.VariableExpressionAst] -and
                $Statement.Left.VariablePath.UserPath -ceq "workloadLease"
        }
        "lease_check" {
            return $Statement -is [Management.Automation.Language.IfStatementAst] -and
                $Statement.Extent.Text.Contains('$null -eq $workloadLease')
        }
        "main" {
            return $Statement -is [Management.Automation.Language.TryStatementAst] -and
                $Statement.Extent.Text.Contains("=== bounded worktree suite starting ===")
        }
    }
    throw "unknown pre-gate statement rule: $Rule"
}

$pregateStatements = @($pregateHostAst.EndBlock.Statements)
$pregateRules = @("trap", "window", "hard_stop", "lease", "lease_check", "main")
foreach ($pregateRule in $pregateRules) {
    $pregateMatches = @($pregateStatements | Where-Object {
        Test-WorkstationPregateStatement -Statement $_ -Rule $pregateRule
    })
    if ($pregateMatches.Count -ne 1) {
        throw (
            "host bounded suite drifted: pre-gate rule '$pregateRule' matched " +
            "$($pregateMatches.Count) top-level statements (expected exactly 1)"
        )
    }
}
if (-not (Test-WorkstationPregateStatement -Statement $pregateStatements[-1] -Rule "main")) {
    throw "host bounded suite drifted: the main try statement is no longer last"
}

$script:pregateSkipNotes = @(
    "WORKSTATION PRE-GATE: host suite replayed from $pregateHostSuitePath",
    "WORKSTATION PRE-GATE: skipped host-only check: 00:30-09:00 start window",
    "WORKSTATION PRE-GATE: skipped host-only check: 09:00 hard stop (MaxRuntimeSeconds=$MaxRuntimeSeconds still applies)",
    "WORKSTATION PRE-GATE: skipped host-only check: capture-host heavy-workload lease (workstation queue lease held by the caller)",
    "WORKSTATION PRE-GATE: skipped host-only check: Assert-HostAdmission capture workers and host commit ceiling"
)
$script:pregateSkipNotesWritten = $false

foreach ($pregateStatement in $pregateStatements) {
    if (Test-WorkstationPregateStatement -Statement $pregateStatement -Rule "trap") { continue }
    if (Test-WorkstationPregateStatement -Statement $pregateStatement -Rule "window") { continue }
    if (Test-WorkstationPregateStatement -Statement $pregateStatement -Rule "lease_check") { continue }
    if (Test-WorkstationPregateStatement -Statement $pregateStatement -Rule "hard_stop") {
        $hardStop = [datetime]::MaxValue
        continue
    }
    if (Test-WorkstationPregateStatement -Statement $pregateStatement -Rule "lease") {
        $workloadLease = $null
        continue
    }
    if (Test-WorkstationPregateStatement -Statement $pregateStatement -Rule "main") {
        # Host-only admission replaced just before the main body runs, after
        # every host function definition and helper dot-source has executed.
        function Assert-HostAdmission {
            param(
                [Parameter(Mandatory = $true)][double]$CommitCeiling,
                [Parameter(Mandatory = $true)][string]$Phase
            )
            if (-not $script:pregateSkipNotesWritten) {
                foreach ($note in $script:pregateSkipNotes) { Write-SuiteLog $note }
                $script:pregateSkipNotesWritten = $true
            }
            $observed = "unavailable"
            try { $observed = "$(Get-CommitPercent)%" } catch { }
            Write-SuiteLog (
                "$Phase admission: SKIPPED on workstation (capture workers, host commit " +
                "ceiling=$CommitCeiling%); observed commit=$observed"
            )
        }
        function Exit-WeatherHeavyWorkloadLease {
            param([AllowNull()][object]$Lease)
            if ($null -ne $Lease) {
                throw "workstation pre-gate driver must never hold a host workload lease"
            }
        }
    }
    # Invoke-Expression has no script file, so $PSScriptRoot/$PSCommandPath
    # would be empty. Rebind them to the host suite's own values; the driver
    # lives beside the suite, so every helper resolves to the same file.
    $pregateText = $pregateStatement.Extent.Text
    if ($pregateText -cmatch '\$MyInvocation\b') {
        throw "host bounded suite drifted: a top-level statement uses `$MyInvocation"
    }
    $pregateText = $pregateText -creplace '\$PSScriptRoot\b', '$pregateHostScriptRoot'
    $pregateText = $pregateText -creplace '\$PSCommandPath\b', '$pregateHostSuitePath'
    Invoke-Expression $pregateText
}
# The host main statement always exits; reaching here means it drifted.
throw "host bounded suite main statement returned without an exit code"
