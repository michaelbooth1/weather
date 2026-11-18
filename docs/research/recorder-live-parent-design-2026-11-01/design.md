# Live parents for long-running workers: design (2026-11-01)

Status: research design, lane L34, workstation DESKTOP-RFCD2GH. It proposes changes and acts on none.
No Task Scheduler, launcher, pin, process or system setting was changed. Times are UTC unless marked
local. The workstation clock is EST (UTC-5); DST ended at 06:00 UTC that morning.

## 0. Verdict

- **Exposure (verified).** All 10 workstation forward recorders hang off one short-lived WMI provider host.
  Every capture-host loop launched by an `ensure` task hangs off a short-lived `ensure` interpreter. In both
  cases the top `ParentProcessId` of the worker chain names a process that has exited. Windows keeps that
  stale number, and a later unrelated process can reuse it. A tree kill (`taskkill /PID <reused> /T`)
  that walks numeric parent ids then reaches the workers.
- **Cause of the 22:06-22:08 death (UNVERIFIED).** The stale-parent tree kill matches the evidence: all 10
  died at once with no error tail, they share one parent, and an unrelated python and node processes
  survived. No record ties a `taskkill` target to the old parent PID, because that PID was never logged
  (§1.3).
- **Harness behaviour.** Claude Code 2.1.309 contains a Windows kill path that runs
  `taskkill.exe /PID <pid> /T /F`. This is verified from the installed binary, and the Codex binary
  contains a similar path. Whether either fired at 22:06 on a PID equal to the old parent is
  **UNVERIFIED**. Whether `taskkill /T` checks child creation time is also **UNVERIFIED**: Microsoft's
  documentation is silent, a public Codex bug report asserts it does not, and a self-contained probe
  here was inconclusive (§3).
- **Recommendation.**
  - **Workstation:** option (a). Each recorder runs as its own Task Scheduler task, with the existing
    launcher in a foreground mode, so the chain is Schedule svchost → launcher → recorder, and every
    parent stays alive for the worker's life. Log the WMI parent in the meantime (§4.1). This needs the
    owner's yes.
  - **Capture host:** before 12-13, only roll-free, read-only or documentation changes (§4.2). The
    structural change (option (d), a parent handle in the loop, or option (a) for loops) waits for the
    quiet window and an owner decision after 12-13.

## 1. Parent chains today and why the parent is dead

### 1.1 Workstation forward recorders (read-only census, 2026-11-01 ~22:50Z)

The launch path is the same for all 10 recorders. Each trigger runs the recorder's pinned launcher
(`C:\wt\<lane>\tools\research\*_forward_recorder_launch.ps1`). The launcher checks three things: the STOP
file in `<OutDir>`, the git blob pins of the recorder code, and whether the PID in `recorder.pid` is alive
with a matching command line. Then it calls `Invoke-CimMethod Win32_Process Create` with
`cmd.exe /c ""venv\python.exe" <recorder>.py ... 1>>stdout_<stamp>.log 2>>stderr_<stamp>.log"`. The
launcher exits within about a minute.

The triggers are:

- a logon task per recorder, "L13 ... forward recorder (logon)", Interactive, limit PT10M;
- "L13 HRRR forward recorder keepalive (launcher)" every 15 minutes, for HRRR only;
- "L13 recorder keepalive (15 min)", which runs `C:\wt\l13rk\tools\research\recorder_keepalive.ps1`.
  The keepalive checks the sha256 pin of each launcher and starts it hidden through `Start-Process`. It
  waits up to 90 s and has a mutex and a STOP file.

The resulting chain, observed for all 10:

```
WmiPrvSE.exe (pid 42348, EXITED)          <- WMI provider host that executed Win32_Process.Create
  cmd.exe /c ... 1>>stdout 2>>stderr      <- ParentProcessId = 42348 (stale), not in a Job
    venv\Scripts\python.exe <recorder>    <- venv redirector, parent alive
      Python311\python.exe <recorder>     <- real interpreter, in the redirector's Job, parent alive
```

