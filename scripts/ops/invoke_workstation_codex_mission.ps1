# Run or inspect one immutable, deadline-bound workstation Codex mission attempt.
# The runner never pushes, merges, retries, registers tasks, reads credentials,
# or contacts production. Run-mode Git operations are local-only.

[CmdletBinding()]
param(
    [ValidateSet("Run", "Status", "InternalChild")]
    [string]$Mode = "Run",
    [string]$MissionId,
    [string]$MissionPath,
    [ValidatePattern('\A[0-9a-fA-F]{64}\z')][string]$ExpectedMissionSha256,
    [string]$AttemptRoot,
    [ValidateRange(1, 999)][int]$Attempt = 1,
    [string]$RepositoryRoot,
    [string]$ControllerWorktree,
    [ValidatePattern('\A[0-9a-fA-F]{40}\z')][string]$ExpectedSourceTip,
    [ValidatePattern('\A[0-9a-fA-F]{40}\z')][string]$ExpectedSourceTree,
    [ValidatePattern('\A[0-9a-fA-F]{40}\z')][string]$ExpectedSourceParent,
    [ValidatePattern('\A[0-9a-fA-F]{40}\z')][string]$ExpectedBaseTip,
    [string]$ResultRef,
    [string]$ResultWorktree,
    [string]$RequiredReportPath,
    [string]$RequiredReceiptPath,
    [string]$BundlePath,
    [string]$CodexPath,
    [ValidatePattern('\A[0-9a-fA-F]{64}\z')][string]$ExpectedCodexSha256,
    [string]$DeadlineUtc,
    [ValidateRange(1, 300)][int]$HeartbeatSeconds = 5,
    [string]$Prompt = "",
    [ValidatePattern('\A[0-9a-fA-F]{64}\z')][string]$ExpectedClaimSha256,
    [ValidateRange(1, 86400)][int]$StaleAfterSeconds = 30,
    [string]$ChildContractBase64
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:Utf8 = [Text.UTF8Encoding]::new($false, $true)
$script:GitExecutable = $null

function Get-UtcText {
    return [DateTimeOffset]::UtcNow.ToString(
        "o",
        [Globalization.CultureInfo]::InvariantCulture
    )
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-StringSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $script:Utf8.GetBytes($Value)
        return -join ($hasher.ComputeHash($bytes) | ForEach-Object {
            $_.ToString("x2")
        })
    }
    finally { $hasher.Dispose() }
}

function Assert-NoReparseAncestry {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = [IO.Path]::GetFullPath($Path)
    $cursor = $full
    while (-not (Test-Path -LiteralPath $cursor)) {
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { throw "path has no existing ancestor: $full" }
        $cursor = $parent.FullName
    }
    while ($true) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "path ancestry contains a reparse point: $cursor"
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
    return $full
}

function Resolve-RegularFile {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$Label = "file")
    if (-not [IO.Path]::IsPathRooted($Path)) { throw "$Label path must be absolute" }
    $full = Assert-NoReparseAncestry -Path $Path
    $item = Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "$Label must be a regular non-reparse file: $full"
    }
    return $item.FullName
}

function Resolve-RegularDirectory {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$Label = "directory")
    if (-not [IO.Path]::IsPathRooted($Path)) { throw "$Label path must be absolute" }
    $full = Assert-NoReparseAncestry -Path $Path
    $item = Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "$Label must be a regular non-reparse directory: $full"
    }
    return $item.FullName
}

function Resolve-FuturePath {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$Label = "path")
    if (-not [IO.Path]::IsPathRooted($Path)) { throw "$Label must be absolute" }
    return Assert-NoReparseAncestry -Path $Path
}

function Test-PathWithin {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Parent)
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $fullParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    if ([string]::Equals($fullPath, $fullParent, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $fullPath.StartsWith(
        $fullParent + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Write-ImmutableBytes {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][byte[]]$Bytes)
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    try {
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
}

function Write-ImmutableJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Payload)
    $json = $Payload | ConvertTo-Json -Depth 20
    Write-ImmutableBytes -Path $Path -Bytes $script:Utf8.GetBytes($json + "`n")
    return Get-Sha256 -Path $Path
}

if (-not ("Weather.Operations.AtomicMissionStateV1" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Weather.Operations
{
    public static class AtomicMissionStateV1
    {
        private const UInt32 MOVEFILE_REPLACE_EXISTING = 0x1;
        private const UInt32 MOVEFILE_WRITE_THROUGH = 0x8;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool MoveFileEx(string existing, string replacement, UInt32 flags);

        public static void Replace(string temporaryPath, string targetPath)
        {
            if (!MoveFileEx(
                temporaryPath,
                targetPath,
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
            ))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "atomic state replacement failed");
            }
        }
    }
}
'@
}

function Publish-AtomicJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload,
        [Parameter(Mandatory = $true)][long]$Sequence
    )
    $directory = [IO.Path]::GetDirectoryName($Path)
    $temporary = Join-Path $directory (
        ".{0}.tmp.{1}.{2}.{3}" -f [IO.Path]::GetFileName($Path), $PID, $Sequence,
        [guid]::NewGuid().ToString("N")
    )
    try {
        $json = $Payload | ConvertTo-Json -Depth 20
        Write-ImmutableBytes -Path $temporary -Bytes $script:Utf8.GetBytes($json + "`n")
        [Weather.Operations.AtomicMissionStateV1]::Replace($temporary, $Path)
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
}

function Read-BoundedJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 16777216)][int]$MaximumBytes = 1048576
    )
    $resolved = Resolve-RegularFile -Path $Path -Label "JSON evidence"
    $stream = [IO.File]::Open(
        $resolved,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    )
    try {
        if ($stream.Length -le 0 -or $stream.Length -gt $MaximumBytes) {
            throw "JSON evidence length is invalid: $resolved"
        }
        $bytes = [byte[]]::new([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $count = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($count -eq 0) { break }
            $offset += $count
        }
        if ($offset -ne $bytes.Length) { throw "JSON evidence was not read completely: $resolved" }
        $text = $script:Utf8.GetString($bytes)
        return $text | ConvertFrom-Json -ErrorAction Stop
    }
    finally { $stream.Dispose() }
}

function Assert-Properties {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string[]]$Required,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($null -eq $Value -or $Value -is [string]) { throw "$Label is not a JSON object" }
    $names = @($Value.PSObject.Properties.Name)
    foreach ($name in $Required) {
        if ($names -cnotcontains $name) { throw "$Label is missing property: $name" }
    }
}

