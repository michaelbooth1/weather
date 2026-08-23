# Codex host overload and unclean reboot — 2026-08-23

Status: historical incident trace. The current prevention contract lives in
[HOST_LOAD_POLICY.md](HOST_LOAD_POLICY.md).

## Verdict

The 14:53 reboot was a second, unclean reboot after the host became
unresponsive. It was not the planned maintenance restart completed at 12:54.

The evidence proves that the prior Codex session violated the production-host
load contract: from 14:00 through 14:38 it issued 387 unique shell calls across
the root and concurrent subagents, including 42 pytest or compile invocations.
At 14:23:19 one agent explicitly launched compileall, two pytest processes,
and the documentation audit in one four-way `Promise.all`. Windows process
telemetry retained 128 Codex-style PowerShell shells from 14:20:06 through
14:38:52, with as many as five concurrent. One 76-second pytest shell covered
the Stage 0/1 sealer, session, and manifest stack and spawned additional
PowerShell fixtures.

Four recursive scans were worse than their visible tool durations. Each unified
executor yielded after 10 or 30 seconds, but its JavaScript caller discarded
the returned session ID instead of polling or terminating it, so the command
continued without an owner:

| Start | Command scope | Actual lifetime |
| --- | --- | ---: |
| 13:07:34 | recursive `AGENTS.md` search from the repository | 86.062 s |
| 13:08:40 | `rg --files data` | 64.592 s |
| 13:28:40 | recursive search from the parent GitHub directory | 120.296 s |
| 14:26:15 | `Get-ChildItem .. -Recurse -Filter python.exe` from a worktree | 95.359 s |

The last scan traversed sibling worktrees and the production checkout,
including ignored `data/`, for about 65 seconds after its tool wrapper had
returned. It overlapped a 92.644-second pytest and other focused tests; executor
concurrency peaked at four. This is the direct abandoned-work mechanism the
standing policy warned about.

This was not a recorded out-of-memory incident. The memory guard completed its
five-minute samples, including 14:50, without recording either its 1.5 GiB
physical-memory warning or 85% commit warning. Windows recorded no Resource
Exhaustion Detector event, bugcheck, or application crash. Do not rewrite the
incident as OOM from the operator-visible sluggishness alone.

A separate network failure is also proven and must not be attributed to Codex
without evidence. NCSI changed from Internet to Local at 14:22 with
`SuspectDnsProbeFailed`; connectivity returned at 14:48, dropped again at
14:51, and DHCP renewal failed at 14:49. Observation died at 14:37. From 14:38
through 14:51 the CLOB loop recorded fleet-wide refresh timeouts and overlapping
timed-out captures, while snapshot Gamma calls timed out. The evidence does
not decide whether local load caused, amplified, or merely coincided with the
DNS/network failure.

## Timeline

| Local time | Evidence |
| --- | --- |
| 12:48:41 | The earlier session invoked an operator-authorized planned `shutdown.exe /r /t 120`. |
| 12:54:13 | The planned maintenance reboot completed cleanly. |
| 13:05 | The next Codex root session began and progressively spawned implementation and audit agents. |
| 14:11–14:38 | Forty-two pytest/compile invocations ran in the protected graded window. |
| 14:22 | Windows NCSI lost Internet reachability on DNS-probe failure. |
| 14:23:19 | Four verification commands were launched concurrently inside one tool call. |
| 14:26:15–14:27:50 | A recursive parent-directory scan continued unowned and overlapped three pytest executions. |
| 14:34:30–14:35:46 | A 76-second pytest process tree exercised broad live-session tests and PowerShell fixtures. |
| 14:37–14:51 | Observation, CLOB, and snapshot capture degraded on network timeouts. |
| 14:50 | The memory guard completed without a memory/commit threshold event; the generated briefing already noted capture errors. |
| 14:53:25 | Windows booted after an unclean reset; Kernel-Power 41 and EventLog 6008 record no clean shutdown. |

