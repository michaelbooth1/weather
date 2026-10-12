# Oracle r1 author setup on the capture host (owner-attended block)

This block was generated from the [isolation runbook](../../../docs/roadmap/maker-replay-v2-shadow-gate-spec-v3.4-oracle-host-isolation-runbook-DRAFT-2026-10-12.md)
at `claude/oracle-handout-h1-20261012` @ `c85494d57`, file sha256
`371c49c7853c014b369ecb5228e86d2a2127434f7ee14e2dcb2aaa6e91378deb`. That runbook commit adds two fixes: an operator
grant in step 4, and a scoped `safe.directory` in step 7. If the landed runbook differs, the runbook wins: regenerate
this block from it.

Bound values. Each one is checked by the code below, so none of them needs retyping:

| Value | |
| --- | --- |
| r1 manifest binding (SHA-256 of `C:\oracle-cut\r1\H1-manifest.json`) | `623279703b2daac805c95e330aef4bede87ac203b75d6724d6bcae793a7b7db9` |
| H-12 r1 (signed 2026-10-12 ~20:45), inside the cut as `handout\H-12-session-prompt-r1.md` | `50afac36accc3d4a613db2d2a6037f0d0a7b2cd1f93092a103b5a8cd4162f878` |
| Cut plan `plan.json` (this folder; byte copy of the workstation r1 plan) | `e75ed9de176e9775009bf64b8162048a703c1f91a9a102695f84b63a7087fc56` |
| `materialize_h1_inputs.py` (this folder), blob `7a77a72e27db09d52c19a6070a791fa0c4835c5d` | `e834f9fc77dc4126f5b1de7d6f705d9f843691767ac0926e0098e0c999227395` |

The workstation reproduced the binding from a fresh top-level ops folder: the materializer wrote the inputs from git
objects, the cut ran into a different output path, and it gave `62327970…7db9`. The binding does not depend on the
output path.

## Who runs what

| Step | Who | Elevated (UAC) | Window | Heavy (lease) |
| --- | --- | --- | --- | --- |
| M0 deny-list discovery and the list file | master | no | not 12:00-18:00 | no (depth-limited listing) |
| M1 fetch, materialize, cut, verify | master | no | 00:30-09:00 (suggest 05:00-07:00, clear of the N9 quiet window) | yes, short (~20 s cut) |
| O1 create the author account | **owner at the machine** | **yes** | not 12:00-18:00 | no |
| O2 sign the deny list, apply the deny ACEs | **owner at the machine** | **yes** | **00:30-09:00** | **yes**: each inheritable deny propagates through the whole tree (the production clone and `data\` included), which is bulk disk I/O |
| M2 cut ACLs, post-ACL verify, the four work folders (step 8), the check script | master | no (master owns the cut) | not 12:00-18:00 | no |
| O3 author profile: harness install and login, settings, git identity, the §3 checks | **owner at the machine**, signed in as the author (Switch user; **never sign out** the operator session) | no | not 12:00-18:00 | no |
| M3 read the check results, light integrity re-check, clear the handback folder | master | no | not 12:00-18:00 | no |
| O4 launch the author session with the one-line launch message | **owner at the machine**, as the author | no | master names the time | no |

Suggested calendar:
- **10-13 (after Phase A, before 12:00):** O1 only.
- **10-13/14 night, 05:00-07:00:** M0 and M1.
- **10-14, ~07:30-09:00:** O2, M2, O3, M3, then O4 when master says go.

O2 must finish by 09:00. All of it can also run on the 10-14 morning in one sitting. Only the author's own unit tests
are bound to 00:30-09:00 (I-6). They run through `scripts\ops\oracle_author_test_run.ps1` (branch
`claude/oracle-author-test-lease-20261012`), which needs its own pytest venv outside every clone.

Any NO-GO stops the sequence. Nothing below reads `data\` contents, credentials or `.env*` files. The author's
password is typed by the owner into a secure prompt. It never appears in this block, a log, a file or a chat.

## Header (master's and the owner's elevated windows: Windows PowerShell 5.1)

```powershell
$ErrorActionPreference = 'Stop'
$P        = '<PROD_CLONE>'                          # the production checkout
$Py       = Join-Path $P 'venv\Scripts\python.exe'  # stdlib-only use; -I everywhere
$Ops      = 'C:\oracle-ops'                         # operator-only; must be top-level (the plan's relative path)
$CutRoot  = 'C:\oracle-cut'
$Cut      = 'C:\oracle-cut\r1'
$Bind     = '623279703b2daac805c95e330aef4bede87ac203b75d6724d6bcae793a7b7db9'
$H12      = '50afac36accc3d4a613db2d2a6037f0d0a7b2cd1f93092a103b5a8cd4162f878'
$Author   = 'oracle-author'                         # <AUTHOR>; change here only
$Operator = '<OPERATOR>'                            # master's account, DOMAIN\user form, e.g. "$env:COMPUTERNAME\<user>"
$Log      = Join-Path $Ops 'setup.log'
function Log($m){ $l = "{0:o} {1}" -f (Get-Date), $m; if (Test-Path -LiteralPath $Ops) { Add-Content -LiteralPath $Log -Value $l -Encoding utf8 }; Write-Host $l }
function NoGo($m){ Log "NO-GO: $m"; throw "NO-GO: $m" }
function Sha($f){ (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower() }
function Icacls([string[]]$a){ & icacls.exe @a | Out-Null; if ($LASTEXITCODE -ne 0) { NoGo "icacls $($a -join ' ') exit $LASTEXITCODE" }; Log "icacls $($a -join ' ')" }
```

## M0. Deny-list discovery (master, read-only)

```powershell
if (-not (Test-Path -LiteralPath $Ops)) {
  New-Item -ItemType Directory $Ops | Out-Null
  Icacls @($Ops,'/inheritance:r','/grant:r',"${Operator}:(OI)(CI)F",'SYSTEM:(OI)(CI)F','Administrators:(OI)(CI)F') }
$sys = 'Windows','Program Files','Program Files (x86)','ProgramData','$Recycle.Bin','System Volume Information','Recovery','PerfLogs','Users','oracle-cut'
$cand = foreach ($d in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match '^[A-Z]:\\$' -and $_.Free })) {
  Get-ChildItem -LiteralPath $d.Root -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -notin $sys } | ForEach-Object FullName }
