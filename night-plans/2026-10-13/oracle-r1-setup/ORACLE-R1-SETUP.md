# Oracle r1 author setup on the capture host (owner-attended block, revision 2)

This block was generated from the [isolation runbook](../../../docs/roadmap/maker-replay-v2-shadow-gate-spec-v3.4-oracle-host-isolation-runbook-DRAFT-2026-10-12.md)
at `claude/oracle-handout-h1-20261012` @ `c85494d57` (runbook file sha256
`371c49c7853c014b369ecb5228e86d2a2127434f7ee14e2dcb2aaa6e91378deb`), and amended by master-agent's review of
2026-10-12:
- **(A) Calendar.** Nothing oracle-related happens on 10-14.
- **(B) Profile handling.** Profile trees are not deny-ACLed; they are asserted closed instead. Inheritable deny ACEs go
  on non-profile roots only.
- **(V) Oracle venv.** The owner approved the PyPI download on 2026-10-12 at about 20:15.
- **r1 re-cut before hand-out** (owner, 2026-10-12 ~21:30). The kept `tests/maker_core/conftest.py` imported an
  excluded fixture, so collection failed. R4 is narrowed for `tests/maker_core/fixtures/__init__.py` and
  `fictional_domain.py` (blob-pinned keep list); `test_re1_parity.py` and `test_re1_session_export.py` are withheld as
  `excluded-import`; the cut tool now refuses any kept `tests/` file whose imports the cut does not keep. The new
  binding below supersedes `62327970…7db9`. H-11, H-12 and the erratum bytes are unchanged.
- **Permission mode** (owner, same sitting): variant 2, `acceptEdits` plus a git-only Bash allow-list (ruling I-8).

Where this block and the runbook differ on (B), this block is the newer ruling. The runbook's step 5 needs the same
amendment when it lands.

Bound values. Each one is checked by the code below, so none of them needs retyping:

| Value | |
| --- | --- |
| r1 manifest binding (SHA-256 of `C:\oracle-cut\r1\H1-manifest.json`), re-cut 2026-10-12 | `61b68b16e4b51b1fd4702e77d0b30edfb1fe2f66c315096087c291053a56673b` |
| H-12 r1 (signed 2026-10-12 ~20:45), inside the cut as `handout\H-12-session-prompt-r1.md` | `50afac36accc3d4a613db2d2a6037f0d0a7b2cd1f93092a103b5a8cd4162f878` |
| Cut plan `plan.json` (this folder; byte copy of the workstation r1 plan) | `e75ed9de176e9775009bf64b8162048a703c1f91a9a102695f84b63a7087fc56` |
| `materialize_h1_inputs.py` (this folder), blob `40ba3c0ce94bd08f4fce73ac1ea45f3a4cfdedbc` | `a6ed3cc7c584b980c5d67110ec643b91ba35a17849189c32a6b1607094627753` |
| Cut tool written by the materializer, blob `9585b5a7ba365f3b95c1b70bc5f18d04e41a7107` (`claude/oracle-cut-fixture-keep-20261012` @ `8b85810bc`) | `7a30cecfe14e01eb500a0ddbf3a688e46a365f6d87453a04868b19effbdf9f47` |
| `oracle-venv-lock-hashed.txt` (this folder, 7 pins with tzdata), blob `5641fa85e4e8d5df64815858dd537d25ed1d4695` | `2593874af3124185fd38311a55df4bea962930c93e0f791f52784045a02e2e77` |

The workstation re-cut twice into different output paths and got `61b68b16…673b` both times, so the binding does not
depend on the output path. In that scratch cut, `pytest --collect-only tests/maker_core` on the six pytest pins
collected 162 tests with 0 errors. Over all of `tests/` it collected 2260 tests with 312 error files, every one a
third-party package; none is a repository module missing from the cut. 44 of them were tzdata (`ZoneInfo` on native
Windows has no system database), so the master agent added `tzdata==2026.3` as the seventh pin: the oracle itself needs
it for local midnights. With it, `tests/` collects 2403 tests with 305 error files, all requests, pandas, numpy,
pyarrow, streamlit, websocket, matplotlib or sklearn. Those packages stay out by design; this is a disclosed limit (the
author sees collect errors for those files and may ask), recorded in the decision log and the isolation runbook §6. The
launch message and H-12 do not change.

## Who runs what, and when

| Step | Who | Elevated (UAC) | When | Heavy (lease) |
| --- | --- | --- | --- | --- |
| O1 create the author account | **owner at the machine** | **yes** | **10-13**, after Phase A, before 12:00, if the owner has time (else 10-15 07:30) | no |
| V1 oracle pytest venv (PyPI download, hash-pinned) | master | no | **10-15** 00:30-04:45, after §T, before M0 | yes, short |
| M0 profile assertions, non-profile root inventory, deny-list file | master | no | **10-15 05:00** | yes (bounded file counts) |
| M1 fetch, materialize, cut, verify | master | no | **10-15** after M0, done by **06:40** (91a runs at 06:50) | yes, short (~20 s cut) |
| O2 sign the deny list, apply the deny ACEs (non-profile roots only) | **owner at the machine** | **yes** | **10-15 07:30** | **yes**: inheritable denies propagate through each tree |
| M2 cut ACLs, post-ACL verify, the four work folders (step 8), the check script | master | no (master owns the cut) | after O2 | no |
| V2 I-6 wrapper proof run (import containment) | master | no | after M2, must end by 08:55 | the wrapper takes the lease itself |
| O3 author profile: harness install and login, settings, git identity, the §3 checks | **owner at the machine**, signed in as the author (Switch user; **never sign out** the operator session) | no | after V2 | no |
| M3 read the check results, light integrity re-check | master | no | after O3 | no |
| O4 launch the author session with the one-line launch message | **owner at the machine**, as the author | no | master names the time | no |

