# Run the one authorized Previous Runs research collection on the assigned
# non-capture workstation under the portable-live host-global mutex.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$RepoRoot
)

$ErrorActionPreference = "Stop"

$admissionScript = Join-Path $PSScriptRoot "workload_admission.ps1"
$jobScript = Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1"
foreach ($requiredScript in @($admissionScript, $jobScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "required research-collection helper is missing: $requiredScript"
    }
}
. $admissionScript
. $jobScript

function Get-ResearchCollectionDirectorySecurity {
    param([Parameter(Mandatory = $true)][IO.DirectoryInfo]$Directory)

    return Get-WeatherStateDirectorySecurity -Directory $Directory
}

function New-ResearchCollectionRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $currentSid) {
        throw "attending Windows identity is unavailable"
    }
    $security = [Security.AccessControl.DirectorySecurity]::new()
    $security.SetOwner($currentSid)
    $security.SetAccessRuleProtection($true, $false)
    foreach ($sidText in @(
        $currentSid.Value,
        "S-1-5-18",
        "S-1-5-32-544"
    )) {
        $sid = [Security.Principal.SecurityIdentifier]::new($sidText)
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                [Security.AccessControl.InheritanceFlags]::ObjectInherit,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$security.AddAccessRule($rule)
    }
    return New-WeatherProtectedStateDirectory -Path $Path -Security $security
}