| Recorder | Worktree | cmd pid | cmd ppid | Created (UTC) |
| --- | --- | --- | --- | --- |
| hrrr | C:\wt\l13 | 60424 | 42348 (dead) | 22:15:02 |
| ecmwf_ens | C:\wt\l13ens | 59396 | 42348 (dead) | 22:15:02 |
| eccc_gem | C:\wt\l13gem | 33300 | 42348 (dead) | 22:15:05 |
| gefs_00_12_18z | C:\wt\l13gc | 29168 | 42348 (dead) | 22:15:07 |
| gefs_06z | C:\wt\l13g | 8004 | 42348 (dead) | 22:15:10 |
| mosmix | C:\wt\l13mx | 20364 | 42348 (dead) | 22:15:12 |
| nbm_text | C:\wt\l13nbm | 49408 | 42348 (dead) | 22:15:14 |
| l3_t1_price | C:\wt\l3t1rec | 48456 | 42348 (dead) | 22:15:16 |
| l8_om_prev_runs | C:\wt\omprevrec | 53500 | 42348 (dead) | 22:15:19 |
| iem_mos | C:\wt\l13iem | 61084 | 42348 (dead) | 22:15:21 |

**Why the parent is dead.** `Win32_Process.Create` runs inside the CIMWin32 provider, which is hosted by
a `WmiPrvSE.exe` instance. That host is an on-demand process and unloads after it has been idle for a
while. A new host, pid 60900, started at 22:47:15. Every `cmd` it created keeps the host's PID as
`ParentProcessId`. A burst of launches within the idle timeout shares one host. That is why the whole
set has one parent: the 10-30 21:47:42-21:48:18 batch did, and so does the 11-01 22:15:02-22:15:21
keepalive batch. A single PID-reuse event can therefore take out all 10 at once. **Today's set carries
the same exposure that killed the previous one.**

The WMI detach was itself a mitigation. On 10-26 recorders that were children of agent tool shells
died, presumably because the harness reaped tool-call trees ([delegation contract §4 process
defect](../../operations/DELEGATION_CONTRACT.md)). WMI removed the agent shell from the ancestry, but it
put a transient process there instead.

### 1.2 Capture-host workers (repository reading only; no host commands)

| Worker | Launch path (scripts/ops) | Chain | Parent state |
| --- | --- | --- | --- |
| CLOB book loop | `register_clob_supervisor.ps1`, task `WeatherClobBookLoopSupervisor`. S4U, AtLogOn plus 1-min repetition, IgnoreNew, limit 2 min. Action `venv\pythonw -m weather.operations.thin_ensure --ensure --loop clob` | Schedule svchost → ensure (venv redirector → interpreter) → `market_microstructure.ensure_clob_loop` → `supervisor.launch_detached` (`DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP`, no breakaway) → loop redirector → loop interpreter | ensure exits in seconds, so the loop redirector's ppid is stale. Census: pythonw 9488, ppid 10004 DEAD |
| Snapshot tracker | `register_snapshot_supervisor.ps1`, `WeatherSnapshotLoopSupervisor`. Every 2 min, limit 5 min. `thin_ensure --ensure --loop snapshot` | same, via `snapshot_tracker.ensure_loop` → `launch_detached` | Census: 20128, ppid 14672 DEAD |
| Observation trigger | `register_observation_trigger_supervisor.ps1`, `WeatherObservationTriggerSupervisor`. 1 min, limit 2 min. `-m weather.operations.observation_trigger ensure` | same, via `observation_trigger.py` → `launch_detached` | Census: 11204, ppid 16984 DEAD |
| Execution tape | `register_execution_tape_supervisor.ps1`, `WeatherExecutionTapeSupervisor`. 1 min, limit 2 min. `-m weather.operations.execution_tape_supervisor ensure` | same, via `execution_tape_supervisor.py` → `launch_detached` | Census: interpreter 4600 under redirector 10128, whose ppid 7428 is DEAD. The census did not name this worker; matching 4600 to execution tape is an inference, because it is the remaining `launch_detached` worker |
| Maker shadow | `register_maker_shadow_runner.ps1`, `WeatherMakerShadowRunner`. Action is the worker itself (`-m weather.market.maker_shadow run --stop-file ...`). ExecutionTimeLimit 0, 5-min repetition, IgnoreNew | Schedule svchost → redirector → interpreter | live (svchost 3400) |
| Maker evidence | `register_maker_evidence_capture.ps1`, `WeatherMakerEvidenceCapture`. Action is the worker. ExecutionTimeLimit 0, 1-min repetition, IgnoreNew | Schedule svchost → redirector → interpreter | live (svchost 3400) |

`boot_recovery.ps1` (AtStartup) and the operator restart scripts reach the same `ensure` entry points.
They inherit the same dead-parent shape.