Fallback: if anything after O1 slips, the whole 10-15 sequence moves to the **10-18 morning**, with the same windows.
O2 must finish by 09:00. Only V1, M0, M1, O2 and V2 are bound to 00:30-09:00. The author's own unit tests are bound to
00:30-09:00 as well (I-6); they run later through the same wrapper as V2.

Any NO-GO stops the sequence. Nothing below reads `data\` contents, credentials or `.env*` files. Directory listings
read names only. The author's password is typed by the owner into a secure prompt. It never appears in this block, a
log, a file or a chat.

## Header (master's and the owner's elevated windows: Windows PowerShell 5.1)

```powershell
$ErrorActionPreference = 'Stop'
$P        = '<PROD_CLONE>'                          # the production checkout (under the operator's profile)
$Py       = Join-Path $P 'venv\Scripts\python.exe'  # stdlib-only use; -I everywhere
$Ops      = 'C:\oracle-ops'                         # operator-only; must be top-level (the plan's relative path)
$CutRoot  = 'C:\oracle-cut'
$Cut      = 'C:\oracle-cut\r1'
$Bind     = '61b68b16e4b51b1fd4702e77d0b30edfb1fe2f66c315096087c291053a56673b'
$H12      = '50afac36accc3d4a613db2d2a6037f0d0a7b2cd1f93092a103b5a8cd4162f878'
$Author   = 'oracle-author'                         # <AUTHOR>; change here only
$Operator = '<OPERATOR>'                            # master's account, DOMAIN\user form, e.g. "$env:COMPUTERNAME\<user>"
$Base     = '<3.11.9 home from Phase A ($R\paths.json)>\python.exe'   # the oracle venv's base interpreter (V1)
$Venv     = Join-Path $Ops 'venv'; $VPy = Join-Path $Venv 'Scripts\python.exe'
$Log      = Join-Path $Ops 'setup.log'
$BadIds   = 'BUILTIN\Users','NT AUTHORITY\Authenticated Users','Everyone','NT AUTHORITY\INTERACTIVE'
function Log($m){ $l = "{0:o} {1}" -f (Get-Date), $m; if (Test-Path -LiteralPath $Ops) { Add-Content -LiteralPath $Log -Value $l -Encoding utf8 }; Write-Host $l }
function NoGo($m){ Log "NO-GO: $m"; throw "NO-GO: $m" }
function Sha($f){ (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower() }
function Icacls([string[]]$a){ & icacls.exe @a | Out-Null; if ($LASTEXITCODE -ne 0) { NoGo "icacls $($a -join ' ') exit $LASTEXITCODE" }; Log "icacls $($a -join ' ')" }
function Grants($path){ @((Get-Acl -LiteralPath $path).Access | Where-Object { $_.AccessControlType -eq 'Allow' -and $BadIds -contains $_.IdentityReference.Value } | ForEach-Object { "$($_.IdentityReference.Value):$($_.FileSystemRights)" }) }
function Blob($blob, $dest, $sha){ & $Py -I -c "import subprocess,sys; open(sys.argv[2],'wb').write(subprocess.check_output(['git','-C',sys.argv[1],'cat-file','blob',sys.argv[3]]))" $P $dest $blob
  if ((Sha $dest) -ne $sha) { NoGo "$dest is not the reviewed file" } }
function New-OpsDir($d){ if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory $d | Out-Null
  Icacls @($d,'/inheritance:r','/grant:r',"${Operator}:(OI)(CI)F",'SYSTEM:(OI)(CI)F','Administrators:(OI)(CI)F') } }