EventLog 6008 reports 14:14:19 as the prior shutdown time even though local
files and process telemetry continued through 14:50. Treat that value as the
last shutdown timestamp Windows could recover after the reset, not proof that
the machine was powered off for those 39 minutes.

## Why the existing controls did not stop it

1. `memory_commit_guard.ps1` had an unreachable emergency action path. At
   commit 85% it assigned `status.action = "warned"`; its 92% branch then
   required `status.action == "none"`. Commit `84378994b` introduced the
   contradiction on 2026-08-13.
2. Even if reachable, the branch enumerated only `python*` stdin, `-c`, and
   bare-script commands. It did not recognize `python -m pytest`, Codex-owned
   PowerShell/Node trees, aggregate memory across tool descendants, or a live
   Codex parent whose abandoned children were therefore not orphans.
3. The five-minute watchdog was memory-only. It could neither prevent
   prohibited daytime verification nor cap concurrent agent tool trees.
4. The repository instruction was advisory. The prior session ran tests and
   compileall directly instead of entering the repository-owned workload
   admission and bounded-suite paths.
5. Boot recovery checked only that a recorded PID could be opened. At 14:53:54
   stale CLOB PID 4840 had already been reused by an uninspectable process, yet
   stale status, lock, heartbeat, and code identity let the receipt report
   `capture_recovered: true` with only four capture-loop processes. The proof
   did not bind the OS process creation token or exact worker command.

## Preventive controls

- The memory guard now separates warnings from actions, attributes process
  trees to Codex/ChatGPT ancestry with PID-plus-creation identity, terminates
  recognized agent-heavy tool trees outside 00:30–09:00, and permits at most
  one such tree inside the window.
- At critical commit, one Codex tree is treated as one aggregate offender, so
  several sub-8-GiB children cannot evade the 8-GiB job budget.
- The recurring S4U guard cadence is one minute. Incident-bearing samples append
  to `data/logs/memory_commit_guard_history.jsonl` without raw command lines;
  latest status publication is atomic.
- A user-layer Codex `PreToolUse` hook rejects direct full pytest, broad `data/`
  scans, and any pytest/compileall/replay/backtest/training command outside the
  heavy-work window before the process launches. The hook is a guardrail, not
  the enforcement boundary; Codex requires review/trust on the next session.
- Direct or parallel verification on this production host remains forbidden.
  Full suites use the repository-owned 25-file bounded wrapper during the
  admitted window.
- Boot recovery now requires the status and writer-lock managed-process
  identities to match each other and the live OS creation token and exact
  code-owned worker command. An uninspectable or reused PID fails closed.

## Evidence boundary

The session rollouts and Windows event logs establish commands, concurrency,
process lifetimes, reboot type, network state, and capture symptoms. They do
not preserve per-process CPU or disk utilization at the peak, and there is no
memory-pressure event. Therefore the defensible conclusion is **uncontrolled
concurrent agent load plus a contemporaneous network failure**, not a more
specific hardware or OOM mechanism.

## Adoption and recovery

At 15:30 local, `WeatherMemoryCommitGuard` was re-registered as S4U/Limited
with `PT1M` repetition, `IgnoreNew`, and the repository-owned action. Its first
new-policy sample recorded 44.1% commit, 9,091 MiB free physical memory, zero
agent-heavy processes, and no action. The user hook was installed at
`C:/Users/micha/.codex/hooks.json` with SHA-256
`1DFB2466A4D736909E70F706F33B65BE0C50086B1CA4ED8F7584128CCF293FD3` and awaits
Codex's next-session trust review.

The old CLOB writer-lock PID had been reused by Intel `jhi_service.exe`.
Managed-process creation tokens proved the current process was unrelated and
the CLOB process inventory was empty, so the stale lock was preserved under
`data/snapshots/_retired_writer_locks/` rather than deleted. The supported
detached start then reached a new PID, clean useful iterations, and
`RUNNING/noop`. The hardened recovery checker subsequently passed all three
workers against their exact live OS creation tokens and commands.
