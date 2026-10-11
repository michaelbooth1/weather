# Host Python upgrade runbook (capture host, 3.11.0 to 3.11.9)

> **PROPOSED - not approved; owner sign-off required before any step.**
> Nothing in this file authorizes a download, an install, a capture gap, a task change or a merge.
> [The owner sign-off checklist](#11-owner-sign-off-checklist) lists what the owner must sign first.
> Live orders, cancels and signing are out of scope here; the live launcher is resealed under its
> own runbook.

Status: proposed runbook. It turns the approved intent (DECISION_LOG, 2026-10-09: host Python
upgrade as a quiet-window job with a release re-bind; installer download, UAC and one capture gap)
into gated steps. Today's host version and the planned night live in
[the state of play](STATE_OF_PLAY.md), not here.

**Owns:** the procedure for moving the production checkout's `venv` from CPython 3.11.0 to 3.11.9
on the 16 GB capture host. That covers a side-by-side install, an offline wheelhouse, a stage venv
qualified by the bounded suite, the cutover through the guarded stop/restore path, the release
re-bind, verification, rollback and cleanup.

**Read when:** you prepare, review, sign or execute the host interpreter upgrade, or you change
something it depends on. That includes the capture stop and restore path, release runtime binding,
the bounded suite's interpreter override, the Scheduler task set, and live interpreter seals.

**Not here:**
- the heavy-work timetable and lease: [host load policy](HOST_LOAD_POLICY.md);
- merges and roll verdicts: [capture-day grading and guarded merges](../ops/streak-soak.md);
- release construction: [Release #1 build runbook](RELEASE_ONE_BUILD_RUNBOOK.md);
- live seals: [portable live execution host](PORTABLE_LIVE_EXECUTION_HOST.md) and
  [International MM live pilot](INTERNATIONAL_MM_LIVE_PILOT.md);
- the workstation interpreter: [development](../development.md).

## 1. Why the upgrade is a planned job, not a silent swap

Four repository facts set the shape of every phase below.

| Fact | Evidence | Consequence |
| --- | --- | --- |
| A release binds the exact interpreter version | `src/weather/release_artifacts.py`: `capture_runtime_versions` (from line 139) records `python`, `implementation`, `platform` and the direct dependency versions. `_verify_runtime_versions` (from line 219) raises `runtime version mismatch` on `python`, `implementation` or any dependency. `platform` is recorded but not compared. | Every release bound on 3.11.0 fails `check_runtime` on 3.11.9, and serving fails closed, until a new release is created and promoted on 3.11.9 (§8). |
| The capture restart identity ignores the interpreter | `src/weather/runtime_identity.py:222` records `python_version`, but the identity key is built from the source fingerprint over repository files. | The swap does not trigger `STALE_CODE` by itself. The workers move to 3.11.9 only because the cutover stops and restarts them (§7 C3/C7). `python_version` in each status file then proves which interpreter is running. |
| Every capture task resolves the interpreter by path | The registrars under `scripts/ops/` build `Join-Path $RepoRoot 'venv\Scripts\python(w).exe'` (for example `scripts/ops/training_window.ps1:99`). The pinned deployments resolve the production venv too: `scripts/ops/cold_snapshot_compression_run.ps1:114`, the watchdog's pinned `status.ps1` through `-RepoRoot` ([operations design](OPERATIONS_DESIGN.md)), and the U6 exam step and export on the build line. | Rebuilding `venv` in place (rename the old one, create a new one at the same path) needs no task re-registration. It also moves **every** production-venv user to 3.11.9 at once, including the pinned deployments (Q7). |
| Live seals bind interpreter bytes | `src/weather/operations/international_live_wrapper_sealer.py` (`INTERPRETER_BINDING_KEYS`, from line 415): redirector, `pyvenv.cfg` and runtime process image hashes. `international_live_session_launcher_sealer.py:387-395` and `:1330-1336`: "reviewed production interpreter hash changed". | Any seal that binds this venv fails closed after the cutover. The state of play already requires every live seal to be resealed before any live attempt (#229). The reseal must come **after** the cutover. |

The live SDK portability check accepts any 3.11 patch release
(`src/weather/market/live_sdk_portability.py:367` checks `sys.version_info[:2] == (3, 11)`).

## 2. Gates (any one fails = NO-GO, nothing touched)

| Gate | Condition | Checked at |
| --- | --- | --- |
| G0 | The owner has signed §11 for this runbook revision and has named the night. | Before Phase A |
| G1 | The bounded suite supports `-InterpreterPath` and `-ExpectedInterpreterVersion` (`scripts/ops/bounded_worktree_test_suite.ps1:44-52`). | Met on master; re-read `param(` if the script changed |
| G2 | Phase A and Phase B passed on earlier nights, and `$R\qualification.json` has `"result":"PASS"`. | C0 |
| G3 | The production HEAD equals the qualified tip, or `roll_verdict.ps1 -Branch` on the difference is roll-free. | C0 |
| G4 | The owner is reachable from 00:30 to 02:30 to give GO. Phase A also needs the owner at the machine for UAC. | C0, A4 |
| G5 | Nothing else is scheduled that night: no integration attempt, quiet-window merge, storage one-shot or held-head work. | C0 |
| G6 | The release case is decided (§8). Case B or C needs the owner-approved spec, decision and boundary drafts in `$R\release\` before 00:30. | C0 |
| G7 (LFC) | The cutover night is **after** LFC session 0 has ended and its handback is recorded. It is never the night before a scheduled LFC session. | C0 |
| G8 (88a) | The night is after the 88a merge freeze ends, and the owner has chosen how the 88a worker is stopped (Q12). | Sign-off |
| G9 (tzdata) | The tzdata sequencing is decided (Q13), so the freeze comparison in `Test-Venv` cannot false-fail. | Before Phase B |
| G10 (seals) | No live attempt is planned between the cutover and the reseal. | Sign-off |

## 3. Question register

Status key:
- **RESOLVED**: settled from repository evidence;
- **NEEDS-HOST-READ**: the read-only command is in §4;
- **OWNER-DECISION**: options are given with the recommendation first, and are collected in §11.

| # | Question | Status | Answer or next step |
| --- | --- | --- | --- |
| Q1 | Can an interactive session stop, see and verify the S4U capture workers? | **RESOLVED** (H6 optional corroboration) | Run Phase C and §R in an **elevated** window. The stop confirmation is PID-based: `capture_resource_gate.py:154-158` marks a loop active when the status PID or the writer-lock PID is alive (or the heartbeat, lock and PID evidence agree). It uses the gate the training window uses (`scripts/ops/training_window.ps1:238-252`), so it works from an interactive shell. The binding recovery proof is the S4U `WeatherTrainingWindowRestore` task (`register_training_window.ps1:117`, `-RestoreOnly` at :140). It writes `restore_only` / `capture_recovery_pass` (`training_window.ps1:277-290`) and takes no lease (the lease is at :352, after the restore-only exit). `capture_recovery_check` is documented to run in the S4U context (`capture_recovery_check.py:1-6`), and a non-elevated session cannot read S4U command lines (HOST_LOAD_POLICY, "residual scan" paragraph), so the interactive check is corroboration only. The rename failing on a locked file is the final backstop. |
| Q2 | Exact interpreter flag on the bounded suite | **RESOLVED** (closed earlier) | `-ExpectedInterpreterVersion` takes an exact `X.Y.Z` and requires `-InterpreterPath` (`bounded_worktree_test_suite.ps1:44-52`). |
| Q3 | Does the U6 export slot collide with the cutover lease? | **RESOLVED, conditional** (H8 confirms) | `WeatherReplayBundleExportNightly` stays unregistered until an owner yes, not before 10-16 (state of play). The build-line registrar allows only `00:35` with a 50-minute limit, so even if registered it releases by 01:25, inside the 01:30 latest lease start (C1). The `04:10` slot exists only on an unlanded branch. If it is registered by then, the owner may skip one export (§11). |
| Q4 | Will the installer offer "Upgrade" over the existing 3.11.0? | **NEEDS-HOST-READ** (H1), then **OWNER-DECISION** | PEP 514 allows one `PythonCore\3.11` registration per hive (HKCU, HKLM). Inference, not tested: install 3.11.9 in the **opposite** scope from the existing 3.11.0 (all users if 3.11.0 is per-user, and the reverse). The owner cancels if the first page says *Upgrade* or *Modify*. A NuGet or embeddable-zip fallback is a new download and needs its own approval. |
| Q5 | Release case A, B or C? | **RESOLVED: case A expected** (H5 re-checks) | The state of play says there is no release store on the host. Re-check at B3 and C0. If Release #1 is bootstrapped first, the case changes and §8 C8b applies. |
| Q6 | Wheel-RECORD test ids for #259 | **RESOLVED** (closed earlier) | #259 is on master, so the `[pre_3_11_2]` / `[constructor]` ids exist and must pass in B2. |
| Q7 | Which venvs and deployments move with the cutover? | **RESOLVED for the pinned deployments; contradicts the original plan.** Other venvs: H3/H4 | The pinned watchdog, the 91a cold snapshot and the U6 exam deployment all run the **production** venv (evidence in §1), so they move to 3.11.9 at the cutover. They are not left on 3.11.0. They are quiesced in C2 and verified in §9. Other worktree venvs keep `home = <3.11.0>` and keep working, because 3.11.0 stays installed. |
| Q8 | Are 3.11.10 and later fixes needed? | **OWNER-DECISION** | 3.11.9 is the last 3.11 release with a Windows installer. §5 gives the audited and not-audited items. Recommendation: take 3.11.9 now and track a 3.12/3.13 move separately. |
| Q9 | Where does the installer SHA-256 come from? | **OWNER-DECISION** | python.org publishes the size and MD5 for 3.11.9, but no SHA-256. Recommendation: require all four of the python.org size, the python.org MD5, the third-party winget manifest SHA-256 and a valid PSF Authenticode signature. Sigstore verification is optional and needs its own download decision. |
| Q10 | Build backend for the editable install | **RESOLVED** (H2 records versions) | `pyproject.toml` requires `setuptools>=69`, but a fresh 3.11.9 venv bundles setuptools 65.5.0. The editable install must therefore use build isolation fed from the wheelhouse: pip passes `--no-index --find-links` to the isolated build. Pin a setuptools release of 70.1 or later in `lock-build`. From 70.1 setuptools ships `bdist_wheel` itself, so the build does not also need the `wheel` package. If you pin an older release, add `wheel` to `lock-build`. The hash script fails closed if the wheel is missing. |
| Q11 | Names on master (memory guard reader, tape stop verb, status key, gate labels) | **RESOLVED** (closed earlier) | `Read-WeatherMemoryGuardStatus -Path` (`memory_guard_status_reader.ps1:13-17`); `execution_tape_supervisor stop` has no arguments (`execution_tape_supervisor.py:880`); `updated_at` (`training_window.ps1:144`). |
| Q12 (new) | How does the 88a worker release the venv? | **OWNER-DECISION** | `WeatherMakerEvidenceCapture` runs one long-lived worker that holds the lock ([passive maker evidence capture](passive-maker-evidence-capture.md), "Commands and registration"). Its CLI has no stop verb and no stop file (`maker_evidence_capture.py:367-372`). Disabling the task does not end the worker, so the C4 rename would fail on its locked files. **Recommendation:** after the 88a freeze, the owner authorizes `Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture` at C2, and its restart is verified in C8. Risk: the store rejects a torn journal (`maker_evidence_store.py:143`), and the effect of an abrupt stop on the open journal has not been tested. Alternative: land a reviewed graceful-stop verb first. That is 88a capture behaviour, so it waits for the freeze to end. |
| Q13 (new) | When should tzdata 2026.3 be installed? | **OWNER-DECISION** | `tzdata` is not pinned in `requirements.txt`. If the lock forces `tzdata==2026.3` while the 3.11.0 freeze has another version, `Test-Venv` and C1 compare the freeze and false-fail. **Recommendation:** run §T on an earlier admitted night, then take the A1 receipts so the freeze already contains 2026.3. Alternative: exempt the `tzdata` line in both comparisons and record that exemption. |
| Q14 (new) | Do the pinned deployments behave the same on 3.11.9? | **RESOLVED to a verification step** | They run the same code and the same pinned dependencies on the new interpreter. The first post-cutover run of each is checked in §9; 91a fires at 06:50 the same morning. |

## 4. Host reads (read-only; master-agent runs them before sign-off)

Run these in Windows PowerShell 5.1 on the capture host, outside 12:00-00:30, using the session
variables from §6. None of them changes state. Save the output under `$R\host-reads\`.

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
# H2 (Q10): production venv identity and packaging tools
& $Py -VV | Out-File "$HR\h2-vv.txt" -Encoding utf8
Get-Content -LiteralPath (Join-Path $P 'venv\pyvenv.cfg') | Out-File "$HR\h2-pyvenv.txt" -Encoding utf8
& $Py -m pip freeze --all | Select-String -Pattern '^(pip|setuptools|wheel|tzdata)==' | Out-File "$HR\h2-tools.txt" -Encoding utf8
# H3 (Q7, C2): every task whose action names a venv, python or a .ps1 wrapper, with state and principal
Get-ScheduledTask | ForEach-Object { $t = $_; foreach ($a in $t.Actions) { [pscustomobject]@{
  Task=$t.TaskPath+$t.TaskName; State=[string]$t.State; Logon=[string]$t.Principal.LogonType; Execute=$a.Execute; Arguments=$a.Arguments } } } |
  Where-Object { ($_.Execute + ' ' + $_.Arguments) -match 'venv|python|\.ps1' } |
  Export-Csv -LiteralPath "$HR\h3-tasks.csv" -NoTypeInformation -Encoding utf8
# H4 (Q7): other venvs and their home
Get-ChildItem -LiteralPath (Split-Path $P) -Directory | ForEach-Object { $c = Join-Path $_.FullName 'venv\pyvenv.cfg'
  if (Test-Path -LiteralPath $c) { "$($_.FullName): " + ((Get-Content -LiteralPath $c) -join ' | ') } } | Out-File "$HR\h4-venvs.txt" -Encoding utf8
# H5 (Q5): release store presence
'releases={0} pointer={1}' -f (Test-Path -LiteralPath (Join-Path $P 'artifacts\releases')), (Test-Path -LiteralPath (Join-Path $P 'artifacts\current_release.json')) |
  Out-File "$HR\h5-release.txt" -Encoding utf8
# H6 (Q1, optional): run once elevated and once non-elevated; compare the two files
$tag = if (([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { 'elevated' } else { 'plain' }
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Select-Object ProcessId, ParentProcessId, ExecutablePath, @{n='CmdVisible';e={[bool]$_.CommandLine}}, CommandLine |
  Format-List | Out-File "$HR\h6-procs-$tag.txt" -Encoding utf8
& $Py -m weather.operations.capture_recovery_check --repo-root $P --json 2>&1 | Out-File "$HR\h6-crc-$tag.txt" -Encoding utf8
# H7 (Q12): which long-running processes hold the production venv (read from H6 output): expect the three
#   capture workers, the execution tape, the maker shadow runner and the 88a worker; list any other holder.
# H8 (Q3): U6 export registration
Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue |
  ForEach-Object { "$($_.State) next=$((Get-ScheduledTaskInfo $_).NextRunTime) limit=$($_.Settings.ExecutionTimeLimit)" } |
  Out-File "$HR\h8-u6.txt" -Encoding utf8
# H9 (receipt baseline): bundled native library versions of the running interpreter
& $Py -I -c "import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print('sqlite', sqlite3.sqlite_version); print('zlib', zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)" |
  Out-File "$HR\h9-native-3110.txt" -Encoding utf8
```

H6 runs `capture_recovery_check` interactively. It only reads, but it is a Python process: run it
outside the protected windows and never in parallel with other work.

## 5. Changelog audit (3.11.1 to 3.11.9) and wheel compatibility

The audit is scoped to fixes that touch the stdlib surfaces this repository uses. It lists only
items that can be cited with confidence. Everything else is **not audited**, and the receipts
(§7 C8e) plus the bounded suite on the stage interpreter (B2) are the safety net.

| Release | Item | Relevance here | Confidence |
| --- | --- | --- | --- |
| 3.11.1 | gh-98433 (CVE-2022-45061), quadratic IDNA decoding | `urllib.request` / `requests` hostname handling | High |
| 3.11.1 | gh-98517 (CVE-2022-37454), `_sha3` buffer overflow | `hashlib` sha3 is not a binding hash here (SHA-256 is) | High |
| 3.11.1 | gh-98744 (traceback unicode crash); gh-97825 | gh-97825: no matching call in `src/` | High (repo-verified in the #259 report) |
| 3.11.1-3.11.2 | Windows build zlib 1.2.13 and OpenSSL 1.1.1 updates (gh-98689, gh-100180) | `gzip` (widely used), all HTTPS | High |
| 3.11.2 | gh-98778 `HTTPError` construction | Already guarded by #259 | High (verified at the tags) |
| 3.11.2 | gh-95882 wrong tracebacks through `@contextmanager` | Several `src/` modules use `contextmanager` | High |
| 3.11.2 | gh-101283 safer `cmd.exe` lookup for `shell=True` | No `shell=True` in `src/` or `app/` | Medium |
| 3.11.4 | PEP 706 tarfile extraction filters (gh-102950) | Archives are written and read through `extractfile` only (`verified_cold_archive.py:1249`, `:1432`); no `extractall` | Medium |
| 3.11.4 | gh-102153 (CVE-2023-24329) `urlsplit` strips leading C0 control and space characters | `urllib.parse` is widely used; inputs are configured URLs | Medium |
| 3.11.5 | gh-108310 (CVE-2023-40217) `ssl` pre-close data bypass | All HTTPS (no direct `import ssl` in `src/`) | Medium |
| 3.11.8 | `traceback` `__notes__` guard | Repo-verified at the tags (#259 report) | High |
| 3.11.9 | Bundled OpenSSL 3.0.x (the night-block record says 3.0.13) | All HTTPS. The OpenSSL 1.1.1-to-3.0 move in the 3.11.x Windows builds tightens TLS defaults. It is proven only by capture recovering in C7/C8. | Medium |
| any | `zipfile`, `email`, `http.server`, `xml.etree`, `sqlite3`, `ctypes`, `subprocess` changes | Used here (`wu_token_scan.py`, `io.py`, `wallet_reader_server.py`, and others) | **Not audited** |
| any | `tarfile` header (`tobuf`) and gzip compressed-output **byte reproducibility** | `bulk_cold_archive_crypt.py:224-228` compares `tobuf` header bytes | **Not audited.** §9 runs a read-only verify of an existing cold archive on 3.11.9. |

**Wheel compatibility:**
- Every direct pin in `requirements.txt` / `pyproject.toml` installs as a `cp311-win_amd64`, abi3 or pure wheel.
- The CPython ABI is stable across 3.11 patch releases, so no dependency version changes.
- The workstation venv already runs 3.11.9 with identical pins.
- B1a's hash script exits non-zero if any pinned distribution lacks a Windows or pure wheel. B1b proves the wheel bytes equal the files installed in the 3.11.0 venv.

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
$K       = Get-Content -LiteralPath (Join-Path $R 'constants.json') -Raw | ConvertFrom-Json   # §6a
New-Item -ItemType Directory -Force $R, $Tools, $A | Out-Null
function Log($m){ $l = "{0:o} {1}" -f (Get-Date), $m; Add-Content -LiteralPath $Log -Value $l -Encoding utf8; Write-Host $l }
function NoGo($m){ Log "NO-GO: $m"; throw "NO-GO: $m" }
function Sha($f){ (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToUpper() }
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

`Enter-WeatherHeavyWorkloadLease` returns `$null` when the lease is busy and throws outside
00:30-09:00. Keep the whole phase in one PowerShell process, and call
`Exit-WeatherHeavyWorkloadLease` on every exit path.

### 6a. Constants file (prepared before Phase A, reviewed in the handoff)

`$R\constants.json` holds the published installer facts. It keeps them in one reviewed place,
not in prose. Source each value as stated:

| Key | Source |
| --- | --- |
| `installer_url` | python.org 3.11.9 release page (`python-3.11.9-amd64.exe`) |
| `installer_size`, `installer_md5` | python.org release page / release API |
| `installer_sha256` | `microsoft/winget-pkgs`, manifest for `Python.Python.3.11` version 3.11.9 (third-party, Q9) |
| `signer_subject_prefix`, `signer_thumbprint` | Authenticode of the same installer, observed on the workstation |
| `vv_prefix` | `python -VV` of the workstation's 3.11.9 install |
| `binaries` | SHA-256 of `python.exe`, `pythonw.exe`, `python311.dll`, `python3.dll`, `vcruntime140*.dll`, `Lib\venv\scripts\nt\python(w).exe`, `DLLs\_ssl.pyd`, `DLLs\libssl-3.dll`, `DLLs\libcrypto-3.dll` from the workstation's 3.11.9 home |

Workstation command for `binaries` and `vv_prefix` (read-only; on the workstation, never the host):

```powershell
$WsHome = (& .\venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)").Trim()
$rel = 'python.exe','pythonw.exe','python311.dll','python3.dll','vcruntime140.dll','vcruntime140_1.dll',
       'Lib\venv\scripts\nt\python.exe','Lib\venv\scripts\nt\pythonw.exe','DLLs\_ssl.pyd','DLLs\libssl-3.dll','DLLs\libcrypto-3.dll'
$b = [ordered]@{}; foreach ($r in $rel) { $b[$r] = (Get-FileHash -LiteralPath (Join-Path $WsHome $r) -Algorithm SHA256).Hash.ToUpper() }
[ordered]@{ vv_prefix = ((& (Join-Path $WsHome 'python.exe') -VV) -replace ',.*$',''); binaries = $b } | ConvertTo-Json
```

## 7. Phases

| Phase | Night | Window | Lease | Capture effect |
| --- | --- | --- | --- | --- |
| §4 host reads | before sign-off | outside 12:00-00:30 | no | none |
| §T tzdata (if Q13 = earlier night) | an earlier night | 00:30-09:00 (quiet window recommended) | yes | none expected |
| A install side by side | any night after sign-off | 00:30-09:00, owner at the machine | no | none |
| B wheelhouse, stage venv, bounded suite | a prep night after A | start 00:30-07:00 | yes (released before B2) | none |
| C cutover | the signed night (G7, G8) | 00:30-02:30; rollback starts by 03:15 | yes | about 20-35 min gap |
| §D cleanup | a later night | 00:30-09:00 | no | none |

### §T. tzdata 2026.3 on the current 3.11.0 venv (if Q13 chooses an earlier night)

Light pip work under the lease, inside 00:30-09:00, with the workers left running. Capture does not
import the replay code that needs the pin. Treat it as roll-sensitive until `roll_verdict.ps1` or
the supervisors' fingerprint list shows that tzdata files are not fingerprinted.

```powershell
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py_tzdata_2026_3'; if (-not $Lease) { NoGo 'lease busy' }
try {
  & $Py -m pip freeze --all | Out-File "$R\freeze-before-tzdata.txt" -Encoding utf8
  & $Py -m pip download --isolated --no-cache-dir --only-binary=:all: --no-deps tzdata==2026.3 -d "$R\tzdata"
  # verify the wheel SHA-256 against PyPI with the B1a hash script on a one-line lock before installing
  & $Py -m pip install --isolated --no-index --no-deps --find-links "$R\tzdata" tzdata==2026.3
  & $Py -m pip freeze --all | Out-File "$R\freeze-after-tzdata.txt" -Encoding utf8
  Compare-Object (Get-Content "$R\freeze-before-tzdata.txt") (Get-Content "$R\freeze-after-tzdata.txt")   # only the tzdata line may differ
} finally { Exit-WeatherHeavyWorkloadLease -Lease $Lease }
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

**A1 review (master-agent, at prep):** build `$R\aux-tasks.txt`, one task name per line, from
`tasks-venv.csv`. It lists every task that starts the production venv, **except**:
- the three capture supervisors (C3 handles them);
- `WeatherTrainingWindowRestore` (the restore path);
- `WeatherMemoryCommitGuard` (no Python; it must keep guarding);
- `WeatherBootRecovery` (startup trigger only).

**Disabled-at-C2 list.** It must also include any of these that exist:

| Task | Note |
| --- | --- |
| `WeatherExecutionTapeSupervisor` | |
| `WeatherMakerEvidenceCapture` | |
| `WeatherMakerShadowRunner` | |
| `WeatherManualOrderJournal` | |
| `WeatherHostHealthWatchdog` | |
| `WeatherModelMarketDisagreementAnalysis` | |
| `WeatherClobEnrichmentLoop` | |
| `WeatherNightlyRetrainValidatePromote` | |
| `WeatherDailySettlementPromotionRefresh` | |
| `WeatherEveningEvidenceRefresh` | |
| `WeatherLocationConfigRefresh` | |
| `WeatherClobTiering` | |
| `WeatherClobRawTapeTiering` | |
| `WeatherColdSnapshotNightly` | |
| `WeatherExchangeEconomicsSnapshotRefresh` | |
| `WeatherReplayBundleExportNightly` | only if present |
| host-local tasks that name the venv | for example a streak monitor or staleness sweep |

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
existing 3.11.0 is per-user, `0` if it is all-users. Turn off PATH, the launcher, file associations,
shortcuts and precompile.

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
- Choose *Customize installation*, then confirm the scope, the target directory, launcher off, environment variables off and precompile off.

```powershell
if ($proc.ExitCode -ne 0) { NoGo "installer exit $($proc.ExitCode)" }
foreach ($p in $K.binaries.PSObject.Properties) { if ((Sha (Join-Path $NewHome $p.Name)) -ne $p.Value) { NoGo "binary $($p.Name)" } }
if ((& $NewPy -VV) -notlike "$($K.vv_prefix)*") { NoGo 'new -VV' }
$now = Get-ChildItem -LiteralPath $OldHome -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\' } | ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.FullName.Substring($OldHome.Length) }
if (Compare-Object (Get-Content "$A\oldhome-sha256.txt") $now) { NoGo 'OLD HOME CHANGED' }
if ((& $Py -VV) -notlike 'Python 3.11.0*') { NoGo 'prod venv no longer 3.11.0' }
if ([Environment]::GetEnvironmentVariable('Path','Machine') -ne $before.M -or [Environment]::GetEnvironmentVariable('Path','User') -ne $before.U) { NoGo 'PATH changed' }
& $NewPy -I -c "import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print('sqlite', sqlite3.sqlite_version); print('zlib', zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)" | Set-Content "$R\native-3119.txt"
Log 'PHASE A PASS'
```

If A4 fails after the installer ran:
- restore the old home from the freeze copy if it changed;
- check capture through the next `status.ps1` run;
- do not continue to Phase B.

### Phase B. Wheelhouse, stage venv, qualification (prep night; capture keeps running on 3.11.0)

**B0. Admission (00:30-07:00).**

```powershell
$h = (Get-Date).Hour + (Get-Date).Minute/60; if ($h -lt 0.5 -or $h -ge 7.0) { NoGo 'outside prep window' }
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 55GB) { NoGo 'disk below the bounded-suite floor plus margin' }
$Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_prep'; if (-not $Lease) { NoGo 'lease busy' }
```

**B1a. Hashed lock.** The repository pins only the direct dependencies, without hashes. The lock
comes from the A1 freeze, and the hashes come from PyPI over HTTPS.

```powershell
New-Item -ItemType Directory -Force $WH | Out-Null
Get-Content "$A\freeze-3110.txt" | Where-Object { $_ -match '^[A-Za-z0-9_.\-]+==' } | Set-Content "$R\lock.txt" -Encoding ascii
'setuptools==<a release >= 70.1 chosen at prep>' | Set-Content "$R\lock-build.txt" -Encoding ascii     # Q10
# Only if Q13 chose the exemption: replace the tzdata line with tzdata==2026.3 here and in nothing else.
```

Save `$Tools\pypi_hash_lock.py` outside `$WH`. For each `name==version` line, the script:
- reads `https://pypi.org/pypi/<name>/<version>/json`;
- keeps the SHA-256 of non-yanked `bdist_wheel` files whose tag is `cp311-cp311-win_amd64`, `abi3-win_amd64`, `none-win_amd64`, `py3-none-any` or `py2.py3-none-any`;
- exits non-zero if a pin has none;
- writes `name==version --hash=sha256:...` lines.

The night-block draft carried a reviewed copy; review the script in the handoff before it runs.

```powershell
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

`verify_wheels_vs_installed.py` (reviewed in the handoff) compares, per wheel, the hashed rows of
the wheel's `.dist-info/RECORD` with the installed `RECORD`, ignoring `.pyc` and `.data/` rows.

**Go/no-go B1b:** every wheel reports `OK`. Only the build-only `setuptools` (and `tzdata` under the
Q13 exemption) may be `UNMATCHED-ALLOWED`. A `DIFF` limited to `.dist-info` metadata at an
identical version goes to the owner. Any other `DIFF` is NO-GO.

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
`$WH` because pip passes `--no-index --find-links` to it (Q10).

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
artifacts from the production checkout. They are unpickled by `src/weather/model/model_features.py:68`.

```powershell
Push-Location -LiteralPath $Stage
& $StagePy -c "import glob, pickle, sys; fs = sorted(glob.glob(sys.argv[1])); assert fs, 'no artifacts'; [pickle.load(open(f, 'rb')) for f in fs]; print('hgb load ok')" (Join-Path $P 'artifacts\models\hgb\feature_model_hgb*.pkl')
if ($LASTEXITCODE) { NoGo 'hgb load' }
Pop-Location
Exit-WeatherHeavyWorkloadLease -Lease $Lease; $Lease = $null
```

**B2. Bounded suite on the stage interpreter.** The suite takes its own lease and needs at least
50 GiB free. Start it inside the window.

```powershell
$SuiteLog = Join-Path $R ('bounded-suite-' + (Get-Date -Format yyyyMMdd) + '.log')
$suite = Join-Path $P 'scripts\ops\bounded_worktree_test_suite.ps1'
& $suite -RepoRoot $P -WorktreeRoot $Stage -ExpectedTip $Tip -BranchRef $QBranch -LogPath "$SuiteLog.preflight" -PreflightOnly -InterpreterPath $StagePy -ExpectedInterpreterVersion '3.11.9'
if ($LASTEXITCODE) { NoGo 'suite preflight' }
& $suite -RepoRoot $P -WorktreeRoot $Stage -ExpectedTip $Tip -BranchRef $QBranch -LogPath $SuiteLog -InterpreterPath $StagePy -ExpectedInterpreterVersion '3.11.9'
$SuiteExit = $LASTEXITCODE; Log "bounded suite exit $SuiteExit"
```

**Go/no-go B2:**
- the suite exits 0;
- its interpreter-override line names `$StagePy` and 3.11.9;
- the stage worktree is clean;
- the #259 `[pre_3_11_2]` / `[constructor]` ids **pass** (on 3.11.0 they are expected to xfail or skip).

**B3. Release case** (read-only, §8):

```powershell
& $Py -m weather.operations.release_lifecycle_cli --repo-root $P active 2>&1 | Tee-Object -FilePath "$R\release-active-3110.txt"
```

**B4. Qualification record.**

```powershell
@{ result = if ($SuiteExit -eq 0) {'PASS'} else {'FAIL'}; tip=$Tip; branch=$QBranch; stage=$Stage; suite_log=$SuiteLog
   release_case='<A|B|C from B3>'; wheelhouse_manifest="$R\wheelhouse-sha256.txt"; at=(Get-Date).ToString('o') } |
  ConvertTo-Json | Set-Content "$R\qualification.json" -Encoding utf8
```

Keep `$Stage` until §D.

### Phase C. Cutover night

| Clock (local) | Step | Hard stop |
| --- | --- | --- |
| 00:30-00:55 | C0 GO checks | Any fail = NO-GO, nothing touched |
| 01:00, latest 01:30 | C1 lease and receipts | No lease by 01:30 = NO-GO |
| +5 min | C2 quiesce the auxiliary tasks and long-running holders | Shadow not sealed in 3 min = undo, NO-GO |
| +5-10 min | C3 stop the capture workers | Still active after 600 s = undo, restore, NO-GO |
| by 01:45 | C4 rename `venv` to `venv-cp3110` | Rename fails 3 times or it is past 01:45 = undo, restore, NO-GO |
| +3 min | C5 build the new `venv` offline | Fail = §R |
| +2 min | C6 quick verify | Fail = §R |
| +5-15 min | C7 S4U restore, 3/3 | Not 3/3 after one rerun = §R |
| +10 min | C8 full verify (+ C8b if case B or C) | Fail = §R |
| 02:30 | C9 PASS decision | Not passed = §R |
| start by 03:15, done by 03:45 | §R rollback | Escalate to the owner if not 3/3 by 03:45 |

This sits inside the 01:00-04:00 quiet window and ends well before the 04:15
`WeatherTrainingWindowRestore` trigger, which stays armed as the final safety net. The expected
capture gap (C3 to C7) is about 20-35 minutes. A failure before the C4 rename means **undo with no
swap**: re-enable what C2 and C3 disabled, then start the S4U restore. A failure after the rename
means §R.

**C0. GO checks.**

```powershell
$q = Get-Content "$R\qualification.json" -Raw | ConvertFrom-Json; if ($q.result -ne 'PASS') { NoGo 'not qualified' }
$Head = (git -C $P rev-parse HEAD).Trim()
if ($Head -ne $q.tip) { Log "HEAD moved from the qualified tip; master must attach roll_verdict.ps1 output showing roll-free before GO" }
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'prod tree dirty' }
if (Test-Path -LiteralPath $Old) { NoGo "$Old exists" }
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 10GB) { NoGo 'disk' }
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
Log "lease state $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P) | ConvertTo-Json -Compress)"
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $P 'scripts\ops\status.ps1') -Json | Out-File "$R\c0-status.json" -Encoding utf8
& $Py -m weather.operations.release_lifecycle_cli --repo-root $P active 2>&1 | Out-File "$R\c0-release-active.txt" -Encoding utf8
Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } | ForEach-Object { $i = Get-ScheduledTaskInfo $_
  if ($i.NextRunTime -and $i.NextRunTime -lt (Get-Date).Date.AddHours(4)) { "$($_.TaskName) next=$($i.NextRunTime)" } } | Tee-Object -FilePath "$R\c0-next-runs.txt"
Log 'C0 complete - awaiting owner GO'
```

**Go/no-go C0:**
- `status.ps1 -Json` shows capture healthy (3/3) with no FLAG that the owner has not accepted;
- `c0-release-active.txt` matches the B3 case;
- the next-runs list shows nothing outside the C2 list firing before 04:00;
- G3, G5 and G7 hold;
- the owner types GO.

**C1. Lease and fresh receipts.**

```powershell
$Lease = $null; $deadline = (Get-Date).Date.AddHours(1).AddMinutes(30)
while (-not $Lease) { $Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_cutover'
  if (-not $Lease) { if ((Get-Date) -gt $deadline) { NoGo 'no lease by 01:30' }; Start-Sleep -Seconds 30 } }
$N = Join-Path $R ('night-' + (Get-Date -Format yyyyMMdd)); New-Item -ItemType Directory -Force $N | Out-Null
& $Py -m pip freeze --all | Set-Content "$N\freeze-3110-tonight.txt"
if (Compare-Object (Get-Content "$A\freeze-3110.txt") (Get-Content "$N\freeze-3110-tonight.txt")) { NoGo 'prod venv changed since Phase B - requalify' }
foreach ($f in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') { Copy-Item -LiteralPath (Join-Path $P "data\snapshots\$f") "$N\pre-$f" }
```

**C2. Quiesce the auxiliary tasks and long-running holders.**

```powershell
$Aux = @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })
$pre = foreach ($t in $Aux) { $x = Get-ScheduledTask -TaskName $t; [pscustomobject]@{ Task=$t; State=[string]$x.State } }   # throws on a wrong name
$pre | Export-Csv -LiteralPath "$N\aux-prestate.csv" -NoTypeInformation
function Undo-Aux { foreach ($row in Import-Csv "$N\aux-prestate.csv") { if ($row.State -ne 'Disabled') { Enable-ScheduledTask -TaskName $row.Task | Out-Null } }
  Remove-Item -LiteralPath (Join-Path $P 'data\maker_shadow\STOP') -ErrorAction SilentlyContinue }
