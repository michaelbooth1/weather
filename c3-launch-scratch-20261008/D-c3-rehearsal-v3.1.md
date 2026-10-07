# C3 v3.1 — keyless console rehearsal of the live launcher (operator checklist)

Swarm M, Wave 2 author, 2026-10-06 (2026-10-07 UTC). This replaces `D-c3-rehearsal-v3.md`. It applies the Defender
review `C3-v3-defender.md` (verdict **CLEARED-AFTER-FIXES**): must-fixes M1–M3, the two owner answers (Q5
`consoleForeign` stays a HARD STOP; Q6 a `started` difference is an ABORT, now enforced by the script), and notes
N1–N9. It also applies two master-agent additions: an owner-attended host slot, and a § "Resource profile". Changes
against v3 are tagged **[v3.1: id]**; the v3 tags (**[v3: id]**) are kept, so the v2→v3 history stays readable.

It is a review draft. The scripts are text in this file, and nothing here has run on the capture host. The one
permitted workstation self-test re-run **found a defect in the review's own M1 edit** (V31-R1: PowerShell turns an
empty array returned from an `if` expression into `$null`, so every clean run read as "evidence missing"). It
failed closed. The defect is fixed below and unit-checked without starting a process, but the fixed `c3_run.ps1`
has **not** had a live re-run; see § "Workstation self-test result" and the open owner questions.

**[F1, 2026-10-07 workstation, after `C3-LAUNCH-PACKET.md` blocker F1].** Steps 3, 5, 6, 7 and 8 could not pass as
written: under `-I -S` no `site.venv()` runs, so `sys.prefix` is the base Python and `sysconfig` purelib is the base
install's `Lib\site-packages`. Both the step-3 query and the #230 harness (`run_break_case` sets
`WEATHER_FIXED_SESSION_SITE_PACKAGES = sysconfig.get_paths()["purelib"]` in its caller, `c3_break.py`/`c3_ctrlc.py`)
got the base path, and the runner import failed with `ModuleNotFoundError: No module named 'requests'` (reproduced on
the workstation). Fix: step 3 uses the template's rule `<venv>\Lib\site-packages` (computed in PowerShell, checked
with `Test-Path`); `c3_break.py` and `c3_ctrlc.py run` set `sys.prefix`/`sys.exec_prefix` to the venv **before the
first import of `sysconfig`** (sysconfig copies `sys.prefix` into module globals at import, so a reset after the import
has no effect; this was verified) and assert that purelib equals step 3's value. **Trap: `-S` means `sys.prefix` is
the base install; never derive a venv path from `sysconfig` under `-S`.** `k` and the `started` formulas are unchanged.

**[F3, 2026-10-07 workstation dry pass].** The first dry pass through `c3_run.ps1` hit a **HARD STOP at 6b**
(`started=6` against the pin `2k+1=5`; `consoleForeign=1`), and the next call was `REFUSED` (console shared). Cause,
proven on the workstation: (a) the 6b mutant adds `CREATE_NO_WINDOW` to the stub's `Popen`, so the stub gets its own
`conhost.exe`, created inside the Job: one extra member, so **6b is `2k+2`**, not `2k+1`; (b) the runner then sends
`CTRL_BREAK_EVENT` to the stub's process group from the C3 console, where that group does not live, and conhost leaves
the stub's PID in this console's `GetConsoleProcessList` **after the stub has exited** (reproduced in isolation: the
entry appears only when the Ctrl+Break is sent, and the PID has no process). It is a stale list entry, not a process:
nothing escaped (`escaped=0`, `stillAlive=0`), and a PID with no process cannot receive a keystroke. Fix in
`c3_run.ps1` (version `c3-run-v3.1-F3`): a console entry whose PID **provably has no live process** (`OpenProcess`
fails with `ERROR_INVALID_PARAMETER`, or the process object is signalled) is recorded in the new record-only field
`consoleStale` and excluded from both the start refusal and `consoleForeign`. Every other entry, including one that
cannot be opened for any other reason, still counts (fail closed). `consoleForeign>0` stays a HARD STOP (Q5).

The rehearsal is the "supervised keyless rehearsal at a real operator console" that PR #230 adds to
`INTERNATIONAL_MM_LIVE_PILOT.md` ("Gate before the first live attempt after PR #229"). The runbook text is the
authority. C3 is only the Swarm M brief's label for it.

## What this rehearsal never does

- **No step places, signs, cancels or prepares an order.**
- **No step uses credentials.** None opens Credential Manager, a `.env*`, `*.cred`, `*.key`, `*.pem` or
  `config/local/*` file, or reads a credential-shaped environment value.
- **No step touches a live path.** None builds a session manifest, runs the sealer, starts a sealed launcher,
  takes the shared lease, reads production `data/`, contacts the exchange or a wallet, or calls a paid API.
- The only production function that executes is the runner's launcher-control function,
  `_default_launcher_runner`. It runs only on stub PowerShell scripts in the scratch folder. Step 8 pins its stub by
  path and SHA-256, and **[v3: N4]** also passes the stub, its child and the tree's Job helper as `protected_files`,
  so the runner itself holds deny-write handles on them and re-hashes them. Importing the runner module loads its
  import-time closure (registry, sealer, lifecycle probe) and nothing else.
- Every process the rehearsal starts runs inside a kill-on-close Windows Job object that the rehearsal itself owns.
  Cleanup never looks for processes by name or start time (§ "The cleanup rule").
- **The official record must come from the production tree after #230 lands** (and before any reseal). A run on
  the #230 worktree is a **dry pass**, not the record, and it runs only on the 32 GB workstation.

## Host paths **[v3: capture-host paths]**

Every command meant for the capture host uses these paths, and only these:

| Name | Capture host (official record) |
| --- | --- |
| `<tree>` | `C:\Users\micha\Desktop\github\weather` (the production checkout). Use a deployed exact tip, `C:\Users\micha\Desktop\github\weather-exam-deployed-<sha>`, only if the owner names that tip for the record. |
| `<venv>` | `C:\Users\micha\Desktop\github\weather\venv` (so `$py` is `C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe`) |
| `<date>` | `yyyymmdd` of the rehearsal; the scratch folder is `C:\c3\<date>` |

