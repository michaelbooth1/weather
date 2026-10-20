# Host Python upgrade runbook (capture host, 3.11.0 to 3.11.9)

> **APPROVED by the owner 2026-10-12 (DECISION_LOG, §11)**, including the 2026-10-12 G0/G7 revisions
> and the §7a calendar. The cutover night was 00:30 on 10-17 and did not run; it is now 00:30 on Thu 10-22
> (the night of 10-21 to 10-22; owner 2026-10-20 ~16:4x EDT, verbatim "Keep Python 10-21/22 (Recommended)", relayed by master-agent), on pre-N12 master. The state of play owns the date.
> Nothing in this file authorizes a download, an install, a capture gap, a task change or a merge.
> [The owner sign-off checklist](#11-owner-sign-off-checklist) lists what the owner must sign first.
> Live orders, cancels and signing are out of scope here; the live launcher is resealed under its
> own runbook.

Status: approved runbook (owner sign-off 2026-10-12, with the §11 details recorded the same day). It turns the approved intent (DECISION_LOG, 2026-10-09: host Python
upgrade as a quiet-window job with a release re-bind; installer download, UAC and one capture gap; the installer and UAC
were replaced by the NuGet route in the 2026-10-13 revision)
into gated steps. Today's host version, the planned night and every dated hold live in
[the state of play](STATE_OF_PLAY.md), not here.

Revision 2026-10-12, **confirmed by the owner the same day**: the owner postponed LFC session 0 on 10-12 and
approved the upgrade, so G7 no longer waits for session 0's handback. It now only keeps the Phase B
and Phase C nights clear of scheduled LFC sessions. G0 now names each phase's own morning or night,
so Phase A can run on its owner-named morning before the cutover night is named. §7a holds the
calendar; because Phase A runs before §T, §T ends by re-taking the venv receipts (T-R).

Revision 2026-10-13 (r2 after an adversarial review), **DRAFT, pending owner sign-off (G0, G12, Q4, Q9)**: the installer route for A4 is
withdrawn. On the host, the 3.11.9 installer with `InstallAllUsers=1` detected the per-user 3.11.0
bundle and planned a **MajorUpgrade** of it, not a side-by-side install (detect log
`install-detect-20261013-0858.log`: "Detected related bundle ... scope: PerUser ... operation:
MajorUpgrade"; it was stopped before plan or apply, and nothing changed). A3 and A4 now download the
python.org NuGet package `python` 3.11.9 and copy its `tools` tree into the new home: no installer,
no MSI, no registry, no PATH, no UAC prompt and no owner click. Its binaries are the same build as
the installer's: the 11 files pinned in `binaries` (§6a) have identical sizes in the package and in
the workstation's installer-built 3.11.9 home, and A4 proves the SHA-256 values. Phase A runs in
the elevated operator session on an owner-named morning; the §7a dates are re-set by the owner in
the decision log and the state of play.

Revision 2026-10-14 (A' r2): **every comparison of a stored `pip freeze` against the live production venv masks the
weather editable line's commit sha** (`Mask-Editable`, §6). That line,
`-e git+https://github.com/michaelbooth1/weather.git@<sha>#egg=weather_market`, records the production HEAD and so changes
on every master merge. A' r1 (10-14 05:16) stopped on a false NO-GO for exactly that line (HEAD `4bc93ae5d` to
`378256d49`; nothing installed); r2 masked it and passed at 05:23, and a negative control (a changed pip version) still
failed. The mask replaces only the 40-hex sha, only on that exact line, so a missing or different weather install still
differs. HEAD itself is checked by G3 (C0), not by the freeze. §T, T-R, C1 and §R use the mask; Test-Venv already drops
`-e` lines, and the B1a lock never contained them.

Revision 2026-10-16 (B1b verifier r2): **Phase B attempt 1 stopped on a false NO-GO at 00:30:42.**
The r1 `verify_wheels_vs_installed.py` (§6b) took the symmetric difference of the wheel and installed `RECORD`
row sets, so rows that pip itself writes at install time counted as differences: the dist-info `INSTALLER`,
`REQUESTED` and `direct_url.json`, the `../Scripts` launchers, and wheel `.data/` files installed under
`../../share` or `../../etc`. 76 of 77 packages showed `DIFF`, but no wheel row actually differed. r2 (Fable
RUN) requires the wheel rows to be a subset of the installed rows and allows only those pip-written kinds as
installed-only rows, with `.data/` files matched by identical hash. Against that night's wheelhouse it
returned rc 0 and 77 `OK`; attempt 2 started at 00:35:34. The pinned r2 sha256 is
`FE9F7A574CF914E070AC9FD70C93C661D9DD2239AB9109B02E71263EE9DA668D`. The host file is canonical, and the Phase B
wrapper r2 differs from r1 only in that pin.

Revision 2026-10-16 (Phase B wrapper defects, also in C): Phase B qualified (bounded suite 21/21), but the wrapper
stopped at B3, and master-agent finished B3 and E by hand. Two defects would have hit Phase C as well.
(1) `Get-ReleaseActive` read the release CLI output through a `[string]` cast of `Get-Content -Raw`, which is `$null` for an
empty file in PowerShell 5.1, so the expected BLOCK case (empty stdout) threw at `$o.Trim()`; it now uses
`"$(...)"`. It runs at B3, C0, C8 and §R. No other block of this file casts `Get-Content -Raw` directly.
(2) `status.ps1 -Json` exits 2 on any flag, and the host carries standing flags that predate the night
(an overdue documentation transaction and two STALENESS_SWEEP CRITICAL rows), so an exit-0 test never
passes. B0 and C0 now save a flag baseline (`Save-StatusBaseline`), and C8 and C9c judge only new flags
(`Get-NewStatusFlags`). A wrapper must never gate on that exit code.

Revision 2026-10-19 (delta review for a post-N12 cutover; [review](pyup-c-1021-delta-review.md)). N12 adds a second
long-running holder of the production venv with no stop verb, the capture-family task
`WeatherMakerEvidenceLowestTemperature` (`maker_evidence_capture --family`, `register_maker_evidence_family_capture.ps1`).
C0 now requires every registered `WeatherMakerEvidence<Family>` task to be in `aux-tasks.txt` and its stop to be
recorded as `STOP_AUTHORIZED` in `$R\q12b.txt` (Q12b); C2 stops it with the 88a worker; C9c checks it. **Every family step is conditional on registration:** C0 lists the registered `WeatherMakerEvidence<Family>` tasks, and with none, C0, C2 and C9c skip the family steps and never read `q12b.txt`. G3 now names the
exact `roll_verdict.ps1` call, and **B-R** requalifies a stage venv in a new stage path when HEAD moved roll-sensitively after Phase B
(N12 would), and §D now removes every qualification worktree. **B-R is parked:** C on 10-22 runs on pre-N12 master, so G3 rests on
the Phase B tip; B-R is used only if C fails and N12 lands first. No date in this file changed; the state of play and the decision log own the cutover night.

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
| G0 | The owner has signed §11 for this runbook revision and has named the morning or night of the phase about to run (Phase A: its owner-attended morning; Phase B and C: their nights). Revised 2026-10-12 (owner-confirmed). | Before Phase A, B0, C0 |
| G1 | The bounded suite supports `-InterpreterPath` and `-ExpectedInterpreterVersion` (`scripts/ops/bounded_worktree_test_suite.ps1:44-52`). | Met on master; re-read `param(` if the script changed |
| G2 | Phase A and Phase B passed on earlier nights, and `$R\qualification.json` has `"result":"PASS"`. | C0 |
| G3 | The production HEAD equals the qualified tip, or `scripts\ops\roll_verdict.ps1 -Branch <HEAD sha> -Base <qualified tip sha>` exits 0 (ROLL-FREE; exit 3 or 1 fails G3). A failed G3 needs B-R (requalify on the new tip) on an earlier night, or an owner ruling. | C0 |
| G4 | The owner is reachable from 00:30 to 03:45 on the cutover night: GO at C0, and any escalation up to the end of §R. Phase A needs no owner click since the 2026-10-13 revision (A4 has no installer).  **For C on the night of 10-21 to 10-22** the escalation rule is the owner's "Auto net, you in the morning" (owner 2026-10-19 ~13:1x EDT, selected options relayed by master-agent), which supersedes the DECISION_LOG rows of 2026-10-13 (advance GO, automatic rollback) and 2026-10-17 (the owner's own GO that night) on who answers an escalation; GO at C0 still comes from the owner in chat (§R, "Escalation"). | C0 |
| G5 | No other lease user is due that night. Specifically: <br>- `WeatherTrainingWindow` (a 01:00 one-shot, `register_training_window.ps1:3`) is disabled or has no trigger that night; <br>- Stage B `WeatherEveningEvidenceRefresh` (00:35, holds the lease to 09:00 when enabled; `register_daily_refresh.ps1:20-24`) is disabled; <br>- a U6 export registered at 00:35 (Q3) is disabled (enforced in B0 and C0 by `Assert-NoU6At0035`);<br>- no integration attempt, quiet-window merge, storage one-shot or held-head work is scheduled;<br>- no host replay or research batch (for example a lever-5 or item 337 replay) is scheduled or still running, and none holds the lease. | Phase B (B0), C0 |
| G6 | Release case A: `artifacts\releases\current_release.json` is absent (H5, B3, C0). Case B or C is NO-GO for this runbook (§8). | H5, B3, C0 |
| G7 (LFC) | The cutover night (and any Phase B prep night) is not the night before or the night of a scheduled LFC session. Revised 2026-10-12 (owner-confirmed): it no longer waits for LFC session 0, which the owner postponed. **Dated exception 2026-10-14** (owner: "Keep B" (2026-10-14 16:27 EDT, relayed verbatim by master-agent); DECISION_LOG 2026-10-13 LFC session 0 row): Phase B runs at 00:30 on 10-16, the morning of LFC session 0 (Fri 10-16), on the guard that B ends clean by 09:00 with the 8765 reader and capture re-checked, else session 0 slips; C stays at 00:30 on 10-17. | Phase B (B0), C0 |
| G8 (88a) | The night is after the 88a merge freeze in the state of play. `$R\q12.txt` records the owner's Q12 choice as `STOP_AUTHORIZED` with its DECISION_LOG reference. Any other value means NO-GO, because the 88a worker would hold the venv. | Sign-off, C0, C2 |
| G9 (tzdata) | The tzdata sequencing is decided (Q13), so the freeze comparison in `Test-Venv` cannot false-fail. | Before Phase B |
| G10 (seals) | No live attempt is planned between the cutover and the reseal. | Sign-off |
| G11 (DST) | No phase of this runbook runs on the DST fall-back night (the night of 10-31 to 11-01). That night is under OD30 (HOST_LOAD_POLICY rule 10), and the repeated hour breaks the `.Date.AddHours()` deadlines below. | Every phase |
| G12 (downloads) | The owner has approved the PyPI wheel downloads (§T, B1a, B1b) and the NuGet package download (A3; revision 2026-10-13). The installer download approved earlier is no longer used. | Sign-off |

## 3. Question register

Status key:
- **RESOLVED**: settled from repository evidence;
- **NEEDS-HOST-READ**: the read-only command is in §4;
- **OWNER-DECISION**: options are given with the recommendation first, and are collected in §11.

The owner decided Q4, Q7-Q9, Q12 (`STOP_AUTHORIZED`) and Q13 (§T on an earlier night) with their
recommendations on 2026-10-12 (DECISION_LOG); the H-reads that Q4 and Q5 still need stay due.

| # | Question | Status | Answer or next step |
| --- | --- | --- | --- |
| Q1 | Can an interactive session stop, see and verify the S4U capture workers? | **RESOLVED** (H6 optional corroboration) | Run Phase C and §R in an **elevated** window. The stop confirmation is PID-based: `capture_resource_gate.py:150-158` marks a loop active when the status PID or the writer-lock PID is alive (or heartbeat, lock and PID evidence agree). It uses the gate the training window uses (`training_window.ps1:238-252`), so it works from an interactive shell. The binding recovery proof is the S4U `WeatherTrainingWindowRestore` task (S4U at `register_training_window.ps1:115-118`, `-RestoreOnly` at :140). It writes `restore_only` / `capture_recovery_pass` (`training_window.ps1:277-290`) and takes no lease (the lease is at :352, after the restore-only exit). `capture_recovery_check` is documented to run in the S4U context (`capture_recovery_check.py:1-6`), and a non-elevated session cannot read S4U command lines (HOST_LOAD_POLICY, "residual scan" paragraph), so the interactive check is corroboration only. The rename failing on a locked file is the final backstop. |
| Q2 | Exact interpreter flag on the bounded suite | **RESOLVED** (closed earlier) | `-ExpectedInterpreterVersion` takes an exact `X.Y.Z` and requires `-InterpreterPath` (`bounded_worktree_test_suite.ps1:44-52`). |
| Q3 | Does the U6 export collide with the cutover? | **RESOLVED, conditional** (H8 confirms) | `WeatherReplayBundleExportNightly` stays unregistered until the owner says yes (state of play). The owner approved its 04:10 slot (DECISION_LOG 2026-10-09), so 04:10 is the likely registration. The 00:35 slot is the only one on the build-line registrar. If it is registered, it is in the C2 aux list and stays **disabled** from C2 until C9b, and §R does not re-enable it unless capture is 3/3. A 00:35 run with its 50-minute limit can hold the lease until 01:25, after the 01:15 latest cutover lease, so a 00:35 registration must be disabled for the cutover night (G5). A 04:10 run starts after the 03:45 rollback deadline. |
| Q4 | Will the installer offer "Upgrade" over the existing 3.11.0? | **ANSWERED 2026-10-13: yes for the all-users scope** (host detect log, revision note; a same-scope per-user install is an upgrade by definition); **OWNER-DECISION**: install from the NuGet package (A3/A4) | Superseded inference, kept for the record: PEP 514 allows one `PythonCore\3.11` registration per hive (HKCU, HKLM). Inference, not tested: install 3.11.9 in the **opposite** scope from the existing 3.11.0 (all users if 3.11.0 is per-user, and the reverse). The owner cancels if the first page says *Upgrade* or *Modify*. A NuGet or embeddable-zip fallback is a new download and needs its own approval. |
| Q5 | Release case A, B or C? | **RESOLVED: case A expected; NEEDS-HOST-READ H5 to confirm** | The state of play says there is no release store on the host. The pointer path is `artifacts\releases\current_release.json` (`release_artifacts.py:49-50`). H5, B3 and C0 re-check it. Any case other than A is NO-GO (G6, §8). |
| Q6 | #259 test ids | **RESOLVED** (closed earlier) | #259 is on master. Its parametrized `constructor` / `pre_3_11_2` tests (`tests/sources/test_wu_redaction.py`, around lines 680 and 721) run on every 3.11 patch without skip or xfail, and must pass in B2. |
| Q7 | Which venvs and deployments move with the cutover? | **RESOLVED; contradicts the original plan.** Sibling venvs: H4 | The pinned watchdog, the 91a cold snapshot, the manual order journal, boot recovery and the U6 exam deployment all run the **production** venv (evidence in §1). They move to 3.11.9 at the cutover; none is left on 3.11.0. The scheduled ones are quiesced in C2 and verified in §9. Sibling worktree venvs keep `home = <3.11.0>` and keep working, because 3.11.0 stays installed. |
| Q8 | Are 3.11.10 and later fixes needed? | **OWNER-DECISION** | 3.11.9 is the last 3.11 release with a Windows installer. §5 lists the audited and not-audited items. Recommendation: take 3.11.9 now and track a 3.12/3.13 move separately. |
| Q9 | What proves the NuGet package's provenance? | **OWNER-DECISION** (revision 2026-10-13) | The nuget.org size and SHA-512 (same origin as the download), the W0 full-tree comparison against the workstation's python.org-installer home, the pinned `binaries` SHA-256 values, and PSF Authenticode on the signed binaries. The earlier installer provenance (python.org size and MD5, winget SHA-256) is retired with the installer. |
| Q10 | Build backend for the editable install | **RESOLVED** (H2 records versions) | `pyproject.toml` requires `setuptools>=69`, but a fresh 3.11.9 venv bundles setuptools 65.5.0. The editable install therefore uses build isolation fed from the wheelhouse: pip passes `--no-index --find-links` to the isolated build. Pin a setuptools release of 70.1 or later in `lock-build`. From 70.1 setuptools ships `bdist_wheel` itself; if you pin an older release, add `wheel` to `lock-build`. The B1a hash script fails closed if a wheel is missing. |
| Q11 | Names on master (memory guard reader, tape stop verb, status key, gate flags) | **RESOLVED** (closed earlier) | `Read-WeatherMemoryGuardStatus -Path` (`memory_guard_status_reader.ps1:13-17`); `execution_tape_supervisor stop` has no arguments (`execution_tape_supervisor.py:880`); `updated_at` (`training_window.ps1:144`). |
| Q12 (new) | How does the 88a worker release the venv? | **OWNER-DECISION**, recorded in `$R\q12.txt` (G8) | `WeatherMakerEvidenceCapture` runs one long-lived worker that holds the lock ([passive maker evidence capture](passive-maker-evidence-capture.md), "Commands and registration"). Its CLI has no stop verb and no stop file (`maker_evidence_capture.py:365-372`), so disabling the task does not end it, and the rename fails while it runs. **Recommendation:** after the 88a freeze, the owner authorizes `Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture` at C2 (record `STOP_AUTHORIZED`), with the resume check in C9c. Risk: an abrupt stop skips `store.seal()` (`maker_evidence_capture.py:343-360`), and the store raises "torn journal" on a partial last line (`maker_evidence_store.py:142-143`). Alternative: wait for a reviewed graceful-stop verb, which is 88a capture behaviour and waits for the freeze to end. Until one exists, the cutover is NO-GO. |
| Q12b (2026-10-19) | How does a capture-family task (`WeatherMakerEvidence<Family>`, N12) release the venv? | **OWNER-DECISION**, recorded in `$R\q12b.txt`; needed only if such a task is registered on the cutover night | Same code and the same risk as Q12: `maker_evidence_capture --family` has no stop verb, its S4U task repeats every minute with `IgnoreNew`, so only disable-then-`Stop-ScheduledTask` ends it, and an abrupt stop can leave a partial last journal line in its own root `data\maker_evidence_families\<id>`. **Recommendation:** `STOP_AUTHORIZED` (C2 stops it next to the 88a worker; C9c checks it). Alternative: leave it unregistered until after the cutover. |
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
$(foreach ($hk in 'HKCU:\Software\Python\PythonCore','HKLM:\SOFTWARE\Python\PythonCore','HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore') {
  Get-ChildItem -LiteralPath $hk -ErrorAction SilentlyContinue | ForEach-Object {
    $ip = Get-ItemProperty -LiteralPath (Join-Path $_.PSPath 'InstallPath') -ErrorAction SilentlyContinue
    '{0} | InstallPath={1}' -f $_.Name, $ip.'(default)'
    $pp = Get-Item -LiteralPath (Join-Path $_.PSPath 'PythonPath') -ErrorAction SilentlyContinue
    if ($pp) { '{0} | PythonPath(default)={1}' -f $_.Name, $pp.GetValue('')
      Get-ChildItem -LiteralPath $pp.PSPath -Recurse -ErrorAction SilentlyContinue | ForEach-Object { '{0} | PythonPath subkey={1}' -f $_.Name, $_.GetValue('') } } } }) |
  Out-File "$HR\h1-pythoncore.txt" -Encoding utf8   # expect no PythonPath subkey (getpath appends each subkey's default value)
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -like 'Python 3.11*' } | Select-Object DisplayName, DisplayVersion, InstallLocation, PSPath |
  Format-List | Out-File "$HR\h1-uninstall.txt" -Encoding utf8
