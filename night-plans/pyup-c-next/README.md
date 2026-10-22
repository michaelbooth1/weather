# Phase C kit for the night 2026-10-23/24 (files dated 20261024)

Operator kit for the Python 3.11.9 venv cutover (Phase C) on the capture host. This branch never goes to
master. Owner GO, relayed by master-agent, verbatim: "yes approve that for now". It covers: start at 00:30;
up to 2 same-night retries until 03:30, only for failures before the swap (before C3, zero capture gap); any
failure after the swap undoes itself and waits for the owner.

| File | Role |
| --- | --- |
| `phase-c0-run-20261024.ps1` | Standalone C0, read-only, with the G3 operator values. Writes `c0-done-20261024.flag` only when every check passes. |
| `phase-c-run-20261024.ps1` | One attempt: C0 re-run, then C1 to C10, with §R after a failure past the rename. Takes `-Attempt 1..3 -RunId <id>`. |
| `phase-c-retry-wrapper-20261024.ps1` | Runs the attempt file up to 3 times, under the mechanical decision table in its header. |
| `phase-c-raw-20261022.md` | The 10-22 runbook extract the run file mirrors. Its night-specific fills (EXPECTED_HEAD, the 01:00 timetable, roll_verdict G3) do not apply to 10-24. |
| `SHA256SUMS.txt` | Authoritative hashes. The retry wrapper refuses to run unless the run file matches its line. |

Launch everything as a FILE, elevated, with no redirects, from local copies in `C:\pyup\cp3119`. Never press
Ctrl+C in the wrapper window: the attempt shares that console and touches the Scheduler.

## Night timeline (host local, America/Toronto, EDT; not a DST night)

1. **Before 00:30.** Put the prerequisites in place (`aux-tasks.txt`, `q12.txt`, `gap-overrun.txt`, and `q12b.txt`
   if a family task exists). G5 must hold: no merge, integration attempt, U6, Stage B, training window, replay or
   research batch is scheduled for the night.
2. **00:30:00. Run the standalone C0** with the G3 values (see "G3" below). C0 refuses before 00:30. It prints
   `G3 PASS branch=...` or `G3 FAIL reason=...` and, only on PASS, writes the flag. Line 2 of the flag records the
   G3 operator values.
3. **GO review.** Master reviews the C0 receipts and the G3 PASS line, then writes `owner-go-20261024.txt` with
   first token `GO`.
4. **About 00:32 or later. Launch the retry wrapper.** Each attempt re-runs C0, including G3, from the flag's
   values, then runs C1, which takes the lease. The C1 window is **00:30 to 01:04**.
5. A pass case ends at about 01:40-01:50 when the lease is taken around 00:31.

**G3 in this timeline.** G3 runs inside C0: once in the standalone C0 at about 00:30, and again in every attempt's
C0 re-run. Each attempt runs it before C1 takes the lease and before C2 touches anything. A G3 fail therefore
comes before C3 and costs no capture gap. It is deterministic, so it is never retried:

- the standalone C0 writes no flag, so the attempt's preflight refuses with exit 3 and
  `PYUPC-GATE-REFUSAL gate=PREFLIGHT`;
- inside an attempt, the run file logs `G3 FAIL`, NO-GOes and prints `PYUPC-GATE-REFUSAL gate=G3`.

Either way the wrapper's verdict is `STOPPED reason=GATE_REFUSAL_*`.

## G3 (master ruling 2026-10-22, verbatim)

"G3 holds if HEAD equals the qualified tip, OR all of these hold: (i) no dependency file (requirements*, pyproject.toml, *.lock, constraints*, setup.cfg, setup.py) differs between the qualified tip 90b2e1844 and HEAD; (ii) the exact HEAD tree, or a tree whose non-docs diff vs HEAD is empty, has a full WS pregate PASS run on Python 3.11.9; (iii) C0's other checks are clean. Otherwise B-R is needed, and B-R may run in any 00:30-09:00 heavy window before the cutover night, including the same night after a landing."

How the kit implements it (`Test-G3Gate`, identical in both files: run file :309-328, C0 file :155-174). All git is read-only:

- **Operator-supplied values, never defaults.** The C0 parameters are listed below. The values for 10-23/24 come
  from master's ruling and are not hardcoded in any `.ps1`.
  - `-G3QualifiedTip`: the full qualified tip, `90b2e1844ad0de71916c67996026dea7b04ce5ff`. It must equal
    `qualification.json` `tip`, else `G3 FAIL reason=operator_tip_ne_qualification_json`.
  - `-G3PregateReceipt`: `pg-739c03eff1e2-20261018T045220-105120`, a PASS receipt. The workstation pregate receipt
    is not on the host, so the kit records the id and does not read the receipt.
  - `-G3TestedSha`: `739c03eff1e2f26c49759899e4e39b669d2c6628`. It must be 40-hex, start with the receipt's
    12-hex head, and exist in the production repo.
  - `-G3PregatePython`: `3.11.9`. This is an operator attestation. The workstation venv is 3.11.9, and the pregate
    uses `$RepoRoot\venv` (`workstation_pregate.ps1:60`).
