# Host Python upgrade runbook (capture host, 3.11.0 to 3.11.9)

> **PROPOSED - not approved; owner sign-off required before any step.**
> Nothing in this file authorizes a download, an install, a capture gap, a task change or a merge.
> [The owner sign-off checklist](#11-owner-sign-off-checklist) lists what the owner must sign first.
> Live orders, cancels and signing are out of scope here; the live launcher is resealed under its
> own runbook.

Status: proposed runbook. It turns the approved intent (DECISION_LOG, 2026-10-09: host Python
upgrade as a quiet-window job with a release re-bind; installer download, UAC and one capture gap)
into gated steps. Today's host version, the planned night and every dated hold live in
[the state of play](STATE_OF_PLAY.md), not here.

**Owns:** the procedure for moving the production checkout's `venv` from CPython 3.11.0 to 3.11.9
on the 16 GB capture host. That covers a side-by-side install, an offline wheelhouse, a stage venv
qualified by the bounded suite, the cutover through the guarded stop/restore path, verification,
rollback and cleanup. It supports release **case A only** (no active release pointer). Cases B and C
are NO-GO until a separately reviewed re-bind procedure exists (§8).

**Read when:** you prepare, review, sign or execute the host interpreter upgrade, or you change
something it depends on. That includes the capture stop and restore path, release runtime binding,
the bounded suite's interpreter override, the Scheduler task set, and live interpreter seals.

**Not here:**
- the heavy-work timetable and lease: [host load policy](HOST_LOAD_POLICY.md);
- merges and roll verdicts: [capture-day grading and guarded merges](../ops/streak-soak.md);
- release construction and promotion: [Release #1 build runbook](RELEASE_ONE_BUILD_RUNBOOK.md);
- live seals: [portable live execution host](PORTABLE_LIVE_EXECUTION_HOST.md) and
  [International MM live pilot](INTERNATIONAL_MM_LIVE_PILOT.md);
- the workstation interpreter: [development](../development.md).

## 1. Why the upgrade is a planned job, not a silent swap

Four repository facts set the shape of every phase below.

| Fact | Evidence | Consequence |
| --- | --- | --- |
| A release binds the exact interpreter version | `src/weather/release_artifacts.py`: `capture_runtime_versions` (from line 139) records `python`, `implementation`, `platform` and the direct dependency versions. `_verify_runtime_versions` (lines 219-240) raises `runtime version mismatch` on `python`, `implementation` or any dependency; `platform` is recorded but not compared. | Every release bound on 3.11.0 fails `check_runtime` on 3.11.9, and serving fails closed, until it is re-bound. With no active pointer (case A) nothing is bound. Cases B and C need a reviewed re-bind (§8). |
| The capture restart identity ignores the interpreter and the venv | `src/weather/runtime_identity.py`: `SOURCE_PATTERNS` (lines 19-28) cover repository source only, and the scope explicitly excludes `venv` site-packages (lines 141-145). `python_version` is recorded at line 222 but is not part of the identity key. | The swap does not trigger `STALE_CODE` by itself. The workers move to 3.11.9 only because the cutover stops and restarts them (C3/C7). `python_version` in each status file then proves which interpreter is running. |
| Every production-venv user resolves the interpreter by path | The registrars under `scripts/ops/` build `Join-Path $RepoRoot 'venv\Scripts\python(w).exe'` (for example `scripts/ops/training_window.ps1:99`). The pinned and linked deployments also resolve the production venv: `cold_snapshot_compression_run.ps1:114` (91a); the watchdog's pinned `status.ps1` through `-RepoRoot` ([operations design](OPERATIONS_DESIGN.md)); `manual_order_journal.ps1` through `-StateRoot`, which defaults to the code checkout (header, lines 3-6 and 28); `boot_recovery.ps1` (its `$repo` at line 37 is the production checkout, used at line 449); and the U6 exam step and export on the build line. | Rebuilding `venv` in place (rename the old one, create a new one at the same path) needs no task re-registration. It also moves **every** production-venv user to 3.11.9 at once (Q7). |
| Live seals bind interpreter bytes | `src/weather/operations/international_live_wrapper_sealer.py` (`INTERPRETER_BINDING_KEYS`, line 422): redirector, `pyvenv.cfg` and runtime process image hashes. `international_live_session_launcher_sealer.py:387-395` and `:1330-1336`: "reviewed production interpreter hash changed". | Any seal that binds this venv fails closed after the cutover. The state of play already requires every live seal to be resealed before any live attempt. The reseal must come **after** the cutover. |

The live SDK portability check accepts any 3.11 patch release
(`src/weather/market/live_sdk_portability.py:367` checks `sys.version_info[:2] == (3, 11)`).

## 2. Gates (any one fails = NO-GO, nothing touched)

| Gate | Condition | Checked at |
| --- | --- | --- |
| G0 | The owner has signed §11 for this runbook revision and has named the night. | Before Phase A |
| G1 | The bounded suite supports `-InterpreterPath` and `-ExpectedInterpreterVersion` (`scripts/ops/bounded_worktree_test_suite.ps1:44-52`). | Met on master; re-read `param(` if the script changed |
| G2 | Phase A and Phase B passed on earlier nights, and `$R\qualification.json` has `"result":"PASS"`. | C0 |
| G3 | The production HEAD equals the qualified tip, or `roll_verdict.ps1 -Branch` on the difference is roll-free. | C0 |
| G4 | The owner is reachable from 00:30 to 03:45 on the cutover night: GO at C0, and any escalation up to the end of §R. Phase A also needs the owner at the machine for UAC. | C0, A4 |
| G5 | No other lease user is due that night. Specifically: <br>- `WeatherTrainingWindow` (a 01:00 one-shot, `register_training_window.ps1:3`) is disabled or has no trigger that night; <br>- Stage B `WeatherEveningEvidenceRefresh` (00:35, holds the lease to 09:00 when enabled; `register_daily_refresh.ps1:20-24`) is disabled; <br>- no integration attempt, quiet-window merge, storage one-shot or held-head work is scheduled. | Phase B (B0), C0 |
| G6 | Release case A: `artifacts\releases\current_release.json` is absent (H5, B3, C0). Case B or C is NO-GO for this runbook (§8). | H5, B3, C0 |
| G7 (LFC) | The cutover night is **after** LFC session 0 has ended and its handback is recorded. It is never the night before a scheduled LFC session. | C0 |
| G8 (88a) | The night is after the 88a merge freeze in the state of play. `$R\q12.txt` records the owner's Q12 choice as `STOP_AUTHORIZED` with its DECISION_LOG reference. Any other value means NO-GO, because the 88a worker would hold the venv. | Sign-off, C0, C2 |
| G9 (tzdata) | The tzdata sequencing is decided (Q13), so the freeze comparison in `Test-Venv` cannot false-fail. | Before Phase B |
| G10 (seals) | No live attempt is planned between the cutover and the reseal. | Sign-off |
| G11 (DST) | No phase of this runbook runs on the DST fall-back night (the night of 10-31 to 11-01). That night is under OD30 (HOST_LOAD_POLICY rule 10), and the repeated hour breaks the `.Date.AddHours()` deadlines below. | Every phase |
| G12 (downloads) | The owner has approved the PyPI wheel downloads (§T, B1a, B1b) as well as the installer download. | Sign-off |

## 3. Question register

Status key:
- **RESOLVED**: settled from repository evidence;
- **NEEDS-HOST-READ**: the read-only command is in §4;
- **OWNER-DECISION**: options are given with the recommendation first, and are collected in §11.

| # | Question | Status | Answer or next step |
| --- | --- | --- | --- |
| Q1 | Can an interactive session stop, see and verify the S4U capture workers? | **RESOLVED** (H6 optional corroboration) | Run Phase C and §R in an **elevated** window. The stop confirmation is PID-based: `capture_resource_gate.py:150-158` marks a loop active when the status PID or the writer-lock PID is alive (or heartbeat, lock and PID evidence agree). It uses the gate the training window uses (`training_window.ps1:238-252`), so it works from an interactive shell. The binding recovery proof is the S4U `WeatherTrainingWindowRestore` task (S4U at `register_training_window.ps1:115-118`, `-RestoreOnly` at :140). It writes `restore_only` / `capture_recovery_pass` (`training_window.ps1:277-290`) and takes no lease (the lease is at :352, after the restore-only exit). `capture_recovery_check` is documented to run in the S4U context (`capture_recovery_check.py:1-6`), and a non-elevated session cannot read S4U command lines (HOST_LOAD_POLICY, "residual scan" paragraph), so the interactive check is corroboration only. The rename failing on a locked file is the final backstop. |
| Q2 | Exact interpreter flag on the bounded suite | **RESOLVED** (closed earlier) | `-ExpectedInterpreterVersion` takes an exact `X.Y.Z` and requires `-InterpreterPath` (`bounded_worktree_test_suite.ps1:44-52`). |
| Q3 | Does the U6 export collide with the cutover? | **RESOLVED, conditional** (H8 confirms) | `WeatherReplayBundleExportNightly` stays unregistered until the owner says yes (state of play). The owner approved its 04:10 slot (DECISION_LOG 2026-10-09), so 04:10 is the likely registration. The 00:35 slot is the only one on the build-line registrar. If it is registered, it is in the C2 aux list and stays **disabled** from C2 until C9b, and §R does not re-enable it unless capture is 3/3. A 00:35 run with its 50-minute limit releases by 01:25, before the 01:30 latest lease; a 04:10 run starts after the 03:45 rollback deadline. |
| Q4 | Will the installer offer "Upgrade" over the existing 3.11.0? | **NEEDS-HOST-READ** (H1), then **OWNER-DECISION** | PEP 514 allows one `PythonCore\3.11` registration per hive (HKCU, HKLM). Inference, not tested: install 3.11.9 in the **opposite** scope from the existing 3.11.0 (all users if 3.11.0 is per-user, and the reverse). The owner cancels if the first page says *Upgrade* or *Modify*. A NuGet or embeddable-zip fallback is a new download and needs its own approval. |
| Q5 | Release case A, B or C? | **RESOLVED: case A expected; NEEDS-HOST-READ H5 to confirm** | The state of play says there is no release store on the host. The pointer path is `artifacts\releases\current_release.json` (`release_artifacts.py:49-50`). H5, B3 and C0 re-check it. Any case other than A is NO-GO (G6, §8). |
| Q6 | #259 test ids | **RESOLVED** (closed earlier) | #259 is on master. Its parametrized `constructor` / `pre_3_11_2` tests (`tests/sources/test_wu_redaction.py`, around lines 680 and 721) run on every 3.11 patch without skip or xfail, and must pass in B2. |
| Q7 | Which venvs and deployments move with the cutover? | **RESOLVED; contradicts the original plan.** Sibling venvs: H4 | The pinned watchdog, the 91a cold snapshot, the manual order journal, boot recovery and the U6 exam deployment all run the **production** venv (evidence in §1). They move to 3.11.9 at the cutover; none is left on 3.11.0. The scheduled ones are quiesced in C2 and verified in §9. Sibling worktree venvs keep `home = <3.11.0>` and keep working, because 3.11.0 stays installed. |
| Q8 | Are 3.11.10 and later fixes needed? | **OWNER-DECISION** | 3.11.9 is the last 3.11 release with a Windows installer. §5 lists the audited and not-audited items. Recommendation: take 3.11.9 now and track a 3.12/3.13 move separately. |
| Q9 | Where does the installer SHA-256 come from? | **OWNER-DECISION** | python.org publishes the size and MD5 for 3.11.9, but no SHA-256. Recommendation: require all four of the python.org size, the python.org MD5, the third-party winget manifest SHA-256 and a valid PSF Authenticode signature. Sigstore verification is optional and needs its own download decision. |
| Q10 | Build backend for the editable install | **RESOLVED** (H2 records versions) | `pyproject.toml` requires `setuptools>=69`, but a fresh 3.11.9 venv bundles setuptools 65.5.0. The editable install therefore uses build isolation fed from the wheelhouse: pip passes `--no-index --find-links` to the isolated build. Pin a setuptools release of 70.1 or later in `lock-build`. From 70.1 setuptools ships `bdist_wheel` itself; if you pin an older release, add `wheel` to `lock-build`. The B1a hash script fails closed if a wheel is missing. |
| Q11 | Names on master (memory guard reader, tape stop verb, status key, gate flags) | **RESOLVED** (closed earlier) | `Read-WeatherMemoryGuardStatus -Path` (`memory_guard_status_reader.ps1:13-17`); `execution_tape_supervisor stop` has no arguments (`execution_tape_supervisor.py:880`); `updated_at` (`training_window.ps1:144`). |
| Q12 (new) | How does the 88a worker release the venv? | **OWNER-DECISION**, recorded in `$R\q12.txt` (G8) | `WeatherMakerEvidenceCapture` runs one long-lived worker that holds the lock ([passive maker evidence capture](passive-maker-evidence-capture.md), "Commands and registration"). Its CLI has no stop verb and no stop file (`maker_evidence_capture.py:365-372`), so disabling the task does not end it, and the rename fails while it runs. **Recommendation:** after the 88a freeze, the owner authorizes `Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture` at C2 (record `STOP_AUTHORIZED`), with the resume check in C9c. Risk: an abrupt stop skips `store.seal()` (`maker_evidence_capture.py:343-360`), and the store raises "torn journal" on a partial last line (`maker_evidence_store.py:142-143`). Alternative: wait for a reviewed graceful-stop verb, which is 88a capture behaviour and waits for the freeze to end. Until one exists, the cutover is NO-GO. |
| Q13 (new) | When should tzdata 2026.3 be installed? | **OWNER-DECISION** | `tzdata` is not pinned in `requirements.txt`. If the lock forces `tzdata==2026.3` while the 3.11.0 freeze holds another version, `Test-Venv` and C1 compare the freeze and false-fail. **Recommendation:** run §T on an earlier admitted night, then take the A1 receipts so the freeze already contains 2026.3. Alternative: exempt the `tzdata` line in both comparisons and record the exemption. |
| Q14 (new) | Do the moved deployments behave the same on 3.11.9? | **RESOLVED to a verification step** | They run the same code and pinned dependencies on the new interpreter. The first post-cutover run of each is checked in §9; 91a fires at 06:50 the same morning. |

## 4. Host reads (read-only; master-agent runs them before sign-off)

Run these in Windows PowerShell 5.1 on the capture host:
- **only inside 00:30-09:00**, serially, never in parallel with other work;
- not on the DST night (G11);
- with the session variables and helpers from §6 loaded.

Rule 6 of the host load policy lets the S4U guard end agent-owned Python outside that window. None
of these reads changes state. Save the output under `$R\host-reads\`.

```powershell
$HR = Join-Path $R 'host-reads'; New-Item -ItemType Directory -Force $HR | Out-Null
# H1 (Q4): PEP 514 registrations and uninstall entries for 3.11
foreach ($k in 'HKCU:\Software\Python\PythonCore','HKLM:\SOFTWARE\Python\PythonCore','HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore') {
  Get-ChildItem -LiteralPath $k -ErrorAction SilentlyContinue | ForEach-Object {
    $ip = Get-ItemProperty -LiteralPath (Join-Path $_.PSPath 'InstallPath') -ErrorAction SilentlyContinue
    '{0} | InstallPath={1}' -f $_.Name, $ip.'(default)' } } | Out-File "$HR\h1-pythoncore.txt" -Encoding utf8
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -like 'Python 3.11*' } | Select-Object DisplayName, DisplayVersion, InstallLocation, PSPath |
  Format-List | Out-File "$HR\h1-uninstall.txt" -Encoding utf8
# H2 (Q10, Q13): production venv identity and packaging tools
$null = Invoke-Native $Py @('-VV') "$HR\h2-vv"
Get-Content -LiteralPath (Join-Path $P 'venv\pyvenv.cfg') | Out-File "$HR\h2-pyvenv.txt" -Encoding utf8
$null = Invoke-Native $Py @('-m','pip','freeze','--all') "$HR\h2-freeze"
Select-String -LiteralPath "$HR\h2-freeze.out.txt" -Pattern '^(pip|setuptools|wheel|tzdata)==' | ForEach-Object Line | Out-File "$HR\h2-tools.txt" -Encoding utf8
# H3 (Q7, C2): every task whose action names a venv, python or a .ps1 wrapper, with state and principal
Get-ScheduledTask | ForEach-Object { $t = $_; foreach ($a in $t.Actions) { [pscustomobject]@{
  Task=$t.TaskPath+$t.TaskName; State=[string]$t.State; Logon=[string]$t.Principal.LogonType; Execute=$a.Execute; Arguments=$a.Arguments } } } |
  Where-Object { ($_.Execute + ' ' + $_.Arguments) -match 'venv|python|\.ps1' } |
  Export-Csv -LiteralPath "$HR\h3-tasks.csv" -NoTypeInformation -Encoding utf8
# H4 (Q7): sibling venvs and their home
Get-ChildItem -LiteralPath (Split-Path $P) -Directory | ForEach-Object { $c = Join-Path $_.FullName 'venv\pyvenv.cfg'
  if (Test-Path -LiteralPath $c) { "$($_.FullName): " + ((Get-Content -LiteralPath $c) -join ' | ') } } | Out-File "$HR\h4-venvs.txt" -Encoding utf8
# H5 (Q5, G6): release store and the active pointer (release_artifacts.py:49-50)
'releases_dir={0} pointer={1}' -f (Test-Path -LiteralPath (Join-Path $P 'artifacts\releases')),
  (Test-Path -LiteralPath (Join-Path $P 'artifacts\releases\current_release.json')) | Out-File "$HR\h5-release.txt" -Encoding utf8
# H6 (Q1, optional): run once elevated and once non-elevated; compare the two files
$tag = if (([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { 'elevated' } else { 'plain' }
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Select-Object ProcessId, ParentProcessId, ExecutablePath, @{n='CmdVisible';e={[bool]$_.CommandLine}}, CommandLine |
  Format-List | Out-File "$HR\h6-procs-$tag.txt" -Encoding utf8
$crc = Invoke-Native $Py @('-m','weather.operations.capture_recovery_check','--repo-root',$P,'--json') "$HR\h6-crc-$tag"; "exit=$crc" | Out-File "$HR\h6-crc-$tag.exit.txt"
# H7 (Q12): long-running holders of the production venv, read from the H6 output. Expect the three capture
#   workers, the execution tape, the maker shadow runner and the 88a worker; list any other holder.
# H8 (Q3): U6 export registration
Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue |
  ForEach-Object { "$($_.State) next=$((Get-ScheduledTaskInfo $_).NextRunTime) limit=$($_.Settings.ExecutionTimeLimit)" } |
  Out-File "$HR\h8-u6.txt" -Encoding utf8
# H9 (receipt baseline): bundled native library versions of the running interpreter
$null = Invoke-Native $Py @('-I','-c','import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version); print(zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)') "$HR\h9-native-3110"
```

## 5. Changelog audit (3.11.1 to 3.11.9) and wheel compatibility

The audit is scoped to fixes that touch the stdlib surfaces this repository uses. It lists only
items that can be cited with confidence. Everything else is **not audited**, and two things stand
in for it: the receipts (C8e) and the bounded suite on the stage interpreter (B2).

| Release | Item | Relevance here | Confidence |
| --- | --- | --- | --- |
| 3.11.1 | gh-98433 (CVE-2022-45061), quadratic IDNA decoding | `urllib.request` / `requests` hostname handling | High |
| 3.11.1 | gh-98517 (CVE-2022-37454), `_sha3` buffer overflow | `hashlib` sha3 is not a binding hash here (SHA-256 is) | High |
| 3.11.1 | gh-98744 (traceback unicode crash); gh-97825 | gh-97825: no matching call in `src/` | High (repo-verified in the #259 report) |
| 3.11.1-3.11.2 | Windows build zlib and OpenSSL 1.1.1 updates (gh-98689, gh-100180) | `gzip`, all HTTPS | High |
| 3.11.2 | gh-98778 `HTTPError` construction | Already guarded by #259 | High (verified at the tags) |
| 3.11.2 | gh-95882 wrong tracebacks through `@contextmanager` | Several `src/` modules use `contextmanager` | High |
| 3.11.2 | gh-101283 safer `cmd.exe` lookup for `shell=True` | No `shell=True` in `src/` or `app/` | Medium |
| 3.11.4 | PEP 706 tarfile extraction filters (gh-102950) | Archives are read through `extractfile` only (`verified_cold_archive.py:1249`, `:1432`); no `extractall` | Medium |
| 3.11.4 | gh-102153 (CVE-2023-24329) `urlsplit` strips leading C0 control and space characters | `urllib.parse` is widely used; inputs are configured URLs | Medium |
| 3.11.5 | gh-108310 (CVE-2023-40217) `ssl` pre-close data bypass | All HTTPS (no direct `import ssl` in `src/`) | Medium |
| 3.11.8 | `traceback` guard for a malformed `__notes__` | Checked at the v3.11.x tags by the #259 report. Issue number not audited. | High for presence |
| 3.11.x | Windows builds moving from OpenSSL 1.1.1 to 3.0, and the OpenSSL version bundled with 3.11.9 | All HTTPS; OpenSSL 3.0 tightens TLS defaults | **Not audited** (which release made the move, and the exact 3.11.9 version). The A4 and C8e receipts record the real version; capture recovering in C7 and the tape in C9c are the functional proof. |
| any | `zipfile`, `email`, `http.server`, `xml.etree`, `sqlite3`, `ctypes`, `subprocess` changes | Used here (`wu_token_scan.py`, `io.py`, `wallet_reader_server.py`, and others) | **Not audited** |
| any | Byte reproducibility of `tarfile` headers (`tobuf`) and gzip output | `bulk_cold_archive_crypt.py:222-228` compares `tobuf` header bytes | **Not audited.** §9 runs a read-only verify of an existing cold archive on 3.11.9. |

**Wheel compatibility:**
- Every direct pin in `requirements.txt` / `pyproject.toml` installs as a `cp311-win_amd64`, abi3 or pure wheel.
- The CPython ABI is stable across 3.11 patch releases, so no dependency version changes.
- The workstation venv already runs 3.11.9 with identical pins.
- The B1a hash script exits non-zero if any pinned distribution lacks a Windows or pure wheel.
- B1b proves the wheel bytes equal the files installed in the 3.11.0 venv.

## 6. Session header (paste first in every host session)

Windows PowerShell 5.1, ELEVATED, as the capture host's operator account. **The paths below are
illustrative. Set them from the host's own facts** (the task actions in `Get-ScheduledTask`, and
the `home` key of `pyvenv.cfg`) and record them in `$R\paths.json` during Phase A. Never paste
workstation paths.

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
function Assert-CaseA($ra, $tag) {
  if ($ra.status -ne 'BLOCK' -or $ra.error -notlike '*active release pointer is missing*') { NoGo "$tag release is not case A: $($ra | ConvertTo-Json -Compress)" }
  if (Test-Path -LiteralPath (Join-Path $P 'artifacts\releases\current_release.json')) { NoGo "$tag active release pointer exists" } }
. (Join-Path $P 'scripts\ops\workload_admission.ps1')
. (Join-Path $P 'scripts\ops\memory_guard_status_reader.ps1')
Log "session start host=$env:COMPUTERNAME head=$(git -C $P rev-parse HEAD)"
```

Trap reminders ([operations agent role](OPERATIONS_AGENT_ROLE.md) §5):
- there is no `&&`;
- use `-LiteralPath`;
- never append `2>$null` to native `git`;
- never run a recursive listing of `data\`;
- track and terminate every process you start.

Plain `& $exe ...; if ($LASTEXITCODE)` calls with no stderr redirection are safe under `Stop`.

`Enter-WeatherHeavyWorkloadLease` returns `$null` when the lease is busy and throws outside
00:30-09:00. Keep a whole phase in one PowerShell process, and release the lease on every exit path.
`NoGo` does that while `$global:ReleaseOnNoGo` is set. If any other command throws in a leased
step, run `Release-Lease` before you leave the session. The one exception is after the C4 rename,
where §R needs the lease.

### 6a. Constants file (prepared before Phase A, reviewed in the handoff)

`$R\constants.json` holds the published installer facts. It keeps them in one reviewed place,
not in prose. Source each value as stated:

| Key | Source |
| --- | --- |
| `installer_url` | python.org 3.11.9 release page (`python-3.11.9-amd64.exe`) |
| `installer_size`, `installer_md5` | python.org release page / release API |
| `installer_sha256` | `microsoft/winget-pkgs`, manifest for `Python.Python.3.11` version 3.11.9 (third-party, Q9) |
| `signer_subject_prefix`, `signer_thumbprint` | Authenticode of the same installer, observed on the workstation |
| `vv_prefix` | `python -VV` of the workstation's 3.11.9 install, up to the first comma |
| `binaries` | SHA-256 of `python.exe`, `pythonw.exe`, `python311.dll`, `python3.dll`, `vcruntime140*.dll`, `Lib\venv\scripts\nt\python(w).exe`, `DLLs\_ssl.pyd`, `DLLs\libssl-3.dll`, `DLLs\libcrypto-3.dll` from the workstation's 3.11.9 home |

Workstation command for `binaries` and `vv_prefix`. It is read-only and runs on the workstation,
never the host:

```powershell
$WsHome = (& .\venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)").Trim()
$rel = 'python.exe','pythonw.exe','python311.dll','python3.dll','vcruntime140.dll','vcruntime140_1.dll',
       'Lib\venv\scripts\nt\python.exe','Lib\venv\scripts\nt\pythonw.exe','DLLs\_ssl.pyd','DLLs\libssl-3.dll','DLLs\libcrypto-3.dll'
$b = [ordered]@{}; foreach ($r in $rel) { $b[$r] = (Get-FileHash -LiteralPath (Join-Path $WsHome $r) -Algorithm SHA256).Hash.ToUpper() }
[ordered]@{ vv_prefix = ((& (Join-Path $WsHome 'python.exe') -VV) -replace ',.*$',''); binaries = $b } | ConvertTo-Json
```

### 6b. Helper scripts (verbatim; copy into `$Tools`, outside `$WH`)

These two stdlib-only scripts decide B1a and B1b. They are part of the reviewed text, so review them
here and do not edit them on the night.

`pypi_hash_lock.py` reads a `name==version` file and writes a `--require-hashes` lock. It accepts
Windows and pure wheels only, and exits non-zero if any pin has none:

```python
import json, re, sys, urllib.request
OK = re.compile(r"-(cp311-cp311-win_amd64|cp311-abi3-win_amd64|abi3-win_amd64|none-win_amd64|py3-none-any|py2\.py3-none-any)\.whl$")
out = []
for line in open(sys.argv[1], encoding="ascii"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    name, ver = line.split("==", 1)
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=60) as r:
        data = json.load(r)
    hashes = sorted({u["digests"]["sha256"] for u in data["urls"]
                     if u["packagetype"] == "bdist_wheel" and OK.search(u["filename"]) and not u.get("yanked")})
    if not hashes:
        sys.exit(f"NO WINDOWS/PURE WHEEL for {name}=={ver}")
    out.append(f"{name}=={ver} " + " ".join(f"--hash=sha256:{h}" for h in hashes))
open(sys.argv[2], "w", encoding="ascii").write("\n".join(out) + "\n")
print(f"{len(out)} pins hashed")
```

`verify_wheels_vs_installed.py` compares each wheel's hashed `RECORD` rows with the installed
`RECORD` of the same distribution, ignoring `.pyc` and `.data/` rows. It prints `OK`, `DIFF`,
`MISSING-INSTALLED` or `UNMATCHED-ALLOWED` per wheel:

```python
import csv, io, pathlib, re, sys, zipfile
wh, site = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
allow_unmatched = {a.lower() for a in sys.argv[3:]}
def rows(text):
    return {(p, h) for p, h, *_ in csv.reader(io.StringIO(text)) if h and ".data/" not in p and not p.endswith(".pyc")}
bad = 0
for whl in sorted(wh.glob("*.whl")):
    with zipfile.ZipFile(whl) as z:
        rec = next(n for n in z.namelist() if n.endswith(".dist-info/RECORD") and n.count("/") == 1)
        dist = rec.split("/")[0]
        wrows = rows(z.read(rec).decode("utf-8"))
    inst = site / dist / "RECORD"
    name = re.split(r"-\d", dist, maxsplit=1)[0].lower().replace("_", "-")
    if not inst.exists():
        if name in allow_unmatched:
            print("UNMATCHED-ALLOWED", whl.name); continue
        print("MISSING-INSTALLED", whl.name); bad += 1; continue
    diff = wrows ^ rows(inst.read_text("utf-8"))
    print(("OK " if not diff else "DIFF ") + whl.name + ("" if not diff else f" ({len(diff)} rows)"))
    bad += bool(diff)
sys.exit(1 if bad else 0)
```

## 7. Phases

| Phase | Night | Window | Lease | Capture effect |
| --- | --- | --- | --- | --- |
| §4 host reads | before sign-off | 00:30-09:00, serial | no | none |
| §T tzdata (if Q13 = earlier night) | an earlier night | 00:30-04:45 | yes | none until the next worker restart |
| A install side by side | any night after sign-off | 00:30-09:00, owner at the machine | no | none |
| B wheelhouse, stage venv, bounded suite | a prep night after A, G5 holds | B0 by 02:00, suite start by 03:00, finished by 04:45 | yes (released before B2) | none |
| C cutover | the signed night (G7, G8, G11) | 00:30-02:30; rollback starts by 03:15 | yes | about 20-35 min gap |
| §D cleanup | a later night | 00:30-04:45 | no | none |

Phase B must finish before the 04:45-06:45 tiering reserve and the 06:50 jobs (91a, exchange
economics). The bounded suite's own limit (`MaxRuntimeSeconds`, `bounded_worktree_test_suite.ps1:27`)
is why the suite starts no later than 03:00. Using the tiering hole (HOST_LOAD_POLICY rule 10) to run
later needs at least 100 GiB free and skips tiering that night; that is an owner choice, not a
default.

### §T. tzdata 2026.3 on the current 3.11.0 venv (if Q13 chooses an earlier night)

This is light pip work under the lease, with the workers left running.
- **Not a code roll.** The source fingerprint excludes the venv (`runtime_identity.py` lines 19-28 and
  141-145), so installing tzdata cannot trigger `STALE_CODE`.
- **Capture does read tzdata.** On Windows, `ZoneInfo("America/Toronto")` (`model_constants.py:13`,
  `runtime_monitor.py:39`) loads it from the `tzdata` package. Running workers keep the zone data they
  already loaded. The new data takes effect at each worker's next restart, which is at the latest the
  cutover itself.

```powershell
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py_tzdata_2026_3'; if (-not $Lease) { NoGo 'lease busy' }
try {
  & $Py -m pip freeze --all | Out-File "$R\freeze-before-tzdata.txt" -Encoding utf8
  'tzdata==2026.3' | Set-Content "$R\lock-tz.txt" -Encoding ascii
  & $Py -I "$Tools\pypi_hash_lock.py" "$R\lock-tz.txt" "$R\lock-tz-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tzdata hash' }
  & $Py -m pip download --isolated --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r "$R\lock-tz-hashed.txt" -d "$R\tzdata"; if ($LASTEXITCODE) { NoGo 'tzdata download' }
  & $Py -m pip install --isolated --no-index --no-deps --require-hashes --find-links "$R\tzdata" -r "$R\lock-tz-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tzdata install' }
  & $Py -m pip freeze --all | Out-File "$R\freeze-after-tzdata.txt" -Encoding utf8
  $d = Compare-Object (Get-Content "$R\freeze-before-tzdata.txt") (Get-Content "$R\freeze-after-tzdata.txt"); $d | Out-File "$R\freeze-diff-tzdata.txt"
  if ($d | Where-Object { $_.InputObject -notmatch '^tzdata==' }) { NoGo 'a line other than tzdata changed - roll back tzdata and inspect' }
  if (-not ($d | Where-Object { $_.SideIndicator -eq '=>' -and $_.InputObject -eq 'tzdata==2026.3' })) { NoGo 'tzdata==2026.3 not in the after-freeze' }
} finally { Release-Lease }
```

Rollback: reinstall the previous version from the before-freeze, or `pip uninstall tzdata` if it was
absent.

### Phase A. Install side by side (owner-attended; no capture change; no lease)

**A1. Receipts.** Take them after §T if §T runs.

```powershell
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

**A1 review (master-agent, at prep).** Build `$R\aux-tasks.txt`, one task name per line, from
`tasks-venv.csv`. It lists every task that starts the production venv, **except**:
- the three capture supervisors (C3 handles them);
- `WeatherTrainingWindowRestore` (the restore path);
- `WeatherMemoryCommitGuard` (no Python; it must keep guarding);
- `WeatherBootRecovery` (startup trigger only).

**Disabled-at-C2 list.** It must include any of these that exist:

| Task |
| --- |
| `WeatherExecutionTapeSupervisor` |
| `WeatherMakerEvidenceCapture` |
| `WeatherMakerShadowRunner` |
| `WeatherManualOrderJournal` |
| `WeatherHostHealthWatchdog` |
| `WeatherModelMarketDisagreementAnalysis` |
| `WeatherClobEnrichmentLoop` |
| `WeatherNightlyRetrainValidatePromote` |
| `WeatherDailySettlementPromotionRefresh` |
| `WeatherEveningEvidenceRefresh` |
| `WeatherLocationConfigRefresh` |
| `WeatherClobTiering` |
| `WeatherClobRawTapeTiering` |
| `WeatherColdSnapshotNightly` |
| `WeatherExchangeEconomicsSnapshotRefresh` |
| `WeatherReplayBundleExportNightly` (only if present) |
| host-local tasks that name the venv |

Use the exact names from the dump. A wrong name fails loudly in C2, because C2 does not suppress
lookup errors.

**A2. Disaster copy of the old home.**

```powershell
robocopy $OldHome '<freeze copy, e.g. C:\PyFreeze\cp3110>' /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NP /LOG:"$R\robocopy-oldhome.log"
if ($LASTEXITCODE -ge 8) { NoGo "robocopy exit $LASTEXITCODE" }
```

**A3. Download and verify the installer on the host (approved download).**

```powershell
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

**A4. UAC install (the owner clicks).** Set the scope from H1 (Q4): `InstallAllUsers=1` if the
existing 3.11.0 is per-user, `0` if it is all-users. PATH, the launcher, file associations,
shortcuts and precompile are all off.

```powershell
$before = @{ M=[Environment]::GetEnvironmentVariable('Path','Machine'); U=[Environment]::GetEnvironmentVariable('Path','User') }
$AllUsers = '<1 or 0 from H1>'
$instArgs = @("InstallAllUsers=$AllUsers","TargetDir=$NewHome","DefaultAllUsersTargetDir=$NewHome","DefaultJustForMeTargetDir=$NewHome",
  'PrependPath=0','AppendPath=0','Include_launcher=0','InstallLauncherAllUsers=0','AssociateFiles=0','Shortcuts=0','CompileAll=0',
  'Include_symbols=0','Include_debug=0','Include_test=0','Include_doc=0','Include_tcltk=1','/log',"$R\install.log")
$proc = Start-Process -FilePath $Exe -ArgumentList $instArgs -Verb RunAs -Wait -PassThru; Log "installer exit $($proc.ExitCode)"
```

Owner instructions:
- The first page must say **"Install Python 3.11.9"**. If it says *Upgrade* or *Modify*, click **Cancel**: that is NO-GO, and Q4 goes back to the owner.
- Choose *Customize installation*. Confirm the scope and the target directory, and that the launcher, environment variables and precompile are off.

```powershell
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

If A4 fails after the installer ran:
- restore the old home from the freeze copy if it changed;
- check capture with the next `status.ps1` run;
- do not continue to Phase B.

### Phase B. Wheelhouse, stage venv, qualification (prep night; capture keeps running on 3.11.0)

**B0. Admission (00:30-02:00; G5 holds).**

```powershell
$h = (Get-Date).Hour + (Get-Date).Minute/60; if ($h -lt 0.5 -or $h -ge 2.0) { NoGo 'outside the Phase B start window' }
foreach ($t in 'WeatherTrainingWindow','WeatherEveningEvidenceRefresh') { $x = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  if ($x -and [string]$x.State -ne 'Disabled') { NoGo "$t is enabled (G5)" } }
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 55GB) { NoGo 'disk below the bounded-suite floor plus margin' }
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_prep'; if (-not $Lease) { NoGo 'lease busy' }
$global:ReleaseOnNoGo = $true     # any NoGo from here to the end of B1e releases the lease
```

From B0 to B1e, any `NoGo` releases the lease. If something else throws, run `Release-Lease`
before you stop.

**B1a. Hashed lock.** The repository pins only the direct dependencies, without hashes. The lock
comes from the A1 freeze, and the hashes come from PyPI over HTTPS (owner-approved under G12).

```powershell
New-Item -ItemType Directory -Force $WH | Out-Null
Get-Content "$A\freeze-3110.txt" | Where-Object { $_ -match '^[A-Za-z0-9_.\-]+==' } | Set-Content "$R\lock.txt" -Encoding ascii
'setuptools==<a release >= 70.1 chosen at prep>' | Set-Content "$R\lock-build.txt" -Encoding ascii     # Q10
# Only if Q13 chose the exemption: replace the tzdata line in lock.txt with tzdata==2026.3.
& $NewPy -I "$Tools\pypi_hash_lock.py" "$R\lock.txt" "$R\lock-hashed.txt";             if ($LASTEXITCODE) { NoGo 'hash lock' }
& $NewPy -I "$Tools\pypi_hash_lock.py" "$R\lock-build.txt" "$R\lock-build-hashed.txt"; if ($LASTEXITCODE) { NoGo 'build lock' }
```

**B1b. Download with hashes, then prove the bytes equal the installed 3.11.0 files.**

```powershell
& $NewPy -I -m pip download --isolated --no-cache-dir --require-hashes --only-binary=:all: --no-deps `
  --python-version 3.11 --platform win_amd64 --implementation cp -r "$R\lock-hashed.txt" -d $WH;  if ($LASTEXITCODE) { NoGo 'download lock' }
& $NewPy -I -m pip download --isolated --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r "$R\lock-build-hashed.txt" -d $WH; if ($LASTEXITCODE) { NoGo 'download build' }
Get-ChildItem -LiteralPath $WH -File | ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.Name } | Set-Content "$R\wheelhouse-sha256.txt" -Encoding utf8
& $NewPy -I "$Tools\verify_wheels_vs_installed.py" $WH (Join-Path $P 'venv\Lib\site-packages') setuptools | Tee-Object -FilePath "$R\wheel-vs-installed.txt"
if ($LASTEXITCODE) { NoGo 'wheel bytes differ from the installed 3.11.0 packages' }
```

**Go/no-go B1b:**
- every wheel reports `OK`;
- only the build-only `setuptools` may be `UNMATCHED-ALLOWED` (add `tzdata` to the allow list only under the Q13 exemption);
- a `DIFF` limited to `.dist-info` metadata at an identical version goes to the owner;
- any other `DIFF` is NO-GO.

**B1c. Stage worktree and stage venv, fully offline.**

```powershell
$Tip = (git -C $P rev-parse HEAD).Trim(); $QBranch = 'py3119-qual-' + (Get-Date -Format yyyyMMdd)
$env:GIT_LFS_SKIP_SMUDGE = '1'; git -C $P worktree add -b $QBranch $Stage $Tip; $wt = $LASTEXITCODE; Remove-Item Env:GIT_LFS_SKIP_SMUDGE
if ($wt) { NoGo 'worktree add' }
& $NewPy -I -m venv (Join-Path $Stage 'venv'); if ($LASTEXITCODE) { NoGo 'stage venv' }
function Build-Venv($vpy, $root) {
  Select-String -LiteralPath "$R\lock-hashed.txt" -Pattern '^(pip|setuptools|wheel)==' | ForEach-Object Line | Set-Content "$R\lock-tools-hashed.txt" -Encoding ascii
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-tools-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tools install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-hashed.txt";       if ($LASTEXITCODE) { NoGo 'lock install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --no-deps -e $root;                                    if ($LASTEXITCODE) { NoGo 'editable install' }
}
Build-Venv $StagePy $Stage
```

The editable install builds in an isolated environment. That environment gets `setuptools` from
`$WH`, because pip passes `--no-index --find-links` to it (Q10).

**B1d. Test-Venv (reused in C6).**

```powershell
function Test-Venv($vpy, $root, $tag) {
  $out = Join-Path $R "check-$tag"; New-Item -ItemType Directory -Force $out | Out-Null
  $vv = & $vpy -VV; $vv | Set-Content "$out\VV.txt"; if ($vv -notlike "$($K.vv_prefix)*") { NoGo "$tag VV" }
  $cfg = Get-Content -LiteralPath (Join-Path (Split-Path (Split-Path $vpy)) 'pyvenv.cfg')
  if (-not ($cfg -match ('^home\s*=\s*' + [regex]::Escape($NewHome) + '\s*$'))) { NoGo "$tag pyvenv home" }
  & $vpy -I -m pip check | Set-Content "$out\pipcheck.txt"; if ($LASTEXITCODE) { NoGo "$tag pip check" }
  $skip = '^(-e |#)'   # under the Q13 exemption use '^(-e |#|tzdata==)'
  $d = Compare-Object (Get-Content "$A\freeze-3110.txt" | Where-Object { $_ -notmatch $skip }) (& $vpy -m pip freeze --all | Where-Object { $_ -notmatch $skip })
  $d | Out-File "$out\freeze-diff.txt"; if ($d) { NoGo "$tag freeze differs" }
  # import location: run from a neutral directory so only the editable install can supply the packages
  Push-Location -LiteralPath $R
  try {
    $loc = & $vpy -c "import weather, maker_core; print(weather.__file__); print(maker_core.__file__)"; if ($LASTEXITCODE) { NoGo "$tag import location" }
    $src = (Join-Path $root 'src') + '\'
    foreach ($l in $loc) { if (-not $l.StartsWith($src, [StringComparison]::OrdinalIgnoreCase)) { NoGo "$tag package imported from $l, not $src" } }
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
Test-Venv $StagePy $Stage 'stage'
```

**B1e. Model-load smoke.** The stage worktree has LFS pointers only, so load the serving HGB
artifacts from the production checkout. `src/weather/model/model_features.py:66-68` unpickles them.

```powershell
Push-Location -LiteralPath $Stage
& $StagePy -c "import glob, pickle, sys; fs = sorted(glob.glob(sys.argv[1])); assert fs, 'no artifacts'; [pickle.load(open(f, 'rb')) for f in fs]; print('hgb load ok')" (Join-Path $P 'artifacts\models\hgb\feature_model_hgb*.pkl')
if ($LASTEXITCODE) { NoGo 'hgb load' }
Pop-Location
$global:ReleaseOnNoGo = $false; Release-Lease
```

**B2. Bounded suite on the stage interpreter.** The suite takes its own lease, needs at least
50 GiB free, and starts by 03:00 (§7). Run it in a child PowerShell, so that a throw cannot skip the
qualification record.

```powershell
if ((Get-Date) -gt (Get-Date).Date.AddHours(3)) { NoGo 'past the 03:00 suite start limit' }
$SuiteLog = Join-Path $R ('bounded-suite-' + (Get-Date -Format yyyyMMdd) + '.log')
$suite = Join-Path $P 'scripts\ops\bounded_worktree_test_suite.ps1'
$SuiteExit = 99
try {
  powershell -NoProfile -ExecutionPolicy Bypass -File $suite -RepoRoot $P -WorktreeRoot $Stage -ExpectedTip $Tip -BranchRef $QBranch `
    -LogPath "$SuiteLog.preflight" -PreflightOnly -InterpreterPath $StagePy -ExpectedInterpreterVersion '3.11.9'
  if ($LASTEXITCODE -eq 0) {
    powershell -NoProfile -ExecutionPolicy Bypass -File $suite -RepoRoot $P -WorktreeRoot $Stage -ExpectedTip $Tip -BranchRef $QBranch `
      -LogPath $SuiteLog -InterpreterPath $StagePy -ExpectedInterpreterVersion '3.11.9'
  }
  $SuiteExit = $LASTEXITCODE
} finally {
  Log "bounded suite exit $SuiteExit"
  @{ result = if ($SuiteExit -eq 0) {'PENDING_B3'} else {'FAIL'}; tip=$Tip; branch=$QBranch; stage=$Stage; suite_log=$SuiteLog; suite_exit=$SuiteExit; at=(Get-Date).ToString('o') } |
    ConvertTo-Json | Set-Content "$R\qualification.json" -Encoding utf8
}
```

**Go/no-go B2:**
- the suite exits 0;
- its interpreter-override line names `$StagePy` and 3.11.9;
- the stage worktree is clean;
- the #259 `constructor` / `pre_3_11_2` tests pass.

**B3. Release case and qualification record** (read-only, §8):

```powershell
$ra = Get-ReleaseActive $Py "$R\release-active-3110"; Assert-CaseA $ra 'B3'
$q = Get-Content "$R\qualification.json" -Raw | ConvertFrom-Json
if ($q.suite_exit -eq 0) { $q.result = 'PASS' }
$q | Add-Member -NotePropertyName release_case -NotePropertyValue 'A' -Force
$q | Add-Member -NotePropertyName wheelhouse_manifest -NotePropertyValue "$R\wheelhouse-sha256.txt" -Force
$q | ConvertTo-Json | Set-Content "$R\qualification.json" -Encoding utf8
```

Keep `$Stage` until §D.

### Phase C. Cutover night

| Clock (local) | Step | Hard stop |
| --- | --- | --- |
| 00:30-00:55 | C0 GO checks | Any fail = NO-GO, nothing touched |
| 01:00, latest 01:30 | C1 lease and receipts | No lease by 01:30 = NO-GO |
| +5 min | C2 quiesce the auxiliary tasks and long-running holders | Any throw = `Undo-Aux`, NO-GO |
| +5-10 min | C3 stop the capture workers | Still active after 600 s = undo, restore, NO-GO |
| by 01:45 | C4 rename `venv` to `venv-cp3110` | Rename fails 3 times or it is past 01:45 = undo, restore, NO-GO |
| +3 min | C5 build the new `venv` offline | Fail = §R |
| +2 min | C6 quick verify | Fail = §R |
| +5-32 min | C7 S4U restore of the three capture workers only | Not 3/3 after one rerun = §R |
| +5 min | C8 core verify | Fail = §R |
| by 02:30 | C9 core PASS decision; C9b restore the aux tasks; C9c aux verify | Core not passed = §R; aux failure per C9c |
| start by 03:15, done by 03:45 | §R rollback | Escalate to the owner if not 3/3 by 03:45 |

This sits inside the 01:00-04:00 quiet window and ends before the 04:15 `WeatherTrainingWindowRestore`
trigger, which stays armed as the final safety net. The expected capture gap (C3 to C7) is about
20-35 minutes. The auxiliary tasks (tape, shadow, 88a and the rest) stay quiesced until C9b, so
§R never has to stop processes running on the new venv except the three capture workers. §R still
re-runs the quiesce to be safe.

A failure before the C4 rename means **undo with no swap**: re-enable what C2 and C3 disabled, then
start the S4U restore. A failure after the rename means §R.

**C0. GO checks.**

```powershell
$q = Get-Content "$R\qualification.json" -Raw | ConvertFrom-Json; if ($q.result -ne 'PASS' -or $q.release_case -ne 'A') { NoGo 'not qualified for case A' }
if (((Get-Content -LiteralPath "$R\q12.txt" -TotalCount 1) -split '\s+')[0] -ne 'STOP_AUTHORIZED') { NoGo 'Q12 not recorded as STOP_AUTHORIZED (G8)' }
$Head = (git -C $P rev-parse HEAD).Trim()
if ($Head -ne $q.tip) { Log "HEAD moved from the qualified tip; master must attach roll_verdict.ps1 output showing roll-free before GO" }
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'prod tree dirty' }
if (Test-Path -LiteralPath $Old) { NoGo "$Old exists" }
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 10GB) { NoGo 'disk' }
foreach ($t in 'WeatherTrainingWindow','WeatherEveningEvidenceRefresh') { $x = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  if ($x -and [string]$x.State -ne 'Disabled') { NoGo "$t is enabled (G5)" } }
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
Log "lease state $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P) | ConvertTo-Json -Compress)"
$st0 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$R\c0-status"
$ra0 = Get-ReleaseActive $Py "$R\c0-release-active"; Assert-CaseA $ra0 'C0'
$Exempt = @('WeatherMemoryCommitGuard','WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor','WeatherTrainingWindowRestore') +
          @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })
Get-ScheduledTask | Where-Object { [string]$_.State -ne 'Disabled' -and $Exempt -notcontains $_.TaskName } | ForEach-Object { $i = Get-ScheduledTaskInfo $_
  if ($i.NextRunTime -and $i.NextRunTime -lt (Get-Date).Date.AddHours(4)) { "$($_.TaskName) next=$($i.NextRunTime)" } } | Tee-Object -FilePath "$R\c0-next-runs.txt"
Log "C0 complete (status.ps1 exit $st0) - awaiting owner GO"
```

**Go/no-go C0:**
- `c0-status.out.txt` shows capture healthy (3/3), with no FLAG the owner has not accepted;
- the release is case A (already asserted);
- `c0-next-runs.txt` is empty. The exempt tasks are the memory guard, the three supervisors, the 04:15 restore, and the aux tasks that C2 disables. Any other task due before 04:00 goes to the owner;
- G3, G5, G7, G8 and G11 hold;
- the owner types GO.

**C1. Lease and fresh receipts.**

```powershell
$Lease = $null; $deadline = (Get-Date).Date.AddHours(1).AddMinutes(30)
while (-not $Lease) { $Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_cutover'
  if (-not $Lease) { if ((Get-Date) -gt $deadline) { NoGo 'no lease by 01:30' }; Start-Sleep -Seconds 30 } }
