# Shared action-token contract for training-window registration and attestation.
#
# The registration script serializes these exact tokens into Task Scheduler.
# The running training-window wrapper independently rebuilds the same list and
# passes a base64-encoded JSON copy to the delegated nightly child. Any drift in
# executable, token order, path, task name, or working directory then blocks
# producer attestation until the task is deliberately re-registered.

function Get-TrainingWindowTaskActionTokens {
    [CmdletBinding(DefaultParameterSetName = "Full")]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
        [Parameter(Mandatory = $true)]
        [string]$WindowTaskName,
        [Parameter(Mandatory = $true)]
        [string]$SchedulerTaskExecutable,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$RunAtLocal,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainTargetDate,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainParentReleaseId,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainTrainingAsOf,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainFeatureContractId,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainCorpusManifest,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainPitForecastCorpusManifest,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainCandidateDir,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string]$BaseRetrainRuntimeId,
        [Parameter(Mandatory = $true, ParameterSetName = "RestoreOnly")]
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
    } else {
        $tokens += @(
            "-RunAtLocal", $RunAtLocal,
            "-BaseRetrainTargetDate", $BaseRetrainTargetDate,
            "-BaseRetrainParentReleaseId", $BaseRetrainParentReleaseId,
            "-BaseRetrainTrainingAsOf", $BaseRetrainTrainingAsOf,
            "-BaseRetrainFeatureContractId", $BaseRetrainFeatureContractId,
            "-BaseRetrainCorpusManifest", $BaseRetrainCorpusManifest,
            "-BaseRetrainPitForecastCorpusManifest", $BaseRetrainPitForecastCorpusManifest,
            "-BaseRetrainCandidateDir", $BaseRetrainCandidateDir,
            "-BaseRetrainRuntimeId", $BaseRetrainRuntimeId
        )
    }
    return $tokens
}

function Resolve-TrainingWindowRunAtLocal {
    param(
        [Parameter(Mandatory = $true)][string]$RunAtLocal,
        [datetime]$Now = (Get-Date),
        [switch]$RequireFuture
    )

    $parsed = [datetime]::MinValue
    if (-not [datetime]::TryParseExact(
            $RunAtLocal,
            "yyyy-MM-ddTHH:mm:ss",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeLocal,
            [ref]$parsed
        )) {
        throw "RunAtLocal must use exact local yyyy-MM-ddTHH:mm:ss form."
    }
    if ($parsed.TimeOfDay -ne [timespan]::FromHours(1)) {
        throw "The capture-host training window is fixed to 01:00:00 local."
    }
    if ($RequireFuture -and $parsed -le $Now.AddMinutes(2)) {
        throw "RunAtLocal must be more than two minutes in the future."
    }
    return $parsed
}

function Resolve-TrainingWindowBaseRetrainBindings {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ScheduleLocalTime,
        [Parameter(Mandatory = $true)][string]$BaseRetrainTargetDate,
        [Parameter(Mandatory = $true)][string]$BaseRetrainParentReleaseId,
        [Parameter(Mandatory = $true)][string]$BaseRetrainTrainingAsOf,
        [Parameter(Mandatory = $true)][string]$BaseRetrainFeatureContractId,
        [Parameter(Mandatory = $true)][string]$BaseRetrainCorpusManifest,
        [Parameter(Mandatory = $true)][string]$BaseRetrainPitForecastCorpusManifest,
        [Parameter(Mandatory = $true)][string]$BaseRetrainCandidateDir,
        [Parameter(Mandatory = $true)][string]$BaseRetrainRuntimeId
    )

    function Require-TrainingBinding([string]$Value, [string]$Label) {
        if ([string]::IsNullOrWhiteSpace($Value)) { throw "$Label is required." }
        if ($Value.Contains('"')) { throw "$Label may not contain a double quote." }
        return $Value.Trim()
    }
    function Resolve-TrainingManifest([string]$Path, [string]$Label) {
        if ([string]::IsNullOrWhiteSpace($Path) -or
            -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "$Label must name an existing regular file: $Path"
        }
        return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    }

    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
    $parsedSchedule = [datetime]::MinValue
    if (-not [datetime]::TryParseExact(
            $ScheduleLocalTime,
            "HH:mm",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None,
            [ref]$parsedSchedule
        )) {
        throw "ScheduleLocalTime must use exact 24-hour HH:mm form."
    }
    $parsedTarget = [datetime]::MinValue
    if (-not [datetime]::TryParseExact(
            $BaseRetrainTargetDate,
            "yyyy-MM-dd",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None,
            [ref]$parsedTarget
        )) {
        throw "BaseRetrainTargetDate must be a real yyyy-MM-dd date."
    }
    $parsedTrainingAsOf = [DateTimeOffset]::MinValue
    if ($BaseRetrainTrainingAsOf -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$' -or
        -not [DateTimeOffset]::TryParse(
            $BaseRetrainTrainingAsOf,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None,
            [ref]$parsedTrainingAsOf
        )) {
        throw "BaseRetrainTrainingAsOf must be ISO-8601 with an explicit timezone."
    }
    $candidateDir = [IO.Path]::GetFullPath(
        (Require-TrainingBinding $BaseRetrainCandidateDir "BaseRetrainCandidateDir")
    )
    if (Test-Path -LiteralPath $candidateDir) {
        throw "BaseRetrainCandidateDir must not already exist: $candidateDir"
    }
    $repoPrefix = $RepoRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if ($candidateDir -ieq $RepoRoot -or
        $candidateDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "BaseRetrainCandidateDir must be outside the repository: $candidateDir"
    }
    return [pscustomobject]@{
        ScheduleLocalTime = $parsedSchedule.ToString("HH:mm")
        BaseRetrainTargetDate = $parsedTarget.ToString("yyyy-MM-dd")
        BaseRetrainParentReleaseId = (Require-TrainingBinding $BaseRetrainParentReleaseId "BaseRetrainParentReleaseId")
        BaseRetrainTrainingAsOf = $BaseRetrainTrainingAsOf.Trim()
        BaseRetrainFeatureContractId = (Require-TrainingBinding $BaseRetrainFeatureContractId "BaseRetrainFeatureContractId")
        BaseRetrainCorpusManifest = (Resolve-TrainingManifest $BaseRetrainCorpusManifest "Base-retrain corpus manifest")
        BaseRetrainPitForecastCorpusManifest = (Resolve-TrainingManifest $BaseRetrainPitForecastCorpusManifest "Base-retrain PIT forecast corpus manifest")
        BaseRetrainCandidateDir = $candidateDir
        BaseRetrainRuntimeId = (Require-TrainingBinding $BaseRetrainRuntimeId "BaseRetrainRuntimeId")
    }
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