- **PASS, branch `HEAD==tip`:** HEAD equals the tip. The pregate values may then be empty.
- **(i):** `git diff --name-only <tip> HEAD`. A path fails (i) when its leaf name matches `requirements*`,
  `constraints*`, `*.lock`, `pyproject.toml`, `setup.cfg` or `setup.py`, at any depth.
- **(ii):** `git diff --name-only <tested sha> HEAD`. Every path must match `^docs/.+\.md$` ("non-docs diff empty").
- **(iii):** the PASS line is printed only after every other C0 check has passed. Any C0 NO-GO stops before it.
- **Fixed output.**
  - Pass: `G3 PASS branch=HEAD==tip tip=<sha>`, or
    `G3 PASS branch=(i)+(ii)+(iii) deps_changed=none pregate=<id> tested=<sha> nondocs_diff=empty`.
  - Fail: `G3 FAIL reason=<token> head=<sha> tip=<sha>`, followed by `NO-GO: G3 FAIL: ...`.
- **On a fail:** no retry. B-R per the ruling, then a new C0.
- **Operator command** (one line):
  `Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File C:\pyup\cp3119\phase-c0-run-20261024.ps1 -G3QualifiedTip 90b2e1844ad0de71916c67996026dea7b04ce5ff -G3PregateReceipt pg-739c03eff1e2-20261018T045220-105120 -G3TestedSha 739c03eff1e2f26c49759899e4e39b669d2c6628 -G3PregatePython 3.11.9'`
- **Static pre-check on the workstation.** Against N12 `068591d0671af92a7d1ae351df331b68f18b279b`: (i) no
  dependency file, (ii) an empty non-docs diff against `739c03eff`, so PASS. This holds only if the host HEAD is
  exactly N12. A local drift commit on the host (10-22 had one with two fleet config files) is a non-docs diff and
  fails (ii).

## CLOCKS (re-derived from the 00:30 floor)

The 10-22 kit put the C1 floor at 01:00, the quiet-window start. That floor was a runbook choice
(runbook follow-up, "The 01:00 floor is the 01:00-04:00 quiet window ... and stays"). No code requires it (see
"Quiet window" below). The other clocks fall into two kinds:

- **Back-anchored deadlines** are set by the end of the night and do not depend on the start: §R must end by 03:45,
  owner reachability (G4) runs to 03:45, and the 04:15 `WeatherTrainingWindowRestore` must never fire mid-cutover.
  The deadline chain runs backward from those anchors, so a 00:30 floor only widens the C1 window.
- **Waits** are task time limits plus a margin, so they are durations and do not move.

| Clock | Old (10-22) | New (10-24) | Derivation |
| --- | --- | --- | --- |
| Standalone C0 launch | 00:30-00:55 (runbook) | 00:30:00, refused earlier (C0 :27) | 00:00-00:30 is the protected near-close tail (HOST_LOAD_POLICY window table). The flag must be written after midnight. |
| C1 floor (preflight) | 01:00 | **00:30:00** (run :66) | Lease admission opens at minute 30 (`workload_admission.ps1:596-598`, `$localMinute -ge 30`). Before that, `Enter-WeatherHeavyWorkloadLease` throws (`:1771-1775`). |
| C0 re-run inside an attempt | ~13 s | ~13 s (plus G3: 3 read-only git calls) | Measured on 10-21/22 (01:01:14 to 01:01:27). |
| First lease probe | ≥ 01:00:13 | ≥ 00:30:13 | Floor plus the C0 re-run. |
| Lease probe retry sleep | 30 s | 30 s (run :387) | A duration. It can overshoot the deadline by ≤ 30 s, which the post-acquire check (run :389) catches. |
| C1 lease deadline | 01:04 | **01:04** (run :385, :389, preflight :67) | T − (C1 1 min + shadow seal 3.17 + tape ensure 2.58 + C2 rest 1.25) = 01:12 − 8.0 min. T is back-anchored, so this does not move. The C1 window grows from 4 to 34 min. |
| C2 shadow seal wait | 180 s | 180 s (run :442) | A duration (STOP-file seal). |
| C2 tape-supervisor ensure wait | 150 s | 150 s (run :450) | 2 min `ExecutionTimeLimit` (`register_execution_tape_supervisor.ps1:34`) + 30 s. |
| Pre-C3 deadline T | 01:12 | **01:12** (run :520) | S − C3 pass-case worst case: 5.5 (ensure) + 1 (stop verbs) + 10 (gate) + 1 = 17.5 min. 01:30 − 17.5 = 01:12:30, rounded down. |
| C3 supervisor ensure waits | 330 s | 330 s (run :475) | Snapshot supervisor 5 min limit (`register_snapshot_supervisor.ps1:46`) + 30 s. |
| C3 stop-confirmation gate loop | 600 s | 600 s (run :484) | A duration. |
| Swap deadline S (C4) | 01:30 | **01:30** (run :528) | Core decision 02:15 − 45 min (C5 build, C6, C7 `Wait-Restore` ≤ 32 min, C8). Back-anchored. |
| `Wait-Restore` (C7, undo, §R) | 32 min, rerun after 16 | same (run :491, :495) | 15 min task limit (`register_training_window.ps1:153`): one run plus one rerun. |
| C8 operator decision | max(02:15, now + 5 min) | same (run :575) | Core decision by 02:15 (runbook C9). Back-anchored: 02:45 §R start − 30 min (C9b, C9c settle 10 min, tape 5 min). |
| C9c operator decision / §R start limit | 02:45 | **02:45** (run :644, :171) | §R worst case ~60 min (69 if every ensure wait runs out): 02:45 + 60 = 03:45 (G4, owner ruling), + 69 = 03:54. Both before 04:10 and 04:15. |
| §R not 3/3 escalation | 03:45 | 03:45 | G4 owner reachability and the 10-19 owner ruling. |
| Dead-man restore | 04:15 daily | 04:15 (C0 asserts it is armed) | A scheduled task, not ours. Every capture-disrupting step must end before it. The chain above ends ≤ 03:54. |
| C0 next-runs horizon | < 04:00 | < 04:00 (run :369) | Covers everything up to the end of §R. |
| Hold reminder / auto-release | 08:30 / 08:55 | same (run :129-130) | Anchored on the 09:00 end of the heavy window. |
| Retry: no attempt starts at or after | — | **03:30** (owner) and **after 01:04** (lease deadline) | Owner cutoff 03:30. A start after 01:04 would only be refused by the run file's preflight (exit 3), so the wrapper stops instead (`LEASE_WINDOW_CLOSED_0104`). **The 03:30 cutoff never binds tonight; 01:04 does.** |
| Retry settle | — | 60 s | Lets the restarted holders and the released lease settle before the next C2. |
| Retry restore-verify waits | — | holders 90 s, tape status 180 s (run :84-112) | Read-only checks after the undo. A tape status call is the same command as C9c. |

