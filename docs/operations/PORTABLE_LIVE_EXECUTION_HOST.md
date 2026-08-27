# Portable International Live Execution Host

Status: canonical provisioning and relocation runbook.

This lane lets the attended Stage 0/1 lifecycle test run from a Windows PC
other than the dedicated capture host. It removes only dependencies that are
local to the 16 GB capture machine: its capture workers, execution tape,
streak state, and protected host-load timetable. It does not remove Git,
source, SDK, credential, identity, geography, account, balance, allowance,
zero-state, order, cancellation, deadline, or cleanup checks.

The live protocol remains owned by
[`INTERNATIONAL_MM_LIVE_PILOT.md`](INTERNATIONAL_MM_LIVE_PILOT.md). This file
owns only execution-host provisioning and relocation.

## Fixed profiles

| Profile | Intended machine | Local host gate |
| --- | --- | --- |
| `capture_colocated_v1` | Dedicated capture PC | Three capture workers, execution tape, streak, clock, reboot, shared lease, and `[00:30, 09:00) America/Toronto` containment |
| `portable_execution_v1` | Separate attended execution-only PC | Exact tracked Windows-installation and token-principal assignment, clock, reboot, and a host-global exclusive lease; no local capture/tape/streak dependency |

The profile is explicit and immutable in every session manifest, seal,
launcher, execution receipt, and predecessor lineage. It is never inferred
from RAM, time of day, a missing process, or user-layer Codex configuration.
The tracked `config/international_live_execution_host.json` registry is the
sole role authority: it names the dedicated capture installation and at most
one active portable Windows installation plus token principal. Its workload
admission is restricted to the three canonical
`InternationalLive-*` stage names and cannot carry Stage-A or historical
owner-exception inputs.

The public execution-host ID hashes the Windows `MachineGuid` under a
versioned domain. It is not a credential. Moving the checkout on one Windows
installation preserves the ID; moving to another PC or reinstalling Windows
changes it and intentionally invalidates all old manifests and launchers.

## Host requirements

- Windows x64 on local fixed or removable storage; no UNC, device, reparse, or
  redirected repository/SDK path.
- 64-bit CPython **3.11**. The ordinary application supports newer 3.11+
  versions, but the sealed live SDK wheelhouse is specifically `cp311-win_amd64`.
- A machine-wide Git for Windows installation registered at
  `HKLM\SOFTWARE\GitForWindows`, with its real `mingw64\bin\git.exe` payload
  and sibling `git-lfs.exe` present. A user-local/PATH-only Git is not the
  canonical live Git identity.
- A clean local clone whose checked-out `master`, tree, and freshly observed
  canonical `origin/master` are identical at the production-adopted live tip.
- A new venv built in that clone. Never copy a venv or its `.pth` files from
  another checkout.
- Windows Time synchronized with a successful sync no more than 24 hours old
  and no pending reboot.
- The current operator physically present with the PC in an eligible location,
  with no VPN, proxy, remote-location service, or circumvention. Repository
  timezone and machine name are not location evidence.
- A direct network configuration: no non-empty `HTTP_PROXY`, `HTTPS_PROXY`,
  `ALL_PROXY`, `NO_PROXY`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`,
  `SSL_CERT_FILE`, `SSL_CERT_DIR`, or `WEATHER_MARKET_REGISTRY`; Windows user
  proxy, PAC, and automatic proxy discovery disabled; and the machine-wide
  WinHTTP proxy set to direct. The builder, sealer, and sealed wrapper recheck
  these conditions around live Git proof and at both sides of every official
  geographic-eligibility request.

Do not copy `data/` from the capture PC. It is ignored local runtime state and
is not cross-host authority. A new execution host must nevertheless collect a
fresh, attempt-local public candidate substrate: selected-date event metadata,
weather/source status, observation state, CLOB tokens/books, economics, and a
strictly passing paper run. The live-pilot runbook gives the exact sequence.

## Clone and build the local environment

Use a writable, ordinary local path and an exact 64-bit Python 3.11
interpreter. The defaults below stay inside the current operator's local
application-data directory, so a standard user does not need permission to
create a drive-root directory. To relocate on the same Windows installation,
set `$weatherPortableRoot` to another new absolute path on fixed or removable
local media. The later status and sealing checks reject redirected paths:

```powershell
$ErrorActionPreference = "Stop"
$executionPolicy = Get-ExecutionPolicy -List
$executionPolicy | Format-Table -AutoSize
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
# Process scope ends with this PowerShell process. Keep this shell for the
# workflow, or repeat these three lines in every later shell.