. (Join-Path $P 'scripts\ops\workload_admission.ps1')
```

## V1. Oracle-author pytest venv (master, 10-15 00:30-04:45, after §T, lease)

- **What it holds.** pytest and its Windows runtime dependencies, plus `tzdata==2026.3` (the §T artifact): native
  Windows `zoneinfo` has no system database, and the oracle computes local midnights. The handout modules
  (`maker_core.contracts`, `maker_core.quoting.policy` and what they import) use the standard library alone. Nothing
  else is installed, so tests that need requests, pandas, numpy and similar packages do not collect (a disclosed
  limit). The pins equal the workstation
  3.11.9 venv: `oracle-venv-pins.txt`, hashed by the Python upgrade runbook's §6b `pypi_hash_lock.py` logic.
- **Download rules.** Windows and pure wheels only, `--require-hashes`, `--only-binary=:all:`, `--no-deps`; then
  `pip check`.
- **Base interpreter.** The 3.11.9 home that Phase A installs side by side on 10-13. It is not the production venv
  (the I-6 wrapper refuses that venv, because its editable `.pth` adds the production `src`).
- **After the 10-17 cutover (C).** No rebuild is needed. The cutover rebuilds only `$P\venv`; the 3.11.9 home this
  venv points at stays installed and unchanged. V3 below is a one-line check.
- **Fallback if Phase A has not run.** Use the 3.11.0 home (the `home` key in `$P\venv\pyvenv.cfg`) and change the
  version expectation below. That venv keeps working after C, because 3.11.0 stays installed (runbook Q7). Rebuild it
  on 3.11.9 only if 3.11.0 is ever uninstalled.
- **Location.** `C:\oracle-ops\venv`, inside the operator-only `$Ops`. The author account cannot read it and does not
  need to: the wrapper runs as the operator. `$Ops` is therefore **not** passed to the wrapper's `-ForbiddenRoot`
  (V2).

```powershell
New-OpsDir $Ops
$Lock = Join-Path $Ops 'oracle-venv-lock-hashed.txt'; $Wh = Join-Path $Ops 'wheels'
foreach ($x in $Venv, $Wh, $Lock) { if (Test-Path -LiteralPath $x) { NoGo "$x exists" } }
if ((& $Base -VV) -notlike 'Python 3.11.9 *') { NoGo "base interpreter is not 3.11.9: $(& $Base -VV)" }
& git -C $P fetch origin claude/night-plans; if ($LASTEXITCODE -ne 0) { NoGo 'fetch failed' }
Blob '5641fa85e4e8d5df64815858dd537d25ed1d4695' $Lock '2593874af3124185fd38311a55df4bea962930c93e0f791f52784045a02e2e77'
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'oracle-author-venv'
try {
  & $Base -I -m venv $Venv; if ($LASTEXITCODE -ne 0) { NoGo 'venv create' }
  & $VPy -I -m pip download --isolated --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r $Lock -d $Wh; if ($LASTEXITCODE -ne 0) { NoGo 'download' }
  & $VPy -I -m pip install --isolated --no-index --no-deps --require-hashes --find-links $Wh -r $Lock; if ($LASTEXITCODE -ne 0) { NoGo 'install' }
  & $VPy -I -m pip check; if ($LASTEXITCODE -ne 0) { NoGo 'pip check' }
} finally { Exit-WeatherHeavyWorkloadLease -Lease $Lease; Log 'lease released' }
$cfg = Get-Content -LiteralPath (Join-Path $Venv 'pyvenv.cfg')
if (-not ($cfg -match '^include-system-site-packages\s*=\s*false')) { NoGo 'venv sees system site-packages' }
$vhome = (($cfg -match '^home\s*=') -replace '^home\s*=\s*', '' | Select-Object -First 1).Trim()
if ($vhome -ne (Split-Path -Parent $Base)) { NoGo "venv home $vhome is not $(Split-Path -Parent $Base)" }
$freeze = @(& $VPy -I -m pip freeze --all); $freeze | Set-Content -LiteralPath "$Ops\venv-freeze.txt" -Encoding utf8
$want = 'colorama==0.4.6','iniconfig==2.3.0','packaging==26.2','pluggy==1.6.0','Pygments==2.20.0','pytest==9.0.3','tzdata==2026.3'
$extra = @($freeze | Where-Object { $_ -notmatch '^(pip|setuptools)==' -and $want -notcontains $_ })
$miss = @($want | Where-Object { $freeze -notcontains $_ })
if ($extra.Count -or $miss.Count) { NoGo "venv contents differ: extra=$($extra -join ',') missing=$($miss -join ',')" }
Log "V1 PASS venv $Venv on $(& $VPy -VV); freeze sha256 $(Sha "$Ops\venv-freeze.txt")"
```

## M0. Profile assertions, root inventory, deny-list file (master, 10-15 05:00, lease)

1. **Profiles are asserted, not deny-ACLed.** Every profile root under `C:\Users` must carry no allow ACE for
   Users, Authenticated Users, Everyone or INTERACTIVE. The expected ACEs are the profile's owner, SYSTEM and
   Administrators; anything else is listed for master. If any profile grants one of the four, the step lists it and
   **stops**. Master decides; this block does not fix it.
2. **Direct paths.** Windows grants "bypass traverse checking" to Everyone by default. A child folder with its own
   allow ACE for Users would therefore be reachable by its full path even though the profile root is closed. M0 reads
   the direct ACLs of the production paths the author must never reach. O3 then probes those paths as the author.
3. **Non-profile roots.** Every top-level folder on every fixed drive, other than system folders, gets a bounded file
   count, its Users-type grants and a repository count. Roots over 50 000 files are marked `LARGE` for master's call.

```powershell
New-OpsDir $Ops
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'oracle-r1-m0-inventory'
try {
  # 1. profile roots
  $skip = 'Public','Default','Default User','All Users',$Author
  $prof = foreach ($d in Get-ChildItem -LiteralPath 'C:\Users' -Directory -Force) {
    if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    $acl = Get-Acl -LiteralPath $d.FullName
    $other = @($acl.Access | Where-Object { $_.AccessControlType -eq 'Allow' } | ForEach-Object { $_.IdentityReference.Value } |
      Where-Object { $_ -notin 'NT AUTHORITY\SYSTEM','BUILTIN\Administrators' -and $BadIds -notcontains $_ -and $_ -notlike "*\$($d.Name)" } | Sort-Object -Unique)
    [pscustomobject]@{ profile = $d.Name; owner = $acl.Owner; users_grant = (Grants $d.FullName) -join ','; review = $other -join ',' } }
  $prof | Format-Table -AutoSize | Out-String -Width 400 | Set-Content -LiteralPath "$Ops\m0-profiles.txt" -Encoding utf8
  # 2. direct ACLs of the production paths (names only; no file content is read)
  $direct = @($P, "$P\.git", "$P\data", "$P\src", "$P\venv", "$P\config", (Split-Path -Parent $P)) | Where-Object { Test-Path -LiteralPath $_ }
  $drows = foreach ($x in $direct) { [pscustomobject]@{ path = $x; users_grant = (Grants $x) -join ',' } }
  $drows | Format-Table -AutoSize | Out-String -Width 400 | Set-Content -LiteralPath "$Ops\m0-direct.txt" -Encoding utf8
  # 3. non-profile roots
  $sys = 'Windows','Program Files','Program Files (x86)','ProgramData','$Recycle.Bin','System Volume Information',
         'Recovery','PerfLogs','Users','Documents and Settings','Config.Msi','oracle-cut'
  $roots = foreach ($dr in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match '^[A-Z]:\\$' -and $_.Free })) {
    Get-ChildItem -LiteralPath $dr.Root -Directory -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -notin $sys -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) } | ForEach-Object FullName }
  $rrows = foreach ($r in $roots) {
    $n = @(Get-ChildItem -LiteralPath $r -Recurse -File -Force -ErrorAction SilentlyContinue | Select-Object -First 200001).Count
    $g = @(Get-ChildItem -LiteralPath $r -Filter '.git' -Force -Recurse -Depth 3 -ErrorAction SilentlyContinue).Count
    [pscustomobject]@{ root = $r; files = $(if ($n -gt 200000) { '>200000' } else { $n }); large = $(if ($n -gt 50000) { 'LARGE' } else { '' })
                       repos = $g; users_grant = (Grants $r) -join ',' } }
  $rrows | Format-Table -AutoSize | Out-String -Width 400 | Set-Content -LiteralPath "$Ops\m0-roots.txt" -Encoding utf8
} finally { Exit-WeatherHeavyWorkloadLease -Lease $Lease; Log 'lease released' }
$roots | Set-Content -LiteralPath "$Ops\m0-roots-list.txt" -Encoding utf8
Get-Content "$Ops\m0-profiles.txt", "$Ops\m0-direct.txt", "$Ops\m0-roots.txt"
$badProf = @($prof | Where-Object { $_.profile -notin $skip -and $_.users_grant })
if ($badProf.Count) { NoGo "profile root grants a Users-type identity: $(($badProf | ForEach-Object { "$($_.profile)=$($_.users_grant)" }) -join '; ') (STOP: master's call)" }
$badDirect = @($drows | Where-Object { $_.users_grant })
if ($badDirect.Count) { NoGo "production path grants a Users-type identity: $(($badDirect | ForEach-Object { "$($_.path)=$($_.users_grant)" }) -join '; ') (STOP: master's call)" }
if (-not (@($prof | Where-Object { $P -like "C:\Users\$($_.profile)\*" -and $_.profile -notin $skip }).Count)) { NoGo "$P is not under a checked profile root: it must go on the deny list instead" }
Log "M0 PASS profiles=$(@($prof).Count) roots=$(@($roots).Count) large=$(@($rrows | Where-Object large).Count)"
```

Read the three tables. `review` lists other allow ACEs on a profile; `Public` and `Default` are listed for
information only (they are open to Users by design). Then master writes `$Ops\deny-list.txt`:
- **One absolute path per line, and only non-profile roots.** Every root in `m0-roots-list.txt` must be on the list
  unless a line `#ALLOW <root> <reason>` names it. Examples are a root holding only the harness install, or the
  3.11.9 home if it is a top-level folder: the author needs neither, so denying is the default.