**Why the parent is dead.** The `ensure` design deliberately makes the scheduled action short-lived. It
observes, decides, possibly calls `launch_detached`, and exits well inside its 2-5 minute limit. The loop
outlives its launcher by days, so its top `ParentProcessId` is stale within seconds of each start. The
maker pattern is the only one with a live parent. Its task action is the worker, so the parent is the
Schedule service host, which lives as long as the service.

**The repository's own guard is safe.** `memory_commit_guard.ps1` rejects a child whose creation time
is earlier than its parent's, in `Get-ProcessTreeRows`, `Get-AgentToolRoot` and the orphan sweep. It
also re-checks creation identity before each `Stop-Process`. This is the Raymond Chen rule (§3.3). The
remaining raw `taskkill /T` call sites (`training_window.ps1` and three test helpers) belong to lane L33.

### 1.3 What the 22:06-22:08 evidence does and does not show

- The keepalive saw all 10 alive at 22:00:02 and all 10 dead at 22:15. HRRR's own launcher log agrees:
  pid 52532 was alive at 22:00:01 and restarted at 22:15:03. The death time comes from the master; the
  15-minute keepalive cannot see anything finer than its interval.
- Unrelated long-lived processes survived. A python started 10-27 17:46 and the youtube-trader node
  trees started 10-27 17:45 are still alive. That rules out a kill by image name (`python.exe`,
  `node.exe`) and a logoff.
- The co-resident youtube-trader supervisor (`apps/youtube-projector/scripts/supervise.js`) does run
  `taskkill /PID <pid> /T /F`. Its targets are verified collector PIDs, and the collector nodes it
  supervises are still the 10-27 instances, so it did not fire. It remains a standing stale-PPID hazard
  on this machine (§3.4).
- The previous WMI host PID was never recorded. The launcher logs only the `cmd` PID and the
  interpreter's parent, so no `taskkill` target can be matched against it after the fact. §4.1 item 1
  closes that gap.
- Several Claude Code tool calls from one coordinator session completed in the window. They include a
  PowerShell call from 22:05:08 to 22:05:28, and a Bash call from 22:04:22 to 22:09:24 that ran a
  bounded pytest wrapper. That run reported no timeout, and the repository's `taskkill /T` helpers in
  tests fire only on timeout. The transcripts show normal completions, not aborts. Co-occurrence is not
  attribution.

## 2. Options

Two kinds of kill matter here, and every option is judged against both:

- **K1, stale-PPID tree kill.** Someone tree-kills an unrelated process that has reused the worker's
  dead parent PID. This is the 22:06 hypothesis.
- **K2, deliberate tree kill of the true parent.** Someone tree-kills the worker's real, live parent. A
  live parent closes K1, because a PID cannot be reused while its process exists, or while any handle to
  it is open (§3.3). It does nothing for K2.

### (a) Launched directly by Task Scheduler, so the parent is the Schedule svchost (the maker pattern)

**What it is.**

- The task action runs the worker in the foreground, or runs a wrapper that runs it in the foreground
  and waits. Settings: `ExecutionTimeLimit 0`, `MultipleInstances IgnoreNew`, and a repetition trigger
  as the keepalive. The repetition is a no-op while an instance runs and a restart after a death.
- On the workstation the wrapper is the existing launcher with a new foreground switch. It keeps its
  STOP, pin and alive checks, then runs `& $Python $script ... *>> logs` or `Start-Process -Wait
  -NoNewWindow` instead of the WMI create. The launcher then stays alive as the worker's parent.

**Protects against.**

- K1, for every link: svchost lives for the service's life, and the wrapper and redirector live for the
  worker's life.
- Harness reaping: the task is not a descendant of any agent shell.
- Shared blast radius, if each recorder has its own task: no single parent then spans more than one
  recorder.

**Does not protect against.**

- K2 on the wrapper PID, or a kill of the Schedule host (Task Scheduler service restart).
- Stopping the task (End, re-registration, or the time limit, if one is set). Task processes run inside
  a Task Scheduler Job (the census found task children `in_job`). Whether Stop terminates the whole Job
  or only the action process is **UNVERIFIED** here; testing it needs a throwaway task, which is a
  Scheduler change.
- Interactive logon type: tasks registered "Interactive" run only while the user is logged on, so
  logoff ends them. S4U survives logoff but changes the principal, and needs the owner's yes.

**Reboot.**

- AtLogOn (Interactive) or AtStartup (S4U) restarts the workers.
- The repetition trigger with `StartWhenAvailable` covers missed ticks.

**Keepalive.**