# H2 (Q10, Q13): production venv identity and packaging tools
$null = Invoke-Native $Py @('-VV') "$HR\h2-vv"
Get-Content -LiteralPath (Join-Path $P 'venv\pyvenv.cfg') | Out-File "$HR\h2-pyvenv.txt" -Encoding utf8
$null = Invoke-Native $Py @('-m','pip','freeze','--all') "$HR\h2-freeze"
Select-String -LiteralPath "$HR\h2-freeze.out.txt" -Pattern '^(pip|setuptools|wheel|tzdata)==' | ForEach-Object Line | Out-File "$HR\h2-tools.txt" -Encoding utf8
# H3 (Q7, C2): every task whose action names a venv, python or a .ps1 wrapper, with state and principal
Get-ScheduledTask | ForEach-Object { $st = $_; foreach ($act in $st.Actions) { [pscustomobject]@{
  Task=$st.TaskPath+$st.TaskName; State=[string]$st.State; Logon=[string]$st.Principal.LogonType; Execute=$act.Execute; Arguments=$act.Arguments } } } |
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

Pasting a block into the console is safe. **A block saved as a `.ps1` must be saved as UTF-8 with a
BOM** (`Set-Content -Encoding utf8` writes one in 5.1). Windows PowerShell 5.1 decodes a BOM-less
script as ANSI, so a non-ASCII character such as an em dash decodes into a smart quote that ends a
string early and breaks parsing (seen on the host, 2026-10-13).
`scripts\ops\check_markdown_powershell_fences.ps1` parses every block with the 5.1 parser and flags
the non-ASCII ones.

