# Install the repository-owned host-load PreToolUse policy at the user layer.
#
# The user layer is intentional: the dedicated capture host must be protected
# even when Codex starts from a sibling worktree or the parent github folder,
# and a non-capture workstation must route heavy work through the shared-mutex
# wrapper while it can also serve as the portable live executor. Existing hook
# configuration is never overwritten implicitly.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$CodexRoot = (Join-Path $env:USERPROFILE ".codex")
)

$policyPath = Join-Path $RepoRoot ".codex\hooks\pre_tool_use_host_load.py"
if (-not (Test-Path -LiteralPath $policyPath -PathType Leaf)) {
    throw "Codex host-load policy not found at $policyPath"
}

$hookPath = Join-Path $CodexRoot "hooks.json"
if (Test-Path -LiteralPath $hookPath) {
    throw "Refusing to overwrite existing Codex hooks at $hookPath"
}
if (-not (Test-Path -LiteralPath $CodexRoot)) {
    New-Item -ItemType Directory -Path $CodexRoot -Force | Out-Null
}

$escapedPolicy = $policyPath.Replace('"', '\"')
$payload = [ordered]@{
    description = "Enforce capture-host limits and portable-live/workstation-heavy exclusion."
    hooks = [ordered]@{
        PreToolUse = @(
            [ordered]@{
                matcher = "^Bash$"
                hooks = @(
                    [ordered]@{
                        type = "command"
                        command = "python3 `"$escapedPolicy`""
                        commandWindows = "py -3 `"$escapedPolicy`""
                        timeout = 5
                        statusMessage = "Checking host-role load policy"
                    }
                )
            }
        )
    }
}

$tempPath = "{0}.{1}.tmp" -f $hookPath, [guid]::NewGuid().ToString("N")
try {
    $json = ($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($tempPath, $json, $utf8NoBom)
    Move-Item -LiteralPath $tempPath -Destination $hookPath
}
finally {
    if (Test-Path -LiteralPath $tempPath) { Remove-Item -LiteralPath $tempPath -Force }
}

$installedBytes = [System.IO.File]::ReadAllBytes($hookPath)
if (
    $installedBytes.Length -ge 3 -and
    $installedBytes[0] -eq 0xEF -and
    $installedBytes[1] -eq 0xBB -and
    $installedBytes[2] -eq 0xBF
) {
    throw "Codex hook readback unexpectedly contains a UTF-8 BOM"
}

$installed = Get-Content -Raw -LiteralPath $hookPath | ConvertFrom-Json
$handler = @($installed.hooks.PreToolUse)[0].hooks[0]
if (
    [string]@($installed.hooks.PreToolUse)[0].matcher -ne "^Bash$" -or
    [string]$handler.commandWindows -ne "py -3 `"$escapedPolicy`""
) {
    throw "Codex hook readback did not reproduce the installed policy"
}

Write-Host "Installed Codex host-load hook: $hookPath"
Write-Host "Codex will require review/trust of this exact hook definition on the next session."