- The 15-minute keepalive becomes redundant as a starter. Keep it check-only as the per-recorder gap
  logger, or point it at `Start-ScheduledTask` instead of launching directly.
- Worst-case restart lag becomes the repetition interval. Use 5 minutes, which is cheap with IgnoreNew.
  Today's lag is 15 minutes.

**Log handles.**

- The wrapper owns the redirection. `cmd /c ... 1>> 2>>` still works, with cmd under a live wrapper.
- Per-launch `stdout_<stamp>.log` naming is unchanged.
- No handle is inherited by Task Scheduler.

**STOP files.**

- The launcher's precheck still runs on every repetition tick.
- To stop a running recorder: create STOP, then stop the task or the recorder PID. Nothing restarts it,
  because the next tick refuses on STOP.

**Pins.**

- Launcher sha256 pins in the keepalive change once, for the foreground switch.
- The recorder blob pins are untouched.
- The task action pins the launcher path, as today.

**Cost.**

- The logon task's action changes, and its limit goes from PT10M to 0. The HRRR keepalive task and
  the L13 keepalive change role.
- Each is a Scheduler change and needs the owner's yes.

**On the host**, applying (a) to the `ensure` loops means making the task action the loop itself. That
removes the `ensure` layer's heartbeat-hang detection, its restart budget, pause flags, and the
STALE_CODE readoption restart, or forces them to become task stop/start operations. It is a large
design change, not a pre-12-13 candidate.

### (b) A persistent keepalive or supervisor that stays alive as the parent

**What it is.** One long-running supervisor, for example the keepalive converted to a loop, with its
task set to `ExecutionTimeLimit 0`. It starts the workers as direct children with `Start-Process`, not
WMI, and restarts them when they exit. It can wait on process handles instead of polling every 15
minutes.

**Protects against.**

- K1, while the supervisor lives.
- Restart lag is seconds instead of 15 minutes.
- Exit codes and exit times are captured exactly. Today a death is invisible until the next tick.

**Does not protect against.**

- K2 on the supervisor: one tree kill takes all children, the same blast radius as today's shared WMI
  parent.
- The supervisor's own death. Its children's top PPID then goes stale again, unless they die with it
  through (c).
- Supervisor code updates force a choice: restart all workers, or let them orphan, which brings back
  the stale PPID. That conflicts with "the recorder keeps running across launcher changes".

**Reboot.**

- The supervisor's task trigger brings it back.
- An outer watchdog task is still needed in case the supervisor itself dies.

**Logs, STOP and pins.**

- The supervisor must reimplement each launcher's STOP, pin and alive checks, or call the launchers in
  a foreground mode. That is the same launcher change as (a), plus a new long-lived component that must
  be pinned and reviewed.

**Verdict.** (b) is weaker than (a) on blast radius and on the update story, and adds code. Choose it
only if per-recorder tasks are unacceptable.

### (c) A Job object that owns the workers, without breakaway

**What it is.** A holder process creates a Job and starts each worker suspended inside it, as the
existing `scripts/ops/windows_kill_on_close_job.ps1` does with `CREATE_SUSPENDED` plus assignment.
Membership is then an identity that cannot be recycled. Enumeration goes through the Job, and teardown
through `TerminateJobObject`. Optionally the Job is `KILL_ON_JOB_CLOSE`.

**Protects against.**

- Orphan leaks.
- Mis-targeted teardown by the repository's own code, which kills the Job instead of a PID tree.
- Grandchildren escaping, since there is no breakaway.

**Does not protect against.**

- **K1 by itself.** A Job does not change `ParentProcessId`, and `taskkill /T` walks parent ids, not
  Jobs. If the holder exits, the workers' top PPID is stale again (or, with kill-on-close, the workers
  die).
- K2, or a kill of the holder: with kill-on-close, any holder death kills every worker. That is
  deliberate for bounded heavy work (`workstation_heavy.ps1`) and wrong for always-on recorders.

**Reboot and keepalive.** No effect; a Job dies at reboot. The holder needs (a) or (b) to exist.

**Logs, STOP and pins.** Unchanged, but suspended-start assignment needs the C# helper, so another
pinned script.

**Verdict.** (c) is a complement to (a) or (b), not a fix. It is right for bounded jobs and for a future
supervisor's teardown. It is not the answer to K1.

### (d) Parent-handle reservation by the worker (extra option)