# Maker shadow runner: STOP file only, never a kill
if ($Aux -contains 'WeatherMakerShadowRunner') {
  New-Item -ItemType File -Force (Join-Path $P 'data\maker_shadow\STOP') | Out-Null
  $t0 = Get-Date; while ((Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running' -and ((Get-Date)-$t0).TotalSeconds -lt 180) { Start-Sleep 10 }
  if ((Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running') { Undo-Aux; NoGo 'shadow did not seal in 3 min' } }
foreach ($row in $pre) { if ($row.State -ne 'Disabled') { Disable-ScheduledTask -TaskName $row.Task | Out-Null } }
& $Py -m weather.operations.execution_tape_supervisor stop 2>&1 | Tee-Object -FilePath "$N\tape-stop.txt"
# 88a worker: only with the owner's Q12 authorization for this night
Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture; Log 'C2 88a worker stopped (owner Q12)'
Log 'C2 quiesced'
```

**C3. Stop the capture workers** (the training-window stop sequence, `training_window.ps1:396-412`):

```powershell
$Sup = 'WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor'
function Undo-Stop { foreach ($t in $Sup) { Enable-ScheduledTask -TaskName $t | Out-Null }; Start-ScheduledTask -TaskName WeatherTrainingWindowRestore; Undo-Aux }
foreach ($t in $Sup) { Disable-ScheduledTask -TaskName $t | Out-Null }
Push-Location -LiteralPath $P
& $Py -m weather.collection.snapshot_tracker --stop
& $Py -m weather.market.market_microstructure stop
& $Py -m weather.operations.observation_trigger stop
$t0 = Get-Date; $stopped = $false
while (((Get-Date)-$t0).TotalSeconds -lt 600) {
  & $Py -m weather.operations.capture_resource_gate --workload py3119_cutover_stop_confirmation --capture-mode no_live_capture `
     --min-free-memory-bytes 0 --min-free-disk-bytes 0 --no-write --fail-on-block | Out-Null
  if ($LASTEXITCODE -eq 0) { $stopped = $true; break }; Start-Sleep 5 }
Pop-Location
if (-not $stopped) { Undo-Stop; NoGo 'C3 stop timeout - restored' }
$GapStart = Get-Date; Log 'C3 capture stopped'
```

In no-live-capture mode, one gate call checks all three loops. That is what `Wait-CaptureStopped`
does (`training_window.ps1:238-252`). `--workload` is only a label
(`capture_resource_gate.py`, the `--workload` argument).

**C4. Sweep and rename (deadline 01:45).**

```powershell
if ((Get-Date) -gt (Get-Date).Date.AddHours(1).AddMinutes(45)) { Undo-Stop; NoGo 'swap deadline passed' }
$OldHomeNorm = (Get-Content "$R\oldhome.txt").Trim().TrimEnd('\')
function Get-VenvHolders { Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
  $_.ExecutablePath -like "$P\venv\*" -or $_.CommandLine -like "*$P\venv*" -or ($_.ExecutablePath -like "$OldHomeNorm\*" -and $_.CommandLine -like "*$P*") } |
  Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine }
$swapped = $false
for ($i = 1; $i -le 3 -and -not $swapped; $i++) {
  $hold = Get-VenvHolders; $hold | Format-List | Out-File "$N\holders-try$i.txt"
  if ($hold) { Log "try $i holders $(($hold.ProcessId) -join ',')"; Start-Sleep 20; continue }
  try { Rename-Item -LiteralPath (Join-Path $P 'venv') -NewName 'venv-cp3110' -ErrorAction Stop; $swapped = $true }
  catch { Log "rename try $i failed: $($_.Exception.Message)"; Start-Sleep 20 } }
if (-not $swapped) { Undo-Stop; NoGo 'C4 rename failed - no swap, restored' }
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
Test-Venv $Py $P 'prod'
foreach ($k in 'python.exe','pythonw.exe') { if ((Sha (Join-Path $P "venv\Scripts\$k")) -ne $K.binaries."Lib\venv\scripts\nt\$k") { NoGo "launcher $k -> ROLLBACK" } }
$pthNew = Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" }
Compare-Object (Get-Content "$A\pth-3110.txt") $pthNew | Out-File "$N\pth-diff.txt"   # the editable path must still point at $P\src; review any difference
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'tree dirty -> ROLLBACK' }
```

**C7. Restore through the S4U path.**

```powershell
foreach ($t in $Sup) { Enable-ScheduledTask -TaskName $t | Out-Null }
Start-ScheduledTask -TaskName WeatherTrainingWindowRestore
$t0 = Get-Date; $ok = $false; $rerun = $false
while (((Get-Date)-$t0).TotalMinutes -lt 15) { Start-Sleep 20
  $st = Get-Content -LiteralPath (Join-Path $P 'data\logs\training_window_status.json') -Raw | ConvertFrom-Json
  if ($st.phase -eq 'restore_only' -and $st.outcome -eq 'capture_recovery_pass' -and [datetimeoffset]$st.updated_at -gt [datetimeoffset]$GapStart) { $ok = $true; break }
  if ($st.outcome -eq 'capture_recovery_failed' -and -not $rerun -and (Get-ScheduledTask WeatherTrainingWindowRestore).State -ne 'Running') {
    $rerun = $true; Log 'restore failed once; rerun'; Start-ScheduledTask -TaskName WeatherTrainingWindowRestore } }
if (-not $ok) { NoGo 'C7 not recovered -> ROLLBACK' }
$GapEnd = Get-Date; Log ("C7 3/3; gap {0:n1} min" -f ($GapEnd-$GapStart).TotalMinutes)
Undo-Aux   # re-enable aux tasks to their pre-state; remove the shadow STOP file
foreach ($t in 'WeatherExecutionTapeSupervisor','WeatherMakerShadowRunner','WeatherMakerEvidenceCapture') {
  $row = Import-Csv "$N\aux-prestate.csv" | Where-Object Task -eq $t; if ($row -and $row.State -ne 'Disabled') { Start-ScheduledTask -TaskName $t } }
```

The restore task enables the supervisors itself (`training_window.ps1:159` onward). Enabling them
first is harmless.

**C8. Full verify.**

```powershell
# a) the workers run 3.11.9
foreach ($f in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') {
  $v = (Get-Content -LiteralPath (Join-Path $P "data\snapshots\$f") -Raw | ConvertFrom-Json).runtime_identity.python_version
  Log "$f python_version=$v"; if ($v -ne '3.11.9') { NoGo "$f $v -> ROLLBACK" } }
# b) execution tape (allow up to 5 min to reconnect)
& $Py -m weather.operations.execution_tape_supervisor status --stale-after-seconds 180 | Tee-Object -FilePath "$N\tape-status.json"
# c) release readiness
& $Py -m weather.operations.release_lifecycle_cli --repo-root $P active 2>&1 | Tee-Object -FilePath "$N\release-active-3119.txt"
# d) host status, including the 88a status and the maker shadow
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $P 'scripts\ops\status.ps1') -Json | Out-File "$N\status.json" -Encoding utf8
# e) native-library receipt, old and new
& $Py -I -c "import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print('sqlite', sqlite3.sqlite_version); print('zlib', zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)" | Set-Content "$N\native-3119.txt"
```

**Go/no-go C8:**
- (a) all three status files report 3.11.9.
- (b) the tape health is `RUNNING` or `DEGRADED` with a live PID, its identity matches the current runtime, evidence integrity passes, and the connection state is `CONNECTED`.
- (c) case A: the output equals `$R\release-active-3110.txt` (the same missing-pointer BLOCK). Case B or C: the expected runtime-mismatch BLOCK, then C8b.
- (d) no new FLAG; the 88a worker and the maker shadow are capturing again.
- (e) is a receipt only.

**C9. 02:30 decision.** PASS needs all of:
- C6, C7 and C8 green;
- a gap of 35 minutes or less, or an overrun the owner accepts;
- for case B or C, C8b `active` returns PASS.

Otherwise run §R.

**C10. Close-out.**

```powershell
@{ result='PASS'; head=$Head; gap_minutes=[math]::Round(($GapEnd-$GapStart).TotalMinutes,1); old_venv=$Old; new_home=$NewHome; release_case=$q.release_case; at=(Get-Date).ToString('o') } |
  ConvertTo-Json | Set-Content "$N\cutover-receipt.json" -Encoding utf8
Exit-WeatherHeavyWorkloadLease -Lease $Lease; $Lease = $null; Log 'CUTOVER PASS; lease released'
```

Keep these for at least 14 days:
- `venv-cp3110`;
- the freeze copy of the old home;
- the 3.11.0 installation;
- every 3.11.0 release manifest;
- `$R`.

Uninstalling 3.11.0 is a later, separate owner decision.

### §R. Rollback (start by 03:15, done by 03:45)

```powershell
Log 'ROLLBACK start'
foreach ($t in $Sup) { Disable-ScheduledTask -TaskName $t | Out-Null }
$RbPy = if (Test-Path -LiteralPath "$P\venv\Scripts\python.exe") { "$P\venv\Scripts\python.exe" } else { "$Old\Scripts\python.exe" }
Push-Location -LiteralPath $P
& $RbPy -m weather.collection.snapshot_tracker --stop; & $RbPy -m weather.market.market_microstructure stop; & $RbPy -m weather.operations.observation_trigger stop
# wait with the same single gate call as C3 (600 s); stop the tape with its own verb; stop the 88a task only under the Q12 authorization
Pop-Location
if (Test-Path -LiteralPath "$P\venv") { Rename-Item -LiteralPath "$P\venv" -NewName 'venv-cp3119-failed' -ErrorAction Stop }
Rename-Item -LiteralPath $Old -NewName 'venv' -ErrorAction Stop
if ((& "$P\venv\Scripts\python.exe" -VV) -notlike 'Python 3.11.0*') { Log 'ROLLBACK: venv not 3.11.0 - ESCALATE' }
if (Compare-Object (Get-Content "$A\freeze-3110.txt") (& "$P\venv\Scripts\python.exe" -m pip freeze --all)) { Log 'ROLLBACK: freeze differs - ESCALATE' }
foreach ($t in $Sup) { Enable-ScheduledTask -TaskName $t | Out-Null }
Start-ScheduledTask -TaskName WeatherTrainingWindowRestore   # poll exactly as C7
Undo-Aux
& "$P\venv\Scripts\python.exe" -m weather.operations.release_lifecycle_cli --repo-root $P active 2>&1 | Out-File "$N\rollback-active.txt"
```

**Rollback passes when:**
- the S4U restore reports 3/3;
- the three status files report 3.11.0;
- case A: `active` equals the 3.11.0 text;
- case B or C: if C8b promoted, restore the previous pointer with `release_lifecycle_cli rollback --market-day-boundary <fresh boundary>`. The 3.11.0 release is untouched, so `active` passes on 3.11.0.

Keep `venv-cp3119-failed` and `$R` for diagnosis. Release the lease. If 3/3 is not reached by 03:45,
escalate to the owner and leave the 04:15 restore trigger armed.

### §D. Cleanup after PASS (a later admitted night)

```powershell
git -C $P worktree remove $Stage      # use --force only if git refuses because of the ignored stage venv
git -C $P branch -D $QBranch
```

## 8. Release re-bind

| `active` on 3.11.0 (B3, C0) | Case | Cutover requirement |
| --- | --- | --- |
| `BLOCK`, active release pointer missing | **A** (expected) | Nothing to re-bind. After the swap, `active` must print the identical BLOCK. |
| `PASS`, a research or bootstrap release that is not capital-serving | **B** | C8b on the night, with owner-approved spec, decision and boundary drafts. |
| `PASS`, a release serving paper or live | **C** | As B. The owner signs `spec.json` and `decision.json` before 00:30, or it is NO-GO. |

**C8b (case B or C only).** Follow [Release #1 build runbook](RELEASE_ONE_BUILD_RUNBOOK.md) §3c and
§4 on the new interpreter. The CLI shape is in `src/weather/operations/release_lifecycle_cli.py`.

```powershell
& $Py -m weather.operations.release_lifecycle_cli --repo-root $P create --candidate '<candidate dir from spec>' --spec "$R\release\spec.json" | Tee-Object "$N\rebind-create.json"
& $Py -m weather.operations.release_lifecycle_cli --repo-root $P verify '<release_id>' | Tee-Object "$N\rebind-verify.json"
& $Py -m weather.operations.release_lifecycle_cli --repo-root $P promote '<release_id>' --decision "$R\release\decision.json" --market-day-boundary "$R\release\boundary.json" | Tee-Object "$N\rebind-promote.json"
& $Py -m weather.operations.release_lifecycle_cli --repo-root $P active | Tee-Object "$N\rebind-active.json"   # must be PASS
```

- `create` records `capture_runtime_versions()` from the running 3.11.9 interpreter.
- Write the boundary file just before `promote`, from the repository template, and keep it fresh as that runbook requires.
- The 3.11.0 release stays on disk as the rollback target.

## 9. After the cutover (not part of the night)

1. **Pinned deployments (Q7, Q14).** On their first run after the cutover, check each one:
   - the watchdog's next 15-minute run reports normally (`status.ps1 -Json` watchdog row, task `LastTaskResult`);
   - the 91a `WeatherColdSnapshotNightly` run at 06:50 completes with its normal receipt;
   - the U6 export, when registered, completes its first run.
2. **Cold-archive byte check (§5).** In a later admitted window, run a read-only verify of one
   existing cold archive on 3.11.9 ([verified cold archive](verified-cold-archive.md)). This
   checks that the `tarfile` and gzip paths still match bytes written on 3.11.0.
3. **Live seals (G10).** Reseal every live seal under its own runbook before any live attempt. This
   needs an SDK audit on 3.11.9, the owner's credential receipt and a fresh seal. Nothing here
   authorizes a live action.
4. **Follow-up changes (separate branches):**
   - repin the Windows qualification lane from `3.11.0` to `3.11.9` (`.github/workflows/windows-qualification.yml:244`);
   - update the `src/` comments that say the host runs 3.11.0 (`wallet_reader_transport.py:73`, `wu_history.py:157`, `wu_redaction.py:255`). They are roll-sensitive: send them through `roll_verdict.ps1`;
   - update the findings that cite pre-3.11.2 behaviour.
5. **State.** Production rewrites [the state of play](STATE_OF_PLAY.md) (host Python) and records
   the cutover in the owning roadmap item.
6. **Day 14.** The owner decides on deleting `venv-cp3110` and the freeze copy, and on uninstalling 3.11.0.

## 10. Timings against the host timetable

| Window | Allowed for this runbook |
| --- | --- |
| 00:30-09:00 | §T, Phase B (start by 07:00 so the suite ends inside the window), §D |
| 01:00-04:00 quiet window | Phase C only (latest lease 01:30, latest rename 01:45, decision 02:30, rollback start 03:15) |
| 09:30-11:55 | Stage-A chain only; nothing from this runbook |
| 12:00-18:00 graded and 18:00-00:30 near-close | Nothing. Host reads (§4) belong outside 12:00-00:30. |

## 11. Owner sign-off checklist

The owner initials each line in the decision log. Recommendations come first.

- [ ] **Runbook revision** approved as written (G0). The night is named, and it is after LFC session 0
      (G7) and after the 88a freeze (G8). Recommendation: the first quiet window after 10-14, not
      the night before an LFC session.
- [ ] **Q12, 88a stop:** authorize `Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture` at C2,
      accepting a short 88a gap and an untested abrupt stop (recommended). The alternative is to wait
      for a reviewed graceful-stop verb.
- [ ] **Capture gap:** about 20-35 minutes across the capture workers, the execution tape, the maker
      shadow and 88a. Confirm this is within the approved one-gap budget, and that the gap's timing
      relative to the desk-study panel window is acceptable.
- [ ] **Q13, tzdata:** run §T on an earlier night (recommended), or exempt tzdata in the comparisons.
- [ ] **Q4, installer scope:** install in the opposite scope to 3.11.0 per H1, and cancel on
      "Upgrade" (recommended). Any NuGet or embeddable fallback is a new approval.
- [ ] **Q9, provenance:** require the python.org size and MD5, the winget SHA-256 and the PSF
      Authenticode signature together (recommended). Sigstore is optional.
- [ ] **Q8, scope:** accept 3.11.9 with the partial audit in §5 (recommended), and track 3.12/3.13
      separately.
- [ ] **Q7, deployments:** accept that the pinned watchdog, 91a and U6 deployments move to 3.11.9
      with the production venv, verified per §9 (recommended).
- [ ] **Q3, U6:** if it is registered before the night, let the 00:35 export finish before C1
      (recommended), or skip one export.
- [ ] **Release case:** case A confirmed by H5 and B3, or case B/C drafts signed (G6).
- [ ] **Retention:** keep the old venv, the freeze copy, the 3.11.0 install and its manifests for 14 days.
- [ ] **Live:** no live attempt between the cutover and the reseal (G10).

## Update this file when

- the capture stop or restore path, the bounded suite's interpreter flags, release runtime binding,
  live interpreter seals or the Scheduler task set changes;
- an open question above is answered (move it to RESOLVED with its evidence);
- the target interpreter changes;
- the upgrade has run: mark this file historical, or retarget it, in the same change that updates
  the state of play.

Validate with `.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit`.