```powershell
$ErrorActionPreference = 'Stop'
$P       = '<production checkout>'                 # e.g. the WeatherSnapshotLoopSupervisor working directory
$Py      = Join-Path $P 'venv\Scripts\python.exe'
$R       = '<cutover record root, outside data\ and outside the checkout>'
$WH      = Join-Path $R 'wheelhouse'; $Tools = Join-Path $R 'tools'   # $Inst (installer) retired 2026-10-13
$A       = Join-Path $R 'receipts-3110'
$NewHome = '<new 3.11.9 home, e.g. C:\Program Files\Python311-cp3119>'   # under Program Files: Users get read/execute only
$NewPy   = Join-Path $NewHome 'python.exe'
$Stage   = '<stage worktree next to the checkout>'; $StagePy = Join-Path $Stage 'venv\Scripts\python.exe'
$Old     = Join-Path $P 'venv-cp3110'
$Log     = Join-Path $R 'night.log'
New-Item -ItemType Directory -Force $R, $Tools, $A | Out-Null
$K = if (Test-Path -LiteralPath (Join-Path $R 'constants.json')) { Get-Content -LiteralPath (Join-Path $R 'constants.json') -Raw | ConvertFrom-Json }   # §6a
if ($K) { foreach ($kk in 'nupkg_url','nupkg_size','nupkg_sha512_b64','tools_manifest_sha256','binary_signer_thumbprint','vv_prefix','binaries') { if (-not $K.$kk) { throw "constants.json lacks $kk" } } }
# Session globals that a later phase reads come from files, never from an earlier session (A1 writes oldhome.txt).
$OldHome = if (Test-Path -LiteralPath "$R\oldhome.txt") { (Get-Content -LiteralPath "$R\oldhome.txt" -TotalCount 1).Trim() }
function Log($m){ $l = "{0:o} {1}" -f (Get-Date), $m; Add-Content -LiteralPath $Log -Value $l -Encoding utf8; Write-Host $l }
# The lease lives in the session's global scope. While $global:ReleaseOnNoGo is set (B0-B1e, and C1 until the C4 rename),
# every NoGo releases it; after the C4 rename it stays held for §R.
$global:Lease = $null; $global:ReleaseOnNoGo = $false
function Release-Lease { if ($global:Lease) { Exit-WeatherHeavyWorkloadLease -Lease $global:Lease; $global:Lease = $null; Log 'lease released' } }
function NoGo($m){ Log "NO-GO: $m"; if ($global:ReleaseOnNoGo) { $global:ReleaseOnNoGo = $false; Release-Lease }; throw "NO-GO: $m" }
function Sha($f){ (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToUpper() }
# pip freeze records the production HEAD on the weather editable line, so it changes on every master merge (A' r2, 2026-10-14).
# Mask only that 40-hex sha, only on that exact line; every other line, and any other form of that line, is compared as is.
function Mask-Editable([string[]]$Lines) { foreach ($line in $Lines) {
  if ($line -cmatch '^-e git\+https://github\.com/michaelbooth1/weather\.git@[0-9a-f]{40}#egg=weather_market$') { $line -creplace '@[0-9a-f]{40}#', '@<HEAD>#' } else { $line } } }
# Native calls whose stderr matters go through Invoke-Native. Never use 2>&1 or 2> on a native command while
# $ErrorActionPreference is 'Stop': Windows PowerShell 5.1 turns each stderr line into a terminating error.
function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$OutBase) {
  $quoted = foreach ($a in $Arguments) { if ($a -match '[\s"]') { '"' + ($a -replace '"','\"') + '"' } else { $a } }
  $proc = Start-Process -FilePath $Exe -ArgumentList ($quoted -join ' ') -WorkingDirectory $P -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "$OutBase.out.txt" -RedirectStandardError "$OutBase.err.txt"
  $proc.WaitForExit(); if ($null -eq $proc.ExitCode) { NoGo "no exit code from $Exe" }
  Log ("native exit {0}: {1} {2}" -f $proc.ExitCode, (Split-Path -Leaf $Exe), ($Arguments -join ' ')); [int]$proc.ExitCode }
# Release readiness as parsed fields (release_lifecycle_cli prints JSON; a BLOCK goes to stderr with a non-zero exit)
function Get-ReleaseActive([string]$Exe, [string]$OutBase) {
  $code = Invoke-Native $Exe @('-m','weather.operations.release_lifecycle_cli','--repo-root',$P,'active') $OutBase
  # "$(...)" not [string](...): Get-Content -Raw of an empty file is $null and [string]$null stays $null in PS 5.1,
  # so the BLOCK case (empty stdout) threw at $o.Trim() (Phase B B3, 2026-10-16).
  $o = "$(Get-Content -LiteralPath "$OutBase.out.txt" -Raw)"; $e = "$(Get-Content -LiteralPath "$OutBase.err.txt" -Raw)"
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
# status.ps1 -Json exits 2 on ANY flag, and the host can carry standing flags that predate the night (2026-10-16: an
# overdue documentation transaction and two STALENESS_SWEEP CRITICAL rows). Never gate on its exit code; compare its
# flags with a baseline taken before the phase. Keys mask 64-hex hashes and numbers, so an ageing standing flag
# ("63 days" -> "64 days") keeps its key while a new kind of flag does not.
function Get-StatusFlagKeys([string]$OutBase) {
  $raw = "$(Get-Content -LiteralPath "$OutBase.out.txt" -Raw)"; if (-not $raw.Trim()) { NoGo "status.ps1 printed nothing ($OutBase)" }
  try { $j = $raw | ConvertFrom-Json } catch { NoGo "status.ps1 output is not JSON ($OutBase)" }
  if ($null -eq $j -or -not $j.PSObject.Properties['flags']) { NoGo "status.ps1 JSON has no flags field ($OutBase)" }
  @(@($j.flags) | ForEach-Object { ([string]$_ -replace '[0-9a-fA-F]{64}','<sha>') -replace '\d+(\.\d+)?','#' } | Sort-Object -Unique) }
function Save-StatusBaseline([string]$OutBase, [string]$Path) {
  $k = @(Get-StatusFlagKeys $OutBase); $k | Set-Content -LiteralPath $Path -Encoding utf8; Log "status baseline $Path ($($k.Count) flags)" }
function Get-NewStatusFlags([string]$OutBase, [string]$Baseline, [string]$Tag) {
  if (-not (Test-Path -LiteralPath $Baseline)) { NoGo "$Tag status baseline $Baseline is missing" }
  $base = @(Get-Content -LiteralPath $Baseline | Where-Object { $_ })
  $new = @(Get-StatusFlagKeys $OutBase | Where-Object { $base -notcontains $_ })
  $new | Set-Content -LiteralPath "$OutBase.new-flags.txt" -Encoding utf8
  Log "$Tag status: $($new.Count) new flag(s) vs $(Split-Path -Leaf $Baseline)"; $new }
. (Join-Path $P 'scripts\ops\workload_admission.ps1')
. (Join-Path $P 'scripts\ops\memory_guard_status_reader.ps1')
Log "session start host=$env:COMPUTERNAME head=$(git -C $P rev-parse HEAD)"
```

Trap reminders ([operations agent role](OPERATIONS_AGENT_ROLE.md) §5):
- there is no `&&`;
- use `-LiteralPath`;
- never append `2>$null` to native `git`;
- never run a recursive listing of `data\`;
- track and terminate every process you start;
- an agent session runs in Windows session 0, so any window it starts (an installer, a UAC prompt) is invisible. A step that needs the owner to click runs in the owner's own elevated window (seen on the host, 2026-10-13);
- a value one phase assigns is `$null` in the fresh session of a later night: read it from the file that phase wrote
  (the §6 header reads `oldhome.txt`), never from a variable set earlier (found in review 2026-10-13);
- PowerShell variable names ignore case, and `foreach` and `ForEach-Object` assign in the session scope: a loop variable `$k`, `$p`, `$a` or `$r` overwrites `$K`, `$P`, `$A` or `$R`. Never reuse a session constant's name for a loop variable (a `foreach ($k ...)` in C6 would have rolled back every cutover; found in review 2026-10-13);
- never follow `night.log` with a tailing reader (`Get-Content -Wait`, `tail -F`): it can hold the file so that `Log`'s `Add-Content` fails and stops the phase. Read snapshots instead (seen on the host, 2026-10-13).

Plain `& $exe ...; if ($LASTEXITCODE)` calls with no stderr redirection are safe under `Stop`.

`Enter-WeatherHeavyWorkloadLease` returns `$null` when the lease is busy and throws outside
00:30-09:00. Keep a whole phase in one PowerShell process, and release the lease on every exit path.
`NoGo` does that while `$global:ReleaseOnNoGo` is set. If any other command throws in a leased
step, run `Release-Lease` before you leave the session. The one exception is after the C4 rename,
where §R needs the lease.

### 6a. Constants file (prepared before Phase A, reviewed in the handoff)

`$R\constants.json` holds the published package and binary facts. It keeps them in one reviewed place,
not in prose. Source each value as stated:

| Key | Source |
| --- | --- |
| `nupkg_url` | `https://api.nuget.org/v3-flatcontainer/python/3.11.9/python.3.11.9.nupkg` (the `packageContent` of the nuget.org registration for `python` 3.11.9) |
| `nupkg_size`, `nupkg_sha512_b64` | `packageSize` and `packageHash` (SHA512, base64) of the nuget.org catalog entry for `python` 3.11.9 |
| `tools_manifest_sha256` | §6a-W0 on the workstation, from the same package after its SHA-512 check |
| `binary_signer_thumbprint` | PSF Authenticode thumbprint of `python.exe` in the workstation's installer-built 3.11.9 home |
| `installer_*`, `signer_*` | Retired with the 2026-10-13 revision (the installer is not run). Keep them for the record. |
| `vv_prefix` | `python -VV` of the workstation's 3.11.9 install, up to the first comma |
| `binaries` | SHA-256 of `python.exe`, `pythonw.exe`, `python311.dll`, `python3.dll`, `vcruntime140*.dll`, `Lib\venv\scripts\nt\python(w).exe`, `DLLs\_ssl.pyd`, `DLLs\libssl-3.dll`, `DLLs\libcrypto-3.dll` from the workstation's 3.11.9 home |

Workstation command for `binaries` and `vv_prefix`. It is read-only and runs on the workstation,
never the host:

```powershell
$WsHome = (& .\venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)").Trim()
$rel = 'python.exe','pythonw.exe','python311.dll','python3.dll','vcruntime140.dll','vcruntime140_1.dll',
       'Lib\venv\scripts\nt\python.exe','Lib\venv\scripts\nt\pythonw.exe','DLLs\_ssl.pyd','DLLs\libssl-3.dll','DLLs\libcrypto-3.dll'
$b = [ordered]@{}; foreach ($rp in $rel) { $b[$rp] = (Get-FileHash -LiteralPath (Join-Path $WsHome $rp) -Algorithm SHA256).Hash.ToUpper() }
[ordered]@{ vv_prefix = ((& (Join-Path $WsHome 'python.exe') -VV) -replace ',.*$',''); binaries = $b } | ConvertTo-Json
```

**6a-W0. NuGet manifest (workstation, read-only toward the host; needs the G12 download approval).**
It runs in an empty scratch folder on the workstation, never the host. It proves the package's
`binaries` equal the installer-built home, and pins the exact extracted tree for A4.