function Get-VerifiedPortableLocalPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  $suppliedRoot = [IO.Path]::GetPathRoot($Path)
  if (-not [IO.Path]::IsPathRooted($Path) -or
      $suppliedRoot -cnotmatch '\A[A-Za-z]:\\\z') {
    throw "portable paths must be absolute"
  }
  $fullPath = [IO.Path]::GetFullPath($Path)
  $pathRoot = [IO.Path]::GetPathRoot($fullPath)
  $drive = [IO.DriveInfo]::new($pathRoot)
  if ($drive.DriveType -notin @(
      [IO.DriveType]::Fixed,
      [IO.DriveType]::Removable
    )) {
    throw "portable paths must use fixed or removable local media"
  }
  $cursor = $pathRoot
  foreach ($component in $fullPath.Substring($pathRoot.Length).Split(
      [char[]]@(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
      ),
      [StringSplitOptions]::RemoveEmptyEntries
    )) {
    $cursor = Join-Path $cursor $component
    if (-not (Test-Path -LiteralPath $cursor)) { break }
    $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "portable path contains a redirected entry"
    }
  }
  return $fullPath
}
$configuredPortableRoot = Get-Variable -Name weatherPortableRoot `
  -ValueOnly -ErrorAction SilentlyContinue
if ([string]::IsNullOrWhiteSpace([string]$configuredPortableRoot)) {
  $localApplicationData = [Environment]::GetFolderPath("LocalApplicationData")
  if ([string]::IsNullOrWhiteSpace($localApplicationData) -or
      -not [IO.Path]::IsPathRooted($localApplicationData) -or
      [IO.Path]::GetPathRoot($localApplicationData) -cnotmatch
        '\A[A-Za-z]:\\\z') {
    throw "current-user local application-data path is unavailable"
  }
  $weatherPortableRoot = Join-Path $localApplicationData "WeatherPortable"
} else {
  $weatherPortableRoot = [string]$configuredPortableRoot
}
$weatherPortableRoot = Get-VerifiedPortableLocalPath $weatherPortableRoot
$weatherRepositoryRoot = Join-Path $weatherPortableRoot "repository"
if (Test-Path -LiteralPath $weatherRepositoryRoot) {
  throw "portable repository destination must be new"
}
New-Item -ItemType Directory -Path $weatherPortableRoot -Force -ErrorAction Stop |
  Out-Null
$weatherPortableRoot = Get-VerifiedPortableLocalPath $weatherPortableRoot

$gitInstallRoots = @(
  foreach ($registryView in @(
      [Microsoft.Win32.RegistryView]::Registry64,
      [Microsoft.Win32.RegistryView]::Registry32
    )) {
    $gitBaseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
      [Microsoft.Win32.RegistryHive]::LocalMachine,
      $registryView
    )
    $gitRegistration = $null
    try {
      $gitRegistration = $gitBaseKey.OpenSubKey("SOFTWARE\GitForWindows", $false)
      if ($null -eq $gitRegistration) { continue }
      if ($gitRegistration.GetValueKind("InstallPath") -ne
          [Microsoft.Win32.RegistryValueKind]::String) {
        throw "machine-wide Git registration has an invalid install path"
      }
      $registeredRoot = [string]$gitRegistration.GetValue(
        "InstallPath", $null,
        [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
      )
      if ([string]::IsNullOrWhiteSpace($registeredRoot)) {
        throw "machine-wide Git registration has an empty install path"
      }
      [IO.Path]::GetFullPath($registeredRoot)
    }
    finally {
      if ($null -ne $gitRegistration) { $gitRegistration.Dispose() }
      $gitBaseKey.Dispose()
    }
  }
)
$gitInstallRoots = @($gitInstallRoots | Sort-Object -Unique)
if ($gitInstallRoots.Count -ne 1) {
  throw "exactly one machine-wide Git for Windows installation is required"
}
$gitInstallRoot = $gitInstallRoots[0]
$gitPayload = Join-Path $gitInstallRoot "mingw64\bin\git.exe"
$gitLfsPayload = Join-Path $gitInstallRoot "mingw64\bin\git-lfs.exe"
$gitLauncher = Join-Path $gitInstallRoot "cmd\git.exe"
if (
  -not (Test-Path -LiteralPath $gitPayload -PathType Leaf) -or
  -not (Test-Path -LiteralPath $gitLfsPayload -PathType Leaf) -or
  -not (Test-Path -LiteralPath $gitLauncher -PathType Leaf)
) {
  throw "machine-wide Git for Windows and Git LFS are unavailable"
}
& $gitPayload --version
if ($LASTEXITCODE -ne 0) { throw "canonical Git payload is unavailable" }
& $gitLfsPayload version
if ($LASTEXITCODE -ne 0) { throw "canonical Git LFS payload is unavailable" }

& $gitLauncher clone https://github.com/michaelbooth1/weather.git $weatherRepositoryRoot
if ($LASTEXITCODE -ne 0) { throw "canonical clone failed" }
$verifiedRepositoryRoot = Get-VerifiedPortableLocalPath $weatherRepositoryRoot
if ($verifiedRepositoryRoot -cne [IO.Path]::GetFullPath($weatherRepositoryRoot)) {
  throw "portable repository path identity changed after clone"
}
Set-Location -LiteralPath $weatherRepositoryRoot
& $gitLauncher switch master
if ($LASTEXITCODE -ne 0) { throw "master checkout failed" }
& $gitLauncher fetch --prune origin
if ($LASTEXITCODE -ne 0) { throw "canonical origin refresh failed" }
$originUrl = (& $gitLauncher remote get-url origin)
if ($LASTEXITCODE -ne 0 -or
    $originUrl -cne "https://github.com/michaelbooth1/weather.git") {
  throw "origin is not the canonical HTTPS repository"
}
$localTip = (& $gitLauncher rev-parse HEAD)
if ($LASTEXITCODE -ne 0) { throw "local tip query failed" }
$remoteTip = (& $gitLauncher rev-parse origin/master)
if ($LASTEXITCODE -ne 0 -or $localTip -cne $remoteTip) {
  throw "local master is not the freshly observed canonical production tip"
}

& $gitLauncher lfs pull --include="artifacts/models/hgb/*.pkl"
if ($LASTEXITCODE -ne 0) { throw "required HGB Git LFS pull failed" }
$trackedHgbPaths = @(& $gitLauncher ls-files -- "artifacts/models/hgb/*.pkl")
if ($LASTEXITCODE -ne 0) { throw "tracked HGB inventory failed" }
$trackedHgbPaths = @($trackedHgbPaths | Sort-Object)
$lfsRows = @(& $gitLauncher lfs ls-files --long --include="artifacts/models/hgb/*.pkl")
if ($LASTEXITCODE -ne 0) { throw "Git LFS HGB inventory failed" }
if ($trackedHgbPaths.Count -eq 0 -or $lfsRows.Count -ne $trackedHgbPaths.Count) {
  throw "tracked HGB and Git LFS inventories differ"
}
$materializedHgbPaths = @()
foreach ($row in $lfsRows) {
  if ([string]$row -cnotmatch '^(?<oid>[0-9a-f]{64}) \* (?<path>artifacts/models/hgb/[^/]+\.pkl)$') {
    throw "an HGB artifact remains a pointer or has an invalid Git LFS identity"
  }
  $relativePath = [string]$Matches.path
  $materializedHgbPaths += $relativePath
  if (-not (Test-Path -LiteralPath $relativePath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $relativePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        ([string]$Matches.oid).ToLowerInvariant()) {
    throw "an HGB artifact is absent or differs from its exact Git LFS object"
  }
}
if (@(Compare-Object $trackedHgbPaths @($materializedHgbPaths | Sort-Object) -CaseSensitive).Count -ne 0) {
  throw "materialized HGB paths do not equal the tracked HGB paths"
}

$basePython = "replace-with-absolute-path-to-python-3.11.exe"
$basePythonRoot = [IO.Path]::GetPathRoot($basePython)
if (-not [IO.Path]::IsPathRooted($basePython) -or
    $basePythonRoot -cnotmatch '\A[A-Za-z]:\\\z' -or
    -not (Test-Path -LiteralPath $basePython -PathType Leaf)) {
  throw "an absolute CPython 3.11 executable path is required"
}
$basePython = [IO.Path]::GetFullPath($basePython)
& $basePython -I -c "import struct,sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3,11) and struct.calcsize('P') * 8 == 64 else 2)"
if ($LASTEXITCODE -ne 0) { throw "Python must be exact 64-bit CPython 3.11" }
& $basePython -m venv venv
if ($LASTEXITCODE -ne 0) { throw "portable venv creation failed" }
.\venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed" }
.\venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "runtime dependency install failed" }
.\venv\Scripts\python.exe -m pip install -e ".[test]"
if ($LASTEXITCODE -ne 0) { throw "editable test dependency install failed" }
```