- **Expected entries:** `C:\wt`, `C:\tmp`, `C:\pt`, `C:\oracle-ops`, the l-data location, `C:\b` and any other
  scratch root, as present.
- **`LARGE` roots** are master's call. Denying one only costs propagation time inside O2's lease.
- **No path under `C:\Users`.** O2 refuses one.
- `#` lines are comments, and they are part of the signed bytes.

## M1. Fetch, materialize, cut, verify (master, 10-15, done by 06:40, lease)

```powershell
if (Test-Path -LiteralPath $Cut) { NoGo "$Cut exists (the cut writes only to a new directory)" }
& git -C $P fetch origin codex/maker-replay-v2-build-20261003 claude/oracle-handout-h1-20261012 claude/oracle-cut-fixture-keep-20261012 claude/scratch-h1-sources-20261007 claude/night-plans
if ($LASTEXITCODE -ne 0) { NoGo 'fetch failed' }
foreach ($c in '501f475796f70263907d4d7d5fd3cd44fe7d1d5b','cf7b0d5337dd7ef2d5385077602cfb9812c41558') {
  & git -C $P cat-file -e "$c^{commit}"; if ($LASTEXITCODE -ne 0) { NoGo "commit $c missing" } }
New-OpsDir 'C:\wt'                                  # holds the frozen sources; created operator-only if absent
$M = Join-Path $Ops 'materialize_h1_inputs.py'
Blob '40ba3c0ce94bd08f4fce73ac1ea45f3a4cfdedbc' $M 'a6ed3cc7c584b980c5d67110ec643b91ba35a17849189c32a6b1607094627753'
& $Py -I $M --repo $P --ops $Ops; if ($LASTEXITCODE -ne 0) { NoGo 'materialize refused' }
New-OpsDir $CutRoot
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'oracle-r1-cut'
try {
  $o = & $Py -I "$Ops\tool\maker_replay_v2_h1_cut.py" cut --plan "$Ops\plan\plan.json" --repo $P --out $Cut
  $rc = $LASTEXITCODE; $o | Set-Content -LiteralPath "$Ops\cut.out.txt" -Encoding utf8
  if ($rc -ne 0) { NoGo "cut exit $rc (see $Ops\cut.out.txt)" }
  if ((Sha "$Cut\H1-manifest.json") -ne $Bind) { NoGo "manifest sha256 $(Sha "$Cut\H1-manifest.json") != $Bind" }
  $v = & $Py -I "$Ops\tool\maker_replay_v2_h1_cut.py" verify --out $Cut --binding $Bind
  $rc = $LASTEXITCODE; $v | Set-Content -LiteralPath "$Ops\verify-pre.txt" -Encoding utf8
  if ($rc -ne 0) { NoGo "pre-session verify exit $rc" }
  if ((Sha "$Cut\handout\H-12-session-prompt-r1.md") -ne $H12) { NoGo 'H-12 in the cut is not the signed bytes' }
} finally { Exit-WeatherHeavyWorkloadLease -Lease $Lease; Log 'lease released' }
Log "M1 PASS binding $Bind"
```

