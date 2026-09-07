# Capture memory pressure — September 7, 2026

Status: dated incident and repair record. All times are America/Toronto.

The owner requested a full production-PC systems check, then authorized all
necessary repairs. No live trading was requested. Capture, retention and
host-admission contracts remained in force.

## Incident and recovery

The snapshot loop's last clean iteration was 09:19:10. Windows Scheduler
started `\Microsoft\Windows\Defrag\ScheduledDefrag` at 09:20:55. During the
09:22–09:28 audit, free physical RAM was approximately 2.3–2.5 GiB. Snapshot
admission required 3.25 GiB for one worker and began refusing market captures.
At 09:27:49, the worker reported ten consecutive errors. At repair intake,
10:07:56, that had grown to 547 errors and all twelve markets were named.
CLOB, observation-trigger and public execution capture remained active.

The `defragsvc` service host held about 1.3 GiB of working set and Explorer
about 2.1 GiB. These are observed consumers, not independently proved leaks.
The combined repair was:

1. Export the exact ScheduledDefrag definition, disable the automatic
   maintenance task, stop its running instance, and stop `defragsvc` through
   Service Control Manager. The service stopped and the task read back Disabled.
2. Restart Explorer after a zero-read/zero-write I/O sample. Its replacement
   desktop-shell process initially held about 230 MiB. The direct child launch
   did not persist, so an on-demand Interactive/Limited Scheduler action restored
   the shell in the attended desktop session; it has no recurrence.
3. Verify a new clean snapshot iteration at **10:10:15**, zero consecutive
   errors, and more than 5 GiB free physical RAM. The capture worker did not
   require a restart.

The first audit's healthy process check was superseded by the later actual
capture errors. Likewise, `ensure_status=OK` alongside supervisor `ERRORING`
was not evidence of successful collection. The failure interval must remain
visible in retained capture evidence; this repair does not reconstruct it.

## Capacity and other repairs

- Disabled Windows hibernation and Fast Startup with `powercfg /hibernate off`.
  This reclaimed approximately 6.3 GiB from OS-reserved space; C: free space
  rose from about 23.5 to 29.8 GiB. No project evidence was deleted. AC sleep
  was already disabled. Hibernation can be restored with `powercfg /hibernate on`
  only after reviewing its disk cost and the unattended-host power policy.
- Retired the disabled `WeatherMaintenancePostBoot0823` registration after
  exporting it and verifying its August 23 PASS receipt, receipt SHA-256
  sidecar, wrapper SHA-256, action and zero task result. That wrapper deliberately
  self-disabled on completion. The current `WeatherBootRecovery` task remains
  enabled; its September 3 run succeeded. Historical receipts remain untouched.
- The accompanying monitoring change exposes the fresh memory guard's commit
  percentage and thresholds in the main digest, fails visibly on invalid/stale
  guard evidence, and classifies erroring capture loops as capture incidents.
  The watchdog's Stage-A window and capacity/durability advice now follow the
  existing host-load and retention contracts.

The drive-optimization hold is reversible from its retained XML, but must not
be re-enabled as opportunistic daytime maintenance. A reviewed bounded schedule
is still needed. Do not trade capture headroom for a blanket maintenance restart.

## Remaining boundaries

The bounded recent-ledger checker (400 tail lines per market) reported all
twelve markets missing August 28–31, September 1, September 4 and September 5.
This is 84 flagged market-dates, not a full historical ledger audit. September
6 and September 7 Stage A both deferred at `ingest_quality_gate`; the retained
September 6 admission receipt explicitly names host commit above its 70% limit.
The resource fix does not itself settle those dates or complete today's chain.

Free disk space remains below the ordinary heavy-work preflight minimum.
Both scheduled CLOB tiering jobs already succeeded this morning. Additional
tiering, historical settlement recovery, and production archive scans retain
their admitted-window requirements. The paused mirror is not verified archival
storage; encrypted off-site transfer and restore must be proved before any
exact-manifest source reclaim. No new archive upload or restore was claimed.

Windows also reported shadow-copy storage failures, a recent DNS-policy error,
UDP-port exhaustion warnings, and firmware-limited CPU speed. Current DNS
lookups and time synchronization passed. Those historical errors do not
justify resetting the active network or claiming an SSD failure; the SSD
reported Healthy and 43 C at the check. Hardware/firmware root causes and
off-site resilience remain open.

## Retained evidence

Production-local ignored/host-local evidence, not assumed in a clean checkout:

- `C:/Users/micha/ops/system-health-20260907-0927/REPORT.md` and sibling status
  snapshots and bounded Windows System event export.
- `C:/Users/micha/ops/system-health-20260907-0925-status.json` (initial digest).
- `C:/Users/micha/ops/capture-repair-20260907-1008/`: pre-repair snapshot,
  memory and daily-chain receipts; exported drive-optimization and retired
  post-boot task definitions; repair closeout evidence.

Source publication, tests and adoption are recorded in Git/CI and the repair
closeout receipt. A source patch or this narrative alone does not establish
that the new monitor has been adopted.

## Follow-up: diagnostic deployment at 11:22

The owner renewed authority to continue stability and technical-debt repairs.
The combined source preserves the watchdog repair from PR 29 and archive
qualification documentation from PR 21. It adds hash binding for both the
watchdog and its diagnostic status child while retaining the production runtime
root. Source `aa99048ea249536ee0920f20dd9aa5e2c64170da` passed
[Linux CI](https://github.com/michaelbooth1/weather/actions/runs/34136242629)
(4,278 tests, 921 subtests) and all 105 native workstation checks in 546.55 seconds.
The native receipt has zero failures, errors or skips. An earlier stalled SSH
run was terminated; both teardown checks proved the workload marker absent.

At 11:22:22, `WeatherHostHealthWatchdog` ran the frozen diagnostic deployment
and completed with result 0. Its 11:22:44 output reports memory guard `OK`,
75.5% commit, the exact status-child hash, and the correct `daily_chain` window.
It preserves the seven-date settlement flag and outstanding documentation and
historical recovery alerts. The task's S4U principal, recurrence, timeout and
working directory are unchanged; before/after XML differs only in arguments.

The locked detached source checkout is
`C:/Users/micha/Desktop/github/weather-watchdog-deployed-aa99048`.
Keep it unchanged while the task references it. SHA-256 bindings are:

- `health_watchdog.ps1`: `45C9271D5F1252460E51038BF2884DE51527E17533BE154BD374A439A5AB3F05`.
- `status.ps1`: `5DC275AF957B3FD8CD7D9CA0749646CDB2A15D463A6B4D9C8808B44C17341FDA`.

The retained repair directory contains `watchdog-before-20260907.xml` for
rollback, `watchdog-after-20260907.xml` (SHA-256
`0A9D4535AD18D3CB1FDA9C1351A6E19EB5EB02D496BE6B90F3B297FD6A0341C7`) and
`watchdog-adoption-status-20260907.json` (SHA-256
`85EE8CCB9AA8015A6047A710D6E8977FDDF801FF939106BC18A094C5E5601827`).
This adopts diagnostic scripts only. Production master and its two generated
config changes remain intact. The canonical roll verdict is ROLL-FREE, but
master integration and the pending documentation transaction still require the
installed admitted workflow; neither is declared complete.

The storage follow-up also verified that the signed-in September 5 `v3-r1`
one-file encrypted restore had already passed all 17 checks. Item 325 now
preserves that evidence instead of repeating the superseded DPAPI blocker.
Production-source identity, retention qualification and reclaim remain open;
the one-file result does not prove whole-mirror recovery.