$prof = Get-ChildItem -LiteralPath 'C:\Users' -Directory -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -notin 'Public','Default','Default User','All Users',$Author } | ForEach-Object FullName
# repositories and worktrees up to depth 3 below each candidate (a worktree's .git is a file)
$repos = foreach ($c in $cand + $prof) { Get-ChildItem -LiteralPath $c -Filter '.git' -Force -Recurse -Depth 3 -ErrorAction SilentlyContinue | ForEach-Object { $_.Parent.FullName; if (-not $_.PSIsContainer) { $_.DirectoryName } } }
($cand + $prof + ($repos | Sort-Object -Unique)) | Sort-Object -Unique | Set-Content -LiteralPath "$Ops\deny-candidates.txt" -Encoding utf8
Log "M0 candidates: $((Get-Content "$Ops\deny-candidates.txt").Count)"
```

Master writes `$Ops\deny-list.txt` from the candidates: one absolute path per line, with `#` comment lines. It must
cover at least these roots:
- `$P`;
- every other clone and worktree;
- `$Ops`;
- `C:\wt` (it holds the frozen sources after M1);
- l-data;
- `C:\b` and any other scratch root;
- every user profile other than the author's.

`C:\Users\Public` is master's judgement: deny it unless something the author needs lives there. Remove only system
folders the author must use: Windows, Program Files and the harness install. The O2 code refuses a list that omits a
must-include root.

## M1. Fetch, materialize, cut, verify (master, 00:30-09:00, lease)