function Resolve-GitExecutable {
    $commands = @(Get-Command git.exe -CommandType Application -All -ErrorAction Stop)
    if ($commands.Count -lt 1) { throw "git.exe is unavailable" }
    return Resolve-RegularFile -Path $commands[0].Source -Label "Git executable"
}

function Assert-FinalExecutableIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$MissionPath,
        [Parameter(Mandatory = $true)][string]$CodexPath,
        [Parameter(Mandatory = $true)][string]$RunnerPath,
        [Parameter(Mandatory = $true)][string]$JobHelperPath,
        [Parameter(Mandatory = $true)][string]$PowerShellPath,
        [Parameter(Mandatory = $true)][string]$GitPath,
        [Parameter(Mandatory = $true)]$Claim
    )
    $identities = @(
        @("mission", $MissionPath, [string]$Claim.mission_path, [string]$Claim.mission_sha256),
        @("Codex executable", $CodexPath, [string]$Claim.codex_path, [string]$Claim.codex_sha256),
        @("runner", $RunnerPath, [string]$Claim.runner_path, [string]$Claim.runner_sha256),
        @("Job helper", $JobHelperPath, [string]$Claim.job_helper_path, [string]$Claim.job_helper_sha256),
        @("Windows PowerShell executable", $PowerShellPath, [string]$Claim.powershell_path, [string]$Claim.powershell_sha256),
        @("Git executable", $GitPath, [string]$Claim.git_path, [string]$Claim.git_sha256)
    )
    foreach ($identity in $identities) {
        $label = [string]$identity[0]
        $actualPath = Resolve-RegularFile -Path ([string]$identity[1]) -Label $label
        if (
            $actualPath -cne [string]$identity[2] -or
            (Get-Sha256 -Path $actualPath) -cne [string]$identity[3]
        ) { throw "$label identity drift" }
    }
}

function Invoke-LocalGit {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int[]]$AllowedExitCodes = @(0)
    )
    $oldPrompt = $env:GIT_TERMINAL_PROMPT
    $oldInteractive = $env:GCM_INTERACTIVE
    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $env:GIT_TERMINAL_PROMPT = "0"
        $env:GCM_INTERACTIVE = "Never"
        $ErrorActionPreference = "Continue"
        $output = @(& $script:GitExecutable -c credential.helper= -c core.askPass= @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $env:GIT_TERMINAL_PROMPT = $oldPrompt
        $env:GCM_INTERACTIVE = $oldInteractive
        $ErrorActionPreference = $oldErrorActionPreference
    }
    if ($exitCode -notin $AllowedExitCodes) {
        throw "local Git command failed ($exitCode): git $($Arguments -join ' ')`n$($output -join "`n")"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

function Get-GitScalar {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $result = Invoke-LocalGit -Arguments $Arguments
    if ($result.Output.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$result.Output[0])) {
        throw "Git scalar query returned an invalid result: $($Arguments -join ' ')"
    }
    return ([string]$result.Output[0]).Trim()
}

function Get-BootId {
    $boot = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
    return Get-StringSha256 -Value (
        "workstation_mission_boot_v1`0" + $boot.ToUniversalTime().ToString("o")
    )
}

function Get-HostId {
    $machineGuid = [string](Get-ItemPropertyValue `
        -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography" `
        -Name "MachineGuid" -ErrorAction Stop)
    return Get-StringSha256 -Value (
        "workstation_mission_host_v1`0" + $machineGuid.Trim().ToLowerInvariant()
    )
}

function Get-PrincipalId {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    return Get-StringSha256 -Value (
        "workstation_mission_principal_v1`0" + $sid.Trim().ToLowerInvariant()
    )
}

function Get-ProcessStartUtc {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    if ($null -eq $process -or $null -eq $process.CreationDate) {
        throw "process creation identity is unavailable: $ProcessId"
    }
    return $process.CreationDate.ToUniversalTime().ToString("o")
}

function Test-ExactProcessAlive {
    param([Parameter(Mandatory = $true)][int]$ProcessId, [Parameter(Mandatory = $true)][string]$StartedAtUtc)
    try { return (Get-ProcessStartUtc -ProcessId $ProcessId) -ceq $StartedAtUtc }
    catch { return $false }
}

function Assert-ArtifactOutsideWorktrees {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$RepoRoot)
    $listing = Invoke-LocalGit -Arguments @("-C", $RepoRoot, "worktree", "list", "--porcelain")
    foreach ($line in $listing.Output) {
        if ([string]$line -clike "worktree *") {
            $root = ([string]$line).Substring(9)
            if (Test-PathWithin -Path $Path -Parent $root) {
                throw "mutable attempt artifact must be outside every Git worktree: $Path"
            }
        }
    }
}

function ConvertTo-ChildContract {
    param([Parameter(Mandatory = $true)]$Payload)
    $json = $Payload | ConvertTo-Json -Compress -Depth 10
    return [Convert]::ToBase64String($script:Utf8.GetBytes($json))
}

function ConvertFrom-ChildContract {
    param([Parameter(Mandatory = $true)][string]$Encoded)
    if ($Encoded.Length -gt 131072 -or $Encoded -cnotmatch '\A(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\z') {
        throw "internal child contract is not canonical base64"
    }
    $bytes = [Convert]::FromBase64String($Encoded)
    if ([Convert]::ToBase64String($bytes) -cne $Encoded) { throw "internal child base64 is not canonical" }
    return $script:Utf8.GetString($bytes) | ConvertFrom-Json -ErrorAction Stop
}