## O1. Author account (owner, elevated; 10-13 after Phase A, before 12:00)

O1 needs only the header lines up to `$Author` and the `Log`/`NoGo` functions. `$Ops` may not exist yet; `Log` then
writes to the screen only.

```powershell
if (Get-LocalUser -Name $Author -ErrorAction SilentlyContinue) { NoGo "$Author already exists" }
$pw = Read-Host -AsSecureString "Owner: type the password for $Author (not shown, not logged)"
New-LocalUser -Name $Author -Password $pw -PasswordNeverExpires -AccountNeverExpires -Description 'oracle r1 author (I-1 option A)' | Out-Null
Remove-Variable pw
Add-LocalGroupMember -Group 'Users' -Member $Author
$groups = foreach ($g in Get-LocalGroup) { try { if (@(Get-LocalGroupMember -Group $g.Name -ErrorAction Stop | Where-Object { $_.Name -like "*\$Author" }).Count) { $g.Name } } catch {} }
if ((@($groups) -join ',') -ne 'Users') { NoGo "$Author groups: $($groups -join ',') (want Users only)" }
Log "O1 $Author created, groups=Users (password set by the owner, not recorded)"
```

## O2. Sign and apply the deny list (owner, elevated, 10-15 07:30, lease)

```powershell
$DL = Join-Path $Ops 'deny-list.txt'
$lines = @(Get-Content -LiteralPath $DL | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$paths = @($lines | Where-Object { -not $_.StartsWith('#') })
$allow = @($lines | Where-Object { $_ -match '^#ALLOW\s+(\S+)\s+\S' } | ForEach-Object { ($_ -split '\s+')[1] })
foreach ($r in @(Get-Content -LiteralPath "$Ops\m0-roots-list.txt")) { if ($paths -notcontains $r -and $allow -notcontains $r) { NoGo "deny list neither denies nor #ALLOWs $r" } }
foreach ($p in $paths) {
  if ($p -like 'C:\Users*') { NoGo "profile path on the deny list: $p (profiles are asserted in M0, not deny-ACLed)" }
  if (-not (Test-Path -LiteralPath $p)) { NoGo "deny path missing: $p" } }
if ($paths -notcontains $Ops) { NoGo "deny list lacks $Ops" }
$h = Sha $DL
$lines | ForEach-Object { Write-Host "  $_" }
Write-Host "deny-list.txt sha256 $h ($($paths.Count) deny paths, $($allow.Count) allowed roots)"
$s = Read-Host 'Owner: to sign this list type SIGN followed by the first 8 characters of the sha256'
if ($s -cne "SIGN $($h.Substring(0,8))") { NoGo 'owner did not sign the deny list' }
Log "O2 owner signed deny-list sha256 $h"
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'oracle-r1-deny-acl'
try { foreach ($p in $paths) { Icacls @($p,'/deny',"${Author}:(OI)(CI)RX") } }
finally { Exit-WeatherHeavyWorkloadLease -Lease $Lease; Log 'lease released' }
# Scheduler (runbook step 6): nothing runs as the author
if (@(Get-ScheduledTask | Where-Object { $_.Principal.UserId -like "*$Author" }).Count) { NoGo "a scheduled task runs as $Author" }
Log 'O2 PASS'
```

Children whose inheritance is switched off do not receive an inherited deny. The O3 checks probe direct paths for
exactly that reason: each deny root and its first-level children, plus the profile paths from M0.

## M2. Cut ACLs, post-ACL verify, work folders, check script (master)