The Git LFS object-ID/hash comparison proves that each tracked HGB working file
is materialized rather than a pointer before any public substrate is built. The
live sealer later repeats exact Git, interpreter, source, and path checks. These
setup commands do not make a session ready.

## Move the public SDK substrate

The pinned SDK overlay and wheelhouse live outside Git and contain no secrets.
Export them on a machine where the exact substrate already validates, copy the
resulting directory by trusted local/removable media, then import it into the
current Windows user's profile on the destination. Create receipt directories
before invoking the tool; every receipt path is create-only and outside the
repository.

Use a new transfer ID and new bundle/receipt paths on every move. Reusing a
prior create-only namespace is an expected hard failure. Source host:

```powershell
$ErrorActionPreference = "Stop"
$sourceSdkReceiptRoot = Join-Path (
  [Environment]::GetFolderPath("LocalApplicationData")
) "WeatherPortable\sdk-receipts"
New-Item -ItemType Directory -Force $sourceSdkReceiptRoot -ErrorAction Stop |
  Out-Null
$transferId = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$sourceTransferMedia = "replace-with-existing-local-or-removable-media-root"
$bundleRoot = Join-Path $sourceTransferMedia "weather-international-live-sdk-$transferId"
$exportReceiptPath = Join-Path $sourceSdkReceiptRoot "export-$transferId.json"
& .\scripts\ops\portable_live_sdk.ps1 `
  -Command Export `
  -BundleRoot $bundleRoot `
  -ReceiptOut $exportReceiptPath `
  -Confirmation AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_EXPORT
if ($LASTEXITCODE -ne 0) { throw "public SDK export blocked" }
$exportReceipt = Get-Content -LiteralPath $exportReceiptPath -Raw |
  ConvertFrom-Json -ErrorAction Stop
if ($exportReceipt.status -cne "PASS") { throw "public SDK export did not pass" }
```