```powershell
$W = '<empty scratch folder>'; $Pkg = Join-Path $W 'python.3.11.9.nupkg'
curl.exe -fsSL --proto '=https' --tlsv1.2 -o $Pkg 'https://api.nuget.org/v3-flatcontainer/python/3.11.9/python.3.11.9.nupkg'
$want512 = -join ([Convert]::FromBase64String('<packageHash from the catalog entry>') | ForEach-Object { $_.ToString('X2') })
if ((Get-FileHash -LiteralPath $Pkg -Algorithm SHA512).Hash.ToUpper() -ne $want512) { throw 'nupkg sha512' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($Pkg, (Join-Path $W 'x')); $T = Join-Path $W 'x\tools'
if (Get-ChildItem -LiteralPath (Join-Path $W 'x') -Recurse | Where-Object Name -like '*%*') { throw 'encoded entry name' }
[string[]]$tree = Get-ChildItem -LiteralPath $T -Recurse -File | ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToUpper(), $_.FullName.Substring($T.Length) }
[Array]::Sort($tree, [StringComparer]::Ordinal)
$tree | Set-Content (Join-Path $W 'nuget-tools-sha256.txt') -Encoding utf8
-join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes(($tree -join "`n"))) | ForEach-Object { $_.ToString('X2') })   # tools_manifest_sha256
$WsHome = '<workstation installer-built 3.11.9 home>'; if ((& (Join-Path $WsHome 'python.exe') -VV) -notlike 'Python 3.11.9*') { throw 'ws home' }
$tree | ForEach-Object { $h, $rel = $_ -split '  ', 2; $o = Join-Path $WsHome $rel.TrimStart('\')
  if (-not (Test-Path -LiteralPath $o)) { "ONLY-NUGET $rel" } elseif ((Get-FileHash -LiteralPath $o -Algorithm SHA256).Hash.ToUpper() -ne $h) { "DIFF $rel" } }
$nset = [Collections.Generic.HashSet[string]]::new([string[]]($tree | ForEach-Object { ($_ -split '  ', 2)[1] }), [StringComparer]::OrdinalIgnoreCase)
$expected = '\\__pycache__\\|^\\(tcl|Tools\\scripts|Lib\\(site-packages|idlelib|tkinter|turtledemo|test|ctypes\\test|distutils\\tests|lib2to3\\tests|unittest\\test))\\|' +
            '^\\(NEWS\.txt|Lib\\turtle\.py|Scripts\\pip[0-9.]*\.exe|libs\\_tkinter\.lib|DLLs\\(tcl86t\.dll|tk86t\.dll|_tkinter\.pyd|pyc?d?\.ico|python_(lib|tools)\.cat))$'
Get-ChildItem -LiteralPath $WsHome -Recurse -File | ForEach-Object { $_.FullName.Substring($WsHome.TrimEnd('\').Length) } |
  Where-Object { -not $nset.Contains($_) } | ForEach-Object { if ($_ -match $expected) { "ONLY-INSTALLER $_" } else { "ONLY-INSTALLER-UNEXPECTED $_" } }
```

Go/no-go W0: every `binaries` path is present and not `DIFF`; any `DIFF` or `ONLY-NUGET` outside
`Lib\site-packages\*.dist-info\`, `__pycache__`, `libs\*.lib` and `DLLs\python.cat` is NO-GO (the
nuget.org SHA-512 has the same origin as the download, so this full-tree comparison against the
python.org-installer home is the independent check on every file A4 pins); no extracted name
contains `%`; any `ONLY-INSTALLER-UNEXPECTED` line is NO-GO (the reverse pass's `$expected` pattern is
the reviewed list of installer-only content). The two extra exemptions were added after the first W0 run (2026-10-13), which found
exactly two `DIFF`s (the `RECORD` files of `pip` and `setuptools`) and 22 `ONLY-NUGET` files: 21
link-time import libraries under `libs\` (the installer adds only `python3.lib`, `python311.lib` and
`_tkinter.lib`; no runtime path loads a `.lib`) and the package's PSF-signed `DLLs\python.cat`
(Authenticode `Valid`, `binary_signer_thumbprint`). The reverse pass's expected set is what the package omits: `tkinter`,
Tcl/Tk, `idlelib`, `turtle`, `test`, the `ctypes`, `distutils`, `lib2to3` and `unittest` test packages,
`turtledemo`, `Tools\scripts`, base `Scripts\pip*.exe`, icons, `NEWS.txt` and the installer's two
catalogs (`Lib\site-packages` is exempt because a workstation home holds its own installs); nothing under `src/`, `app/`, `tools/`, `scripts/` or
`tests/` imports them, venv `pip` comes from `ensurepip`, and the bounded suite in B2 is the proof.

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

`verify_wheels_vs_installed.py` (r2, 2026-10-16) checks each wheel's hashed `RECORD` rows against the
installed `RECORD` of the same distribution, ignoring `.pyc` rows. Every wheel row must be installed with
the same hash. The installed side may add only the rows pip writes at install time: the dist-info
`INSTALLER`, `REQUESTED` and `direct_url.json`, `../Scripts` launchers, and the wheel's own `.data/` files
installed under `../../<scheme>` with an identical hash. It prints `OK`, `DIFF` (with up to five
`WHEEL-ONLY` and `INSTALLED-ONLY` rows), `MISSING-INSTALLED` or `UNMATCHED-ALLOWED` per wheel. The host copy
is canonical: `sha256 FE9F7A574CF914E070AC9FD70C93C661D9DD2239AB9109B02E71263EE9DA668D` (2710 bytes, ASCII,
LF line endings, trailing LF). The text below is byte-identical to it, so a fresh copy must hash to that value:

```python
import csv, io, pathlib, re, sys, zipfile
# r2 (master-agent 2026-10-16 00:4x): r1 compared the two RECORD row sets symmetrically, so the rows pip itself
# writes at install time (dist-info INSTALLER / REQUESTED / direct_url.json, ../Scripts launchers, and the wheel's own
# .data/ files installed under ../../<scheme> with the same hash) failed every package (B NO-GO 00:30:42, 0 wheel rows actually differed). r2: every hashed wheel row must be in
# the installed RECORD with the same hash, and installed-only rows may only be those pip-written kinds.
wh, site = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
allow_unmatched = {a.lower() for a in sys.argv[3:]}
def rows(text):
    return {(p, h) for p, h, *_ in csv.reader(io.StringIO(text)) if h and ".data/" not in p and not p.endswith(".pyc")}
def data_rows(text):
    # wheel .data/<scheme>/<rel> rows install outside site-packages as ../../<scheme dir>/<rel>; keep (rel, hash)
    out = set()
    for p, h, *_ in csv.reader(io.StringIO(text)):
        if h and ".data/" in p:
            parts = p.split("/", 2)
            if len(parts) == 3: out.add((parts[2], h))
    return out
def pip_written(path, h, dist, wdata):
    if path in (f"{dist}/INSTALLER", f"{dist}/REQUESTED", f"{dist}/direct_url.json"):
        return True
    if path.startswith("../") and "/Scripts/" in path:
        return True
    # a .data/ file from this wheel, same bytes (hash), installed under its scheme directory
    return path.startswith("../") and any(path.endswith("/" + rel) and h == wh_ for rel, wh_ in wdata)
bad = 0
for whl in sorted(wh.glob("*.whl")):
    with zipfile.ZipFile(whl) as z:
        rec = next(n for n in z.namelist() if n.endswith(".dist-info/RECORD") and n.count("/") == 1)
        dist = rec.split("/")[0]
        rtext = z.read(rec).decode("utf-8"); wrows = rows(rtext); wdata = data_rows(rtext)
    inst = site / dist / "RECORD"
    name = re.split(r"-\d", dist, maxsplit=1)[0].lower().replace("_", "-")
    if not inst.exists():
        if name in allow_unmatched:
            print("UNMATCHED-ALLOWED", whl.name); continue
        print("MISSING-INSTALLED", whl.name); bad += 1; continue
    irows = rows(inst.read_text("utf-8"))
    missing = wrows - irows
    extra = {r for r in irows - wrows if not pip_written(r[0], r[1], dist, wdata)}
    if not missing and not extra:
        print("OK " + whl.name)
    else:
        print(f"DIFF {whl.name} (wheel rows not installed: {len(missing)}; unexpected installed rows: {len(extra)})")
        for p, h in sorted(missing)[:5]: print("  WHEEL-ONLY", p, h)
        for p, h in sorted(extra)[:5]: print("  INSTALLED-ONLY", p, h)
    bad += bool(missing or extra)
sys.exit(1 if bad else 0)
```

## 7. Phases

| Phase | Night | Window | Lease | Capture effect |
| --- | --- | --- | --- | --- |
| §4 host reads | before sign-off | 00:30-09:00, serial | no | none |
| §T tzdata (if Q13 = earlier night) | an earlier night | 00:30-04:45 | yes | none until the next worker restart |
| A install side by side | an owner-named morning after sign-off | 00:30-09:00, elevated operator session (no owner click since 2026-10-13) | no | none |
| B wheelhouse, stage venv, bounded suite | a prep night after A; G5 and G7 hold | B0 by 02:00, suite start by 03:00, finished by 04:45 | yes (released before B2) | none |
| C cutover | the signed night (G7, G8, G11) | 00:30-02:25; rollback starts by 02:45 | yes | about 20-35 min gap |
| §D cleanup | a later night | 00:30-04:45 | no | none |

Phase B must finish before the 04:45-06:45 tiering reserve and the 06:50 jobs (91a, exchange
economics). The bounded suite's own limit (`MaxRuntimeSeconds`, `bounded_worktree_test_suite.ps1:27`)
is why the suite starts no later than 03:00. Using the tiering hole (HOST_LOAD_POLICY rule 10) to run
later needs at least 100 GiB free and skips tiering that night; that is an owner choice, not a
default.

### 7a. Phase calendar (owner-confirmed 2026-10-12; Phase A done 2026-10-14)

The owner confirmed this calendar on 2026-10-12, including the fallbacks, and named the cutover
night 00:30 on 10-17 (owner reachable 00:30-03:45, G4), accepting the short gap inside the 88a
desk-study panel window (DECISION_LOG 2026-10-12). Today's position lives in
[the state of play](STATE_OF_PLAY.md). A night is named by its
morning: "00:30 on 10-16" is the night of 10-15 to 10-16.

| Phase | Primary | Fallback | Reason |
| --- | --- | --- | --- |
| A install (elevated operator session; no owner click since 2026-10-13) | **done**: P0-A2 10-13 08:54-08:57 (A4 NO-GO on the installer route); A' (A3 + A4, NuGet route) **PASS 10-14 05:23** after N9 handed back | none needed | It ran before §T, so §T ends with T-R. |
| §T tzdata + T-R | 00:30-02:00 on Thu 10-15 | 00:30 on Fri 10-16 | First admitted night after N9 (00:30 on 10-14). |
| B prep night | 00:30-04:45 on Fri 10-16 | 00:30 on Sat 10-17 | After A and after §T's T-R (B builds its lock from the refreshed freeze). |
| C cutover | 00:30-02:25 on Sat 10-17 (owner-named; did not run). **Now 00:30-02:25 on Thu 10-22** (owner 2026-10-20 ~16:4x EDT, verbatim "Keep Python 10-21/22 (Recommended)", relayed by master-agent), before N12 | the next night inside 10-15..10-30 that meets G4 and G5, named by the owner (G0) | The night after B, so the qualified tip has little time to move (G3); after the freeze (G8). If B uses its fallback (10-17), C moves too. |
| Latest second attempt | 00:30 on Thu 10-29 | none | Keeps 10-30 and 10-31 spare; never 11-01 (G11). |
| §D cleanup | first admitted night after a C PASS that has no other lease user | any later night | Removes the stage worktree; not urgent. |

Re-check every row against the night plan of the day. A later quiet-window merge night (including
the held 88a heads) that collides with a row moves the phase to its fallback (G5). G0 (the night is
named), G4 (the owner reachable 00:30-03:45) and G7 (not the night before or the night of a
scheduled LFC session) are checked again before each Phase B and Phase C night.

### §T. tzdata 2026.3 on the current 3.11.0 venv (if Q13 chooses an earlier night)

This is light pip work under the lease, with the workers left running.
- **Precondition:** `$Tools\pypi_hash_lock.py` exists, copied verbatim from §6b. No step creates it (§6 makes only
  the folder), so on a §T night that runs before Phase B, copy it in after the §6 session header and before the block
  below (the 10-15 §T run found it missing).
- **Not a code roll.** The source fingerprint excludes the venv (`runtime_identity.py` lines 19-28 and
  141-145), so installing tzdata cannot trigger `STALE_CODE`.
- **Capture does read tzdata.** On Windows, `ZoneInfo("America/Toronto")` (`model_constants.py:13`,
  `runtime_monitor.py:39`) loads it from the `tzdata` package. Running workers keep the zone data they
  already loaded. The new data takes effect at each worker's next restart, which is at the latest the
  cutover itself.

```powershell
$global:Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py_tzdata_2026_3'; if (-not $global:Lease) { NoGo 'lease busy' }
try {
  & $Py -m pip freeze --all | Out-File "$R\freeze-before-tzdata.txt" -Encoding utf8
  'tzdata==2026.3' | Set-Content "$R\lock-tz.txt" -Encoding ascii
  & $Py -I "$Tools\pypi_hash_lock.py" "$R\lock-tz.txt" "$R\lock-tz-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tzdata hash' }
  & $Py -m pip download --isolated --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r "$R\lock-tz-hashed.txt" -d "$R\tzdata"; if ($LASTEXITCODE) { NoGo 'tzdata download' }
  & $Py -m pip install --isolated --no-index --no-deps --require-hashes --find-links "$R\tzdata" -r "$R\lock-tz-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tzdata install' }
  & $Py -m pip freeze --all | Out-File "$R\freeze-after-tzdata.txt" -Encoding utf8
  $d = Compare-Object (Mask-Editable (Get-Content "$R\freeze-before-tzdata.txt")) (Mask-Editable (Get-Content "$R\freeze-after-tzdata.txt")); $d | Out-File "$R\freeze-diff-tzdata.txt"
  if ($d | Where-Object { $_.InputObject -notmatch '^tzdata==' }) { NoGo 'a line other than tzdata changed - roll back tzdata and inspect' }
  if (-not ($d | Where-Object { $_.SideIndicator -eq '=>' -and $_.InputObject -eq 'tzdata==2026.3' })) { NoGo 'tzdata==2026.3 not in the after-freeze' }
} finally { Release-Lease }
```

Rollback: reinstall the previous version from the before-freeze, or `pip uninstall tzdata` if it was
absent.

**T-R. Refresh the A1 venv receipts (only if Phase A ran before §T).** The old-home hashes are
unaffected, because tzdata lives in the venv. B builds its lock from `freeze-3110.txt`, and C1
compares against it, so this step must pass before Phase B.

```powershell
foreach ($f in 'freeze-3110.txt','pth-3110.txt','rtv-3110.json') { Copy-Item -LiteralPath "$A\$f" "$A\$f.pre-tzdata" }
& $Py -m pip freeze --all | Set-Content "$A\freeze-3110.txt" -Encoding utf8
Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" } |
  Set-Content "$A\pth-3110.txt" -Encoding utf8
Push-Location -LiteralPath $P
& $Py -c "import json; from weather.release_artifacts import capture_runtime_versions as c; print(json.dumps(c(), indent=1, sort_keys=True))" | Set-Content "$A\rtv-3110.json" -Encoding utf8
Pop-Location
if (-not (Select-String -LiteralPath "$A\freeze-3110.txt" -Pattern '^tzdata==2026\.3$' -Quiet)) { NoGo 'T-R: freeze-3110 lacks tzdata==2026.3' }
$d = Compare-Object (Mask-Editable (Get-Content "$A\freeze-3110.txt.pre-tzdata")) (Mask-Editable (Get-Content "$A\freeze-3110.txt"))
if ($d | Where-Object { $_.InputObject -notmatch '^tzdata==' }) { NoGo 'T-R: a line other than tzdata changed since Phase A' }
Log 'T-R PASS'
```

### Phase A. Install side by side (owner-attended; no capture change; no lease)

**A1. Receipts.** If §T has already run, take them after it. If Phase A runs first (the §7a
calendar), §T ends with T-R, which re-takes the venv receipts.

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
| every registered capture-family task `WeatherMakerEvidence<Family>` (N12: `WeatherMakerEvidenceLowestTemperature`; Q12b) |
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

**A3. Download and verify the NuGet package on the host (approved download, G12).**

```powershell
if (-not $K) { NoGo 'constants.json is missing' }
$Nup = Join-Path $R 'nuget'
if (Test-Path -LiteralPath $Nup) { NoGo 'nuget dir exists; inspect first' }
New-Item -ItemType Directory $Nup | Out-Null
$Pkg = Join-Path $Nup 'python.3.11.9.nupkg'
curl.exe -fsSL --proto '=https' --tlsv1.2 -o $Pkg $K.nupkg_url; if ($LASTEXITCODE) { NoGo "curl $LASTEXITCODE" }
$len = (Get-Item -LiteralPath $Pkg).Length
$want512 = -join ([Convert]::FromBase64String($K.nupkg_sha512_b64) | ForEach-Object { $_.ToString('X2') })
$have512 = (Get-FileHash -LiteralPath $Pkg -Algorithm SHA512).Hash.ToUpper()
Log "nupkg len=$len sha512=$have512 sha256=$(Sha $Pkg)"
if ($len -ne [int64]$K.nupkg_size) { NoGo 'nupkg size' }
if ($have512 -ne $want512) { NoGo 'nupkg sha512' }
```

**A4. Copy the package's `tools` tree into the new home (elevated operator session; no installer).**
Nothing is registered: no PEP 514 key, no uninstall entry, no launcher, no PATH change. The copy
takes the ACL of the destination (`robocopy /COPY:DAT` copies no security), so under Program Files
ordinary users get read and execute only; a home directly under `C:\` would inherit Modify for
Authenticated Users, which A4 refuses.

```powershell
if (Test-Path -LiteralPath $NewHome) { NoGo 'new home exists; inspect first' }
function Get-PyCoreKeys { @(foreach ($k in 'HKCU:\Software\Python\PythonCore','HKLM:\SOFTWARE\Python\PythonCore','HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore') {
  Get-ChildItem -LiteralPath $k -ErrorAction SilentlyContinue | ForEach-Object Name }) -join '|' }
$before = @{ M=[Environment]::GetEnvironmentVariable('Path','Machine'); U=[Environment]::GetEnvironmentVariable('Path','User'); Reg=(Get-PyCoreKeys) }
$X = Join-Path $Nup 'x'
if (Test-Path -LiteralPath $X) { Remove-Item -LiteralPath $X -Recurse -Force; Log 'removed a partial extraction from an earlier A4 run' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($Pkg, $X)
$T = Join-Path $X 'tools'
if (Get-ChildItem -LiteralPath $T -Filter '*._pth' -File) { NoGo 'a ._pth file is present' }
function Get-Tree([string]$Root) { $n = $Root.TrimEnd('\').Length
  [string[]]$a = Get-ChildItem -LiteralPath $Root -Recurse -File | ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.FullName.Substring($n) }
  [Array]::Sort($a, [StringComparer]::Ordinal); ,$a }
$tree = Get-Tree $T; $tree | Set-Content "$R\nuget-tools-sha256.txt" -Encoding utf8
$treeSha = -join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes(($tree -join "`n"))) | ForEach-Object { $_.ToString('X2') })
Log "nuget tools files=$($tree.Count) manifest=$treeSha"
if ($treeSha -ne $K.tools_manifest_sha256.ToUpper()) { NoGo 'nuget tools tree differs from the reviewed manifest' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $NewHome) -PathType Container)) { NoGo 'the parent of the new home must already exist (C:\Program Files)' }
function Get-WeakAce([string]$Dir) { @((Get-Acl -LiteralPath $Dir).Access | Where-Object { $_.AccessControlType -eq 'Allow' -and
  [string]$_.IdentityReference -match '(^|\\)(Users|Authenticated Users|Everyone|INTERACTIVE)$' -and ([int]$_.FileSystemRights -band 0x500D0156) }) }
if ((Get-WeakAce (Split-Path -Parent $NewHome)).Count) { NoGo 'the parent of the new home grants ordinary users write access' }
robocopy $T $NewHome /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NP /LOG:"$R\robocopy-newhome.log"
if ($LASTEXITCODE -ge 8) { NoGo "robocopy exit $LASTEXITCODE" }
if (Compare-Object -CaseSensitive $tree (Get-Tree $NewHome)) { NoGo 'new home differs from the verified tree' }
$weak = Get-WeakAce $NewHome
if ($weak.Count) { NoGo "new home is writable by $($weak.IdentityReference -join ', ')" }
foreach ($f in 'python.exe','pythonw.exe','python311.dll','Lib\venv\scripts\nt\python.exe','Lib\venv\scripts\nt\pythonw.exe') {
  $s = Get-AuthenticodeSignature -LiteralPath (Join-Path $NewHome $f)
  if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Thumbprint -ne $K.binary_signer_thumbprint) { NoGo "authenticode $f" } }
