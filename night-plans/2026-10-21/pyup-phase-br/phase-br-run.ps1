# phase-br-run.ps1 - host Python upgrade B-R: requalify the 3.11.9 stage venv on a moved tip.
# Night 10-20/21 (morning date 2026-10-21), capture host, ONE elevated Windows PowerShell 5.1 window.
# Source: docs/operations/HOST_PYTHON_UPGRADE_RUNBOOK.md, section "B-R" (claude/pyup-c-1021-review-20261019),
# with the section 6 header, B0, B1c, B1d, B1e, B2 and B3 copied from the landed runbook. If the landed runbook
# differs, the runbook wins: regenerate this file.
#
# What it does (fail-closed; any gate failure = NO-GO, exit 1):
#   P   read-only preconditions: night date, HEAD pinned to -ExpectedHead, clean tree, Phase A/B files,
#       wheelhouse manifest unchanged, masked 3.11.0 freeze unchanged, rtv direct dependencies unchanged,
#       G5 and the exclusive-night task list, lease free, disk, git binding, suite parameters, release case A.
#   B0  window 00:30-02:00, shared lease (workload py3119_requal), held through B1e.
#   B1c new stage worktree at -ExpectedHead (new path, new py3119-qual-<night> branch), stage venv built
#       OFFLINE from the Phase B wheelhouse (pip --isolated --no-index --find-links only; no download step exists).
#   B1d Test-Venv, B1e model-load smoke, lease released.
#   B2  bounded suite (its own lease; start by 03:00; runtime capped to end by 04:45; 09:00 hard teardown is the
#       suite's own). The suite gives every chunk an explicit --basetemp under %SystemDrive%\pt and deletes it;
#       this wrapper re-checks for leftovers of this run and removes them.
#   B3  release case A; then qualification.json is replaced ONLY on PASS (atomic), with the new tip, the venv
#       identity and the suite receipt sha. The previous qualification.json is archived first.
#
# -DryRun (or -WhatIf) runs every P gate read-only, writes nothing (no record dir, no night.log line, no lease,
# no worktree, no venv), reports each gate, and exits 0 only if every non-window gate passes. Window gates
# (night date, 00:30-02:00) are reported as informational in a dry run.
#
# Downloads: none. Network: none, except what the bounded suite's own tests do (unchanged from Phase B).
# Exit: 0 = PASS (or dry run clean); 1 = NO-GO or error. The lease is released on every exit path.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$ProductionRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedHead,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$NightDate,
    [string]$RecordRoot = 'C:\pyup\cp3119',
    [string]$NewHome = 'C:\Program Files\Python311-cp3119',
    [string]$StagePath = '',
    [string]$GitExe = 'C:\Program Files\Git\cmd\git.exe',
    [ValidatePattern('^[0-9a-fA-F]{64}$')][string]$GitSha = '5385ff9ae361ca41e7a31b335fc0d81f2de9c35fc62a165c5e34850d837b59cc',
    [string]$GitVer = '2.45.2.windows.1',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Off
$Dry = $DryRun.IsPresent -or [bool]$WhatIfPreference
$WhatIfPreference = $false          # the gates below decide what is written; never half-apply cmdlets
$ExpectedHead = $ExpectedHead.ToLowerInvariant()
$GitSha = $GitSha.ToUpperInvariant()
$exitCode = 1