Worst-case attempt arithmetic for retries:

- An attempt that stops in C2 costs about C0 0.2 + C1 1 + C2 ≤ 8 + undo ~1 + restore verify ≤ 4.5 + settle 1,
  about 16 min at worst and typically 3-5 min.
- So attempts launched about 00:32, 00:37 and 00:42 all fit before 01:04 in the typical case. In the worst case
  the third attempt meets the 01:04 lease deadline and is not started.
- A retry with an earlier C1 still uses the same back-anchored deadlines, so it can only have more slack, never less.

## Quiet window (QWM) interaction: the 01:00 floor does not apply to C

Refuted from code:

- `quiet_window_merge.ps1:18-21` and `:3274-3279` refuse 12:00-00:30.
- `:3281-3284` then takes the same shared lease (`Enter-WeatherHeavyWorkloadLease -Workload quiet_window_merge`)
  and fails if another workload holds it.
- The 01:00-04:00 confinement applies only to a roll-sensitive branch, after the roll verdict (`:3360-3362`, after the roll verdict from `:3300`).
- The only floor for a lease user is minute 30 (`workload_admission.ps1:596-598`).

C does no git merge. Its git calls are all read-only:

- `rev-parse HEAD` (run :263, :341);
- `status --porcelain --untracked-files=no` (run :355 in C0, :548 in C6);
- the G3 `diff --name-only` and `cat-file -t` calls (run :317, :324-325, and the same in C0).

`git status` can briefly take `.git\index.lock` to refresh the index.

Collision analysis:

- From C1 to the release, C holds the lease, so any QWM run fails at `:3284` before touching git.
- Before C1, the C0 re-run (≈13 s) and the standalone C0 run without the lease.
- A ROLL-FREE QWM is admitted from 00:30, so on this night the 00:30-01:00 slot is no longer free of possible
  merges. A merge running at that moment would make C0 NO-GO ("prod tree dirty", or HEAD differing from the flag
  gives exit 4). Both are deterministic gate refusals with no retry. C0's `git status` could also make that merge
  fail on `index.lock`.
- G5 (no merge or integration attempt that night) and the C0 next-runs check (any non-exempt task due before
  04:00 must be absent from the GO review) are the guards.

**Master: the state of play (10-21) schedules the MG-1 bound + SD-1 merges for 10-23/24, and
`origin/claude/integration-20261023-n13-on-docs` exists. Neither may run that night if C runs.**

## Retry markers and decision

The marker formats and the decision table live in the run file and wrapper headers. The self-test (a scratch
script, not in the kit) dot-sources the wrapper and feeds it fake transcripts. It passes 20 decision cases and
6 G3 cases.

Retries happen only for a stop before C3 that:

- exits 1,
- carries `PYUPC-RESTORE-VERIFY result=PASS`,
- carries no `PYUPC-GATE-REFUSAL` marker, and
- leaves the next start at or before 01:04 and before 03:30, within 3 attempts.

Anything at or after C3, or any marker that is missing or unparseable, gives WAIT-FOR-OWNER.