```powershell
. (Join-Path $P 'scripts\ops\workload_admission.ps1')
if (Test-Path -LiteralPath $Cut) { NoGo "$Cut exists (the cut writes only to a new directory)" }
& git -C $P fetch origin codex/maker-replay-v2-build-20261003 claude/oracle-handout-h1-20261012 claude/scratch-h1-sources-20261007 claude/night-plans
if ($LASTEXITCODE -ne 0) { NoGo 'fetch failed' }
foreach ($c in '501f475796f70263907d4d7d5fd3cd44fe7d1d5b','cf7b0d5337dd7ef2d5385077602cfb9812c41558') {
  & git -C $P cat-file -e "$c^{commit}"; if ($LASTEXITCODE -ne 0) { NoGo "commit $c missing" } }
# C:\wt holds the frozen sources: create it operator-only if it does not exist yet
if (-not (Test-Path -LiteralPath 'C:\wt')) { New-Item -ItemType Directory 'C:\wt' | Out-Null
  Icacls @('C:\wt','/inheritance:r','/grant:r',"${Operator}:(OI)(CI)F",'SYSTEM:(OI)(CI)F','Administrators:(OI)(CI)F') }
# the materializer itself, byte-exact from its blob
$M = Join-Path $Ops 'materialize_h1_inputs.py'
& $Py -I -c "import subprocess,sys; open(sys.argv[2],'wb').write(subprocess.check_output(['git','-C',sys.argv[1],'cat-file','blob',sys.argv[3]]))" $P $M '7a77a72e27db09d52c19a6070a791fa0c4835c5d'
if ((Sha $M) -ne 'e834f9fc77dc4126f5b1de7d6f705d9f843691767ac0926e0098e0c999227395') { NoGo 'materializer is not the reviewed file' }
& $Py -I $M --repo $P --ops $Ops; if ($LASTEXITCODE -ne 0) { NoGo 'materialize refused' }
if (-not (Test-Path -LiteralPath $CutRoot)) { New-Item -ItemType Directory $CutRoot | Out-Null }
Icacls @($CutRoot,'/inheritance:r','/grant:r',"${Operator}:(OI)(CI)F",'SYSTEM:(OI)(CI)F','Administrators:(OI)(CI)F')
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

## O1. Author account (owner, elevated)

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

## O2. Sign and apply the deny list (owner, elevated, 00:30-09:00, lease)

```powershell
. (Join-Path $P 'scripts\ops\workload_admission.ps1')
$DL = Join-Path $Ops 'deny-list.txt'
$paths = @(Get-Content -LiteralPath $DL | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
$must = @($P, $Ops, 'C:\wt') + @(Get-ChildItem -LiteralPath 'C:\Users' -Directory -Force | Where-Object { $_.Name -notin 'Public','Default','Default User','All Users',$Author } | ForEach-Object FullName)
foreach ($m in $must) { if ($paths -notcontains $m) { NoGo "deny list lacks $m" } }
foreach ($p in $paths) { if (-not (Test-Path -LiteralPath $p)) { NoGo "deny path missing: $p" } }
$h = Sha $DL
$paths | ForEach-Object { Write-Host "  DENY $_" }
Write-Host "deny-list.txt sha256 $h ($($paths.Count) paths)"
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
exactly that reason.

## M2. Cut ACLs, post-ACL verify, work folders (master)

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
# the §3 check script for O3: the deny list is copied in, and master deletes it again in M3
$deny = @(Get-Content -LiteralPath "$Ops\deny-list.txt" | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
$probe = @("$P\.git\HEAD","$P\README.md","$P\src","$P\docs","$P\tools","$P\data")
$snap = (& git -C "$Cut\oracle-repo" rev-parse HEAD).Trim()
$body = @"
`$deny = @('$($deny -join "','")')
`$probe = @('$($probe -join "','")')
`$Cut = '$Cut'; `$snap = '$snap'; `$out = '$Cut\handback\setup-checks.txt'
"@ + @'
$r = New-Object System.Collections.Generic.List[string]
function Rec($ok,$m){ $r.Add(("{0} {1}" -f ($(if ($ok) {'PASS'} else {'FAIL'})), $m)) }
Rec (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators')) "not admin ($env:USERNAME)"
foreach ($p in $deny + $probe) { $denied = $false; try { Get-ChildItem -LiteralPath $p -Force -ErrorAction Stop | Select-Object -First 1 | Out-Null } catch { $denied = $true }
  if (-not $denied) { try { Get-Content -LiteralPath $p -TotalCount 1 -ErrorAction Stop | Out-Null } catch { $denied = $true } }
  Rec $denied "no read: $p" }
& git -C $probe[0].Replace('\.git\HEAD','') rev-parse HEAD 2>$null | Out-Null; Rec ($LASTEXITCODE -ne 0) 'git rev-parse on the production clone fails'
Rec (@(Get-ChildItem env: | Where-Object { $_.Name -like 'GIT_*' }).Count -eq 0) 'no GIT_* variable'
$envhit = @(Get-ChildItem env: | Where-Object { $v = [string]$_.Value; @($deny | Where-Object { $v -like "*$_*" }).Count })
Rec ($envhit.Count -eq 0) "no variable points into a denied root $($envhit.Name -join ',')"
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
Log "M2 PASS; check script $(Sha "$Cut\test-results\setup-checks.ps1")"
```

## O3. Author profile and checks (owner, signed in as the author)

Use Start > Switch user and sign in as `oracle-author` with the password the owner set. Do not sign out the operator
session, because capture runs there. In a normal (not elevated) PowerShell:

1. Install Claude Code for this account the way the owner normally does. That is a download, so it is the owner's own
   decision. Then run `claude` once and log in. The login is the owner's credential, typed by the owner.
2. Settings, git identity and the scoped `safe.directory`:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude" | Out-Null
'{ "permissions": { "deny": ["WebFetch", "WebSearch"] }, "env": { "DISABLE_AUTOUPDATER": "1" } }' |
  Set-Content -LiteralPath "$env:USERPROFILE\.claude\settings.json" -Encoding ascii
git config --global user.name 'oracle-author'
git config --global user.email 'oracle-author@localhost.invalid'
git config --global --add safe.directory 'C:/oracle-cut/r1/oracle-repo'
powershell -NoProfile -ExecutionPolicy Bypass -File C:\oracle-cut\r1\test-results\setup-checks.ps1
```

3. In `claude`, started from `C:\oracle-cut\r1`:
   - `/mcp` must list **no** servers, including claude.ai connectors. If any appear, disable them before the launch.
   - `/status` gives the model and version. Note them for master (E1).
   - The sandbox setting: if this Windows build offers no shell network sandbox, record "not supported" for the N1
     disclosure.
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
Oracle handout r1. Manifest C:\oracle-cut\r1\H1-manifest.json, SHA-256 623279703b2daac805c95e330aef4bede87ac203b75d6724d6bcae793a7b7db9. Your session prompt is C:\oracle-cut\r1\handout\H-12-session-prompt-r1.md: read it in full and follow it.
```

After that, say nothing else to the session (erratum 1 E1). The owner tells master the start time, model and Claude Code
version. Master records them with the archive (I-7).

Still open for master: the permission mode the author runs in. The default mode means the owner approves each tool call
at the machine. A mode that allows edits inside the cut removes that. The OS-level isolation holds either way.