**What it is.** At startup the worker opens a `SYNCHRONIZE` or `PROCESS_QUERY_LIMITED_INFORMATION`
handle to the topmost ancestor that will exit, and holds it for life. For a workstation recorder that
ancestor is the WmiPrvSE host. For a host loop it is the `ensure` interpreter. Before trusting the
handle, the worker verifies that ancestor's creation time is not later than the child's. An open handle
keeps the process object, and therefore its PID, from being freed (§3.3). The stale number then cannot
be reused for the worker's life.

**Protects against.**

- K1, for any launcher (WMI, `ensure`, a harness), without changing the launch topology, the task
  shape, the restart semantics or STALE_CODE readoption.

**Does not protect against.**

- K2, and a deliberate kill by number of the reserved PID.
- The start-up race if the ancestor exits first, which the creation-time check detects.
- Access: opening a handle to a WmiPrvSE running as SYSTEM or NetworkService from a Limited user may be
  denied; **UNVERIFIED**.

**Cost.**

- One kernel process object per worker.
- A code change in the worker. On the workstation that is a recorder blob-pin change, so it needs the
  owner's yes. On the host it touches a loop-imported module, so it is roll-sensitive and lands in the
  quiet window.

## 3. The harness hypothesis

### 3.1 Claude Code (verified from the installed binary, not from public docs)

The Claude Code build running these sessions is 2.1.309, at
`%LOCALAPPDATA%\Claude-Data\claude_*\claude-code\2.1.309\...\claude.exe`. Its embedded JavaScript has a
Windows kill routine. It pins the target PID with `Bun.ant.windowsProcessPin(pid)`, spawns
`%SYSTEMROOT%\System32\taskkill.exe` with `["/PID", pid, "/T", "/F"]`, and falls back to
`process.kill(pid)`. Failures are logged as `killProcessTree taskkill failed` under the telemetry event
`tengu_bash_tool_kill_error`. So this is the Bash or PowerShell tool's process-tree kill. A second path
in the agent spawner runs `taskkill /T /F /PID <pid>` on Windows.

The same binary has a separate in-process tree walk (`windowsProcessList`), and that walk keeps a
child only if its creation time is at or after the parent's. The authors guard their own walk against
PID reuse, but the kill is delegated to `taskkill /T`, which does its own traversal. The pin protects
the target PID. It does not protect stale-PPID children of that target.

When the routine runs is **UNVERIFIED**. The telemetry name points to tool kill (timeout, interrupt,
background stop), but it may also run at every normal completion. No public documentation for this was
found.

### 3.2 Codex

- The installed `codex.exe` contains `taskkill` invocations and the string
  `failed to run taskkill for exec-server stdio process tree` next to `/PID /T /F`.