function Assert-ResearchCollectionRootAcl {
    param([Parameter(Mandatory = $true)][IO.DirectoryInfo]$Directory)

    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $trusted = @(
        $currentSid.Value,
        "S-1-5-18",
        "S-1-5-32-544"
    )
    $security = Get-ResearchCollectionDirectorySecurity -Directory $Directory
    if (-not $security.AreAccessRulesProtected) {
        throw "research-collection root ACL inherits from its parent"
    }
    $owner = $security.GetOwner([Security.Principal.SecurityIdentifier])
    if ($owner.Value -cne $currentSid.Value) {
        throw "research-collection root is not owned by the attending identity"
    }
    $writeMask =
        [Security.AccessControl.FileSystemRights]::WriteData -bor
        [Security.AccessControl.FileSystemRights]::AppendData -bor
        [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
        [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in $security.GetAccessRules(
        $true,
        $false,
        [Security.Principal.SecurityIdentifier]
    )) {
        if (
            $rule.AccessControlType -eq
                [Security.AccessControl.AccessControlType]::Allow -and
            ([int64]$rule.FileSystemRights -band [int64]$writeMask) -ne 0 -and
            $rule.IdentityReference.Value -cnotin $trusted
        ) {
            throw "research-collection root grants write access beyond trusted identities"
        }
    }
    return $security
}

function Set-ResearchCollectionOfflineDeny {
    param([Parameter(Mandatory = $true)][IO.DirectoryInfo]$Directory)

    $security = Assert-ResearchCollectionRootAcl -Directory $Directory
    $offlineAccount = [Security.Principal.NTAccount]::new(
        [Environment]::MachineName,
        "CodexSandboxOffline"
    )
    try {
        $offlineSid = $offlineAccount.Translate(
            [Security.Principal.SecurityIdentifier]
        )
    }
    catch {
        throw "CodexSandboxOffline identity is unavailable"
    }
    $rights =
        [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $offlineSid,
        $rights,
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Deny
    )
    [void]$security.AddAccessRule($rule)
    $aclExtensions = "System.IO.FileSystemAclExtensions" -as [type]
    if ($null -ne $aclExtensions) {
        $method = $aclExtensions.GetMethod(
            "SetAccessControl",
            [type[]]@(
                [IO.DirectoryInfo],
                [Security.AccessControl.DirectorySecurity]
            )
        )
        if ($null -eq $method) {
            throw "Core filesystem ACL mutation is unavailable"
        }
        [void]$method.Invoke($null, [object[]]@($Directory, $security))
    }
    else {
        [IO.Directory]::SetAccessControl($Directory.FullName, $security)
    }

    $observed = Assert-ResearchCollectionRootAcl -Directory $Directory
    $matching = @($observed.GetAccessRules(
        $true,
        $false,
        [Security.Principal.SecurityIdentifier]
    ) | Where-Object {
        -not $_.IsInherited -and
        $_.IdentityReference.Value -ceq $offlineSid.Value -and
        $_.AccessControlType -eq
            [Security.AccessControl.AccessControlType]::Deny -and
        ([int64]$_.FileSystemRights -band [int64]$rights) -eq [int64]$rights
    })
    if ($matching.Count -ne 1) {
        throw "CodexSandboxOffline explicit deny did not persist exactly once"
    }
    return [ordered]@{
        root = $Directory.FullName
        owner_sid = [string]$observed.GetOwner(
            [Security.Principal.SecurityIdentifier]
        ).Value
        acl_protected = [bool]$observed.AreAccessRulesProtected
        identity = $offlineSid.Value
        access_control_type = "Deny"
        rights = @("Write", "Delete", "DeleteSubdirectoriesAndFiles")
        inherited = $false
        matching_rule_count = $matching.Count
    }
}

if (-not [IO.Path]::IsPathRooted($RepoRoot)) {
    throw "research-collection repository root must be absolute"
}
$repo = Get-Item -LiteralPath $RepoRoot -Force -ErrorAction Stop
$wrapperRepo = Get-Item -LiteralPath (Join-Path $PSScriptRoot "..\..") `
    -Force -ErrorAction Stop
if (
    $repo -isnot [IO.DirectoryInfo] -or
    ($repo.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    -not [string]::Equals(
        $repo.FullName,
        $wrapperRepo.FullName,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "research-collection repository root must own this exact wrapper"
}

$expectedPlan = Join-Path $repo.FullName `
    "docs\roadmap\previous-runs-multiyear-collection-plan-2026-09-87a.json"
$planItem = Get-Item -LiteralPath $PlanPath -Force -ErrorAction Stop
if (
    $planItem -isnot [IO.FileInfo] -or
    ($planItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    -not [string]::Equals(
        $planItem.FullName,
        $expectedPlan,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "research collection requires the exact tracked immutable plan"
}
$plan = Get-Content -Raw -LiteralPath $planItem.FullName | ConvertFrom-Json
$planFileHash = (Get-FileHash -Algorithm SHA256 `
    -LiteralPath $planItem.FullName).Hash.ToLowerInvariant()
if (
    $planFileHash -cne
        "924ddd2f1ca5a85def80dcee1296752df3df167f8a37d9ae7566a8c5f7ec303a" -or
    [string]$plan.schema_version -cne
        "previous_runs_research_collection_plan_v1" -or
    [string]$plan.status -cne
        "IMMUTABLE_OUTCOME_BLIND_PLAN_BEFORE_NETWORK_ACCESS" -or
    [string]$plan.provider_contract.endpoint -cne
        "https://previous-runs-api.open-meteo.com/v1/forecast" -or
    [string]$plan.execution_contract.profile -cne
        "workstation_research_collection_v1" -or
    [string]$plan.plan_sha256 -cne
        "20b45f3c0d98a57170a66a237de865374309da67371805fc15204d00f354b09e"
) {
    throw "research-collection plan contract differs from authorization"
}
$assignmentPath = Join-Path $repo.FullName `
    "config\international_live_execution_host.json"
$assignmentHash = (Get-FileHash -Algorithm SHA256 `
    -LiteralPath $assignmentPath).Hash.ToLowerInvariant()
if ($assignmentHash -cne [string]$plan.execution_contract.assignment_sha256) {
    throw "research-collection host assignment differs from the frozen plan"
}

$python = Get-Item -LiteralPath $PythonPath -Force -ErrorAction Stop
if (
    -not [IO.Path]::IsPathRooted($PythonPath) -or
    $python -isnot [IO.FileInfo] -or
    ($python.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    $python.Name -cnotmatch '(?i)\Apython(?:3(?:\.\d+)?)?\.exe\z'
) {
    throw "research collection requires a regular absolute CPython executable"
}

$outputPath = [IO.Path]::GetFullPath([string]$plan.output_contract.root)
if (-not [IO.Path]::IsPathRooted($outputPath)) {
    throw "research-collection output root must be absolute"
}
$createdOutputRoot = $false
if (-not (Test-Path -LiteralPath $outputPath)) {
    $outputRoot = New-ResearchCollectionRoot -Path $outputPath
    $createdOutputRoot = $true
}
else {
    $outputRoot = Get-Item -LiteralPath $outputPath -Force -ErrorAction Stop
}
if (
    $outputRoot -isnot [IO.DirectoryInfo] -or
    ($outputRoot.Attributes -band [IO.FileAttributes]::ReparsePoint)
) {
    throw "research-collection output root is absent or redirected"
}
[void](Assert-ResearchCollectionRootAcl -Directory $outputRoot)
if (-not $createdOutputRoot) {
    $retainedPlan = Join-Path $outputRoot.FullName "collection-plan.json"
    if (-not (Test-Path -LiteralPath $retainedPlan -PathType Leaf)) {
        $existingChildren = @(Get-ChildItem -LiteralPath $outputRoot.FullName `
            -Force -ErrorAction Stop)
        if ($existingChildren.Count -ne 0) {
            throw "existing research-collection root lacks its immutable plan"
        }
        # A prior wrapper preflight may have atomically created the protected
        # root before Python launched. Only that exact empty, ACL-verified root
        # is safe to resume; no retained artifact is removed or overwritten.
    }
    else {
        $expectedHash = (Get-FileHash -Algorithm SHA256 `
            -LiteralPath $planItem.FullName).Hash
        $retainedHash = (Get-FileHash -Algorithm SHA256 `
            -LiteralPath $retainedPlan).Hash
        if ($expectedHash -cne $retainedHash) {
            throw "existing research-collection root plan differs byte-for-byte"
        }
    }
}

$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $repo.FullName `
    -Workload ("WorkstationResearchCollection-{0}" -f `
        ([string]$plan.plan_sha256).Substring(0, 12)) `
    -ExecutionHostProfile "workstation_research_collection_v1"
if ($null -eq $lease) {
    throw "research collection is blocked by another heavy or portable live lease"
}

$job = $null
$child = $null
$exitCode = 1
try {
    $job = New-WeatherKillOnCloseJob
    $arguments = @(
        "-m",
        "weather.sources.previous_runs_research_collection",
        "collect",
        "--plan",
        $planItem.FullName
    )
    $argumentString = ConvertTo-WeatherWindowsArgumentString -Tokens $arguments
    [Environment]::SetEnvironmentVariable(
        "WEATHER_RESEARCH_COLLECTION_WRAPPER_ACTIVE",
        "1",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "PSExecutionPolicyPreference",
        "Bypass",
        "Process"
    )
    $child = Start-WeatherInteractiveProcessInJob `
        -Job $job `
        -FilePath $python.FullName `
        -ArgumentString $argumentString `
        -WorkingDirectory $repo.FullName
    $child.WaitForExit()
    $exitCode = $child.ExitCode

    $verificationPath = Join-Path $outputRoot.FullName `
        "final\final-verification.json"
    if (
        $exitCode -in @(0, 2) -and
        (Test-Path -LiteralPath $verificationPath -PathType Leaf)
    ) {
        $aclProof = Set-ResearchCollectionOfflineDeny -Directory $outputRoot
        [pscustomobject]@{
            schema_version = "previous_runs_research_acl_proof_v1"
            recorded_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            plan_sha256 = [string]$plan.plan_sha256
            proof = $aclProof
        } | ConvertTo-Json -Depth 8 -Compress | Write-Output
    }
}
finally {
    $teardownTransitionError = $null
    $jobTeardownError = $null
    if ($null -ne $lease) {
        try {
            Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease |
                Out-Null
        }
        catch { $teardownTransitionError = $_ }
    }
    if ($job -and $null -eq $teardownTransitionError) {
        try { $job.TerminateAndWait(5000) }
        catch { $jobTeardownError = $_ }
    }
    if ($child) { $child.Dispose() }
    if ($job) { $job.Dispose() }
    if ($null -ne $teardownTransitionError) {
        # Kill-on-close still owns the child; the ACTIVE marker and mutex stay.
    }
    elseif ($jobTeardownError) {
        Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease
    }
    else {
        Exit-WeatherHeavyWorkloadLease -Lease $lease
    }
    if ($null -ne $teardownTransitionError) { throw $teardownTransitionError }
    if ($jobTeardownError) { throw $jobTeardownError }
}
exit $exitCode
