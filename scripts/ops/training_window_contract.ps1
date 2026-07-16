# Shared action-token contract for training-window registration and attestation.
#
# The registration script serializes these exact tokens into Task Scheduler.
# The running training-window wrapper independently rebuilds the same list and
# passes a base64-encoded JSON copy to the delegated nightly child. Any drift in
# executable, token order, path, task name, or working directory then blocks
# producer attestation until the task is deliberately re-registered.

function Get-TrainingWindowTaskActionTokens {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
        [Parameter(Mandatory = $true)]
        [string]$WindowTaskName,
        [Parameter(Mandatory = $true)]
        [string]$SchedulerTaskExecutable,
        [switch]$RestoreOnly
    )

    $tokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $ScriptPath,
        "-RepoRoot", $RepoRoot,
        "-WindowTaskName", $WindowTaskName,
        "-SchedulerTaskExecutable", $SchedulerTaskExecutable
    )
    if ($RestoreOnly) {
        $tokens += "-RestoreOnly"
    }
    return $tokens
}

function ConvertTo-ScheduledTaskArgumentString {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Tokens
    )

    $encoded = foreach ($token in $Tokens) {
        $value = [string]$token
        if ($value.Contains('"')) {
            throw "Scheduled-task action tokens may not contain a double quote: $value"
        }
        if ($value -match '\s') {
            if ($value.EndsWith('\')) {
                throw "A quoted scheduled-task action token may not end in a backslash: $value"
            }
            '"{0}"' -f $value
        } elseif ($value.Length -eq 0) {
            '""'
        } else {
            $value
        }
    }
    return ($encoded -join " ")
}

function ConvertTo-SchedulerArgumentContract {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Tokens
    )

    $json = ConvertTo-Json -InputObject @($Tokens) -Compress
    return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
}