```powershell
Icacls @($Cut,'/inheritance:r','/grant:r',"${Author}:(OI)(CI)RX","${Operator}:(OI)(CI)F",'SYSTEM:(OI)(CI)F','Administrators:(OI)(CI)F')
Icacls @("$Cut\oracle-repo",'/grant',"${Author}:(OI)(CI)M")
$v = & $Py -I "$Ops\tool\maker_replay_v2_h1_cut.py" verify --out $Cut --binding $Bind
$rc = $LASTEXITCODE; $v | Set-Content -LiteralPath "$Ops\verify-post-acl.txt" -Encoding utf8
if ($rc -ne 0) { NoGo "post-ACL verify exit $rc" }
# runbook step 8: only now, because verify refuses any top-level entry the cut did not write
foreach ($f in 'questions','test-requests','test-results','handback') { New-Item -ItemType Directory "$Cut\$f" | Out-Null }
foreach ($f in 'questions','test-requests','handback') { Icacls @("$Cut\$f",'/grant',"${Author}:(OI)(CI)M") }
& icacls.exe $Cut /T | Set-Content -LiteralPath "$Ops\acl-cut.txt" -Encoding utf8
# the §3 check script for O3; master deletes it again in M3
$deny = @(Get-Content -LiteralPath "$Ops\deny-list.txt" | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
$kids = foreach ($d in $deny) { Get-ChildItem -LiteralPath $d -Force -ErrorAction SilentlyContinue | Select-Object -First 20 | ForEach-Object FullName }
$profRoot = (Get-Item -LiteralPath $P).FullName; while ((Split-Path -Parent $profRoot) -ne 'C:\Users') { $profRoot = Split-Path -Parent $profRoot }
$dataFile = Get-ChildItem -LiteralPath "$P\data" -File -Force -ErrorAction SilentlyContinue | Select-Object -First 1 | ForEach-Object FullName   # a name only
$probe = @($profRoot, "$P", "$P\.git", "$P\.git\HEAD", "$P\.git\config", "$P\README.md", "$P\src", "$P\docs", "$P\tools", "$P\data", "$P\venv") + @($dataFile) + @($kids) | Where-Object { $_ }
$snap = (& git -C "$Cut\oracle-repo" rev-parse HEAD).Trim()
$body = @"
`$deny = @('$($deny -join "','")')
`$probe = @('$($probe -join "','")')
`$P = '$P'; `$Cut = '$Cut'; `$snap = '$snap'; `$out = '$Cut\handback\setup-checks.txt'
"@ + @'
$r = New-Object System.Collections.Generic.List[string]
function Rec($ok,$m){ $r.Add(("{0} {1}" -f ($(if ($ok) {'PASS'} else {'FAIL'})), $m)) }
Rec (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators')) "not admin ($env:USERNAME)"
foreach ($p in $deny + $probe) { $denied = $false; try { Get-ChildItem -LiteralPath $p -Force -ErrorAction Stop | Select-Object -First 1 | Out-Null } catch { $denied = $true }
  if (-not $denied) { try { Get-Content -LiteralPath $p -TotalCount 1 -ErrorAction Stop | Out-Null } catch { $denied = $true } }
  Rec $denied "no read: $p" }
& git -C $P rev-parse HEAD 2>$null | Out-Null; Rec ($LASTEXITCODE -ne 0) 'git rev-parse on the production clone fails'
Rec (@(Get-ChildItem env: | Where-Object { $_.Name -like 'GIT_*' }).Count -eq 0) 'no GIT_* variable'
$envhit = @(Get-ChildItem env: | Where-Object { $v = [string]$_.Value; @(@($deny) + @($P) | Where-Object { $v -like "*$_*" }).Count })
Rec ($envhit.Count -eq 0) "no variable points into a denied root or the production clone $($envhit.Name -join ',')"
$ck = (cmdkey /list) -join ' '; Rec ($ck -notmatch 'Target:') 'cmdkey: no stored credential'
$gc = (git config --global --list) -join ' '; Rec ($gc -notmatch 'credential') "git global config has no credential helper"
$r.Add("INFO git system credential config: $((git config --system --get-all credential.helper) -join ',')")
Rec ([string]::IsNullOrWhiteSpace((git -C "$Cut\oracle-repo" remote -v) -join '')) 'oracle-repo: no remote'
Rec (@(git -C "$Cut\oracle-repo" for-each-ref).Count -eq 1) 'oracle-repo: one ref'
Rec (((git -C "$Cut\oracle-repo" rev-list --all --count) -join '').Trim() -eq '1') 'oracle-repo: one commit'
Rec (((git -C "$Cut\oracle-repo" rev-parse HEAD) -join '').Trim() -eq $snap) 'oracle-repo: HEAD is the snapshot'
Rec (-not (Test-Path -LiteralPath "$Cut\oracle-repo\.git\objects\info\alternates")) 'oracle-repo: no alternates'
foreach ($w in 'oracle-repo','questions','test-requests','handback') { $t = "$Cut\$w\.write-probe"; $ok = $true
  try { Set-Content -LiteralPath $t -Value x -ErrorAction Stop; Remove-Item -LiteralPath $t -ErrorAction Stop } catch { $ok = $false }; Rec $ok "can write $w" }
foreach ($w in 'handout','test-results','.') { $t = "$Cut\$w\.write-probe"; $ok = $false
  try { Set-Content -LiteralPath $t -Value x -ErrorAction Stop; Remove-Item -LiteralPath $t } catch { $ok = $true }; Rec $ok "cannot write $w" }
$net = Test-NetConnection github.com -Port 443 -WarningAction SilentlyContinue
$r.Add("INFO egress (N1 residual, disclosed): github.com:443 reachable=$($net.TcpTestSucceeded)")
$r | Set-Content -LiteralPath $out -Encoding utf8; $r
if ($r -match '^FAIL') { Write-Host 'SETUP CHECKS FAILED' -ForegroundColor Red } else { Write-Host 'SETUP CHECKS PASS' -ForegroundColor Green }
'@
Set-Content -LiteralPath "$Cut\test-results\setup-checks.ps1" -Value $body -Encoding utf8
Log "M2 PASS; check script $(Sha "$Cut\test-results\setup-checks.ps1") ($($probe.Count) direct probes)"
```