# ---- section 6 header values (host facts; Phase B values as defaults) ----
$P       = (Resolve-Path -LiteralPath $ProductionRoot).Path.TrimEnd('\')
$Py      = Join-Path $P 'venv\Scripts\python.exe'
$R       = $RecordRoot.TrimEnd('\')
$WH      = Join-Path $R 'wheelhouse'
$A       = Join-Path $R 'receipts-3110'
$NewPy   = Join-Path $NewHome 'python.exe'
if (-not $StagePath) { $StagePath = Join-Path (Split-Path -Parent $P) 'weather-py3119-stage-br' }
$Stage   = $StagePath.TrimEnd('\'); $StagePy = Join-Path $Stage 'venv\Scripts\python.exe'
$Log     = Join-Path $R 'night.log'
$QBranch = 'py3119-qual-' + ($NightDate -replace '-', '')
$BRDir   = Join-Path $R ('br-' + $NightDate + '-' + (Get-Date -Format HHmmss))
$OldHome = $null; $K = $null
$global:Lease = $null; $global:ReleaseOnNoGo = $false
$script:GateFails = New-Object System.Collections.Generic.List[string]
$script:DryTemp = $null

function Log($m) { $l = "{0:o} {1}{2}" -f (Get-Date), $(if ($Dry) { 'DRY ' } else { '' }), $m
  if (-not $Dry) { Add-Content -LiteralPath $Log -Value $l -Encoding utf8 }; Write-Host $l }
function Release-Lease { if ($global:Lease) { Exit-WeatherHeavyWorkloadLease -Lease $global:Lease; $global:Lease = $null; Log 'lease released' } }
function NoGo($m) { Log "NO-GO: $m"; if ($global:ReleaseOnNoGo) { $global:ReleaseOnNoGo = $false; Release-Lease }; throw "NO-GO: $m" }
function Sha($f) { (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToUpper() }
function Mask-Editable([string[]]$Lines) { foreach ($line in $Lines) {
  if ($line -cmatch '^-e git\+https://github\.com/michaelbooth1/weather\.git@[0-9a-f]{40}#egg=weather_market$') { $line -creplace '@[0-9a-f]{40}#', '@<HEAD>#' } else { $line } } }
function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$OutBase) {
  $quoted = foreach ($q in $Arguments) { if ($q -match '[\s"]') { '"' + ($q -replace '"','\"') + '"' } else { $q } }
  $proc = Start-Process -FilePath $Exe -ArgumentList ($quoted -join ' ') -WorkingDirectory $P -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "$OutBase.out.txt" -RedirectStandardError "$OutBase.err.txt"
  $proc.WaitForExit(); if ($null -eq $proc.ExitCode) { NoGo "no exit code from $Exe" }
  Log ("native exit {0}: {1} {2}" -f $proc.ExitCode, (Split-Path -Leaf $Exe), ($Arguments -join ' ')); [int]$proc.ExitCode }
function Get-ReleaseActive([string]$Exe, [string]$OutBase) {
  $code = Invoke-Native $Exe @('-m','weather.operations.release_lifecycle_cli','--repo-root',$P,'active') $OutBase
  $o = "$(Get-Content -LiteralPath "$OutBase.out.txt" -Raw)"; $e = "$(Get-Content -LiteralPath "$OutBase.err.txt" -Raw)"
  $raw = if ($o.Trim()) { $o } else { @($e -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') }) | Select-Object -Last 1 }
  try { $j = $raw | ConvertFrom-Json } catch { NoGo "release active output is not JSON ($OutBase)" }
  $ra = [pscustomobject]@{ exit=$code; status=[string]$j.status; error=[string]$j.error }
  $ra | ConvertTo-Json | Set-Content -LiteralPath "$OutBase.json" -Encoding utf8; $ra }
function Assert-NoU6At0035([string]$Tag) {
  $u6 = Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue
  if ($u6 -and [string]$u6.State -ne 'Disabled' -and @($u6.Triggers | Where-Object { [string]$_.StartBoundary -match 'T00:35' }).Count -gt 0) {
    NoGo "$Tag U6 export is registered at 00:35 and enabled (G5, Q3)" } }
function Assert-CaseA($ra, $tag) {
  if ($ra.status -ne 'BLOCK' -or $ra.error -notlike '*active release pointer is missing*') { NoGo "$tag release is not case A: $($ra | ConvertTo-Json -Compress)" }
  if (Test-Path -LiteralPath (Join-Path $P 'artifacts\releases\current_release.json')) { NoGo "$tag active release pointer exists" } }

# A gate: real run = NO-GO on failure; dry run = record and continue. A throw while evaluating is a failure.
function Gate([string]$Name, [scriptblock]$Test, [switch]$Window) {
  $ok = $false; $why = ''
  try { $res = & $Test; if ($res -is [array]) { $res = $res[-1] }; $ok = [bool]$res } catch { $why = $_.Exception.Message }
  if ($ok) { Log "GATE PASS $Name"; return }
  if ($Dry) {
    if ($Window) { Log "GATE WINDOW-CLOSED $Name (dry run: informational) $why" }
    else { Log "GATE FAIL $Name $why"; $script:GateFails.Add($Name) }
    return }
  NoGo "$Name $why" }

# ---- runbook B1c Build-Venv and B1d Test-Venv, verbatim ----
function Build-Venv($vpy, $root) {
  Select-String -LiteralPath "$R\lock-hashed.txt" -Pattern '^(pip|setuptools|wheel)==' | ForEach-Object Line | Set-Content "$R\lock-tools-hashed.txt" -Encoding ascii
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-tools-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tools install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-hashed.txt";       if ($LASTEXITCODE) { NoGo 'lock install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --no-deps -e $root;                                    if ($LASTEXITCODE) { NoGo 'editable install' }
}
function Test-Venv($vpy, $root, $tag) {
  $out = Join-Path $R "check-$tag"; New-Item -ItemType Directory -Force $out | Out-Null
  $vv = & $vpy -VV; $vv | Set-Content "$out\VV.txt"; if ($vv -notlike "$($K.vv_prefix)*") { NoGo "$tag VV" }
  $cfg = Get-Content -LiteralPath (Join-Path (Split-Path (Split-Path $vpy)) 'pyvenv.cfg')
  if (-not ($cfg -match ('^home\s*=\s*' + [regex]::Escape($NewHome) + '\s*$'))) { NoGo "$tag pyvenv home" }
  & $vpy -I -m pip check | Set-Content "$out\pipcheck.txt"; if ($LASTEXITCODE) { NoGo "$tag pip check" }
  $skip = '^(-e |#)'   # under the Q13 exemption use '^(-e |#|tzdata==)'
  $d = Compare-Object (Get-Content "$A\freeze-3110.txt" | Where-Object { $_ -notmatch $skip }) (& $vpy -m pip freeze --all | Where-Object { $_ -notmatch $skip })
  $d | Out-File "$out\freeze-diff.txt"; if ($d) { NoGo "$tag freeze differs" }
  Push-Location -LiteralPath $R
  try {
    $loc = & $vpy -c "import weather, maker_core; print(weather.__file__); print(maker_core.__file__)"; if ($LASTEXITCODE) { NoGo "$tag import location" }
    $src = (Join-Path $root 'src') + '\'
    foreach ($l in $loc) { if (-not $l.StartsWith($src, [StringComparison]::OrdinalIgnoreCase)) { NoGo "$tag package imported from $l, not $src" } }
    $std = & $vpy -c "import os, ssl, sys; print(os.__file__); print(ssl.__file__); print('\n'.join(p for p in sys.path if p))"; if ($LASTEXITCODE) { NoGo "$tag stdlib location" }
    $std | Set-Content "$out\stdlib-path.txt" -Encoding utf8
    if (-not $OldHome) { NoGo "$tag oldhome.txt missing" }
    $nh = $NewHome.TrimEnd('\') + '\'; $oh = $OldHome.TrimEnd('\') + '\'
    foreach ($s in $std[0..1]) { if (-not $s.StartsWith($nh, [StringComparison]::OrdinalIgnoreCase)) { NoGo "$tag stdlib from $s, not $nh" } }
    foreach ($s in $std) { if (($s.TrimEnd('\') + '\').StartsWith($oh, [StringComparison]::OrdinalIgnoreCase)) { NoGo "$tag sys.path reaches the 3.11.0 home: $s" } }
  } finally { Pop-Location }
  Push-Location -LiteralPath $root
  try {
    & $vpy -c "import json; from weather.release_artifacts import capture_runtime_versions as c; print(json.dumps(c(), indent=1, sort_keys=True))" | Set-Content "$out\rtv.json" -Encoding utf8
    & $vpy -c "import weather.collection.snapshot_tracker, weather.market.market_microstructure, weather.operations.observation_trigger, weather.operations.execution_tape_supervisor, weather.operations.capture_recovery_check, weather.release_serving, weather.market.maker_evidence_capture, weather.market.maker_shadow; import sklearn, numpy, scipy, pandas, pyarrow, netCDF4, websocket, requests; print('import smoke ok')"
    if ($LASTEXITCODE) { NoGo "$tag import smoke" }
  } finally { Pop-Location }
  $o = Get-Content "$A\rtv-3110.json" -Raw | ConvertFrom-Json; $n = Get-Content "$out\rtv.json" -Raw | ConvertFrom-Json
  if ($n.python -ne '3.11.9' -or $o.implementation -ne $n.implementation) { NoGo "$tag rtv python/implementation" }
  if (($o.direct_dependencies | ConvertTo-Json -Compress) -ne ($n.direct_dependencies | ConvertTo-Json -Compress)) { NoGo "$tag direct dependencies moved" }
  Log "$tag Test-Venv PASS"
}

# Start a child process, record its PID (track-and-terminate rule), wait, return its exit code.
function Invoke-Tracked([string]$Exe, [string[]]$Arguments, [string]$OutBase) {
  $quoted = foreach ($q in $Arguments) { if ($q -match '[\s"]') { '"' + ($q -replace '"','\"') + '"' } else { $q } }
  $proc = Start-Process -FilePath $Exe -ArgumentList ($quoted -join ' ') -WorkingDirectory $P -NoNewWindow -PassThru `
        -RedirectStandardOutput "$OutBase.out.txt" -RedirectStandardError "$OutBase.err.txt"
  $null = $proc.Handle   # cache the handle so ExitCode is readable after WaitForExit
  "$($proc.Id) $((Get-Date).ToString('o')) $Exe" | Set-Content -LiteralPath "$OutBase.pid.txt" -Encoding ascii
  Log "started pid $($proc.Id): $(Split-Path -Leaf $Exe) (pid file $OutBase.pid.txt)"
  $proc.WaitForExit(); if ($null -eq $proc.ExitCode) { NoGo "no exit code from $Exe" }
  Log ("child exit {0}: pid {1}" -f $proc.ExitCode, $proc.Id); [int]$proc.ExitCode }

$receipt = [ordered]@{ procedure='B-R'; night=$NightDate; expected_head=$ExpectedHead; dry_run=$Dry; outcome='NO-GO'; at_start=(Get-Date).ToString('o') }
try {
  # ---------------- P: preconditions (read-only) ----------------
  if (-not (Test-Path -LiteralPath $R -PathType Container)) { throw "record root $R missing" }
  if (-not $Dry) { New-Item -ItemType Directory $BRDir | Out-Null }
  else { $script:DryTemp = Join-Path $env:TEMP ('pyup-br-dry-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory $script:DryTemp | Out-Null }
  $Work = if ($Dry) { $script:DryTemp } else { $BRDir }
  $env:PYTHONDONTWRITEBYTECODE = '1'   # the read-only probes must not write __pycache__ into the production checkout
  Gate 'production checkout has venv python' { Test-Path -LiteralPath $Py -PathType Leaf }
  . (Join-Path $P 'scripts\ops\workload_admission.ps1')
  . (Join-Path $P 'scripts\ops\memory_guard_status_reader.ps1')
  Log "B-R session start host=$env:COMPUTERNAME P=$P R=$R stage=$Stage branch=$QBranch expected_head=$ExpectedHead"

  Gate "night date is $NightDate" { (Get-Date).ToString('yyyy-MM-dd') -eq $NightDate } -Window
  Gate 'B0 window 00:30-02:00' { $h = (Get-Date).Hour + (Get-Date).Minute/60; $h -ge 0.5 -and $h -lt 2.0 } -Window
  $headNow = (git -C $P rev-parse HEAD).Trim()
  Gate "production HEAD equals -ExpectedHead (HEAD $headNow)" { $headNow -ceq $ExpectedHead }
  Gate 'production tree clean (tracked files)' { -not (git -C $P status --porcelain --untracked-files=no) }
  Gate 'constants.json present with every key' {
    $script:K = Get-Content -LiteralPath (Join-Path $R 'constants.json') -Raw | ConvertFrom-Json
    foreach ($kk in 'nupkg_url','nupkg_size','nupkg_sha512_b64','tools_manifest_sha256','binary_signer_thumbprint','vv_prefix','binaries') { if (-not $script:K.$kk) { throw "constants.json lacks $kk" } }; $true }
  $K = $script:K
  Gate 'oldhome.txt present' { $script:OldHome = (Get-Content -LiteralPath "$R\oldhome.txt" -TotalCount 1).Trim(); [bool]$script:OldHome }
  $OldHome = $script:OldHome
  Gate 'new home python is the pinned 3.11.9 build' { (Test-Path -LiteralPath $NewPy) -and ((& $NewPy -VV) -like "$($K.vv_prefix)*") -and ((Sha $NewPy) -eq [string]$K.binaries.'python.exe') }
  Gate 'paths.json matches this session' { $pj = Get-Content -LiteralPath "$R\paths.json" -Raw | ConvertFrom-Json
    $pj.P -eq $P -and $pj.R -eq $R -and $pj.NewHome -eq $NewHome -and $pj.OldHome -eq $OldHome }
  Gate 'previous qualification.json is a case-A PASS on another tip' { $oq = Get-Content -LiteralPath "$R\qualification.json" -Raw | ConvertFrom-Json
    $script:OldQ = $oq; $oq.result -eq 'PASS' -and $oq.release_case -eq 'A' -and ([string]$oq.tip -match '^[0-9a-f]{40}$') -and ([string]$oq.tip -ne $ExpectedHead) }
  Gate "stage path $Stage is absent" { -not (Test-Path -LiteralPath $Stage) }
  Gate "branch $QBranch is absent" { -not @(git -C $P branch --list $QBranch).Count }
  Gate 'wheelhouse equals the Phase B manifest' {
    $wh = @(Get-ChildItem -LiteralPath $WH -File | ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.Name })
    $wh.Count -gt 0 -and -not (Compare-Object (Get-Content -LiteralPath "$R\wheelhouse-sha256.txt") $wh) }
  Gate 'hashed lock present, every line hash-pinned' { $lk = @(Get-Content -LiteralPath "$R\lock-hashed.txt" | Where-Object { $_.Trim() })
    $lk.Count -gt 0 -and -not @($lk | Where-Object { $_ -notmatch '^[A-Za-z0-9_.\-]+==\S+ (--hash=sha256:[0-9a-f]{64} ?)+$' }).Count }
  Gate 'production freeze (masked) equals freeze-3110.txt' {
    $fz = Join-Path $Work 'freeze-3110-br.txt'; & $Py -m pip freeze --all | Set-Content -LiteralPath $fz -Encoding utf8; if ($LASTEXITCODE) { throw 'pip freeze failed' }
    -not (Compare-Object (Mask-Editable (Get-Content -LiteralPath "$A\freeze-3110.txt")) (Mask-Editable (Get-Content -LiteralPath $fz))) }
  Gate 'rtv direct dependencies unchanged since rtv-3110.json' {
    Push-Location -LiteralPath $P
    try { $rt = & $Py -c "import json; from weather.release_artifacts import capture_runtime_versions as c; print(json.dumps(c(), indent=1, sort_keys=True))"; if ($LASTEXITCODE) { throw 'rtv probe failed' } } finally { Pop-Location }
    $o1 = Get-Content -LiteralPath "$A\rtv-3110.json" -Raw | ConvertFrom-Json; $n1 = ($rt -join "`n") | ConvertFrom-Json
    ($o1.direct_dependencies | ConvertTo-Json -Compress) -eq ($n1.direct_dependencies | ConvertTo-Json -Compress) }
  Gate 'G5: training window and Stage B disabled or absent' {
    -not @('WeatherTrainingWindow','WeatherEveningEvidenceRefresh' | ForEach-Object { Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue } | Where-Object { [string]$_.State -ne 'Disabled' }).Count }
  Gate 'G5: no U6 at 00:35' { Assert-NoU6At0035 'P'; $true }
  Gate 'exclusive night: U6, capture-family and evidence-host tasks are not registered' {
    -not @('WeatherReplayBundleExportNightly','WeatherEvidenceHost' | ForEach-Object { Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue }).Count -and
    -not @(Get-ScheduledTask -TaskName 'WeatherMakerEvidence*' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ne 'WeatherMakerEvidenceCapture' }).Count }
  Gate 'exclusive night: no enabled integration, storage or re-enable one-shot due before 09:00' {
    $until = (Get-Date).Date.AddHours(9); if ((Get-Date).Hour -ge 9) { $until = $until.AddDays(1) }
    $due = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like 'WeatherIntegration*' -or $_.TaskName -like 'WeatherStorageRecovery-*' -or $_.TaskName -like 'WeatherTrainingWindowReenable*' -or $_.TaskName -like 'WeatherSuite*' } |
      Where-Object { [string]$_.State -ne 'Disabled' } | Where-Object { $ni = (Get-ScheduledTaskInfo $_).NextRunTime; $ni -and $ni -lt $until })
    foreach ($dt in $due) { Log "due task: $($dt.TaskName)" }; -not $due.Count }
  Gate 'shared heavy-workload lease is free' { $ls = Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P; Log "lease state $($ls | ConvertTo-Json -Compress)"; -not $ls.Active }
  Gate 'C: free space at least 55 GB' { (Get-Volume -DriveLetter C).SizeRemaining -ge 55GB }
  Gate 'git binding matches the host git.exe' { ((Sha $GitExe) -eq $GitSha) -and ((Get-Item -LiteralPath $GitExe).VersionInfo.FileVersion -eq $GitVer) }
  $suite = Join-Path $P 'scripts\ops\bounded_worktree_test_suite.ps1'
  Gate 'G1: bounded suite has the interpreter and git binding parameters' {
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($suite, [ref]$null, [ref]$null)
    $names = @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
    -not @('InterpreterPath','ExpectedInterpreterVersion','GitExecutablePath','ExpectedGitExecutableSha256','ExpectedGitExecutableFileVersion','PreflightOnly','MaxRuntimeSeconds' | Where-Object { $names -notcontains $_ }).Count }
  Gate 'release is case A on 3.11.0' { $ra0 = Get-ReleaseActive $Py (Join-Path $Work 'release-active-3110-pre'); Assert-CaseA $ra0 'P'; $true }
  $mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"

  if ($Dry) {
    if ($script:GateFails.Count) { Log "RESULT: $($script:GateFails.Count) gate(s) FAIL: $($script:GateFails -join '; ')"; $exitCode = 1 }
    else { Log 'RESULT: every non-window gate PASS; nothing was written'; $exitCode = 0 }
  } else {
  Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue   # B1-B3 run exactly as Phase B did

  # ---------------- B0: admission and lease ----------------
  $global:Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_requal'; if (-not $global:Lease) { NoGo 'lease busy' }
  $global:ReleaseOnNoGo = $true
  Log 'B0 lease held (py3119_requal)'
  $oldTip = [string]$script:OldQ.tip
  $archive = Join-Path $R ('qualification-' + $oldTip.Substring(0,12) + '.json')
  if (Test-Path -LiteralPath $archive) { if ((Sha $archive) -ne (Sha "$R\qualification.json")) { NoGo "archive $archive exists with other content" } }
  else { Copy-Item -LiteralPath "$R\qualification.json" $archive; if ((Sha $archive) -ne (Sha "$R\qualification.json")) { NoGo 'archive copy differs' } }
  Log "previous qualification archived to $archive (tip $oldTip)"

  # ---------------- B1c: stage worktree and offline stage venv ----------------
  foreach ($ev in 'PIP_INDEX_URL','PIP_EXTRA_INDEX_URL','PIP_FIND_LINKS','PIP_TRUSTED_HOST','PIP_PROXY') { Remove-Item -LiteralPath "Env:$ev" -ErrorAction SilentlyContinue }
  $env:PIP_NO_INDEX = '1'      # belt and braces; every pip call is also --isolated --no-index --find-links $WH
  $Tip = $ExpectedHead
  $env:GIT_LFS_SKIP_SMUDGE = '1'; git -C $P worktree add -b $QBranch $Stage $Tip; $wt = $LASTEXITCODE; Remove-Item Env:GIT_LFS_SKIP_SMUDGE
  if ($wt) { NoGo 'worktree add' }
  if ((git -C $Stage rev-parse HEAD).Trim() -cne $Tip) { NoGo 'stage HEAD is not the expected tip' }
  & $NewPy -I -m venv (Join-Path $Stage 'venv'); if ($LASTEXITCODE) { NoGo 'stage venv' }
  Build-Venv $StagePy $Stage

  # ---------------- B1d, B1e ----------------
  Test-Venv $StagePy $Stage 'stage-br'
  Push-Location -LiteralPath $Stage
  & $StagePy -c "import glob, pickle, sys; fs = sorted(glob.glob(sys.argv[1])); assert fs, 'no artifacts'; [pickle.load(open(f, 'rb')) for f in fs]; print('hgb load ok')" (Join-Path $P 'artifacts\models\hgb\feature_model_hgb*.pkl')
  if ($LASTEXITCODE) { NoGo 'hgb load' }
  Pop-Location
  $global:ReleaseOnNoGo = $false; Release-Lease

  # ---------------- B2: bounded suite on the stage interpreter ----------------
  if ((Get-Date) -gt (Get-Date).Date.AddHours(3)) { NoGo 'past the 03:00 suite start limit' }
  if ((Sha $GitExe) -ne $GitSha -or (Get-Item -LiteralPath $GitExe).VersionInfo.FileVersion -ne $GitVer) { NoGo 'B2 git binding does not match the host git.exe' }
  $maxRun = [int][math]::Floor(((Get-Date).Date.AddHours(4).AddMinutes(45) - (Get-Date)).TotalSeconds)
  if ($maxRun -gt 5400) { $maxRun = 5400 }; if ($maxRun -lt 60) { NoGo 'no runtime left before 04:45' }
  $SuiteLog = Join-Path $BRDir 'bounded-suite.log'
  $suiteStart = Get-Date
  $common = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$suite,'-RepoRoot',$P,'-WorktreeRoot',$Stage,'-ExpectedTip',$Tip,'-BranchRef',$QBranch,
              '-InterpreterPath',$StagePy,'-ExpectedInterpreterVersion','3.11.9','-GitExecutablePath',$GitExe,
              '-ExpectedGitExecutableSha256',$GitSha.ToLowerInvariant(),'-ExpectedGitExecutableFileVersion',$GitVer)
  $pre = Invoke-Tracked 'powershell.exe' ($common + @('-LogPath',"$SuiteLog.preflight",'-PreflightOnly')) (Join-Path $BRDir 'suite-preflight')
  $SuiteExit = 99
  if ($pre -eq 0) { $SuiteExit = Invoke-Tracked 'powershell.exe' ($common + @('-LogPath',$SuiteLog,'-MaxRuntimeSeconds',[string]$maxRun)) (Join-Path $BRDir 'suite') }
  Log "bounded suite preflight exit $pre, suite exit $SuiteExit (max runtime $maxRun s)"
  $receipt.suite_preflight_exit = $pre; $receipt.suite_exit = $SuiteExit

  # The suite deletes each chunk's explicit --basetemp (%SystemDrive%\pt\bs-<run>-NNN); remove any leftover of this run.
  $ptRoot = Join-Path $env:SystemDrive 'pt'; $left = @()
  if (Test-Path -LiteralPath $ptRoot) {
    foreach ($bt in @(Get-ChildItem -LiteralPath $ptRoot -Directory -Filter 'bs-*' -Force | Where-Object { $_.CreationTime -ge $suiteStart.AddMinutes(-1) })) {
      if (($bt.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $left += "$($bt.FullName) (reparse point, not touched)"; continue }
      & cmd.exe /d /c "rmdir /s /q `"$($bt.FullName)`"" | Out-Null
      if (Test-Path -LiteralPath $bt.FullName) { $left += $bt.FullName } else { Log "removed leftover basetemp $($bt.FullName)" } } }
  $receipt.basetemp_leftovers = $left
  if ($left.Count) { Log "WARN basetemp leftovers not removed: $($left -join ', ')" }

  if ($SuiteExit -ne 0) { NoGo "bounded suite exit $SuiteExit (preflight $pre); qualification.json unchanged" }
  $logText = Get-Content -LiteralPath $SuiteLog -Raw
  if ($logText -notmatch 'VERDICT: ALL CHUNKS PASSED') { NoGo 'suite log has no ALL CHUNKS PASSED verdict' }
  if ($logText -notmatch 'interpreter override re-hash matched') { NoGo 'suite log has no interpreter re-hash line' }
  $ovr = @($logText -split "`r?`n" | Where-Object { $_ -match 'interpreter_override ' }) | Select-Object -First 1
  if (-not $ovr -or $ovr -notmatch '3\.11\.9' -or $ovr -notmatch [regex]::Escape((Split-Path -Leaf $Stage))) { NoGo 'interpreter_override line does not name the stage venv and 3.11.9' }
  if ($logText -notmatch ('selected_git=' + [regex]::Escape($GitExe) + ' expected_git_sha256=' + $GitSha.ToLowerInvariant() + ' expected_git_file_version=' + [regex]::Escape($GitVer))) { NoGo 'suite log git binding line does not match' }
  if (git -C $Stage status --porcelain) { NoGo 'stage worktree is dirty after the suite' }

  # ---------------- B3: release case and the qualification record (PASS only) ----------------
  $ra = Get-ReleaseActive $Py (Join-Path $BRDir 'release-active-3110'); Assert-CaseA $ra 'B3'
  $vvLine = ((& $StagePy -VV) -join ' ').Trim()
  $cfgPath = Join-Path $Stage 'venv\pyvenv.cfg'
  $stageFreeze = Join-Path $BRDir 'stage-freeze.txt'; & $StagePy -m pip freeze --all | Set-Content -LiteralPath $stageFreeze -Encoding utf8; if ($LASTEXITCODE) { NoGo 'stage pip freeze' }
  $q = [ordered]@{
    result = 'PASS'; procedure = 'B-R'; release_case = 'A'; tip = $Tip; branch = $QBranch; stage = $Stage
    stage_python = $StagePy; python_version = '3.11.9'; python_vv = $vvLine
    pyvenv_cfg = $cfgPath; pyvenv_cfg_sha256 = (Sha $cfgPath); pyvenv_home = $NewHome
    stage_freeze = $stageFreeze; stage_freeze_sha256 = (Sha $stageFreeze)
    suite_log = $SuiteLog; suite_log_sha256 = (Sha $SuiteLog); suite_exit = $SuiteExit
    suite_preflight_log = "$SuiteLog.preflight"; suite_preflight_log_sha256 = (Sha "$SuiteLog.preflight")
    git_binding = [ordered]@{ path = $GitExe; sha256 = $GitSha; file_version = $GitVer }
    wheelhouse_manifest = "$R\wheelhouse-sha256.txt"; wheelhouse_manifest_sha256 = (Sha "$R\wheelhouse-sha256.txt")
    lock_hashed_sha256 = (Sha "$R\lock-hashed.txt")
    supersedes = [ordered]@{ tip = $oldTip; archive = $archive; archive_sha256 = (Sha $archive) }
    basetemp_leftovers = $left; record_dir = $BRDir; at = (Get-Date).ToString('o') }
  $tmp = "$R\qualification.json.br-tmp"
  $q | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tmp -Encoding utf8
  $chk = Get-Content -LiteralPath $tmp -Raw | ConvertFrom-Json
  if ($chk.result -ne 'PASS' -or $chk.tip -ne $Tip -or $chk.release_case -ne 'A') { NoGo 'qualification temp file did not read back' }
  Move-Item -LiteralPath $tmp -Destination "$R\qualification.json" -Force
  Log "B-R PASS: qualification.json now names tip $Tip (sha256 $(Sha "$R\qualification.json"))"
  $receipt.outcome = 'PASS'; $receipt.qualification_sha256 = (Sha "$R\qualification.json")
  $exitCode = 0
  }   # end of the real run
}
catch {
  Log "stopped: $($_.Exception.Message)"
  $receipt.error = $_.Exception.Message
  $exitCode = 1
}
finally {
  $global:ReleaseOnNoGo = $false
  try { Release-Lease } catch { Log "ESCALATE: lease release failed: $($_.Exception.Message)"; $exitCode = 1 }
  if ($Dry) { if ($script:DryTemp -and (Test-Path -LiteralPath $script:DryTemp)) { Remove-Item -LiteralPath $script:DryTemp -Recurse -Force } }
  elseif (Test-Path -LiteralPath $BRDir) {
    $receipt.at_end = (Get-Date).ToString('o')
    $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $BRDir 'br-receipt.json') -Encoding utf8 }
  Remove-Item Env:PIP_NO_INDEX -ErrorAction SilentlyContinue
  Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
}
exit $exitCode
