# Phase A, owner-attended, 2026-10-13 ~07:30-09:00 (capture host)

Generated from `docs/operations/HOST_PYTHON_UPGRADE_RUNBOOK.md` at branch `claude/decisions-pyup-20261012`
(file sha256 `238c4546668d202875ee74ac2c467def3adae8bbbb6a47b6614770cbcf378737`). The code is copied from the runbook by script, not retyped. If the landed
runbook differs, the landed runbook wins: regenerate the block from it.

Constants file: copy `constants.json` from this folder byte-for-byte to `$R\constants.json`
(sha256 `D498DBB3FAAF36196847C271EDA3640A457276ACFB9EDE3218CECA83ECF19EEF`). It holds only public installer facts.

Order:
1. One elevated PowerShell 5.1 window. Paste the section 6 header with the host's own paths
   (`$P`, `$R`, `$NewHome`; `$Stage` is unused in A).
2. P0, then A1 and A1b, A2, A3, A4 (launch), and the owner clicks through the installer, then the A4 checks.
3. Any NoGo stops the session. A4 failure after the installer ran: follow the runbook's "If A4 fails" list.

```powershell
$ErrorActionPreference = 'Stop'
$P       = '<production checkout>'                 # e.g. the WeatherSnapshotLoopSupervisor working directory
$Py      = Join-Path $P 'venv\Scripts\python.exe'
$R       = '<cutover record root, outside data\ and outside the checkout>'
$WH      = Join-Path $R 'wheelhouse'; $Inst = Join-Path $R 'installer'; $Tools = Join-Path $R 'tools'
$A       = Join-Path $R 'receipts-3110'
$NewHome = '<new 3.11.9 home, e.g. C:\Python\cp3119>'
$NewPy   = Join-Path $NewHome 'python.exe'
$Stage   = '<stage worktree next to the checkout>'; $StagePy = Join-Path $Stage 'venv\Scripts\python.exe'
$Old     = Join-Path $P 'venv-cp3110'
$Log     = Join-Path $R 'night.log'
New-Item -ItemType Directory -Force $R, $Tools, $A | Out-Null
$K = if (Test-Path -LiteralPath (Join-Path $R 'constants.json')) { Get-Content -LiteralPath (Join-Path $R 'constants.json') -Raw | ConvertFrom-Json }   # §6a
function Log($m){ $l = "{0:o} {1}" -f (Get-Date), $m; Add-Content -LiteralPath $Log -Value $l -Encoding utf8; Write-Host $l }
# The lease lives in the session's global scope. While $global:ReleaseOnNoGo is set (B0-B1e, and C1 until the C4 rename),
# every NoGo releases it; after the C4 rename it stays held for §R.
$global:Lease = $null; $global:ReleaseOnNoGo = $false
function Release-Lease { if ($global:Lease) { Exit-WeatherHeavyWorkloadLease -Lease $global:Lease; $global:Lease = $null; Log 'lease released' } }
function NoGo($m){ Log "NO-GO: $m"; if ($global:ReleaseOnNoGo) { $global:ReleaseOnNoGo = $false; Release-Lease }; throw "NO-GO: $m" }
function Sha($f){ (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToUpper() }
# Native calls whose stderr matters go through Invoke-Native. Never use 2>&1 or 2> on a native command while
# $ErrorActionPreference is 'Stop': Windows PowerShell 5.1 turns each stderr line into a terminating error.
function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$OutBase) {
  $quoted = foreach ($a in $Arguments) { if ($a -match '[\s"]') { '"' + ($a -replace '"','\"') + '"' } else { $a } }
  $p = Start-Process -FilePath $Exe -ArgumentList ($quoted -join ' ') -WorkingDirectory $P -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "$OutBase.out.txt" -RedirectStandardError "$OutBase.err.txt"
  $p.WaitForExit(); if ($null -eq $p.ExitCode) { NoGo "no exit code from $Exe" }
  Log ("native exit {0}: {1} {2}" -f $p.ExitCode, (Split-Path -Leaf $Exe), ($Arguments -join ' ')); [int]$p.ExitCode }
# Release readiness as parsed fields (release_lifecycle_cli prints JSON; a BLOCK goes to stderr with a non-zero exit)
function Get-ReleaseActive([string]$Exe, [string]$OutBase) {
  $code = Invoke-Native $Exe @('-m','weather.operations.release_lifecycle_cli','--repo-root',$P,'active') $OutBase
  $o = [string](Get-Content -LiteralPath "$OutBase.out.txt" -Raw); $e = [string](Get-Content -LiteralPath "$OutBase.err.txt" -Raw)
  # PASS prints indented JSON on stdout; BLOCK prints one JSON line on stderr (release_lifecycle_cli.py:191).
  # Take only that last JSON line from stderr, so a stray warning line cannot break the parse.
  $raw = if ($o.Trim()) { $o } else { @($e -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') }) | Select-Object -Last 1 }
  try { $j = $raw | ConvertFrom-Json } catch { NoGo "release active output is not JSON ($OutBase)" }
  $r = [pscustomobject]@{ exit=$code; status=[string]$j.status; error=[string]$j.error }
  $r | ConvertTo-Json | Set-Content -LiteralPath "$OutBase.json" -Encoding utf8; $r }
# G5/Q3: a U6 export registered at 00:35 can hold the lease until 01:25, so it must be disabled on Phase B and C nights
function Assert-NoU6At0035([string]$Tag) {
  $u6 = Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue
  if ($u6 -and [string]$u6.State -ne 'Disabled' -and @($u6.Triggers | Where-Object { [string]$_.StartBoundary -match 'T00:35' }).Count -gt 0) {
    NoGo "$Tag U6 export is registered at 00:35 and enabled (G5, Q3)" } }
# §11: the owner's recorded choice for a capture gap over 35 minutes; first token ACCEPT_OVERRUN or ROLLBACK_ON_OVERRUN
function Get-GapChoice { $c = if (Test-Path -LiteralPath "$R\gap-overrun.txt") { ((Get-Content -LiteralPath "$R\gap-overrun.txt" -TotalCount 1) -split '\s+')[0] }
  if ($c -notin 'ACCEPT_OVERRUN','ROLLBACK_ON_OVERRUN') { NoGo 'gap-overrun choice not recorded in $R\gap-overrun.txt (§11)' }; $c }
function Assert-CaseA($ra, $tag) {
  if ($ra.status -ne 'BLOCK' -or $ra.error -notlike '*active release pointer is missing*') { NoGo "$tag release is not case A: $($ra | ConvertTo-Json -Compress)" }
  if (Test-Path -LiteralPath (Join-Path $P 'artifacts\releases\current_release.json')) { NoGo "$tag active release pointer exists" } }
. (Join-Path $P 'scripts\ops\workload_admission.ps1')
. (Join-Path $P 'scripts\ops\memory_guard_status_reader.ps1')
Log "session start host=$env:COMPUTERNAME head=$(git -C $P rev-parse HEAD)"
```