## V2. I-6 wrapper proof run (master, after M2, ends by 08:55)

This step proves that, under the wrapper, every import comes from the cut or the oracle venv. The wrapper's probe
child checks four things before pytest starts, and refuses on any failure:
- the `-I -S -B` flags;
- the prefix is the venv or its base;
- every `sys.path` entry is inside the cut repository or the interpreter;
- `pytest` resolves from the venv, and `weather`, `maker_core`, `app`, `sitecustomize` and `usercustomize` resolve
  inside the cut or not at all.

The test is a stdlib-only snapshot test that reads one file of the cut. Precondition: the I-6 wrapper
(`claude/oracle-author-test-lease-20261012`) has landed and is present in `$P`.

```powershell
$W = Join-Path $P 'scripts\ops\oracle_author_test_run.ps1'
if (-not (Test-Path -LiteralPath $W)) { NoGo 'the I-6 wrapper is not in the production checkout' }
$TL = Join-Path $Ops 'test-logs'; New-OpsDir $TL
$baseRoot = [IO.Path]::GetPathRoot($Base) + (($Base.Substring(3)) -split '\\')[0]
$forbid = @(Get-Content -LiteralPath "$Ops\deny-list.txt" | ForEach-Object { $_.Trim() } |
  Where-Object { $_ -and -not $_.StartsWith('#') -and $_ -ne $Ops -and $_ -ne $baseRoot }) -join ';'
powershell -NoProfile -ExecutionPolicy Bypass -File $W -CutDir $Cut -PythonPath $VPy -LogDir $TL `
  -TestPath 'tests/operations/test_roll_verdict_script.py' -ExpectedManifestSha256 $Bind -ForbiddenRoot $forbid