Destination host:

```powershell
$ErrorActionPreference = "Stop"
$destinationSdkReceiptRoot = Join-Path (
  [Environment]::GetFolderPath("LocalApplicationData")
) "WeatherPortable\sdk-receipts"
New-Item -ItemType Directory -Force $destinationSdkReceiptRoot -ErrorAction Stop |
  Out-Null
$transferId = "replace-with-the-source-transfer-id"
$destinationTransferMedia = "replace-with-existing-local-or-removable-media-root"
$bundleRoot = Join-Path $destinationTransferMedia "weather-international-live-sdk-$transferId"
$importReceiptPath = Join-Path $destinationSdkReceiptRoot "import-$transferId.json"
& .\scripts\ops\portable_live_sdk.ps1 `
  -Command Import `
  -BundleRoot $bundleRoot `
  -ReceiptOut $importReceiptPath `
  -Confirmation AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_IMPORT
if ($LASTEXITCODE -ne 0) { throw "public SDK import blocked" }
$importReceipt = Get-Content -LiteralPath $importReceiptPath -Raw |
  ConvertFrom-Json -ErrorAction Stop
if ($importReceipt.status -cne "PASS") { throw "public SDK import did not pass" }

$auditReceiptPath = Join-Path $destinationSdkReceiptRoot "installed-audit-$transferId.json"
& .\scripts\ops\portable_live_sdk.ps1 `
  -Command Audit `
  -ReceiptOut $auditReceiptPath
if ($LASTEXITCODE -ne 0) { throw "installed public SDK audit blocked" }
$auditReceipt = Get-Content -LiteralPath $auditReceiptPath -Raw |
  ConvertFrom-Json -ErrorAction Stop
if ($auditReceipt.status -cne "PASS") { throw "installed public SDK audit did not pass" }
```