```powershell
# P0. Preconditions (owner at the machine; elevated Windows PowerShell 5.1; after N8 has handed back)
$Freeze = '<freeze copy root, e.g. C:\PyFreeze\cp3110; must not exist>'
if (Test-Path -LiteralPath $NewHome) { NoGo 'NewHome exists' }
if (Test-Path -LiteralPath $Freeze) { NoGo 'freeze copy target exists' }
if ((Sha (Join-Path $R 'constants.json')) -ne 'D498DBB3FAAF36196847C271EDA3640A457276ACFB9EDE3218CECA83ECF19EEF') { NoGo 'constants.json is not the reviewed file' }
$K = Get-Content -LiteralPath (Join-Path $R 'constants.json') -Raw | ConvertFrom-Json
foreach ($f in 'h1-pythoncore.txt','h1-uninstall.txt','h3-tasks.csv','h5-release.txt') {
  if (-not (Test-Path -LiteralPath (Join-Path $R "host-reads\$f"))) { NoGo "host read $f missing (runbook section 4)" } }
if (((Get-Date) - (Get-Item -LiteralPath (Join-Path $R 'host-reads\h3-tasks.csv')).LastWriteTime).TotalHours -gt 24) { NoGo 'H3 is older than a day; re-run H3' }
if ((& $Py -VV) -notlike 'Python 3.11.0*') { NoGo 'prod venv is not 3.11.0' }
Log "PHASE A start constants=$(Sha (Join-Path $R 'constants.json'))"
```

```powershell
# A1. Receipts (Phase A runs before section T; section T ends with T-R)
& $Py -VV | Set-Content -LiteralPath "$A\VV.txt" -Encoding utf8
Copy-Item -LiteralPath (Join-Path $P 'venv\pyvenv.cfg') "$A\pyvenv.cfg"
$OldHome = ((Get-Content -LiteralPath "$A\pyvenv.cfg" | Where-Object { $_ -match '^\s*home\s*=' }) -replace '^\s*home\s*=\s*','').Trim()
$OldHome | Set-Content -LiteralPath "$R\oldhome.txt" -Encoding utf8
[Environment]::GetEnvironmentVariable('Path','Machine') | Set-Content "$A\PATH-machine.txt" -Encoding utf8
[Environment]::GetEnvironmentVariable('Path','User')    | Set-Content "$A\PATH-user.txt" -Encoding utf8
Get-ChildItem -LiteralPath $OldHome -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\' } |
  ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.FullName.Substring($OldHome.Length) } | Set-Content "$A\oldhome-sha256.txt" -Encoding utf8
& $Py -m pip freeze --all | Set-Content "$A\freeze-3110.txt" -Encoding utf8
Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" } |
  Set-Content "$A\pth-3110.txt" -Encoding utf8
Push-Location -LiteralPath $P
& $Py -c "import json; from weather.release_artifacts import capture_runtime_versions as c; print(json.dumps(c(), indent=1, sort_keys=True))" | Set-Content "$A\rtv-3110.json" -Encoding utf8
Pop-Location
Copy-Item -LiteralPath "$R\host-reads\h3-tasks.csv" "$A\tasks-venv.csv"   # §4 H3, refreshed if older than a day
```