$global:ReleaseOnNoGo = $true     # until the C4 rename, any NoGo releases the lease; after it, §R needs the lease
$N = Join-Path $R ('night-' + (Get-Date -Format yyyyMMdd)); New-Item -ItemType Directory -Force $N | Out-Null
& $Py -m pip freeze --all | Set-Content "$N\freeze-3110-tonight.txt"
if (Compare-Object (Get-Content "$A\freeze-3110.txt") (Get-Content "$N\freeze-3110-tonight.txt")) { NoGo 'prod venv changed since Phase B - requalify' }
foreach ($f in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') { Copy-Item -LiteralPath (Join-Path $P "data\snapshots\$f") "$N\pre-$f" }
$shadowTask = Get-ScheduledTask -TaskName WeatherMakerShadowRunner -ErrorAction SilentlyContinue
$ShadowStop = $null
if ($shadowTask) {   # the registrar's -StopFile (register_maker_shadow_runner.ps1:31, :43)
  if ([string]$shadowTask.Actions[0].Arguments -match '--stop-file\s+"([^"]+)"') { $ShadowStop = $Matches[1] } else { NoGo 'shadow task registered but its stop-file argument is unreadable' } }
Log "shadow task registered=$([bool]$shadowTask) stop file: $ShadowStop"
```

If the shadow task is not registered, `aux-tasks.txt` must not list it (A1 review). If it does
list it, `Get-ScheduledTask` throws in C2, before anything has changed.

**C2. Quiesce the auxiliary tasks and long-running holders.** The functions are defined once and
reused by C3, C9b and §R.
- `Quiesce-Aux` is idempotent. It records the pre-state only once, and stopping something already
  stopped succeeds.
- With `-Soft` (§R only), a failed step logs `ESCALATE` and the next step still runs.

```powershell
$Sup = 'WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor'
$Holders = 'WeatherExecutionTapeSupervisor','WeatherMakerShadowRunner','WeatherMakerEvidenceCapture'
function Undo-Aux { foreach ($row in Import-Csv "$N\aux-prestate.csv") { if ($row.State -ne 'Disabled') { Enable-ScheduledTask -TaskName $row.Task | Out-Null } }
  if ($ShadowStop) { Remove-Item -LiteralPath $ShadowStop -ErrorAction SilentlyContinue } }
function Start-AuxHolders {   # restart the long-running holders that C2 stopped, only where their pre-state was enabled
  foreach ($t in $Holders) { $row = Import-Csv "$N\aux-prestate.csv" -ErrorAction SilentlyContinue | Where-Object Task -eq $t
    if ($row -and $row.State -ne 'Disabled') { Start-ScheduledTask -TaskName $t; Log "started $t" } } }
function Stop-Tape([string]$Exe) {
  # 'stop' exits 0 only when it stopped a live worker (execution_tape_supervisor.py:909-912). A worker that is
  # already gone returns authorization.process_gone=true / recorded_process_not_found (supervisor.py:1353-1361),
  # which supervisor.managed_stop_allows_start (supervisor.py:796-804) also treats as stopped.
  $base = "$N\tape-stop-$(Get-Date -Format HHmmss)"
  $tc = Invoke-Native $Exe @('-m','weather.operations.execution_tape_supervisor','stop') $base
  if ($tc -eq 0) { Log 'tape stopped'; return }
  try { $j = Get-Content -LiteralPath "$base.out.txt" -Raw | ConvertFrom-Json } catch { NoGo "tape stop exit $tc with unreadable output" }
  if ($j.authorization.process_gone -eq $true) { Log "tape already stopped ($($j.reason))"; return }
  if ($j.reason -eq 'status_pid_unknown') {
    $sc = Invoke-Native $Exe @('-m','weather.operations.execution_tape_supervisor','status','--stale-after-seconds','180') "$base-status"
    if ($sc -ne 0) { Log 'tape has no recorded PID and is not healthy: treated as stopped (the C4/§R holder sweep is the backstop)'; return } }
  NoGo "execution tape stop exit $tc reason $($j.reason)" }
function Invoke-QStep([string]$Name, [scriptblock]$Body, [bool]$Soft) {
  try { & $Body } catch { if ($Soft) { Log "ESCALATE: quiesce step '$Name' failed: $($_.Exception.Message); continuing" } else { throw } } }
function Quiesce-Aux([string]$Exe, [switch]$Soft) {
  $Aux = @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })
  Invoke-QStep 'prestate' {
    if (-not (Test-Path -LiteralPath "$N\aux-prestate.csv")) {
      $Aux | ForEach-Object { $x = Get-ScheduledTask -TaskName $_; [pscustomobject]@{ Task=$_; State=[string]$x.State } } |   # throws on a wrong name
        Export-Csv -LiteralPath "$N\aux-prestate.csv" -NoTypeInformation } } $Soft.IsPresent
  Invoke-QStep 'shadow' {   # STOP file only, never a kill
    if ($Aux -contains 'WeatherMakerShadowRunner') {
      if (-not $ShadowStop) { NoGo 'shadow stop-file path unknown' }
      New-Item -ItemType File -Force $ShadowStop | Out-Null
      $t0 = Get-Date; while ([string](Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running' -and ((Get-Date)-$t0).TotalSeconds -lt 180) { Start-Sleep 10 }
      if ([string](Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running') { NoGo 'shadow did not seal in 3 min' } } } $Soft.IsPresent
  foreach ($t in $Aux) { Invoke-QStep "disable $t" { Disable-ScheduledTask -TaskName $t | Out-Null
    if ([string](Get-ScheduledTask -TaskName $t).State -ne 'Disabled') { NoGo "disable $t" } } $Soft.IsPresent }
  Invoke-QStep 'tape' { Stop-Tape $Exe } $Soft.IsPresent
  Invoke-QStep '88a' {   # only with the recorded owner choice (G8, Q12)
    if (((Get-Content -LiteralPath "$R\q12.txt" -TotalCount 1) -split '\s+')[0] -ne 'STOP_AUTHORIZED') { NoGo 'Q12 not STOP_AUTHORIZED' }
    if ([string](Get-ScheduledTask -TaskName WeatherMakerEvidenceCapture).State -eq 'Running') { Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture; Log '88a worker stopped (Q12)' } } $Soft.IsPresent
}
try { Quiesce-Aux $Py; Log 'C2 quiesced' }
catch { $msg = $_.Exception.Message; Log "C2 failed: $msg - undoing"
  if (Test-Path -LiteralPath "$N\aux-prestate.csv") { Undo-Aux; Start-AuxHolders }
  $global:ReleaseOnNoGo = $false; Release-Lease; throw }
```

A tape that is not running at C2 (crashed, or disabled in its pre-state) is not a NO-GO. Its stop
returns `process_gone` and C2 carries on.

**C3. Stop the capture workers.** This is the training-window stop sequence, with the exit codes
checked as `training_window.ps1:404-409` does. The capture stop verbs print JSON and exit 0 even
when the loop was already stopped (`snapshot_tracker.py:2413-2415`, `market_microstructure.py:2276-2278`,
`observation_trigger.py:1955-1957`), so the gate is the stop proof.

```powershell
function Stop-Capture([string]$Exe, [switch]$Soft) {
  foreach ($t in $Sup) { Invoke-QStep "disable $t" { Disable-ScheduledTask -TaskName $t | Out-Null
    if ([string](Get-ScheduledTask -TaskName $t).State -ne 'Disabled') { NoGo "disable $t" } } $Soft.IsPresent }
  $stamp = Get-Date -Format HHmmss
  $c1 = Invoke-Native $Exe @('-m','weather.collection.snapshot_tracker','--stop') "$N\stop-snapshot-$stamp"
  $c2 = Invoke-Native $Exe @('-m','weather.market.market_microstructure','stop') "$N\stop-clob-$stamp"
  $c3 = Invoke-Native $Exe @('-m','weather.operations.observation_trigger','stop') "$N\stop-obs-$stamp"
  if ($c1 -or $c2 -or $c3) { Log "stop verb exits $c1/$c2/$c3"; if (-not $Soft) { return $false } }
  $t0 = Get-Date
  while (((Get-Date)-$t0).TotalSeconds -lt 600) {
    $g = Invoke-Native $Exe @('-m','weather.operations.capture_resource_gate','--workload','py3119_cutover_stop_confirmation','--capture-mode','no_live_capture',
          '--min-free-memory-bytes','0','--min-free-disk-bytes','0','--no-write','--fail-on-block') "$N\gate-$stamp"
    if ($g -eq 0) { return $true }; Start-Sleep 5 }
  return $false }
function Wait-Restore([datetime]$Since) {   # S4U restore; the task limit is 15 min (register_training_window.ps1:153): one run plus one rerun
  Start-ScheduledTask -TaskName WeatherTrainingWindowRestore; $t0 = Get-Date; $rerun = $false
  while (((Get-Date)-$t0).TotalMinutes -lt 32) { Start-Sleep 20
    $st = Get-Content -LiteralPath (Join-Path $P 'data\logs\training_window_status.json') -Raw | ConvertFrom-Json
    $fresh = [datetimeoffset]$st.updated_at -gt [datetimeoffset]$Since
    if ($fresh -and $st.phase -eq 'restore_only' -and $st.outcome -eq 'capture_recovery_pass') { return $true }
    if ([string](Get-ScheduledTask WeatherTrainingWindowRestore).State -ne 'Running' -and ($fresh -or ((Get-Date)-$t0).TotalMinutes -ge 16)) {
      if ($rerun) { return $false }; $rerun = $true; Log 'restore did not pass; one rerun'; $Since = Get-Date; Start-ScheduledTask -TaskName WeatherTrainingWindowRestore } }
  return $false }
function Undo-Stop {   # pre-rename undo: the venv is still the intact 3.11.0
  foreach ($t in $Sup) { Enable-ScheduledTask -TaskName $t | Out-Null }
  $ok = Wait-Restore (Get-Date); Undo-Aux; Start-AuxHolders
  if ($ok) { Log 'undo: capture 3/3, aux tasks restored' } else { Log 'ESCALATE: undo restore did not report capture_recovery_pass' } }
if (-not (Stop-Capture $Py)) { Undo-Stop; NoGo 'C3 stop failed - no swap, restored' }
$GapStart = Get-Date; Log 'C3 capture stopped'
```

In no-live-capture mode, one gate call checks all three loops, as `Wait-CaptureStopped` does
(`training_window.ps1:238-252`). `--workload` is only a label.

**C4. Sweep and rename (deadline 01:45).**

```powershell
$OldHomeNorm = (Get-Content "$R\oldhome.txt").Trim().TrimEnd('\'); $NewHomeNorm = $NewHome.TrimEnd('\')
function Get-VenvHolders([string]$Dir) {
  # Anchored with a trailing backslash, so a sibling worktree such as <checkout>-<name>\venv never matches.
  # The base-interpreter clause catches child processes of either home that name the production checkout.
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
    $_.ExecutablePath -like "$Dir\*" -or $_.CommandLine -like "*$Dir\*" -or
    (($_.ExecutablePath -like "$OldHomeNorm\*" -or $_.ExecutablePath -like "$NewHomeNorm\*") -and $_.CommandLine -like "*$P\*") } |
    Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine }
function Rename-WithSweep([string]$From, [string]$To, [string]$Tag) {
  for ($i = 1; $i -le 3; $i++) {
    $hold = Get-VenvHolders $From; $hold | Format-List | Out-File "$N\holders-$Tag-try$i.txt"
    if ($hold) { Log "$Tag try $i holders $(($hold.ProcessId) -join ',')"; Start-Sleep 20; continue }
    try { Rename-Item -LiteralPath $From -NewName $To -ErrorAction Stop; return $true } catch { Log "$Tag rename try $i failed: $($_.Exception.Message)"; Start-Sleep 20 } }
  return $false }
if ((Get-Date) -gt (Get-Date).Date.AddHours(1).AddMinutes(45)) { Undo-Stop; NoGo 'swap deadline passed - no swap, restored' }
if (-not (Rename-WithSweep (Join-Path $P 'venv') 'venv-cp3110' 'c4')) { Undo-Stop; NoGo 'C4 rename failed - no swap, restored' }
$global:ReleaseOnNoGo = $false    # from here on a failure means §R, which needs the lease
Log 'C4 renamed'
```

C4 never kills a holder. An unknown holder means NO-GO with no swap. The holder file goes to the
owner.

**C5. Build the new venv offline.** From here on, any failure means §R.

```powershell
& $NewPy -I -m venv (Join-Path $P 'venv'); if ($LASTEXITCODE) { NoGo 'venv create -> ROLLBACK' }
Build-Venv $Py $P
```

**C6. Quick verify.**

```powershell
Test-Venv $Py $P 'prod'      # includes the import-location check: weather and maker_core must import from $P\src
foreach ($k in 'python.exe','pythonw.exe') { if ((Sha (Join-Path $P "venv\Scripts\$k")) -ne $K.binaries."Lib\venv\scripts\nt\$k") { NoGo "launcher $k -> ROLLBACK" } }
Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" } |
  Set-Content "$N\pth-3119.txt" -Encoding utf8     # receipt only; the import-location check is the pass rule
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'tree dirty -> ROLLBACK' }
```

**C7. Restore the capture workers through the S4U path.** `Wait-Restore` (defined in C3) allows
one full 15-minute run plus one rerun.

```powershell
foreach ($t in $Sup) { Enable-ScheduledTask -TaskName $t | Out-Null }
if (-not (Wait-Restore $GapStart)) { NoGo 'C7 not recovered -> ROLLBACK' }
$GapEnd = Get-Date; Log ("C7 3/3; gap {0:n1} min" -f ($GapEnd-$GapStart).TotalMinutes)
```

The restore task enables the supervisors itself (`training_window.ps1:159` onward), so enabling
them first is harmless. The auxiliary tasks stay disabled until C9b.

**C8. Core verify.**

```powershell
# a) the workers run 3.11.9
foreach ($f in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') {
  $v = (Get-Content -LiteralPath (Join-Path $P "data\snapshots\$f") -Raw | ConvertFrom-Json).runtime_identity.python_version
  Log "$f python_version=$v"; if ($v -ne '3.11.9') { NoGo "$f $v -> ROLLBACK" } }
# c) release readiness: still case A
$ra1 = Get-ReleaseActive $Py "$N\release-active-3119"; Assert-CaseA $ra1 'C8'
if ($ra1.status -ne $ra0.status -or $ra1.error -ne $ra0.error) { NoGo 'release active fields changed across the swap -> ROLLBACK' }
# d) host status
$st1 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$N\status-core"
# e) native-library receipt, old and new
$null = Invoke-Native $Py @('-I','-c','import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version); print(zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)') "$N\native-3119"
```

**Go/no-go C8:**
- (a) all three status files report 3.11.9;
- (c) `status` and `error` are identical to C0, a missing-pointer BLOCK;
- (d) capture shows no new FLAG (aux-task flags are expected until C9b);
- (e) is a receipt only.

**C9. Core decision (by 02:30).** PASS needs C6, C7 and C8 all green, and a gap of 35 minutes or
less (or an overrun the owner accepts). Otherwise run §R.

**C9b. Restore the auxiliary tasks.**

```powershell
Undo-Aux; Start-AuxHolders
$AuxRestart = Get-Date
```

**C9c. Aux verify (within 10 minutes).**

```powershell
$tapeOk = $false; $tapeWanted = (Import-Csv "$N\aux-prestate.csv" | Where-Object Task -eq 'WeatherExecutionTapeSupervisor' | Where-Object State -ne 'Disabled')
if ($tapeWanted) { $t0 = Get-Date
  while (-not $tapeOk -and ((Get-Date)-$t0).TotalMinutes -lt 5) {   # status exits 0 only for RUNNING/DEGRADED (execution_tape_supervisor.py:936)
    $tsc = Invoke-Native $Py @('-m','weather.operations.execution_tape_supervisor','status','--stale-after-seconds','180') "$N\tape-status-$(Get-Date -Format HHmmss)"
    if ($tsc -eq 0) { $tapeOk = $true } else { Start-Sleep 20 } }
  if (-not $tapeOk) { NoGo 'tape not RUNNING/DEGRADED after 5 min - inspect the tape status files; import or runtime error -> ROLLBACK' } }
$m = Get-Content -LiteralPath (Join-Path $P 'data\maker_evidence\status.json') -Raw | ConvertFrom-Json
Log "88a state=$($m.state) updated=$($m.updated_at_utc) cycles=$($m.cycles) last_error=$($m.last_error)"
$st2 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$N\status-full"
```

**Go/no-go C9c:**
- **Tape:** the status command exited 0 within 5 minutes (health `RUNNING` or `DEGRADED`). In its
  latest `tape-status-*.out.txt`, the identity matches the current runtime, evidence integrity
  passes, and the connection state is `CONNECTED`.
- **Shadow:** running again, with the STOP file gone.
- **88a:** `status.json` has an `updated_at_utc` after `$AuxRestart`, `state` is `CAPTURING` or `NO_ELIGIBLE_BANDS`, and no `last_error` mentions a torn journal.

If the tape or shadow fails with an import or runtime error on the new venv, run §R. It must start
by 03:15.

If 88a fails with a journal or store error (the Q12 risk), do **not** roll back and do not delete or
rewrite any journal. The production agent records the evidence and escalates to the owner, who
decides the remediation under the 88a retention hold.

**C10. Close-out.**

```powershell
@{ result='PASS'; head=$Head; gap_minutes=[math]::Round(($GapEnd-$GapStart).TotalMinutes,1); old_venv=$Old; new_home=$NewHome; release_case='A'; at=(Get-Date).ToString('o') } |
  ConvertTo-Json | Set-Content "$N\cutover-receipt.json" -Encoding utf8
Release-Lease; Log 'CUTOVER PASS'
```

Keep these for at least 14 days:
- `venv-cp3110`;
- the freeze copy of the old home;
- the 3.11.0 installation;
- every 3.11.0 release manifest;
- `$R`.

Uninstalling 3.11.0 is a later, separate owner decision.

### §R. Rollback (start by 03:15, done by 03:45)

§R uses the C2, C3 and C4 functions in the same session. It runs the stop verbs with the **intact
3.11.0 venv** (`$Old`, renamed in C4): a renamed venv still runs `-m`, and its editable install
points at `$P\src`. The new venv may be the thing that is broken. An `import weather` probe picks the
interpreter. Every quiesce and stop step is soft: a failure logs `ESCALATE` and §R carries on to the
swap-back and the restore. Only an interpreter or rename failure stops §R. The aux tasks are
re-enabled only after capture is 3/3.

```powershell
Log 'ROLLBACK start'
$global:ReleaseOnNoGo = $false
function Test-Interp([string]$Exe, [string]$Tag) { if (-not (Test-Path -LiteralPath $Exe)) { return $false }
  (Invoke-Native $Exe @('-c','import weather.operations.execution_tape_supervisor, weather.operations.capture_resource_gate') "$N\probe-$Tag") -eq 0 }
$RbPy = $null
foreach ($c in @(@("$Old\Scripts\python.exe",'old'), @("$P\venv\Scripts\python.exe",'new'))) { if (Test-Interp $c[0] $c[1]) { $RbPy = $c[0]; break } }
if (-not $RbPy) { Log 'ESCALATE: neither venv imports weather; stop verbs skipped, the holder sweep decides' }
else { Log "rollback stop interpreter: $RbPy"
  Quiesce-Aux $RbPy -Soft     # idempotent: shadow STOP file, disable aux tasks, tape stop (already-stopped is fine), 88a stop (Q12)
  if (-not (Stop-Capture $RbPy -Soft)) { Log 'ESCALATE: capture stop not confirmed in 600 s; continuing to the swap-back' } }
if (Test-Path -LiteralPath "$P\venv") { if (-not (Rename-WithSweep "$P\venv" 'venv-cp3119-failed' 'r1')) { NoGo 'ROLLBACK: new venv still held - ESCALATE (holders file in $N)' } }
if (-not (Rename-WithSweep $Old 'venv' 'r2')) { NoGo 'ROLLBACK: venv-cp3110 cannot be renamed back - ESCALATE (holders file in $N)' }
if ((& "$P\venv\Scripts\python.exe" -VV) -notlike 'Python 3.11.0*') { Log 'ESCALATE: venv not 3.11.0' }
if (Compare-Object (Get-Content "$A\freeze-3110.txt") (& "$P\venv\Scripts\python.exe" -m pip freeze --all)) { Log 'ESCALATE: freeze differs' }
foreach ($t in $Sup) { Enable-ScheduledTask -TaskName $t | Out-Null }
$rb = Wait-Restore (Get-Date)
if ($rb) { Undo-Aux; Start-AuxHolders }
else { Log 'ESCALATE: capture not 3/3 - aux tasks (including any U6 export) left DISABLED' }
$rar = Get-ReleaseActive "$P\venv\Scripts\python.exe" "$N\rollback-active"; Assert-CaseA $rar 'rollback'
Release-Lease; Log 'ROLLBACK DONE'
```

**Rollback passes when:**
- the S4U restore reports 3/3;
- the three status files report 3.11.0;
- the aux tasks are back in their pre-state;
- `active` is still the case-A BLOCK.

There is no release pointer to roll back in case A.

Keep `venv-cp3119-failed` and `$R` for diagnosis. If 3/3 is not reached by 03:45, escalate to the
owner. The aux tasks stay disabled, so a 04:10 U6 export cannot start on a half-restored venv. The
04:15 restore trigger stays armed.

### §D. Cleanup after PASS (a later admitted night)

```powershell
git -C $P worktree remove $Stage      # use --force only if git refuses because of the ignored stage venv
git -C $P branch -D $QBranch
```

## 8. Release cases

| `active` on 3.11.0 (H5, B3, C0) | Case | This runbook |
| --- | --- | --- |
| `BLOCK`, active release pointer missing; `artifacts\releases\current_release.json` absent | **A** (expected; the state of play records no release store on the host) | Supported. `active` must give identical `status` and `error` fields before and after the swap. |
| `PASS`, any release | **B or C** | **NO-GO.** A separately reviewed re-bind procedure is required first. |

**What a future re-bind procedure must satisfy.** Promotion and pointer rollback both:
- need a market-day boundary proof taken while every release-writing process is quiesced
  ([Release #1 build runbook](RELEASE_ONE_BUILD_RUNBOOK.md) §4 and §4a);
- return `restart_required` (`release_promotion.py`).

So a re-bind must run between C6 and C7, while capture is still stopped, and a restart must follow.
Its rollback must restore the previous pointer before the §R restore, under the same quiesce. Workers
started on 3.11.9 against a 3.11.0-bound release would fail `check_runtime`
(`release_artifacts.py:219-240`). None of this is drafted here.

## 9. After the cutover (not part of the night)

1. **Moved deployments (Q7, Q14).** Check each one on its first run after the cutover:
   - the watchdog's next 15-minute run reports normally (`status.ps1 -Json` watchdog row, task `LastTaskResult`);
   - `WeatherManualOrderJournal` records normally on its next 5-minute run (its runbook's verify step);
   - the 91a `WeatherColdSnapshotNightly` run at 06:50 completes with its normal receipt;
   - the U6 export, when registered, completes its first run;
   - boot recovery is next exercised at a reboot; its venv is the production venv.
2. **Cold-archive byte check (§5).** In a later admitted window, run a read-only verify of one
   existing cold archive on 3.11.9 ([verified cold archive](verified-cold-archive.md)). This checks
   that the `tarfile` and gzip paths still match bytes written on 3.11.0.
3. **88a follow-up (Q12).** The next day, read the 88a status and its inspector output for the
   cutover hour. Report any torn-journal or seal error to the owner.
4. **Live seals (G10).** Reseal every live seal under its own runbook before any live attempt. This
   needs an SDK audit on 3.11.9, the owner's credential receipt and a fresh seal. Nothing here
   authorizes a live action.
5. **Follow-up changes (separate branches):**
   - repin the Windows qualification lane from `3.11.0` to `3.11.9` (`.github/workflows/windows-qualification.yml:244`);
   - update the `src/` comments that say the host runs 3.11.0 (`wallet_reader_transport.py:73`, `wu_history.py:157`, `wu_redaction.py:255`). They are roll-sensitive, so send them through `roll_verdict.ps1`;
   - update the findings that cite pre-3.11.2 behaviour.
6. **State.** Production rewrites [the state of play](STATE_OF_PLAY.md) (host Python) and records the
   cutover in the owning roadmap item.
7. **Day 14.** The owner decides on deleting `venv-cp3110` and the freeze copy, and on uninstalling
   3.11.0.

## 10. Timings against the host timetable

| Window | Allowed for this runbook |
| --- | --- |
| 00:30-04:45 | §T; Phase B (B0 by 02:00, suite start by 03:00); §D |
| 00:30-09:00 | §4 host reads (serial); Phase A |
| 01:00-04:00 quiet window | Phase C only. Latest lease 01:30, latest rename 01:45, core decision 02:30, rollback start 03:15. |
| 04:45-06:45 tiering reserve, 06:50 jobs | Nothing heavy from this runbook |
| 09:30-11:55 Stage-A | Nothing |
| 12:00-18:00 graded and 18:00-00:30 near-close | Nothing |
| DST night 10-31 to 11-01 | Nothing (G11) |

## 11. Owner sign-off checklist

The owner initials each line in the decision log. Recommendations come first.

- [ ] **Runbook revision** approved as written (G0). The night is named. It must come after LFC
      session 0 (G7) and after the 88a freeze in the state of play (G8), and must not be the night
      before an LFC session or the DST night (G11).
- [ ] **Q12, 88a stop:** record `STOP_AUTHORIZED` in `$R\q12.txt`, authorizing `Stop-ScheduledTask
      -TaskName WeatherMakerEvidenceCapture` at C2 and accepting a short 88a gap and an untested
      abrupt stop (recommended). The alternative is to wait for a reviewed graceful-stop verb; the
      cutover stays NO-GO until then.
- [ ] **Capture gap:** about 20-35 minutes for the capture workers, and somewhat longer for the
      execution tape, the maker shadow and 88a (they restart at C9b). Confirm this is within the
      approved one-gap budget, and that the gap's timing against the desk-study panel window is
      acceptable.
- [ ] **G12, downloads:** approve the PyPI wheel downloads (§T, B1a and B1b; hash-pinned, Windows
      and pure wheels only), in addition to the already-approved installer download.
- [ ] **Q13, tzdata:** run §T on an earlier night (recommended), or exempt tzdata in the comparisons.
- [ ] **Q4, installer scope:** install in the opposite scope to 3.11.0 per H1, and cancel on
      "Upgrade" (recommended). Any NuGet or embeddable fallback is a new approval.
- [ ] **Q9, provenance:** require the python.org size and MD5, the winget SHA-256 and the PSF
      Authenticode signature together (recommended). Sigstore is optional.
- [ ] **Q8, scope:** accept 3.11.9 with the partial audit in §5 (recommended), and track 3.12/3.13
      separately.
- [ ] **Q7, deployments:** accept that the watchdog, 91a, manual order journal, boot recovery and U6
      deployments move to 3.11.9 with the production venv, verified per §9 (recommended).
- [ ] **G5, lease users:** keep `WeatherTrainingWindow` and Stage B disabled on the Phase B and
      Phase C nights.
- [ ] **Release case:** case A, confirmed by H5 and B3. Cases B and C are NO-GO (§8).
- [ ] **Retention:** keep the old venv, the freeze copy, the 3.11.0 install and its manifests for
      14 days.
- [ ] **Live:** no live attempt until the reseal (G10).

## Update this file when

- the capture stop or restore path, the bounded suite's interpreter flags, release runtime binding,
  live interpreter seals or the Scheduler task set changes;
- a reviewed release re-bind procedure exists (replace the §8 NO-GO with it);
- an open question above is answered (move it to RESOLVED with its evidence);
- the target interpreter changes;
- the upgrade has run: mark this file historical, or retarget it, in the same change that updates
  the state of play.

Validate with `.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit`.