**Dry pass, 32 GB workstation only [v3.1: N5]:** `<tree>` is `C:\wt\workstation-chat\integration-20261006-rf2`
(reviewed at `f9063256e`), and `<venv>` is `C:\Users\Michael\Documents\github\weather\venv` (Python 3.11.9; the
#230 worktree has no venv of its own). The dry pass therefore runs the #230 tree's `src` against that venv's
`purelib`. Record both paths. A workstation path never appears in a command typed on the capture
host. The scripts below are written once with `<tree>`, `<venv>` and `<date>` placeholders. Substitute the capture-host
values for the record.

## Host slot **[v3.1: master-agent, N7]**

P8 item 6 and step 7 need a **real keypress by the owner** at the console, so the official run is owner-attended.

- **Recommended: 09:00–09:30**, on a morning after a night with no landing and no export. Save the six scripts into
  `C:\c3\<date>` beforehand (writing files is not part of the timed run). Start step 1 at 09:00. **If step 8a has not
  started by 09:20, stop**: close the console and repeat another day from step 1. The Stage-A chain starts at 09:30,
  and the rehearsal must not overlap it.
- **Alternative, if the owner is at the console then: 05:10–05:55** on a night with no landing. This avoids the landing
  windows (01:00–03:44 on landing nights), the 03:40 and 02:48–03:44 exports, and the 04:15, 05:00 and 06:00
  triggers. 88a fires every 5 minutes from 02:34. That only adds record-only noise (`vanishedOutsideJob`), and v3.1's
  M1 fix keeps it from causing a false HARD STOP.
- **Never:** 09:30–11:55 (Stage-A), **12:00–18:00 (the protected graded window)**, 18:00–00:30 (the protected
  near-close window), during a merge or the 01:00–04:00 quiet-window merge, or while anything writes the production
  checkout. Step 8 holds a read lock on one checkout file for up to about 130 s (N6).
- **Conflict to resolve [owner].** The request mentioned "an evening before 18:00". Every time before 18:00 and after
  12:00 is inside the protected graded window, and every evening time from 18:00 to 00:30 is inside the protected
  near-close window. So no evening slot complies, and this checklist offers none. 09:00–09:30 is the
  owner-attended slot.
- **Why 09:00–09:30 is allowed although it is outside 00:30–09:00.** That window gates *heavy* work (test suites,
  compileall, training, replay, bulk scans), which must also hold the lease. This rehearsal is not heavy: it starts
  about seven short processes at a time, holds no lease, and writes kilobytes (§ "Resource profile"). It is still
  kept out of every protected window, because a capture-day risk is not worth any convenience, and because step 8
  briefly read-locks a checkout file.

## Resource profile **[v3.1: master-agent]**

Labels: **MEASURED (workstation)** is from the v3 and v3.1 self-tests on the 32 GB workstation (Windows 11
10.0.26200, PowerShell 5.1.26100, the Python 3.11.9 venv, stub children only). **ESTIMATED** is derived from the
script parameters and the measured stub costs. Steps 3–8 need the live runner and the templates, which the brief
excluded, so they were not run. v3.1's `c3_run.ps1` records `peakActive` (peak concurrent Job members) and
`peakJobPrivateMB` (the Job's `PeakJobMemoryUsed`) on every ledger line. The dry pass and the official run therefore
**measure** these figures on their own host; copy them into the record.

| Quantity | Figure | Label |
| --- | --- | --- |
| Processes per `python.exe` call (`k`) | 2: the venv launcher plus the real interpreter, both inside the Job | MEASURED (workstation) |
| Peak concurrent processes, rehearsal-wide | Step 7: `3k+1` = 7 Job members (the driver, helper and sentinel, each a launcher plus an interpreter, and the stub `powershell.exe`), plus this console's `powershell.exe` and its console host: **about 9**. Step 8: at most `2k+3` = 7 members, of which `csc.exe`/`cvtres.exe` are only momentary | ESTIMATED from the measured `k` |
| Console PowerShell memory | 74.7 MB working set and 58.6 MB private at start; **146.9 MB peak working set and 98.1 MB private** after `Add-Type` and five `c3_run.ps1` calls | MEASURED (workstation) |
| Job peak private bytes, one stub `python.exe` call | **8.7 MB** (`peakJobPrivateMB`, the launcher and interpreter together); 12.7 MB for 4 processes (a nested-Job grandchild) | MEASURED (workstation) |
| Job peak private bytes, `python.exe` plus a child `powershell.exe` | **60.9 MB** (so one bare `powershell.exe -Command` costs about 52 MB) | MEASURED (workstation) |
| Job peak private bytes, steps 5–7 | About 120–200 MB: a driver of about 10 MB; a helper that imports the runner, about 40–80 MB; the stub `powershell.exe`, about 52 MB; the sentinel, about 9 MB (step 7) | ESTIMATED |
| Job peak private bytes, step 8 | About 200–300 MB: a driver that imports the runner, about 40–80 MB; a stub `powershell.exe` that runs `Add-Type`, about 80–100 MB; a transient `csc.exe`, about 30–60 MB; the prompt child, about 9 MB | ESTIMATED |
| Peak working set, rehearsal-wide | Under 500 MB, with the console counted | ESTIMATED |
| `c3_run.ps1` overhead per call | About 1.2–1.7 s: two WMI snapshots, the Job reads and the ledger write. The **first** call in a console adds about 3–4 s for `Add-Type` (`csc.exe`) | MEASURED (workstation): `p8-pin-diff` took 1.25 s in all; `p8-guard-2` took 7.7 s against a 6 s stub; `p8-guard-1` took 8.8 s against a 4 s stub, including the compile |
| Whole self-test, 5 calls including console start | 42 s | MEASURED (workstation) |
| Machine time per step | P8 items 2 and 6: about 25 s. Steps 3 and 4: about 3 s each. Step 5: 3 × about 7 s. Step 6: 2 × about 7 s. Step 7: control and operator, about 35 s each, plus 2 judges of about 3 s. Step 8: 8a and 8b, about 10 s plus typing; 8c, about 95 s if run | ESTIMATED |
| Overall duration, owner-paced | **About 5 min of machine time; 15–25 min with reading and typing** (more if 8c runs). The 09:20 cut-off in § "Host slot" bounds it | ESTIMATED |
| Disk writes | **Under 1 MB, all in `C:\c3\<date>`**: the six scripts (about 70 KB); `p8-pins.json`; `launch-ledger.txt` (about 0.5–1 KB per call, about 25 calls); and one run folder per run, holding `markers.txt`, `helper-output.txt`, `helper-rc.txt`, `cooperative.ps1` and `sentinel.txt`, a few KB each. Outside it: `Add-Type`'s CodeDom temporary files in the operator's `%TEMP%` (created and deleted by `csc.exe`; the first call in the console, and once per step-8 stub); PSReadLine appending the typed commands to `%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt` (no secret is ever typed); and OS bookkeeping (Prefetch, and WER only after a crash) | MEASURED (workstation) for the ledger (2.5 KB for 5 calls); rest by construction |
| `.pyc` writes | **None anywhere [v3.1: M3].** Every rehearsal Python is started with `-B` (`-I -S -B` everywhere except step 4's `-B -c` and the 6b mutant's `-c`). The bootstraps also set `sys.dont_write_bytecode`. Step 4 and the 6b mutant (the only two without `-I`) inherit `PYTHONDONTWRITEBYTECODE=1` from P8 item 2. The harness passes `os.environ` through, minus three named variables, none of them this one. The venv lives inside the production checkout (`…\weather\venv`), so this also covers `venv\Lib\site-packages\__pycache__`. Step 9 checks the checkout's `src`, `tests`, `scripts` and root for new `.pyc` files | by construction, and checked at step 9 |
| Capture files, `data\` | Never opened, read or written | by construction |
| Production checkout | **Reads only**: `src`, `tests\operations` (the harness), `scripts\ops` (the launcher template, `stage0`/`stage1` templates, the Job helper), the root `sitecustomize.py` (steps 4 and 6b), and `git rev-parse`. `git status` is run with `--no-optional-locks` [v3.1], so it does not rewrite `.git\index`. Step 8's `protected_files` holds a read handle with read-only sharing on `scripts\ops\windows_kill_on_close_job.ps1` for up to about 130 s, so a *writer* to that file (a merge or pull) would fail in that window. Nothing writes source files, so supervisors' `STALE_CODE` fingerprints cannot change and **no capture worker rolls** | by construction |
| Scheduler, lease, network | **None.** No task is registered, run or changed; `workload_admission.ps1` is not used, because the rehearsal is not heavy work; no rehearsal code opens a socket. The runner is called only on stub launchers | by construction |

**Verdict on timing.**
- **09:00–09:30: yes**, owner-attended, finishing by 09:25 (see the cut-off above). It is light, so the heavy-work
  window does not apply, and it overlaps no protected window or scheduled chain.
- **00:30–09:00: also yes**, at a quiet time (05:10–05:55), if the owner is at the console.
- **12:00–18:00: no.** It is the protected graded window. The rehearsal cannot roll a worker, but it adds processes
  and console activity on the capture host during graded capture. A HARD STOP or an operator mistake (for example a
  Ctrl+Break) in that window would also need investigation on a graded day. The same applies to 18:00–00:30 and to
  the 09:30–11:55 Stage-A chain.

## Changes from v3 (v3.1)

| ID | v3 problem | v3.1 fix | Where |
| --- | --- | --- | --- |
| **M1** | `escaped` counted a reused PID (a non-member whose PID was once seen) and a snapshot race (a member born between the last Job read and the WMI snapshot) as escapes: false HARD STOPs on a busy host. `consoleForeign` had the same race | The **snapshot is taken first**, then the consistent Job read, then the console list, then a **late Job PID read**; `$members` = the PIDs read at both points. The escape rule checks the **identity** of the parent (the live parent entry with the same PID created no later than the candidate must be a member or already escaped); a parent missing from both snapshots fails closed. A non-member with a seen PID is counted as `pidReuse` (record-only). `consoleForeign` is computed against `$members` | `c3_run.ps1` |
| **V31-R1** (new, from the re-run) | The review's exact M1 edit, `$foreign = if (…) { $null } else { @(…) }`, gives `$null` for an empty list, because PowerShell unrolls an empty array returned from an `if` expression. Every clean call therefore read as "console list failed" → `verify=FAIL (evidence-missing)`. Fail-closed, but the rehearsal could never pass | `$foreign = $null; if (…) { $foreign = @(…) }`. `evidence-missing` now names its source (`:snapshot`, `:console`, `:job`) | `c3_run.ps1` |
| **M2** | Per-step `started` pins came from workstation numbers | `k` = `started` of `p8-guard-1` **on the host's own console**, and it must be 1 or 2. Every later call passes `-ExpectStarted`: `k` (s3, s4, all judges), `2k+1` (s5, s6a; **[F3]** `2k+2` for s6b), `3k+1` (s7), `2k+3` (s8) | P8 item 6, steps 3–8 |
| **Q6** | "`started` must equal the pin" was operator prose only | `-ExpectStarted` and the ledger field `startedPin` (`unpinned`, `OK` or `DIFF`). `DIFF` gives `verify=FAIL` (ABORT the step). A HARD STOP still takes precedence | `c3_run.ps1`, Step 9 |
| **Q5** | — | `consoleForeign>0` at close stays a **HARD STOP** (master-agent's ruling), now free of the M1 race | `c3_run.ps1` |
| **M3** | Step 4 and the 6b mutant could write `__pycache__\*.pyc` into the production checkout | Step 4 gets `-B`; P8 item 2 sets `PYTHONDONTWRITEBYTECODE=1` (6b inherits it); the step-3 `sysconfig` query gets `-B`; Step 9 checks for new `.pyc` files | P8, steps 3, 4, 6b, 9 |
| N1 | `escaped` cannot see a process created *by a service* on a member's request | Stated in § "Containment verdict" | — |
| N2 | An inconsistent Job read became `memberMismatch≠0`, a HARD STOP | It is now `job-list-inconsistent` → `FAIL` (evidence missing) | `c3_run.ps1` |
| N3 | The return value of `Uninstall()` was ignored | `guardRemoved` on the ledger line. The guard is removed just before the ledger write, and the `C3RUN` line prints after it ("hands off until the `C3RUN` line" covers that gap) | `c3_run.ps1` |
| N4 | Step 7 said a double press "shows up as `forced: true`" | Corrected: two presses inside the wait give two sentinel stamps and `ctrlCCount=2`, which is classed timing-only (one repeat); `forced: true` only if the second press lands in the cleanup loop | Step 7 |
| N5 | The dry-pass venv was unnamed | Named, workstation only | § "Host paths" |
| N6 | The `protected_files` read lock can block a checkout writer | P3 and step 8: no merge **and no checkout write** during the rehearsal | P3, Step 8 |
| N7 | No host slot | § "Host slot" | — |
| N8 | `c3_prompt.py` said "nothing was launched" for errors that can occur after the launch | "the runner refused or failed; see detail" (still exit 9) | `c3_prompt.py` |
| N9 | Members of nested Jobs alive at close were never exercised | The v3.1 self-test included one such call (`p8-nested-alive`). It confirms kill-on-close through the nested Job (nothing was left running afterwards); its ledger fields were masked by V31-R1. Optional dry-pass call in P8 item 7 | P8 item 7 |
| master-agent | — | § "Resource profile"; owner-attended slot | top |
| (new) | `git status` can rewrite `.git\index` in the production checkout | `git --no-optional-locks status --short` | P2 |
| (new) | — | `peakActive`, `peakJobPrivateMB` and `lateMembers` on every ledger line (record-only) | `c3_run.ps1` |

## Changes from v2 (kept for history)

| ID | v2 problem | v3 fix | Where |
| --- | --- | --- | --- |
| **B1** | The Ctrl+C guard used .NET `Console.CancelKeyPress`. Its native hook is never re-registered after the first unhook, so from the second `c3_run.ps1` call onward PowerShell's own break handler wins: the Job closes mid-run, no ledger line is written, and step 7 can never pass. **The workstation self-test reproduced this exactly** with the v2 script. | A native `SetConsoleCtrlHandler` routine (Add-Type), **removed and re-added on every call** so it is always the newest handler and runs first (`C3-handler-order-proof.md`). It swallows `CTRL_C_EVENT` in this PowerShell only; it is not the inheritable `(NULL, TRUE)` flag. **Type caching:** the C# namespace is derived from the SHA-256 of its own source text, so an edited script always compiles a new type and never silently reuses stale code, plus a `Version` constant check. P8 item 6 is a two-run self-test that passes only if the **second** run's ledger shows the Ctrl+C caught. | `c3_run.ps1`, P8 item 6 |
| **B2** | Step 7 passed with no keypress: on CPython 3.11 the runner honours Ctrl+C only when its wait returns at the deadline, the same branch as a timeout | A **sentinel** process (inside the Job, same console and group) records the console `SIGINT` with a timestamp. The judge requires exactly one `SIGINT` between `START` and the deadline, **and** the ledger's `ctrlC=True ctrlCCount=1`, **and** the step-5 asserts. A mandatory control run with no keypress must show no `SIGINT`. The verdict is binary; the "explained `EARLY_EXIT_NO_BREAK`" escape is deleted; at most one repeat, and only for operator timing | Step 7, `c3_ctrlc.py` |
| **M1** | A snapshot failure skipped the Job close; any interruption skipped the ledger | The Job queries and snapshot are in an inner `try` whose `finally` always closes the Job. The ledger line is written in the outermost `finally`, unconditionally. Missing evidence forces `verify=FAIL` | `c3_run.ps1` |
| **M2** + steer | `vanishedOutsideJob` was a hard stop that host noise trips, and nothing observed an escape | New hard checks: **`escaped`** (a process this run caused that is not in the Job) and **`memberMismatch`** (this Job's own members, started versus ended), plus `consoleForeign`. `started` comes from the Job's `TotalProcesses`. `vanishedOutsideJob` is **record-only**. § "Containment verdict" explains how this implements master-agent's rule | `c3_run.ps1`, every step, Step 9 |
| **M3** | Ctrl+C and Ctrl+Break are console broadcasts; nothing proved the console was private | `c3_run.ps1` refuses (`verify=REFUSED`, exit 64) unless `GetConsoleProcessList` is exactly `{ $PID }`, and checks again at close (`consoleForeign`) | `c3_run.ps1`, P4, Step 1 |
| **M4** | Step 1 typed `powershell.exe -NoProfile` inside a shell, then aborted on the nested parent | The console is opened directly: **Win+R** or a **Windows Terminal profile**. The nested-shell line is deleted | Step 1 |
| **M5** | Step 8 checked stdin at the wrong process, and `sys.stdin.isatty()` could crash the child | The stub launcher prints `C3 STUB stdin_redirected=` and refuses (exit 7) unless it is `True`, which is the #229 proof. The child records `stdin` for information only and cannot crash on `None` | Step 8, both step-8 stubs |
| **V3-1** (new) | v2's `ActiveProcesses()` passed a 64-byte buffer. `QueryInformationJobObject` requires the exact 48-byte size and fails, so v2 logged "Job query failed", left `activeAtClose=-1`, and still printed `verify OK` with an empty member list. **Observed** in the workstation self-test | Exact size 48; the Win32 code is in the message; a failed Job query is now `evidence-missing` → `verify=FAIL` | `c3_run.ps1` |
| N1 | `PROC_THREAD_ATTRIBUTE_JOB_LIST` needs Windows 10 | `c3_run.ps1` reads the true version (`RtlGetVersion`) and refuses below 10.0; P8 records it | `c3_run.ps1`, P8 |
| N2 | P3 omitted `csc.exe`/`cvtres.exe` | Listed in P3 | P3 |
| N3 | `Add-Type` caching could desynchronise pins from loaded code | See B1 (hash-derived namespace + `Version`) | `c3_run.ps1` |
| N4 | Step-8 time-of-check gap | `protected_files` passed to `_default_launcher_runner`; it holds deny-write handles and re-hashes before the launch | `c3_prompt.py` |
| N5 | Pins are self-derived | Compare `p8-pins.json` with the paper copy before step 5 and before step 8; compare `prompt_until` with the reviewed value | P8, Steps 5, 8 |
| N6 | Static check too narrow | Pattern widened; `Get-CimInstance` allowed only inside `Get-C3Snapshot`; re-run before step 5 | P8 item 5, Step 5 |
| N7 | Environment inheritance | P5 stays a hard abort; Step 9 closes the console | P5, Step 9 |
| N8 | Runbook text | The Ctrl+C wait can last until the sealed session deadline (120 s or 240 s) | § "Runbook note" |

## What it proves and why each part is needed

| Property | Why it matters | Step |
| --- | --- | --- |
| The live runner is started exactly as the template does: `python -I -S -B -c <bootstrap>` | Only then does the repository `sitecustomize.py` (the CREATE_NO_WINDOW patch) never load. If it loads, Ctrl+Break never reaches the launcher, yet the receipt still says "cooperative" (2026-10-06 root cause) | 2, 3 |
| Ctrl+Break sent by the runner at the sealed deadline reaches the launcher's PowerShell, which cleans up cooperatively (`cooperative=true`, `forced=false`, the stub's own exit code) on **this** console | A receipt's `cooperative` flag cannot tell a handled break from a launcher that ended on its own. Only the stub's `BREAK` marker proves delivery | 5 |
| A runner that sends no break, and a helper that loads `sitecustomize`, are both **detected** | Shows the marker is not spurious on this host | 4, 6 |
| The operator's own Ctrl+C at the console is **delivered** (sentinel record) and the run still ends in the cooperative path **[v3: B2]** | Pilot runbook: console interrupts enter the cleanup path. On CPython 3.11 the runner acts on it when its wait returns, which is the sealed deadline | 7 |
| With stdin on the null device (#229), the confirmation prompt (the templates' own `_prompt_until`) still reads typed keys from the console and refuses a wrong literal | Otherwise every live attempt would expire at its prompt | 8 |
| Nothing the rehearsal causes runs or ends outside its own Job **[v3: M2]** | Capture-host safety: the rehearsal must not touch capture workers | every step, 9 |
| The result is recorded with date, host, console and hashes | The runbook forbids a live attempt until the record exists | 9 |

## The cleanup rule (hard rule; read before P3)

1. Cleanup **never** finds, filters or stops a process by name, image path, command line or start time. The
   checklist contains no `Get-Process … | Where-Object StartTime`, no `Stop-Process`, no `taskkill`, no `wmic …
   delete`. On the capture host a name or time sweep can match capture workers that a `STALE_CODE` readoption or a
   scheduled task restarted minutes earlier.
2. The rehearsal starts processes in exactly one way: `c3_run.ps1` (below).
   - It refuses to start anything unless this console has no other attached process **[v3: M3]** and the OS is
     Windows 10 or later **[v3: N1]**.
   - It creates a fresh, unnamed Job with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. The Job handle is not inheritable.
   - It creates its one child **directly inside that Job** (`PROC_THREAD_ATTRIBUTE_JOB_LIST`). If the Job cannot
     take the child, `CreateProcess` fails and no process exists, so there is never a moment when the child is
     outside the Job and would need a separate kill.
   - Everything the child starts (the venv launcher's real interpreter, the harness helper, the runner's own nested
     Job, the stub launcher, the step-7 sentinel, the step-8 prompt child, and the `csc.exe` that the step-8 stub's
     `Add-Type` runs) is created inside this Job, or inside a Job nested in it.
3. The **only** termination `c3_run.ps1` performs is closing its own Job handle, the last one, which makes Windows
   end every process still in that Job. **[v3: M1]** That close sits in a `finally` that runs even if the Job query or
   the snapshot throws. Below it, the harness and the runner end only processes they created themselves, inside the
   same Job. That is production code and #230 test code, unchanged.
4. Verification, printed after every run and appended to `launch-ledger.txt` (the ledger write is itself in a
   `finally`, so every call leaves exactly one line) **[v3: M1, M2]**:
   - **[v3.1: M1]** Just before the close, in this order: a full PID, parent PID and creation-time snapshot; then the
     Job's own accounting, which gives `started` (`TotalProcesses`: every process ever in the Job, nested Jobs
     included) and `activeAtClose`, with the member PID list (`JobObjectBasicProcessIdList`) read between two
     accounting reads until all three agree (if they never agree, `FAIL`, not HARD STOP); then the console's attached
     PIDs; then a **late** member PID read. Every Job read is therefore newer than the snapshot. While waiting, every
     250 ms poll adds the member PIDs to `seen` and tracks `peakActive`.
   - A second snapshot is taken just after the close. **Both snapshots are read-only evidence and are never fed to
     any stop call.**
   - The containment verdict is computed as in § "Containment verdict".
5. If PowerShell itself dies (window closed, or a Ctrl+Break into a `[DBG]` prompt that you then quit), Windows
   closes the Job handle and kill-on-close applies. Containment never depends on the script reaching its `finally`
   block.

## Containment verdict **[v3: M2 and the master-agent steer]**

**The rule (master-agent, 2026-10-06):** anything the rehearsal itself caused is a **HARD STOP**. Host-wide
vanishings of processes outside the Job are only **RECORDED**, never a stop.

`c3_run.ps1` computes these fields on every call and prints them on its `C3RUN` line:

| Field | Meaning | Class |
| --- | --- | --- |
| `escaped` | Processes **this run caused** that are not in its Job: created after the launch, not a member, and whose **parent is identity-checked** as a member or an already-escaped process (the parent entry with that PID created no later than the candidate). A parent missing from both snapshots, whose PID the Job once held, fails closed. Fixpoint over both snapshots **[v3.1: M1]** | **HARD STOP if > 0** |
| `memberMismatch` | This Job's own members, **started versus ended**: `started` (`TotalProcesses`) against `endedBeforeClose` (`TotalProcesses − ActiveProcesses`) plus `endedAtClose` (members at close that are gone afterwards); plus any disagreement between the PID list and `ActiveProcesses`, more PIDs seen than started, or `started < 1` | **HARD STOP if ≠ 0** |
| `consoleForeign` | Processes attached to this console at close that are neither this PowerShell nor a Job member, where members include the late PID read **[v3.1: M1]** (they would receive the operator's keystrokes) | **HARD STOP if > 0** (master-agent, Q5) |
| `consoleStale` | **[F3]** Console-list entries whose PID provably has no live process (stale conhost entries left by a Ctrl+Break sent to a process group on another console; `close:` marks those found at close). They are excluded from the start refusal and from `consoleForeign` | **RECORD ONLY** |
| `startedPin` | `OK` or `DIFF` against `-ExpectStarted`; `unpinned` when no pin was passed **[v3.1: Q6]** | **`DIFF` → `verify=FAIL` (ABORT)**; a HARD STOP takes precedence |
| `pidReuse` | Non-members whose PID the Job once held: by construction a reused PID, because a process cannot leave a Job **[v3.1: M1]** | record only |
| `lateMembers`, `peakActive`, `peakJobPrivateMB`, `guardRemoved` | Members first seen by the late read; peak concurrent members; the Job's peak committed bytes; whether the guard was removed **[v3.1]** | record only |
| `stillAlive` | Job members still present after the close (also counted in `memberMismatch`) | must be 0 |
| `vanishedOutsideJob` | Processes **outside** the Job, not attributable to the run, that ended during the close window. Each is listed with name and parent PID in `outsideJob=[…]` | **RECORD ONLY**, never a stop |
| `started`, `seen`, `unseen` | Member counts; `unseen` = members too short-lived for the 250 ms poll | record; `started` is checked against the dry-pass value per step |
| `ctrlC`, `ctrlCCount` | Console Ctrl+C events the native guard caught in this PowerShell during the call | step 7 and P8 item 6 |

`verify` on the ledger line is one of:
- `OK` — every hard check is 0 and the evidence is complete;
- `HARDSTOP` — `escaped`, `memberMismatch` or `consoleForeign` is non-zero. **Stop the whole rehearsal**, record
  FAIL, keep the folder, and do not run it again on the capture host until the ledger line has been reviewed;
- `FAIL` — evidence missing (`evidence-missing:snapshot|console|job`, an inconsistent Job read, or a failed ledger
  write), **or `startedPin=DIFF` [v3.1: Q6]**. The step aborts; the rehearsal stops and is repeated later from step 1;
- `REFUSED` — nothing was launched (shared console, or Windows below 10). Close the console and restart from step 1
  in a new console and a new scratch folder.

**How the record-only metric and the hard-stop rule fit together.** The rule is about *causation*. There are only
three ways the rehearsal could end, or leave running, a process outside its own Job, and each has its own check:
1. **The Job close itself.** Closing a Job can end only that Job's members. That is an OS invariant, and the scripts
   contain no other stop call (P8 item 5's static check). So a Job close can never cause an outside exit.
2. **A process the rehearsal started that left the Job** (a breakaway, or a launch outside `c3_run.ps1`). That
   process, and everything it starts, is by definition created after the launch by a PID the Job held. It is counted
   in `escaped`, whether it is still running or has already ended. And `memberMismatch` proves that every member the
   Job ever had is accounted for, as either ended or gone at the close.
3. **A console broadcast** (the operator's Ctrl+C or Ctrl+Break) reaching a process that shares the console. M3
   refuses to launch unless the console is exclusive, and `consoleForeign` proves it is still exclusive at close.

What is left in `vanishedOutsideJob` is, by construction, a process the rehearsal had no route to: not a member, not
a descendant of a member, not on this console. On a busy host such processes come and go every second. The
workstation self-test, on an idle desk, recorded 0–5 per call: `cmd.exe`, `conhost.exe`, `powershell.exe` and
`git.exe` children of an unrelated process. On the capture host the one-minute S4U guard and collector subprocesses
will show up too. The v3 review's re-run on a busy workstation saw 14–16 per call. That is why the metric is recorded,
never a stop. If a reviewer finds an `outsideJob` entry whose
`ppid` is a rehearsal PID, it would already be in `escaped`. The ledger keeps the list so that this reasoning can be
audited after the fact.

**Not visible to `escaped` [v3.1: N1].** A process that a *service* creates on a member's request (WMI
`Win32_Process.Create`, the Task Scheduler, a COM LocalServer, `ShellExecute` with RunAs) has the service as its
parent. No rehearsal script or tree code on the path does this: the static scan forbids `wmic` and
`Invoke-CimMethod`, and the harness, runner and Job helper use only `CreateProcess`/`Popen`. The one realistic case,
a crash's `WerFault.exe`, is harmless, and nothing ends it.

**Timing residual [v3.1: M1].** A member born after the late PID read and ended by the close could be in the
after-close snapshot for a moment. That window is now microseconds wide, and it is fail-closed.

**Residual.** A member that lived for less than one 250 ms poll (`unseen > 0`) and started a process that broke away
before ending would be missed, unless that process's own parent chain reaches a seen PID. No rehearsal code asks for
breakaway: the C3 Job sets no breakaway flag, and the venv launcher's silent breakaway stops at the C3 Job. The
self-test observed the venv launcher and the real interpreter both inside the Job (`started=2` for one `python.exe`
call).

## Preconditions (abort the rehearsal if any fails)

- [ ] P1. `STATE_OF_PLAY.md` still says no live trading. This rehearsal needs no authorization and grants none.
- [ ] P2. The tree under test contains PR #230: `tests/operations/live_launcher_break_harness.py`,
      `tests/operations/test_live_runner_console_guards.py`, and the stdin change in the runner.
      - For the **official record** this is the production checkout `C:\Users\micha\Desktop\github\weather` after
        #230 lands (and before any reseal).
      - For a dry pass it is the #230 worktree on the 32 GB workstation (§ "Host paths").
      - Record which, with `git -C $tree rev-parse HEAD`. Abort if `git -C $tree --no-optional-locks status --short` is not empty. (`--no-optional-locks` keeps `git` from
        rewriting the checkout's `.git\index` [v3.1].)
- [ ] P3. Host: the host that will run the live session. That is the capture host for `capture_colocated_v1`,
      or the 32 GB workstation for `portable_execution_v1`.
      - On the capture host use the § "Host slot" **[v3.1]**: owner-attended, 09:00–09:30 (stop if 8a has not started
        by 09:20), or 05:10–05:55 on a night with no landing. Never 09:30–11:55, 12:00–18:00 or 18:00–00:30. Never
        during a merge, **and never while anything writes the production checkout** (step 8 read-locks one checkout
        file for up to about 130 s) [v3.1: N6].
      - The rehearsal is light (a handful of short processes) and holds no lease, but it must not overlap heavy
        work.
      - **Every rehearsal process (P8 items 2 and 6, and steps 3–8) is started through `c3_run.ps1`, and nothing is
        ever stopped by name or start time** (the cleanup rule above). The only processes started outside it are
        one-shots that exit on their own: `git rev-parse`/`status`, `Get-FileHash` (**[F1]** the step-3 `sysconfig`
        query is gone; step 3 computes the path in PowerShell), and **[v3: N2]** the `csc.exe` and `cvtres.exe` that `Add-Type` runs as children of this console the first
        time `c3_run.ps1` loads in it.
- [ ] P4. A real interactive console, **opened directly for this rehearsal and for nothing else** **[v3: M3, M4]**:
      - **Win+R**, then `powershell.exe -NoProfile`, then Enter (its parent is `explorer.exe`); **or**
      - a Windows Terminal profile whose command line is exactly `powershell.exe -NoProfile` (its parent is
        `WindowsTerminal.exe` or `OpenConsole.exe`).
      - Never type `powershell.exe` inside another shell. Never reuse a window in which anything else was started
        (a worker, a tool, a recovery command). `c3_run.ps1` refuses a shared console anyway.
      - It runs **Windows PowerShell 5.1**, the session you are physically typing into. An RDP session is acceptable
        only if it is the interactive session. A disconnected session or a scheduled task is not.
      - Run every command, including `c3_run.ps1` (invoked with `&`), **inside this one PowerShell process**.
      - If script execution is blocked, run `Set-ExecutionPolicy -Scope Process Bypass -Force` in this console
        only. It applies to this process and ends when the console closes.
- [ ] P5. No credential material anywhere near. List names only, never values:
      `(Get-ChildItem Env:).Name | Where-Object { $_ -match 'WEATHER|POLY|CLOB|KEY|SECRET|TOKEN|PRIVATE' }`.
      - Expect no credential-shaped name. Any such name is a **hard abort** **[v3: N7]**: every child inherits
        this console's whole environment.
      - You have not run the credential import, discovery or manifest build.
      - Nothing here opens `.env*`, `*.cred`, `*.key`, `*.pem` or `config/local/*`.
- [ ] P6. A new, empty scratch folder `C:\c3\<date>\`.
      - It must contain **no** `.py` file named after a standard-library module (the `bisect.py` trap).
      - All scripts, run folders, markers and the ledger live there. Nothing is written under the repository or
        `data\`.
- [ ] P7. `(Get-Volume -DriveLetter C).SizeRemaining` is greater than 5 GiB. The rehearsal writes kilobytes; this
      is a host check.
- [ ] P8. Done **after step 1**, in the step-1 console. Write down and pin:
      - the tree path and HEAD, host name, console program, `$PSVersionTable.PSVersion`;
      - the Windows version from `[Environment]::OSVersion.Version` and from `cmd /c ver`. **Abort if below 10.0**
        **[v3: N1]**: `PROC_THREAD_ATTRIBUTE_JOB_LIST` needs Windows 10. (`c3_run.ps1` also refuses on its own
        `RtlGetVersion` reading);
      - the `python.exe` path and SHA-256: `Get-FileHash $py`.

      Then create the scripts and pin them:
      1. Save the six scripts in § "Scripts" into `C:\c3\<date>\`, substituting `<tree>`, `<venv>` and `<date>` with
         the § "Host paths" values. Leave `<PROMPT_SHA256>` in `c3_prompt_launcher.ps1` for now. **[v3: N3]** Do not
         edit `c3_run.ps1` after this point. If it must change, close the console and start again from step 1.
      2. Set the session variables and helpers, and extract the prompt hash. This is the first `c3_run.ps1` call in
         this console:

         ```powershell
         # Capture host (official record). Dry pass on the workstation: use the § "Host paths" dry-pass values instead.
         $tree = 'C:\Users\micha\Desktop\github\weather'
         $py   = 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe'
         $c3   = 'C:\c3\<date>'
         $env:PYTHONDONTWRITEBYTECODE = '1'      # [v3.1: M3] no .pyc anywhere; -I children use -B instead
         $c3Start = Get-Date                     # for the step-9 .pyc check
         function New-C3RunDir([string]$name) { $d = Join-Path $c3 $name; if (Test-Path $d) { throw "run folder exists: $d" }; (New-Item -ItemType Directory -Path $d).FullName }
         function Get-C3Ledger([string]$label) {
             $l = @(Get-Content "$c3\launch-ledger.txt" | Where-Object { $_ -match (' label=' + [regex]::Escape($label) + ' ') })
             if ($l.Count -ne 1) { throw "expected exactly one ledger line for $label, found $($l.Count)" }
             $h = @{}; foreach ($m in [regex]::Matches($l[0], '(\w+)=(\[[^\]]*\]|\S+)')) { $h[$m.Groups[1].Value] = $m.Groups[2].Value }; $h
         }
         function Test-C3Contained([hashtable]$row) {   # the containment verdict (§ "Containment verdict")
             $row.verify -eq 'OK' -and $row.escaped -eq '0' -and $row.memberMismatch -eq '0' -and $row.consoleForeign -eq '0' -and $row.startedPin -ne 'DIFF'
         }
         & "$c3\c3_run.ps1" -Label p8-prompt-hash -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 60 `
             -Tokens @('-I','-S','-B',"$c3\c3_prompt_child.py",$tree,'--hash-only')
         ```

         Expected: JSON with one entry per template. The two `prompt_until_sha256` values are **equal**, and the
         last line is `C3 PROMPT EXTRACTION OK`. **[v3: N5]** Compare the value with the reviewed
         `c03caf8cbe6114c2c42ff216c49e8c2b6453f57f29ed2ea12146b40cffd44597` (`f9063256e`). A different value needs a
         reviewed template diff before the rehearsal continues, not just a new record.
         **Abort** if the run exits non-zero, the two hashes differ, either template lacks exactly one top-level
         `_prompt_until`, or the `C3RUN p8-prompt-hash` line is not `verify OK`. **HARD STOP** if it shows
         `escaped>0`, `memberMismatch≠0` or `consoleForeign>0`. `vanishedOutsideJob` and `pidReuse` are recorded only. (This call is unpinned: `k` is not known yet.)
      3. Put that hash in place of `<PROMPT_SHA256>` in `c3_prompt_launcher.ps1`.
      4. Pin all scripts, plus the tree's Job helper that the step-8 stub dot-sources **[v3: N4]**:

         ```powershell
         $files = 'c3_run.ps1','c3_break.py','c3_ctrlc.py','c3_prompt.py','c3_prompt_child.py','c3_prompt_launcher.ps1'
         $pin = [ordered]@{ tree = $tree; head = (git -C $tree rev-parse HEAD); prompt_until = '<hash from 2>'
                            job_helper = (Get-FileHash (Join-Path $tree 'scripts\ops\windows_kill_on_close_job.ps1') -Algorithm SHA256).Hash.ToLower() }
         foreach ($f in $files) { $pin[$f] = (Get-FileHash (Join-Path $c3 $f) -Algorithm SHA256).Hash.ToLower() }
         $pin | ConvertTo-Json | Set-Content -Encoding ascii "$c3\p8-pins.json"; Get-Content "$c3\p8-pins.json"
         ```

         Copy `p8-pins.json` into the paper record now. Steps 5–8 use these pins.
      5. Static cleanup check **[v3: N6, widened]**. The first command must print **nothing**; any line is an abort.
         The second must print exactly **one** line, inside `Get-C3Snapshot` in `c3_run.ps1`:

         ```powershell
         Select-String -Path "$c3\*.ps1","$c3\*.py" -Pattern 'Stop-Process|taskkill|Get-Process|wmic|TerminateProcess|TerminateJobObject|StartTime|os\.kill|\.kill\(|\.terminate\(|send_signal|GenerateConsoleCtrlEvent|psutil|Stop-Job|Remove-Job|Invoke-CimMethod'
         Select-String -Path "$c3\*.ps1","$c3\*.py" -Pattern 'Get-CimInstance|Win32_Process'
         ```

         The scratch scripts contain no name, time or PID stop path. The step-7 sentinel uses `signal.signal`, not
         `send_signal`. Outside the scan by design: the harness's own `helper.kill()`, the runner's `terminate()`,
         and the dot-sourced `windows_kill_on_close_job.ps1` (its `TerminateProcess` acts only on its own
         just-created suspended child when assignment fails, and `$job.Dispose()` closes its own Job). All of these
         live in the pinned tree, act only on processes they created, and run inside the C3 Job.
      6. **Guard self-test [v3: B1].** It proves that the native Ctrl+C guard still works on the **second** call in
         this console, which is exactly where v2's guard broke. Run both commands; press nothing during the first:

         ```powershell
         $g = "import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);print('C3 GUARD STUB READY',flush=True);time.sleep(10)"
         & "$c3\c3_run.ps1" -Label p8-guard-1 -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 30 -Tokens @('-I','-S','-B','-c',$g)
         $k = [int](Get-C3Ledger 'p8-guard-1').started       # [v3.1: M2] this host's processes per python.exe call
         if ($k -notin 1,2) { throw "k=$k is not 1 or 2: abort (unexplained venv layout)" } else { "k=$k" }
         & "$c3\c3_run.ps1" -Label p8-guard-2 -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 30 -ExpectStarted $k -Tokens @('-I','-S','-B','-c',$g)
         ```

         During `p8-guard-2` only: wait for `C3 GUARD STUB READY`, press **Ctrl+C once**, then wait for its
         `C3RUN p8-guard-2 … verify` line. Then judge from the ledger:

         ```powershell
         $g1 = Get-C3Ledger 'p8-guard-1'; $g2 = Get-C3Ledger 'p8-guard-2'
         $ok1 = (Test-C3Contained $g1) -and $g1.rc -eq '0' -and $g1.ctrlC -eq 'False' -and $g1.ctrlCCount -eq '0'
         $ok2 = (Test-C3Contained $g2) -and $g2.rc -eq '0' -and $g2.timedOut -eq 'False' -and $g2.interrupted -eq 'False' -and $g2.ctrlC -eq 'True' -and $g2.ctrlCCount -eq '1' -and $g2.startedPin -eq 'OK'
         if ($ok1 -and $ok2) { 'C3 P8 GUARD SELF-TEST PASS' } else { 'C3 P8 GUARD SELF-TEST FAIL'; $g1; $g2 }
         ```

         **Pass criteria (all must hold):**
         - the `p8-guard-2` ledger line has `ctrlC=True ctrlCCount=1 interrupted=False timedOut=False rc=0`. **The
           second run is the one that matters.** A pass on run 1 alone proves nothing, because v2's guard also worked
           on the first call;
         - the `p8-guard-1` line has `ctrlC=False ctrlCCount=0 rc=0`;
         - both lines are contained: `verify=OK escaped=0 memberMismatch=0 consoleForeign=0`. `vanishedOutsideJob`
           is recorded only and is not a pass criterion;
         - **[v3.1: M2]** `k` = `started` on `p8-guard-1` is 1 or 2 (a copied interpreter gives 1; a venv launcher
           gives 2), and `p8-guard-2` has `startedPin=OK`. Write `k` in the paper record. From here on every call
           passes `-ExpectStarted`, and a difference is an ABORT (`verify=FAIL`), not a HARD STOP;
         - this PowerShell is still at its prompt (it was not stopped).

         **HARD STOP** if either line shows `escaped>0`, `memberMismatch≠0` or `consoleForeign>0`. **Abort** on
         any other failure. A missing `p8-guard-2` line, or `interrupted=True`, means the guard did not hold: the
         Job was closed by `finally` (that is contained) and this checklist cannot run on this host. Do not retry in
         the same console. After a timing slip (Ctrl+C pressed before `READY`), you may start once more from step 1
         in a new console and a new scratch folder.
      7. **Optional, dry pass only [v3.1: N9]:** one call whose grandchild, in the venv launcher's *nested* Job, is
         still alive when `-TimeoutSeconds` expires. It exercises the PID list for nested-Job members at a non-zero
         count:

         ```powershell
         $n = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(60)']);time.sleep(60)"
         & "$c3\c3_run.ps1" -Label p8-nested-alive -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 6 -ExpectStarted (2*$k) -Tokens @('-I','-S','-B','-c',$n)
         ```

         Expected: `exit=TIMEOUT`, `activeAtClose=4` (with `k=2`), `memberMismatch=0`, `stillAlive=0`, `verify OK`.
         Do not run it on the capture host; it adds nothing that the dry pass has not shown.

## Step 1 — open the console and prove it is a console **[v3: M4]**

Open the console as P4 says: **Win+R → `powershell.exe -NoProfile`**, or the dedicated Windows Terminal profile. Do
not open it from inside another shell. Then type:

```powershell
[Console]::IsInputRedirected; [Console]::IsOutputRedirected; $Host.Name; $PSVersionTable.PSVersion
$parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
(Get-CimInstance Win32_Process -Filter "ProcessId=$parent").Name
```

(The parent lookup is read-only, by this console's own PID.)

**Expected:** `False`, `False`, `ConsoleHost`, `5.1.x`. The parent is `explorer.exe` (Win+R), or
`WindowsTerminal.exe` or `OpenConsole.exe` (Terminal profile). `conhost.exe` is also accepted.

**Abort** if any value differs, and in particular if the parent is a shell (`powershell.exe`, `pwsh.exe`,
`cmd.exe`), `python.exe`, an agent process or a Scheduler service. The rehearsal would not be on an operator console,
and the console would be shared. The root-cause table shows the break works in every isolated context; the point
here is *this* console. (`c3_run.ps1`'s console check, M3, catches a nested shell independently.)

Then do P8's script items, including the item-6 guard self-test, in this same console.

## Step 2 — prove the template still starts the runner isolated

```powershell
$tmpl = Join-Path $tree 'scripts\ops\international_live_templates\fixed_session_launcher.ps1.tmpl'
Select-String -Path $tmpl -Pattern '^\s*"-I",$|^\s*"-S",$|^\s*"-B",$|runpy.run_module' | ForEach-Object { $_.LineNumber.ToString() + ': ' + $_.Line.Trim() }
```

**Expected:** four lines.
- `"-I",`, `"-S",` and `"-B",` (lines 141–143 at `f9063256e`).
- The one-line bootstrap, ending in
  `runpy.run_module('weather.operations.international_live_session_runner',run_name='__main__')`.

**Abort** if `-I` or `-S` is absent, or if the bootstrap differs from `BOOTSTRAP` in
`tests/operations/live_launcher_break_harness.py` plus that `run_module` call. (The guard test
`test_the_break_harness_starts_the_runner_exactly_as_the_template_does` would also fail.)

## Step 3 — prove the production shape loads neither console-silencing patch

```powershell
$env:WEATHER_FIXED_SESSION_SRC = Join-Path $tree 'src'
# [F1] The template's own rule, <venv>\Lib\site-packages. NEVER derive it from sysconfig under -I -S: without
# site, sys.prefix is the BASE install, so purelib is the base site-packages (ModuleNotFoundError: requests).
$env:WEATHER_FIXED_SESSION_SITE_PACKAGES = Join-Path (Split-Path -Parent (Split-Path -Parent $py)) 'Lib\site-packages'
if (-not (Test-Path -LiteralPath $env:WEATHER_FIXED_SESSION_SITE_PACKAGES -PathType Container) -or ((Get-Item -LiteralPath $env:WEATHER_FIXED_SESSION_SITE_PACKAGES -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'venv site-packages missing or a reparse point: abort' } else { $env:WEATHER_FIXED_SESSION_SITE_PACKAGES }
Remove-Item Env:WEATHER_ALLOW_CONSOLE_CHILDREN -ErrorAction SilentlyContinue
$env:PYTHONPATH = $tree      # R7: -I must ignore it
$probe = "import os,runpy,sys;sys.dont_write_bytecode=True;sys.path.insert(0,os.environ['WEATHER_FIXED_SESSION_SRC']);sys.path.append(os.environ['WEATHER_FIXED_SESSION_SITE_PACKAGES']);import json,subprocess;before=subprocess.Popen;import weather.operations.international_live_session_runner as r;print(json.dumps({'patched': subprocess.Popen is not before or bool(getattr(subprocess.Popen,'_weather_silent_windows_children',False)),'silencer':'weather.operations.windows_silent' in sys.modules,'sitecustomize':'sitecustomize' in sys.modules,'runner':r.__file__}))"
& "$c3\c3_run.ps1" -Label s3 -Exe $py -WorkingDirectory $tree -TimeoutSeconds 60 -ExpectStarted $k -Tokens @('-I','-S','-B','-c',$probe)
Remove-Item Env:PYTHONPATH
```

**[F1]** The site-packages path is computed in PowerShell from `$py`; no process is started for it. It must print
`<venv>\Lib\site-packages` and exist. Steps 5, 6, 7 and 8 inherit this variable: `c3_break.py` and `c3_ctrlc.py run`
reset `sys.prefix` to the venv (as `site.venv()` would) before the harness import and **assert** that the harness's
`sysconfig` purelib equals it; step 8's bootstrap appends it directly.

**Expected:**
- `{"patched": false, "silencer": false, "sitecustomize": false, "runner": "<tree>\src\weather\operations\international_live_session_runner.py"}`
- `C3RUN s3 … startedPin=OK … verify OK` (`started` = `k`) [v3.1: M2, Q6].

**Abort** if any flag is `true` or the runner path is not under `<tree>`: the live path would silence its own
child. This is `test_runner_import_under_isolation_leaves_popen_unpatched`, run by hand on this host, with
`PYTHONPATH` set as the guard test sets it. **Abort** if `verify` is not `OK` (this includes `startedPin=DIFF`). **HARD STOP** on `escaped>0`,
`memberMismatch≠0` or `consoleForeign>0`. `vanishedOutsideJob` and `pidReuse` are recorded only.

## Step 4 — negative control: the failure mode is reproducible here

```powershell
$env:PYTHONPATH = $tree
# [v3.1: M3] -B, and PYTHONDONTWRITEBYTECODE=1 from P8 item 2: this is the one run without -I in the production tree
& "$c3\c3_run.ps1" -Label s4 -Exe $py -WorkingDirectory $tree -TimeoutSeconds 60 -ExpectStarted $k -Tokens @('-B','-c',"import json,subprocess,sys;print(json.dumps({'patched': bool(getattr(subprocess.Popen,'_weather_silent_windows_children',False)),'sitecustomize':'sitecustomize' in sys.modules}))")
Remove-Item Env:PYTHONPATH
```

**Expected:** `{"patched": true, "sitecustomize": true}`.

If it prints `false`, do **not** abort, but record it. It means the host cannot reproduce the silencing (for
example, `WEATHER_ALLOW_CONSOLE_CHILDREN` is set machine-wide), so step 6b is expected to behave differently. The
positive steps still stand.

**Abort** if `verify` is not `OK` (this includes `startedPin=DIFF`). **HARD STOP** on `escaped>0`, `memberMismatch≠0` or
`consoleForeign>0`. `vanishedOutsideJob` and `pidReuse` are recorded only.

## Step 5 — cooperative Ctrl+Break at the sealed deadline (the BREAK marker)

**Before the first repetition [v3: N5, N6]:** print `p8-pins.json`, compare it line by line with the paper copy, and
re-run the P8 item 5 static check. Abort on any difference or any line.

`c3_break.py` runs the **real** runner's `_default_launcher_runner` through the #230 harness:
- in a helper started with the production flags and bootstrap;
- sharing this console;
- with the caller's stdin held open (R6).

The harness's stub launcher registers a `DebuggerStop` handler and writes `START`, `BREAK` and `EXIT` markers. It
exits 3 on its own only `tail` seconds after the deadline.

Each repetition gets its own new run folder:

```powershell
foreach ($n in 1..3) {
  $d = New-C3RunDir "s5-$n"
  & "$c3\c3_run.ps1" -Label "s5-$n" -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 120 -ExpectStarted (2*$k+1) `
      -Tokens @('-I','-S','-B',"$c3\c3_break.py",$tree,$d,'s5','positive')
}
```

**Expected output** for each repetition (values vary; the shape and the asserts do not):

```
{"step": "s5", "mode": "positive", "rc": 0,
 "outcome": {"deadline_ms": ..., "release_ms": ..., "raised": true, "cooperative": true, "forced": false,
             "exit_code": 3, "popen_silenced": false, "sitecustomize_loaded": false,
             "elapsed_s": 3.5-5.0, "returned_ms": ..., "runner_file": "<tree>\\src\\...\\international_live_session_runner.py",
             "child_stdin": ["-3"]},
 "events": [["START", t0], ["BREAK", t1], ["EXIT", t2]], "break_lag_ms": ..., "work": "C:\\c3\\<date>\\s5-1\\c3-s5-positive-..."}
C3 STEP 5 PASS
C3RUN s5-1 exit=0 started=5 startedPin=OK ended=5 memberMismatch=0 escaped=0 consoleForeign=0 stillAlive=0 ctrlC=False/0 peakActive=5 peakJobPrivateMB=… pidReuse=0(record-only) vanishedOutsideJob=N(record-only) verify OK
```

Checks to read off the output:
- `events` shows `START` before `deadline_ms`, then `BREAK` **between** `deadline_ms` and `release_ms`, then `EXIT`.
  On the workstation the break landed 26–102 ms after the deadline.
- `raised: true`, `cooperative: true`, `forced: false`, `exit_code: 3`.
- `child_stdin: ["-3"]`, which is `subprocess.DEVNULL` (the #229 stdin change).
- `sitecustomize_loaded: false` and `popen_silenced: false`.
- `returned_ms - deadline_ms` well under `TAIL + MARGIN` = 8 s (typically under 1 s).
- The `C3RUN` line is `verify OK` with `startedPin=OK`: `started` = `2k+1` (5 when `k=2`): a launcher and an
  interpreter each for the driver and the helper, plus the stub `powershell.exe` **[v3.1: M2]**. Record
  `peakActive` and `peakJobPrivateMB`.

**Abort** (the rehearsal FAILS; record it; no live attempt) if any of these occur:
- no `BREAK` marker;
- `forced: true`;
- `exit_code` is not 3;
- `child_stdin` is not `["-3"]`;
- any assert in `assert_cooperative_break` raises;
- the helper printed no `OUTCOME` line;
- the `C3RUN` line is not `verify OK` (including `startedPin=DIFF`).

**HARD STOP** on `escaped>0`, `memberMismatch≠0` or `consoleForeign>0` on any repetition. `vanishedOutsideJob` and
`pidReuse` are recorded only.

Do not hunt for leftover processes. `c3_run.ps1` has already closed the run's Job; its `C3RUN` line and the ledger
are the leftover check.

All three repetitions must pass. (The root-cause evidence used 4–6 repetitions per context.) Optionally, run one
more repetition with stdin closed (`… s5 positive-stdin-closed`) and record it.

## Step 6 — the detectors detect (mutants)

6a. Run:

```powershell
$d = New-C3RunDir 's6a'
& "$c3\c3_run.ps1" -Label s6a -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 120 -ExpectStarted (2*$k+1) -Tokens @('-I','-S','-B',"$c3\c3_break.py",$tree,$d,'s6a','no_break')
```

**Expected:** `events` has `START` and `EXIT` but **no** `BREAK`. `outcome.cooperative` may still read `true`,
because the stub exited on its own at release. That is exactly the false "cooperative" the marker exists to
expose.

**Abort** if a `BREAK` marker appears: the marker is spurious on this host, and step 5 proved nothing.
**[F1 Defender N1]** Also abort (for 6a and 6b) if the driver printed no JSON, or `outcome` is `null` (for example an F1
assert traceback); 6a additionally requires both `START` and `EXIT` in `events`.

6b. **[F3 Defender MUST-FIX 1] Do not run 6b here. Run it as the LAST `c3_run.ps1` call, after step 8 and before
step 9** (step 8d below). The 6b Ctrl+Break leaves a stale console-list entry that lasts as long as the console. If its
PID were reused by any host process, every later call would be falsely REFUSED or HARD STOPPED. Running 6b last
leaves no later call exposed. The commands and expectations are listed here; the run happens at 8d:

```powershell
# [F3 S-F3a] pin from step 4: 2k+2 when step 4 printed "patched": true (the silenced stub has its own conhost),
# 2k+1 when it printed "patched": false (the stub shares the console: no conhost, no stale entry).
$pin6b = 2*$k+2          # set to (2*$k+1) ONLY if step 4 printed "patched": false
$d = New-C3RunDir 's6b'
& "$c3\c3_run.ps1" -Label s6b -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 120 -ExpectStarted $pin6b -Tokens @('-I','-S','-B',"$c3\c3_break.py",$tree,$d,'s6b','sitecustomize')
```

**Expected:** no `BREAK`; `outcome.sitecustomize_loaded: true` and `popen_silenced: true`. This mutant's helper runs
without `-I` and `-B` against the production tree; it inherits `PYTHONDONTWRITEBYTECODE=1` (P8 item 2), so it writes
no `.pyc` there **[v3.1: M3]**.

**[F3]** 6b is pinned at `2k+2`: the silenced stub's own `conhost.exe` is the extra Job member. The C3RUN line shows
`consoleStale=[close:<stub PID>]` (the Ctrl+Break leaves a stale console-list entry; record-only, see [F3] above).

If step 4 showed the patch cannot load here, expect a `BREAK` instead, and record "6b not reproducible on this
host". That is not an abort. Use `$pin6b = 2*$k+1` (S-F3a), so the line is still `verify OK`; `consoleStale` is `[]`.

For both mutants, the `C3RUN` line must still be `verify OK`. A mutant's stub may still be in the Job at close, so
`activeAtClose` greater than 0 is acceptable here. The close ends it, and `memberMismatch` must still be 0.
**Abort** if `verify` is not `OK` (this includes `startedPin=DIFF`). **HARD STOP** on `escaped>0`, `memberMismatch≠0` or
`consoleForeign>0`. `vanishedOutsideJob` and `pidReuse` are recorded only.

## Step 7 — operator interrupt: Ctrl+C at the console is delivered and ends cooperatively **[v3: B1, B2]**

> **Press Ctrl+C once, then wait.** A second Ctrl+C during the runner's cleanup interrupts its cleanup loop.
> That turns a cooperative shutdown into a forced kill (the kill-on-close Job tears the launcher down, and no
> receipt fields are written). Do not press Ctrl+Break either.

What this step proves, exactly:
- **Delivery.** A sentinel process records the console `SIGINT` with a timestamp **[v3: B2]**. It is a child of
  the driver, inside the C3 Job, on the same console and in the same process group as the harness helper and the
  runner, so it sees exactly the event they see. The driver never stops it; it exits on its own after
  `ALLOWANCE + GRACE` = 32 s, and the Job is the backstop.
- **Containment of this PowerShell.** The native guard caught the same keypress, so `c3_run.ps1` kept waiting
  and did not close the Job early (`ctrlC=True ctrlCCount=1 interrupted=False` on the ledger line) **[v3: B1]**.
- **Cooperative outcome.** The step-5 asserts: `BREAK` between deadline and release, `cooperative: true`,
  `forced: false`, `exit_code: 3`.

What it does **not** prove [v3: N8, corrected text]: on CPython 3.11 the runner's `Popen.wait(timeout)` is a
non-alertable `WaitForSingleObject`, so a console Ctrl+C does not wake it. The runner raises `KeyboardInterrupt` only
when the wait returns, at the sealed deadline, into the same branch as a timeout. The interrupt is therefore honoured
**at the deadline**, not at the keypress. `honoured` is recorded for information only (`at_keypress` would indicate a
different interpreter). The launcher child is created with `CREATE_NEW_PROCESS_GROUP`, which disables Ctrl+C for its
group, so the stub itself does not see the keypress. The pilot runbook's statement that console interrupts enter the
cleanup path is about the Python wrapper (the Stage 0/1 templates), which is not part of this keyless stub.

`c3_ctrlc.py` ignores Ctrl+C itself (`SIG_IGN` is its first statement; Python handlers are not inherited, so the
helper, the runner and the sentinel still receive the event). Its allowance is 20 s. Every run uses a new run folder,
and the work-folder prefix `c3-s7-ctrlc-`, so no marker from steps 5 and 6 can match.

**7.0 Control (mandatory; press nothing) [v3: B2].** It shows the sentinel is not spurious and the no-keypress path
is distinguishable:

```powershell
$d = New-C3RunDir 's7-control'
& "$c3\c3_run.ps1" -Label s7-control -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 150 -ExpectStarted (3*$k+1) `
    -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'run',$tree,$d,'control')
$w = @(Get-ChildItem -Path $d -Directory -Filter 'c3-s7-ctrlc-control-*' | ForEach-Object { $_.FullName })   # [F4] not @(...).FullName
if ($w.Count -ne 1) { throw "expected exactly one control work folder, found $($w.Count)" }
& "$c3\c3_run.ps1" -Label s7-control-judge -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 60 -ExpectStarted $k `
    -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'judge',$tree,$w[0],'s7-control','control')
```

**[F4, 2026-10-07 workstation dry pass]** v3.1 wrote `$w = @(Get-ChildItem …).FullName`. With exactly one folder,
member enumeration returns a **string**, so `$w.Count` is 1 and `$w[0]` is its first character (`C`); the judge then
refused `C:\c3\<date>\C` ("not this step's work folder", exit 2). It failed closed but would have voided step 7. The
line now collects the names with `ForEach-Object`, which keeps an array.

**Expected:** `C3 STEP 7 CONTROL PASS`. The sentinel has `READY` and `DONE` and **no** `SIGINT`; the ledger line for
`s7-control` has `ctrlC=False ctrlCCount=0 verify=OK`; and the step-5 shape holds (the runner timed out at the
deadline and broke cooperatively).

**7.1 Operator run:**

```powershell
$d = New-C3RunDir 's7-1'
& "$c3\c3_run.ps1" -Label s7-1 -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 150 -ExpectStarted (3*$k+1) -WatchMarkersUnder $d `
    -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'run',$tree,$d,'operator')
```

1. Wait for the wrapper's line
   `C3RUN s7-1: START and sentinel READY seen in <work> - press Ctrl+C ONCE now, then wait.`
   It appears about 1–2 s after launch, and only for this run's folder.
2. Within 15 s, press **Ctrl+C once**. Then keep your hands off the keyboard until the `C3RUN s7-1 … verify` line.
   Expect the wait to last until the 20 s deadline, plus cleanup and the sentinel's 32 s window.
3. Judge it from the files and the ledger. **This is the step's verdict:**

   ```powershell
   $w = @(Get-ChildItem -Path $d -Directory -Filter 'c3-s7-ctrlc-*' | ForEach-Object { $_.FullName })   # [F4] not @(...).FullName
   if ($w.Count -ne 1) { throw "expected exactly one work folder, found $($w.Count)" }
   & "$c3\c3_run.ps1" -Label s7-1-judge -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 60 -ExpectStarted $k `
       -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'judge',$tree,$w[0],'s7-1','operator')
   ```

**PASS** only if the judge prints `C3 STEP 7 PASS`, which requires **all** of:
- the step-5 asserts (`assert_cooperative_break` with the 20 s allowance);
- `sentinel.txt`: exactly one `READY`, exactly one `DONE`, and **exactly one** `SIGINT t` with
  `READY < t`, `START < t < deadline_ms`;
- exactly one ledger line for `s7-1`, with `rc=0 timedOut=False interrupted=False ctrlC=True ctrlCCount=1
  verify=OK escaped=0 memberMismatch=0 consoleForeign=0`.

Anything else is `C3 STEP 7 FAIL` [v3: B2, binary verdict]. There is no "explained" exception. A plain timeout cannot
pass: with no keypress the sentinel has no `SIGINT` and the ledger has `ctrlC=False`.

**Repeat rule (bounded).** The judge prints `operator_timing_only: true` when every failure is one of: no `SIGINT`
or more than one, a `SIGINT` outside the window, or a ledger `ctrlCCount` other than 1 while the sentinel also
recorded no single in-window `SIGINT`. Only then may you repeat **once**, as `s7-2` in a new folder (same commands,
labels `s7-2` and `s7-2-judge`). A second FAIL is step 7 FAIL. Never run a third time. Every other FAIL is a step 7
FAIL at once.

**A double press [v3.1: N4, corrected].** Two presses *inside the runner's wait* give one `KeyboardInterrupt` at the
wait's return, a cooperative outcome, two sentinel stamps and `ctrlCCount=2`. The judge classes that as timing-only,
so the one repeat applies. Only a second press that lands *during the runner's cleanup loop* turns the outcome into
`forced: true`, which is a step 7 FAIL at once.

**Do not press Ctrl+Break yourself.** Ctrl+Break from the keyboard reaches every process on the console. The guard
lets it fall through, so PowerShell may stop at a `[DBG]` prompt; type `c` and Enter. The driver and the sentinel end,
and the stub is ended by kill-on-close containment. The judge prints `C3 STEP 7 FAIL`. That is containment working,
not the path being rehearsed. The `C3RUN` line must still be `verify OK`; the repeat rule decides whether one repeat
is allowed (it is not timing-only, so it is not).

**Abort** if any of these occur:
- the judge prints `C3 STEP 7 FAIL` (after the repeat rule) or `C3 STEP 7 CONTROL FAIL`;
- the run did not return within `TimeoutSeconds`;
- any `C3RUN` line in this step is not `verify OK`, including `startedPin=DIFF` (the runs expect `3k+1`, which is 7
  when `k=2`: the step-5 five plus the sentinel's launcher and interpreter; the judges expect `k`) [v3.1: M2].

**HARD STOP** on `escaped>0`, `memberMismatch≠0` or `consoleForeign>0` on the run or on the judge. `vanishedOutsideJob`
and `pidReuse` are recorded only.

## Step 8 — the confirmation prompt accepts typed input with stdin on NUL

**Before 8a [v3: N5]:** print `p8-pins.json` and compare it with the paper copy again. **[v3.1: N6]** Confirm that
nothing will write the production checkout for the next few minutes (no merge, no pull, no scheduled checkout
write). Step 8 read-locks `scripts\ops\windows_kill_on_close_job.ps1` for up to about 130 s.

The production chain for the prompt:
1. the runner;
2. the inner fixed-scope launcher (`powershell -File`). Since #229 the runner starts it with
   `stdin=subprocess.DEVNULL` (runner line 363);
3. the Python wrapper, started by `Start-WeatherInteractiveProcessInJob` (`-I -S`). It shares the console. **[v3: M5]**
   It is created with `bInheritHandles=false` and no `STARTF_USESTDHANDLES`, so it does **not** reliably inherit the
   launcher's NUL stdin; what it gets is not the #229 evidence;
4. `_prompt_until`, which reads keys with `msvcrt.kbhit()`/`getwch()` from the console input buffer, not from stdin.

The rehearsal reproduces that chain:
- The stub launcher, `c3_prompt_launcher.ps1`, **first proves the #229 change at the right process [v3: M5]**: it
  prints `C3 STUB stdin_redirected=<bool>` from `[Console]::IsInputRedirected` and refuses (exit 7) unless it is
  `True`. Then it starts its child through the repository's own Job helper. (The workstation self-test showed that a
  `powershell.exe` started with `stdin=subprocess.DEVNULL` and `CREATE_NEW_PROCESS_GROUP`, as the runner starts it,
  reports `True`.)
- The stub wrapper, `c3_prompt_child.py`, **extracts `_prompt_until` at run time from both `stage0.py.tmpl` and
  `stage1_cancel_all.py.tmpl`**.
  - It requires the two extracted sources to be byte-identical and equal to the P8 pin.
  - It executes exactly that source. The only substitutions are a stub `SCOPE["run_not_after_local"]` (now +
    120 s) and `PRE_CREDENTIAL_RESERVE_SECONDS` = 30, which give a 90-second prompt window.
  - It records its own `stdin` state (`null`, `true`, `false` or `"unusable"`) **for information only**, and cannot
    crash on `sys.stdin is None` [v3: M5].
  - Nothing else from the templates runs. There is no hand copy.
- The driver, `c3_prompt.py`, calls the real `_default_launcher_runner` **only after** verifying all of the
  following:
  - the stub's resolved path is `C:\c3\<date>\c3_prompt_launcher.ps1` and is not a link;
  - the stub's SHA-256 equals the P8 pin;
  - the child's SHA-256 equals its P8 pin;
  - the tree's `scripts\ops\windows_kill_on_close_job.ps1` equals its P8 pin [v3: N4];
  - the stub names the child and contains no live reference.

  Otherwise it exits 9 without calling the runner. **[v3: N4]** It then passes all three files as
  `protected_files`. The runner takes deny-write handles, re-hashes the files, and holds the handles until it
  returns, which closes the time-of-check gap. A runner refusal there also exits 9.

The owner should record in the C3 entry that "the templates' `_prompt_until`, extracted by hash and reached through
the production process chain" meets the runbook's "reach that confirmation prompt". A keyless run of the real
wrapper needs a sealed manifest, which this rehearsal must not build.

Run (same environment as step 3, `PYTHONPATH` unset):

```powershell
$pin = Get-Content "$c3\p8-pins.json" -Raw | ConvertFrom-Json
$boot = "import os,runpy,sys;sys.dont_write_bytecode=True;sys.path.insert(0,os.environ['WEATHER_FIXED_SESSION_SRC']);sys.path.append(os.environ['WEATHER_FIXED_SESSION_SITE_PACKAGES']);p=sys.argv.pop(1);runpy.run_path(p,run_name='__main__')"
$s8 = @('-I','-S','-B','-c',$boot,"$c3\c3_prompt.py","$c3\c3_prompt_launcher.ps1",$pin.'c3_prompt_launcher.ps1',$pin.'c3_prompt_child.py',$pin.job_helper)
& "$c3\c3_run.ps1" -Label s8a -Exe $py -WorkingDirectory $tree -TimeoutSeconds 180 -ExpectStarted (2*$k+3) -Tokens $s8
```

The output appears in this order:
1. The driver's pin line: `{"stub": "C:\\c3\\<date>\\c3_prompt_launcher.ps1", "checks": {…all true…}}`.
2. The stub launcher's line: `C3 STUB stdin_redirected=True` [v3: M5].
3. The child's evidence line: `{"stdin": …, "sitecustomize": false, "prompt_bound": true, "prompt_until_sha256": {…both equal to the pin…}}`.
4. The prompt itself, printed by the extracted function: `Type C3_REHEARSAL_TYPED_INPUT_ACCEPTED to continue: `.

8a. Positive. Type the literal and press Enter.

**Expected**, in order:
- your characters echoed as you type (backspace works);
- `{"typed_matches": true, "length": 33}`;
- the driver's `{"returncode": 0, "raised": false}`;
- `C3RUN s8a … startedPin=OK … verify OK`: `started` = `2k+3` (7 when `k=2`): the driver's launcher and
  interpreter, the stub `powershell.exe`, the `csc.exe` and `cvtres.exe` that its `Add-Type` runs, and the child's
  launcher and interpreter [v3.1: M2]. If the dry pass shows that the stub's `Add-Type` spawns a different number of
  compiler processes on that host, abort and amend the formula by review. Do not adjust the pin at the console.

**Abort** if any of these occur:
- the pin line has any `false`, or the runner refused or failed (exit 9, `refused_by_runner` in the output)
  [v3.1: N8]. **Never** work around it by editing the pin; redo P8 from scratch in a new console;
- `C3 STUB stdin_redirected=False`, or the stub exits 7 [v3: M5]: the runner did not give the launcher NUL stdin,
  so the tree lacks #229;
- `prompt_bound` is `false` (exit 8);
- typed characters do not echo, or `kbhit` never sees them (the prompt would time out in production);
- `returncode` is not 0;
- the `C3RUN` line is not `verify OK` (including `startedPin=DIFF`).

The child's `stdin` value is information only and is **not** an abort criterion [v3: M5].

8b. Refusal. Run again with `-Label s8b` (same `-ExpectStarted`), and type `WRONG` and Enter.

**Expected:** `{"typed_matches": false, "length": 5}`, then `{"returncode": 4, "raised": false}`. A mistyped
literal fails closed.

**Abort** if `returncode` is 0, or the `C3RUN` line is not `verify OK`.

8c. Timeout (optional, 90 s). Run again with `-Label s8c` (same `-ExpectStarted`), and type nothing. On the capture
host, skip 8c if it would push the run past 09:25.

**Expected:** `{"typed_matches": null, "reason": "timeout"}`, then `returncode: 5`, before the driver's own 120 s
deadline. If the driver's deadline fires first, you will see `{"raised": true, "cooperative": true, …}`. That is
also acceptable; record which. **Abort** if the `C3RUN` line is not `verify OK`.

For 8a, 8b and 8c: **HARD STOP** on `escaped>0`, `memberMismatch≠0` or `consoleForeign>0`. `vanishedOutsideJob` and
`pidReuse` are recorded only.

8d. **[F3 MUST-FIX 1] Step 6b, run now as the last `c3_run.ps1` call** (commands and expectations under step 6). Run
it even if 8c was skipped. Then go straight to step 9 in the same console.

## Step 9 — record and verify cleanup

- [ ] **Containment, from the ledger [v3: M1, M2].** `Get-Content "$c3\launch-ledger.txt"`.
      - It has exactly one line per `c3_run.ps1` call. (The ledger write is in a `finally`, so a missing line means
        PowerShell itself died mid-call. That is a FAIL, though kill-on-close still applied.)
      - Every line has `verify=OK escaped=0 memberMismatch=0 consoleForeign=0`, and no line has `startedPin=DIFF`.
        Every line after `p8-guard-1` has `startedPin=OK`.
      - Check it mechanically [v3.1: Q6]:
        `Get-Content "$c3\launch-ledger.txt" | Where-Object { $_ -notmatch ' escaped=0 ' -or $_ -notmatch ' memberMismatch=0 ' -or $_ -notmatch ' consoleForeign=0 ' -or $_ -notmatch ' verify=OK ' -or $_ -match ' startedPin=DIFF ' }`
        must print nothing.
      - **[F3 MUST-FIX 1]** `consoleStale` is `[]` on every line except s6b, where it may be `[]` or exactly
        `[close:<one PID>]`. Any other value → **Abort** (record FAIL: an unexplained stale entry, or a console that
        was not fresh). Mechanically, this must print nothing:
        `Get-Content "$c3\launch-ledger.txt" | Where-Object { if ($_ -match ' label=s6b ') { $_ -notmatch ' consoleStale=\[(close:\d+)?\]( |$)' } else { $_ -notmatch ' consoleStale=\[\]( |$)' } }`
      - **HARD STOP** (record FAIL; no rerun on the capture host until reviewed) on any `verify=HARDSTOP` line, or
        any `escaped`, `memberMismatch` or `consoleForeign` other than 0. Report its `escapedList` and the whole
        line.
      - **Abort** (record FAIL) on any `verify=FAIL` (including `startedPin=DIFF`) or `verify=REFUSED` line.
      - **Record only:** the sum of `vanishedOutsideJob` and the `outsideJob` entries, the sum of `pidReuse`, and the
        per-call `peakActive` and `peakJobPrivateMB` (the § "Resource profile" figures, now MEASURED on this host).
        These are host noise or measurements by construction (§ "Containment verdict"). They are copied into the
        record and never fail the rehearsal.
      - The P8 static check printed nothing, both times.
- [ ] **No `.pyc` was written into the production checkout [v3.1: M3].** This prints nothing:
      `Get-ChildItem -LiteralPath "$tree\src","$tree\tests","$tree\scripts","$tree\__pycache__" -Recurse -Filter *.pyc -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $c3Start } | Select-Object -ExpandProperty FullName`.
      Any line is a P6 deviation: record step 9 FAIL with the paths. It is not a safety stop: source fingerprints are
      unaffected. (`venv\` is covered by `-B` and `PYTHONDONTWRITEBYTECODE` by construction, and is not walked.)
- [ ] No `c3_run.ps1` is still running in this console. Each one has returned and printed its `C3RUN … verify`
      line, so every Job it created is closed.
- [ ] Hash the evidence: `Get-FileHash "$c3\*.ps1","$c3\*.py","$c3\p8-pins.json","$c3\launch-ledger.txt"`,
      plus `Get-ChildItem $c3 -Recurse -Include markers.txt,helper-output.txt,helper-rc.txt,sentinel.txt | Get-FileHash`.
      Keep the folder; it is the record's evidence.
- [ ] Close this console [v3: N7]. `WEATHER_FIXED_SESSION_*`, the process-scope execution policy and the loaded
      C3 types live only in it.
- [ ] Write the record where the runbook says, by a docs-only PR on the light path: the "Gate before the first live
      attempt after PR #229" section of `INTERNATIONAL_MM_LIVE_PILOT.md`, or item 330. Include:
      - date, host, slot (start and end time), console program, Windows version, tree and HEAD;
      - the python SHA-256 and `p8-pins.json` (including the `_prompt_until` and Job-helper hashes);
      - the P8 guard self-test result (both ledger lines) and `k` [v3.1: M2];
      - step 5 ×3, with the `BREAK` lag in ms and `started` for each;
      - the 6a and 6b outcomes;
      - the step 7 control and operator outcomes: the sentinel `SIGINT` time relative to `START` and to the
        deadline, `ctrlCCount`, `honoured`, `elapsed_s`, and whether a repeat was used;
      - the 8a, 8b (and 8c) outcomes, with the `stdin_redirected` line;
      - the ledger verdict, the recorded `vanishedOutsideJob` and `pidReuse` totals, the peak `peakActive` and
        `peakJobPrivateMB`, the `.pyc` check, and the evidence hashes;
      - the operator's name.

      One line per step, `PASS`, `FAIL` or `NOT REPRODUCIBLE` only.
- [ ] If the record was produced on the #230 worktree and not the production checkout, it is a **dry pass**, not
      the record. Repeat on the production checkout after #230 lands and before the reseal. The official run pins
      `started` from its **own** `k` [v3.1: M2]; the dry pass only confirms the formulas (with `k=2`: 2, 5, 7, 7).
- [ ] Until that record exists, no live attempt is launched (runbook text). Every launcher sealed before #229 is
      stale and must be resealed anyway.

## Abort summary

Every row that launches anything also carries the containment rule: **HARD STOP** on `escaped>0`,
`memberMismatch≠0` or `consoleForeign>0`, which take precedence over everything else. **ABORT** (`verify=FAIL`) on
`startedPin=DIFF` [v3.1: Q6]. `vanishedOutsideJob` and `pidReuse` are **recorded only**, never a stop.

| Step | Abort when | HARD STOP when | Meaning |
| --- | --- | --- | --- |
| P1–P7 | Any precondition unmet; a credential-shaped variable name | — | Not a valid rehearsal |
| P8 items 1–5 | Windows below 10.0; prompt hashes differ across templates or from the reviewed value without a reviewed diff; the static check prints a line; `p8-prompt-hash` not `verify OK` | containment rule on `p8-prompt-hash` | Not a valid rehearsal |
| P8 item 6 | `p8-guard-2` lacks `ctrlC=True ctrlCCount=1 interrupted=False rc=0 startedPin=OK`; `p8-guard-1` not clean; `k` not 1 or 2; either line not `verify OK` | containment rule on either line | The guard does not hold on this host; step 7 cannot run |
| 1 | Not a console host; input redirected; parent is a shell | — | Wrong or shared console |
| 2 | The template lost `-I` or `-S`, or the bootstrap differs | — | The live path would load the silencer |
| 3 | Any flag `true`; not `verify OK` | containment rule | The live path silences its child |
| 4 | Not `verify OK` (a `false` result is recorded, not an abort) | containment rule | — |
| 5 | No `BREAK`; `forced`; exit code ≠ 3; stdin ≠ DEVNULL; asserts fail; any of 3 repetitions; not `verify OK`; `startedPin=DIFF` (≠ `2k+1`) | containment rule | Ctrl+Break does not reach the launcher on this console; live cleanup would be forced |
| 6a | `BREAK` present; not `verify OK` | containment rule | The marker is spurious; step 5 is void |
| 6b | Not `verify OK` | containment rule | — |
| 7 | Control: any `SIGINT`, or not PASS. Operator: `C3 STEP 7 FAIL` after the bounded repeat rule; not `verify OK`; `startedPin=DIFF` (≠ `3k+1`; judges ≠ `k`) | containment rule on the runs and the judges | The operator's Ctrl+C is not delivered, or does not end in cooperative cleanup |
| 8a | Pin refused, or the runner refused or failed (exit 9); `startedPin=DIFF` (≠ `2k+3`); `stdin_redirected=False` (exit 7); prompt not bound (exit 8); no echo; rc ≠ 0; not `verify OK` | containment rule | The prompt would not accept the literal in production, the tree lacks #229, or the rehearsal ran the wrong file |
| 8b | rc = 0 on a wrong literal; not `verify OK` | containment rule | Fail-open prompt |
| 8c | Not `verify OK` | containment rule | — |
| 9 | A missing ledger line; any `verify=FAIL`/`REFUSED` or `startedPin=DIFF`; a new `.pyc` in the checkout (P6); record not written | any `verify=HARDSTOP`, or any non-zero `escaped`/`memberMismatch`/`consoleForeign` | Cleanup unproven, or the rehearsal caused something outside its Job |

Any abort is recorded as a FAIL line with its step number. After the cause is fixed, the rehearsal is repeated
from step 1 in a new console and a new scratch folder, never resumed mid-way. After a HARD STOP, the ledger line is
reviewed before any rerun on the capture host.

## Runbook note (proposed text for `INTERNATIONAL_MM_LIVE_PILOT.md`, for #230 or a follow-up docs PR) **[v3: N8, reworded]**

Add after "Console interrupts and other process-level Python exits enter that same cleanup path":

> To interrupt a live session from the console, **press Ctrl+C once, then wait.** Do not press it again and do not
> press Ctrl+Break. The runner acts on the Ctrl+C only when its wait for the launcher returns, which can be as late as
> the session's sealed deadline: up to 120 s for `capture_colocated_v1` and 240 s for `portable_execution_v1`. It then
> sends Ctrl+Break to the launcher and polls for its cooperative exit. Nothing may appear to happen until then; that
> is expected. A second Ctrl+C during that polling interrupts the cleanup loop itself. The kill-on-close Job then
> tears the launcher down by force, and no cooperative receipt is written.

(Defender R9 also proposes masking `SIGINT` in the runner's cleanup loop. The Defender's answer to owner question 4
places that, with this runbook note, in a follow-up PR, not #230.)

## Workstation self-test result

### v3.1 re-run (the one permitted run) **[v3.1]**

Run once on 2026-10-07 at about 02:53 UTC, on the 32 GB workstation, in the same way as before: a new console
(`CREATE_NEW_CONSOLE`), stub processes only, scratch folder `C:\Users\Michael\AppData\Local\Temp\c3-selftest-20261006\v31run`,
and the workstation venv. The script under test was the v3.1 `c3_run.ps1` *before* the V31-R1 fix (SHA-256 `9ab7cb12…2d10bd`).
The driver (`selftest31.ps1`) derived `k` from `p8-guard-1`, then made four more calls: `p8-guard-2` (`CTRL_C_EVENT`,
`-ExpectStarted $k`), `p8-stdin` (`-ExpectStarted k+1`), `p8-pin-diff` (`-ExpectStarted 9`, meant to show
`startedPin=DIFF`), and `p8-nested-alive` (a nested-Job grandchild alive at a 6 s timeout).

**Result: FAIL, fail-closed. The guard works; the verification has a defect, V31-R1, which is now fixed.**

| Observation | Value |
| --- | --- |
| Guard (B1) | `p8-guard-2`: `rc=0 timedOut=False interrupted=False ctrlC=True ctrlCCount=1 guardRemoved=True`. The driver logged `DRIVER SURVIVED` after all five calls. **The native guard holds in v3.1** |
| `k` | `started=2` on `p8-guard-1` → `k=2`. Also `started=3` (`p8-stdin`) and `started=4` (`p8-nested-alive`), which agree with the formulas |
| Verification | **Every call: `verify=FAIL reason=evidence-missing`**, and the escape, foreign and pin fields were left at their defaults. Cause: the review's exact M1 edit, `$foreign = if ($null -eq $consoleNow) { $null } else { @(…) }`. PowerShell unrolls the empty array returned from the `else` branch to `$null`, so a clean console (no foreign PID, the normal case) looked like a failed console query. Confirmed with a pure-language check (`$x = if ($false) {$null} else { @() }` gives `$null`; assigning inside the branch gives an empty array) |
| Containment | Fail-closed as designed: no HARD STOP, no `verify OK`. Afterwards, a read-only query found no process whose command line referenced the scratch folder or the grandchild's `time.sleep(60)`, so the nested-Job grandchild was ended by the Job close (N9) |
| Resource figures | Recorded in § "Resource profile" (`peakJobPrivateMB` 8.7 / 60.9 / 12.7 MB; console 146.9 MB peak working set and 98.1 MB private; per-call timings). The stubs' own memory probe printed zeros: it passed the pseudo-handle without `argtypes`. That is a self-test bug, fixed in `selftest31.ps1`, and the `peakJobPrivateMB` figures do not depend on it |

**After the run (no process started):**
- V31-R1 is fixed (`$foreign = $null; if (…) { $foreign = @(…) }`), and `evidence-missing` now names its source.
- The fixed text compiles (`Add-Type`, compile-only) and parses with 0 errors.
- A synthetic unit check runs the **exact** escape and `pidReuse` block from the fixed `c3_run.ps1` against
  fabricated snapshots, with all seven cases correct:
  - A, a clean run: escaped 0;
  - B, a child and a grandchild of a member outside the Job: escaped 2;
  - C, a reused dead-member PID: escaped 0, `pidReuse` 1;
  - D, a child of a reused parent PID: escaped 0;
  - E, a parent gone from both snapshots: fail-closed, escaped 1;
  - F, created before the launch: ignored;
  - G, an empty foreign list stays an empty array, not `$null`.
- Every other `$x = if (…)` in the script assigns a scalar, so V31-R1 has no other instance.

**Not done:** a live re-run of the **fixed** `c3_run.ps1`. The brief allowed exactly one run. The fixed script must
pass one more workstation self-test, or the dry pass's P8 item 6, before it goes to the capture host. That run should
show, for the five calls in order:
- `verify OK` with `startedPin=unpinned`;
- `verify OK` with `startedPin=OK` and `ctrlC=True/1`;
- `verify OK` with `startedPin=OK`;
- `verify FAIL` with `started-differs-from-pin`;
- `TIMEOUT`, `activeAtClose=4`, `memberMismatch=0` and `verify OK`.

The command is `launch31.py v31run2 <venv python>`, after copying `v31\c3_run.ps1` into the new folder.

### v3 run **[v3: B1]**

Run on 2026-10-06 (2026-10-07 UTC) on the 32 GB workstation, not the capture host. Setup:
- scratch folder `C:\Users\Michael\AppData\Local\Temp\c3-selftest-20261006`;
- a short-lived Python parent started `powershell.exe -NoProfile -ExecutionPolicy Bypass -File selftest.ps1` with
  `CREATE_NEW_CONSOLE`, as in `c3_handler_order_probe.py`, so that every console event stayed inside that new
  console. The parent first cleared any inherited "ignore Ctrl+C" flag in itself, so that the new console started
  with normal Ctrl+C handling, as an operator console does;
- Windows 11 (10.0.26200), Windows PowerShell 5.1.26100, Python 3.11.9 venv;
- stubs only. Run 1's stub slept. Run 2's stub ignored `SIGINT`, then called `GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0)`
  on its own console, standing in for the operator's keypress (the same console-wide event). Run 3 started
  `powershell.exe` with `stdin=DEVNULL` and `CREATE_NEW_PROCESS_GROUP`, and recorded `[Console]::IsInputRedirected`.

| Variant | Run | Ledger / outcome |
| --- | --- | --- |
| **v3 `c3_run.ps1`** (text-identical to the one printed below; CRLF copy SHA-256 `9e38eb76…579d8a`) | p8-guard-1 | `rc=0 ctrlC=False ctrlCCount=0 started=2 ended=2 memberMismatch=0 escaped=0 consoleForeign=0 verify=OK vanishedOutsideJob=3` |
| | p8-guard-2 (Ctrl+C) | `rc=0 timedOut=False interrupted=False ctrlC=True ctrlCCount=1 started=2 ended=2 memberMismatch=0 escaped=0 consoleForeign=0 verify=OK vanishedOutsideJob=3` |
| | p8-stdin | `started=3 ended=3 memberMismatch=0 escaped=0 verify=OK`; `IsInputRedirected` = **True** |
| | driver | ran to the end (`DRIVER SURVIVED`); console list at launch `[<own PID>]` every time |
| **v2 `c3_run.ps1`** (control, extracted from `D-c3-rehearsal-v2.md`) | p8-guard-1 | `verify=OK`, but the log shows `Job query failed: … "Job accounting query failed"` and `activeAtClose=-1` (V3-1) |
| | p8-guard-2 (Ctrl+C) | `C3RUN p8-guard-2 wrapper interrupted (Job closed by finally)`, then `TerminatingError(): "The pipeline has been stopped."`. **No ledger line; the driver did not survive.** This is B1, exactly as the Defender predicted |

Conclusions:
- **PASS.** The native guard catches Ctrl+C on the second call in a console, and PowerShell keeps waiting.
- The two-run self-test **discriminates**: v2 fails it and v3 passes it.
- The venv launcher and its interpreter are both observed inside the Job (`started=2`). The launcher survived the
  console Ctrl+C in run 2 (`rc=0`), which matters for step 7, where five such processes share the console.
- The NUL-stdin launcher shape reports `IsInputRedirected=True`, which supports the M5 check.
- `vanishedOutsideJob` was 0–5 per call on an idle workstation, all from unrelated processes, which confirms that it
  must be record-only.
- An earlier draft of v3 still had the 64-byte accounting buffer. It produced `verify=FAIL reason=job-query-failed;evidence-missing`
  (fail-closed), which is how V3-1 was found. The fix was re-tested in the final run above.
- Afterwards, a read-only query found no process whose command line referenced the scratch folder.
- Static checks on the six scripts as re-extracted from this file: both `.ps1` files parse with 0 errors
  (PowerShell `Parser::ParseFile`), and all four `.py` files parse (`ast.parse`). The P8 item 5 stop-verb scan prints
  nothing, and the CIM scan prints exactly one line (`Get-C3Snapshot`). Steps 5–8 were **not** run: they need the
  live runner and the templates, which this brief excluded.

The capture host still needs P8 item 6 with a real keypress. A workstation result does not transfer, because the
console host and the PowerShell build may differ.

---

## Scripts (review text; not committed anywhere)

Substitute `<tree>`, `<venv>`, `<date>` (§ "Host paths") and, after P8 item 2, `<PROMPT_SHA256>`. Save as UTF-8.

### `c3_run.ps1` — the only way the rehearsal starts a process; cleanup by closing its own Job **[v3.1: M1, V31-R1, Q6, N2, N3; v3: B1, M1, M2, M3, N1, N3, V3-1]**

This is the v3.1 text **after** the V31-R1 fix. It compiles and parses, and its escape logic passed the synthetic
unit check. It has **not** yet had a live self-test run (§ "Workstation self-test result").

```powershell
# C3 rehearsal launcher and cleanup, v3.1. Starts ONE child directly inside a fresh
# kill-on-close Job owned by this script, waits with a bound, then closes the Job.
# Closing the last Job handle is the ONLY termination this script performs. It never
# looks a process up by name, image, command line or start time, and it never ends a
# process by PID. The snapshots and console lists below are read-only evidence.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Tokens,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][ValidateRange(5, 600)][int]$TimeoutSeconds,
    [string]$WatchMarkersUnder = '',
    [ValidateRange(-1, 64)][int]$ExpectStarted = -1      # v3.1 Q6: -1 records only; otherwise a difference is verify=FAIL
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$C3RunVersion = 'c3-run-v3.1-F3'
$scratch = Split-Path -Parent $PSCommandPath
$ledger = Join-Path $scratch 'launch-ledger.txt'
if ($Label -notmatch '^[A-Za-z0-9._-]+$') { throw "Label must match [A-Za-z0-9._-]+: $Label" }
if (-not [IO.Path]::IsPathRooted($Exe) -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Exe must be an existing absolute path: $Exe" }

# The C# source. __NS__ is replaced by a namespace derived from the SHA-256 of this text, so an
# edited source always compiles a NEW type: Add-Type can never silently reuse stale code (N3).
$csSource = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace __NS__
{
    public static class Info { public const string Version = "c3-run-v3.1-F3"; }

    // Read-only host facts: the console's attached PIDs (M3) and the true OS version (N1).
    public static class Native
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint GetConsoleProcessList([Out] uint[] list, uint count);
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct OSVERSIONINFOW
        {
            public uint Size, Major, Minor, Build, Platform;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Csd;
        }
        [DllImport("ntdll.dll")]
        static extern int RtlGetVersion(ref OSVERSIONINFOW info);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint WaitForSingleObject(IntPtr handle, uint ms);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);

        // F3: conhost keeps a console-list entry for a process group that was sent Ctrl+Break from this console
        // while it lived on ANOTHER console (the 6b CREATE_NO_WINDOW stub). The entry outlives the process. True
        // ONLY when the PID provably has no live process: no such PID (ERROR_INVALID_PARAMETER), or its process
        // object is signalled (exited). Any other failure (access denied, ...) is false: treated as live, fail closed.
        public static bool IsGone(uint pid)
        {
            IntPtr h = OpenProcess(0x00100000 | 0x00001000, false, pid);   // SYNCHRONIZE | QUERY_LIMITED_INFORMATION
            if (h == IntPtr.Zero) return Marshal.GetLastWin32Error() == 87;
            try { return WaitForSingleObject(h, 0) == 0; } finally { CloseHandle(h); }
        }

        public static uint[] ConsoleProcesses()
        {
            uint[] list = new uint[256];
            uint n = GetConsoleProcessList(list, (uint)list.Length);
            if (n == 0) throw new Win32Exception(Marshal.GetLastWin32Error(), "GetConsoleProcessList failed (no console?)");
            if (n > list.Length) throw new InvalidOperationException("more than 256 processes share this console");
            Array.Resize(ref list, (int)n);
            return list;
        }

        public static Version OsVersion()
        {
            OSVERSIONINFOW v = new OSVERSIONINFOW();
            v.Size = (uint)Marshal.SizeOf(typeof(OSVERSIONINFOW));
            if (RtlGetVersion(ref v) != 0) throw new InvalidOperationException("RtlGetVersion failed");
            return new Version((int)v.Major, (int)v.Minor, (int)v.Build);
        }
    }

    public sealed class OwnJob
    {
        const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        const int JobObjectBasicAccountingInformation = 1;
        const int JobObjectBasicProcessIdList = 3;
        const int JobObjectExtendedLimitInformation = 9;
        const uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
        static readonly IntPtr PROC_THREAD_ATTRIBUTE_JOB_LIST = new IntPtr(0x0002000D);
        const uint WAIT_TIMEOUT = 0x00000102;

        [StructLayout(LayoutKind.Sequential)]
        struct BASIC_LIMIT
        {
            public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize; public uint ActiveProcessLimit;
            public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct IO_COUNTERS { public ulong R, W, O, RT, WT, OT; }
        [StructLayout(LayoutKind.Sequential)]
        struct EXTENDED_LIMIT
        {
            public BASIC_LIMIT Basic; public IO_COUNTERS Io; public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit; public UIntPtr PeakProcessMemoryUsed; public UIntPtr PeakJobMemoryUsed;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct STARTUPINFO
        {
            public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
            public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
            public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct STARTUPINFOEX { public STARTUPINFO StartupInfo; public IntPtr lpAttributeList; }
        [StructLayout(LayoutKind.Sequential)]
        struct PROCESS_INFORMATION { public IntPtr hProcess; public IntPtr hThread; public int dwProcessId; public int dwThreadId; }

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern IntPtr CreateJobObjectW(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref EXTENDED_LIMIT info, uint size);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool QueryInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint size, IntPtr returned);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returnSize);
        [DllImport("kernel32.dll")]
        static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern bool CreateProcessW(string application, StringBuilder commandLine, IntPtr processAttributes, IntPtr threadAttributes,
            bool inheritHandles, uint creationFlags, IntPtr environment, string currentDirectory,
            ref STARTUPINFOEX startupInfo, out PROCESS_INFORMATION processInformation);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);

        IntPtr job;
        IntPtr child = IntPtr.Zero;
        public int ChildPid { get; private set; }

        OwnJob(IntPtr handle) { job = handle; }

        // 1. Create the Job: unnamed, non-inheritable handle, kill-on-close.
        public static OwnJob Create()
        {
            IntPtr handle = CreateJobObjectW(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");
            EXTENDED_LIMIT limits = new EXTENDED_LIMIT();
            limits.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if (!SetInformationJobObject(handle, JobObjectExtendedLimitInformation, ref limits, (uint)Marshal.SizeOf(typeof(EXTENDED_LIMIT))))
            {
                int error = Marshal.GetLastWin32Error();
                CloseHandle(handle);   // empty Job: closing it ends nothing
                throw new Win32Exception(error, "KILL_ON_JOB_CLOSE configuration failed");
            }
            return new OwnJob(handle);
        }

        // 2. The child is CREATED inside the Job (PROC_THREAD_ATTRIBUTE_JOB_LIST, Windows 10+).
        //    If the Job cannot take it, CreateProcess fails and no process exists.
        //    Same console, same process group, so a console Ctrl+C reaches it.
        public int Launch(string executable, string commandLine, string workingDirectory)
        {
            if (job == IntPtr.Zero) throw new ObjectDisposedException("OwnJob");
            if (child != IntPtr.Zero) throw new InvalidOperationException("one child per Job");
            IntPtr size = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            IntPtr list = Marshal.AllocHGlobal(size);
            IntPtr jobs = Marshal.AllocHGlobal(IntPtr.Size);
            bool initialized = false;
            try
            {
                if (!InitializeProcThreadAttributeList(list, 1, 0, ref size))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "InitializeProcThreadAttributeList failed");
                initialized = true;
                Marshal.WriteIntPtr(jobs, job);
                if (!UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST, jobs, new IntPtr(IntPtr.Size), IntPtr.Zero, IntPtr.Zero))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "UpdateProcThreadAttribute(JOB_LIST) failed");
                STARTUPINFOEX startup = new STARTUPINFOEX();
                startup.StartupInfo.cb = Marshal.SizeOf(typeof(STARTUPINFOEX));
                startup.lpAttributeList = list;
                PROCESS_INFORMATION info;
                if (!CreateProcessW(executable, new StringBuilder(commandLine), IntPtr.Zero, IntPtr.Zero, false,
                        EXTENDED_STARTUPINFO_PRESENT, IntPtr.Zero, workingDirectory, ref startup, out info))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcess into the Job failed");
                CloseHandle(info.hThread);
                child = info.hProcess;
                ChildPid = info.dwProcessId;
                return info.dwProcessId;
            }
            finally
            {
                if (initialized) DeleteProcThreadAttributeList(list);
                Marshal.FreeHGlobal(list);
                Marshal.FreeHGlobal(jobs);
            }
        }

        public bool WaitChild(int milliseconds)
        {
            uint result = WaitForSingleObject(child, (uint)milliseconds);
            if (result == 0) return true;
            if (result == WAIT_TIMEOUT) return false;
            throw new Win32Exception(Marshal.GetLastWin32Error(), "WaitForSingleObject failed");
        }

        public int ChildExitCode()
        {
            uint code;
            if (!GetExitCodeProcess(child, out code)) throw new Win32Exception(Marshal.GetLastWin32Error(), "GetExitCodeProcess failed");
            return unchecked((int)code);
        }

        // JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: { TotalProcesses @36, ActiveProcesses @40 }.
        // TotalProcesses counts every process ever associated with the Job (nested Jobs included).
        public int[] Accounting()
        {
            const int size = 48;   // sizeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION); the call requires the exact size
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                if (!QueryInformationJobObject(job, JobObjectBasicAccountingInformation, buffer, size, IntPtr.Zero))
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Win32Exception(error, "Job accounting query failed (Win32 error " + error + ")");
                }
                return new int[] { Marshal.ReadInt32(buffer, 36), Marshal.ReadInt32(buffer, 40) };
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        // v3.1: JOBOBJECT_EXTENDED_LIMIT_INFORMATION.PeakJobMemoryUsed, the peak committed (private) bytes of
        // all members together (nested Jobs included). Read-only; for the resource profile.
        public long PeakJobPrivateBytes()
        {
            int size = Marshal.SizeOf(typeof(EXTENDED_LIMIT));
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                if (!QueryInformationJobObject(job, JobObjectExtendedLimitInformation, buffer, (uint)size, IntPtr.Zero))
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Win32Exception(error, "Job extended-limit query failed (Win32 error " + error + ")");
                }
                EXTENDED_LIMIT info = (EXTENDED_LIMIT)Marshal.PtrToStructure(buffer, typeof(EXTENDED_LIMIT));
                return (long)info.PeakJobMemoryUsed.ToUInt64();
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        // Member PIDs, read from the Job itself (JOBOBJECT_BASIC_PROCESS_ID_LIST).
        public int[] ProcessIds()
        {
            const int capacity = 4096;
            int bytes = 8 + capacity * IntPtr.Size;
            IntPtr buffer = Marshal.AllocHGlobal(bytes);
            try
            {
                if (!QueryInformationJobObject(job, JobObjectBasicProcessIdList, buffer, (uint)bytes, IntPtr.Zero))
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Win32Exception(error, "Job PID list query failed (Win32 error " + error + ")");
                }
                int count = Marshal.ReadInt32(buffer, 4);
                int[] ids = new int[count];
                for (int i = 0; i < count; i++) ids[i] = (int)Marshal.ReadIntPtr(buffer, 8 + i * IntPtr.Size).ToInt64();
                return ids;
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }

        // 3. Close the Job to terminate: closing the last handle of a KILL_ON_JOB_CLOSE Job
        //    makes Windows end every process still in it (and in Jobs nested in it).
        public void CloseToTerminate()
        {
            if (child != IntPtr.Zero) { CloseHandle(child); child = IntPtr.Zero; }   // a process handle; closing it ends nothing
            if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
        }
    }

    // B1 (v3): a NATIVE console control handler. SetConsoleCtrlHandler calls a process's handlers
    // newest-first until one returns TRUE (C3-handler-order-proof.md). Install() removes and re-adds
    // the routine on EVERY call, so it is always the newest handler, ahead of PowerShell's own
    // ConsoleHost break handler. It swallows CTRL_C_EVENT in THIS process only; Ctrl+Break and
    // close/logoff events fall through. It is not SetConsoleCtrlHandler(NULL, TRUE), so nothing is
    // inherited: children still receive the console event.
    public static class CtrlCGuard
    {
        public delegate bool HandlerRoutine(uint ctrlType);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetConsoleCtrlHandler(HandlerRoutine routine, bool add);
        static readonly HandlerRoutine Routine = new HandlerRoutine(OnCtrl);   // static: never collected
        static volatile bool fired;
        static int count;
        public static bool Fired { get { return fired; } }
        public static int Count { get { return System.Threading.Interlocked.CompareExchange(ref count, 0, 0); } }
        static bool OnCtrl(uint ctrlType)
        {
            if (ctrlType == 0) { fired = true; System.Threading.Interlocked.Increment(ref count); return true; }
            return false;
        }
        public static void Install()
        {
            SetConsoleCtrlHandler(Routine, false);   // drop any earlier registration (FALSE if none; ignored)
            fired = false;
            System.Threading.Interlocked.Exchange(ref count, 0);
            if (!SetConsoleCtrlHandler(Routine, true))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "SetConsoleCtrlHandler(add) failed");
        }
        public static bool Uninstall()                   // v3.1 N3: the result is recorded (guardRemoved)
        {
            return SetConsoleCtrlHandler(Routine, false);
        }
    }
}
'@

$hasher = [Security.Cryptography.SHA256]::Create()
try { $srcHash = -join ($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($csSource)) | ForEach-Object { $_.ToString('x2') }) }
finally { $hasher.Dispose() }
$ns = 'C3R_' + $srcHash.Substring(0, 16)
if (-not ("$ns.OwnJob" -as [type])) { Add-Type -TypeDefinition $csSource.Replace('__NS__', $ns) }   # csc.exe runs once per console per source (N2)
$OwnJobType = "$ns.OwnJob" -as [type]
$GuardType = "$ns.CtrlCGuard" -as [type]
$NativeType = "$ns.Native" -as [type]
if ((("$ns.Info" -as [type])::Version) -ne $C3RunVersion) { throw "loaded C3 type is not $C3RunVersion" }

function ConvertTo-C3Token([string]$value) {
    if ($value.Length -gt 0 -and $value -notmatch '[\s"]') { return $value }
    $sb = [Text.StringBuilder]::new(); [void]$sb.Append('"'); $slashes = 0
    foreach ($ch in $value.ToCharArray()) {
        if ($ch -eq '\') { $slashes++; continue }
        if ($ch -eq '"') { [void]$sb.Append('\' * ($slashes * 2 + 1)); [void]$sb.Append('"'); $slashes = 0; continue }
        if ($slashes) { [void]$sb.Append('\' * $slashes); $slashes = 0 }
        [void]$sb.Append($ch)
    }
    [void]$sb.Append('\' * ($slashes * 2)); [void]$sb.Append('"')
    return $sb.ToString()
}

# Read-only snapshot "pid|creationUtc" -> {Pid, Parent, Name, Created}. Evidence only; never passed to any stop call.
function Get-C3Snapshot {
    $map = @{}
    foreach ($p in @(Get-CimInstance -ClassName Win32_Process -Property ProcessId, ParentProcessId, CreationDate, Name -OperationTimeoutSec 30)) {
        $created = if ($p.CreationDate) { $p.CreationDate.ToUniversalTime() } else { [DateTime]::MinValue }
        $map['{0}|{1}' -f $p.ProcessId, $created.ToString('o')] = [pscustomobject]@{
            Pid = [int]$p.ProcessId; Parent = [int]$p.ParentProcessId; Name = ([string]$p.Name) -replace '\s', '_'; Created = $created }
    }
    return $map
}

$f = [ordered]@{
    label = $Label; version = $C3RunVersion; rc = 70; timedOut = $false; interrupted = $true; ctrlC = $false; ctrlCCount = 0
    console = '[]'; started = -1; endedBeforeClose = -1; activeAtClose = -1; endedAtClose = -1; memberMismatch = -1
    seen = 0; unseen = -1; lateMembers = 0; jobPids = '[]'; stillAlive = -1; escaped = -1; consoleForeign = -1
    startedPin = 'unpinned'; expectStarted = $ExpectStarted; pidReuse = 0; peakActive = -1; peakJobPrivateMB = -1
    guardRemoved = 'n/a'; vanishedOutsideJob = -1; verify = 'FAIL'; reason = ''; escapedList = '[]'; outsideJob = '[]'
    consoleStale = '[]'                                     # F3: record-only, console entries with no live process
}
$job = $null; $closed = $false; $guardInstalled = $false; $exitCode = 70
$seen = New-Object 'System.Collections.Generic.HashSet[int]'
$jobPids = @(); $members = @(); $foreign = @(); $pre = $null; $post = $null; $listConsistent = $false
$seenAtRead = 0; $peakActive = 0
$launchUtc = [DateTime]::UtcNow.AddSeconds(-2)

try {
    $GuardType::Install(); $guardInstalled = $true          # registered on EVERY call (B1)
    try {
        $os = $NativeType::OsVersion()
        if ($os.Major -lt 10) { $f.reason = 'windows-below-10'; throw "Windows 10 or later is required (PROC_THREAD_ATTRIBUTE_JOB_LIST); this is $os" }
        $attached = @($NativeType::ConsoleProcesses())
        $f.console = '[' + ($attached -join ';') + ']'
        $stale = @($attached | Where-Object { [int]$_ -ne $PID -and $NativeType::IsGone([uint32]$_) })   # F3
        $f.consoleStale = '[' + ($stale -join ';') + ']'
        $attached = @($attached | Where-Object { $stale -notcontains $_ })
        if ($attached.Count -ne 1 -or [int]$attached[0] -ne $PID) {   # M3: refuse unless this console is ours alone (live PIDs)
            $f.reason = 'console-shared'
            throw "REFUSED: this console is shared with PIDs [$($attached -join ',')]; open a fresh console (P4, step 1)"
        }
        $job = $OwnJobType::Create()
        $commandLine = (@($Exe) + $Tokens | ForEach-Object { ConvertTo-C3Token $_ }) -join ' '
        $launchUtc = [DateTime]::UtcNow.AddSeconds(-2)
        $childPid = $job.Launch($Exe, $commandLine, $WorkingDirectory)
        [void]$seen.Add($childPid)
        Write-Host "C3RUN ${Label}: child pid $childPid started inside this script's own kill-on-close Job"
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        $announced = $false
        while (-not $job.WaitChild(250)) {
            foreach ($p in $job.ProcessIds()) { [void]$seen.Add($p) }      # M2: union of every member seen
            $acc = $job.Accounting(); if ($acc[1] -gt $peakActive) { $peakActive = $acc[1] }   # v3.1: peak concurrent members
            if ($WatchMarkersUnder -and -not $announced) {
                $found = @(Get-ChildItem -LiteralPath $WatchMarkersUnder -Filter 'markers.txt' -Recurse -File -ErrorAction SilentlyContinue)
                if ($found.Count -eq 1 -and (Select-String -LiteralPath $found[0].FullName -Pattern '^START ' -Quiet)) {
                    $sentinel = Join-Path $found[0].DirectoryName 'sentinel.txt'
                    if ((Test-Path -LiteralPath $sentinel) -and (Select-String -LiteralPath $sentinel -Pattern '^READY ' -Quiet)) {
                        Write-Host "C3RUN ${Label}: START and sentinel READY seen in $($found[0].DirectoryName) - press Ctrl+C ONCE now, then wait."
                        $announced = $true
                    }
                }
            }
            if ([DateTime]::UtcNow -gt $deadline) { $f.timedOut = $true; break }
        }
        $f.rc = if ($f.timedOut) { 124 } else { $job.ChildExitCode() }
        $f.interrupted = $false
    }
    catch {
        Write-Host "C3RUN ${Label}: launch or wait error: $_"
        if (-not $f.reason) { $f.reason = 'launch-or-wait-error' }
        $f.rc = if ($f.reason -eq 'console-shared') { 64 } else { 71 }
        if ($_.Exception -isnot [System.Management.Automation.PipelineStoppedException]) { $f.interrupted = $false }
    }
    finally {
        if ($null -ne $job) {
            try {
                # v3.1 M1: the (slow, WMI) snapshot is taken FIRST, so every Job read below is newer than it.
                try { $pre = Get-C3Snapshot } catch { Write-Host "C3RUN ${Label}: snapshot failed: $_"; $pre = $null }
                try {
                    for ($i = 0; $i -lt 5; $i++) {                          # a consistent read: accounting, list, accounting
                        $a1 = $job.Accounting(); $ids = @($job.ProcessIds()); $a2 = $job.Accounting()
                        $listConsistent = ($a1[0] -eq $a2[0]) -and ($a1[1] -eq $a2[1]) -and ($ids.Count -eq $a2[1])
                        if ($listConsistent) { break }
                        Start-Sleep -Milliseconds 50
                    }
                    if (-not $listConsistent) { $f.reason += ';job-list-inconsistent'; throw 'job list never consistent' }   # v3.1 N2: FAIL, not HARD STOP
                    $jobPids = $ids; foreach ($p in $ids) { [void]$seen.Add($p) }
                    $seenAtRead = $seen.Count
                    $f.started = $a2[0]; $f.activeAtClose = $a2[1]; $f.endedBeforeClose = $a2[0] - $a2[1]
                    if ($a2[1] -gt $peakActive) { $peakActive = $a2[1] }
                } catch { Write-Host "C3RUN ${Label}: Job query failed: $_"; $f.reason += ';job-query-failed'; $f.started = -1 }
                try { $f.peakJobPrivateMB = [Math]::Round($job.PeakJobPrivateBytes() / 1MB, 1) } catch { Write-Host "C3RUN ${Label}: peak memory query failed: $_" }
                try { $consoleNow = @($NativeType::ConsoleProcesses()) } catch { Write-Host "C3RUN ${Label}: console list failed: $_"; $consoleNow = $null }
                try { $lateIds = @($job.ProcessIds()) } catch { $lateIds = @() }
                $members = @($jobPids) + @($lateIds | Where-Object { $jobPids -notcontains $_ })   # membership is permanent
                $f.lateMembers = $members.Count - @($jobPids).Count
                foreach ($p in $lateIds) { [void]$seen.Add($p) }
                # v3.1-R1: assign INSIDE the branch. `$x = if (..) { @() }` unrolls an empty array to $null, which
                # made every clean run look like "console list failed" (observed in the v3.1 self-test).
                $foreign = $null
                if ($null -ne $consoleNow) {
                    # F3: an entry with no live process cannot receive a keystroke; record it (consoleStale), never count it.
                    $staleNow = @($consoleNow | Where-Object { [int]$_ -ne $PID -and $members -notcontains [int]$_ -and $NativeType::IsGone([uint32]$_) })
                    if ($staleNow.Count -gt 0) { $f.consoleStale = '[' + ((@($f.consoleStale.Trim('[]') -split ';' | Where-Object { $_ }) + @($staleNow | ForEach-Object { "close:$_" })) -join ';') + ']' }
                    $foreign = @($consoleNow | Where-Object { [int]$_ -ne $PID -and $members -notcontains [int]$_ -and $staleNow -notcontains $_ })
                }
            }
            finally {
                $job.CloseToTerminate(); $closed = $true        # M1: always; the ONLY termination in this script
            }
        }
        if ($f.interrupted) { Write-Host "C3RUN ${Label} wrapper interrupted (Job closed by finally)" }
    }

    # Verification. Everything here is read-only evidence.
    if ($f.reason -eq 'console-shared' -or $f.reason -eq 'windows-below-10') {
        $f.verify = 'REFUSED'
    }
    elseif ($null -eq $job -or -not $closed) { $f.reason += ';no-job' }
    elseif ($null -eq $pre -or $null -eq $foreign -or $f.started -lt 0) {
        $f.reason += ';evidence-missing'
        if ($null -eq $pre) { $f.reason += ':snapshot' }; if ($null -eq $foreign) { $f.reason += ':console' }; if ($f.started -lt 0) { $f.reason += ':job' }
    }
    else {
        $jobKeys = @($pre.Keys | Where-Object { $members -contains $pre[$_].Pid })
        $readKeys = @($pre.Keys | Where-Object { $jobPids -contains $pre[$_].Pid })
        $until = [DateTime]::UtcNow.AddSeconds(10)
        do {
            $post = Get-C3Snapshot
            $alive = @($jobKeys | Where-Object { $post.ContainsKey($_) })
            if ($alive.Count -eq 0) { break }
            Start-Sleep -Milliseconds 100
        } while ([DateTime]::UtcNow -lt $until)
        $f.stillAlive = $alive.Count
        # Started versus ended, for this Job's own members (master-agent: a mismatch is a HARD STOP).
        $f.endedAtClose = @($jobPids).Count - @($readKeys | Where-Object { $post.ContainsKey($_) }).Count
        $ended = $f.endedBeforeClose + $f.endedAtClose
        $f.memberMismatch = [Math]::Abs($f.started - $ended) + [Math]::Abs($jobPids.Count - $f.activeAtClose)
        if ($seenAtRead -gt $f.started) { $f.memberMismatch += $seenAtRead - $f.started }   # late PIDs excluded (v3.1 M1)
        if ($f.started -lt 1) { $f.memberMismatch += 1 }                  # the child itself is always a member
        $f.seen = $seen.Count; $f.unseen = [Math]::Max(0, $f.started - $seenAtRead); $f.peakActive = $peakActive
        if ($ExpectStarted -ge 0) { $f.startedPin = if ($f.started -eq $ExpectStarted) { 'OK' } else { 'DIFF' } }   # v3.1 Q6
        # Escaped: a process this run caused (created after launch; a seen member itself, or a descendant of one)
        # that is NOT a Job member. Fixpoint over the parent chain in the before and after snapshots.
        $all = @{}; foreach ($k in $pre.Keys) { $all[$k] = $pre[$k] }; foreach ($k in $post.Keys) { $all[$k] = $post[$k] }
        $roots = New-Object 'System.Collections.Generic.HashSet[int]'; foreach ($p in $seen) { [void]$roots.Add($p) }
        $escapedKeys = New-Object 'System.Collections.Generic.HashSet[string]'
        # v3.1 M1: parent-IDENTITY rule. A process can never leave a Job, so a non-member whose PID is in $seen is a
        # reused PID (recorded as pidReuse, never counted as escaped). A candidate counts only if its live parent entry
        # (same PID, created no later than the candidate) is a member or an already-escaped process.
        do {
            $grew = $false
            foreach ($k in @($all.Keys)) {
                $e = $all[$k]
                if ($escapedKeys.Contains($k) -or $e.Pid -eq $PID -or $members -contains $e.Pid -or $e.Created -lt $launchUtc) { continue }
                $parentKey = @($all.Keys | Where-Object { $all[$_].Pid -eq $e.Parent -and $all[$_].Created -le $e.Created } |
                              Sort-Object { $all[$_].Created } | Select-Object -Last 1)
                $byMember = if ($parentKey.Count -eq 1) {
                    ($members -contains $all[$parentKey[0]].Pid) -or $escapedKeys.Contains($parentKey[0])   # identity-checked parent
                } else {
                    $roots.Contains($e.Parent)                                                              # parent gone: fail closed
                }
                if ($byMember) { [void]$escapedKeys.Add($k); [void]$roots.Add($e.Pid); $grew = $true }
            }
        } while ($grew)
        $f.pidReuse = @($all.Keys | Where-Object { $seen.Contains($all[$_].Pid) -and $members -notcontains $all[$_].Pid -and -not $escapedKeys.Contains($_) }).Count
        $f.escaped = $escapedKeys.Count
        $f.escapedList = '[' + (($escapedKeys | ForEach-Object { '{0}|{1}|ppid{2}' -f $_, $all[$_].Name, $all[$_].Parent }) -join ';') + ']'
        $f.consoleForeign = $foreign.Count
        # Host-wide: processes OUTSIDE the Job that ended during the close window. RECORD ONLY, never a stop (M2).
        $outside = @($pre.Keys | Where-Object { -not $post.ContainsKey($_) -and $jobKeys -notcontains $_ -and -not $escapedKeys.Contains($_) })
        $f.vanishedOutsideJob = $outside.Count
        $f.outsideJob = '[' + (($outside | ForEach-Object { '{0}|{1}|ppid{2}' -f $_, $pre[$_].Name, $pre[$_].Parent }) -join ';') + ']'
        if ($f.escaped -gt 0 -or $f.memberMismatch -ne 0 -or $f.consoleForeign -gt 0) { $f.verify = 'HARDSTOP' }
        elseif ($f.startedPin -eq 'DIFF') { $f.verify = 'FAIL'; $f.reason += ';started-differs-from-pin' }   # ABORT, not HARD STOP
        elseif ($f.stillAlive -eq 0) { $f.verify = 'OK' }
    }
}
catch {
    Write-Host "C3RUN ${Label}: verification error: $_"
    $f.reason += ';verification-error'
    if ($f.verify -eq 'OK') { $f.verify = 'FAIL' }
}
finally {
    # M1: the ledger line is written unconditionally.
    try { $f.ctrlC = $GuardType::Fired; $f.ctrlCCount = $GuardType::Count } catch { }
    if ($guardInstalled) { try { $f.guardRemoved = $GuardType::Uninstall(); $guardInstalled = $false } catch { $f.guardRemoved = 'error' } }
    $f.jobPids = '[' + ($jobPids -join ';') + ']'
    if (-not $f.reason) { $f.reason = 'none' }
    $f.reason = $f.reason.TrimStart(';') -replace '\s', '_'
    $line = ([DateTime]::UtcNow.ToString('o')) + ' ' + (($f.GetEnumerator() | ForEach-Object { '{0}={1}' -f $_.Key, $_.Value }) -join ' ')
    try { Add-Content -LiteralPath $ledger -Value $line -Encoding UTF8 }
    catch { Write-Host "C3RUN ${Label}: LEDGER WRITE FAILED: $_ (treat as verify FAIL)"; $f.verify = 'FAIL' }
    Write-Host ("C3RUN {0} exit={1} started={2} startedPin={3} ended={4} memberMismatch={5} escaped={6} consoleForeign={7} stillAlive={8} ctrlC={9}/{10} peakActive={11} peakJobPrivateMB={12} pidReuse={13}(record-only) vanishedOutsideJob={14}(record-only) consoleStale={16}(record-only) verify {15}" -f `
        $Label, $(if ($f.timedOut) { 'TIMEOUT' } else { $f.rc }), $f.started, $f.startedPin, ($f.endedBeforeClose + $f.endedAtClose), $f.memberMismatch,
        $f.escaped, $f.consoleForeign, $f.stillAlive, $f.ctrlC, $f.ctrlCCount, $f.peakActive, $f.peakJobPrivateMB, $f.pidReuse, $f.vanishedOutsideJob, $f.verify, $f.consoleStale)
    if ($f.verify -eq 'HARDSTOP') { Write-Host "C3RUN ${Label}: HARD STOP. The rehearsal caused a process outside its Job, or its Job's members do not add up. Stop the rehearsal; record FAIL." }
    elseif ($f.verify -ne 'OK') { Write-Host "C3RUN ${Label}: verify $($f.verify) ($($f.reason)). This script issued no stop call. Abort the step." }
    $exitCode = if ($f.verify -eq 'OK') { [int]$f.rc } elseif ($f.verify -eq 'REFUSED') { 64 } else { 125 }
    if ($guardInstalled) { [void]$GuardType::Uninstall() }
}
exit $exitCode
```

Notes for the reviewer:
- The pattern is: create the Job (`OwnJob.Create`), assign the child (`Launch`, which creates the child already in
  the Job), then close the Job to terminate (`CloseToTerminate`, in a `finally`).
- There is no `TerminateProcess`, no `TerminateJobObject`, and no other handle to the Job, so the close is the last
  handle. If PowerShell dies, the OS closes the handle and the result is the same.
- `PROC_THREAD_ATTRIBUTE_JOB_LIST` requires **Windows 10** or later; nested Jobs need Windows 8. The script reads
  the true version with `RtlGetVersion`, because `[Environment]::OSVersion` can be shimmed, and refuses below 10.
- **Guard (B1).** `CtrlCGuard.Install()` calls `SetConsoleCtrlHandler(Routine, false)` and then `(Routine, true)` on
  every call, so this routine is always the newest handler in the process and runs before ConsoleHost's handler. The
  delegate is a static field, so it is never garbage-collected while registered. It returns TRUE only for
  `CTRL_C_EVENT` (0); Ctrl+Break, close, logoff and shutdown fall through to PowerShell. `Uninstall()` runs in the
  outermost `finally`.
- **Type caching (N3).** The namespace is `C3R_` plus the first 16 hex digits of the SHA-256 of the C# text. Editing the
  C# compiles a new type alongside the old one, and the `Version` constant is checked against the script's literal.
  P8 item 1 still says not to edit after P8 item 2, because a pinned file must be the file that ran.
- **Accounting (V3-1).** `QueryInformationJobObject(JobObjectBasicAccountingInformation)` is called with exactly 48
  bytes. v2 passed 64, which fails.
- `escaped` and `vanishedOutsideJob` key processes by PID **and** creation time, so PID reuse cannot hide or fake an
  entry. **[v3.1: M1]** A candidate for `escaped` must have been created after the launch (minus 2 s of clock slack)
  and have an identity-checked member parent. A reused PID is counted in `pidReuse`, never in `escaped`. Only a
  parent that has vanished from both snapshots falls back to the PID test, which is fail-closed.
- **Order at close [v3.1: M1]:** snapshot → consistent Job read (`FAIL` if it is never consistent) → peak memory →
  console list → late PID read → `CloseToTerminate()` (in `finally`) → after-close snapshot.
- **[v3.1: V31-R1]** Never write `$x = if (…) { … } else { @(…) }` for a list in this script. Assign inside the
  branch, or an empty list becomes `$null`.
- **[v3.1: N3]** The guard is removed just before the ledger write (`guardRemoved`). The `C3RUN` line is printed after
  the ledger write, so "hands off until the `C3RUN` line" covers the gap.

### `c3_break.py` — steps 5 and 6 driver **[F1: venv prefix reset before the harness import]**

```python
"""C3 steps 5/6 driver: the #230 harness on this console. Kills nothing itself."""
import json, sys, tempfile
from pathlib import Path

tree, run_dir, step, mode = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3], sys.argv[4]
# mode: positive | positive-stdin-closed | no_break | sitecustomize
assert mode in ("positive", "positive-stdin-closed", "no_break", "sitecustomize"), mode
assert run_dir.is_dir() and not any(run_dir.iterdir()), f"run folder must be new and empty: {run_dir}"
# F1: -S skipped site.venv(), so sys.prefix is the BASE install and the harness's sysconfig purelib would be
# the base site-packages (ModuleNotFoundError: requests). Do what site.venv() does, BEFORE the first import
# of sysconfig (it copies sys.prefix at import time), then cross-check against step 3's value. Fail closed.
assert "sysconfig" not in sys.modules, "sysconfig was imported before the venv prefix reset"
_venv = Path(sys.executable).parent.parent                      # ...\venv\Scripts\python.exe -> ...\venv
assert (_venv / "pyvenv.cfg").is_file(), f"not a venv interpreter: {sys.executable}"
sys.prefix = sys.exec_prefix = str(_venv)
import os, sysconfig
_pl = os.path.normcase(os.path.normpath(sysconfig.get_paths()["purelib"]))
_want = os.environ.get("WEATHER_FIXED_SESSION_SITE_PACKAGES", "")
assert _want and _pl == os.path.normcase(os.path.normpath(_want)), f"purelib {_pl} != step-3 site-packages {_want!r}"
sys.path.insert(0, str(tree))                  # the tests package; -S means no site, no sitecustomize
from tests.operations.live_launcher_break_harness import assert_cooperative_break, run_break_case
assert "sitecustomize" not in sys.modules
runner = tree / "src" / "weather" / "operations" / "international_live_session_runner.py"
work = Path(tempfile.mkdtemp(prefix=f"c3-{step}-{mode}-", dir=run_dir))
ALLOWANCE, TAIL, GRACE, MARGIN = 3.0, 0.5, 12.0, 7.5
positive = mode.startswith("positive")
rc, text, outcome, events = run_break_case(
    work, str(runner), allowance=ALLOWANCE, tail=TAIL, grace=GRACE,
    caller_stdin_open=(mode != "positive-stdin-closed"),       # R6: the stdin-lane shape by default
    mutant=None if positive else mode)
(work / "helper-rc.txt").write_text(str(rc), encoding="ascii")
stamps = dict(events)
lag = stamps["BREAK"] - outcome["deadline_ms"] if outcome and "BREAK" in stamps else None
print(json.dumps({"step": step, "mode": mode, "rc": rc, "outcome": outcome, "events": events,
                  "break_lag_ms": lag, "work": str(work)}, indent=1))
if positive:
    assert_cooperative_break(rc, text, outcome, events, runner_file=str(runner),
                             max_return_after_deadline_s=TAIL + MARGIN, max_elapsed_s=ALLOWANCE + GRACE)
    print("C3 STEP 5 PASS")
```

### `c3_ctrlc.py` — step 7 driver, sentinel and strict judge **[v3: B2; F1: venv prefix reset in `run`]**

```python
"""C3 step 7 (v3): operator Ctrl+C. The driver ignores Ctrl+C itself. A sentinel child records
the console SIGINT. The verdict comes from a separate judge run that reads helper-output.txt,
markers.txt, sentinel.txt and this run's own ledger line. It is binary: PASS or FAIL."""
import signal
signal.signal(signal.SIGINT, signal.SIG_IGN)   # FIRST: never consume the operator's Ctrl+C (not inherited by children)

import json, re, subprocess, sys, tempfile, time
from pathlib import Path

ALLOWANCE, TAIL, GRACE, MARGIN = 20.0, 0.5, 12.0, 7.5
PREFIX = "c3-s7-ctrlc-"
HERE = Path(__file__).resolve().parent                 # C:\c3\<date>
LEDGER = HERE / "launch-ledger.txt"
SENTINEL_WINDOW_S = ALLOWANCE + GRACE
# The sentinel: same console, same process group, inside the C3 Job (a child of this driver).
# It records READY, then every console SIGINT with a wall-clock ms stamp, then DONE, and exits on
# its own. time.sleep is interruptible on Windows, so the stamp is taken at the keypress.
SENTINEL = (
    "import signal,sys,time\n"
    "p=sys.argv[1]\n"
    "def rec(kind):\n"
    "    with open(p,'a',encoding='ascii') as h: h.write('%s %d\\n'%(kind,int(time.time()*1000)))\n"
    "signal.signal(signal.SIGINT,lambda s,f:rec('SIGINT'))\n"
    "rec('READY')\n"
    "end=time.monotonic()+float(sys.argv[2])\n"
    "while time.monotonic()<end: time.sleep(0.1)\n"
    "rec('DONE')\n")


def runner_file(tree: Path) -> Path:
    return tree / "src" / "weather" / "operations" / "international_live_session_runner.py"


def read_stamps(path: Path) -> list:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition(" ")
            rows.append((name, int(value)))
    return rows


def ledger_row(label: str):
    lines = [line for line in LEDGER.read_text(encoding="utf-8-sig").splitlines() if f" label={label} " in line]
    if len(lines) != 1:
        return None, len(lines)
    return dict(re.findall(r"(\w+)=(\[[^\]]*\]|\S+)", lines[0])), 1


def judge(tree: Path, work: Path, label: str, mode: str) -> int:
    sys.path.insert(0, str(tree))
    from tests.operations.live_launcher_break_harness import assert_cooperative_break
    work = work.resolve()
    control = mode == "control"
    want = PREFIX + ("control-" if control else "")
    if (mode not in ("operator", "control") or not work.name.startswith(want)
            or (not control and work.name.startswith(PREFIX + "control-")) or work.parent.parent != HERE):
        print(f"C3 STEP 7 FAIL refusing {work} for mode {mode!r}: not this step's work folder")
        return 2
    failures, timing = [], []
    output = work / "helper-output.txt"
    text = output.read_text(encoding="utf-8", errors="replace") if output.exists() else ""
    found = re.findall(r"OUTCOME (\{.*\})", text)
    outcome = json.loads(found[0]) if len(found) == 1 else None
    events = read_stamps(work / "markers.txt")
    rc_file = work / "helper-rc.txt"
    rc = int(rc_file.read_text(encoding="ascii").strip()) if rc_file.exists() else -1
    stamps = dict(events)
    try:
        assert_cooperative_break(rc, text, outcome, events, runner_file=str(runner_file(tree)),
                                 max_return_after_deadline_s=TAIL + MARGIN, max_elapsed_s=ALLOWANCE + GRACE)
    except (AssertionError, KeyError, TypeError) as exc:
        failures.append("step-5 asserts: " + (str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__))
    sentinel = read_stamps(work / "sentinel.txt")
    ready = [t for k, t in sentinel if k == "READY"]
    done = [t for k, t in sentinel if k == "DONE"]
    sigint = [t for k, t in sentinel if k == "SIGINT"]
    if len(ready) != 1:
        failures.append(f"sentinel READY count {len(ready)} (exactly 1 required)")
    if len(done) != 1:
        failures.append(f"sentinel DONE count {len(done)} (exactly 1 required)")
    start, deadline = stamps.get("START"), (outcome or {}).get("deadline_ms")
    in_window = (len(sigint) == 1 and len(ready) == 1 and start is not None and deadline is not None
                 and ready[0] < sigint[0] and start < sigint[0] < deadline)
    if control:
        if sigint:
            failures.append(f"control: sentinel recorded {len(sigint)} SIGINT with no keypress (spurious)")
    elif not in_window:
        timing.append(f"sentinel SIGINT {sigint} is not exactly one stamp between START/READY and the deadline")
    row, count = ledger_row(label)
    if row is None:
        failures.append(f"ledger has {count} lines for {label} (exactly 1 required)")
    else:
        for key, value in (("rc", "0"), ("timedOut", "False"), ("interrupted", "False"), ("verify", "OK"),
                           ("escaped", "0"), ("memberMismatch", "0"), ("consoleForeign", "0")):
            if row.get(key) != value:
                failures.append(f"ledger {key}={row.get(key)} (want {value})")
        want_ctrl = ("False", "0") if control else ("True", "1")
        got_ctrl = (row.get("ctrlC"), row.get("ctrlCCount"))
        if got_ctrl != want_ctrl:
            message = f"ledger ctrlC/ctrlCCount={got_ctrl} (want {want_ctrl})"
            (timing if (not control and not in_window) else failures).append(message)
    hardstop = row is not None and (row.get("verify") == "HARDSTOP" or row.get("escaped") != "0"
                                    or row.get("memberMismatch") != "0" or row.get("consoleForeign") != "0")
    honoured = None
    if outcome is not None and "elapsed_s" in outcome:
        honoured = "at_keypress" if outcome["elapsed_s"] < ALLOWANCE - 1.0 else "at_wait_return"
    passed = not failures and not timing
    print(json.dumps({"step": "s7", "mode": mode, "label": label, "work": str(work), "rc": rc, "outcome": outcome,
                      "events": events, "sentinel": sentinel,
                      "sigint_after_start_ms": (sigint[0] - start) if sigint and start else None,
                      "sigint_before_deadline_ms": (deadline - sigint[0]) if sigint and deadline else None,
                      "break_lag_ms": (stamps["BREAK"] - deadline) if deadline and "BREAK" in stamps else None,
                      "honoured_info_only": honoured, "ledger": row,
                      "failures": failures, "timing_failures": timing,
                      "operator_timing_only": (not passed and not failures and bool(timing))}, indent=1))
    if hardstop:
        print("C3 STEP 7 HARD STOP: the run's ledger line shows escaped, memberMismatch or consoleForeign")
        return 3
    name = "C3 STEP 7 CONTROL" if control else "C3 STEP 7"
    print(f"{name} PASS" if passed else f"{name} FAIL")
    return 0 if passed else 1


def run(tree: Path, run_dir: Path, mode: str) -> int:
    assert mode in ("operator", "control"), mode
    run_dir = run_dir.resolve()
    assert run_dir.parent == HERE, f"run folder must be directly under {HERE}: {run_dir}"
    assert run_dir.is_dir() and not any(run_dir.iterdir()), f"run folder must be new and empty: {run_dir}"
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    # F1: -S skipped site.venv(), so sys.prefix is the BASE install and the harness's sysconfig purelib would be
    # the base site-packages. Do what site.venv() does, BEFORE the first import of sysconfig (it copies
    # sys.prefix at import time), then cross-check against step 3's value. Fail closed.
    assert "sysconfig" not in sys.modules, "sysconfig was imported before the venv prefix reset"
    venv = Path(sys.executable).parent.parent                   # ...\venv\Scripts\python.exe -> ...\venv
    assert (venv / "pyvenv.cfg").is_file(), f"not a venv interpreter: {sys.executable}"
    sys.prefix = sys.exec_prefix = str(venv)
    import os, sysconfig
    purelib = os.path.normcase(os.path.normpath(sysconfig.get_paths()["purelib"]))
    want = os.environ.get("WEATHER_FIXED_SESSION_SITE_PACKAGES", "")
    assert want and purelib == os.path.normcase(os.path.normpath(want)), f"purelib {purelib} != step-3 site-packages {want!r}"
    sys.path.insert(0, str(tree))
    from tests.operations.live_launcher_break_harness import run_break_case
    assert "sitecustomize" not in sys.modules
    work = Path(tempfile.mkdtemp(prefix=PREFIX + ("control-" if mode == "control" else ""), dir=run_dir))
    sentinel_file = work / "sentinel.txt"
    sentinel = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", SENTINEL, str(sentinel_file),
                                 str(SENTINEL_WINDOW_S)], stdin=subprocess.DEVNULL)
    ready_by = time.monotonic() + 15
    while time.monotonic() < ready_by:
        if sentinel_file.exists() and "READY " in sentinel_file.read_text(encoding="ascii"):
            break
        time.sleep(0.05)
    else:
        print("C3 STEP 7: sentinel not READY within 15 s; not running the case (the judge will FAIL)", flush=True)
        return 3                                     # no kill path: the C3 Job ends the sentinel at close
    print("C3 STEP 7 WORK " + str(work), flush=True)
    if mode == "operator":
        print("C3 STEP 7: wait for the wrapper's 'START and sentinel READY' line, press Ctrl+C ONCE, then wait.", flush=True)
    else:
        print("C3 STEP 7 CONTROL: press NOTHING.", flush=True)
    rc, _text, _outcome, _events = run_break_case(
        work, str(runner_file(tree)), allowance=ALLOWANCE, tail=TAIL, grace=GRACE,
        caller_stdin_open=True, mutant=None)
    (work / "helper-rc.txt").write_text(str(rc), encoding="ascii")
    try:
        sentinel.wait(timeout=SENTINEL_WINDOW_S + 30)    # it exits on its own; no kill path
    except subprocess.TimeoutExpired:
        print("C3 STEP 7: sentinel still running; the C3 Job ends it at close (the judge will FAIL: no DONE)", flush=True)
        return 3
    print("C3 STEP 7 RUN DONE: judge it with the separate 'judge' run (the verdict needs this run's ledger line)", flush=True)
    return 0


if __name__ == "__main__":
    verb = sys.argv[1]
    if verb == "run":
        sys.exit(run(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]))
    if verb == "judge":
        sys.exit(judge(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]))
    sys.exit(f"unknown verb {verb!r}")
```

### `c3_prompt.py` — step 8 driver (pins the stub, then `protected_files`) **[v3: N4; v3.1: N8]**

```python
"""C3 step 8 driver (v3.1). Runs the real _default_launcher_runner ONLY on the pinned stub, and
passes the stub, its child and the tree's Job helper as protected_files (deny-write + re-hash)."""
import hashlib, json, os, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path
from weather.operations import international_live_session_runner as runner
from weather.operations.live_path_security import LivePathSecurityError

assert "sitecustomize" not in sys.modules and not getattr(subprocess.Popen, "_weather_silent_windows_children", False)
HERE = Path(__file__).resolve().parent                    # C:\c3\<date>
EXPECTED_NAME = "c3_prompt_launcher.ps1"
CHILD = (HERE / "c3_prompt_child.py").resolve()
TREE = Path(os.environ["WEATHER_FIXED_SESSION_SRC"]).resolve().parent
JOB_HELPER = (TREE / "scripts" / "ops" / "windows_kill_on_close_job.ps1").resolve()
FORBIDDEN = ("international_live", "fixed_scope", "fixed_session", "session_manifest", "manifest", "seal",
             "credential", "wallet", "clob", "polymarket", "stage0", "stage1", "data\\")

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

stub = Path(sys.argv[1])
want_launcher, want_child, want_helper = (value.strip().lower() for value in sys.argv[2:5])
resolved = stub.resolve(strict=True)
text = resolved.read_text(encoding="utf-8").lower()
checks = {
    "in_scratch_folder": resolved.parent == HERE,
    "exact_name": resolved.name == EXPECTED_NAME,
    "not_a_link": not stub.is_symlink() and stub.absolute() == resolved,
    "launcher_sha256_pinned": sha256(resolved) == want_launcher,
    "child_sha256_pinned": CHILD.is_file() and sha256(CHILD) == want_child,
    "job_helper_sha256_pinned": JOB_HELPER.is_file() and sha256(JOB_HELPER) == want_helper,
    "names_the_child": str(CHILD).lower() in text,
    "no_live_reference": not any(token in text for token in FORBIDDEN),
}
print(json.dumps({"stub": str(resolved), "checks": checks}), flush=True)
if not all(checks.values()):
    print("C3 STEP 8 REFUSED: stub pin failed; the launcher control was not called", flush=True)
    sys.exit(9)

# N4: the runner itself takes deny-write handles on these files, re-hashes them, and holds the
# handles until it returns (the same mechanism that guards sealed artifacts).
protected = {resolved: want_launcher, CHILD: want_child, JOB_HELPER: want_helper}
deadline = datetime.now().astimezone() + timedelta(seconds=120)
try:
    done = runner._default_launcher_runner(resolved, timeout_seconds=130, absolute_deadline=deadline,
                                           protected_files=protected, cleanup_grace_seconds=12)
    print(json.dumps({"returncode": done.returncode, "raised": False}), flush=True)
except runner.LauncherControlError as exc:
    print(json.dumps({"raised": True, "cooperative": exc.cooperative, "forced": exc.forced,
                      "exit_code": exc.exit_code}), flush=True)
except (runner.SessionCompositionError, LivePathSecurityError) as exc:
    print(json.dumps({"refused_by_runner": type(exc).__name__, "detail": str(exc)[:200]}), flush=True)
    # v3.1 N8: the runner can also raise this AFTER launch (e.g. "launcher child-tree termination was not proved").
    print("C3 STEP 8 ABORT: the runner refused or failed; see detail (exit 9)", flush=True)
    sys.exit(9)
```

### `c3_prompt_launcher.ps1` — step 8 stub launcher (checks its own stdin first) **[v3: M5]**

```powershell
$ErrorActionPreference = "Stop"; Set-StrictMode -Version Latest
# M5: the #229 proof belongs HERE. The runner starts this launcher with stdin=subprocess.DEVNULL.
$stdinRedirected = [Console]::IsInputRedirected
Write-Host ("C3 STUB stdin_redirected=" + $stdinRedirected)
if (-not $stdinRedirected) { Write-Host "C3 STUB REFUSED: stdin is a console, not NUL; the tree lacks #229"; exit 7 }
$tree = '<tree>'; $py = '<venv>\Scripts\python.exe'
$promptSha = '<PROMPT_SHA256>'
. (Join-Path $tree 'scripts\ops\windows_kill_on_close_job.ps1')
$job = New-WeatherKillOnCloseJob
$code = 70
try {
    $childArgs = ConvertTo-WeatherWindowsArgumentString -Tokens @("-I", "-S", "-B", "C:\c3\<date>\c3_prompt_child.py", $tree, $promptSha)
    $child = Start-WeatherInteractiveProcessInJob -Job $job -FilePath $py -ArgumentString $childArgs -WorkingDirectory $tree
    $child.WaitForExit(); $code = [int]$child.ExitCode
} finally {
    if ($null -ne $job) { $job.Dispose() }   # close this stub's own kill-on-close Job; nothing else
}
exit $code
```

(The `names_the_child` check in `c3_prompt.py` compares against the literal `C:\c3\<date>\c3_prompt_child.py`. Keep
that literal in the token list exactly as written.)

### `c3_prompt_child.py` — step 8 stub wrapper (the templates' own `_prompt_until`, bound by hash) **[v3: M5]**

```python
"""C3 step 8 stub wrapper (v3): runs the tree's own _prompt_until, extracted at run time from BOTH
templates, bound by SHA-256. Nothing else from the templates is executed."""
import __future__
import ast, hashlib, json, msvcrt, sys, time
from datetime import datetime, timedelta
from pathlib import Path

TEMPLATES = ("stage0.py.tmpl", "stage1_cancel_all.py.tmpl")
EXPECTED = "C3_REHEARSAL_TYPED_INPUT_ACCEPTED"
PROMPT_WINDOW_S, RESERVE_S = 90, 30


def extract(tree: Path) -> dict:
    found = {}
    for name in TEMPLATES:
        path = tree / "scripts" / "ops" / "international_live_templates" / name
        source = path.read_text(encoding="utf-8")
        functions = [node for node in ast.parse(source).body
                     if isinstance(node, ast.FunctionDef) and node.name == "_prompt_until"]
        if len(functions) != 1:
            sys.exit(f"{name}: expected exactly one top-level _prompt_until, found {len(functions)}")
        segment = ast.get_source_segment(source, functions[0])
        found[name] = {"source": segment,
                       "prompt_until_sha256": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
                       "template_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return found


tree, mode = Path(sys.argv[1]), sys.argv[2]
extracted = extract(tree)
hashes = {name: {k: v for k, v in item.items() if k != "source"} for name, item in extracted.items()}
sources = {item["source"] for item in extracted.values()}
if mode == "--hash-only":
    print(json.dumps(hashes, indent=1))
    if len(sources) != 1:
        sys.exit("C3 PROMPT EXTRACTION FAIL: Stage 0 and Stage 1 _prompt_until differ")
    print("C3 PROMPT EXTRACTION OK")
    sys.exit(0)

pinned = mode.strip().lower()
bound = len(sources) == 1 and all(h["prompt_until_sha256"] == pinned for h in hashes.values())


def stdin_state():
    # M5: information only. This wrapper is created with bInheritHandles=false, so its stdin may be
    # None or unusable; that must never crash the evidence line. The #229 proof is at the stub launcher.
    if sys.stdin is None:
        return None
    try:
        return sys.stdin.isatty()
    except (ValueError, OSError):
        return "unusable"


print(json.dumps({"stdin": stdin_state(), "sitecustomize": "sitecustomize" in sys.modules,
                  "prompt_bound": bound,
                  "prompt_until_sha256": {n: h["prompt_until_sha256"] for n, h in hashes.items()}}), flush=True)
if not bound:
    sys.exit(8)

# The extracted function's globals: exactly what the templates provide, with a stub scope and reserve.
# A minimal builtins table makes any unexpected reference fail closed (NameError).
namespace = {
    "__name__": "c3_extracted_prompt",
    "__builtins__": {"str": str, "int": int, "list": list, "RuntimeError": RuntimeError,
                     "KeyboardInterrupt": KeyboardInterrupt, "TimeoutError": TimeoutError},
    "sys": sys, "time": time, "msvcrt": msvcrt, "datetime": datetime, "timedelta": timedelta,
    "PRE_CREDENTIAL_RESERVE_SECONDS": RESERVE_S,
    "SCOPE": {"run_not_after_local":
              (datetime.now().astimezone() + timedelta(seconds=PROMPT_WINDOW_S + RESERVE_S)).isoformat()},
}
code = compile(next(iter(sources)), "<_prompt_until extracted from stage0 and stage1 templates>", "exec",
               flags=__future__.annotations.compiler_flag, dont_inherit=True)   # the templates use the future import
exec(code, namespace)
try:
    typed = namespace["_prompt_until"](EXPECTED).strip()    # production: _prompt_until(...).strip() != confirmation
except TimeoutError:
    print(json.dumps({"typed_matches": None, "reason": "timeout"}), flush=True)
    sys.exit(5)
except KeyboardInterrupt:
    print(json.dumps({"typed_matches": None, "reason": "interrupt"}), flush=True)
    sys.exit(6)
print(json.dumps({"typed_matches": typed == EXPECTED, "length": len(typed)}), flush=True)
sys.exit(0 if typed == EXPECTED else 4)
```

## Open owner questions

1. (Carried; the Defender recommends keeping it.) R6, `caller_stdin_open=True` for the positive runs: keep?
2. (Carried; the Defender accepts it, given M5.) Does the owner accept "the templates' `_prompt_until`, extracted by
   hash and reached through the production process chain" as meeting the runbook's "reach that confirmation prompt"?
3. **Closed:** `vanishedOutsideJob` is record-only; `escaped`, `memberMismatch` and `consoleForeign` are the HARD STOPs.
4. (Defender: a follow-up PR, not #230.) R9's `SIGINT` mask in the runner's cleanup loop, with the runbook note.
5. **Closed (master-agent):** `consoleForeign>0` at close is a HARD STOP.
6. **Closed (owner leaning, Defender Q6):** a `started` difference is an ABORT (`verify=FAIL`), implemented by
   `-ExpectStarted` and `startedPin`.
7. **New [v3.1].** The fixed `c3_run.ps1` needs one more workstation self-test run (V31-R1 was found by the single
   permitted run). Authorize that run, or accept the dry pass's P8 item 6 as that run? The capture host must not see
   this script before one of them passes.
8. **New [v3.1].** The slot request mentioned "an evening before 18:00", but that is inside the protected 12:00–18:00
   window. Confirm 09:00–09:30, owner-attended (or 05:10–05:55), as the official slot.