The two media-root placeholders may be different drive letters. The directory
name and transfer ID must be unchanged across the copy.

Export and import use create-new/no-replace publication and validate every file
before and after movement. The current SDK layout has two independent roots,
so publication cannot be one filesystem rename. A power loss between those
renames can leave a partial installation. A retry resumes only when exactly
one root exists and every directory, file name, byte count, and hash in that
root still matches the trusted bundle; it publishes only the absent root and
then revalidates both. Any changed, extra, redirected, or otherwise ambiguous
partial state remains blocked without deleting or overwriting it.

The bundle explicitly contains no credentials and grants no network, exchange,
Scheduler, capture, or live-trading authority.

## Credentials and attempts are host-local

Windows Credential Manager entries are per Windows user and machine. Transfer
the independently retained source credential file through a separate private
channel, keep it outside Git, and apply a private ACL. Follow the importer
sequence in the live-pilot runbook on the destination. The first-session
builder accepts only a new `mm_live_credential_import_receipt_v0.4` generated
for this exact Windows installation and current token principal within two
hours by compare-only verification of all four existing entries with zero
credential-store mutation.

Never copy a prior host's credential receipt, attempt root, candidate,
manifest, launcher, seal, or predecessor receipt. Their absolute paths,
interpreter/source identities, timestamps, and execution-host ID are
intentionally local and expiring. Generate a completely new three-stage
attempt on every destination host.

## Enroll one active portable host

Run the offline audit below before credentials. On an unassigned new PC it
exits nonzero by design, but its JSON still reports `execution_host_id` and
`execution_principal_id`. Put those exact public hashes into
`config/international_live_execution_host.json`, change `assignment_status` to
`ASSIGNED`, review and merge that change as a new production tip, then pull
that exact tip on both PCs. Never copy the old host's hashes forward.

Once assigned, capture-colocated International live admission is disabled on
the capture PC, and every other host/principal is refused. Moving again is a
new reviewed assignment and production tip; this deauthorizes the old PC
across separate machines where a local mutex cannot coordinate.

## Offline host audit

Before any credential resolution or exchange contact, run:

