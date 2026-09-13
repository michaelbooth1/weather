# A reviewed qualification binds one executable, not the number of Git paths
# exposed by an interactive or S4U PATH. Keep record validation separate from
# current-file validation so historical receipts remain readable after upgrades.

function Assert-WeatherGitExecutableIdentityRecord {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object]$Identity)

    foreach ($name in @("path", "sha256", "file_version")) {
        $property = $Identity.PSObject.Properties[$name]
        if ($null -eq $property -or $property.Value -isnot [string] -or
            [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "Git executable identity requires a non-empty string: $name"
        }
    }
    if ([string]$Identity.path -notmatch '^[A-Za-z]:[\\/]' -or
        [IO.Path]::GetFileName([string]$Identity.path) -ine "git.exe" -or
        [string]$Identity.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "Git executable identity requires a local absolute git.exe path and lowercase SHA256."
    }
}

function Get-WeatherGitExecutableIdentity {
    [CmdletBinding()]
    param([string]$Path = "")

    if ([string]::IsNullOrWhiteSpace($Path)) {
        # Selection occurs once, while preparing the reviewable manifest.
        # Runtime callers must supply the frozen identity instead of reselecting.
        $commands = @(Get-Command git.exe -CommandType Application -All -ErrorAction Stop)
        if ($commands.Count -eq 0 -or
            [string]$commands[0].CommandType -cne "Application" -or
            [string]::IsNullOrWhiteSpace([string]$commands[0].Source)) {
            throw "No regular Git Application is available for manifest preparation."
        }
        $Path = [string]$commands[0].Source
    }
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or
        [IO.Path]::GetFileName($Path) -ine "git.exe") {
        throw "Selected Git must be a local absolute git.exe path."
    }
    $resolved = [IO.Path]::GetFullPath($Path)
    $item = Get-Item -LiteralPath $resolved -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Selected Git must be a regular file, not a directory or reparse point."
    }
    $parent = $item.Directory
    while ($null -ne $parent) {
        if (($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Selected Git may not traverse a reparse-point directory."
        }
        $parent = $parent.Parent
    }
    $identity = [pscustomobject][ordered]@{
        path = $resolved
        sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        file_version = [string]$item.VersionInfo.FileVersion
    }
    Assert-WeatherGitExecutableIdentityRecord -Identity $identity
    return $identity
}

function Assert-WeatherGitExecutableIdentity {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object]$Identity)

    Assert-WeatherGitExecutableIdentityRecord -Identity $Identity
    $actual = Get-WeatherGitExecutableIdentity -Path ([string]$Identity.path)
    if (-not [string]::Equals(
            [string]$actual.path, [string]$Identity.path,
            [StringComparison]::OrdinalIgnoreCase
        ) -or [string]$actual.sha256 -cne [string]$Identity.sha256 -or
        [string]$actual.file_version -cne [string]$Identity.file_version) {
        throw "Selected Git executable identity changed after review; create a new attempt."
    }
    return [string]$actual.path
}