foreach ($bp in $K.binaries.PSObject.Properties) { if ((Sha (Join-Path $NewHome $bp.Name)) -ne $bp.Value) { NoGo "binary $($bp.Name)" } }
if ((& $NewPy -VV) -notlike "$($K.vv_prefix)*") { NoGo 'new -VV' }
$now = Get-ChildItem -LiteralPath $OldHome -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\' } | ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.FullName.Substring($OldHome.Length) }
if (Compare-Object (Get-Content "$A\oldhome-sha256.txt") $now) { NoGo 'OLD HOME CHANGED' }
if ((& $Py -VV) -notlike 'Python 3.11.0*') { NoGo 'prod venv no longer 3.11.0' }
if ([Environment]::GetEnvironmentVariable('Path','Machine') -ne $before.M -or [Environment]::GetEnvironmentVariable('Path','User') -ne $before.U) { NoGo 'PATH changed' }
if ((Get-PyCoreKeys) -ne $before.Reg) { NoGo 'PEP 514 registrations changed' }
$null = Invoke-Native $NewPy @('-I','-c','import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version); print(zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)') "$R\native-3119"
$Smoke = Join-Path $Nup 'venv-smoke'
& $NewPy -I -m venv $Smoke; if ($LASTEXITCODE) { NoGo 'smoke venv' }
foreach ($ln in 'python.exe','pythonw.exe') { if ((Sha (Join-Path $Smoke "Scripts\$ln")) -ne $K.binaries."Lib\venv\scripts\nt\$ln") { NoGo "smoke launcher $ln" } }
& (Join-Path $Smoke 'Scripts\python.exe') -I -m pip --version | Set-Content "$R\smoke-pip.txt" -Encoding utf8; if ($LASTEXITCODE) { NoGo 'smoke pip' }
Remove-Item -LiteralPath $Smoke, $X -Recurse -Force
Log 'PHASE A PASS'
```

The smoke venv proves B1c and C5 will work from this home: the venv launchers are present and
equal the pinned ones, and `ensurepip` installs its bundled pip. B1a and B1b run `$NewPy -m pip`
from the home's own `site-packages` (the package ships pip there, as the installer does).

If A4 fails:
- nothing was installed or registered: delete `$NewHome` if it exists, and keep `$Nup` and the log. A4 can then be
  re-run on its own (it clears `$Nup\x` and re-checks the extracted tree against `tools_manifest_sha256`); do not re-run A3,
  which refuses an existing `$Nup`;
- if `OLD HOME CHANGED` fired, restore the old home from the freeze copy and check capture with the next `status.ps1` run;
- do not continue to Phase B.

### Phase B. Wheelhouse, stage venv, qualification (prep night; capture keeps running on 3.11.0)

**B0. Admission (00:30-02:00; G5 and G7 hold).**

```powershell
$h = (Get-Date).Hour + (Get-Date).Minute/60; if ($h -lt 0.5 -or $h -ge 2.0) { NoGo 'outside the Phase B start window' }
foreach ($tn in 'WeatherTrainingWindow','WeatherEveningEvidenceRefresh') { $x = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
  if ($x -and [string]$x.State -ne 'Disabled') { NoGo "$tn is enabled (G5)" } }
Assert-NoU6At0035 'B0'
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 55GB) { NoGo 'disk below the bounded-suite floor plus margin' }
$null = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$R\b0-status"
Save-StatusBaseline "$R\b0-status" "$R\b0-status-flags.txt"   # standing flags; any later Phase B status check uses Get-NewStatusFlags against it
$global:Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_prep'; if (-not $global:Lease) { NoGo 'lease busy' }
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

**B1d. Test-Venv (reused in C6).** `rtv.json` records each direct dependency's *declared* string from
`pyproject.toml` as well as its installed version (`capture_runtime_versions`, `release_artifacts.py`). So if a
`pyproject.toml` pin changes on master after `$A\rtv-3110.json` was taken, re-take that receipt from the merged
production checkout before B1d, keeping the old one beside it (the T-R `rtv` line). The 2026-10-15 `python-dotenv`
1.2.3 to 1.2.2 pin was such a change. Otherwise the stage compare stops with `direct dependencies moved`.

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
    # Without -I (as the workers run): the stdlib comes from the new home and no sys.path entry reaches the
    # 3.11.0 home, whose PEP 514 PythonPath key shares sys.winver 3.11.
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
qualification record. Bind the suite's Git executable explicitly. Without the binding the suite resolves `git.exe`
from PATH and refuses when it finds more than one, which is the case on the capture host: User PATH `Git\bin` and
Machine PATH `Git\cmd` (Fable review of the Phase B wrapper, 2026-10-15). Use the reviewed binding the night
sequencers pass: its path, SHA-256 and file version, read on the host with `Get-FileHash` and
`(Get-Item).VersionInfo.FileVersion`.