function Invoke-InternalChild {
    $contract = ConvertFrom-ChildContract -Encoded $ChildContractBase64
    Assert-Properties -Value $contract -Label "internal child contract" -Required @(
        "claim_path", "codex_path", "controller_worktree", "events_path", "stderr_path",
        "last_message_path", "prompt_path", "child_start_path", "child_result_path"
    )
    $claimPath = Resolve-FuturePath -Path ([string]$contract.claim_path) -Label "claim path"
    $deadline = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $claimPath -PathType Leaf)) {
        if ($deadline.Elapsed.TotalSeconds -ge 15) { throw "immutable claim did not appear before child gate deadline" }
        Start-Sleep -Milliseconds 25
    }
    $claim = Read-BoundedJson -Path $claimPath
    $claimSha = Get-Sha256 -Path $claimPath
    if ([string]$claim.schema_version -cne "workstation_codex_mission_claim_v0.1") {
        throw "internal child claim schema mismatch"
    }
    $codex = Resolve-RegularFile -Path ([string]$contract.codex_path) -Label "Codex executable"
    $controller = Resolve-RegularDirectory -Path ([string]$contract.controller_worktree) -Label "controller worktree"
    $events = Resolve-FuturePath -Path ([string]$contract.events_path)
    $stderr = Resolve-FuturePath -Path ([string]$contract.stderr_path)
    $lastMessage = Resolve-FuturePath -Path ([string]$contract.last_message_path)
    $promptPath = Resolve-RegularFile -Path ([string]$contract.prompt_path) -Label "prompt"
    $startPath = Resolve-FuturePath -Path ([string]$contract.child_start_path)
    $resultPath = Resolve-FuturePath -Path ([string]$contract.child_result_path)
    foreach ($path in @($events, $stderr, $lastMessage, $startPath, $resultPath)) {
        if (Test-Path -LiteralPath $path) { throw "internal child output collision: $path" }
    }

    $eventStream = [IO.File]::Open($events, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
    $errorStream = [IO.File]::Open($stderr, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
    $process = $null
    $startedAt = $null
    try {
        . (Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1")
        $tokens = @(
            "-c", 'plugins."cloudflare@openai-curated-remote".mcp_servers.cloudflare-api.enabled=false',
            "exec", "--dangerously-bypass-approvals-and-sandbox", "--json",
            "--output-last-message", $lastMessage, "-"
        )
        $argumentString = ConvertTo-WeatherWindowsArgumentString -Tokens $tokens
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $codex
        $info.Arguments = $argumentString
        $info.WorkingDirectory = $controller
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $info
        if (-not $process.Start()) { throw "Codex process did not start" }
        $startedAt = $process.StartTime.ToUniversalTime().ToString("o")
        $startReceipt = [ordered]@{
            schema_version = "workstation_codex_child_start_v0.1"
            claim_sha256 = $claimSha
            child_root_pid = $PID
            codex_pid = $process.Id
            codex_started_at_utc = $startedAt
            started_at_utc = Get-UtcText
        }
        [void](Write-ImmutableJson -Path $startPath -Payload $startReceipt)
        $stdoutTask = $process.StandardOutput.BaseStream.CopyToAsync($eventStream)
        $stderrTask = $process.StandardError.BaseStream.CopyToAsync($errorStream)
        $promptBytes = [IO.File]::ReadAllBytes($promptPath)
        $process.StandardInput.BaseStream.Write($promptBytes, 0, $promptBytes.Length)
        $process.StandardInput.BaseStream.Flush()
        $process.StandardInput.Close()
        $process.WaitForExit()
        $stdoutTask.GetAwaiter().GetResult()
        $stderrTask.GetAwaiter().GetResult()
        $eventStream.Flush($true)
        $errorStream.Flush($true)
        $result = [ordered]@{
            schema_version = "workstation_codex_child_result_v0.1"
            claim_sha256 = $claimSha
            child_root_pid = $PID
            codex_pid = $process.Id
            codex_started_at_utc = $startedAt
            codex_ended_at_utc = Get-UtcText
            exit_code = $process.ExitCode
        }
        [void](Write-ImmutableJson -Path $resultPath -Payload $result)
        exit $process.ExitCode
    }
    finally {
        if ($process) { $process.Dispose() }
        $eventStream.Dispose()
        $errorStream.Dispose()
    }
}

function Invoke-StatusReader {
    $root = Resolve-RegularDirectory -Path $AttemptRoot -Label "attempt root"
    if ([string]::IsNullOrWhiteSpace($MissionId) -or [string]::IsNullOrWhiteSpace($ExpectedClaimSha256)) {
        throw "Status mode requires MissionId and ExpectedClaimSha256"
    }
    $claimPath = Join-Path $root "claim.json"
    if ((Get-Sha256 -Path $claimPath) -cne $ExpectedClaimSha256.ToLowerInvariant()) {
        throw "claim SHA-256 mismatch"
    }
    $claim = Read-BoundedJson -Path $claimPath
    Assert-Properties -Value $claim -Label "claim" -Required @(
        "schema_version", "mission_id", "mission_sha256", "attempt", "claim_path",
        "status_path", "heartbeat_path", "terminal_receipt_path", "runner_pid",
        "runner_started_at_utc", "host_boot_id", "deadline_utc"
    )
    if (
        [string]$claim.schema_version -cne "workstation_codex_mission_claim_v0.1" -or
        [string]$claim.mission_id -cne $MissionId -or
        [int]$claim.attempt -ne $Attempt -or
        [string]$claim.claim_path -cne $claimPath
    ) { throw "claim identity mismatch" }

    $status = Read-BoundedJson -Path ([string]$claim.status_path)
    $heartbeat = Read-BoundedJson -Path ([string]$claim.heartbeat_path)
    foreach ($pair in @(@($status, "status"), @($heartbeat, "heartbeat"))) {
        $value = $pair[0]
        Assert-Properties -Value $value -Label $pair[1] -Required @(
            "schema_version", "mission_id", "mission_sha256", "attempt", "claim_sha256",
            "state", "sequence", "observed_at_utc", "monotonic_elapsed_ms", "runner_pid",
            "child_root_pid", "codex_pid", "deadline_utc", "detail", "terminal_receipt_path"
        )
        if (
            [string]$value.schema_version -cne "workstation_codex_mission_state_v0.1" -or
            [string]$value.mission_id -cne $MissionId -or
            [string]$value.mission_sha256 -cne [string]$claim.mission_sha256 -or
            [int]$value.attempt -ne $Attempt -or
            [string]$value.claim_sha256 -cne $ExpectedClaimSha256.ToLowerInvariant() -or
            [int]$value.runner_pid -ne [int]$claim.runner_pid -or
            [string]$value.deadline_utc -cne [string]$claim.deadline_utc -or
            [long]$value.sequence -lt 1 -or
            [long]$value.monotonic_elapsed_ms -lt 0
        ) { throw "$($pair[1]) identity or monotonic contract mismatch" }
    }
    if ([math]::Abs([long]$status.sequence - [long]$heartbeat.sequence) -gt 1) {
        throw "status and heartbeat sequence diverged"
    }
    $observed = [DateTimeOffset]::Parse(
        [string]$heartbeat.observed_at_utc,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind
    )
    $ageSeconds = ([DateTimeOffset]::UtcNow - $observed.ToUniversalTime()).TotalSeconds
    $readerState = [string]$status.state
    if ($ageSeconds -gt $StaleAfterSeconds -and $null -eq $status.terminal_receipt_path) {
        if ((Get-BootId) -cne [string]$claim.host_boot_id) {
            $readerState = "ABRUPT_HOST_REBOOT"
        }
        elseif (-not (Test-ExactProcessAlive -ProcessId ([int]$claim.runner_pid) -StartedAtUtc ([string]$claim.runner_started_at_utc))) {
            $readerState = "ABRUPT_WRAPPER_EXIT_OR_CLIENT_DISCONNECT"
        }
        else { $readerState = "RUNNING_STALE" }
    }
    $summary = [ordered]@{
        schema_version = "workstation_codex_mission_status_read_v0.1"
        mission_id = $MissionId
        attempt = $Attempt
        claim_sha256 = $ExpectedClaimSha256.ToLowerInvariant()
        state = $readerState
        writer_state = [string]$status.state
        sequence = [math]::Max([long]$status.sequence, [long]$heartbeat.sequence)
        observed_at_utc = [string]$heartbeat.observed_at_utc
        age_seconds = [math]::Round($ageSeconds, 3)
        detail = [string]$status.detail
        terminal_receipt_path = $status.terminal_receipt_path
    }
    $summary | ConvertTo-Json -Depth 8
}

function Assert-ControllerIdentity {
    param([Parameter(Mandatory = $true)][string]$Controller)
    $head = Get-GitScalar -Arguments @("-C", $Controller, "rev-parse", "HEAD")
    $tree = Get-GitScalar -Arguments @("-C", $Controller, "rev-parse", "HEAD^{tree}")
    $status = Invoke-LocalGit -Arguments @("-C", $Controller, "status", "--porcelain=v1")
    if ($head -cne $ExpectedSourceTip.ToLowerInvariant() -or $tree -cne $ExpectedSourceTree.ToLowerInvariant() -or $status.Output.Count -ne 0) {
        throw "controller worktree identity drift"
    }
}

function Assert-Handback {
    param(
        [Parameter(Mandatory = $true)][string]$ClaimSha,
        [Parameter(Mandatory = $true)][string]$VerificationRoot
    )
    $resultRoot = Resolve-RegularDirectory -Path $ResultWorktree -Label "result worktree"
    $tip = Get-GitScalar -Arguments @("-C", $RepositoryRoot, "rev-parse", "--verify", $ResultRef)
    $head = Get-GitScalar -Arguments @("-C", $resultRoot, "rev-parse", "HEAD")
    $tree = Get-GitScalar -Arguments @("-C", $resultRoot, "rev-parse", "HEAD^{tree}")
    if ($tip -cne $head) { throw "result ref does not match result worktree HEAD" }
    $clean = Invoke-LocalGit -Arguments @("-C", $resultRoot, "status", "--porcelain=v1")
    if ($clean.Output.Count -ne 0) { throw "result worktree is not clean" }
    $ancestor = Invoke-LocalGit -Arguments @("-C", $RepositoryRoot, "merge-base", "--is-ancestor", $ExpectedSourceTip, $tip) -AllowedExitCodes @(0, 1)
    if ($ancestor.ExitCode -ne 0 -or $tip -ceq $ExpectedSourceTip) { throw "result tip does not descend from source" }

    $reportFull = Join-Path $resultRoot ($RequiredReportPath -replace '/', '\')
    $receiptFull = Join-Path $resultRoot ($RequiredReceiptPath -replace '/', '\')
    [void](Resolve-RegularFile -Path $reportFull -Label "required report")
    [void](Resolve-RegularFile -Path $receiptFull -Label "required receipt")
    foreach ($relative in @($RequiredReportPath, $RequiredReceiptPath)) {
        $tracked = Invoke-LocalGit -Arguments @("-C", $resultRoot, "ls-files", "--error-unmatch", "--", $relative)
        if ($tracked.Output.Count -ne 1) { throw "required handback path is not tracked: $relative" }
    }
    $receipt = Read-BoundedJson -Path $receiptFull -MaximumBytes 4194304
    Assert-Properties -Value $receipt -Label "handback receipt" -Required @(
        "schema_version", "mission_id", "mission_sha256", "source_tip", "source_tree",
        "base_tip", "base_tree", "result_ref", "implementation_tip", "implementation_tree",
        "report_path", "receipt_path", "bundle_path", "changed_paths", "tests",
        "script_sha256", "terminal_state_semantics", "measured_evidence",
        "remaining_reboot_boundary", "prohibited_actions", "external_binding"
    )
    $baseTree = Get-GitScalar -Arguments @("-C", $RepositoryRoot, "rev-parse", "$ExpectedBaseTip^{tree}")
    if (
        [string]$receipt.schema_version -cne "workstation_unattended_mission_handback_v0.1" -or
        [string]$receipt.mission_id -cne $MissionId -or
        [string]$receipt.mission_sha256 -cne $ExpectedMissionSha256.ToLowerInvariant() -or
        [string]$receipt.source_tip -cne $ExpectedSourceTip.ToLowerInvariant() -or
        [string]$receipt.source_tree -cne $ExpectedSourceTree.ToLowerInvariant() -or
        [string]$receipt.base_tip -cne $ExpectedBaseTip.ToLowerInvariant() -or
        [string]$receipt.base_tree -cne $baseTree -or
        [string]$receipt.result_ref -cne $ResultRef -or
        [string]$receipt.report_path -cne $RequiredReportPath -or
        [string]$receipt.receipt_path -cne $RequiredReceiptPath -or
        [string]$receipt.bundle_path -cne $BundlePath
    ) { throw "handback receipt identity mismatch" }
    Assert-Properties -Value $receipt.external_binding -Label "external binding" -Required @("rule", "final_tip", "final_tree", "bundle_sha256")
    if (
        [string]$receipt.external_binding.rule -cne "terminal_receipt_binds_final_result_tip_tree_and_bundle_sha256" -or
        $null -ne $receipt.external_binding.final_tip -or
        $null -ne $receipt.external_binding.final_tree -or
        $null -ne $receipt.external_binding.bundle_sha256
    ) { throw "handback receipt external binding rule is invalid" }
    $implementationTip = [string]$receipt.implementation_tip
    $implementationTree = Get-GitScalar -Arguments @("-C", $RepositoryRoot, "rev-parse", "$implementationTip^{tree}")
    if ($implementationTree -cne [string]$receipt.implementation_tree) { throw "implementation tree mismatch" }
    $implementationAncestor = Invoke-LocalGit -Arguments @("-C", $RepositoryRoot, "merge-base", "--is-ancestor", $implementationTip, $tip) -AllowedExitCodes @(0, 1)
    if ($implementationAncestor.ExitCode -ne 0) { throw "implementation tip is not an ancestor of result" }

    $actualChanged = @((Invoke-LocalGit -Arguments @("-C", $RepositoryRoot, "diff", "--name-only", "$ExpectedSourceTip..$tip")).Output | ForEach-Object { [string]$_ } | Sort-Object -CaseSensitive)
    $declaredChanged = @($receipt.changed_paths | ForEach-Object { [string]$_ } | Sort-Object -CaseSensitive)
    if ($actualChanged.Count -ne $declaredChanged.Count -or @(Compare-Object $actualChanged $declaredChanged -CaseSensitive).Count -ne 0) {
        throw "handback changed-path binding mismatch"
    }
    if (@($receipt.tests).Count -lt 1 -or @($receipt.tests | Where-Object { [string]$_.status -cne "PASS" }).Count -ne 0) {
        throw "handback test evidence is absent or non-passing"
    }
    foreach ($property in $receipt.script_sha256.PSObject.Properties) {
        $scriptRelative = [string]$property.Name
        $scriptFull = Join-Path $resultRoot ($scriptRelative -replace '/', '\')
        [void](Resolve-RegularFile -Path $scriptFull -Label "bound script")
        if ((Get-Sha256 -Path $scriptFull) -cne [string]$property.Value) { throw "bound script hash mismatch: $scriptRelative" }
    }
    if ([string]::IsNullOrWhiteSpace([string]$receipt.remaining_reboot_boundary) -or @($receipt.prohibited_actions).Count -lt 1) {
        throw "handback boundary declarations are incomplete"
    }

    $bundle = Resolve-RegularFile -Path $BundlePath -Label "complete bundle"
    $verifyRoot = $VerificationRoot
    if (Test-Path -LiteralPath $verifyRoot) { throw "bundle verification root collision" }
    [void](Invoke-LocalGit -Arguments @("init", "--bare", $verifyRoot))
    [void](Invoke-LocalGit -Arguments @("-C", $verifyRoot, "bundle", "verify", $bundle))
    [void](Invoke-LocalGit -Arguments @("-C", $verifyRoot, "fetch", "--no-tags", $bundle, "$ResultRef`:refs/heads/verified"))
    $bundledTip = Get-GitScalar -Arguments @("-C", $verifyRoot, "rev-parse", "refs/heads/verified")
    if ($bundledTip -cne $tip) { throw "bundle result tip mismatch" }
    foreach ($object in @($ExpectedBaseTip, $ExpectedSourceTip, $implementationTip, $tip)) {
        [void](Invoke-LocalGit -Arguments @("-C", $verifyRoot, "cat-file", "-e", "$object^{commit}"))
    }
    [void](Invoke-LocalGit -Arguments @("-C", $verifyRoot, "fsck", "--strict", "--full", "--no-dangling"))
    return [ordered]@{
        result_tip = $tip
        result_tree = $tree
        implementation_tip = $implementationTip
        implementation_tree = $implementationTree
        report_sha256 = Get-Sha256 -Path $reportFull
        handback_receipt_sha256 = Get-Sha256 -Path $receiptFull
        bundle_path = $bundle
        bundle_bytes = (Get-Item -LiteralPath $bundle).Length
        bundle_sha256 = Get-Sha256 -Path $bundle
        bundle_verify = "PASS"
        strict_fsck = "PASS"
        verification_root = $verifyRoot
        claim_sha256 = $ClaimSha
    }
}

function Invoke-Run {
    $requiredText = @{
        MissionId = $MissionId; MissionPath = $MissionPath; AttemptRoot = $AttemptRoot;
        RepositoryRoot = $RepositoryRoot; ControllerWorktree = $ControllerWorktree;
        ExpectedSourceTip = $ExpectedSourceTip; ExpectedSourceTree = $ExpectedSourceTree;
        ExpectedSourceParent = $ExpectedSourceParent; ExpectedBaseTip = $ExpectedBaseTip;
        ResultRef = $ResultRef; ResultWorktree = $ResultWorktree;
        RequiredReportPath = $RequiredReportPath; RequiredReceiptPath = $RequiredReceiptPath;
        BundlePath = $BundlePath; CodexPath = $CodexPath; DeadlineUtc = $DeadlineUtc
    }
    foreach ($entry in $requiredText.GetEnumerator()) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.Value)) { throw "Run mode requires $($entry.Key)" }
    }
    if ($ResultRef -cnotmatch '\Arefs/heads/codex/[A-Za-z0-9._/-]+\z' -or $ResultRef -match '\.\.' -or $ResultRef.EndsWith('/')) {
        throw "result ref must be one canonical codex branch ref"
    }
    foreach ($relative in @($RequiredReportPath, $RequiredReceiptPath)) {
        if ([IO.Path]::IsPathRooted($relative) -or $relative -notmatch '\A(?:[^./\\][^/\\]*/)*[^./\\][^/\\]*\z' -or $relative -match '\.\.') {
            throw "required handback path must be canonical repository-relative: $relative"
        }
    }
    $mission = Resolve-RegularFile -Path $MissionPath -Label "mission"
    $repo = Resolve-RegularDirectory -Path $RepositoryRoot -Label "repository root"
    $codex = Resolve-RegularFile -Path $CodexPath -Label "Codex executable"
    $attemptRootPath = Resolve-FuturePath -Path $AttemptRoot -Label "attempt root"
    $controller = Resolve-FuturePath -Path $ControllerWorktree -Label "controller worktree"
    $resultWorktreePath = Resolve-FuturePath -Path $ResultWorktree -Label "result worktree"
    $bundle = Resolve-FuturePath -Path $BundlePath -Label "bundle path"
    foreach ($future in @($attemptRootPath, $controller, $resultWorktreePath, $bundle)) {
        if (Test-Path -LiteralPath $future) { throw "create-only path already exists: $future" }
    }
    if ((Get-Sha256 -Path $mission) -cne $ExpectedMissionSha256.ToLowerInvariant()) { throw "mission SHA-256 mismatch" }
    if ((Get-Sha256 -Path $codex) -cne $ExpectedCodexSha256.ToLowerInvariant()) { throw "Codex SHA-256 mismatch" }

    $script:GitExecutable = Resolve-GitExecutable
    $origin = Get-GitScalar -Arguments @("-C", $repo, "remote", "get-url", "origin")
    if ($origin -cne "https://github.com/michaelbooth1/weather.git") { throw "canonical origin mismatch" }
    $sourceTip = Get-GitScalar -Arguments @("-C", $repo, "rev-parse", "$ExpectedSourceTip^{commit}")
    $sourceTree = Get-GitScalar -Arguments @("-C", $repo, "rev-parse", "$ExpectedSourceTip^{tree}")
    $parents = (Get-GitScalar -Arguments @("-C", $repo, "show", "-s", "--format=%P", $ExpectedSourceTip)) -split ' '
    if ($sourceTip -cne $ExpectedSourceTip.ToLowerInvariant() -or $sourceTree -cne $ExpectedSourceTree.ToLowerInvariant() -or $parents.Count -ne 1 -or $parents[0] -cne $ExpectedSourceParent.ToLowerInvariant()) {
        throw "source tip/tree/sole-parent identity mismatch"
    }
    $baseAncestor = Invoke-LocalGit -Arguments @("-C", $repo, "merge-base", "--is-ancestor", $ExpectedBaseTip, $ExpectedSourceTip) -AllowedExitCodes @(0, 1)
    if ($baseAncestor.ExitCode -ne 0) { throw "base is not an ancestor of source" }
    $resultRefProbe = Invoke-LocalGit -Arguments @("-C", $repo, "show-ref", "--verify", "--quiet", $ResultRef) -AllowedExitCodes @(0, 1)
    if ($resultRefProbe.ExitCode -eq 0) { throw "result ref already exists" }
    Assert-ArtifactOutsideWorktrees -Path $attemptRootPath -RepoRoot $repo
    Assert-ArtifactOutsideWorktrees -Path $bundle -RepoRoot $repo

    $deadline = [DateTimeOffset]::Parse(
        $DeadlineUtc,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind
    ).ToUniversalTime()
    if ($deadline.Offset -ne [TimeSpan]::Zero -or $deadline -le [DateTimeOffset]::UtcNow.AddSeconds(2) -or $deadline -gt [DateTimeOffset]::UtcNow.AddHours(24)) {
        throw "deadline must be an absolute UTC instant between 2 seconds and 24 hours ahead"
    }
    $deadlineText = $deadline.ToString("o", [Globalization.CultureInfo]::InvariantCulture)
    $startedAt = Get-UtcText
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $verificationRoot = Join-Path ([IO.Path]::GetTempPath()) (
        "wmr-{0}-a{1}-{2}.git" -f $ExpectedMissionSha256.Substring(0, 12).ToLowerInvariant(),
        $Attempt, $PID
    )
    $verificationRoot = Resolve-FuturePath -Path $verificationRoot -Label "bundle verification root"
    if (Test-Path -LiteralPath $verificationRoot) { throw "bundle verification root collision" }
    Assert-ArtifactOutsideWorktrees -Path $verificationRoot -RepoRoot $repo
    [void](New-Item -ItemType Directory -Path $attemptRootPath -ErrorAction Stop)
    $attemptRootPath = Resolve-RegularDirectory -Path $attemptRootPath -Label "attempt root"
    $paths = [ordered]@{
        claim = Join-Path $attemptRootPath "claim.json"
        status = Join-Path $attemptRootPath "status.json"
        heartbeat = Join-Path $attemptRootPath "heartbeat.json"
        terminal_receipt = Join-Path $attemptRootPath "terminal-receipt.json"
        events = Join-Path $attemptRootPath "events.jsonl"
        stderr = Join-Path $attemptRootPath "stderr.log"
        last_message = Join-Path $attemptRootPath "last-message.txt"
        prompt = Join-Path $attemptRootPath "prompt.txt"
        child_start = Join-Path $attemptRootPath "child-start.json"
        child_result = Join-Path $attemptRootPath "child-result.json"
        interrupt_request = Join-Path $attemptRootPath "interrupt-request.json"
    }
    $promptText = $Prompt
    if ([string]::IsNullOrWhiteSpace($promptText)) {
        $promptText = "Read and execute the complete sealed mission at $mission. Its required SHA-256 is $($ExpectedMissionSha256.ToLowerInvariant()). Read that exact file first; it is the sole authoritative task. Work autonomously through its stated falsifiers, bounded implementation, serial workstation verification, immutable handback, and complete verified bundle."
    }
    Write-ImmutableBytes -Path $paths.prompt -Bytes $script:Utf8.GetBytes($promptText + "`n")
    $previousLfsSkipSmudge = [Environment]::GetEnvironmentVariable(
        "GIT_LFS_SKIP_SMUDGE",
        "Process"
    )
    try {
        [Environment]::SetEnvironmentVariable("GIT_LFS_SKIP_SMUDGE", "1", "Process")
        [void](Invoke-LocalGit -Arguments @(
            "-C", $repo, "worktree", "add", "--detach", $controller, $ExpectedSourceTip
        ))
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            "GIT_LFS_SKIP_SMUDGE",
            $previousLfsSkipSmudge,
            "Process"
        )
    }
    $controller = Resolve-RegularDirectory -Path $controller -Label "controller worktree"
    Assert-ControllerIdentity -Controller $controller

    $runnerPath = Resolve-RegularFile -Path $PSCommandPath -Label "runner script"
    $jobHelper = Resolve-RegularFile -Path (Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1") -Label "Job helper"
    . $jobHelper
    $powerShellPath = Resolve-RegularFile -Path (Join-Path $PSHOME "powershell.exe") -Label "Windows PowerShell"
    $childContract = ConvertTo-ChildContract -Payload ([ordered]@{
        claim_path = $paths.claim; codex_path = $codex; controller_worktree = $controller;
        events_path = $paths.events; stderr_path = $paths.stderr;
        last_message_path = $paths.last_message; prompt_path = $paths.prompt;
        child_start_path = $paths.child_start; child_result_path = $paths.child_result
    })
    $childTokens = @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", $runnerPath, "-Mode", "InternalChild", "-ChildContractBase64", $childContract
    )
    $job = $null
    $child = $null
    $claimSha = $null
    $terminalState = "RUNNER_FAILURE"
    $terminalDetail = "runner did not reach child launch"
    $terminalExitCode = 26
    $validation = $null
    $teardownConfirmed = $false
    $sequence = 0L
    $lastObserved = [DateTimeOffset]::MinValue
    $script:missionSequence = 0L
    $script:missionLastObserved = [DateTimeOffset]::MinValue
    $codexPid = $null
    try {
        $job = New-WeatherKillOnCloseJob
        $child = Start-WeatherProcessInJob -Job $job -FilePath $powerShellPath `
            -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $childTokens) `
            -WorkingDirectory $controller
        $childStart = Get-ProcessStartUtc -ProcessId $child.Id
        $claim = [ordered]@{
            schema_version = "workstation_codex_mission_claim_v0.1"
            mission_id = $MissionId
            mission_path = $mission
            mission_sha256 = $ExpectedMissionSha256.ToLowerInvariant()
            attempt = $Attempt
            attempt_root = $attemptRootPath
            claimed_at_utc = $startedAt
            deadline_utc = $deadlineText
            heartbeat_seconds = $HeartbeatSeconds
            runner_pid = $PID
            runner_started_at_utc = Get-ProcessStartUtc -ProcessId $PID
            child_root_pid = $child.Id
            child_root_started_at_utc = $childStart
            host_id = Get-HostId
            principal_id = Get-PrincipalId
            host_boot_id = Get-BootId
            repository_root = $repo
            controller_worktree = $controller
            canonical_origin = $origin
            source_tip = $ExpectedSourceTip.ToLowerInvariant()
            source_tree = $ExpectedSourceTree.ToLowerInvariant()
            source_parent = $ExpectedSourceParent.ToLowerInvariant()
            base_tip = $ExpectedBaseTip.ToLowerInvariant()
            base_tree = Get-GitScalar -Arguments @("-C", $repo, "rev-parse", "$ExpectedBaseTip^{tree}")
            result_ref = $ResultRef
            result_worktree = $resultWorktreePath
            required_report_path = $RequiredReportPath
            required_receipt_path = $RequiredReceiptPath
            bundle_path = $bundle
            bundle_verification_root = $verificationRoot
            runner_path = $runnerPath
            runner_sha256 = Get-Sha256 -Path $runnerPath
            job_helper_path = $jobHelper
            job_helper_sha256 = Get-Sha256 -Path $jobHelper
            powershell_path = $powerShellPath
            powershell_sha256 = Get-Sha256 -Path $powerShellPath
            git_path = $script:GitExecutable
            git_sha256 = Get-Sha256 -Path $script:GitExecutable
            codex_path = $codex
            codex_sha256 = $ExpectedCodexSha256.ToLowerInvariant()
            prompt_path = $paths.prompt
            prompt_sha256 = Get-Sha256 -Path $paths.prompt
            claim_path = $paths.claim
            status_path = $paths.status
            heartbeat_path = $paths.heartbeat
            terminal_receipt_path = $paths.terminal_receipt
            events_path = $paths.events
            stderr_path = $paths.stderr
            last_message_path = $paths.last_message
            child_start_path = $paths.child_start
            child_result_path = $paths.child_result
            interrupt_request_path = $paths.interrupt_request
        }
        $claimSha = Write-ImmutableJson -Path $paths.claim -Payload $claim

        function Publish-State {
            param([string]$State, [string]$Detail, $TerminalReceiptPath = $null)
            $script:missionSequence += 1
            $now = [DateTimeOffset]::UtcNow
            if ($now -le $script:missionLastObserved) { $now = $script:missionLastObserved.AddTicks(1) }
            $script:missionLastObserved = $now
            $payload = [ordered]@{
                schema_version = "workstation_codex_mission_state_v0.1"
                mission_id = $MissionId
                mission_sha256 = $ExpectedMissionSha256.ToLowerInvariant()
                attempt = $Attempt
                claim_sha256 = $claimSha
                state = $State
                sequence = $script:missionSequence
                observed_at_utc = $now.ToString("o", [Globalization.CultureInfo]::InvariantCulture)
                monotonic_elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
                runner_pid = $PID
                child_root_pid = $child.Id
                codex_pid = $codexPid
                deadline_utc = $deadlineText
                detail = $Detail
                terminal_receipt_path = $TerminalReceiptPath
            }
            Publish-AtomicJson -Path $paths.heartbeat -Payload $payload -Sequence $script:missionSequence
            Publish-AtomicJson -Path $paths.status -Payload $payload -Sequence $script:missionSequence
        }

        Publish-State -State "RUNNING" -Detail "child root is Job-contained; waiting for Codex start receipt"
        while (-not $child.HasExited) {
            if (Test-Path -LiteralPath $paths.child_start -PathType Leaf) {
                try {
                    $childStartReceipt = Read-BoundedJson -Path $paths.child_start
                    if ([string]$childStartReceipt.claim_sha256 -ceq $claimSha) {
                        $codexPid = [int]$childStartReceipt.codex_pid
                    }
                }
                catch { }
            }
            if (Test-Path -LiteralPath $paths.interrupt_request -PathType Leaf) {
                $request = Read-BoundedJson -Path $paths.interrupt_request
                Assert-Properties -Value $request -Label "interrupt request" -Required @(
                    "schema_version", "mission_id", "attempt", "claim_sha256", "requested_at_utc", "reason"
                )
                if (
                    [string]$request.schema_version -cne "workstation_codex_mission_interrupt_v0.1" -or
                    [string]$request.mission_id -cne $MissionId -or [int]$request.attempt -ne $Attempt -or
                    [string]$request.claim_sha256 -cne $claimSha -or
                    [string]::IsNullOrWhiteSpace([string]$request.reason)
                ) { throw "interrupt request identity mismatch" }
                $terminalState = "INTERRUPTED"
                $terminalDetail = "validated create-only interrupt request"
                $terminalExitCode = 22
                break
            }
            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                $terminalState = "DEADLINE"
                $terminalDetail = "absolute mission deadline reached"
                $terminalExitCode = 21
                break
            }
            Publish-State -State "RUNNING" -Detail "mission child tree is active"
            [void]$child.WaitForExit($HeartbeatSeconds * 1000)
        }
        if ($child.HasExited -and $terminalState -eq "RUNNER_FAILURE") {
            if (-not (Test-Path -LiteralPath $paths.child_result -PathType Leaf)) {
                $terminalState = "CHILD_FAILURE"
                $terminalDetail = "child root exited without an immutable result"
                $terminalExitCode = 20
            }
            else {
                $childResult = Read-BoundedJson -Path $paths.child_result
                $codexPid = [int]$childResult.codex_pid
                if ([string]$childResult.claim_sha256 -cne $claimSha -or [int]$childResult.child_root_pid -ne $child.Id) {
                    $terminalState = "IDENTITY_DRIFT"
                    $terminalDetail = "child result identity mismatch"
                    $terminalExitCode = 24
                }
                elseif ([int]$childResult.exit_code -ne 0) {
                    $terminalState = "CHILD_FAILURE"
                    $terminalDetail = "Codex child returned exit code $([int]$childResult.exit_code)"
                    $terminalExitCode = 20
                }
                else {
                    $terminalState = "PENDING_VALIDATION"
                    $terminalDetail = "child exited zero; validating exact handback"
                    $terminalExitCode = 23
                }
            }
        }
        try {
            $job.TerminateAndWait(5000)
            $teardownConfirmed = $true
        }
        catch {
            $terminalState = "TEARDOWN_FAILURE"
            $terminalDetail = $_.Exception.Message
            $terminalExitCode = 25
        }
        if ($teardownConfirmed -and $terminalState -eq "PENDING_VALIDATION") {
            try {
                $finalPowerShellPath = Resolve-RegularFile `
                    -Path (Join-Path $PSHOME "powershell.exe") `
                    -Label "Windows PowerShell"
                $finalGitPath = Resolve-GitExecutable
                Assert-FinalExecutableIdentity `
                    -MissionPath $mission `
                    -CodexPath $codex `
                    -RunnerPath $runnerPath `
                    -JobHelperPath $jobHelper `
                    -PowerShellPath $finalPowerShellPath `
                    -GitPath $finalGitPath `
                    -Claim $claim
                Assert-ControllerIdentity -Controller $controller
            }
            catch {
                $terminalState = "IDENTITY_DRIFT"
                $terminalDetail = $_.Exception.Message
                $terminalExitCode = 24
            }
            if ($terminalState -eq "PENDING_VALIDATION") {
                try {
                    $validation = Assert-Handback -ClaimSha $claimSha -VerificationRoot $verificationRoot
                    $terminalState = "COMPLETE_VALIDATED"
                    $terminalDetail = "child exit, identity, handback, complete bundle, and strict fsck validated"
                    $terminalExitCode = 0
                }
                catch {
                    $terminalState = "INVALID_HANDBACK"
                    $terminalDetail = $_.Exception.Message
                    $terminalExitCode = 23
                }
            }
        }
    }
    catch [System.Management.Automation.PipelineStoppedException] {
        $terminalState = "INTERRUPTED"
        $terminalDetail = "PowerShell pipeline interruption received"
        $terminalExitCode = 22
        if ($job) {
            try { $job.TerminateAndWait(5000); $teardownConfirmed = $true }
            catch { $terminalState = "TEARDOWN_FAILURE"; $terminalDetail = $_.Exception.Message; $terminalExitCode = 25 }
        }
    }
    catch {
        $terminalState = "RUNNER_FAILURE"
        $terminalDetail = $_.Exception.Message
        $terminalExitCode = 26
        if ($job) {
            try { $job.TerminateAndWait(5000); $teardownConfirmed = $true }
            catch { $terminalState = "TEARDOWN_FAILURE"; $terminalDetail = $_.Exception.Message; $terminalExitCode = 25 }
        }
    }
    finally {
        if ($child) { $child.Dispose() }
        if ($job) { $job.Dispose() }
    }

    if ($null -ne $claimSha) {
        $sequence = $script:missionSequence
        $lastObserved = $script:missionLastObserved
        $terminal = [ordered]@{
            schema_version = "workstation_codex_mission_terminal_v0.1"
            mission_id = $MissionId
            mission_sha256 = $ExpectedMissionSha256.ToLowerInvariant()
            attempt = $Attempt
            claim_path = $paths.claim
            claim_sha256 = $claimSha
            state = $terminalState
            exit_code = $terminalExitCode
            detail = $terminalDetail
            started_at_utc = $startedAt
            ended_at_utc = Get-UtcText
            deadline_utc = $deadlineText
            runner_pid = $PID
            child_root_pid = [int]$claim.child_root_pid
            codex_pid = $codexPid
            child_tree_teardown_confirmed = $teardownConfirmed
            outputs = [ordered]@{}
            validation = $validation
        }
        foreach ($name in @("events", "stderr", "last_message", "child_start", "child_result", "interrupt_request")) {
            $path = $paths[$name]
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $terminal.outputs[$name] = [ordered]@{
                    path = $path
                    bytes = (Get-Item -LiteralPath $path).Length
                    sha256 = Get-Sha256 -Path $path
                }
            }
        }
        $terminalSha = Write-ImmutableJson -Path $paths.terminal_receipt -Payload $terminal
        $sequence += 1
        $terminalTime = [DateTimeOffset]::UtcNow
        if ($terminalTime -le $lastObserved) { $terminalTime = $lastObserved.AddTicks(1) }
        $terminalPayload = [ordered]@{
            schema_version = "workstation_codex_mission_state_v0.1"
            mission_id = $MissionId
            mission_sha256 = $ExpectedMissionSha256.ToLowerInvariant()
            attempt = $Attempt
            claim_sha256 = $claimSha
            state = $terminalState
            sequence = $sequence
            observed_at_utc = $terminalTime.ToString("o", [Globalization.CultureInfo]::InvariantCulture)
            monotonic_elapsed_ms = [long]$stopwatch.ElapsedMilliseconds
            runner_pid = $PID
            child_root_pid = [int]$claim.child_root_pid
            codex_pid = $codexPid
            deadline_utc = $deadlineText
            detail = $terminalDetail
            terminal_receipt_path = $paths.terminal_receipt
        }
        Publish-AtomicJson -Path $paths.heartbeat -Payload $terminalPayload -Sequence $sequence
        Publish-AtomicJson -Path $paths.status -Payload $terminalPayload -Sequence $sequence
        [pscustomobject]@{
            state = $terminalState
            exit_code = $terminalExitCode
            claim_sha256 = $claimSha
            terminal_receipt_sha256 = $terminalSha
            attempt_root = $attemptRootPath
        } | ConvertTo-Json -Compress
    }
    exit $terminalExitCode
}

switch ($Mode) {
    "InternalChild" { Invoke-InternalChild; break }
    "Status" { Invoke-StatusReader; break }
    "Run" { Invoke-Run; break }
}
