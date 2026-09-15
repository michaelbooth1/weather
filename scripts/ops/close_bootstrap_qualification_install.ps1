# Close only an acknowledged first landing after its two exact tasks terminate.
# No task is registered, started, deleted or replaced; no Git ref is changed.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$EnvelopePath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedEnvelopeSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedResultSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCloserSha256
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Open-WeatherBootstrapPinnedFile {
    param([string]$Path,[string]$Sha256,[Int64]$Size,[Int64]$Maximum=2097152)
    if(-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\') -or
        $Sha256 -cnotmatch '^[0-9a-f]{64}$' -or $Size -lt 0 -or $Size -gt $Maximum) { throw 'Invalid bootstrap file pin' }
    $cursor=[IO.Path]::GetFullPath($Path)
    while($cursor -and $cursor -ne [IO.Path]::GetPathRoot($cursor)) {
        if(([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Bootstrap pin redirects' }
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if($stream.Length -ne $Size) { throw 'Bootstrap pinned length differs' }
        $hasher=[Security.Cryptography.SHA256]::Create()
        try {$actual=-join($hasher.ComputeHash($stream) | ForEach-Object {$_.ToString('x2')})} finally {$hasher.Dispose()}
        if($actual -cne $Sha256) { throw 'Bootstrap pinned bytes differ' }
        $stream.Position=0
        return $stream
    } catch {$stream.Dispose();throw}
}

function Read-WeatherBootstrapPinnedObject {
    param([IO.Stream]$Stream)
    $reader=[IO.StreamReader]::new($Stream,[Text.UTF8Encoding]::new($false,$true),$false,4096,$true)
    try {$raw=$reader.ReadToEnd();$Stream.Position=0;return ($raw | ConvertFrom-Json)} finally {$reader.Dispose()}
}


$locks=New-Object 'System.Collections.Generic.List[System.IO.Stream]'
$lease=$null
try {
    $locks.Add((Open-WeatherBootstrapPinnedFile $PSCommandPath $ExpectedCloserSha256 ([IO.FileInfo]::new($PSCommandPath).Length)))
    $path=[IO.Path]::GetFullPath($EnvelopePath);$root=[IO.Path]::GetDirectoryName($path)
    $stream=Open-WeatherBootstrapPinnedFile $path $ExpectedEnvelopeSha256 ([IO.FileInfo]::new($path).Length)
    $locks.Add($stream);$value=Read-WeatherBootstrapPinnedObject $stream
    if($value.schema -cne 'qualification_bootstrap_install_envelope_v1' -or $value.operation -cne 'install_control_plane_K_once') {
        throw 'Closeout requires the separate first-landing envelope'
    }
    $authority=[IO.Path]::GetFullPath([string]$value.control.root)
    if([IO.Path]::GetFullPath($PSScriptRoot) -ine (Join-Path $authority 'scripts/ops') -or
        [IO.Path]::GetFullPath([string]$value.evidence_root) -ine $root) {throw 'Closeout source/evidence location differs'}
    $adopted=@($value.adopted_helpers.files)
    if((@($adopted.path) -join '|') -cne 'scripts/ops/windows_kill_on_close_job.ps1|scripts/ops/workload_admission.ps1') {
        throw 'Closeout adopted helper inventory differs'
    }
    foreach($pin in $adopted) {
        $locks.Add((Open-WeatherBootstrapPinnedFile (Join-Path $value.baseline_control.root $pin.path) $pin.sha256 $pin.size))
    }
    . (Join-Path $value.baseline_control.root 'scripts/ops/workload_admission.ps1')
    $ref=$value.control.closure
    if($ref.path -isnot [string] -or $ref.path -match '[\\:*?"<>|]' -or
        $ref.path -match '(^|/)(\.|\.\.|)(/|$)' -or $ref.path.StartsWith('/')) {throw 'Unsafe closeout closure reference'}
    $stream=Open-WeatherBootstrapPinnedFile (Join-Path $root $ref.path) $ref.sha256 $ref.size
    $locks.Add($stream);$closure=Read-WeatherBootstrapPinnedObject $stream
    if($closure.schema -cne 'qualification_runtime_files_v2' -or @($closure.files).Count -gt 512) {throw 'Wrong closeout closure'}
    [Int64]$bytes=0
    $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach($pin in $closure.files) {
        if($pin.path -isnot [string] -or $pin.path -match '[\\:*?"<>|]' -or
            $pin.path -match '(^|/)(\.|\.\.|)(/|$)' -or $pin.path.StartsWith('/') -or -not $seen.Add([string]$pin.path)) {
            throw 'Unsafe closeout dependency path'
        }
        $bytes+=[Int64]$pin.size
        if($bytes -gt 8388608) {throw 'Closeout closure exceeds eight MiB'}
        $locks.Add((Open-WeatherBootstrapPinnedFile (Join-Path $authority $pin.path) $pin.sha256 $pin.size))
    }
    foreach($name in @('scripts/ops/close_bootstrap_qualification_install.ps1','scripts/ops/qualification_bootstrap_install_contract.ps1',
        'scripts/ops/qualification_bootstrap_probe_contract.ps1','scripts/ops/qualification_host_identity.ps1')) {
        if(-not $seen.Contains($name)) {throw 'Closeout dependency is not independently pinned'}
    }
    $selfPin=@($closure.files | Where-Object path -CEQ 'scripts/ops/close_bootstrap_qualification_install.ps1')
    if($selfPin.Count -ne 1 -or $selfPin[0].sha256 -cne $ExpectedCloserSha256) {throw 'Closer pin and closure disagree'}
    . (Join-Path $PSScriptRoot 'qualification_bootstrap_install_contract.ps1')
    . (Join-Path $PSScriptRoot 'qualification_host_identity.ps1')
    $value=Read-WeatherBootstrapInstallEnvelope $path $ExpectedEnvelopeSha256
    Assert-WeatherBootstrapProbeTree -Root $authority -Inventory $closure -MaximumEntries 1024 -SourceOnly $true
    $identity=Get-WeatherQualificationCurrentLogon
    if((Get-WeatherExecutionHostId) -cne [string]$value.host.host_id -or
        (Get-WeatherExecutionPrincipalId) -cne [string]$value.host.principal_id -or
        $identity.sid -cne [string]$value.host.user_sid -or $identity.elevated) {throw 'Wrong closeout host/principal'}
    $lease=Enter-WeatherHeavyWorkloadLease -RepoRoot $value.repo_root -Workload ('BootstrapCloseout-'+[string]$value.bootstrap_id)
    if($null -eq $lease) {throw 'Another host workload owns the closeout boundary'}
    Close-WeatherBootstrapInstallation $value $ExpectedEnvelopeSha256 $ExpectedResultSha256
} finally {
    if($lease) {Exit-WeatherHeavyWorkloadLease -Lease $lease}
    foreach($stream in $locks) {$stream.Dispose()}
}
