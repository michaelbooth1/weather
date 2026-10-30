# HRRR keepalive replacement: launcher task registrar (lane L13, 2026-10-30)

Dated research note, not canonical guidance. **Status: drafted and tested, NOT registered.** Registering is a
Scheduler change, and every Scheduler change goes through the coordinator and the owner. Agents never run this
registrar without `-WhatIf`.

- **Code:** `tools/research/register_hrrr_keepalive_task.ps1`.
- **Tests:** `tests/sources/test_hrrr_keepalive_registrar.py`.
- **Action:** the existing `tools/research/hrrr_forward_recorder_launch.ps1`, the launcher the HRRR logon task already
  runs, from the pinned worktree `C:\wt\l13`.

## Why

The old task "L13 HRRR forward recorder keepalive" ran `cmd.exe /c C:\t\l13\recorder_keepalive.cmd` every 10 minutes
with StartWhenAvailable on. Its three relaunches failed for one reason: it started the recorder without
`--wait-lock-seconds`, so the new process exited while the dying recorder still held the single-instance lock. The
task was Disabled. It was deleted on 2026-10-30 (see Incident), and the owner ruled that it stays deleted.

## Shape

| Setting | Value |
| --- | --- |
| Trigger | once at the next quarter hour, then repeating every 15 min with no end |
| StartWhenAvailable | off, so there is no catch-up burst after sleep or logoff |
| MultipleInstances | IgnoreNew |
| ExecutionTimeLimit | PT2M |
| Principal | current user, Interactive, Limited |

The launcher refuses when:

- the STOP file `C:\t\l13\hrrr_forward\STOP` exists;
- a pinned code blob does not match.

It does nothing when the PID in `recorder.pid` is alive with a recorder command line. Otherwise it starts the
recorder detached through WMI with `--wait-lock-seconds 120` and appends a line to `C:\t\l13\recorder_pid_log.txt`.
The recorder is not in the task's process tree, so the 2-minute limit stops only the launcher.

The registrar refuses unless all of these hold:

- the launcher's sha256 equals `-ExpectedLauncherSha256`;
- the new task does not exist yet;
- any old keepalive task is Disabled and has the `recorder_keepalive.cmd` action.

If all hold, it registers the new task, then unregisters the old one.

## Incident (2026-10-30): a stubbed test reached the real Task Scheduler

The first version of the test ran the registrar without `-WhatIf` and replaced the Scheduler cmdlets with global
function stubs. But `ScheduledTasks` is a CDXML module, and its commands are functions. The registrar's first
`New-ScheduledTaskAction` call autoloaded the module, and the import replaced the stubs. So the real cmdlets ran:

- they registered a "(launcher)" task that pointed at a fixture path;
- they unregistered the real Disabled keepalive task, whose action matched the registrar's guard.

The coordinator removed the stray task with the owner's answer. The old task stays deleted. No live task or recorder
was affected.

There are now three guards:

1. The harness imports `ScheduledTasks` before defining its stubs and forces any autoload. It refuses to run the
   registrar unless every Scheduler mutator resolves to a harness function, and it checks again after the run.
2. The tests use fake task names, so even a failed stub cannot match a real task.
3. The registrar itself refuses when `WEATHER_TASK_TEST=1` is set and a Scheduler command is the real module
   command. A test runs the registrar with no stubs to prove the refusal.

The same pattern exists in other repository tests that stub the scheduled-task cmdlets without importing the
module first. These are listed in lane L13's report to the coordinator and have not been changed here.