```powershell
if ((Get-Date) -gt (Get-Date).Date.AddHours(3)) { NoGo 'past the 03:00 suite start limit' }
$SuiteLog = Join-Path $R ('bounded-suite-' + (Get-Date -Format yyyyMMdd) + '.log')
$suite = Join-Path $P 'scripts\ops\bounded_worktree_test_suite.ps1'
$GitExe = '<reviewed git.exe, e.g. C:\Program Files\Git\cmd\git.exe>'; $GitSha = '<its SHA-256>'; $GitVer = '<its file version, e.g. 2.45.2.windows.1>'
if ((Sha $GitExe) -ne $GitSha.ToUpper() -or (Get-Item -LiteralPath $GitExe).VersionInfo.FileVersion -ne $GitVer) { NoGo 'B2 git binding does not match the host git.exe' }
$SuiteExit = 99
try {
  powershell -NoProfile -ExecutionPolicy Bypass -File $suite -RepoRoot $P -WorktreeRoot $Stage -ExpectedTip $Tip -BranchRef $QBranch `
    -LogPath "$SuiteLog.preflight" -PreflightOnly -InterpreterPath $StagePy -ExpectedInterpreterVersion '3.11.9' `
    -GitExecutablePath $GitExe -ExpectedGitExecutableSha256 $GitSha -ExpectedGitExecutableFileVersion $GitVer
  if ($LASTEXITCODE -eq 0) {
    powershell -NoProfile -ExecutionPolicy Bypass -File $suite -RepoRoot $P -WorktreeRoot $Stage -ExpectedTip $Tip -BranchRef $QBranch `
      -LogPath $SuiteLog -InterpreterPath $StagePy -ExpectedInterpreterVersion '3.11.9' `
      -GitExecutablePath $GitExe -ExpectedGitExecutableSha256 $GitSha -ExpectedGitExecutableFileVersion $GitVer
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
- its `selected_git=` and `expected_git_*` values name `$GitExe`, `$GitSha` and `$GitVer`;
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

**B-R. Requalify on a moved tip (only when G3 fails; added 2026-10-19; parked: used only if C fails and N12 lands first).** A qualification binds the tip it
tested. When HEAD has since moved by a roll-sensitive change (G3), run B-R on an admitted night **before**
the cutover night, under the Phase B rules (B0 window, G5, G7, suite start by 03:00); never on the cutover night.
It reuses the wheelhouse and the A1 receipts, so it downloads nothing:
1. archive the old record, and set `$Stage` to a **new** path (B1c refuses an existing one). The old stage and its
   `py3119-qual-*` branch stay until §D, which removes every qualification worktree;
2. run B0;
3. run the block below, which proves the wheelhouse and the 3.11.0 freeze are unchanged since Phase B. If it
   stops, run the full Phase B from B1a instead;
4. run B1c, B1d (re-take `rtv-3110.json` first only if a `pyproject.toml` pin changed), B1e, B2 (re-read the git
   binding on the host) and B3 as written. The new `qualification.json` then names the new tip. A night wrapper
   should replace `qualification.json` only on PASS, so that a failed B-R leaves the old tip and G3 stops C.

```powershell
$old = Get-Content -LiteralPath "$R\qualification.json" -Raw | ConvertFrom-Json
Copy-Item -LiteralPath "$R\qualification.json" ("$R\qualification-" + ([string]$old.tip).Substring(0,12) + '.json')
# after B0:
$wh = Get-ChildItem -LiteralPath $WH -File | ForEach-Object { '{0}  {1}' -f (Sha $_.FullName), $_.Name }
if (Compare-Object (Get-Content -LiteralPath "$R\wheelhouse-sha256.txt") $wh) { NoGo 'B-R: wheelhouse changed since Phase B - run the full Phase B' }
$fz = Join-Path $R ('freeze-3110-br-' + (Get-Date -Format yyyyMMdd) + '.txt'); & $Py -m pip freeze --all | Set-Content -LiteralPath $fz -Encoding utf8
if (Compare-Object (Mask-Editable (Get-Content -LiteralPath "$A\freeze-3110.txt")) (Mask-Editable (Get-Content -LiteralPath $fz))) { NoGo 'B-R: prod venv changed since Phase B - run the full Phase B' }
Log 'B-R inputs unchanged; continue at B1c'
```

### Phase C. Cutover night

| Clock (local) | Step | Hard stop |
| --- | --- | --- |
| 00:30-00:55 | C0 GO checks | Any fail = NO-GO, nothing touched |
| 01:00, latest 01:15 | C1 lease and receipts | No lease by 01:15 = NO-GO |
| +5 min | C2 quiesce the auxiliary tasks and long-running holders | Any throw = `Undo-Aux`, NO-GO |
| +5-10 min | C3 stop the capture workers | Still active after 600 s = undo, restore, NO-GO |
| by 01:30 | C4 rename `venv` to `venv-cp3110` | Rename fails 3 times or it is past 01:30 = undo, restore, NO-GO |
| +3 min | C5 build the new `venv` offline | Fail = §R |
| +2 min | C6 quick verify | Fail = §R |
| +5-32 min | C7 S4U restore of the three capture workers only | Not 3/3 after one rerun = §R |
| +5 min | C8 core verify | Fail = §R |
| by 02:15; aux by 02:25 | C9 core PASS decision; C9b restore the aux tasks; C9c aux verify | Core not passed = §R; aux failure per C9c |
| start by 02:45, done by 03:45 | §R rollback (worst case about 50 min) | Not 3/3 by 03:45: the 04:15 restore is the net; record and message the owner (§R, "Escalation") |

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
$GapChoice = Get-GapChoice; Log "gap-overrun choice: $GapChoice"
Assert-NoU6At0035 'C0'     # enforced here, not left to the C0 next-runs exemption of the aux list
$Head = (git -C $P rev-parse HEAD).Trim()
if ($Head -ne $q.tip) { Log "HEAD moved from the qualified tip; G3 needs roll_verdict.ps1 -Branch $Head -Base $($q.tip) exit 0 (ROLL-FREE) attached before GO, else B-R" }
# Q12b: a capture-family task (N12) holds the venv like the 88a worker; it must be quiesced at C2 under a recorded choice
$FamilyTasks = @(Get-ScheduledTask -TaskName 'WeatherMakerEvidence*' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ne 'WeatherMakerEvidenceCapture' } | ForEach-Object { $_.TaskName })
Log "capture-family tasks: $($FamilyTasks -join ',')"
if ($FamilyTasks.Count) {
  if (-not (Test-Path -LiteralPath "$R\q12b.txt") -or ((Get-Content -LiteralPath "$R\q12b.txt" -TotalCount 1) -split '\s+')[0] -ne 'STOP_AUTHORIZED') { NoGo 'a capture-family task is registered but Q12b is not STOP_AUTHORIZED' }
  $auxNames = @(Get-Content -LiteralPath "$R\aux-tasks.txt" | ForEach-Object { $_.Trim() })
  foreach ($ft in $FamilyTasks) { if ($auxNames -notcontains $ft) { NoGo "$ft is not in aux-tasks.txt (A1 review)" } } }
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'prod tree dirty' }
if (Test-Path -LiteralPath $Old) { NoGo "$Old exists" }
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 10GB) { NoGo 'disk' }
foreach ($tn in 'WeatherTrainingWindow','WeatherEveningEvidenceRefresh') { $x = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
  if ($x -and [string]$x.State -ne 'Disabled') { NoGo "$tn is enabled (G5)" } }
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
Log "lease state $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P) | ConvertTo-Json -Compress)"
$st0 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$R\c0-status"
Save-StatusBaseline "$R\c0-status" "$R\c0-status-flags.txt"   # exit $st0 is 2 whenever any standing flag exists; not a gate
$ra0 = Get-ReleaseActive $Py "$R\c0-release-active"; Assert-CaseA $ra0 'C0'
$Exempt = @('WeatherMemoryCommitGuard','WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor','WeatherTrainingWindowRestore') +
          @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })
Get-ScheduledTask | Where-Object { [string]$_.State -ne 'Disabled' -and $Exempt -notcontains $_.TaskName } | ForEach-Object { $i = Get-ScheduledTaskInfo $_
  if ($i.NextRunTime -and $i.NextRunTime -lt (Get-Date).Date.AddHours(4)) { "$($_.TaskName) next=$($i.NextRunTime)" } } | Tee-Object -FilePath "$R\c0-next-runs.txt"
Log "C0 complete (status.ps1 exit $st0) - awaiting owner GO"
```

**Go/no-go C0:**
- `c0-status.out.txt` shows capture healthy (3/3), with no FLAG the owner has not accepted. The flags in
  `c0-status-flags.txt` are the accepted baseline for C8 and C9c; `status.ps1` exit 2 alone is not a NO-GO;
- the release is case A (already asserted);
- `c0-next-runs.txt` is empty. The exempt tasks are the memory guard, the three supervisors, the 04:15 restore, and the aux tasks that C2 disables. Any other task due before 04:00 goes to the owner;
- G3, G5, G7, G8 and G11 hold; with a capture-family task registered, Q12b is recorded (asserted above);
- the owner types GO.

**C1. Lease and fresh receipts.**

```powershell
$global:Lease = $null; $deadline = (Get-Date).Date.AddHours(1).AddMinutes(15)
while (-not $global:Lease) { $global:Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_cutover'
  if (-not $global:Lease) { if ((Get-Date) -gt $deadline) { NoGo 'no lease by 01:15' }; Start-Sleep -Seconds 30 } }
$global:ReleaseOnNoGo = $true     # until the C4 rename, any NoGo releases the lease; after it, §R needs the lease
$N = Join-Path $R ('night-' + (Get-Date -Format yyyyMMdd)); New-Item -ItemType Directory -Force $N | Out-Null
& $Py -m pip freeze --all | Set-Content "$N\freeze-3110-tonight.txt"
if (Compare-Object (Mask-Editable (Get-Content "$A\freeze-3110.txt")) (Mask-Editable (Get-Content "$N\freeze-3110-tonight.txt"))) { NoGo 'prod venv changed since Phase B - requalify (full Phase B on another night)' }
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
$Holders = @('WeatherExecutionTapeSupervisor','WeatherMakerShadowRunner','WeatherMakerEvidenceCapture') + $FamilyTasks   # $FamilyTasks from C0
function Undo-Aux { foreach ($row in Import-Csv "$N\aux-prestate.csv") { if ($row.State -ne 'Disabled') { Enable-ScheduledTask -TaskName $row.Task | Out-Null } }
  if ($ShadowStop) { Remove-Item -LiteralPath $ShadowStop -ErrorAction SilentlyContinue } }
function Start-AuxHolders {   # restart the long-running holders that C2 stopped, only where their pre-state was enabled
  foreach ($tn in $Holders) { $row = Import-Csv "$N\aux-prestate.csv" -ErrorAction SilentlyContinue | Where-Object Task -eq $tn
    if ($row -and $row.State -ne 'Disabled') { Start-ScheduledTask -TaskName $tn; Log "started $tn" } } }
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
  foreach ($tn in $Aux) { Invoke-QStep "disable $tn" { Disable-ScheduledTask -TaskName $tn | Out-Null
    if ([string](Get-ScheduledTask -TaskName $tn).State -ne 'Disabled') { NoGo "disable $tn" } } $Soft.IsPresent }
  Invoke-QStep 'tape' { Stop-Tape $Exe } $Soft.IsPresent
  Invoke-QStep '88a' {   # only with the recorded owner choice (G8, Q12)
    if (((Get-Content -LiteralPath "$R\q12.txt" -TotalCount 1) -split '\s+')[0] -ne 'STOP_AUTHORIZED') { NoGo 'Q12 not STOP_AUTHORIZED' }
    if ([string](Get-ScheduledTask -TaskName WeatherMakerEvidenceCapture).State -eq 'Running') { Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture; Log '88a worker stopped (Q12)' }
    foreach ($ft in $FamilyTasks) {   # Q12b, asserted at C0; disabled above, so its one-minute trigger cannot restart it
      if ([string](Get-ScheduledTask -TaskName $ft).State -eq 'Running') { Stop-ScheduledTask -TaskName $ft; Log "$ft worker stopped (Q12b)" } } } $Soft.IsPresent
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
# $Exe is one interpreter for everything (C3), or a hashtable with keys snapshot, clob, obs and gate (§R, per worker).
function Stop-Capture($Exe, [switch]$Soft) {
  $X = if ($Exe -is [hashtable]) { $Exe } else { @{ snapshot=$Exe; clob=$Exe; obs=$Exe; gate=$Exe } }
  foreach ($tn in $Sup) { Invoke-QStep "disable $tn" { Disable-ScheduledTask -TaskName $tn | Out-Null
    if ([string](Get-ScheduledTask -TaskName $tn).State -ne 'Disabled') { NoGo "disable $tn" } } $Soft.IsPresent }
  $stamp = Get-Date -Format HHmmss; $script:c1 = $script:c2 = $script:c3 = 99
  Invoke-QStep 'stop snapshot' { $script:c1 = Invoke-Native $X.snapshot @('-m','weather.collection.snapshot_tracker','--stop') "$N\stop-snapshot-$stamp" } $Soft.IsPresent
  Invoke-QStep 'stop clob'     { $script:c2 = Invoke-Native $X.clob @('-m','weather.market.market_microstructure','stop') "$N\stop-clob-$stamp" } $Soft.IsPresent
  Invoke-QStep 'stop obs'      { $script:c3 = Invoke-Native $X.obs @('-m','weather.operations.observation_trigger','stop') "$N\stop-obs-$stamp" } $Soft.IsPresent
  $c1 = $script:c1; $c2 = $script:c2; $c3 = $script:c3
  if ($c1 -or $c2 -or $c3) { Log "stop verb exits $c1/$c2/$c3"; if (-not $Soft) { return $false } }
  $t0 = Get-Date
  while (((Get-Date)-$t0).TotalSeconds -lt 600) {
    $g = Invoke-Native $X.gate @('-m','weather.operations.capture_resource_gate','--workload','py3119_cutover_stop_confirmation','--capture-mode','no_live_capture',
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
  foreach ($tn in $Sup) { Invoke-QStep "enable $tn" { Enable-ScheduledTask -TaskName $tn | Out-Null } $true }
  $ok = Wait-Restore (Get-Date); Invoke-QStep 'undo aux' { Undo-Aux; Start-AuxHolders } $true
  if ($ok) { Log 'undo: capture 3/3, aux tasks restored' } else { Log 'ESCALATE: undo restore did not report capture_recovery_pass' } }
```