- Public bug [openai/codex#36258](https://github.com/openai/codex/issues/36258), "[Windows][MCP]
  taskkill /T can terminate the host application after stale PPID reuse", is open as of 2026-11-01 with
  no maintainer response. It describes `codex-rs/rmcp-client` running `taskkill /PID <pid> /T /F`, with
  a numeric PID only and the result ignored, while tearing down a stdio MCP server. In the reported
  incident about 90 unrelated processes died within two seconds, including a host process about 24
  hours old. The reporter asserts that `/T` walks numeric PID/PPID relations without validating
  creation identity. Like ours, the report cannot prove which invocation did the kill.

### 3.3 Does `taskkill /T` check child creation time?

- Microsoft's [taskkill reference](https://technet.microsoft.com/en-ca/library/bb491009.aspx) describes
  `/t` only as terminating the process and the child processes it started. It says nothing about PID
  reuse or creation time. **No primary source says taskkill checks it.**
- Raymond Chen, ["Why is CreateToolhelp32Snapshot returning incorrect parent process IDs all of a
  sudden?"](https://devblogs.microsoft.com/oldnewthing/20150403-00/?p=44313) (2015), is primary
  Microsoft guidance on the hazard. The parent id is recorded at creation, and after the parent exits
  the id can be reassigned. Callers must compare the reported parent's creation time with the child's.
  Holding an open handle to a process keeps its id from being reused, and a Job object is the reliable
  way to find a process's children. Options (c) and (d) rest on this.
- **Probe here: inconclusive.** A self-contained probe was run twice; it used only processes it
  created, ran under 45 s and used a few MB. It let parent A exit, leaving a marker `ping` child B, then
  spawned and killed throwaway processes to obtain A's PID again. It would have aborted if any foreign
  process shared the stale PPID. About 6,000 spawns per run never reused A's PID, so no `taskkill` was
  ever issued. Marker processes were cleaned up, with 0 left. Recent Windows builds do not reuse a freed
  PID quickly, so this probe cannot settle the question.
- **Verdict:** creation-time checking by `taskkill /T` is UNVERIFIED. Treat it as absent: the bug
  report asserts it, and nothing documents the opposite.

### 3.4 Other tree-killers on this workstation

`youtube-trader/apps/youtube-projector/scripts/supervise.js` runs `taskkill /PID <pid> /T /F` after it
verifies that the target's command line is its own `src/server.js`. That check is correct for the
target and irrelevant for stale-PPID children. It did not fire at 22:06 (§1.3), but it is a standing
K1 source for any WMI-launched recorder.

## 4. Landing plan

### 4.1 Workstation recorders (propose only; each item needs the owner's yes in the coordinator chat)

1. **Attribution logging.** Smallest change; launcher sha change only. Each launcher logs the `cmd`
   wrapper's `ParentProcessId` and that parent's creation time, so the WMI host is identified. The
   keepalive appends a once-per-tick stale-PPID census line: worker, top ppid, whether that ppid is
   alive, and if it is alive, the holder's image and creation time. The next mass death is then
   attributable or excluded. Keepalive launcher pins move with it.
2. **Option (a) per recorder.** Add a `-Foreground` switch to each launcher, defaulting to today's
   behaviour. Re-register each "(logon)" task with action `launcher -Foreground`, `ExecutionTimeLimit
   0`, IgnoreNew, AtLogOn plus a 5-minute repetition, and keep it Interactive. Retire the HRRR keepalive
   task. Make the L13 keepalive check-only.
   - Cut over one recorder at a time: create STOP, let the current instance be stopped, remove STOP,
     start the task.
   - Each recorder gaps for under a minute.
3. **Optional (d) in recorder code**, only if (a) is refused. This needs a recorder blob-pin change per
   lane worktree.
4. **Not recommended:** (b) as the primary design, or (c) alone.
5. **Agent discipline, docs only.** Never `taskkill /T` by PID on the workstation. Use `Stop-Process` on
   one creation-verified PID, or a Job.

### 4.2 Capture host (assume no launcher change before 12-13)

A change qualifies as tiny and roll-clean only if `scripts\ops\roll_verdict.ps1 -Branch <b>` returns a
roll-free verdict, and the change needs no Scheduler re-registration and no process restart.

| Change | Roll verdict expectation | Qualifies before 12-13? |
| --- | --- | --- |
| This design doc, and a policy line in the host load policy and operations role: agents never run `taskkill /T` by PID on the host, and use the guard's creation-verified tree stop or a Job instead | Markdown, roll-free | Yes |
| A read-only `.ps1` stale-PPID census, run by hand. It lists each capture worker, its top ppid, whether that ppid is alive, and the holder's identity if it has been reused | `.ps1`, roll-free; no registration | Yes |
| Scheduling that census | Scheduler change | No (owner yes; after 12-13) |
| Option (d) in loop code (`supervisor.launch_detached` child-side handle, or each loop's start-up) | Loop-imported Python, roll-sensitive (STALE_CODE restart) | No; quiet window after 12-13 |
| Option (a) for `ensure` loops (task action becomes the loop) | `.ps1` re-registration plus Python semantics change | No; needs a design decision |
| Option (c) in `launch_detached` | Roll-sensitive, and does not fix K1 | No |

The maker workers already have live parents and need no change.

## 5. Open questions

1. Does Task Scheduler's Stop or time limit terminate the whole task Job, or only the action process?
   This decides whether option (a) with a wrapper is stopped cleanly. Answering it needs a throwaway
   task, which needs the owner's yes.
2. When does Claude Code 2.1.309 call its `taskkill /T` routine: only on timeout or interrupt, or at
   every tool completion? The same question applies to Codex's exec-server and MCP teardown.
3. Can a Limited-token process open `SYNCHRONIZE` on the CIMWin32 WmiPrvSE host? This decides whether
   option (d) is feasible for WMI-launched workers.
4. Enabling process-termination auditing (Security 4689 with the caller) would attribute the next
   event. It is a system-setting change, so it needs the owner's yes. Is it wanted on the workstation,
   the host, or neither?
5. Which capture-host worker is census pid 4600? §1.2 infers execution tape.
6. Should each recorder get its own WMI host (impossible to force), or should launches be staggered so
   that no two share a parent? (a) makes this moot.