$rc = $LASTEXITCODE
$rcpt = Get-ChildItem -LiteralPath $TL -Filter '*.receipt.json' | Sort-Object LastWriteTime | Select-Object -Last 1
$j = Get-Content -LiteralPath $rcpt.FullName -Raw | ConvertFrom-Json
Log "V2 exit $rc status $($j.status) python $($j.probe.version) pytest=$($j.probe.pytest) maker_core=$($j.probe.guarded.maker_core) receipt $(Sha $rcpt.FullName)"
if ($rc -ne 0) { NoGo "wrapper proof exit $rc ($($j.reason))" }
if ($j.probe.version -ne '3.11.9') { NoGo "probe interpreter $($j.probe.version)" }
# tzdata: the oracle venv must resolve America/Toronto from its own tzdata 2026.3 (no system database on Windows).
$tz = @(& $VPy -I -c "import importlib.metadata as m, zoneinfo, tzdata, datetime as d; z = zoneinfo.ZoneInfo('America/Toronto'); print(m.version('tzdata')); print(tzdata.__file__); print(int(d.datetime(2026, 7, 1, tzinfo=z).utcoffset().total_seconds()), int(d.datetime(2026, 1, 1, tzinfo=z).utcoffset().total_seconds()))")
if ($LASTEXITCODE -ne 0 -or $tz.Count -ne 3) { NoGo "zoneinfo probe failed: $($tz -join ' | ')" }
if ($tz[0] -ne '2026.3') { NoGo "tzdata version $($tz[0])" }
if (-not $tz[1].StartsWith((Join-Path $Venv 'Lib\site-packages\tzdata\'), [StringComparison]::OrdinalIgnoreCase)) { NoGo "tzdata not from the oracle venv: $($tz[1])" }
if ($tz[2] -ne '-14400 -18000') { NoGo "America/Toronto offsets $($tz[2])" }
Log "V2 tzdata $($tz[0]) from $($tz[1]); America/Toronto offsets $($tz[2])"
```

- **Expected result:** exit 0 and 2 passed, with `maker_core` resolving under `$Cut\oracle-repo\src`.
- **Wrapper refusals:** exit 64 is a refusal before pytest started, and its reason is printed. Exit 65 means the run
  modified the cut; inspect before O3.
- **`$Ops` is not a forbidden root here,** because the venv lives in it. Nothing in `$Ops` can be imported: it is on
  no `sys.path` entry, and the probe proves that.
- **The base home's top-level root is also left out,** because the wrapper refuses an interpreter whose base overlaps
  a forbidden root. Both roots stay denied to the author account.

## O3. Author profile and checks (owner, signed in as the author)

Use Start > Switch user and sign in as `oracle-author` with the password the owner set. Do not sign out the operator
session, because capture runs there. In a normal (not elevated) PowerShell:

1. Install Claude Code for this account the way the owner normally does. That is a download, so it is the owner's own
   decision. Then run `claude` once and log in. The login is the owner's credential, typed by the owner.
2. Settings (ruling I-8: `acceptEdits` plus the git-only allow-list), git identity and the scoped
   `safe.directory`:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude" | Out-Null
'{ "permissions": { "defaultMode": "acceptEdits", "disableBypassPermissionsMode": "disable", "deny": ["WebFetch", "WebSearch", "mcp__*"], "allow": ["Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git add *)", "Bash(git commit *)", "Bash(git switch *)", "Bash(git checkout -b *)", "Bash(git bundle create *)"] }, "env": { "DISABLE_AUTOUPDATER": "1" } }' |
  Set-Content -LiteralPath "$env:USERPROFILE\.claude\settings.json" -Encoding ascii
git config --global user.name 'oracle-author'
git config --global user.email 'oracle-author@localhost.invalid'
git config --global --add safe.directory 'C:/oracle-cut/r1/oracle-repo'
powershell -NoProfile -ExecutionPolicy Bypass -File C:\oracle-cut\r1\test-results\setup-checks.ps1
```

3. In `claude`, started from `C:\oracle-cut\r1`:
   - `/mcp` must list **no** servers, including claude.ai connectors. If any appear, disable them before the launch.
   - `/permissions` must show the deny and allow rules above, and the mode `acceptEdits`.
   - `/status` gives the model and version. Note them for master (E1).
   - Record the sandbox as "not supported on native Windows" for the N1 disclosure.
   - Exit.

## M3. Results and pre-launch re-check (master)

```powershell
$res = Get-Content -LiteralPath "$Cut\handback\setup-checks.txt"
Copy-Item -LiteralPath "$Cut\handback\setup-checks.txt" "$Ops\setup-checks.txt"
if ($res -match '^FAIL') { NoGo "setup checks failed: $(($res -match '^FAIL') -join '; ')" }
Remove-Item -LiteralPath "$Cut\handback\setup-checks.txt", "$Cut\test-results\setup-checks.ps1"
foreach ($f in 'questions','test-requests','test-results','handback') { if (@(Get-ChildItem -LiteralPath "$Cut\$f" -Force).Count) { NoGo "$f is not empty" } }
if ((Sha "$Cut\H1-manifest.json") -ne $Bind) { NoGo 'manifest changed' }
$m = Get-Content -LiteralPath "$Cut\H1-manifest.json" -Raw | ConvertFrom-Json
foreach ($row in $m.handout) { if ((Sha (Join-Path "$Cut\handout" $row.handout_path)) -ne $row.sha256) { NoGo "handout $($row.handout_path) changed" } }
if (((& git -C "$Cut\oracle-repo" status --porcelain) -join '').Trim()) { NoGo 'oracle-repo working tree is not clean' }
Log 'M3 PASS: ready to launch'
```

The full `verify` cannot run again once the work folders exist. M3's manifest, handout and clean-tree checks stand in
for it, and the I-6 wrapper fingerprints the cut on every test run.

## O4. Launch (owner, as the author, at the time master names)

```powershell
Set-Location C:\oracle-cut\r1
claude
```

The first and only message, pasted exactly as one line:

```text
Oracle handout r1. Manifest C:\oracle-cut\r1\H1-manifest.json, SHA-256 61b68b16e4b51b1fd4702e77d0b30edfb1fe2f66c315096087c291053a56673b. Your session prompt is C:\oracle-cut\r1\handout\H-12-session-prompt-r1.md: read it in full and follow it.
```

After that, say nothing else to the session (erratum 1 E1). The owner tells master the start time, model and Claude Code
version. Master records them with the archive (I-7).

## V3. After the 10-17 cutover (master, one line, any admitted window)

```powershell
& $VPy -I -c "import sys, pytest; print(sys.version.split()[0], pytest.__version__)"   # expect 3.11.9 9.0.3
```

If it fails, the base home has moved. Rebuild with V1 into a new path; never repair the venv in place.

## Permission mode (owner: variant 2, ruling I-8)

What Claude Code can and cannot confine on this host (Claude Code docs: permissions, sandboxing, settings):
- **Bash cannot be scoped to a directory.** Bash and PowerShell rules match the command text only. A deny such as
  `Bash(cd *)` is literal text matching and is bypassable, so it is not a boundary.
- **Read and Edit path rules** cover the file tools and recognized shell file commands (`cat`, `sed`, redirects). They
  do not cover a script that opens files itself.
- **`acceptEdits`** auto-accepts edits only inside the working directory (`C:\oracle-cut\r1`) and any
  `additionalDirectories`. An edit elsewhere still prompts.
- **The shell sandbox** (filesystem and network limits) exists on macOS, Linux and WSL2 only. On native Windows,
  commands run unsandboxed, so the N1 egress residual stays and stays disclosed.
- **Managed settings** (`C:\Program Files\ClaudeCode\managed-settings.json`) cannot be overridden by the author, but
  they would also bind master's own Claude Code session on this host. They are not used here.

The OS boundary is the author account's NTFS rights, which this block sets and O3 checks.

The two variants that were offered (the owner chose 2 on 2026-10-12 ~21:30):
1. **Default mode.** The owner approves every edit and every command at the machine. Strongest control, slowest.
2. **`acceptEdits` plus a small allow-list (chosen; shown in O3).** Add `"defaultMode": "acceptEdits"` and
   `"allow": ["Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git add *)", "Bash(git commit *)",
   "Bash(git switch *)", "Bash(git checkout -b *)", "Bash(git bundle create *)"]`, and keep the deny list.
   - Edits inside the cut and those git commands run without a prompt. Every other command still prompts the owner,
     including any `python`, `pytest` or network tool, which H-12 rule 5 forbids anyway.
   - The settings file sits in the author's own profile, so the author session could edit it. That edit lies outside
     the working directory, so it prompts too.