C3 and C4 run as one guarded block (below, after C4's functions). Any failure before the rename,
whether a `NoGo` or any other throw, runs `Undo-Stop` and then releases the lease.

In no-live-capture mode, one gate call checks all three loops, as `Wait-CaptureStopped` does
(`training_window.ps1:238-252`). `--workload` is only a label.

**C4. Sweep and rename (deadline 01:30).**

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
# C3 + C4 guarded block. NoGo must not release the lease before the undo has run, so the catch releases it itself.
$global:ReleaseOnNoGo = $false
try {
  if (-not (Stop-Capture $Py)) { NoGo 'C3 stop not confirmed' }
  $GapStart = Get-Date; Log 'C3 capture stopped'
  if ((Get-Date) -gt (Get-Date).Date.AddHours(1).AddMinutes(30)) { NoGo 'swap deadline 01:30 passed' }
  if (-not (Rename-WithSweep (Join-Path $P 'venv') 'venv-cp3110' 'c4')) { NoGo 'C4 rename failed' }
} catch {
  $msg = $_.Exception.Message; Log "C3/C4 failed before the rename: $msg - undo, no swap"
  try { Undo-Stop } finally { Release-Lease }
  throw }
Log 'C4 renamed'                  # from here on a failure means §R, which keeps the lease
```

C4 never kills a holder. An unknown holder means NO-GO with no swap. The holder file goes to the
owner.

**C5. Build the new venv offline.** From here on, any failure means §R. The C session is fresh: before
C5, define `Build-Venv` (B1c) and `Test-Venv` (B1d) in it by pasting those two function definitions
only, not the B1c and B1d calls. Both read only §6 header values (`$R`, `$WH`, `$A`, `$K`, `$NewHome`,
`$OldHome`).

```powershell
& $NewPy -I -m venv (Join-Path $P 'venv'); if ($LASTEXITCODE) { NoGo 'venv create -> ROLLBACK' }
Build-Venv $Py $P
```

**C6. Quick verify.**

```powershell
Test-Venv $Py $P 'prod'      # includes the import-location check: weather and maker_core must import from $P\src
foreach ($ln in 'python.exe','pythonw.exe') { if ((Sha (Join-Path $P "venv\Scripts\$ln")) -ne $K.binaries."Lib\venv\scripts\nt\$ln") { NoGo "launcher $ln -> ROLLBACK" } }
Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" } |
  Set-Content "$N\pth-3119.txt" -Encoding utf8     # receipt only; the import-location check is the pass rule
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'tree dirty -> ROLLBACK' }
```

**C7. Restore the capture workers through the S4U path.** `Wait-Restore` (defined in C3) allows
one full 15-minute run plus one rerun.

```powershell
foreach ($tn in $Sup) { Enable-ScheduledTask -TaskName $tn | Out-Null }
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
$new1 = Get-NewStatusFlags "$N\status-core" "$R\c0-status-flags.txt" 'C8'   # judged below; aux flags are expected until C9b
# e) native-library receipt, old and new
$null = Invoke-Native $Py @('-I','-c','import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version); print(zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)') "$N\native-3119"
```

**Go/no-go C8:**
- (a) all three status files report 3.11.9;
- (c) `status` and `error` are identical to C0, a missing-pointer BLOCK;
- (d) `status-core.new-flags.txt` (new flags against the C0 baseline) lists nothing but aux-task flags, which are
  expected until C9b; a new capture flag is a fail. The `status.ps1` exit code is not the test;
- (e) is a receipt only.

**C9. Core decision (by 02:15).** PASS needs C6, C7 and C8 all green, and either a gap of
35 minutes or less, or an overrun covered by the owner's choice recorded before the night (§11,
`$R\gap-overrun.txt`, read at C0). Nobody is asked at 02:15. Otherwise run §R.

```powershell
$GapMin = ($GapEnd-$GapStart).TotalMinutes
if ($GapMin -gt 35) {
  Log ("gap {0:n1} min over 35; recorded choice {1}" -f $GapMin, $GapChoice)
  if ($GapChoice -eq 'ROLLBACK_ON_OVERRUN') { NoGo 'capture gap overran and the owner chose rollback -> ROLLBACK' } }
Log 'C9 core PASS'
```

The worst-case gap with C7 passing is about 47 minutes: the C4 sweeps, then C5 and C6, then the
full C7 run and its rerun. A rollback after an overrun adds a second stop and restart, so it
lengthens the total gap rather than shortening it. That is why accepting the overrun is the
recommendation.

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
foreach ($ft in $FamilyTasks) {   # family id from the task name: WeatherMakerEvidenceLowestTemperature -> lowest_temperature
  $fid = (($ft -replace '^WeatherMakerEvidence','') -creplace '([a-z0-9])([A-Z])','$1_$2').ToLowerInvariant()
  $fs = Get-Content -LiteralPath (Join-Path $P "data\maker_evidence_families\$fid\status.json") -Raw | ConvertFrom-Json
  Log "family $fid state=$($fs.state) updated=$($fs.updated_at_utc) cycles=$($fs.cycles) last_error=$($fs.last_error)" }
$st2 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$N\status-full"
$new2 = Get-NewStatusFlags "$N\status-full" "$R\c0-status-flags.txt" 'C9c'
```

**Go/no-go C9c:**
- **Tape:** the status command exited 0 within 5 minutes (health `RUNNING` or `DEGRADED`). In its
  latest `tape-status-*.out.txt`, the identity matches the current runtime, evidence integrity
  passes, and the connection state is `CONNECTED`.
- **Shadow:** running again, with the STOP file gone.
- **88a:** `status.json` has an `updated_at_utc` after `$AuxRestart`, `state` is `CAPTURING` or `NO_ELIGIBLE_BANDS`, and no `last_error` mentions a torn journal.
- **Capture family (Q12b, if registered):** its `status.json` has an `updated_at_utc` after `$AuxRestart`, `state` is
  `CAPTURING` (`STOPPED_FAMILY_DISK_FLOOR` is its own disk brake, a WARN), and no `last_error` mentions a torn journal.
  Its task restarts on its one-minute trigger, so run `status.ps1` only after its first fresh status; a family failure
  is handled like an 88a failure below.
- **Status:** `status-full.new-flags.txt` is empty: no flag beyond the C0 baseline. A new flag names the component
  to judge under the rules above; the `status.ps1` exit code (2 while any standing flag exists) is not the test.

If the tape or shadow fails with an import or runtime error on the new venv, run §R. It must start
by 02:45.

If 88a or a capture family fails with a journal or store error (the Q12 or Q12b risk), do **not** roll back and do not delete or
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

Uninstalling 3.11.0 is a later, separate owner decision. The 3.11.9 home is a plain directory with no
uninstall entry, so uninstalling 3.11.0 cannot touch it.

### §R. Rollback (start by 02:45, done by 03:45)

§R uses the C2, C3 and C4 functions in the same session. Every quiesce and stop step is soft: a
failure logs `ESCALATE`, and §R carries on to the swap-back and the restore. Only a rename failure,
or a failed final release check, stops §R. The aux tasks are re-enabled only after capture is 3/3.

**Which interpreter runs the stop verbs.** A stop verb kills a worker only if the expected command
matches what the worker recorded. The verb builds its expected command from its own
`sys.executable`. `managed_stop_expected_command` (`supervisor.py:1231-1266`) adopts the recorded
`managed_process.expected_command` only when its `argv[0]` is a `python.exe`/`pythonw.exe` sibling
in the **same directory**. Anything else fails closed as
`managed_process_provenance_missing_or_mismatched` (`supervisor.py:1341-1343`). So for each worker,
§R reads `managed_process.expected_command[0]` from that worker's status file, which is the file the
stop verb itself reads:
- `loop_status.json` (`snapshot_tracker.py:240`, `:789`);
- `clob_loop_status.json` (`market_microstructure_constants.py:34`, `market_microstructure.py:982`);
- `observation_trigger_status.json` (`observation_trigger.py:102`, `:986`);
- `execution_tape_status.json` (`execution_tape_supervisor.py:74`, `:502`).

§R then runs that worker's stop verb with the `python.exe` in the recorded directory, if it imports
`weather`. Only when nothing is recorded, or the recorded directory has no importable interpreter,
does it fall back to an `import weather` probe of `$Old`, then of the new venv. The two failure
cases:

| Failure at | What is running | Recorded `argv[0]` | Stop interpreter |
| --- | --- | --- | --- |
| C5 or C6 (before C7) | Nothing on the new venv. The capture workers and aux holders were stopped at C2/C3 on 3.11.0. | `$P\venv\Scripts\pythonw.exe`, from the 3.11.0 run; that path is now the new, possibly broken, venv | `$P\venv\Scripts\python.exe` if it imports; otherwise the `$Old` fallback. The recorded processes are gone, so the capture verbs only report. The gate (PID-based, no provenance check) is the stop proof, and the holder sweep proves that nothing holds the new venv. A tape stop refused for provenance logs `ESCALATE` and §R continues. |
| C7, C8, C9 or C9c | The capture workers on the new venv; after C9b, also the tape, shadow and 88a | `$P\venv\Scripts\pythonw.exe`, on the new venv | `$P\venv\Scripts\python.exe` (it imported at C6). It passes the same-directory rule, so the verbs stop the live workers. The `$Old` interpreter would be refused here. |

