Set-StrictMode -Version Latest

function Get-WeatherIntegrationTrackedStatusRows {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    $rows = @(& git -C $RepositoryRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the production tracked working tree."
    }
    return @($rows | ForEach-Object { [string]$_ } | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    })
}

function Assert-WeatherIntegrationQuietMergePreconditions {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    if (-not [IO.Path]::IsPathRooted($RepositoryRoot)) {
        throw "Production repository root must be absolute."
    }
    $repo = [IO.Path]::GetFullPath($RepositoryRoot)
    if (-not (Test-Path -LiteralPath $repo -PathType Container)) {
        throw "Production repository root is missing: $repo"
    }
    $mergeHeadRows = @(& git -C $repo rev-parse --git-path MERGE_HEAD)
    if ($LASTEXITCODE -ne 0 -or $mergeHeadRows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$mergeHeadRows[0])) {
        throw "Could not resolve the production MERGE_HEAD path."
    }
    $mergeHeadPath = ([string]$mergeHeadRows[0]).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $repo $mergeHeadPath
    }
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        throw "Production has an in-progress merge (.git/MERGE_HEAD exists)."
    }

    $allowedTrackedDrift = @(
        "config/locations.json",
        "config/location_market_events.json"
    )
    $trackedRows = @(Get-WeatherIntegrationTrackedStatusRows -RepositoryRoot $repo)
    $observedDrift = New-Object System.Collections.Generic.List[string]
    foreach ($row in $trackedRows) {
        if ($row.Length -lt 4) {
            throw "Production tracked status contains an unreadable row."
        }
        $relativePath = $row.Substring(3).Trim().Replace("\", "/")
        if ($relativePath.Contains(" -> ") -or
            $allowedTrackedDrift -cnotcontains $relativePath) {
            throw "Production tracked drift is outside the exact generated-config allowlist: $relativePath"
        }
        $observedDrift.Add($relativePath)
    }
    if (@($observedDrift | Sort-Object -Unique).Count -ne $observedDrift.Count) {
        throw "Production tracked drift contains duplicate or ambiguous generated-config rows."
    }
    foreach ($relativePath in $allowedTrackedDrift) {
        $absolutePath = Join-Path $repo ($relativePath.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            throw "Required fleet-generated config file is missing: $relativePath"
        }
    }

    try {
        $pushTasks = @(Get-ScheduledTask `
            -TaskName "WeatherOneShotPush" -ErrorAction Stop)
    }
    catch {
        throw "WeatherOneShotPush is unavailable: $($_.Exception.Message)"
    }
    if ($pushTasks.Count -ne 1) {
        throw "WeatherOneShotPush must resolve to exactly one scheduled task; found $($pushTasks.Count)"
    }
    $pushTask = $pushTasks[0]
    $expectedTaskXmlSha256 =
        "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
    $taskXml = [string](Export-ScheduledTask `
        -TaskName "WeatherOneShotPush" -TaskPath "\" -ErrorAction Stop)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $actualTaskXmlSha256 = -join @(
            $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskXml)) |
                ForEach-Object { $_.ToString("x2") }
        )
    }
    finally { $algorithm.Dispose() }
    if ($actualTaskXmlSha256 -ne $expectedTaskXmlSha256) {
        throw "WeatherOneShotPush task XML changed from its reviewed exact contract."
    }

    $pushActions = @($pushTask.Actions)
    $expectedSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $expectedWorkingDirectory = $repo.TrimEnd("\")
    $actualWorkingDirectory = try {
        [IO.Path]::GetFullPath([string]$pushActions[0].WorkingDirectory).TrimEnd("\")
    }
    catch { "" }
    $expectedArguments =
        '/c git -C c:\Users\micha\Desktop\github\weather push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1'
    if ([string]$pushTask.TaskPath -cne "\" -or
        [string]$pushTask.State -cne "Ready" -or
        -not [bool]$pushTask.Settings.Enabled -or
        [string]$pushTask.Principal.UserId -ine "micha" -or
        $currentSid -cne $expectedSid -or
        [string]$pushTask.Principal.LogonType -cne "Interactive" -or
        [string]$pushTask.Principal.RunLevel -cne "Limited" -or
        $pushActions.Count -ne 1 -or
        [string]$pushActions[0].Execute -ine "cmd.exe" -or
        [string]$pushActions[0].Arguments -ine $expectedArguments -or
        $actualWorkingDirectory -ine $expectedWorkingDirectory) {
        throw "WeatherOneShotPush is not exactly bound to the enabled current-user Interactive/Limited publication contract."
    }

    return [pscustomobject][ordered]@{
        merge_head_path = [IO.Path]::GetFullPath($mergeHeadPath)
        tracked_drift = @($observedDrift | ForEach-Object { $_ })
        required_generated_configs = @($allowedTrackedDrift)
        one_shot_push_task_name = "WeatherOneShotPush"
        one_shot_push_task_xml_sha256 = $actualTaskXmlSha256
        checked_at_local = (Get-Date).ToString("o")
    }
}
