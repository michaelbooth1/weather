[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Audit", "Export", "Import")]
    [string]$Command,

    [string]$BundleRoot,

    [Parameter(Mandatory = $true)]
    [string]$ReceiptOut,

    [string]$ProfileRoot,

    [string]$Confirmation,

    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-LocalPortableSdkPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Path.IndexOf([char]0) -ge 0 -or
        $Path.Replace('/', '\').StartsWith('\\')) {
        throw "$Label must not use a network or device path."
    }
    $suppliedRoot = [IO.Path]::GetPathRoot($Path)
    if (-not [IO.Path]::IsPathRooted($Path) -or
        $suppliedRoot -cnotmatch '\A[A-Za-z]:\\\z') {
        throw "$Label must be an absolute local-drive path."
    }
    $full = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetPathRoot($full)
    try { $driveType = ([IO.DriveInfo]::new($root)).DriveType }
    catch { throw "$Label drive type is unavailable." }
    if ($driveType -notin @([IO.DriveType]::Fixed, [IO.DriveType]::Removable)) {
        throw "$Label must be on fixed or removable local media."
    }
    return $full
}

function Assert-NoPortableSdkReparseAncestor {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $root = [IO.Path]::GetPathRoot($Path)
    $cursor = $root
    $relative = $Path.Substring($root.Length)
    foreach ($component in $relative.Split(
            [char[]]@(
                [IO.Path]::DirectorySeparatorChar,
                [IO.Path]::AltDirectorySeparatorChar
            ),
            [StringSplitOptions]::RemoveEmptyEntries
        )) {
        $cursor = Join-Path $cursor $component
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($null -eq $item) { break }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label contains a redirected path entry."
        }
    }
}

$repoRoot = Resolve-LocalPortableSdkPath `
    -Path (Join-Path $PSScriptRoot "..\..") `
    -Label "repository root"
Assert-NoPortableSdkReparseAncestor -Path $repoRoot -Label "repository root"
$sourceRoot = Join-Path $repoRoot "src"
$manifestPath = Join-Path $PSScriptRoot "international_live_templates\sdk_overlay_manifest.json"
$manifestSha256 = "2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13"
$exportLiteral = "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_EXPORT"
$importLiteral = "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_IMPORT"

if (-not $PythonPath) {
    $repoPython = Join-Path $repoRoot "venv\Scripts\python.exe"
    $repoPythonItem = Get-Item `
        -LiteralPath $repoPython `
        -Force `
        -ErrorAction SilentlyContinue
    if ($null -ne $repoPythonItem -and
        -not $repoPythonItem.PSIsContainer -and
        ($repoPythonItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
        $PythonPath = $repoPython
    }
    else {
        throw "CPython 3.11 x64 is required; pass its absolute local path with -PythonPath."
    }
}

$PythonPath = Resolve-LocalPortableSdkPath -Path $PythonPath -Label "PythonPath"
Assert-NoPortableSdkReparseAncestor -Path $PythonPath -Label "PythonPath"
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "PythonPath is not an existing file: $PythonPath"
}

$ReceiptOut = Resolve-LocalPortableSdkPath -Path $ReceiptOut -Label "ReceiptOut"
Assert-NoPortableSdkReparseAncestor -Path $ReceiptOut -Label "ReceiptOut"
if ($BundleRoot) {
    $BundleRoot = Resolve-LocalPortableSdkPath -Path $BundleRoot -Label "BundleRoot"
    Assert-NoPortableSdkReparseAncestor -Path $BundleRoot -Label "BundleRoot"
}
if ($ProfileRoot) {
    $ProfileRoot = Resolve-LocalPortableSdkPath -Path $ProfileRoot -Label "ProfileRoot"
    Assert-NoPortableSdkReparseAncestor -Path $ProfileRoot -Label "ProfileRoot"
}

$moduleBootstrap = @'
import runpy
import sys
sys.dont_write_bytecode = True
source_root = sys.argv.pop(1)
sys.path.insert(0, source_root)
# PowerShell 5.1's native argument marshaller strips embedded double quotes.
# Python single-quoted literals preserve this fixed module bootstrap exactly.
runpy.run_module('weather.market.live_sdk_portability', run_name='__main__')
'@

$arguments = [Collections.Generic.List[string]]::new()
$arguments.Add("-I")
$arguments.Add("-S")
$arguments.Add("-B")
$arguments.Add("-c")
$arguments.Add($moduleBootstrap)
$arguments.Add($sourceRoot)

switch ($Command) {
    "Audit" {
        $arguments.Add("audit")
        if ($BundleRoot) {
            $arguments.Add("--bundle-root")
            $arguments.Add($BundleRoot)
        }
        else {
            $arguments.Add("--manifest")
            $arguments.Add($manifestPath)
            $arguments.Add("--expected-manifest-sha256")
            $arguments.Add($manifestSha256)
            if ($ProfileRoot) {
                $arguments.Add("--profile-root")
                $arguments.Add($ProfileRoot)
            }
        }
    }
    "Export" {
        if (-not $BundleRoot) {
            throw "Export requires -BundleRoot."
        }
        if ($Confirmation -cne $exportLiteral) {
            throw "Export requires the exact public, non-secret SDK export confirmation."
        }
        $arguments.Add("export")
        $arguments.Add("--manifest")
        $arguments.Add($manifestPath)
        $arguments.Add("--expected-manifest-sha256")
        $arguments.Add($manifestSha256)
        $arguments.Add("--bundle-root")
        $arguments.Add($BundleRoot)
        $arguments.Add("--confirmation")
        $arguments.Add($Confirmation)
    }
    "Import" {
        if (-not $BundleRoot) {
            throw "Import requires -BundleRoot."
        }
        if ($Confirmation -cne $importLiteral) {
            throw "Import requires the exact public, non-secret SDK import confirmation."
        }
        if ($ProfileRoot) {
            throw "Import is current-user-only and does not accept -ProfileRoot."
        }
        $arguments.Add("import")
        $arguments.Add("--bundle-root")
        $arguments.Add($BundleRoot)
        $arguments.Add("--confirmation")
        $arguments.Add($Confirmation)
    }
}

$arguments.Add("--receipt-out")
$arguments.Add($ReceiptOut)

& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Public SDK $Command failed with exit $LASTEXITCODE."
}