```powershell
Log 'ROLLBACK start'
$global:ReleaseOnNoGo = $false
function Test-Interp([string]$Exe, [string]$Tag) { if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
  (Invoke-Native $Exe @('-c','import weather.operations.execution_tape_supervisor, weather.operations.capture_resource_gate') "$N\probe-$Tag") -eq 0 }
$StatusFile = @{ snapshot='loop_status.json'; clob='clob_loop_status.json'; obs='observation_trigger_status.json'; tape='execution_tape_status.json' }
function Resolve-StopPy([string]$Key) {
  $rec = $null
  try { $s = Get-Content -LiteralPath (Join-Path $P "data\snapshots\$($StatusFile[$Key])") -Raw | ConvertFrom-Json
        $cmd = @($s.managed_process.expected_command); if ($cmd.Count -gt 0 -and $cmd[0]) { $rec = ([string]$cmd[0]).Trim().Trim('"') } } catch {}
  if ($rec) {
    $cand = Join-Path (Split-Path -Parent $rec) 'python.exe'     # same-directory sibling of the recorded argv[0]
    if (Test-Interp $cand "rec-$Key") { Log "$Key stop interpreter $cand (recorded $rec)"; return $cand }
    Log "ESCALATE: $Key recorded $rec but $cand does not import weather; using the probe fallback" }
  foreach ($c in @(@("$Old\Scripts\python.exe",'old'), @("$P\venv\Scripts\python.exe",'new'))) {
    if (Test-Interp $c[0] "$Key-$($c[1])") { Log "$Key stop interpreter $($c[0]) (probe fallback)"; return $c[0] } }
  Log "ESCALATE: no interpreter for $Key"; return $null }
$X = @{}; foreach ($sk in 'snapshot','clob','obs','tape') { $X[$sk] = Resolve-StopPy $sk }
$X.gate = @($X.snapshot, $X.clob, $X.obs, $X.tape | Where-Object { $_ })[0]     # the gate has no provenance check; any importable interpreter will do
$X | ConvertTo-Json | Set-Content "$N\rollback-interpreters.json" -Encoding utf8
Quiesce-Aux $X.tape -Soft         # idempotent: shadow STOP file, disable aux tasks, tape stop (already-stopped is fine), 88a stop (Q12)
if (-not $X.gate) { Log 'ESCALATE: no importable interpreter; capture stop verbs skipped, the holder sweep decides' }
elseif (-not (Stop-Capture $X -Soft)) { Log 'ESCALATE: capture stop not confirmed in 600 s; continuing to the swap-back' }
if (Test-Path -LiteralPath "$P\venv") { if (-not (Rename-WithSweep "$P\venv" 'venv-cp3119-failed' 'r1')) { NoGo 'ROLLBACK: new venv still held - ESCALATE (holders file in $N); lease kept, see below' } }
if (-not (Rename-WithSweep $Old 'venv' 'r2')) { NoGo 'ROLLBACK: venv-cp3110 cannot be renamed back - ESCALATE (holders file in $N); lease kept, see below' }
if ((& "$P\venv\Scripts\python.exe" -VV) -notlike 'Python 3.11.0*') { Log 'ESCALATE: venv not 3.11.0' }
if (Compare-Object (Mask-Editable (Get-Content "$A\freeze-3110.txt")) (Mask-Editable (& "$P\venv\Scripts\python.exe" -m pip freeze --all))) { Log 'ESCALATE: freeze differs' }
foreach ($tn in $Sup) { Enable-ScheduledTask -TaskName $tn | Out-Null }
$rb = Wait-Restore (Get-Date)
if ($rb) { Undo-Aux; Start-AuxHolders }
else { Log 'ESCALATE: capture not 3/3 - aux tasks (including any U6 export) left DISABLED' }
$rar = Get-ReleaseActive "$P\venv\Scripts\python.exe" "$N\rollback-active"; Assert-CaseA $rar 'rollback'
Release-Lease; Log 'ROLLBACK DONE'
```

**Worst-case duration.** The steps add up to about 50 minutes:
- interpreter probes: about 1 minute;
- the shadow seal wait: 3 minutes;
- the capture gate wait: 10 minutes;
- the r1 and r2 sweeps: up to 2 minutes each;
- `Wait-Restore`: 32 minutes.

That is why §R must start by 02:45: it then ends by about 03:35, inside 03:45, and well before the
04:10 U6 slot and the 04:15 restore trigger.

**Lease on an escalated §R.** If §R stops at r1, r2 or the final `Assert-CaseA`, it deliberately
keeps the lease. Nothing heavy may start on a host in an unknown state.
- **Who holds it:** the elevated PowerShell session that runs §R (workload `py3119_cutover`). The
  lease is an OS file handle on `data\logs\heavy_workload.lock`, and
  `Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P` shows it `Active` with its owner record
  (`workload_admission.ps1:2352-2377`).
- **Who releases it, and when:** the production agent that ran §R, with the owner's agreement after
  the escalation. The hard deadline is **09:00**, the end of the heavy-work window, so the 09:30
  Stage-A chain finds the lease free.
- **How:** in the same session, run `Release-Lease` (that is,
  `Exit-WeatherHeavyWorkloadLease -Lease $global:Lease`), then confirm that
  `Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P` shows `Active = False`.
- **If the session is lost:** the OS closes the handle with the process. The next
  `Enter-WeatherHeavyWorkloadLease` recovers the stale marker only after proving there are no
  residual heavy processes, and asks for a retry (`workload_admission.ps1:1940-1953`).
- **If the host cannot be made safe by 09:00:** the owner decides whether Stage-A runs. Nobody else
  releases the lease to unblock it.

**Rollback passes when:**
- the S4U restore reports 3/3;
- the three status files report 3.11.0;
- the aux tasks are back in their pre-state;
- `active` is still the case-A BLOCK.

There is no release pointer to roll back in case A.

Keep `venv-cp3119-failed` and `$R` for diagnosis. If 3/3 is not reached by 03:45, escalate to the
owner. The aux tasks stay disabled, so a 04:10 U6 export cannot start on a half-restored venv. The
04:15 restore trigger stays armed.

**Escalation (C on the night of 10-21 to 10-22).** The owner's ruling, verbatim: "Auto net, you in the morning"
(owner 2026-10-19 ~13:1x EDT, selected options relayed by master-agent). If capture is not 3/3 by 03:45, the 04:15 `WeatherTrainingWindowRestore` task stays the automatic
net and nobody improvises a further repair overnight. Master-agent records everything (`night.log`, `$N`, the holders
files, the lease state) and messages the owner, who acts when up. The lease rules above still apply, including the
09:00 deadline and the owner's call on Stage-A. This ruling supersedes the DECISION_LOG rows of 2026-10-13 and 2026-10-17
on who answers an escalation for that night.

### §D. Cleanup after PASS (a later admitted night)

```powershell
# Every qualification worktree and branch (Phase B, and B-R if it ran); they were made in earlier sessions.
$QBranches = @(git -C $P branch --list 'py3119-qual-*' --format='%(refname:short)')
if (-not $QBranches.Count) { throw 'no py3119-qual-* branch' }
$wtl = @(git -C $P worktree list --porcelain)
foreach ($qb in $QBranches) {
  $wi = [array]::IndexOf($wtl, "branch refs/heads/$qb"); if ($wi -lt 2) { throw "no worktree for $qb" }
  $qwt = $wtl[$wi - 2] -replace '^worktree ', ''
  git -C $P worktree remove $qwt      # use --force only if git refuses because of the ignored stage venv
  git -C $P branch -D $qb }
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
   - repin the Windows qualification lane from `3.11.0` to `3.11.9` (the `python-version: '3.11.0'` line of `.github/workflows/windows-qualification.yml`; its line number moves with the shard lists);
   - update the `src/` comments that say the host runs 3.11.0 (`wallet_reader_transport.py:73`, `wu_history.py:157`, `wu_redaction.py:255`). They are roll-sensitive, so send them through `roll_verdict.ps1`;
   - update the findings that cite pre-3.11.2 behaviour.
6. **State.** Production rewrites [the state of play](STATE_OF_PLAY.md) (host Python) and records the
   cutover in the owning roadmap item.
7. **Day 14.** The owner decides on deleting `venv-cp3110` and the freeze copy, and on uninstalling
   3.11.0. After a §R rollback, `$NewHome` is a plain directory: delete it on a later night once no
   venv's `pyvenv.cfg` names it.

## 10. Timings against the host timetable

| Window | Allowed for this runbook |
| --- | --- |
| 00:30-04:45 | §T; Phase B (B0 by 02:00, suite start by 03:00); §D |
| 00:30-09:00 | §4 host reads (serial); Phase A (no lease; after any landing night has handed back) |
| 01:00-04:00 quiet window | Phase C only. Latest lease 01:15, latest rename 01:30, core decision 02:15, aux verify 02:25, rollback start 02:45 (worst case done about 03:35). |
| 04:45-06:45 tiering reserve, 06:50 jobs | Nothing heavy from this runbook |
| 09:30-11:55 Stage-A | Nothing |
| 12:00-18:00 graded and 18:00-00:30 near-close | Nothing |
| DST night 10-31 to 11-01 | Nothing (G11); §7a keeps the last attempt two nights earlier |
| Night before or night of a scheduled LFC session | No Phase B or Phase C (G7), except the dated 2026-10-14 exception in G7 (B 00:30 10-16) |

## 11. Owner sign-off checklist

The owner initials each line in the decision log. Recommendations come first.

- [ ] **Runbook revision** approved as written (G0), including the 2026-10-12 G7 revision. The
      night is named (G0: Phase A its morning, B and C their nights). It must come after the 88a freeze in the state of play (G8), must not be the
      night before or the night of a scheduled LFC session (G7), and must not be the DST night (G11).
- [ ] **Q12, 88a stop:** record `STOP_AUTHORIZED` in `$R\q12.txt`, authorizing `Stop-ScheduledTask
      -TaskName WeatherMakerEvidenceCapture` at C2 and accepting a short 88a gap and an untested
      abrupt stop (recommended). The alternative is to wait for a reviewed graceful-stop verb; the
      cutover stays NO-GO until then.
- [ ] **Q12b, capture-family stop (2026-10-19; only if a `WeatherMakerEvidence<Family>` task is registered):**
      record `STOP_AUTHORIZED` in `$R\q12b.txt`, authorizing its stop at C2 on the same terms as Q12
      (recommended), or keep the task unregistered until after the cutover. C0 is NO-GO without it.
- [ ] **Capture gap:** about 20-35 minutes for the capture workers, and somewhat longer for the
      execution tape, the maker shadow and 88a (they restart at C9b). Confirm this is within the
      approved one-gap budget, and that the gap's timing against the desk-study panel window is
      acceptable. **MG-1 and the 10-22 gap** (C on the night of 10-21 to 10-22): "Test's own rule decides" (owner 2026-10-19 ~13:1x EDT, selected options relayed by master-agent):
      MG-1's signed rule alone decides whether 2026-10-22 counts. That is the promotion-countable condition, MG-1
      §3 (e), with the countable-date population of §4 and the void conditions of §6
      (`docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md`, binding sha in
      [the reserved confirmation window](reserved-confirmation-window.md)). There is no special exception either way.
- [ ] **Gap overrun (pre-decided; C9 acts on it):** if the capture gap exceeds 35 minutes but C7
      recovered (worst case about 47 minutes), record the choice as the first token of
      `$R\gap-overrun.txt`, with its DECISION_LOG reference:
      - `ACCEPT_OVERRUN` (recommended): keep 3.11.9. A rollback would add a second gap.
      - `ROLLBACK_ON_OVERRUN`: run §R.

      C0 is NO-GO without a recorded choice.
- [ ] **G12, downloads:** approve the PyPI wheel downloads (§T, B1a and B1b; hash-pinned, Windows
      and pure wheels only) and the NuGet package `python` 3.11.9 (A3 on the host, W0 on the
      workstation; about 17 MB, SHA-512 pinned). The installer download is no longer used.
- [ ] **Q13, tzdata:** run §T on an earlier night (recommended), or exempt tzdata in the comparisons.
- [ ] **Q4, install method (revision 2026-10-13):** copy the NuGet package's `tools` tree into a
      new home under Program Files (A4; recommended). Rejected: the installer in either scope (it
      plans a MajorUpgrade of 3.11.0); an admin layout with direct MSI installs (more downloads,
      registry writes, unproven upgrade tables); the embeddable zip (no `venv`, no `ensurepip`).
- [ ] **Q9, provenance (revision 2026-10-13):** require the nuget.org size and SHA-512, the W0
      manifest, the `binaries` SHA-256 values from the workstation's python.org-installer home and
      the PSF Authenticode signature together (recommended).
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

Validate with `.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit`, and parse-check
every PowerShell block of this file and of the night-plan blocks built from it (exit 0 required;
read-only, nothing is executed):

```text
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\check_markdown_powershell_fences.ps1 -Path 'docs\operations\HOST_PYTHON_UPGRADE_RUNBOOK.md;<night-plans folder>'
```