```powershell
$ErrorActionPreference = "Stop"
$hostStatusOutput = & .\scripts\ops\international_live_execution_host_status.ps1 `
  -RepoRoot (Get-Location).Path `
  -Json
$hostStatusExit = $LASTEXITCODE
$hostStatus = $hostStatusOutput | ConvertFrom-Json -ErrorAction Stop
if (-not $hostStatus.execution_host_id -or
    -not $hostStatus.execution_principal_id) {
  throw "pre-enrollment status did not report public host/principal IDs"
}
# Before enrollment, one exact assignment-only blocker is expected. Refuse to
# enroll around a dedicated-host, media, path, clock, reboot, or network issue.
$expectedEnrollmentFlags = @(
  "no portable execution host is assigned in the production tip",
  "this host and Windows principal are not the active portable executor"
)
if ($hostStatusExit -eq 0) {
  if ($hostStatus.status -cne "PASS" -or @($hostStatus.flags).Count -ne 0) {
    throw "successful pre-enrollment status is internally inconsistent"
  }
} elseif ($hostStatusExit -eq 2) {
  if ($hostStatus.status -cne "BLOCKED" -or
      @($hostStatus.flags).Count -ne 1 -or
      [string]$hostStatus.flags[0] -cnotin $expectedEnrollmentFlags) {
    throw "pre-enrollment audit has a non-assignment blocker"
  }
} else {
  throw "pre-enrollment host audit failed"
}
```

A usable assigned portable host returns exit 0 with an empty `flags` list, its exact
execution-host ID and repository root, synchronized clock evidence, no pending
reboot, and explicit false values for credential access, exchange contact,
Scheduler mutation, and capture mutation. Any assignment, clock, reboot,
identity, or repository-media disagreement is a technical blocker. The SDK
audit and later manifest/seal inventory independently validate the exact SDK,
interpreter, Git executable, origin, source, and attempt paths; this offline
status command does not claim those later gates have passed.
The `public_candidate_substrate` field remains `NOT_EVALUATED`: this command is
deliberately offline and does not claim that market data or a paper quote is
ready.

After the exact assignment tip is merged and pulled, rerun and require a clean
terminal result:

```powershell
$ErrorActionPreference = "Stop"
$hostStatusOutput = & .\scripts\ops\international_live_execution_host_status.ps1 `
  -RepoRoot (Get-Location).Path `
  -Json
$hostStatusExit = $LASTEXITCODE
$hostStatus = $hostStatusOutput | ConvertFrom-Json -ErrorAction Stop
if ($hostStatusExit -ne 0 -or
    $hostStatus.status -cne "PASS" -or
    @($hostStatus.flags).Count -ne 0) {
  throw "assigned portable execution-host audit did not pass"
}
```

After that offline audit, return to the live-pilot runbook. Candidate/economics
collection, host-local credential comparison, official geographic eligibility,
account bootstrap, and every attended mutation literal remain action-time
gates. The portable lane permits a same-target-date session outside the
capture PC's `[00:30, 09:00)` timetable, but its fixed 240-second execution
envelope plus cleanup reserve may not cross the target-date boundary. Its
strict public paper proof uses `--config quote_ttl_seconds=600`, and the
reviewed launcher requires at least 180 seconds remaining at its boundary.
The local substrate preflight is valid for at most 600 seconds and its
constrained candidate plan for at most 300 seconds. Every attended confirmation
consumes the same absolute cutoff; none extends it. The portable wrapper also
requires 120 seconds before credential context and 60 seconds immediately
before mutation, so a fresh candidate must flow directly into its no-argument
launcher.

## Relocating again

For another checkout on the same Windows installation and token principal, the
host/principal assignment does not change. Build a clean clone and venv, prove
Git/Git-LFS and HGB materialization, run SDK `Audit` against the existing
current-user installation, create a fresh compare-only credential receipt, and
create a fresh candidate and all three attempts. Do not re-import the already
installed SDK roots.

For a different PC, Windows reinstall, or token principal, commit and merge a
new exact host/principal assignment, then repeat clone/venv provisioning,
Git/Git-LFS and HGB proof, SDK transfer/import under a new transfer namespace,
offline host audit, fresh public candidate collection, credential provisioning
and compare-only verification, and all three attempt builds. Do not edit an old
host ID or absolute path into existing evidence; the old production tip and all
old host receipts are designed to block.

## Update when

Update when the execution-host profiles or assignment, host/principal identity,
SDK layout or pin, Python ABI, credential receipt freshness, public substrate,
or relocation procedure changes.