```powershell
# A1b. Record the host paths (runbook section 6)
[ordered]@{ P = $P; R = $R; NewHome = $NewHome; OldHome = $OldHome; FreezeCopy = $Freeze } | ConvertTo-Json |
  Set-Content -LiteralPath "$R\paths.json" -Encoding utf8
```

```powershell
# A2. Disaster copy of the old home
robocopy $OldHome $Freeze /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NP /LOG:"$R\robocopy-oldhome.log"
if ($LASTEXITCODE -ge 8) { NoGo "robocopy exit $LASTEXITCODE" }
```

```powershell
# A3. Download and verify the installer (approved download)
if (Test-Path -LiteralPath $Inst) { NoGo 'installer dir exists; inspect first' }
New-Item -ItemType Directory $Inst | Out-Null
$Exe = Join-Path $Inst 'python-3.11.9-amd64.exe'
curl.exe -fsSL --proto '=https' --tlsv1.2 -o $Exe $K.installer_url; if ($LASTEXITCODE) { NoGo "curl $LASTEXITCODE" }
$len = (Get-Item -LiteralPath $Exe).Length; $md5 = (Get-FileHash -LiteralPath $Exe -Algorithm MD5).Hash.ToLower(); $sha = Sha $Exe
$sig = Get-AuthenticodeSignature -LiteralPath $Exe
Log "installer len=$len md5=$md5 sha256=$sha sig=$($sig.Status) thumb=$($sig.SignerCertificate.Thumbprint)"
if ($len -ne [int64]$K.installer_size) { NoGo 'size' }
if ($md5 -ne $K.installer_md5.ToLower()) { NoGo 'md5' }
if ($sha -ne $K.installer_sha256.ToUpper()) { NoGo 'sha256' }
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike "$($K.signer_subject_prefix)*" -or $sig.SignerCertificate.Thumbprint -ne $K.signer_thumbprint) { NoGo 'authenticode' }
```

```powershell
# A4. UAC install: set $AllUsers from H1 (1 if 3.11.0 is per-user, 0 if all-users)
$before = @{ M=[Environment]::GetEnvironmentVariable('Path','Machine'); U=[Environment]::GetEnvironmentVariable('Path','User') }
$AllUsers = '<1 or 0 from H1>'
$instArgs = @("InstallAllUsers=$AllUsers","TargetDir=$NewHome","DefaultAllUsersTargetDir=$NewHome","DefaultJustForMeTargetDir=$NewHome",
  'PrependPath=0','AppendPath=0','Include_launcher=0','InstallLauncherAllUsers=0','AssociateFiles=0','Shortcuts=0','CompileAll=0',
  'Include_symbols=0','Include_debug=0','Include_test=0','Include_doc=0','Include_tcltk=1','/log',"$R\install.log")
$proc = Start-Process -FilePath $Exe -ArgumentList $instArgs -Verb RunAs -Wait -PassThru; Log "installer exit $($proc.ExitCode)"
```

Owner, on the installer: the first page must say "Install Python 3.11.9" (Upgrade or Modify: click Cancel, NO-GO).
Choose Customize installation; confirm the scope, the target directory, and that the launcher, PATH and precompile are off.

```powershell
# A4 checks
if ($proc.ExitCode -ne 0) { NoGo "installer exit $($proc.ExitCode)" }
foreach ($p in $K.binaries.PSObject.Properties) { if ((Sha (Join-Path $NewHome $p.Name)) -ne $p.Value) { NoGo "binary $($p.Name)" } }
if ((& $NewPy -VV) -notlike "$($K.vv_prefix)*") { NoGo 'new -VV' }
$now = Get-ChildItem -LiteralPath $OldHome -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\' } | ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.FullName.Substring($OldHome.Length) }
if (Compare-Object (Get-Content "$A\oldhome-sha256.txt") $now) { NoGo 'OLD HOME CHANGED' }
if ((& $Py -VV) -notlike 'Python 3.11.0*') { NoGo 'prod venv no longer 3.11.0' }
if ([Environment]::GetEnvironmentVariable('Path','Machine') -ne $before.M -or [Environment]::GetEnvironmentVariable('Path','User') -ne $before.U) { NoGo 'PATH changed' }
$null = Invoke-Native $NewPy @('-I','-c','import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version); print(zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)') "$R\native-3119"
Log 'PHASE A PASS'
```
